from __future__ import annotations

import json
import threading
import unittest
import re
import time
from unittest.mock import patch

from core import action_policy, outcome, task_plan, tool_audit


class TaskPlanExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history_patch = patch.object(
            task_plan.task_history, "save_snapshot", return_value=None
        )
        self.history_patch.start()
        self.steps = [{
            "tool": "computer_control",
            "arguments": {"action": "wait", "seconds": 1},
            "purpose": "Wait briefly",
            "verification": {
                "tool": "computer_control",
                "arguments": {"action": "inspect_windows", "limit": 5},
                "expect": "Demo",
            },
        }]

    def tearDown(self) -> None:
        self.history_patch.stop()

    def test_execution_requires_hud_approval(self) -> None:
        result = task_plan.execute("Approved later", self.steps, lambda *_: "")
        self.assertIn("status=failed", result)
        self.assertIn("confirmation HUD", result)

    def test_real_wait_step_proceeds_directly_to_read_only_verification(self) -> None:
        from actions import computer_control

        preview = task_plan.preview("Wait then verify", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        calls: list[str] = []

        def executor(tool, args):
            calls.append(args["action"])
            if args["action"] == "wait":
                return computer_control.computer_control(args)
            return (
                "status=done action=inspect_windows verified=true evidence=Demo"
            )

        with patch.object(computer_control.time, "sleep") as sleep:
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                result = task_plan.execute(
                    "Wait then verify", self.steps, executor, task_id
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=done", result)
        self.assertEqual(calls, ["wait", "inspect_windows"])
        sleep.assert_called_once_with(1.0)

    def test_preview_bounds_registry_and_evicts_old_pending_plan(self) -> None:
        with (
            patch.dict(task_plan._tasks, {}, clear=True),
            patch.object(task_plan, "MAX_TASK_RECORDS", 2),
        ):
            first = task_plan.preview("First plan", self.steps)
            first_id = re.search(r"task_id=(\w+)", first).group(1)
            second = task_plan.preview("Second plan", self.steps)
            third = task_plan.preview("Third plan", self.steps)

            self.assertIn("status=done", third)
            self.assertEqual(len(task_plan._tasks), 2)
            self.assertNotIn(first_id, task_plan._tasks)

    def test_preview_fails_when_registry_is_full_of_active_tasks(self) -> None:
        with (
            patch.dict(task_plan._tasks, {}, clear=True),
            patch.object(task_plan, "MAX_TASK_RECORDS", 2),
        ):
            for task_id, state in (
                ("active-task", "running"),
                ("waiting-task", "waiting_for_user"),
            ):
                task_plan._tasks[task_id] = task_plan.TaskRecord(
                    task_id, task_id, [], state
                )

            result = task_plan.preview("Blocked plan", self.steps)

            self.assertIn("status=failed", result)
            self.assertIn("task registry is full", result)
            self.assertEqual(
                {record.state for record in task_plan._tasks.values()},
                {"running", "waiting_for_user"},
            )

    def test_ambiguous_action_requires_manual_read_only_recovery(self) -> None:
        calls: list[tuple[str, dict]] = []
        preview = task_plan.preview("Recover safely", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )
        def executor(tool, args):
            calls.append((tool, args))
            if args.get("action") == "wait":
                return (
                    "status=unverified action=wait recovery=focus_lost "
                    "reason=synthetic"
                )
            return "status=done action=inspect_windows verified=true evidence=Demo"

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute("Recover safely", self.steps, executor, task_id)
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("state=recovery_required", task_plan.status(task_id))
            self.assertIn("not be repeated", task_plan.status(task_id))
            self.assertIn("recovery=focus_lost", task_plan.status(task_id))
            self.assertIn("status=done", task_plan.resume(task_id))
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual([args["action"] for _, args in calls], [
            "wait", "inspect_windows"
        ])

    def test_recovery_taxonomy_never_repeats_effectful_action(self) -> None:
        for recovery_kind in sorted(task_plan.RECOVERY_KINDS):
            with self.subTest(recovery=recovery_kind):
                preview = task_plan.preview(
                    f"Recover {recovery_kind}", self.steps
                )
                task_id = re.search(r"task_id=(\w+)", preview).group(1)
                recovery = threading.Event()
                calls: list[str] = []
                results: list[str] = []
                progress_events: list[tuple] = []

                def on_progress(*event):
                    progress_events.append(event)
                    if event[2] == "recovery_required":
                        recovery.set()

                task_plan.bind_progress(on_progress)

                def executor(_tool, args):
                    action = args["action"]
                    calls.append(action)
                    if action == "wait":
                        return (
                            "status=unverified action=wait "
                            f"recovery={recovery_kind} reason=synthetic"
                        )
                    return (
                        "status=done action=inspect_windows verified=true "
                        "evidence=Demo"
                    )

                def run():
                    token = action_policy._CONFIRMED_TOOL.set("task_planner")
                    try:
                        results.append(
                            task_plan.execute(
                                f"Recover {recovery_kind}",
                                self.steps,
                                executor,
                                task_id,
                            )
                        )
                    finally:
                        action_policy._CONFIRMED_TOOL.reset(token)

                worker = threading.Thread(target=run)
                worker.start()
                try:
                    self.assertTrue(recovery.wait(2), recovery_kind)
                    recovery_status = task_plan.status(task_id)
                    self.assertIn("state=recovery_required", recovery_status)
                    self.assertIn(f"recovery={recovery_kind}", recovery_status)
                    self.assertIn("status=done", task_plan.resume(task_id))
                    worker.join(2)
                    self.assertFalse(worker.is_alive(), recovery_kind)
                finally:
                    if worker.is_alive():
                        task_plan.cancel(task_id)
                        worker.join(2)
                    task_plan.bind_progress(None)

                self.assertIn("status=done", results[0], recovery_kind)
                self.assertEqual(
                    calls,
                    ["wait", "inspect_windows"],
                    recovery_kind,
                )

    def test_verification_exception_recovers_as_unreadable_without_repeating_action(self):
        preview = task_plan.preview("Recover unreadable state", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        verification_calls = 0
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(_tool, args):
            nonlocal verification_calls
            self.assertEqual(_tool, "computer_control")
            action = args["action"]
            calls.append(action)
            if action == "wait":
                return "status=done action=wait verified=true"
            verification_calls += 1
            if verification_calls == 1:
                raise RuntimeError("synthetic read failure")
            return (
                "status=done action=inspect_windows verified=true evidence=Demo"
            )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Recover unreadable state", self.steps, executor, task_id
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("state=recovery_required", task_plan.status(task_id))
            self.assertIn("recovery=state_unreadable", task_plan.status(task_id))
            task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows", "inspect_windows"])

    def test_action_exception_is_ambiguous_and_recovery_only_rechecks(self):
        preview = task_plan.preview("Recover action exception", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(_tool, args):
            action = args["action"]
            calls.append(action)
            if action == "wait":
                raise RuntimeError("synthetic action failure")
            return (
                "status=done action=inspect_windows verified=true evidence=Demo"
            )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Recover action exception", self.steps, executor, task_id
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("state=recovery_required", task_plan.status(task_id))
            self.assertIn("recovery=effect_ambiguous", task_plan.status(task_id))
            task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_cancel_during_recovery_never_runs_action_or_verifier_again(self):
        preview = task_plan.preview("Cancel ambiguous recovery", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(_tool, args):
            action = args["action"]
            calls.append(action)
            return (
                "status=unverified action=wait recovery=effect_ambiguous "
                "reason=synthetic"
                if action == "wait"
                else "status=done action=inspect_windows verified=true "
                "evidence=Demo"
            )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Cancel ambiguous recovery", self.steps, executor, task_id
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("state=recovery_required", task_plan.status(task_id))
            self.assertIn("state=cancelled", task_plan.cancel(task_id))
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=unverified", results[0])
        self.assertIn("state=cancelled", results[0])
        self.assertEqual(calls, ["wait"])

    def test_structured_uia_result_recovery_is_consumed_without_retry(self):
        preview = task_plan.preview("Recover structured UIA result", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(tool, args):
            self.assertEqual(tool, "computer_control")
            action = args["action"]
            calls.append(action)
            if action == "wait":
                return json.dumps({
                    "status": "unverified",
                    "recovery": "effect_ambiguous",
                    "verified": False,
                })
            return (
                "status=done action=inspect_windows verified=true evidence=Demo"
            )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Recover structured UIA result",
                        self.steps,
                        executor,
                        task_id,
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("recovery=effect_ambiguous", task_plan.status(task_id))
            task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_browser_timeout_result_requires_recovery_without_repeating_action(self):
        preview = task_plan.preview("Recover timed out action", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(tool, args):
            self.assertEqual(tool, "computer_control")
            action = args["action"]
            calls.append(action)
            if action == "wait":
                return (
                    "status=unverified action=click recovery=timeout "
                    "reason=synthetic browser timeout"
                )
            return "status=done action=inspect_windows verified=true evidence=Demo"

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Recover timed out action", self.steps, executor, task_id
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            self.assertIn("recovery=timeout", task_plan.status(task_id))
            task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_task_timeout_never_repeats_an_action(self) -> None:
        preview = task_plan.preview("Bound execution time", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def executor(tool, args):
            calls.append(args["action"])
            if args["action"] == "wait":
                time.sleep(0.03)
                return "status=done action=wait verified=true"
            return "status=done action=inspect_windows verified=true evidence=Demo"

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute(
                        "Bound execution time", self.steps, executor, task_id
                    )
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        with patch.object(task_plan, "MAX_TASK_RUNTIME_SECONDS", 0.01):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(recovery.wait(2))
                self.assertIn("runtime limit", task_plan.status(task_id))
                task_plan.resume(task_id)
                worker.join(2)
                self.assertFalse(worker.is_alive())
            finally:
                if worker.is_alive():
                    task_plan.cancel(task_id)
                    worker.join(2)
                task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_human_wait_does_not_consume_active_task_budget(self) -> None:
        for wait_kind in ("checkpoint", "recovery"):
            with self.subTest(wait=wait_kind):
                preview = task_plan.preview(
                    f"Preserve budget during {wait_kind}", self.steps
                )
                task_id = re.search(r"task_id=(\w+)", preview).group(1)
                record = task_plan._tasks[task_id]
                record.state = "running"
                record.deadline_at = 110.0
                waiting = threading.Event()
                wait_results: list[bool] = []
                task_plan.bind_progress(
                    lambda *event: waiting.set()
                    if event[2] == (
                        "waiting_for_user"
                        if wait_kind == "checkpoint"
                        else "recovery_required"
                    )
                    else None
                )

                def wait():
                    if wait_kind == "checkpoint":
                        wait_results.append(
                            task_plan._wait_for_user(
                                record, "Complete the synthetic checkpoint"
                            )
                        )
                    else:
                        wait_results.append(
                            task_plan._wait_for_recovery(
                                record, 1, "synthetic timeout", "timeout"
                            )
                        )

                with patch.object(
                    task_plan.time,
                    "monotonic",
                    side_effect=[105.0, 1000.0],
                ):
                    worker = threading.Thread(target=wait)
                    worker.start()
                    try:
                        self.assertTrue(waiting.wait(2), wait_kind)
                        self.assertIn("status=done", task_plan.resume(task_id))
                        worker.join(2)
                        self.assertFalse(worker.is_alive(), wait_kind)
                    finally:
                        if worker.is_alive():
                            task_plan.cancel(task_id)
                            worker.join(2)
                        task_plan.bind_progress(None)

                self.assertEqual(wait_results, [True])
                self.assertEqual(record.deadline_at, 1005.0)
                with patch.object(task_plan.time, "monotonic", return_value=1004.0):
                    self.assertFalse(task_plan._task_expired(record))

    def test_execution_rejects_done_without_verified_true(self) -> None:
        preview = task_plan.preview("Reject false verification", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        calls: list[tuple[str, dict]] = []
        recovery = threading.Event()
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(task_plan.execute(
                    "Reject false verification",
                    self.steps,
                    lambda tool, args: calls.append((tool, args))
                    or (
                        "status=done action=wait verified=false"
                        if args.get("action") == "wait"
                        else "status=done action=inspect_windows "
                        "verified=false evidence=Demo"
                    ),
                    task_id,
                ))
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            for _ in range(task_plan.MAX_RECOVERY_ATTEMPTS):
                self.assertTrue(recovery.wait(2))
                recovery.clear()
                task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=unverified", results[0])
        self.assertEqual([args["action"] for _, args in calls].count("wait"), 1)

    def test_verification_ignores_outcome_metadata_as_evidence(self) -> None:
        result = outcome.normalize_dispatch_result(
            "browser_control",
            json.dumps({
                "status": "done",
                "action": "get_text",
                "text": outcome.untrusted("webpage", "Synthetic page evidence"),
                "verified": True,
            }),
        )

        evidence = task_plan._verification_evidence(result)

        self.assertEqual(task_plan._status(result), outcome.DONE)
        self.assertIn("Synthetic page evidence", evidence)
        self.assertNotIn("verified=true", evidence)
        self.assertNotIn('"status": "done"', evidence)

    def test_verification_ignores_echoed_search_arguments_and_counts(self) -> None:
        result = (
            "status=done action=search query=Steam count=0 "
            "max_results=5 verified=true"
        )

        evidence = task_plan._verification_evidence(result)

        self.assertEqual(evidence, "")

    def test_cancel_prevents_execution(self) -> None:
        preview = task_plan.preview("Cancel safely", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)

        self.assertIn("state=cancelled", task_plan.cancel(task_id))
        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            result = task_plan.execute(
                "Cancel safely", self.steps, lambda *_: "", task_id
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=failed", result)
        self.assertIn("already cancelled", result)

    def test_cancel_during_final_step_does_not_report_completion(self) -> None:
        preview = task_plan.preview("Cancel active step", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        calls: list[tuple[str, dict]] = []
        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            def executor(tool, args):
                calls.append((tool, args))
                task_plan.cancel(task_id)
                return "status=done action=wait verified=true"

            result = task_plan.execute(
                "Cancel active step", self.steps, executor, task_id
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=unverified", result)
        self.assertIn("state=cancelled", result)
        self.assertEqual(len(calls), 1)
        self.assertIn("state=cancelled", task_plan.status(task_id))

    def test_status_reports_preview_state(self) -> None:
        preview = task_plan.preview("Inspect state", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)

        self.assertIn("state=pending", task_plan.status(task_id))

    def test_planned_human_checkpoint_waits_before_verification(self) -> None:
        step = dict(self.steps[0], wait_for_user="Complete the sign-in and MFA prompt")
        preview = task_plan.preview("Sign in safely", [step])
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        waiting = threading.Event()
        calls: list[tuple[str, dict]] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: waiting.set()
            if event[2] == "waiting_for_user" and "MFA" in event[5]
            else None
        )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(task_plan.execute(
                    "Sign in safely",
                    [step],
                    lambda tool, args: calls.append((tool, args))
                    or (
                        "status=unverified action=wait reason=login needed"
                        if args.get("action") == "wait"
                        else "status=done action=inspect_windows verified=true evidence=Demo"
                    ),
                    task_id,
                ))
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(waiting.wait(2))
            self.assertEqual([call[1]["action"] for call in calls], ["wait"])
            self.assertIn("state=waiting_for_user", task_plan.status(task_id))
            self.assertIn("MFA", task_plan.status(task_id))
            self.assertIn("status=done", task_plan.resume(task_id))
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIn("status=done", results[0])
            self.assertEqual(len(calls), 2)
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

    def test_pause_button_waits_after_active_action_then_verifies(self) -> None:
        preview = task_plan.preview("Pause between steps", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        paused = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: paused.set() if event[2] == "paused" else None
        )

        def executor(*call):
            args = call[1]
            calls.append(args["action"])
            if args["action"] == "wait":
                task_plan.pause(task_id)
                return "status=done action=wait verified=true"
            return "status=done action=inspect_windows verified=true evidence=Demo"

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(task_plan.execute(
                    "Pause between steps", self.steps, executor, task_id
                ))
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(paused.wait(2))
            self.assertEqual(calls, ["wait"])
            self.assertIn("state=paused", task_plan.status(task_id))
            self.assertIn("status=done", task_plan.resume(task_id))
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(calls, ["wait", "inspect_windows"])
            self.assertIn("status=done", results[0])
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

    def test_cancel_while_waiting_for_user_unblocks_plan(self) -> None:
        step = dict(self.steps[0], wait_for_user="Resolve the unexpected dialog")
        preview = task_plan.preview("Cancel waiting plan", [step])
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        waiting = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: waiting.set()
            if event[2] == "waiting_for_user"
            else None
        )

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(task_plan.execute(
                    "Cancel waiting plan",
                    [step],
                    lambda *call: calls.append(call[1]["action"])
                    or "status=done action=wait verified=true",
                    task_id,
                ))
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(waiting.wait(2))
            self.assertIn("state=cancelled", task_plan.cancel(task_id))
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(calls, ["wait"])
            self.assertIn("status=unverified", results[0])
            self.assertIn("state=cancelled", results[0])
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

    def test_plan_authorization_is_exact(self) -> None:
        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            with action_policy.authorize_plan(
                [("computer_control", {"action": "wait", "seconds": 1})]
            ):
                self.assertEqual(
                    action_policy.dispatch(
                        "computer_control",
                        {"action": "wait", "seconds": 1},
                        lambda: "status=done action=wait verified=true",
                    ),
                    "status=done action=wait verified=true",
                )
                self.assertEqual(
                    tool_audit.classify_risk(
                        "task_planner", {"mode": "execute"}
                    ),
                    "high",
                )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

    def test_execution_requires_matching_read_only_evidence(self) -> None:
        preview = task_plan.preview("Verify evidence", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        calls: list[tuple[str, dict]] = []
        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            result = task_plan.execute(
                "Verify evidence",
                self.steps,
                lambda tool, args: calls.append((tool, args))
                or (
                    "status=done action=wait verified=true"
                    if args.get("action") == "wait"
                    else "status=done action=inspect_windows verified=true"
                    " evidence=Demo"
                ),
                task_id,
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=done", result)
        self.assertEqual(len(calls), 2)

    def test_running_task_cannot_be_started_twice(self) -> None:
        preview = task_plan.preview("No duplicate effects", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        record = task_plan._tasks[task_id]
        record.state = "running"

        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            result = task_plan.execute(
                "No duplicate effects", self.steps, lambda *_: "", task_id
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=failed", result)
        self.assertIn("already running", result)

    def test_completed_task_id_cannot_repeat_effects(self) -> None:
        preview = task_plan.preview("No completed replay", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        calls: list[str] = []

        def executor(_tool, args):
            action = args["action"]
            calls.append(action)
            if action == "wait":
                return "status=done action=wait verified=true"
            return (
                "status=done action=inspect_windows verified=true evidence=Demo"
            )

        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            first_result = task_plan.execute(
                "No completed replay", self.steps, executor, task_id
            )
            replay_result = task_plan.execute(
                "No completed replay", self.steps, executor, task_id
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=done", first_result)
        self.assertIn("status=failed", replay_result)
        self.assertIn("already completed", replay_result)
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_preview_rejects_effectful_verifier(self) -> None:
        step = dict(self.steps[0])
        step["verification"] = {
            "tool": "computer_control",
            "arguments": {"action": "click", "x": 1, "y": 1},
            "expect": "clicked",
        }

        result = task_plan.preview("Unsafe evidence", [step])

        self.assertIn("status=failed", result)
        self.assertIn("read-only", result)

    def test_preview_rejects_browser_navigation_as_verification(self) -> None:
        step = dict(self.steps[0])
        step["verification"] = {
            "tool": "browser_control",
            "arguments": {
                "action": "go_to",
                "url": "https://example.test/next",
            },
            "expect": "https://example.test/next",
        }

        result = task_plan.preview("No navigation verifier", [step])

        self.assertIn("status=failed", result)
        self.assertIn("explicitly read-only", result)

    def test_form_preview_shows_values_and_redacts_sensitive_fields(self) -> None:
        step = {
            "tool": "browser_control",
            "arguments": {
                "action": "fill_form",
                "fields": {
                    'input[name="email"]': "person@example.test",
                    'input[name="password"]': "secret-value",
                    'input[name="credential"]': "credential-value",
                },
            },
            "purpose": "Fill the sign-in form",
            "verification": {
                "tool": "browser_control",
                "arguments": {"action": "get_url"},
                "expect": "https://example.test",
            },
        }

        result = task_plan.preview("Fill form", [step])

        self.assertIn("form_preview=", result)
        self.assertIn("person@example.test", result)
        self.assertIn("[REDACTED]", result)
        self.assertNotIn("secret-value", result)
        self.assertNotIn("credential-value", result)

    def test_executor_exception_can_recover_by_verifying_without_retry(self) -> None:
        preview = task_plan.preview("Executor error", self.steps)
        task_id = re.search(r"task_id=(\w+)", preview).group(1)
        recovery = threading.Event()
        calls: list[str] = []
        results: list[str] = []
        task_plan.bind_progress(
            lambda *event: recovery.set()
            if event[2] == "recovery_required"
            else None
        )
        def executor(tool, args):
            calls.append(args["action"])
            if args["action"] == "wait":
                raise RuntimeError("private detail")
            return "status=done action=inspect_windows verified=true evidence=Demo"

        def run():
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                results.append(
                    task_plan.execute("Executor error", self.steps, executor, task_id)
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(recovery.wait(2))
            task_plan.resume(task_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                task_plan.cancel(task_id)
                worker.join(2)
            task_plan.bind_progress(None)

        self.assertIn("status=done", results[0])
        self.assertNotIn("private detail", results[0])
        self.assertEqual(calls, ["wait", "inspect_windows"])

    def test_plan_rejects_non_json_arguments(self) -> None:
        step = dict(self.steps[0])
        step["arguments"] = {"action": "wait", "seconds": object()}

        result = task_plan.preview("Invalid JSON", [step])

        self.assertIn("status=failed", result)
        self.assertIn("JSON-compatible", result)
