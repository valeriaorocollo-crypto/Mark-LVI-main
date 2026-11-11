from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch

from actions import computer_control, file_controller, meet_control, send_message
from core import appidentity, confirm


class ConfirmedActionTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        preflight = patch.object(
            send_message,
            "_prepare_whatsapp_recipient",
            side_effect=lambda receiver: (receiver, ""),
        )
        preflight.start()
        self.addCleanup(preflight.stop)
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_file_delete_waits_for_hud_and_cancel_does_not_delete(self) -> None:
        deleted = threading.Event()
        path = r"C:\test-data\never-delete.txt"

        with patch.object(
            file_controller, "delete_file",
            side_effect=lambda *_args, **_kwargs: deleted.set() or "deleted",
        ):
            result = file_controller.file_controller({
                "action": "delete",
                "path": path,
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertEqual(self.prompts[-1][1], path)
            self.assertFalse(deleted.is_set())

            confirm.resolve(False)

            self.assertFalse(deleted.wait(0.1))

    def test_file_write_waits_for_hud_and_cancel_does_not_write(self) -> None:
        written = threading.Event()
        content = "synthetic file contents"

        with patch.object(
            file_controller, "write_file",
            side_effect=lambda *_args, **_kwargs: written.set() or "written",
        ):
            result = file_controller.file_controller({
                "action": "write",
                "path": "documents",
                "name": "safe-test.txt",
                "content": content,
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Complete content:\n" + content, self.prompts[-1][1])
            self.assertFalse(written.is_set())

            confirm.resolve(False)

            self.assertFalse(written.wait(0.1))

    def test_file_write_refuses_when_complete_preview_exceeds_hud_limit(self) -> None:
        written = threading.Event()
        content = "x" * confirm.MAX_DETAIL_LENGTH

        with patch.object(
            file_controller, "write_file",
            side_effect=lambda *_args, **_kwargs: written.set() or "written",
        ):
            result = file_controller.file_controller({
                "action": "write",
                "path": "documents",
                "name": "safe-test.txt",
                "content": content,
            })

        self.assertIn("details exceed", result)
        self.assertEqual(self.prompts, [])
        self.assertFalse(written.is_set())

    def test_file_move_waits_for_hud_and_cancel_does_not_move(self) -> None:
        moved = threading.Event()

        with patch.object(
            file_controller, "move_file",
            side_effect=lambda *_args, **_kwargs: moved.set() or "moved",
        ):
            result = file_controller.file_controller({
                "action": "move",
                "path": "documents",
                "name": "safe-test.txt",
                "destination": "downloads",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("safe-test.txt", self.prompts[-1][1])
            self.assertIn("Downloads", self.prompts[-1][1])
            self.assertFalse(moved.is_set())

            confirm.resolve(False)

            self.assertFalse(moved.wait(0.1))

    def test_file_copy_waits_for_hud_and_cancel_does_not_copy(self) -> None:
        copied = threading.Event()

        with patch.object(
            file_controller, "copy_file",
            side_effect=lambda *_args, **_kwargs: copied.set() or "copied",
        ):
            result = file_controller.file_controller({
                "action": "copy",
                "path": "documents",
                "name": "safe-test.txt",
                "destination": "downloads",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("safe-test.txt", self.prompts[-1][1])
            self.assertIn("Downloads", self.prompts[-1][1])
            self.assertFalse(copied.is_set())

            confirm.resolve(False)

            self.assertFalse(copied.wait(0.1))

    def test_file_create_waits_for_hud_and_cancel_does_not_create(self) -> None:
        created = threading.Event()
        with patch.object(
            file_controller, "create_file",
            side_effect=lambda *_args, **_kwargs: created.set() or "created",
        ):
            result = file_controller.file_controller({
                "action": "create_file",
                "path": "documents",
                "name": "safe-test.txt",
                "content": "synthetic content",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Create or replace", self.prompts[-1][0])
            self.assertIn("synthetic content", self.prompts[-1][1])
            self.assertFalse(created.is_set())

            confirm.resolve(False)

            self.assertFalse(created.wait(0.1))

    def test_file_create_folder_waits_for_hud_and_cancel_does_not_create(self) -> None:
        created = threading.Event()
        with patch.object(
            file_controller, "create_folder",
            side_effect=lambda *_args, **_kwargs: created.set() or "created",
        ):
            result = file_controller.file_controller({
                "action": "create_folder",
                "path": "documents",
                "name": "safe-test-folder",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("safe-test-folder", self.prompts[-1][1])
            self.assertFalse(created.is_set())

            confirm.resolve(False)

            self.assertFalse(created.wait(0.1))

    def test_file_rename_waits_for_hud_and_cancel_does_not_rename(self) -> None:
        renamed = threading.Event()
        source = Path.home() / "Documents" / "safe-test.txt"
        with (
            patch.object(file_controller, "_resolve_path", return_value=source.parent),
            patch.object(file_controller, "_is_safe_path", return_value=True),
            patch.object(
                Path,
                "exists",
                autospec=True,
                side_effect=lambda candidate: candidate == source,
            ),
            patch.object(
                file_controller,
                "rename_file",
                side_effect=lambda *_args, **_kwargs: renamed.set() or "renamed",
            ),
        ):
            result = file_controller.file_controller({
                "action": "rename",
                "path": "documents",
                "name": source.name,
                "new_name": "safe-renamed.txt",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn(str(source), self.prompts[-1][1])
            self.assertIn(str(source.with_name("safe-renamed.txt")), self.prompts[-1][1])
            self.assertFalse(renamed.is_set())

            confirm.resolve(False)

            self.assertFalse(renamed.wait(0.1))

    def test_close_tab_waits_for_hud_before_action(self) -> None:
        from actions import computer_settings

        invoked = threading.Event()
        with patch.dict(
            computer_settings.ACTION_MAP,
            {"close_tab": lambda: invoked.set()},
        ):
            result = computer_settings.computer_settings({
                "action": "close_tab",
            })

            self.assertIn("status=failed", result)
            self.assertFalse(invoked.is_set())
            self.assertFalse(invoked.wait(0.1))

    def test_computer_settings_bounds_reload_and_scroll_inputs(self) -> None:
        from actions import computer_settings

        with (
            patch.object(computer_settings, "_PYAUTOGUI", True),
            patch.object(computer_settings, "reload_page_n") as reload_page,
            patch.object(computer_settings, "scroll_up") as scroll,
        ):
            for value in (0, 21, True, "many", 10**9):
                with self.subTest(action="reload_n", value=value):
                    result = computer_settings.computer_settings({
                        "action": "reload_n",
                        "value": value,
                    })
                    self.assertIn("status=failed", result)

            for value in (-1, 10_001, True, "many", 10**9):
                with self.subTest(action="scroll_up", value=value):
                    result = computer_settings.computer_settings({
                        "action": "scroll_up",
                        "value": value,
                    })
                    self.assertIn("status=failed", result)

            self.assertFalse(reload_page.called)
            self.assertFalse(scroll.called)

    def test_computer_settings_rejects_missing_or_invalid_volume(self) -> None:
        from actions import computer_settings

        with (
            patch.object(computer_settings, "_PYAUTOGUI", True),
            patch.object(computer_settings, "volume_set") as volume_set,
        ):
            for value in (None, True, -1, 101, "loud"):
                with self.subTest(value=value):
                    result = computer_settings.computer_settings({
                        "action": "volume_set",
                        "value": value,
                    })
                    self.assertIn("status=failed", result)

            self.assertFalse(volume_set.called)

    def test_computer_settings_blocks_unscoped_text_input(self) -> None:
        from actions import computer_settings

        secret_text = "synthetic-private-input"
        with (
            patch.object(computer_settings, "_PYAUTOGUI", True),
            patch.object(computer_settings, "type_text") as type_text,
        ):
            result = computer_settings.computer_settings({
                "action": "type_text",
                "value": secret_text,
            })

        type_text.assert_not_called()
        self.assertIn("status=failed", result)
        self.assertNotIn(secret_text, result)

    def test_unscoped_save_is_blocked_before_action(self) -> None:
        from actions import computer_settings

        invoked = threading.Event()
        with patch.dict(
            computer_settings.ACTION_MAP,
            {"save": lambda: invoked.set()},
        ):
            result = computer_settings.computer_settings({"action": "save"})

            self.assertIn("status=failed", result)
            self.assertFalse(invoked.is_set())
            self.assertFalse(invoked.wait(0.1))

    def test_all_irreversible_settings_wait_for_hud(self) -> None:
        from actions import computer_settings

        calls: list[str] = []
        test_actions = {
            action: (lambda name=action: calls.append(name))
            for action in computer_settings._IRREVERSIBLE
            if action != "close_app"
        }
        with patch.dict(computer_settings.ACTION_MAP, test_actions):
            for action in test_actions:
                with self.subTest(action=action):
                    with confirm._lock:
                        confirm._pending = None
                    result = computer_settings.computer_settings({"action": action})

                    if action in {"close_window", "close_tab", "save"}:
                        self.assertIn("status=failed", result)
                        self.assertNotIn(action, calls)
                        self.assertEqual(confirm.pending_title(), "")
                        continue

                    self.assertIn("[CONFIRMATION_PENDING]", result)
                    self.assertNotIn(action, calls)
                    confirm.resolve(False)
                    self.assertNotIn(action, calls)

    def test_message_send_waits_for_hud_and_cancel_does_not_dispatch(self) -> None:
        dispatched = threading.Event()
        message = "Synthetic test message; never deliver"
        terminal = io.StringIO()

        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report",
            side_effect=lambda *_args: dispatched.set(),
        ), redirect_stdout(terminal):
            result = send_message.send_message({
                "receiver": "Synthetic Test Contact",
                "message_text": message,
                "platform": "WhatsApp",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Destinatario: Synthetic Test Contact", self.prompts[-1][1])
            self.assertIn("Mensaje:\n" + message, self.prompts[-1][1])
            self.assertIn("encontró y abrió una conversación", self.prompts[-1][1])
            self.assertIn("sí, enviar", self.prompts[-1][1])
            self.assertFalse(dispatched.is_set())

            confirm.resolve(False)

            self.assertFalse(dispatched.wait(0.1))
            self.assertNotIn("Synthetic Test Contact", terminal.getvalue())
            self.assertNotIn(message, terminal.getvalue())

    def test_message_send_can_be_approved_by_voice_after_review(self) -> None:
        dispatched = threading.Event()
        calls: list[tuple[str, str, str]] = []

        def capture(_player, platform, receiver, message):
            calls.append((platform, receiver, message))
            dispatched.set()

        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report", side_effect=capture,
        ):
            result = send_message.send_message({
                "receiver": "Mama Luisa",
                "message_text": "Llegaré una hora tarde.",
                "platform": "WhatsApp",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertTrue(confirm.handle_voice("Sí, enviar."))
            self.assertTrue(dispatched.wait(2))

        self.assertEqual(
            calls, [("WhatsApp", "Mama Luisa", "Llegaré una hora tarde.")]
        )

    def test_message_edit_updates_preview_and_requires_new_voice_approval(self) -> None:
        dispatched = threading.Event()
        calls: list[tuple[str, str, str]] = []

        def capture(_player, platform, receiver, message):
            calls.append((platform, receiver, message))
            dispatched.set()

        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report", side_effect=capture,
        ):
            result = send_message.send_message({
                "receiver": "Yampier",
                "message_text": "Hola",
                "platform": "WhatsApp",
            })
            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertTrue(confirm.voice_pending())

            self.assertTrue(confirm.handle_voice("El mensaje está mal."))
            self.assertIn("Corrección pendiente: mensaje", self.prompts[-1][1])
            self.assertFalse(dispatched.is_set())

            confirm.resolve(True)
            self.assertFalse(dispatched.wait(0.1))
            self.assertIn("Corrección pendiente: mensaje", self.prompts[-1][1])

            self.assertTrue(confirm.handle_voice("Hola, ¿cómo estás?"))
            self.assertIn("Mensaje:\nHola, ¿cómo estás?", self.prompts[-1][1])
            self.assertNotIn("Corrección pendiente", self.prompts[-1][1])
            self.assertFalse(dispatched.is_set())

            self.assertTrue(confirm.handle_voice("Sí, enviar"))
            self.assertTrue(dispatched.wait(2))
            self.assertFalse(confirm.voice_pending())

        self.assertEqual(
            calls, [("WhatsApp", "Yampier", "Hola, ¿cómo estás?")]
        )

    def test_unclear_voice_cannot_approve_message(self) -> None:
        dispatched = threading.Event()
        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report",
            side_effect=lambda *_args: dispatched.set(),
        ):
            send_message.send_message({
                "receiver": "Casa de Edith",
                "message_text": "testeo",
                "platform": "WhatsApp",
            })

            self.assertTrue(confirm.handle_voice("Mmm, puede ser."))
            self.assertFalse(dispatched.wait(0.1))
            self.assertEqual(confirm.pending_title(),
                             "¿Enviar este mensaje por WhatsApp?")

    def test_explicit_recipient_correction_updates_preview_before_reapproval(self) -> None:
        dispatched = threading.Event()
        calls: list[tuple[str, str, str]] = []

        def capture(_player, platform, receiver, message):
            calls.append((platform, receiver, message))
            dispatched.set()

        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report", side_effect=capture,
        ), patch.object(
            send_message,
            "_prepare_whatsapp_recipient",
            side_effect=lambda receiver: (
                "Yampier Contact" if receiver == "Yampier" else receiver,
                "",
            ),
        ) as preflight:
            send_message.send_message({
                "receiver": "Mama Luisa",
                "message_text": "Llegaré tarde.",
                "platform": "WhatsApp",
            })

            self.assertTrue(confirm.handle_voice(
                "El destinatario está mal, es Yampier."
            ))
            self.assertIn("Destinatario: Yampier Contact", self.prompts[-1][1])
            self.assertIn("encontró y abrió una conversación", self.prompts[-1][1])
            self.assertFalse(dispatched.is_set())

            self.assertTrue(confirm.handle_voice("Sí, enviar"))
            self.assertTrue(dispatched.wait(2))

        self.assertEqual(
            calls, [("WhatsApp", "Yampier Contact", "Llegaré tarde.")]
        )
        self.assertEqual(
            preflight.call_args_list,
            [call("Mama Luisa"), call("Yampier")],
        )

    def test_unverified_recipient_correction_cannot_be_approved_or_sent(self) -> None:
        dispatched = threading.Event()
        with patch.object(send_message, "_PYAUTOGUI", True), patch.object(
            send_message, "_send_and_report",
            side_effect=lambda *_args: dispatched.set(),
        ), patch.object(
            send_message,
            "_prepare_whatsapp_recipient",
            side_effect=[
                ("Mama Luisa", ""),
                (None, "no unique chat was found"),
            ],
        ):
            send_message.send_message({
                "receiver": "Mama Luisa",
                "message_text": "Llegaré tarde.",
                "platform": "WhatsApp",
            })

            self.assertTrue(confirm.handle_voice(
                "El destinatario está mal, es Yampier."
            ))
            self.assertIn("No se pudo verificar el destinatario",
                          confirm.pending_title())
            self.assertIn("no unique chat was found", self.prompts[-1][1])
            confirm.resolve(True)
            self.assertFalse(dispatched.wait(0.1))
            self.assertTrue(confirm.handle_voice("cancelar"))
            self.assertFalse(dispatched.wait(0.1))

    def test_whatsapp_driver_unavailable_never_falls_back_to_typing(self) -> None:
        with patch.object(send_message, "_desktop_send") as blind_send:
            result = send_message._send_whatsapp("Synthetic Contact", "test")

        self.assertIn("status=failed", result)
        self.assertIn("no message was sent", result)
        blind_send.assert_not_called()

    def test_unverified_messaging_platforms_stop_before_confirmation_or_input(self) -> None:
        platforms = (
            "Telegram", "Signal", "Discord", "Instagram", "Messenger",
            "Unlisted Service",
        )
        for platform in platforms:
            with self.subTest(platform=platform):
                with (
                    patch.object(send_message, "_PYAUTOGUI", True),
                    patch.object(send_message, "_desktop_send") as desktop_send,
                    patch.object(send_message, "_send_and_report") as send_and_report,
                    patch.object(send_message, "_send_whatsapp") as whatsapp_send,
                    patch.object(
                        send_message.action_policy, "request_confirmation"
                    ) as request_confirmation,
                ):
                    result = send_message.send_message({
                        "receiver": "Synthetic Contact",
                        "message_text": "Synthetic text; never deliver",
                        "platform": platform,
                    })

                self.assertIn("status=failed", result)
                self.assertIn("no verified", result)
                self.assertIn("no message was sent", result)
                self.assertEqual(self.prompts, [])
                desktop_send.assert_not_called()
                send_and_report.assert_not_called()
                whatsapp_send.assert_not_called()
                request_confirmation.assert_not_called()

    def test_whatsapp_recipient_preflight_failure_never_shows_send_confirmation(self) -> None:
        with patch.object(
            send_message,
            "_prepare_whatsapp_recipient",
            return_value=(None, "no unique chat was found"),
        ):
            result = send_message.send_message({
                "receiver": "Unknown Contact",
                "message_text": "Synthetic test; never deliver",
                "platform": "WhatsApp",
            })

        self.assertIn("status=failed", result)
        self.assertIn("no unique chat was found", result)
        self.assertEqual(self.prompts, [])
        self.assertFalse(confirm.voice_pending())

    def test_meet_does_not_open_before_hud_accepts(self) -> None:
        opened = threading.Event()

        with patch.object(
            meet_control, "_open_meet",
            side_effect=lambda _browser: opened.set() or "mocked",
        ):
            result = meet_control.meet_control({"action": "create"})

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertFalse(opened.is_set())

            confirm.resolve(True)

            self.assertTrue(opened.wait(2))

    def test_model_parameter_cannot_bypass_close_app_hud(self) -> None:
        match = appidentity.Match(
            pid=12345, name="SyntheticApp.exe", score=100, is_self=False
        )
        closed = threading.Event()

        with (
            patch.object(appidentity, "_PSUTIL", True),
            patch.object(appidentity, "running", return_value=[match]),
            patch.object(
                appidentity, "request_close",
                side_effect=lambda _match: closed.set() or (True, "mocked"),
            ),
        ):
            result = computer_control._close_app(
                "SyntheticApp", confirmed_index=True
            )

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertEqual(self.prompts[-1][1], "SyntheticApp")
            self.assertFalse(closed.is_set())

            confirm.resolve(False)

            self.assertFalse(closed.wait(0.1))


if __name__ == "__main__":
    unittest.main()
