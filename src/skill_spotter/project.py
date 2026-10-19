"""Project identity: the git root of the working directory, else the directory itself."""

from __future__ import annotations

import os
from typing import Optional


def project_root(cwd: Optional[str]) -> Optional[str]:
    """Nearest ancestor of ``cwd`` containing ``.git`` (a dir, or a file for worktrees)."""
    if not cwd:
        return None
    path = os.path.abspath(cwd)
    current = path
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return path
        current = parent


def project_key(cwd: Optional[str]) -> str:
    return project_root(cwd) or "?"
