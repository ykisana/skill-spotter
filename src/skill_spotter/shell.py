"""Import shell history (M5): ``skill-spotter scan-shell``.

Commands from zsh (extended history, ``: <ts>:<dur>;<cmd>``) or bash (``#<ts>`` lines,
with HISTTIMEFORMAT set) are grouped into turns: commands less than ``gap`` minutes apart
belong together, and each day is a session. Each turn goes through the same recording
and matching as a Claude Code turn, with no prompt text, so tasks you repeat in the shell
count towards suggesting them when you start doing them with Claude.

Nothing leaves the machine; commands are redacted before they're stored.
"""

from __future__ import annotations

import os
import re
import time
import zlib
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

ZSH_LINE = re.compile(r"^: (\d+):\d+;(.*)$")


def parse_history(text: str) -> List[Tuple[float, str]]:
    """(timestamp, command) pairs. Untimestamped bash history gets no entries."""
    out: List[Tuple[float, str]] = []
    lines = text.splitlines()
    i = 0
    pending_ts: Optional[float] = None
    while i < len(lines):
        line = lines[i]
        m = ZSH_LINE.match(line)
        if m:
            ts, cmd = float(m.group(1)), m.group(2)
            while cmd.endswith("\\") and i + 1 < len(lines):  # multi-line command
                i += 1
                cmd = cmd[:-1] + "\n" + lines[i]
            out.append((ts, cmd.strip()))
        elif line.startswith("#") and line[1:].isdigit():
            pending_ts = float(line[1:])
        elif pending_ts is not None and line.strip():
            out.append((pending_ts, line.strip()))
            pending_ts = None
        i += 1
    return [(ts, cmd) for ts, cmd in out if cmd]


def group_turns(
    entries: Iterable[Tuple[float, str]], gap_minutes: float = 10
) -> List[List[Tuple[float, str]]]:
    turns: List[List[Tuple[float, str]]] = []
    for ts, cmd in sorted(entries):
        if (
            turns
            and ts - turns[-1][-1][0] <= gap_minutes * 60
            and time.localtime(ts).tm_yday == time.localtime(turns[-1][-1][0]).tm_yday
        ):
            turns[-1].append((ts, cmd))
        else:
            turns.append([(ts, cmd)])
    return turns


def default_history_file() -> Optional[Path]:
    for name in (os.environ.get("HISTFILE"), "~/.zsh_history", "~/.bash_history"):
        if name:
            path = Path(name).expanduser()
            if path.is_file():
                return path
    return None


def import_history(
    conn, path: Path, project_key: str, gap_minutes: float = 10, since_days: float = 90
) -> dict:
    """Record history turns newer than ``since_days`` for ``project_key``; idempotent."""
    from . import patterns, recorder

    text = path.read_text(errors="replace")
    cutoff = time.time() - since_days * 86400
    entries = [(ts, cmd) for ts, cmd in parse_history(text) if ts >= cutoff]
    stats = {"commands": len(entries), "turns": 0, "skipped_existing": 0, "patterns": 0}
    for group in group_turns(entries, gap_minutes):
        start = group[0][0]
        prompt_id = f"shell-{int(start)}-{zlib.crc32(project_key.encode()):08x}"
        if conn.execute("SELECT 1 FROM turns WHERE prompt_id = ?", (prompt_id,)).fetchone():
            stats["skipped_existing"] += 1
            continue
        session = "shell-" + time.strftime("%Y-%m-%d", time.localtime(start))
        conn.execute(
            "INSERT INTO turns(prompt_id, session_id, project_key, ts_start, prompt_redacted, "
            "prompt_norm) "
            "VALUES(?, ?, ?, ?, '', '')",
            (prompt_id, session, project_key, start),
        )
        for k, (ts, cmd) in enumerate(group):
            recorder.record_action(
                conn,
                {
                    "prompt_id": prompt_id,
                    "session_id": session,
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                    "tool_use_id": f"{prompt_id}-{k}",
                },
                ts,
            )
        pid = patterns.finalize_turn(conn, prompt_id, group[-1][0] + 1)
        stats["turns"] += 1
        stats["patterns"] += pid is not None
    stats["patterns"] = conn.execute(
        "SELECT COUNT(DISTINCT pattern_id) FROM turns WHERE session_id LIKE 'shell-%' AND "
        "pattern_id IS NOT NULL"
    ).fetchone()[0]
    return stats
