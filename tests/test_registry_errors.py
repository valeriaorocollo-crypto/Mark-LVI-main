from __future__ import annotations

import unittest
from unittest.mock import patch

from core.action_loader import ActionRecord, ActionRegistry
from core.plugin_loader import PluginRecord, PluginRegistry


class RegistryErrorPrivacyTests(unittest.TestCase):
    def test_action_failure_does_not_log_or_return_exception_message(self) -> None:
        private_detail = "synthetic-token-should-not-leak"
        logs: list[str] = []

        def fail(*_args, **_kwargs):
            raise RuntimeError(private_detail)

        registry = ActionRegistry(
            {
                "synthetic_action": ActionRecord(
                    name="synthetic_action",
                    handler=fail,
                    valid=True,
                )
            },
            logs.append,
        )

        result = registry.run("synthetic_action", {})

        self.assertIn("status=failed", result)
        self.assertIn("error=RuntimeError", result)
        self.assertNotIn(private_detail, result)
        self.assertEqual(logs, ["Action 'synthetic_action' failed (RuntimeError)."])

    def test_action_registry_normalizes_legacy_success_text(self) -> None:
        registry = ActionRegistry(
            {
                "synthetic_action": ActionRecord(
                    name="synthetic_action",
                    handler=lambda **_kwargs: "Done.",
                    valid=True,
                )
            },
            lambda _message: None,
        )

        result = registry.run("synthetic_action", {})

        self.assertIn("status=unverified", result)
        self.assertIn("<<<UNTRUSTED", result)
        self.assertNotIn("status=done", result)

    def test_plugin_failure_does_not_log_or_return_exception_message(self) -> None:
        private_detail = "synthetic-token-should-not-leak"
        logs: list[str] = []
        notices: list[str] = []

        def fail(_parameters):
            raise RuntimeError(private_detail)

        registry = PluginRegistry(
            {
                "synthetic_plugin": PluginRecord(
                    name="synthetic_plugin",
                    run=fail,
                    valid=True,
                )
            },
            logs.append,
            notices.append,
        )

        with patch("core.plugin_loader.get_plugin_enabled", return_value=True):
            result = registry.run("synthetic_plugin", {})

        self.assertIn("RuntimeError", result)
        self.assertNotIn(private_detail, result)
        self.assertEqual(
            logs,
            ["Plugin 'synthetic_plugin' failed (RuntimeError)."],
        )
        self.assertEqual(
            notices,
            ["Plugin 'synthetic_plugin' failed (RuntimeError)."],
        )

    def test_plugin_registry_normalizes_legacy_success_text(self) -> None:
        registry = PluginRegistry(
            {
                "synthetic_plugin": PluginRecord(
                    name="synthetic_plugin",
                    run=lambda _parameters: "Done.",
                    valid=True,
                )
            },
            lambda _message: None,
            lambda _message: None,
        )

        with patch("core.plugin_loader.get_plugin_enabled", return_value=True):
            result = registry.run("synthetic_plugin", {})

        self.assertIn("status=unverified", result)
        self.assertIn("<<<UNTRUSTED", result)


if __name__ == "__main__":
    unittest.main()
