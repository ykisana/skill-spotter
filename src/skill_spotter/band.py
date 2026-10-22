"""Hand-off between the Stop hook and the skill-spotter mod's band (M7, ADR 0009).

When the mod is loaded, it registers the session (``skill-spotter band register``), the
Stop hook queues suggestions here instead of printing a ``systemMessage``, and the mod
fetches them after each turn (``skill-spotter band pending``) to draw
"You've repeated this 5 times: "…"  [Create /name] [Not now]". Without the mod, nothing changes.

The hand-off is a mailbox of small files in a fixed folder, not the database: a mod
can't learn the plugin's data folder (``CLAUDE_PLUGIN_DATA`` is only set for hooks), so
each queued suggestion carries the data folder the mod's buttons must act on.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

BAND_DIR_ENV = "SKILL_SPOTTER_BAND_DIR"
_STALE_SECONDS = 7 * 86400

_MESSAGE = re.compile(
    r"^skill-spotter: (?P<summary>.+)\. To save (?:it|them) as (?:/(?P<name>[\w\-]+)|a skill), "
    r"run /skill-spotter:draft (?P<id>[pw]\d+)$",
    re.S,
)


def band_dir() -> Path:
    explicit = os.environ.get(BAND_DIR_ENV)
    if explicit and explicit.strip():
        return Path(explicit).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "skill-spotter" / "band"


def _file(session_id: str, suffix: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id)[:128]
    return band_dir() / f"{safe}.{suffix}"


def register(session_id: str) -> None:
    base = band_dir()
    base.mkdir(parents=True, exist_ok=True)
    _file(session_id, "on").touch()
    _prune(base, time.time())


def is_active(session_id: str) -> bool:
    return bool(session_id) and _file(session_id, "on").exists()


def parse(text: str) -> Dict[str, Any]:
    m = _MESSAGE.search(text)
    if not m:
        return {"text": text}
    summary = m.group("summary")
    return {
        "text": text,
        "summary": summary[:1].upper() + summary[1:],
        "id": m.group("id"),
        "name": m.group("name"),
        "draft": f"/skill-spotter:draft {m.group('id')}",
    }


def queue(session_id: str, text: str, data_dir: str) -> None:
    payload = parse(text)
    payload["data_dir"] = data_dir
    path = _file(session_id, "pending")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def pop(session_id: str) -> Optional[Dict[str, Any]]:
    path = _file(session_id, "pending")
    try:
        text = path.read_text()
        path.unlink()
    except OSError:
        return None
    return json.loads(text)


def forget(session_id: str) -> None:
    for suffix in ("on", "pending"):
        with contextlib.suppress(OSError):
            _file(session_id, suffix).unlink()


def _prune(base: Path, now: float) -> None:
    """Drop files of sessions that ended without a SessionEnd (crash, kill)."""
    for entry in base.iterdir():
        try:
            if now - entry.stat().st_mtime > _STALE_SECONDS:
                entry.unlink()
        except OSError:
            continue
