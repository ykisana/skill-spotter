"""SQLite storage and schema migrations. Standard library only (runs inside hooks).

The schema version lives in ``PRAGMA user_version``. To change the schema, append a
new script to ``MIGRATIONS``; never edit one that has shipped, because users'
databases have already run it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: initial schema (SPEC section 8)
    """
    CREATE TABLE turns (
        prompt_id            TEXT PRIMARY KEY,
        session_id           TEXT NOT NULL,
        project_key          TEXT NOT NULL,
        ts_start             REAL NOT NULL,
        ts_end               REAL,
        prompt_redacted      TEXT,
        prompt_norm          TEXT,
        n_meaningful_actions INTEGER NOT NULL DEFAULT 0,
        pattern_id           INTEGER REFERENCES patterns(id) ON DELETE SET NULL,
        finalized            INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX turns_project_ts ON turns(project_key, ts_end);
    CREATE INDEX turns_session ON turns(session_id);

    CREATE TABLE actions (
        id             INTEGER PRIMARY KEY,
        prompt_id      TEXT,
        session_id     TEXT NOT NULL,
        agent_id       TEXT,
        ts             REAL NOT NULL,
        tool_name      TEXT NOT NULL,
        input_redacted TEXT,
        template_id    INTEGER REFERENCES templates(id),
        tokens_json    TEXT NOT NULL DEFAULT '[]',
        failed         INTEGER NOT NULL DEFAULT 0,
        danger         INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX actions_prompt ON actions(prompt_id);

    CREATE TABLE templates (
        id         INTEGER PRIMARY KEY,
        tool_name  TEXT NOT NULL,
        template   TEXT NOT NULL,
        count      INTEGER NOT NULL DEFAULT 0,
        first_seen REAL NOT NULL,
        last_seen  REAL NOT NULL,
        UNIQUE (tool_name, template)
    );

    CREATE TABLE vectors (
        owner_type TEXT NOT NULL,
        owner_id   TEXT NOT NULL,
        method     TEXT NOT NULL,
        dim        INTEGER NOT NULL,
        blob       BLOB NOT NULL,
        PRIMARY KEY (owner_type, owner_id, method)
    );

    CREATE TABLE patterns (
        id                  INTEGER PRIMARY KEY,
        project_key         TEXT NOT NULL,
        representative_json TEXT NOT NULL DEFAULT '{}',
        count               INTEGER NOT NULL DEFAULT 0,
        session_count       INTEGER NOT NULL DEFAULT 0,
        first_seen          REAL NOT NULL,
        last_seen           REAL NOT NULL,
        suggested_name      TEXT,
        params_json         TEXT NOT NULL DEFAULT '[]',
        danger              INTEGER NOT NULL DEFAULT 0,
        state               TEXT NOT NULL DEFAULT 'candidate'
                            CHECK (state IN ('candidate', 'ready', 'suggested', 'accepted',
                                             'snoozed', 'dismissed')),
        state_until         REAL,
        snooze_count        INTEGER NOT NULL DEFAULT 0,
        skill_path          TEXT,
        method_version      TEXT NOT NULL DEFAULT 'baseline-0'
    );
    CREATE INDEX patterns_project_state ON patterns(project_key, state);

    CREATE TABLE events (
        id         INTEGER PRIMARY KEY,
        ts         REAL NOT NULL,
        type       TEXT NOT NULL,
        pattern_id INTEGER,
        session_id TEXT,
        data_json  TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_type_ts ON events(type, ts);

    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2: matching state for M1 (IDF counts, inverted index, per-session filter state)
    """
    ALTER TABLE turns ADD COLUMN fingerprint_json TEXT;
    ALTER TABLE turns ADD COLUMN danger INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE actions ADD COLUMN tool_use_id TEXT;
    ALTER TABLE actions ADD COLUMN values_json TEXT NOT NULL DEFAULT '[]';
    CREATE UNIQUE INDEX actions_tool_use ON actions(tool_use_id) WHERE tool_use_id IS NOT NULL;
    CREATE INDEX turns_pattern ON turns(pattern_id, ts_end);

    CREATE TABLE token_df (
        project_key TEXT NOT NULL,
        token       TEXT NOT NULL,
        df          INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (project_key, token)
    ) WITHOUT ROWID;

    CREATE TABLE project_stats (
        project_key TEXT PRIMARY KEY,
        n_turns     INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE pattern_tokens (
        token      TEXT NOT NULL,
        pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
        PRIMARY KEY (token, pattern_id)
    ) WITHOUT ROWID;
    CREATE INDEX pattern_tokens_pattern ON pattern_tokens(pattern_id);

    CREATE TABLE session_meta (
        session_id       TEXT PRIMARY KEY,
        last_prompt_hash TEXT,
        last_prompt_ts   REAL,
        crons_json       TEXT NOT NULL DEFAULT '[]',
        pending_context  TEXT,
        updated          REAL NOT NULL DEFAULT 0
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: Path, *, timeout: float = 2.0) -> sqlite3.Connection:
    """Open the database, creating it and applying any pending migrations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema v{current} is newer than this skill-spotter (v{SCHEMA_VERSION})"
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        # Each step runs in its own transaction, so a crash can't leave a half-built schema.
        script = MIGRATIONS[version - 1]
        conn.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def is_enabled(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "enabled", "1") == "1"
