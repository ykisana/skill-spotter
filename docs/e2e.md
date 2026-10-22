# Manual end-to-end checks

## M0: scaffold

```bash
claude plugin validate .                 # expect: ✔ Validation passed
claude --plugin-dir .                    # starts with no plugin errors
```

In that session:

1. `/skill-spotter:status` → `skill-spotter: no patterns yet.`, plus a line showing suggestions on, 0 turns, and the data dir (`~/.claude/plugins/data/skill-spotter-inline`).
2. `/skill-spotter:off`, then `/skill-spotter:status` → `Suggestions: paused`. Then `/skill-spotter:on`.
3. Send any prompt. Nothing from skill-spotter appears, and `<data dir>/logs/errors.log` doesn't exist.

Suggestion display (open question 2):

```bash
SKILL_SPOTTER_DEBUG_SUGGEST=1 claude --plugin-dir .
```

After each reply, a `skill-spotter: debug: …` message should appear. Note where and how it's shown.

Hooks firing:

```bash
claude --plugin-dir . --debug-file /tmp/ss.log   # ask something that uses a tool, then /exit
grep -E "hooks/on_" /tmp/ss.log                  # each should complete with status 0
rm -f /tmp/ss.log latest                         # --debug-file leaves a `latest` symlink
```

Headless check of the main done-criterion:

```bash
claude --plugin-dir . -p "/skill-spotter:status"
```

## M1: detect a repeated task and draft a skill

Use a throwaway repo; the headless commands below use `bypassPermissions` only for the draft step.

```bash
rm -rf ~/.claude/plugins/data/skill-spotter-inline        # start clean (dev data only)
mkdir /tmp/ss-scratch && cd /tmp/ss-scratch && git init -b main
printf '# Changelog\n\n## Unreleased\n' > CHANGELOG.md && git add -A && git commit -m init && git tag v0.1.0
echo x >> CHANGELOG.md && git commit -am "some change"
```

Do the same task three times, each in a new session, with different wording (add a commit in between so there's something to summarise):

```bash
P=/path/to/skill-spotter
claude --plugin-dir $P -p "add a changelog entry under Unreleased summarizing the commits since the last tag, then commit it" --allowedTools "Bash(git *)" Read Edit
claude --plugin-dir $P -p "update CHANGELOG.md with what changed since the previous release tag and commit" --allowedTools "Bash(git *)" Read Edit
claude --plugin-dir $P -p "write release notes into the changelog for commits after the latest tag, commit the result" --allowedTools "Bash(git *)" Read Edit --output-format stream-json --verbose | grep "skill-spotter]"
```

Expect, after the third run: `Stop says: skill-spotter: you've repeated this 3 times: "write release notes into the changelog for commits after…". To save it as /update-changelog, run /skill-spotter:draft p1`

```bash
$P/scripts/skill-spotter --data-dir ~/.claude/plugins/data/skill-spotter-inline show p1
claude --plugin-dir $P -p "/skill-spotter:draft p1 manual" --permission-mode bypassPermissions
cat .claude/skills/update-changelog/SKILL.md      # manual-only skill with the observed steps
claude --plugin-dir $P -p "/update-changelog" --allowedTools "Bash(git *)" Read Edit
```

Interactively, `/skill-spotter:draft p1` asks one question (typed-only or model-invocable) and Claude Code asks you to approve writing into `.claude/skills/`.

## M2: lifecycle

Lower the thresholds in a dev database so one session is enough (undo afterwards):

```bash
D=~/.claude/plugins/data/skill-spotter-inline
sqlite3 $D/skill-spotter.db "insert or replace into settings values('min_count','1'),('min_sessions','1');"
```

| Check | How | Expect |
|---|---|---|
| Snooze on session end | run any new task headless; the session ends | `patterns.state = snoozed`, a `snoozed` event with `until` 14 days out |
| Accept via ConfigChange | in a session long enough for the file watcher (e.g. ask Claude to write `.claude/skills/<suggested-name>/SKILL.md` then `sleep 3`) | `accepted` event with `"via": "config_change"`; debug log shows `ConfigChange:skills … status 0` |
| Accept via scan | create the skill folder outside a session, then run any turn in the project | `"via": "scan"` |
| Usage | `claude -p "/<skill-name>"` | a `used` event; `skill-spotter status` shows `used 1x` |
| Stats | `scripts/skill-spotter --data-dir $D stats` | suggestions shown, accepted %, skills used at least once |

```bash
sqlite3 $D/skill-spotter.db "delete from settings where key in ('min_count','min_sessions');"
```

## M3–M4: Method Lab and the shipped matcher

```bash
.venv/bin/python -m bench.run --reuse --stages text,templating,actions,fusion,cluster,replay
.venv/bin/python -m bench.select && .venv/bin/python -m bench.export_extras
.venv/bin/python -m bench.validate_runtime     # real hooks vs lab simulation, tolerance 0.05
.venv/bin/python -m bench.report               # docs/benchmarks/README.md
python3 -m bench.replay --quick --min-precision 0.9 --min-recall 0.6   # the CI check, stdlib only
```

Background tier: `scripts/skill-spotter train` runs the job synchronously and prints its summary.
`scripts/skill-spotter extras` installs the optional dependencies (asks first; about 400 MB).

## M5: workflows and shell history

- Do the same three prompts in a row (e.g. list merged PRs → write the changelog entry → open the release PR) in three sessions. After the third session's last step, one suggestion appears: `skill-spotter: you've run these 3 steps together in 3 sessions: /… → /… → /…. To save them as /…, run /skill-spotter:draft wN`. No step is suggested on its own.
- `scripts/skill-spotter show wN` lists the steps; `/skill-spotter:draft wN` writes one skill that runs them in order.
- `scripts/skill-spotter scan-shell --project .` imports your zsh/bash history for this project (local only; re-running adds nothing new).

## M6: skill verification

```bash
scripts/skill-spotter verify path/to/.claude/skills/<name>/SKILL.md --n 4      # ~9 Haiku calls
scripts/skill-spotter verify --revise                                           # all skills it created
```

Manual-only skills are skipped (their quality signal is `used` events). `/skill-spotter:status` shows `trigger F1 0.80 (8 prompts)` next to verified skills.

## M7: mod band

Requires Claude Code v2.1.287+ (`claude --version`). Load with `claude --plugin-dir .`, repeat a task until a suggestion is due: instead of the `Stop says: skill-spotter: …` notice, a band above the prompt shows `skill-spotter: You've repeated this 3 times: "…"  [Create /name] [Not now]`. Create fills the prompt with `/skill-spotter:draft pN`; Not now snoozes the pattern. On older versions the module doesn't load and the notice appears as before. `claude plugin validate .` lists the module's hooks and calls, and `claude plugin test` runs its tests.

If no band appears, start with `claude --debug` and grep the log for `skill-spotter`: a line `hooks module skill-spotter@… loaded` then `session.start settled` with no `hook failed` means the mod ran. While the session is open, `ls ~/.claude/plugins/data/skill-spotter/band/` shows a `<session>.on` file (ADR 0009).
