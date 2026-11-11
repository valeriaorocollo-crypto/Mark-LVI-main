from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import config_manager


class PluginCredentialTests(unittest.TestCase):
    def test_sensitive_plugin_fields_use_secure_store(self) -> None:
        fake = _FakeKeyring()
        secrets = {
            "private_key": "private-key-value",
            "authorization": "authorization-value",
            "otp": "one-time-code",
        }
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_plugin_config("weather", secrets)
                self.assertEqual(config_manager.get_plugin_config("weather"), secrets)

            saved = config_file.read_text(encoding="utf-8")
            for value in secrets.values():
                self.assertNotIn(value, saved)
            for key, value in secrets.items():
                account = config_manager._plugin_secret_account("weather", key)
                self.assertEqual(fake.values[account], value)

    def test_sensitive_name_or_type_marks_plugin_field_secret(self) -> None:
        self.assertTrue(config_manager.is_plugin_secret_field("private_key"))
        self.assertTrue(config_manager.is_plugin_secret_field("api_key", "text"))
        self.assertTrue(config_manager.is_plugin_secret_field("custom", "password"))
        self.assertFalse(config_manager.is_plugin_secret_field("city", "text"))

    def test_password_fields_use_secure_store(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_plugin_config(
                    "weather",
                    {"token": "plugin-secret", "city": "Lima"},
                    secret_keys=["token"],
                )
                self.assertEqual(
                    config_manager.get_plugin_config("weather"),
                    {"city": "Lima", "token": "plugin-secret"},
                )

            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("plugin-secret", saved)
            self.assertNotIn('"token":', saved)
            self.assertIn('"token"', saved)
            account = config_manager._plugin_secret_account("weather", "token")
            self.assertEqual(fake.values[account], "plugin-secret")

    def test_legacy_password_field_is_migrated(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                json.dumps(
                    {"plugin_config": {"weather": {
                        "token": "legacy-plugin-secret", "city": "Lima"
                    }}}
                ),
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertEqual(
                    config_manager.get_plugin_config(
                        "weather", secret_keys=["token"]
                    ),
                    {"city": "Lima", "token": "legacy-plugin-secret"},
                )

            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("legacy-plugin-secret", saved)

    def test_legacy_sensitive_fields_are_migrated(self) -> None:
        fake = _FakeKeyring()
        secrets = {
            "private_key": "legacy-private-key",
            "authorization": "legacy-authorization",
            "otp": "legacy-one-time-code",
        }
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                json.dumps({"plugin_config": {"weather": secrets}}),
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertEqual(config_manager.get_plugin_config("weather"), secrets)

            saved = config_file.read_text(encoding="utf-8")
            for value in secrets.values():
                self.assertNotIn(value, saved)
            for key, value in secrets.items():
                account = config_manager._plugin_secret_account("weather", key)
                self.assertEqual(fake.values[account], value)

    def test_clearing_password_field_removes_secure_credential(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_plugin_config(
                    "weather",
                    {"token": "plugin-secret"},
                    secret_keys=["token"],
                )
                config_manager.save_plugin_config(
                    "weather",
                    {"token": ""},
                    secret_keys=["token"],
                )

            account = config_manager._plugin_secret_account("weather", "token")
            self.assertNotIn(account, fake.values)


class _FakeKeyring:
    def __init__(self) -> None:
        self.backend = type("WinVaultKeyring", (), {"priority": 5})()
        self.values: dict[str, str] = {}

    def get_keyring(self):
        return self.backend

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get(account)

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[account] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop(account, None)
