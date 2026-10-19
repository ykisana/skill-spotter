"""M6 skill verification, with a fake `claude` runner (no network, no tokens)."""

from __future__ import annotations

import json
import subprocess

from skill_spotter import cli, paths, store, verify

SKILL = """---
description: Update CHANGELOG.md with the commits merged since the last release tag.
---

1. Find the last tag.
2. Summarize commits since it into CHANGELOG.md.
"""


def fake_runner(trigger_words, revised=None):
    """Imitate `claude -p`: generation returns prompts, trigger runs fire on keywords."""

    def run(cmd, **kwargs):
        prompt = cmd[2]
        if "--tools" in cmd and cmd[cmd.index("--tools") + 1] == "Skill":
            fire = any(w in prompt for w in trigger_words)
            content = (
                [{"type": "tool_use", "name": "Skill", "input": {"skill": "update-changelog"}}]
                if fire
                else []
            )
            out = json.dumps({"type": "assistant", "message": {"content": content}})
        elif "triggers poorly" in prompt:
            out = json.dumps({"result": json.dumps({"description": revised or "x"})})
        else:
            out = json.dumps(
                {
                    "result": json.dumps(
                        {
                            "should": [
                                "update the changelog",
                                "add release notes to CHANGELOG",
                                "changelog since v1.2",
                            ],
                            "should_not": ["bump the version", "write the README", "tag a release"],
                        }
                    )
                }
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    return run


def make_skill(tmp_path, text=SKILL):
    skill = tmp_path / "repo" / ".claude" / "skills" / "update-changelog" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(text)
    return skill


def test_scores_trigger_precision_and_recall(tmp_path, isolated_data_dir):
    skill = make_skill(tmp_path)
    conn = store.connect(paths.db_path(isolated_data_dir))
    result = verify.verify(conn, skill, n=3, runner=fake_runner(["changelog", "CHANGELOG", "tag"]))
    assert result["recall"] == 1.0 and result["precision"] == 0.75
    assert result["false_triggers"] == ["tag a release"]
    assert verify.latest_scores(conn)[str(skill)]["n"] == 6


def test_revise_rewrites_description_when_f1_is_low(tmp_path, isolated_data_dir):
    skill = make_skill(tmp_path)
    conn = store.connect(paths.db_path(isolated_data_dir))
    result = verify.verify(
        conn,
        skill,
        n=3,
        revise=True,
        runner=fake_runner(["release"], revised="Changelog updates only, not version bumps."),
    )
    assert result["revised"] and "Changelog updates only" in skill.read_text()


def test_manual_only_skills_are_not_trigger_tested(tmp_path, isolated_data_dir):
    skill = make_skill(
        tmp_path, SKILL.replace("---\n\n1.", "disable-model-invocation: true\n---\n\n1.", 1)
    )
    conn = store.connect(paths.db_path(isolated_data_dir))
    assert "manual-only" in verify.verify(conn, skill, runner=fake_runner([]))["skipped"]


def test_status_shows_trigger_score(tmp_path, isolated_data_dir, capsys, monkeypatch):
    conn = store.connect(paths.db_path(isolated_data_dir))
    skill = make_skill(tmp_path)
    conn.execute(
        "INSERT INTO patterns(project_key, first_seen, last_seen, state, suggested_name, "
        "skill_path, count, "
        "session_count) VALUES('p', 0, 0, 'accepted', 'update-changelog', ?, 3, 2)",
        (str(skill),),
    )
    verify.verify(conn, skill, n=3, runner=fake_runner(["changelog", "CHANGELOG"]))
    assert cli.main(["status"]) == 0
    assert "trigger F1 1.00 (6 prompts)" in capsys.readouterr().out
