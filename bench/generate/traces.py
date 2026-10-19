"""Step 5 of SPEC 11.4: expand trace templates into Claude Code tool calls, by code.

Perturbations make repeated runs look like real ones: parameter values change, optional
steps get skipped, independent steps get reordered, exploration noise appears, commands
fail and get retried, and some steps run inside a subagent.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

NOISE_BASH = ["git status", "ls", "ls -la", "git diff", "git log --oneline -5", "pwd", "git branch"]
NOISE_READ = [
    "README.md",
    "package.json",
    "pyproject.toml",
    "Makefile",
    "src/index.ts",
    "src/main.py",
]
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def fill(text: str, values: Dict[str, str], rng: random.Random) -> str:
    def sub(m):
        name = m.group(1)
        if name in values:
            return str(values[name])
        values[name] = f"{name}-{rng.randint(1, 99)}"  # unknown placeholder: invent once
        return values[name]

    return PLACEHOLDER.sub(sub, text)


def choose_values(params: Dict[str, List[Any]], rng: random.Random) -> Dict[str, str]:
    values = {}
    for name, options in (params or {}).items():
        if isinstance(options, list) and options:
            values[name] = str(rng.choice(options))
        elif options not in (None, "", []):
            values[name] = str(options)
    return values


def to_tool_call(
    step: Dict[str, Any], root: str, values: Dict[str, str], rng: random.Random
) -> Optional[Dict[str, Any]]:
    tool = step.get("tool")
    if tool == "Bash" and step.get("command"):
        command = fill(str(step["command"]), values, rng)
        return {"tool": "Bash", "input": {"command": command}}
    if tool in ("Edit", "Write", "Read") and step.get("file"):
        path = fill(str(step["file"]), values, rng).lstrip("/")
        return {"tool": tool, "input": {"file_path": f"{root}/{path}"}}
    if tool == "Grep":
        return {
            "tool": "Grep",
            "input": {
                "pattern": fill(str(step.get("pattern", "")), values, rng),
                "path": f"{root}/{str(step.get('path', '')).lstrip('/')}".rstrip("/"),
            },
        }
    if tool == "mcp" and step.get("server") and step.get("name"):
        args = [str(a) for a in step.get("args") or []]
        return {"tool": f"mcp__{step['server']}__{step['name']}", "input": {a: "x" for a in args}}
    if tool == "WebFetch" and step.get("url"):
        return {"tool": "WebFetch", "input": {"url": fill(str(step["url"]), values, rng)}}
    return None


def _vary_numbers(command: str, rng: random.Random) -> str:
    return re.sub(r"(?<![\w.-])\d{1,4}(?![\w.])", lambda m: str(rng.randint(1, 500)), command)


def expand(
    trace: List[Dict[str, Any]],
    params: Dict[str, List[Any]],
    root: str,
    rng: random.Random,
    *,
    perturb: bool = True,
    values: Optional[Dict[str, str]] = None,
    src: str = "",
) -> List[Dict[str, Any]]:
    """``src`` labels each call with its template step (``<src>:<i>``), so templaters can be
    scored on whether calls from the same step get the same template."""
    values = dict(values) if values is not None else choose_values(params, rng)
    steps = [s for s in trace if isinstance(s, dict)]
    if perturb:
        steps = [s for s in steps if not (s.get("optional") and rng.random() < 0.35)]
        # reorder steps that share a group, keeping each group's slots
        groups: Dict[Any, List[int]] = {}
        for i, s in enumerate(steps):
            if s.get("group") is not None:
                groups.setdefault(s["group"], []).append(i)
        for slots in groups.values():
            members = [steps[i] for i in slots]
            rng.shuffle(members)
            for i, s in zip(slots, members):
                steps[i] = s
    calls = []
    for s in steps:
        call = to_tool_call(s, root, values, rng)
        if call:
            call["src"] = f"{src}:{trace.index(s)}" if src else None
            calls.append(call)
    for c in calls:
        c.setdefault("failed", False)
        c.setdefault("agent_id", None)
    if not perturb:
        return calls
    # vary numeric values in commands
    for c in calls:
        if c["tool"] == "Bash" and rng.random() < 0.3:
            c["input"]["command"] = _vary_numbers(c["input"]["command"], rng)
    # failed-and-retried command
    bash_idx = [i for i, c in enumerate(calls) if c["tool"] == "Bash"]
    if bash_idx and rng.random() < 0.15:
        i = rng.choice(bash_idx)
        failed = {
            "tool": "Bash",
            "input": dict(calls[i]["input"]),
            "failed": True,
            "agent_id": None,
            "src": calls[i].get("src"),
        }
        calls.insert(i, failed)
    # subagent doing part of the work
    if len(calls) >= 3 and rng.random() < 0.15:
        start = rng.randrange(0, len(calls) - 1)
        agent = f"agent-{rng.randint(100, 999)}"
        for c in calls[start : start + rng.randint(1, 3)]:
            c["agent_id"] = agent
    # exploration noise
    for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
        if rng.random() < 0.6:
            noise = {"tool": "Bash", "input": {"command": rng.choice(NOISE_BASH)}}
        else:
            noise = {"tool": "Read", "input": {"file_path": f"{root}/{rng.choice(NOISE_READ)}"}}
        noise.update(failed=False, agent_id=None, src="noise")
        calls.insert(rng.randint(0, len(calls)), noise)
    return calls


def fill_prompt(prompt: str, values: Dict[str, str], rng: random.Random) -> str:
    return fill(prompt, values, rng)
