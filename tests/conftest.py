from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point every test at a throwaway data dir so the real one is never touched."""
    data = tmp_path / "data"
    monkeypatch.setenv("SKILL_SPOTTER_DATA", str(data))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    return data
