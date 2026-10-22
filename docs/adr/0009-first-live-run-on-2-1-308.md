# 0009: first live run on Claude Code 2.1.308

Status: accepted (October 2026)

The plugin was installed from a local marketplace on Claude Code 2.1.308. The first live suggestion had several problems:
- it came from chit-chat ("hey claude, say hi");
- it was named after an unrelated command (`/sqlite3`);
- it read `Stop says: [skill-spotter] You've done this 3 times (pattern p2). …`;
- the mod band never showed up.

## Mod band (M7) never ran

Checked against the mods reference and the generated `claude-code.d.ts` for this build. The debug log (`claude --debug`) shows the module loading, then every hook throwing:
- **`$.plugin.root` is a string, not a function.** `$.plugin.root()` threw `TypeError` in `session.start` and `turn.complete`.
- **`$.env.get` and `$.session.id` return promises.** Un-awaited, the promise went into `$.process.run`, which rejects arguments that aren't plain data.
- **`$.process.run` takes one argv array**, not `(command, args)`.
- **A mod can't read `CLAUDE_PLUGIN_DATA`.** Claude Code sets it only for hook processes, and `$.plugin` has only `name` and `root`. So the CLI the mod started fell back to `~/.claude/plugins/data/skill-spotter/`, while the hooks used `skill-spotter-skill-spotter/` (or `skill-spotter-inline/` with `--plugin-dir`). The band registration and the Stop hook never met.
- **Static checks:** the module loader requires every `$` call to be written in full. `value($.session.id)` fails to load with "used as a value".

Decision:
- **Hand-off through a mailbox, not the database.** The hand-off is now a folder of small files at a fixed path, `~/.claude/plugins/data/skill-spotter/band/` (`$SKILL_SPOTTER_BAND_DIR` overrides it):
  - `<session>.on` marks a session the mod registered;
  - `<session>.pending` holds the queued suggestion, including the hook's `data_dir`, so **[Not now]** snoozes in the right database;
  - `SessionEnd` deletes the session's files, and `band register` prunes files older than 7 days.
  - The `band` CLI never opens the database. The `session_meta.band_active` and `pending_band` columns are no longer used.
- **Tests for the mod itself:** `tests/mod/band.test.ts` runs under `claude plugin test` with every `$` call stubbed. It covers registration, fetching, drawing, and both buttons. Against the old module, 4 of its 6 tests fail. CI runs `claude plugin validate .` and `claude plugin test`.

## "Stop says:" can't be renamed

Claude Code prefixes every hook `systemMessage` with `<Event> says:`. Neither the hooks reference, the plugin manifest reference nor the changelog (up to 2.1.308) has a field to change it. The band is the only way to show suggestions under the plugin's own name. Without the mod, the message must name skill-spotter itself.

## Chit-chat became a pattern

"hey claude, say hi" normalizes to `claude say`. A pattern with no meaningful actions is generic only when it has fewer than 2 strong words, and here "claude" and "say" counted as 2. Decision: `claude`, `say`, `hello` and `thx` are stop words. Addressing the assistant is never part of a task. The CI replay is unchanged (precision, recall and false suggestions are identical before and after).

## The message didn't say what repeated

`You've done this 3 times (pattern p2)` gave no way to tell *what* "this" was, and `pattern p2` is internal vocabulary. Decision:
- **Patterns:** `skill-spotter: you've repeated this 3 times: "<latest prompt>". To save it as /<name>, run /skill-spotter:draft p2`.
- **Workflows:** `skill-spotter: you've run these 3 steps together in 3 sessions: /a → /b → /c. To save them as /<name>, run /skill-spotter:draft w7`.
- **The quote:** the latest prompt (already redacted), on one line, without pasted blocks, cut at a word within 60 characters.
- **The band** shows the part before "To save…" next to its buttons. The fallback message starts with `skill-spotter:` because Claude Code's `Stop says:` label can't be changed.
