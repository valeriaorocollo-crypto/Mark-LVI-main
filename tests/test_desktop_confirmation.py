from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import desktop
from core import confirm


class DesktopConfirmationTests(unittest.TestCase):
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

    def test_organize_previews_exact_moves_and_cancel_moves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "report.txt"
            source.write_text("synthetic", encoding="utf-8")
            destination = root / "Documents" / source.name

            with patch.object(desktop, "_get_desktop", return_value=root), patch.object(
                desktop, "_OS", "Windows"
            ):
                result = desktop.desktop_control({
                    "action": "organize",
                    "mode": "by_type",
                })

                self.assertIn("[CONFIRMATION_PENDING]", result)
                self.assertIn(str(source), self.prompts[-1][1])
                self.assertIn(
                    str(Path("Documents") / source.name), self.prompts[-1][1]
                )
                self.assertTrue(source.exists())
                self.assertFalse(destination.exists())

                confirm.resolve(False)

                self.assertTrue(source.exists())
                self.assertFalse(destination.exists())

    def test_approved_organize_moves_only_the_previewed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "report.txt"
            source.write_text("synthetic", encoding="utf-8")
            destination = root / "Documents" / source.name

            with patch.object(desktop, "_get_desktop", return_value=root), patch.object(
                desktop, "_OS", "Windows"
            ):
                result = desktop.desktop_control({
                    "action": "organize",
                    "mode": "by_type",
                })
                self.assertIn("[CONFIRMATION_PENDING]", result)

                confirm.resolve(True)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not destination.exists():
                    time.sleep(0.01)

                self.assertTrue(destination.exists())
                self.assertFalse(source.exists())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not any(
                    "action status=" in message for message in self.logs
                ):
                    time.sleep(0.01)
                self.assertIn(
                    "action status=done; effect=verified",
                    self.logs[-1],
                )

    def test_desktop_change_after_preview_aborts_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "report.txt"
            source.write_text("synthetic", encoding="utf-8")
            destination = root / "Documents" / source.name

            with patch.object(desktop, "_get_desktop", return_value=root), patch.object(
                desktop, "_OS", "Windows"
            ):
                result = desktop.desktop_control({
                    "action": "organize",
                    "mode": "by_type",
                })
                self.assertIn("[CONFIRMATION_PENDING]", result)

                (root / "new.txt").write_text("new", encoding="utf-8")
                confirm.resolve(True)
                time.sleep(0.05)

                self.assertTrue(source.exists())
                self.assertFalse(destination.exists())

    def test_clean_requires_approval_with_archive_destination_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "report.txt"
            source.write_text("synthetic", encoding="utf-8")

            with patch.object(desktop, "_get_desktop", return_value=root), patch.object(
                desktop, "_OS", "Windows"
            ):
                result = desktop.desktop_control({"action": "clean"})

                self.assertIn("[CONFIRMATION_PENDING]", result)
                self.assertIn(source.name, self.prompts[-1][1])
                self.assertIn("Desktop Archive ", self.prompts[-1][1])
                self.assertTrue(source.exists())
                confirm.resolve(False)
                self.assertTrue(source.exists())

    def test_wallpaper_change_requires_approval(self) -> None:
        with patch.object(desktop, "set_wallpaper", return_value="done") as apply:
            result = desktop.desktop_control({
                "action": "wallpaper",
                "path": r"C:\synthetic\wallpaper.png",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn(r"C:\synthetic\wallpaper.png", self.prompts[-1][1])
            apply.assert_not_called()
            confirm.resolve(False)
            apply.assert_not_called()

    def test_wallpaper_url_rejects_private_and_unresolvable_hosts(self) -> None:
        with patch.object(desktop, "_is_public_host", return_value=False):
            result = desktop.set_wallpaper_from_url("https://example.test/image.png")

        self.assertIn("status=failed", result)
        self.assertIn("local, private, reserved", result)

    def test_desktop_control_rejects_non_object_parameters(self) -> None:
        result = desktop.desktop_control("wallpaper")

        self.assertIn("status=failed", result)
        self.assertIn("parameters must be an object", result)


if __name__ == "__main__":
    unittest.main()
