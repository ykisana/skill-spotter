"""Skill verification (M6): does a model-invocable skill trigger when it should, and only then?

``skill-spotter verify`` (an explicit, token-spending command; never run by hooks):

1. reads the skill's ``description``;
2. asks Claude for ``n`` prompts that should trigger it and ``n`` near-misses that should not;
3. runs each prompt headless in the project (``claude -p``, only the Skill tool enabled)
   and checks whether Claude invoked this skill;
4. stores trigger precision / recall / F1 in ``skill_scores``;
5. with ``--revise``, if F1 < 0.8 asks Claude for a sharper description, writes it, and
   re-tests once.

Manual-only skills (``disable-model-invocation: true``) aren't trigger-tested: Claude never
starts them, so their quality signal is how often the user runs them (``used`` events).
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

GENERATE = """A Claude Code skill named "{name}" has this description:

{description}

Write {n} realistic prompts a developer might type that SHOULD make Claude use this skill \
(varied wording, some terse), and {n} prompts that should NOT (related but different tasks, \
near-misses that share words). Reply with ONLY JSON: \
{{"should": ["..."], "should_not": ["..."]}}"""

REVISE = """A Claude Code skill named "{name}" triggers poorly with this description:

{description}

Missed (should have triggered): {missed}
False triggers (should not have): {false}

Write a better one-paragraph description (max 400 characters): key use case first, the \
phrases users actually type, and what it is NOT for. \
Reply with ONLY JSON: {{"description": "..."}}"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_scores (
    skill_path TEXT NOT NULL,
    name       TEXT NOT NULL,
    ts         REAL NOT NULL,
    precision  REAL,
    recall     REAL,
    f1         REAL,
    n          INTEGER NOT NULL,
    details    TEXT NOT NULL DEFAULT '{}'
);
"""


def frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"')
    return fm, m.group(2)


def is_model_invocable(skill_md: Path) -> bool:
    fm, _ = frontmatter(skill_md.read_text())
    return fm.get("disable-model-invocation", "false").lower() != "true"


def _claude_json(prompt: str, model: str, cwd: Path, runner=subprocess.run) -> Any:
    proc = runner(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--tools",
            "",
            "--no-session-persistence",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(cwd),
    )
    result = json.loads(proc.stdout).get("result", "")
    fenced = re.search(r"```(?:json)?\s*(.*?)```", result, re.S)
    text = fenced.group(1) if fenced else result
    return json.loads(text[text.find("{") :])


def triggered(prompt: str, name: str, model: str, cwd: Path, runner=subprocess.run) -> bool:
    """Run the prompt headless with only the Skill tool and see if Claude invokes ``name``."""
    proc = runner(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--tools",
            "Skill",
            "--allowedTools",
            "Skill",
            "--max-turns",
            "2",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(cwd),
    )
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                called = str(
                    (block.get("input") or {}).get("skill")
                    or (block.get("input") or {}).get("command")
                    or ""
                )
                if called.lstrip("/").split(":")[-1] == name:
                    return True
    return False


def score(should: List[str], should_not: List[str], fired: Callable[[str], bool]) -> Dict[str, Any]:
    hits = [p for p in should if fired(p)]
    false = [p for p in should_not if fired(p)]
    tp, fn, fp = len(hits), len(should) - len(hits), len(false)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "missed": [p for p in should if p not in hits],
        "false_triggers": false,
    }


def set_description(skill_md: Path, description: str) -> None:
    text = skill_md.read_text()
    new = re.sub(
        r"(?m)^description:.*$", "description: " + description.replace("\n", " "), text, count=1
    )
    skill_md.write_text(new)


def verify(
    conn: sqlite3.Connection,
    skill_md: Path,
    *,
    n: int = 6,
    model: str = "haiku",
    revise: bool = False,
    runner=subprocess.run,
) -> Dict[str, Any]:
    conn.executescript(SCHEMA)
    name = skill_md.parent.name
    cwd = (
        skill_md.parents[3]
        if skill_md.parent.parent.name == "skills" and skill_md.parents[2].name == ".claude"
        else skill_md.parent
    )
    fm, _ = frontmatter(skill_md.read_text())
    if fm.get("disable-model-invocation", "false").lower() == "true":
        return {"name": name, "skipped": "manual-only: quality = usage (used events)"}
    prompts = _claude_json(
        GENERATE.format(name=name, description=fm.get("description", ""), n=n), model, cwd, runner
    )
    should, should_not = prompts.get("should", [])[:n], prompts.get("should_not", [])[:n]
    result = score(should, should_not, lambda p: triggered(p, name, model, cwd, runner))
    result.update(name=name, n=len(should) + len(should_not), revised=False)
    if revise and (result["f1"] or 0) < 0.8:
        better = _claude_json(
            REVISE.format(
                name=name,
                description=fm.get("description", ""),
                missed=json.dumps(result["missed"]),
                false=json.dumps(result["false_triggers"]),
            ),
            model,
            cwd,
            runner,
        )
        if better.get("description"):
            before = dict(result)
            set_description(skill_md, better["description"])
            result = score(should, should_not, lambda p: triggered(p, name, model, cwd, runner))
            result.update(
                name=name,
                n=len(should) + len(should_not),
                revised=True,
                before={k: before[k] for k in ("precision", "recall", "f1")},
                description=better["description"],
            )
    conn.execute(
        "INSERT INTO skill_scores(skill_path, name, ts, precision, recall, f1, n, details) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(skill_md),
            name,
            time.time(),
            result["precision"],
            result["recall"],
            result["f1"],
            result["n"],
            json.dumps({k: v for k, v in result.items() if k not in ("precision", "recall", "f1")}),
        ),
    )
    return result


def latest_scores(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT skill_path, precision, recall, f1, n, ts FROM skill_scores ORDER BY ts"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["skill_path"]: dict(r) for r in rows}


def usage(conn: sqlite3.Connection, pattern_id: int) -> Tuple[int, Optional[float]]:
    row = conn.execute(
        "SELECT COUNT(*), MAX(ts) FROM events WHERE type = 'used' AND pattern_id = ?", (pattern_id,)
    ).fetchone()
    return row[0], row[1]
