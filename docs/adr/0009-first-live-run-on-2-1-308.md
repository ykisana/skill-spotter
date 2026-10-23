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

## Names

`/sqlite3` came from a bug. In `naming.from_words`, `usable()` compared `_verb(w) != verb`, and when no prompt started with a verb both sides were `None`. So every word was rejected, and the name fell back to the first command (`/psql`, `/pytest`, `/git-push`). The blind-judge benchmark scored these 1/5.

Changes, each checked against the Claude reference names stored by `bench.naming` (share of families where the heuristic shares a word with Claude's name):

| | dev | test |
|---|---|---|
| before | 0.43 | 0.66 |
| bug fixed | 0.57 | 0.79 |
| + verb among the first 3 content words (`lead` in the representative) | 0.62 | 0.84 |
| + `run` kept as a naming verb (still a stop word for matching and the generic check) | 0.63 | 0.84 |

Blind judge (Sonnet, 1–5), re-run:
- **dev:** heuristic 2.47 → 2.70;
- **test:** heuristic 2.66 → 2.87;
- **Claude's own names:** 4.8–4.9.

A word heuristic can't name paraphrased tasks well, so:
- **Weak guesses aren't shown.** `naming.guess` flags a name as weak if:
  - it came from a command rather than the prompts' words;
  - it is a lone noun (`/prod`);
  - it needed a number to avoid a clash (`/memory-2`).

  The suggestion then says "To save it as a skill", the band button reads **[Create skill]**, and the name isn't stored, so a re-suggestion derives it again. In the judged sets, the hidden names averaged 1.3–1.6 and the names still shown averaged 2.9–3.0.
- **Claude names the skill when drafting.** `/skill-spotter:draft` now picks the name in its own step, before asking who may run the skill. It keeps the guess only if it's already the name the user would type. The final names are therefore Claude's, which judged 4.8.
- **Patterns created before this change** have no `lead` and fall back to first-word verbs until they're rebuilt.

## Real repeats didn't match

Claude Code (Sonnet) ran "update the changelog with the commits since the last tag and commit it" in two sessions. The two runs became two patterns. The shipped matcher scored the pair **0.03** against θ = 0.7, despite:
- identical wording (BM25 1.0);
- the same edited file.

Claude reached the result by different commands each run: `git tag --list` vs `git tag --sort`, and `git add` + `git commit` vs `git commit -a`. So action similarity was 0.29, and the "few actions" term (2 meaningful actions) pulled the score down further. The learned weights are text 0.17 against actions 1.47. The synthetic data repeats its commands, so it never showed this. Paraphrased runs ("add a changelog entry under Unreleased…", "update CHANGELOG.md with what changed since…") didn't match either. That part is still open (Known limitations in the README).

Decision: a rule next to the existing text-only path. Two turns are the same task (0.99) when:
- their word 1–2-grams overlap ≥ 0.6, the same bar as the text-only path;
- and they edited the same files (file Jaccard ≥ 0.5) or share at least half their actions (action ≥ `action_weak`).

Results:
- **Full replay:** test and dev precision, recall and false suggestions are unchanged. On test, duplicates went from 26 to 25 and extra patterns from 6 to 5.
- **Scenario test:** `tests/test_shipped_matcher.py` replays the live command variations. It fails on the old matcher.
- **Still unmeasured:** real labelled data (`bench.label`), which is still the way to tune this properly.

## Heredocs and command substitutions became fake commands

In an interactive session, Claude edited the changelog with `python3 - <<'E' … E`, and found the tag with `git log $(git describe --tags --abbrev=0)..HEAD`. The normalizer split the heredoc's Python into commands (`bash:p`, `bash:.read`, `bash:## Unreleased…`) and made `..HEAD` a command name. The fake "meaningful" actions kept the turn out of the text-only path, so the third repeat matched nothing.

Decision:
- `split_commands` drops heredoc bodies (`<<`, `<<-`, quoted or bare tags; an unterminated body runs to the end).
- `$(…)`, `$((…))` and backquotes become the value placeholder `%sub`.
- **Full replay:** dev is identical. On test, one more duplicate suggestion and extra pattern; precision and recall are unchanged.
- **Still open:** an edit made through a shell command (a heredoc script, `sed -i`) doesn't count as a file edit.

## The band after /clear

`/clear` gives the session a new id and fires `SessionEnd`, which removed the band registration, but the mod gets no new `session.start`. So every suggestion after a `/clear` fell back to the `Stop says:` message. Decision: the mod reads `$.session.id()` after every turn, and `band pending` registers the id it's given.
