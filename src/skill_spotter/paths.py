"""Where skill-spotter keeps its data. Standard library only (runs inside hooks)."""

from __future__ import annotations

import os
from pathlib import Path

DB_NAME = "skill-spotter.db"

# Used when nothing else says where to go, e.g. running the CLI from a plain shell.
FALLBACK_DATA_DIR = Path.home() / ".claude" / "plugins" / "data" / "skill-spotter"


def data_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve the data directory.

    Order: explicit argument, $SKILL_SPOTTER_DATA, $CLAUDE_PLUGIN_DATA (exported to
    hooks by Claude Code), then the fallback. Empty values and unsubstituted
    placeholders like "${CLAUDE_PLUGIN_DATA}" are skipped, so a misconfiguration
    can never create a database in whatever the current directory happens to be.
    """
    for candidate in (
        explicit,
        os.environ.get("SKILL_SPOTTER_DATA"),
        os.environ.get("CLAUDE_PLUGIN_DATA"),
    ):
        if candidate and str(candidate).strip() and "${" not in str(candidate):
            return Path(candidate).expanduser()
    return FALLBACK_DATA_DIR


def display(path: str | os.PathLike) -> str:
    """``path`` with the home folder as ``~``: shorter, and screenshots of the status
    output don't show the user's account name."""
    text, home = str(path), str(Path.home())
    if text == home or text.startswith(home + os.sep):
        return "~" + text[len(home) :]
    return text


def db_path(base: Path) -> Path:
    return base / DB_NAME


def error_log_path(base: Path) -> Path:
    return base / "logs" / "errors.log"
