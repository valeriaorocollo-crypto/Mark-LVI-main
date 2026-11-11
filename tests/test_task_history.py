from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import task_planner as task_planner_action
from core import action_policy, task_history, task_plan, tool_audit


class TaskHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ, {"LOCALAPPDATA": self.temp_dir.name}, clear=False
        )
        self.env_patch.start()
        self.path = (
            Path(self.temp_dir.name) / "MARK-LVI" / "task_history.json"
        )

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def _snapshot(self, task_id: str, **updates):
        snapshot = {
            "task_id": task_id,
            "state": "running",
            "current_step": 1,
            "total_steps": 2,
            "completed": 0,
            "recovery_attempts": 0,
            "recovery_kind": "",
        }
        snapshot.update(updates)
        return snapshot

    def test_history_persists_only_allowlisted_metadata(self) -> None:
        task_history.save_snapshot(
            self._snapshot(
                "task123",
                task="private task title",
                arguments={"password": "do-not-store"},
                result="private page text",
            )
        )
        content = self.path.read_text(encoding="utf-8")
        records = task_history.read_history()

        self.assertNotIn("private task title", content)
        self.assertNotIn("do-not-store", content)
        self.assertNotIn("private page text", content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["task_id"], "task123")
        self.assertEqual(records[0]["state"], "running")

    def test_snapshot_updates_existing_task_and_history_is_newest_first(self) -> None:
        task_history.save_snapshot(self._snapshot("taskA", state="pending"))
        first_created = task_history.read_history()[0]["created_at"]
        task_history.save_snapshot(
            self._snapshot("taskA", state="completed", completed=2)
        )
        task_history.save_snapshot(self._snapshot("taskB", state="failed"))

        records = task_history.read_history()

        self.assertEqual([item["task_id"] for item in records], ["taskB", "taskA"])
        self.assertEqual(records[1]["state"], "completed")
        self.assertEqual(records[1]["created_at"], first_created)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 2)

    def test_history_prunes_old_entries_and_limits_result_count(self) -> None:
        records = []
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        for index in range(3):
            item = self._snapshot(f"old{index}")
            item["created_at"] = old
            item["updated_at"] = old
            records.append(item)
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(records), encoding="utf-8")

        self.assertEqual(task_history.read_history(), [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [])
        with self.assertRaisesRegex(ValueError, "1 to 50"):
            task_history.read_history(0)

    def test_corrupt_history_is_reported_without_replacing_file(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")

        with self.assertRaises(task_history.HistoryStorageError):
            task_history.save_snapshot(self._snapshot("task123"))
        with self.assertRaises(task_history.HistoryStorageError):
            task_history.read_history()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")

    def test_failed_atomic_write_reports_error_and_cleans_temporary_file(self) -> None:
        with patch.object(
            task_history.os, "replace", side_effect=PermissionError("private path")
        ):
            with self.assertRaisesRegex(
                task_history.HistoryStorageError, "PermissionError"
            ):
                task_history.save_snapshot(self._snapshot("task123"))

        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob(".task_history.*.tmp")), [])

    def test_planner_history_mode_returns_metadata_not_task_content(self) -> None:
        task_history.save_snapshot(self._snapshot("task123", state="completed"))
        result = task_plan.history()

        self.assertIn("status=done", result)
        self.assertIn("task123,completed", result)
        self.assertNotIn("arguments", result)

    def test_clear_history_removes_only_persisted_metadata(self) -> None:
        task_history.save_snapshot(self._snapshot("task123", state="completed"))

        cleared = task_history.clear_history()

        self.assertEqual(cleared, 1)
        self.assertEqual(task_history.read_history(), [])
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            [],
        )

    def test_clear_history_preserves_corrupt_file_and_reports_error(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")

        with self.assertRaises(task_history.HistoryStorageError):
            task_history.clear_history()

        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")

    def test_planner_clear_history_reports_count_and_repopulation_caveat(self) -> None:
        task_history.save_snapshot(self._snapshot("task123", state="completed"))

        result = task_plan.clear_history()

        self.assertIn("status=done", result)
        self.assertIn("cleared=1", result)
        self.assertIn("active tasks may create new history snapshots", result)
        self.assertEqual(task_history.read_history(), [])

    def test_tool_schema_routes_explicit_clear_history_mode(self) -> None:
        with patch.object(
            task_plan, "clear_history", return_value="status=done"
        ) as clear_history:
            result = task_planner_action.task_planner(
                {"mode": "clear_history"}
            )

        self.assertEqual(result, "status=done")
        clear_history.assert_called_once_with()
        self.assertIn(
            "clear_history",
            task_planner_action.TOOL["parameters"]["properties"]["mode"]["enum"],
        )

    def test_preview_persists_only_task_operational_metadata(self) -> None:
        steps = [{
            "tool": "computer_control",
            "arguments": {"action": "wait", "seconds": 1},
            "purpose": "private purpose",
            "verification": {
                "tool": "computer_control",
                "arguments": {"action": "inspect_windows", "limit": 5},
                "expect": "private expected text",
            },
        }]

        preview = task_plan.preview("private task title", steps)
        task_id = preview.split("task_id=", 1)[1].split()[0]

        def executor(tool, args):
            self.assertEqual(tool, "computer_control")
            return (
                "status=done action=wait verified=true"
                if args.get("action") == "wait"
                else "status=done action=inspect_windows verified=true "
                "evidence=private expected text"
            )

        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            result = task_plan.execute(
                "private task title",
                steps,
                executor,
                task_id,
            )
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)
        content = self.path.read_text(encoding="utf-8")
        records = task_history.read_history()

        self.assertIn("status=done", result)
        self.assertIn(f'"task_id":"{task_id}"', content)
        self.assertNotIn("private task title", content)
        self.assertNotIn("private purpose", content)
        self.assertNotIn("private expected text", content)
        self.assertEqual(records[0]["state"], "completed")

    def test_history_storage_error_is_reported_without_blocking_execution(self) -> None:
        steps = [{
            "tool": "computer_control",
            "arguments": {"action": "wait", "seconds": 1},
            "purpose": "Wait briefly",
            "verification": {
                "tool": "computer_control",
                "arguments": {"action": "inspect_windows", "limit": 5},
                "expect": "Demo",
            },
        }]
        preview = task_plan.preview("Storage failure", steps)
        task_id = preview.split("task_id=", 1)[1].split()[0]

        def executor(tool, args):
            self.assertEqual(tool, "computer_control")
            return (
                "status=done action=wait verified=true"
                if args.get("action") == "wait"
                else "status=done action=inspect_windows verified=true "
                "evidence=Demo"
            )

        token = action_policy._CONFIRMED_TOOL.set("task_planner")
        try:
            with patch.object(
                task_history,
                "save_snapshot",
                side_effect=task_history.HistoryStorageError(
                    "task history could not be saved (PermissionError)"
                ),
            ):
                result = task_plan.execute(
                    "Storage failure",
                    steps,
                    executor,
                    task_id,
                )
                status = task_plan.status(task_id)
        finally:
            action_policy._CONFIRMED_TOOL.reset(token)

        self.assertIn("status=done", result)
        self.assertIn("history_storage=unavailable", status)
        self.assertIn("PermissionError", status)

    def test_history_action_is_audited_as_read_only_metadata(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk("task_planner", {"mode": "history"}),
            "standard",
        )
        self.assertEqual(
            tool_audit._audit_action(
                "task_planner", {"mode": "history", "history_limit": 5}
            ),
            "history",
        )

    def test_clear_history_is_classified_as_high_impact(self) -> None:
        self.assertEqual(
            tool_audit.classify_risk(
                "task_planner", {"mode": "clear_history"}
            ),
            "high",
        )
