from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import browser_control


class BrowserProfileSafetyTests(unittest.TestCase):
    def test_automation_profile_isolated_from_real_browser_data(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            home_path = Path(home)
            with patch.object(Path, "home", return_value=home_path):
                profile = Path(browser_control._automation_profile_dir("chrome"))

            self.assertEqual(
                profile, home_path / ".jarvis_profiles" / "chrome"
            )
            self.assertTrue(profile.is_dir())
            self.assertNotEqual(profile, home_path / "AppData" / "Local")

    def test_automation_profile_rejects_empty_browser_name(self) -> None:
        with self.assertRaises(ValueError):
            browser_control._automation_profile_dir(" ")
