"""Fail-open wrapper every hook goes through. Standard library only.

The contract (SPEC sections 0 and 3):
- always finish normally, so the hook exits 0;
- print nothing unless the adapter's ``render`` returns output;
- on any error, write a traceback to ``<data dir>/logs/errors.log`` and carry on.
A bug in skill-spotter must never block, delay or change the user's work.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from types import ModuleType
from typing import IO, Optional

from . import claude_code, paths


def run(
    hook_event: Optional[str],
    adapter: ModuleType = claude_code,
    stdin: Optional[IO[str]] = None,
    stdout: Optional[IO[str]] = None,
) -> None:
    """Handle one hook call. Never raises.

    ``hook_event`` may be None when one script serves several events; it is then read
    from the input's ``hook_event_name``.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        raw = stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        name = hook_event or payload.get("hook_event_name")
        handler = adapter.HANDLERS.get(name) if isinstance(name, str) else None
        if handler is None:
            return
        result = handler(adapter.normalize(name, payload))
        output = adapter.render(name, result)
        if output:
            stdout.write(output)
            stdout.flush()
    except Exception:
        log_error(hook_event)


def log_error(hook_event: Optional[str]) -> None:
    try:
        log = paths.error_log_path(paths.data_dir())
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            f.write(f"--- {stamp} {hook_event or '?'}\n{traceback.format_exc()}\n")
    except Exception:
        pass  # even logging can fail (read-only disk, bad path); stay silent anyway
