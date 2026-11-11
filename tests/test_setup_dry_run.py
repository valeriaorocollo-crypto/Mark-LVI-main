from __future__ import annotations

import subprocess
import sys
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import setup


class SetupDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_install_or_download(self) -> None:
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "setup.py", "--dry-run"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run complete", result.stdout)
        self.assertNotIn("Installing Python dependencies", result.stdout)
        self.assertNotIn("Installing Playwright browsers", result.stdout)

    def test_dry_run_handles_legacy_windows_output_encoding(self) -> None:
        root = Path(__file__).resolve().parent.parent
        environment = os.environ.copy()
        environment.pop("PYTHONUTF8", None)
        environment.pop("PYTHONIOENCODING", None)
        result = subprocess.run(
            [sys.executable, "setup.py", "--dry-run"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="cp1252",
            errors="replace",
            env=environment,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run complete", result.stdout)

    def test_dry_run_fails_when_avatar_asset_is_missing(self) -> None:
        root = Path(__file__).resolve().parent.parent
        manifests = (
            *(str(Path("requirements") / name) for name in setup.REQUIRED_MANIFESTS),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            clean_copy = Path(temp_dir)
            for relative_path in ("setup.py", *manifests):
                source_path = root / relative_path
                target_path = clean_copy / relative_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
            result = subprocess.run(
                [sys.executable, "setup.py", "--dry-run"],
                cwd=clean_copy,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required assets", result.stdout + result.stderr)
