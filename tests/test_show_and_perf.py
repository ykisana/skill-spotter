from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid

import pytest
from conftest import ROOT
from helpers import Session, bash

from skill_spotter import cli, paths, patterns, recorder, store


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "acme-api"
    (root / ".git").mkdir(parents=True)
    return str(root)


def make_pattern(repo):
    s1, s2 = Session(repo), Session(repo)
    prompts = [
        ("deploy the api to staging", "staging"),
        ("ship api to staging env now", "staging"),
        ("deploy api to production please", "production"),
    ]
    for (prompt, env), s in zip(prompts, (s1, s1, s2)):
        s.turn(
            prompt,
            [
                bash("git status"),
                bash("npm run build"),
                bash(f"make deploy ENV={env}"),
                bash(f"curl -X GET https://api.{env}.acme.io/health"),
            ],
        )


def test_show_json_has_what_the_draft_skill_needs(repo, capsys):
    make_pattern(repo)
    assert cli.main(["show", "p1", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["id"] == "p1" and d["count"] == 3 and d["sessions"] == 2
    steps = [s["step"] for s in d["common_steps"]]
    assert steps == ["npm run build", "make deploy", "curl -X GET"]  # in order, no git status
    assert d["danger"] and d["dangerous_steps"] == ["make deploy"]
    varying = {v["step"]: v["examples"] for v in d["varying_values"]}
    assert set(varying["make deploy"]) == {"ENV=staging", "ENV=production"}
    assert d["skill_path"].startswith(os.path.join(repo, ".claude", "skills"))
    assert d["skill_path"].endswith("SKILL.md")
    assert len(d["turns"]) == 3 and d["turns"][0]["prompt"] == "deploy api to production please"


def test_show_text_and_errors(repo, capsys):
    make_pattern(repo)
    assert cli.main(["show", "1"]) == 0
    assert "common steps:" in capsys.readouterr().out
    assert cli.main(["show", "p999"]) == 1
    assert cli.main(["show", "nope"]) == 2


def test_accept_marks_pattern(repo, capsys, isolated_data_dir):
    make_pattern(repo)
    path = os.path.join(repo, ".claude", "skills", "deploy-api", "SKILL.md")
    assert cli.main(["accept", "p1", path]) == 0
    conn = store.connect(paths.db_path(isolated_data_dir))
    p = conn.execute(
        "SELECT state, skill_path, suggested_name FROM patterns WHERE id = 1"
    ).fetchone()
    assert tuple(p) == ("accepted", path, "deploy-api")
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type = 'accepted'").fetchone()[0] == 1


def test_status_lists_patterns(repo, capsys):
    make_pattern(repo)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "p1" in out and "3x in 2 sessions" in out


# --- latency budgets (SPEC M1 done criteria) ------------------------------------------

WORDS = (
    "deploy build test release changelog migrate database api web worker cache queue "
    "logs metrics docs readme auth login billing search index backup restore staging "
    "production review triage label issue branch merge rebase tag version bump lint"
).split()
COMMANDS = [
    "npm run {w}",
    "make {w}",
    "git commit -m x",
    "gh pr list --label {w}",
    "pytest tests/{w}",
    "docker compose up {w}",
    "kubectl rollout restart deploy/{w}",
    "terraform plan -target={w}",
    "python3 scripts/{w}.py",
    "cargo test {w}",
    "gh issue create --title {w}",
    "uv run {w}",
]


def populate(conn, repo, n_turns=2000, seed=7):
    rng = random.Random(seed)
    now = time.time() - n_turns * 60
    sessions = [f"s{i}" for i in range(80)]
    for i in range(n_turns):
        ts = now + i * 60
        pid = str(uuid.uuid4())
        sid = rng.choice(sessions)
        words = rng.sample(WORDS, 5)
        recorder.record_prompt(
            conn, {"prompt_id": pid, "session_id": sid, "cwd": repo, "prompt": " ".join(words)}, ts
        )
        for _ in range(rng.randint(1, 6)):
            cmd = rng.choice(COMMANDS).format(w=rng.choice(WORDS))
            recorder.record_action(
                conn,
                {
                    "prompt_id": pid,
                    "session_id": sid,
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                },
                ts + 1,
            )
        if rng.random() < 0.3:
            recorder.record_action(
                conn,
                {
                    "prompt_id": pid,
                    "session_id": sid,
                    "tool_name": "Edit",
                    "tool_input": {"file_path": f"{repo}/src/{rng.choice(WORDS)}.py"},
                },
                ts + 2,
            )
        patterns.finalize_turn(conn, pid, ts + 3)


def p95(samples):
    return statistics.quantiles(samples, n=20)[18]


@pytest.fixture(scope="module")
def big_db(tmp_path_factory):
    data = tmp_path_factory.mktemp("perf")
    repo = tmp_path_factory.mktemp("perf-repo")
    (repo / ".git").mkdir()
    conn = store.connect(paths.db_path(data))
    populate(conn, str(repo))
    conn.close()
    return data, str(repo)


def run_hook_timed(script, payload, data_dir):
    env = {**os.environ, "SKILL_SPOTTER_DATA": str(data_dir)}
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-S", str(ROOT / "hooks" / script)],  # as hooks.json runs it
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return (time.perf_counter() - start) * 1000


def test_stop_hook_p95_under_100ms_with_2000_turns(big_db):
    data, repo = big_db
    conn = store.connect(paths.db_path(data))
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] >= 2000
    conn.close()
    samples = []
    for i in range(43):
        pid = str(uuid.uuid4())
        base = {"session_id": "perf", "cwd": repo, "prompt_id": pid}
        run_hook_timed(
            "on_prompt.py",
            {
                **base,
                "hook_event_name": "UserPromptSubmit",
                "prompt": f"deploy the api worker to staging run {i}",
            },
            data,
        )
        for cmd in ("npm run build", "make deploy", "gh pr list --label release"):
            run_hook_timed(
                "on_action.py",
                {
                    **base,
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                    "tool_use_id": uuid.uuid4().hex,
                },
                data,
            )
        samples.append(
            run_hook_timed(
                "on_stop.py", {**base, "hook_event_name": "Stop", "session_crons": []}, data
            )
        )
    samples = samples[3:]  # first runs pay for cold disk caches and .pyc compilation
    print(f"\nStop hook p95: {p95(samples):.1f} ms, median {statistics.median(samples):.1f} ms")
    assert p95(samples) < 100, f"Stop p95 {p95(samples):.1f} ms"


def test_action_append_p95_under_20ms(big_db):
    """In-process cost of recording one tool call (the hook itself runs async)."""
    data, repo = big_db
    conn = store.connect(paths.db_path(data))
    pid = str(uuid.uuid4())
    recorder.record_prompt(
        conn,
        {
            "prompt_id": pid,
            "session_id": "perf2",
            "cwd": repo,
            "prompt": "run the full release checklist for the api",
        },
        time.time(),
    )
    samples = []
    for i in range(200):
        start = time.perf_counter()
        recorder.record_action(
            conn,
            {
                "prompt_id": pid,
                "session_id": "perf2",
                "tool_name": "Bash",
                "tool_input": {"command": f"npm run test -- --shard={i}"},
                "tool_use_id": f"t{i}",
            },
            time.time(),
        )
        samples.append((time.perf_counter() - start) * 1000)
    print(f"\naction append p95: {p95(samples):.2f} ms")
    assert p95(samples) < 20, f"append p95 {p95(samples):.2f} ms"
