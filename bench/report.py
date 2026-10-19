"""Write docs/benchmarks/README.md (tables, PR curves, ablation) from the latest lab run.

.venv/bin/python -m bench.report
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import data as D

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results"
DOCS = ROOT / "docs" / "benchmarks"
SCORES = ROOT / "bench" / ".cache" / "scores"


def fmt(x, digits=3):
    return "–" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def pr_curves(rows, stage, title, filename, top=8):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve

    y = np.array([p[2] for p in D.make_pairs(D.load("test"))])
    ranked = sorted(
        (r for r in rows if r.get("stage") == stage and "test" in r),
        key=lambda r: -(r["test"]["pr_auc"] or 0),
    )[:top]
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for r in ranked:
        path = SCORES / f"{stage}-{r['method']}-test.npy"
        if not path.exists():
            continue
        s = np.load(path)
        p, rc, _ = precision_recall_curve(y, s)
        ax.plot(rc, p, label=f"{r['method']} (AP {r['test']['pr_auc']:.3f})", linewidth=1.3)
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title(title)
    ax.set_ylim(0.4, 1.01)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    fig.savefig(DOCS / filename, dpi=130)
    plt.close(fig)


def pair_table(rows, stage):
    out = [
        "| method | track | dev PR-AUC | test PR-AUC | test P | test R | test F1 | P@0.9 recall (test) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(
        (r for r in rows if r.get("stage") == stage and "test" in r),
        key=lambda r: -(r["test"]["pr_auc"] or 0),
    ):
        t = r["test"]
        out.append(
            f"| {r['method']} | {r.get('track') or ''} | {fmt(r['dev']['pr_auc'])} | {fmt(t['pr_auc'])} | "
            f"{fmt(t['precision'])} | {fmt(t['recall'])} | {fmt(t['f1'])} | {fmt(t['at_p90']['recall'])} |"
        )
    failed = [r for r in rows if r.get("stage") == stage and r.get("error")]
    out += [f"| {r['method']} | – | failed: {r['error'][:80]} | | | | | |" for r in failed]
    return out


def tier_table(rows, stage, method):
    r = next((r for r in rows if r.get("stage") == stage and r.get("method") == method), None)
    if not r:
        return []
    out = ["| pair type | n | recall / false-positive rate |", "|---|---|---|"]
    for g, v in sorted(r["test_by_tier"].items()):
        val = v.get("recall", v.get("false_positive_rate"))
        label = "recall" if "recall" in v else "FP rate"
        out.append(f"| {g} | {v['n']} | {label} {fmt(val)} |")
    return out


def extra_sections(rows):
    """Ablation (what each change did), the M4 runtime check, and M5 sequence mining."""
    lines = []
    chosen = RESULTS / "runtime_chosen.json"
    sweep = RESULTS / "sweep.json"
    lines += [
        "",
        "## Ablation: what each change did (real-hook replay)",
        "",
        "| matcher | dev P | dev R | test P | test R | test false / 100 turns |",
        "|---|---|---|---|---|---|",
        "| rule, M1 baseline (before ADR 0006) | 0.651 | 0.883 | 0.671 | 0.868 | 1.07 |",
    ]
    base = {
        r["split"]: r
        for r in rows
        if r.get("stage") == "replay" and r.get("method") == "runtime<baseline>"
    }
    if base:
        lines.append(
            f"| + meaningful-only actions, text gate, no double suggestions | {fmt(base['dev']['precision'])} | "
            f"{fmt(base['dev']['recall'])} | {fmt(base['test']['precision'])} | {fmt(base['test']['recall'])} | "
            f"{fmt(base['test']['false_per_100_turns'])} |"
        )
    if sweep.exists():
        sw = json.loads(sweep.read_text())
        b, t = sw["best"], sw["test_of_best"]
        lines.append(
            f"| + swept rule `{json.dumps(b['params'])}` | {fmt(b['precision'])} | {fmt(b['recall'])} | "
            f"{fmt(t['precision'])} | {fmt(t['recall'])} | {fmt(t['false_per_100_turns'])} |"
        )
    if chosen.exists():
        c = json.loads(chosen.read_text())
        lines.append(
            f"| **chosen: logreg fusion + leader (runtime)** | {fmt(c['dev']['runtime']['precision'])} | "
            f"{fmt(c['dev']['runtime']['recall'])} | {fmt(c['test']['runtime']['precision'])} | "
            f"{fmt(c['test']['runtime']['recall'])} | {fmt(c['test']['runtime']['false_per_100_turns'])} |"
        )
        lines += [
            "",
            "M4 check, the shipped runtime vs the lab's simulation of the same method (tolerance 0.05): "
            f"dev difference {c['dev']['difference']}, test difference {c['test']['difference']}.",
        ]
    seqs = RESULTS / "sequences.json"
    if seqs.exists():
        d = json.loads(seqs.read_text())
        lines += [
            "",
            "## Multi-turn workflow mining (M5)",
            "",
            f"{len(d['planted'])} planted workflows (2-4 steps, 3-6 sessions each, noise turns between "
            f"steps) among {d['sessions']} sessions. Found = reported as a frequent sequence (support >= 3).",
            "",
            "| method | found | recall | false workflows | reported | seconds |",
            "|---|---|---|---|---|---|",
        ]
        for r in d["results"]:
            lines.append(
                f"| {r['method']} | {r['found']}/{r['planted']} | {fmt(r['recall'])} | "
                f"{r['false_workflows']} | {r['reported']} | {fmt(r['seconds'])} |"
            )
    return lines


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (RESULTS / "results.jsonl").read_text().splitlines()]
    run = rows[-1]["run"]
    rows = [r for r in rows if r.get("run") == run]
    inputs = next((r for r in rows if r.get("stage") == "selection_inputs"), {})
    for stage, title in (
        ("text", "Text similarity (test pairs)"),
        ("actions", "Action similarity (test pairs)"),
        ("fusion", "Fusion (test pairs)"),
    ):
        pr_curves(rows, stage, title, f"pr_{stage}.png")
    card = (
        (ROOT / "bench" / "data" / "dataset_card.md")
        .read_text()
        .split("## Counts")[1]
        .split("## Quality")[0]
        if (ROOT / "bench" / "data" / "dataset_card.md").exists()
        else ""
    )
    lines = [
        "# Method Lab results",
        "",
        f"Run `{run}` on the synthetic v1 dataset ([dataset card](../../bench/data/dataset_card.md)). "
        "Reproduce with `.venv/bin/python -m bench.run --stages text,templating,actions,fusion,cluster,replay`, "
        "then `bench.scale`, `bench.naming`, `bench.select`, `bench.report`.",
        "",
        "**Caveat:** synthetic traces come from templates, so action similarity is easier here than on real",
        "sessions. The real held-out check (SPEC 11.5) is still pending; the configs are provisional until it passes.",
        "",
        "## Dataset",
        card.strip(),
        "",
        "## Pairwise: text",
        "",
        "![text PR curves](pr_text.png)",
        "",
        *pair_table(rows, "text"),
        "",
        "## Command templating",
        "",
        "Grouping accuracy: calls generated from the same trace step should get the same template.",
        "",
        "| templater | dev group F1 | test group F1 | test precision | test recall |",
        "|---|---|---|---|---|",
    ]
    for r in (r for r in rows if r.get("stage") == "templating" and "test" in r):
        lines.append(
            f"| {r['method']} | {fmt(r['dev']['group_f1'])} | {fmt(r['test']['group_f1'])} | "
            f"{fmt(r['test']['group_precision'])} | {fmt(r['test']['group_recall'])} |"
        )
    lines += [
        "",
        "## Pairwise: actions",
        "",
        "![action PR curves](pr_actions.png)",
        "",
        *pair_table(rows, "actions"),
        "",
        "## Fusion",
        "",
        f"Inputs: text = {inputs.get('text')}, actions = {inputs.get('actions')}.",
        "",
        "![fusion PR curves](pr_fusion.png)",
        "",
        *pair_table(rows, "fusion"),
        "",
    ]
    lr = [r for r in rows if r.get("stage") == "fusion" and r.get("coefficients")]
    for r in lr:
        lines.append(
            f"- `{r['method']}` coefficients (standardised features): `{r['coefficients']}`"
        )
    best_fusion = max(
        (r for r in rows if r.get("stage") == "fusion" and r.get("track") == "stdlib"),
        key=lambda r: r["dev"]["pr_auc"] or 0,
        default=None,
    )
    if best_fusion:
        lines += [
            "",
            f"Test breakdown by pair type for `{best_fusion['method']}`:",
            "",
            *tier_table(rows, "fusion", best_fusion["method"]),
        ]
    lines += [
        "",
        "## Clustering",
        "",
        "| clusterer | track | theta | test B3-F1 | B3-P | B3-R | ARI | NMI | V | one-offs left alone |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(
        (r for r in rows if r.get("stage") == "cluster" and "test" in r),
        key=lambda r: -r["test"]["bcubed_f1"],
    ):
        t = r["test"]
        lines.append(
            f"| {r['method']} | {r['track']} | {r['theta']} | {fmt(t['bcubed_f1'])} | {fmt(t['bcubed_p'])} | "
            f"{fmt(t['bcubed_r'])} | {fmt(t['ari'])} | {fmt(t['nmi'])} | {fmt(t['v_measure'])} | {fmt(t['oneoffs_left_alone'])} |"
        )
    lines += [
        "",
        "## Replay (product metrics)",
        "",
        "Chronological replay with the trigger rule (3+ times, 2+ sessions, 30 days, 1 per session, 3 per day). "
        "`runtime<baseline>` drives the real hook code.",
        "",
        "| method | split | suggestions | precision | recall | median occurrences before first | false / 100 turns | duplicates |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in (r for r in rows if r.get("stage") == "replay"):
        lines.append(
            f"| {r['method']} | {r['split']} | {r['suggestions']} | {fmt(r.get('precision'))} | {fmt(r.get('recall'))} | "
            f"{fmt(r.get('median_occurrences_before_first'))} | {fmt(r.get('false_per_100_turns'))} | {r.get('duplicate_suggestions')} |"
        )
    scale = RESULTS / "scale.json"
    if scale.exists():
        data = json.loads(scale.read_text())
        lines += [
            "",
            "## Lookup",
            "",
            "Can the matcher find an earlier turn of the same task? Recall@10 on test, latency with "
            "the index padded to 100k vectors (bge-small embeddings for vector methods).",
            "",
            "| method | recall@10 | p50 ms | p95 ms |",
            "|---|---|---|---|",
        ]
        for r in data.get("lookup", []):
            if "error" in r:
                lines.append(f"| {r['method']} | – | {r['error']} | |")
                continue
            lines.append(
                f"| {r['method']} | {fmt(r['recall@10'])} | {fmt(r['p50_ms'])} | {fmt(r['p95_ms'])} |"
            )
    rt = RESULTS / "scale_runtime.json"
    if rt.exists():
        r = json.loads(rt.read_text())
        lines += [
            "",
            "## Scale (runtime)",
            "",
            f"{r['turns']:,} turns / {r['actions']:,} actions / {r['patterns']:,} patterns in one database "
            f"({r['db_mb']} MB, built in {r['build_seconds']} s). Stop hook with that database: "
            f"p50 {r['stop_p50_ms']} ms, p95 {r['stop_p95_ms']} ms.",
        ]
    naming = RESULTS / "naming.json"
    if naming.exists():
        s = json.loads(naming.read_text())["summary"]
        lines += [
            "",
            "## Naming",
            "",
            f"Judge scores (1-5, blind, Claude Sonnet) over {s['families']} test families: runtime heuristic "
            f"{s['heuristic_mean']} ({fmt(s['heuristic_ge4'])} rated 4+), Claude reference {s['claude_mean']}. "
            f"Exact match {fmt(s['exact_match'])}. Local LLM: {s['local_llm']}. Claude refines the name when "
            "drafting, so the heuristic only needs to be a sensible default.",
        ]
    lines += extra_sections(rows)
    for name, title in (
        ("method.json", "Chosen: stdlib (online tier)"),
        ("method.extras.json", "Chosen: with extras (background tier)"),
    ):
        path = ROOT / "config" / name
        if path.exists():
            lines += ["", f"## {title}", "", "```json", path.read_text().strip(), "```"]
    (DOCS / "README.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {DOCS / 'README.md'}")


if __name__ == "__main__":
    main()
