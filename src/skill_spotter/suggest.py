"""When to suggest a pattern, and what to say (SPEC sections 9.3–9.5)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Mapping, Optional

from . import naming, patterns, store
from .capture import normalize_text

DEFAULT_MIN_COUNT = 3
DEFAULT_MIN_SESSIONS = 2
MAX_PER_DAY = 3
GENERIC_DF_RATIO = 0.3
MIN_TURNS_FOR_DF = 10


def is_generic(conn: sqlite3.Connection, project_key: str, rep: Mapping) -> bool:
    """True if the pattern is only made of things nearly every turn does."""
    meaningful = [
        t for t, w in rep.get("tokens", {}).items() if w >= 0.5 and not t.startswith("seq:")
    ]
    if not meaningful:
        strong_words = [w for w, f in rep.get("words", {}).items() if f >= 0.6]
        return len(strong_words) < 2
    total = patterns.n_turns(conn, project_key)
    if total < MIN_TURNS_FOR_DF:
        return False
    dfs = patterns.df_lookup(conn, project_key, set(meaningful))
    return all(dfs.get(t, 0) / total > GENERIC_DF_RATIO for t in meaningful)


def _start_of_day(now: float) -> float:
    local = time.localtime(now)
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))


def message(pattern_id: int, count: int, name: str) -> str:
    return (
        f"[skill-spotter] You've done this {count} time{'s' if count != 1 else ''} "
        f"(pattern p{pattern_id}). "
        f"Run /skill-spotter:draft p{pattern_id} to save it as /{name}."
    )


def session_or_day_capped(conn: sqlite3.Connection, session_id: str, now: float) -> bool:
    """One suggestion per session, three per day (patterns and workflows together)."""
    already = conn.execute(
        "SELECT COUNT(*) FROM events WHERE type = 'suggested' AND session_id = ?", (session_id,)
    ).fetchone()[0]
    if already:
        return True
    today = conn.execute(
        "SELECT COUNT(*) FROM events WHERE type = 'suggested' AND ts >= ?", (_start_of_day(now),)
    ).fetchone()[0]
    return today >= MAX_PER_DAY


def context_text(suggestion: str) -> str:
    """The suggestion as a factual statement for Claude (``suggest_via = claude``)."""
    body = suggestion.replace("[skill-spotter] ", "")
    return (
        "skill-spotter (a local Claude Code plugin) noticed a repeated task in this project. "
        f"{body} The user decides whether to do this."
    )


def maybe_suggest(
    conn: sqlite3.Connection, pattern_id: int, session_id: str, now: float
) -> Optional[str]:
    """Return the suggestion text if the pattern crosses the trigger rule now."""
    if not store.is_enabled(conn):
        return None
    p = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if p is None:
        return None
    state = p["state"]
    snooze_over = state == "snoozed" and (p["state_until"] or 0) <= now
    if state not in ("candidate", "ready") and not snooze_over:
        return None
    min_count = int(store.get_setting(conn, "min_count", str(DEFAULT_MIN_COUNT)))
    min_sessions = int(store.get_setting(conn, "min_sessions", str(DEFAULT_MIN_SESSIONS)))
    count, sessions = patterns.recent_stats(conn, pattern_id, now)
    if count < min_count or sessions < min_sessions:
        return None
    rep = json.loads(p["representative_json"])
    if is_generic(conn, p["project_key"], rep):
        return None
    # A task split across two patterns: fold this one into the pattern already shown (or
    # accepted, or dismissed) instead of suggesting the same task twice.
    twin = patterns.similar_pattern(
        conn, pattern_id, ("suggested", "snoozed", "accepted", "dismissed")
    )
    if twin is not None:
        patterns.merge_into(conn, twin, [pattern_id])
        conn.execute(
            "INSERT INTO events(ts, type, pattern_id, session_id, data_json) "
            "VALUES(?, 'merged', ?, ?, ?)",
            (now, twin, session_id, json.dumps({"from": [pattern_id], "via": "suggest"})),
        )
        return None
    if session_or_day_capped(conn, session_id, now):
        return None
    # Part of a multi-prompt workflow that is forming (or was suggested): the workflow
    # gets the single suggestion instead (M5).
    if p["workflow_id"] is not None:
        return None
    from . import workflows

    if workflows.forming_for_pattern(conn, pattern_id, session_id, now):
        return None
    taken = [
        r[0]
        for r in conn.execute(
            "SELECT suggested_name FROM patterns WHERE project_key = ? AND id != ? "
            "AND suggested_name IS NOT NULL",
            (p["project_key"], pattern_id),
        )
    ]
    root = p["project_key"] if p["project_key"] != "?" else None
    latest = conn.execute(
        "SELECT prompt_redacted FROM turns WHERE pattern_id = ? ORDER BY ts_start DESC LIMIT 1",
        (pattern_id,),
    ).fetchone()
    hint = normalize_text.content_words(latest[0] or "") if latest else []
    name = p["suggested_name"] or naming.suggest_name(rep, root, taken, hint)
    conn.execute(
        "UPDATE patterns SET state = 'suggested', suggested_name = ?, state_until = NULL "
        "WHERE id = ?",
        (name, pattern_id),
    )
    conn.execute(
        "INSERT INTO events(ts, type, pattern_id, session_id, data_json) "
        "VALUES(?, 'suggested', ?, ?, ?)",
        (now, pattern_id, session_id, json.dumps({"count": count, "name": name})),
    )
    return message(pattern_id, count, name)


def suggest_ready(
    conn: sqlite3.Connection, project_key: str, session_id: str, now: float
) -> Optional[str]:
    """Show the oldest pattern the background job marked ``ready`` in this project."""
    row = conn.execute(
        "SELECT id FROM patterns WHERE project_key = ? AND state = 'ready' "
        "ORDER BY last_seen LIMIT 1",
        (project_key,),
    ).fetchone()
    return maybe_suggest(conn, row[0], session_id, now) if row else None
