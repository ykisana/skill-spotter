"""Step 7 of SPEC 11.4: quality control, then write the dataset card.

1. schema validation (drop malformed items)
2. exact and near-duplicate removal (normalized prompt)
3. AI label audit on a ~10% sample of families (second pass, different model)
4. a 50-item human spot-check sheet (bench/data/spotcheck.md) for the owner to fill in
5. bench/data/dataset_card.md

Run after build:  .venv/bin/python -m bench.generate.qc
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_spotter.capture import normalize_text as nt  # noqa: E402

from . import llm  # noqa: E402

DATA = ROOT / "bench" / "data"
OUT = DATA / "synthetic" / "v1"
REQUIRED = {"item_id", "kind", "label_group", "project", "session", "ts", "prompt", "actions"}

AUDIT = """You are auditing labels in a benchmark about recognising repeated developer tasks.
Each item below says which task FAMILY it claims to belong to (positive) or which family it \
merely looks like (hard_negative = a DIFFERENT task that only shares words/commands).

For each item answer whether the label is right: a positive must be the same task as the \
family intent (paraphrase or different parameters is fine); a hard_negative must be a \
genuinely different task from the family intent.

Items:
{items}

Reply with ONLY JSON: {{"verdicts": [{{"item_id": "...", "label_ok": true|false, "note": "..."}}]}}"""


def validate(rows):
    good, bad = [], 0
    for r in rows:
        if not set(r) >= REQUIRED or not isinstance(r["prompt"], str) or not r["prompt"].strip():
            bad += 1
            continue
        if not isinstance(r["actions"], list):
            bad += 1
            continue
        good.append(r)
    return good, bad


def dedupe(rows):
    """Exact duplicates of a normalized prompt within the split; one-offs that nearly
    duplicate a family positive (they'd be mislabelled as different tasks)."""
    seen, out, dropped = set(), [], Counter()
    positives = [set(nt.ngrams(nt.normalize(r["prompt"]))) for r in rows if r["kind"] == "positive"]
    for r in rows:
        key = (r["kind"], r.get("family_id"), " ".join(nt.normalize(r["prompt"])))
        if key in seen:
            dropped["exact"] += 1
            continue
        if r["kind"] == "one_off":
            grams = set(nt.ngrams(nt.normalize(r["prompt"])))
            if grams and any(len(grams & p) / len(grams | p) >= 0.8 for p in positives):
                dropped["near_duplicate_of_positive"] += 1
                continue
        seen.add(key)
        out.append(r)
    return out, dropped


def audit(families, splits, share=0.1, seed=11):
    rng = random.Random(seed)
    fams = rng.sample(families, max(1, int(len(families) * share)))
    intents = {f["family_id"]: f["intent"] for f in fams}
    items = [
        r
        for rows in splits.values()
        for r in rows
        if r.get("family_id") in intents and r["kind"] in ("positive", "hard_negative")
    ]
    verdicts = []
    for start in range(0, len(items), 40):
        chunk = items[start : start + 40]
        text = "\n".join(
            f'- item_id={r["item_id"]} label={r["kind"]} family_intent="{intents[r["family_id"]]}" prompt="{r["prompt"]}"'
            for r in chunk
        )
        try:
            verdicts += llm.call(
                AUDIT.format(items=text), model="haiku", label=f"audit:{start}"
            ).get("verdicts", [])
        except Exception as exc:  # noqa: BLE001
            print(f"audit chunk {start} failed: {exc}")
    ok = sum(1 for v in verdicts if v.get("label_ok"))
    flagged = [v for v in verdicts if not v.get("label_ok")]
    return {
        "families_sampled": len(fams),
        "items_audited": len(verdicts),
        "agreement": round(ok / len(verdicts), 4) if verdicts else None,
        "flagged": flagged,
    }


def spotcheck(splits, n=50, seed=5):
    rng = random.Random(seed)
    rows = [r for rows in splits.values() for r in rows]
    sample = rng.sample(rows, min(n, len(rows)))
    lines = [
        "# Human spot-check (50 items)",
        "",
        "Mark each item: is the label right, and do the actions look like what Claude would do?",
        "Fill in the last two columns (ok / wrong) and commit.",
        "",
        "| item | kind | family/label | prompt | first actions | label ok? | actions ok? |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sample:
        acts = "; ".join(
            (
                a["input"].get("command")
                or a["input"].get("file_path", "").split("/")[-1]
                or a["tool"]
            )[:40]
            for a in r["actions"][:3]
        ).replace("|", "\\|")
        prompt = r["prompt"].replace("|", "\\|")[:120]
        lines.append(
            f"| {r['item_id']} | {r['kind']} | {r['label_group']} | {prompt} | {acts} |  |  |"
        )
    (DATA / "spotcheck.md").write_text("\n".join(lines) + "\n")


def card(splits, families, dropped, invalid, audit_result):
    def counts(rows, key):
        return dict(sorted(Counter(r.get(key) for r in rows).items(), key=lambda x: str(x[0])))

    calls = (
        [json.loads(line) for line in (DATA / "raw" / "calls.jsonl").read_text().splitlines()]
        if (DATA / "raw" / "calls.jsonl").exists()
        else []
    )
    cost = sum(c.get("cost_usd") or 0 for c in calls)
    lines = [
        "# Dataset card: skill-spotter synthetic v1",
        "",
        "Synthetic, AI-generated benchmark for deciding whether two Claude Code turns are the same task.",
        "No real user data. Generated at development time with `claude -p` (SPEC 11.4); raw replies are",
        "cached in `bench/data/raw/` (keyed by sha256 of model + prompt), so `bench.generate.build` rebuilds",
        "the same dataset without new calls.",
        "",
        "## Sources",
        "",
        f"- **Families** (`catalog.py`, Sonnet): {len(families)} task families in 14 categories, each with an intent,",
        "  parameters, an action-trace template, 10 prompt variants (2 light, 3 heavy, 2 terse, 1 typo, 2 param)",
        "  and 4 hard negatives (lookalike but different tasks, with their own traces).",
        "- **One-offs** (`oneoffs.py`, Haiku): single-occurrence requests per category and project type.",
        "- **Action traces** are expanded by code (`traces.py`) with perturbations: parameter values, skipped",
        "  optional steps, reordered independent steps, exploration noise (git status, ls, reads), failed-and-",
        "  retried commands (15%), subagent actions (15%).",
        "- **Timeline** (`build.py`, seed 2026): 11 projects, 75 days from 2026-08-03, sessions per project and day;",
        "  each family's repeats spread over 12-70 days, so some are frequent and some rarely repeat within 30 days.",
        f"- **Generation calls:** {len(calls)} (budget 300), about ${cost:.2f}.",
        "",
        "## Counts",
        "",
        "| split | turns | positive | hard_negative | one_off |",
        "|---|---|---|---|---|",
    ]
    for name, rows in splits.items():
        c = Counter(r["kind"] for r in rows)
        lines.append(
            f"| {name} | {len(rows)} | {c['positive']} | {c['hard_negative']} | {c['one_off']} |"
        )
    lines += [
        "",
        "Families are split by family (60% dev / 40% test): no family appears in both.",
        "",
        "### Difficulty tiers (positives, both splits)",
        "",
        "```",
        json.dumps(
            counts(
                [r for rows in splits.values() for r in rows if r["kind"] == "positive"],
                "difficulty",
            )
        ),
        "```",
        "",
        "### Categories (all items)",
        "",
        "```",
        json.dumps(counts([r for rows in splits.values() for r in rows], "category")),
        "```",
        "",
        "## Quality control",
        "",
        f"- Schema validation dropped {invalid} items.",
        f"- Duplicates dropped: {dict(dropped)}.",
        f"- AI label audit (Haiku, second pass) on {audit_result['families_sampled']} sampled families,",
        f"  {audit_result['items_audited']} items: agreement {audit_result['agreement']}. Flagged items are listed in",
        "  `bench/data/audit.json`.",
        "- Human spot-check: **pending.** 50 random items are in `bench/data/spotcheck.md` for the owner to mark.",
        "",
        "## Known gaps",
        "",
        "- Prompts are written by models, so they're cleaner and more uniform than real ones; typos are mild.",
        "- Traces come from templates: real sessions have more exploration, longer retries and more variety in",
        "  commands. Matching quality on real data can be lower or higher; the real held-out set (SPEC 11.5)",
        "  decides.",
        "- Terse prompts under 4 words are filtered by the runtime on purpose, which lowers replay recall.",
        "- Multi-turn workflows (a task split over several prompts) are not in v1; M5 adds them.",
        "- English only.",
    ]
    (DATA / "dataset_card.md").write_text("\n".join(lines) + "\n")


def main():
    families = json.loads((DATA / "families.json").read_text())
    splits, dropped, invalid = {}, Counter(), 0
    for name in ("dev", "test"):
        rows = [json.loads(line) for line in (OUT / f"{name}.jsonl").read_text().splitlines()]
        rows, bad = validate(rows)
        rows, d = dedupe(rows)
        invalid += bad
        dropped.update(d)
        splits[name] = rows
        with (OUT / f"{name}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    result = audit(families, splits)
    (DATA / "audit.json").write_text(json.dumps(result, indent=1))
    spotcheck(splits)
    card(splits, families, dropped, invalid, result)
    print(
        json.dumps({k: v for k, v in result.items() if k != "flagged"}),
        dict(dropped),
        "invalid",
        invalid,
    )


if __name__ == "__main__":
    main()
