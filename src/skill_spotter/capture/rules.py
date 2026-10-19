"""Baseline knowledge about common CLIs, used by ``normalize_actions`` (SPEC section 5.2).

Per command:
- ``sub``: how many leading words are subcommands (``git commit`` → 1, ``gh pr list`` → 2)
- ``sub2``: first subcommands that take one more level (``git stash pop``)
- ``identity``: how many positionals after the subcommands identify the task
  (``make deploy``); ``identity_after`` does the same for one subcommand (``npm run test``)
- ``drop_flags``: flags whose value is free text or a target; flag and value both go
  (``git commit -m "msg"`` → ``git commit``)
- ``value_flags``: flags that change behavior but take a value; keep flag, drop value
- ``keep_value_flags``: flags whose value *is* the identity (``python -m pytest``)
- ``danger_flags``: flags that mark the action dangerous for this command

Unknown flags are kept as behavior flags; unknown positionals are dropped as values.
The Method Lab (M3) compares this file against learned alternatives.
"""

from __future__ import annotations

from typing import Any, Dict

_NPM_LIKE: Dict[str, Any] = {
    "sub": 1,
    "identity_after": {"run": 1, "run-script": 1, "exec": 1, "x": 1, "dlx": 1},
    "drop_flags": {"--prefix", "-w", "--workspace", "--registry", "--filter", "-F", "--otp"},
    "value_flags": {"--tag", "--access"},
}

CLI_RULES: Dict[str, Dict[str, Any]] = {
    "git": {
        "sub": 1,
        "sub2": {
            "remote",
            "stash",
            "submodule",
            "worktree",
            "bisect",
            "lfs",
            "notes",
            "sparse-checkout",
        },
        "drop_flags": {
            "-m",
            "--message",
            "-F",
            "--file",
            "-C",
            "-c",
            "--author",
            "--date",
            "--git-dir",
            "--work-tree",
            "--since",
            "--until",
            "--after",
            "--before",
            "--grep",
            "-n",
            "--max-count",
            "--format",
            "--pretty",
            "-S",
            "-G",
            "--depth",
            "--onto",
            "--set-upstream-to",
            "--trailer",
        },
        "value_flags": {"-b", "-B", "--orphan", "-X", "--strategy-option", "-s", "--strategy"},
        "danger_flags": {"-D", "-f"},
    },
    "gh": {
        "sub": 2,
        "drop_flags": {
            "--title",
            "-t",
            "--body",
            "-b",
            "--body-file",
            "--search",
            "-S",
            "--limit",
            "-L",
            "--json",
            "-q",
            "--jq",
            "--template",
            "--repo",
            "-R",
            "--label",
            "-l",
            "--assignee",
            "-a",
            "--reviewer",
            "-r",
            "--milestone",
            "-m",
            "--base",
            "-B",
            "--head",
            "-H",
            "--state",
            "-s",
            "--author",
            "-A",
            "--branch",
            "--ref",
            "--field",
            "-f",
            "--raw-field",
            "--method",
            "-X",
            "--header",
            "--hostname",
            "--env",
            "-e",
            "--name",
            "-n",
            "--message",
            "--workflow",
            "--job",
            "--commit",
            "-c",
            "--notes",
            "--target",
        },
    },
    "docker": {
        "sub": 1,
        "sub2": {
            "compose",
            "image",
            "container",
            "volume",
            "network",
            "system",
            "buildx",
            "context",
        },
        "drop_flags": {
            "--tag",
            "-f",
            "--file",
            "-e",
            "--env",
            "--env-file",
            "-p",
            "--publish",
            "-v",
            "--volume",
            "--name",
            "--network",
            "-w",
            "--workdir",
            "--build-arg",
            "--platform",
            "--label",
            "-l",
            "--entrypoint",
            "-u",
            "--user",
            "-m",
            "--memory",
            "--cpus",
            "--project-name",
            "--mount",
            "--target",
        },
    },
    "kubectl": {
        "sub": 1,
        "sub2": {"rollout", "config", "auth", "top", "set", "certificate"},
        "identity_after": {"get": 1, "describe": 1, "delete": 1, "edit": 1, "explain": 1},
        "drop_flags": {
            "-n",
            "--namespace",
            "-l",
            "--selector",
            "-o",
            "--output",
            "-f",
            "--filename",
            "--context",
            "-c",
            "--container",
            "--image",
            "--replicas",
            "--tail",
            "--since",
            "--field-selector",
            "--kubeconfig",
            "--timeout",
            "--to-revision",
            "-p",
        },
    },
    "helm": {
        "sub": 1,
        "sub2": {"repo", "plugin", "dependency"},
        "drop_flags": {
            "-n",
            "--namespace",
            "-f",
            "--values",
            "--set",
            "--set-string",
            "--version",
            "--kube-context",
        },
    },
    "terraform": {
        "sub": 1,
        "sub2": {"state", "workspace"},
        "no_bundle": True,
        "drop_flags": {
            "-var",
            "-var-file",
            "-target",
            "-out",
            "-backend-config",
            "-lock-timeout",
            "-parallelism",
            "-chdir",
        },
    },
    "npm": _NPM_LIKE,
    "pnpm": _NPM_LIKE,
    "yarn": _NPM_LIKE,
    "bun": _NPM_LIKE,
    "npx": {"drop_flags": {"-p", "--package"}},
    "uvx": {"drop_flags": {"--from", "--with", "-p", "--python"}},
    "uv": {
        "sub": 1,
        "sub2": {"pip", "tool", "python", "cache"},
        "drop_flags": {"--with", "-p", "--python", "--group", "--extra", "--package"},
    },
    "poetry": {"sub": 1, "drop_flags": {"-E", "--extras", "--with", "-G", "--group"}},
    "pip": {
        "sub": 1,
        "drop_flags": {
            "-r",
            "--requirement",
            "-i",
            "--index-url",
            "-c",
            "--constraint",
            "--target",
            "-t",
        },
    },
    "pip3": {
        "sub": 1,
        "drop_flags": {
            "-r",
            "--requirement",
            "-i",
            "--index-url",
            "-c",
            "--constraint",
            "--target",
            "-t",
        },
    },
    "python": {"script": True, "drop_flags": {"-c", "-W", "-X"}},
    "python3": {"script": True, "drop_flags": {"-c", "-W", "-X"}},
    "node": {"script": True, "drop_flags": {"-e", "--eval", "-r", "--require"}},
    "deno": {"sub": 1, "script": True},
    "ruby": {"script": True, "drop_flags": {"-e"}},
    "make": {"identity": 2, "drop_flags": {"-C", "-f", "--file", "-j", "--jobs"}},
    "just": {"identity": 2},
    "rake": {"identity": 2},
    "task": {"identity": 2},
    "cargo": {
        "sub": 1,
        "drop_flags": {
            "-p",
            "--package",
            "--features",
            "-F",
            "--target",
            "-j",
            "--bin",
            "--example",
            "--manifest-path",
            "--test",
        },
    },
    "go": {
        "sub": 1,
        "no_bundle": True,
        "drop_flags": {
            "-run",
            "-tags",
            "-o",
            "-ldflags",
            "-timeout",
            "-count",
            "-bench",
            "-p",
            "-coverprofile",
        },
    },
    "pytest": {
        "drop_flags": {
            "-k",
            "-m",
            "-n",
            "-p",
            "--maxfail",
            "--tb",
            "-c",
            "--rootdir",
            "--deselect",
            "--ignore",
            "-o",
        }
    },
    "jest": {"drop_flags": {"-t", "--testNamePattern", "-c", "--config", "--testPathPattern"}},
    "vitest": {"sub": 1, "drop_flags": {"-t", "--testNamePattern", "-c", "--config", "--project"}},
    "ruff": {"sub": 1, "drop_flags": {"--select", "--ignore", "--config", "--target-version"}},
    "mypy": {"drop_flags": {"--config-file", "-p", "--package", "-m", "--module"}},
    "tsc": {"drop_flags": {"-p", "--project", "--outDir", "--target"}},
    "eslint": {"drop_flags": {"-c", "--config", "--ext", "--rule"}},
    "prettier": {"drop_flags": {"--config", "--ignore-path"}},
    "brew": {"sub": 1},
    "apt": {"sub": 1},
    "apt-get": {"sub": 1},
    "systemctl": {"sub": 1, "identity": 1},
    "service": {"identity": 2},
    "aws": {
        "sub": 2,
        "drop_flags": {
            "--region",
            "--profile",
            "--output",
            "--query",
            "--cluster",
            "--service",
            "--bucket",
            "--key",
            "--function-name",
            "--stack-name",
            "--endpoint-url",
        },
    },
    "gcloud": {
        "sub": 3,
        "drop_flags": {"--project", "--region", "--zone", "--format", "--account", "--filter"},
    },
    "az": {
        "sub": 2,
        "drop_flags": {
            "--resource-group",
            "-g",
            "--name",
            "-n",
            "--subscription",
            "--output",
            "-o",
            "--query",
        },
    },
    "heroku": {"sub": 1, "drop_flags": {"-a", "--app", "-r", "--remote"}},
    "fly": {"sub": 1, "drop_flags": {"-a", "--app", "-c", "--config"}},
    "flyctl": {"sub": 1, "drop_flags": {"-a", "--app", "-c", "--config"}},
    "vercel": {"sub": 1, "drop_flags": {"--token", "--scope", "-e", "--env"}},
    "netlify": {"sub": 1, "drop_flags": {"--site", "--auth", "--dir", "-d"}},
    "wrangler": {"sub": 1, "drop_flags": {"--env", "-e", "--name", "-c", "--config"}},
    "rails": {"sub": 1},
    "bundle": {"sub": 1, "identity_after": {"exec": 1}},
    "dotnet": {
        "sub": 1,
        "drop_flags": {
            "-c",
            "--configuration",
            "-f",
            "--framework",
            "-o",
            "--output",
            "-p",
            "--project",
        },
    },
    "mvn": {"identity": 2, "drop_flags": {"-D", "-P", "-pl", "-f"}, "no_bundle": True},
    "gradle": {"identity": 2, "drop_flags": {"-P", "-D", "-p"}, "no_bundle": True},
    "./gradlew": {"identity": 2, "drop_flags": {"-P", "-D", "-p"}, "no_bundle": True},
    "xcodebuild": {
        "no_bundle": True,
        "drop_flags": {
            "-scheme",
            "-project",
            "-workspace",
            "-configuration",
            "-destination",
            "-sdk",
            "-derivedDataPath",
        },
    },
    "fastlane": {"identity": 2},
    "psql": {
        "drop_flags": {
            "-h",
            "--host",
            "-U",
            "--username",
            "-d",
            "--dbname",
            "-c",
            "--command",
            "-f",
            "--file",
            "-p",
            "--port",
        }
    },
    "mysql": {
        "drop_flags": {
            "-h",
            "--host",
            "-u",
            "--user",
            "-p",
            "--password",
            "-e",
            "--execute",
            "-D",
            "--database",
            "-P",
            "--port",
        }
    },
    "curl": {
        "keep_value_flags": {"-X", "--request"},
        "drop_flags": {
            "-H",
            "--header",
            "-d",
            "--data",
            "--data-raw",
            "--data-binary",
            "-o",
            "--output",
            "-u",
            "--user",
            "-A",
            "--user-agent",
            "-e",
            "--cert",
            "-F",
            "--form",
            "-b",
            "--cookie",
            "-w",
            "--write-out",
            "-m",
            "--max-time",
        },
    },
    "wget": {"drop_flags": {"-O", "--output-document", "--header", "-P", "--user", "--password"}},
    "ssh": {"drop_flags": {"-i", "-p", "-o", "-l", "-J", "-L", "-R", "-F"}},
    "scp": {"drop_flags": {"-i", "-P", "-o", "-F"}},
    "rsync": {"drop_flags": {"-e", "--exclude", "--include", "--rsh"}},
    "tar": {"drop_flags": {"-f", "--file", "-C", "--directory", "--exclude"}},
    "find": {"no_bundle": True},
    "rm": {},
    "openssl": {"sub": 1, "no_bundle": True},
}

# Commands that only wrap another command: strip them and normalize the rest.
WRAPPERS = frozenset(
    {"sudo", "time", "nohup", "nice", "env", "caffeinate", "command", "exec", "builtin", "stdbuf"}
)
# Wrappers followed by options and a duration/count before the real command.
WRAPPERS_WITH_ARGS = frozenset({"timeout", "watch", "xargs", "parallel"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "fish"})
# Runners that just launch another tool: "uv run pytest" and "pytest" are the same task.
RUNNERS = frozenset({"npx", "pnpx", "bunx", "uvx"})
RUNNER_SUBCOMMANDS = frozenset(
    {
        ("python", "-m"),
        ("python3", "-m"),
        ("uv", "run"),
        ("poetry", "run"),
        ("pipenv", "run"),
        ("bundle", "exec"),
        ("npm", "exec"),
        ("pnpm", "exec"),
        ("pnpm", "dlx"),
        ("yarn", "dlx"),
        ("bun", "x"),
    }
)

# Exploration and housekeeping: recorded, but weighted down and not "meaningful".
LOW_VALUE_COMMANDS = frozenset(
    """ls ll la pwd cd cat bat less more head tail echo printf which whereis type wc find fd
    grep rg ag tree file stat du df true false sleep date whoami hostname clear history
    sort uniq cut tr tee jq yq diff realpath dirname basename test [ mkdir touch open man
    help sed awk env export source alias read""".split()
)
LOW_VALUE_SUBCOMMANDS = frozenset(
    {
        "git status",
        "git diff",
        "git log",
        "git show",
        "git branch",
        "git rev-parse",
        "git ls-files",
        "git blame",
        "git remote",
        "git config",
        "git describe",
        "npm ls",
        "npm view",
        "pip show",
        "pip list",
        "pip freeze",
        "brew info",
        "brew list",
        "docker ps",
        "docker images",
        "kubectl get",
        "kubectl describe",
        "kubectl config",
    }
)

# Flags that mark an action dangerous for any command.
DANGER_FLAGS = frozenset(
    {"--amend", "--force", "--force-with-lease", "--hard", "--no-verify", "--delete", "--prune"}
)
# Subcommand/identity words that mark an action dangerous.
DANGER_WORDS = frozenset(
    {"deploy", "publish", "destroy", "delete", "drop", "rollback", "undeploy", "purge", "truncate"}
)
# (command, subcommand) pairs that are dangerous on their own.
DANGER_SUBCOMMANDS = frozenset(
    {
        ("terraform", "apply"),
        ("npm", "unpublish"),
        ("kubectl", "apply"),
        ("helm", "uninstall"),
        ("git", "clean"),
    }
)

# Flags that only change output verbosity or colour: dropped everywhere.
NOISE_FLAGS = frozenset(
    {
        "-v",
        "-vv",
        "-vvv",
        "-q",
        "-qq",
        "--verbose",
        "--quiet",
        "--silent",
        "--no-color",
        "--color",
        "--no-pager",
        "-y",
        "--yes",
    }
)

# Tool names that are bookkeeping, not part of the task.
IGNORED_TOOLS = frozenset(
    """TodoWrite TodoRead TaskCreate TaskUpdate TaskGet TaskList TaskOutput TaskStop
    ExitPlanMode EnterPlanMode AskUserQuestion ToolSearch BashOutput KillShell KillBash
    ListMcpResourcesTool ReadMcpResourceTool SendMessage ScheduleWakeup CronCreate
    CronDelete CronList Monitor EnterWorktree ExitWorktree ListAgents""".split()
)
READ_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "LSP", "NotebookRead"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
