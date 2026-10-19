# 0003: Editor-neutral core, one repo, no submodules

- Status: accepted
- Date: 2026-10-18

## Context

A Cursor version is likely later. Cursor has plugins (`.cursor-plugin/plugin.json`), `skills/` and `hooks/hooks.json`, with events close to ours:

| Our event | Claude Code | Cursor |
|---|---|---|
| prompt | `UserPromptSubmit` | `beforeSubmitPrompt` |
| action | `PostToolUse` / `PostToolUseFailure` | `postToolUse` / `postToolUseFailure` |
| turn end | `Stop` | `stop` |
| session end | `SessionEnd` | `sessionEnd` |

Cursor gaps (from its docs, October 2026):

- **No zero-token message from `stop`.** Its only output is `followup_message`, which Cursor submits as the next user message.
- **No `ConfigChange` or `UserPromptExpansion` equivalent.**
- **No documented plugin data directory.**
- **Skill frontmatter documents only `name` and `description`.**
- **It can't load our plugin directly.** Cursor's Claude Code compatibility only reads hooks from `.claude/settings*.json`, not from Claude Code plugins.

We considered splitting the core into its own repo, used as a git submodule.

## Decision

- **One repo.** `src/skill_spotter/` is the editor-neutral core.
- **One adapter per editor.** `claude_code.py` is the only module that knows Claude Code's hook formats. It exposes `HANDLERS`, `normalize` (hook input → neutral `Event` with `kind` = prompt / action / turn_end / skill_change / command_used / session_end) and `render` (handler result → hook output).
- **No submodules.** Plugin installs copy only the plugin folder, the docs don't say whether submodules are fetched, and pinned submodule commits drift.
- **When Cursor work starts:** restructure as `core/` + `plugins/claude-code/` + `plugins/cursor/`. A build script will copy the core into each plugin folder, and each editor's marketplace will point at its own subfolder. The Cursor `render` would likely send an OS notification instead of a chat message. That gets its own ADR.

## Consequences

- Handlers never see editor field names. New editors only add an adapter and entry scripts.
- Event fields are picked explicitly (e.g. `tool_response` is dropped), so the adapter is also where we decide what is kept.
