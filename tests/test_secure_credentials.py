from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from memory import config_manager


class SecureCredentialTests(unittest.TestCase):
    def test_secure_key_is_preferred_over_config_file(self) -> None:
        with (
            patch.dict("sys.modules", {"keyring": _FakeKeyring("secure-key")}),
            patch.object(config_manager.platform, "system", return_value="Windows"),
            patch.object(
                config_manager,
                "load_api_keys",
                return_value={"gemini_api_key": "legacy-key"},
            ),
        ):
            self.assertEqual(config_manager.get_gemini_key(), "secure-key")

    def test_empty_key_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            config_manager.save_api_keys(" ")

    def test_non_text_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be text"):
            config_manager.save_api_keys(None)

    def test_backend_without_valid_priority_is_rejected(self) -> None:
        fake = _FakeKeyring(None)
        fake.backend.priority = None
        with (
            patch.dict("sys.modules", {"keyring": fake}),
            patch.object(config_manager.platform, "system", return_value="Windows"),
        ):
            with self.assertRaisesRegex(RuntimeError, "backend is unavailable"):
                config_manager.save_api_keys("some-secret")

    def test_delete_uses_secure_store_without_returning_secret(self) -> None:
        fake = _FakeKeyring("secure-key")
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                '{"gemini_api_key": "legacy-key"}', encoding="utf-8"
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertIs(config_manager.delete_gemini_key(), True)
                self.assertIsNone(fake.value)
                self.assertNotIn(
                    "gemini_api_key", config_file.read_text(encoding="utf-8")
                )

    def test_save_uses_secure_store_and_preserves_nonsecret_config(self) -> None:
        fake = _FakeKeyring(None)
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text('{"language": "es"}', encoding="utf-8")
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_api_keys("  new-secret  ")

            self.assertEqual(fake.value, "new-secret")
            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("new-secret", saved)
            self.assertNotIn("gemini_api_key", saved)
            self.assertIn('"language": "es"', saved)

    def test_saving_key_invalidates_the_live_client_cache(self) -> None:
        fake = _FakeKeyring(None)
        invalidate = Mock()
        gemini_module = type(
            "GeminiModule", (), {"invalidate_api_key_cache": staticmethod(invalidate)}
        )()
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            with (
                patch.dict(
                    "sys.modules",
                    {"keyring": fake, "core.gemini": gemini_module},
                ),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(
                    config_manager, "CONFIG_FILE", config_dir / "api_keys.json"
                ),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                config_manager.save_api_keys("new-secret")

        invalidate.assert_called_once_with()

    def test_save_failure_restores_previous_secure_key(self) -> None:
        fake = _FakeKeyring("previous-secret")
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text('{"language": "es"}', encoding="utf-8")
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
                    config_manager.save_api_keys("new-secret")

            self.assertEqual(fake.value, "previous-secret")

    def test_legacy_key_is_migrated_to_secure_store(self) -> None:
        fake = _FakeKeyring(None)
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "api_keys.json"
            config_file.write_text(
                '{"gemini_api_key": "legacy-secret", "language": "es"}',
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", Path(temp_dir)),
            ):
                self.assertEqual(config_manager.get_gemini_key(), "legacy-secret")

            saved_config = config_file.read_text(encoding="utf-8")
            self.assertEqual(fake.value, "legacy-secret")
            self.assertNotIn("legacy-secret", saved_config)
            self.assertIn('"language": "es"', saved_config)

    def test_legacy_cleanup_failure_rolls_back_new_secure_key(self) -> None:
        fake = _FakeKeyring(None)
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                '{"gemini_api_key": "legacy-secret"}', encoding="utf-8"
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
                    config_manager.get_gemini_key()

            self.assertIsNone(fake.value)
            self.assertIn("legacy-secret", config_file.read_text(encoding="utf-8"))

    def test_existing_secure_key_removes_stale_legacy_copy(self) -> None:
        fake = _FakeKeyring("secure-secret")
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                '{"gemini_api_key": "legacy-secret", "language": "es"}',
                encoding="utf-8",
            )
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertEqual(config_manager.get_gemini_key(), "secure-secret")

            saved = config_file.read_text(encoding="utf-8")
            self.assertNotIn("legacy-secret", saved)
            self.assertIn('"language": "es"', saved)

    def test_existing_secure_key_reports_stale_copy_cleanup_failure(self) -> None:
        fake = _FakeKeyring("secure-secret")
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text(
                '{"gemini_api_key": "legacy-secret"}', encoding="utf-8"
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
                with self.assertRaisesRegex(RuntimeError, "could not be removed"):
                    config_manager.get_gemini_key()

            self.assertEqual(fake.value, "secure-secret")
            self.assertIn("legacy-secret", config_file.read_text(encoding="utf-8"))

    def test_non_object_json_does_not_break_config_load_or_key_lookup(self) -> None:
        fake = _FakeKeyring(None)
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "api_keys.json"
            config_file.write_text("null", encoding="utf-8")
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_dir),
            ):
                self.assertEqual(config_manager.load_api_keys(), {})
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    config_manager.get_gemini_key()

    def test_plaintext_keyring_is_rejected_without_config_fallback(self) -> None:
        fake = _FakeKeyring(None, backend_name="PlaintextKeyring")
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config" / "api_keys.json"
            with (
                patch.dict("sys.modules", {"keyring": fake}),
                patch.object(config_manager.platform, "system", return_value="Windows"),
                patch.object(config_manager, "CONFIG_FILE", config_file),
                patch.object(config_manager, "CONFIG_DIR", config_file.parent),
            ):
                with self.assertRaisesRegex(RuntimeError, "Plaintext"):
                    config_manager.save_api_keys("must-not-be-saved")
            self.assertFalse(config_file.exists())


class _FakeKeyring:
    def __init__(self, value: str | None, backend_name: str = "WinVaultKeyring"):
        self.value = value
        self.values: dict[str, str] = {}
        self.backend = type(backend_name, (), {"priority": 5})()

    def get_keyring(self):
        return self.backend

    def get_password(self, service: str, account: str) -> str | None:
        if account == "gemini_api_key":
            return self.value
        return self.values.get(account)

    def set_password(self, service: str, account: str, value: str) -> None:
        if account == "gemini_api_key":
            self.value = value
        else:
            self.values[account] = value

    def delete_password(self, service: str, account: str) -> None:
        if account == "gemini_api_key":
            self.value = None
        else:
            self.values.pop(account, None)
