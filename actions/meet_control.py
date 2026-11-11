"""Safely open a new Google Meet after an on-screen human confirmation."""
from __future__ import annotations

from core import action_policy, confirm, outcome


def _open_meet(browser: str | None) -> str:
    from actions.browser_control import _open_native

    url = "https://meet.google.com/new"
    result = _open_native(url, browser)
    if result.startswith("Opened"):
        return outcome.unverified(
            "meet_control",
            "the browser accepted the request, but Google Meet's page and "
            "meeting creation could not be verified; no camera, microphone, "
            "invitation, or screen share was started",
            url=url,
        )
    return outcome.failed(
        "meet_control",
        f"the browser could not open the new-meeting page ({result})",
        url=url,
    )


def meet_control(parameters: dict | None = None, response=None, player=None,
                 session_memory=None) -> str:
    if parameters is not None and not isinstance(parameters, dict):
        return outcome.failed("meet_control", "parameters must be an object")
    params = parameters or {}
    action_value = params.get("action", "")
    if not isinstance(action_value, str) or len(action_value) > 16:
        return outcome.failed(
            "meet_control", "action must be text of at most 16 characters"
        )
    action = action_value.strip().lower()
    if action not in {"create", "new"}:
        return outcome.failed(
            "meet_control", "action must be create",
            action=action or "unspecified",
        )

    browser_value = params.get("browser")
    if browser_value is not None and not isinstance(browser_value, str):
        return outcome.failed("meet_control", "browser must be text")
    browser = browser_value.strip().lower() if browser_value else None
    if browser is not None and (
        len(browser) > 32
        or browser not in {
            "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "safari",
        }
    ):
        return outcome.failed("meet_control", "browser name is not supported")
    if confirm.pending_title():
        return outcome.ask(
            "meet_control",
            "another confirmation is already waiting on the HUD; "
            "Google Meet was not opened",
        )
    return action_policy.request_confirmation(
        "meet_control",
        "create",
        title="Open a new Google Meet?",
        detail=(
            "This opens Google Meet in your normal browser. It will not "
            "enable your camera or microphone, invite anyone, or share your screen.\n"
            f"Browser: {browser or 'system default'}"
        ),
        run=lambda: _open_meet(browser),
    )


TOOL = {
    "name": "meet_control",
    "description": (
        "For an explicit request to create a new Google Meet, open "
        "https://meet.google.com/new in the user's normal browser after the "
        "user confirms on the HUD. This only opens the page: it does not "
        "enable camera/microphone, invite people, join, record, or share the "
        "screen. Report the result as unverified. Do not use for opening the "
        "ordinary Meet homepage."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'create' or 'new' to request a new meeting.",
                "enum": ["create", "new"],
            },
            "browser": {
                "type": "STRING",
                "description": (
                    "Optional browser name: chrome, edge, firefox, brave, "
                    "opera, vivaldi, or safari."
                ),
            },
        },
        "required": ["action"],
    },
    "handler": meet_control,
}
