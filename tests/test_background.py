"""Background tier (M4): merge split patterns, mark ready, suggest at the next Stop."""

from __future__ import annotations

import json

import pytest
from helpers import Session, bash, edit, system_message

from skill_spotter import clock, paths, store
from skill_spotter.background import job, launcher

DAY = 86400.0
T0 = 1_790_000_000.0


@pytest.fixture
def at(monkeypatch):
    current = {"t": T0}
    monkeypatch.setattr(clock, "now", lambda: current["t"])
    return lambda days: current.update(t=T0 + days * DAY)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "acme"
    (root / ".git").mkdir(parents=True)
    return str(root)


@pytest.fixture
def db(isolated_data_dir):
    return lambda: store.connect(paths.db_path(isolated_data_dir))


def release_turn(s, repo, i):
    return s.turn(
        f"cut the weekly release and publish notes, round {i}",
        [
            bash("npm run build"),
            bash("npm version patch"),
            edit(f"{repo}/CHANGELOG.md"),
            bash("git push --follow-tags"),
        ],
    )


def split_pattern(db):
    """Simulate the online matcher having split one task into two patterns."""
    conn = db()
    rows = conn.execute("SELECT prompt_id FROM turns ORDER BY ts_start").fetchall()
    rep = conn.execute(
        "SELECT representative_json, first_seen FROM patterns WHERE id = 1"
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO patterns(project_key, representative_json, count, session_count, "
        "first_seen, last_seen) SELECT project_key, representative_json, 1, 1, first_seen, "
        "last_seen FROM patterns WHERE id = 1"
    )
    new_id = cur.lastrowid
    conn.execute("UPDATE turns SET pattern_id = ? WHERE prompt_id = ?", (new_id, rows[-1][0]))
    conn.execute("UPDATE patterns SET count = count - 1 WHERE id = 1")
    conn.close()
    return new_id, rep


def test_job_merges_split_patterns_and_marks_ready(repo, db, at, isolated_data_dir):
    store.set_setting(db(), "enabled", "0")  # keep the online path from suggesting first
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        at(i)
        release_turn(s, repo, i)
    new_id, _ = split_pattern(db)
    assert db().execute("SELECT COUNT(*) FROM patterns").fetchone()[0] == 2

    summary = job.run(isolated_data_dir, T0 + 3 * DAY)
    assert summary["merged"] == 1 and summary["ready"] == 1
    conn = db()
    rows = conn.execute("SELECT id, state, count, session_count FROM patterns").fetchall()
    assert [tuple(r) for r in rows] == [(1, "ready", 3, 2)]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type = 'merged'").fetchone()[0] == 1

    # the next Stop in that project shows it
    store.set_setting(conn, "enabled", "1")
    at(4)
    out = Session(repo).turn("something else entirely about the docs site", [bash("npm run docs")])
    assert system_message(out["stop"]).endswith("run /skill-spotter:draft p1")


def test_job_leaves_accepted_and_dismissed_patterns_alone(repo, db, at, isolated_data_dir):
    store.set_setting(db(), "enabled", "0")
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        at(i)
        release_turn(s, repo, i)
    new_id, _ = split_pattern(db)
    db().execute("UPDATE patterns SET state = 'dismissed' WHERE id = ?", (new_id,))
    summary = job.run(isolated_data_dir, T0 + 3 * DAY)
    assert summary["merged"] == 0
    assert db().execute("SELECT COUNT(*) FROM patterns").fetchone()[0] == 2


def test_launcher_spawns_only_when_due_and_unlocked(repo, db, at, isolated_data_dir, monkeypatch):
    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    conn = db()
    store.set_setting(conn, "background_every", "2")
    assert not launcher.maybe_spawn(conn, T0)  # no turns yet
    s = Session(repo)
    for i in range(2):
        release_turn(s, repo, i + 10)
    assert spawned  # the Stop hook launched it once 2 turns were in
    count = len(spawned)
    (isolated_data_dir / "background.lock").write_text("123")
    assert not launcher.maybe_spawn(conn, clock.now())  # lock held
    assert len(spawned) == count


def test_launcher_respects_off_switch(db, monkeypatch, at):
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    conn = db()
    store.set_setting(conn, "background", "off")
    store.set_setting(conn, "background_every", "0")
    assert not launcher.maybe_spawn(conn, T0)


def test_job_cli_entry_point_and_lock(isolated_data_dir, db):
    db().close()
    assert job.main(["--data-dir", str(isolated_data_dir)]) == 0
    assert not (isolated_data_dir / "background.lock").exists()
    summary = json.loads(store.get_setting(db(), "background_last_summary"))
    assert summary["projects"] == 0
