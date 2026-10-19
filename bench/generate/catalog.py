"""Steps 1–3 of SPEC 11.4: task families with prompt variants and hard negatives.

One call per (category, batch) asks for several families at once: canonical intent,
an action-trace template, parameters, 10 prompt variants across difficulty tiers and
4 lookalike hard negatives with their own traces. Traces are templates; ``traces.py``
expands them deterministically.

Run:  .venv/bin/python -m bench.generate.catalog [--jobs 6]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm

CATEGORIES = {
    "git": "git and pull requests (branches, rebases, PR creation/review requests, cherry-picks)",
    "release": "releases and changelogs (version bumps, tags, release notes, publishing packages)",
    "testing": "testing and CI (running suites, fixing flaky tests, CI reruns, coverage reports)",
    "deploy": "deploy and rollback (staging/production deploys, rollbacks, health checks, feature flags)",
    "database": "database migrations (creating/applying/reverting migrations, schema dumps, seeding)",
    "debugging": "debugging and logs (tailing logs, reproducing errors, profiling, inspecting crashes)",
    "docs": "documentation (READMEs, API docs generation, ADRs, docstrings, doc sites)",
    "data": "data analysis (CSV/SQL exploration, notebooks, reports, metrics queries)",
    "infra": "infrastructure (Docker, Kubernetes, Terraform, cloud CLIs, secrets rotation)",
    "review": "code review (reviewing diffs/PRs, applying review comments, security review)",
    "deps": "dependency upgrades (npm/pip/cargo updates, lockfile refresh, vulnerability fixes)",
    "scaffold": "project scaffolding (new services, components, endpoints, boilerplate generation)",
    "mobile": "mobile builds (iOS/Android builds, TestFlight, fastlane, simulators, signing)",
    "mcp": "MCP-heavy tasks with issue trackers and chat tools (Linear, Jira, GitHub issues, Slack, Notion)",
}
FAMILIES_PER_CATEGORY = 7
BATCH = 4  # families per call

PROMPT = """You are generating a synthetic benchmark for a tool that detects when a developer \
repeats the same task in Claude Code (an AI coding agent), so it can suggest saving the task \
as a reusable command. Category: {category_desc}.

Create {n} distinct, realistic task FAMILIES a developer would repeat over weeks in this category. \
Avoid these families already created: {avoid}.

For each family output:
- "slug": short kebab-case id
- "intent": one sentence, the canonical task
- "project_type": one of node-web, python-service, go-cli, ios-app, android-app, infra-repo, data-notebooks, monorepo
- "params": object mapping parameter names to 3-6 realistic example values (things that vary between runs: env names, PR numbers, versions, dates, service names...)
- "trace": the tool calls Claude typically makes for this task, 3-8 steps, as objects using ONLY these shapes:
    {{"tool": "Bash", "command": "<shell command, may use {{param}} placeholders>"}}
    {{"tool": "Edit" | "Write" | "Read", "file": "<repo-relative path, may use {{param}}>"}}
    {{"tool": "Grep", "pattern": "<regex>", "path": "<dir>"}}
    {{"tool": "mcp", "server": "<linear|jira|github|slack|notion|sentry|datadog>", "name": "<tool_name>", "args": ["<argument names only>"]}}
    {{"tool": "WebFetch", "url": "<url>"}}
  Optionally add "optional": true to a step that is sometimes skipped, and "group": <int> to steps whose order can vary among themselves.
- "positives": exactly 10 prompts a developer might type for THIS SAME task, as objects {{"difficulty": ..., "prompt": ...}}: \
2 "light" (light rewording), 3 "heavy" (heavy paraphrase, different vocabulary), 2 "terse" (shorthand, 3-7 words), \
1 "typo" (realistic typos), 2 "param" (different parameter values, written out concretely). Prompts may use {{param}} placeholders.
- "hard_negatives": exactly 4 lookalike tasks that share words or commands with this family but are a DIFFERENT task \
(e.g. "deploy api to staging" vs "roll back api on staging"; "git commit" vs "git commit --amend"; "fix the login bug" vs "fix the checkout bug"). \
Each: {{"prompt": ..., "relation": "different" | "related", "why": "<what differs>", "trace": [<same step shapes, 2-6 steps>]}}. \
"related" means same area and partly overlapping work, still not the same task.

Make prompts sound like real developers (lowercase, casual, sometimes imperative, sometimes questions). \
Use realistic commands (gh, git, npm, pnpm, pytest, uv, docker, kubectl, terraform, make, fastlane, xcodebuild, psql, alembic, etc).

Reply with ONLY a JSON object: {{"families": [ ... ]}}"""


def batches():
    for cat, desc in CATEGORIES.items():
        made = 0
        index = 0
        while made < FAMILIES_PER_CATEGORY:
            n = min(BATCH, FAMILIES_PER_CATEGORY - made)
            yield cat, desc, index, n
            made += n
            index += 1


def run_batch(cat: str, desc: str, index: int, n: int, avoid):
    prompt = PROMPT.format(category_desc=desc, n=n, avoid=", ".join(avoid) or "none")
    data = {}
    for attempt in range(3):
        suffix = "" if attempt == 0 else f"\n(Attempt {attempt + 1}: output strictly valid JSON.)"
        try:
            data = llm.call(prompt + suffix, model="sonnet", label=f"catalog:{cat}:{index}")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"catalog batch {cat}/{index} attempt {attempt + 1} failed: {exc}")
    return cat, index, data.get("families", [])


def generate(jobs: int = 6):
    """Two rounds so batch 2 of a category can avoid batch 1's slugs."""
    by_cat = {}
    first = [b for b in batches() if b[2] == 0]
    with ThreadPoolExecutor(jobs) as pool:
        for cat, _i, fams in pool.map(lambda b: run_batch(*b, avoid=[]), first):
            by_cat[cat] = list(fams)
    rest = [b for b in batches() if b[2] > 0]
    with ThreadPoolExecutor(jobs) as pool:
        futures = [
            pool.submit(run_batch, *b, avoid=[f.get("slug", "") for f in by_cat[b[0]]])
            for b in rest
        ]
        for fut in futures:
            cat, _i, fams = fut.result()
            by_cat[cat].extend(fams)
    families = []
    for cat in CATEGORIES:
        for fam in by_cat[cat]:
            fam["category"] = cat
            fam["family_id"] = f"f{len(families) + 1:03d}"
            families.append(fam)
    return families


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent.parent / "data" / "families.json")
    )
    args = parser.parse_args()
    families = generate(args.jobs)
    Path(args.out).write_text(json.dumps(families, indent=1))
    print(f"{len(families)} families -> {args.out}")


if __name__ == "__main__":
    main()
