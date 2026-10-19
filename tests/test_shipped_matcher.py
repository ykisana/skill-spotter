"""The matcher the Method Lab ships (config/method.json) on the key scenarios.

The other tests pin the plain rule; these run the shipped config, so a re-tuned model
that breaks basic behaviour (e.g. learning the synthetic timeline) fails here.
"""

from __future__ import annotations

import json

import pytest
from helpers import Session, bash, edit, read, system_message

from skill_spotter import paths, store
from skill_spotter.match import fused

SHIPPED = fused.CONFIG_DIR / "method.json"
pytestmark = pytest.mark.skipif(not SHIPPED.exists(), reason="no shipped config")


@pytest.fixture(autouse=True)
def shipped(monkeypatch):
    monkeypatch.delenv("SKILL_SPOTTER_METHOD_CONFIG", raising=False)
    assert fused.load_config()["fusion"] == json.loads(SHIPPED.read_text())["fusion"]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "app"
    (root / ".git").mkdir(parents=True)
    return str(root)


@pytest.fixture
def db(isolated_data_dir):
    return lambda: store.connect(paths.db_path(isolated_data_dir))


def login(s, repo, prompt):
    return s.turn(
        prompt, [read(f"{repo}/src/auth.py"), edit(f"{repo}/src/auth.py"), bash("npm run test")]
    )


def test_repeats_with_identical_actions_join_one_pattern(repo, db):
    s1, s2, s3 = Session(repo), Session(repo), Session(repo)
    login(s1, repo, "fix the failing login test in the auth module")
    login(s1, repo, "the login test in auth is failing again, fix it")
    login(s2, repo, "fix that flaky login test in the auth module please")
    out = login(s3, repo, "auth module login test broke, fix it")
    assert db().execute("SELECT COUNT(DISTINCT pattern_id) FROM turns").fetchone()[0] == 1
    assert (
        "4 times" in (system_message(out["stop"]) or "")
        or db().execute("SELECT state FROM patterns").fetchone()[0] == "suggested"
    )


def test_different_questions_with_the_same_single_command_stay_apart(repo, db):
    sessions = [Session(repo) for _ in range(3)]
    questions = [
        (
            "how many users signed up last week?",
            "psql $DATABASE_URL -c 'select count(*) from users'",
        ),
        (
            "which index is the orders query missing?",
            "psql $DATABASE_URL -c 'explain select * from orders'",
        ),
        (
            "are there duplicate emails in the accounts table?",
            "psql $DATABASE_URL -c 'select email from accounts'",
        ),
    ]
    outs = [s.turn(q, [bash(cmd)]) for s, (q, cmd) in zip(sessions, questions)]
    assert all(o["stop"] == "" for o in outs)
    assert db().execute("SELECT COUNT(DISTINCT pattern_id) FROM turns").fetchone()[0] == 3


def test_same_task_three_times_two_sessions_suggests_once(repo, db):
    s1, s2 = Session(repo), Session(repo)
    prompts = [
        "pull this week's merged PRs and write the changelog summary for #eng",
        "write release notes from the pull requests merged since monday",
        "update CHANGELOG.md with what got merged this week",
    ]
    outs = []
    for s, p in zip((s1, s1, s2), prompts):
        outs.append(
            s.turn(
                p,
                [
                    bash("gh pr list --state merged --json number,title"),
                    read(f"{repo}/CHANGELOG.md"),
                    edit(f"{repo}/CHANGELOG.md"),
                    bash("git add CHANGELOG.md && git commit -m changelog"),
                ],
            )
        )
    assert [bool(o["stop"]) for o in outs] == [False, False, True]


def test_repeated_questions_without_meaningful_actions_join(repo, db):
    """Exploration-only repeats (only git log / reads) match on their identical wording."""
    for s in (Session(repo), Session(repo), Session(repo)):
        s.turn(
            "list the commits since the last tag",
            [bash("git describe --tags --abbrev=0"), bash("git log v1.0.0..HEAD --oneline")],
        )
    assert db().execute("SELECT COUNT(DISTINCT pattern_id) FROM turns").fetchone()[0] == 1
