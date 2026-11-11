from __future__ import annotations

import unittest
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from core import tts
from providers import audio, llm_openai, stt_whisper, tts_system


class ProviderRegressionTests(unittest.TestCase):
    def test_openai_compatible_provider_sends_bearer_key(self) -> None:
        provider = llm_openai.OpenAICompatLLM({
            "base_url": "https://api.example.test",
            "model": "test-model",
            "api_key": "test-secret",
        })

        self.assertEqual(
            provider._headers()["Authorization"],
            "Bearer test-secret",
        )

    def test_whisper_provider_sends_bearer_key(self) -> None:
        provider = stt_whisper.WhisperSTT({
            "backend": "api",
            "base_url": "https://api.example.test/v1",
            "model": "whisper-test",
            "api_key": "test-secret",
        })
        client_context = MagicMock()
        client = client_context.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {"text": "recognized"}

        with (
            patch("httpx.Client", return_value=client_context),
            patch.object(audio, "to_wav", return_value=b"wav"),
        ):
            result = provider._api_blocking(b"\x00\x00", 16_000)

        self.assertEqual(result, "recognized")
        self.assertEqual(
            client.post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-secret",
        )

    def test_openai_compatible_url_removes_duplicated_terminal_v1(self) -> None:
        self.assertEqual(
            llm_openai._normalise("https://api.example.test/v1/v1"),
            "https://api.example.test/v1",
        )
        self.assertEqual(
            llm_openai._normalise("https://api.example.test/api/v1"),
            "https://api.example.test/api/v1",
        )

    def test_spd_say_alone_is_not_advertised_as_a_wav_engine(self) -> None:
        def find_executable(name: str) -> str | None:
            return "/usr/bin/spd-say" if name == "spd-say" else None

        with (
            patch.object(tts_system, "_SYS", "Linux"),
            patch.object(tts_system.shutil, "which", side_effect=find_executable),
        ):
            self.assertEqual(tts_system.engine_name(), "")
            self.assertFalse(tts_system.available())

    def test_incompatible_kokoro_reports_repair_without_running_pip(self) -> None:
        with (
            patch.dict(sys.modules, {"kokoro": ModuleType("kokoro")}),
            patch("subprocess.run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "incompatible"):
                tts._import_kokoro_pipeline()

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
