#desktop.py
import os
import sys
import json
import ipaddress
import socket
import subprocess
import tempfile
import platform
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit

from core import action_policy, outcome

# pyautogui is gone from this file along with the generated-code sandbox that
# was the only thing using it — see the note below. Nothing here drives the
# mouse or the keyboard any more; that is computer_control's job.

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"
_MAX_WALLPAPER_DOWNLOAD = 20 * 1024 * 1024
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def _is_public_host(hostname: str) -> bool:
    """Reject URL hosts that resolve to local, reserved, or non-routable space."""
    if not isinstance(hostname, str) or not hostname:
        return False
    normalized = hostname.rstrip(".").lower()
    if (normalized in _BLOCKED_HOSTNAMES or normalized.endswith(".localhost")
            or normalized.endswith(".local")):
        return False
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                normalized, 443, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(
        not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
        for address in addresses
    )


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key
    
def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"

# ─────────────────────────────────────────────────────────────────────────────
#  REMOVED IN MARK LVI: the generated-code path
# ─────────────────────────────────────────────────────────────────────────────
# This file used to carry three functions the rest of the project has no
# equivalent of: `_ask_gemini_for_desktop_action` asked Gemini to write Python
# for whatever the user described, `_build_sandbox` assembled a namespace, and
# `_execute_generated_code` ran the result with exec().
#
# WHY IT WENT
#     The sandbox was not one. Its rules — "NO subprocess", "NO file deletion",
#     "NO import statements" — were sentences in a PROMPT, with nothing in the
#     code enforcing any of them, and the namespace handed the generated code
#     `getattr`, the real `pathlib.Path`, `pyautogui` and, on Windows, `ctypes`.
#     Verified rather than assumed: from inside that namespace,
#     `getattr(getattr(().__class__, "__bases__")[0], "__subclasses__")()`
#     reaches `subprocess.Popen` in one line, and `Path.unlink` was never
#     hidden at all. The only thing standing between a stray instruction and
#     arbitrary code on the user's machine was the model choosing to behave.
#
#     It was also the one tool in this project that broke its own architecture.
#     Every other one of the thirty-eight declares typed parameters and lets the
#     model FILL THEM IN; this one asked the model to emit a program. The rest
#     of the file — wallpaper, organize, clean, list, stats — was already doing
#     it the right way, and those are what remain.
#
# WHAT REPLACED IT
#     Nothing new, because nothing was missing. Typing, clicking, hotkeys,
#     scrolling, screenshots and find-on-screen are `computer_control`; a
#     multi-step job on the screen is the `screen_agent` plugin; files are
#     `file_controller`. All of them are typed, checked and reversible in a way
#     generated code never was.
#
#     An action this file does not recognise is now a failure that names the
#     ones it does — the shape computer_settings has used since Mark LII —
#     rather than a prompt asking a model to invent something.


_ACTIONS = ("wallpaper", "wallpaper_url", "current_wallpaper",
            "organize", "clean", "list", "stats")


def _unknown(said: str) -> str:
    """An action this file does not have, answered with the ones it does.

    Spelling tolerance rather than a second model call: `difflib` matches
    "organise" to "organize" and "wallpapers" to "wallpaper" in microseconds,
    which is the same trick computer_settings uses for its fifty-six actions.
    Where the old code sent an unrecognised string to Gemini to have Python
    written for it, this says what is available and stops.
    """
    import difflib
    guess = difflib.get_close_matches(said.lower().strip(), _ACTIONS, n=1, cutoff=0.6)
    if guess:
        return outcome.ask(
            "desktop_control",
            f"'{said}' is not a desktop action - did you mean '{guess[0]}'?",
            said=said,
        )
    return outcome.failed(
        "desktop_control",
        f"'{said}' is not something this tool does. It handles only: "
        f"{', '.join(_ACTIONS)}. For typing, clicking or keyboard shortcuts "
        f"use computer_control; for files use file_controller",
        said=said,
    ) if said else outcome.failed(
        "desktop_control",
        f"no action was given - choose one of: {', '.join(_ACTIONS)}",
    )


def _apply_wallpaper(image_path: str) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        return f"Image not found: {image_path}"
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return f"Unsupported format: {path.suffix}. Use jpg, png, bmp or webp."

    try:
        if _OS == "Windows":
            import ctypes
            if path.suffix.lower() in {".webp", ".png"}:
                bmp_path = None
                try:
                    from PIL import Image
                    with tempfile.NamedTemporaryFile(
                        prefix="mark-wallpaper-", suffix=".bmp", delete=False
                    ) as bmp_file:
                        bmp_path = Path(bmp_file.name)
                    Image.open(path).convert("RGB").save(bmp_path, "BMP")
                    path = bmp_path
                except ImportError:
                    pass 
                except Exception:
                    if bmp_path is not None:
                        bmp_path.unlink(missing_ok=True)
                    raise
            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3)
            return f"Wallpaper set: {path.name}"

        elif _OS == "Darwin":
            script = (
                f'tell application "System Events" to tell every desktop to '
                f'set picture to POSIX file "{path}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return f"Wallpaper set: {path.name}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            uri = f"file://{path}"

            if "gnome" in desktop_env or "unity" in desktop_env:
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri", uri
                ], capture_output=True)
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri-dark", uri
                ], capture_output=True)

            elif "kde" in desktop_env:
                # KDE Plasma
                script = f"""
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {{
    d = allDesktops[i];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", "file://{path}");
}}
"""
                subprocess.run(
                    ["qdbus", "org.kde.plasmashell", "/PlasmaShell",
                     "org.kde.PlasmaShell.evaluateScript", script],
                    capture_output=True
                )

            elif "xfce" in desktop_env:
                subprocess.run([
                    "xfconf-query", "-c", "xfce4-desktop",
                    "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                    "-s", str(path)
                ], capture_output=True)

            else:
                result = subprocess.run(
                    ["feh", "--bg-scale", str(path)],
                    capture_output=True
                )
                if result.returncode != 0:
                    return (
                        f"Could not set wallpaper automatically on {desktop_env}. "
                        f"Try manually or install 'feh'."
                    )

            return f"Wallpaper set: {path.name}"

    except Exception as e:
        return f"Could not set wallpaper: {e}"


def set_wallpaper(image_path: str) -> str:
    """Set the wallpaper, then READ IT BACK before saying it worked.

    Every platform call underneath reports only that it accepted the request:
    Windows' SystemParametersInfoW returns a bool nobody checked, osascript
    exits 0 whether or not the picture changed, and `feh` succeeds on a file
    the compositor then ignores. The old code returned "Wallpaper set: x.jpg"
    off the back of that — and a wallpaper that did not change is the one
    failure the user can see from across the room.

    `get_current_wallpaper()` already existed for the user to ask with. Using
    it here costs one registry read and turns a claim into a check.

    Where the desktop environment will not report its wallpaper — several
    Linux setups — this says `unverified` rather than guessing, because
    "I set it and cannot confirm" is true and "Wallpaper set" would not be.
    """
    applied = _apply_wallpaper(image_path)
    name = Path(image_path).name

    # The inner function returns its own prose on the paths that never reached
    # the operating system at all — a missing file, an unsupported format.
    if not applied.startswith("Wallpaper set"):
        return outcome.failed("set_wallpaper", applied, image=name)

    reading = get_current_wallpaper()
    if not reading.startswith("Current wallpaper:"):
        return outcome.unverified(
            "set_wallpaper",
            "this desktop environment does not report its wallpaper, so the "
            "change could not be read back",
            image=name,
        )

    current = reading.split(":", 1)[1].strip()
    if Path(current).name.lower() == Path(applied.split(":", 1)[1].strip()).name.lower():
        return outcome.done("set_wallpaper", image=name, verified=True)

    return outcome.unverified(
        "set_wallpaper",
        f"the desktop still reports '{Path(current).name}' - the change may "
        f"need a moment, or this environment may not have accepted it",
        image=name,
    )


def set_wallpaper_from_url(url: str) -> str:
    if (not isinstance(url, str) or not url.strip() or len(url) > 2048
            or any(ord(char) < 32 or char.isspace() for char in url)):
        return outcome.failed(
            "set_wallpaper", "the image URL is invalid or too long"
        )
    try:
        parsed = urlsplit(url)
        if (parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None):
            return outcome.failed(
                "set_wallpaper",
                "the image URL must use HTTP or HTTPS and must not contain credentials",
            )
    except ValueError:
        return outcome.failed("set_wallpaper", "the image URL is malformed")

    tmp_path: Path | None = None
    original_host = parsed.hostname.lower()
    if not _is_public_host(original_host):
        return outcome.failed(
            "set_wallpaper",
            "the image URL host is local, private, reserved, or could not be resolved",
        )
    try:
        import urllib.request
        class _HttpRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, new_url):
                redirected = urlsplit(new_url)
                if (redirected.scheme.lower() not in {"http", "https"}
                        or not redirected.hostname
                        or redirected.username is not None
                        or redirected.password is not None
                        or redirected.hostname is None
                        or redirected.hostname.lower() != original_host
                        or not _is_public_host(redirected.hostname)
                        or (req.full_url.lower().startswith("https://")
                            and redirected.scheme.lower() != "https")):
                    return None
                return super().redirect_request(
                    req, fp, code, msg, headers, new_url
                )

        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        opener = urllib.request.build_opener(_HttpRedirectHandler())
        with opener.open(request, timeout=10) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_WALLPAPER_DOWNLOAD:
                return outcome.failed(
                    "set_wallpaper", "the image exceeds the 20 MiB download limit"
                )
            header = response.read(12)
            if header.startswith(b"\xff\xd8\xff"):
                suffix = ".jpg"
            elif header.startswith(b"\x89PNG\r\n\x1a\n"):
                suffix = ".png"
            elif header.startswith(b"BM"):
                suffix = ".bmp"
            elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
                suffix = ".webp"
            else:
                return outcome.failed(
                    "set_wallpaper", "the downloaded content is not a supported image"
                )
            with tempfile.NamedTemporaryFile(
                prefix="mark-wallpaper-", suffix=suffix, delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(header)
                total = len(header)
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_WALLPAPER_DOWNLOAD:
                        return outcome.failed(
                            "set_wallpaper",
                            "the image exceeds the 20 MiB download limit",
                        )
                    tmp.write(chunk)
        result = set_wallpaper(str(tmp_path))
        return result
    except (OSError, ValueError) as e:
        return outcome.failed("set_wallpaper",
                              f"the image could not be downloaded ({type(e).__name__})")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                print(
                    "[Desktop] Temporary wallpaper cleanup failed "
                    f"({type(cleanup_error).__name__})"
                )


def get_current_wallpaper() -> str:
    try:
        if _OS == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop"
            )
            val, _ = winreg.QueryValueEx(key, "Wallpaper")
            winreg.CloseKey(key)
            return f"Current wallpaper: {val}"

        elif _OS == "Darwin":
            script = (
                'tell application "System Events" to get picture of desktop 1'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            return f"Current wallpaper: {result.stdout.strip()}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            if "gnome" in desktop_env or "unity" in desktop_env:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                return f"Current wallpaper: {result.stdout.strip()}"
            return "Wallpaper path retrieval not supported for this desktop environment."

    except Exception as e:
        return f"Could not get wallpaper: {e}"

FILE_TYPE_MAP = {
    "Images":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents":   {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                    ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
    "Videos":      {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Music":       {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Archives":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code":        {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                    ".cpp", ".java", ".cs", ".go", ".rs", ".sh", ".php"},
    "Executables": {".exe", ".msi", ".bat", ".cmd", ".sh", ".appimage", ".deb", ".rpm"},
}

_SKIP_EXTENSIONS = {
    "Windows": {".lnk", ".url"},
    "Darwin":  {".webloc"},
    "Linux":   {".desktop"},
}


def _desktop_move_plan(action: str, mode: str = "by_type") -> list[tuple[Path, Path]]:
    desktop = _get_desktop()
    skip_exts = _SKIP_EXTENSIONS.get(_OS, set())
    if action == "organize" and mode not in {"by_type", "by_date"}:
        raise ValueError("mode must be by_type or by_date")

    if action == "clean":
        target_root = desktop / f"Desktop Archive {datetime.now():%Y-%m-%d}"
    else:
        target_root = desktop

    plan = []
    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in skip_exts:
            continue

        if action == "clean":
            destination = target_root / item.name
        else:
            if mode == "by_date":
                folder_name = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m")
            else:
                folder_name = next(
                    (folder for folder, extensions in FILE_TYPE_MAP.items()
                     if item.suffix.lower() in extensions),
                    "Others",
                )
            destination = desktop / folder_name / item.name

        if destination.parent.is_symlink():
            raise ValueError("destination folder is a symbolic link")
        if not destination.exists():
            plan.append((item, destination))
    return plan


def _apply_desktop_move_plan(
    action: str,
    mode: str,
    plan: list[tuple[Path, Path]],
) -> str:
    desktop = _get_desktop()
    moved = []
    try:
        if _desktop_move_plan(action, mode) != plan:
            return outcome.failed(
                "desktop_control",
                "desktop contents changed after confirmation; no files were moved",
                wanted=action,
            )
        for source, destination in plan:
            if not source.is_file() or destination.exists():
                return outcome.failed(
                    "desktop_control",
                    "a planned source or destination changed; no files were moved",
                    wanted=action,
                )

        for source, destination in plan:
            destination.parent.mkdir(exist_ok=True)
            source.rename(destination)
            moved.append(f"{source.name} -> {destination.relative_to(desktop)}")
    except (OSError, ValueError) as exc:
        if moved:
            return outcome.unverified(
                "desktop_control",
                f"{len(moved)} file(s) moved before {type(exc).__name__}; "
                "the remaining moves did not complete",
                wanted=action,
                moved=len(moved),
            )
        return outcome.failed(
            "desktop_control",
            f"no files moved ({type(exc).__name__})",
            wanted=action,
        )

    verified = all(destination.is_file() and not source.exists()
                   for source, destination in plan)
    if not verified:
        return outcome.unverified(
            "desktop_control",
            "the move calls returned, but the final file locations could not "
            "all be verified",
            wanted=action,
            moved=len(moved),
        )
    return outcome.done(
        "desktop_control",
        wanted=action,
        moved=len(moved),
        verified=True,
    )


def _confirm_desktop_move(action: str, mode: str = "by_type") -> str:
    try:
        plan = _desktop_move_plan(action, mode)
    except (OSError, ValueError) as exc:
        return outcome.failed(
            "desktop_control", f"could not prepare move preview ({type(exc).__name__})",
            wanted=action,
        )
    if not plan:
        return f"No eligible desktop files to {action}."

    desktop = _get_desktop()
    preview = "\n".join(
        f"{source} -> {destination.relative_to(desktop)}"
        for source, destination in plan
    )
    detail = (
        f"Action: {action}\nMode: {mode}\n"
        "Exact files and destinations:\n"
        f"{preview}\n"
        "Existing destination conflicts are excluded and will not be overwritten."
    )
    return action_policy.request_confirmation(
        "desktop_control",
        action,
        f"Confirm desktop {action}",
        detail,
        run=lambda: _apply_desktop_move_plan(action, mode, plan),
        arguments={"action": action},
    )


def organize_desktop(mode: str = "by_type") -> str:
    return _confirm_desktop_move("organize", mode)


def list_desktop() -> str:
    desktop = _get_desktop()
    items   = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"📁 {item.name}/ ({count} items)")
        else:
            size     = item.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB" if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            items.append(f"📄 {item.name} ({size_str})")

    if not items:
        return "Desktop is empty."
    return f"Desktop ({len(items)} items):\n" + "\n".join(items)


def clean_desktop() -> str:
    return _confirm_desktop_move("clean")


def get_desktop_stats() -> str:
    desktop    = _get_desktop()
    files      = [i for i in desktop.iterdir() if i.is_file()]
    folders    = [i for i in desktop.iterdir() if i.is_dir()]
    total_size = sum(f.stat().st_size for f in files if f.exists())
    size_str   = (
        f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024
        else f"{total_size / 1024 / 1024:.1f} MB"
    )
    return (
        f"Desktop stats ({_OS}):\n"
        f"  Files   : {len(files)}\n"
        f"  Folders : {len(folders)}\n"
        f"  Size    : {size_str}\n"
        f"  Path    : {desktop}"
    )

def desktop_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action : wallpaper | wallpaper_url | current_wallpaper |
                 organize  | clean | list | stats |
                 task (AI-powered)
        path   : image path for 'wallpaper'
        url    : image URL for 'wallpaper_url'
        mode   : 'by_type' or 'by_date' for 'organize'
        task   : natural language description for AI-powered actions
    """
    if parameters is not None and not isinstance(parameters, dict):
        return outcome.failed("desktop_control", "parameters must be an object")
    params = parameters or {}
    raw_action = params.get("action", "")
    raw_task = params.get("task", "")
    if not isinstance(raw_action, str) or not isinstance(raw_task, str):
        return outcome.failed(
            "desktop_control", "action and task must be strings"
        )
    action = raw_action.lower().strip()
    task = raw_task.strip()

    if player:
        print(f"[Desktop] {action}")             # terminal, not the HUD

    try:
        if action == "wallpaper":
            path = params.get("path", "")
            if not path:
                return outcome.failed("desktop_control",
                                      "no image path was given", wanted=action)
            return action_policy.request_confirmation(
                "desktop_control",
                action,
                "Confirm wallpaper change",
                f"Set the desktop wallpaper from this local file:\n{path}",
                run=lambda p=path: set_wallpaper(p),
                arguments=params,
            )

        elif action == "wallpaper_url":
            url = params.get("url", "")
            if not url:
                return outcome.failed("desktop_control",
                                      "no image URL was given", wanted=action)
            return action_policy.request_confirmation(
                "desktop_control",
                action,
                "Confirm wallpaper download and change",
                f"Download this URL and set its image as the desktop wallpaper:\n{url}",
                run=lambda u=url: set_wallpaper_from_url(u),
                arguments=params,
            )

        elif action == "current_wallpaper":
            return get_current_wallpaper()

        elif action == "organize":
            return organize_desktop(params.get("mode", "by_type"))

        elif action == "clean":
            return clean_desktop()

        elif action == "list":
            return list_desktop()

        elif action == "stats":
            return get_desktop_stats()

        return _unknown(action or params.get("task", ""))

    except Exception as e:
        print(f"[Desktop] Error ({type(e).__name__})")
        return outcome.failed(
            "desktop_control",
            "the desktop operation raised an exception",
            wanted=action,
            error=type(e).__name__,
        )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "desktop_control",
    "description": (
        "Controls the DESKTOP itself: the wallpaper, and tidying the files on "
        "it. Actions: wallpaper (needs 'path') | wallpaper_url (needs 'url') | "
        "current_wallpaper | organize (needs 'mode': by_type or by_date) | "
        "clean | list | stats. "
        "It does ONLY those. For typing, clicking, hotkeys, screenshots or "
        "closing an application use computer_control; for opening one use "
        "open_app; for reading, moving or deleting files use file_controller. "
        "Read the status it returns: 'done' was confirmed, 'unverified' means "
        "it was requested and could not be checked - say that rather than "
        "claiming success - and 'ask' means nothing happened and the question "
        "goes to the user first."
    ),
    # Used in place of `description` only when a small model is on a tool
    # budget - Gemini still gets the full text. See providers/schema.py.
    "brief": (
        "Desktop wallpaper and desktop-file tidying. Actions: wallpaper "
        "(path) | wallpaper_url (url) | current_wallpaper | organize (mode) | "
        "clean | list | stats. Nothing else - typing and clicking are "
        "computer_control."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "wallpaper | wallpaper_url | current_wallpaper | organize | clean | list | stats",
                "enum": ["wallpaper", "wallpaper_url", "current_wallpaper",
                         "organize", "clean", "list", "stats"]
            },
            "path": {
                "type": "STRING",
                "description": "Image file path, for action='wallpaper'"
            },
            "url": {
                "type": "STRING",
                "description": "Image URL, for action='wallpaper_url'"
            },
            "mode": {
                "type": "STRING",
                "description": "by_type or by_date, for action='organize'"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": desktop_control,
}
