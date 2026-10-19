"""Hand-off between the Stop hook and the skill-spotter mod's band (M7).

When the mod is loaded, it registers the session (``skill-spotter band register``), the
Stop hook queues suggestions here instead of printing a ``systemMessage``, and the mod
fetches them after each turn (``skill-spotter band pending``) to draw
"You've done this 5× — [Create /name] [Not now]". Without the mod, nothing changes.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Dict, Optional

_MESSAGE = re.compile(
    r"done this (?P<what>.+?) \((?P<kind>pattern|workflow) (?P<id>[pw]\d+)[:)].*?save it as "
    r"/(?P<name>[\w\-]+)"
)


def register(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO session_meta(session_id, band_active, updated) VALUES(?, 1, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET band_active = 1, updated = excluded.updated",
        (session_id, time.time()),
    )


def parse(text: str) -> Dict[str, Any]:
    m = _MESSAGE.search(text)
    if not m:
        return {"text": text}
    return {
        "text": text,
        "what": m.group("what"),
        "id": m.group("id"),
        "name": m.group("name"),
        "draft": f"/skill-spotter:draft {m.group('id')}",
    }


def queue(conn: sqlite3.Connection, session_id: str, text: str) -> None:
    conn.execute(
        "UPDATE session_meta SET pending_band = ? WHERE session_id = ?",
        (json.dumps(parse(text)), session_id),
    )


def pop(conn: sqlite3.Connection, session_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT pending_band FROM session_meta WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row or not row[0]:
        return None
    conn.execute("UPDATE session_meta SET pending_band = NULL WHERE session_id = ?", (session_id,))
    return json.loads(row[0])
