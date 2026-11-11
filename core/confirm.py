"""
core/confirm.py — a confirmation the model cannot forge.

THE PROBLEM WITH THE OLD GATE
    computer_settings guarded shutdown and restart like this:

        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return "Please confirm by calling again with confirmed=yes."

    `confirmed` is a tool parameter, which means the *model* writes it. Nothing
    stops it from sending confirmed=yes on the first call, and nothing checks
    that a human was ever involved. It is a convention, not a gate — and its
    coverage was two actions, so deleting files and switching off the WiFi the
    assistant is talking over went through with no gate at all.

THE DESIGN HERE
    The confirmation token is issued by the *interface*, never by the model:

      1. An action calls `request(...)` with a callable that does the real work.
      2. This module hands the UI a banner with CONFIRM / CANCEL and returns
         IMMEDIATELY with a sentence for the model to say out loud.
      3. If — and only if — the user presses CONFIRM or an opted-in voice
         handler recognizes an explicit approval, the action runs off the
         Qt thread.

    Nothing blocks. The model keeps talking while the banner is up, so this
    costs no latency at all; in fact it is cheaper than the old gate, which
    burned two tool round trips (reject, then re-call) on every shutdown.

WHAT BELONGS HERE AND WHAT DOES NOT
    Only genuinely irreversible things. Anything that can be reversed should be
    done at once and pushed onto core/undo.py instead — undo is faster than a
    question, and an assistant that asks before every action is one nobody uses.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Literal, Optional

from core import outcome, tool_audit

# A pending confirmation is abandoned after this long. Chosen to outlast a
# normal "hang on, let me look at the screen" pause without leaving a live
# shutdown button sitting on the HUD for the rest of the day.
TIMEOUT_SECONDS = 90.0
MAX_TITLE_LENGTH = 240
MAX_DETAIL_LENGTH = 20_000


class ConfirmationDecision(Enum):
    APPROVE_ONCE = "approve_once"
    REMEMBER_30_DAYS = "remember_30_days"
    CANCEL = "cancel"


@dataclass
class _Pending:
    key:     str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float
    voice_handler: Optional[Callable[[str], "VoiceDecision"]] = None
    button_enabled: bool = True
    grant_action: Optional[Callable[[], None]] = None
    on_cancel: Optional[Callable[[], None]] = None


@dataclass(frozen=True)
class VoiceDecision:
    action: Literal["accept", "cancel", "update", "ignore"]
    title: str = ""
    detail: str = ""
    button_enabled: bool = True


_pending: Optional[_Pending] = None
_lock = threading.Lock()

# Set once at startup by main.py. Signature: (title, detail) -> None for show,
# and () -> None for hide. Both are marshalled onto the Qt thread by the UI.
_show_cb: Optional[Callable[[str, str], None]] = None
_show_grant_cb: Optional[Callable[[str, str, str], None]] = None
_hide_cb: Optional[Callable[[], None]] = None
_log_cb:  Optional[Callable[[str], None]] = None


def bind(show, hide, log=None, show_grant=None) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _show_grant_cb, _hide_cb, _log_cb
    _show_cb, _show_grant_cb, _hide_cb, _log_cb = show, show_grant, hide, log


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            pass


def request(
    key: str,
    title: str,
    detail: str,
    run: Callable[[], str],
    voice_handler: Optional[Callable[[str], VoiceDecision]] = None,
    grant_action: Optional[Callable[[], None]] = None,
    grant_label: str = "",
    on_cancel: Optional[Callable[[], None]] = None,
) -> str:
    """Park an irreversible action behind the on-screen gate.

    Returns the sentence the tool should hand back to the model — phrased as an
    instruction so the assistant asks the user out loud in their own language,
    rather than reading an English string verbatim."""
    global _pending

    if not isinstance(title, str) or not isinstance(detail, str):
        return "I cannot ask for confirmation because its title and details must be text. Nothing was done."
    if len(title) > MAX_TITLE_LENGTH:
        return (
            f"I cannot ask for confirmation because the title exceeds "
            f"{MAX_TITLE_LENGTH} characters. Nothing was done."
        )
    if len(detail) > MAX_DETAIL_LENGTH:
        return (
            f"I cannot ask for confirmation because the details exceed "
            f"{MAX_DETAIL_LENGTH} characters. Nothing was done."
        )
    if grant_action is not None and (
        not callable(grant_action)
        or not isinstance(grant_label, str)
        or not grant_label.strip()
        or len(grant_label) > MAX_TITLE_LENGTH
    ):
        return "I cannot offer this session permission safely. Nothing was done."
    if on_cancel is not None and not callable(on_cancel):
        return "I cannot safely track this confirmation. Nothing was done."

    pending = _Pending(
        key=key, title=title, detail=detail, run=run, at=time.monotonic(),
        voice_handler=voice_handler, on_cancel=on_cancel,
    )
    with _lock:
        if _show_cb is None:
            # No interface bound (headless, or a very early call). Refuse rather
            # than silently performing something irreversible.
            return (f"I cannot confirm '{title}' right now because the interface is "
                    f"not available, so I have not done it.")

        if _pending is not None:
            if time.monotonic() - _pending.at <= TIMEOUT_SECONDS:
                return (
                    f"[CONFIRMATION_PENDING] Another action is already awaiting "
                    f"human confirmation: {_pending.title}. Nothing was done for "
                    f"'{title}'. Ask the user to resolve the visible confirmation "
                    "first."
                )
            _pending = None

        grant_offered = (
            grant_action is not None
            and _show_grant_cb is not None
            and voice_handler is None
        )
        show_cb = _show_grant_cb if grant_offered else _show_cb
        if grant_offered:
            pending.grant_action = grant_action
        _pending = pending

    try:
        if grant_offered:
            show_cb(title, detail, grant_label)
        else:
            show_cb(title, detail)
    except Exception as e:
        with _lock:
            if _pending is pending:
                _pending = None
        return (
            "Could not display the confirmation "
            f"({type(e).__name__}). Nothing was done."
        )

    _log(f"SYS: Awaiting confirmation — {key}")
    if voice_handler is not None:
        return (
            f"[CONFIRMATION_PENDING] A confirmation is visible for: {title}. "
            "Ask the user to review the recipient and full message in the popup, "
            "then say clearly whether to send it, correct a field, or cancel. "
            "Do not interpret your own response or a tool argument as approval."
        )
    if grant_offered:
        return (
            f"[CONFIRMATION_PENDING] Review the action on the HUD. Choose "
            f"ALLOW ONCE for this operation only, or REMEMBER FOR 30 DAYS "
            f"to save the displayed local permission and run this operation."
        )
    return (
        f"[CONFIRMATION_PENDING] I have put a confirmation on screen for: {title}. "
        f"Say ONE short sentence in the user's own language telling them you need "
        f"them to confirm it on the HUD before you do it. Do not claim it is done."
    )


async def request_async(
    key: str,
    title: str,
    detail: str,
    run: Callable[[], str],
    *,
    grant_action: Optional[Callable[[], None]] = None,
    grant_label: str = "",
    cancel_event: threading.Event | None = None,
) -> str:
    """Wait asynchronously for a HUD decision and return its action result."""
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[str] = loop.create_future()

    def finish_future(result: str) -> None:
        if not result_future.done():
            result_future.set_result(result)

    def on_cancel() -> None:
        if cancel_event is not None:
            cancel_event.set()
        loop.call_soon_threadsafe(
            finish_future,
            outcome.failed(
                "confirmation",
                "visual capture was not approved; no image was captured or sent",
                action=key,
            ),
        )

    def run_after_approval() -> str:
        try:
            result = run()
        except Exception as error:
            result = outcome.failed(
                "confirmation",
                "the approved visual capture failed",
                action=key,
                error=type(error).__name__,
            )
        loop.call_soon_threadsafe(finish_future, result)
        return result

    message = request(
        key,
        title,
        detail,
        run_after_approval,
        grant_action=grant_action,
        grant_label=grant_label,
        on_cancel=on_cancel,
    )
    with _lock:
        is_our_confirmation = (
            _pending is not None and _pending.run is run_after_approval
        )
    if not is_our_confirmation:
        return message

    try:
        return await asyncio.wait_for(result_future, TIMEOUT_SECONDS + 1)
    except asyncio.TimeoutError:
        if cancel_event is not None:
            cancel_event.set()
        cancel_pending(key, run_after_approval)
        return outcome.failed(
            "confirmation",
            "visual capture approval timed out; no image was captured or sent",
            action=key,
        )


def cancel_pending(key: str, expected_run: Callable[[], str] | None = None) -> bool:
    """Cancel a specific pending confirmation, used when an async wait expires."""
    global _pending
    with _lock:
        pending = _pending
        if (
            pending is None
            or pending.key != key
            or (expected_run is not None and pending.run is not expected_run)
        ):
            return False
        _pending = None
    _finish(pending, False)
    return True


def _finish(
    p: Optional[_Pending],
    accepted: bool,
    *,
    grant: bool = False,
) -> None:
    if _hide_cb:
        try:
            _hide_cb()
        except Exception as error:
            _log(
                "ERR: Confirmation panel could not be hidden "
                f"({type(error).__name__})"
            )

    if p is None:
        return

    if time.monotonic() - p.at > TIMEOUT_SECONDS:
        _log(f"SYS: Confirmation expired — {p.key}")
        if p.on_cancel is not None:
            p.on_cancel()
        return

    if not isinstance(accepted, bool):
        _log(f"ERR: Invalid confirmation decision — {p.key}; action was not run")
        return

    if not accepted:
        _log(f"SYS: Cancelled — {p.key}")
        if p.on_cancel is not None:
            p.on_cancel()
        return

    if grant:
        if p.grant_action is None:
            _log(f"ERR: No session permission was offered — {p.key}")
            return
        try:
            p.grant_action()
        except Exception as error:
            _log(
                f"ERR: Session permission could not be created "
                f"({type(error).__name__}); action was not run — {p.key}"
            )
            if p.on_cancel is not None:
                p.on_cancel()
            return

    def _worker():
        try:
            result = p.run()
            normalized = outcome.normalize_dispatch_result(p.key, result)
            status = tool_audit.classify_status(normalized)
            effect = tool_audit.classify_effect(status)
            _log(
                f"SYS: Confirmation accepted — {p.key}; "
                f"action status={status}; effect={effect}"
            )
        except Exception as e:
            normalized = outcome.failed(
                "confirmation",
                "the confirmed action raised an exception",
                action=p.key,
                error=type(e).__name__,
            )
            status = tool_audit.classify_status(normalized)
            effect = tool_audit.classify_effect(status)
            _log(
                f"SYS: Confirmation accepted — {p.key}; "
                f"action status={status}; effect={effect}"
            )

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def resolve(accepted: ConfirmationDecision | bool | str) -> None:
    """Resolve the visible confirmation from an explicit HUD control."""
    global _pending

    if isinstance(accepted, ConfirmationDecision):
        decision = accepted
    elif isinstance(accepted, bool):
        decision = (
            ConfirmationDecision.APPROVE_ONCE
            if accepted else ConfirmationDecision.CANCEL
        )
    elif isinstance(accepted, str) and accepted == "accept":
        decision = ConfirmationDecision.APPROVE_ONCE
    elif isinstance(accepted, str) and accepted == "cancel":
        decision = ConfirmationDecision.CANCEL
    elif isinstance(accepted, str) and accepted == "grant":
        _log(
            "ERR: Untrusted string decisions cannot create permissions; "
            "the HUD must provide a typed decision"
        )
        return
    else:
        _log("ERR: Invalid confirmation decision; action was not run")
        return
    grant_requested = decision is ConfirmationDecision.REMEMBER_30_DAYS
    should_run = decision is not ConfirmationDecision.CANCEL

    blocked: Optional[tuple[Callable[[str, str], None], str, str, str]] = None
    button_blocked = False
    with _lock:
        p = _pending
        if grant_requested and (p is None or p.grant_action is None):
            _log("ERR: Session permission was not offered; action was not run")
            return
        if p is not None and should_run and not p.button_enabled:
            button_blocked = True
            if _show_cb is not None:
                blocked = (_show_cb, p.title, p.detail, p.key)
        else:
            _pending = None

    if button_blocked:
        key = blocked[3] if blocked is not None else "pending-action"
        _log(f"SYS: Confirmation requires the requested voice edit — {key}")
        if blocked is None:
            _log("ERR: Confirmation panel is unavailable; action remains unapproved")
            return
        try:
            blocked[0](blocked[1], blocked[2])
        except Exception as error:
            _log(
                "ERR: Confirmation panel could not be restored "
                f"({type(error).__name__}); action remains unapproved"
            )
        return

    _finish(p, should_run, grant=grant_requested)


def handle_voice(transcript: str) -> bool:
    """Handle a completed user utterance for a confirmation that opted in.

    The Boolean says whether this utterance belongs to the confirmation flow;
    callers use it to prevent model-generated tool calls from treating the
    approval phrase as a new instruction.
    """
    global _pending
    if not isinstance(transcript, str) or not transcript.strip():
        return False

    expired = False
    show_update: Optional[tuple[Callable[[str, str], None], str, str]] = None
    resolution: Optional[tuple[_Pending, bool]] = None
    with _lock:
        pending = _pending
        if pending is None or pending.voice_handler is None:
            return False
        if time.monotonic() - pending.at > TIMEOUT_SECONDS:
            _pending = None
            expired = True
        else:
            try:
                decision = pending.voice_handler(transcript)
            except Exception as error:
                _log(
                    "ERR: Voice confirmation parser failed "
                    f"({type(error).__name__}); action remains unapproved"
                )
                return True

            if not isinstance(decision, VoiceDecision):
                _log("ERR: Invalid voice confirmation decision; action remains unapproved")
                return True
            if decision.action == "accept":
                _pending = None
                resolution = (pending, True)
            elif decision.action == "cancel":
                _pending = None
                resolution = (pending, False)
            elif decision.action == "update":
                if (
                    not isinstance(decision.title, str)
                    or not isinstance(decision.detail, str)
                    or len(decision.title) > MAX_TITLE_LENGTH
                    or len(decision.detail) > MAX_DETAIL_LENGTH
                ):
                    _log("ERR: Voice edit exceeds confirmation display limits")
                    return True
                pending.title = decision.title
                pending.detail = decision.detail
                pending.at = time.monotonic()
                pending.button_enabled = decision.button_enabled
                if _show_cb is not None:
                    show_update = (_show_cb, pending.title, pending.detail)
            elif decision.action != "ignore":
                _log("ERR: Unknown voice confirmation decision; action remains unapproved")
                return True

    if expired:
        _log("SYS: Confirmation expired")
        if _hide_cb:
            try:
                _hide_cb()
            except Exception as error:
                _log(f"ERR: Confirmation panel could not be hidden ({type(error).__name__})")
    elif resolution is not None:
        _finish(*resolution)
    elif show_update is not None:
        try:
            show_update[0](show_update[1], show_update[2])
        except Exception as error:
            with _lock:
                if _pending is pending:
                    _pending = None
            if _hide_cb:
                try:
                    _hide_cb()
                except Exception as hide_error:
                    _log(
                        "ERR: Confirmation panel could not be hidden "
                        f"({type(hide_error).__name__})"
                    )
            _log(
                "ERR: Updated confirmation could not be displayed "
                f"({type(error).__name__}); action remains unapproved"
            )
    return True


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            return ""
        return _pending.title


def voice_pending() -> bool:
    """Whether an unexpired action is waiting on its opted-in voice gate."""
    with _lock:
        return (
            _pending is not None
            and _pending.voice_handler is not None
            and time.monotonic() - _pending.at <= TIMEOUT_SECONDS
        )
