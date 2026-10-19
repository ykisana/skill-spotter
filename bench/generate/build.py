"""Steps 5–8 of SPEC 11.4: expand traces, lay out a timeline, split by family, write JSONL.

Inputs: bench/data/families.json (catalog.py) and bench/data/oneoffs.json (oneoffs.py).
Output: bench/data/synthetic/v1/{dev,test}.jsonl, one item per turn (SPEC 11.4 schema),
sorted by time. Deterministic for a given seed.

Run:  .venv/bin/python -m bench.generate.build [--seed 2026]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import traces

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "synthetic" / "v1"
START = datetime(2026, 8, 3, tzinfo=timezone.utc)
DAYS = 75
TEST_SHARE = 0.4

PROJECTS = {
    "node-web": ["acme-web", "shop-frontend"],
    "python-service": ["billing-api", "ml-pipeline"],
    "go-cli": ["fleetctl"],
    "ios-app": ["acme-ios"],
    "android-app": ["acme-android"],
    "infra-repo": ["platform-infra"],
    "data-notebooks": ["analytics"],
    "monorepo": ["core-monorepo"],
}
# How spread out a family's repeats are (days): frequent weekly tasks to rare monthly ones.
SPANS = [12, 20, 30, 45, 70]


def stable_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def split_of(key: str) -> str:
    return "test" if stable_hash(key) % 1000 < TEST_SHARE * 1000 else "dev"


class Timeline:
    """Sessions per project and day; occurrences get placed into sessions."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.sessions: Dict[tuple, List[dict]] = {}
        self.counter = 0

    def session_for(self, project: str, day: int) -> dict:
        key = (project, day)
        existing = self.sessions.setdefault(key, [])
        if existing and self.rng.random() < 0.65:
            return self.rng.choice(existing)
        self.counter += 1
        start = START + timedelta(
            days=day, hours=self.rng.randint(8, 18), minutes=self.rng.randint(0, 59)
        )
        session = {"id": f"s{self.counter:04d}", "start": start, "used": 0}
        existing.append(session)
        return session

    def place(self, project: str, day: int) -> tuple:
        day = max(0, min(DAYS - 1, day))
        session = self.session_for(project, day)
        session["used"] += 1
        ts = session["start"] + timedelta(minutes=session["used"] * self.rng.randint(4, 25))
        return session["id"], ts


def project_for(project_type: str, key: str) -> str:
    options = PROJECTS.get(project_type) or PROJECTS["monorepo"]
    return options[stable_hash(key) % len(options)]


def build(seed: int = 2026) -> Dict[str, List[Dict[str, Any]]]:
    rng = random.Random(seed)
    families = json.loads((DATA / "families.json").read_text())
    oneoffs = json.loads((DATA / "oneoffs.json").read_text())
    timeline = Timeline(rng)
    items: List[Dict[str, Any]] = []

    for fam in families:
        fid = fam["family_id"]
        split = split_of(fid)
        project = project_for(fam.get("project_type", "monorepo"), fid)
        root = f"/work/{project}"
        params = fam.get("params") or {}
        positives = [p for p in fam.get("positives", []) if isinstance(p, dict) and p.get("prompt")]
        span = rng.choice(SPANS)
        first_day = rng.randint(0, max(0, DAYS - span - 1))
        days = sorted(first_day + rng.randint(0, span) for _ in positives)
        for i, (pos, day) in enumerate(zip(positives, days)):
            values = traces.choose_values(params, rng)
            session, ts = timeline.place(project, day)
            items.append(
                {
                    "family_id": fid,
                    "split": split,
                    "item_id": f"{fid}-v{i + 1:02d}",
                    "kind": "positive",
                    "label_group": fid,
                    "difficulty": pos.get("difficulty", "light"),
                    "related_to": None,
                    "category": fam.get("category"),
                    "project": project,
                    "session": session,
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "prompt": traces.fill_prompt(pos["prompt"], dict(values), rng),
                    "actions": traces.expand(
                        fam.get("trace", []), params, root, rng, values=values, src=fid
                    ),
                }
            )
        for j, neg in enumerate(fam.get("hard_negatives", [])):
            if not isinstance(neg, dict) or not neg.get("prompt"):
                continue
            values = traces.choose_values(params, rng)
            session, ts = timeline.place(
                project, rng.randint(first_day, min(DAYS - 1, first_day + span))
            )
            items.append(
                {
                    "family_id": fid,
                    "split": split,
                    "item_id": f"{fid}-n{j + 1}",
                    "kind": "hard_negative",
                    "label_group": f"{fid}-n{j + 1}",
                    "difficulty": neg.get("relation", "different"),
                    "related_to": fid,
                    "category": fam.get("category"),
                    "project": project,
                    "session": session,
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "prompt": traces.fill_prompt(neg["prompt"], dict(values), rng),
                    "actions": traces.expand(
                        neg.get("trace", []) or fam.get("trace", [])[:2],
                        params,
                        root,
                        rng,
                        values=values,
                        src=f"{fid}-n{j + 1}",
                    ),
                }
            )

    for k, one in enumerate(oneoffs):
        if not isinstance(one, dict) or not one.get("prompt"):
            continue
        oid = f"o{k + 1:05d}"
        project = project_for(one.get("project_type", "monorepo"), oid)
        session, ts = timeline.place(project, rng.randint(0, DAYS - 1))
        items.append(
            {
                "family_id": None,
                "split": split_of(oid),
                "item_id": oid,
                "kind": "one_off",
                "label_group": oid,
                "difficulty": None,
                "related_to": None,
                "category": one.get("category"),
                "project": project,
                "session": session,
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "prompt": one["prompt"],
                "actions": traces.expand(
                    one.get("trace", []), {}, f"/work/{project}", rng, src=oid
                ),
            }
        )

    items.sort(key=lambda it: (it["ts"], it["item_id"]))
    return {
        "dev": [it for it in items if it["split"] == "dev"],
        "test": [it for it in items if it["split"] == "test"],
    }


def write(splits: Dict[str, List[Dict[str, Any]]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with (OUT / f"{name}.jsonl").open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    splits = build(args.seed)
    write(splits)
    for name, rows in splits.items():
        kinds = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        print(name, len(rows), kinds)


if __name__ == "__main__":
    main()
