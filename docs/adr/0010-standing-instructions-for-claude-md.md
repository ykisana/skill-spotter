# 0010: Standing instructions for CLAUDE.md

Status: accepted (October 2026)

## Context

A user typed "make sure I'm the only author, no claude" (in various words) in 7 prompts across 6 sessions and 6 projects, and skill-spotter never said anything. The task matcher can't see this kind of repetition, for two reasons:
- **It isn't a task.** The instruction rides along with different tasks (fix CI, update a PR, push dotfiles), so the actions differ every time and the turns land in different patterns.
- **Patterns are per project.** Each prompt was the first of its kind in its project.

A repeated instruction like this belongs in CLAUDE.md, which Claude Code loads every session, not in a skill.

## Decision

`src/skill_spotter/rules.py` looks at prompt text only, in the Stop hook:

1. **Directives.** Split the prompt into sentences (pasted blocks removed). Keep a sentence if it has an instruction cue (`make sure`, `ensure`, `always`, `never`, `don't`, `do not`, `no`, `not`, `only`, `keep`, `without`, `avoid`, `must`, `should`) and isn't a question.
2. **Key words.** Normalize with the shared text pipeline, but:
   - keep `claude`, because rules about the assistant are common;
   - drop the cue words and filler;
   - join contractions first. The shared normalizer reads the text between two apostrophes ("I'm the only author … someone else's") as a `'quoted string'` and drops it.

   A word within one typo of a word already seen (difflib ratio ≥ 0.8, 5+ letters) is read as that word ("athor" → "author").
3. **Rules.** A pair of key words shared by 3+ directives, in 3+ sessions within 30 days, creates a rule keyed by the pair. The pair with the most sessions wins. Later directives containing both words join the rule. If most of a new pair's directives already belong to a rule, they join that rule rather than starting a new one. Unlike patterns, rules are counted across projects.
4. **Suggest** once the rule crosses the trigger, unless an instruction file loaded in this session has both words on one line:
   - **Message:** `skill-spotter: you've asked for this in 7 prompts across 6 projects: "…". To add it to CLAUDE.md, run /skill-spotter:rule r1`
   - **Shared caps:** rules come after workflows and patterns in a turn, and share the one-per-session, three-per-day cap.
   - **Scope:** a rule seen in one project is only offered in that project.
5. **Which files are "loaded"** is Claude Code knowledge, so the adapter (`claude_code.instruction_files`) lists them and passes them on the `turn_end` event, following the memory docs:
   - managed policy;
   - `~/.claude/CLAUDE.md` and `~/.claude/rules/**/*.md`;
   - `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and `AGENTS.md` from the working directory up to the root;
   - the project's `.claude/rules/**/*.md`, following symlinks without looping.

   `handlers.py` stays editor-neutral (ADR 0003).
6. **`/skill-spotter:rule rN`** (manual-only, like every plugin skill):
   1. reads `skill-spotter show rN --json`;
   2. writes one general instruction from what the directives have in common;
   3. asks one question, personal file or project file (default: personal when seen in 2+ projects);
   4. edits the file, updating an existing line about the same thing if there is one;
   5. runs `skill-spotter accept rN <file>`.
7. **Lifecycle** is the same as for patterns: **[Not now]** and `snooze`, dismissal after two snoozes, `dismiss`, `accept`. `status` and `stats` list rules.
8. **Storage.** Migration 6 adds `rules`, `directives` (the sentence, already redacted as part of the prompt) and `events.rule_id`. Directives are pruned with turns at 90 days. The background job reads turns recorded before this feature, once.

## Calibration on real data

The prototype ran against one user's 124 recorded prompts:
- **With a frequency filter on common words:** nothing was found. The rule's own words were frequent precisely because the user kept repeating them.
- **Without it (shipped):** exactly one rule, `author claude`, with 8 directives, 6 sessions and 6 projects, typo included. No false positives.

The shipped code, replayed on a copy of the same database:
- **Rule:** `r1`, 7 prompts in 6 sessions across 6 projects.
- **Cost:** 12.8 ms to backfill 118 turns, 0.1 ms per turn to record, under 4 ms for the suggestion check.
- **Coverage:** no suggestion once `~/.claude/CLAUDE.md` holds the rule, and suggested without it.

## Known gaps

- **Mid-turn messages aren't recorded.** A message typed while Claude is still working doesn't go through `UserPromptSubmit`, so neither patterns nor rules see it.
- **The pair key is coarse.** Two different rules about the same two words would share a rule. The skill writes the instruction from the actual sentences, so the text stays right.
- **Coverage is word-based.** A CLAUDE.md line that mentions both words in an unrelated way hides the suggestion. That's the cheap, safe side to err on: a missed suggestion rather than a duplicate rule.
- **The shared normalizer's apostrophe quirk** also affects task matching. Fixing it there would shift the Method Lab calibration, so that needs its own run.
