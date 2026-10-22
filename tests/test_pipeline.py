"""End-to-end through the real hook runner: record → match → suggest (M1 done criteria)."""

from __future__ import annotations

import json
import sqlite3

import pytest
from helpers import Session, bash, edit, read, system_message

from skill_spotter import paths, store


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "acme-api"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    return str(root)


@pytest.fixture
def db(isolated_data_dir):
    def open_db():
        return store.connect(paths.db_path(isolated_data_dir))

    return open_db


CHANGELOG_PROMPTS = [
    "write the changelog from merged pull requests this week",
    "changelog from this week's merged PRs please, for the eng channel",
    "write release notes for merged pull requests this week",
    "update the changelog with the merged pull requests",
]


def changelog_turn(session, repo, prompt, since="2026-10-08"):
    return session.turn(
        prompt,
        [
            bash("git status"),
            bash(f"gh pr list --state merged --search 'merged:>={since}' --json number,title"),
            read(f"{repo}/CHANGELOG.md"),
            edit(f"{repo}/CHANGELOG.md"),
            bash("git add CHANGELOG.md && git commit -m 'changelog'"),
        ],
    )


def login_fix_turn(session, repo):
    return session.turn(
        "fix the failing login test in the auth module",
        [read(f"{repo}/src/auth.py"), edit(f"{repo}/src/auth.py"), bash("npm run test")],
    )


def test_same_task_three_times_across_two_sessions_with_different_wording(repo, db):
    s1, s2 = Session(repo), Session(repo)
    out1 = changelog_turn(
        s1, repo, "pull this week's merged PRs and write the changelog summary for #eng"
    )
    login_fix_turn(s1, repo)
    out2 = changelog_turn(
        s1, repo, "write release notes from the pull requests merged since monday", "2026-10-13"
    )
    out3 = changelog_turn(
        s2, repo, "update CHANGELOG.md with what got merged this week", "2026-10-15"
    )

    assert out1["stop"] == "" and out2["stop"] == ""  # 1st and 2nd time: nothing yet
    message = system_message(out3["stop"])
    assert message is not None
    # Names skill-spotter, says how often, and quotes the latest prompt (ADR 0009).
    assert message.startswith("skill-spotter: you've repeated this 3 times: ")
    assert '"update CHANGELOG.md with what got merged this week"' in message
    assert "run /skill-spotter:draft p" in message

    conn = db()
    rows = conn.execute(
        "SELECT pattern_id, prompt_redacted FROM turns ORDER BY ts_start"
    ).fetchall()
    changelog_patterns = {r[0] for r in rows if "login" not in r[1]}
    login_pattern = {r[0] for r in rows if "login" in r[1]}
    assert len(changelog_patterns) == 1
    assert changelog_patterns.isdisjoint(login_pattern)
    pattern = conn.execute(
        "SELECT * FROM patterns WHERE id = ?", (changelog_patterns.pop(),)
    ).fetchone()
    assert pattern["state"] == "suggested"
    assert pattern["count"] == 3 and pattern["session_count"] == 2
    assert f"save it as /{pattern['suggested_name']}," in message


def test_no_hook_prints_anything_but_the_stop_suggestion(repo):
    s1, s2 = Session(repo), Session(repo)
    outs = [
        changelog_turn(s1, repo, "write the changelog from merged pull requests this week"),
        changelog_turn(
            s1, repo, "changelog from this week's merged PRs please, for the eng channel"
        ),
        changelog_turn(s2, repo, "write release notes for merged pull requests this week"),
    ]
    for out in outs:
        assert out["prompt"] == "" and out["actions"] == ""
    assert outs[-1]["stop"]  # only this one speaks
    assert "decision" not in json.loads(outs[-1]["stop"])


def test_one_suggestion_per_session(repo):
    s1, s2 = Session(repo), Session(repo)
    outs = [changelog_turn(s, repo, CHANGELOG_PROMPTS[i]) for i, s in enumerate((s1, s1, s2))]
    assert outs[-1]["stop"]
    # a different task that repeats enough doesn't get a second suggestion in session s2
    for i, s in enumerate((s1, s1, s2)):
        out = s.turn(
            f"fix the failing login test in the auth module, attempt {'abc'[i]}",
            [read(f"{repo}/src/auth.py"), edit(f"{repo}/src/auth.py"), bash("npm run test")],
        )
    assert out["stop"] == ""
    s3 = Session(repo)
    nxt = s3.turn(
        "fix the failing login test in the auth module again",
        [read(f"{repo}/src/auth.py"), edit(f"{repo}/src/auth.py"), bash("npm run test")],
    )
    assert "4 times" in system_message(nxt["stop"])  # new session: allowed


def test_needs_two_sessions(repo):
    s = Session(repo)
    outs = [changelog_turn(s, repo, p) for p in CHANGELOG_PROMPTS]
    assert all(o["stop"] == "" for o in outs)


def test_paused_means_no_suggestion_but_still_recording(repo, db):
    conn = db()
    store.set_setting(conn, "enabled", "0")
    conn.close()
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        out = changelog_turn(s, repo, CHANGELOG_PROMPTS[i])
    assert out["stop"] == ""
    assert db().execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 3


def test_quick_exact_repeat_in_a_session_is_skipped(repo, db):
    s = Session(repo)
    for _ in range(3):
        changelog_turn(s, repo, CHANGELOG_PROMPTS[0])
    assert db().execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1


def test_filtered_prompts_are_not_recorded(repo, db):
    s = Session(repo)
    s.turn("/review 42", [bash("gh pr view 42")])
    s.turn("yes do it", [bash("npm run test")])
    s.turn("<task-notification>agent finished</task-notification>", [bash("ls")])
    s.turn(
        "check the status of the build pipeline",
        [bash("gh run list")],
        crons=["check the status of the build pipeline"],
    )
    s.turn("check the status of the build pipeline", [bash("gh run list")])  # matches the cron now
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1


def test_secrets_never_reach_the_database(repo, isolated_data_dir):
    s = Session(repo)
    s.turn(
        "deploy using token ghp_abcdefghijklmnopqrstuvwxyz0123456789 to staging now",
        [
            bash(
                "API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz "
                "curl -H 'Authorization: Bearer abcdefghijklmnop123' https://x.io"
            )
        ],
    )
    raw = (isolated_data_dir / "skill-spotter.db").read_bytes()
    wal = isolated_data_dir / "skill-spotter.db-wal"
    if wal.exists():
        raw += wal.read_bytes()
    for secret in (b"ghp_abcdefghij", b"sk-ant-api03", b"abcdefghijklmnop123"):
        assert secret not in raw


def test_stop_is_idempotent(repo, db):
    s = Session(repo)
    out = changelog_turn(s, repo, "write the changelog from merged pull requests this week")
    s._send("Stop", prompt_id=out["prompt_id"], session_crons=[])
    conn = db()
    assert conn.execute("SELECT count FROM patterns").fetchone()[0] == 1


def test_generic_patterns_are_never_suggested(repo, db):
    s = [Session(repo) for _ in range(4)]
    # many different tasks so token statistics are meaningful
    for i in range(12):
        s[i % 4].turn(
            f"implement feature number {i} in module {i}",
            [edit(f"{repo}/src/m{i}.py"), bash("git status")],
        )
    # exploration-only turns with varied wording: nothing meaningful repeats
    outs = [
        s[i % 4].turn(prompt, [bash("git status"), read(f"{repo}/src/a.py"), bash("ls -la")])
        for i, prompt in enumerate(
            [
                "look around the codebase for me",
                "what is going on in this repository",
                "show me the current state of things",
            ]
        )
    ]
    assert all(o["stop"] == "" for o in outs)


def test_chit_chat_is_never_suggested(repo, db):
    # First live run (ADR 0009): "hey claude, say hi" three times in two sessions,
    # one of them with an unrelated check in between, became /sqlite3.
    s1, s2 = Session(repo), Session(repo)
    outs = [
        s1.turn("hey claude can you say hi", [bash("sqlite3 x.db 'select 1'")]),
        s2.turn("hey claude, say hi", []),
        s2.turn("hello claude, can you say hi please", []),
        s1.turn("hey claude, say hi", []),
    ]
    assert all(o["stop"] == "" for o in outs)


def test_addressing_claude_is_not_a_task_word():
    from skill_spotter.capture import normalize_text

    assert normalize_text.normalize("hey claude, say hi") == []
    assert normalize_text.normalize("claude, update the changelog") == ["update", "changelog"]


def test_danger_flag_reaches_the_pattern(repo, db):
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        s.turn(
            f"amend the last commit and force push the branch ({i})",
            [bash("git commit --amend --no-edit"), bash("git push --force-with-lease")],
        )
    assert db().execute("SELECT danger FROM patterns").fetchone()[0] == 1


def test_corrupt_db_mid_session_is_silent(repo, isolated_data_dir):
    s = Session(repo)
    changelog_turn(s, repo, "write the changelog from merged pull requests this week")
    for f in isolated_data_dir.glob("skill-spotter.db*"):
        f.write_bytes(b"garbage" * 100)
    out = changelog_turn(s, repo, "write the changelog from merged pull requests this week")
    assert out == {**out, "prompt": "", "actions": "", "stop": ""}
    assert (isolated_data_dir / "logs" / "errors.log").exists()


def test_suggest_via_claude_hands_context_to_next_prompt(repo, db):
    conn = db()
    store.set_setting(conn, "suggest_via", "claude")
    conn.close()
    s1, s2 = Session(repo), Session(repo)
    for i, s in enumerate((s1, s1, s2)):
        out = changelog_turn(s, repo, CHANGELOG_PROMPTS[i])
    assert out["stop"] == ""  # nothing shown directly
    nxt = s2.turn("now something else entirely different", [])
    context = json.loads(nxt["prompt"])["hookSpecificOutput"]["additionalContext"]
    assert "/skill-spotter:draft p" in context
    assert s2.turn("and another unrelated request here", [])["prompt"] == ""  # only once


def test_schema_upgrade_from_v1(isolated_data_dir):
    path = paths.db_path(isolated_data_dir)
    path.parent.mkdir(parents=True)
    raw = sqlite3.connect(path)
    raw.executescript(store.MIGRATIONS[0] + "\nPRAGMA user_version = 1;")
    raw.close()
    conn = store.connect(path)
    assert store.schema_version(conn) == store.SCHEMA_VERSION
