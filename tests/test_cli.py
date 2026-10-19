from __future__ import annotations

import json
import subprocess
import sys

from conftest import ROOT

from skill_spotter import cli


def test_status_empty(capsys, isolated_data_dir):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "no patterns yet" in out
    assert str(isolated_data_dir) in out


def test_status_json(capsys):
    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["patterns"] == []
    assert data["counts"] == {"turns": 0, "actions": 0, "patterns": 0}
    assert data["enabled"] is True


def test_on_off(capsys):
    cli.main(["off"])
    assert "paused" in capsys.readouterr().out
    cli.main(["status", "--json"])
    assert json.loads(capsys.readouterr().out)["enabled"] is False
    cli.main(["on"])
    capsys.readouterr()
    cli.main(["status", "--json"])
    assert json.loads(capsys.readouterr().out)["enabled"] is True


def test_explicit_data_dir_wins(tmp_path, capsys):
    other = tmp_path / "elsewhere"
    cli.main(["--data-dir", str(other), "status"])
    assert (other / "skill-spotter.db").exists()


def test_unsubstituted_placeholder_is_ignored(isolated_data_dir, capsys):
    cli.main(["--data-dir", "${CLAUDE_PLUGIN_DATA}", "status"])
    assert (isolated_data_dir / "skill-spotter.db").exists()


def test_forget_asks_first(isolated_data_dir, monkeypatch, capsys):
    cli.main(["status"])  # creates the database
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert cli.main(["forget"]) == 1
    assert isolated_data_dir.exists()
    assert cli.main(["forget", "--yes"]) == 0
    assert not isolated_data_dir.exists()


def test_planned_commands_say_so(capsys):
    assert cli.main(["train"]) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_bin_shim_runs():
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "skill-spotter"), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "no patterns yet" in result.stdout


def test_corrupt_database_gives_a_clear_error(isolated_data_dir, capsys):
    isolated_data_dir.mkdir(parents=True)
    (isolated_data_dir / "skill-spotter.db").write_bytes(b"this is not sqlite" * 100)
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "can't open the database" in err
    assert "forget" in err
