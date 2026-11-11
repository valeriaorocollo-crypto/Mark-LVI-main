"""Bounded local task history containing operational metadata only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import platform
from pathlib import Path
import tempfile
import threading
from typing import Any

MAX_RECORDS = 100
MAX_AGE_DAYS = 30
MAX_FILE_BYTES = 128 * 1024
_LOCK = threading.RLock()
_FIELDS = {
    "task_id",
    "state",
    "current_step",
    "total_steps",
    "completed",
    "recovery_attempts",
    "recovery_kind",
    "created_at",
    "updated_at",
}
_TASK_STATES = {
    "pending",
    "awaiting_confirmation",
    "running",
    "paused",
    "waiting_for_user",
    "recovery_required",
    "completed",
    "failed",
    "cancelled",
}
_RECOVERY_KINDS = {
    "focus_lost",
    "window_changed",
    "page_changed",
    "control_missing",
    "target_ambiguous",
    "timeout",
    "effect_ambiguous",
    "state_unreadable",
}


class HistoryStorageError(RuntimeError):
    """A safe, user-presentable task history storage error."""


def _history_path() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if not base:
            raise HistoryStorageError("LOCALAPPDATA is not configured")
        root = Path(base)
        if not root.is_absolute():
            raise HistoryStorageError("LOCALAPPDATA is not an absolute path")
    else:
        base = os.environ.get("XDG_DATA_HOME", "").strip()
        root = Path(base) if base else Path.home() / ".local" / "share"
        if not root.is_absolute():
            raise HistoryStorageError("the user data directory is not an absolute path")
    return root / "MARK-LVI" / "task_history.json"


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _validate_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HistoryStorageError("task history has an invalid format")
    records: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise HistoryStorageError("task history has an invalid record")
        if (
            not isinstance(item["task_id"], str)
            or not item["task_id"].isalnum()
            or len(item["task_id"]) > 64
            or not isinstance(item["state"], str)
            or item["state"] not in _TASK_STATES
            or not isinstance(item["recovery_kind"], str)
            or item["recovery_kind"] not in _RECOVERY_KINDS | {""}
            or any(
                not isinstance(item[field], int) or isinstance(item[field], bool)
                or item[field] < 0
                for field in (
                    "current_step",
                    "total_steps",
                    "completed",
                    "recovery_attempts",
                )
            )
        ):
            raise HistoryStorageError("task history has an invalid record")
        try:
            _timestamp(item["created_at"])
            _timestamp(item["updated_at"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise HistoryStorageError("task history has an invalid timestamp") from exc
        records.append(dict(item))
    return records


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        if path.stat().st_size > MAX_FILE_BYTES:
            raise HistoryStorageError("task history exceeds its size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except HistoryStorageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoryStorageError(
            f"task history could not be read ({type(exc).__name__})"
        ) from exc
    return _validate_records(value)


def _retained(records: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    recent = [
        item for item in records
        if _timestamp(item["updated_at"]) >= cutoff
    ]
    return recent[-MAX_RECORDS:]


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    temp_path: Path | None = None
    storage_error: HistoryStorageError | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".task_history.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(records, temp_file, ensure_ascii=False, separators=(",", ":"))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        storage_error = HistoryStorageError(
            f"task history could not be saved ({type(exc).__name__})"
        )
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                if storage_error is None:
                    storage_error = HistoryStorageError(
                        f"temporary task history file could not be removed "
                        f"({type(exc).__name__})"
                    )
    if storage_error is not None:
        raise storage_error


def save_snapshot(snapshot: dict[str, Any]) -> None:
    """Insert or replace a task metadata snapshot, never persisting task text."""
    path = _history_path()
    now = datetime.now(timezone.utc)
    task_id = snapshot.get("task_id")
    if (
        not isinstance(task_id, str)
        or not task_id.isalnum()
        or len(task_id) > 64
    ):
        raise ValueError("task history task ID is invalid")
    with _LOCK:
        records = _read(path)
        existing = next(
            (item for item in records if item["task_id"] == task_id), None
        )
        record = {
            "task_id": task_id,
            "state": snapshot["state"],
            "current_step": snapshot["current_step"],
            "total_steps": snapshot["total_steps"],
            "completed": snapshot["completed"],
            "recovery_attempts": snapshot["recovery_attempts"],
            "recovery_kind": snapshot["recovery_kind"],
            "created_at": (
                existing["created_at"]
                if existing
                else now.isoformat(timespec="seconds")
            ),
            "updated_at": now.isoformat(timespec="seconds"),
        }
        record = _validate_records([record])[0]
        records = [item for item in records if item["task_id"] != task_id]
        records.append(record)
        _write(path, _retained(records, now))


def read_history(limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("history limit must be an integer from 1 to 50")
    path = _history_path()
    now = datetime.now(timezone.utc)
    with _LOCK:
        stored = _read(path)
        records = _retained(stored, now)
        if records != stored:
            _write(path, records)
    return list(reversed(records[-limit:]))


def clear_history() -> int:
    """Clear persisted task metadata after validating the existing file."""
    path = _history_path()
    with _LOCK:
        try:
            path.stat()
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise HistoryStorageError(
                f"task history could not be inspected ({type(exc).__name__})"
            ) from exc
        records = _read(path)
        _write(path, [])
        return len(records)
