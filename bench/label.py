"""Real held-out set (SPEC 11.5): label your own recorded turns, locally.

Your data never leaves this machine: everything is written under bench/data/real/,
which git ignores, and nothing here calls a model.

    .venv/bin/python -m bench.label export [--data-dir DIR]   # your DB -> real/turns.jsonl
    .venv/bin/python -m bench.label pairs [--n 150]           # sample pairs to label
    .venv/bin/python -m bench.label label                     # y/n/s in the terminal
    .venv/bin/python -m bench.label eval                      # methods on your labels

The final method choice must also hold here (replay precision >= 0.85, SPEC 11.8).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_spotter import paths, store  # noqa: E402

REAL = ROOT / "bench" / "data" / "real"


def export(data_dir=None):
    """Turn the runtime database into the benchmark's item format (prompts are already
    redacted; action inputs are the stored redacted summaries)."""
    base = paths.data_dir(data_dir)
    conn = store.connect(paths.db_path(base))
    REAL.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT * FROM turns WHERE finalized = 1 ORDER BY ts_start").fetchall()
    with (REAL / "turns.jsonl").open("w") as f:
        for t in rows:
            actions = []
            for a in conn.execute(
                "SELECT tool_name, input_redacted, failed, agent_id FROM actions WHERE prompt_id = ? ORDER BY ts, id",
                (t["prompt_id"],),
            ):
                inp = (
                    {"command": a["input_redacted"]}
                    if a["tool_name"] == "Bash"
                    else {"file_path": f"{t['project_key']}/{a['input_redacted']}"}
                )
                actions.append(
                    {
                        "tool": a["tool_name"],
                        "input": inp,
                        "failed": bool(a["failed"]),
                        "agent_id": a["agent_id"],
                    }
                )
            f.write(
                json.dumps(
                    {
                        "item_id": t["prompt_id"],
                        "kind": "real",
                        "label_group": None,
                        "family_id": None,
                        "project": t["project_key"].rstrip("/").split("/")[-1],
                        "session": t["session_id"],
                        "ts": datetime.fromtimestamp(t["ts_start"], timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "prompt": t["prompt_redacted"] or "",
                        "actions": actions,
                        "runtime_pattern": t["pattern_id"],
                    }
                )
                + "\n"
            )
    print(f"exported {len(rows)} turns from {base} -> {REAL / 'turns.jsonl'}")


def load_turns():
    return [json.loads(line) for line in (REAL / "turns.jsonl").read_text().splitlines()]


def sample_pairs(n=150, seed=3):
    """Half from inside runtime patterns (are they really the same task?), a quarter
    near-misses (same project, overlapping words), a quarter random same-project pairs."""
    from skill_spotter.capture import normalize_text as nt

    rng = random.Random(seed)
    turns = load_turns()
    by_pattern, by_project = {}, {}
    for i, t in enumerate(turns):
        if t.get("runtime_pattern") is not None:
            by_pattern.setdefault(t["runtime_pattern"], []).append(i)
        by_project.setdefault(t["project"], []).append(i)
    pairs = set()
    groups = [g for g in by_pattern.values() if len(g) >= 2]
    while groups and len(pairs) < n // 2:
        g = rng.choice(groups)
        a, b = rng.sample(g, 2)
        pairs.add((min(a, b), max(a, b), "same_runtime_pattern"))
    toks = [set(nt.normalize(t["prompt"])) for t in turns]
    attempts = 0
    while len(pairs) < 3 * n // 4 and attempts < 50000:
        attempts += 1
        proj = rng.choice(list(by_project))
        if len(by_project[proj]) < 2:
            continue
        a, b = rng.sample(by_project[proj], 2)
        if toks[a] & toks[b] and turns[a].get("runtime_pattern") != turns[b].get("runtime_pattern"):
            pairs.add((min(a, b), max(a, b), "near_miss"))
    while len(pairs) < n and attempts < 100000:
        attempts += 1
        proj = rng.choice(list(by_project))
        if len(by_project[proj]) >= 2:
            a, b = rng.sample(by_project[proj], 2)
            pairs.add((min(a, b), max(a, b), "random"))
    with (REAL / "pairs.jsonl").open("w") as f:
        for a, b, kind in sorted(pairs):
            f.write(
                json.dumps({"a": turns[a]["item_id"], "b": turns[b]["item_id"], "kind": kind})
                + "\n"
            )
    print(f"{len(pairs)} pairs -> {REAL / 'pairs.jsonl'}")


def label():
    turns = {t["item_id"]: t for t in load_turns()}
    pairs = [json.loads(line) for line in (REAL / "pairs.jsonl").read_text().splitlines()]
    out = REAL / "labels.jsonl"
    done = (
        {(d["a"], d["b"]) for d in map(json.loads, out.read_text().splitlines())}
        if out.exists()
        else set()
    )
    with out.open("a") as f:
        for k, p in enumerate(pairs):
            if (p["a"], p["b"]) in done:
                continue
            for side in ("a", "b"):
                t = turns[p[side]]
                cmds = "; ".join(
                    (x["input"].get("command") or x["input"].get("file_path", "").split("/")[-1])[
                        :50
                    ]
                    for x in t["actions"][:5]
                )
                print(f"\n[{side.upper()}] {t['prompt'][:300]}\n    actions: {cmds}")
            answer = (
                input(f"\n({k + 1}/{len(pairs)}) same task? [y]es / [n]o / [s]kip / [q]uit: ")
                .strip()
                .lower()
            )
            if answer == "q":
                break
            if answer in ("y", "n"):
                f.write(json.dumps({**p, "same": answer == "y"}) + "\n")
                f.flush()


def evaluate():
    """Pairwise quality of the runtime matcher on your labels, and how often runtime
    patterns you saw were judged the same task (a proxy for suggestion precision)."""
    sys.path.insert(0, str(ROOT))
    from bench import data as D
    from bench.methods.actions import HierIdfJaccard
    from bench.methods.templating import HandRules
    from bench.methods.text import WordJaccard
    from skill_spotter.match import baseline

    labels = [json.loads(line) for line in (REAL / "labels.jsonl").read_text().splitlines()]
    turns = D.load(path=REAL / "turns.jsonl")
    by_id = {t.item_id: t for t in turns}
    for t, raw in zip(turns, load_turns()):
        t.cache["runtime_pattern"] = raw.get("runtime_pattern")
    text, act = WordJaccard(), HierIdfJaccard(HandRules())
    act.fit(turns)
    tp = fp = fn = tn = 0
    same_pattern_pairs = same_pattern_correct = 0
    for lab in labels:
        a, b = by_id[lab["a"]], by_id[lab["b"]]
        pred = baseline.same_task(act.score(a, b), text.score(a, b), 2)
        tp += pred and lab["same"]
        fp += pred and not lab["same"]
        fn += (not pred) and lab["same"]
        tn += (not pred) and not lab["same"]
        if (
            a.cache["runtime_pattern"] is not None
            and a.cache["runtime_pattern"] == b.cache["runtime_pattern"]
        ):
            same_pattern_pairs += 1
            same_pattern_correct += lab["same"]
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    result = {
        "labelled_pairs": len(labels),
        "pairwise_precision": p,
        "pairwise_recall": r,
        "runtime_pattern_purity": same_pattern_correct / same_pattern_pairs
        if same_pattern_pairs
        else None,
    }
    (REAL / "eval.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "pairs", "label", "eval"])
    parser.add_argument("--data-dir")
    parser.add_argument("--n", type=int, default=150)
    args = parser.parse_args()
    {
        "export": lambda: export(args.data_dir),
        "pairs": lambda: sample_pairs(args.n),
        "label": label,
        "eval": evaluate,
    }[args.command]()


if __name__ == "__main__":
    main()
