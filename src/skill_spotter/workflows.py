"""Multi-turn workflows (M5): a task the user splits across several prompts in a session,
e.g. "pull the merged PRs" → "draft the changelog" → "open the release PR".

Each turn is already assigned to a pattern. A session's recent turns form a sequence of
pattern ids; at each Stop the sequences of length 2–4 ending at this turn are counted
across sessions (contiguous n-grams, allowing ``MAX_GAP`` unrelated turns between steps,
within ``SESSION_WINDOW``). A sequence seen in ``MIN_SESSIONS`` sessions becomes one
suggestion, so a 3-prompt workflow isn't suggested as three separate skills:

- longer workflows win: a sequence isn't suggested while a longer one extending it is
  forming (seen in at least as many sessions minus one);
- step patterns are held back while a workflow containing them is forming, and are
  suppressed once that workflow is suggested.

The Method Lab (``bench.sequences``) compares this against PrefixSpan and SPADE.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple

MIN_LEN, MAX_LEN = 2, 4
MAX_GAP = 1
SESSION_WINDOW = 4 * 3600.0
MIN_SESSIONS = 3
FORMING_SESSIONS = 2


def _key(steps: Sequence[int]) -> str:
    return ">".join(str(s) for s in steps)


def session_steps(conn: sqlite3.Connection, session_id: str, now: float) -> List[Tuple[int, float]]:
    rows = conn.execute(
        "SELECT pattern_id, ts_end FROM turns WHERE session_id = ? AND finalized = 1 "
        "AND pattern_id IS NOT NULL AND ts_end >= ? ORDER BY ts_end",
        (session_id, now - SESSION_WINDOW),
    ).fetchall()
    out: List[Tuple[int, float]] = []
    for pid, ts in rows:
        if not out or out[-1][0] != pid:  # the same task twice in a row is one step
            out.append((pid, ts))
    return out


def candidates_ending_here(steps: List[int], max_gap: int = MAX_GAP) -> List[Tuple[int, ...]]:
    """Sequences of 2..4 distinct steps ending at the last step, skipping at most
    ``max_gap`` unrelated steps in total."""
    if len(steps) < MIN_LEN:
        return []
    last = steps[-1]
    found = set()

    def extend(seq, i, gaps):
        if MIN_LEN <= len(seq) <= MAX_LEN:
            found.add(tuple(reversed(seq)))
        if len(seq) == MAX_LEN or i < 0:
            return
        for j in range(i, max(-1, i - 1 - (max_gap - gaps)), -1):
            if steps[j] in seq:
                continue
            extend(seq + [steps[j]], j - 1, gaps + (i - j))

    extend([last], len(steps) - 2, 0)
    return sorted(found, key=len)


def record(conn: sqlite3.Connection, project_key: str, session_id: str, now: float) -> List[int]:
    """Count the sequences ending at the session's latest turn. Returns workflow ids touched."""
    steps = [pid for pid, _ in session_steps(conn, session_id, now)]
    touched = []
    for seq in candidates_ending_here(steps):
        key = _key(seq)
        conn.execute(
            "INSERT INTO workflows(project_key, steps_key, steps_json, count, session_count, "
            "first_seen, last_seen) VALUES(?, ?, ?, 0, 0, ?, ?) "
            "ON CONFLICT(project_key, steps_key) DO NOTHING",
            (project_key, key, json.dumps(list(seq)), now, now),
        )
        wid = conn.execute(
            "SELECT id FROM workflows WHERE project_key = ? AND steps_key = ?", (project_key, key)
        ).fetchone()[0]
        new_session = conn.execute(
            "INSERT OR IGNORE INTO workflow_sessions(workflow_id, session_id, ts) VALUES(?, ?, ?)",
            (wid, session_id, now),
        ).rowcount
        conn.execute(
            "UPDATE workflows SET count = count + ?, last_seen = ?, session_count = "
            "(SELECT COUNT(*) FROM workflow_sessions WHERE workflow_id = ?) WHERE id = ?",
            (1 if new_session else 0, now, wid, wid),
        )
        touched.append(wid)
    return touched


def forming_for_pattern(
    conn: sqlite3.Connection, pattern_id: int, session_id: str, now: float
) -> bool:
    """Hold a step's own suggestion while this session is part-way through a workflow that
    is taking shape: the session's latest steps match the workflow's steps up to this one.
    A first step the user also does on its own a lot isn't held back."""
    steps = [pid for pid, _ in session_steps(conn, session_id, now)]
    if not steps or steps[-1] != pattern_id:
        return False
    count = conn.execute("SELECT count FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    count = count[0] if count else 0
    for steps_json, sessions in conn.execute(
        "SELECT steps_json, session_count FROM workflows "
        "WHERE state = 'candidate' AND session_count >= ?",
        (FORMING_SESSIONS,),
    ):
        flow = json.loads(steps_json)
        if pattern_id not in flow:
            continue
        i = flow.index(pattern_id)
        if i == len(flow) - 1:
            continue  # the workflow would complete now; it gets suggested on its own
        if i == 0 and count >= 2 * sessions + 1:
            continue  # often done alone
        if _contains(steps[-(i + 1 + MAX_GAP) :], flow[: i + 1]):
            return True
    return False


def _longer_forming(conn, project_key: str, seq: List[int], sessions: int, touched=()) -> bool:
    """A longer workflow containing ``seq`` that could still complete later in this
    session. Ones that just ended at this turn (``touched``) can't, so they don't count."""
    for wid, steps_json, _n in conn.execute(
        "SELECT id, steps_json, session_count FROM workflows "
        "WHERE project_key = ? AND state = 'candidate' "
        "AND session_count >= ?",
        (project_key, max(FORMING_SESSIONS, sessions - 1)),
    ):
        if wid in touched:
            continue
        longer = json.loads(steps_json)
        if len(longer) > len(seq) and _contains(longer, seq):
            return True
    return False


def _contains(longer: Sequence[int], seq: Sequence[int]) -> bool:
    it = iter(longer)
    return all(any(x == y for y in it) for x in seq)


def _step_names(conn, steps: Sequence[int]) -> List[str]:
    names = []
    for pid in steps:
        row = conn.execute("SELECT suggested_name FROM patterns WHERE id = ?", (pid,)).fetchone()
        names.append(row[0] if row and row[0] else f"p{pid}")
    return names


def maybe_suggest(
    conn: sqlite3.Connection, project_key: str, session_id: str, touched: List[int], now: float
) -> Optional[str]:
    """Suggest the longest workflow that crossed the threshold at this turn, if any."""
    from . import naming, store, suggest

    if not touched or not store.is_enabled(conn):
        return None
    if suggest.session_or_day_capped(conn, session_id, now):
        return None
    marks = ",".join("?" * len(touched))
    rows = conn.execute(
        f"SELECT * FROM workflows WHERE id IN ({marks}) "
        "AND state = 'candidate' AND session_count >= ?",
        (*touched, MIN_SESSIONS),
    ).fetchall()
    rows.sort(key=lambda r: (-len(json.loads(r["steps_json"])), -r["session_count"]))
    for w in rows:
        steps = json.loads(w["steps_json"])
        if _longer_forming(conn, project_key, steps, w["session_count"], set(touched)):
            continue
        # Name it after the step patterns' words (a workflow of "pull merged PRs" →
        # "write changelog" → "open release PR" usually names itself after its middle).
        reps = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT representative_json FROM patterns "
                f"WHERE id IN ({','.join('?' * len(steps))})",
                steps,
            )
        ]
        merged: Dict[str, float] = {}
        tokens: Dict[str, float] = {}
        for rep in reps:
            for word, frac in rep.get("words", {}).items():
                merged[word] = max(merged.get(word, 0.0), frac)
            tokens.update(rep.get("tokens", {}))
        root = project_key if project_key != "?" else None
        name = w["suggested_name"] or naming.suggest_name({"words": merged, "tokens": tokens}, root)
        if not name.endswith("-flow"):
            name = f"{name}-flow"[:40]
        conn.execute(
            "UPDATE workflows SET state = 'suggested', suggested_name = ? WHERE id = ?",
            (name, w["id"]),
        )
        # sub-sequences are covered by this one; step patterns are part of it now
        for other_id, other_json in conn.execute(
            "SELECT id, steps_json FROM workflows "
            "WHERE project_key = ? AND state = 'candidate' AND id != ?",
            (project_key, w["id"]),
        ).fetchall():
            if _contains(steps, json.loads(other_json)):
                conn.execute("UPDATE workflows SET state = 'superseded' WHERE id = ?", (other_id,))
        conn.execute(
            f"UPDATE patterns SET workflow_id = ? WHERE id IN ({','.join('?' * len(steps))})",
            (w["id"], *steps),
        )
        conn.execute(
            "INSERT INTO events(ts, type, session_id, workflow_id, data_json) "
            "VALUES(?, 'suggested', ?, ?, ?)",
            (now, session_id, w["id"], json.dumps({"steps": steps, "name": name})),
        )
        chain = " → ".join(f"/{n}" for n in _step_names(conn, steps))
        return (
            f"[skill-spotter] You've done this {len(steps)}-step workflow in "
            f"{w['session_count']} sessions (workflow w{w['id']}: {chain}). "
            f"Run /skill-spotter:draft w{w['id']} to save it as /{name}."
        )
    return None
