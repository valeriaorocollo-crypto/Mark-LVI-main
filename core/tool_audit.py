"""Bounded, in-memory audit metadata for tool dispatch.

The audit intentionally never stores tool arguments or result text: those may
contain message bodies, file paths, page contents, credentials, or personal data.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass

MAX_EVENTS = 100
_STATUS_RE = re.compile(r"^status=(done|unverified|failed|ask|started)\b")
_FAILURE_RE = re.compile(
    r"^(?:Tool '[^']+' failed:|Action '[^']+' crashed during run\(\):)"
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

_EXTERNAL_TOOLS = {
    "send_message",
    "meet_control",
    "gmail_control",
    "calendar_control",
}
_TOOL_RISK = {
    "dev_agent": "high",
    "shutdown_jarvis": "high",
    "flight_finder": "read_or_navigate",
    "reminder": "high",
    "screen_process": "read_or_navigate",
    "weather_report": "read_or_navigate",
}
_DESTRUCTIVE_ACTIONS = {
    "delete",
    "delete_file",
    "delete_folder",
    "delete_directory",
    "shutdown",
    "restart",
    "toggle_wifi",
    "close_app",
    "close_application",
    "quit_app",
    "send",
    "publish",
    "purchase",
    "buy",
    "create",
    "new",
}
_SEMANTIC_TARGET_RISK_RE = re.compile(
    r"\b(?:buy|purchase|checkout|pay|payment|order|send|submit|publish|share|save|"
    r"delete|remove|erase|format|shutdown|restart|power off|rent|rental|"
    r"comprar|compra|pagar|pago|pedido|enviar|publicar|compartir|guardar|"
    r"eliminar|borrar|suprimir|formatear|apagar|reiniciar|alquilar|alquiler|"
    r"password|passwd|secret|token|credential|private key|api key|otp|"
    r"contraseña|clave|credencial|correo|e-mail|email|phone|teléfono|telefono|"
    r"address|dirección|direccion|card|tarjeta|recipient|destinatario|"
    r"message|mensaje|account|cuenta)\b",
    re.IGNORECASE,
)
_STANDARD_TOOLS = {
    "close_camera",
    "manage_monitor",
    "open_app",
    "recall_memory",
    "system_status",
    "undo",
}
_READ_ONLY_VERIFICATION_ACTIONS = {
    "browser_control": {"get_text", "get_url"},
    "computer_control": {
        "inspect_windows", "inspect_controls", "read_control",
    },
    "file_processor": {
        "extract_preview", "search",
    },
    "gmail_control": {"search"},
}
_ACTION_RISK = {
    "browser_control": {
        "list_browsers": "read_or_navigate",
        "get_text": "read_or_navigate",
        "get_url": "read_or_navigate",
        "screenshot": "read_or_navigate",
        "scroll": "read_or_navigate",
        "go_to": "read_or_navigate",
        "search": "read_or_navigate",
        "back": "read_or_navigate",
        "forward": "read_or_navigate",
        "reload": "read_or_navigate",
        "new_tab": "read_or_navigate",
        "open": "read_or_navigate",
        "switch": "read_or_navigate",
        "click": "high",
        "type": "high",
        "fill_form": "high",
        "smart_click": "high",
        "smart_type": "high",
        "press": "high",
        "close_tab": "high",
        "close": "high",
        "close_all": "high",
    },
    "spotify_control": {
        "search": "read_or_navigate",
        "play": "state_change",
        "play_pause": "state_change",
        "next": "state_change",
        "previous": "state_change",
    },
    "video_player": {
        "play": "state_change",
        "stop": "state_change",
        "mute": "state_change",
        "unmute": "state_change",
    },
    "computer_control": {
        "close_app": "high",
        "screenshot": "read_or_navigate",
        "screen_find": "high",
        "inspect_windows": "read_or_navigate",
        "inspect_controls": "read_or_navigate",
        "read_control": "read_or_navigate",
        "list_processes": "read_or_navigate",
        "processes": "read_or_navigate",
        "task_manager": "read_or_navigate",
        "wait": "read_or_navigate",
        "focus_window": "read_or_navigate",
        "activate_window": "state_change",
        "focus_control": "state_change",
        "write_control": "high",
        "invoke_control": "high",
        "click": "high",
        "type": "high",
        "smart_type": "high",
        "double_click": "high",
        "right_click": "high",
        "move": "state_change",
        "drag": "high",
        "hotkey": "high",
        "press": "high",
        "scroll": "state_change",
        "copy": "high",
        "paste": "high",
        "screen_click": "high",
        "clear_field": "high",
        "random_data": "high",
        "user_data": "high",
    },
    "task_planner": {
        "preview": "read_or_navigate",
    },
    "computer_settings": {
        "restart": "high",
        "shutdown": "high",
        "toggle_wifi": "high",
        "close_window": "high",
        "close_tab": "high",
        "close_app": "high",
        "volume_up": "state_change",
        "volume_down": "state_change",
        "volume_set": "state_change",
        "mute": "state_change",
        "unmute": "state_change",
        "toggle_mute": "state_change",
        "brightness_up": "state_change",
        "brightness_down": "state_change",
        "sleep_display": "state_change",
        "full_screen": "state_change",
        "fullscreen": "state_change",
        "screen_off": "state_change",
        "play_pause": "state_change",
        "show_desktop": "state_change",
        "lock_screen": "state_change",
        "dark_mode": "state_change",
        "task_manager": "read_or_navigate",
        "screenshot": "read_or_navigate",
        "find_on_page": "read_or_navigate",
        "refresh_page": "state_change",
        "reload": "state_change",
        "new_tab": "state_change",
        "close_tab": "high",
        "pause_video": "state_change",
        "minimize": "state_change",
        "maximize": "state_change",
        "snap_left": "state_change",
        "snap_right": "state_change",
        "switch_window": "state_change",
        "focus_search": "state_change",
        "next_tab": "state_change",
        "prev_tab": "state_change",
        "go_back": "state_change",
        "go_forward": "state_change",
        "zoom_in": "state_change",
        "zoom_out": "state_change",
        "zoom_reset": "state_change",
        "scroll_up": "state_change",
        "scroll_down": "state_change",
        "scroll_top": "state_change",
        "scroll_bottom": "state_change",
        "page_up": "state_change",
        "page_down": "state_change",
        "copy": "state_change",
        "paste": "high",
        "cut": "high",
        "undo": "state_change",
        "redo": "state_change",
        "select_all": "state_change",
        "save": "high",
        "enter": "high",
        "escape": "state_change",
        "press_key": "high",
        "type_text": "high",
        "open_settings": "state_change",
        "file_explorer": "state_change",
        "open_run": "high",
        "reload_n": "state_change",
        "refresh_n": "state_change",
        "reload_page_n": "state_change",
        "type": "high",
        "write": "high",
        "write_on_screen": "high",
    },
    "file_controller": {
        "list": "read_or_navigate",
        "read": "read_or_navigate",
        "find": "read_or_navigate",
        "largest": "read_or_navigate",
        "disk_usage": "read_or_navigate",
        "info": "read_or_navigate",
        "delete": "high",
        "write": "high",
        "create_file": "high",
        "create_folder": "high",
        "move": "high",
        "copy": "high",
        "rename": "high",
        "organize_desktop": "high",
    },
    "desktop_control": {
        "wallpaper": "high",
        "wallpaper_url": "high",
        "organize": "high",
        "clean": "high",
        "current_wallpaper": "read_or_navigate",
        "list": "read_or_navigate",
        "stats": "read_or_navigate",
    },
    "game_updater": {
        "": "external",
        "install": "external",
        "update": "external",
        "schedule": "high",
        "cancel_schedule": "high",
        "list": "read_or_navigate",
        "download_status": "read_or_navigate",
        "schedule_status": "read_or_navigate",
    },
    "manage_monitor": {
        "add": "high",
        "remove": "high",
        "list": "read_or_navigate",
    },
    "save_memory": {
        "save": "high",
    },
    "reminder": {
        "schedule": "high",
    },
    "code_helper": {
        "auto": "high",
        "write": "high",
        "edit": "high",
        "optimize": "high",
        "screen_debug": "high",
        "run": "high",
        "build": "high",
        "explain": "read_or_navigate",
    },
    "file_processor": {
        "info": "read_or_navigate",
        "list": "read_or_navigate",
        "read": "read_or_navigate",
        "extract_preview": "read_or_navigate",
        "search": "read_or_navigate",
        "word_count": "read_or_navigate",
        "validate": "read_or_navigate",
        "stats": "read_or_navigate",
        "explain": "read_or_navigate",
        "review": "read_or_navigate",
        "run": "high",
        "extract": "high",
        "resize": "high",
        "convert": "high",
        "compress": "high",
        "extract_text": "high",
        "to_word": "high",
        "filter": "high",
        "sort": "high",
        "format": "high",
        "to_csv": "high",
        "to_excel": "high",
        "to_json": "high",
        "fix": "high",
        "optimize": "high",
        "document": "high",
        "transcribe": "high",
        "trim": "high",
        "extract_audio": "high",
        "extract_frame": "high",
        "describe": "high",
        "ocr": "high",
        "analyze": "high",
        "summarize": "high",
        "translate_hint": "high",
        "reformat": "high",
        "to_bullet": "high",
        "custom": "high",
    },
    "web_search": {
        "": "read_or_navigate",
        "search": "read_or_navigate",
        "news": "read_or_navigate",
        "research": "read_or_navigate",
        "price": "read_or_navigate",
        "compare": "read_or_navigate",
    },
    "youtube_video": {
        "": "read_or_navigate",
        "play": "read_or_navigate",
        "summarize": "read_or_navigate",
        "get_info": "read_or_navigate",
        "trending": "read_or_navigate",
    },
}
_OPAQUE_DESKTOP_ACTIONS = {
    "computer_control": {
        "click", "double_click", "right_click", "drag", "hotkey", "press",
        "paste", "type", "smart_type", "clear_field", "focus_window", "move",
    },
    "computer_settings": {
        "press_key", "type_text", "write_on_screen", "type", "write",
        "paste", "enter", "open_run", "close_window", "close_tab",
        "close_app", "save",
    },
    "browser_control": {"press"},
}
_NAVIGATION_ACTIONS = {
    "browser_control": {
        "open", "go_to", "search", "new_tab", "switch", "back", "forward", "reload",
        "scroll",
    },
    "computer_control": {"activate_window", "focus_control"},
    "computer_settings": {
        "open_settings", "file_explorer", "show_desktop", "switch_window",
        "go_back", "go_forward", "next_tab", "prev_tab",
    },
}
_DYNAMIC_TOOL_RISK: dict[str, str] = {}
_DYNAMIC_RISK_LOCK = threading.Lock()


@dataclass(frozen=True)
class ToolEvent:
    tool: str
    action: str
    status: str
    risk: str
    effect: str
    duration_ms: int
    at: float


_events: deque[ToolEvent] = deque(maxlen=MAX_EVENTS)
_lock = threading.Lock()


def classify_status(result: object) -> str:
    """Return a known outcome status, or `unclassified` for legacy prose."""
    if not isinstance(result, str):
        return "unclassified"
    text = result.strip()
    match = _STATUS_RE.match(text)
    if match:
        return match.group(1)
    if _FAILURE_RE.match(text):
        return "failed"
    if text.startswith("[CONFIRMATION_PENDING]"):
        return "ask"
    return "unclassified"


def classify_effect(status: str) -> str:
    """Conservatively describe the possible effect, not the requested intent."""
    if status == "ask":
        return "none"
    if status == "done":
        return "verified"
    if status in {"started", "unverified", "failed"}:
        return "possible"
    return "unknown"


def failure_result(tool: str, error: BaseException) -> str:
    """Build a useful failure result without exposing exception contents."""
    safe_tool = tool if isinstance(tool, str) and _IDENTIFIER_RE.fullmatch(tool) else "unknown"
    error_type = type(error).__name__
    safe_type = (
        error_type
        if isinstance(error_type, str) and _IDENTIFIER_RE.fullmatch(error_type)
        else "Exception"
    )
    return f"Tool '{safe_tool}' failed: {safe_type}"


def classify_risk(tool: str, arguments: dict | None = None) -> str:
    """Classify a tool request without retaining or exposing its arguments."""
    name = tool.strip().lower() if isinstance(tool, str) else ""
    args = arguments if isinstance(arguments, dict) else {}
    with _DYNAMIC_RISK_LOCK:
        dynamic_risk = _DYNAMIC_TOOL_RISK.get(name)
    if dynamic_risk:
        return dynamic_risk
    raw_action = (
        args.get("mode") if name in {"web_search", "task_planner"}
        else args.get("action")
    )
    action = (
        raw_action.strip().lower().replace("-", "_")
        if isinstance(raw_action, str) else ""
    )

    if name == "computer_control" and action in {
        "focus_control", "write_control", "invoke_control",
    }:
        selector = args.get("selector")
        if isinstance(selector, dict) and action in {"write_control", "invoke_control"}:
            return "high"
        if isinstance(selector, dict):
            target_fields = (
                "window_name", "name", "control_type", "automation_id",
            )
            if any(
                isinstance(selector.get(field), str)
                and _SEMANTIC_TARGET_RISK_RE.search(selector[field][:2_000])
                for field in target_fields
            ):
                return "high"
        return "state_change"

    if name == "task_planner" and action in {"execute", "clear_history"}:
        return "high"
    if name == "task_planner" and action in {"cancel", "status", "history"}:
        return "standard"
    if name in _EXTERNAL_TOOLS:
        return "external"
    if name == "flight_finder" and args.get("save") is True:
        return "high"
    if name == "youtube_video" and args.get("save") is True:
        return "high"
    if name == "computer_settings" and not action:
        return "high"
    if name in _TOOL_RISK:
        return _TOOL_RISK[name]
    if action.startswith("delete_"):
        return "high"
    tool_actions = _ACTION_RISK.get(name)
    if tool_actions is not None:
        return tool_actions.get(action, "unclassified")
    if action in _DESTRUCTIVE_ACTIONS:
        return "high"
    if name in _STANDARD_TOOLS:
        return "standard"
    return "unclassified"


def classify_action_effect(tool: str, arguments: dict | None = None) -> str:
    """Classify the requested effect; opaque or unreviewed targets fail closed."""
    name = tool.strip().lower() if isinstance(tool, str) else ""
    args = arguments if isinstance(arguments, dict) else {}
    action_key = "mode" if name in {"web_search", "task_planner"} else "action"
    raw_action = args.get(action_key)
    action = (
        raw_action.strip().lower().replace("-", "_")
        if isinstance(raw_action, str) else ""
    )

    if action in _OPAQUE_DESKTOP_ACTIONS.get(name, set()):
        return "unknown"
    if name == "computer_control":
        selector = args.get("selector")
        has_selector = isinstance(selector, dict) and bool(
            isinstance(selector.get("window_name"), str)
            and selector["window_name"].strip()
            and isinstance(selector.get("control_type"), str)
            and selector["control_type"].strip()
            and isinstance(selector.get("name"), str)
            and isinstance(selector.get("automation_id", ""), str)
        )
        if action in {"write_control", "invoke_control"}:
            return "external_communication" if has_selector else "unknown"
        if action == "focus_control":
            return "navigation" if has_selector else "unknown"
        if action == "activate_window":
            title = args.get("title")
            return "navigation" if isinstance(title, str) and title.strip() else "unknown"
        if action == "screen_click":
            description = args.get("description")
            return (
                "local_destructive_change"
                if isinstance(description, str) and description.strip()
                else "unknown"
            )
        if action in {"screen_find", "copy", "user_data"}:
            return "external_communication"
        if action == "close_app":
            target = args.get("app_name") or args.get("text")
            return (
                "local_destructive_change"
                if isinstance(target, str) and target.strip()
                else "unknown"
            )

    if name == "browser_control":
        if action in {"click", "type"}:
            selector = args.get("selector")
            target_text = args.get("text")
            if (
                isinstance(selector, str) and selector.strip()
            ) or (
                isinstance(target_text, str) and target_text.strip()
            ):
                return "external_communication"
            return "unknown"
        if action == "fill_form":
            fields = args.get("fields")
            if isinstance(fields, dict) and fields and all(
                isinstance(selector, str) and selector.strip()
                for selector in fields
            ):
                return "external_communication"
            return "unknown"
        if action in {"smart_click", "smart_type", "close", "close_all", "close_tab"}:
            return "unknown"

    if action in _NAVIGATION_ACTIONS.get(name, set()):
        return "navigation"

    if name in {"send_message", "meet_control", "gmail_control", "calendar_control"}:
        return "external_communication"
    if name == "game_updater" and action in {"install", "update"}:
        return "financial_administrative"
    if name == "computer_settings" and action in {
        "restart", "shutdown", "toggle_wifi",
    }:
        return "financial_administrative"
    if name == "manage_monitor" and action in {"add", "remove"}:
        return "financial_administrative"
    if name == "computer_control" and action in {"screen_find", "copy", "user_data"}:
        return "external_communication"
    if name == "file_controller":
        if action == "delete":
            return "local_destructive_change"
        if action in {
            "write", "create_file", "create_folder", "move", "copy", "rename",
            "organize_desktop",
        }:
            return "local_reversible_change"
    if name == "file_processor" and classify_risk(name, args) == "high":
        return "local_reversible_change"
    if name == "code_helper" and action in {
        "auto", "write", "edit", "optimize",
    }:
        return "local_reversible_change"
    if name == "task_planner" and action == "clear_history":
        return "local_destructive_change"
    if name == "shutdown_jarvis":
        return "financial_administrative"
    if name == "undo":
        return "local_destructive_change"
    if name == "open_app":
        return "navigation"
    if name == "close_camera":
        return "local_reversible_change"
    if name in {"flight_finder", "youtube_video"} and args.get("save") is True:
        return "local_reversible_change"
    if name in {"reminder", "save_memory"}:
        return "local_reversible_change"

    risk = classify_risk(name, args)
    return {
        "read_or_navigate": "read_only",
        "state_change": "local_reversible_change",
        "high": "local_destructive_change",
        "external": "external_communication",
        "standard": "read_only",
        "unclassified": "unknown",
    }.get(risk, "unknown")


def is_reviewed_tool(tool: str) -> bool:
    """Return whether a tool has an explicit local risk policy."""
    name = tool.strip().lower() if isinstance(tool, str) else ""
    with _DYNAMIC_RISK_LOCK:
        return bool(
            name in _TOOL_RISK
            or name in _STANDARD_TOOLS
            or name in _ACTION_RISK
            or name in _EXTERNAL_TOOLS
            or name in _DYNAMIC_TOOL_RISK
        )


def is_read_only_verification(tool: str, arguments: dict | None = None) -> bool:
    """Allow only explicitly enumerated inspection/read actions as verifiers."""
    name = tool.strip().lower() if isinstance(tool, str) else ""
    args = arguments if isinstance(arguments, dict) else {}
    action_key = "mode" if name == "web_search" else "action"
    raw_action = args.get(action_key, "")
    action = (
        raw_action.strip().lower().replace("-", "_")
        if isinstance(raw_action, str) else ""
    )
    return action in _READ_ONLY_VERIFICATION_ACTIONS.get(name, set())


def _audit_action(tool: str, arguments: dict | None) -> str:
    if not isinstance(arguments, dict):
        return "execute"
    field = "mode" if tool in {"web_search", "task_planner"} else "action"
    raw_action = arguments.get(field)
    if raw_action is None:
        return "execute"
    if not isinstance(raw_action, str):
        return "unclassified"
    action = raw_action.strip().lower().replace("-", "_")
    return action if _IDENTIFIER_RE.fullmatch(action) else "unclassified"


def register_tool_risk(tool: str, risk: str) -> None:
    """Set a process-local risk classification for a discovered extension."""
    if (not isinstance(tool, str) or not _IDENTIFIER_RE.fullmatch(tool)
            or risk not in {"high", "external"}):
        raise ValueError("tool name or dynamic risk is invalid")
    with _DYNAMIC_RISK_LOCK:
        _DYNAMIC_TOOL_RISK[tool.lower()] = risk


def record(tool: str, result: object, duration_ms: float,
           arguments: dict | None = None) -> ToolEvent:
    """Record metadata only; never retain the supplied arguments or result."""
    name = tool[:64] if isinstance(tool, str) and tool else "unknown"
    try:
        duration = max(0, min(int(duration_ms), 86_400_000))
    except (TypeError, ValueError, OverflowError):
        duration = 0
    status = classify_status(result)
    event = ToolEvent(
        tool=name,
        action=_audit_action(name, arguments),
        status=status,
        risk=classify_risk(name, arguments),
        effect=classify_effect(status),
        duration_ms=duration,
        at=time.time(),
    )
    with _lock:
        _events.append(event)
    return event


def recent(limit: int = 20) -> list[ToolEvent]:
    """Return newest-first metadata for local diagnostics."""
    try:
        count = max(1, min(int(limit), MAX_EVENTS))
    except (TypeError, ValueError):
        count = 20
    with _lock:
        return list(reversed(tuple(_events)[-count:]))


def clear() -> None:
    """Clear in-memory audit data, e.g. when a session is reset."""
    with _lock:
        _events.clear()
