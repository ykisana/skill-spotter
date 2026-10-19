"""What skill-spotter does on each event. Editor-neutral, standard library only.

Handlers receive an ``Event`` (a plain dict built by an editor adapter such as
``claude_code.py``) and never see editor-specific field names or output formats.
Every event has ``editor``, ``kind``, ``session_id``, ``prompt_id``, ``cwd`` and
``agent_id``; each handler's docstring lists the extra fields it gets.

Each handler imports what its event needs inside the function: hooks start a fresh
process every time, and import time is most of a hook's cost. ``test_lazy_imports``
keeps it that way.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import clock, paths, store

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
    from . import recorder

    conn = _connect()
    try:
        recorder.record_prompt(conn, event, clock.now())
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
    from . import recorder

    conn = _connect()
    try:
        recorder.record_action(conn, event, clock.now())
    finally:
        conn.close()


def on_turn_end(event: Event) -> Optional[str]:
    """Claude finished responding. Extra: ``scheduled_prompts``.
    Returns suggestion text to show the user, or None."""
    from . import lifecycle, patterns, project, recorder, suggest, workflows

    text = None
    conn = _connect()
    try:
        now = clock.now()
        session_id = event.get("session_id") or ""
        recorder.remember_scheduled_prompts(
            conn, session_id, event.get("scheduled_prompts") or [], now
        )
        prompt_id = event.get("prompt_id")
        pattern_id = patterns.finalize_turn(conn, prompt_id, now) if prompt_id else None
        project_key = project.project_key(event.get("cwd"))
        lifecycle.scan_for_created_skills(conn, project_key, now)
        if pattern_id is not None:
            touched = workflows.record(conn, project_key, session_id, now)
            text = workflows.maybe_suggest(conn, project_key, session_id, touched, now)
            if text is None:
                text = suggest.maybe_suggest(conn, pattern_id, session_id, now)
        if text is None:  # patterns the background job marked ready in this project
            text = suggest.suggest_ready(conn, project_key, session_id, now)
        band = conn.execute(
            "SELECT band_active FROM session_meta WHERE session_id = ?", (session_id,)
        ).fetchone()
        if text and band and band[0]:
            # The skill-spotter mod draws this as a band with buttons (M7); no systemMessage.
            from . import band as band_mod

            band_mod.queue(conn, session_id, text)
            text = None
        if text and _suggest_via(conn) == "claude":
            conn.execute(
                "UPDATE session_meta SET pending_context = ? WHERE session_id = ?",
                (suggest.context_text(text), session_id),
            )
            text = None
        lifecycle.maybe_prune(conn, now)
        from .background import launcher

        launcher.maybe_spawn(conn, now)
    finally:
        conn.close()
    if text is None and os.environ.get(DEBUG_SUGGEST_ENV) == "1":
        text = (
            "[skill-spotter] debug: this is where a suggestion would appear "
            f"(session {event.get('session_id')})."
        )
    return text


def on_skill_change(event: Event) -> None:
    """A skill file was created or edited. Extra: ``file_path``."""
    from . import lifecycle, project

    conn = _connect()
    try:
        lifecycle.skill_file_changed(
            conn, event.get("file_path"), project.project_key(event.get("cwd")), clock.now()
        )
    finally:
        conn.close()


def on_command_used(event: Event) -> None:
    """The user typed a slash command. Extra: ``command_name``, ``command_args``,
    ``command_source``."""
    from . import lifecycle

    conn = _connect()
    try:
        lifecycle.command_used(
            conn, event.get("command_name"), event.get("session_id"), clock.now()
        )
    finally:
        conn.close()


def on_session_end(event: Event) -> None:
    """The session ended. Extra: ``reason``. Must be fast: ~1 s budget."""
    from . import lifecycle

    conn = _connect()
    try:
        lifecycle.snooze_unanswered(conn, event.get("session_id"), clock.now())
    finally:
        conn.close()
