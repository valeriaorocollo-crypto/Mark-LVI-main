from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class ProcessPolicyTests(unittest.TestCase):
    def test_importing_main_does_not_replace_subprocess_popen(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = (
            "import subprocess; original = subprocess.Popen; import main; "
            "assert subprocess.Popen is original"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
