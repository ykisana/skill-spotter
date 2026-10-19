# skill-spotter: dev notes

- Build one milestone at a time. M0 (scaffold) is done; M1 is turn capture + baseline matching.
- Record decisions in `docs/adr/`. Check the Claude Code docs before relying on any hook, manifest or skill field (ADR 0002 is the last check).
- **Commits:** one-line lowercase messages. No Claude attribution, no `Co-Authored-By`, no "Generated with" lines.
- **Online tier:** everything hooks import (`src/skill_spotter/`). Standard library only, and it must run on Python 3.9 (keep `typing.Dict`/`Optional`, no `match`). `tests/test_plugin_layout.py` enforces this.
- **Hooks:** they fail open and print nothing except the `Stop` `systemMessage`. Only `claude_code.py` knows Claude Code formats; `handlers.py` is editor-neutral (a Cursor adapter is planned, see ADR 0003).
- **Plugin skills:** all have `disable-model-invocation: true`.
- Commands:
  - tests: `python3 -m pytest`
  - lint: `pipx run ruff check . && pipx run ruff format --check .`
  - validate: `claude plugin validate .`
  - try it: `claude --plugin-dir .`
- Pipe a fixture into a hook: `SKILL_SPOTTER_DATA=/tmp/ss python3 hooks/on_stop.py < tests/fixtures/hook_inputs/stop.json`
