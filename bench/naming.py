"""Naming benchmark (SPEC 11.2, naming row).

For each test family: the runtime heuristic name (built from the family's prompts and
actions exactly as the runtime would see them) vs a reference name proposed by Claude.
A Claude judge then rates both, blind and in random order, from 1 (misleading) to 5
(exactly what I'd type). A small local LLM (Ollama/llama.cpp) is not evaluated: neither
is installed and the machine is short on disk.

    .venv/bin/python -m bench.naming
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from skill_spotter import naming
from skill_spotter.capture import normalize_text as nt
from skill_spotter.capture.normalize_actions import normalize_action, turn_fingerprint

from . import data as D
from .generate import llm

RESULTS = Path(__file__).resolve().parent / "results"

PROPOSE = """For each repeated developer task below, propose the slash-command name a developer \
would want for a reusable Claude Code skill: kebab-case, 1-3 words, verb first when natural.

{items}

Reply with ONLY JSON: {{"names": {{"<family_id>": "<name>", ...}}}}"""

JUDGE = """Rate how well each proposed slash-command name fits its task, from 1 (misleading or \
meaningless) to 5 (exactly what a developer would type). Each task has two names, A and B.

{items}

Reply with ONLY JSON: {{"ratings": {{"<family_id>": {{"A": <1-5>, "B": <1-5>}}, ...}}}}"""


def heuristic_names(turns):
    by_fam = defaultdict(list)
    for t in turns:
        if t.kind == "positive":
            by_fam[t.family].append(t)
    out, info = {}, {}
    for fam, items in by_fam.items():
        n = len(items)
        words, first, lead, tokens = Counter(), Counter(), Counter(), defaultdict(float)
        for t in items:
            content = nt.content_words(t.prompt)
            words.update(set(content))
            lead.update(set(content[: naming.LEAD_WORDS]))
            if content:
                first[content[0]] += 1
            fp = turn_fingerprint(
                [
                    normalize_action(
                        a["tool"], a.get("input") or {}, t.root, failed=bool(a.get("failed"))
                    )
                    for a in t.actions
                ]
            )
            for k, w in fp.items():
                tokens[k] += w / n
        rep = {
            "words": {w: c / n for w, c in words.items()},
            "first": {w: c / n for w, c in first.items()},
            "lead": {w: c / n for w, c in lead.items()},
            "tokens": dict(tokens),
        }
        hint = nt.content_words(items[-1].prompt)
        out[fam] = naming.suggest_name(rep, None, order_hint=hint)
        info[fam] = items
    return out, info


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", help="tune on dev, report on test")
    args = parser.parse_args()
    test = D.load(args.split)
    families = {f["family_id"]: f for f in json.loads((D.DATA / "families.json").read_text())}
    heur, info = heuristic_names(test)
    fams = sorted(heur)
    items = "\n".join(
        f'- {f}: intent="{families[f]["intent"]}" examples="{info[f][0].prompt}" | "{info[f][-1].prompt}"'
        for f in fams
    )
    reference = llm.call(PROPOSE.format(items=items), model="sonnet", label="naming:propose").get(
        "names", {}
    )
    rng = random.Random(1)
    order, lines = {}, []
    for f in fams:
        pair = [("heuristic", heur[f]), ("claude", reference.get(f, "?"))]
        rng.shuffle(pair)
        order[f] = pair
        lines.append(f'- {f}: task="{families[f]["intent"]}" A=/{pair[0][1]} B=/{pair[1][1]}')
    ratings = llm.call(
        JUDGE.format(items="\n".join(lines)), model="sonnet", label="naming:judge"
    ).get("ratings", {})
    scores = {"heuristic": [], "claude": []}
    rows = []
    for f in fams:
        r = ratings.get(f) or {}
        got = {}
        for slot, (who, name) in zip("AB", order[f]):
            if isinstance(r.get(slot), (int, float)):
                scores[who].append(r[slot])
                got[who] = r[slot]
        rows.append(
            {
                "family": f,
                "heuristic": heur[f],
                "claude": reference.get(f),
                **{f"score_{k}": v for k, v in got.items()},
            }
        )
    summary = {
        "families": len(fams),
        "heuristic_mean": round(sum(scores["heuristic"]) / max(1, len(scores["heuristic"])), 2),
        "claude_mean": round(sum(scores["claude"]) / max(1, len(scores["claude"])), 2),
        "exact_match": round(sum(1 for f in fams if heur[f] == reference.get(f)) / len(fams), 3),
        "heuristic_ge4": round(
            sum(1 for s in scores["heuristic"] if s >= 4) / max(1, len(scores["heuristic"])), 3
        ),
        "local_llm": "not evaluated (no Ollama/llama.cpp; disk nearly full)",
    }
    RESULTS.mkdir(exist_ok=True)
    summary["split"] = args.split
    out = RESULTS / ("naming.json" if args.split == "test" else f"naming-{args.split}.json")
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
