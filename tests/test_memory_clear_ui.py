from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ui
from memory import memory_manager


class MemoryClearUiTests(unittest.TestCase):
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

    def test_cancel_keeps_memory_unchanged(self) -> None:
        original = {"identity": {"name": {"value": "synthetic"}}}
        self.memory_path.write_text(json.dumps(original), encoding="utf-8")

        with (
            patch.object(
                ui.QMessageBox,
                "question",
                return_value=ui.QMessageBox.StandardButton.No,
            ) as question,
            patch.object(ui.QTimer, "singleShot") as single_shot,
            patch.object(memory_manager, "clear_personal_memory") as clear_memory,
        ):
            ui.MemoryOverlay._clear_all_memory(
                SimpleNamespace(_rebuild=lambda: None)
            )

        self.assertEqual(json.loads(self.memory_path.read_text(encoding="utf-8")), original)
        clear_memory.assert_not_called()
        single_shot.assert_not_called()
        self.assertEqual(
            question.call_args.args[4],
            ui.QMessageBox.StandardButton.No,
        )

    def test_confirm_clears_only_the_configured_memory_file(self) -> None:
        original = {
            "identity": {"name": {"value": "synthetic"}},
            "monitors": {"enabled": True},
        }
        self.memory_path.write_text(json.dumps(original), encoding="utf-8")

        with (
            patch.object(
                ui.QMessageBox,
                "question",
                return_value=ui.QMessageBox.StandardButton.Yes,
            ),
            patch.object(ui.QTimer, "singleShot") as single_shot,
        ):
            rebuild = lambda: None
            ui.MemoryOverlay._clear_all_memory(
                SimpleNamespace(_rebuild=rebuild)
            )

        stored = json.loads(self.memory_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["monitors"], original["monitors"])
        self.assertEqual(
            stored,
            {**memory_manager._empty_memory(), "monitors": original["monitors"]},
        )
        single_shot.assert_called_once_with(0, rebuild)


if __name__ == "__main__":
    unittest.main()
