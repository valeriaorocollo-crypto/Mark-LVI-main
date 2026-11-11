from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class SetupOptionalGroupsTests(unittest.TestCase):
    def test_optional_install_requires_explicit_confirmation(self) -> None:
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "setup.py", "--install-optional", "documents"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm", result.stderr + result.stdout)
        self.assertNotIn("Installing Python dependencies", result.stdout)

    def test_unknown_optional_group_is_rejected(self) -> None:
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [
                sys.executable, "setup.py", "--install-optional",
                "unknown", "--confirm",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown optional group", result.stderr + result.stdout)
