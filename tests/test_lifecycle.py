"""M2 done criterion: a scripted scenario produces the expected states and stats."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from conftest import ROOT
from helpers import Session, bash, edit, read, system_message

from skill_spotter import cli, clock, lifecycle, paths, store

DAY = 86400.0
T0 = 1_790_000_000.0  # a fixed moment, so the scenario is deterministic


@pytest.fixture
def at(monkeypatch):
    """at(days) moves the hooks' clock to T0 + days."""
    current = {"t": T0}
    monkeypatch.setattr(clock, "now", lambda: current["t"])

    def move(days):
        current["t"] = T0 + days * DAY

    return move


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "acme-api"
    (root / ".git").mkdir(parents=True)
    return str(root)


@pytest.fixture
def db(isolated_data_dir):
    return lambda: store.connect(paths.db_path(isolated_data_dir))


def changelog(s, repo, i):
    prompts = [
        "write the changelog from merged pull requests this week",
        "changelog from this week's merged PRs please",
        "write release notes for merged pull requests",
        "update the changelog with the merged pull requests",
        "summarize merged PRs into the changelog",
        "add this week's merged pull requests to the changelog",
    ]
    return s.turn(
        prompts[i % len(prompts)],
        [
            bash("gh pr list --state merged"),
            read(f"{repo}/CHANGELOG.md"),
            edit(f"{repo}/CHANGELOG.md"),
        ],
    )


def deploy(s, repo, i):
    return s.turn(
        f"deploy the api service to staging (round {i})",
        [
            bash("npm run build"),
            bash("docker build -t api ."),
            bash("kubectl rollout restart deploy/api"),
        ],
    )


def migrate(s, repo, i):
    return s.turn(
        f"run the database migrations and regenerate the schema dump, take {i}",
        [
            bash("alembic upgrade head"),
            bash("python scripts/dump_schema.py"),
            edit(f"{repo}/db/schema.sql"),
        ],
    )


def state(db, pattern_id):
    return (
        db()
        .execute("SELECT state, snooze_count FROM patterns WHERE id = ?", (pattern_id,))
        .fetchone()
    )


def pattern_of(db, needle):
    return (
        db()
        .execute(
            "SELECT pattern_id FROM turns WHERE prompt_redacted LIKE ? LIMIT 1", (f"%{needle}%",)
        )
        .fetchone()[0]
    )


def test_scripted_lifecycle(repo, db, at, capsys):
    # --- pattern A: suggested, ignored twice -> snoozed, then dismissed ---
    at(0)
    s1, s2 = Session(repo), Session(repo)
    changelog(s1, repo, 0)
    changelog(s1, repo, 1)
    assert system_message(changelog(s2, repo, 2)["stop"])
    a = pattern_of(db, "changelog")
    assert tuple(state(db, a)) == ("suggested", 0)
    s2.end()
    assert tuple(state(db, a)) == ("snoozed", 1)

    at(1)
    assert changelog(Session(repo), repo, 3)["stop"] == ""  # still snoozed

    at(15)  # snooze over
    s4 = Session(repo)
    assert "pattern p" in system_message(changelog(s4, repo, 4)["stop"])
    s4.end()
    assert tuple(state(db, a)) == ("dismissed", 2)

    at(16)
    assert changelog(Session(repo), repo, 5)["stop"] == ""  # dismissed for good

    # --- pattern B: suggested, user creates the skill -> ConfigChange -> accepted, used ---
    at(17)
    s5, s6 = Session(repo), Session(repo)
    deploy(s5, repo, 1)
    deploy(s5, repo, 2)
    msg = system_message(deploy(s6, repo, 3)["stop"])
    b = pattern_of(db, "deploy the api")
    name = db().execute("SELECT suggested_name FROM patterns WHERE id = ?", (b,)).fetchone()[0]
    assert f"/{name}." in msg
    skill = os.path.join(repo, ".claude", "skills", name, "SKILL.md")
    os.makedirs(os.path.dirname(skill))
    with open(skill, "w") as f:
        f.write("---\ndescription: deploy\ndisable-model-invocation: true\n---\nsteps\n")
    s6.skill_changed(skill)
    assert state(db, b)["state"] == "accepted"
    s6.end()
    assert state(db, b)["state"] == "accepted"  # accepted patterns aren't snoozed
    s7 = Session(repo)
    s7.expand(name)
    s7.expand(name, "production")
    s7.expand("some-other-skill")

    # --- pattern C: suggested, skill appears without a ConfigChange -> scan accepts it ---
    at(18)
    s8, s9 = Session(repo), Session(repo)
    migrate(s8, repo, 1)
    migrate(s8, repo, 2)
    assert system_message(migrate(s9, repo, 3)["stop"])
    c = pattern_of(db, "migrations")
    c_name = db().execute("SELECT suggested_name FROM patterns WHERE id = ?", (c,)).fetchone()[0]
    skill_c = os.path.join(repo, ".claude", "skills", c_name, "SKILL.md")
    os.makedirs(os.path.dirname(skill_c))
    with open(skill_c, "w") as f:
        f.write("---\ndescription: migrate\n---\n")
    s9.turn("something unrelated to check on the build", [bash("gh run list")])
    assert state(db, c)["state"] == "accepted"

    # --- stats ---
    data = lifecycle.stats(db())
    assert data["patterns_suggested"] == 3
    assert data["suggestions_shown"] == 4  # A twice, B, C
    assert data["accepted"] == 2 and data["accepted_pct"] == pytest.approx(66.7)
    assert data["dismissed"] == 1
    assert data["skills_used_at_least_once"] == 1 and data["skill_uses"] == 2

    assert cli.main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "accepted: 2 (66.7%)" in out and "skills used at least once: 1 (2 uses)" in out
    assert cli.main(["status"]) == 0
    assert "used 2x" in capsys.readouterr().out
    events = [r[0] for r in db().execute("SELECT type FROM events ORDER BY id")]
    assert events.count("snoozed") == 1 and events.count("dismissed") == 1


def test_cli_dismiss_and_snooze(repo, db, at, capsys):
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        deploy(s, repo, i)
    assert cli.main(["snooze", "p1", "--days", "3"]) == 0
    assert state(db, 1)["state"] == "snoozed"
    assert cli.main(["dismiss", "p1"]) == 0
    assert state(db, 1)["state"] == "dismissed"
    assert cli.main(["dismiss", "p77"]) == 1
    capsys.readouterr()
    assert cli.main(["stats", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dismissed"] == 1


def test_retention_prunes_old_turns_but_keeps_patterns(repo, db, at):
    at(0)
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        deploy(s, repo, i)
    at(100)
    Session(repo).turn("a fresh request about the docs site", [bash("npm run docs")])
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    assert conn.execute("SELECT count FROM patterns WHERE id = 1").fetchone()[0] == 3


def test_lazy_imports():
    """The hook runner must not pull in the matching code until a handler needs it."""
    code = (
        "import sys; sys.path.insert(0, 'src'); import skill_spotter.hookrunner; "
        "print(' '.join(sorted(m for m in sys.modules if m.startswith('skill_spotter'))))"
    )
    out = subprocess.run(
        [sys.executable, "-S", "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    for heavy in (
        "skill_spotter.patterns",
        "skill_spotter.recorder",
        "skill_spotter.suggest",
        "skill_spotter.capture.normalize_actions",
        "skill_spotter.lifecycle",
    ):
        assert heavy not in out
