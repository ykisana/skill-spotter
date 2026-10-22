"""M7 band hand-off: with the mod registered, Stop queues suggestions instead of printing."""

from __future__ import annotations

import json

from helpers import Session, bash, edit, read

from skill_spotter import band, cli


def changelog(s, repo, prompt):
    return s.turn(
        prompt,
        [
            bash("gh pr list --state merged"),
            read(f"{repo}/CHANGELOG.md"),
            edit(f"{repo}/CHANGELOG.md"),
        ],
    )


def test_parse_suggestion_text():
    from skill_spotter import suggest

    d = band.parse(suggest.message(42, 5, "weekly-changelog", "write the weekly changelog."))
    assert d == {
        "text": d["text"],
        "summary": 'You\'ve repeated this 5 times: "write the weekly changelog."',
        "id": "p42",
        "name": "weekly-changelog",
        "draft": "/skill-spotter:draft p42",
    }
    w = band.parse(
        "skill-spotter: you've run these 2 steps together in 3 sessions: /a → /b. "
        "To save them as /ship-flow, run /skill-spotter:draft w7"
    )
    assert w["id"] == "w7" and w["name"] == "ship-flow"
    assert w["summary"] == "You've run these 2 steps together in 3 sessions: /a → /b"


def test_band_session_gets_no_system_message_but_a_pending_band(
    tmp_path, isolated_data_dir, capsys
):
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    repo = str(repo)
    s1, s2 = Session(repo), Session(repo)
    changelog(s1, repo, "write the changelog from merged pull requests this week")
    changelog(s1, repo, "changelog from this week's merged PRs please")
    assert cli.main(["band", "register", "--session", s2.session_id]) == 0
    out = changelog(s2, repo, "write release notes for merged pull requests")
    assert out["stop"] == ""  # the band shows it instead
    capsys.readouterr()
    assert cli.main(["band", "pending", "--session", s2.session_id]) == 0
    pending = json.loads(capsys.readouterr().out)
    assert pending["id"].startswith("p") and pending["draft"].startswith("/skill-spotter:draft p")
    # The mod can't read CLAUDE_PLUGIN_DATA, so the hook names the folder "Not now" acts on.
    assert pending["data_dir"] == str(isolated_data_dir)
    cli.main(["band", "pending", "--session", s2.session_id])  # popped: empty now
    assert capsys.readouterr().out.strip() == ""


def test_hooks_json_declares_the_mod_module():
    from conftest import ROOT

    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    assert config["modules"] == ["./register.ts"]
    assert (ROOT / "hooks" / "register.ts").is_file()


def test_mailbox_round_trip():
    assert not band.is_active("s1")
    band.register("s1")
    assert band.is_active("s1") and not band.is_active("s2")
    assert band.pop("s1") is None
    band.queue("s1", "plain text", "/data")
    assert band.pop("s1") == {"text": "plain text", "data_dir": "/data"}
    assert band.pop("s1") is None


def test_session_ids_cannot_escape_the_mailbox():
    band.register("../../etc/x")
    assert [p.name for p in band.band_dir().iterdir()] == ["______etc_x.on"]


def test_band_cli_never_touches_the_database(isolated_data_dir, capsys):
    assert cli.main(["band", "register", "--session", "s1"]) == 0
    assert cli.main(["band", "pending", "--session", "s1"]) == 0
    assert capsys.readouterr().out.strip() == ""
    assert not isolated_data_dir.exists()


def test_session_end_clears_the_mailbox(tmp_path):
    s = Session(str(tmp_path))
    band.register(s.session_id)
    band.queue(s.session_id, "text", "/data")
    s.end()
    assert not band.is_active(s.session_id) and band.pop(s.session_id) is None


def test_register_prunes_files_of_sessions_that_never_ended():
    import os
    import time

    band.register("old")
    old = band.band_dir() / "old.on"
    stale = time.time() - 8 * 86400
    os.utime(old, (stale, stale))
    band.register("new")
    assert not band.is_active("old") and band.is_active("new")


def test_hook_without_band_still_prints_the_system_message(tmp_path):
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    repo = str(repo)
    s1, s2 = Session(repo), Session(repo)
    changelog(s1, repo, "write the changelog from merged pull requests this week")
    changelog(s1, repo, "changelog from this week's merged PRs please")
    out = changelog(s2, repo, "write release notes for merged pull requests")
    assert "skill-spotter" in out["stop"]
    assert band.pop(s2.session_id) is None
