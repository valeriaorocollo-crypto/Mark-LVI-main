"""Spotify Web API control using user-authorized OAuth with PKCE."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import threading
import time
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from core import appidentity, outcome
from memory import config_manager

_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API_URL = "https://api.spotify.com/v1"
_TOKEN_KEY = "oauth_credentials"
_NAMESPACE = "spotify_control"
_SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)
_MAX_QUERY_LENGTH = 200
_CALLBACK_TIMEOUT = 180
_VERIFY_TIMEOUT = 8
_DESKTOP_SEARCH_TIMEOUT = 12

PLUGIN = {
    "name": "spotify_control",
    "description": (
        "Control Spotify using its official Web API when authorized, with a "
        "Windows desktop UI Automation fallback for Spotify Free. 'play' "
        "searches and plays only a uniquely matching exact song title and "
        "artist, never a search page or an arbitrary first result. If the "
        "user says only 'play music', ask what track or artist they want. "
        "'search' returns candidate tracks; 'play_pause', 'next', and "
        "'previous' use the active Spotify session. Never claim success "
        "unless the requested song is confirmed as currently playing."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["search", "play", "play_pause", "next", "previous"],
                "description": (
                    "search lists candidates; play searches and starts the "
                    "exact requested song; play_pause toggles the current "
                    "Spotify session; next/previous skip the current song."
                ),
            },
            "query": {
                "type": "STRING",
                "description": "Exact song title to find or play.",
            },
            "artist": {
                "type": "STRING",
                "description": (
                    "Optional artist name to disambiguate a track. Prefer "
                    "including it when the title has multiple versions."
                ),
            },
        },
        "required": ["action"],
    },
}


def _plugin_config() -> dict:
    return config_manager.get_plugin_config(
        _NAMESPACE, secret_keys=[_TOKEN_KEY]
    )


def _api_is_configured() -> bool:
    config = _plugin_config()
    return bool(
        isinstance(config.get("client_id"), str)
        and config["client_id"].strip()
        and isinstance(config.get(_TOKEN_KEY), str)
        and config[_TOKEN_KEY].strip()
    )


def _save_token(token: dict) -> None:
    config_manager.save_plugin_config(
        _NAMESPACE,
        {_TOKEN_KEY: json.dumps(token, separators=(",", ":"))},
        secret_keys=[_TOKEN_KEY],
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _authorization_code(client_id: str) -> tuple[str | None, str | None]:
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    callback: dict[str, str] = {}
    callback_event = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            returned_state = values.get("state", [""])[0]
            if not secrets.compare_digest(returned_state, state):
                callback["error"] = "OAuth state validation failed."
            elif values.get("error"):
                callback["error"] = "Spotify authorization was declined."
            else:
                callback["code"] = values.get("code", [""])[0]
                if not callback["code"]:
                    callback["error"] = "Spotify returned no authorization code."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Spotify authorization received. You can close this tab."
            )
            callback_event.set()

        def log_message(self, _format, *_args):
            _ = _format, _args
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    parameters = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": _pkce_challenge(verifier),
        "state": state,
        "scope": " ".join(_SCOPES),
    }
    authorization_url = f"{_AUTH_URL}?{urlencode(parameters)}"

    try:
        if not webbrowser.open(authorization_url):
            return None, "Could not open the Spotify authorization page."
        deadline = time.monotonic() + _CALLBACK_TIMEOUT
        while not callback_event.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if not callback_event.is_set():
        return None, "Spotify authorization timed out; try connecting again."
    if callback.get("error"):
        return None, callback["error"]
    return json.dumps({
        "code": callback["code"],
        "verifier": verifier,
        "redirect_uri": redirect_uri,
    }), None


def _authorize_from_settings(values: dict) -> tuple[bool, str]:
    client_id = values.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        return False, "Enter a Spotify app Client ID first."

    try:
        flow_result, error = _authorization_code(client_id.strip())
        if error:
            return False, error
        authorization = json.loads(flow_result or "{}")
        response = requests.post(
            _TOKEN_URL,
            data={
                "client_id": client_id.strip(),
                "grant_type": "authorization_code",
                "code": authorization["code"],
                "redirect_uri": authorization["redirect_uri"],
                "code_verifier": authorization["verifier"],
            },
            timeout=(3, 10),
        )
        if response.status_code != 200:
            return False, (
                "Spotify rejected authorization "
                f"(HTTP {response.status_code}). Check the app Client ID "
                "and its registered loopback redirect URI."
            )
        token = response.json()
        if not isinstance(token.get("access_token"), str):
            return False, "Spotify returned an invalid authorization token."
        if not isinstance(token.get("refresh_token"), str):
            return False, "Spotify did not grant a refresh token."
        granted_scopes = set(str(token.get("scope") or "").split())
        if not set(_SCOPES).issubset(granted_scopes):
            return False, "Spotify did not grant all required playback scopes."
        token["client_id"] = client_id.strip()
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
        _save_token(token)
    except Exception as exc:
        return False, f"Spotify authorization failed ({type(exc).__name__})."
    return True, (
        "Spotify Premium API is connected. Spotify Free desktop control "
        "remains available without API credentials."
    )


PLUGIN_SETTINGS = {
    "namespace": _NAMESPACE,
    "title": "SPOTIFY API — OPTIONAL",
    "fields": [{
        "key": "client_id",
        "type": "text",
        "label": "Spotify Developer Client ID (Premium API)",
        "placeholder": (
            "Optional for Premium API. Free desktop playback needs no Client ID."
        ),
    }],
    "action": {
        "label": "CONNECT PREMIUM API",
        "run": _authorize_from_settings,
    },
}


def _authorized_token() -> tuple[dict | None, str | None]:
    config = _plugin_config()
    client_id = config.get("client_id")
    raw_token = config.get(_TOKEN_KEY)
    if not isinstance(client_id, str) or not client_id.strip():
        return None, "Add a Spotify app Client ID in plugin settings."
    if not isinstance(raw_token, str) or not raw_token.strip():
        return None, "Connect Spotify in plugin settings before using playback."

    try:
        token = json.loads(raw_token)
        if not isinstance(token, dict) or not token.get("refresh_token"):
            raise ValueError("invalid saved token")
        if int(token.get("expires_at", 0)) <= int(time.time()) + 60:
            response = requests.post(
                _TOKEN_URL,
                data={
                    "client_id": client_id.strip(),
                    "grant_type": "refresh_token",
                    "refresh_token": token["refresh_token"],
                },
                timeout=(3, 10),
            )
            if response.status_code != 200:
                return None, (
                    "Spotify authorization expired or was revoked; reconnect "
                    f"in plugin settings (HTTP {response.status_code})."
                )
            refreshed = response.json()
            token.update(refreshed)
            token["client_id"] = client_id.strip()
            token["expires_at"] = int(time.time()) + int(
                refreshed.get("expires_in", 3600)
            )
            _save_token(token)
        return token, None
    except (ValueError, TypeError, requests.RequestException) as exc:
        return None, f"Could not refresh Spotify authorization ({type(exc).__name__})."


def _api_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
) -> tuple[int, dict | None, str | None]:
    token, error = _authorized_token()
    if error:
        return 0, None, error
    try:
        response = requests.request(
            method,
            f"{_API_URL}{path}",
            headers={"Authorization": f"Bearer {token['access_token']}"},
            params=params,
            json=body,
            timeout=(3, 10),
        )
    except requests.RequestException as exc:
        return 0, None, f"Spotify request failed ({type(exc).__name__})."
    if response.status_code == 204:
        return response.status_code, None, None
    try:
        payload = response.json() if response.content else None
    except ValueError:
        payload = None
    if response.status_code >= 400:
        return response.status_code, payload, _spotify_http_error(response.status_code)
    return response.status_code, payload, None


def _spotify_http_error(status: int) -> str:
    if status == 401:
        return "Spotify authorization is invalid; reconnect the account."
    if status == 403:
        return (
            "Spotify denied playback control. Confirm the account has Premium "
            "and the app has the requested playback scopes."
        )
    if status == 404:
        return "Spotify has no active playback device. Open Spotify on this laptop."
    if status == 429:
        return "Spotify rate-limited the request; wait briefly and try again."
    return f"Spotify returned HTTP {status}."


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(ch for ch in decomposed if not unicodedata.combining(ch)).split()
    )


def _search_tracks(query: str, artist: str = "") -> tuple[list[dict], str | None]:
    if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_LENGTH:
        return [], "Track query must contain 1-200 characters."
    if not isinstance(artist, str) or len(artist) > _MAX_QUERY_LENGTH:
        return [], "Artist must be text of at most 200 characters."
    search_query = query.strip()
    if artist.strip():
        search_query += f" artist:{artist.strip()}"
    _, payload, error = _api_request(
        "GET",
        "/search",
        params={"q": search_query, "type": "track", "limit": 10},
    )
    if error:
        return [], error
    tracks = (payload or {}).get("tracks", {}).get("items", [])
    return [item for item in tracks if isinstance(item, dict)], None


def _track_summary(track: dict) -> dict:
    artists = track.get("artists") or []
    return {
        "title": str(track.get("name") or "")[:200],
        "artist": ", ".join(
            str(item.get("name") or "")[:100]
            for item in artists if isinstance(item, dict)
        )[:300],
        "album": str((track.get("album") or {}).get("name") or "")[:200],
        "uri": str(track.get("uri") or "")[:200],
    }


def _resolve_exact_track(
    tracks: list[dict], query: str, artist: str
) -> tuple[dict | None, list[dict]]:
    wanted_title = _fold(query)
    wanted_artist = _fold(artist)
    matches = []
    for track in tracks:
        summary = _track_summary(track)
        if _fold(summary["title"]) != wanted_title:
            continue
        if wanted_artist and wanted_artist not in {
            _fold(str(item.get("name") or ""))
            for item in track.get("artists", [])
            if isinstance(item, dict)
        }:
            continue
        if summary["uri"].startswith("spotify:track:"):
            matches.append((track, summary))
    unique = {summary["uri"]: (track, summary) for track, summary in matches}
    candidates = [summary for _, summary in unique.values()]
    if len(unique) == 1:
        return next(iter(unique.values()))[0], candidates
    return None, candidates or [_track_summary(item) for item in tracks[:5]]


def _desktop_candidates(
    query: str, artist: str
) -> tuple[Any | None, list[tuple[Any, dict]], str | None]:
    """Search Spotify Desktop and read exact song rows through Windows UIA."""
    if platform.system() != "Windows":
        return None, [], "Spotify Free desktop control is supported on Windows."
    if (
        not isinstance(query, str) or not query.strip()
        or len(query) > _MAX_QUERY_LENGTH
    ):
        return None, [], "Track query must contain 1-200 characters."
    if not isinstance(artist, str) or len(artist) > _MAX_QUERY_LENGTH:
        return None, [], "Artist must be text of at most 200 characters."

    search_text = query.strip()
    if artist.strip():
        search_text += f" {artist.strip()}"
    try:
        os.startfile(f"spotify:search:{quote(search_text, safe='')}")
    except OSError as exc:
        return None, [], (
            "Could not open Spotify Desktop search "
            f"({type(exc).__name__})."
        )

    from _ctypes import COMError

    deadline = time.monotonic() + _DESKTOP_SEARCH_TIMEOUT
    last_error = "Spotify search results are not available through UI Automation."
    while time.monotonic() < deadline:
        try:
            from pywinauto import Desktop

            processes = appidentity.running("Spotify")
            spotify_pids = {
                process.pid for process in processes
                if process.name.casefold() == "spotify.exe"
            }
            windows = [
                window
                for window in Desktop(backend="uia").windows(
                    visible_only=True, top_level_only=True
                )
                if window.process_id() in spotify_pids
            ]
            if len(windows) != 1:
                last_error = (
                    "Spotify Desktop did not expose one unambiguous window."
                )
            else:
                window = windows[0]
                grids = [
                    control
                    for control in window.descendants()
                    if (
                        str(control.element_info.control_type or "") == "DataGrid"
                        and _fold(str(control.element_info.name or ""))
                        in {"search results", "resultados de busqueda"}
                    )
                ]
                if len(grids) == 1:
                    wanted_title = _fold(query)
                    wanted_artist = _fold(artist)
                    candidates: list[tuple[Any, dict]] = []
                    for row in grids[0].descendants():
                        if (
                            str(row.element_info.control_type or "") != "Group"
                            or _fold(str(row.element_info.name or ""))
                            != wanted_title
                        ):
                            continue
                        children = row.descendants()
                        labels = [
                            (
                                str(child.element_info.control_type or ""),
                                str(child.element_info.name or "").strip(),
                            )
                            for child in children
                        ]
                        if not any(
                            kind == "DataItem"
                            and _fold(name).startswith(("cancion", "song", "pista"))
                            for kind, name in labels
                        ):
                            continue
                        artists = list(dict.fromkeys(
                            name for kind, name in labels
                            if kind == "Hyperlink"
                            and _fold(name) != wanted_title
                        ))
                        if wanted_artist and wanted_artist not in {
                            _fold(name) for name in artists
                        }:
                            continue
                        buttons = [
                            child
                            for child in children
                            if str(child.element_info.control_type or "") == "Button"
                            and _is_track_play_button(
                                str(child.element_info.name or ""), wanted_title
                            )
                        ]
                        if len(buttons) != 1:
                            continue
                        summary = {
                            "title": str(row.element_info.name or "")[:200],
                            "artist": ", ".join(artists)[:300],
                        }
                        identity = (
                            _fold(summary["title"]),
                            _fold(summary["artist"]),
                        )
                        if not any(
                            (
                                _fold(existing["title"]),
                                _fold(existing["artist"]),
                            ) == identity
                            for _, existing in candidates
                        ):
                            candidates.append((buttons[0], summary))
                    if candidates:
                        return window, candidates, None
                    last_error = (
                        "Spotify is still loading this search or exposed no "
                        "exact matching song and artist."
                    )
                else:
                    last_error = (
                        "Spotify's search results are not exposed as one "
                        "accessible result list."
                    )
        except (
            ImportError, AttributeError, RuntimeError, TypeError, OSError,
            COMError,
        ) as exc:
            return None, [], (
                "Spotify Desktop UI Automation failed "
                f"({type(exc).__name__})."
            )
        time.sleep(0.35)
    return None, [], last_error


def _is_track_play_button(name: str, wanted_title: str) -> bool:
    folded = _fold(name)
    return (
        folded in {"play", "reproducir"}
        or folded.startswith(f"play {wanted_title}")
        or folded.startswith(f"reproducir {wanted_title}")
    )


def _desktop_search(query: str, artist: str) -> str:
    _, candidates, error = _desktop_candidates(query, artist)
    if error:
        return outcome.failed("spotify_control", error, action="search")
    return json.dumps({
        "status": "done",
        "action": "search",
        "verified": True,
        "tracks": [summary for _, summary in candidates[:5]],
    }, ensure_ascii=False)


def _desktop_is_playing(
    window: Any, title: str, artist: str
) -> bool:
    controls = window.descendants()
    player_bars = [
        control
        for control in controls
        if (
            str(control.element_info.control_type or "") == "Group"
            and _fold(str(control.element_info.name or ""))
            in {"barra estas escuchando", "now playing bar"}
        )
    ]
    if len(player_bars) != 1:
        return False
    bar = player_bars[0]
    children = bar.descendants()
    names = {
        (
            str(child.element_info.control_type or ""),
            _fold(str(child.element_info.name or "")),
        )
        for child in children
    }
    return (
        ("Hyperlink", _fold(title)) in names
        and (not artist or ("Hyperlink", _fold(artist)) in names)
        and any(
            kind == "Button" and name in {"pause", "pausar"}
            for kind, name in names
        )
    )


def _desktop_play(query: str, artist: str) -> str:
    window, candidates, error = _desktop_candidates(query, artist)
    if error:
        return outcome.failed("spotify_control", error, action="play")
    if not candidates:
        return outcome.failed(
            "spotify_control",
            "Spotify Desktop exposed no exact matching song and artist.",
            action="play",
        )
    if len(candidates) != 1:
        return outcome.ask(
            "spotify_control",
            "Multiple exact Spotify songs match. Ask the user to choose "
            "a title and artist; do not start playback yet.",
            action="play",
            candidates=json.dumps(
                [summary for _, summary in candidates[:5]],
                ensure_ascii=False,
            ),
        )

    from _ctypes import COMError

    button, summary = candidates[0]
    effect_started = False
    try:
        if not button.is_visible() or not button.is_enabled():
            return outcome.failed(
                "spotify_control",
                "The exact Spotify result's Play control is unavailable.",
                action="play",
            )
        window.set_focus()
        if not bool(window.element_info.element.CurrentHasKeyboardFocus):
            return outcome.failed(
                "spotify_control",
                "Spotify Desktop focus could not be verified; no song was started.",
                action="play",
            )
        effect_started = True
        button.invoke()
    except (
        AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        if not effect_started:
            return outcome.failed(
                "spotify_control",
                f"Spotify Desktop could not invoke the exact Play control "
                f"({type(exc).__name__}).",
                action="play",
            )
        return outcome.unverified(
            "spotify_control",
            f"Spotify accepted no verifiable play action ({type(exc).__name__})",
            action="play",
            track=summary["title"],
            artist=summary["artist"],
        )

    deadline = time.monotonic() + _VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if _desktop_is_playing(window, query, artist):
                return outcome.done(
                    "spotify_control",
                    action="play",
                    track=summary["title"],
                    artist=summary["artist"],
                    verified=True,
                )
        except (
            AttributeError, RuntimeError, TypeError, OSError, COMError
        ):
            break
        time.sleep(0.4)
    return outcome.unverified(
        "spotify_control",
        "The exact Spotify result was selected, but the current playing "
        "track could not be verified.",
        action="play",
        track=summary["title"],
        artist=summary["artist"],
    )


def _desktop_control(action: str) -> str:
    if platform.system() != "Windows":
        return outcome.failed(
            "spotify_control",
            "Spotify Free desktop controls are supported on Windows.",
            action=action,
        )
    from _ctypes import COMError

    effect_started = False
    try:
        from pywinauto import Desktop

        processes = appidentity.running("Spotify")
        spotify_pids = {
            process.pid for process in processes
            if process.name.casefold() == "spotify.exe"
        }
        windows = [
            window
            for window in Desktop(backend="uia").windows(
                visible_only=True, top_level_only=True
            )
            if window.process_id() in spotify_pids
        ]
        if len(windows) != 1:
            return outcome.failed(
                "spotify_control",
                "Spotify Desktop did not expose one unambiguous window.",
                action=action,
            )
        window = windows[0]
        bars = [
            control
            for control in window.descendants()
            if (
                str(control.element_info.control_type or "") == "Group"
                and _fold(str(control.element_info.name or ""))
                in {"barra estas escuchando", "now playing bar"}
            )
        ]
        if len(bars) != 1:
            return outcome.failed(
                "spotify_control",
                "Spotify's current-player controls are not uniquely accessible.",
                action=action,
            )
        bar = bars[0]
        children = bar.descendants()
        buttons = [
            child
            for child in children
            if str(child.element_info.control_type or "") == "Button"
        ]
        before_track = tuple(
            _fold(str(child.element_info.name or ""))
            for child in children
            if str(child.element_info.control_type or "") == "Hyperlink"
        )
        labels = {
            "previous": {"anterior", "previous"},
            "next": {"siguiente", "next"},
        }
        if action in labels:
            matching = [
                button for button in buttons
                if _fold(str(button.element_info.name or "")) in labels[action]
            ]
            expected_playing = None
        else:
            pause_names = {"pausar", "pause"}
            play_names = {"reproducir", "play", "reanudar", "resume"}
            current_names = {
                _fold(str(button.element_info.name or ""))
                for button in buttons
            }
            was_playing = bool(current_names & pause_names)
            targets = pause_names if was_playing else play_names
            matching = [
                button for button in buttons
                if _fold(str(button.element_info.name or "")) in targets
            ]
            expected_playing = not was_playing
        if len(matching) != 1:
            return outcome.failed(
                "spotify_control",
                "Spotify did not expose one unique semantic playback control.",
                action=action,
            )
        button = matching[0]
        if not button.is_visible() or not button.is_enabled():
            return outcome.failed(
                "spotify_control",
                "The Spotify playback control is not available.",
                action=action,
            )
        window.set_focus()
        if not bool(window.element_info.element.CurrentHasKeyboardFocus):
            return outcome.failed(
                "spotify_control",
                "Spotify Desktop focus could not be verified; no control was used.",
                action=action,
            )
        effect_started = True
        button.invoke()
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        if effect_started:
            return outcome.unverified(
                "spotify_control",
                f"Spotify may have received the control "
                f"({type(exc).__name__}), but its result was not verified.",
                action=action,
            )
        return outcome.failed(
            "spotify_control",
            f"Spotify Desktop control failed ({type(exc).__name__}).",
            action=action,
        )

    deadline = time.monotonic() + _VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            fresh_children = bars[0].descendants()
            if action == "play_pause":
                names = {
                    _fold(str(child.element_info.name or ""))
                    for child in fresh_children
                    if str(child.element_info.control_type or "") == "Button"
                }
                if (
                    bool(names & {"pausar", "pause"}) is expected_playing
                ):
                    return outcome.done(
                        "spotify_control", action=action, verified=True
                    )
            else:
                after_track = tuple(
                    _fold(str(child.element_info.name or ""))
                    for child in fresh_children
                    if str(child.element_info.control_type or "") == "Hyperlink"
                )
                if after_track and after_track != before_track:
                    return outcome.done(
                        "spotify_control", action=action, verified=True
                    )
        except (
            AttributeError, RuntimeError, TypeError, OSError, COMError
        ):
            break
        time.sleep(0.4)
    return outcome.unverified(
        "spotify_control",
        "Spotify accepted the desktop control but the resulting state "
        "could not be confirmed.",
        action=action,
    )


def _active_computer_device() -> tuple[str | None, str | None]:
    _, payload, error = _api_request("GET", "/me/player")
    if error:
        return None, error
    device = (payload or {}).get("device") or {}
    if not device.get("id") or not device.get("is_active"):
        return None, "No active Spotify playback device. Open Spotify on this laptop."
    if str(device.get("type") or "").casefold() != "computer":
        return None, (
            "The active Spotify device is not this computer. Switch playback "
            "to Spotify on the laptop, then try again."
        )
    return str(device["id"]), None


def _wait_for_track(uri: str) -> tuple[bool, str | None]:
    deadline = time.monotonic() + _VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        _, payload, error = _api_request("GET", "/me/player/currently-playing")
        if error:
            return False, error
        item = (payload or {}).get("item") or {}
        if item.get("uri") == uri and (payload or {}).get("is_playing") is True:
            return True, None
        time.sleep(0.5)
    return False, None


def _play(query: str, artist: str) -> str:
    tracks, error = _search_tracks(query, artist)
    if error:
        return outcome.failed("spotify_control", error, action="play")
    if not tracks:
        return outcome.failed(
            "spotify_control", "Spotify found no matching tracks", action="play"
        )
    track, candidates = _resolve_exact_track(tracks, query, artist)
    if track is None:
        return outcome.ask(
            "spotify_control",
            "I found multiple or no exact title matches. Ask the user to "
            "choose a title and artist; do not start playback yet.",
            action="play",
            candidates=json.dumps(candidates[:5], ensure_ascii=False),
        )

    device_id, error = _active_computer_device()
    if error:
        return outcome.failed("spotify_control", error, action="play")
    uri = str(track["uri"])
    _, _, error = _api_request(
        "PUT",
        "/me/player/play",
        params={"device_id": device_id},
        body={"uris": [uri]},
    )
    if error:
        return outcome.failed("spotify_control", error, action="play")
    verified, verify_error = _wait_for_track(uri)
    summary = _track_summary(track)
    if verify_error:
        return outcome.unverified(
            "spotify_control",
            verify_error,
            action="play",
            track=summary["title"],
            artist=summary["artist"],
        )
    if not verified:
        return outcome.unverified(
            "spotify_control",
            "Spotify accepted the play request but did not confirm that the "
            "requested track is playing",
            action="play",
            track=summary["title"],
            artist=summary["artist"],
        )
    return outcome.done(
        "spotify_control",
        action="play",
        track=summary["title"],
        artist=summary["artist"],
        verified=True,
    )


def _search(query: str, artist: str) -> str:
    tracks, error = _search_tracks(query, artist)
    if error:
        return outcome.failed("spotify_control", error, action="search")
    return json.dumps({
        "status": "done",
        "action": "search",
        "verified": True,
        "tracks": [_track_summary(track) for track in tracks[:5]],
    }, ensure_ascii=False)


def run(parameters: dict, player=None, session_memory=None) -> str:
    _ = player, session_memory
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action") or "").strip().lower()
    query = params.get("query", "")
    artist = params.get("artist", "")
    if action == "search":
        if not isinstance(query, str) or not query.strip():
            return outcome.failed(
                "spotify_control", "a track query is required", action=action
            )
        if not _api_is_configured():
            return _desktop_search(query.strip(), artist)
        return _search(query, artist)
    if action == "play":
        if not isinstance(query, str) or not query.strip():
            return outcome.ask(
                "spotify_control",
                "Ask which song or artist the user wants; do not resume the "
                "currently playing track as a substitute.",
                action=action,
            )
        if not _api_is_configured():
            return _desktop_play(query.strip(), artist)
        result = _play(query.strip(), artist)
        if "Premium" in result and platform.system() == "Windows":
            return _desktop_play(query.strip(), artist)
        return result
    if action not in {"play_pause", "next", "previous"}:
        return outcome.failed(
            "spotify_control",
            "action must be search, play, play_pause, next, or previous",
            action=action or "unspecified",
        )
    if not _api_is_configured():
        return _desktop_control(action)
    result = _control_current_playback(action)
    if "Premium" in result and platform.system() == "Windows":
        return _desktop_control(action)
    return result


def _control_current_playback(action: str) -> str:
    device_id, error = _active_computer_device()
    if error:
        return outcome.failed("spotify_control", error, action=action)
    if action == "play_pause":
        status, payload, error = _api_request("GET", "/me/player")
        if error:
            return outcome.failed("spotify_control", error, action=action)
        is_playing = bool((payload or {}).get("is_playing"))
        method = "PUT"
        path = "/me/player/pause" if is_playing else "/me/player/play"
    else:
        method = "POST"
        path = f"/me/player/{action}"
        is_playing = None
    status, _, error = _api_request(
        method, path, params={"device_id": device_id}
    )
    if error:
        return outcome.failed("spotify_control", error, action=action)
    if action == "play_pause":
        expected = not is_playing
        deadline = time.monotonic() + _VERIFY_TIMEOUT
        while time.monotonic() < deadline:
            _, state, error = _api_request("GET", "/me/player")
            if error:
                break
            if bool((state or {}).get("is_playing")) is expected:
                return outcome.done(
                    "spotify_control", action=action, verified=True
                )
            time.sleep(0.5)
    return outcome.unverified(
        "spotify_control",
        "Spotify accepted the playback command but the resulting state "
        "could not be confirmed",
        action=action,
        http_status=status,
    )
