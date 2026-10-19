"""Background re-clustering job (SPEC 5.5). Runs detached; never blocks a hook.

1. Take each project's turns from the last 30 days.
2. Score pairs with the configured matcher (the stdlib fused scorer by default; an extras
   scorer when optional dependencies are installed in ``<data dir>/extras``).
3. Cluster (union-find over pairs above theta, stdlib) and merge online patterns that
   the batch view says are one task: the online matcher only sees one turn at a time and
   sometimes splits a task early.
4. Mark merged patterns that now cross the trigger rule ``ready``; the next Stop in that
   project shows the suggestion.

    python3 -S job.py --data-dir DIR        (started by background.launcher)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List

if __package__ in (None, ""):  # run as a script: make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from skill_spotter import paths, store  # noqa: E402

WINDOW = 30 * 86400.0
MAX_TURNS_PER_PROJECT = 1500  # cap the O(n^2) pass; newest turns win


def _extras_path(base: Path) -> Path:
    return base / "extras"


def use_extras(base: Path) -> bool:
    path = _extras_path(base)
    if not path.is_dir():
        return False
    sys.path.insert(0, str(path))
    try:
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
    except Exception:
        return False
    return True


class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def cluster_project(conn, project_key: str, now: float, scorer, theta: float) -> List[List[str]]:
    rows = conn.execute(
        "SELECT prompt_id FROM turns WHERE project_key = ? AND finalized = 1 AND ts_end >= ? "
        "AND pattern_id IS NOT NULL ORDER BY ts_end DESC LIMIT ?",
        (project_key, now - WINDOW, MAX_TURNS_PER_PROJECT),
    ).fetchall()
    ids = [r[0] for r in rows]
    if len(ids) < 3:
        return []
    data = scorer.load(conn, ids)
    words = set()
    for d in data.values():
        words.update(d["tokens"])
    scorer.bind(conn, project_key, words)
    uf = UnionFind(ids)
    pairs = [
        (a, b)
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
        if a in data and b in data and not scorer.quick_reject(data[a], data[b])
    ]
    if hasattr(scorer, "score_many"):  # extras: batch prediction
        scores = []
        for start in range(0, len(pairs), 5000):
            chunk = pairs[start : start + 5000]
            scores += scorer.score_many([(data[a], data[b]) for a, b in chunk])
    else:
        scores = [scorer.score(data[a], data[b]) for a, b in pairs]
    for (a, b), s in zip(pairs, scores):
        if s >= theta:
            uf.union(a, b)
    groups: Dict[str, List[str]] = {}
    for x in ids:
        groups.setdefault(uf.find(x), []).append(x)
    return [g for g in groups.values() if len(g) >= 2]


MERGEABLE = ("candidate", "ready", "suggested", "snoozed")


def merge_patterns(conn, group: List[str], now: float) -> int:
    """Put the group's turns into one pattern; returns the target pattern id or -1."""
    from skill_spotter import patterns as P

    marks = ",".join("?" * len(group))
    pids = sorted(
        {
            r[0]
            for r in conn.execute(
                f"SELECT pattern_id FROM turns WHERE prompt_id IN ({marks})", group
            )
        }
    )
    states = {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT id, state FROM patterns WHERE id IN ({','.join('?' * len(pids))})", pids
        )
    }
    pids = [p for p in pids if states.get(p) in MERGEABLE]
    if len(pids) < 2:
        return pids[0] if pids else -1
    # Prefer a pattern the user has already seen as the target, else the oldest.
    rank = {"suggested": 0, "snoozed": 1, "ready": 2, "candidate": 3}
    target = min(pids, key=lambda p: (rank[states[p]], p))
    others = [p for p in pids if p != target]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE turns SET pattern_id = ? WHERE pattern_id IN ({','.join('?' * len(others))})",
            [target, *others],
        )
        P.rebuild_representative(conn, target)
        conn.execute(f"DELETE FROM patterns WHERE id IN ({','.join('?' * len(others))})", others)
        conn.execute(
            "INSERT INTO events(ts, type, pattern_id, data_json) VALUES(?, 'merged', ?, ?)",
            (now, target, json.dumps({"from": others, "via": "background"})),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return target


def mark_ready(conn, pattern_id: int, now: float) -> bool:
    from skill_spotter import patterns as P
    from skill_spotter import suggest

    p = conn.execute(
        "SELECT state, project_key, representative_json FROM patterns WHERE id = ?", (pattern_id,)
    ).fetchone()
    if p is None or p["state"] != "candidate":
        return False
    count, sessions = P.recent_stats(conn, pattern_id, now)
    min_count = int(store.get_setting(conn, "min_count", str(suggest.DEFAULT_MIN_COUNT)))
    min_sessions = int(store.get_setting(conn, "min_sessions", str(suggest.DEFAULT_MIN_SESSIONS)))
    if count < min_count or sessions < min_sessions:
        return False
    if suggest.is_generic(conn, p["project_key"], json.loads(p["representative_json"])):
        return False
    conn.execute("UPDATE patterns SET state = 'ready' WHERE id = ?", (pattern_id,))
    return True


def run(base: Path, now: float) -> Dict:
    from skill_spotter.match import fused

    conn = store.connect(paths.db_path(base), timeout=10)
    extras = use_extras(base)
    scorer = None
    if extras:
        try:
            from skill_spotter.background import extras as extras_mod

            scorer = extras_mod.load(base, fused.CONFIG_DIR)
        except Exception:  # broken or partial install: fall back to the stdlib scorer
            traceback.print_exc()
            scorer = None
    extras = scorer is not None
    if scorer is None:
        scorer = fused.load_scorer()
    theta = scorer.batch_theta
    summary = {"extras": extras, "projects": 0, "groups": 0, "merged": 0, "ready": 0}
    projects = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT project_key FROM turns WHERE ts_end >= ?", (now - WINDOW,)
        )
    ]
    for project in projects:
        summary["projects"] += 1
        for group in cluster_project(conn, project, now, scorer, theta):
            summary["groups"] += 1
            before = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            target = merge_patterns(conn, group, now)
            summary["merged"] += (
                before - conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            )
            if target >= 0 and mark_ready(conn, target, now):
                summary["ready"] += 1
    total = conn.execute("SELECT COUNT(*) FROM turns WHERE finalized = 1").fetchone()[0]
    store.set_setting(conn, "background_last_turns", str(total))
    store.set_setting(conn, "background_last_run", str(now))
    store.set_setting(conn, "background_last_summary", json.dumps(summary))
    conn.close()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    base = Path(args.data_dir)
    lock = base / "background.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 1800:
            return 0  # another job is running
        lock.unlink()
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        started = time.time()
        summary = run(base, started)
        print(
            json.dumps(
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "seconds": round(time.time() - started, 2),
                    **summary,
                }
            )
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


if __name__ == "__main__":
    sys.exit(main())
