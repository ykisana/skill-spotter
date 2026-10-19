# skill-spotter

A Claude Code plugin that notices tasks you keep repeating and suggests saving them as a skill you can run with `/skill-name`.

> **Status: M1.** Records prompts and tool calls, recognises the same task phrased differently, suggests it after 3 times in 2+ sessions, and drafts the skill with `/skill-spotter:draft`. Lifecycle tracking (snooze, acceptance stats) is next.

- **Local only.** Data stays in Claude Code's plugin data folder. No network calls.
- **Zero tokens per turn.** Hooks print nothing to Claude. Suggestions use a `systemMessage`, which only you see.
- **Never creates a skill on its own.** You decide when to turn a suggestion into a skill.

## Try it

```bash
git clone https://github.com/ykisana/skill-spotter && cd skill-spotter
claude plugin validate .
claude --plugin-dir .
# then, in the session:
/skill-spotter:status
```

To see where suggestions will appear, start with `SKILL_SPOTTER_DEBUG_SUGGEST=1 claude --plugin-dir .`. A fake suggestion then shows after every reply.

## Commands

| Command | What it does |
|---|---|
| `/skill-spotter:status` | Show patterns, suggestions and created skills |
| `/skill-spotter:draft <id>` | Save a detected pattern as a `/skill` |
| `/skill-spotter:on` / `off` | Resume / pause suggestions |
| `/skill-spotter:forget` | Delete all stored data (asks first) |

The same commands work from a terminal: `bin/skill-spotter --help`.

## How it's built

```
hooks/on_*.py            thin entry points Claude Code runs
  → hookrunner.py        fail-open wrapper: always exit 0, log errors to a file
  → claude_code.py       adapter: Claude Code JSON ⇄ editor-neutral events
  → handlers.py          the logic (no-ops until M1)
store.py                 SQLite schema + migrations
cli.py / bin/            the skill-spotter command the skills call
skills/                  manual-only slash commands
```

Everything a hook imports is standard-library Python and runs on 3.9+. Decisions are recorded in [docs/adr](docs/adr).

## Development

```bash
python3 -m pytest
pipx run ruff check . && pipx run ruff format --check .
claude plugin validate .
```

Manual end-to-end checks: [docs/e2e.md](docs/e2e.md).
