from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import memory_manager


class MemoryManagerPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.temp_dir.name) / "long_term.json"
        self.path_patch = patch.object(
            memory_manager, "MEMORY_PATH", self.memory_path
        )
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_clear_personal_memory_preserves_only_monitor_configuration(self):
        monitor_config = {"enabled": True, "items": ["synthetic"]}
        self.memory_path.write_text(
            json.dumps({
                "identity": {"name": {"value": "synthetic person"}},
                "sessions": [{"summary": "synthetic private summary"}],
                "monitors": monitor_config,
                "unknown_personal_data": {"value": "synthetic"},
            }),
            encoding="utf-8",
        )

        self.assertTrue(memory_manager.clear_personal_memory())

        stored = json.loads(self.memory_path.read_text(encoding="utf-8"))
        self.assertEqual(stored, {
            **memory_manager._empty_memory(),
            "monitors": monitor_config,
        })

    def test_clear_personal_memory_does_not_replace_corrupt_file(self):
        self.memory_path.write_text("{broken", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "could not be read"):
            memory_manager.clear_personal_memory()

        self.assertEqual(self.memory_path.read_text(encoding="utf-8"), "{broken")

    def test_clear_personal_memory_reports_atomic_write_failure(self):
        self.memory_path.write_text(
            json.dumps({"identity": {"name": {"value": "synthetic"}}}),
            encoding="utf-8",
        )

        with patch.object(
            memory_manager.os,
            "replace",
            side_effect=PermissionError("synthetic filesystem denial"),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be cleared"):
                memory_manager.clear_personal_memory()

        self.assertIn(
            "synthetic",
            self.memory_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(list(Path(self.temp_dir.name).glob(".long_term.*.tmp")), [])

    def test_clear_personal_memory_is_idempotent_when_file_is_absent(self):
        self.assertFalse(memory_manager.clear_personal_memory())
        self.assertFalse(self.memory_path.exists())


if __name__ == "__main__":
    unittest.main()
