from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import game_updater
from core import confirm


class GameUpdaterConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        with confirm._lock:
            confirm._pending = None
        self.prompts: list[tuple[str, str]] = []
        confirm.bind(
            lambda title, detail: self.prompts.append((title, detail)),
            lambda: None,
        )

    def tearDown(self) -> None:
        with confirm._lock:
            confirm._pending = None
        confirm.bind(None, None)

    def test_update_waits_for_confirmation_and_cancel_skips_launcher(self) -> None:
        executed = threading.Event()
        with patch.object(
            game_updater,
            "_game_updater_execute",
            side_effect=lambda *_args: executed.set() or "status=done action=update",
        ):
            result = game_updater.game_updater({
                "action": "update",
                "platform": "steam",
                "game_name": "Synthetic Game",
                "shutdown_when_done": "true",
            })

            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("Synthetic Game", self.prompts[-1][1])
            self.assertIn("Shutdown after completion: yes", self.prompts[-1][1])
            self.assertFalse(executed.is_set())

            confirm.resolve(False)

            self.assertFalse(executed.wait(0.1))

    def test_new_steam_session_requires_manual_profile_check_before_action(self) -> None:
        steam_executable = Path(__file__).resolve()
        with (
            patch.object(
                game_updater, "_is_steam_running", side_effect=[False, True]
            ),
            patch.object(game_updater, "_steam_exe", return_value=steam_executable),
            patch.object(game_updater.subprocess, "Popen") as launch,
            patch.object(game_updater.time, "sleep"),
        ):
            ready, reason = game_updater._ensure_steam_running(Path("C:/Steam"))

        self.assertFalse(ready)
        self.assertIn("opened", reason)
        self.assertIn("sign-in/profile selection", reason)
        launch.assert_called_once()

    def test_running_steam_is_ready_without_launching_another_instance(self) -> None:
        with (
            patch.object(game_updater, "_is_steam_running", return_value=True),
            patch.object(game_updater.subprocess, "Popen") as launch,
        ):
            ready, reason = game_updater._ensure_steam_running(Path("C:/Steam"))

        self.assertTrue(ready)
        self.assertEqual(reason, "")
        launch.assert_not_called()

    def test_install_opens_steam_dialog_but_does_not_click_controls(self) -> None:
        with (
            patch.object(
                game_updater, "_ensure_steam_running", return_value=(True, "")
            ),
            patch.object(game_updater, "_get_steam_games", return_value=[]),
            patch.object(game_updater, "is_windows", return_value=True),
            patch.object(game_updater, "_launch_steam_url") as launch,
            patch.object(game_updater.threading, "Thread") as thread,
        ):
            result = game_updater._install_steam_game(
                Path("C:/Steam"), game_name="Synthetic Game", app_id="12345"
            )

        self.assertIn("complete installation manually", result)
        launch.assert_called_once_with(
            game_updater._steam_exe(Path("C:/Steam")),
            "steam://install/12345",
        )
        thread.assert_not_called()

    def test_schedule_is_confirmed_and_bounds_are_checked(self) -> None:
        with patch.object(
            game_updater, "_game_updater_execute", return_value="status=done action=schedule"
        ) as execute:
            result = game_updater.game_updater({
                "action": "schedule",
                "hour": 25,
                "minute": 0,
            })

            self.assertIn("00:00 and 23:59", result)
            self.assertEqual(self.prompts, [])
            execute.assert_not_called()

            result = game_updater.game_updater({
                "action": "schedule",
                "platform": "steam",
                "hour": 3,
                "minute": 30,
            })
            self.assertIn("[CONFIRMATION_PENDING]", result)
            self.assertIn("03:30 daily", self.prompts[-1][1])
            confirm.resolve(False)
            execute.assert_not_called()

    def test_scheduled_update_uses_internal_approval_from_schedule(self) -> None:
        with patch.object(
            game_updater, "_game_updater_execute", return_value="status=done action=update"
        ) as execute:
            result = game_updater.game_updater(
                {"action": "update", "platform": "both"},
                _scheduled=True,
            )

        self.assertEqual(result, "status=done action=update")
        execute.assert_called_once()
        self.assertEqual(self.prompts, [])


if __name__ == "__main__":
    unittest.main()
