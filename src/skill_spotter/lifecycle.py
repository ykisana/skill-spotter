"""Pattern lifecycle after a suggestion (SPEC section 9.6).

candidate → ready → suggested → accepted | snoozed(until) | dismissed

- accepted: a skill named after the pattern appears (ConfigChange on skills, a scan when
  the next turn ends, or the draft skill calling ``skill-spotter accept``);
- snoozed: the session ends without the user acting on the suggestion; 14 days;
- dismissed: after the second snooze, or ``skill-spotter dismiss``;
- used: the user types the accepted skill's command (logged as an event).
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

SNOOZE_DAYS = 14
DISMISS_AFTER_SNOOZES = 2
RETENTION_DAYS = 90
DAY = 86400.0
WAITING_STATES = ("suggested", "snoozed", "candidate", "ready")


def log_event(
    conn: sqlite3.Connection,
    kind: str,
    now: float,
    pattern_id: Optional[int] = None,
    session_id: Optional[str] = None,
    **data,
) -> None:
    conn.execute(
        "INSERT INTO events(ts, type, pattern_id, session_id, data_json) VALUES(?, ?, ?, ?, ?)",
        (now, kind, pattern_id, session_id, json.dumps(data)),
    )


def accept(
    conn: sqlite3.Connection,
    pattern_id: int,
    skill_path: str,
    now: float,
    via: str,
    session_id: Optional[str] = None,
) -> bool:
    """Mark a pattern accepted: the user saved it as a skill at ``skill_path``."""
    p = conn.execute(
        "SELECT state, skill_path FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if p is None:
        return False
    if p["state"] == "accepted" and p["skill_path"] == skill_path:
        return True
    name = skill_name_from_path(skill_path)
    conn.execute(
        "UPDATE patterns SET state = 'accepted', skill_path = ?, state_until = NULL, "
        "suggested_name = COALESCE(?, suggested_name) WHERE id = ?",
        (skill_path, name, pattern_id),
    )
    log_event(conn, "accepted", now, pattern_id, session_id, via=via, skill_path=skill_path)
    return True


def skill_name_from_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if os.path.basename(path) == "SKILL.md":
        return os.path.basename(os.path.dirname(path)) or None
    return None


def skill_file_changed(
    conn: sqlite3.Connection, file_path: Optional[str], project_key: str, now: float
) -> Optional[int]:
    """ConfigChange(skills): if the skill is one we suggested, mark it accepted."""
    name = skill_name_from_path(file_path)
    if not name or not os.path.exists(file_path or ""):
        return None
    marks = ",".join("?" * len(WAITING_STATES))
    row = conn.execute(
        f"SELECT id FROM patterns WHERE suggested_name = ? AND state IN ({marks}) "
        "ORDER BY (project_key = ?) DESC, last_seen DESC LIMIT 1",
        (name, *WAITING_STATES, project_key),
    ).fetchone()
    if row is None:
        return None
    accept(conn, row[0], os.path.abspath(file_path), now, via="config_change")
    return row[0]


def scan_for_created_skills(conn: sqlite3.Connection, project_key: str, now: float) -> List[int]:
    """Fallback for ConfigChange (it isn't documented for ~/.claude/skills): look for
    skill folders named after patterns we suggested in this project."""
    rows = conn.execute(
        "SELECT id, suggested_name FROM patterns WHERE project_key = ? "
        "AND state IN ('suggested', 'snoozed') AND suggested_name IS NOT NULL",
        (project_key,),
    ).fetchall()
    accepted = []
    bases = []
    if project_key and project_key != "?":
        bases.append(os.path.join(project_key, ".claude", "skills"))
    bases.append(os.path.expanduser("~/.claude/skills"))
    for row in rows:
        for base in bases:
            path = os.path.join(base, row["suggested_name"], "SKILL.md")
            if os.path.isfile(path):
                accept(conn, row["id"], path, now, via="scan")
                accepted.append(row["id"])
                break
    return accepted


def command_used(
    conn: sqlite3.Connection, command_name: Optional[str], session_id: Optional[str], now: float
) -> Optional[int]:
    """UserPromptExpansion: log use of a skill created from a pattern."""
    if not command_name:
        return None
    name = command_name.lstrip("/").split(":")[-1]
    for row in conn.execute(
        "SELECT id, skill_path, suggested_name FROM patterns WHERE state = 'accepted'"
    ):
        if name in (skill_name_from_path(row["skill_path"]), row["suggested_name"]):
            log_event(conn, "used", now, row["id"], session_id, command=name)
            return row["id"]
    return None


def snooze_unanswered(conn: sqlite3.Connection, session_id: Optional[str], now: float) -> List[int]:
    """SessionEnd: suggestions made in this session that are still waiting get snoozed;
    the second snooze dismisses the pattern."""
    if not session_id:
        return []
    rows = conn.execute(
        "SELECT DISTINCT p.id, p.snooze_count FROM events e JOIN patterns p ON p.id = e.pattern_id "
        "WHERE e.type = 'suggested' AND e.session_id = ? AND p.state = 'suggested'",
        (session_id,),
    ).fetchall()
    changed = []
    for row in rows:
        count = row["snooze_count"] + 1
        if count >= DISMISS_AFTER_SNOOZES:
            conn.execute(
                "UPDATE patterns SET state = 'dismissed', snooze_count = ?, state_until = NULL "
                "WHERE id = ?",
                (count, row["id"]),
            )
            log_event(conn, "dismissed", now, row["id"], session_id, reason="snoozed twice")
        else:
            until = now + SNOOZE_DAYS * DAY
            conn.execute(
                "UPDATE patterns SET state = 'snoozed', snooze_count = ?, state_until = ? "
                "WHERE id = ?",
                (count, until, row["id"]),
            )
            log_event(conn, "snoozed", now, row["id"], session_id, until=until)
        changed.append(row["id"])
    return changed


def snooze(conn: sqlite3.Connection, pattern_id: int, days: float, now: float) -> bool:
    cur = conn.execute(
        "UPDATE patterns SET state = 'snoozed', state_until = ?, snooze_count = snooze_count + 1 "
        "WHERE id = ? AND state != 'accepted'",
        (now + days * DAY, pattern_id),
    )
    if cur.rowcount:
        log_event(conn, "snoozed", now, pattern_id, until=now + days * DAY, via="cli")
    return bool(cur.rowcount)


def dismiss(conn: sqlite3.Connection, pattern_id: int, now: float) -> bool:
    cur = conn.execute(
        "UPDATE patterns SET state = 'dismissed', state_until = NULL WHERE id = ?", (pattern_id,)
    )
    if cur.rowcount:
        log_event(conn, "dismissed", now, pattern_id, reason="cli")
    return bool(cur.rowcount)


def maybe_prune(conn: sqlite3.Connection, now: float) -> int:
    """Delete turns and actions older than 90 days, at most once a day. Patterns keep
    their aggregates (count, representative), so detection isn't affected."""
    from . import store

    last = float(store.get_setting(conn, "last_prune", "0") or 0)
    if now - last < DAY:
        return 0
    cutoff = now - RETENTION_DAYS * DAY
    old = [r[0] for r in conn.execute("SELECT prompt_id FROM turns WHERE ts_start < ?", (cutoff,))]
    for start in range(0, len(old), 500):
        chunk = old[start : start + 500]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"DELETE FROM actions WHERE prompt_id IN ({marks})", chunk)
        conn.execute(f"DELETE FROM turns WHERE prompt_id IN ({marks})", chunk)
    conn.execute("DELETE FROM actions WHERE ts < ? AND prompt_id IS NULL", (cutoff,))
    conn.execute("DELETE FROM session_meta WHERE updated < ?", (cutoff,))
    store.set_setting(conn, "last_prune", str(now))
    return len(old)


def stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Suggestion and adoption numbers for ``skill-spotter stats`` (SPEC M2)."""

    def scalar(sql: str, *args) -> int:
        return conn.execute(sql, args).fetchone()[0]

    suggested = scalar("SELECT COUNT(DISTINCT pattern_id) FROM events WHERE type = 'suggested'")
    accepted = scalar("SELECT COUNT(*) FROM patterns WHERE state = 'accepted'")
    used_once = scalar("SELECT COUNT(DISTINCT pattern_id) FROM events WHERE type = 'used'")
    return {
        "turns_recorded": scalar("SELECT COUNT(*) FROM turns"),
        "patterns": scalar("SELECT COUNT(*) FROM patterns"),
        "suggestions_shown": scalar("SELECT COUNT(*) FROM events WHERE type = 'suggested'"),
        "patterns_suggested": suggested,
        "accepted": accepted,
        "accepted_pct": round(100.0 * accepted / suggested, 1) if suggested else None,
        "skills_used_at_least_once": used_once,
        "skill_uses": scalar("SELECT COUNT(*) FROM events WHERE type = 'used'"),
        "snoozed": scalar("SELECT COUNT(*) FROM patterns WHERE state = 'snoozed'"),
        "dismissed": scalar("SELECT COUNT(*) FROM patterns WHERE state = 'dismissed'"),
    }
