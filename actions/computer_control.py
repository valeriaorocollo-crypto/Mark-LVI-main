#computer_control.py
import io
import hashlib
import json
import math
import platform
import re
import string
import subprocess
import sys
import threading
from collections import deque

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import time
import random
from pathlib import Path

from core import action_policy, appidentity, confirm, outcome, ui_adapter
from core.lazyimport import LazyModule, installed

# pyautogui and pyperclip are imported on first USE, not at launch — see
# core/lazyimport.py for why and for what stays the same. The flags still mean
# "is it installed?" and still answer without importing anything.
_PYAUTOGUI = installed("pyautogui")
_PYPERCLIP = installed("pyperclip")
_MAX_TEXT_INPUT = 10_000
_SCREEN_CLICK_WINDOW_SECONDS = 30.0
_SCREEN_CLICK_MAXIMUM = 3
_screen_click_history: deque[float] = deque()
_screen_click_history_lock = threading.Lock()


def _configure_pyautogui(module) -> None:
    """Settings that used to sit beside the import, run once when it happens."""
    module.FAILSAFE = True
    module.PAUSE    = 0.05


pyautogui = LazyModule("pyautogui", _configure_pyautogui)
pyperclip = LazyModule("pyperclip")

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )


def _focus_control(selector: object, arguments: dict) -> str:
    if not isinstance(selector, dict):
        return outcome.failed(
            "computer_control",
            "focus_control requires a structured selector",
            action="focus_control",
        )
    try:
        ui_adapter.validate_focus_selector(selector)
    except ValueError as exc:
        return outcome.failed(
            "computer_control",
            f"invalid focus_control selector: {exc}",
            action="focus_control",
        )

    def run() -> str:
        result = ui_adapter.focus_control(selector)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    return action_policy.run_or_confirm(
        "computer_control",
        "focus_control",
        title="Allow focusing this desktop control?",
        detail=(
            f"Target: {action_policy.confirmation_arguments({'selector': selector})}\n"
            "The selected control will receive keyboard focus.\n"
            "No click, text entry, or submission will be performed."
        ),
        run=run,
        arguments=arguments,
    )

def _activate_window(window_name: object, arguments: dict) -> str:
    if not isinstance(window_name, str):
        return outcome.failed(
            "computer_control",
            "activate_window requires a window title",
            action="activate_window",
        )
    try:
        if not window_name.strip() or len(window_name) > 300:
            raise ValueError("window name must contain 1-300 characters")
    except ValueError as exc:
        return outcome.failed(
            "computer_control", f"invalid activate_window title: {exc}",
            action="activate_window",
        )

    def run() -> str:
        result = ui_adapter.activate_window(window_name)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    return action_policy.run_or_confirm(
        "computer_control",
        "activate_window",
        title="Allow activating this desktop window?",
        detail=(
            f"Window title: {window_name}\n"
            "The selected window will be brought to the foreground."
        ),
        run=run,
        arguments=arguments,
    )

def _write_control(selector: object, text: object, arguments: dict) -> str:
    if not isinstance(selector, dict):
        return outcome.failed(
            "computer_control",
            "write_control requires a structured selector",
            action="write_control",
        )
    try:
        ui_adapter.validate_focus_selector(selector)
        if not isinstance(text, str) or len(text) > 10_000:
            raise ValueError("text must contain 0-10000 characters")
    except ValueError as exc:
        return outcome.failed(
            "computer_control", f"invalid write_control input: {exc}",
            action="write_control",
        )

    def run() -> str:
        result = ui_adapter.write_control(selector, text)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    return action_policy.run_or_confirm(
        "computer_control",
        "write_control",
        title="Allow writing into this desktop field?",
        detail=(
            f"Target and input: {action_policy.confirmation_arguments(arguments)}\n"
            "Text will be written only to the uniquely selected non-password "
            "field. No submit or click will be performed."
        ),
        run=run,
        arguments=arguments,
    )

def _invoke_control(selector: object, arguments: dict) -> str:
    if not isinstance(selector, dict):
        return outcome.failed(
            "computer_control",
            "invoke_control requires a structured selector",
            action="invoke_control",
        )
    try:
        ui_adapter.validate_focus_selector(selector)
    except ValueError as exc:
        return outcome.failed(
            "computer_control", f"invalid invoke_control selector: {exc}",
            action="invoke_control",
        )

    def run() -> str:
        result = ui_adapter.invoke_control(selector)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    return action_policy.run_or_confirm(
        "computer_control",
        "invoke_control",
        title="Allow invoking this desktop control?",
        detail=(
            f"Target: {action_policy.confirmation_arguments({'selector': selector})}\n"
            "The uniquely selected semantic control will be invoked once. "
            "No coordinates, arbitrary click, or repeated action will be used."
        ),
        run=run,
        arguments=arguments,
    )

def _get_os() -> str:
    return _load_config().get("os_system", _platform_os()).lower()


def _get_api_key() -> str:
    from memory.config_manager import get_gemini_key

    key = get_gemini_key()
    if not key:
        raise RuntimeError("No Gemini API key is configured.")
    return key

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "jarvis_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    """Refuse early, with the sentence that says what to install.

    The import itself is the module `__getattr__`'s job; this stays exactly
    what it was — the check that turns a missing optional dependency into an
    instruction rather than a traceback.
    """
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _require_pyperclip() -> bool:
    """Is the clipboard usable? Returns a bool rather than raising, because
    every caller already has a hotkey fallback written for the case where it
    is not — turning that into an exception would break the path built to
    survive it."""
    return _PYPERCLIP

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed {len(text)} characters."


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _require_pyperclip():
        pyperclip.copy(text)
        time.sleep(0.1)
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Smart-typed {len(text)} characters via clipboard."

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed {len(text)} characters."


def _screen_point(x, y, field: str = "coordinates") -> tuple[int, int]:
    try:
        point = int(x), int(y)
        width, height = pyautogui.size()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be integer screen coordinates") from exc
    if not (0 <= point[0] < width and 0 <= point[1] < height):
        raise ValueError(
            f"{field} must be inside the current screen ({width}x{height})"
        )
    return point


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        x, y = _screen_point(x, y, "click coordinates")
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    if x is not None or y is not None:
        raise ValueError("both click coordinates must be supplied together")
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    x, y = _screen_point(x, y, "mouse coordinates")
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    x1, y1 = _screen_point(x1, y1, "drag start coordinates")
    x2, y2 = _screen_point(x2, y2, "drag end coordinates")
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _require_pyperclip():
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _require_pyperclip():
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Pasted {len(text)} characters."
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    title = str(title or "").strip()
    if not title:
        return outcome.failed("computer_control", "no window title was given")
    if len(title) > 256:
        return outcome.failed(
            "computer_control", "window title exceeds the 256-character limit"
        )
    if not appidentity._PSUTIL:
        return outcome.failed(
            "computer_control",
            "psutil is not installed, so running windows cannot be identified",
        )

    matches = appidentity.running(title, include_self=True)
    if not matches:
        return outcome.failed(
            "computer_control", "no running window matched that title",
            window=title,
        )
    for match in matches[:10]:
        if appidentity.focus(match):
            return outcome.done(
                "computer_control", action="focus_window",
                window=title, matched=match.label, verified=True,
            )
    return outcome.failed(
        "computer_control", "matching windows were found but none could be focused",
        window=title, candidates=len(matches),
    )


def _text_input(value, field: str = "text") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > _MAX_TEXT_INPUT:
        raise ValueError(
            f"{field} exceeds the {_MAX_TEXT_INPUT}-character limit"
        )
    return value

def _list_processes(limit: int = 10) -> str:
    """Read-only, memory-sorted process summary without command-line contents."""
    if not appidentity._PSUTIL:
        return "Process listing is unavailable because psutil is not installed."

    try:
        count = max(1, min(int(limit), 25))
    except (TypeError, ValueError):
        count = 10

    rows = []
    try:
        for proc in appidentity.psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = proc.info
                memory = info.get("memory_info")
                if not memory:
                    continue
                rows.append((
                    int(memory.rss),
                    int(info.get("pid") or 0),
                    str(info.get("name") or "Unknown"),
                ))
            except (appidentity.psutil.NoSuchProcess,
                    appidentity.psutil.AccessDenied):
                continue
    except Exception as exc:
        print(f"[ComputerControl] Process listing failed: {exc}")
        return f"Could not read the process list: {exc}"

    rows.sort(reverse=True)
    if not rows:
        return "No readable running processes were found."
    lines = ["Top running processes by memory (read-only):"]
    for index, (rss, pid, name) in enumerate(rows[:count], 1):
        lines.append(f"{index}. {name} (PID {pid}) — {rss / (1024 ** 2):.0f} MiB")
    lines.append(
        "To close one, specify its application name; a human confirmation "
        "will be required before anything is closed."
    )
    return "\n".join(lines)


def _close_app(app_name: str, confirmed_index: int | None = None, *,
               user_approved: bool = False) -> str:
    """Close the application the user named — that one, and never this one.

    THE BUG THIS REPLACES
        `computer_settings.close_app` was two lines:

            if _OS == "Darwin": pyautogui.hotkey("command", "q")
            else:               pyautogui.hotkey("alt", "f4")

        No target. It sent Alt+F4 to whatever window had focus, and while
        somebody is talking to the assistant the window with focus is very
        often the assistant — which is why people reported that asking it to
        close an app closed JARVIS itself. It also returned nothing at all, so
        the model announced a success it had no information about.

        The keystroke is not fixable by aiming it better. "The focused window"
        is the wrong idea: the user named an application, so the application is
        what should be found and asked to close.

    HOW THIS ONE BEHAVES
        * The name is matched against what is actually RUNNING — no list of
          applications, so anything on any machine in any country works.
        * The assistant's own process tree is never a candidate. When the only
          thing matching is the assistant, that is said out loud rather than
          obeyed.
        * Two equally good matches is a question, not a coin toss. Closing the
          wrong window loses somebody's unsaved work.
        * It asks politely — WM_CLOSE on Windows, SIGTERM elsewhere — so an
          application with unsaved changes gets to say so, and it NEVER
          escalates to a kill.
        * It then checks whether the process is gone, and answers `done` only
          if it is.
    """
    if not isinstance(app_name, str):
        return outcome.failed("close_app", "application name must be text")
    app_name = app_name.strip()
    if not app_name:
        return outcome.failed("close_app", "no application name was given")
    if len(app_name) > 128 or any(ord(char) < 32 for char in app_name):
        return outcome.failed(
            "close_app",
            "application name must be at most 128 characters and contain no control characters",
        )

    if not appidentity._PSUTIL:
        return outcome.failed(
            "close_app",
            "psutil is not installed, so running applications cannot be found "
            "- run: pip install psutil",
            app=app_name,
        )

    matches = appidentity.running(app_name)

    if not matches:
        # Nothing, or nothing that is not us. Telling those two apart matters:
        # "it is not running" and "the only thing by that name is me" need
        # completely different sentences.
        including_self = appidentity.running(app_name, include_self=True)
        if any(m.is_self for m in including_self):
            return outcome.failed(
                "close_app",
                "the only thing matching that name is the assistant itself, "
                "and it will not close itself - if the user really wants the "
                "assistant closed they should close its window themselves",
                app=app_name,
            )
        return outcome.failed(
            "close_app",
            "no running application matches that name - it may already be "
            "closed, or be running under a different name",
            app=app_name,
        )

    # Group by process NAME, because twenty `opera.exe` are one application
    # with nineteen helpers, not twenty applications — and closing "Opera"
    # means all of them. `matches` is already best-first, so insertion order
    # here ranks the groups.
    by_name: dict[str, list] = {}
    for match in matches:
        by_name.setdefault(match.label, []).append(match)

    ranked = list(by_name.items())          # [(name, [matches...]), ...]
    target_name, group = ranked[0]

    # Two DIFFERENT applications that answer equally well is a question, not a
    # coin toss. Only when they tie: "discord" beating "discordcanary" on an
    # exact match is a clear winner and interrupting the user to confirm it
    # would be the assistant refusing to do an unambiguous thing.
    if len(ranked) > 1 and not confirmed_index:
        best_score = group[0].score
        tied = [name for name, ms in ranked if ms[0].score == best_score]
        if len(tied) > 1:
            return outcome.ask(
                "close_app",
                f"more than one application matches '{app_name}' equally well: "
                f"{', '.join(tied[:4])} - which one should be closed?",
                app=app_name, candidates=len(tied),
            )
        print(f"[ComputerControl] close_app: '{app_name}' -> {target_name} "
              f"(also matched: {', '.join(n for n, _ in ranked[1:5])})")

    if not user_approved:
        if confirm.pending_title():
            return outcome.ask(
                "close_app",
                "another confirmation is already waiting on the HUD; "
                "nothing was closed",
                app=app_name,
            )
        return action_policy.request_confirmation(
            "computer_control",
            "close_app",
            title="Close this application?",
            detail=target_name,
            run=lambda: _close_app(
                app_name,
                confirmed_index=confirmed_index,
                user_approved=True,
            ),
            arguments={"app_name": app_name},
        )

    closed, still_open, reason = 0, 0, ""
    for match in group:
        gone, detail = appidentity.request_close(match)
        if gone:
            closed += 1
        else:
            still_open += 1
            reason = reason or detail

    if closed and not still_open:
        return outcome.done(
            "close_app", app=app_name, closed=target_name,
            processes=closed, verified=True,
        )

    if closed and still_open:
        # Partly gone. Common and benign for multi-process applications: the
        # window is shut and a background helper is taking its time. Said as
        # `unverified` because that is exactly what it is.
        return outcome.unverified(
            "close_app",
            f"{closed} of {closed + still_open} processes closed; the rest are "
            f"still running - {reason}",
            app=app_name, closed=target_name,
        )

    return outcome.failed(
        "close_app", reason or "the application did not close",
        app=app_name, matched=target_name,
    )


def _screen_find(description: str) -> tuple[int, int] | None:
    if not isinstance(description, str) or not description.strip():
        raise ValueError("screen element description is required")
    if len(description) > 500:
        raise ValueError("screen element description exceeds 500 characters")
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] ⚠️ No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        _require_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        buf   = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        prompt = (
            f"This is a screenshot of a {w}×{h} pixel screen. "
            f"Locate the UI element described as: '{description}'. "
            f"Reply with ONLY the center coordinates as: x,y "
            f"If the element is not visible, reply: NOT_FOUND"
        )

        from core import gemini
        response = gemini.call(
            [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
            tier=gemini.FAST, timeout_ms=20_000,
        )
        if response is None:
            return None

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")

    return None


def _screen_fingerprint(image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def _reserve_screen_click() -> bool:
    now = time.monotonic()
    with _screen_click_history_lock:
        while (
            _screen_click_history
            and now - _screen_click_history[0] >= _SCREEN_CLICK_WINDOW_SECONDS
        ):
            _screen_click_history.popleft()
        if len(_screen_click_history) >= _SCREEN_CLICK_MAXIMUM:
            return False
        _screen_click_history.append(now)
        return True


def _screen_click(description: object, arguments: dict) -> str:
    if not isinstance(description, str) or not description.strip():
        return outcome.failed(
            "computer_control",
            "screen_click requires an element description",
            action="screen_click",
        )
    detail = (
        f"Target: {description[:500]}\n"
        "After approval, MARK will send screen captures to Gemini to locate "
        "and revalidate the target. If both observations agree, it will "
        "perform one left click. A local before/after comparison only checks "
        "whether the screen changed, not whether the intended goal was reached."
    )

    def run() -> str:
        if not _reserve_screen_click():
            return outcome.failed(
                "screen_click",
                "screen click rate limit reached; no screenshot or click was sent",
                maximum=_SCREEN_CLICK_MAXIMUM,
                window_seconds=_SCREEN_CLICK_WINDOW_SECONDS,
            )
        coordinates = _screen_find(description)
        if coordinates is None:
            return outcome.failed(
                "computer_control",
                "the described element was not found on the current screen",
                action="screen_click",
            )
        _require_pyautogui()
        coordinates = _screen_point(*coordinates, "screen_find coordinates")
        refreshed = _screen_find(description)
        if refreshed != coordinates:
            return outcome.failed(
                "screen_click",
                "the target changed after confirmation; no click was sent",
                coordinates=coordinates,
                refreshed_coordinates=refreshed,
            )
        before = pyautogui.screenshot()
        before_hash = _screen_fingerprint(before)
        _click(*coordinates)
        after = pyautogui.screenshot()
        after_hash = _screen_fingerprint(after)
        changed = before_hash != after_hash
        if not changed:
            return outcome.unverified(
                "screen_click",
                "the click was sent but the screen did not visibly change",
                coordinates=coordinates,
                screen_changed=False,
            )
        return outcome.done(
            "screen_click",
            coordinates=coordinates,
            screen_changed=True,
            goal_verified=False,
            verified=True,
        )

    return action_policy.run_or_confirm(
        "computer_control",
        "screen_click",
        title="Allow one vision-guided screen click?",
        detail=detail,
        run=run,
        arguments=arguments,
    )

def _computer_control_impl(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      focus_control — focus one uniquely identified UI Automation control
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    if not isinstance(parameters, dict):
        return outcome.failed(
            "computer_control",
            "tool parameters must be an object",
            action="unknown",
        )
    params = parameters
    action_value = params.get("action", "")
    action = action_value.lower().strip() if isinstance(action_value, str) else ""

    if not action:
        return outcome.failed(
            "computer_control",
            "no action was specified",
            action="unknown",
        )

    if player:
        # Terminal, not the HUD: the activity log is for the conversation and
        # for problems, not a receipt for every keystroke. See
        # core/outcome.is_problem().
        print(f"[ComputerControl] {action}")

    print(f"[ComputerControl] action={action}")

    try:

        if action == "type":
            return _type(_text_input(params.get("text", "")))

        if action == "smart_type":
            return _smart_type(
                _text_input(params.get("text", "")),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw = params.get("keys", "")
            if not isinstance(raw, str):
                raise ValueError("keys must be a '+'-separated string")
            keys = [key.strip() for key in raw.split("+")]
            if not 1 <= len(keys) <= 5 or any(
                not key or len(key) > 32 for key in keys
            ):
                raise ValueError("hotkey must contain 1-5 keys of 1-32 characters")
            return _hotkey(*keys)

        if action == "press":
            key = params.get("key", "enter")
            if not isinstance(key, str) or not 1 <= len(key) <= 32:
                raise ValueError("key must be a name of 1-32 characters")
            return _press(key)

        if action == "scroll":
            direction = str(params.get("direction", "down")).lower().strip()
            if direction not in {"up", "down", "left", "right"}:
                raise ValueError("scroll direction must be up, down, left, or right")
            amount = int(params.get("amount", 3))
            if not 1 <= amount <= 100:
                raise ValueError("scroll amount must be between 1 and 100")
            return _scroll(
                direction=direction,
                amount=amount,
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(_text_input(params.get("text", "")))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "inspect_windows":
            max_windows = params.get("limit", 20)
            if not isinstance(max_windows, int) or isinstance(max_windows, bool):
                raise ValueError("limit must be an integer")
            if not 1 <= max_windows <= 50:
                raise ValueError("limit must be between 1 and 50")
            caps = ui_adapter.capabilities()
            if not caps.available:
                return outcome.failed(
                    "computer_control",
                    caps.reason or "Windows UI Automation is unavailable",
                    action="inspect_windows",
                )
            return json.dumps(
                {
                    "status": "done",
                    "action": "inspect_windows",
                    "windows": ui_adapter.inspect_windows(max_windows),
                    "verified": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        if action == "inspect_controls":
            max_windows = params.get("limit", 20)
            if not isinstance(max_windows, int) or isinstance(max_windows, bool):
                raise ValueError("limit must be an integer")
            if not 1 <= max_windows <= 50:
                raise ValueError("limit must be between 1 and 50")
            criteria = {
                key: params.get(key)
                for key in ("name", "control_type", "enabled", "visible")
            }
            if not any(value is not None for value in criteria.values()):
                raise ValueError(
                    "inspect_controls requires name, control_type, enabled, or visible"
                )
            caps = ui_adapter.capabilities()
            if not caps.available:
                return outcome.failed(
                    "computer_control",
                    caps.reason or "Windows UI Automation is unavailable",
                    action="inspect_controls",
                )
            found = ui_adapter.inspect_controls(
                **criteria, max_windows=max_windows
            )
            return json.dumps(
                {
                    "status": "done",
                    "action": "inspect_controls",
                    "result": found,
                    "verified": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        if action == "read_control":
            selector = params.get("selector")
            if not isinstance(selector, dict):
                raise ValueError("read_control requires a structured selector")
            ui_adapter.validate_focus_selector(selector)
            caps = ui_adapter.capabilities()
            if not caps.available:
                return outcome.failed(
                    "computer_control",
                    caps.reason or "Windows UI Automation is unavailable",
                    action="read_control",
                )
            result = ui_adapter.read_control(selector)
            return json.dumps(
                result | {"action": "read_control"},
                ensure_ascii=False,
                sort_keys=True,
            )

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""))
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            return _screen_click(desc, params)

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            if not math.isfinite(secs) or not 0 <= secs <= 30:
                raise ValueError("wait duration must be between 0 and 30 seconds")
            time.sleep(secs)
            return outcome.done(
                "wait",
                verified=True,
                duration_seconds=secs,
                evidence="wait completed",
            )

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "activate_window":
            return _activate_window(params.get("title", ""), params)

        if action == "write_control":
            return _write_control(
                params.get("selector"), params.get("text", ""), params
            )

        if action == "invoke_control":
            return _invoke_control(params.get("selector"), params)

        if action == "focus_control":
            return _focus_control(params.get("selector"), params)

        if action in ("list_processes", "processes", "task_manager"):
            return _list_processes(params.get("limit", 10))

        if action in ("close_app", "close_application", "quit_app"):
            return _close_app(
                params.get("app_name") or params.get("text") or "",
                confirmed_index=params.get("confirmed"),
            )

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        return outcome.failed(
            "computer_control",
            "the requested action is not supported",
            action=action or "unknown",
        )

    except ValueError as e:
        message = str(e)
        safe_prefixes = (
            "window name must ",
            "text must ",
            "text exceeds ",
            "both click coordinates ",
            "coordinates must ",
            "click coordinates must ",
            "keys must ",
            "hotkey must ",
            "key must ",
            "scroll direction must ",
            "scroll amount must ",
            "limit must ",
            "inspect_controls requires ",
            "read_control requires ",
            "wait duration must ",
            "screen element description ",
        )
        error_type = type(e).__name__
        print(f"[ComputerControl] input rejected ({error_type})")
        reason = (
            message
            if message.startswith(safe_prefixes)
            else f"the action failed with {error_type}"
        )
        return outcome.failed(
            "computer_control",
            reason,
            action=action or "unknown",
        )
    except Exception as e:
        error_type = type(e).__name__
        print(f"[ComputerControl] action failed ({error_type})")
        return outcome.failed(
            "computer_control",
            f"the action failed with {error_type}",
            action=action or "unknown",
        )


def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Keep direct handler calls behind the same effect policy as dispatch."""
    return action_policy.dispatch(
        "computer_control",
        parameters,
        lambda: _computer_control_impl(
            parameters, response, player, session_memory
        ),
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_control",
    "description": (
        "Direct computer control: type, click, hotkeys, scroll, move mouse, "
        "screenshots, inspect accessible windows, find elements on screen, "
        "list running processes, and "
        "CLOSE a named application. "
        "For 'open Task Manager' or 'what is using memory', use "
        "action='list_processes' for a read-only summary sorted by RAM. "
        "Use action='close_app' with 'app_name' whenever the user asks to "
        "close, quit or exit a program - 'close Spotify', 'quit Chrome'. "
        "Always name the application in 'app_name'; there is no action that "
        "closes 'whatever is in front', because that is usually the assistant. "
        "Before closing an application, ask the user to confirm on the HUD; "
        "the user's confirmation parameter cannot substitute for that click. "
        "To OPEN an application use the open_app tool instead. "
        "Read the status the tool returns: 'done' means it was confirmed, "
        "'unverified' means it was requested and could NOT be confirmed - say "
        "so rather than claiming success - and 'ask' means nothing was done "
        "and the question must go to the user first."
    ),
    # Used in place of `description` only when a small model is on a tool
    # budget - Gemini still gets the full text. See providers/schema.py.
    "brief": (
        "Controls the computer: inspect processes, type, click, hotkeys, scroll, screenshots, and close a named application (put its name in 'app_name'). Use open_app to open one."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description":                                                 "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | inspect_windows | inspect_controls | read_control | wait | clear_field | focus_window | activate_window | focus_control | write_control | invoke_control | list_processes | close_app | screen_find | screen_click | random_data | user_data"
            },
            "app_name": {
                "type": "STRING",
                "description": (
                    "For close_app: the application to close, named as the "
                    "user said it. Any application running on the machine "
                    "works - there is no fixed list. Never leave this empty."
                )
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": (
                    "For close_app only: set true if the user explicitly "
                    "selected among multiple matching applications, and pass "
                    "the selected application name in 'app_name'. This does "
                    "not replace the separate HUD confirmation before closing."
                )
            },
            "text": {
                "type": "STRING",
                "description": "Text to type or paste"
            },
            "x": {
                "type": "INTEGER",
                "description": "X coordinate"
            },
            "y": {
                "type": "INTEGER",
                "description": "Y coordinate"
            },
            "keys": {
                "type": "STRING",
                "description": "Key combination e.g. 'ctrl+c'"
            },
            "key": {
                "type": "STRING",
                "description": "Single key e.g. 'enter'"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount (default: 3)"
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Seconds to wait"
            },
            "limit": {
                "type": "INTEGER",
                "description": "For list_processes or inspect_windows: 1-50 (default 10)"
            },
            "title": {
                "type": "STRING",
                "description": "Window title for focus_window or activate_window"
            },
            "selector": {
                "type": "OBJECT",
                "description": (
                    "Unique UI Automation selector for focus_control, "
                    "write_control or invoke_control. "
                    "Use window_name, name, control_type and optional automation_id."
                ),
                "properties": {
                    "window_name": {"type": "STRING"},
                    "name": {"type": "STRING"},
                    "control_type": {"type": "STRING"},
                    "automation_id": {"type": "STRING"},
                },
            },
            "name": {
                "type": "STRING",
                "description": "Exact accessible control name for inspect_controls",
            },
            "control_type": {
                "type": "STRING",
                "description": "Exact UIA control type for inspect_controls",
            },
            "enabled": {
                "type": "BOOLEAN",
                "description": "Filter accessible controls by enabled state",
            },
            "visible": {
                "type": "BOOLEAN",
                "description": "Filter accessible controls by visible state",
            },
            "description": {
                "type": "STRING",
                "description": "Element description for screen_find/screen_click"
            },
            "type": {
                "type": "STRING",
                "description": "Data type for random_data"
            },
            "field": {
                "type": "STRING",
                "description": "Field for user_data: name|email|city"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": computer_control,
}
