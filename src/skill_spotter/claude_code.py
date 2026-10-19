"""Claude Code adapter: the only module that knows Claude Code's hook formats.

It maps Claude Code hook events to editor-neutral handlers, turns hook input into an
``Event``, and turns a handler's result back into hook output. A future Cursor adapter
would be a sibling module with the same three names: HANDLERS, normalize, render.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

from . import handlers

# Claude Code hook event -> (neutral event kind, handler)
EVENTS: Dict[str, Tuple[str, Callable[[handlers.Event], Any]]] = {
    "UserPromptSubmit": ("prompt", handlers.on_prompt),
    "PostToolUse": ("action", handlers.on_action),
    "PostToolUseFailure": ("action", handlers.on_action),
    "Stop": ("turn_end", handlers.on_turn_end),
    "ConfigChange": ("skill_change", handlers.on_skill_change),
    "UserPromptExpansion": ("command_used", handlers.on_command_used),
    "SessionEnd": ("session_end", handlers.on_session_end),
}

HANDLERS: Dict[str, Callable[[handlers.Event], Any]] = {
    hook_event: handler for hook_event, (_kind, handler) in EVENTS.items()
}


def normalize(hook_event: str, payload: Dict[str, Any]) -> handlers.Event:
    """Pick the fields skill-spotter uses out of Claude Code's hook input."""
    kind = EVENTS[hook_event][0] if hook_event in EVENTS else hook_event
    event: handlers.Event = {
        "editor": "claude-code",
        "kind": kind,
        "session_id": payload.get("session_id"),
        "prompt_id": payload.get("prompt_id"),
        "cwd": payload.get("cwd"),
        "agent_id": payload.get("agent_id"),  # set when a subagent made the call
    }
    if kind == "prompt":
        event["prompt"] = payload.get("prompt")
    elif kind == "action":
        event["tool_name"] = payload.get("tool_name")
        event["tool_input"] = payload.get("tool_input")
        event["tool_use_id"] = payload.get("tool_use_id")
        event["failed"] = hook_event == "PostToolUseFailure"
        # tool_response is left out on purpose: it can be huge and we don't need it.
    elif kind == "skill_change":
        event["file_path"] = payload.get("file_path")
    elif kind == "command_used":
        event["command_name"] = payload.get("command_name")
        event["command_args"] = payload.get("command_args")
        event["command_source"] = payload.get("command_source")
    elif kind == "session_end":
        event["reason"] = payload.get("reason")
    elif kind == "turn_end":
        crons = payload.get("session_crons")
        crons = crons if isinstance(crons, list) else []
        event["scheduled_prompts"] = [c.get("prompt") for c in crons if isinstance(c, dict)]
    return event


def render(hook_event: str, result: Any) -> Optional[str]:
    """Hook stdout for a handler result, or None to print nothing.

    Stop may print a ``systemMessage``: Claude Code shows it to the user without adding
    it to Claude's context. UserPromptSubmit may print ``additionalContext``, but only
    when the user opted into ``suggest_via = claude``. Anything else costs tokens or changes
    Claude's behavior: stdout from UserPromptSubmit and any output from an async hook
    (PostToolUse here) are delivered to Claude, and ``decision`` blocks it.
    """
    if hook_event == "Stop" and isinstance(result, str) and result:
        return json.dumps({"systemMessage": result})
    if (
        hook_event == "UserPromptSubmit"
        and isinstance(result, dict)
        and isinstance(result.get("context"), str)
        and result["context"]
    ):
        # Opt-in only (suggest_via = claude): ~100 tokens, once per suggestion.
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": result["context"][:2000],
                }
            }
        )
    return None
