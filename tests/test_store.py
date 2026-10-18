from __future__ import annotations

import sqlite3

import pytest

from skill_spotter import store

TABLES = {"turns", "actions", "templates", "vectors", "patterns", "events", "settings"}
INDEXES = {"actions_prompt", "turns_project_ts", "patterns_project_state"}


def names(conn, kind):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def test_fresh_database_gets_full_schema(tmp_path):
    conn = store.connect(tmp_path / "nested" / "db.sqlite")  # parent dirs get created
    assert names(conn, "table") >= TABLES
    assert names(conn, "index") >= INDEXES
    assert store.schema_version(conn) == store.SCHEMA_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reopening_does_not_rerun_migrations(tmp_path):
    path = tmp_path / "db.sqlite"
    store.connect(path).close()
    conn = store.connect(path)  # would fail with "table already exists" if it re-ran
    assert store.schema_version(conn) == store.SCHEMA_VERSION


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "db.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
    raw.close()
    with pytest.raises(RuntimeError, match="newer"):
        store.connect(path)


def test_settings_roundtrip_and_enabled_default(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    assert store.is_enabled(conn)  # on by default
    assert store.get_setting(conn, "missing", "d") == "d"
    store.set_setting(conn, "enabled", "0")
    store.set_setting(conn, "enabled", "0")  # upsert: setting twice is fine
    assert not store.is_enabled(conn)


def test_pattern_state_is_constrained(tmp_path):
    conn = store.connect(tmp_path / "db.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO patterns(project_key, first_seen, last_seen, state) "
            "VALUES('p', 0, 0, 'bogus')"
        )
