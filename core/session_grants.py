"""Explicit, in-memory permissions limited to one MARK process session."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

SESSION_GRANT_TTL_SECONDS = 60 * 60
MAX_SESSION_GRANTS = 32

_SUPPORTED_SCOPES = {
    ("share_screen_search", "Gemini", "active_screen"),
}


@dataclass(frozen=True)
class GrantScope:
    capability: str
    integration: str
    resource: str

    def key(self) -> tuple[str, str, str]:
        return self.capability, self.integration, self.resource


@dataclass(frozen=True)
class ActiveGrant:
    scope: GrantScope
    label: str
    expires_in_seconds: int


@dataclass(frozen=True)
class _Grant:
    scope: GrantScope
    label: str
    expires_at: float


_grants: dict[tuple[str, str, str], _Grant] = {}
_lock = threading.Lock()


def create(scope: GrantScope, label: str) -> None:
    if not isinstance(scope, GrantScope) or scope.key() not in _SUPPORTED_SCOPES:
        raise ValueError("this session permission scope is not supported")
    if not isinstance(label, str) or not label.strip() or len(label) > 240:
        raise ValueError("session permission label must be short text")

    now = time.monotonic()
    with _lock:
        _remove_expired(now)
        if scope.key() not in _grants and len(_grants) >= MAX_SESSION_GRANTS:
            raise RuntimeError("the session permission limit has been reached")
        _grants[scope.key()] = _Grant(
            scope=scope,
            label=label.strip(),
            expires_at=now + SESSION_GRANT_TTL_SECONDS,
        )


def allows(scope: GrantScope) -> bool:
    if not isinstance(scope, GrantScope):
        return False
    now = time.monotonic()
    with _lock:
        _remove_expired(now)
        return scope.key() in _grants


def active() -> tuple[ActiveGrant, ...]:
    now = time.monotonic()
    with _lock:
        _remove_expired(now)
        return tuple(
            ActiveGrant(
                scope=grant.scope,
                label=grant.label,
                expires_in_seconds=max(0, int(grant.expires_at - now)),
            )
            for grant in _grants.values()
        )


def revoke(scope: GrantScope) -> bool:
    if not isinstance(scope, GrantScope):
        return False
    with _lock:
        return _grants.pop(scope.key(), None) is not None


def revoke_all() -> int:
    with _lock:
        count = len(_grants)
        _grants.clear()
        return count


def _remove_expired(now: float) -> None:
    expired = [
        key for key, grant in _grants.items()
        if grant.expires_at <= now
    ]
    for key in expired:
        del _grants[key]
