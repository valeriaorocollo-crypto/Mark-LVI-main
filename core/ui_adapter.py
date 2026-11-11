"""Windows UI Automation adapter with bounded inspection and verified actions.

The adapter exposes bounded inspection plus explicitly gated UI Automation
actions. It never uses coordinates, arbitrary selectors, or shell commands.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any
from _ctypes import COMError


@dataclass(frozen=True)
class ApplicationCapabilities:
    platform: str
    available: bool
    read_only: bool
    capabilities: tuple[str, ...]
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "available": self.available,
            "read_only": self.read_only,
            "capabilities": list(self.capabilities),
            "reason": self.reason,
        }


def _selection_recovery(
    status: str, missing_kind: str = "control_missing"
) -> str:
    return "target_ambiguous" if status == "ambiguous" else missing_kind


def capabilities() -> ApplicationCapabilities:
    """Describe the adapter without importing or launching UI automation."""
    system = platform.system()
    if system != "Windows":
        return ApplicationCapabilities(
            platform=system or "unknown",
            available=False,
            read_only=True,
            capabilities=(),
            reason="Windows UI Automation is the only supported adapter.",
        )
    try:
        import pywinauto  # noqa: F401
    except (ImportError, AttributeError, OSError, RuntimeError):
        return ApplicationCapabilities(
            platform=system,
            available=False,
            read_only=True,
            capabilities=(),
            reason="pywinauto or its Windows UI Automation backend is unavailable.",
        )
    return ApplicationCapabilities(
        platform=system,
        available=True,
        read_only=False,
        capabilities=(
            "list_windows", "inspect_controls", "read_allowed_text",
            "focus_verified_control", "activate_verified_window",
            "write_verified_control",
            "invoke_verified_control",
        ),
    )


def _safe_text(control: Any, max_length: int = 500) -> str:
    """Return non-sensitive control text without reading password fields."""
    try:
        if _is_password_control(control):
            return ""
        info = control.element_info
        control_type = str(getattr(info, "control_type", "") or "").lower()
        element = getattr(info, "element", None)
        if element is not None:
            is_password = getattr(element, "CurrentIsPassword", None)
            if is_password is not None and bool(is_password):
                return ""
        text = ""
        if control_type in {"edit", "document"}:
            getter = getattr(control, "get_value", None)
            if callable(getter):
                text = str(getter() or "")
        if not text:
            text = str(control.window_text() or "")
    except (AttributeError, RuntimeError, TypeError, OSError, COMError):
        return ""
    return text[:max_length]


def _is_password_control(control: Any) -> bool:
    """Detect password controls from UIA metadata, failing closed on errors."""
    try:
        info = control.element_info
        control_type = str(getattr(info, "control_type", "") or "").casefold()
        name = str(getattr(info, "name", "") or "").casefold()
        if "password" in control_type or "password" in name:
            return True
        element = getattr(info, "element", None)
        if element is None:
            return False
        is_password = getattr(element, "CurrentIsPassword", None)
        return bool(is_password) if is_password is not None else False
    except (AttributeError, RuntimeError, TypeError, OSError, COMError):
        return True


def _control_record(control: Any) -> dict[str, Any]:
    try:
        info = control.element_info
        control_type = str(info.control_type or "")
        name = str(info.name or "")[:300]
        automation_id = str(info.automation_id or "")[:200]
        is_password = _is_password_control(control)
    except (AttributeError, RuntimeError, TypeError, OSError, COMError) as exc:
        raise RuntimeError(
            f"UI Automation control inspection failed: {type(exc).__name__}"
        ) from exc
    enabled, enabled_error = _control_flag(control, "is_enabled")
    visible, visible_error = _control_flag(control, "is_visible")
    errors = {
        key: error
        for key, error in (
            ("enabled", enabled_error),
            ("visible", visible_error),
        )
        if error is not None
    }
    record = {
        "control_type": control_type,
        "name": name,
        "automation_id": automation_id,
        "is_password": is_password,
        "enabled": enabled,
        "visible": visible,
        "text": _safe_text(control),
    }
    if errors:
        record["inspection_errors"] = errors
    return record


def _control_flag(control: Any, method: str) -> tuple[bool | None, str | None]:
    try:
        return bool(getattr(control, method)()), None
    except (AttributeError, RuntimeError, TypeError, OSError, COMError) as exc:
        return None, type(exc).__name__


def _has_focus(control: Any) -> bool:
    """Read focus from the wrapper or the native UIA element."""
    has_focus = getattr(control, "has_focus", None)
    if callable(has_focus):
        return bool(has_focus())
    element_info = getattr(control, "element_info", None)
    element = getattr(element_info, "element", None)
    return bool(element.CurrentHasKeyboardFocus)


def inspect_windows(max_windows: int = 50) -> list[dict[str, Any]]:
    """List visible top-level windows and bounded control metadata."""
    if not isinstance(max_windows, int) or isinstance(max_windows, bool):
        raise ValueError("max_windows must be an integer")
    if not 1 <= max_windows <= 50:
        raise ValueError("max_windows must be between 1 and 50")
    caps = capabilities()
    if not caps.available:
        raise RuntimeError(caps.reason or "Windows UI Automation is unavailable")

    records: list[dict[str, Any]] = []
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(
            visible_only=True, top_level_only=True
        )
        for window in windows[:max_windows]:
            record = _control_record(window)
            record["controls"] = [
                _control_record(child)
                for child in window.descendants()[:100]
            ]
            records.append(record)
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        raise RuntimeError(
            f"Windows UI Automation inspection failed: {type(exc).__name__}"
        ) from exc
    return records


def find_controls(
    windows: list[dict[str, Any]],
    *,
    name: str | None = None,
    control_type: str | None = None,
    enabled: bool | None = None,
    visible: bool | None = None,
) -> dict[str, Any]:
    """Find controls using exact metadata matches, without acting on them.

    A single match returns a stable descriptive selector. Zero matches and
    multiple matches are explicit outcomes; callers must not guess.
    """
    if not isinstance(windows, list):
        raise ValueError("windows must be a list")
    criteria = {
        "name": name.strip().casefold() if isinstance(name, str) else None,
        "control_type": (
            control_type.strip().casefold()
            if isinstance(control_type, str)
            else None
        ),
        "enabled": enabled,
        "visible": visible,
    }
    if not any(value is not None for value in criteria.values()):
        raise ValueError("at least one control selector is required")
    if any(
        value is not None and not isinstance(value, (str, bool))
        for value in criteria.values()
    ):
        raise ValueError("control selector values have invalid types")

    matches: list[dict[str, Any]] = []
    unknown_matches = 0
    for window in windows:
        if not isinstance(window, dict):
            continue
        window_name = str(window.get("name") or "")[:300]
        for index, control in enumerate(window.get("controls", [])):
            if not isinstance(control, dict):
                continue
            if criteria["name"] is not None and (
                str(control.get("name") or "").casefold() != criteria["name"]
            ):
                continue
            if criteria["control_type"] is not None and (
                str(control.get("control_type") or "").casefold()
                != criteria["control_type"]
            ):
                continue
            if (
                criteria["enabled"] is not None
                and control.get("enabled") is None
            ) or (
                criteria["visible"] is not None
                and control.get("visible") is None
            ):
                unknown_matches += 1
                continue
            if criteria["enabled"] is not None and (
                control.get("enabled") is not criteria["enabled"]
            ):
                continue
            if criteria["visible"] is not None and (
                control.get("visible") is not criteria["visible"]
            ):
                continue
            matches.append(
                {
                    "window_name": window_name,
                    "control": dict(control),
                    "selector": {
                        "window_name": window_name,
                        "name": str(control.get("name") or "")[:300],
                        "automation_id": str(
                            control.get("automation_id") or ""
                        )[:200],
                        "control_type": str(
                            control.get("control_type") or ""
                        )[:100],
                        "ordinal": index,
                    },
                }
            )

    if unknown_matches:
        return {
            "status": "unverified",
            "recovery": "state_unreadable",
            "matches": [],
            "ambiguous": bool(matches or unknown_matches > 1),
            "reason": "one or more possible matches have unreadable state",
        }
    if len(matches) == 1:
        return {"status": "found", "matches": matches, "ambiguous": False}
    if not matches:
        return {
            "status": "not_found",
            "recovery": "control_missing",
            "matches": [],
            "ambiguous": False,
        }
    return {
        "status": "ambiguous",
        "recovery": "target_ambiguous",
        "matches": matches[:20],
        "ambiguous": True,
    }


def inspect_controls(
    *,
    name: str | None = None,
    control_type: str | None = None,
    enabled: bool | None = None,
    visible: bool | None = None,
    max_windows: int = 20,
) -> dict[str, Any]:
    """Inspect and exact-match accessible controls without acting on them."""
    windows = inspect_windows(max_windows)
    return find_controls(
        windows,
        name=name,
        control_type=control_type,
        enabled=enabled,
        visible=visible,
    )


def read_control(selector: dict[str, Any]) -> dict[str, Any]:
    """Read one uniquely identified, non-sensitive control and verify its text."""
    validate_focus_selector(selector)
    if (
        "password" in selector["name"].casefold()
        or "password" in selector["control_type"].casefold()
    ):
        return {
            "status": "failed",
            "verified": False,
            "text": "",
            "reason": "password controls cannot be read by this adapter",
        }
    caps = capabilities()
    if not caps.available:
        return {"status": "failed", "verified": False, "text": "", "reason": caps.reason}
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(
            title=selector["window_name"], visible_only=True, top_level_only=True
        )
        if len(windows) != 1:
            status = "ambiguous" if windows else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status, "window_changed"),
                "verified": False,
                "text": "",
                "reason": "window selector did not identify exactly one window",
            }
        candidates = []
        for control in windows[0].descendants()[:100]:
            info = control.element_info
            if str(info.control_type or "") != selector["control_type"]:
                continue
            if str(info.name or "") != selector["name"]:
                continue
            if selector.get("automation_id") and (
                str(info.automation_id or "") != selector["automation_id"]
            ):
                continue
            candidates.append(control)
        if len(candidates) != 1:
            status = "ambiguous" if candidates else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status),
                "verified": False,
                "text": "",
                "reason": "control selector did not identify exactly one control",
            }
        control = candidates[0]
        if _is_password_control(control):
            return {
                "status": "failed",
                "verified": False,
                "text": "",
                "reason": "password controls cannot be read by this adapter",
            }
        if not control.is_visible():
            return {
                "status": "failed",
                "verified": False,
                "text": "",
                "reason": "control is not visible",
            }
        text = _safe_text(control)
        return {
            "status": "done",
            "verified": True,
            "text": text,
            "reason": "control text was read from the live UIA element",
        }
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        return {
            "status": "failed",
            "recovery": "state_unreadable",
            "verified": False,
            "text": "",
            "reason": f"UI Automation failed: {type(exc).__name__}",
        }


def focus_control(selector: dict[str, Any]) -> dict[str, Any]:
    """Focus one uniquely identified non-sensitive control and verify focus."""
    validate_focus_selector(selector)
    window_name = selector["window_name"]
    control_name = selector["name"]
    control_type = selector["control_type"]
    automation_id = selector.get("automation_id", "")
    if "password" in control_type.casefold() or "password" in control_name.casefold():
        return {
            "status": "failed",
            "verified": False,
            "reason": "password controls cannot be focused by this adapter",
        }

    caps = capabilities()
    if not caps.available:
        return {
            "status": "failed",
            "verified": False,
            "reason": caps.reason,
        }
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(
            title=window_name, visible_only=True, top_level_only=True
        )
        if len(windows) != 1:
            status = "ambiguous" if windows else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status, "window_changed"),
                "verified": False,
                "reason": "window selector did not identify exactly one window",
            }
        candidates = []
        for control in windows[0].descendants()[:100]:
            info = control.element_info
            if str(info.control_type or "") != control_type:
                continue
            if str(info.name or "") != control_name:
                continue
            if automation_id and str(info.automation_id or "") != automation_id:
                continue
            candidates.append(control)
        if len(candidates) != 1:
            status = "ambiguous" if candidates else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status),
                "verified": False,
                "reason": "control selector did not identify exactly one control",
            }
        control = candidates[0]
        if _is_password_control(control):
            return {
                "status": "failed",
                "verified": False,
                "reason": "password controls cannot be focused by this adapter",
            }
        if not control.is_visible() or not control.is_enabled():
            return {
                "status": "failed",
                "verified": False,
                "reason": "control is not visible and enabled",
            }
        control.set_focus()
        verified = _has_focus(control)
        return {
            "status": "done" if verified else "unverified",
            "recovery": None if verified else "focus_lost",
            "verified": verified,
            "reason": "focus state was read back" if verified else
            "focus state could not be verified",
        }
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        return {
            "status": "failed",
            "recovery": "state_unreadable",
            "verified": False,
            "reason": f"UI Automation failed: {type(exc).__name__}",
        }


def activate_window(window_name: str) -> dict[str, Any]:
    """Activate one visible window and verify that it owns keyboard focus."""
    if not isinstance(window_name, str) or not window_name.strip():
        raise ValueError("window name must be non-empty text")
    if len(window_name) > 300:
        raise ValueError("window name must contain at most 300 characters")
    if platform.system() != "Windows":
        return {
            "status": "failed",
            "verified": False,
            "reason": "Windows UI Automation is the only supported adapter.",
        }
    caps = capabilities()
    if not caps.available:
        return {"status": "failed", "verified": False, "reason": caps.reason}
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(
            title=window_name.strip(), visible_only=True, top_level_only=True
        )
        if len(windows) != 1:
            status = "ambiguous" if windows else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status, "window_changed"),
                "verified": False,
                "reason": "window selector did not identify exactly one window",
            }
        window = windows[0]
        if not window.is_visible() or not window.is_enabled():
            return {
                "status": "failed",
                "verified": False,
                "reason": "window is not visible and enabled",
            }
        window.set_focus()
        verified = _has_focus(window)
        return {
            "status": "done" if verified else "unverified",
            "recovery": None if verified else "state_unreadable",
            "verified": verified,
            "reason": "window focus was read back" if verified
            else "window focus could not be verified",
        }
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        return {
            "status": "failed",
            "recovery": "state_unreadable",
            "verified": False,
            "reason": f"UI Automation failed: {type(exc).__name__}",
        }


def write_control(selector: dict[str, Any], text: str) -> dict[str, Any]:
    """Write and read back one uniquely identified, non-sensitive edit."""
    validate_focus_selector(selector)
    if not isinstance(text, str):
        raise ValueError("text must be text")
    if len(text) > 10_000:
        raise ValueError("text must contain at most 10000 characters")
    if selector["control_type"].casefold() not in {"edit", "document"}:
        return {
            "status": "failed",
            "verified": False,
            "reason": "only Edit or Document controls may receive UIA text",
        }
    if (
        "password" in selector["name"].casefold()
        or "password" in selector["control_type"].casefold()
    ):
        return {
            "status": "failed",
            "verified": False,
            "reason": "password controls cannot receive UIA text",
        }
    caps = capabilities()
    if not caps.available:
        return {"status": "failed", "verified": False, "reason": caps.reason}
    effect_started = False
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(
            title=selector["window_name"], visible_only=True, top_level_only=True
        )
        if len(windows) != 1:
            status = "ambiguous" if windows else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status, "window_changed"),
                "verified": False,
                "reason": "window selector did not identify exactly one window",
            }
        candidates = []
        for control in windows[0].descendants()[:100]:
            info = control.element_info
            if str(info.control_type or "") != selector["control_type"]:
                continue
            if str(info.name or "") != selector["name"]:
                continue
            if selector.get("automation_id") and (
                str(info.automation_id or "") != selector["automation_id"]
            ):
                continue
            candidates.append(control)
        if len(candidates) != 1:
            status = "ambiguous" if candidates else "not_found"
            return {
                "status": status,
                "recovery": _selection_recovery(status),
                "verified": False,
                "reason": "control selector did not identify exactly one control",
            }
        control = candidates[0]
        if _is_password_control(control):
            return {
                "status": "failed",
                "verified": False,
                "reason": "password controls cannot receive UIA text",
            }
        if not control.is_visible() or not control.is_enabled():
            return {
                "status": "failed",
                "verified": False,
                "reason": "control is not visible and enabled",
            }
        setter = getattr(control, "set_edit_text", None)
        if not callable(setter):
            return {
                "status": "failed",
                "verified": False,
                "reason": "UIA edit value setter is unavailable",
            }
        effect_started = True
        setter(text)
        readback = _safe_text(control, max_length=10_000)
        verified = readback == text
        return {
            "status": "done" if verified else "unverified",
            "recovery": None if verified else "effect_ambiguous",
            "verified": verified,
            "reason": "text was read back exactly" if verified
            else "text readback did not match",
        }
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        return {
            "status": "unverified" if effect_started else "failed",
            "recovery": (
                "effect_ambiguous" if effect_started else "state_unreadable"
            ),
            "verified": False,
            "reason": f"UI Automation failed: {type(exc).__name__}",
        }


def invoke_control(selector: dict[str, Any]) -> dict[str, Any]:
    """Invoke one uniquely identified semantic control and verify a transition."""
    validate_focus_selector(selector)
    allowed_types = {
        "button", "hyperlink", "listitem", "menuitem", "tabitem",
        "checkbox", "radiobutton",
    }
    if selector["control_type"].casefold() not in allowed_types:
        return {
            "status": "failed",
            "verified": False,
            "reason": "control type does not expose a safe invoke action",
        }
    if "password" in selector["name"].casefold():
        return {
            "status": "failed",
            "verified": False,
            "reason": "password controls cannot be invoked by this adapter",
        }
    caps = capabilities()
    if not caps.available:
        return {"status": "failed", "verified": False, "reason": caps.reason}

    def locate(desktop: Any) -> tuple[str, Any, Any] | None:
        windows = desktop.windows(
            title=selector["window_name"], visible_only=True, top_level_only=True
        )
        if len(windows) != 1:
            return (
                "ambiguous" if windows else "not_found",
                None,
                None,
            )
        matches = []
        for control in windows[0].descendants()[:100]:
            info = control.element_info
            if str(info.control_type or "") != selector["control_type"]:
                continue
            if str(info.name or "") != selector["name"]:
                continue
            if selector.get("automation_id") and (
                str(info.automation_id or "") != selector["automation_id"]
            ):
                continue
            matches.append(control)
        if len(matches) != 1:
            return (
                "ambiguous" if matches else "not_found",
                windows[0],
                None,
            )
        return "found", windows[0], matches[0]

    effect_started = False
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        status, window, control = locate(desktop)
        if status != "found":
            return {
                "status": status,
                "recovery": (
                    "window_changed"
                    if window is None and status != "ambiguous"
                    else _selection_recovery(status)
                ),
                "verified": False,
                "reason": "control selector did not identify exactly one control",
            }
        if _is_password_control(control):
            return {
                "status": "failed",
                "verified": False,
                "reason": "password controls cannot be invoked by this adapter",
            }
        if not control.is_visible() or not control.is_enabled():
            return {
                "status": "failed",
                "verified": False,
                "reason": "control is not visible and enabled",
            }
        try:
            window_has_focus = _has_focus(window)
        except (AttributeError, RuntimeError, TypeError, OSError, COMError):
            return {
                "status": "failed",
                "verified": False,
                "reason": "window focus could not be verified before invoke",
            }
        if not window_has_focus:
            return {
                "status": "unverified",
                "recovery": "focus_lost",
                "verified": False,
                "reason": "window lost focus before invoke; no action was sent",
            }
        invoker = getattr(control, "invoke", None)
        if not callable(invoker):
            return {
                "status": "failed",
                "verified": False,
                "reason": "UIA invoke pattern is unavailable",
            }
        before = _control_record(control)
        effect_started = True
        invoker()
        import time
        time.sleep(0.2)
        after = locate(desktop)
        if after is None or after[0] == "not_found":
            if after is not None and after[1] is None:
                return {
                    "status": "unverified",
                    "recovery": "window_changed",
                    "verified": False,
                    "reason": "window disappeared after invoke; the control "
                    "transition could not be verified",
                }
            return {
                "status": "done",
                "verified": True,
                "reason": "control transition was verified because the target "
                "was no longer present",
            }
        if after[0] == "ambiguous":
            return {
                "status": "unverified",
                "recovery": "target_ambiguous",
                "verified": False,
                "reason": "control became ambiguous after invoke",
            }
        after_record = _control_record(after[2])
        changed = before != after_record
        return {
            "status": "done" if changed else "unverified",
            "recovery": None if changed else "effect_ambiguous",
            "verified": changed,
            "reason": "control state changed after invoke" if changed
            else "invoke completed but no observable control transition was read",
        }
    except (
        ImportError, AttributeError, RuntimeError, TypeError, OSError, COMError
    ) as exc:
        return {
            "status": "unverified" if effect_started else "failed",
            "recovery": (
                "effect_ambiguous" if effect_started else "state_unreadable"
            ),
            "verified": False,
            "reason": f"UI Automation failed: {type(exc).__name__}",
        }


def validate_focus_selector(selector: dict[str, Any]) -> None:
    """Validate a focus selector without importing or querying UI Automation."""
    if not isinstance(selector, dict):
        raise ValueError("selector must be an object")
    window_name = selector.get("window_name")
    control_name = selector.get("name")
    control_type = selector.get("control_type")
    automation_id = selector.get("automation_id", "")
    if not all(isinstance(value, str) for value in (
        window_name, control_name, control_type, automation_id,
    )):
        raise ValueError("selector fields must be text")
    if not window_name.strip() or not control_type.strip():
        raise ValueError("selector needs a window name and control type")
    if len(window_name) > 300 or len(control_name) > 300:
        raise ValueError("window and control names must contain at most 300 characters")
    if len(control_type) > 100:
        raise ValueError("control type must contain at most 100 characters")
    if len(automation_id) > 200:
        raise ValueError("automation id must contain at most 200 characters")
