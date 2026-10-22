"""Finalize turns and group them into patterns with online leader clustering.

When ``Stop`` fires, the turn's actions become a fingerprint ({token: weight}), and the
turn joins the best-matching pattern in its project, or starts a new one. A pattern's
``representative`` is the running average of its members, so it drifts to the task's
common core instead of staying pinned to the first example.

Candidates come from an inverted index (``pattern_tokens``) over distinctive tokens, so a
lookup costs the same with 20 or 2,000 active patterns.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from . import naming
from .capture import normalize_text
from .capture.normalize_actions import turn_fingerprint
from .match import baseline

WINDOW_DAYS = 30
MAX_CANDIDATES = 50
INDEX_MIN_WEIGHT = 0.25
INDEX_MIN_TEXT = 0.34
PRUNE_BELOW = 0.05
METHOD_VERSION = "baseline-1"
DAY = 86400.0


def load_turn_actions(conn: sqlite3.Connection, prompt_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT tokens_json, danger FROM actions WHERE prompt_id = ? ORDER BY ts, id", (prompt_id,)
    ).fetchall()
    actions = []
    for row in rows:
        stored = json.loads(row["tokens_json"])
        if isinstance(stored, dict) and "tokens" in stored:
            stored["danger"] = bool(row["danger"])
            actions.append(stored)
    return actions


def df_lookup(conn: sqlite3.Connection, project_key: str, tokens: Set[str]) -> Dict[str, int]:
    found: Dict[str, int] = {}
    tokens_list = list(tokens)
    for start in range(0, len(tokens_list), 500):
        chunk = tokens_list[start : start + 500]
        marks = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT token, df FROM token_df WHERE project_key = ? AND token IN ({marks})",
            [project_key, *chunk],
        ):
            found[row[0]] = row[1]
    return found


def n_turns(conn: sqlite3.Connection, project_key: str) -> int:
    row = conn.execute(
        "SELECT n_turns FROM project_stats WHERE project_key = ?", (project_key,)
    ).fetchone()
    return row[0] if row else 0


def index_tokens(rep: Mapping[str, Any]) -> Set[str]:
    tokens = {t for t, w in rep.get("tokens", {}).items() if w >= INDEX_MIN_WEIGHT}
    tokens.update(
        f"txt:{g}" for g, f in rep.get("text", {}).items() if " " not in g and f >= INDEX_MIN_TEXT
    )
    return tokens


def _average(old: Mapping[str, float], new: Mapping[str, float], n: int) -> Dict[str, float]:
    merged = {}
    for key in old.keys() | new.keys():
        value = (old.get(key, 0.0) * n + new.get(key, 0.0)) / (n + 1)
        if value >= PRUNE_BELOW:
            merged[key] = round(value, 4)
    return merged


def _reindex(conn: sqlite3.Connection, pattern_id: int, rep: Mapping[str, Any]) -> None:
    conn.execute("DELETE FROM pattern_tokens WHERE pattern_id = ?", (pattern_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO pattern_tokens(token, pattern_id) VALUES(?, ?)",
        [(t, pattern_id) for t in index_tokens(rep)],
    )


def best_match(
    conn: sqlite3.Connection,
    project_key: str,
    fingerprint: Mapping[str, float],
    grams: Set[str],
    n_meaningful: int,
    now: float,
    params: Optional[Mapping[str, Any]] = None,
) -> Tuple[Optional[int], float, float]:
    """(pattern_id, action_sim, text_sim) of the best pattern passing the rule."""
    if params is None:
        from .match import fused

        params = fused.online_params()
    probe = {t for t, w in fingerprint.items() if w >= INDEX_MIN_WEIGHT}
    probe.update(f"txt:{g}" for g in grams if " " not in g)
    if not probe:
        return None, 0.0, 0.0
    marks = ",".join("?" * len(probe))
    candidates = conn.execute(
        f"SELECT pt.pattern_id, COUNT(*) AS hits FROM pattern_tokens pt "
        f"JOIN patterns p ON p.id = pt.pattern_id "
        f"WHERE pt.token IN ({marks}) AND p.project_key = ? AND p.last_seen >= ? "
        f"GROUP BY pt.pattern_id ORDER BY hits DESC, p.last_seen DESC LIMIT ?",
        [*probe, project_key, now - WINDOW_DAYS * DAY, MAX_CANDIDATES],
    ).fetchall()
    if not candidates:
        return None, 0.0, 0.0
    reps = {}
    ids = [c[0] for c in candidates]
    for row in conn.execute(
        f"SELECT id, representative_json FROM patterns WHERE id IN ({','.join('?' * len(ids))})",
        ids,
    ):
        reps[row[0]] = json.loads(row[1])
    all_tokens = set(fingerprint)
    for rep in reps.values():
        all_tokens.update(rep.get("tokens", {}))
    dfs = df_lookup(conn, project_key, all_tokens)
    total = n_turns(conn, project_key)

    use_idf = params.get("action_weighting", "idf") == "idf"

    def weight_of(token: str) -> float:
        return baseline.idf(dfs.get(token, 0), total) if use_idf else 1.0

    best: Tuple[Optional[int], float, float] = (None, 0.0, 0.0)
    best_score = -1.0
    min_w = params.get("meaningful_min_weight", 0.0)
    probe_fp = baseline.meaningful(fingerprint, min_w)
    for pattern_id, rep in reps.items():
        a = baseline.weighted_jaccard(
            probe_fp, baseline.meaningful(rep.get("tokens", {}), min_w), weight_of
        )
        t = baseline.text_similarity(grams, rep.get("text", {}))
        if baseline.same_task(a, t, n_meaningful, params):
            s = baseline.score(a, t, params)
            if s > best_score:
                best, best_score = (pattern_id, a, t), s
    return best


def fused_match(
    conn: sqlite3.Connection,
    scorer,
    project_key: str,
    turn: Dict[str, Any],
    fingerprint: Mapping[str, float],
    grams: Set[str],
    now: float,
) -> Optional[int]:
    """The Method Lab's chosen matcher (config/method.json): mean fused score between the
    turn and the last ``scorer.members`` turns of each candidate pattern; join the best if
    it reaches ``scorer.theta``. Candidates come from the inverted index, as for the rule."""
    probe = {t for t, w in fingerprint.items() if w >= INDEX_MIN_WEIGHT}
    probe.update(f"txt:{g}" for g in grams if " " not in g)
    if not probe:
        return None
    marks = ",".join("?" * len(probe))
    candidates = [
        r[0]
        for r in conn.execute(
            f"SELECT pt.pattern_id, COUNT(*) AS hits FROM pattern_tokens pt "
            f"JOIN patterns p ON p.id = pt.pattern_id "
            f"WHERE pt.token IN ({marks}) AND p.project_key = ? AND p.last_seen >= ? "
            f"GROUP BY pt.pattern_id ORDER BY hits DESC, p.last_seen DESC LIMIT ?",
            [*probe, project_key, now - WINDOW_DAYS * DAY, scorer.max_candidates],
        )
    ]
    if not candidates:
        return None
    members: Dict[int, List[str]] = {}
    for pid in candidates:
        members[pid] = [
            r[0]
            for r in conn.execute(
                "SELECT prompt_id FROM turns WHERE pattern_id = ? AND finalized = 1 "
                "ORDER BY ts_end DESC LIMIT ?",
                (pid, scorer.members),
            )
        ]
    data = scorer.load(conn, [m for ms in members.values() for m in ms])
    words = set(turn["tokens"])
    for d in data.values():
        words.update(d["tokens"])
    scorer.bind(conn, project_key, words)
    best, best_score = None, -1.0
    for pid, ms in members.items():
        scores = [scorer.score(turn, data[m]) for m in ms if m in data]
        if scores and sum(scores) / len(scores) > best_score:
            best, best_score = pid, sum(scores) / len(scores)
    return best if best is not None and best_score >= scorer.theta else None


def finalize_turn(conn: sqlite3.Connection, prompt_id: str, now: float) -> Optional[int]:
    """Close the turn, assign it to a pattern and return the pattern id (idempotent)."""
    turn = conn.execute("SELECT * FROM turns WHERE prompt_id = ?", (prompt_id,)).fetchone()
    if turn is None:
        return None
    if turn["finalized"]:
        return turn["pattern_id"]
    actions = load_turn_actions(conn, prompt_id)
    fingerprint = turn_fingerprint(actions)
    tokens = (turn["prompt_norm"] or "").split()
    grams = normalize_text.ngrams(tokens)
    n_meaningful = sum(1 for a in actions if not a.get("low"))
    seq = [a["primary"] for a in actions if a.get("primary") and not a.get("low")]
    seq = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]
    danger = any(a.get("danger") for a in actions)
    project_key = turn["project_key"]

    conn.execute("BEGIN IMMEDIATE")
    try:
        pattern_id = None
        if fingerprint or grams:
            from .match import fused

            scorer = fused.load_scorer()
            if scorer.fusion != "rule" and tokens:
                turn_data = {
                    "fp": fingerprint,
                    "seq": seq,
                    "files": {t for t in fingerprint if t.startswith("edit:")},
                    "tokens": tokens,
                    "grams": grams,
                    "n": n_meaningful,
                    "session": turn["session_id"],
                    "ts": now,
                }
                pattern_id = fused_match(
                    conn, scorer, project_key, turn_data, fingerprint, grams, now
                )
            else:
                params = fused.online_params()
                if not tokens:  # shell history: no prompt, so actions alone decide
                    params = {**params, "text_gate": 0.0}
                pattern_id, _a, _t = best_match(
                    conn, project_key, fingerprint, grams, n_meaningful, now, params
                )
            # Count this turn in the IDF statistics after matching against the old ones.
            conn.executemany(
                "INSERT INTO token_df(project_key, token, df) VALUES(?, ?, 1) "
                "ON CONFLICT(project_key, token) DO UPDATE SET df = df + 1",
                [(project_key, t) for t in fingerprint],
            )
            conn.executemany(  # word document frequencies, for BM25 text similarity
                "INSERT INTO token_df(project_key, token, df) VALUES(?, ?, 1) "
                "ON CONFLICT(project_key, token) DO UPDATE SET df = df + 1",
                [(project_key, f"w:{w}") for w in set(tokens)],
            )
            conn.execute(
                "INSERT INTO project_stats(project_key, n_turns, text_len) VALUES(?, 1, ?) "
                "ON CONFLICT(project_key) DO UPDATE SET n_turns = n_turns + 1, "
                "text_len = text_len + excluded.text_len",
                (project_key, len(tokens)),
            )
            text = {g: 1.0 for g in grams}
            content = normalize_text.content_words(turn["prompt_redacted"] or "")
            words = {w: 1.0 for w in set(content)}
            first = {content[0]: 1.0} if content else {}
            lead = {w: 1.0 for w in set(content[: naming.LEAD_WORDS])}
            if pattern_id is None:
                rep = {
                    "tokens": fingerprint,
                    "text": text,
                    "words": words,
                    "first": first,
                    "lead": lead,
                    "n": 1,
                }
                cur = conn.execute(
                    "INSERT INTO patterns(project_key, representative_json, count, session_count, "
                    "first_seen, last_seen, danger, method_version) VALUES(?, ?, 1, 1, ?, ?, ?, ?)",
                    (project_key, json.dumps(rep), now, now, int(danger), METHOD_VERSION),
                )
                pattern_id = cur.lastrowid
            else:
                row = conn.execute(
                    "SELECT representative_json, count, danger FROM patterns WHERE id = ?",
                    (pattern_id,),
                ).fetchone()
                old = json.loads(row["representative_json"])
                n = int(old.get("n", row["count"]) or 1)
                rep = {
                    "tokens": _average(old.get("tokens", {}), fingerprint, n),
                    "text": _average(old.get("text", {}), text, n),
                    "words": _average(old.get("words", {}), words, n),
                    "first": _average(old.get("first", {}), first, n),
                    "lead": _average(old.get("lead", {}), lead, n),
                    "n": n + 1,
                }
                conn.execute(
                    "UPDATE patterns SET representative_json = ?, count = count + 1, "
                    "last_seen = ?, danger = MAX(danger, ?) WHERE id = ?",
                    (json.dumps(rep), now, int(danger), pattern_id),
                )
            _reindex(conn, pattern_id, rep)
        conn.execute(
            "UPDATE turns SET finalized = 1, ts_end = ?, pattern_id = ?, fingerprint_json = ?, "
            "n_meaningful_actions = ?, danger = ?, seq_json = ? WHERE prompt_id = ?",
            (
                now,
                pattern_id,
                json.dumps(fingerprint),
                n_meaningful,
                int(danger),
                json.dumps(seq),
                prompt_id,
            ),
        )
        if pattern_id is not None:
            sessions = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM turns WHERE pattern_id = ?", (pattern_id,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE patterns SET session_count = ? WHERE id = ?", (sessions, pattern_id)
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return pattern_id


def rebuild_representative(conn: sqlite3.Connection, pattern_id: int) -> Dict[str, Any]:
    """Recompute a pattern's representative from its member turns (after a merge)."""
    rows = conn.execute(
        "SELECT session_id, ts_start, ts_end, prompt_norm, prompt_redacted, fingerprint_json, "
        "danger FROM turns WHERE pattern_id = ? ORDER BY ts_start",
        (pattern_id,),
    ).fetchall()
    rep: Dict[str, Any] = {"tokens": {}, "text": {}, "words": {}, "first": {}, "lead": {}, "n": 0}
    for n, row in enumerate(rows):
        content = normalize_text.content_words(row["prompt_redacted"] or "")
        new = {
            "tokens": json.loads(row["fingerprint_json"] or "{}"),
            "text": {g: 1.0 for g in normalize_text.ngrams((row["prompt_norm"] or "").split())},
            "words": {w: 1.0 for w in set(content)},
            "first": {content[0]: 1.0} if content else {},
            "lead": {w: 1.0 for w in set(content[: naming.LEAD_WORDS])},
        }
        for key in ("tokens", "text", "words", "first", "lead"):
            rep[key] = _average(rep[key], new[key], n)
        rep["n"] = n + 1
    if rows:
        conn.execute(
            "UPDATE patterns SET representative_json = ?, count = ?, session_count = ?, "
            "first_seen = ?, last_seen = ?, danger = ? WHERE id = ?",
            (
                json.dumps(rep),
                len(rows),
                len({r["session_id"] for r in rows}),
                rows[0]["ts_start"],
                rows[-1]["ts_end"] or rows[-1]["ts_start"],
                int(any(r["danger"] for r in rows)),
                pattern_id,
            ),
        )
        _reindex(conn, pattern_id, rep)
    return rep


def merge_into(conn: sqlite3.Connection, target: int, others: List[int]) -> None:
    """Move the turns of ``others`` into ``target`` and delete ``others`` (caller commits)."""
    if not others:
        return
    marks = ",".join("?" * len(others))
    conn.execute(
        f"UPDATE turns SET pattern_id = ? WHERE pattern_id IN ({marks})", [target, *others]
    )
    conn.execute(f"DELETE FROM patterns WHERE id IN ({marks})", others)
    rebuild_representative(conn, target)


def similar_pattern(
    conn: sqlite3.Connection, pattern_id: int, states, params: Optional[Mapping[str, Any]] = None
) -> Optional[int]:
    """Another pattern in the same project, in one of ``states``, that the same-task rule
    says is this task: used to stop a task split across two patterns being suggested twice."""
    if params is None:
        from .match import fused

        params = fused.online_params()
    p = conn.execute(
        "SELECT project_key, representative_json FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if p is None:
        return None
    rep = json.loads(p["representative_json"])
    marks = ",".join("?" * len(states))
    others = conn.execute(
        f"SELECT id, representative_json FROM patterns WHERE project_key = ? AND id != ? "
        f"AND state IN ({marks})",
        (p["project_key"], pattern_id, *states),
    ).fetchall()
    if not others:
        return None
    tokens = set(rep.get("tokens", {}))
    reps = {o["id"]: json.loads(o["representative_json"]) for o in others}
    for r in reps.values():
        tokens.update(r.get("tokens", {}))
    dfs = df_lookup(conn, p["project_key"], tokens)
    total = n_turns(conn, p["project_key"])
    min_w = params.get("meaningful_min_weight", 0.0)
    mine = baseline.meaningful(rep.get("tokens", {}), min_w)
    my_text = {g for g, f in rep.get("text", {}).items() if f >= 0.5}
    best, best_score = None, -1.0
    for oid, r in reps.items():
        a = baseline.weighted_jaccard(
            mine,
            baseline.meaningful(r.get("tokens", {}), min_w),
            lambda t: (
                baseline.idf(dfs.get(t, 0), total)
                if params.get("action_weighting", "idf") == "idf"
                else 1.0
            ),
        )
        t = baseline.text_similarity(my_text, r.get("text", {}))
        if baseline.same_task(a, t, 3, params) and baseline.score(a, t, params) > best_score:
            best, best_score = oid, baseline.score(a, t, params)
    return best


def recent_stats(conn: sqlite3.Connection, pattern_id: int, now: float) -> Tuple[int, int]:
    """(occurrences, distinct sessions) in the last 30 days."""
    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_id) FROM turns "
        "WHERE pattern_id = ? AND ts_end >= ?",
        (pattern_id, now - WINDOW_DAYS * DAY),
    ).fetchone()
    return row[0], row[1]
