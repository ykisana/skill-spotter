"""Static checks on the plugin files: manifest, skills and the stdlib-only rule."""

from __future__ import annotations

import ast
import json
import re
import sys

import pytest
from conftest import ROOT

import skill_spotter

PACKAGE_DIR = ROOT / "src" / "skill_spotter"
SKILL_FILES = sorted(ROOT.glob("skills/*/SKILL.md"))


def test_manifest_name_and_version():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "skill-spotter"
    assert manifest["version"] == skill_spotter.__version__


def test_pyproject_version_matches():
    text = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{skill_spotter.__version__}"' in text


def frontmatter(path):
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert match, f"{path} has no frontmatter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_plugin_skills_are_manual_only(path):
    """Model-invocable skills put their description in Claude's context every turn."""
    fm = frontmatter(path)
    assert fm.get("disable-model-invocation") == "true"
    assert fm.get("description")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skills_only_preapprove_the_cli(path):
    allowed = frontmatter(path).get("allowed-tools")
    if allowed is not None:
        assert allowed == "Bash(${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter *)"


def imported_roots(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module.split(".")[0]


@pytest.mark.parametrize(
    "path", sorted(PACKAGE_DIR.glob("*.py")) + sorted((ROOT / "hooks").glob("*.py")),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_online_tier_imports_stdlib_only(path):
    """Hooks run with whatever python3 is on PATH, with nothing installed (SPEC section 0)."""
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:
        pytest.skip("needs Python 3.10+ for sys.stdlib_module_names")
    allowed = set(stdlib) | {"__future__", "skill_spotter"}
    assert set(imported_roots(path)) <= allowed


@pytest.mark.parametrize(
    "path", sorted((ROOT / "hooks").glob("*.py")) + [ROOT / "bin" / "skill-spotter"],
    ids=lambda p: p.name,
)
def test_entry_points_are_executable(path):
    assert path.stat().st_mode & 0o111
