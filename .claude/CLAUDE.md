# skill-spotter: dev notes

- Milestones M0–M8 are built (see `docs/adr/` 0001–0008). Open items: real held-out labelling (`bench.label`), live test of the mod band on Claude Code ≥ 2.1.287, publishing.
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
- CLI: `scripts/skill-spotter` (not `bin/`: claude.ai/Cowork refuse a top-level `bin/`).
- Method Lab: `.venv/bin/python -m bench.run --reuse --stages ...`, then `bench.select`, `bench.export_extras`, `bench.validate_runtime`, `bench.report`. Scenario guard for the shipped model: `tests/test_shipped_matcher.py`.
- Pipe a fixture into a hook: `SKILL_SPOTTER_DATA=/tmp/ss python3 hooks/on_stop.py < tests/fixtures/hook_inputs/stop.json`
