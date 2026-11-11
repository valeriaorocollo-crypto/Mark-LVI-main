from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import file_controller


class FileControllerPathTests(unittest.TestCase):
    def test_copy_creates_a_new_destination_and_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            destination = root / "copy.txt"
            source.write_bytes(b"source bytes")

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(file_controller, "push_undo") as push_undo,
            ):
                result = file_controller.copy_file(
                    str(root), source.name, str(destination)
                )

            self.assertIn("Copied:", result)
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"source bytes")
            push_undo.assert_called_once()

    def test_copy_undo_refuses_to_delete_a_copy_changed_afterward(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            destination = root / "copy.txt"
            source.write_bytes(b"source bytes")
            undo_entries = []

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(
                    file_controller,
                    "push_undo",
                    side_effect=lambda _label, undo_fn: undo_entries.append(undo_fn),
                ),
            ):
                result = file_controller.copy_file(
                    str(root), source.name, str(destination)
                )

            self.assertIn("Copied:", result)
            destination.write_bytes(b"user replacement")
            undo_result = undo_entries[0]()

            self.assertIn("changed", undo_result)
            self.assertEqual(destination.read_bytes(), b"user replacement")

    def test_directory_copy_is_rejected_until_safe_directory_undo_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "file.txt").write_text("content", encoding="utf-8")
            destination = root / "copy"

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(file_controller, "push_undo") as push_undo,
            ):
                result = file_controller.copy_file(
                    str(root), source.name, str(destination)
                )

            self.assertIn("temporarily disabled", result)
            self.assertFalse(destination.exists())
            push_undo.assert_not_called()

    def test_copy_refuses_existing_destination_without_changing_or_undoing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_text("new content", encoding="utf-8")
            destination.write_text("original content", encoding="utf-8")

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(file_controller, "push_undo") as push_undo,
            ):
                result = file_controller.copy_file(
                    str(root), source.name, str(destination)
                )

            self.assertIn("already exists", result)
            self.assertEqual(
                destination.read_text(encoding="utf-8"), "original content"
            )
            push_undo.assert_not_called()

    def test_create_and_write_refuse_binary_or_oversized_existing_files(self) -> None:
        writers = (
            lambda root, name, content: file_controller.create_file(
                str(root), name=name, content=content
            ),
            lambda root, name, content: file_controller.write_file(
                str(root), name=name, content=content
            ),
        )
        originals = (
            b"\x89PNG\x00binary-content",
            b"valid-utf8\x00binary-marker",
            b"x" * (file_controller._UNDO_CONTENT_LIMIT + 1),
        )

        for writer in writers:
            for original in originals:
                with self.subTest(writer=writer, original_size=len(original)):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        root = Path(temp_dir)
                        target = root / "existing.bin"
                        target.write_bytes(original)
                        with (
                            patch.object(file_controller, "_SAFE_ROOTS", [root]),
                            patch.object(file_controller, "push_undo") as push_undo,
                        ):
                            writer(root, target.name, "replacement text")

                        self.assertEqual(target.read_bytes(), original)
                        push_undo.assert_not_called()

    def test_write_preserves_original_if_sync_or_atomic_replace_fails(self) -> None:
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                target = root / "notes.txt"
                target.write_bytes(b"original bytes")
                with (
                    patch.object(file_controller, "_SAFE_ROOTS", [root]),
                    patch.object(file_controller, "push_undo") as push_undo,
                    patch.object(
                        file_controller.os,
                        operation,
                        side_effect=OSError("synthetic disk failure"),
                    ),
                ):
                    result = file_controller.write_file(
                        str(root), name=target.name, content="replacement"
                    )

                self.assertIn("Could not write file", result)
                self.assertEqual(target.read_bytes(), b"original bytes")
                self.assertFalse(list(root.glob(".mark-write-*.tmp")))
                push_undo.assert_not_called()

    def test_write_refuses_to_change_file_when_snapshot_read_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "notes.txt"
            target.write_bytes(b"original bytes")
            original_open = Path.open

            def deny_target_read(path, *args, **kwargs):
                if path == target:
                    raise PermissionError("synthetic ACL denial")
                return original_open(path, *args, **kwargs)

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(file_controller, "push_undo") as push_undo,
                patch.object(Path, "open", deny_target_read),
            ):
                result = file_controller.write_file(
                    str(root), name=target.name, content="replacement"
                )

            self.assertIn("could not be backed up", result)
            self.assertEqual(target.read_bytes(), b"original bytes")
            push_undo.assert_not_called()

    def test_undo_write_keeps_assistant_content_if_restore_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "notes.txt"
            target.write_bytes(b"original bytes")
            undo_entries = []
            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(
                    file_controller,
                    "push_undo",
                    side_effect=lambda _label, undo_fn: undo_entries.append(undo_fn),
                ),
            ):
                result = file_controller.write_file(
                    str(root), name=target.name, content="assistant content"
                )

            self.assertIn("Written to", result)
            with patch.object(
                file_controller.os,
                "replace",
                side_effect=OSError("synthetic restore failure"),
            ):
                undo_result = undo_entries[0]()

            self.assertIn("could not be restored safely", undo_result)
            self.assertEqual(target.read_bytes(), b"assistant content")
            self.assertFalse(list(root.glob(".mark-write-*.tmp")))

    def test_undo_write_preserves_content_changed_after_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "notes.txt"
            target.write_bytes(b"before")
            undo_entries = []

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(
                    file_controller,
                    "push_undo",
                    side_effect=lambda label, undo_fn: undo_entries.append(undo_fn),
                ),
            ):
                result = file_controller.write_file(
                    str(root), name=target.name, content="assistant edit"
                )

            self.assertIn("Written to", result)
            target.write_bytes(b"user edit after assistant")
            undo_result = undo_entries[0]()

            self.assertIn("leaving it untouched", undo_result)
            self.assertEqual(target.read_bytes(), b"user edit after assistant")

    def test_undo_write_restores_exact_previous_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "notes.txt"
            target.write_bytes(b"previous text")
            undo_entries = []

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(
                    file_controller,
                    "push_undo",
                    side_effect=lambda label, undo_fn: undo_entries.append(undo_fn),
                ),
            ):
                result = file_controller.write_file(
                    str(root), name=target.name, content="replacement text"
                )

            self.assertIn("Written to", result)
            self.assertEqual(target.read_bytes(), b"replacement text")
            undo_entries[0]()
            self.assertEqual(target.read_bytes(), b"previous text")

    def test_undo_write_removes_a_file_created_by_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "new.txt"
            undo_entries = []

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(
                    file_controller,
                    "push_undo",
                    side_effect=lambda _label, undo_fn: undo_entries.append(undo_fn),
                ),
            ):
                result = file_controller.write_file(
                    str(root), name=target.name, content="created"
                )

            self.assertIn("Written to", result)
            self.assertTrue(target.exists())
            undo_result = undo_entries[0]()

            self.assertIn("Removed", undo_result)
            self.assertFalse(target.exists())

    def test_move_refuses_an_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_bytes(b"source")
            destination.write_bytes(b"original")

            with (
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
                patch.object(file_controller, "push_undo") as push_undo,
            ):
                result = file_controller.move_file(
                    str(root), source.name, str(destination)
                )

            self.assertIn("Destination already exists", result)
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(destination.read_bytes(), b"original")
            push_undo.assert_not_called()

    def test_text_writers_create_new_files(self) -> None:
        writers = (
            lambda root, name: file_controller.create_file(
                str(root), name=name, content="created text"
            ),
            lambda root, name: file_controller.write_file(
                str(root), name=name, content="created text"
            ),
        )
        for index, writer in enumerate(writers):
            with self.subTest(writer=index), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                target = root / f"new-{index}.txt"
                with (
                    patch.object(file_controller, "_SAFE_ROOTS", [root]),
                    patch.object(file_controller, "push_undo"),
                ):
                    result = writer(root, target.name)
                expected = "File created" if index == 0 else "Written to"
                self.assertIn(expected, result)
                self.assertEqual(target.read_text(encoding="utf-8"), "created text")

    def test_rename_rejects_parent_traversal_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            source.write_text("synthetic", encoding="utf-8")

            with (
                patch.object(file_controller, "_resolve_path", return_value=root),
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
            ):
                result = file_controller.rename_file(
                    ".", name=source.name, new_name="../outside.txt"
                )

            self.assertIn("single safe filename", result)
            self.assertTrue(source.exists())
            self.assertFalse((root.parent / "outside.txt").exists())

    def test_rename_refuses_destination_outside_safe_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.txt"
            source.write_text("synthetic", encoding="utf-8")

            with (
                patch.object(file_controller, "_resolve_path", return_value=root),
                patch.object(file_controller, "_SAFE_ROOTS", [root]),
            ):
                result = file_controller.rename_file(
                    ".", name=source.name, new_name=str(root.parent / "outside.txt")
                )

            self.assertIn("single safe filename", result)
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
