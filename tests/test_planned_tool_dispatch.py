from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import main
from core import action_policy, confirm, task_plan, tool_audit


_PLUGIN_NAME = "planned_plugin_dispatch_test"


class _EmptyActionRegistry:
    def has(self, name: str) -> bool:
        return name == ""


class _PluginRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, object, object]] = []

    def has(self, name: str) -> bool:
        return name == _PLUGIN_NAME

    def run(self, name, arguments, *, player=None, session_memory=None):
        self.calls.append((name, arguments, player, session_memory))
        return "status=done verified=true evidence=Steam"


class PlannedToolDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        tool_audit.register_tool_risk(_PLUGIN_NAME, "external")
        self.plugins = _PluginRegistry()
        self.player = object()
        self.context = {"player": self.player, "session_memory": None}
        with confirm._lock:
            confirm._pending = None
        confirm.bind(lambda *_: None, lambda: None)

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_exact_plan_approval_dispatches_plugin_with_context(self) -> None:
        arguments = {"action": "search", "query": "Steam"}
        with action_policy.authorize_plan([(_PLUGIN_NAME, arguments)]):
            result = main._execute_planned_tool(
                _PLUGIN_NAME,
                arguments,
                _EmptyActionRegistry(),
                self.plugins,
                self.context,
            )

        self.assertIn("evidence=Steam", result)
        self.assertEqual(
            self.plugins.calls,
            [(_PLUGIN_NAME, arguments, self.player, None)],
        )

    def test_plugin_step_without_plan_approval_requires_hud_confirmation(self) -> None:
        arguments = {"action": "search", "query": "Steam"}
        result = main._execute_planned_tool(
            _PLUGIN_NAME,
            arguments,
            _EmptyActionRegistry(),
            self.plugins,
            self.context,
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(self.plugins.calls, [])
        confirm.resolve(True)
        self.assertEqual(len(self.plugins.calls), 1)

    def test_composite_plan_executes_and_verifies_a_plugin_step(self) -> None:
        task = "Search Steam through an installed integration"
        steps = [{
            "tool": _PLUGIN_NAME,
            "arguments": {"action": "search", "query": "Steam"},
            "purpose": "Find Steam information",
            "verification": {
                "tool": "computer_control",
                "arguments": {"action": "inspect_windows", "limit": 5},
                "expect": "Steam",
            },
        }]
        preview = task_plan.preview(task, steps)
        task_match = re.search(r"\btask_id=([0-9a-f]+)", preview)
        self.assertIsNotNone(task_match, preview)
        task_id = task_match.group(1)

        def execute_tool(name, arguments):
            if name == "computer_control":
                return "status=done verified=true evidence=Steam"
            return main._execute_planned_tool(
                name,
                arguments,
                _EmptyActionRegistry(),
                self.plugins,
                self.context,
            )

        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            with patch("core.task_plan.task_history.save_snapshot"):
                result = task_plan.execute(task, steps, execute_tool, task_id)
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=done", result)
        self.assertEqual(len(self.plugins.calls), 1)

    def test_unavailable_planned_tool_fails_without_dispatch(self) -> None:
        result = main._execute_planned_tool(
            "unknown_planned_tool",
            {},
            _EmptyActionRegistry(),
            self.plugins,
            self.context,
        )

        self.assertIn("status=failed", result)
        self.assertEqual(self.plugins.calls, [])


if __name__ == "__main__":
    unittest.main()
