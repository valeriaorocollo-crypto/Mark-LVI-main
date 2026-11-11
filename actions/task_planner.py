"""Preview and execute bounded multi-step tasks behind explicit approval."""
from __future__ import annotations

from core import outcome, task_plan


def task_planner(parameters: dict, execute_tool=None) -> str:
    mode = parameters.get("mode", "preview")
    if mode == "preview":
        return task_plan.preview(parameters.get("task"), parameters.get("steps"))
    if mode == "execute":
        return task_plan.execute(
            parameters.get("task"), parameters.get("steps"), execute_tool,
            parameters.get("task_id"),
        )
    if mode == "cancel":
        return task_plan.cancel(parameters.get("task_id"))
    if mode == "status":
        return task_plan.status(parameters.get("task_id"))
    if mode == "history":
        return task_plan.history(parameters.get("history_limit", 20))
    if mode == "clear_history":
        return task_plan.clear_history()
    return outcome.failed(
        "task_planner",
        "mode must be preview, execute, cancel, status, history, or clear_history",
        action="dispatch",
    )


TOOL = {
    "name": "task_planner",
    "description": (
        "Create a bounded preview of a multi-step task. Execution requires "
        "HUD approval. A step may declare a human checkpoint after its action "
        "and before verification; the HUD then waits for the user to resume. "
        "Effectful steps have a five-minute active-time budget checked at safe "
        "boundaries; an in-flight call is not interrupted. Ambiguous results "
        "require manual recovery and may repeat only read-only verification, "
        "never an effectful action."
        " A local task history stores only task IDs, states, step counts, "
        "recovery counts/categories, and timestamps; it excludes task text, "
        "arguments, and results and retains at most 100 records for 30 days. "
        "Clearing that local history requires explicit HUD confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {
                "type": "STRING",
                "description": "Short description of the requested task",
            },
            "mode": {
                "type": "STRING",
                "enum": [
                    "preview", "execute", "cancel", "status", "history",
                    "clear_history",
                ],
                "description": (
                    "Preview before execution; execution and clearing history "
                    "require HUD approval"
                ),
            },
            "history_limit": {
                "type": "INTEGER",
                "description": (
                    "Number of recent task history entries to return (1-50); "
                    "used only with mode=history"
                ),
            },
            "task_id": {
                "type": "STRING",
                "description": "ID returned by preview, required for execute/cancel/status",
            },
            "steps": {
                "type": "ARRAY",
                "description": (
                    "Up to 12 steps, each with tool, arguments and purpose. "
                        "Each step must include a read-only verification object "
                        "with tool, arguments and expected evidence. Preview only; "
                        "no step is executed."
                ),
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "tool": {"type": "STRING"},
                        "arguments": {"type": "OBJECT"},
                        "purpose": {"type": "STRING"},
                        "wait_for_user": {
                            "type": "STRING",
                            "description": (
                                "Optional human checkpoint after this action "
                                "and before its verification, for sign-in, MFA, "
                                "CAPTCHA, permissions, or an unexpected dialog"
                            ),
                        },
                        "verification": {
                            "type": "OBJECT",
                            "properties": {
                                "tool": {"type": "STRING"},
                                "arguments": {"type": "OBJECT"},
                                "expect": {"type": "STRING"},
                            },
                            "required": ["tool", "arguments", "expect"],
                        },
                    },
                    "required": ["tool", "arguments", "purpose", "verification"],
                },
            },
        },
        "required": [],
    },
    "handler": task_planner,
}
