"""Claude Code adapter: the only module that knows Claude Code's hook formats.

It maps Claude Code hook events to editor-neutral handlers, turns hook input into an
``Event``, and turns a handler's result back into hook output. A future Cursor adapter
would be a sibling module with the same three names: HANDLERS, normalize, render.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from . import handlers

HANDLERS: Dict[str, Callable[[handlers.Event], Any]] = {
    "Stop": handlers.on_turn_end,
}


def normalize(hook_event: str, payload: Dict[str, Any]) -> handlers.Event:
    """Pick the fields skill-spotter uses out of Claude Code's hook input."""
    return {
        "editor": "claude-code",
        "kind": hook_event,
        "session_id": payload.get("session_id"),
        "prompt_id": payload.get("prompt_id"),
        "cwd": payload.get("cwd"),
    }


def render(hook_event: str, result: Any) -> Optional[str]:
    """Hook stdout for a handler result, or None to print nothing.

    Only Stop may print, and only ``systemMessage``: Claude Code shows it to the user
    without adding it to Claude's context. Anything else (``decision``,
    ``additionalContext``, plain text) would cost tokens or change Claude's behavior.
    """
    if hook_event == "Stop" and isinstance(result, str) and result:
        return json.dumps({"systemMessage": result})
    return None
