"""What skill-spotter does on each event. Editor-neutral, standard library only.

Handlers receive an ``Event`` (a plain dict built by an editor adapter such as
``claude_code.py``) and never see editor-specific field names or output formats.
Every event has ``editor``, ``kind``, ``session_id``, ``prompt_id``, ``cwd`` and
``agent_id``; each handler's docstring lists the extra fields it gets.

M0: handlers do nothing yet. Turn capture and matching arrive in M1, the lifecycle
(acceptance, usage, snoozing) in M2.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

Event = Dict[str, Any]

# Debug switch: start Claude Code with SKILL_SPOTTER_DEBUG_SUGGEST=1 to get a fake
# suggestion after every turn, to see how suggestions are displayed (SPEC open question 2).
DEBUG_SUGGEST_ENV = "SKILL_SPOTTER_DEBUG_SUGGEST"


def on_prompt(event: Event) -> None:
    """The user submitted a prompt. Extra: ``prompt``. (M1: filter, redact, store.)"""
    return None


def on_action(event: Event) -> None:
    """A tool call finished. Extra: ``tool_name``, ``tool_input``, ``tool_use_id``,
    ``failed``. (M1: normalize to action tokens, store.)"""
    return None


def on_turn_end(event: Event) -> Optional[str]:
    """Claude finished responding. Returns suggestion text to show the user, or None.
    (M1: finalize the turn, match it to a pattern, maybe suggest.)"""
    if os.environ.get(DEBUG_SUGGEST_ENV) == "1":
        return (
            "[skill-spotter] debug: this is where a suggestion would appear "
            f"(session {event.get('session_id')})."
        )
    return None


def on_skill_change(event: Event) -> None:
    """A skill file was created or edited. Extra: ``file_path``.
    (M2: mark the matching pattern accepted.)"""
    return None


def on_command_used(event: Event) -> None:
    """The user typed a slash command. Extra: ``command_name``, ``command_args``,
    ``command_source``. (M2: log use of skills we suggested.)"""
    return None


def on_session_end(event: Event) -> None:
    """The session ended. Extra: ``reason``. Must be fast: ~1 s budget.
    (M2: snooze suggestions the user didn't act on.)"""
    return None
