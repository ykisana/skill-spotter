# 0006: M3 findings — one-offs fool action similarity; tasks fragment

- Status: accepted
- Date: 2026-10-19
- Milestone: M3

## What the first full lab run showed

With the full dataset (about 5 one-off turns per repeated turn), every matcher was too trusting of action similarity:

| replay on synthetic test (real hooks) | precision | recall | false / 100 turns |
|---|---|---|---|
| runtime baseline, before | 0.671 | 0.868 | 1.07 |
| learned fusion (logreg, stdlib features), before | 0.578 | 0.974 | 1.15 |

Inspecting the false suggestions, they fall into three groups:

1. **Exploration-only turns matched each other.** Two different questions answered with only Grep or Read have identical fingerprints made of low-weight `read:` tokens. Weighted Jaccard of identical sets is 1.0, whatever the weights or IDF.
2. **Same tool, different task.** Several `psql -c "…"` questions, or `pod …` commands, share one command template, while their prompts share nothing.
3. **Label noise.** Some one-offs are arguably the same task as a family (e.g. "generate a v2.1.0 changelog entry"). That puts a ceiling on measurable precision.

Separately, about 13 test families were suggested twice. One task got **split across two patterns**: optional or rare steps (an occasional `kubectl logs`) carry high IDF, so leaving them out pushed action similarity below the 0.7 threshold, and paraphrased prompts added little text overlap.

The pairwise benchmark hid all of this: its random negatives rarely shared a command, so pairwise PR-AUC was about 0.99 while replay precision was about 0.6.

## Decisions

1. **Only meaningful tokens count towards action similarity** (`baseline.meaningful`, weight ≥ 0.25). L1 command names and low-value exploration tokens are dropped first, so a turn with no meaningful actions scores 0 on actions and text decides.
2. **Text gate:** an action-only match ("action ≥ 0.7") needs text similarity ≥ 0.08 when either turn has fewer than 3 meaningful actions.
3. **No double suggestions:** before suggesting, a pattern that the rule says is the same task as one already suggested, snoozed, accepted or dismissed in the project is merged into it instead.
4. **The benchmark gets harder negatives:** `shared_command` pairs, meaning same project, sharing a meaningful command token, different task.
5. **New candidates:** `hier_jaccard_meaningful` and `hier_idf_jaccard_meaningful` action representations, and `action_x_text` / `few_actions` interaction features for the learned fusers. The runtime scorer (`match/fused.py`) mirrors the features.
6. **Replay reports duplicates in two parts:** `resuggested_after_snooze` (by design: snooze for 14 days, suggest again, then dismiss) and `extra_patterns_per_family` (the matcher split a task).
7. **The online matcher's parameters are configurable** via `config/method.json` (`rule_params`, `action_weighting`) and swept with the real-hook replay (`bench.sweep`): tune on dev, confirm on test.

## Effect (real-hook replay)

| | dev precision | dev recall | test precision | test recall | false / 100 turns (test) |
|---|---|---|---|---|---|
| before | 0.651 | 0.883 | 0.671 | 0.868 | 1.07 |
| decisions 1–3 | 0.903 | 0.883 | 0.933 | 0.868 | 0.15 |

The sweep results and the final choice are in `docs/benchmarks/README.md` and ADR 0007.
