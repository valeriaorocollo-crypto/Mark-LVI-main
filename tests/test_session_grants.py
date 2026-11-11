from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import session_grants


class SessionGrantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.store_directory.cleanup)
        patcher = patch.object(
            session_grants,
            "GRANT_STORE_PATH",
            Path(self.store_directory.name) / "permissions.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def scope(self, task: str = "find the blue icon") -> session_grants.GrantScope:
        return session_grants.scope_for("share_screen_search", task)

    def test_grant_is_limited_to_the_exact_supported_task(self) -> None:
        allowed = self.scope()
        other_task = self.scope("find the red icon")

        session_grants.create(allowed, "Find the blue icon")

        self.assertTrue(session_grants.allows(allowed))
        self.assertFalse(session_grants.allows(other_task))
        self.assertEqual(len(session_grants.active()), 1)

    def test_unsupported_grant_scope_is_rejected(self) -> None:
        unsupported = session_grants.GrantScope(
            "send_message", "WhatsApp", "all_contacts"
        )

        with self.assertRaises(ValueError):
            session_grants.create(unsupported, "Send messages")

        self.assertFalse(session_grants.active())

    def test_grant_expires_at_fixed_thirty_day_deadline(self) -> None:
        scope = self.scope()

        with patch.object(session_grants.time, "time", return_value=100):
            session_grants.create(scope, "Find the blue icon")
        with patch.object(
            session_grants.time,
            "time",
            return_value=100 + session_grants.GRANT_TTL_SECONDS - 1,
        ):
            self.assertTrue(session_grants.allows(scope))
            expiry = session_grants.active()[0].expires_at
        with patch.object(
            session_grants.time,
            "time",
            return_value=100 + session_grants.GRANT_TTL_SECONDS,
        ):
            self.assertFalse(session_grants.allows(scope))
            self.assertEqual(session_grants.active(), ())
        self.assertEqual(expiry, 100 + session_grants.GRANT_TTL_SECONDS)

    def test_grant_survives_reload_without_sliding_its_expiration(self) -> None:
        scope = self.scope()
        with patch.object(session_grants.time, "time", return_value=1_000):
            session_grants.create(scope, "Find the blue icon")
        with patch.object(session_grants.time, "time", return_value=1_000):
            initial_expiry = session_grants.active()[0].expires_at
        payload = json.loads(
            session_grants.GRANT_STORE_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(payload["version"], 3)
        self.assertRegex(payload["grants"][0]["id"], r"^[0-9a-f]{32}$")
        self.assertNotIn("image_bytes", json.dumps(payload))

        with patch.object(session_grants.time, "time", return_value=5_000):
            self.assertTrue(session_grants.allows(scope))
            grant = session_grants.active()[0]
            self.assertEqual(grant.expires_at, initial_expiry)
            self.assertEqual(grant.use_count, 1)
            self.assertEqual(grant.last_used_at, 5_000)

    def test_usage_updates_metadata_without_extending_expiration(self) -> None:
        scope = self.scope()
        with patch.object(session_grants.time, "time", return_value=10_000):
            session_grants.create(scope, "Find the blue icon")
        original_expiry = 10_000 + session_grants.GRANT_TTL_SECONDS

        with patch.object(session_grants.time, "time", return_value=20_000):
            self.assertTrue(session_grants.allows(scope))
            self.assertTrue(session_grants.allows(scope))
            grant = session_grants.active()[0]
            self.assertEqual(grant.use_count, 2)
            self.assertEqual(grant.last_used_at, 20_000)
            self.assertEqual(grant.expires_at, original_expiry)

    def test_malformed_store_fails_closed_and_can_be_cleared(self) -> None:
        session_grants.GRANT_STORE_PATH.write_text("{", encoding="utf-8")
        scope = self.scope()

        with self.assertRaises(session_grants.GrantStoreError):
            session_grants.allows(scope)
        with self.assertRaises(session_grants.GrantStoreError):
            session_grants.active()

        self.assertEqual(session_grants.revoke_all(), 0)
        self.assertEqual(session_grants.active(), ())

    def test_profile_mismatch_clears_foreign_permissions(self) -> None:
        scope = self.scope()
        session_grants.create(scope, "Find the blue icon")
        payload = json.loads(
            session_grants.GRANT_STORE_PATH.read_text(encoding="utf-8")
        )
        payload["profile_id"] = "different-profile"
        session_grants.GRANT_STORE_PATH.write_text(
            json.dumps(payload), encoding="utf-8"
        )

        self.assertFalse(session_grants.allows(scope))
        self.assertEqual(session_grants.active(), ())
        cleared = json.loads(
            session_grants.GRANT_STORE_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(cleared["profile_id"], session_grants._PROFILE_ID)
        self.assertEqual(cleared["grants"], [])

    def test_long_task_is_not_offered_as_a_remembered_permission(self) -> None:
        with self.assertRaises(ValueError):
            session_grants.permission_label(
                "share_screen_search", "x" * 161
            )

    def test_grant_can_be_revoked_individually_or_globally(self) -> None:
        scope = self.scope()
        session_grants.create(scope, "Find the blue icon")

        self.assertTrue(session_grants.revoke(scope))
        self.assertFalse(session_grants.allows(scope))
        self.assertFalse(session_grants.revoke(scope))

        session_grants.create(scope, "Find the blue icon")
        self.assertEqual(session_grants.revoke_all(), 1)
        self.assertFalse(session_grants.allows(scope))

    def test_grant_audit_keeps_only_bounded_scope_metadata(self) -> None:
        scope = self.scope()
        session_grants.create(scope, "Find the blue icon")
        self.assertTrue(session_grants.allows(scope))
        self.assertTrue(session_grants.revoke(scope))

        events = session_grants.recent_events(3)
        self.assertEqual(
            [event.action for event in events],
            ["revoked", "used", "created"],
        )
        self.assertEqual(
            {event.resource for event in events},
            {scope.resource},
        )
        self.assertNotIn(
            "Find the blue icon",
            json.dumps([event.__dict__ for event in events]),
        )

    def test_grants_overlay_wraps_permission_details(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from ui import SessionGrantsOverlay

        app = QApplication.instance() or QApplication([])
        overlay = SessionGrantsOverlay()
        try:
            self.assertTrue(overlay._items.wordWrap())
        finally:
            overlay.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
