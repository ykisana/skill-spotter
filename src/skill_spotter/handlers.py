"""What skill-spotter does on each event. Editor-neutral, standard library only.

Handlers receive an ``Event`` (a plain dict built by an editor adapter such as
``claude_code.py``) and never see editor-specific field names or output formats.
Every event has ``editor``, ``kind``, ``session_id``, ``prompt_id``, ``cwd`` and
``agent_id``; each handler's docstring lists the extra fields it gets.

M1: prompts, actions and turn ends are recorded and matched. The lifecycle (acceptance,
usage, snoozing) arrives in M2.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from . import paths, patterns, recorder, store, suggest

Event = Dict[str, Any]

# Debug switch: start Claude Code with SKILL_SPOTTER_DEBUG_SUGGEST=1 to get a fake
# suggestion after every turn, to see how suggestions are displayed (SPEC open question 2).
DEBUG_SUGGEST_ENV = "SKILL_SPOTTER_DEBUG_SUGGEST"


def _connect():
    return store.connect(paths.db_path(paths.data_dir()))


def _suggest_via(conn) -> str:
    return store.get_setting(conn, "suggest_via", "system") or "system"


def on_prompt(event: Event) -> Optional[Dict[str, str]]:
    """The user submitted a prompt. Extra: ``prompt``.

    Returns ``{"context": text}`` only in the opt-in ``suggest_via = claude`` mode, to hand
    Claude a suggestion queued at the end of the previous turn."""
    conn = _connect()
    try:
        now = time.time()
        recorder.record_prompt(conn, event, now)
        if _suggest_via(conn) != "claude" or not event.get("session_id"):
            return None
        row = conn.execute(
            "SELECT pending_context FROM session_meta WHERE session_id = ?", (event["session_id"],)
        ).fetchone()
        if row and row[0]:
            conn.execute(
                "UPDATE session_meta SET pending_context = NULL WHERE session_id = ?",
                (event["session_id"],),
            )
            return {"context": row[0]}
        return None
    finally:
        conn.close()


def on_action(event: Event) -> None:
    """A tool call finished. Extra: ``tool_name``, ``tool_input``, ``tool_use_id``, ``failed``."""
    conn = _connect()
    try:
        recorder.record_action(conn, event, time.time())
    finally:
        conn.close()


def on_turn_end(event: Event) -> Optional[str]:
    """Claude finished responding. Extra: ``scheduled_prompts``.
    Returns suggestion text to show the user, or None."""
    text = None
    conn = _connect()
    try:
        now = time.time()
        session_id = event.get("session_id") or ""
        recorder.remember_scheduled_prompts(
            conn, session_id, event.get("scheduled_prompts") or [], now
        )
        pattern_id = (
            patterns.finalize_turn(conn, event["prompt_id"], now)
            if event.get("prompt_id")
            else None
        )
        if pattern_id is not None:
            text = suggest.maybe_suggest(conn, pattern_id, session_id, now)
        if text and _suggest_via(conn) == "claude":
            conn.execute(
                "UPDATE session_meta SET pending_context = ? WHERE session_id = ?",
                (suggest.context_text(text), session_id),
            )
            text = None
    finally:
        conn.close()
    if text is None and os.environ.get(DEBUG_SUGGEST_ENV) == "1":
        text = (
            "[skill-spotter] debug: this is where a suggestion would appear "
            f"(session {event.get('session_id')})."
        )
    return text


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
