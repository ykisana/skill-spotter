"""The current time, in one place so tests can move it (e.g. past a 14-day snooze)."""

from __future__ import annotations

import time


def now() -> float:
    return time.time()
