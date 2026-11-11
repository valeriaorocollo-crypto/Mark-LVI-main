from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from actions import computer_control
from core import tool_audit, ui_adapter


class ComputerControlDiscoveryTests(unittest.TestCase):
    def test_exact_control_discovery_is_read_only(self) -> None:
        expected = {
            "status": "found",
            "ambiguous": False,
            "matches": [{"selector": {"name": "Search"}}],
        }
        with patch.object(
            computer_control.ui_adapter,
            "capabilities",
            return_value=type("Caps", (), {"available": True})(),
        ), patch.object(
            computer_control.ui_adapter,
            "inspect_controls",
            return_value=expected,
        ) as inspect:
            result = computer_control.computer_control({
                "action": "inspect_controls",
                "name": "Search",
                "control_type": "Edit",
            })

        payload = json.loads(result)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["result"], expected)
        inspect.assert_called_once_with(
            name="Search",
            control_type="Edit",
            enabled=None,
            visible=None,
            max_windows=20,
        )

    def test_discovery_rejects_empty_criteria(self) -> None:
        result = computer_control.computer_control({
            "action": "inspect_controls",
        })

        self.assertIn("failed", result.lower())

    def test_discovery_requires_unique_result_at_consumption(self) -> None:
        result = ui_adapter.find_controls(
            [{
                "name": "App",
                "controls": [
                    {"name": "Search", "control_type": "Edit"},
                    {"name": "Search", "control_type": "Edit"},
                ],
            }],
            name="Search",
            control_type="Edit",
        )

        self.assertEqual(result["status"], "ambiguous")
        self.assertTrue(result["ambiguous"])

    def test_discovery_is_read_only_classification(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control", {"action": "inspect_controls"}
            ),
            "read_or_navigate",
        )
