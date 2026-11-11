"""Central confirmation policy for high-impact tool actions."""
from __future__ import annotations

from collections.abc import Callable
import contextvars
import json
import re
from contextlib import contextmanager

from core import confirm, outcome, session_grants, tool_audit

_CONFIRMATION_RISKS = {"high", "external"}
_CONFIRMED_TOOL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "confirmed_tool_dispatch", default=None
)
_CONFIRMED_SIGNATURE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "confirmed_tool_signature", default=None
)
_AUTHORIZED_PLAN: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "authorized_task_plan", default=None
)
_PRECISE_HANDLER_GATES = {
    "computer_control": {
        "close_app", "focus_control", "activate_window", "write_control",
        "invoke_control",
        "screen_click"
    },
    "computer_settings": {
        "restart", "shutdown", "toggle_wifi", "close_window",
        "close_tab", "close_app", "save",
    },
    "desktop_control": {"wallpaper", "wallpaper_url", "organize", "clean"},
    "file_controller": {
        "delete", "create_file", "create_folder", "move", "copy", "rename",
        "write", "organize_desktop",
    },
    "file_processor": {
        "resize", "convert", "compress", "extract_text", "to_word", "filter",
        "sort", "format", "to_csv", "to_excel", "to_json", "fix", "optimize",
        "document", "transcribe", "trim", "extract_audio", "extract_frame",
        "describe", "ocr", "analyze", "summarize", "translate_hint", "reformat",
        "to_bullet", "custom",
    },
    "game_updater": {"install", "update", "schedule", "cancel_schedule"},
    "meet_control": {"create", "new"},
    "manage_monitor": {"add", "remove"},
    "send_message": {"send"},
    "reminder": {"schedule"},
    "code_helper": {"auto", "write", "edit", "optimize", "screen_debug"},
    "dev_agent": {"build_project"},
}
_SENSITIVE_NAME_RE = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key|otp)",
    re.IGNORECASE,
)
_SENSITIVE_TARGET_KEYS = {
    "automation_id", "control_name", "control_type", "label", "name",
    "placeholder", "selector", "target", "window_title",
}
_SENSITIVE_VALUE_KEYS = {"content", "text", "value"}
_MAX_ARGUMENT_BYTES = 256_000
_MAX_ARGUMENT_DEPTH = 32
_MAX_ARGUMENT_ITEMS = 1_000
_MAX_ARGUMENT_STRING = 100_000


def _session_grant_for(tool: str, action: str) -> tuple[
    session_grants.GrantScope, str
] | None:
    if tool == "computer_control" and action == "screen_find":
        scope = session_grants.GrantScope(
            "share_screen_search", "Gemini", "active_screen"
        )
        return scope, "Send requested screen captures to Gemini for visual search"
    return None


def _effect_arguments(tool: str, action: str, arguments: dict | None) -> dict:
    params = dict(arguments) if isinstance(arguments, dict) else {}
    action_key = "mode" if tool == "task_planner" else "action"
    params[action_key] = action
    return params


def _has_sensitive_target(value) -> bool:
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if str(key).casefold() not in _SENSITIVE_TARGET_KEYS:
            continue
        if isinstance(item, dict):
            if _has_sensitive_target(item):
                return True
        elif is_sensitive_name(item):
            return True
    return False


def is_sensitive_name(value: object) -> bool:
    """Whether a field name or selector identifies sensitive data."""
    return isinstance(value, str) and bool(_SENSITIVE_NAME_RE.search(value))


def _confirmation_value(value, *, selector_sensitive: bool = False):
    if selector_sensitive:
        return "[REDACTED]"
    if isinstance(value, dict):
        is_form = value.get("action") == "fill_form"
        sensitive_target = _has_sensitive_target(value)
        result = {}
        for key, item in value.items():
            if is_sensitive_name(str(key)):
                result[key] = "[REDACTED]"
            elif sensitive_target and str(key).casefold() in _SENSITIVE_VALUE_KEYS:
                result[key] = "[REDACTED]"
            elif is_form and key == "fields" and isinstance(item, dict):
                result[key] = {
                    selector: _confirmation_value(
                        field_value,
                        selector_sensitive=bool(
                            is_sensitive_name(str(selector))
                        ),
                    )
                    for selector, field_value in item.items()
                }
            else:
                result[key] = _confirmation_value(item)
        return result
    if isinstance(value, list):
        return [_confirmation_value(item) for item in value]
    return value


def confirmation_arguments(arguments: dict) -> str:
    """Serialize exact confirmation arguments while redacting sensitive values."""
    try:
        return json.dumps(
            _confirmation_value(arguments),
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError, RecursionError):
        raise ValueError("confirmation arguments could not be safely serialized") from None


def _validate_argument_tree(value, depth: int = 0) -> None:
    if depth > _MAX_ARGUMENT_DEPTH:
        raise ValueError("tool arguments are nested too deeply")
    if isinstance(value, str):
        if len(value) > _MAX_ARGUMENT_STRING:
            raise ValueError("a tool argument exceeds the text size limit")
    elif isinstance(value, dict):
        if len(value) > _MAX_ARGUMENT_ITEMS:
            raise ValueError("a tool argument object has too many entries")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 1_000:
                raise ValueError("tool argument keys must be short text")
            _validate_argument_tree(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > _MAX_ARGUMENT_ITEMS:
            raise ValueError("a tool argument list has too many entries")
        for item in value:
            _validate_argument_tree(item, depth + 1)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("tool arguments must contain JSON-compatible values")


def validate_arguments(arguments: object) -> str | None:
    """Validate shared JSON argument limits before any tool handler runs."""
    if not isinstance(arguments, dict):
        return "tool arguments must be an object"
    try:
        _validate_argument_tree(arguments)
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, ValueError):
            return str(error)
        return "tool arguments must contain bounded JSON-compatible values"
    try:
        serialized = json.dumps(
            arguments, ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError, RecursionError):
        return "tool arguments must contain bounded JSON-compatible values"
    try:
        serialized_size = len(serialized.encode("utf-8"))
    except UnicodeEncodeError:
        return "tool arguments contain invalid text"
    if serialized_size > _MAX_ARGUMENT_BYTES:
        return "tool arguments exceed the supported size limit"
    return None


def requires_confirmation(tool: str, action: str,
                         arguments: dict | None = None) -> bool:
    """Whether the central risk policy requires explicit HUD approval."""
    params = dict(arguments) if isinstance(arguments, dict) else {}
    params["action"] = action
    return (
        tool_audit.classify_risk(tool, params)
        in _CONFIRMATION_RISKS
    )


def request_confirmation(
    tool: str,
    action: str,
    title: str,
    detail: str,
    run: Callable[[], str],
    arguments: dict | None = None,
    voice_handler: Callable[[str], confirm.VoiceDecision] | None = None,
    session_grant: tuple[session_grants.GrantScope, str] | None = None,
) -> str:
    """Queue an action only when the central policy classifies it as sensitive.

    This function intentionally fails closed if a caller attempts to use the
    confirmation gate for an action not marked high-impact.
    """
    if tool_audit.classify_action_effect(
        tool, _effect_arguments(tool, action, arguments)
    ) == "unknown":
        return outcome.failed(
            "action_policy",
            "the action effect or target is unknown; nothing was executed",
            tool=tool,
            action=action,
        )
    if not requires_confirmation(tool, action, arguments):
        return outcome.failed(
            "action_policy",
            "the confirmation gate was requested for an action not classified "
            "as high-impact; nothing was executed",
            tool=tool,
            action=action,
        )
    if voice_handler is None and (
        _is_confirmed_call(tool, arguments or {})
        or _plan_authorizes(tool, arguments or {})
    ):
        return run()
    if voice_handler is None:
        return confirm.request(
            key=f"{tool}-{action}",
            title=title,
            detail=detail,
            run=run,
            grant_action=(
                (lambda: session_grants.create(*session_grant))
                if session_grant is not None else None
            ),
            grant_label=session_grant[1] if session_grant is not None else "",
        )
    return confirm.request(
        key=f"{tool}-{action}",
        title=title,
        detail=detail,
        run=run,
        voice_handler=voice_handler,
    )


def run_or_confirm(
    tool: str,
    action: str,
    title: str,
    detail: str,
    run: Callable[[], str],
    arguments: dict | None = None,
) -> str:
    """Run routine actions directly and gate only high-impact actions."""
    if tool_audit.classify_action_effect(
        tool, _effect_arguments(tool, action, arguments)
    ) == "unknown":
        return outcome.failed(
            "action_policy",
            "the action effect or target is unknown; nothing was executed",
            tool=tool,
            action=action,
        )
    if not requires_confirmation(tool, action, arguments):
        return run()
    return request_confirmation(
        tool=tool,
        action=action,
        title=title,
        detail=detail,
        run=run,
        arguments=arguments,
    )


def is_confirmed(tool: str) -> bool:
    """Whether this dispatch is running inside its HUD-approved callback."""
    return _CONFIRMED_TOOL.get() == tool


def _request_signature(tool: str, arguments: dict) -> str:
    return json.dumps(
        [tool, arguments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_confirmed_call(tool: str, arguments: dict) -> bool:
    try:
        signature = _request_signature(tool, arguments)
    except (TypeError, ValueError, RecursionError):
        return False
    return _CONFIRMED_SIGNATURE.get() == signature


def _plan_authorizes(tool: str, arguments: dict) -> bool:
    authorized = _AUTHORIZED_PLAN.get()
    if authorized is None:
        return False
    try:
        return _request_signature(tool, arguments) in authorized
    except (TypeError, ValueError):
        return False


@contextmanager
def authorize_plan(steps: list[tuple[str, dict]]):
    """Authorize only the exact tool calls shown in an approved plan."""
    signatures = frozenset(_request_signature(tool, args) for tool, args in steps)
    token = _AUTHORIZED_PLAN.set(signatures)
    try:
        yield
    finally:
        _AUTHORIZED_PLAN.reset(token)


def dispatch(
    tool: str,
    arguments: dict,
    run: Callable[[], str],
) -> str:
    """Enforce a dispatcher-level confirmation for unreviewed sensitive tools.

    Migrated handlers keep their exact, action-specific preview. All other
    high-impact handlers and discovered plugins are gated here with the full
    serialized arguments; a handler-level gate under this authorization runs
    only after the dispatcher confirmation has already been accepted.
    """
    if not isinstance(arguments, dict):
        return outcome.failed(
            "action_policy",
            "tool arguments must be an object; nothing was executed",
            tool=tool,
        )
    if not callable(run):
        return outcome.failed(
            "action_policy",
            "tool handler is not callable; nothing was executed",
            tool=tool,
        )
    validation_error = validate_arguments(arguments)
    if validation_error:
        return outcome.failed(
            "action_policy",
            f"{validation_error}; nothing was executed",
            tool=tool,
        )

    effect = tool_audit.classify_action_effect(tool, arguments)
    if effect == "unknown":
        action_value = arguments.get(
            "mode" if tool == "task_planner" else "action", "execute"
        )
        action = (
            action_value.strip().lower()
            if isinstance(action_value, str) else "execute"
        )
        return outcome.failed(
            "action_policy",
            "the action effect or target is unknown; nothing was executed",
            tool=tool,
            action=action,
        )

    default_actions = {
        "game_updater": "update",
        "reminder": "schedule",
        "task_planner": "preview",
    }
    action_value = arguments.get(
        "mode" if tool == "task_planner" else "action",
        default_actions.get(tool, "execute"),
    )
    action = action_value.strip().lower() if isinstance(action_value, str) else "execute"
    risk = tool_audit.classify_risk(tool, arguments)
    if risk == "unclassified":
        return outcome.failed(
            "action_policy",
            "the tool action has no reviewed risk classification; nothing was executed",
            tool=tool,
            action=action,
        )
    authorized_plan = _AUTHORIZED_PLAN.get()
    if authorized_plan is not None:
        try:
            exact = _request_signature(tool, arguments)
        except (TypeError, ValueError):
            exact = ""
        if exact in authorized_plan:
            return run()
    session_grant = _session_grant_for(tool, action)
    if session_grant is not None and session_grants.allows(session_grant[0]):
        return run()
    if risk not in _CONFIRMATION_RISKS:
        return run()
    if action in _PRECISE_HANDLER_GATES.get(tool, set()):
        return run()

    try:
        serialized = confirmation_arguments(arguments)
    except ValueError:
        return outcome.failed(
            "action_policy",
            "arguments could not be safely shown for confirmation; nothing was executed",
            tool=tool,
        )
    detail = f"Tool: {tool}\nAction: {action}\nArguments:\n{serialized}"
    if len(detail) > confirm.MAX_DETAIL_LENGTH:
        return outcome.failed(
            "action_policy",
            "the complete arguments do not fit in the confirmation panel; "
            "nothing was executed",
            tool=tool,
            action=action,
        )

    def run_after_approval() -> str:
        tool_token = _CONFIRMED_TOOL.set(tool)
        signature_token = _CONFIRMED_SIGNATURE.set(
            _request_signature(tool, arguments)
        )
        try:
            return run()
        finally:
            _CONFIRMED_SIGNATURE.reset(signature_token)
            _CONFIRMED_TOOL.reset(tool_token)

    return request_confirmation(
        tool,
        action,
        f"Allow {tool} to perform this action?",
        detail,
        run_after_approval,
        arguments=arguments,
        session_grant=session_grant,
    )
