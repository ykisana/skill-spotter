"""What skill-spotter does on each event. Editor-neutral, standard library only.

Handlers receive an ``Event`` (a plain dict built by an editor adapter such as
``claude_code.py``) and never see editor-specific field names or output formats.

M0: handlers do nothing yet. Turn capture and matching arrive in M1.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

Event = Dict[str, Any]

# Debug switch: start Claude Code with SKILL_SPOTTER_DEBUG_SUGGEST=1 to get a fake
# suggestion after every turn, to see how suggestions are displayed (SPEC open question 2).
DEBUG_SUGGEST_ENV = "SKILL_SPOTTER_DEBUG_SUGGEST"


def on_turn_end(event: Event) -> Optional[str]:
    """Claude finished responding. Returns suggestion text to show the user, or None."""
    if os.environ.get(DEBUG_SUGGEST_ENV) == "1":
        return (
            "[skill-spotter] debug: this is where a suggestion would appear "
            f"(session {event.get('session_id')})."
        )
    return None
