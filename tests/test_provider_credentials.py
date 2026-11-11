from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import config_manager


class ProviderCredentialTests(unittest.TestCase):
    def test_delete_provider_credentials_removes_selection_and_secret(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                json.dumps(
                    {
                        "providers": {
                            "creds": {"openai_compat": {"api_key": "secret"}},
                            "sidecar": "openai_compat",
                            "pipeline": {"llm": "openai_compat"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertTrue(
                    config_manager.delete_provider_credentials("openai_compat")
                )

            saved = json.loads(config_file.read_text(encoding="utf-8"))
            providers = saved["providers"]
            self.assertNotIn("openai_compat", providers["creds"])
            self.assertEqual(providers["sidecar"], "")
            self.assertEqual(providers["pipeline"]["llm"], "")
            self.assertNotIn(
                "provider:openai_compat:api_key", fake.values
            )
            self.assertNotIn('"secret"', config_file.read_text(encoding="utf-8"))

    def test_provider_api_key_is_saved_and_read_from_secure_store(self) -> None:
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
                config_manager.save_provider_config(
                    "openai_compat",
                    {"api_key": "  provider-secret  ", "model": "qwen"},
                )
                self.assertEqual(
                    config_manager.get_provider_config("openai_compat"),
                    {"api_key": "provider-secret", "model": "qwen"},
                )

            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("provider-secret", saved)
            self.assertNotIn('"api_key"', saved)
            self.assertEqual(
                fake.values["provider:openai_compat:api_key"], "provider-secret"
            )

    def test_legacy_provider_key_is_migrated_and_removed_from_json(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                json.dumps(
                    {"providers": {"creds": {
                        "openai_compat": {
                            "api_key": "legacy-provider-secret",
                            "model": "qwen",
                        }
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
                    config_manager.get_provider_config("openai_compat"),
                    {"model": "qwen", "api_key": "legacy-provider-secret"},
                )

            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("legacy-provider-secret", saved)
            self.assertEqual(
                fake.values["provider:openai_compat:api_key"],
                "legacy-provider-secret",
            )

    def test_provider_migration_failure_rolls_back_new_secret(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                '{"providers":{"creds":{"openai_compat":'
                '{"api_key":"legacy-secret"}}}}',
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
                patch.object(
                    config_manager,
                    "_write_api_config",
                    side_effect=OSError("simulated write failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "rolled back"):
                    config_manager.get_providers()

            self.assertNotIn("provider:openai_compat:api_key", fake.values)
            self.assertIn("legacy-secret", config_file.read_text(encoding="utf-8"))

    def test_provider_save_failure_restores_previous_secret(self) -> None:
        fake = _FakeKeyring()
        fake.values["provider:openai_compat:api_key"] = "previous-secret"
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
                patch.object(
                    config_manager,
                    "_write_api_config",
                    side_effect=OSError("simulated write failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "restored"):
                    config_manager.save_provider_config(
                        "openai_compat", {"api_key": "new-secret"}
                    )

            self.assertEqual(
                fake.values["provider:openai_compat:api_key"],
                "previous-secret",
            )

    def test_clearing_provider_key_removes_it_from_secure_store(self) -> None:
        fake = _FakeKeyring()
        fake.values["provider:openai_compat:api_key"] = "provider-secret"
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_provider_config(
                    "openai_compat", {"api_key": ""}
                )

            self.assertNotIn(
                "provider:openai_compat:api_key", fake.values
            )

    def test_bulk_provider_save_keeps_api_keys_out_of_config(self) -> None:
        fake = _FakeKeyring()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
                patch.object(
                    config_manager,
                    "_write_api_config",
                    wraps=config_manager._write_api_config,
                ) as write_config,
            ):
                config_manager.save_providers(
                    mode="pipeline",
                    pipeline={"llm": "openai_compat"},
                    creds={
                        "openai_compat": {
                            "api_key": "bulk-provider-secret",
                            "model": "qwen",
                        }
                    },
                )

            self.assertEqual(write_config.call_count, 1)
            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("bulk-provider-secret", saved)
            self.assertEqual(
                fake.values["provider:openai_compat:api_key"],
                "bulk-provider-secret",
            )


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
