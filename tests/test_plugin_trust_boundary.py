from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.plugin_loader import _MAX_PLUGIN_SOURCE_BYTES, discover_plugins
from memory.config_manager import get_plugin_enabled, get_plugin_trusted


class PluginTrustBoundaryTests(unittest.TestCase):
    def test_untrusted_plugin_is_not_imported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugins = root / "plugins"
            plugins.mkdir()
            marker = root / "import-ran"
            (plugins / "untrusted.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )

            registry = discover_plugins(
                plugins,
                set(),
                logger=lambda _message: None,
            )

            self.assertFalse(marker.exists())
            listed = registry.list_for_ui()
            self.assertEqual(len(listed), 1)
            self.assertTrue(listed[0]["trust_required"])
            self.assertIn("run with MARK's permissions", listed[0]["error"])

    def test_explicitly_trusted_plugin_is_imported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugins = root / "plugins"
            plugins.mkdir()
            marker = root / "import-ran"
            (plugins / "trusted.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
                "PLUGIN = {'name': 'trusted', 'description': 'synthetic'}\n"
                "def run(parameters):\n    return 'status=done verified=true'\n",
                encoding="utf-8",
            )

            source = (plugins / "trusted.py").read_bytes()
            source_hash = hashlib.sha256(source).hexdigest()
            with patch(
                "core.plugin_loader.get_plugin_trusted",
                return_value=True,
            ) as trusted:
                registry = discover_plugins(
                    plugins,
                    set(),
                    logger=lambda _message: None,
                )

            self.assertTrue(registry.has("trusted"))
            self.assertTrue(marker.exists())
            trusted.assert_called_once_with("trusted.py", source_hash)

    def test_oversized_plugin_is_rejected_without_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins = Path(temp_dir) / "plugins"
            plugins.mkdir()
            marker = Path(temp_dir) / "import-ran"
            source = (
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            ).encode("utf-8")
            source += b"#" * (_MAX_PLUGIN_SOURCE_BYTES + 1 - len(source))
            (plugins / "oversized.py").write_bytes(source)

            registry = discover_plugins(
                plugins,
                set(),
                logger=lambda _message: None,
            )

        self.assertFalse(marker.exists())
        self.assertIn("2 MiB size limit", registry._all_records[0].error)

    def test_plugins_are_disabled_without_explicit_enablement(self) -> None:
        with patch("memory.config_manager.load_api_keys", return_value={}):
            self.assertFalse(get_plugin_enabled("synthetic"))
            self.assertFalse(
                get_plugin_trusted("synthetic.py", "0" * 64)
            )

    def test_plugin_trust_is_bound_to_exact_source_hash(self) -> None:
        approved_hash = "a" * 64
        with patch(
            "memory.config_manager.load_api_keys",
            return_value={
                "plugins_trusted": {"synthetic.py": approved_hash}
            },
        ):
            self.assertTrue(
                get_plugin_trusted("synthetic.py", approved_hash)
            )
            self.assertFalse(
                get_plugin_trusted("synthetic.py", "b" * 64)
            )


if __name__ == "__main__":
    unittest.main()
