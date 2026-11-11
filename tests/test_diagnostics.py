from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from core import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_report_is_local_and_json_serializable(self) -> None:
        report = diagnostics.run_diagnostics(Path(__file__).parent.parent)

        self.assertIn("dependencies", report)
        self.assertIn("accessibility", report)
        self.assertIn("audio", report)
        self.assertIn("native_tools", report)
        self.assertIn("optional", report)
        self.assertIn("secure_storage", report)
        self.assertIn("ui_automation", report)
        self.assertIn("config_writable", report["paths"])
        self.assertIn("temp_writable", report["paths"])
        self.assertIn("integrations", report["optional"])
        self.assertIn("installed", report["playwright"])
        self.assertNotIn("api_key", str(report).lower())

    def test_missing_dependency_is_reported_without_installing(self) -> None:
        with patch.object(diagnostics, "_module_available", return_value=False):
            report = diagnostics.run_diagnostics(Path.cwd())

        self.assertFalse(report["dependencies"]["PyQt6"])
        self.assertIn("packages:", diagnostics.summarize_diagnostics(report))

    def test_summary_does_not_include_paths(self) -> None:
        report = diagnostics.run_diagnostics(Path("C:/private/project"))

        self.assertNotIn("C:\\private", diagnostics.summarize_diagnostics(report))
        self.assertNotIn("C:/private", diagnostics.summarize_diagnostics(report))

    def test_browser_detection_only_checks_local_cache(self) -> None:
        with (
            patch.object(
                diagnostics,
                "_playwright_cache_dir",
                return_value=Path("C:/nonexistent-playwright-cache"),
            ),
            patch.object(diagnostics, "_path_readable", return_value=False),
        ):
            report = diagnostics._browser_status("Windows", True)

        self.assertFalse(report["cache_present"])
        self.assertEqual(
            report["installed"],
            {"chromium": False, "firefox": False, "webkit": False},
        )

    def test_optional_status_is_package_only(self) -> None:
        with patch.object(diagnostics, "_module_available", return_value=False):
            report = diagnostics.run_diagnostics(Path.cwd())

        self.assertTrue(report["optional"])
        self.assertFalse(report["optional"]["local-voice"]["faster-whisper"])
