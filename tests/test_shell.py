from __future__ import annotations

import time

from skill_spotter import cli, paths, shell, store

DAY = 86400


def history(now):
    lines = []
    for d in range(3):  # the same release routine on three days, plus noise
        t = int(now - (3 - d) * DAY)
        lines += [
            f": {t}:0;npm run build",
            f": {t + 60}:0;npm version patch",
            f": {t + 120}:0;git push --follow-tags",
            f": {t + 4000}:0;ls -la",
            f": {t + 9000}:0;vim notes-{d}.md",
        ]
    lines.append(f": {int(now - DAY)}:0;echo multi \\\nline")
    return "\n".join(lines) + "\n"


def test_parse_zsh_and_bash_history():
    zsh = shell.parse_history(": 1700000000:0;git status\n: 1700000100:0;echo a \\\nb\n")
    assert zsh == [(1700000000.0, "git status"), (1700000100.0, "echo a \nb")]
    bash = shell.parse_history("#1700000000\nmake deploy\nno-timestamp\n")
    assert bash == [(1700000000.0, "make deploy")]


def test_grouping_by_gap():
    turns = shell.group_turns([(0, "a"), (60, "b"), (5000, "c")], gap_minutes=10)
    assert [len(t) for t in turns] == [2, 1]


def test_scan_shell_imports_and_matches_repeated_routines(tmp_path, isolated_data_dir, capsys):
    hist = tmp_path / "zsh_history"
    hist.write_text(history(time.time()))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert cli.main(["scan-shell", "--file", str(hist), "--project", str(repo)]) == 0
    assert "imported" in capsys.readouterr().out
    conn = store.connect(paths.db_path(isolated_data_dir))
    rows = conn.execute(
        "SELECT pattern_id, COUNT(*) FROM turns WHERE session_id LIKE 'shell-%' GROUP BY pattern_id"
    ).fetchall()
    assert max(r[1] for r in rows) == 3  # the routine joined one pattern across 3 days
    # importing again adds nothing
    assert cli.main(["scan-shell", "--file", str(hist), "--project", str(repo)]) == 0
    assert "already imported" in capsys.readouterr().out
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == sum(r[1] for r in rows)
