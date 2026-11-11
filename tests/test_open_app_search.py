from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

from actions import open_app


class _Edit:
    def __init__(self, automation_id: str = "SearchTextBox") -> None:
        self.element_info = types.SimpleNamespace(
            control_type="Edit", automation_id=automation_id
        )
        self.value = ""

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def set_edit_text(self, value: str) -> None:
        self.value = value

    def get_value(self) -> str:
        return self.value


class _Window:
    def __init__(self, controls: list[_Edit]) -> None:
        self.controls = controls
        self.element_info = types.SimpleNamespace(
            element=types.SimpleNamespace(CurrentHasKeyboardFocus=True)
        )

    def descendants(self) -> list[_Edit]:
        return self.controls


class OpenAppSearchTests(unittest.TestCase):
    def _run_search(self, controls: list[_Edit]) -> tuple[bool, Mock, Mock]:
        keyboard = types.SimpleNamespace(
            hotkey=Mock(),
            press=Mock(),
            write=Mock(),
        )
        desktop = Mock()
        desktop.return_value.windows.return_value = [_Window(controls)]
        pywinauto = types.SimpleNamespace(Desktop=desktop)
        with (
            patch.object(open_app, "_PYAUTOGUI", True),
            patch.object(open_app, "_SYSTEM", "Windows"),
            patch.object(open_app, "pyautogui", keyboard),
            patch("actions.open_app.time.sleep"),
            patch.dict(sys.modules, {"pywinauto": pywinauto}),
        ):
            result = open_app._desktop_search("Spotify")
        return result, keyboard, desktop

    def test_windows_search_uses_verified_ui_automation_edit(self) -> None:
        field = _Edit()

        result, keyboard, desktop = self._run_search([field])

        self.assertTrue(result)
        keyboard.hotkey.assert_called_once_with("win", "s")
        keyboard.press.assert_called_once_with("enter")
        keyboard.write.assert_not_called()
        desktop.assert_called_once_with(backend="uia")
        self.assertEqual(field.value, "Spotify")

    def test_windows_search_does_not_type_into_ambiguous_controls(self) -> None:
        fields = [_Edit(), _Edit()]

        result, keyboard, _ = self._run_search(fields)

        self.assertFalse(result)
        keyboard.press.assert_not_called()
        self.assertEqual([field.value for field in fields], ["", ""])

    def test_windows_search_ignores_an_unrelated_edit_control(self) -> None:
        field = _Edit(automation_id="view_1012")

        result, keyboard, _ = self._run_search([field])

        self.assertFalse(result)
        keyboard.press.assert_not_called()
        self.assertEqual(field.value, "")

    def test_windows_search_does_not_submit_unverified_query(self) -> None:
        field = _Edit()
        field.get_value = Mock(return_value="different query")

        result, keyboard, _ = self._run_search([field])

        self.assertFalse(result)
        keyboard.press.assert_not_called()


if __name__ == "__main__":
    unittest.main()
