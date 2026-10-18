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


def stop_input():
    return (FIXTURES / "stop.json").read_text()


# --- the real script, as a separate process ---------------------------------------


def test_stop_exits_zero_and_prints_nothing(isolated_data_dir):
    result = run_hook("on_stop.py", stop_input(), isolated_data_dir)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "stdin",
    ["", "not json", "[1, 2, 3]", '{"hook_event_name": 7}', "{" * 5000],
    ids=["empty", "garbage", "list", "bad-event-type", "deep-garbage"],
)
def test_malformed_input_fails_open(stdin, isolated_data_dir):
    result = run_hook("on_stop.py", stdin, isolated_data_dir)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_unusable_data_dir_fails_open(tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("a file where a directory should be")
    result = run_hook("on_stop.py", stop_input(), blocker / "data")
    assert result.returncode == 0
    assert result.stdout == ""


def test_debug_suggestion_is_a_system_message(isolated_data_dir):
    result = run_hook(
        "on_stop.py", stop_input(), isolated_data_dir, {handlers.DEBUG_SUGGEST_ENV: "1"}
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert list(output) == ["systemMessage"]
    assert "sess-1" in output["systemMessage"]


# --- the runner and adapter, in-process --------------------------------------------


def run_in_process(monkeypatch, hook_event, handler):
    monkeypatch.setitem(claude_code.HANDLERS, hook_event, handler)
    out = io.StringIO()
    hookrunner.run(hook_event, stdin=io.StringIO(stop_input()), stdout=out)
    return out.getvalue()


def test_handler_gets_a_normalized_event(monkeypatch):
    seen = []
    run_in_process(monkeypatch, "Stop", seen.append)
    assert seen == [
        {
            "editor": "claude-code",
            "kind": "Stop",
            "session_id": "sess-1",
            "prompt_id": "11111111-1111-1111-1111-111111111111",
            "cwd": "/tmp/scratch-repo",
        }
    ]


@pytest.mark.parametrize(
    "result", [{"decision": "block", "reason": "keep going"}, {"systemMessage": "x"}, 42, ""]
)
def test_only_suggestion_text_is_ever_rendered(monkeypatch, result):
    assert run_in_process(monkeypatch, "Stop", lambda event: result) == ""


def test_other_events_never_print(monkeypatch):
    assert run_in_process(monkeypatch, "UserPromptSubmit", lambda event: "leak") == ""


def test_handler_crash_is_logged_not_raised(monkeypatch, isolated_data_dir):
    def boom(event):
        raise RuntimeError("boom")

    assert run_in_process(monkeypatch, "Stop", boom) == ""
    log = (isolated_data_dir / "logs" / "errors.log").read_text()
    assert "RuntimeError: boom" in log
