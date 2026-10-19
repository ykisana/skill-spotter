"""Record prompts and tool calls as they happen (SPEC section 5.1)."""

from __future__ import annotations

import json
import sqlite3
import zlib
from typing import Any, Dict, List, Optional

from . import project
from .capture import filters, normalize_text
from .capture.normalize_actions import normalize_action
from .capture.redact import redact

MAX_PROMPT_CHARS = 2000
REPEAT_WINDOW = 600  # seconds


def _hash(text: str) -> str:
    """Cheap fingerprint for spotting exact repeats (zlib imports much faster than hashlib)."""
    data = text.encode("utf-8", "replace")
    return f"{zlib.crc32(data):08x}{zlib.adler32(data):08x}{len(data):x}"


def _session_meta(conn: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM session_meta WHERE session_id = ?", (session_id,)).fetchone()


def record_prompt(conn: sqlite3.Connection, event: Dict[str, Any], now: float) -> Optional[str]:
    """Store the prompt as the start of a turn. Returns why it was skipped, or None."""
    prompt_id, session_id, prompt = (
        event.get("prompt_id"),
        event.get("session_id"),
        event.get("prompt"),
    )
    if not prompt_id or not session_id:
        return "no ids"
    meta = _session_meta(conn, session_id)
    crons: List[str] = json.loads(meta["crons_json"]) if meta else []
    reason = filters.skip_reason(prompt, scheduled_prompts=crons)
    text = filters.strip_pasted(prompt) if isinstance(prompt, str) else ""
    digest = _hash(text)
    if (
        reason is None
        and meta is not None
        and meta["last_prompt_hash"] == digest
        and meta["last_prompt_ts"] is not None
        and now - meta["last_prompt_ts"] <= REPEAT_WINDOW
    ):
        reason = "repeat"
    conn.execute(
        "INSERT INTO session_meta(session_id, last_prompt_hash, last_prompt_ts, updated) "
        "VALUES(?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
        "last_prompt_hash = excluded.last_prompt_hash, last_prompt_ts = excluded.last_prompt_ts, "
        "updated = excluded.updated",
        (session_id, digest, now, now),
    )
    if reason:
        return reason
    redacted = redact(text)[:MAX_PROMPT_CHARS]
    norm = " ".join(normalize_text.normalize(redacted))
    conn.execute(
        "INSERT OR IGNORE INTO turns(prompt_id, session_id, project_key, ts_start, "
        "prompt_redacted, prompt_norm) VALUES(?, ?, ?, ?, ?, ?)",
        (prompt_id, session_id, project.project_key(event.get("cwd")), now, redacted, norm),
    )
    return None


def record_action(conn: sqlite3.Connection, event: Dict[str, Any], now: float) -> bool:
    """Store one tool call for its turn. Returns False if there's no recorded turn."""
    prompt_id = event.get("prompt_id")
    if not prompt_id:
        return False
    turn = conn.execute(
        "SELECT project_key, finalized FROM turns WHERE prompt_id = ?", (prompt_id,)
    ).fetchone()
    if turn is None:
        return False  # the prompt was filtered out (slash command, too short, automatic)
    root = turn["project_key"] if turn["project_key"] != "?" else None
    action = normalize_action(
        event.get("tool_name") or "",
        event.get("tool_input"),
        root,
        failed=bool(event.get("failed")),
    )
    if not action["tokens"]:
        return False
    template_id = None
    if action["template"]:
        conn.execute(
            "INSERT INTO templates(tool_name, template, count, first_seen, last_seen) "
            "VALUES(?, ?, 1, ?, ?) ON CONFLICT(tool_name, template) DO UPDATE SET "
            "count = count + 1, last_seen = excluded.last_seen",
            (action["tool"], action["template"], now, now),
        )
        template_id = conn.execute(
            "SELECT id FROM templates WHERE tool_name = ? AND template = ?",
            (action["tool"], action["template"]),
        ).fetchone()[0]
    stored = {"tokens": action["tokens"], "primary": action["primary"], "low": action["low"]}
    conn.execute(
        "INSERT OR IGNORE INTO actions(prompt_id, session_id, agent_id, ts, tool_name, "
        "input_redacted, template_id, tokens_json, failed, danger, tool_use_id, values_json) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prompt_id,
            event.get("session_id") or "",
            event.get("agent_id"),
            now,
            action["tool"],
            action["summary"],
            template_id,
            json.dumps(stored, separators=(",", ":")),
            int(bool(event.get("failed"))),
            int(action["danger"]),
            event.get("tool_use_id"),
            json.dumps(action["values"]),
        ),
    )
    return True


def remember_scheduled_prompts(
    conn: sqlite3.Connection, session_id: str, prompts: List[str], now: float
) -> None:
    """Keep the session's scheduled-task prompts so future automatic turns can be skipped."""
    prompts = [p for p in prompts if isinstance(p, str) and p.strip()]
    if not session_id:
        return
    conn.execute(
        "INSERT INTO session_meta(session_id, crons_json, updated) VALUES(?, ?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET crons_json = excluded.crons_json, "
        "updated = excluded.updated",
        (session_id, json.dumps(prompts[:50]), now),
    )
