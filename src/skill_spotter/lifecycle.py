"""Pattern lifecycle after a suggestion (SPEC section 9.6).

candidate → ready → suggested → accepted | snoozed(until) | dismissed
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

SNOOZE_DAYS = 14
DISMISS_AFTER_SNOOZES = 2
DAY = 86400.0


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
    name = (
        os.path.basename(os.path.dirname(skill_path)) if skill_path.endswith("SKILL.md") else None
    )
    conn.execute(
        "UPDATE patterns SET state = 'accepted', skill_path = ?, state_until = NULL, "
        "suggested_name = COALESCE(?, suggested_name) WHERE id = ?",
        (skill_path, name, pattern_id),
    )
    log_event(conn, "accepted", now, pattern_id, session_id, via=via, skill_path=skill_path)
    return True
