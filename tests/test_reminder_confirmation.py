from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from actions import reminder
from core import confirm, tool_audit


class ReminderConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    @staticmethod
    def future_args(message: str = "Synthetic reminder") -> dict[str, str]:
        target = datetime.now() + timedelta(days=1)
        return {
            "date": target.strftime("%Y-%m-%d"),
            "time": target.strftime("%H:%M"),
            "message": message,
        }

    def test_schedule_waits_for_approval_and_cancel_does_not_create_job(self) -> None:
        scheduled = threading.Event()
        with (
            patch.object(reminder, "_get_os", return_value="windows"),
            patch.object(reminder, "_write_notify_script", return_value=object()) as write_script,
            patch.object(
                reminder,
                "_schedule_windows",
                side_effect=lambda *_args: scheduled.set() or "task-id",
            ) as schedule,
        ):
            result = reminder.reminder(self.future_args())

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Synthetic reminder", self.prompts[-1][1])
            self.assertIn("Date:", self.prompts[-1][1])
            write_script.assert_not_called()
            schedule.assert_not_called()

            confirm.resolve(False)

            self.assertFalse(scheduled.wait(0.1))
            write_script.assert_not_called()
            schedule.assert_not_called()

    def test_approval_schedules_once(self) -> None:
        scheduled = threading.Event()
        script = object()

        with (
            patch.object(reminder, "_get_os", return_value="windows"),
            patch.object(reminder, "_write_notify_script", return_value=script) as write_script,
            patch.object(
                reminder,
                "_schedule_windows",
                side_effect=lambda *_args: scheduled.set() or "task-id",
            ) as schedule,
        ):
            result = reminder.reminder(self.future_args())
            self.assertIn("[CONFIRMATION_PENDING]", result)

            confirm.resolve(True)

            self.assertTrue(scheduled.wait(2))
            write_script.assert_called_once()
            schedule.assert_called_once()

    def test_invalid_or_overlong_reminder_is_rejected(self) -> None:
        result = reminder.reminder(self.future_args("x" * 201))

        self.assertIn("status=failed", result)
        self.assertEqual(self.prompts, [])

    def test_reminder_schedule_is_high_risk(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk("reminder", {"action": "schedule"}),
            "high",
        )


if __name__ == "__main__":
    unittest.main()
