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

After each reply, a `[skill-spotter] debug: …` message should appear. Note where and how it's shown.

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

Expect, after the third run: `Stop says: [skill-spotter] You've done this 3 times (pattern p1). Run /skill-spotter:draft p1 to save it as /update-changelog.`

```bash
$P/bin/skill-spotter --data-dir ~/.claude/plugins/data/skill-spotter-inline show p1
claude --plugin-dir $P -p "/skill-spotter:draft p1 manual" --permission-mode bypassPermissions
cat .claude/skills/update-changelog/SKILL.md      # manual-only skill with the observed steps
claude --plugin-dir $P -p "/update-changelog" --allowedTools "Bash(git *)" Read Edit
```

Interactively, `/skill-spotter:draft p1` asks one question (typed-only or model-invocable) and Claude Code asks you to approve writing into `.claude/skills/`.
