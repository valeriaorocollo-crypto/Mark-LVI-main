from __future__ import annotations

import unittest
from pathlib import Path

from actions import computer_settings
from core.action_loader import discover_actions
from core import tool_audit


class ToolAuditTests(unittest.TestCase):
    KNOWN_ACTIONS = {
        "computer_control": {
            "type", "smart_type", "click", "double_click", "right_click",
            "hotkey", "press", "scroll", "move", "copy", "paste",
            "screenshot", "wait", "clear_field", "focus_window",
            "list_processes", "close_app", "screen_find", "screen_click",
            "focus_control",
            "random_data", "user_data", "processes", "task_manager",
        },
        "computer_settings": {
            "volume_up", "volume_down", "volume_set", "mute",
            "unmute", "toggle_mute", "brightness_up", "brightness_down",
            "sleep_display", "screen_off", "pause_video", "play_pause",
            "close_app", "close_window", "full_screen", "fullscreen",
            "minimize", "maximize", "snap_left",
            "snap_right", "switch_window", "show_desktop", "task_manager",
            "focus_search", "refresh_page", "reload", "close_tab", "new_tab",
            "next_tab", "prev_tab", "go_back", "go_forward", "zoom_in", "zoom_out",
            "zoom_reset", "find_on_page", "scroll_up", "scroll_down",
            "scroll_top", "scroll_bottom", "page_up", "page_down", "copy",
            "paste", "cut", "undo", "redo", "select_all", "save", "enter",
            "escape", "press_key", "type_text", "screenshot", "lock_screen",
            "open_settings", "file_explorer", "open_run", "dark_mode",
            "toggle_wifi", "restart", "shutdown", "reload_n", "refresh_n",
            "reload_page_n", "type", "write", "write_on_screen",
        },
        "file_controller": {
            "list", "create_file", "create_folder", "delete", "move", "copy",
            "rename", "read", "write", "find", "largest", "disk_usage",
            "organize_desktop", "info",
        },
        "desktop_control": {
            "wallpaper", "wallpaper_url", "current_wallpaper", "organize",
            "clean", "list", "stats",
        },
        "game_updater": {
            "install", "update", "list", "download_status", "schedule",
            "cancel_schedule", "schedule_status",
        },
        "manage_monitor": {"add", "remove", "list"},
        "reminder": {"schedule"},
    }

    def setUp(self) -> None:
        tool_audit.clear()

    def tearDown(self) -> None:
        tool_audit.clear()

    def test_classifies_common_result_statuses(self) -> None:
        for status in ("done", "unverified", "failed", "ask", "started"):
            with self.subTest(status=status):
                self.assertEqual(
                    tool_audit.classify_status(f"status={status} action=test"),
                    status,
                )
        self.assertEqual(
            tool_audit.classify_status("Tool 'synthetic_tool' failed: private detail"),
            "failed",
        )
        self.assertEqual(
            tool_audit.classify_status(
                "Action 'synthetic_tool' crashed during run(): private detail"
            ),
            "failed",
        )
        self.assertEqual(
            tool_audit.classify_status("[CONFIRMATION_PENDING] confirm in HUD"),
            "ask",
        )
        self.assertEqual(tool_audit.classify_status("Opened the app"), "unclassified")

    def test_classifies_effect_conservatively(self) -> None:
        expected = {
            "ask": "none",
            "done": "verified",
            "started": "possible",
            "unverified": "possible",
            "failed": "possible",
            "unclassified": "unknown",
        }
        for status, effect in expected.items():
            with self.subTest(status=status):
                self.assertEqual(tool_audit.classify_effect(status), effect)

    def test_failure_result_keeps_failure_visible_but_redacts_exception_text(self) -> None:
        private_detail = "synthetic-token-should-not-leak"

        result = tool_audit.failure_result(
            "synthetic_tool", RuntimeError(private_detail)
        )

        self.assertEqual(result, "Tool 'synthetic_tool' failed: RuntimeError")
        self.assertNotIn(private_detail, result)
        self.assertEqual(
            tool_audit.failure_result("invalid tool name", RuntimeError(private_detail)),
            "Tool 'unknown' failed: RuntimeError",
        )

    def test_classifies_high_risk_and_external_actions(self) -> None:
        self.assertEqual(tool_audit.classify_risk("dev_agent"), "high")
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "delete_file"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "write"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "create_file"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "create_folder"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "rename"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "move"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("file_controller", {"action": "read"}),
            "read_or_navigate",
        )
        self.assertEqual(
            tool_audit.classify_risk("computer_control", {"action": "close_app"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("computer_control", {"action": "unrecognized"}),
            "unclassified",
        )

    def test_every_documented_action_has_an_explicit_risk_class(self) -> None:
        self.assertEqual(
            set(computer_settings.ACTION_MAP)
            - self.KNOWN_ACTIONS["computer_settings"],
            set(),
        )
        for tool, actions in self.KNOWN_ACTIONS.items():
            with self.subTest(tool=tool):
                for action in actions:
                    with self.subTest(action=action):
                        self.assertNotEqual(
                            tool_audit.classify_risk(tool, {"action": action}),
                            "unclassified",
                        )
        self.assertEqual(
            tool_audit.classify_risk("computer_settings", {"action": "restart"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("computer_control", {"action": "list_processes"}),
            "read_or_navigate",
        )
        for action in ("processes", "task_manager"):
            with self.subTest(action=action):
                self.assertEqual(
                    tool_audit.classify_risk(
                        "computer_control", {"action": action}
                    ),
                    "read_or_navigate",
                )
        self.assertEqual(
            tool_audit.classify_risk("computer_control", {"action": "click"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control", {"action": "focus_control"}
            ),
            "state_change",
        )
        self.assertEqual(
            tool_audit.classify_risk("send_message", {"to": "private@example.test"}),
            "external",
        )
        self.assertEqual(
            tool_audit.classify_risk("computer_control", {"action": "type"}),
            "high",
        )
        for action in ("copy", "screen_find"):
            with self.subTest(action=action):
                self.assertEqual(
                    tool_audit.classify_risk(
                        "computer_control", {"action": action}
                    ),
                    "high",
                )
        for arguments in (
            {"action": "press", "key": "delete"},
            {"action": "hotkey", "keys": "shift+delete"},
            {"action": "click", "x": 500, "y": 300},
            {"action": "click"},
            {"action": "click", "target": "Alquilar ahora"},
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    tool_audit.classify_risk("computer_control", arguments),
                    "high",
                )
        for tool, arguments in (
            ("browser_control", {"action": "click", "selector": "Continue"}),
            ("browser_control", {"action": "fill_form", "fields": {}}),
            ("computer_settings", {"action": "press_key", "key": "delete"}),
            ("computer_settings", {"action": "type_text", "text": "x"}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertEqual(tool_audit.classify_risk(tool, arguments), "high")
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control",
                {"action": "screen_click", "description": "Delete this file"},
            ),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk(
                "browser_control",
                {"action": "click", "text": "Buy now"},
            ),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control",
                {
                    "action": "write_control",
                    "selector": {"name": "Email address", "control_type": "Edit"},
                },
            ),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk(
                "computer_control",
                {
                    "action": "invoke_control",
                    "selector": {
                        "window_name": "Store",
                        "name": "Alquilar ahora",
                        "control_type": "Button",
                        "automation_id": "rent",
                    },
                },
            ),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk(
                "browser_control",
                {"action": "type", "selector": "input[name='search']", "text": "news"},
            ),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("desktop_control", {"action": "organize"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("desktop_control", {"action": "list"}),
            "read_or_navigate",
        )

    def test_unknown_browser_and_file_processor_actions_are_unclassified(self) -> None:
        for tool in ("browser_control", "file_processor"):
            with self.subTest(tool=tool):
                self.assertEqual(
                    tool_audit.classify_risk(
                        tool, {"action": "not_a_declared_action"}
                    ),
                    "unclassified",
                )

    def test_spotify_track_playback_is_a_state_change(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk(
                "spotify_control", {"action": "play"}
            ),
            "state_change",
        )

    def test_verifier_allowlist_contains_only_classified_read_actions(self) -> None:
        for tool, actions in tool_audit._READ_ONLY_VERIFICATION_ACTIONS.items():
            action_key = "mode" if tool == "web_search" else "action"
            for action in actions:
                with self.subTest(tool=tool, action=action):
                    expected_risk = (
                        "external" if tool == "gmail_control"
                        else "read_or_navigate"
                    )
                    self.assertEqual(
                        tool_audit.classify_risk(
                            tool, {action_key: action}
                        ),
                        expected_risk,
                    )

    def test_unstructured_or_effectful_reads_are_not_plan_verifiers(self) -> None:
        unsupported = (
            ("spotify_control", {"action": "search"}),
            ("web_search", {"mode": "search"}),
            ("youtube_video", {"action": "get_info"}),
            ("file_controller", {"action": "read"}),
            ("computer_settings", {"action": "task_manager"}),
        )
        for tool, arguments in unsupported:
            with self.subTest(tool=tool, arguments=arguments):
                self.assertFalse(
                    tool_audit.is_read_only_verification(tool, arguments)
                )

    def test_declared_action_enums_have_risk_classifications(self) -> None:
        actions_dir = Path(__file__).resolve().parent.parent / "actions"
        logs: list[str] = []
        registry = discover_actions(actions_dir, logger=logs.append)
        for declaration in registry.get_tool_declarations():
            name = declaration["name"]
            properties = declaration["parameters"].get("properties", {})
            action_property = properties.get("action") or properties.get("mode")
            values = action_property.get("enum", []) if action_property else []
            for value in values:
                with self.subTest(tool=name, action=value):
                    self.assertNotEqual(
                        tool_audit.classify_risk(
                            name,
                            {
                                "mode" if name == "task_planner" else "action": value
                            },
                        ),
                        "unclassified",
                    )

    def test_records_only_bounded_metadata_not_arguments_or_result(self) -> None:
        secret_arg = "private-recipient@example.test"
        secret_result = "message body that must not be retained"

        event = tool_audit.record(
            "send_message",
            f"status=done action=send_message body={secret_result}",
            12.8,
            {"to": secret_arg},
        )

        self.assertEqual(event.status, "done")
        self.assertEqual(event.risk, "external")
        self.assertEqual(event.effect, "verified")
        self.assertEqual(event.duration_ms, 12)
        self.assertEqual(len(tool_audit.recent()), 1)
        event_text = repr(tool_audit.recent())
        self.assertNotIn(secret_arg, event_text)
        self.assertNotIn(secret_result, event_text)

    def test_recent_events_are_newest_first_and_capped(self) -> None:
        for index in range(tool_audit.MAX_EVENTS + 2):
            tool_audit.record(f"tool-{index}", "legacy result", index)

        events = tool_audit.recent(tool_audit.MAX_EVENTS)

        self.assertEqual(len(events), tool_audit.MAX_EVENTS)
        self.assertEqual(events[0].tool, f"tool-{tool_audit.MAX_EVENTS + 1}")
        self.assertEqual(events[-1].tool, "tool-2")


if __name__ == "__main__":
    unittest.main()
