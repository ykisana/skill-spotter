"""The hook contract (SPEC section 14): exit 0, print nothing but the suggestion, never
a decision, and survive every kind of bad input or broken environment."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest
from conftest import ROOT

from skill_spotter import claude_code, handlers, hookrunner

FIXTURES = ROOT / "tests" / "fixtures" / "hook_inputs"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"

# fixture name -> the script hooks.json runs for that event
FIXTURE_SCRIPTS = {
    "user_prompt_submit": "on_prompt.py",
    "post_tool_use_bash": "on_action.py",
    "post_tool_use_edit_subagent": "on_action.py",
    "post_tool_use_failure": "on_action.py",
    "stop": "on_stop.py",
    "config_change_skills": "on_config_change.py",
    "user_prompt_expansion": "on_expansion.py",
    "session_end": "on_session_end.py",
}
SCRIPTS = sorted(set(FIXTURE_SCRIPTS.values()))


def fixture(name):
    return (FIXTURES / f"{name}.json").read_text()


def run_hook(script, stdin, data_dir, extra_env=None):
    """Run a hook script the way Claude Code does: separate process, JSON on stdin."""
    env = {k: v for k, v in os.environ.items() if k != handlers.DEBUG_SUGGEST_ENV}
    env["SKILL_SPOTTER_DATA"] = str(data_dir)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


# --- the real scripts, as separate processes ----------------------------------------


@pytest.mark.parametrize("name,script", sorted(FIXTURE_SCRIPTS.items()))
def test_every_hook_exits_zero_and_prints_nothing(name, script, isolated_data_dir):
    result = run_hook(script, fixture(name), isolated_data_dir)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize(
    "stdin",
    ["", "not json", "[1, 2, 3]", '{"hook_event_name": 7}', "{" * 5000],
    ids=["empty", "garbage", "list", "bad-event-type", "deep-garbage"],
)
def test_malformed_input_fails_open(script, stdin, isolated_data_dir):
    result = run_hook(script, stdin, isolated_data_dir)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("script", SCRIPTS)
def test_unusable_data_dir_fails_open(script, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("a file where a directory should be")
    result = run_hook(script, fixture("stop"), blocker / "data")
    assert result.returncode == 0
    assert result.stdout == ""


def test_debug_suggestion_is_a_system_message(isolated_data_dir):
    env = {handlers.DEBUG_SUGGEST_ENV: "1"}
    result = run_hook("on_stop.py", fixture("stop"), isolated_data_dir, env)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert list(output) == ["systemMessage"]
    assert "sess-1" in output["systemMessage"]


def test_debug_switch_never_leaks_from_other_hooks(isolated_data_dir):
    env = {handlers.DEBUG_SUGGEST_ENV: "1"}
    for name, script in FIXTURE_SCRIPTS.items():
        if script != "on_stop.py":
            assert run_hook(script, fixture(name), isolated_data_dir, env).stdout == ""


# --- the adapter: Claude Code input -> neutral events ----------------------------------


def normalized(name):
    payload = json.loads(fixture(name))
    return claude_code.normalize(payload["hook_event_name"], payload)


def test_every_event_has_the_common_fields():
    for name in FIXTURE_SCRIPTS:
        event = normalized(name)
        assert event["editor"] == "claude-code"
        assert event["session_id"] == "sess-1"
        assert {"kind", "prompt_id", "cwd", "agent_id"} <= set(event)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("user_prompt_submit", {"kind": "prompt", "prompt": "pull this week's merged PRs "
                                "and write the changelog summary for #eng"}),
        ("post_tool_use_bash", {"kind": "action", "tool_name": "Bash", "failed": False}),
        ("post_tool_use_failure", {"kind": "action", "tool_name": "Bash", "failed": True}),
        ("post_tool_use_edit_subagent", {"kind": "action", "agent_id": "agent-7"}),
        ("stop", {"kind": "turn_end"}),
        ("config_change_skills", {"kind": "skill_change", "file_path":
                                  "/tmp/scratch-repo/.claude/skills/weekly-changelog/SKILL.md"}),
        ("user_prompt_expansion", {"kind": "command_used", "command_name": "weekly-changelog"}),
        ("session_end", {"kind": "session_end", "reason": "prompt_input_exit"}),
    ],
)
def test_event_specific_fields(name, expected):
    event = normalized(name)
    assert {k: event[k] for k in expected} == expected


def test_tool_response_is_not_kept():
    assert "tool_response" not in normalized("post_tool_use_bash")


# --- the runner, in-process ------------------------------------------------------------


def run_in_process(monkeypatch, hook_event, handler, stdin=None):
    monkeypatch.setitem(claude_code.HANDLERS, hook_event, handler)
    out = io.StringIO()
    hookrunner.run(hook_event, stdin=io.StringIO(stdin or fixture("stop")), stdout=out)
    return out.getvalue()


def test_one_script_for_two_events_dispatches_on_hook_event_name(monkeypatch):
    seen = []
    monkeypatch.setitem(claude_code.HANDLERS, "PostToolUseFailure", seen.append)
    # hook_event=None is what on_action.py passes: the runner must read it from the input
    hookrunner.run(None, stdin=io.StringIO(fixture("post_tool_use_failure")), stdout=io.StringIO())
    assert [e["failed"] for e in seen] == [True]


@pytest.mark.parametrize(
    "result", [{"decision": "block", "reason": "keep going"}, {"systemMessage": "x"}, 42, ""]
)
def test_only_suggestion_text_is_ever_rendered(monkeypatch, result):
    assert run_in_process(monkeypatch, "Stop", lambda event: result) == ""


@pytest.mark.parametrize("hook_event", [e for e in claude_code.HANDLERS if e != "Stop"])
def test_other_events_never_print(monkeypatch, hook_event):
    assert run_in_process(monkeypatch, hook_event, lambda event: "leak") == ""


def test_handler_crash_is_logged_not_raised(monkeypatch, isolated_data_dir):
    def boom(event):
        raise RuntimeError("boom")

    assert run_in_process(monkeypatch, "Stop", boom) == ""
    log = (isolated_data_dir / "logs" / "errors.log").read_text()
    assert "RuntimeError: boom" in log


# --- hooks.json ---------------------------------------------------------------------


def hook_entries():
    config = json.loads(HOOKS_JSON.read_text())["hooks"]
    for hook_event, groups in config.items():
        for group in groups:
            for hook in group["hooks"]:
                yield hook_event, group, hook


def test_hooks_json_covers_every_handled_event():
    configured = {hook_event for hook_event, _, _ in hook_entries()}
    assert configured == set(claude_code.HANDLERS)


def test_hooks_use_exec_form_and_existing_scripts():
    for _event, _group, hook in hook_entries():
        assert hook["type"] == "command"
        assert hook["command"] == "python3"
        (script,) = hook["args"]
        assert script.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/")
        assert (ROOT / script.replace("${CLAUDE_PLUGIN_ROOT}/", "")).is_file()


def test_only_tool_hooks_are_async():
    for hook_event, _group, hook in hook_entries():
        assert hook.get("async", False) == (hook_event in ("PostToolUse", "PostToolUseFailure"))


def test_config_change_only_watches_skills():
    for hook_event, group, _hook in hook_entries():
        if hook_event == "ConfigChange":
            assert group["matcher"] == "skills"


def test_session_end_fits_its_shared_budget():
    for hook_event, _group, hook in hook_entries():
        if hook_event == "SessionEnd":
            assert hook["timeout"] <= 1.5
