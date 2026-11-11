from __future__ import annotations

import unittest
from unittest.mock import patch

from core import session_grants


class SessionGrantTests(unittest.TestCase):
    def setUp(self) -> None:
        session_grants.revoke_all()

    def tearDown(self) -> None:
        session_grants.revoke_all()

    def test_grant_is_limited_to_the_exact_supported_scope(self) -> None:
        allowed = session_grants.GrantScope(
            "share_screen_search", "Gemini", "active_screen"
        )
        other_resource = session_grants.GrantScope(
            "share_screen_search", "Gemini", "another_screen"
        )

        session_grants.create(allowed, "Share requested screen searches")

        self.assertTrue(session_grants.allows(allowed))
        self.assertFalse(session_grants.allows(other_resource))
        self.assertEqual(len(session_grants.active()), 1)

    def test_unsupported_grant_scope_is_rejected(self) -> None:
        unsupported = session_grants.GrantScope(
            "send_message", "WhatsApp", "all_contacts"
        )

        with self.assertRaises(ValueError):
            session_grants.create(unsupported, "Send messages")

        self.assertFalse(session_grants.active())

    def test_grant_expires_automatically(self) -> None:
        scope = session_grants.GrantScope(
            "share_screen_search", "Gemini", "active_screen"
        )

        with patch.object(session_grants.time, "monotonic", return_value=100):
            session_grants.create(scope, "Share requested screen searches")
        with patch.object(
            session_grants.time,
            "monotonic",
            return_value=100 + session_grants.SESSION_GRANT_TTL_SECONDS + 1,
        ):
            self.assertFalse(session_grants.allows(scope))
            self.assertEqual(session_grants.active(), ())

    def test_grant_can_be_revoked_individually_or_at_session_end(self) -> None:
        scope = session_grants.GrantScope(
            "share_screen_search", "Gemini", "active_screen"
        )
        session_grants.create(scope, "Share requested screen searches")

        self.assertTrue(session_grants.revoke(scope))
        self.assertFalse(session_grants.allows(scope))
        self.assertFalse(session_grants.revoke(scope))

        session_grants.create(scope, "Share requested screen searches")
        self.assertEqual(session_grants.revoke_all(), 1)
        self.assertFalse(session_grants.allows(scope))


if __name__ == "__main__":
    unittest.main()
