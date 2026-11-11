from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions import dev_agent
from core import confirm


class DevAgentConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )
        self.projects = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.projects)
        self.project_root = patch.object(dev_agent, "PROJECTS_DIR", self.root)
        self.project_root.start()
        self.addCleanup(self.project_root.stop)
        self.planner = patch.object(dev_agent, "_plan_project", return_value={
            "project_name": "synthetic-demo",
            "entry_point": "main.py",
            "files": [
                {
                    "path": "main.py",
                    "description": "Synthetic entry point",
                    "imports": [],
                },
            ],
            "run_command": "powershell -Command Remove-Item",
            "dependencies": ["synthetic-package>=1"],
        })
        self.planner.start()
        self.addCleanup(self.planner.stop)

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_preview_lists_plan_and_explicitly_disables_execution(self) -> None:
        with patch.object(dev_agent, "_build_project") as build:
            result = dev_agent.dev_agent({
                "description": "Create a synthetic demo",
                "language": "python",
                "project_name": "synthetic-demo",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("main.py", self.prompts[-1][1])
            self.assertIn("synthetic-package>=1", self.prompts[-1][1])
            self.assertIn("will NOT be run", self.prompts[-1][1])
            self.assertIn("will NOT be installed", self.prompts[-1][1])
            self.assertNotIn("powershell", self.prompts[-1][1].lower())
            build.assert_not_called()

            confirm.resolve(False)
            build.assert_not_called()

    def test_approval_writes_source_only_and_does_not_run_or_install(self) -> None:
        with patch.object(
            dev_agent,
            "_get_model",
            return_value=SimpleNamespace(
                generate_content=lambda _prompt: SimpleNamespace(
                    text="print('synthetic')"
                )
            ),
        ):
            result = dev_agent.dev_agent({
                "description": "Create a synthetic demo",
                "project_name": "synthetic-demo",
            })
            self.assertIn("[CONFIRMATION_PENDING]", result)
            confirm.resolve(True)

            target = self.root / "synthetic-demo" / "main.py"
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not target.exists():
                time.sleep(0.01)

            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "print('synthetic')")
            self.assertFalse(hasattr(dev_agent, "_run_project"))
            self.assertFalse(hasattr(dev_agent, "_install_dependencies"))
            self.assertFalse(hasattr(dev_agent, "_open_vscode"))

    def test_invalid_plan_paths_are_rejected_before_hud(self) -> None:
        invalid_plans = (
            {
                "project_name": "synthetic-demo",
                "entry_point": "../outside.py",
                "files": [{"path": "../outside.py", "description": "outside"}],
                "dependencies": [],
            },
            {
                "project_name": "synthetic-demo",
                "entry_point": "main.py",
                "files": [
                    {"path": "main.py", "description": "one"},
                    {"path": "MAIN.py", "description": "duplicate on Windows"},
                ],
                "dependencies": [],
            },
        )
        for plan in invalid_plans:
            with self.subTest(plan=plan), patch.object(
                dev_agent, "_plan_project", return_value=plan
            ):
                result = dev_agent.dev_agent({
                    "description": "Create a synthetic demo",
                })

                self.assertIn("status=failed", result)
                self.assertEqual(self.prompts, [])
                self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_project_is_not_overwritten(self) -> None:
        existing = self.root / "synthetic-demo"
        existing.mkdir()
        existing_file = existing / "main.py"
        existing_file.write_text("keep this", encoding="utf-8")

        result = dev_agent.dev_agent({
            "description": "Create a synthetic demo",
            "project_name": "synthetic-demo",
        })

        self.assertIn("already exists", result)
        self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep this")
        self.assertEqual(self.prompts, [])


if __name__ == "__main__":
    unittest.main()
