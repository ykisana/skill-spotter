from __future__ import annotations

from pathlib import Path

import pytest

from skill_spotter import paths


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test with neither data-dir variable set."""
    monkeypatch.delenv("SKILL_SPOTTER_DATA", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)


def test_fallback_when_nothing_is_set():
    assert paths.data_dir() == paths.FALLBACK_DATA_DIR


def test_claude_plugin_data_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    assert paths.data_dir() == tmp_path / "plugin"


def test_skill_spotter_data_beats_claude_plugin_data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    monkeypatch.setenv("SKILL_SPOTTER_DATA", str(tmp_path / "override"))
    assert paths.data_dir() == tmp_path / "override"


def test_explicit_argument_beats_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILL_SPOTTER_DATA", str(tmp_path / "override"))
    assert paths.data_dir(tmp_path / "explicit") == tmp_path / "explicit"


@pytest.mark.parametrize("bad", ["", "   ", "${CLAUDE_PLUGIN_DATA}"])
def test_empty_or_unsubstituted_values_are_skipped(monkeypatch, bad):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", bad)
    assert paths.data_dir(bad) == paths.FALLBACK_DATA_DIR


def test_tilde_is_expanded():
    assert paths.data_dir("~/somewhere") == Path.home() / "somewhere"


def test_file_locations(tmp_path):
    assert paths.db_path(tmp_path) == tmp_path / "skill-spotter.db"
    assert paths.error_log_path(tmp_path) == tmp_path / "logs" / "errors.log"
