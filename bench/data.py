"""Load the synthetic dataset and build evaluation pairs."""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "bench" / "data"
SYNTH = DATA / "synthetic" / "v1"


@dataclass
class Turn:
    idx: int
    item_id: str
    kind: str  # positive | hard_negative | one_off
    label: str  # label_group: same label = same task
    family: Optional[str]
    related_to: Optional[str]
    difficulty: Optional[str]
    project: str
    session: str
    ts: float
    prompt: str
    actions: List[Dict[str, Any]]
    cache: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def root(self) -> str:
        return f"/work/{self.project}"


def load(split: str = "dev", path: Optional[Path] = None) -> List[Turn]:
    path = path or SYNTH / f"{split}.jsonl"
    turns = []
    with open(path) as f:
        for i, line in enumerate(f):
            d = json.loads(line)
            ts = datetime.fromisoformat(d["ts"].replace("Z", "+00:00")).timestamp()
            turns.append(
                Turn(
                    idx=len(turns),
                    item_id=d["item_id"],
                    kind=d["kind"],
                    label=d["label_group"],
                    family=d.get("family_id"),
                    related_to=d.get("related_to"),
                    difficulty=d.get("difficulty"),
                    project=d["project"],
                    session=d["session"],
                    ts=ts,
                    prompt=d["prompt"],
                    actions=d["actions"],
                )
            )
    return turns


Pair = Tuple[int, int, int, str]  # (i, j, same_task, pair_type)


def make_pairs(
    turns: List[Turn], seed: int = 7, random_negatives_per_positive: float = 2.0
) -> List[Pair]:
    """Positive pairs within families; hard negatives vs their family; random negatives."""
    rng = random.Random(seed)
    by_family: Dict[str, List[int]] = {}
    for t in turns:
        if t.kind == "positive":
            by_family.setdefault(t.family, []).append(t.idx)
    pairs: List[Pair] = []
    for members in by_family.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                pairs.append((members[a], members[b], 1, "positive"))
    for t in turns:
        if t.kind == "hard_negative" and t.related_to in by_family:
            for j in by_family[t.related_to]:
                pairs.append((t.idx, j, 0, f"hard_{t.difficulty or 'different'}"))
    n_pos = sum(1 for p in pairs if p[2] == 1)
    # Different tasks that share a meaningful command (two unrelated "psql -c ..." questions):
    # the case that fooled action-heavy matchers once one-offs were in the data.
    from skill_spotter.capture.normalize_actions import normalize_action, turn_fingerprint

    by_token: Dict[Tuple[str, str], List[int]] = {}
    for t in turns:
        fp = turn_fingerprint(
            [
                normalize_action(
                    a["tool"], a.get("input") or {}, t.root, failed=bool(a.get("failed"))
                )
                for a in t.actions
            ]
        )
        for tok, w in fp.items():
            if w >= 0.5 and not tok.startswith("seq:"):
                by_token.setdefault((t.project, tok), []).append(t.idx)
    buckets = [v for v in by_token.values() if len(v) >= 2]
    seen_shared = set()
    want_shared = n_pos
    tries = 0
    while want_shared > 0 and buckets and tries < n_pos * 50:
        tries += 1
        bucket = rng.choice(buckets)
        i, j = rng.sample(bucket, 2)
        key = (min(i, j), max(i, j))
        if turns[i].label == turns[j].label or key in seen_shared:
            continue
        seen_shared.add(key)
        pairs.append((key[0], key[1], 0, "shared_command"))
        want_shared -= 1
    positives = [t.idx for t in turns if t.kind == "positive"]
    by_project: Dict[str, List[int]] = {}
    for t in turns:
        by_project.setdefault(t.project, []).append(t.idx)
    want = int(n_pos * random_negatives_per_positive)
    seen = set()
    while want > 0 and positives:
        i = rng.choice(positives)
        j = rng.choice(by_project[turns[i].project])  # same project: harder than any random pair
        if i == j or turns[i].label == turns[j].label or (min(i, j), max(i, j)) in seen:
            continue
        seen.add((min(i, j), max(i, j)))
        kind = "oneoff" if turns[j].kind == "one_off" else "other_task"
        pairs.append((i, j, 0, f"random_{kind}"))
        want -= 1
    return pairs


def difficulty_of(pair: Pair, turns: List[Turn]) -> str:
    i, j, same, kind = pair
    if not same:
        return kind
    tiers = sorted({turns[i].difficulty or "light", turns[j].difficulty or "light"})
    order = ["typo", "terse", "heavy", "param", "light"]
    return min(tiers, key=lambda t: order.index(t) if t in order else 99)
