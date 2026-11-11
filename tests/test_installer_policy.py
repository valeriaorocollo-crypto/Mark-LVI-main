from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from core import installer


class InstallerPolicyTests(unittest.TestCase):
    def test_missing_packages_are_not_installed_without_confirmation(self) -> None:
        logs: list[str] = []
        with (
            patch.object(installer, "_available", return_value=False),
            patch.object(installer, "_pip") as pip,
        ):
            installer.install_for_config({}, logs.append)

        pip.assert_not_called()
        self.assertTrue(any("not started" in message for message in logs))

    def test_confirmation_is_required_by_keyword_only_argument(self) -> None:
        self.assertIs(
            inspect.signature(
                installer.install_for_config
            ).parameters["confirmed"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

    def test_failed_package_install_is_reported_as_incomplete(self) -> None:
        logs: list[str] = []
        with (
            patch.object(installer, "_available", return_value=False),
            patch.object(installer, "_pip", return_value=False),
        ):
            installer.install_for_config({}, logs.append, confirmed=True)

        self.assertTrue(any("incomplete" in message for message in logs))
        self.assertFalse(any("All dependencies ready" in message for message in logs))
