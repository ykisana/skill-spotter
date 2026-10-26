"""Standing instructions repeated across prompts, offered for CLAUDE.md (ADR 0010)."""

from __future__ import annotations

import json
import os

import pytest
from helpers import Session, bash, edit, system_message

from skill_spotter import band, claude_code, cli, paths, rules, store


@pytest.fixture
def db(isolated_data_dir):
    return lambda: store.connect(paths.db_path(isolated_data_dir))


def make_repo(tmp_path, name):
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    return str(root)


# The same rule riding along with different tasks, as the user typed it (one typo included).
AUTHOR_PROMPTS = [
    "fix the failing ci job and push. Make sure i'm only author, no claude",
    "update the PR based on the review comments. make sure I'm only athor no claude",
    "rebase onto main and push my commit on top. Don't make claude an author",
]


def task(s, repo, prompt, i):
    return s.turn(prompt, [bash(f"git log -{i + 1}"), edit(f"{repo}/src/f{i}.py")])


def test_directives_keep_instructions_and_skip_questions():
    found = rules.directives(
        "fix the login bug.\nMake sure I'm the only author, no claude\n"
        "why does it not work? Don't touch the config files"
    )
    assert [text for text, _ in found] == [
        "Make sure I'm the only author, no claude",
        "Don't touch the config files",
    ]
    assert found[0][1] == ["author", "claude"]  # "claude" stays; "make sure", "only" are cues


def test_text_between_two_apostrophes_is_not_dropped_as_a_quote():
    # The shared normalizer reads 'm the only ... else' as a quoted string.
    line = "I'm the only author. Never add Claude when pushing on top of someone else's PR"
    assert {"author", "claude"} <= set(rules.key_words(line))


def test_pasted_blocks_are_not_instructions():
    prompt = 'look at this\n<pasted_content id="1">\nnever do X, always Y\n</pasted_content id="1">'
    assert rules.directives(prompt) == []


def test_a_rule_repeated_across_projects_is_suggested_for_claude_md(tmp_path, db):
    out = None
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        repo = make_repo(tmp_path, f"proj{i}")
        out = task(Session(repo), repo, prompt, i)
        if i < 2:
            assert out["stop"] == ""
    msg = system_message(out["stop"])
    assert msg == (
        "skill-spotter: you've asked for this in 3 prompts across 3 projects: "
        '"Don\'t make claude an author". To add it to CLAUDE.md, run /skill-spotter:rule r1'
    )
    row = db().execute("SELECT key, state FROM rules").fetchone()
    assert tuple(row) == ("author claude", "suggested")
    # The typo joined the rule as "author".
    words = [json.loads(r[0]) for r in db().execute("SELECT words_json FROM directives")]
    assert all("author" in w for w in words)


def test_one_session_repeating_itself_is_not_a_rule(tmp_path, db):
    repo = make_repo(tmp_path, "solo")
    s = Session(repo)
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        assert task(s, repo, prompt, i)["stop"] == ""
    assert db().execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0


def test_a_rule_already_in_claude_md_is_not_suggested(tmp_path, db):
    home = os.path.expanduser("~")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "CLAUDE.md"), "w") as f:
        f.write(
            "# Preferences\n\n- Commits: I'm the only author. Never add Claude as co-author, "
            "and keep someone else's commits as they are.\n"
        )
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        repo = make_repo(tmp_path, f"proj{i}")
        assert task(Session(repo), repo, prompt, i)["stop"] == ""
    assert db().execute("SELECT state FROM rules").fetchone()[0] == "candidate"


def test_a_one_project_rule_stays_in_its_project(tmp_path, db):
    repo, other = make_repo(tmp_path, "api"), make_repo(tmp_path, "web")
    prompts = [
        "add the endpoint. Keep migrations reversible",
        "rename the column. make sure the migrations stay reversible",
    ]
    for i, prompt in enumerate(prompts):
        assert task(Session(repo), repo, prompt, i)["stop"] == ""
    out = task(Session(repo), repo, "drop the old table, keep the migrations reversible", 2)
    assert system_message(out["stop"]).startswith(
        "skill-spotter: you've asked for this in 3 prompts in 3 sessions:"
    )
    # Back to unsuggested: it's offered in its own project, never in another one.
    conn = db()
    conn.execute("UPDATE rules SET state = 'candidate'")
    conn.execute("DELETE FROM events")
    now = conn.execute("SELECT MAX(ts) FROM directives").fetchone()[0]
    assert rules.maybe_suggest(conn, other, "sess-elsewhere", [], now) is None
    assert rules.maybe_suggest(conn, repo, "sess-here", [], now) is not None


def test_show_accept_snooze_dismiss(tmp_path, db, capsys):
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        repo = make_repo(tmp_path, f"proj{i}")
        task(Session(repo), repo, prompt, i)
    capsys.readouterr()
    assert cli.main(["show", "r1", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["kind"] == "rule" and d["words"] == ["author", "claude"]
    assert (d["count"], d["sessions"], len(d["projects"])) == (3, 3, 3)
    assert d["scope"] == "personal"
    assert d["target_path"] == os.path.expanduser("~/.claude/CLAUDE.md")
    assert d["instructions"][0]["said"] == "Don't make claude an author"
    assert "rebase onto main" in d["instructions"][0]["in_prompt"]

    assert cli.main(["snooze", "r1", "--days", "3"]) == 0
    assert db().execute("SELECT state FROM rules").fetchone()[0] == "snoozed"
    target = os.path.expanduser("~/.claude/CLAUDE.md")
    assert cli.main(["accept", "r1", target]) == 0
    assert tuple(db().execute("SELECT state, file_path FROM rules").fetchone()) == (
        "accepted",
        target,
    )
    assert cli.main(["dismiss", "r9"]) == 1
    capsys.readouterr()
    assert cli.main(["stats"]) == 0
    assert "standing instructions: 1 · suggested: 1 · added to CLAUDE.md: 1" in (
        capsys.readouterr().out
    )


def test_status_lists_rules(tmp_path, capsys):
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        repo = make_repo(tmp_path, f"proj{i}")
        task(Session(repo), repo, prompt, i)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "standing instructions (for CLAUDE.md):" in out
    assert "r1     Don't make claude an author" in out
    assert "3x in 3 sessions, 3 projects  [suggested]" in out


def test_session_end_snoozes_an_unanswered_rule(tmp_path, db):
    s = None
    for i, prompt in enumerate(AUTHOR_PROMPTS):
        repo = make_repo(tmp_path, f"proj{i}")
        s = Session(repo)
        task(s, repo, prompt, i)
    s.end()
    assert tuple(db().execute("SELECT state, snooze_count FROM rules").fetchone()) == (
        "snoozed",
        1,
    )


def test_backfill_reads_turns_recorded_before_rules_existed(tmp_path, db):
    for i, prompt in enumerate(AUTHOR_PROMPTS[:2]):
        repo = make_repo(tmp_path, f"proj{i}")
        task(Session(repo), repo, prompt, i)
    conn = db()
    conn.execute("DELETE FROM directives")
    conn.execute("DELETE FROM rules")
    now = conn.execute("SELECT MAX(ts_start) FROM turns").fetchone()[0] + 1
    assert rules.backfill(conn, now) == 2
    assert rules.backfill(conn, now) == 0  # once only
    repo = make_repo(tmp_path, "proj2")
    out = task(Session(repo), repo, AUTHOR_PROMPTS[2], 2)
    assert "/skill-spotter:rule r" in system_message(out["stop"])


def test_band_parses_a_rule_suggestion():
    d = band.parse(rules.message(4, 5, 4, 3, "make sure I'm the only author"))
    assert d["id"] == "r4" and d["name"] is None
    assert d["draft"] == "/skill-spotter:rule r4"
    assert d["action"] == "Add to CLAUDE.md"
    assert d["summary"] == (
        "You've asked for this in 5 prompts across 3 projects: \"make sure I'm the only author\""
    )


def test_instruction_files_follow_claude_code_memory_locations(tmp_path):
    home = os.path.expanduser("~")
    repo = make_repo(tmp_path, "acme")
    sub = os.path.join(repo, "pkg")
    files = {
        os.path.join(home, ".claude", "CLAUDE.md"): "",
        os.path.join(home, ".claude", "rules", "git.md"): "",
        os.path.join(repo, "CLAUDE.md"): "",
        os.path.join(repo, "CLAUDE.local.md"): "",
        os.path.join(repo, "AGENTS.md"): "",
        os.path.join(repo, ".claude", "CLAUDE.md"): "",
        os.path.join(repo, ".claude", "rules", "api", "style.md"): "",
        os.path.join(sub, "CLAUDE.md"): "",
        os.path.join(repo, ".claude", "rules", "notes.txt"): "",
    }
    for path in files:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    # A symlink loop in a rules folder must not hang the Stop hook.
    os.symlink(
        os.path.join(repo, ".claude", "rules"), os.path.join(repo, ".claude", "rules", "loop")
    )
    found = claude_code.instruction_files(sub)
    expected = [p for p in files if p.endswith(".md")]
    assert set(expected) <= set(found)
    assert not any(p.endswith(".txt") for p in found)


def test_stop_event_carries_instruction_files(tmp_path):
    repo = make_repo(tmp_path, "acme")
    open(os.path.join(repo, "CLAUDE.md"), "w").close()
    event = claude_code.normalize("Stop", {"session_id": "s", "cwd": repo, "prompt_id": "p"})
    assert os.path.join(repo, "CLAUDE.md") in event["instruction_files"]
