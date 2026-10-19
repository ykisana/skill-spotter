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
