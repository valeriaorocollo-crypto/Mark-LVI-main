from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from actions.browser_control import _BrowserSession


class BrowserFormTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, locator):
        page = type(
            "Page",
            (),
            {"url": "https://example.test", "locator": lambda _page, _selector: locator},
        )()
        session = _BrowserSession.__new__(_BrowserSession)

        async def get_page():
            return page

        session._get_page = get_page
        session._reserve_interaction = lambda _amount=1: True
        return session

    async def test_fill_form_verifies_safe_text_fields(self):
        locator = type(
            "Locator",
            (),
            {
                "count": AsyncMock(return_value=1),
                "get_attribute": AsyncMock(
                    side_effect=lambda name: {
                        "type": "text",
                        "autocomplete": "email",
                    }.get(name)
                ),
                "clear": AsyncMock(),
                "type": AsyncMock(),
                "input_value": AsyncMock(return_value="person@example.test"),
            },
        )()
        session = self._session(locator)

        result = await session.fill_form(
            {'input[name="email"]': "person@example.test"}
        )

        self.assertIn("status=done", result)
        locator.clear.assert_awaited_once()
        locator.type.assert_awaited_once_with("person@example.test", delay=40)
        locator.input_value.assert_awaited_once()

    async def test_fill_form_refuses_password_inputs_without_typing(self):
        locator = type(
            "Locator",
            (),
            {
                "count": AsyncMock(return_value=1),
                "get_attribute": AsyncMock(
                    side_effect=lambda name: "password" if name == "type" else None
                ),
                "clear": AsyncMock(),
                "type": AsyncMock(),
                "input_value": AsyncMock(return_value=""),
            },
        )()
        session = self._session(locator)

        result = await session.fill_form({"input#field": "secret-value"})

        self.assertIn("status=failed", result)
        self.assertNotIn("secret-value", result)
        locator.clear.assert_not_awaited()
        locator.type.assert_not_awaited()

    async def test_fill_form_refuses_credential_named_fields(self):
        locator = type(
            "Locator",
            (),
            {
                "count": AsyncMock(return_value=1),
                "clear": AsyncMock(),
                "type": AsyncMock(),
            },
        )()
        session = self._session(locator)

        result = await session.fill_form(
            {'input[name="credential"]': "private-credential"}
        )

        self.assertIn("status=failed", result)
        self.assertNotIn("private-credential", result)
        locator.count.assert_not_awaited()
        locator.clear.assert_not_awaited()
        locator.type.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
