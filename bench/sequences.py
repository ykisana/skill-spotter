"""Multi-turn workflow mining benchmark (SPEC 11.2 sequences row; M5).

Synthetic sessions are built from dev families: 15 planted workflows of 2–4 distinct
tasks, each repeated in 3–6 sessions with optional noise turns between steps, plus
sessions of unrelated turns. A session is the sequence of task ids, as the runtime sees
it after pattern assignment (so this isolates the mining step).

Candidates: contiguous n-grams, n-grams allowing 1 gap (the runtime), PrefixSpan and
SPADE (both allowing arbitrary gaps). A planted workflow counts as found if a reported
frequent sequence (support >= 3 sessions, length 2–4) equals it; everything else reported
that isn't a sub-sequence of a planted workflow is a false workflow.

    .venv/bin/python -m bench.sequences
"""

from __future__ import annotations

import json
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from skill_spotter import workflows

RESULTS = Path(__file__).resolve().parent / "results"
MIN_SUPPORT, MAX_LEN = 3, 4


def make_sessions(seed=4, n_workflows=15, n_tasks=120, noise_sessions=120):
    rng = random.Random(seed)
    tasks = list(range(n_tasks))
    planted = []
    for _ in range(n_workflows):
        planted.append(tuple(rng.sample(tasks, rng.choice([2, 3, 3, 4]))))
    sessions = []
    for flow in planted:
        for _ in range(rng.randint(3, 6)):
            seq = [rng.choice(tasks) for _ in range(rng.randint(0, 2))]
            for step in flow:
                seq.append(step)
                if rng.random() < 0.2:  # an unrelated turn in the middle
                    seq.append(rng.choice(tasks))
            seq += [rng.choice(tasks) for _ in range(rng.randint(0, 2))]
            sessions.append(seq)
    for _ in range(noise_sessions):
        sessions.append([rng.choice(tasks) for _ in range(rng.randint(1, 6))])
    rng.shuffle(sessions)
    return planted, sessions


def ngrams(sessions, max_gap: int) -> Dict[Tuple[int, ...], int]:
    """Session support of sequences found the way the runtime finds them: every prefix of
    the session, candidates ending at its last step."""
    support: Dict[Tuple[int, ...], Set[int]] = defaultdict(set)
    for s_idx, seq in enumerate(sessions):
        collapsed = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]
        for end in range(1, len(collapsed)):
            for cand in workflows.candidates_ending_here(collapsed[: end + 1], max_gap=max_gap):
                support[cand].add(s_idx)
    return {k: len(v) for k, v in support.items()}


def is_subsequence(small, big) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def prefixspan(sessions) -> Dict[Tuple[int, ...], int]:
    """PrefixSpan (Pei et al. 2001) over sequences of single items, gaps allowed."""
    out: Dict[Tuple[int, ...], int] = {}

    def project(db, item):
        projected = []
        for sid, seq in db:
            try:
                i = seq.index(item)
            except ValueError:
                continue
            projected.append((sid, seq[i + 1 :]))
        return projected

    def grow(prefix, db):
        counts: Dict[int, Set[int]] = defaultdict(set)
        for sid, seq in db:
            for item in set(seq):
                counts[item].add(sid)
        for item, sids in counts.items():
            if len(sids) < MIN_SUPPORT or item in prefix:
                continue
            new = prefix + (item,)
            if len(new) >= 2:
                out[new] = len(sids)
            if len(new) < MAX_LEN:
                grow(new, project(db, item))

    grow((), list(enumerate(sessions)))
    return out


def spade(sessions) -> Dict[Tuple[int, ...], int]:
    """SPADE (Zaki 2001): vertical id-lists (sid, position), joined to grow sequences."""
    idlists: Dict[Tuple[int, ...], Dict[int, List[int]]] = defaultdict(lambda: defaultdict(list))
    for sid, seq in enumerate(sessions):
        for pos, item in enumerate(seq):
            idlists[(item,)][sid].append(pos)
    frequent = {k: v for k, v in idlists.items() if len(v) >= MIN_SUPPORT}
    out: Dict[Tuple[int, ...], int] = {}
    level = frequent
    singles = list(frequent)
    while level:
        nxt = {}
        for seq, ids in level.items():
            if len(seq) >= MAX_LEN:
                continue
            for (item,) in singles:
                if item in seq:
                    continue
                joined = {}
                for sid, positions in ids.items():
                    later = [p for p in frequent[(item,)].get(sid, []) if p > min(positions)]
                    if later:
                        joined[sid] = later
                if len(joined) >= MIN_SUPPORT:
                    new = seq + (item,)
                    nxt[new] = joined
                    out[new] = len(joined)
        level = nxt
    return out


def evaluate(name, support: Dict[Tuple[int, ...], int], planted, seconds):
    frequent = {k for k, v in support.items() if v >= MIN_SUPPORT and 2 <= len(k) <= MAX_LEN}
    found = [p for p in planted if p in frequent]
    false = [k for k in frequent if not any(is_subsequence(k, p) for p in planted)]
    return {
        "method": name,
        "planted": len(planted),
        "found": len(found),
        "recall": round(len(found) / len(planted), 3),
        "false_workflows": len(false),
        "reported": len(frequent),
        "seconds": round(seconds, 3),
    }


def main():
    planted, sessions = make_sessions()
    results = []
    for name, fn in (
        ("ngram_contiguous", lambda s: ngrams(s, 0)),
        ("ngram_gap1 (runtime)", lambda s: ngrams(s, 1)),
        ("prefixspan", prefixspan),
        ("spade", spade),
    ):
        t0 = time.perf_counter()
        support = fn(sessions)
        results.append(evaluate(name, support, planted, time.perf_counter() - t0))
        print(results[-1])
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "sequences.json").write_text(
        json.dumps(
            {"sessions": len(sessions), "planted": [list(p) for p in planted], "results": results},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
