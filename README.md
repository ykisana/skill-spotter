# skill-spotter

A Claude Code plugin that notices tasks you keep repeating and suggests saving them as a skill you can run with `/name`.

```
You:    write release notes into the changelog for commits after the latest tag, commit the result
Claude: (does the task)
        skill-spotter: You've repeated this 3 times: "write release notes into the
        changelog for commits after…"   [Create /update-changelog]  [Not now]
You:    /skill-spotter:draft p1
Claude: Saved. Next time: /update-changelog
```

It recognises a task from **what Claude actually did** (commands, files edited, tools called) as well as **what you typed**, so the same task phrased differently still counts. It also spots **multi-prompt workflows** ("list merged PRs" → "write the changelog" → "open the release PR") and suggests them as one skill.

- **Local only.** Everything stays in Claude Code's plugin data folder. Secrets are redacted before anything is stored, and nothing is sent anywhere.
- **Zero tokens per turn.** Hooks print nothing to Claude. A suggestion is a `systemMessage`, which you see and Claude doesn't. All plugin commands are manual-only, so their descriptions never sit in Claude's context.
- **Never creates a skill on its own.** You decide, with `/skill-spotter:draft`.
- **Methods chosen by measurement**, not guesswork: see the [Method Lab results](docs/benchmarks/README.md).

## Install

```bash
claude plugin marketplace add ykisana/skill-spotter
claude plugin install skill-spotter@skill-spotter
```

Or try it for one session from a clone: `claude --plugin-dir /path/to/skill-spotter`.

Requirements: Claude Code, and `python3` 3.9 or newer on your `PATH` (macOS's built-in one works). Nothing to `pip install`.

## Commands

| Command | What it does |
|---|---|
| `/skill-spotter:status` | Patterns, suggestions, skills it helped create, how often you use them, trigger scores |
| `/skill-spotter:draft <pN\|wN>` | Turn a pattern or workflow into a `SKILL.md` (asks whether Claude may run it on its own) |
| `/skill-spotter:on` / `:off` | Resume / pause suggestions (recording continues) |
| `/skill-spotter:train` | Run the background re-clustering now |
| `/skill-spotter:extras` | Optional: install numpy, scikit-learn and fastembed (about 400 MB) for a better background tier |
| `/skill-spotter:forget` | Delete everything stored (asks first) |

The CLI (`scripts/skill-spotter`) also has:
- `show`, `dismiss`, `snooze` and `stats` (suggestions shown, acceptance rate, skills used);
- `scan-shell`, which imports your zsh/bash history so repeated shell routines count too;
- `verify`, which trigger-tests skills Claude may start on its own. It spends tokens and only runs when you run it.

## How it works

```
prompt ──► UserPromptSubmit: filter, redact, normalize text ──────────┐
tool calls ──► PostToolUse (async): normalize commands to templates ──┤ SQLite (local)
Claude finishes ──► Stop: match the turn to a pattern ─► suggest? ────┘
                       └─► every 50 turns: background job merges patterns the online pass split
```

1. **Normalize.**
   - `git commit -m "fix typo"` becomes `git commit`, and `git commit -am "wip"` becomes `git commit -a`.
   - Runners are unwrapped (`uv run pytest` → `pytest`), and values, paths and secrets are dropped.
   - Prompts are lower-cased, values become placeholders, words are stemmed, and synonyms are applied ("release notes" → changelog).
2. **Match.** Each turn is compared with the recent members of candidate patterns, found through an inverted index. The comparison is a monotone logistic regression over:
   - BM25 text similarity;
   - action similarity;
   - sequence and file overlap;
   - a gate for turns with few meaningful actions.

   Turns with no meaningful actions match on wording.
3. **Suggest.** A pattern is suggested after 3 occurrences in 2+ sessions within 30 days, at most once per session and 3 times a day. Generic patterns (only `git status`, reads) are never suggested. Anything with dangerous steps (`--force`, `deploy`, `rm -rf`…) becomes a manual-only skill with a confirmation step.
4. **Follow up.**
   - **Ignored suggestions** are snoozed for 14 days, then dismissed.
   - **Accepted:** detected when the skill file appears.
   - **Used:** each time you type the skill's command, the use is counted.

**Multi-prompt workflows:** sequences of 2–4 patterns that recur in 3 sessions become one suggestion, and their steps aren't suggested separately.

## Results

From the [Method Lab](docs/benchmarks/README.md). The benchmark is a synthetic set of 98 task families with 6,460 turns, about 5 one-off turns for every repeated one, replayed chronologically through the real hook code:

| | precision | recall | first suggested at occurrence (median) |
|---|---|---|---|
| test split, shipped runtime | 1.00 | 0.97 | 5 |
| dev split, shipped runtime | 0.98 | 0.97 | 4 |
| M1 rule baseline, test | 0.67 | 0.87 | 7 |

Other numbers:
- **Latency:** the `Stop` hook adds about 40 ms (p95 under 100 ms with 2,000 stored turns). Recording a tool call takes 0.1 ms and runs in the background.
- **Trigger quality of a drafted, model-invocable skill:** F1 0.73–0.80 over 8 generated prompts, via `skill-spotter verify`.
- **Caveat:** the numbers come from synthetic data. Before trusting them for your work, label some of your own turns with `bench.label`; the selection rule requires precision ≥ 0.85 there too.

## Optional: band above the prompt (mods)

With Claude Code v2.1.287+, the bundled mod shows suggestions as a band above the prompt with **[Create /name]** and **[Not now]** buttons instead of a message. On older versions it doesn't load, and you get a message under Claude's reply instead (Claude Code labels every hook message `Stop says:`):

```
Stop says: skill-spotter: you've repeated this 3 times: "write release notes into the changelog
           for commits after…". To save it as /update-changelog, run /skill-spotter:draft p1
```

## Privacy

- **Stored:** redacted prompts, normalized command templates, project-relative file names, and pattern statistics.
- **Never stored:** tool output, secrets (tokens, keys, passwords, connection strings are redacted), or anything from transcripts.
- **Retention:** turns older than 90 days are deleted; pattern summaries stay.
- **Deleting everything:** `/skill-spotter:forget`.
- **Network:** the only network access is the optional `extras` install, which asks first.

## Known limitations

- Paraphrased *questions* answered only by exploring (e.g. "which commits landed since we last tagged" vs "list the commits since the last tag") don't match: with no meaningful actions, only the wording can, and paraphrases share few words.
- Single-edit tasks with very different wording can split into two patterns. The background job merges some of these; your own labelled data is the way to tune it.
- The shipped matcher was chosen on synthetic data. See [ADR 0007](docs/adr/0007-method-selection.md) for what that hid and how the model was constrained.

## Development

```bash
python3 -m pytest                                   # 300+ tests, stdlib only
pipx run ruff check . && pipx run ruff format --check .
claude plugin validate .
claude plugin test                                  # the mod band, Claude Code's test kit
python3 -m bench.replay --quick --min-precision 0.9 # what CI replays on every push
```

The Method Lab (`bench/`) needs its own environment: `python3 -m venv .venv && .venv/bin/pip install -r bench/requirements.txt`. See [docs/e2e.md](docs/e2e.md) for manual checks per milestone, [docs/method-lab.md](docs/method-lab.md) for a short write-up, and [docs/adr](docs/adr) for every decision.

## License

MIT
