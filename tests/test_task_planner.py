from __future__ import annotations

import unittest

from actions.task_planner import task_planner
from core import task_plan


class TaskPlannerTests(unittest.TestCase):
    def _steps(self):
        return [{
            "tool": "computer_control",
            "arguments": {"action": "activate_window", "title": "Settings"},
            "purpose": "Activate the settings window",
            "verification": {
                "tool": "computer_control",
                "arguments": {"action": "inspect_windows", "limit": 5},
                "expect": "Settings",
            },
        }]

    def test_preview_is_non_executing_and_verified(self) -> None:
        result = task_plan.preview("Open settings search", self._steps())

        self.assertIn("status=done", result)
        self.assertIn("execution=preview_only", result)
        self.assertIn("verified=true", result)

    def test_preview_rejects_unclassified_steps(self) -> None:
        result = task_plan.preview(
            "Unsafe plan",
            [{
                "tool": "unknown_tool",
                "arguments": {"action": "run"},
                "purpose": "Unknown action",
                "verification": {
                    "tool": "computer_control",
                    "arguments": {"action": "inspect_windows"},
                    "expect": "Unknown",
                },
            }],
        )

        self.assertIn("status=failed", result)
        self.assertIn("no reviewed risk classification", result)

    def test_preview_rejects_excessive_steps(self) -> None:
        steps = self._steps() * (task_plan.MAX_STEPS + 1)

        result = task_plan.preview("Too long", steps)

        self.assertIn("status=failed", result)
        self.assertIn("at most", result)

    def test_preview_requires_observable_verification(self) -> None:
        step = self._steps()[0].copy()
        step.pop("verification")

        result = task_plan.preview("Missing evidence", [step])

        self.assertIn("status=failed", result)
        self.assertIn("verification", result)

    def test_preview_rejects_outcome_metadata_as_expected_evidence(self) -> None:
        step = self._steps()[0].copy()
        step["verification"] = {
            "tool": "computer_control",
            "arguments": {"action": "inspect_windows", "limit": 5},
            "expect": "verified=true",
        }

        result = task_plan.preview("Reject metadata evidence", [step])

        self.assertIn("status=failed", result)
        self.assertIn("outcome metadata", result)

    def test_unknown_mode_fails_instead_of_creating_a_preview(self) -> None:
        result = task_planner({"mode": "unexpected"})

        self.assertIn("status=failed", result)
        self.assertNotIn("execution=preview_only", result)
