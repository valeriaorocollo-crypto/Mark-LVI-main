"""Explicit, profile-local permissions with fixed expiration and revocation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

GRANT_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_GRANTS = 32
MAX_GRANT_EVENTS = 256
_STORE_VERSION = 3
_TASK_RESOURCE_RE = re.compile(r"^task-sha256:[0-9a-f]{64}$")
_GRANT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SUPPORTED_CAPABILITIES = {"share_screen_search", "capture_screen"}


class GrantStoreError(RuntimeError):
    """The local permission store could not be trusted or updated."""


def _default_store_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "MARK LVI" / "session-grants.json"


def _profile_id() -> str:
    profile = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    return hashlib.sha256(profile.encode("utf-8")).hexdigest()


GRANT_STORE_PATH = _default_store_path()
_PROFILE_ID = _profile_id()


@dataclass(frozen=True)
class GrantScope:
    capability: str
    integration: str
    resource: str

    def key(self) -> tuple[str, str, str]:
        return self.capability, self.integration, self.resource


@dataclass(frozen=True)
class ActiveGrant:
    grant_id: str
    scope: GrantScope
    label: str
    created_at: int
    expires_at: int
    expires_in_seconds: int
    use_count: int
    last_used_at: int | None


@dataclass(frozen=True)
class GrantEvent:
    action: str
    grant_id: str | None
    capability: str | None
    integration: str | None
    resource: str | None
    timestamp: int


@dataclass(frozen=True)
class _Grant:
    grant_id: str
    scope: GrantScope
    label: str
    created_at: int
    expires_at: int
    use_count: int
    last_used_at: int | None


_lock = threading.RLock()
_events: deque[GrantEvent] = deque(maxlen=MAX_GRANT_EVENTS)


def _record_event(action: str, grant: _Grant | None, timestamp: int) -> None:
    _events.append(
        GrantEvent(
            action=action,
            grant_id=grant.grant_id if grant is not None else None,
            capability=grant.scope.capability if grant is not None else None,
            integration=grant.scope.integration if grant is not None else None,
            resource=grant.scope.resource if grant is not None else None,
            timestamp=timestamp,
        )
    )


def recent_events(limit: int = 100) -> tuple[GrantEvent, ...]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("the event limit must be between 1 and 100")
    with _lock:
        return tuple(reversed(tuple(_events)[-limit:]))


def scope_for(capability: str, task: str) -> GrantScope:
    if capability not in _SUPPORTED_CAPABILITIES:
        raise ValueError("this capture permission capability is not supported")
    if not isinstance(task, str) or not task.strip() or len(task) > 2_000:
        raise ValueError("the visual task must be short, non-empty text")
    normalized = " ".join(task.casefold().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return GrantScope(capability, "Gemini", f"task-sha256:{digest}")


def permission_label(capability: str, task: str) -> str:
    scope_for(capability, task)
    title = "visual search" if capability == "share_screen_search" else "screen capture"
    purpose = " ".join(task.split())
    if len(purpose) > 160:
        raise ValueError(
            "a remembered permission requires a task description of at most "
            "160 characters"
        )
    return f"Share screen captures with Gemini for {title}: {purpose}"


def _validate_scope(scope: GrantScope) -> None:
    if (
        not isinstance(scope, GrantScope)
        or scope.capability not in _SUPPORTED_CAPABILITIES
        or scope.integration != "Gemini"
        or not isinstance(scope.resource, str)
        or not _TASK_RESOURCE_RE.fullmatch(scope.resource)
    ):
        raise ValueError("this permission scope is not supported")


def _load() -> dict[tuple[str, str, str], _Grant]:
    path = GRANT_STORE_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise GrantStoreError(
            f"the local permission store could not be read ({type(exc).__name__})"
        ) from exc

    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GrantStoreError("the local permission store is malformed") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != _STORE_VERSION
        or not isinstance(payload.get("grants"), list)
        or len(payload["grants"]) > MAX_GRANTS
    ):
        raise GrantStoreError(
            "the local permission store has an unsupported version or format"
        )
    if payload.get("profile_id") != _PROFILE_ID:
        _write({})
        return {}

    grants: dict[tuple[str, str, str], _Grant] = {}
    for record in payload["grants"]:
        if not isinstance(record, dict):
            raise GrantStoreError("the local permission store contains an invalid entry")
        try:
            grant_id = record["id"]
            scope = GrantScope(
                record["capability"],
                record["integration"],
                record["resource"],
            )
            _validate_scope(scope)
            label = record["label"]
            created_at = record["created_at"]
            expires_at = record["expires_at"]
            use_count = record["use_count"]
            last_used_at = record["last_used_at"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GrantStoreError(
                "the local permission store contains an invalid entry"
            ) from exc
        if (
            not isinstance(grant_id, str)
            or not _GRANT_ID_RE.fullmatch(grant_id)
            or not isinstance(label, str)
            or not label.strip()
            or len(label) > 240
            or not isinstance(created_at, int)
            or isinstance(created_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at != created_at + GRANT_TTL_SECONDS
            or not isinstance(use_count, int)
            or isinstance(use_count, bool)
            or use_count < 0
            or (
                last_used_at is not None
                and (
                    not isinstance(last_used_at, int)
                    or isinstance(last_used_at, bool)
                    or last_used_at < created_at
                    or last_used_at >= expires_at
                )
            )
            or (use_count == 0) != (last_used_at is None)
            or scope.key() in grants
            or grant_id in {grant.grant_id for grant in grants.values()}
        ):
            raise GrantStoreError(
                "the local permission store contains an invalid entry"
            )
        grants[scope.key()] = _Grant(
            grant_id,
            scope,
            label,
            created_at,
            expires_at,
            use_count,
            last_used_at,
        )
    return grants


def _write(grants: dict[tuple[str, str, str], _Grant]) -> None:
    path = GRANT_STORE_PATH
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
        payload = {
            "version": _STORE_VERSION,
            "profile_id": _PROFILE_ID,
            "grants": [
                {
                    "id": grant.grant_id,
                    "capability": grant.scope.capability,
                    "integration": grant.scope.integration,
                    "resource": grant.scope.resource,
                    "label": grant.label,
                    "created_at": grant.created_at,
                    "expires_at": grant.expires_at,
                    "use_count": grant.use_count,
                    "last_used_at": grant.last_used_at,
                }
                for grant in grants.values()
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".session-grants.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            if os.name != "nt":
                os.chmod(temp_path, 0o600)
            json.dump(payload, temp_file, ensure_ascii=False, sort_keys=True)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise GrantStoreError(
            f"the local permission store could not be updated ({type(exc).__name__})"
        ) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise GrantStoreError(
                    "a temporary permission-store file could not be removed"
                ) from exc


def create(scope: GrantScope, label: str) -> None:
    _validate_scope(scope)
    if not isinstance(label, str) or not label.strip() or len(label) > 240:
        raise ValueError("permission label must be short text")

    now = int(time.time())
    with _lock:
        grants = {
            key: grant for key, grant in _load().items()
            if grant.expires_at > now
        }
        if scope.key() not in grants and len(grants) >= MAX_GRANTS:
            raise RuntimeError("the permission limit has been reached")
        grant = _Grant(
            grant_id=uuid.uuid4().hex,
            scope=scope,
            label=label.strip(),
            created_at=now,
            expires_at=now + GRANT_TTL_SECONDS,
            use_count=0,
            last_used_at=None,
        )
        action = "renewed" if scope.key() in grants else "created"
        grants[scope.key()] = grant
        _write(grants)
        _record_event(action, grant, now)


def allows(scope: GrantScope) -> bool:
    try:
        _validate_scope(scope)
    except ValueError:
        return False
    now = int(time.time())
    with _lock:
        grants = _load()
        grant = grants.get(scope.key())
        if grant is None or grant.expires_at <= now:
            return False
        grants[scope.key()] = _Grant(
            grant_id=grant.grant_id,
            scope=grant.scope,
            label=grant.label,
            created_at=grant.created_at,
            expires_at=grant.expires_at,
            use_count=grant.use_count + 1,
            last_used_at=max(
                now, grant.last_used_at or grant.created_at
            ),
        )
        _write(grants)
        _record_event("used", grants[scope.key()], now)
        return True


def active() -> tuple[ActiveGrant, ...]:
    now = int(time.time())
    with _lock:
        grants = _load()
        return tuple(
            ActiveGrant(
                grant_id=grant.grant_id,
                scope=grant.scope,
                label=grant.label,
                created_at=grant.created_at,
                expires_at=grant.expires_at,
                expires_in_seconds=max(0, grant.expires_at - now),
                use_count=grant.use_count,
                last_used_at=grant.last_used_at,
            )
            for grant in grants.values()
            if grant.expires_at > now
        )


def revoke(scope: GrantScope) -> bool:
    try:
        _validate_scope(scope)
    except ValueError:
        return False
    with _lock:
        grants = _load()
        removed = grants.pop(scope.key(), None)
        if removed is not None:
            _write(grants)
            _record_event("revoked", removed, int(time.time()))
        return removed is not None


def revoke_all() -> int:
    with _lock:
        try:
            grants = _load()
        except GrantStoreError:
            grants = {}
        _write({})
        now = int(time.time())
        for grant in grants.values():
            _record_event("revoked", grant, now)
        _record_event("revoked_all", None, now)
        return len(grants)
