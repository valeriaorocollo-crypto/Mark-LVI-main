from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions import computer_control
from core import confirm, session_grants
from core import gemini
import main


class _CaptureUI:
    muted = False

    def __init__(self, *, stop_on_begin: bool = False) -> None:
        self.events: list[str] = []
        self.token: threading.Event | None = None
        self.stop_on_begin = stop_on_begin

    def set_state(self, _state: str) -> None:
        pass

    def write_log(self, _message: str) -> None:
        pass

    def begin_capture_activity(self, source: str) -> threading.Event:
        self.events.append(f"indicator:{source}")
        self.token = threading.Event()
        if self.stop_on_begin:
            self.token.set()
        return self.token

    def mark_capture_transmitting(self, token: threading.Event) -> bool:
        self.events.append("transmitting")
        return not token.is_set()

    def end_capture_activity(self, token: threading.Event) -> None:
        self.events.append("indicator-ended")

    def start_camera_stream(self) -> None:
        self.events.append("camera-preview")

    def stop_camera_stream(self) -> None:
        self.events.append("camera-stopped")


class _Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.sent: list[dict] = []

    async def send_client_content(self, **payload) -> None:
        self.events.append("provider-send")
        self.sent.append(payload)


class ScreenCaptureConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        self.grant_prompts: list[tuple[str, str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
            show_grant=lambda title, detail, label: self.grant_prompts.append(
                (title, detail, label)
            ),
        )
        self.store_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.store_directory.cleanup)
        patcher = patch.object(
            session_grants,
            "GRANT_STORE_PATH",
            Path(self.store_directory.name) / "permissions.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def _dispatcher(self, ui: _CaptureUI) -> main.JarvisLive:
        dispatcher = object.__new__(main.JarvisLive)
        dispatcher.ui = ui
        dispatcher._action_registry = SimpleNamespace(
            scheduling=lambda _name: None
        )
        dispatcher._plugin_registry = SimpleNamespace(
            scheduling=lambda _name: None
        )
        dispatcher.session = _Session(ui.events)
        dispatcher._vision_busy = False
        dispatcher._vision_last_time = 0.0
        dispatcher._pending_vision = None
        dispatcher._pending_vision_activity = None
        dispatcher._vision_cam_active = False
        dispatcher._vision_close_pending = False
        dispatcher.speak_error = lambda *_args: None
        return dispatcher

    def _start_tool(self, dispatcher: main.JarvisLive, angle: str):
        response: list[object] = []
        done = threading.Event()

        def execute() -> None:
            response.append(asyncio.run(dispatcher._execute_tool(
                SimpleNamespace(
                    name="screen_process",
                    args={"angle": angle, "text": "Describe this test screen"},
                    id="synthetic-call",
                )
            )))
            done.set()

        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not confirm.pending_title():
            time.sleep(0.01)
        return thread, done, response

    def test_capture_is_not_started_until_the_hud_approves(self) -> None:
        ui = _CaptureUI()
        dispatcher = self._dispatcher(ui)
        capture_calls: list[str] = []

        def capture_screen():
            capture_calls.append("screen")
            ui.events.append("capture")
            return b"synthetic-image", "image/png"

        with (
            patch.object(
                main,
                "_capture_screen",
                side_effect=capture_screen,
            ),
            patch.object(
                main,
                "_capture_camera",
                side_effect=lambda: capture_calls.append("camera")
                or (b"synthetic-image", "image/png"),
            ),
        ):
            thread, done, response = self._start_tool(dispatcher, "screen")
            self.assertTrue(confirm.pending_title())
            self.assertEqual(capture_calls, [])
            self.assertEqual(dispatcher.session.sent, [])
            self.assertIn("full screen", self.grant_prompts[0][1].lower())
            confirm.resolve(confirm.ConfirmationDecision.APPROVE_ONCE)
            self.assertTrue(done.wait(2))
            thread.join(2)

            self.assertEqual(capture_calls, ["screen"])
            self.assertEqual(
                [event.split(":", 1)[0] for event in ui.events],
                ["indicator", "capture"],
            )
            self.assertEqual(dispatcher.session.sent, [])
            self.assertIn(
                "[VISION_ACTIVE]",
                response[0].response["result"],
            )

            self.assertTrue(asyncio.run(dispatcher._flush_pending_vision()))

        self.assertEqual(
            [event.split(":", 1)[0] for event in ui.events],
            [
                "indicator",
                "capture",
                "transmitting",
                "provider-send",
                "indicator-ended",
            ],
        )
        self.assertEqual(len(dispatcher.session.sent), 1)

    def test_camera_capture_is_per_operation_and_not_rememberable(self) -> None:
        ui = _CaptureUI()
        dispatcher = self._dispatcher(ui)
        capture_calls: list[str] = []

        def capture_camera():
            capture_calls.append("camera")
            ui.events.append("capture")
            return b"synthetic-camera-image", "image/jpeg"

        with patch.object(main, "_capture_camera", side_effect=capture_camera):
            thread, done, response = self._start_tool(dispatcher, "camera")
            self.assertTrue(confirm.pending_title())
            self.assertEqual(self.grant_prompts, [])
            self.assertEqual(capture_calls, [])
            confirm.resolve(confirm.ConfirmationDecision.APPROVE_ONCE)
            self.assertTrue(done.wait(2))
            thread.join(2)
            self.assertEqual(capture_calls, ["camera"])
            self.assertIn("webcam", self.prompts[0][1].lower())
            self.assertTrue(asyncio.run(dispatcher._flush_pending_vision()))

        self.assertIn("[VISION_ACTIVE]", response[0].response["result"])
        self.assertEqual(
            [event.split(":", 1)[0] for event in ui.events],
            [
                "indicator",
                "capture",
                "camera-preview",
                "transmitting",
                "provider-send",
                "indicator-ended",
            ],
        )

    def test_cancelled_capture_does_not_read_screen_or_call_provider(self) -> None:
        ui = _CaptureUI()
        dispatcher = self._dispatcher(ui)
        capture_calls: list[str] = []

        with (
            patch.object(
                main,
                "_capture_screen",
                side_effect=lambda: capture_calls.append("screen")
                or (b"synthetic-image", "image/png"),
            ),
            patch.object(
                main,
                "_capture_camera",
                side_effect=lambda: capture_calls.append("camera")
                or (b"synthetic-image", "image/png"),
            ),
        ):
            thread, done, response = self._start_tool(dispatcher, "camera")
            self.assertTrue(confirm.pending_title())
            confirm.resolve(confirm.ConfirmationDecision.CANCEL)
            self.assertTrue(done.wait(2))
            thread.join(2)

        self.assertEqual(capture_calls, [])
        self.assertEqual(dispatcher.session.sent, [])
        self.assertEqual(ui.events, [])
        self.assertIn("status=failed", response[0].response["result"])

    def test_stop_button_blocks_capture_after_approval(self) -> None:
        ui = _CaptureUI(stop_on_begin=True)
        dispatcher = self._dispatcher(ui)
        capture_calls: list[str] = []
        with patch.object(
            main,
            "_capture_screen",
            side_effect=lambda: capture_calls.append("screen")
            or (b"synthetic-image", "image/png"),
        ):
            thread, done, response = self._start_tool(dispatcher, "screen")
            self.assertTrue(confirm.pending_title())
            confirm.resolve(confirm.ConfirmationDecision.APPROVE_ONCE)
            self.assertTrue(done.wait(2))
            thread.join(2)

        self.assertEqual(capture_calls, [])
        self.assertEqual(dispatcher.session.sent, [])
        self.assertEqual(
            [event.split(":", 1)[0] for event in ui.events],
            ["indicator", "indicator-ended"],
        )
        self.assertIn("status=failed", response[0].response["result"])

    def test_screen_search_indicator_precedes_capture_and_stop_blocks_upload(self) -> None:
        fake_google = types.ModuleType("google")
        fake_google.__path__ = []
        fake_google.genai = types.ModuleType("google.genai")
        fake_google.genai.types = SimpleNamespace(
            Part=SimpleNamespace(from_bytes=lambda **_kwargs: object())
        )

        class CaptureUI(_CaptureUI):
            def __init__(self, *, stop_after_capture: bool = False) -> None:
                super().__init__()
                self.stop_after_capture = stop_after_capture

        def find_element(ui: CaptureUI):
            class Image:
                def save(self, destination, format: str) -> None:
                    ui.events.append("capture")
                    destination.write(b"synthetic-screen")
                    if ui.stop_after_capture:
                        ui.token.set()

            fake_pyautogui = SimpleNamespace(
                size=lambda: (640, 480),
                screenshot=lambda: Image(),
            )

            def send_to_provider(*_args, **_kwargs):
                ui.events.append("provider-send")
                return SimpleNamespace(text="120,240")

            with (
                patch.dict(sys.modules, {
                    "google": fake_google,
                    "google.genai": fake_google.genai,
                }),
                patch.object(computer_control, "_get_api_key", return_value="synthetic-key"),
                patch.object(computer_control, "_require_pyautogui"),
                patch.object(computer_control, "pyautogui", fake_pyautogui),
                patch.object(gemini, "call", side_effect=send_to_provider),
            ):
                return computer_control._screen_find(
                    "synthetic blue icon", player=ui
                )

        ui = CaptureUI()
        self.assertEqual(find_element(ui), (120, 240))
        self.assertEqual(
            [event.split(":", 1)[0] for event in ui.events],
            [
                "indicator",
                "capture",
                "transmitting",
                "provider-send",
                "indicator-ended",
            ],
        )

        stopped_ui = CaptureUI(stop_after_capture=True)
        result = find_element(stopped_ui)
        self.assertIn("status=failed", result)
        self.assertEqual(
            [event.split(":", 1)[0] for event in stopped_ui.events],
            ["indicator", "capture", "indicator-ended"],
        )


if __name__ == "__main__":
    unittest.main()
