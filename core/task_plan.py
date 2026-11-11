"""Validated plans with approval, verification, and human handoff boundaries."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import threading
import time
import uuid
from typing import Any

from core import action_policy, outcome, task_history, tool_audit

MAX_STEPS = 12
MAX_TEXT = 500
MAX_ARGUMENTS = 20
MAX_PLAN_JSON = 15_000
MAX_TASK_RECORDS = 100
MAX_TASK_RUNTIME_SECONDS = 300
MAX_RECOVERY_ATTEMPTS = 2
EVICTABLE_TASK_STATES = {"pending", "completed", "failed", "cancelled"}
RECOVERY_KINDS = outcome.RECOVERY_KINDS
_VERIFICATION_METADATA_FIELDS = frozenset({
    "action", "count", "error", "limit", "max_results", "query", "reason",
    "recovery", "status", "tool", "verified",
})
_VERIFICATION_METADATA_RE = re.compile(
    r"""(?:\b(?:action|count|error|limit|max_results|query|reason|recovery|status|tool|verified)="""
    r"""(?:"[^"]*"|\S+)|"""
    r"""["'](?:action|count|error|limit|max_results|query|reason|recovery|status|tool|verified)["']\s*:\s*"""
    r"""(?:"[^"]*"|'[^']*'|true|false|null|[^,\s}]+))""",
    re.IGNORECASE,
)
TASK_STATES = {
    "pending", "awaiting_confirmation", "running", "paused",
    "waiting_for_user", "recovery_required", "completed", "failed",
    "cancelled",
}


@dataclass(frozen=True)
class PlanStep:
    tool: str
    arguments: dict[str, Any]
    purpose: str
    verification: "Verification"
    risk: str
    effect: str
    wait_for_user: str = ""


@dataclass(frozen=True)
class Verification:
    tool: str
    arguments: dict[str, Any]
    expect: str


@dataclass
class TaskRecord:
    task_id: str
    task: str
    steps: list[PlanStep]
    state: str
    current_step: int = 0
    completed: int = 0
    reason: str = ""
    pause_requested: bool = False
    deadline_at: float = 0.0
    recovery_attempts: int = 0
    recovery_kind: str = ""
    history_error: str = ""


_tasks: dict[str, TaskRecord] = {}
_tasks_lock = threading.RLock()
_tasks_changed = threading.Condition(_tasks_lock)
_progress_cb = None


def bind_progress(callback) -> None:
    """Bind a thread-safe progress callback supplied by the UI."""
    global _progress_cb
    _progress_cb = callback


def _notify(record: TaskRecord) -> None:
    try:
        task_history.save_snapshot(
            {
                "task_id": record.task_id,
                "state": record.state,
                "current_step": record.current_step,
                "total_steps": len(record.steps),
                "completed": record.completed,
                "recovery_attempts": record.recovery_attempts,
                "recovery_kind": record.recovery_kind,
            }
        )
        record.history_error = ""
    except task_history.HistoryStorageError as exc:
        error = str(exc)
        if error != record.history_error:
            print(f"[TaskPlan] {error}")
        record.history_error = error
    if _progress_cb is not None:
        try:
            state = (
                "pause_requested"
                if record.pause_requested and record.state == "running"
                else record.state
            )
            _progress_cb(
                record.task_id,
                record.task,
                state,
                record.current_step,
                len(record.steps),
                record.reason,
            )
        except Exception as exc:
            print(f"[TaskPlan] progress notification failed ({type(exc).__name__})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f"{field} must be non-empty text of at most {MAX_TEXT} characters")
    return value.strip()


def _status(result: Any) -> str:
    if isinstance(result, str):
        parsed = result.strip()
        if parsed.startswith("{"):
            try:
                payload = json.loads(parsed)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("status"), str):
                status = payload["status"]
                if status == outcome.DONE and payload.get("verified") is not True:
                    return outcome.UNVERIFIED
                return status
        status = tool_audit.classify_status(result)
        if status == outcome.DONE and not re.search(
            r"(?:^|\s)verified=true(?:\s|$)", parsed
        ):
            return outcome.UNVERIFIED
        return status
    return "unclassified"


def _verification_evidence(result: Any) -> str:
    """Return observed values without allowing outcome metadata as evidence."""
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() not in _VERIFICATION_METADATA_FIELDS:
                    collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            text = outcome.unwrap(value).strip()
            if text.startswith(("{", "[")):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, (dict, list)):
                    collect(payload)
                    return
            text = _VERIFICATION_METADATA_RE.sub("", text).strip()
            if text:
                values.append(text)
        elif value is not None:
            values.append(str(value))

    collect(result)
    return "\n".join(values)


def _recovery_kind(
    result: Any, *, fallback: str = "effect_ambiguous"
) -> str:
    """Read the adapter's normalized recovery signal, with safe legacy mapping."""
    payload = None
    if isinstance(result, str):
        parsed = result.strip()
        if parsed.startswith("{"):
            try:
                payload = json.loads(parsed)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            match = re.search(r"(?:^|\s)recovery=([a-z_]+)(?:\s|$)", parsed)
            if match and match.group(1) in RECOVERY_KINDS:
                return match.group(1)
    if isinstance(payload, dict):
        recovery = payload.get("recovery")
        if isinstance(recovery, str) and recovery in RECOVERY_KINDS:
            return recovery
        status = payload.get("status")
    else:
        status = _status(result)
    if status == "ambiguous":
        return "target_ambiguous"
    if status in {"not_found", "missing"}:
        return "control_missing"
    return fallback


def validate_steps(raw_steps: Any) -> list[PlanStep]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("steps must be a non-empty list")
    if len(raw_steps) > MAX_STEPS:
        raise ValueError(f"plans may contain at most {MAX_STEPS} steps")

    steps: list[PlanStep] = []
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"step {index} must be an object")
        tool = _text(raw.get("tool"), f"step {index} tool")
        if tool == "task_planner":
            raise ValueError(f"step {index} cannot invoke the task planner")
        if not tool_audit.is_reviewed_tool(tool):
            raise ValueError(
                f"step {index} uses an unregistered tool with no reviewed risk classification"
            )
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError(f"step {index} arguments must be an object")
        if len(arguments) > MAX_ARGUMENTS:
            raise ValueError(f"step {index} has too many arguments")
        if tool == "browser_control" and arguments.get("action") == "fill_form":
            fields = arguments.get("fields")
            if not isinstance(fields, dict) or len(fields) > 20:
                raise ValueError(
                    f"step {index} fill_form requires at most 20 named fields"
                )
            for selector, value in fields.items():
                if (
                    not isinstance(selector, str)
                    or not selector.strip()
                    or len(selector) > 500
                    or not isinstance(value, str)
                    or len(value) > 10_000
                ):
                    raise ValueError(
                        f"step {index} form selectors and values are invalid"
                    )
        action = arguments.get("action", "execute")
        wait_for_user = raw.get("wait_for_user", "")
        if wait_for_user:
            wait_for_user = _text(
                wait_for_user, f"step {index} wait_for_user"
            )
        risk = tool_audit.classify_risk(
            tool, arguments if isinstance(arguments, dict) else {}
        )
        if risk == "unclassified":
            raise ValueError(f"step {index} has no reviewed risk classification")
        verification = raw.get("verification")
        if not isinstance(verification, dict):
            raise ValueError(f"step {index} verification must be an object")
        verifier = _text(
            verification.get("tool"), f"step {index} verification tool"
        )
        if verifier == "task_planner" or not tool_audit.is_reviewed_tool(verifier):
            raise ValueError(
                f"step {index} verification tool is not reviewed"
            )
        verification_args = verification.get("arguments", {})
        if not isinstance(verification_args, dict):
            raise ValueError(f"step {index} verification arguments must be an object")
        if len(verification_args) > MAX_ARGUMENTS:
            raise ValueError(f"step {index} verification has too many arguments")
        if not tool_audit.is_read_only_verification(
            verifier, verification_args
        ):
            raise ValueError(
                f"step {index} verification must use an explicitly read-only action"
            )
        expected_evidence = _text(
            verification.get("expect"),
            f"step {index} verification expect",
        )
        if not _verification_evidence(expected_evidence):
            raise ValueError(
                f"step {index} verification expect cannot consist only of "
                "outcome metadata"
            )
        verification_spec = Verification(
            tool=verifier,
            arguments=dict(verification_args),
            expect=expected_evidence,
        )
        steps.append(
            PlanStep(
                tool=tool,
                arguments=dict(arguments),
                purpose=_text(raw.get("purpose"), f"step {index} purpose"),
                verification=verification_spec,
                risk=risk,
                effect=tool_audit.classify_effect(
                    "started" if action else "unknown"
                ),
                wait_for_user=wait_for_user,
            )
        )
    try:
        serialized = json.dumps(
            [
                {
                    "tool": step.tool,
                    "arguments": step.arguments,
                    "purpose": step.purpose,
                    "wait_for_user": step.wait_for_user,
                    "verification": {
                        "tool": step.verification.tool,
                        "arguments": step.verification.arguments,
                        "expect": step.verification.expect,
                    },
                }
                for step in steps
            ],
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("plan arguments must contain JSON-compatible values") from exc
    if len(serialized) > MAX_PLAN_JSON:
        raise ValueError(
            f"plan exceeds the {MAX_PLAN_JSON}-character confirmation limit"
        )
    return steps


def _form_previews(steps: list[PlanStep]) -> str | None:
    previews = []
    for index, step in enumerate(steps, 1):
        if (
            step.tool != "browser_control"
            or step.arguments.get("action") != "fill_form"
        ):
            continue
        fields = step.arguments["fields"]
        previews.append(
            {
                "step": index,
                "action": "fill_form",
                "fields": [
                    {
                        "selector": selector,
                        "value": (
                            "[REDACTED]"
                            if action_policy.is_sensitive_name(selector)
                            else value
                        ),
                    }
                    for selector, value in fields.items()
                ],
            }
        )
    if not previews:
        return None
    return json.dumps(previews, ensure_ascii=False, separators=(",", ":"))


def preview(task: Any, raw_steps: Any) -> str:
    """Return a bounded plan preview; this function never runs a step."""
    try:
        task_name = _text(task, "task")
        steps = validate_steps(raw_steps)
    except ValueError as exc:
        return outcome.failed("task_planner", str(exc), action="preview")
    task_id = uuid.uuid4().hex
    with _tasks_lock:
        while len(_tasks) >= MAX_TASK_RECORDS:
            evictable_id = next(
                (
                    existing_id
                    for existing_id, record in _tasks.items()
                    if record.state in EVICTABLE_TASK_STATES
                ),
                None,
            )
            if evictable_id is None:
                return outcome.failed(
                    "task_planner",
                    "task registry is full; wait for active tasks to finish",
                    action="preview",
                )
            del _tasks[evictable_id]
        _tasks[task_id] = TaskRecord(task_id, task_name, steps, "pending")

    risk_counts: dict[str, int] = {}
    for step in steps:
        risk_counts[step.risk] = risk_counts.get(step.risk, 0) + 1
    summary = ",".join(f"{key}:{risk_counts[key]}" for key in sorted(risk_counts))
    checkpoints = "; ".join(
        f"step {index}: {step.wait_for_user}"
        for index, step in enumerate(steps, 1)
        if step.wait_for_user
    )
    return outcome.done(
        "task_planner",
        task=task_name,
        steps=len(steps),
        risks=summary,
        verification="; ".join(
            f"{step.verification.tool} expects {step.verification.expect}"
            for step in steps
        ),
        execution="preview_only",
        task_id=task_id,
        state="pending",
        checkpoints=checkpoints or None,
        form_preview=_form_previews(steps),
        verified=True,
    )


def _record_for(
    task: Any, raw_steps: Any, task_id: Any
) -> tuple[TaskRecord | None, str | None]:
    if not isinstance(task_id, str) or not task_id.strip():
        return None, "task_id is required; preview the plan before executing it"
    with _tasks_lock:
        record = _tasks.get(task_id)
        if record is None:
            return None, "task_id is unknown or has expired"
        if record.task != task or record.steps != validate_steps(raw_steps):
            return None, "task_id does not match the approved task and steps"
        if record.state != "pending":
            return None, f"task is already {record.state}"
        record.state = "running"
        record.deadline_at = time.monotonic() + MAX_TASK_RUNTIME_SECONDS
        return record, None


def cancel(task_id: Any) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        return outcome.failed("task_planner", "task_id is required", action="cancel")
    with _tasks_lock:
        record = _tasks.get(task_id)
        if record is None:
            return outcome.failed("task_planner", "task_id is unknown", action="cancel")
        if record.state in {"completed", "failed", "cancelled"}:
            return outcome.failed(
                "task_planner", f"task is already {record.state}", action="cancel",
                task_id=task_id, state=record.state,
            )
        record.state = "cancelled"
        record.reason = "cancelled by user"
        record.pause_requested = False
        _notify(record)
        _tasks_changed.notify_all()
        return outcome.done(
            "task_planner", action="cancel", task_id=task_id,
            state="cancelled", verified=True,
        )


def pause(task_id: Any) -> str:
    """Request a pause at the next safe boundary; never interrupt an active call."""
    if not isinstance(task_id, str) or not task_id.strip():
        return outcome.failed("task_planner", "task_id is required", action="pause")
    with _tasks_changed:
        record = _tasks.get(task_id)
        if record is None:
            return outcome.failed("task_planner", "task_id is unknown", action="pause")
        if record.state != "running":
            return outcome.failed(
                "task_planner",
                f"task cannot be paused while {record.state}",
                action="pause",
                task_id=task_id,
                state=record.state,
            )
        if record.pause_requested:
            return outcome.failed(
                "task_planner",
                "a pause is already waiting for the active step to finish",
                action="pause",
                task_id=task_id,
                state="pause_requested",
            )
        record.pause_requested = True
        record.reason = (
            "Pause requested. The active action will finish; after you resume, "
            "only its read-only verification can run before the next action."
        )
        _notify(record)
        return outcome.done(
            "task_planner",
            action="pause",
            task_id=task_id,
            state="pause_requested",
            verified=True,
        )


def resume(task_id: Any) -> str:
    """Resume a waiting task only after the user activates the HUD control."""
    if not isinstance(task_id, str) or not task_id.strip():
        return outcome.failed("task_planner", "task_id is required", action="resume")
    with _tasks_changed:
        record = _tasks.get(task_id)
        if record is None:
            return outcome.failed("task_planner", "task_id is unknown", action="resume")
        if record.state not in {
            "paused", "waiting_for_user", "recovery_required"
        }:
            return outcome.failed(
                "task_planner",
                f"task is not waiting for the user ({record.state})",
                action="resume",
                task_id=task_id,
                state=record.state,
            )
        record.state = "running"
        record.reason = ""
        if record.recovery_kind:
            record.recovery_kind = ""
        _notify(record)
        _tasks_changed.notify_all()
        return outcome.done(
            "task_planner",
            action="resume",
            task_id=task_id,
            state="running",
            verified=True,
        )


def _wait_for_user(record: TaskRecord, prompt: str) -> bool:
    """Wait at a verified step boundary; return False if cancelled."""
    with _tasks_changed:
        if record.state == "cancelled":
            return False
        if not record.pause_requested and not prompt:
            return True
        remaining = max(0.0, record.deadline_at - time.monotonic())
        record.deadline_at = 0.0
        record.state = "waiting_for_user" if prompt else "paused"
        record.pause_requested = False
        record.reason = prompt or "Paused by the user. Complete the needed action, then resume."
        _notify(record)
        while record.state in {"paused", "waiting_for_user"}:
            _tasks_changed.wait()
        if record.state != "cancelled":
            record.deadline_at = time.monotonic() + remaining
        return record.state != "cancelled"


def _wait_for_recovery(
    record: TaskRecord, step: int, reason: str, recovery_kind: str
) -> bool:
    """Require human intervention before retrying only a read-only verifier."""
    with _tasks_changed:
        if record.state == "cancelled":
            return False
        if record.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
            return False
        remaining = max(0.0, record.deadline_at - time.monotonic())
        record.deadline_at = 0.0
        record.recovery_attempts += 1
        record.recovery_kind = recovery_kind
        record.state = "recovery_required"
        record.reason = (
            f"Step {step} recovery={recovery_kind}: {reason}. Resume to retry only its read-only "
            "verification; the action will not be repeated."
        )
        _notify(record)
        while record.state == "recovery_required":
            _tasks_changed.wait()
        if record.state != "cancelled":
            record.deadline_at = time.monotonic() + remaining
        return record.state != "cancelled"


def _task_expired(record: TaskRecord) -> bool:
    return bool(record.deadline_at and time.monotonic() >= record.deadline_at)


def _fail_task(record: TaskRecord, reason: str) -> None:
    with _tasks_lock:
        if record.state != "cancelled":
            record.state = "failed"
            record.reason = reason
        _notify(record)


def status(task_id: Any) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        return outcome.failed("task_planner", "task_id is required", action="status")
    with _tasks_lock:
        record = _tasks.get(task_id)
        if record is None:
            return outcome.failed("task_planner", "task_id is unknown", action="status")
        return outcome.done(
            "task_planner", action="status", task_id=task_id,
            state=record.state, current_step=record.current_step,
            completed=record.completed,
            recovery_attempts=record.recovery_attempts,
            recovery=record.recovery_kind or None,
            history_storage="unavailable" if record.history_error else "available",
            history_error=record.history_error or None,
            reason=record.reason,
            verified=True,
        )


def history(limit: Any = 20) -> str:
    """Return recent task metadata without task descriptions or action data."""
    try:
        records = task_history.read_history(limit)
    except ValueError as exc:
        return outcome.failed("task_planner", str(exc), action="history")
    except task_history.HistoryStorageError as exc:
        return outcome.failed(
            "task_planner", str(exc), action="history", history_storage="unavailable"
        )
    entries = ";".join(
        ",".join(
            (
                record["task_id"],
                record["state"],
                f"step={record['current_step']}/{record['total_steps']}",
                f"completed={record['completed']}",
                f"recoveries={record['recovery_attempts']}",
                f"recovery={record['recovery_kind'] or 'none'}",
                f"updated={record['updated_at']}",
            )
        )
        for record in records
    )
    return outcome.done(
        "task_planner",
        action="history",
        count=len(records),
        entries=entries or "none",
        retention_days=task_history.MAX_AGE_DAYS,
        verified=True,
    )


def clear_history() -> str:
    """Clear persisted task metadata; active tasks may write later snapshots."""
    try:
        cleared = task_history.clear_history()
    except task_history.HistoryStorageError as exc:
        return outcome.failed(
            "task_planner",
            str(exc),
            action="clear_history",
            history_storage="unavailable",
        )
    return outcome.done(
        "task_planner",
        action="clear_history",
        cleared=cleared,
        note="active tasks may create new history snapshots",
        verified=True,
    )


def execute(
    task: Any,
    raw_steps: Any,
    executor: Any,
    task_id: Any = None,
) -> str:
    """Execute an approved plan one step at a time, never retrying effects."""
    try:
        task_name = _text(task, "task")
        validate_steps(raw_steps)
    except ValueError as exc:
        return outcome.failed("task_planner", str(exc), action="execute")
    if not action_policy.is_confirmed("task_planner"):
        return outcome.failed(
            "task_planner",
            "plan execution requires approval from the confirmation HUD",
            action="execute",
        )
    if not callable(executor):
        return outcome.failed(
            "task_planner",
            "no trusted tool executor is available",
            action="execute",
        )

    try:
        record, error = _record_for(task_name, raw_steps, task_id)
    except ValueError as exc:
        return outcome.failed("task_planner", str(exc), action="execute")
    if error or record is None:
        return outcome.failed("task_planner", error or "task is unavailable", action="execute")

    authorized = [
        (item.tool, item.arguments)
        for step in record.steps
        for item in (step, step.verification)
    ]
    completed: list[int] = []
    with action_policy.authorize_plan(authorized):
        for index, step in enumerate(record.steps, 1):
            with _tasks_lock:
                record.current_step = index
                if record.state == "cancelled":
                    return outcome.failed(
                        "task_planner", "task was cancelled before the next step",
                        task=task_name, task_id=record.task_id,
                        completed=len(completed), state="cancelled",
                    )
                _notify(record)
            if _task_expired(record):
                _fail_task(record, "task runtime limit reached before the next action")
                if completed:
                    return outcome.unverified(
                        "task_planner",
                        "the task runtime limit was reached; completed steps are "
                        "listed and no further action was started",
                        task=task_name,
                        task_id=record.task_id,
                        completed=",".join(str(item) for item in completed),
                        state="failed",
                    )
                return outcome.failed(
                    "task_planner",
                    "task runtime limit reached before any action started",
                    task=task_name,
                    task_id=record.task_id,
                    state="failed",
                )
            if not _wait_for_user(record, ""):
                return outcome.unverified(
                    "task_planner",
                    "the task was cancelled at a safe checkpoint",
                    task=task_name,
                    task_id=record.task_id,
                    completed=len(completed),
                    state="cancelled",
                )

            action_error = None
            try:
                action_result = executor(step.tool, dict(step.arguments))
            except Exception as exc:
                action_error = type(exc).__name__
                action_result = None
            with _tasks_lock:
                if record.state == "cancelled":
                    _notify(record)
                    return outcome.unverified(
                        "task_planner",
                        "the task was cancelled while a step was running; the "
                        "action may have completed but was not verified",
                        task=task_name,
                        task_id=record.task_id,
                        step=index,
                        completed=",".join(str(item) for item in completed),
                        state="cancelled",
                    )

            action_status = (
                _status(action_result)
                if action_error is None
                else outcome.UNVERIFIED
            )
            action_recovery = _recovery_kind(action_result)
            with _tasks_lock:
                pause_requested = record.pause_requested
            recovery_prompted = False
            timed_out = _task_expired(record)
            if action_error or action_status != outcome.DONE or timed_out:
                reason = (
                    f"the action raised {action_error}"
                    if action_error
                    else f"the action returned {action_status}"
                    if action_status != outcome.DONE
                    else "the task runtime limit was reached during the action"
                )
                recovery_kind = (
                    "timeout" if timed_out else action_recovery
                )
                if step.wait_for_user or pause_requested:
                    prompt = step.wait_for_user or (
                        f"{reason}. Resume to run read-only verification only."
                    )
                    resumed = _wait_for_user(record, prompt)
                else:
                    resumed = _wait_for_recovery(
                        record, index, reason, recovery_kind
                    )
                if not resumed:
                    if record.state == "cancelled":
                        return outcome.unverified(
                            "task_planner",
                            "the task was cancelled before recovery verification",
                            task=task_name,
                            task_id=record.task_id,
                            step=index,
                            state="cancelled",
                        )
                    _fail_task(record, f"step {index} recovery limit reached")
                    return outcome.unverified(
                        "task_planner",
                        "the action may have had an effect; recovery attempts "
                        "were exhausted without repeating it",
                        task=task_name,
                        task_id=record.task_id,
                        step=index,
                        completed=",".join(str(item) for item in completed),
                        state="failed",
                        recovery=recovery_kind,
                    )
                recovery_prompted = True
            elif step.wait_for_user or pause_requested:
                if not _wait_for_user(record, step.wait_for_user):
                    return outcome.unverified(
                        "task_planner",
                        "the task was cancelled while waiting for the user; the "
                        "action may have had an effect and was not verified",
                        task=task_name,
                        task_id=record.task_id,
                        step=index,
                        state="cancelled",
                    )

            verification_succeeded = False
            while not verification_succeeded:
                if _task_expired(record) and not recovery_prompted:
                    timed_out = True
                    if not _wait_for_recovery(
                        record,
                        index,
                        "the task runtime limit was reached",
                        "timeout",
                    ):
                        if record.state == "cancelled":
                            return outcome.unverified(
                                "task_planner",
                                "the task was cancelled before recovery verification",
                                task=task_name,
                                task_id=record.task_id,
                                step=index,
                                state="cancelled",
                            )
                        _fail_task(record, f"step {index} recovery limit reached")
                        return outcome.unverified(
                            "task_planner",
                            "the task exceeded its runtime limit and could not "
                            "confirm the current step",
                            task=task_name,
                            task_id=record.task_id,
                            step=index,
                            state="failed",
                            recovery="timeout",
                        )
                    recovery_prompted = True
                try:
                    verification_result = executor(
                        step.verification.tool,
                        dict(step.verification.arguments),
                    )
                    verification_error = None
                except Exception as exc:
                    verification_result = None
                    verification_error = type(exc).__name__
                with _tasks_lock:
                    if record.state == "cancelled":
                        _notify(record)
                        return outcome.unverified(
                            "task_planner",
                            "the task was cancelled while verification was "
                            "running; the current step is not recorded complete",
                            task=task_name,
                            task_id=record.task_id,
                            step=index,
                            completed=",".join(str(item) for item in completed),
                            state="cancelled",
                        )
                verification_succeeded = (
                    verification_error is None
                    and _status(verification_result) == outcome.DONE
                    and step.verification.expect.casefold()
                    in _verification_evidence(verification_result).casefold()
                )
                if verification_succeeded:
                    break
                reason = (
                    f"read-only verification raised {verification_error}"
                    if verification_error
                    else "read-only verification did not match the expected evidence"
                )
                recovery_kind = _recovery_kind(
                    verification_result, fallback="state_unreadable"
                )
                if not _wait_for_recovery(
                    record, index, reason, recovery_kind
                ):
                    if record.state == "cancelled":
                        return outcome.unverified(
                            "task_planner",
                            "the task was cancelled before recovery verification",
                            task=task_name,
                            task_id=record.task_id,
                            step=index,
                            state="cancelled",
                        )
                    _fail_task(record, f"step {index} verification did not match")
                    return outcome.unverified(
                        "task_planner",
                        "the action may have completed, but read-only recovery "
                        "verification did not confirm it; the action was not "
                        "repeated",
                        task=task_name,
                        task_id=record.task_id,
                        step=index,
                        verification=step.verification.expect,
                        completed=",".join(str(item) for item in completed),
                        state="failed",
                        recovery=recovery_kind,
                    )
                recovery_prompted = True

            completed.append(index)
            with _tasks_lock:
                record.completed = len(completed)
                _notify(record)
            if not _wait_for_user(record, ""):
                return outcome.unverified(
                    "task_planner",
                    "the task was cancelled at a safe checkpoint",
                    task=task_name,
                    task_id=record.task_id,
                    completed=",".join(str(item) for item in completed),
                    state="cancelled",
                )
    with _tasks_changed:
        while record.state != "cancelled" and record.pause_requested:
            remaining = max(0.0, record.deadline_at - time.monotonic())
            record.deadline_at = 0.0
            record.state = "paused"
            record.pause_requested = False
            record.reason = (
                "Pause requested. The active action and its read-only "
                "verification have finished."
            )
            _notify(record)
            while record.state == "paused":
                _tasks_changed.wait()
            if record.state != "cancelled":
                record.deadline_at = time.monotonic() + remaining
        if record.state == "cancelled":
            return outcome.unverified(
                "task_planner",
                "the task was cancelled before completion",
                task=task_name,
                task_id=record.task_id,
                completed=",".join(str(item) for item in completed),
                state="cancelled",
            )
        record.state = "completed"
        record.current_step = len(record.steps)
        record.reason = ""
        _notify(record)
    return outcome.done(
        "task_planner",
        task=task_name,
        task_id=record.task_id,
        steps=len(record.steps),
        completed=len(completed),
        verification="; ".join(
            step.verification.expect for step in record.steps
        ),
        state="completed",
        verified=True,
    )
