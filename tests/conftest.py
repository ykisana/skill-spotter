from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RULE_CONFIG = ROOT / "tests" / "fixtures" / "rule_config.json"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point every test at a throwaway data dir so the real one is never touched."""
    data = tmp_path / "data"
    monkeypatch.setenv("SKILL_SPOTTER_DATA", str(data))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("SKILL_SPOTTER_BAND_DIR", str(tmp_path / "band"))
    # The user's own ~/.claude (CLAUDE.md, rules, skills) must not change what tests see.
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Mechanics tests use the plain rule matcher, independent of what the Method Lab ships
    # in config/method.json; test_shipped_matcher.py covers the shipped one.
    monkeypatch.setenv("SKILL_SPOTTER_METHOD_CONFIG", str(RULE_CONFIG))
    return data
