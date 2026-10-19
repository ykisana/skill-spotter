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
    d = band.parse(
        "[skill-spotter] You've done this 5 times (pattern p42). Run /skill-spotter:draft p42 "
        "to save it as /weekly-changelog."
    )
    assert (
        d["id"] == "p42"
        and d["name"] == "weekly-changelog"
        and d["draft"] == "/skill-spotter:draft p42"
    )
    w = band.parse(
        "[skill-spotter] You've done this 3-step workflow in 3 sessions (workflow w7: /a → /b). "
        "Run /skill-spotter:draft w7 to save it as /ship-flow."
    )
    assert w["id"] == "w7" and w["name"] == "ship-flow"


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
    cli.main(["band", "pending", "--session", s2.session_id])  # popped: empty now
    assert capsys.readouterr().out.strip() == ""


def test_hooks_json_declares_the_mod_module():
    from conftest import ROOT

    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    assert config["modules"] == ["./register.ts"]
    assert (ROOT / "hooks" / "register.ts").is_file()
