from __future__ import annotations

import unittest

from plugins import _template


class PluginTemplateTests(unittest.TestCase):
    def test_unimplemented_template_never_claims_success(self) -> None:
        result = _template.run({"example_arg": "value"})

        self.assertIn("status=unverified", result)
        self.assertNotIn("status=done", result)


if __name__ == "__main__":
    unittest.main()
