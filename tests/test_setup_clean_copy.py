from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import setup


class SetupCleanCopyTests(unittest.TestCase):
    def test_isolated_clean_install_inputs_pass_dry_run_without_side_effects(self):
        source = Path(__file__).resolve().parent.parent
        setup_inputs = (
            "setup.py",
            "requirements.txt",
            "requirements-base.txt",
            "requirements-optional.txt",
            *setup.OPTIONAL_GROUPS.values(),
            "core/face_model.obj",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            clean_copy = Path(temp_dir) / "mark-clean"
            for relative_path in setup_inputs:
                source_path = source / relative_path
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
            has_legacy_key_file = (
                clean_copy / "config" / "api_keys.json"
            ).exists()
            has_virtual_environment = (clean_copy / ".venv").exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run complete", result.stdout)
        self.assertNotIn("Installing Python dependencies", result.stdout)
        self.assertFalse(has_legacy_key_file)
        self.assertFalse(has_virtual_environment)


if __name__ == "__main__":
    unittest.main()
