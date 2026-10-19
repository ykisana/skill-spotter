# 0001: Scaffold layout and runtime choices

- Status: accepted
- Date: 2026-10-18
- Milestone: M0

## Context

The project spec was written for a working name, "skillnudge". It left the final name, the minimum Python version and several layout details open.

## Decisions

1. **Name: skill-spotter.** Plugin `skill-spotter`, so commands are `/skill-spotter:<skill>`. Python package `skill_spotter`, CLI `skill-spotter`, database `${CLAUDE_PLUGIN_DATA}/skill-spotter.db`. Before publishing we still need to check the name is free on GitHub, PyPI, npm and the skill directories.
2. **Python ≥ 3.9.** Hooks run `python3` from the user's `PATH`, and on macOS that can be the system Python 3.9. The online tier uses `from __future__ import annotations` and `typing.Dict`/`Optional` at runtime, and ruff's pyupgrade rules that would rewrite those are switched off. CI tests 3.9, 3.12 and 3.13 on Linux and macOS.
3. **Data directory lookup:** `--data-dir`, then `$SKILL_SPOTTER_DATA`, then `$CLAUDE_PLUGIN_DATA`, then `~/.claude/plugins/data/skill-spotter`. Empty values and values that still contain `${` are skipped. Hooks get `CLAUDE_PLUGIN_DATA` from their environment. Skills pass `--data-dir "${CLAUDE_PLUGIN_DATA}"`, because commands run from a skill don't have that variable. With `--plugin-dir` the data id is `skill-spotter-inline`.
4. **SQLite in WAL mode, schema versioned with `PRAGMA user_version`.** Migrations are an append-only list; each runs in its own transaction. A database newer than the code is refused. Pattern states are enforced with a `CHECK` constraint.
5. **One fail-open path for every hook.** `hooks/on_*.py` → `hookrunner.run` → `claude_code` adapter → `handlers`. The entry scripts wrap even the import in `try/except` and always exit 0. The runner logs exceptions to `<data dir>/logs/errors.log`. Only `claude_code.render` can produce output, and only a `systemMessage` on `Stop`.
6. **Hook settings.** Exec form (`python3` plus a script path in `args`). Tool hooks are `async`. Sync hooks have a 5 s timeout and `SessionEnd` has 1 s (all `SessionEnd` hooks share a 1.5 s budget). `ConfigChange` only fires for `skills`. `PostToolUse` and `PostToolUseFailure` share `on_action.py`, which reads the event name from the input.
7. **Skills call the CLI through `` !`…` `` injection, pre-approved with `allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter *)`.** The path is left unquoted so it matches that rule. Claude only relays the output. `forget` asks before running anything. Every plugin skill is `disable-model-invocation: true`, so it adds nothing to Claude's context.
8. **M0 skill set:** `status`, `on`, `off`, `forget`. `draft` arrives in M1, `train`/`extras` in M4. The CLI already has the later subcommands; they exit 2 with "not implemented yet".
9. **Debug switch:** `SKILL_SPOTTER_DEBUG_SUGGEST=1` makes `Stop` show a fake suggestion, so we can see how suggestions are displayed (open question 2) before detection exists.
10. **The spec isn't in the repo.** The owner chose not to add `SPEC.md`. Code comments that mention "SPEC section N" refer to the project spec (v2).

## Consequences

- A top-level `bin/` puts `skill-spotter` on the Bash tool's `PATH` while the plugin is enabled. But claude.ai and Cowork won't install a plugin that has one. Revisit before publishing; the likely fix is moving the shim to `scripts/`.
- Hook tests start real processes, the way Claude Code runs them. That is slower than in-process tests, but it catches import-path and exit-code bugs.
- `ruff format` (0.17+) also formats code blocks inside Markdown, so `*.md` is excluded from ruff.
