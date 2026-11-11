from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import computer_control
from core import tool_audit, ui_adapter


class ComputerControlReadTests(unittest.TestCase):
    def test_read_control_returns_live_text_without_confirmation(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Subject",
            "control_type": "Text",
            "automation_id": "subject",
        }
        with patch.object(
            computer_control.ui_adapter,
            "capabilities",
            return_value=type("Caps", (), {"available": True})(),
        ), patch.object(
            computer_control.ui_adapter,
            "read_control",
            return_value={
                "status": "done",
                "verified": True,
                "text": "Steam sale",
            },
        ) as read:
            result = computer_control.computer_control({
                "action": "read_control",
                "selector": selector,
            })

        payload = json.loads(result)
        self.assertEqual(payload["text"], "Steam sale")
        self.assertTrue(payload["verified"])
        read.assert_called_once_with(selector)

    def test_read_control_rejects_password_selector(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Password",
            "control_type": "Edit",
        }
        result = ui_adapter.read_control(selector)
        self.assertEqual(result["status"], "failed")
        self.assertIn("password", result["reason"])

    def test_read_control_is_read_only(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control", {"action": "read_control"}
            ),
            "read_or_navigate",
        )
