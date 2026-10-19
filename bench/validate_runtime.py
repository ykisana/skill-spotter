"""M4 done criterion: the shipped runtime reproduces the Method Lab's numbers.

Replays dev and test through the real hooks with config/method.json and compares
precision and recall with the lab's simulation of the selected method (tolerance 0.05).
Writes bench/results/runtime_chosen.json; exits 1 if outside tolerance.

    .venv/bin/python -m bench.validate_runtime
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import data as D
from .replay import replay_runtime

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 0.05


def main() -> int:
    config = json.loads((ROOT / "config" / "method.json").read_text())
    rows = [
        json.loads(line)
        for line in (ROOT / "bench" / "results" / "results.jsonl").read_text().splitlines()
    ]
    sim = {
        r["split"]: r
        for r in rows
        if r.get("stage") == "replay"
        and r.get("track") == "stdlib"
        and r.get("method", "").startswith(f"sim:{config['fusion']}")
    }
    out, ok = (
        {
            "config": {
                k: config.get(k) for k in ("fusion", "text", "actions", "theta", "method_version")
            }
        },
        True,
    )
    for split in ("dev", "test"):
        m = replay_runtime(D.load(split))["metrics"]
        lab = sim.get(split, {})
        diff = {k: round((m.get(k) or 0) - (lab.get(k) or 0), 4) for k in ("precision", "recall")}
        within = all(abs(v) <= TOLERANCE for v in diff.values()) if lab else None
        ok = ok and within is not False
        out[split] = {
            "runtime": m,
            "lab": {k: lab.get(k) for k in ("precision", "recall", "theta")},
            "difference": diff,
            "within_tolerance": within,
        }
        print(
            split,
            json.dumps(out[split]["difference"]),
            "within" if within else "OUTSIDE",
            "tolerance",
        )
    (ROOT / "bench" / "results" / "runtime_chosen.json").write_text(json.dumps(out, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
