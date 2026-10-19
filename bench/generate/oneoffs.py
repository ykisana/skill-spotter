"""Step 4 of SPEC 11.4: one-off distractor turns (tasks done once and never repeated).

Real usage is mostly one-offs, so the dataset has ~5x as many of them as repeated turns.
Generated in batches per (category, project type) with a cheaper model.

Run:  .venv/bin/python -m bench.generate.oneoffs [--per-call 60] [--calls-per-category 6]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm
from .catalog import CATEGORIES

PROJECT_TYPES = [
    "node-web",
    "python-service",
    "go-cli",
    "ios-app",
    "android-app",
    "infra-repo",
    "data-notebooks",
    "monorepo",
]

PROMPT = """Generate {n} realistic ONE-OFF requests a developer might type to Claude Code (an AI \
coding agent) while working in a {project_type} project, roughly in the area of: {category_desc}. \
Batch {index}: vary them widely and make each a distinct, specific task that would not be repeated \
(a particular bug, a specific refactor, a question about one file, a single investigation). \
Mix lengths and styles (casual, terse, detailed). Include some that are only questions/explanations.

For each, give the tool calls Claude would make (1-6 steps) using ONLY these shapes:
  {{"tool": "Bash", "command": "<shell command>"}}
  {{"tool": "Edit" | "Write" | "Read", "file": "<repo-relative path>"}}
  {{"tool": "Grep", "pattern": "<regex>", "path": "<dir>"}}
  {{"tool": "mcp", "server": "<linear|jira|github|slack|notion|sentry>", "name": "<tool_name>", "args": ["<arg names>"]}}
  {{"tool": "WebFetch", "url": "<url>"}}
Questions may have only Read/Grep steps.

Reply with ONLY JSON: {{"items": [{{"prompt": "...", "trace": [...]}}, ...]}}"""


def jobs_list(calls_per_category: int, per_call: int):
    for ci, (cat, desc) in enumerate(CATEGORIES.items()):
        for i in range(calls_per_category):
            ptype = PROJECT_TYPES[(ci + i) % len(PROJECT_TYPES)]
            yield cat, desc, ptype, i, per_call


def run(job):
    cat, desc, ptype, index, n = job
    prompt = PROMPT.format(n=n, project_type=ptype, category_desc=desc, index=index + 1)
    data = {}
    for attempt in range(3):  # a retry changes the prompt slightly, so it isn't a cache hit
        suffix = "" if attempt == 0 else f"\n(Attempt {attempt + 1}: output strictly valid JSON.)"
        try:
            data = llm.call(prompt + suffix, model="haiku", label=f"oneoff:{cat}:{ptype}:{index}")
            break
        except Exception as exc:  # noqa: BLE001 - skip a bad batch rather than lose the run
            print(f"oneoff batch {cat}/{ptype}/{index} attempt {attempt + 1} failed: {exc}")
    items = data.get("items", []) if isinstance(data, dict) else data
    return [
        dict(item, category=cat, project_type=ptype) for item in items if isinstance(item, dict)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--per-call", type=int, default=60)
    parser.add_argument("--calls-per-category", type=int, default=6)
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent.parent / "data" / "oneoffs.json")
    )
    args = parser.parse_args()
    out = []
    with ThreadPoolExecutor(args.jobs) as pool:
        for items in pool.map(run, list(jobs_list(args.calls_per_category, args.per_call))):
            out.extend(items)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{len(out)} one-offs -> {args.out}")


if __name__ == "__main__":
    main()
