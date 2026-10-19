"""Start the background job from the Stop hook: only when enough new turns arrived, never
twice at once, fully detached so Claude Code never waits on it. Standard library only."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .. import paths, store

DEFAULT_EVERY = 50
STALE_LOCK_SECONDS = 1800
JOB = Path(__file__).resolve().parent / "job.py"


def lock_path(base: Path) -> Path:
    return base / "background.lock"


def lock_is_held(base: Path, now: float) -> bool:
    path = lock_path(base)
    try:
        return now - path.stat().st_mtime < STALE_LOCK_SECONDS
    except OSError:
        return False


def due(conn, now: float) -> bool:
    every = int(store.get_setting(conn, "background_every", str(DEFAULT_EVERY)) or DEFAULT_EVERY)
    total = conn.execute("SELECT COUNT(*) FROM turns WHERE finalized = 1").fetchone()[0]
    last = int(store.get_setting(conn, "background_last_turns", "0") or 0)
    return total - last >= every


def maybe_spawn(conn, now: float) -> bool:
    """Spawn the job if due. Returns True if a process was started."""
    if store.get_setting(conn, "background", "on") == "off":
        return False
    base = paths.data_dir()
    if not due(conn, now) or lock_is_held(base, now):
        return False
    log = base / "logs"
    log.mkdir(parents=True, exist_ok=True)
    with open(log / "background.log", "ab") as out:
        # Detached and with stdout/stderr redirected, so the hook's output pipe closes
        # immediately (hooks reference: "Hooks that start a background process").
        subprocess.Popen(
            [sys.executable, "-S", str(JOB), "--data-dir", str(base)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            start_new_session=True,
            close_fds=True,
            env={**os.environ, "SKILL_SPOTTER_DATA": str(base)},
        )
    store.set_setting(conn, "background_spawned_at", str(time.time()))
    return True
