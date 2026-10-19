"""Scale test and lookup benchmark (SPEC 11.6, 11.2 lookup row).

1. Runtime scale: synthesize 100k turns / ~1M actions into a real skill-spotter database
   (same generator as the latency tests), then time the Stop hook and measure the DB size.
2. Lookup methods: for each test turn with an earlier same-family turn in its project,
   is that turn among the top-k candidates? Recall@k and per-query latency for brute
   force, inverted index, MinHash LSH, hnswlib, FAISS and sqlite-vec, at the dataset's
   size and at 100k stored vectors.

    .venv/bin/python -m bench.scale [--turns 100000] [--skip-runtime]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import data as D

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results"


def runtime_scale(n_turns: int) -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    from test_show_and_perf import populate  # same synthetic workload as the latency tests

    from skill_spotter import paths, store

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        (repo / ".git").mkdir(parents=True)
        db = paths.db_path(Path(tmp) / "data")
        conn = store.connect(db)
        started = time.time()
        populate(conn, str(repo), n_turns=n_turns, seed=11, max_actions=19)  # ~10 actions/turn
        build_s = time.time() - started
        n_actions = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        n_patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        conn.close()
        env = {**os.environ, "SKILL_SPOTTER_DATA": str(Path(tmp) / "data")}
        samples = []
        for i in range(33):
            pid = str(uuid.uuid4())
            base = {"session_id": "scale", "cwd": str(repo), "prompt_id": pid}
            for script, payload in (
                (
                    "on_prompt.py",
                    {
                        **base,
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": f"deploy the api worker to staging {i}",
                    },
                ),
                (
                    "on_action.py",
                    {
                        **base,
                        "hook_event_name": "PostToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": "make deploy"},
                        "tool_use_id": pid,
                    },
                ),
            ):
                subprocess.run(
                    [sys.executable, "-S", str(ROOT / "hooks" / script)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=env,
                    check=True,
                )
            t0 = time.perf_counter()
            subprocess.run(
                [sys.executable, "-S", str(ROOT / "hooks" / "on_stop.py")],
                input=json.dumps({**base, "hook_event_name": "Stop", "session_crons": []}),
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            samples.append((time.perf_counter() - t0) * 1000)
        samples = samples[3:]
        return {
            "turns": n_turns,
            "actions": n_actions,
            "patterns": n_patterns,
            "db_mb": round(db.stat().st_size / 1e6, 1),
            "build_seconds": round(build_s, 1),
            "stop_p50_ms": round(statistics.median(samples), 1),
            "stop_p95_ms": round(statistics.quantiles(samples, n=20)[18], 1),
            "load_avg": round(os.getloadavg()[0]),
        }


def lookup_benchmark(k: int = 10, scale_to: int = 100_000) -> list:
    from .methods.text import BgeSmall

    test = D.load("test")
    rep = BgeSmall()
    rep.fit(test)
    X = np.asarray(rep.X, dtype=np.float32)
    # Queries: positives that have an earlier same-family turn in the same project.
    by_proj = defaultdict(list)
    queries = []
    for t in test:
        earlier = [u.idx for u in by_proj[t.project]]
        if t.kind == "positive" and any(test[u].family == t.family for u in earlier):
            queries.append(t.idx)
        by_proj[t.project].append(t)
    # Pad the index with random unit vectors to measure latency at scale.
    rng = np.random.default_rng(0)
    pad = rng.normal(size=(max(0, scale_to - len(X)), X.shape[1])).astype(np.float32)
    pad /= np.linalg.norm(pad, axis=1, keepdims=True)
    big = np.vstack([X, pad])
    results = []

    def recall_and_latency(name, search):
        hits, lat = 0, []
        for q in queries:
            t0 = time.perf_counter()
            ids = search(q)
            lat.append((time.perf_counter() - t0) * 1000)
            fam = test[q].family
            earlier = {u.idx for u in test if u.project == test[q].project and u.ts < test[q].ts}
            if any(i in earlier and test[i].family == fam for i in ids if i < len(test)):
                hits += 1
        results.append(
            {
                "method": name,
                f"recall@{k}": round(hits / len(queries), 4),
                "p50_ms": round(statistics.median(lat), 3),
                "p95_ms": round(float(np.percentile(lat, 95)), 3),
                "index_size": len(big),
                "queries": len(queries),
            }
        )
        print(results[-1])

    # brute force (exact cosine), at scale
    recall_and_latency(
        "brute_force", lambda q: [i for i in np.argsort(-(big @ X[q]))[: k + 1] if i != q][:k]
    )

    # inverted index on rare normalized words (no vectors)
    from collections import Counter

    from skill_spotter.capture import normalize_text as nt

    toks = [set(nt.normalize(t.prompt)) for t in test]
    df = Counter(w for s in toks for w in s)
    inv = defaultdict(set)
    for i, s in enumerate(toks):
        for w in s:
            if df[w] <= max(5, len(test) // 50):
                inv[w].add(i)

    def inverted(q):
        counts = Counter(i for w in toks[q] for i in inv.get(w, ()) if i != q)
        return [i for i, _ in counts.most_common(k)]

    recall_and_latency("inverted_index", inverted)

    # MinHash LSH over normalized n-grams
    from datasketch import MinHash, MinHashLSH

    lsh = MinHashLSH(threshold=0.2, num_perm=64)
    mhs = []
    for i, t in enumerate(test):
        mh = MinHash(num_perm=64)
        for g in nt.ngrams(nt.normalize(t.prompt)):
            mh.update(g.encode())
        mhs.append(mh)
        lsh.insert(str(i), mh)
    recall_and_latency(
        "minhash_lsh", lambda q: [int(x) for x in lsh.query(mhs[q]) if int(x) != q][:k]
    )

    # hnswlib
    import hnswlib

    index = hnswlib.Index(space="ip", dim=big.shape[1])
    index.init_index(max_elements=len(big), ef_construction=100, M=16)
    index.add_items(big, np.arange(len(big)))
    index.set_ef(64)
    recall_and_latency(
        "hnswlib", lambda q: [int(i) for i in index.knn_query(X[q], k=k + 1)[0][0] if i != q][:k]
    )

    # FAISS (HNSW, inner product)
    import faiss

    findex = faiss.IndexHNSWFlat(big.shape[1], 16, faiss.METRIC_INNER_PRODUCT)
    findex.add(big)
    recall_and_latency(
        "faiss_hnsw",
        lambda q: [int(i) for i in findex.search(X[q : q + 1], k + 1)[1][0] if i != q][:k],
    )

    # sqlite-vec (exact KNN inside SQLite)
    import sqlite3

    import sqlite_vec

    conn = sqlite3.connect(":memory:")
    if not hasattr(conn, "enable_load_extension"):
        results.append(
            {
                "method": "sqlite_vec",
                "error": "this Python's sqlite3 can't load extensions "
                "(python.org macOS builds); not measured",
            }
        )
        print(results[-1])
        return results
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute(f"CREATE VIRTUAL TABLE v USING vec0(e float[{big.shape[1]}])")
    conn.executemany(
        "INSERT INTO v(rowid, e) VALUES (?, ?)", [(i, big[i].tobytes()) for i in range(len(big))]
    )

    def sqlite_search(q):
        rows = conn.execute(
            "SELECT rowid FROM v WHERE e MATCH ? AND k = ? ORDER BY distance",
            (X[q].tobytes(), k + 1),
        ).fetchall()
        return [r[0] for r in rows if r[0] != q][:k]

    recall_and_latency("sqlite_vec", sqlite_search)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=100_000)
    parser.add_argument("--skip-runtime", action="store_true")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    out = {"lookup": lookup_benchmark()}
    if not args.skip_runtime:
        out["runtime"] = runtime_scale(args.turns)
        print(out["runtime"])
    (RESULTS / "scale.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
