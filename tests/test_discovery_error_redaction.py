from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.action_loader import discover_actions
from core.plugin_loader import discover_plugins


class DiscoveryErrorRedactionTests(unittest.TestCase):
    def test_action_and_plugin_import_errors_do_not_log_exception_text(self) -> None:
        private_detail = "synthetic-private-token"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            actions_dir = root / "actions"
            plugins_dir = root / "plugins"
            actions_dir.mkdir()
            plugins_dir.mkdir()
            (actions_dir / "broken.py").write_text(
                f"raise RuntimeError({private_detail!r})", encoding="utf-8"
            )
            (plugins_dir / "broken.py").write_text(
                f"raise RuntimeError({private_detail!r})", encoding="utf-8"
            )

            logs: list[str] = []
            action_registry = discover_actions(actions_dir, logger=logs.append)
            with patch("core.plugin_loader.get_plugin_trusted", return_value=True):
                plugin_registry = discover_plugins(
                    plugins_dir, set(), logger=logs.append
                )

        self.assertEqual(len(action_registry._all_records), 1)
        self.assertEqual(len(plugin_registry._all_records), 1)
        records = action_registry._all_records + plugin_registry._all_records
        self.assertTrue(all("RuntimeError" in record.error for record in records))
        self.assertNotIn(private_detail, "\n".join(logs))


if __name__ == "__main__":
    unittest.main()
