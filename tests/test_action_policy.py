from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from core import action_policy, confirm, session_grants


class ActionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        session_grants.revoke_all()
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )

    def tearDown(self) -> None:
        session_grants.revoke_all()
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_requires_confirmation_only_for_high_and_external_risks(self) -> None:
        self.assertTrue(action_policy.requires_confirmation(
            "file_controller", "write"
        ))
        self.assertTrue(action_policy.requires_confirmation(
            "send_message", "send"
        ))
        self.assertFalse(action_policy.requires_confirmation(
            "file_controller", "read"
        ))
        self.assertFalse(action_policy.requires_confirmation(
            "computer_control", "unknown_action"
        ))

    def test_gate_fails_closed_for_an_unclassified_action(self) -> None:
        ran = threading.Event()

        result = action_policy.request_confirmation(
            "computer_control",
            "unknown_action",
            "Run unknown action?",
            "Synthetic details",
            lambda: ran.set() or "done",
        )

        self.assertIn("status=failed", result)
        self.assertFalse(ran.is_set())
        self.assertEqual(self.prompts, [])

    def test_dispatch_rejects_invalid_arguments_or_handler(self) -> None:
        self.assertIn(
            "status=failed",
            action_policy.dispatch("file_controller", None, lambda: "done"),
        )
        self.assertIn(
            "status=failed",
            action_policy.dispatch("file_controller", {}, None),
        )

    def test_dispatch_rejects_oversized_arguments_without_calling_handler(self):
        ran = []

        result = action_policy.dispatch(
            "browser_control",
            {"action": "get_url", "text": "x" * 100_001},
            lambda: ran.append(True) or "status=done",
        )

        self.assertIn("status=failed", result)
        self.assertFalse(ran)

    def test_dispatch_rejects_non_json_arguments_without_calling_handler(self):
        ran = []

        result = action_policy.dispatch(
            "browser_control",
            {"action": "get_url", "value": object()},
            lambda: ran.append(True) or "status=done",
        )

        self.assertIn("status=failed", result)
        self.assertFalse(ran)

    def test_shared_argument_validation_covers_core_tool_inputs(self) -> None:
        self.assertIsNone(action_policy.validate_arguments({"query": "safe"}))
        self.assertIn(
            "size limit",
            action_policy.validate_arguments({"query": "x" * 100_001}) or "",
        )
        self.assertEqual(
            action_policy.validate_arguments({"query": "\ud800"}),
            "tool arguments contain invalid text",
        )

    def test_sensitive_action_waits_for_confirmation(self) -> None:
        ran = threading.Event()

        result = action_policy.request_confirmation(
            "file_controller",
            "write",
            "Write file?",
            "Synthetic file contents",
            lambda: ran.set() or "written",
            arguments={"action": "write"},
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(self.prompts, [("Write file?", "Synthetic file contents")])
        self.assertFalse(ran.is_set())

        confirm.resolve(False)

        self.assertFalse(ran.wait(0.1))

    def test_voice_confirmation_is_not_bypassed_by_authorized_task_plan(self) -> None:
        ran = threading.Event()
        voice_handler = lambda _text: confirm.VoiceDecision("accept")
        arguments = {"platform": "WhatsApp", "receiver": "Synthetic"}

        with action_policy.authorize_plan([("send_message", arguments)]):
            result = action_policy.request_confirmation(
                "send_message",
                "send",
                "Send message?",
                "Synthetic message",
                lambda: ran.set() or "sent",
                arguments=arguments,
                voice_handler=voice_handler,
            )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertFalse(ran.is_set())
        self.assertEqual(self.prompts, [("Send message?", "Synthetic message")])
        confirm.resolve(False)
        self.assertFalse(ran.wait(0.1))

    def test_confirmation_masks_secret_form_values(self) -> None:
        result = action_policy.dispatch(
            "task_planner",
            {
                "mode": "execute",
                "task": "fill login form",
                "steps": [
                    {
                        "tool": "browser_control",
                        "arguments": {
                            "action": "fill_form",
                            "fields": {
                                'input[name="email"]': "person@example.test",
                                'input[name="password"]': "private-password",
                                'input[name="credential"]': "private-credential",
                            },
                        },
                        "purpose": "fill fields",
                        "verification": {
                            "tool": "browser_control",
                            "arguments": {"action": "get_url"},
                            "expect": "https://example.test",
                        },
                    }
                ],
            },
            lambda: "not executed",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        detail = self.prompts[-1][1]
        self.assertIn("person@example.test", detail)
        self.assertIn("[REDACTED]", detail)
        self.assertNotIn("private-password", detail)
        self.assertNotIn("private-credential", detail)

    def test_confirmation_masks_text_for_sensitive_desktop_targets(self) -> None:
        result = action_policy.dispatch(
            "computer_control",
            {
                "action": "type",
                "selector": {
                    "window_name": "Synthetic login",
                    "name": "Password",
                    "control_type": "Edit",
                },
                "text": "private-password-value",
            },
            lambda: "not executed",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        detail = self.prompts[-1][1]
        self.assertIn("[REDACTED]", detail)
        self.assertNotIn("private-password-value", detail)

    def test_sensitive_action_refuses_if_hud_is_unavailable(self) -> None:
        ran = threading.Event()
        confirm.bind(None, None)

        result = action_policy.request_confirmation(
            "file_controller",
            "write",
            "Write file?",
            "Synthetic file contents",
            lambda: ran.set() or "written",
            arguments={"action": "write"},
        )

        self.assertIn("interface is not available", result)
        self.assertFalse(ran.is_set())

    def test_approval_runs_sensitive_action_once(self) -> None:
        completed = threading.Event()
        calls: list[int] = []

        def action() -> str:
            calls.append(1)
            completed.set()
            return "written"

        result = action_policy.request_confirmation(
            "file_controller",
            "write",
            "Write file?",
            "Synthetic file contents",
            action,
            arguments={"action": "write"},
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve(True)

        self.assertTrue(completed.wait(2))
        self.assertEqual(calls, [1])

    def test_task_history_clear_requires_hud_confirmation(self) -> None:
        ran = threading.Event()
        args = {"mode": "clear_history"}

        result = action_policy.dispatch(
            "task_planner",
            args,
            lambda: ran.set() or "status=done action=clear_history",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertFalse(ran.is_set())
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("clear_history", self.prompts[0][1])

        confirm.resolve(True)

        self.assertTrue(ran.wait(2))

    def test_plan_authorizes_exact_nested_handler_signature(self) -> None:
        arguments = {"action": "activate_window", "title": "Synthetic"}
        called = []
        with action_policy.authorize_plan(
            [("computer_control", arguments)]
        ):
            result = action_policy.run_or_confirm(
                "computer_control",
                "activate_window",
                "title",
                "detail",
                lambda: called.append(True) or "ran",
                arguments=arguments,
            )

        self.assertEqual(result, "ran")
        self.assertEqual(called, [True])

    def test_routine_screen_action_runs_without_hud_confirmation(self) -> None:
        called = []

        result = action_policy.run_or_confirm(
            "computer_control",
            "activate_window",
            "Activate window?",
            "Synthetic window",
            lambda: called.append(True) or "status=done",
            arguments={"action": "activate_window", "title": "Settings"},
        )

        self.assertEqual(result, "status=done")
        self.assertEqual(called, [True])
        self.assertEqual(self.prompts, [])

    def test_critical_screen_target_still_requires_hud_confirmation(self) -> None:
        called = []

        result = action_policy.run_or_confirm(
            "computer_control",
            "screen_click",
            "Click button?",
            "Buy now",
            lambda: called.append(True) or "status=done",
            arguments={
                "action": "screen_click",
                "description": "Buy now",
            },
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(called, [])
        self.assertEqual(len(self.prompts), 1)

    def test_semantic_rental_button_requires_confirmation(self) -> None:
        called = []
        arguments = {
            "action": "invoke_control",
            "selector": {
                "window_name": "Store",
                "name": "Alquilar ahora",
                "control_type": "Button",
                "automation_id": "rent",
            },
        }

        result = action_policy.run_or_confirm(
            "computer_control",
            "invoke_control",
            "Invoke control?",
            "Store / Alquilar ahora",
            lambda: called.append(True) or "status=done verified=true",
            arguments=arguments,
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(called, [])
        self.assertEqual(len(self.prompts), 1)

    def test_opaque_global_input_requires_hud_before_handler_runs(self) -> None:
        cases = (
            ("computer_control", {"action": "press", "key": "delete"}),
            ("computer_control", {"action": "hotkey", "keys": "shift+delete"}),
            ("computer_control", {"action": "click", "x": 500, "y": 300}),
            ("computer_control", {"action": "click"}),
            ("computer_control", {"action": "click", "target": "Alquilar ahora"}),
            ("computer_control", {"action": "copy"}),
            ("computer_control", {"action": "screen_find", "description": "Save"}),
            ("browser_control", {"action": "click", "selector": "Continue"}),
            ("computer_settings", {"action": "press_key", "key": "delete"}),
        )
        for tool, arguments in cases:
            with self.subTest(arguments=arguments):
                called = []
                result = action_policy.dispatch(
                    tool,
                    arguments,
                    lambda: called.append(True) or "status=done verified=true",
                )

                self.assertIn("[CONFIRMATION_PENDING]", result)
                self.assertEqual(called, [])
                confirm.resolve(False)
                self.assertEqual(called, [])
                self.prompts.clear()

    def test_auto_code_helper_uses_the_generated_write_preview(self) -> None:
        written = []

        def auto_action() -> str:
            return action_policy.request_confirmation(
                "code_helper",
                "write",
                "Confirm generated file?",
                "Generated source preview",
                lambda: written.append(True) or "written",
                arguments={"action": "write", "path": "generated.py"},
            )

        result = action_policy.dispatch(
            "code_helper",
            {"action": "auto", "description": "create a utility"},
            auto_action,
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(
            self.prompts,
            [("Confirm generated file?", "Generated source preview")],
        )
        self.assertEqual(written, [])
        confirm.resolve(False)
        self.assertEqual(written, [])

    def test_confirmation_context_does_not_authorize_another_call(self) -> None:
        called = []
        token = action_policy._CONFIRMED_TOOL.set("computer_control")
        try:
            with patch.object(
                confirm,
                "request",
                return_value="[CONFIRMATION_PENDING]",
            ) as request:
                result = action_policy.request_confirmation(
                    "computer_control",
                    "press",
                    "Press key?",
                    "Delete key",
                    lambda: called.append(True) or "pressed",
                    arguments={"action": "press", "key": "delete"},
                )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertEqual(result, "[CONFIRMATION_PENDING]")
        self.assertEqual(called, [])
        request.assert_called_once()

    def test_screen_search_grant_is_opt_in_scoped_and_revocable(self) -> None:
        granted_prompts: list[tuple[str, str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
            show_grant=lambda title, detail, label: granted_prompts.append(
                (title, detail, label)
            ),
        )
        scope = session_grants.GrantScope(
            "share_screen_search", "Gemini", "active_screen"
        )
        arguments = {
            "action": "screen_find",
            "description": "synthetic blue icon",
        }
        calls: list[int] = []
        completed = threading.Event()

        result = action_policy.dispatch(
            "computer_control",
            arguments,
            lambda: calls.append(1) or completed.set() or "status=done verified=true",
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(len(granted_prompts), 1)
        self.assertIn("screen captures", granted_prompts[0][2])
        self.assertFalse(session_grants.allows(scope))
        self.assertEqual(calls, [])

        confirm.resolve("grant")
        self.assertTrue(completed.wait(2))
        self.assertTrue(session_grants.allows(scope))

        completed.clear()
        result = action_policy.dispatch(
            "computer_control",
            arguments,
            lambda: calls.append(2) or completed.set() or "status=done verified=true",
        )
        self.assertEqual(result, "status=done verified=true")
        self.assertEqual(calls, [1, 2])
        self.assertEqual(len(granted_prompts), 1)

        self.assertTrue(session_grants.revoke(scope))
        result = action_policy.dispatch(
            "computer_control",
            arguments,
            lambda: calls.append(3) or "status=done verified=true",
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(calls, [1, 2])


if __name__ == "__main__":
    unittest.main()
