from __future__ import annotations

import asyncio
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions import browser_control, computer_control
from core import action_policy, confirm, session_grants


class ActionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._grant_store_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._grant_store_dir.cleanup)
        patcher = patch.object(
            session_grants,
            "GRANT_STORE_PATH",
            Path(self._grant_store_dir.name) / "permissions.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_screenshot_requires_confirmation_and_describes_local_destination(self) -> None:
        ran = threading.Event()
        result = action_policy.dispatch(
            "computer_control",
            {"action": "screenshot", "path": "C:\\Users\\Synthetic\\screen.png"},
            lambda: ran.set() or "status=done action=screenshot",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertFalse(ran.is_set())
        self.assertIn("Source: full active screen", self.prompts[0][1])
        self.assertIn("Destination: local file", self.prompts[0][1])
        self.assertIn("does not send it to a provider", self.prompts[0][1])

    def test_screenshot_shows_indicator_before_capture_and_honors_stop(self) -> None:
        events: list[str] = []
        image = SimpleNamespace(
            save=lambda path: events.append(f"save:{path}")
        )
        fake_pyautogui = SimpleNamespace(
            screenshot=lambda: events.append("capture") or image
        )

        class CaptureUI:
            def __init__(self, *, stopped: bool = False) -> None:
                self.stopped = threading.Event()
                if stopped:
                    self.stopped.set()

            def begin_capture_activity(self, source: str) -> threading.Event:
                events.append(f"indicator:{source}")
                return self.stopped

            def end_capture_activity(self, token: threading.Event) -> None:
                events.append("cleanup")

        with (
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control, "_safe_screenshot_path", return_value=Path("screen.png")
            ),
            patch.object(computer_control, "pyautogui", fake_pyautogui),
        ):
            result = computer_control._screenshot("screen.png", player=CaptureUI())

        self.assertIn("status=done", result)
        self.assertEqual(
            [event.split(":", 1)[0] for event in events],
            ["indicator", "capture", "save", "cleanup"],
        )

        events.clear()
        with (
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control, "_safe_screenshot_path", return_value=Path("screen.png")
            ),
            patch.object(computer_control, "pyautogui", fake_pyautogui),
        ):
            result = computer_control._screenshot(
                "screen.png", player=CaptureUI(stopped=True)
            )

        self.assertIn("status=failed", result)
        self.assertEqual(
            [event.split(":", 1)[0] for event in events],
            ["indicator", "cleanup"],
        )

    def test_browser_screenshot_requires_confirmation_and_describes_page(self) -> None:
        result = action_policy.dispatch(
            "browser_control",
            {"action": "screenshot", "path": "browser-shot.png"},
            lambda: "status=done action=screenshot",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertIn("Source: the active browser page", self.prompts[0][1])
        self.assertIn(
            str(Path("browser-shot.png").resolve()), self.prompts[0][1]
        )
        self.assertIn("does not send it to a provider", self.prompts[0][1])

    def test_browser_screenshot_shows_indicator_before_reading_page(self) -> None:
        events: list[str] = []

        class CaptureUI:
            def __init__(self, *, stopped: bool = False) -> None:
                self.token = threading.Event()
                if stopped:
                    self.token.set()

            def begin_capture_activity(self, source: str) -> threading.Event:
                events.append(f"indicator:{source}")
                return self.token

            def end_capture_activity(self, token: threading.Event) -> None:
                events.append("cleanup")

        async def take_screenshot(**_kwargs) -> bytes:
            events.append("capture")
            return b"synthetic browser image"

        page = SimpleNamespace(screenshot=take_screenshot)

        async def get_page():
            return page

        session = SimpleNamespace(_get_page=get_page)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "browser.png"
            result = asyncio.run(
                browser_control._BrowserSession.screenshot(
                    session, str(path), player=CaptureUI()
                )
            )
            self.assertIn("status=done", result)
            self.assertEqual(path.read_bytes(), b"synthetic browser image")
            self.assertEqual(
                [event.split(":", 1)[0] for event in events],
                ["indicator", "capture", "cleanup"],
            )

            events.clear()
            result = asyncio.run(
                browser_control._BrowserSession.screenshot(
                    session, str(path), player=CaptureUI(stopped=True)
                )
            )
            self.assertIn("status=failed", result)
            self.assertEqual(
                [event.split(":", 1)[0] for event in events],
                ["indicator", "cleanup"],
            )

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

    def test_opaque_desktop_effects_fail_closed_before_handler(self) -> None:
        cases = (
            ("computer_control", {"action": "press", "key": "delete"}),
            ("computer_control", {"action": "hotkey", "keys": "shift+delete"}),
            ("computer_control", {"action": "paste", "text": "synthetic"}),
            ("computer_control", {"action": "drag", "x1": 1, "y1": 2, "x2": 3, "y2": 4}),
            ("computer_control", {"action": "click", "x": 500, "y": 300}),
            ("computer_control", {"action": "click"}),
            ("computer_control", {"action": "focus_window", "title": "Synthetic"}),
            ("computer_settings", {"action": "press_key", "key": "delete"}),
            ("computer_settings", {"action": "type_text", "text": "synthetic"}),
        )
        for tool, arguments in cases:
            with self.subTest(tool=tool, arguments=arguments):
                called = []
                result = action_policy.dispatch(
                    tool,
                    arguments,
                    lambda: called.append(True) or "status=done",
                )
                self.assertIn("status=failed", result)
                self.assertEqual(called, [])
                self.assertEqual(self.prompts, [])

    def test_exact_plan_cannot_authorize_an_unknown_effect(self) -> None:
        arguments = {"action": "press", "key": "delete"}
        called = []
        with action_policy.authorize_plan([("computer_control", arguments)]):
            result = action_policy.dispatch(
                "computer_control",
                arguments,
                lambda: called.append(True) or "status=done",
            )

        self.assertIn("status=failed", result)
        self.assertEqual(called, [])

    def test_direct_browser_handler_still_requires_exact_target_approval(self) -> None:
        with patch.object(browser_control._registry, "get") as get_session:
            result = browser_control.browser_control({
                "action": "click",
                "selector": "button[type='submit']",
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        get_session.assert_not_called()
        self.assertEqual(len(self.prompts), 1)

    def test_semantic_write_preview_shows_target_and_masks_sensitive_input(self) -> None:
        selector = {
            "window_name": "Synthetic login",
            "name": "Password",
            "control_type": "Edit",
            "automation_id": "password",
        }
        with patch.object(computer_control.ui_adapter, "write_control") as write:
            result = computer_control.computer_control({
                "action": "write_control",
                "selector": selector,
                "text": "synthetic-secret",
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        detail = self.prompts[-1][1]
        self.assertIn("Synthetic login", detail)
        self.assertIn("Password", detail)
        self.assertIn("[REDACTED]", detail)
        self.assertNotIn("synthetic-secret", detail)
        write.assert_not_called()

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
        result = action_policy.run_or_confirm(
            "computer_control",
            "write_control",
            "Write to control?",
            "Synthetic target",
            lambda: "not executed",
            {
                "action": "write_control",
                "selector": {
                    "window_name": "Synthetic login",
                    "name": "Password",
                    "control_type": "Edit",
                    "automation_id": "password",
                },
                "text": "private-password-value",
            },
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        detail = self.prompts[-1][1]
        self.assertNotIn("private-password-value", detail)
        self.assertEqual(len(self.prompts), 1)

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

    def test_targeted_actions_wait_for_hud_before_handler_runs(self) -> None:
        cases = (
            ("computer_control", {"action": "screen_find", "description": "Save"}),
            ("browser_control", {"action": "click", "selector": "Continue"}),
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

    def test_unscoped_browser_click_fails_closed_before_handler(self) -> None:
        called = []
        result = action_policy.dispatch(
            "browser_control",
            {"action": "click"},
            lambda: called.append(True) or "status=done",
        )

        self.assertIn("status=failed", result)
        self.assertEqual(called, [])
        self.assertEqual(self.prompts, [])

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
                    "screen_click",
                    "Click target?",
                    "Synthetic target",
                    lambda: called.append(True) or "pressed",
                    arguments={
                        "action": "screen_click",
                        "description": "Synthetic target",
                    },
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
        scope = session_grants.scope_for(
            "share_screen_search", "synthetic blue icon"
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

        confirm.resolve(confirm.ConfirmationDecision.REMEMBER_30_DAYS)
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
