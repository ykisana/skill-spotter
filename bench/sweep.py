"""Sweep the online matcher's parameters with the real-hook replay (SPEC 5.3: "M3 tunes them").

Each config is written to a temp file and passed via SKILL_SPOTTER_METHOD_CONFIG, so the
replay runs the shipped code unchanged. Tune on dev, confirm the winner on test.

    .venv/bin/python -m bench.sweep [--jobs 4]
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

GRID = {
    "action_weighting": ["idf", "none"],
    "action_strong": [0.55, 0.6, 0.65, 0.7],
    "action_weak": [0.4, 0.5],
    "text_gate": [0.05, 0.08, 0.12],
}


def run_one(args):
    split, params = args
    from bench import data as D
    from bench.replay import replay_runtime

    config = {
        "fusion": "rule",
        "text": "word_jaccard",
        "actions": "hier_idf_jaccard[hand]",
        "action_weighting": params["action_weighting"],
        "rule_params": {k: v for k, v in params.items() if k != "action_weighting"},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(config, f)
    os.environ["SKILL_SPOTTER_METHOD_CONFIG"] = f.name
    try:
        metrics = replay_runtime(D.load(split))["metrics"]
    finally:
        os.unlink(f.name)
    return {"split": split, "params": params, **metrics}


def rank_key(r):
    """SPEC 11.8 on dev: precision >= 0.90 first, then recall, then fewer split tasks."""
    return (
        (r["precision"] or 0) >= 0.9,
        r["recall"] or 0,
        -(r.get("extra_patterns_per_family") or 0),
        r["precision"] or 0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    keys = list(GRID)
    combos = [dict(zip(keys, values)) for values in itertools.product(*GRID.values())]
    with ProcessPoolExecutor(args.jobs) as pool:
        dev = list(pool.map(run_one, [("dev", c) for c in combos]))
    dev.sort(key=rank_key, reverse=True)
    best = dev[0]
    test = run_one(("test", best["params"]))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "sweep.json").write_text(
        json.dumps({"dev": dev, "best": best, "test_of_best": test}, indent=1)
    )
    for r in dev[:8]:
        print(
            json.dumps(
                {
                    k: r[k]
                    for k in (
                        "params",
                        "precision",
                        "recall",
                        "extra_patterns_per_family",
                        "false_per_100_turns",
                    )
                }
            )
        )
    print(
        "TEST of best:",
        json.dumps(
            {
                k: test[k]
                for k in (
                    "precision",
                    "recall",
                    "extra_patterns_per_family",
                    "resuggested_after_snooze",
                    "median_occurrences_before_first",
                    "false_per_100_turns",
                )
            }
        ),
    )


if __name__ == "__main__":
    main()
