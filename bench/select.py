"""Apply the selection rule (SPEC 11.8) to the latest lab run; write the chosen configs.

1. Hard constraints: zero runtime tokens; the online tier is stdlib-only and within
   latency budgets; heavy dependencies only in the background tier.
2. Primary: replay suggestion precision >= 0.90 on synthetic test (and >= 0.85 on the
   real held-out set, pending until the owner labels it).
3. Then maximise replay recall, then pairwise F1.
4. Prefer simpler: a cheaper method within 2 F1 points of the best wins.
5. Two configs: best stdlib-only (config/method.json), best with extras
   (config/method.extras.json).

    .venv/bin/python -m bench.select
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results" / "results.jsonl"
CONFIG = ROOT / "config"

# Relative cost, used for the "prefer simpler" rule (lower is simpler/cheaper).
COST = {
    "rule": 0,
    "linear": 1,
    "logreg": 2,
    "gbt": 4,
    "runtime<baseline>": 0,
}


def latest_run():
    rows = [json.loads(line) for line in RESULTS.read_text().splitlines()]
    last = rows[-1]["run"]
    return [r for r in rows if r.get("run") == last]


def choose(rows, track):
    replays = [
        r
        for r in rows
        if r.get("stage") == "replay" and r.get("track") == track and r.get("split") == "test"
    ]
    if track == "stdlib":
        replays += [
            r
            for r in rows
            if r.get("stage") == "replay"
            and r.get("method") == "runtime<baseline>"
            and r.get("split") == "test"
        ]
    fusion = {r["method"]: r for r in rows if r.get("stage") == "fusion"}
    passing = [r for r in replays if (r.get("precision") or 0) >= 0.90] or replays
    passing.sort(key=lambda r: (-(r.get("recall") or 0), -(r.get("precision") or 0)))
    best = passing[0]
    # prefer simpler: among those with recall within 0.02 of the best, pick the cheapest
    near = [r for r in passing if (best.get("recall") or 0) - (r.get("recall") or 0) <= 0.02]

    def cost(r):
        m = r["method"]
        if m.startswith("runtime"):
            return 0
        fname = m.split(":")[1].split("+")[0]
        return COST.get(fname, 5) + (3 if m.startswith("batch") else 0)

    pick = min(near, key=cost)
    return pick, fusion


def main():
    rows = latest_run()
    inputs = next(r for r in rows if r.get("stage") == "selection_inputs")
    CONFIG.mkdir(exist_ok=True)
    out = {}
    for track, filename in (("stdlib", "method.json"), ("extras", "method.extras.json")):
        pick, fusion = choose(rows, track)
        method = pick["method"]
        if method.startswith("runtime"):
            config = {
                "fusion": "rule",
                "text": "word_jaccard",
                "actions": "hier_idf_jaccard[hand]",
                "clusterer": "leader",
                "lookup": "inverted_index",
            }
        else:
            fname = method.split(":")[1].split("+")[0]
            config = {
                "fusion": fname,
                "text": inputs["text"][track],
                "actions": inputs["actions"][track],
                "clusterer": method.split("+")[-1].split("<")[0]
                if method.startswith("batch")
                else "leader",
                "theta": pick.get("theta"),
            }
            fusion_row = fusion.get(f"{fname}<{track}>", {})
            if "export" in fusion_row:
                config["logreg"] = fusion_row["export"]
        config.update(
            {
                "track": track,
                "method_version": f"{track}-{pick['run'][:10]}",
                "evidence": {
                    k: pick.get(k)
                    for k in (
                        "precision",
                        "recall",
                        "median_occurrences_before_first",
                        "false_per_100_turns",
                        "duplicate_suggestions",
                    )
                },
                "selected_from_run": pick["run"],
                "real_holdout": "pending: run bench.label export/pairs/label/eval (SPEC 11.5)",
            }
        )
        (CONFIG / filename).write_text(json.dumps(config, indent=2) + "\n")
        out[track] = config
        print(track, json.dumps(config, indent=1))
    return out


if __name__ == "__main__":
    main()
