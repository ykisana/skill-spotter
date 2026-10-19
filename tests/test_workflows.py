"""M5 done criterion: a 3-prompt workflow repeated in 3 sessions triggers a single suggestion."""

from __future__ import annotations

import json

import pytest
from helpers import Session, bash, edit, system_message

from skill_spotter import clock, paths, store, workflows

HOUR = 3600.0
T0 = 1_790_000_000.0


@pytest.fixture
def at(monkeypatch):
    current = {"t": T0}
    monkeypatch.setattr(clock, "now", lambda: current["t"])
    return lambda hours: current.update(t=T0 + hours * HOUR)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "shop"
    (root / ".git").mkdir(parents=True)
    return str(root)


@pytest.fixture
def db(isolated_data_dir):
    return lambda: store.connect(paths.db_path(isolated_data_dir))


STEPS = [
    (
        "pull the list of pull requests merged since the last release",
        [bash("gh pr list --state merged --limit 50")],
    ),
    ("draft the changelog entry from those merged pull requests", [edit("{repo}/CHANGELOG.md")]),
    (
        "open the release pull request with the version bump",
        [bash("npm version minor"), bash("gh pr create --fill")],
    ),
]
WORDING = [
    [
        "pull the list of pull requests merged since the last release",
        "draft the changelog entry from those merged pull requests",
        "open the release pull request with the version bump",
    ],
    [
        "get me every PR merged after the previous release",
        "now write the changelog entry for those merged PRs",
        "create the release PR and bump the version",
    ],
    [
        "which pull requests got merged since we last released",
        "turn those into a changelog entry please",
        "bump the version and open the release pull request",
    ],
]


def run_workflow(session, repo, wording):
    outs = []
    for (_, actions), prompt in zip(STEPS, wording):
        acts = [
            (
                tool,
                {k: v.replace("{repo}", repo) if isinstance(v, str) else v for k, v in inp.items()},
            )
            for tool, inp in actions
        ]
        outs.append(session.turn(prompt, acts))
    return outs


def test_three_step_workflow_in_three_sessions_gives_one_suggestion(repo, db, at):
    messages = []
    for k in range(3):
        at(k * 24)  # one session per day
        s = Session(repo)
        for out in run_workflow(s, repo, WORDING[k]):
            if out["stop"]:
                messages.append(system_message(out["stop"]))
        s.end()
    assert len(messages) == 1, messages
    msg = messages[0]
    assert "3-step workflow in 3 sessions" in msg and "/skill-spotter:draft w" in msg
    conn = db()
    wf = conn.execute("SELECT * FROM workflows WHERE state = 'suggested'").fetchone()
    assert len(json.loads(wf["steps_json"])) == 3
    # the step patterns are part of the workflow now, and never suggested on their own
    steps = json.loads(wf["steps_json"])
    rows = conn.execute(
        f"SELECT workflow_id, state FROM patterns WHERE id IN ({','.join('?' * len(steps))})", steps
    ).fetchall()
    assert all(r["workflow_id"] == wf["id"] and r["state"] == "candidate" for r in rows)
    # sub-sequences are superseded, not suggested later
    assert not conn.execute(
        "SELECT COUNT(*) FROM workflows WHERE state = 'candidate' AND session_count >= 3"
    ).fetchone()[0]


def test_a_step_done_alone_later_is_not_held_back_forever(repo, db, at):
    for k in range(2):  # the workflow forms in two sessions...
        at(k * 24)
        s = Session(repo)
        run_workflow(s, repo, WORDING[k])
        s.end()
    # ...then the last step keeps happening on its own
    outs = []
    for k in range(2, 4):
        at(k * 24)
        s = Session(repo)
        prompt = [
            "bump the version and open the release pull request",
            "open the release PR with a version bump",
        ][k - 2]
        outs.append(s.turn(prompt, [bash("npm version minor"), bash("gh pr create --fill")]))
        s.end()
    assert any(o["stop"] for o in outs)


def test_candidates_allow_one_gap():
    assert set(workflows.candidates_ending_here([1, 2, 9, 3], max_gap=1)) >= {
        (2, 9, 3),
        (1, 2, 9, 3),
        (2, 3),
        (9, 3),
    }
    assert (1, 3) not in set(workflows.candidates_ending_here([1, 2, 9, 3], max_gap=1))
    assert workflows.candidates_ending_here([5]) == []


def test_a_fragmented_middle_step_still_gives_a_single_workflow_suggestion(repo, db, at):
    """If the matcher splits one step into two patterns, the workflow still surfaces once
    (as the steps that did repeat), never as separate step suggestions."""
    wording = [
        WORDING[0],
        [
            "get me every PR merged after the previous release",
            "now write up the changelog section for them",
            "create the release PR and bump the version",
        ],
        WORDING[2],
    ]
    messages = []
    for k in range(3):
        at(k * 24)
        s = Session(repo)
        messages += [
            system_message(o["stop"]) for o in run_workflow(s, repo, wording[k]) if o["stop"]
        ]
        s.end()
    assert len(messages) == 1 and "workflow" in messages[0], messages
