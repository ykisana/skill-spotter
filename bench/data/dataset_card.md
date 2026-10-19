# Dataset card: skill-spotter synthetic v1

Synthetic, AI-generated benchmark for deciding whether two Claude Code turns are the same task.
No real user data. Generated at development time with `claude -p` (SPEC 11.4); raw replies are
cached in `bench/data/raw/` (keyed by sha256 of model + prompt), so `bench.generate.build` rebuilds
the same dataset without new calls.

## Sources

- **Families** (`catalog.py`, Sonnet): 98 task families in 14 categories, each with an intent,
  parameters, an action-trace template, 10 prompt variants (2 light, 3 heavy, 2 terse, 1 typo, 2 param)
  and 4 hard negatives (lookalike but different tasks, with their own traces).
- **One-offs** (`oneoffs.py`, Haiku): single-occurrence requests per category and project type.
- **Action traces** are expanded by code (`traces.py`) with perturbations: parameter values, skipped
  optional steps, reordered independent steps, exploration noise (git status, ls, reads), failed-and-
  retried commands (15%), subagent actions (15%).
- **Timeline** (`build.py`, seed 2026): 11 projects, 75 days from 2026-08-03, sessions per project and day;
  each family's repeats spread over 12-70 days, so some are frequent and some rarely repeat within 30 days.
- **Generation calls:** 116 (budget 300), about $6.49.

## Counts

| split | turns | positive | hard_negative | one_off |
|---|---|---|---|---|
| dev | 3852 | 598 | 240 | 3014 |
| test | 2608 | 379 | 152 | 2077 |

Families are split by family (60% dev / 40% test): no family appears in both.

### Difficulty tiers (positives, both splits)

```
{"heavy": 294, "light": 196, "param": 193, "terse": 196, "typo": 98}
```

### Categories (all items)

```
{"data": 491, "database": 495, "debugging": 456, "deploy": 478, "deps": 412, "docs": 493, "git": 425, "infra": 480, "mcp": 488, "mobile": 498, "release": 478, "review": 404, "scaffold": 495, "testing": 367}
```

## Quality control

- Schema validation dropped 0 items.
- Duplicates dropped: {'exact': 18, 'near_duplicate_of_positive': 1}.
- AI label audit (Haiku, second pass) on 9 sampled families,
  125 items: agreement 1.0. Flagged items are listed in
  `bench/data/audit.json`.
- Human spot-check: **pending.** 50 random items are in `bench/data/spotcheck.md` for the owner to mark.

## Known gaps

- Prompts are written by models, so they're cleaner and more uniform than real ones; typos are mild.
- Traces come from templates: real sessions have more exploration, longer retries and more variety in
  commands. Matching quality on real data can be lower or higher; the real held-out set (SPEC 11.5)
  decides.
- Terse prompts under 4 words are filtered by the runtime on purpose, which lowers replay recall.
- Multi-turn workflows (a task split over several prompts) are not in v1; M5 adds them.
- English only.
