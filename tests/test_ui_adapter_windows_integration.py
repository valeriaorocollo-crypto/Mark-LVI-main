from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
import re
import json
from unittest.mock import patch

from core import ui_adapter
from core import action_policy, task_plan
from core.action_loader import ActionRecord, ActionRegistry
from actions import computer_control


_RUN_INTEGRATION = os.environ.get("MARK_RUN_UIA_INTEGRATION") == "1"


@unittest.skipUnless(
    sys.platform == "win32" and _RUN_INTEGRATION,
    "opt-in Windows UI Automation integration test",
)
class WindowsUiAdapterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._history_patch = patch.object(
            task_plan.task_history, "save_snapshot", return_value=None
        )
        self._history_patch.start()

    def tearDown(self) -> None:
        self._history_patch.stop()

    def _start_message_box(self) -> tuple[subprocess.Popen[bytes], str]:
        window_title = "MARK UIA Synthetic Test"
        script = (
            "import ctypes\n"
            f"ctypes.windll.user32.MessageBoxW("
            f"0, 'Synthetic UIA test', {window_title!r}, 0x40)\n"
        )
        return (
            subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            window_title,
        )

    def _start_edit_window(self) -> tuple[subprocess.Popen[bytes], str]:
        window_title = "MARK UIA Synthetic Edit Test"
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MARK UIA Synthetic Edit Test'
$form.Width = 520
$form.Height = 180
$form.TopMost = $true
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Synthetic field'
$label.Left = 20
$label.Top = 20
$label.Width = 180
$form.Controls.Add($label)
$edit = New-Object System.Windows.Forms.TextBox
$edit.Name = 'SyntheticInput'
$edit.AccessibleName = 'Synthetic input'
$edit.Text = 'Initial synthetic value'
$edit.Left = 20
$edit.Top = 50
$edit.Width = 450
$form.Controls.Add($edit)
$button = New-Object System.Windows.Forms.Button
$button.Name = 'ApplySyntheticValue'
$button.AccessibleName = 'Apply synthetic value'
$button.Text = 'Apply synthetic value'
$button.Left = 20
$button.Top = 90
$button.Width = 220
$form.Controls.Add($button)
[System.Windows.Forms.Application]::Run($form)
"""
        return (
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy",
                    "Bypass", "-Command", script,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            window_title,
        )

    def test_focus_control_on_local_synthetic_window(self) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            result = {"status": "not_found"}
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) != 1:
                    time.sleep(0.2)
                    continue
                controls = [
                    control for control in windows[0].descendants()[:100]
                    if str(control.element_info.control_type or "") == "Button"
                    and str(control.element_info.automation_id or "") == "2"
                ]
                if len(controls) != 1:
                    time.sleep(0.2)
                    continue
                control = controls[0].element_info
                selector = {
                    "window_name": window_title,
                    "name": str(control.name or ""),
                    "control_type": str(control.control_type or ""),
                    "automation_id": str(control.automation_id or ""),
                }
                result = ui_adapter.focus_control(selector)
                if result["status"] != "not_found":
                    break
                time.sleep(0.2)

            self.assertEqual(result["status"], "done", result)
            self.assertTrue(result["verified"], result)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_uia_focus_selector_matrix_measures_exact_and_near_miss_targets(
        self,
    ) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            selector = None
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 1:
                    controls = [
                        control for control in windows[0].descendants()[:100]
                        if str(control.element_info.control_type or "") == "Button"
                        and str(control.element_info.automation_id or "") == "2"
                    ]
                    if len(controls) == 1:
                        info = controls[0].element_info
                        selector = {
                            "window_name": window_title,
                            "name": str(info.name or ""),
                            "control_type": str(info.control_type or ""),
                            "automation_id": str(info.automation_id or ""),
                        }
                        break
                time.sleep(0.2)

            self.assertIsNotNone(selector)
            correct = ui_adapter.focus_control(selector)
            self.assertEqual(correct["status"], "done", correct)
            self.assertTrue(correct["verified"], correct)

            near_misses = (
                dict(selector, name=f"{selector['name']} (wrong target)"),
                dict(selector, control_type="Edit"),
                dict(selector, automation_id="wrong-automation-id"),
            )
            blocked = [
                ui_adapter.focus_control(candidate)
                for candidate in near_misses
            ]
            self.assertEqual(
                [result["status"] for result in blocked],
                ["not_found"] * len(near_misses),
            )
            self.assertTrue(
                all(not result["verified"] for result in blocked), blocked
            )
            self.assertIsNone(
                process.poll(),
                "near-miss selectors must not activate or close the dialog",
            )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_focus_control_stops_when_window_disappears(self) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            selector = None
            seen_controls = []
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 1:
                    controls = [
                        control for control in windows[0].descendants()[:100]
                        if str(control.element_info.control_type or "") == "Button"
                        and str(control.element_info.automation_id or "") == "2"
                    ]
                    if len(controls) == 1:
                        info = controls[0].element_info
                        selector = {
                            "window_name": window_title,
                            "name": str(info.name or ""),
                            "control_type": str(info.control_type or ""),
                            "automation_id": str(info.automation_id or ""),
                        }
                        break
                time.sleep(0.2)

            self.assertIsNotNone(selector)
            process.terminate()
            process.wait(timeout=5)
            result = ui_adapter.focus_control(selector)

            self.assertIn(result["status"], {"not_found", "failed"}, result)
            self.assertFalse(result["verified"], result)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_focus_window_activates_local_synthetic_window(self) -> None:
        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = computer_control._focus_window(window_title)
                if "status=done" in result:
                    break
                time.sleep(0.2)

            self.assertIn("status=done", result)
            self.assertIn("verified=true", result)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_uia_activate_window_verifies_local_synthetic_window(self) -> None:
        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            result = {"status": "not_found", "verified": False}
            while time.monotonic() < deadline:
                result = ui_adapter.activate_window(window_title)
                if result["status"] != "not_found":
                    break
                time.sleep(0.2)

            self.assertEqual(result["status"], "done", result)
            self.assertTrue(result["verified"], result)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_uia_invoke_control_reports_closed_window_as_unverified(self) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            result = {"status": "not_found", "verified": False}
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 1:
                    controls = [
                        control for control in windows[0].descendants()[:100]
                        if str(control.element_info.control_type or "") == "Button"
                        and str(control.element_info.automation_id or "") == "2"
                    ]
                    if len(controls) == 1:
                        info = controls[0].element_info
                        selector = {
                            "window_name": window_title,
                            "name": str(info.name or ""),
                            "control_type": str(info.control_type or ""),
                            "automation_id": str(info.automation_id or ""),
                        }
                        result = ui_adapter.invoke_control(selector)
                        break
                time.sleep(0.2)

            self.assertEqual(result["status"], "unverified", result)
            self.assertEqual(result["recovery"], "window_changed", result)
            self.assertFalse(result["verified"], result)
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_uia_invoke_control_rejects_wrong_selector_without_effect(self) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_message_box()
        try:
            deadline = time.monotonic() + 10
            selector = None
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 1:
                    controls = [
                        control for control in windows[0].descendants()[:100]
                        if str(control.element_info.control_type or "") == "Button"
                        and str(control.element_info.automation_id or "") == "2"
                    ]
                    if len(controls) == 1:
                        info = controls[0].element_info
                        selector = {
                            "window_name": window_title,
                            "name": f"{info.name} (wrong target)",
                            "control_type": str(info.control_type or ""),
                            "automation_id": str(info.automation_id or ""),
                        }
                        break
                time.sleep(0.2)

            self.assertIsNotNone(selector)
            result = ui_adapter.invoke_control(selector)

            self.assertEqual(result["status"], "not_found", result)
            self.assertFalse(result["verified"], result)
            self.assertIsNone(process.poll(), "wrong selector must not close dialog")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_uia_invoke_control_rejects_duplicate_windows(self) -> None:
        from pywinauto import Desktop

        processes_and_titles = [
            self._start_message_box(),
            self._start_message_box(),
        ]
        processes = [item[0] for item in processes_and_titles]
        window_title = processes_and_titles[0][1]
        try:
            deadline = time.monotonic() + 10
            windows = []
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 2:
                    break
                time.sleep(0.2)

            self.assertEqual(len(windows), 2)
            controls = [
                control for control in windows[0].descendants()[:100]
                if str(control.element_info.control_type or "") == "Button"
                and str(control.element_info.automation_id or "") == "2"
            ]
            self.assertEqual(len(controls), 1)
            info = controls[0].element_info
            result = ui_adapter.invoke_control({
                "window_name": window_title,
                "name": str(info.name or ""),
                "control_type": str(info.control_type or ""),
                "automation_id": str(info.automation_id or ""),
            })

            self.assertEqual(result["status"], "ambiguous", result)
            self.assertEqual(result["recovery"], "target_ambiguous", result)
            self.assertFalse(result["verified"], result)
            self.assertTrue(all(process.poll() is None for process in processes))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_task_plan_activates_and_verifies_synthetic_window(self) -> None:
        process, window_title = self._start_message_box()
        task_plan.bind_progress(
            lambda task_id, _task, state, _current, _total, _reason:
            task_plan.resume(task_id)
            if state == "recovery_required"
            else None
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                preview = task_plan.preview(
                    "Activate synthetic window",
                    [{
                        "tool": "computer_control",
                        "arguments": {
                            "action": "activate_window",
                            "title": window_title,
                        },
                        "purpose": "Activate the synthetic window",
                        "verification": {
                            "tool": "computer_control",
                            "arguments": {
                                "action": "inspect_windows",
                                "limit": 50,
                            },
                            "expect": window_title,
                        },
                    }],
                )
                task_id_match = re.search(r"task_id=(\w+)", preview)
                if task_id_match:
                    task_id = task_id_match.group(1)
                    token = action_policy._CONFIRMED_TOOL.set("task_planner")
                    try:
                        result = task_plan.execute(
                            "Activate synthetic window",
                            [{
                                "tool": "computer_control",
                                "arguments": {
                                    "action": "activate_window",
                                    "title": window_title,
                                },
                                "purpose": "Activate the synthetic window",
                                "verification": {
                                    "tool": "computer_control",
                                    "arguments": {
                                        "action": "inspect_windows",
                                        "limit": 50,
                                    },
                                    "expect": window_title,
                                },
                            }],
                            lambda _tool, args: computer_control.computer_control(args),
                            task_id,
                        )
                    finally:
                        action_policy._CONFIRMED_TOOL.reset(token)
                    if "status=done" in result:
                        self.assertIn("verified=true", result)
                        return
                time.sleep(0.2)
            self.fail("synthetic task plan did not complete")
        finally:
            task_plan.bind_progress(None)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_task_plan_writes_and_reads_synthetic_edit(self) -> None:
        from pywinauto import Desktop

        process, window_title = self._start_edit_window()
        try:
            deadline = time.monotonic() + 10
            selector = None
            last_inspection = "no inspection completed"
            while time.monotonic() < deadline:
                windows = Desktop(backend="uia").windows(
                    title=window_title,
                    visible_only=True,
                    top_level_only=True,
                )
                if len(windows) == 1:
                    candidates = []
                    for ordinal, control in enumerate(
                        windows[0].descendants()[:100]
                    ):
                        info = control.element_info
                        if (
                            str(info.control_type or "") == "Edit"
                            and str(info.name or "") == "Synthetic input"
                        ):
                            candidates.append({
                                "window_name": window_title,
                                "name": str(info.name or ""),
                                "automation_id": str(info.automation_id or ""),
                                "control_type": str(info.control_type or ""),
                                "ordinal": ordinal,
                            })
                    if len(candidates) == 1:
                        selector = candidates[0]
                        break
                    last_inspection = f"synthetic edit matches={len(candidates)}"
                else:
                    last_inspection = f"synthetic windows={len(windows)}"
                time.sleep(0.2)

            if selector is None:
                self.fail(
                    "synthetic edit window did not appear; "
                    f"returncode={process.poll()}, last_inspection={last_inspection}"
                )
            typed_text = "synthetic-" * 70
            steps = [{
                "tool": "computer_control",
                "arguments": {
                    "action": "write_control",
                    "selector": selector,
                    "text": typed_text,
                },
                "purpose": "Write non-sensitive synthetic text",
                "verification": {
                    "tool": "computer_control",
                    "arguments": {
                        "action": "read_control",
                        "selector": selector,
                    },
                    "expect": typed_text[:100],
                },
            }]
            preview = task_plan.preview(
                "Write and verify synthetic text", steps
            )
            task_id_match = re.search(r"task_id=(\w+)", preview)
            self.assertIsNotNone(task_id_match, preview)
            task_id = task_id_match.group(1)
            tool_results = []
            registry = ActionRegistry(
                {
                    "computer_control": ActionRecord(
                        name="computer_control",
                        handler=computer_control.computer_control,
                        valid=True,
                    )
                },
                lambda _message: None,
            )

            def execute_tool(_tool, args):
                result = action_policy.dispatch(
                    _tool,
                    args,
                    lambda: registry.run(_tool, args),
                )
                tool_results.append(result)
                return result

            task_plan.bind_progress(
                lambda active_task_id, _task, state, _current, _total, _reason:
                task_plan.resume(active_task_id)
                if state == "recovery_required"
                else None
            )
            token = action_policy._CONFIRMED_TOOL.set("task_planner")
            try:
                result = task_plan.execute(
                    "Write and verify synthetic text",
                    steps,
                    execute_tool,
                    task_id,
                )
            finally:
                action_policy._CONFIRMED_TOOL.reset(token)
                task_plan.bind_progress(None)

            self.assertIn("status=done", result, (result, tool_results))
            self.assertIn("verified=true", result)
            self.assertIn("state=completed", task_plan.status(task_id))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
