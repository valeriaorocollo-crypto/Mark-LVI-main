from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import browser_control, computer_control, file_controller, open_app, send_message
from core import appidentity
import main


class InputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        with computer_control._screen_click_history_lock:
            computer_control._screen_click_history.clear()

    def _run_core_tool(self, name: str, args: object):
        dispatcher = object.__new__(main.JarvisLive)
        dispatcher.ui = SimpleNamespace(
            muted=False,
            set_state=lambda _state: None,
        )
        dispatcher._action_registry = SimpleNamespace(
            scheduling=lambda _name: None
        )
        dispatcher._plugin_registry = SimpleNamespace(
            scheduling=lambda _name: None
        )
        return asyncio.run(dispatcher._execute_tool(SimpleNamespace(
            name=name,
            args=args,
            id="synthetic-call",
        ))).response["result"]

    def test_core_tool_specific_limits_fail_before_side_effects(self) -> None:
        with (
            patch.object(main, "_capture_screen") as capture_screen,
            patch.object(main, "_capture_camera") as capture_camera,
        ):
            result = self._run_core_tool(
                "screen_process",
                {"angle": "unknown", "text": "synthetic"},
            )

        self.assertIn("status=failed", result)
        capture_screen.assert_not_called()
        capture_camera.assert_not_called()

        with patch.object(main, "search_memory") as search_memory:
            result = self._run_core_tool(
                "recall_memory",
                {"query": "x" * 501},
            )

        self.assertIn("status=failed", result)
        search_memory.assert_not_called()

        with patch.object(main.undo_stack, "undo_last") as undo_last:
            result = self._run_core_tool(
                "undo",
                {"action": "unexpected"},
            )

        self.assertIn("status=failed", result)
        undo_last.assert_not_called()

    def test_browser_normalizes_plain_domain_and_http_url(self) -> None:
        self.assertEqual(
            browser_control._normalize_url("example.com/path"),
            "https://example.com/path",
        )
        self.assertEqual(
            browser_control._normalize_url("http://localhost:8000"),
            "http://localhost:8000",
        )
        self.assertEqual(
            browser_control._normalize_url("about:blank"),
            "about:blank",
        )

    def test_browser_rejects_non_web_schemes_and_unsafe_urls(self) -> None:
        for value in (
            "javascript:alert(1)",
            "javascript://example.com",
            "file:///C:/Users/test.txt",
            "data:text/html,example",
            "https://user:password@example.com",
            "https://example.com:invalid",
            "https://example.com/with space",
            "https://" + ("a" * 2041),
        ):
            with self.subTest(value=value[:60]):
                with self.assertRaises(ValueError):
                    browser_control._normalize_url(value)

    def test_focus_window_treats_title_as_data_not_shell_code(self) -> None:
        title = 'Editor"); Start-Process calc; #'
        match = appidentity.Match(
            pid=12345, name="SyntheticEditor.exe", score=100, is_self=False,
            titles=[title],
        )
        with (
            patch.object(appidentity, "_PSUTIL", True),
            patch.object(appidentity, "running", return_value=[match]) as running,
            patch.object(appidentity, "focus", return_value=True),
            patch.object(computer_control.subprocess, "run") as run,
        ):
            result = computer_control._focus_window(title)

        running.assert_called_once_with(title, include_self=True)
        run.assert_not_called()
        self.assertIn("status=done", result)

    def test_focus_window_rejects_empty_or_overlong_titles(self) -> None:
        self.assertIn(
            "no window title",
            computer_control._focus_window("  "),
        )
        self.assertIn(
            "256-character limit",
            computer_control._focus_window("x" * 257),
        )

    def test_focus_window_does_not_report_success_without_foreground_verification(
        self,
    ) -> None:
        title = "Synthetic Editor"
        match = appidentity.Match(
            pid=12345, name="SyntheticEditor.exe", score=100, is_self=False,
            titles=[title],
        )
        with (
            patch.object(appidentity, "_PSUTIL", True),
            patch.object(appidentity, "running", return_value=[match]),
            patch.object(appidentity, "focus", return_value=False),
        ):
            result = computer_control._focus_window(title)

        self.assertIn("status=failed", result)
        self.assertIn("none could be focused", result)

    def test_focus_control_requires_confirmation_before_uia(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with patch.object(
            computer_control.action_policy,
            "request_confirmation",
            return_value="[CONFIRMATION_PENDING]",
        ) as request:
            result = computer_control.computer_control({
                "action": "focus_control",
                "selector": selector,
            })

        self.assertEqual(result, "[CONFIRMATION_PENDING]")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["tool"], "computer_control")
        self.assertEqual(request.call_args.kwargs["action"], "focus_control")

    def test_activate_window_does_not_require_routine_hud_confirmation(self) -> None:
        expected = {"status": "done", "verified": True}
        with patch.object(
            computer_control.ui_adapter,
            "activate_window",
            return_value=expected,
        ) as activate:
            result = computer_control.computer_control({
                "action": "activate_window",
                "title": "Demo",
            })

        self.assertEqual(json.loads(result), expected)
        activate.assert_called_once_with("Demo")

    def test_write_control_does_not_require_confirmation_for_ordinary_field(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Name",
            "control_type": "Edit",
            "automation_id": "name",
        }
        with patch.object(
            computer_control.ui_adapter,
            "write_control",
            return_value={"status": "done", "verified": True},
        ) as write:
            result = computer_control.computer_control({
                "action": "write_control",
                "selector": selector,
                "text": "safe test",
            })

        self.assertEqual(json.loads(result)["status"], "done")
        write.assert_called_once_with(selector, "safe test")

    def test_invoke_control_does_not_require_confirmation_for_routine_target(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with patch.object(
            computer_control.ui_adapter,
            "invoke_control",
            return_value={"status": "done", "verified": True},
        ) as invoke:
            result = computer_control.computer_control({
                "action": "invoke_control",
                "selector": selector,
            })

        self.assertEqual(json.loads(result)["status"], "done")
        invoke.assert_called_once_with(selector)

    def test_focus_control_reports_invalid_selector_after_confirmation(self) -> None:
        selector = {
            "window_name": "x" * 301,
            "name": "Save",
            "control_type": "Button",
            "automation_id": "",
        }
        with patch.object(
            computer_control.action_policy,
            "request_confirmation",
        ) as request:
            result = computer_control.computer_control({
                "action": "focus_control",
                "selector": selector,
            })

        self.assertIn("status=failed", result)
        self.assertIn("invalid focus_control selector", result)
        request.assert_not_called()

    def test_focus_control_preserves_verified_outcomes(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        outcomes = (
            {"status": "done", "verified": True},
            {"status": "unverified", "verified": False},
            {"status": "failed", "verified": False},
        )
        for adapter_result in outcomes:
            with self.subTest(status=adapter_result["status"]):
                with (
                    patch.object(
                        computer_control.action_policy,
                        "request_confirmation",
                        side_effect=lambda *args, **kwargs: kwargs["run"](),
                    ),
                    patch.object(
                        computer_control.ui_adapter,
                        "focus_control",
                        return_value=adapter_result,
                    ),
                ):
                    result = computer_control.computer_control({
                        "action": "focus_control",
                        "selector": selector,
                    })

                self.assertIn(f'"status": "{adapter_result["status"]}"', result)
                self.assertIn(
                    f'"verified": {str(adapter_result["verified"]).lower()}',
                    result,
                )

    def test_computer_control_rejects_oversized_text_before_typing(self) -> None:
        with patch.object(computer_control, "_type") as type_text:
            result = computer_control.computer_control({
                "action": "type",
                "text": "x" * (computer_control._MAX_TEXT_INPUT + 1),
            })

        self.assertIn("10000-character limit", result)
        type_text.assert_not_called()

    def test_computer_control_bounds_wait_and_scroll(self) -> None:
        with (
            patch.object(computer_control.time, "sleep") as sleep,
            patch.object(computer_control, "_scroll") as scroll,
        ):
            negative_wait = computer_control.computer_control({
                "action": "wait",
                "seconds": -1,
            })
            excessive_scroll = computer_control.computer_control({
                "action": "scroll",
                "direction": "down",
                "amount": 101,
            })

        self.assertIn("between 0 and 30 seconds", negative_wait)
        self.assertIn("between 1 and 100", excessive_scroll)
        sleep.assert_not_called()
        scroll.assert_not_called()

    def test_computer_control_rejects_out_of_screen_clicks(self) -> None:
        fake_input = SimpleNamespace(
            size=lambda: (1920, 1080),
            click=lambda *_args, **_kwargs: self.fail("click should not run"),
        )
        with (
            patch.object(computer_control, "_PYAUTOGUI", True),
            patch.object(computer_control, "pyautogui", fake_input),
        ):
            result = computer_control.computer_control({
                "action": "click",
                "x": 1920,
                "y": 10,
            })

        self.assertIn("inside the current screen", result)

    def test_screen_click_requires_confirmation_before_visual_lookup(self) -> None:
        with (
            patch.object(computer_control, "_screen_find", return_value=(10, 20)) as find,
            patch.object(
                computer_control.action_policy,
                "request_confirmation",
                return_value="[CONFIRMATION_PENDING]",
            ) as request,
        ):
            result = computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            })

        self.assertEqual(result, "[CONFIRMATION_PENDING]")
        find.assert_not_called()
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["tool"], "computer_control")
        self.assertEqual(request.call_args.kwargs["action"], "screen_click")
        self.assertIn("Gemini", request.call_args.kwargs["detail"])

    def test_screen_click_reports_done_only_after_visible_change(self) -> None:
        image_before = SimpleNamespace(tobytes=lambda: b"before")
        image_after = SimpleNamespace(tobytes=lambda: b"after")
        with (
            patch.object(computer_control, "_screen_find", return_value=(10, 20)),
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control.pyautogui, "size", return_value=(1920, 1080)
            ),
            patch.object(
                computer_control.pyautogui,
                "screenshot",
                side_effect=[image_before, image_after],
            ),
            patch.object(computer_control, "_click") as click,
            patch.object(
                computer_control.action_policy,
                "request_confirmation",
                side_effect=lambda *_args, **kwargs: kwargs["run"](),
            ),
        ):
            result = computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            })

        self.assertIn("status=done", result)
        self.assertIn("goal_verified=false", result)
        click.assert_called_once_with(10, 20)

    def test_screen_click_is_unverified_when_screen_does_not_change(self) -> None:
        image = SimpleNamespace(tobytes=lambda: b"same")
        with (
            patch.object(computer_control, "_screen_find", return_value=(10, 20)),
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control.pyautogui, "size", return_value=(1920, 1080)
            ),
            patch.object(
                computer_control.pyautogui,
                "screenshot",
                side_effect=[image, image],
            ),
            patch.object(computer_control, "_click"),
            patch.object(
                computer_control.action_policy,
                "request_confirmation",
                side_effect=lambda *_args, **kwargs: kwargs["run"](),
            ),
        ):
            result = computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            })

        self.assertIn("status=unverified", result)

    def test_screen_click_aborts_if_target_moves_after_confirmation(self) -> None:
        with (
            patch.object(
                computer_control, "_screen_find",
                side_effect=[(10, 20), (11, 21)],
            ),
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control.pyautogui, "size", return_value=(1920, 1080)
            ),
            patch.object(computer_control, "_click") as click,
            patch.object(
                computer_control.action_policy,
                "request_confirmation",
                side_effect=lambda *_args, **kwargs: kwargs["run"](),
            ),
        ):
            result = computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            })

        self.assertIn("status=failed", result)
        click.assert_not_called()

    def test_screen_click_rate_limit_blocks_repeated_clicks(self) -> None:
        with (
            patch.object(computer_control, "_screen_find", return_value=(10, 20)),
            patch.object(computer_control, "_require_pyautogui"),
            patch.object(
                computer_control.pyautogui, "size", return_value=(1920, 1080)
            ),
            patch.object(
                computer_control.pyautogui,
                "screenshot",
                side_effect=[
                    SimpleNamespace(tobytes=lambda: b"one"),
                    SimpleNamespace(tobytes=lambda: b"two"),
                    SimpleNamespace(tobytes=lambda: b"three"),
                    SimpleNamespace(tobytes=lambda: b"four"),
                    SimpleNamespace(tobytes=lambda: b"five"),
                    SimpleNamespace(tobytes=lambda: b"six"),
                ],
            ),
            patch.object(computer_control, "_click"),
            patch.object(
                computer_control.action_policy,
                "request_confirmation",
                side_effect=lambda *_args, **kwargs: kwargs["run"](),
            ),
        ):
            results = [
                computer_control.computer_control({
                    "action": "screen_click",
                    "description": "Save button",
                })
                for _ in range(4)
            ]

        self.assertEqual(sum("status=done" in result for result in results), 3)
        self.assertIn("rate limit", results[3])

    def test_computer_control_rejects_oversized_hotkey(self) -> None:
        with patch.object(computer_control, "_hotkey") as press_hotkey:
            result = computer_control.computer_control({
                "action": "hotkey",
                "keys": "ctrl+alt+shift+win+f1+f2",
            })

        self.assertIn("1-5 keys", result)
        press_hotkey.assert_not_called()

    def test_message_rejects_oversized_text_without_needing_desktop(self) -> None:
        with patch.object(send_message, "_PYAUTOGUI", False):
            result = send_message.send_message({
                "receiver": "Synthetic Contact",
                "message_text": "x" * 10_001,
                "platform": "WhatsApp",
            })

        self.assertIn("10000-character limit", result)

    def test_app_and_file_path_lengths_are_bounded(self) -> None:
        self.assertIn(
            "128 characters",
            open_app.open_app({"app_name": "A" * 129}),
        )
        self.assertIn(
            "4096 characters",
            file_controller.file_controller({
                "action": "list",
                "path": "x" * 4097,
            }),
        )


if __name__ == "__main__":
    unittest.main()
