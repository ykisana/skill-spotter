# 0002: Claude Code docs check (October 2026)

- Status: accepted
- Date: 2026-10-18
- Checked against: hooks reference, plugin manifest reference and skills docs at code.claude.com, with Claude Code 2.1.282.

## Matches the spec

- `UserPromptSubmit` input has `prompt`. Pasted text sits between `<pasted_content id="…">` lines. The hook also fires for scheduled tasks, `/loop`, background subagent reports and cross-session messages. Its stdout and `additionalContext` reach Claude.
- `prompt_id` is a common input field, absent until the first user input.
- Exec-form hooks substitute `${CLAUDE_PLUGIN_ROOT}` in each argument. Hooks receive `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and `CLAUDE_PROJECT_DIR` in their environment.
- `SessionEnd` has a 1.5 s shared budget and discards `systemMessage`. `UserPromptSubmit` has a 30 s default timeout.
- Skills support `disable-model-invocation` and `allowed-tools` (with `${CLAUDE_PLUGIN_ROOT}` substituted), plus `arguments`, `argument-hint`, `$ARGUMENTS`, `$N` and `$name`.
- The manifest only requires `name` (kebab-case). The `claude-`/`anthropic-` prefixes are reserved.

## Differences and additions

1. **`systemMessage` on `Stop`** isn't listed as discarded, and the general rule says it's "shown to the user". Still to confirm in a real terminal with the debug switch (open question 2).
2. **Async hook output goes to Claude.** If an `async: true` hook prints `systemMessage` or `additionalContext`, it is delivered to Claude on the next turn, not shown to the user. So `on_action.py` must print nothing; tests check this.
3. **`Stop` input has `background_tasks` and `session_crons`.** `session_crons[].prompt` holds what scheduled wakeups will submit. That's a likely way to spot automatic `UserPromptSubmit` turns in M1 (open question 1).
4. **`ConfigChange` input is `source` plus an optional `file_path`.** The `skills` matcher is documented for `.claude/skills/`; personal `~/.claude/skills/` isn't mentioned. So the M2 fallback scan of skill folders is required, not optional.
5. **`UserPromptExpansion`** also has `expansion_type` (`slash_command` | `mcp_prompt`) and the original `prompt`.
6. **`PostToolUse`** also has `tool_response` and `duration_ms`; **`PostToolUseFailure`** has `tool_error`. File paths in `tool_input` are absolute, so M1 must make them project-relative itself. We deliberately don't keep `tool_response`.
7. **A plugin-root `CLAUDE.md` isn't loaded** and makes validation warn. Dev notes therefore live in `.claude/CLAUDE.md`.
