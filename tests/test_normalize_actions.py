from __future__ import annotations

import pytest

from skill_spotter.capture.normalize_actions import (
    normalize_action,
    split_commands,
    turn_fingerprint,
)

ROOT = "/repo"


def bash(command, failed=False):
    return normalize_action("Bash", {"command": command}, ROOT, failed=failed)


def template(command):
    return bash(command)["template"]


# The required fixtures from SPEC section 5.2
@pytest.mark.parametrize(
    "command,expected",
    [
        ("git commit", "git commit"),
        ('git commit -m "fix typo"', "git commit"),
        ('git commit -am "wip"', "git commit -a"),
        ("git commit --amend", "git commit --amend"),
        ("npm run test", "npm run test"),
        ("npm run build", "npm run build"),
    ],
)
def test_spec_fixtures(command, expected):
    assert template(command) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        # env prefixes, wrappers, chained commands
        ("CI=1 NODE_ENV=test npm run test", "npm run test"),
        ("sudo -E make deploy", "make deploy"),
        ("timeout 30 pytest -x tests/", "pytest -x"),
        ("cd api && npm ci && npm run build", "npm ci ; npm run build"),
        ("git add -A; git commit -m 'x' || true", "git add -A ; git commit"),
        ("cat log.txt | grep ERROR | wc -l", "cat ; grep ; wc -l"),
        ("bash -c 'make clean && make build'", "make clean ; make build"),
        ("echo hi\ngit push origin main", "git push"),
        # flags: values dropped, behavior kept, order-insensitive, verbosity ignored
        ("git push --force-with-lease origin feature/x", "git push --force-with-lease"),
        ("git log --oneline -n 20 --since=2026-01-01", "git log --oneline"),
        ("pytest -v -x", "pytest -x"),
        ("pytest -x -v", "pytest -x"),
        ("docker run -it --rm -e A=1 -p 80:80 nginx", "docker run --rm -i -t"),
        ("rm -rf build dist", "rm -f -r"),
        ("ls -la", "ls -a -l"),
        # subcommand depth and identity positionals
        ("gh pr list --state merged --search 'merged:>=2026-10-01'", "gh pr list"),
        ("gh pr create --fill --draft", "gh pr create --draft --fill"),
        ("git stash pop", "git stash pop"),
        ("docker compose up -d api", "docker compose up -d"),
        ("kubectl get pods -n prod", "kubectl get pods"),
        ("kubectl rollout restart deployment/api", "kubectl rollout restart"),
        ("make deploy ENV=prod", "make deploy"),
        ("uv run pytest tests/test_x.py", "pytest"),
        ("uv run --with httpx pytest -x", "pytest -x"),
        ("npx -y prettier --write src", "prettier --write"),
        ("python3 scripts/release.py --dry-run", "python3 release.py --dry-run"),
        ("python -m pytest -k slow", "pytest"),
        ("docker build -t api:latest .", "docker build -t"),
        ("python manage.py migrate", "python manage.py migrate"),
        ("./scripts/deploy.sh staging", "deploy.sh"),
        ("terraform apply -auto-approve -var-file=prod.tfvars", "terraform apply -auto-approve"),
        ("curl -X POST -H 'Auth: x' https://api.x.io/v1", "curl -X POST"),
        ("npm test 2>&1 > out.log", "npm test"),
    ],
)
def test_normalization(command, expected):
    assert template(command) == expected


def test_hierarchical_tokens():
    tokens = bash("git commit --amend")["tokens"]
    assert tokens == {
        "bash:git": 0.1,
        "bash:git commit": 0.5,
        "bash:git commit --amend": 1.0,
    }


def test_no_flags_means_l2_is_l3():
    assert bash("git commit")["tokens"] == {"bash:git": 0.1, "bash:git commit": 1.0}


def test_low_value_commands_are_weighted_down():
    action = bash("git status")
    assert action["low"]
    assert max(action["tokens"].values()) == pytest.approx(0.1)


def test_failed_actions_count_half():
    assert bash("npm run test", failed=True)["tokens"]["bash:npm run test"] == 0.5


@pytest.mark.parametrize(
    "command,danger",
    [
        ("git commit --amend", True),
        ("git push --force", True),
        ("git push origin main", False),
        ("git reset --hard HEAD~1", True),
        ("git branch -D old", True),
        ("git branch -d old", False),
        ("rm -rf node_modules", True),
        ("rm -f a.txt", False),
        ("npm publish", True),
        ("make deploy", True),
        ("terraform apply", True),
        ("terraform plan", False),
        ("kubectl delete pod x", True),
        ("git commit --no-verify -m x", True),
        ("npm install -D vitest", False),
    ],
)
def test_danger(command, danger):
    assert bash(command)["danger"] is danger


def test_values_are_kept_redacted_for_parameters():
    action = bash("gh pr view 123 --repo acme/api --jq .title")
    assert "123" in action["values"]
    action = bash("deploy.sh --token ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert all("ghp_" not in v for v in action["values"])
    assert "ghp_" not in action["summary"]


def test_split_commands_handles_bad_quotes():
    assert split_commands("echo 'unterminated && ls") != []


# --- non-Bash tools -------------------------------------------------------------------


def test_edit_is_project_relative():
    action = normalize_action("Edit", {"file_path": "/repo/docs/CHANGELOG.md"}, ROOT)
    assert action["tokens"] == {"edit:docs/CHANGELOG.md": 1.0, "editdir:docs": 0.5}
    assert action["summary"] == "docs/CHANGELOG.md"


def test_edit_outside_project_keeps_only_basename():
    action = normalize_action("Write", {"file_path": "/Users/me/.zshrc"}, ROOT)
    assert "edit:<external>/.zshrc" in action["tokens"]
    assert "/Users/me" not in action["summary"]


def test_reads_are_low_value_top_level_dirs():
    action = normalize_action("Read", {"file_path": "/repo/src/app/main.py"}, ROOT)
    assert action["tokens"] == {"read:src": pytest.approx(0.1)}
    assert action["low"]


def test_mcp_uses_argument_names_never_values():
    action = normalize_action(
        "mcp__linear__create_issue", {"title": "secret plan", "team": "eng"}, ROOT
    )
    assert action["tokens"] == {
        "mcp:linear": 0.1,
        "mcp:linear:create_issue": 0.5,
        "mcp:linear:create_issue(team,title)": 1.0,
    }
    assert "secret" not in action["summary"]


@pytest.mark.parametrize(
    "tool,tool_input,token",
    [
        ("WebFetch", {"url": "https://www.github.com/x"}, "web:github.com"),
        ("WebSearch", {"query": "x"}, "web:search"),
        ("Skill", {"skill": "weekly-changelog"}, "skill:weekly-changelog"),
        ("Agent", {"subagent_type": "Explore", "prompt": "x"}, "agent:Explore"),
        ("SomethingNew", {}, "tool:SomethingNew"),
    ],
)
def test_other_tools(tool, tool_input, token):
    assert token in normalize_action(tool, tool_input, ROOT)["tokens"]


def test_bookkeeping_tools_are_ignored():
    assert normalize_action("TodoWrite", {"todos": []}, ROOT)["tokens"] == {}


# --- turn fingerprint -----------------------------------------------------------------


def test_fingerprint_adds_order_bigrams():
    actions = [bash("git status"), bash("git commit --amend"), bash("git push --force-with-lease")]
    tokens = turn_fingerprint(actions)
    assert "seq:bash:git commit>bash:git push" in tokens
    assert not any(t.startswith("seq:bash:git status") for t in tokens)  # low-value skipped


def test_order_matters():
    a = turn_fingerprint([bash("npm run build"), bash("npm run test")])
    b = turn_fingerprint([bash("npm run test"), bash("npm run build")])
    assert {t for t in a if t.startswith("seq:")} != {t for t in b if t.startswith("seq:")}


# Live run on 2.1.308 (ADR 0009): Claude edited the changelog with a python heredoc and
# found the tag with a command substitution; both turned into made-up commands.
LIVE = (
    "python3 - <<'E'\n"
    "p='CHANGELOG.md'\n"
    "s=open(p).read()\n"
    "open(p,'w').write(s)\n"
    "E\n"
    'git commit -qam "update changelog since v0.7.0" && git show --stat HEAD | tail -3'
)


def test_heredoc_bodies_are_not_commands():
    assert split_commands(LIVE) == [
        ["python3", "-"],
        ["git", "commit", "-qam", "update changelog since v0.7.0"],
        ["git", "show", "--stat", "HEAD"],
        ["tail", "-3"],
    ]
    tokens = normalize_action("Bash", {"command": LIVE}, None)["tokens"]
    assert not [t for t in tokens if t in ("bash:p", "bash:.read", "bash:s")]


def test_heredoc_variants():
    assert split_commands("cat <<EOF > notes.md\nhello\nEOF\nls") == [["cat"], ["ls"]]
    assert split_commands('cat <<"END"\nx; rm -rf /\nEND\necho ok') == [["cat"], ["echo", "ok"]]
    # <<- strips leading tabs from the closing tag
    assert split_commands("cat <<-EOF\n\tbody\n\tEOF\necho done") == [["cat"], ["echo", "done"]]
    # an unterminated heredoc swallows the rest, as the shell would
    assert split_commands("cat <<EOF\nno end") == [["cat"]]


def test_command_substitutions_are_values():
    cmd = "git log $(git describe --tags --abbrev=0)..HEAD --oneline"
    assert split_commands(cmd) == [["git", "log", "%sub..HEAD", "--oneline"]]
    tokens = normalize_action("Bash", {"command": cmd}, None)["tokens"]
    assert "bash:git log --oneline" in tokens and not any("HEAD" in t for t in tokens)
    assert split_commands("git log `git describe`..HEAD") == [["git", "log", "%sub..HEAD"]]
    assert split_commands("echo $((1 + 2)) && ls") == [["echo", "%sub"], ["ls"]]
    assert split_commands("echo $(date $(echo +%F)) done") == [["echo", "%sub", "done"]]
