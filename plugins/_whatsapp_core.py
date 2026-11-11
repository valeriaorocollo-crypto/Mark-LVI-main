"""Fail-closed WhatsApp Desktop adapter using verified Windows UI Automation."""
from __future__ import annotations

import ctypes
import platform
import re
import time
import unicodedata
from collections import deque
from typing import Any


_MAX_CONTROLS = 500
_MAX_DEPTH = 10
_MAX_RAW_CONTROLS = 5_000
_MAX_RAW_REPEAT = 48
_WINDOW_TIMEOUT = 20.0
_SEARCH_TIMEOUT = 5.0
_SEND_TIMEOUT = 8.0


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).strip()


def _unique_controls(controls) -> list[Any]:
    unique = []
    seen = set()
    for control in controls:
        runtime_id = _control_runtime_id(control)
        if runtime_id is None:
            unique.append(control)
            continue
        if runtime_id in seen:
            continue
        seen.add(runtime_id)
        unique.append(control)
    return unique


def _control_runtime_id(control) -> tuple[int, ...] | None:
    try:
        return tuple(control.element_info.element.GetRuntimeId())
    except Exception:
        return None


def _window_controls(
    window, recipient: str | None = None, message: str | None = None,
) -> list[Any]:
    controls = window.descendants(control_type="Edit")
    if recipient:
        controls.extend(window.descendants(title=recipient))
    if message:
        controls.extend(
            window.descendants(title=message, control_type="Text")
        )
    return _unique_controls(controls)[:_MAX_CONTROLS]


def _is_whatsapp_title(title: str) -> bool:
    return re.fullmatch(
        r"\s*(?:\(\d+\)\s*)?whatsapp\s*",
        title,
        flags=re.IGNORECASE,
    ) is not None


def _visible_windows():
    from pywinauto import Desktop

    win32 = Desktop(backend="win32")
    uia = Desktop(backend="uia")
    return [
        uia.window(handle=window.handle)
        for window in win32.windows(
            visible_only=True, top_level_only=True
        )
        if _is_whatsapp_title(window.window_text())
    ]


def _connect_window():
    if platform.system() != "Windows":
        return None, "verified WhatsApp Desktop automation is currently Windows-only"

    try:
        windows = _visible_windows()
    except Exception as error:
        return None, (
            "WhatsApp's accessible window could not be inspected "
            f"({type(error).__name__})"
        )

    if not windows:
        from actions.open_app import open_app

        result = open_app({"app_name": "WhatsApp"})
        if "status=failed" in result or "status=unverified" in result:
            return None, "WhatsApp could not be opened or brought to the front"

        deadline = time.monotonic() + _WINDOW_TIMEOUT
        while time.monotonic() < deadline:
            try:
                windows = _visible_windows()
            except Exception:
                windows = []
            if windows:
                break
            time.sleep(0.25)

    if not windows:
        return None, (
            "WhatsApp did not expose a visible desktop window after opening; "
            "no message was sent"
        )

    accessible = []
    for candidate in windows:
        try:
            controls = _window_controls(candidate)
            search, _ = _search_field(controls)
        except Exception:
            continue
        if search is not None:
            accessible.append((candidate, controls))
    if not accessible:
        return None, (
            "WhatsApp is open, but no visible window exposes one accessible "
            "chat search field; no message was sent"
        )
    unique_accessible = []
    seen_search_controls = set()
    for candidate, controls in accessible:
        search, _ = _search_field(controls)
        runtime_id = _control_runtime_id(search)
        if runtime_id is not None and runtime_id in seen_search_controls:
            continue
        if runtime_id is not None:
            seen_search_controls.add(runtime_id)
        unique_accessible.append((candidate, controls))
    if len(unique_accessible) != 1:
        return None, (
            "more than one WhatsApp window exposes chat search; "
            "cannot identify the intended session"
        )

    window, _ = unique_accessible[0]
    try:
        if not _bring_to_front(window):
            return None, "WhatsApp could not be brought to the foreground"
        controls = _window_controls(window)
    except Exception as error:
        return None, (
            "WhatsApp's accessible controls could not be read "
            f"({type(error).__name__})"
        )
    return (window, controls), ""


def _bring_to_front(window) -> bool:
    def wait_until_active() -> bool:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                if window.is_active():
                    return True
            except Exception:
                return False
            time.sleep(0.05)
        return False

    try:
        window.set_focus()
        if wait_until_active():
            return True
    except Exception:
        pass
    if platform.system() != "Windows":
        return False
    try:
        if not ctypes.windll.user32.SetForegroundWindow(int(window.handle)):
            return False
        return wait_until_active()
    except Exception:
        return False


def _control_identity(control) -> tuple[str, str, str]:
    info = control.element_info
    return (
        str(info.control_type or ""),
        str(info.name or "").strip(),
        str(info.automation_id or "").strip(),
    )


def _one_control(controls, predicate, label: str):
    matches = [control for control in controls if predicate(*_control_identity(control))]
    if len(matches) != 1:
        return None, (
            f"WhatsApp must expose exactly one accessible {label}; "
            f"found {len(matches)}. No message was sent"
        )
    return matches[0], ""


def _edit_text(control, text: str, *, keyboard_first: bool = False) -> bool:
    setter = getattr(control, "set_edit_text", None)
    getter = getattr(control, "get_value", None)
    if not callable(getter):
        return False
    if keyboard_first:
        return _type_unicode_into_control(control, text)
    if callable(setter):
        try:
            setter(text)
            if _wait_for_value(getter, text):
                return True
        except Exception:
            pass
    return _type_unicode_into_control(control, text)


def _wait_for_value(getter, expected: str) -> bool:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            if str(getter() or "") == expected:
                return True
        except Exception:
            return False
        time.sleep(0.05)
    return False


def _send_unicode(text: str) -> bool:
    if platform.system() != "Windows":
        return False

    class _KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("virtual_key", ctypes.c_ushort),
            ("scan_code", ctypes.c_ushort),
            ("flags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("extra_info", ctypes.c_size_t),
        ]

    class _InputUnion(ctypes.Union):
        _fields_ = [
            ("keyboard", _KeyboardInput),
            # Windows sizes INPUT's union for its larger MOUSEINPUT member.
            (
                "padding",
                ctypes.c_byte
                * (32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24),
            ),
        ]

    class _Input(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_ulong), ("value", _InputUnion)]

    encoded = text.encode("utf-16-le")
    units = [
        encoded[index] | (encoded[index + 1] << 8)
        for index in range(0, len(encoded), 2)
    ]
    events = []
    for unit in units:
        events.append(_Input(
            1, _InputUnion(_KeyboardInput(0, unit, 0x0004, 0, 0))
        ))
        events.append(_Input(
            1, _InputUnion(_KeyboardInput(0, unit, 0x0006, 0, 0))
        ))
    if not events:
        return True

    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = (
        ctypes.c_uint, ctypes.POINTER(_Input), ctypes.c_int
    )
    user32.SendInput.restype = ctypes.c_uint
    sent = user32.SendInput(
        len(events), (_Input * len(events))(*events), ctypes.sizeof(_Input)
    )
    return sent == len(events)


def _type_unicode_into_control(control, text: str) -> bool:
    getter = getattr(control, "get_value", None)
    focus = getattr(control, "set_focus", None)
    top_level = getattr(control, "top_level_parent", None)
    if not callable(getter) or not callable(focus) or not callable(top_level):
        return False
    try:
        focus()
        window = top_level()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if (
                bool(control.element_info.element.CurrentHasKeyboardFocus)
                and window.is_active()
            ):
                break
            time.sleep(0.05)
        else:
            return False

        import pyautogui

        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        normalized = text.replace("\r\n", "\n")
        if "\r" in normalized:
            return False
        lines = normalized.split("\n")
        for index, line in enumerate(lines):
            if line and not _send_unicode(line):
                return False
            if index < len(lines) - 1:
                pyautogui.hotkey("shift", "enter")
        return _wait_for_value(getter, text)
    except Exception:
        return False


def _search_field(controls):
    def is_search(kind: str, name: str, automation_id: str) -> bool:
        identity = _fold(f"{name} {automation_id}")
        return kind == "Edit" and (
            any(
                token in identity
                for token in (
                    "buscar un chat",
                    "search chats",
                    "search or start new chat",
                    "chat search",
                )
            )
            or automation_id in {"_r_c_", "_r_e_"}
        )

    return _one_control(controls, is_search, "chat search field")


def _composer(controls):
    def is_composer(kind: str, name: str, automation_id: str) -> bool:
        identity = _fold(f"{name} {automation_id}")
        return kind in {"Edit", "Document"} and any(
            token in identity
            for token in (
                "escribe un mensaje",
                "escribir un mensaje",
                "type a message",
                "message input",
            )
        )

    return _one_control(controls, is_composer, "message composer")


def _same_name(candidate: str, expected: str) -> bool:
    return _fold(candidate) == _fold(expected)


def _phone_digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _same_recipient(candidate: str, expected: str) -> bool:
    if _same_name(candidate, expected):
        return True
    expected_digits = _phone_digits(expected)
    candidate_number = re.match(r"\s*(\+?\d[\d\s().-]*\d)", candidate)
    if len(expected_digits) < 9 or candidate_number is None:
        return False
    candidate_digits = _phone_digits(candidate_number.group(1))
    return (
        candidate_digits == expected_digits
        or candidate_digits.endswith(expected_digits)
    )


def _recipient_header_name(control, receiver: str) -> str | None:
    kind, name, _ = _control_identity(control)
    if kind in {"ListItem", "Button"}:
        return name if _same_recipient(name, receiver) else None
    if kind != "DataItem":
        return None
    displayed_name = name.partition(":")[0].strip()
    if _same_recipient(displayed_name, receiver):
        phone_number = re.match(
            r"\s*(\+?\d[\d\s().-]*\d)", displayed_name
        )
        return phone_number.group(1).strip() if phone_number else displayed_name
    if _name_starts_at_boundary(displayed_name, receiver):
        return receiver
    return None


def _recipient_items(controls, receiver: str):
    matches = []
    for control in controls:
        kind, name, _ = _control_identity(control)
        if kind in {"ListItem", "Button"} and _same_recipient(name, receiver):
            matches.append(control)
            continue
        if kind != "DataItem":
            continue
        displayed_name = name.partition(":")[0].strip()
        if not _same_recipient(displayed_name, receiver):
            continue
        parent = getattr(control, "parent", None)
        try:
            parent_control = parent() if callable(parent) else None
        except Exception:
            continue
        if parent_control is not None and _control_identity(parent_control)[0] == "DataGrid":
            matches.append(control)
    return matches


def _name_starts_at_boundary(candidate: str, expected: str) -> bool:
    candidate = _fold(candidate)
    expected = _fold(expected)
    return candidate.startswith(expected) and (
        len(candidate) == len(expected)
        or not candidate[len(expected)].isalnum()
    )


def _raw_recipient_items(window, search, receiver: str):
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo

    ui = IUIA().iuia
    raw_walker = ui.RawViewWalker
    search_rect = search.rectangle()
    list_root = search.element_info.element
    for _ in range(20):
        bounds = list_root.CurrentBoundingRectangle
        if (
            int(list_root.CurrentControlType) == 50026
            and bounds.left < search_rect.left
            and bounds.right >= search_rect.right
            and bounds.bottom > search_rect.bottom + 100
        ):
            break
        list_root = raw_walker.GetParentElement(list_root)
        if list_root is None:
            raise RuntimeError("WhatsApp's chat-list accessibility root was not found")
    else:
        raise RuntimeError("WhatsApp's chat-list accessibility root was not found")

    condition = ui.CreatePropertyCondition(30003, 50029)
    walker = ui.CreateTreeWalker(condition)
    item = walker.GetFirstChildElement(list_root)
    matches = {}
    seen = set()
    repeated = 0
    steps = 0
    window_rect = window.rectangle()
    while item is not None and steps < _MAX_RAW_CONTROLS:
        steps += 1
        runtime_id = tuple(item.GetRuntimeId())
        if runtime_id in seen:
            repeated += 1
        else:
            repeated = 0
            seen.add(runtime_id)
            name = str(item.CurrentName or "").strip()
            bounds = item.CurrentBoundingRectangle
            if (
                (
                    _name_starts_at_boundary(name, receiver)
                    or _same_recipient(name, receiver)
                )
                and not bool(item.CurrentIsOffscreen)
                and bounds.left < search_rect.right
                and bounds.right > search_rect.left
                and bounds.top >= search_rect.bottom
                and bounds.bottom > window_rect.top
                and bounds.top < window_rect.bottom
                and bounds.right > bounds.left
                and bounds.bottom > bounds.top
            ):
                matches.setdefault(
                    runtime_id,
                    (UIAWrapper(UIAElementInfo(item)), bounds),
                )
        item = walker.GetNextSiblingElement(item)
        if repeated >= _MAX_RAW_REPEAT:
            break

    if item is not None and steps >= _MAX_RAW_CONTROLS:
        raise RuntimeError("WhatsApp's chat-list results exceeded the scan limit")

    clusters = []
    for wrapper, bounds in matches.values():
        overlapping = next(
            (
                cluster for cluster in clusters
                if max(bounds.top, cluster["top"])
                < min(bounds.bottom, cluster["bottom"])
            ),
            None,
        )
        if overlapping is None:
            clusters.append({
                "top": bounds.top,
                "bottom": bounds.bottom,
                "items": [(wrapper, bounds)],
            })
        else:
            overlapping["top"] = min(overlapping["top"], bounds.top)
            overlapping["bottom"] = max(overlapping["bottom"], bounds.bottom)
            overlapping["items"].append((wrapper, bounds))

    return [
        min(
            cluster["items"],
            key=lambda item_and_bounds: (
                (item_and_bounds[1].right - item_and_bounds[1].left)
                * (item_and_bounds[1].bottom - item_and_bounds[1].top)
            ),
        )[0]
        for cluster in clusters
    ]


def _conversation_header(controls, receiver: str):
    return [
        control
        for control in controls
        if _control_identity(control)[0] in {"Text", "Group", "Button"}
        and _same_name(_control_identity(control)[1], receiver)
    ]


class WhatsAppDesktop:
    def __init__(self, window, controls) -> None:
        self.window = window
        self.controls = controls

    def _refresh(
        self, recipient: str | None = None, message: str | None = None,
    ) -> bool:
        try:
            active = self.window.is_active()
        except Exception:
            active = False
        if not active and not _bring_to_front(self.window):
            return False
        try:
            if not self.window.is_active():
                return False
            self.controls = _window_controls(
                self.window, recipient=recipient, message=message
            )
            return True
        except Exception:
            return False

    def prepare_recipient(self, receiver: str) -> tuple[str | None, str]:
        if not self._refresh():
            return None, "WhatsApp lost focus or its controls became unreadable"

        search, error = _search_field(self.controls)
        if search is None:
            return None, error
        if not _edit_text(search, receiver, keyboard_first=True):
            return None, (
                "WhatsApp did not accept and verify the exact recipient search; "
                "no message was sent"
            )

        deadline = time.monotonic() + _SEARCH_TIMEOUT
        recipient_item = None
        raw_search_at = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            if not self._refresh():
                return None, "WhatsApp lost focus while searching; no message was sent"
            matches = _recipient_items(self.controls, receiver)
            if not matches and time.monotonic() >= raw_search_at:
                try:
                    matches = _raw_recipient_items(
                        self.window, search, receiver
                    )
                except Exception as error:
                    return None, (
                        "WhatsApp's accessible search result could not be "
                        f"verified ({type(error).__name__}); no message was sent"
                    )
                raw_search_at = time.monotonic() + 0.8
            if len(matches) > 1:
                return None, (
                    "multiple WhatsApp chats have that exact displayed name; "
                    "no message was sent"
                )
            if len(matches) == 1:
                recipient_item = matches[0]
                break
            time.sleep(0.2)
        if recipient_item is None:
            return None, (
                "WhatsApp did not show one exact recipient match; "
                "no message was sent"
            )

        expected_header = _recipient_header_name(recipient_item, receiver)
        if expected_header is None:
            return None, (
                "WhatsApp's exact search result could not be tied to a "
                "unique conversation header; no message was sent"
            )
        try:
            recipient_item.click_input()
        except Exception:
            return None, "the exact WhatsApp chat could not be opened"

        deadline = time.monotonic() + _SEARCH_TIMEOUT
        while time.monotonic() < deadline:
            if not self._refresh(recipient=expected_header):
                return None, "WhatsApp lost focus after opening the chat"
            headers = _conversation_header(self.controls, expected_header)
            composer, composer_error = _composer(self.controls)
            if len(headers) == 1 and composer is not None:
                self._prepared_receiver = receiver
                self._prepared_header = _control_identity(headers[0])[1]
                return self._prepared_header, ""
            if len(headers) > 1:
                return None, (
                    "the open WhatsApp conversation header is ambiguous; "
                    "no message was sent"
                )
            time.sleep(0.2)
        if composer is None:
            return None, composer_error
        return None, (
            "the open WhatsApp conversation header does not uniquely match "
            "the requested recipient; no message was sent"
        )

    def send_prepared_message(
        self, receiver: str, message: str
    ) -> tuple[bool | None, str]:
        expected_header = getattr(self, "_prepared_header", "")
        if not self._refresh(recipient=expected_header):
            return False, "WhatsApp lost focus or its controls became unreadable"
        if not _same_name(getattr(self, "_prepared_receiver", ""), receiver):
            return False, (
                "the requested WhatsApp conversation was not prepared; "
                "no message was sent"
            )
        headers = _conversation_header(self.controls, expected_header)
        if len(headers) != 1:
            return False, (
                "the open WhatsApp conversation header does not uniquely "
                "match the requested recipient; no message was sent"
            )
        composer, error = _composer(self.controls)
        if composer is None:
            return False, error
        before = sum(
            1 for control in self.controls
            if _control_identity(control)[0] == "Text"
            and _control_identity(control)[1] == message
        )
        if not _edit_text(composer, message, keyboard_first=True):
            return False, (
                "WhatsApp did not accept and verify the exact message text; "
                "no message was sent"
            )

        try:
            composer.set_focus()
            if not bool(composer.element_info.element.CurrentHasKeyboardFocus):
                return False, (
                    "the verified message composer did not retain keyboard focus; "
                    "no message was sent"
                )
        except Exception:
            return False, (
                "the message composer focus could not be verified; "
                "no message was sent"
            )

        import pyautogui

        try:
            pyautogui.press("enter")
        except Exception as error:
            return None, (
                "WhatsApp's send keystroke raised "
                f"{type(error).__name__}; whether it sent is unknown"
            )
        deadline = time.monotonic() + _SEND_TIMEOUT
        while time.monotonic() < deadline:
            if not self._refresh(
                recipient=expected_header, message=message
            ):
                return None, "WhatsApp became unreadable after the send request"
            sent_count = sum(
                1 for control in self.controls
                if _control_identity(control)[0] == "Text"
                and _control_identity(control)[1] == message
            )
            if sent_count > before:
                return True, ""
            time.sleep(0.2)
        return None, (
            "WhatsApp did not visibly confirm the message in the intended chat; "
            "the send outcome is unknown, do not retry automatically"
        )

    def send_message_to(
        self, receiver: str, message: str
    ) -> tuple[bool | None, str]:
        prepared_receiver, error = self.prepare_recipient(receiver)
        if prepared_receiver is None:
            return False, error
        return self.send_prepared_message(receiver, message)


def get():
    connected, reason = _connect_window()
    if connected is None:
        return None, reason
    window, controls = connected
    transport = WhatsAppDesktop(window, controls)
    return transport, ""
