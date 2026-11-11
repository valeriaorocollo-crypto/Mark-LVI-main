from __future__ import annotations

import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions import code_helper
from core import confirm, tool_audit


class CodeHelperSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )
        self.temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp_dir)

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def _wait_until_content(self, path: Path, expected: str) -> bool:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                if path.read_text(encoding="utf-8") == expected:
                    return True
            except (OSError, UnicodeError):
                pass
            time.sleep(0.01)
        return False

    def test_write_shows_complete_code_and_cancel_does_not_create_file(self) -> None:
        target = self.root / "created.py"
        content = "print('synthetic')\n" * 20
        with patch.object(code_helper, "_write", return_value=(content, target)):
            result = code_helper.code_helper({
                "action": "write",
                "description": "Create a harmless synthetic sample",
                "output_path": str(target),
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertIn(f"Exact destination: {target.resolve()}", self.prompts[-1][1])
        self.assertIn("Complete replacement code:\n" + content, self.prompts[-1][1])
        self.assertFalse(target.exists())

        confirm.resolve(False)
        self.assertFalse(target.exists())

    def test_approved_write_is_saved_and_verified(self) -> None:
        target = self.root / "approved.py"
        content = "print('approved synthetic output')\n"
        with patch.object(code_helper, "_write", return_value=(content, target)):
            result = code_helper.code_helper({
                "action": "write",
                "description": "Create a harmless synthetic sample",
                "output_path": str(target),
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        confirm.resolve(True)
        self.assertTrue(self._wait_until_content(target, content))
        self.assertEqual(target.read_text(encoding="utf-8"), content)

    def test_edit_waits_for_approval_and_refuses_if_file_changed(self) -> None:
        target = self.root / "existing.py"
        original = "print('original')\n"
        target.write_text(original, encoding="utf-8")
        generated = "print('reviewed replacement')\n"
        fake_model = SimpleNamespace(
            generate_content=lambda _prompt: SimpleNamespace(text=generated)
        )
        with patch.object(code_helper, "_get_gemini", return_value=fake_model):
            result = code_helper.code_helper({
                "action": "edit",
                "file_path": str(target),
                "description": "Replace the synthetic output",
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertIn(generated.strip(), self.prompts[-1][1])
        self.assertEqual(target.read_text(encoding="utf-8"), original)

        target.write_text("changed after preview\n", encoding="utf-8")
        confirm.resolve(True)
        time.sleep(0.05)
        self.assertEqual(target.read_text(encoding="utf-8"), "changed after preview\n")

    def test_write_refuses_existing_destination_without_overwriting(self) -> None:
        target = self.root / "keep.py"
        target.write_text("keep this\n", encoding="utf-8")
        with patch.object(code_helper, "_write", return_value=("new code\n", target)):
            result = code_helper.code_helper({
                "action": "write",
                "description": "Create a sample",
                "output_path": str(target),
            })

        self.assertIn("status=failed", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep this\n")
        self.assertEqual(self.prompts, [])

    def test_write_refuses_code_that_cannot_fit_in_complete_confirmation(self) -> None:
        target = self.root / "large.py"
        content = "x" * confirm.MAX_DETAIL_LENGTH
        with patch.object(code_helper, "_write", return_value=(content, target)):
            result = code_helper.code_helper({
                "action": "write",
                "description": "Create a synthetic sample",
                "output_path": str(target),
            })

        self.assertIn("details exceed", result)
        self.assertEqual(self.prompts, [])
        self.assertFalse(target.exists())

    def test_run_and_build_are_blocked_without_executing_code(self) -> None:
        for action in ("run", "build"):
            with self.subTest(action=action):
                result = code_helper.code_helper({
                    "action": action,
                    "file_path": str(self.root / "anything.py"),
                    "description": "synthetic",
                })
                self.assertIn("status=failed", result)
                self.assertIn("sandbox", result)

    def test_screen_debug_correction_waits_for_approval(self) -> None:
        target = self.root / "debugged.py"
        original = "print('broken')\n"
        target.write_text(original, encoding="utf-8")
        screenshot = self.root / "screen.png"
        screenshot.write_bytes(b"synthetic image")
        fixed_code = "print('fixed')"

        fake_google = types.ModuleType("google")
        fake_google.__path__ = []
        fake_genai = types.ModuleType("google.genai")
        fake_genai.types = SimpleNamespace(
            Part=SimpleNamespace(from_bytes=lambda **_kwargs: object())
        )
        response = SimpleNamespace(text=f"```python\n{fixed_code}\n```")

        with (
            patch.dict(sys.modules, {
                "google": fake_google,
                "google.genai": fake_genai,
            }),
            patch.object(code_helper, "_take_screenshot", return_value=screenshot),
            patch.object(code_helper.gemini, "call", return_value=response),
        ):
            result = code_helper.code_helper({
                "action": "screen_debug",
                "file_path": str(target),
                "description": "Review this synthetic issue",
            })

        self.assertIn("[CONFIRMATION_PENDING]", result)
        self.assertIn(fixed_code, self.prompts[-1][1])
        self.assertIn(str(target.resolve()), self.prompts[-1][1])
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertFalse(screenshot.exists())

    def test_screen_debug_deletes_screenshot_when_provider_returns_no_response(self):
        screenshot = self.root / "no-response.png"
        screenshot.write_bytes(b"synthetic image")
        fake_google = types.ModuleType("google")
        fake_google.__path__ = []
        fake_genai = types.ModuleType("google.genai")
        fake_genai.types = SimpleNamespace(
            Part=SimpleNamespace(from_bytes=lambda **_kwargs: object())
        )

        with (
            patch.dict(sys.modules, {
                "google": fake_google,
                "google.genai": fake_genai,
            }),
            patch.object(code_helper, "_take_screenshot", return_value=screenshot),
            patch.object(code_helper.gemini, "call", return_value=None),
        ):
            result = code_helper._screen_debug_action(
                "synthetic request", None, None
            )

        self.assertIn("couldn't reach Gemini", result)
        self.assertFalse(screenshot.exists())

    def test_screen_debug_reports_screenshot_cleanup_failure(self):
        screenshot = self.root / "undeleted.png"
        screenshot.write_bytes(b"synthetic image")
        fake_google = types.ModuleType("google")
        fake_google.__path__ = []
        fake_genai = types.ModuleType("google.genai")
        fake_genai.types = SimpleNamespace(
            Part=SimpleNamespace(from_bytes=lambda **_kwargs: object())
        )
        response = SimpleNamespace(text="Synthetic screen analysis.")

        with (
            patch.dict(sys.modules, {
                "google": fake_google,
                "google.genai": fake_genai,
            }),
            patch.object(code_helper, "_take_screenshot", return_value=screenshot),
            patch.object(code_helper.gemini, "call", return_value=response),
            patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=PermissionError("synthetic filesystem denial"),
            ),
        ):
            result = code_helper._screen_debug_action(
                "synthetic request", None, None
            )

        self.assertIn("status=unverified", result)
        self.assertIn("could not be deleted", result)
        self.assertIn(str(screenshot), result)
        self.assertTrue(screenshot.exists())

    def test_temporary_debug_capture_uses_unique_temp_files(self) -> None:
        fake_pyautogui = types.ModuleType("pyautogui")
        fake_pyautogui.screenshot = lambda: SimpleNamespace(
            save=lambda path: Path(path).write_bytes(b"synthetic image")
        )

        with (
            patch.dict(sys.modules, {"pyautogui": fake_pyautogui}),
            patch.object(code_helper.tempfile, "tempdir", str(self.root)),
        ):
            first = code_helper._take_screenshot()
            second = code_helper._take_screenshot()

        try:
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, self.root)
            self.assertEqual(second.parent, self.root)
            self.assertTrue(first.name.startswith("mark_screen_debug_"))
            self.assertTrue(second.name.startswith("mark_screen_debug_"))
            self.assertEqual(first.read_bytes(), b"synthetic image")
            self.assertEqual(second.read_bytes(), b"synthetic image")
        finally:
            if first is not None:
                first.unlink(missing_ok=True)
            if second is not None:
                second.unlink(missing_ok=True)

    def test_temporary_debug_capture_removes_partial_file_on_save_failure(self):
        def fail_save(_path):
            raise OSError("synthetic image write failure")

        fake_pyautogui = types.ModuleType("pyautogui")
        fake_pyautogui.screenshot = lambda: SimpleNamespace(
            save=fail_save
        )

        with (
            patch.dict(sys.modules, {"pyautogui": fake_pyautogui}),
            patch.object(code_helper.tempfile, "tempdir", str(self.root)),
        ):
            self.assertIsNone(code_helper._take_screenshot())

        self.assertEqual(list(self.root.glob("mark_screen_debug_*.png")), [])

    def test_stale_cleanup_only_removes_old_owned_regular_files(self) -> None:
        stale_owned = self.root / "mark_screen_debug_stale.png"
        recent_owned = self.root / "mark_screen_debug_recent.png"
        unrelated = self.root / "user_screenshot.png"
        for path in (stale_owned, recent_owned, unrelated):
            path.write_bytes(b"synthetic image")
        stale_time = time.time() - code_helper._DEBUG_SCREENSHOT_MAX_AGE_SECONDS - 1
        os.utime(stale_owned, (stale_time, stale_time))

        with patch.object(code_helper.tempfile, "tempdir", str(self.root)):
            code_helper._cleanup_stale_debug_screenshots()

        self.assertFalse(stale_owned.exists())
        self.assertTrue(recent_owned.exists())
        self.assertTrue(unrelated.exists())

    def test_stale_cleanup_does_not_follow_or_remove_symlinks(self) -> None:
        target = self.root / "user_screenshot.png"
        target.write_bytes(b"synthetic image")
        link = self.root / "mark_screen_debug_link.png"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable in this environment")

        with (
            patch.object(code_helper.tempfile, "tempdir", str(self.root)),
            patch.object(code_helper, "_DEBUG_SCREENSHOT_MAX_AGE_SECONDS", -1),
        ):
            code_helper._cleanup_stale_debug_screenshots()

        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_code_helper_actions_are_classified_explicitly(self) -> None:
        for action in ("write", "edit", "optimize", "screen_debug", "run", "build"):
            with self.subTest(action=action):
                self.assertEqual(
                    tool_audit.classify_risk("code_helper", {"action": action}),
                    "high",
                )
        self.assertEqual(
            tool_audit.classify_risk("code_helper", {"action": "explain"}),
            "read_or_navigate",
        )


if __name__ == "__main__":
    unittest.main()
