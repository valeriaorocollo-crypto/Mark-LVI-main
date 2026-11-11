from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from actions import background_monitor
from core import confirm, tool_audit


class BackgroundMonitorConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        self.logs: list[str] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
            self.logs.append,
        )

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_add_requires_approval_and_cancel_does_not_save_topic(self) -> None:
        state: dict = {}
        saved = threading.Event()

        def save(value: dict) -> None:
            state.clear()
            state.update(value)
            saved.set()

        with (
            patch.object(background_monitor, "_load", side_effect=lambda: dict(state)),
            patch.object(background_monitor, "_save", side_effect=save) as save_mock,
        ):
            result = background_monitor.add_monitor("Peru space news")

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Peru space news", self.prompts[-1][1])
            self.assertFalse(saved.is_set())

            confirm.resolve(False)

            self.assertFalse(saved.wait(0.1))
            save_mock.assert_not_called()
            self.assertEqual(state, {})

    def test_approved_remove_deletes_only_exactly_previewed_topic(self) -> None:
        state = {
            "peru_space_news": {"topic": "Peru space news"},
            "peru_space_policy": {"topic": "Peru space policy"},
        }
        saved = threading.Event()

        def save(value: dict) -> None:
            state.clear()
            state.update(value)
            saved.set()

        with (
            patch.object(background_monitor, "_load", side_effect=lambda: dict(state)),
            patch.object(background_monitor, "_save", side_effect=save),
        ):
            result = background_monitor.remove_monitor("Peru space news")

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Peru space news", self.prompts[-1][1])
            confirm.resolve(True)

            self.assertTrue(saved.wait(2))
            self.assertEqual(set(state), {"peru_space_policy"})

    def test_ambiguous_partial_remove_does_not_change_monitors(self) -> None:
        state = {
            "peru_space_news": {"topic": "Peru space news"},
            "peru_space_policy": {"topic": "Peru space policy"},
        }
        with (
            patch.object(background_monitor, "_load", return_value=state),
            patch.object(background_monitor, "_save") as save,
        ):
            result = background_monitor.remove_monitor("Peru space")

        self.assertIn("status=ask", result)
        self.assertEqual(self.prompts, [])
        save.assert_not_called()
        self.assertEqual(len(state), 2)

    def test_add_monitor_risk_is_high_but_listing_is_read_only(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk("manage_monitor", {"action": "add"}),
            "high",
        )
        self.assertEqual(
            tool_audit.classify_risk("manage_monitor", {"action": "list"}),
            "read_or_navigate",
        )


if __name__ == "__main__":
    unittest.main()
