from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from google.genai import types

from actions import computer_control
from core import tool_audit


class ComputerInspectionTests(unittest.TestCase):
    def test_tool_schema_is_valid_for_gemini_live_config(self) -> None:
        tool = computer_control.TOOL
        declaration = {
            key: tool[key]
            for key in ("name", "description", "parameters")
        }

        config = types.LiveConnectConfig(
            tools=[{"function_declarations": [declaration]}]
        )

        properties = config.tools[0].function_declarations[0].parameters.properties
        self.assertIn("name", properties)
        self.assertIn("control_type", properties)
        self.assertIn("enabled", properties)
        self.assertIn("visible", properties)
        self.assertIn("window_name", properties["selector"].properties)

    def test_unknown_action_fails_instead_of_returning_success_shaped_text(self) -> None:
        result = computer_control.computer_control(
            {"action": "not_supported"}
        )

        self.assertIn("status=failed", result)
        self.assertNotIn("done", result)

    def test_non_object_parameters_are_rejected(self) -> None:
        result = computer_control.computer_control(["not", "an", "object"])

        self.assertIn("status=failed", result)

    def test_inspect_windows_is_bounded_read_only_and_verified(self) -> None:
        fake_windows = [{"name": "Synthetic", "controls": []}]
        with patch.object(
            computer_control.ui_adapter, "inspect_windows",
            return_value=fake_windows,
        ) as inspect, patch.object(
            computer_control.ui_adapter,
            "capabilities",
            return_value=type("Caps", (), {"available": True})(),
        ):
            result = computer_control.computer_control({
                "action": "inspect_windows",
                "limit": 3,
            })

        payload = json.loads(result)
        self.assertEqual(payload["status"], "done")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["windows"], fake_windows)
        inspect.assert_called_once_with(3)

    def test_inspect_windows_rejects_unbounded_limit(self) -> None:
        result = computer_control.computer_control({
            "action": "inspect_windows",
            "limit": 51,
        })

        self.assertIn("failed", result.lower())

    def test_inspect_windows_has_read_only_risk(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control", {"action": "inspect_windows"}
            ),
            "read_or_navigate",
        )
