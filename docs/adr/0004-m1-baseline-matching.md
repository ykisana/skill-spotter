# 0004: M1 baseline matching, and what real sessions showed

- Status: accepted
- Date: 2026-10-19
- Milestone: M1

## Decisions that go beyond the spec

1. **Candidate lookup uses an inverted index from M1 on.** Brute-force comparison against up to 2,000 patterns meant loading and parsing every representative on each `Stop`, about 100 ms of JSON alone. `pattern_tokens` indexes each pattern's distinctive tokens (weight ≥ 0.25) and text unigrams (`txt:` prefix). The top 50 candidates by shared tokens are then scored exactly, so scoring itself is unchanged. The spec listed this index as an M3 candidate; M3 still benchmarks it against brute force.
2. **Pattern representatives are running averages** of member fingerprints, text n-gram fractions, prompt words and first words. Values under 0.05 are pruned.
3. **Runners are unwrapped.** `python -m X`, `uv run X`, `poetry run X`, `npx X` and similar normalize as plain `X`, so "uv run pytest" and "pytest" are the same task.
4. **Value-taking flags come in two kinds.** `drop_flags` drop the flag and its value (`git commit -m "…"` → `git commit`, which the spec's fixtures require). `value_flags` keep the flag and drop its value. Unknown flags are kept as behavior.
5. **Danger:** global danger flags, per-command ones (`git -D`/`-f`), `rm -r -f`, danger words in subcommands (`deploy`, `publish`, `delete`, …), and a few (command, subcommand) pairs such as `terraform apply`. Plain `git push` is not dangerous.
6. **Automatic turns (open question 1):** a prompt is skipped if it starts with a tag line (`<task-notification>` and similar wrappers), if it matches a scheduled prompt seen in the session's last `Stop` input (`session_crons[].prompt`, including the `… [+N chars]` truncation), or if it repeats the previous prompt in the same session within 10 minutes.
7. **Naming:** the object is a consistent prompt word that names the edited file, else the most consistent non-generic word. The verb is the prompts' consistent first word, else "update" for file edits. A qualifier is added only if it directly precedes the object. In the live run this turned `/tag-changelog-commit` into `/update-changelog`.
8. **Hook startup:** hooks run as `python3 -S` (no site-packages; they're stdlib-only), handlers import only what their event needs, and the repeat check uses `zlib` instead of `hashlib`. `Stop` p95 went from ~150 ms to ~47 ms locally with 2,000 stored turns.
9. **`suggest_via = claude`** queues the suggestion and returns it as `additionalContext` on the next `UserPromptSubmit`. Using `Stop`'s `additionalContext` would make Claude continue the turn.
10. **The draft skill records acceptance itself** (`skill-spotter accept <id> <path>`), so a renamed skill still maps back to its pattern.

## Findings from real sessions (Claude Code 2.1.282)

- **Suggestion display (open question 2):** a `Stop` `systemMessage` arrives in `--output-format stream-json` as `{"type":"system","subtype":"informational","content":"Stop says: [skill-spotter] …","level":"notice"}`. It's a notice to the user, not context for Claude. Interactive terminal rendering still needs the owner's eyes; run with `SKILL_SPOTTER_DEBUG_SUGGEST=1`.
- **Same task, three wordings, three sessions:**
  - "add a changelog entry under Unreleased summarizing the commits since the last tag, then commit it"
  - "update CHANGELOG.md with what changed since the previous release tag and commit"
  - "write release notes into the changelog for commits after the latest tag, commit the result"

  All three joined pattern p1, and the third produced the suggestion.
- **`/skill-spotter:draft p1 manual`** wrote a manual-only `.claude/skills/update-changelog/SKILL.md` and recorded acceptance. In a new session, `/update-changelog` did the task correctly.
- **Writing into `.claude/` is a protected path.** Interactively the user approves one prompt. Headless runs need `--permission-mode bypassPermissions`; no allow rule covers it. Only do that in throwaway repos.
- **cwd may be a resolved path** (`/private/tmp/...` for `/tmp/...`). `project_key` uses whatever Claude Code sends, which is consistent within a machine.

## Consequences

- Latency budgets are asserted strictly locally and loosely on CI (400 ms / 50 ms), because shared runners showed 250–300 ms spikes from disk noise.

## M2 additions (2026-10-19)

- **Acceptance has three paths:** `ConfigChange` (matcher `skills`), a scan of the project and personal skill folders when a turn ends, and the draft skill's `accept` call.
  - Real sessions showed `ConfigChange` only fires if the session lives long enough for Claude Code's file watcher. A short headless session that wrote the skill was caught by the scan instead.
- **Snoozing:** `SessionEnd` snoozes suggestions shown in that session that are still `suggested`. The second snooze dismisses the pattern. Accepted patterns are never snoozed.
- **Usage:** `UserPromptExpansion` logs `used` when the command matches an accepted pattern's skill folder name or suggested name. A plugin prefix (`plugin:name`) is stripped.
- **Retention:** turns and actions older than 90 days are pruned at most once a day, when a turn ends. Pattern aggregates stay.
- **Testable time:** `clock.now()` is the only time source the handlers use, so tests can move past snoozes.
- **Naming, revised again:** after the edited-file object, prefer a word the prompts share with the task's commands ("create an annotated git tag" + `git tag` → `/create-tag`, not `/create-annotated`). The verb is chosen first, so a command word can still be the object.
