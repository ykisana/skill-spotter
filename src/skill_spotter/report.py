"""Read-side views of the database for the CLI and the draft skill."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import naming

MAX_TURNS_SHOWN = 8


def parse_pattern_id(text: str) -> Optional[int]:
    text = (text or "").strip().lower().lstrip("p")
    return int(text) if text.isdigit() else None


def _iso(ts: Optional[float]) -> Optional[str]:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else None


def pattern_detail(conn: sqlite3.Connection, pattern_id: int) -> Optional[Dict[str, Any]]:
    """Everything the draft skill needs to write a SKILL.md for one pattern."""
    p = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if p is None:
        return None
    turns = conn.execute(
        "SELECT prompt_id, session_id, ts_start, prompt_redacted FROM turns "
        "WHERE pattern_id = ? ORDER BY ts_start DESC LIMIT ?",
        (pattern_id, MAX_TURNS_SHOWN),
    ).fetchall()
    shown = []
    step_presence: Dict[str, int] = defaultdict(int)
    step_positions: Dict[str, List[float]] = defaultdict(list)
    step_values: Dict[str, List[List[str]]] = defaultdict(list)
    step_danger: Dict[str, bool] = defaultdict(bool)
    for turn in turns:
        rows = conn.execute(
            "SELECT a.tool_name, t.template, a.input_redacted, a.failed, a.danger, "
            "a.values_json, a.tokens_json FROM actions a LEFT JOIN templates t "
            "ON t.id = a.template_id WHERE a.prompt_id = ? ORDER BY a.ts, a.id",
            (turn["prompt_id"],),
        ).fetchall()
        actions = []
        ordered: List[str] = []
        for r in rows:
            low = json.loads(r["tokens_json"]).get("low", False)
            actions.append(
                {
                    "tool": r["tool_name"],
                    "step": r["template"],
                    "input": r["input_redacted"],
                    "failed": bool(r["failed"]),
                    "danger": bool(r["danger"]),
                    "exploration": bool(low),
                }
            )
            if r["template"] and not low and not r["failed"] and r["template"] not in ordered:
                ordered.append(r["template"])
                step_values[r["template"]].append(json.loads(r["values_json"] or "[]"))
                step_danger[r["template"]] |= bool(r["danger"])
        for i, step in enumerate(ordered):
            step_presence[step] += 1
            step_positions[step].append(i / max(1, len(ordered) - 1))
        shown.append(
            {
                "prompt": turn["prompt_redacted"],
                "when": _iso(turn["ts_start"]),
                "session": turn["session_id"][:8],
                "actions": actions,
            }
        )
    n = max(1, len(turns))
    common = [s for s, c in step_presence.items() if c / n >= 0.5]
    common.sort(key=lambda s: sum(step_positions[s]) / len(step_positions[s]))
    varying = []
    for step in common:
        seen = [tuple(v) for v in step_values[step]]
        if len(set(seen)) > 1:
            distinct = []
            for values in seen:
                text = " ".join(values)
                if text and text not in distinct:
                    distinct.append(text)
            varying.append({"step": step, "examples": distinct[:5]})
    root = p["project_key"] if p["project_key"] != "?" else None
    rep = json.loads(p["representative_json"])
    name = p["suggested_name"] or naming.suggest_name(rep, root)
    skills_dir = (
        os.path.join(root, ".claude", "skills") if root else os.path.expanduser("~/.claude/skills")
    )
    return {
        "id": f"p{p['id']}",
        "project": p["project_key"],
        "state": p["state"],
        "count": p["count"],
        "sessions": p["session_count"],
        "first_seen": _iso(p["first_seen"]),
        "last_seen": _iso(p["last_seen"]),
        "suggested_name": name,
        "danger": bool(p["danger"]) or any(step_danger[s] for s in common),
        "dangerous_steps": [s for s in common if step_danger[s]],
        "common_steps": [
            {"step": s, "in_turns": f"{step_presence[s]}/{len(turns)}"} for s in common
        ],
        "varying_values": varying,
        "turns": shown,
        "skill_scope": "project" if root else "personal",
        "skills_dir": skills_dir,
        "skills_dir_exists": os.path.isdir(skills_dir),
        "skill_path": os.path.join(skills_dir, name, "SKILL.md"),
    }


def format_detail(d: Dict[str, Any]) -> str:
    lines = [
        f"{d['id']}  /{d['suggested_name']}  [{d['state']}]  "
        f"{d['count']}x in {d['sessions']} sessions",
        f"project: {d['project']}",
    ]
    if d["danger"]:
        lines.append(f"DANGER: {', '.join(d['dangerous_steps']) or 'yes'}")
    lines.append("common steps:")
    lines += [f"  - {s['step']}  ({s['in_turns']})" for s in d["common_steps"]] or ["  (none)"]
    if d["varying_values"]:
        lines.append("varying values:")
        lines += [f"  - {v['step']}: {' | '.join(v['examples'])}" for v in d["varying_values"]]
    lines.append("recent prompts:")
    lines += [f"  - [{t['when']}] {t['prompt']}" for t in d["turns"]]
    return "\n".join(lines)
