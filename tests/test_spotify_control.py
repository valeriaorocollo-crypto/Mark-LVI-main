from __future__ import annotations

import json
import sys
import types
import unittest
import urllib.request
from threading import Thread
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch
from pathlib import Path

from plugins import spotify_control
from core.plugin_loader import discover_plugins


def _track(title: str, artist: str, uri: str) -> dict:
    return {
        "name": title,
        "uri": uri,
        "artists": [{"name": artist}],
        "album": {"name": "Synthetic album"},
    }


class _UiaNode:
    def __init__(
        self, control_type: str, name: str = "", children: list | None = None
    ) -> None:
        self.element_info = types.SimpleNamespace(
            control_type=control_type, name=name
        )
        self._children = children or []

    def descendants(self) -> list:
        return [
            descendant
            for child in self._children
            for descendant in [child, *child.descendants()]
        ]


def _spotify_search_tree() -> tuple[_UiaNode, _UiaNode]:
    song = _UiaNode("Group", "One More Time", [
        _UiaNode("DataItem", "Canción • Daft Punk"),
        _UiaNode("Hyperlink", "One More Time"),
        _UiaNode("Hyperlink", "Daft Punk"),
        _UiaNode("Button", "Reproducir"),
    ])
    video = _UiaNode("Group", "One More Time", [
        _UiaNode("DataItem", "Video musical • Daft Punk"),
        _UiaNode("Hyperlink", "One More Time"),
        _UiaNode("Hyperlink", "Daft Punk"),
        _UiaNode("Button", "Reproducir One More Time"),
    ])
    grid = _UiaNode("DataGrid", "Search results", [song, video])
    window = _UiaNode("Pane", "Spotify Free", [grid])
    window.process_id = lambda: 123
    return window, song._children[-1]


class SpotifyControlTests(unittest.TestCase):
    def test_free_desktop_search_targets_only_exact_song_not_video(self) -> None:
        window, expected_button = _spotify_search_tree()
        desktop = types.SimpleNamespace(
            windows=lambda **_kwargs: [window]
        )
        process = types.SimpleNamespace(pid=123, name="Spotify.exe")
        with (
            patch.object(spotify_control.os, "startfile"),
            patch.object(spotify_control.appidentity, "running",
                         return_value=[process]),
            patch.dict(
                sys.modules,
                {"pywinauto": types.SimpleNamespace(
                    Desktop=lambda **_kwargs: desktop
                )},
            ),
        ):
            actual_window, candidates, error = (
                spotify_control._desktop_candidates(
                    "One More Time", "Daft Punk"
                )
            )

        self.assertIsNone(error)
        self.assertIs(actual_window, window)
        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0][0], expected_button)
        self.assertEqual(candidates[0][1]["artist"], "Daft Punk")

    def test_free_desktop_search_waits_out_stale_results(self) -> None:
        stale = _UiaNode("Pane", "Spotify Free", [
            _UiaNode("DataGrid", "Search results", [
                _UiaNode("Group", "One More Time", [
                    _UiaNode("DataItem", "Canción • Daft Punk"),
                    _UiaNode("Hyperlink", "One More Time"),
                    _UiaNode("Hyperlink", "Daft Punk"),
                    _UiaNode("Button", "Reproducir"),
                ]),
            ]),
        ])
        current = _UiaNode("Pane", "Spotify Free", [
            _UiaNode("DataGrid", "Search results", [
                _UiaNode("Group", "COQUETA", [
                    _UiaNode("DataItem", "Canción • Fuerza Regida, Grupo Frontera"),
                    _UiaNode("Hyperlink", "COQUETA"),
                    _UiaNode("Hyperlink", "Fuerza Regida"),
                    _UiaNode("Hyperlink", "Grupo Frontera"),
                    _UiaNode("Button", "Reproducir COQUETA"),
                ]),
            ]),
        ])
        for window in (stale, current):
            window.process_id = lambda: 123
        desktop = types.SimpleNamespace(
            windows=Mock(side_effect=[[stale], [current]])
        )
        process = types.SimpleNamespace(pid=123, name="Spotify.exe")
        with (
            patch.object(spotify_control.os, "startfile"),
            patch.object(spotify_control.appidentity, "running",
                         return_value=[process]),
            patch.object(spotify_control.time, "sleep"),
            patch.dict(
                sys.modules,
                {"pywinauto": types.SimpleNamespace(
                    Desktop=lambda **_kwargs: desktop
                )},
            ),
        ):
            _, candidates, error = spotify_control._desktop_candidates(
                "Coqueta", "Grupo Frontera"
            )

        self.assertIsNone(error)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][1]["artist"],
                         "Fuerza Regida, Grupo Frontera")

    def test_free_desktop_search_keeps_duplicate_artist_choices_ambiguous(self) -> None:
        window, _ = _spotify_search_tree()
        grid = window._children[0]
        grid._children.append(_UiaNode("Group", "One More Time", [
            _UiaNode("DataItem", "Canción • Remix Artist"),
            _UiaNode("Hyperlink", "One More Time"),
            _UiaNode("Hyperlink", "Remix Artist"),
            _UiaNode("Button", "Reproducir"),
        ]))
        desktop = types.SimpleNamespace(
            windows=lambda **_kwargs: [window]
        )
        process = types.SimpleNamespace(pid=123, name="Spotify.exe")
        with (
            patch.object(spotify_control.os, "startfile"),
            patch.object(spotify_control.appidentity, "running",
                         return_value=[process]),
            patch.dict(
                sys.modules,
                {"pywinauto": types.SimpleNamespace(
                    Desktop=lambda **_kwargs: desktop
                )},
            ),
        ):
            _, candidates, error = spotify_control._desktop_candidates(
                "One More Time", ""
            )

        self.assertIsNone(error)
        self.assertEqual(len(candidates), 2)

    def test_free_desktop_search_collapses_duplicate_rows_for_same_song(self) -> None:
        window, _ = _spotify_search_tree()
        grid = window._children[0]
        grid._children.append(_UiaNode("Group", "One More Time", [
            _UiaNode("DataItem", "Canción • Daft Punk"),
            _UiaNode("Hyperlink", "One More Time"),
            _UiaNode("Hyperlink", "Daft Punk"),
            _UiaNode("Button", "Reproducir"),
        ]))
        desktop = types.SimpleNamespace(
            windows=lambda **_kwargs: [window]
        )
        process = types.SimpleNamespace(pid=123, name="Spotify.exe")
        with (
            patch.object(spotify_control.os, "startfile"),
            patch.object(spotify_control.appidentity, "running",
                         return_value=[process]),
            patch.dict(
                sys.modules,
                {"pywinauto": types.SimpleNamespace(
                    Desktop=lambda **_kwargs: desktop
                )},
            ),
        ):
            _, candidates, error = spotify_control._desktop_candidates(
                "One More Time", "Daft Punk"
            )

        self.assertIsNone(error)
        self.assertEqual(len(candidates), 1)

    def test_free_play_invokes_exact_button_and_verifies_current_track(self) -> None:
        button = types.SimpleNamespace(
            is_visible=lambda: True,
            is_enabled=lambda: True,
            invoke=Mock(),
        )
        window = types.SimpleNamespace(
            set_focus=Mock(),
            element_info=types.SimpleNamespace(
                element=types.SimpleNamespace(CurrentHasKeyboardFocus=True)
            ),
        )
        summary = {"title": "One More Time", "artist": "Daft Punk"}
        with (
            patch.object(
                spotify_control,
                "_desktop_candidates",
                return_value=(window, [(button, summary)], None),
            ),
            patch.object(spotify_control, "_desktop_is_playing",
                         return_value=True),
        ):
            result = spotify_control._desktop_play(
                "One More Time", "Daft Punk"
            )

        self.assertIn("status=done", result)
        self.assertIn("verified=true", result)
        button.invoke.assert_called_once()

    def test_free_play_does_not_invoke_ambiguous_search_results(self) -> None:
        button = types.SimpleNamespace(invoke=Mock())
        summary = {"title": "One More Time", "artist": "Daft Punk"}
        with patch.object(
            spotify_control,
            "_desktop_candidates",
            return_value=(
                types.SimpleNamespace(),
                [(button, summary), (button, {"title": "One More Time",
                                              "artist": "Remix Artist"})],
                None,
            ),
        ):
            result = spotify_control._desktop_play("One More Time", "")

        self.assertIn("status=ask", result)
        button.invoke.assert_not_called()

    def test_free_play_pause_uses_player_bar_and_verifies_transition(self) -> None:
        button = _UiaNode("Button", "Reproducir")
        button.is_visible = lambda: True
        button.is_enabled = lambda: True

        def invoke() -> None:
            button.element_info.name = "Pausar"

        button.invoke = invoke
        bar = _UiaNode("Group", "Barra Estás escuchando", [
            _UiaNode("Hyperlink", "Locked out of Heaven"),
            _UiaNode("Hyperlink", "Bruno Mars"),
            button,
        ])
        window = _UiaNode("Pane", "Spotify Free", [bar])
        window.process_id = lambda: 123
        window.set_focus = Mock()
        window.element_info.element = types.SimpleNamespace(
            CurrentHasKeyboardFocus=True
        )
        desktop = types.SimpleNamespace(
            windows=lambda **_kwargs: [window]
        )
        process = types.SimpleNamespace(pid=123, name="Spotify.exe")
        with (
            patch.object(spotify_control.appidentity, "running",
                         return_value=[process]),
            patch.dict(
                sys.modules,
                {"pywinauto": types.SimpleNamespace(
                    Desktop=lambda **_kwargs: desktop
                )},
            ),
        ):
            result = spotify_control._desktop_control("play_pause")

        self.assertIn("status=done", result)
        self.assertIn("verified=true", result)
        self.assertEqual(button.element_info.name, "Pausar")

    def test_play_uses_desktop_when_api_credentials_are_not_configured(self) -> None:
        with (
            patch.object(spotify_control, "_api_is_configured",
                         return_value=False),
            patch.object(spotify_control, "_desktop_play",
                         return_value="status=done action=play verified=true")
            as desktop_play,
        ):
            result = spotify_control.run({
                "action": "play",
                "query": "One More Time",
                "artist": "Daft Punk",
            })

        self.assertIn("status=done", result)
        desktop_play.assert_called_once_with("One More Time", "Daft Punk")

    def test_play_falls_back_to_desktop_after_premium_api_denial(self) -> None:
        with (
            patch.object(spotify_control, "_api_is_configured",
                         return_value=True),
            patch.object(
                spotify_control,
                "_play",
                return_value=(
                    "status=failed reason='Spotify requires Premium'"
                ),
            ),
            patch.object(spotify_control.platform, "system",
                         return_value="Windows"),
            patch.object(spotify_control, "_desktop_play",
                         return_value="status=done action=play verified=true")
            as desktop_play,
        ):
            result = spotify_control.run({
                "action": "play",
                "query": "One More Time",
                "artist": "Daft Punk",
            })

        self.assertIn("status=done", result)
        desktop_play.assert_called_once_with("One More Time", "Daft Punk")

    def test_free_search_and_controls_use_desktop_without_api_credentials(self) -> None:
        with (
            patch.object(spotify_control, "_api_is_configured",
                         return_value=False),
            patch.object(spotify_control, "_desktop_search",
                         return_value="status=done action=search verified=true")
            as desktop_search,
        ):
            search_result = spotify_control.run({
                "action": "search",
                "query": "One More Time",
            })
        desktop_search.assert_called_once_with("One More Time", "")
        self.assertIn("status=done", search_result)

        with patch.object(
            spotify_control,
            "_desktop_control",
            return_value="status=done action=play_pause verified=true",
        ) as desktop_control:
            control_result = spotify_control.run({"action": "play_pause"})

        desktop_control.assert_called_once_with("play_pause")
        self.assertIn("status=done", control_result)

    def test_free_desktop_route_reports_unsupported_platform_cleanly(self) -> None:
        with patch.object(spotify_control.platform, "system",
                          return_value="Linux"):
            result = spotify_control._desktop_play("Song", "Artist")

        self.assertIn("status=failed", result)
        self.assertIn("supported on Windows", result)

    def test_play_refuses_to_guess_when_track_title_is_ambiguous(self) -> None:
        tracks = [
            _track("Blue", "Artist One", "spotify:track:one"),
            _track("Blue", "Artist Two", "spotify:track:two"),
        ]

        selected, candidates = spotify_control._resolve_exact_track(
            tracks, "Blue", ""
        )

        self.assertIsNone(selected)
        self.assertEqual(len(candidates), 2)

    def test_play_selects_only_exact_title_and_artist_match(self) -> None:
        tracks = [
            _track("Blue", "Artist One", "spotify:track:one"),
            _track("Blue", "Artist Two", "spotify:track:two"),
            _track("Blue Moon", "Artist One", "spotify:track:three"),
        ]

        selected, candidates = spotify_control._resolve_exact_track(
            tracks, "Blue", "Artist Two"
        )

        self.assertEqual(selected["uri"], "spotify:track:two")
        self.assertEqual([item["uri"] for item in candidates],
                         ["spotify:track:two"])

    def test_play_uses_spotify_uri_and_verifies_playing_track(self) -> None:
        track = _track("Blue", "Artist One", "spotify:track:one")
        with (
            patch.object(spotify_control, "_search_tracks",
                         return_value=([track], None)),
            patch.object(spotify_control, "_active_computer_device",
                         return_value=("device-1", None)),
            patch.object(spotify_control, "_api_request",
                         return_value=(204, None, None)) as api_request,
            patch.object(spotify_control, "_wait_for_track",
                         return_value=(True, None)),
        ):
            result = spotify_control._play("Blue", "Artist One")

        self.assertIn("status=done", result)
        self.assertIn("verified=true", result)
        api_request.assert_called_once_with(
            "PUT",
            "/me/player/play",
            params={"device_id": "device-1"},
            body={"uris": ["spotify:track:one"]},
        )

    def test_play_does_not_send_request_without_a_confirmed_device(self) -> None:
        track = _track("Blue", "Artist One", "spotify:track:one")
        with (
            patch.object(spotify_control, "_search_tracks",
                         return_value=([track], None)),
            patch.object(spotify_control, "_active_computer_device",
                         return_value=(None, "No active Spotify playback device.")),
            patch.object(spotify_control, "_api_request") as api_request,
        ):
            result = spotify_control._play("Blue", "Artist One")

        self.assertIn("status=failed", result)
        api_request.assert_not_called()

    def test_play_returns_choices_without_starting_an_ambiguous_track(self) -> None:
        tracks = [
            _track("Blue", "Artist One", "spotify:track:one"),
            _track("Blue", "Artist Two", "spotify:track:two"),
        ]
        with (
            patch.object(spotify_control, "_search_tracks",
                         return_value=(tracks, None)),
            patch.object(spotify_control, "_api_request") as api_request,
        ):
            result = spotify_control._play("Blue", "")

        self.assertIn("status=ask", result)
        self.assertIn("Artist One", result)
        self.assertIn("Artist Two", result)
        api_request.assert_not_called()

    def test_play_without_track_asks_instead_of_resuming_current_track(self) -> None:
        result = spotify_control.run({"action": "play"})

        self.assertIn("status=ask", result)
        self.assertIn("currently playing track", result)

    def test_authorization_uses_pkce_and_stores_token_as_secret(self) -> None:
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": " ".join(spotify_control._SCOPES),
                }

        flow = {
            "code": "authorization-code",
            "verifier": "pkce-verifier",
            "redirect_uri": "http://127.0.0.1:12345/callback",
        }
        with (
            patch.object(spotify_control, "_authorization_code",
                         return_value=(json.dumps(flow), None)),
            patch.object(spotify_control.requests, "post",
                         return_value=Response()) as post,
            patch.object(spotify_control, "_save_token") as save_token,
        ):
            success, message = spotify_control._authorize_from_settings({
                "client_id": "synthetic-client-id",
            })

        self.assertTrue(success)
        self.assertIn("connected", message)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["data"]["code_verifier"], "pkce-verifier"
        )
        self.assertEqual(
            post.call_args.kwargs["data"]["client_id"], "synthetic-client-id"
        )
        token = save_token.call_args.args[0]
        self.assertEqual(token["refresh_token"], "refresh")
        self.assertEqual(token["client_id"], "synthetic-client-id")

    def test_pkce_callback_checks_state_and_returns_authorization_code(self) -> None:
        opened_urls = []
        callback_threads = []

        def open_browser(url):
            opened_urls.append(url)
            parameters = parse_qs(urlparse(url).query)
            redirect = urlparse(parameters["redirect_uri"][0])

            def send_callback():
                callback_url = (
                    f"http://{redirect.netloc}{redirect.path}?"
                    f"code=synthetic-code&state={parameters['state'][0]}"
                )
                with urllib.request.urlopen(callback_url, timeout=3) as response:
                    self.assertEqual(response.status, 200)

            thread = Thread(target=send_callback)
            thread.start()
            callback_threads.append(thread)
            return True

        with patch.object(spotify_control.webbrowser, "open",
                          side_effect=open_browser):
            raw, error = spotify_control._authorization_code(
                "synthetic-client-id"
            )
        for thread in callback_threads:
            thread.join(timeout=3)

        self.assertIsNone(error)
        flow = json.loads(raw)
        parameters = parse_qs(urlparse(opened_urls[0]).query)
        self.assertEqual(flow["code"], "synthetic-code")
        self.assertEqual(
            parameters["code_challenge"][0],
            spotify_control._pkce_challenge(flow["verifier"]),
        )
        self.assertEqual(parameters["code_challenge_method"], ["S256"])

    def test_plugin_exposes_connection_settings(self) -> None:
        self.assertEqual(spotify_control.PLUGIN["name"], "spotify_control")
        self.assertEqual(spotify_control.PLUGIN_SETTINGS["namespace"],
                         "spotify_control")
        self.assertEqual(
            spotify_control.PLUGIN_SETTINGS["action"]["label"],
            "CONNECT PREMIUM API",
        )

    def test_plugin_discovery_registers_api_and_connect_settings(self) -> None:
        messages = []
        with patch("core.plugin_loader.get_plugin_trusted", return_value=True):
            registry = discover_plugins(
                Path(spotify_control.__file__).parent,
                set(),
                logger=messages.append,
            )

        self.assertTrue(registry.has("spotify_control"), messages)
        settings = registry._plugins["spotify_control"].settings
        self.assertTrue(callable(settings["action"]["run"]))
        self.assertEqual(settings["namespace"], "spotify_control")


if __name__ == "__main__":
    unittest.main()
