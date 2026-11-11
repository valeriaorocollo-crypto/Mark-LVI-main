from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from core import confirm


class ConfirmationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_request_without_ui_refuses_without_running_action(self) -> None:
        ran = threading.Event()

        result = confirm.request("test", "Do the thing", "details",
                                 lambda: ran.set() or "done")

        self.assertIn("interface is not available", result)
        self.assertFalse(ran.is_set())
        self.assertEqual(confirm.pending_title(), "")

    def test_long_confirmation_detail_is_preserved_in_full(self) -> None:
        shown: list[tuple[str, str]] = []
        detail = "Synthetic content " * 400
        confirm.bind(lambda title, body: shown.append((title, body)), lambda: None)

        result = confirm.request("long-detail", "Review full content", detail,
                                 lambda: "done")

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(shown, [("Review full content", detail)])

    def test_confirmation_log_does_not_store_title_or_details(self) -> None:
        logs: list[str] = []
        title = "Send to private-recipient@example.test"
        detail = "Private message body"
        confirm.bind(lambda _title, _detail: None, lambda: None, logs.append)

        result = confirm.request("send-message", title, detail, lambda: "done")
        self.assertIn("[CONFIRMATION_PENDING]", result)
        confirm.resolve(False)

        self.assertEqual(logs, [
            "SYS: Awaiting confirmation — send-message",
            "SYS: Cancelled — send-message",
        ])
        self.assertNotIn(title, "\n".join(logs))
        self.assertNotIn(detail, "\n".join(logs))

    def test_confirmation_rejects_details_too_long_to_display_safely(self) -> None:
        ran = threading.Event()
        confirm.bind(lambda _title, _detail: None, lambda: None)

        result = confirm.request(
            "oversized-detail",
            "Review content",
            "x" * (confirm.MAX_DETAIL_LENGTH + 1),
            lambda: ran.set() or "done",
        )

        self.assertIn("details exceed", result)
        self.assertFalse(ran.is_set())
        self.assertEqual(confirm.pending_title(), "")

    def test_cancel_does_not_run_action(self) -> None:
        ran = threading.Event()
        confirm.bind(lambda _title, _detail: None, lambda: None)

        result = confirm.request("test-cancel", "Do the thing", "details",
                                 lambda: ran.set() or "done")
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve(False)

        self.assertFalse(ran.wait(0.1))
        self.assertEqual(confirm.pending_title(), "")

    def test_confirm_runs_action_once_off_the_calling_thread(self) -> None:
        ran = threading.Event()
        worker_threads: list[str] = []
        confirm.bind(lambda _title, _detail: None, lambda: None)

        def action() -> str:
            worker_threads.append(threading.current_thread().name)
            ran.set()
            return "done"

        result = confirm.request("test-accept", "Do the thing", "details", action)
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve(True)

        self.assertTrue(ran.wait(2))
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], threading.current_thread().name)

    def test_scoped_session_grant_requires_its_own_hud_choice(self) -> None:
        shown_grants: list[tuple[str, str, str]] = []
        created: list[str] = []
        completed = threading.Event()
        confirm.bind(
            lambda _title, _detail: None,
            lambda: None,
            show_grant=lambda title, detail, label: shown_grants.append(
                (title, detail, label)
            ),
        )

        result = confirm.request(
            "screen-find",
            "Search the current screen?",
            "The screen will be sent to Gemini.",
            lambda: completed.set() or "done",
            grant_action=lambda: created.append("screen"),
            grant_label="Send requested screen captures to Gemini",
        )

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertEqual(
            shown_grants,
            [(
                "Search the current screen?",
                "The screen will be sent to Gemini.",
                "Send requested screen captures to Gemini",
            )],
        )
        self.assertEqual(created, [])
        self.assertFalse(completed.is_set())

        confirm.resolve("grant")

        self.assertTrue(completed.wait(2))
        self.assertEqual(created, ["screen"])

    def test_session_grant_cannot_be_chosen_when_it_was_not_offered(self) -> None:
        ran = threading.Event()
        confirm.bind(lambda _title, _detail: None, lambda: None)

        result = confirm.request(
            "ordinary",
            "Confirm this operation",
            "No reusable permission is offered.",
            lambda: ran.set() or "done",
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve("grant")

        self.assertFalse(ran.wait(0.1))
        self.assertEqual(confirm.pending_title(), "Confirm this operation")
        confirm.resolve(False)

    def test_string_cancel_decision_never_runs_the_action(self) -> None:
        ran = threading.Event()
        confirm.bind(lambda _title, _detail: None, lambda: None)
        confirm.request(
            "cancel-string",
            "Confirm this operation",
            "This is a cancellation regression.",
            lambda: ran.set() or "done",
        )

        confirm.resolve("cancel")

        self.assertFalse(ran.wait(0.1))
        self.assertEqual(confirm.pending_title(), "")

    def test_confirmed_action_logs_only_sanitized_result_status(self) -> None:
        logs: list[str] = []
        completed = threading.Event()

        def log(message: str) -> None:
            logs.append(message)
            if "action status=" in message:
                completed.set()

        confirm.bind(lambda _title, _detail: None, lambda: None, log)
        result = confirm.request(
            "test-result",
            "Do the thing",
            "synthetic details",
            lambda: "status=failed action=test private-result",
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve(True)

        self.assertTrue(completed.wait(2))
        self.assertEqual(
            logs[-1],
            "SYS: Confirmation accepted — test-result; "
            "action status=failed; effect=possible",
        )
        self.assertNotIn("private-result", "\n".join(logs))

    def test_confirmed_action_exception_is_a_failed_audited_result(self) -> None:
        logs: list[str] = []
        completed = threading.Event()

        def log(message: str) -> None:
            logs.append(message)
            if "action status=" in message:
                completed.set()

        def fail_with_private_detail() -> str:
            raise RuntimeError("private exception detail")

        confirm.bind(lambda _title, _detail: None, lambda: None, log)

        result = confirm.request(
            "test-exception",
            "Do the thing",
            "synthetic details",
            fail_with_private_detail,
        )
        self.assertIn("[CONFIRMATION_PENDING]", result)

        confirm.resolve(True)

        self.assertTrue(completed.wait(2))
        self.assertEqual(
            logs[-1],
            "SYS: Confirmation accepted — test-exception; "
            "action status=failed; effect=possible",
        )
        self.assertNotIn("private exception detail", "\n".join(logs))

    def test_second_request_cannot_replace_visible_confirmation(self) -> None:
        entered_show = threading.Event()
        release_show = threading.Event()
        calls: list[str] = []
        first_result: list[str] = []

        def show(title: str, _detail: str) -> None:
            calls.append(title)
            entered_show.set()
            self.assertTrue(release_show.wait(2))

        confirm.bind(show, lambda: None)
        first = threading.Thread(
            target=lambda: first_result.append(
                confirm.request("first", "First action", "one", lambda: "first done")
            )
        )
        first.start()
        self.assertTrue(entered_show.wait(2))

        second_result = confirm.request(
            "second", "Second action", "two", lambda: "second done"
        )
        release_show.set()
        first.join(2)

        self.assertFalse(first.is_alive())
        self.assertEqual(calls, ["First action"])
        self.assertIn("[CONFIRMATION_PENDING]", second_result)
        self.assertIn("First action", second_result)
        self.assertEqual(confirm.pending_title(), "First action")

    def test_failed_hud_request_redacts_exception_details(self) -> None:
        confirm.bind(
            lambda _title, _detail: (_ for _ in ()).throw(
                RuntimeError("private window path")
            ),
            lambda: None,
        )

        result = confirm.request("test-failure", "Do the thing", "details",
                                 lambda: "must not run")

        self.assertIn("RuntimeError", result)
        self.assertIn("Nothing was done", result)
        self.assertNotIn("private window path", result)
        self.assertEqual(confirm.pending_title(), "")

    def test_expired_confirmation_does_not_run_action(self) -> None:
        ran = threading.Event()
        confirm.bind(lambda _title, _detail: None, lambda: None)

        with patch.object(confirm.time, "monotonic", return_value=100.0):
            confirm.request("test-expiry", "Do the thing", "details",
                            lambda: ran.set() or "done")
        with patch.object(confirm.time, "monotonic",
                          return_value=100.0 + confirm.TIMEOUT_SECONDS + 1):
            confirm.resolve(True)

        self.assertFalse(ran.wait(0.1))
        self.assertEqual(confirm.pending_title(), "")


if __name__ == "__main__":
    unittest.main()
