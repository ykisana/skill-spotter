# 0007: Method selection (M3 → M4)

- Status: accepted (provisional until the real held-out check, SPEC 11.5)
- Date: 2026-10-19
- Evidence: `docs/benchmarks/README.md`, `bench/results/` (results, sweep, runtime check)

## Selection rule (SPEC 11.8) applied

1. **Hard constraints:** zero runtime tokens (all candidates); the online tier is stdlib-only with `Stop` p95 under 100 ms; heavy dependencies only in the background tier.
2. **Primary:** replay precision ≥ 0.90 on synthetic test. The real held-out check (≥ 0.85) is pending.
3. **Then recall, then pairwise F1, preferring simpler within 2 points.**
4. **Added after M3 findings (below):** online learned fusers must be monotone, meaning they can't put negative weight on any similarity feature.

## Online tier: `config/method.json`

**Monotone logistic-regression fusion with leader clustering, θ = 0.7.**
- **Features:** BM25 text, hierarchical action Jaccard without IDF, LCS sequence similarity, edited-file overlap, `action × text`, and a "fewer than 3 meaningful actions" gate.
- **Comparison:** a turn is scored against the last 10 members of up to 20 candidate patterns.
- **Learned weights (standardised):** text 0.17, action 1.47, sequence 1.18, files 0, action × text 0, few-actions −1.99.
- **Implementation:** stdlib, a dot product and a sigmoid (`match/fused.py`).

| replay (synthetic) | dev P | dev R | test P | test R |
|---|---|---|---|---|
| rule, M1 baseline before ADR 0006 | 0.651 | 0.883 | 0.671 | 0.868 |
| rule after ADR 0006 fixes | 0.883 | 0.883 | 0.903 | 0.895 |
| rule, swept parameters | 0.906 | 0.967 | 0.899 | 0.947 |
| logreg (unconstrained, content features) | 0.955 | 0.950 | 0.977 | 0.974 |
| **logreg_monotone, lab simulation** | **0.969** | **0.950** | **1.000** | **0.974** |
| **logreg_monotone, shipped runtime** | **0.978** | **0.967** | **1.000** | **0.974** |

**M4 check:** the shipped runtime matches the lab's simulation within 0.05: dev +0.009 precision / +0.017 recall; test identical.

## Why "monotone" and "content features only"

Two learned models looked best on paper and were wrong in ways the synthetic numbers didn't show. Scenario tests (`tests/test_shipped_matcher.py`) caught both:

1. **Timeline and count features were dropped** (same session, time gap, raw action counts). With them, the model learned the generator's timeline: synthetic repeats never happen within one session, so "same session" became evidence of a *different* task. On real use, two identical login fixes in one session scored 0.34.
2. **Similarity weights are constrained to ≥ 0.** Synthetic repeats are deliberately paraphrased, so high word overlap was rare in training, and the unconstrained model gave `action × text` a negative weight. It rejected near-identical prompts and accepted two unrelated `psql -c` questions (0.85).
3. **θ tie-break:** where several thresholds tie on dev recall and are within 0.01 on precision, the lowest is chosen (0.7 rather than 0.9). That keeps real near-identical repeats, which synthetic data under-represents, joining their pattern.

## Background tier: `config/method.extras.json`

**Monotone logistic regression with jina-embeddings-v2-small text similarity.** Lab replay on test gives precision 1.0 and recall 0.974. The background job uses it only to merge patterns the online matcher split, and to mark merged patterns `ready`.
- **Gradient-boosted trees were also evaluated:** test PR-AUC 0.969, but replay recall on test was 0.895.
- **Batch re-clustering as a suggestion source was rejected:** HDBSCAN or agglomerative clustering every 50 turns keeps precision about 0.99, but adds dozens of duplicate suggestions without raising recall.

## Other categories

- **Command templating:** the hand rules stay. Entropy typing and Fig specs score slightly higher on grouping accuracy and on pairwise action PR-AUC, but both need a learned or bundled model, and replay recall is already 0.97. That's within the "prefer simpler" margin. Revisit with real data.
- **Lookup:** the inverted index on distinctive action tokens and text words stays; it's needed for latency. For vectors in the background tier, FAISS-HNSW matches brute-force recall@10 (0.85) at 0.06 ms per query with 100k vectors. sqlite-vec couldn't be measured on this Python build (no extension loading).
- **Multi-turn sequences (M5):** n-grams allowing one gap find all 15 planted workflows with no false ones. PrefixSpan and SPADE find them too, but report false workflows because they allow arbitrary gaps.
- **Naming:**
  - The heuristic scores 2.66/5 with a blind judge, against 4.84 for Claude's names; it scored 1.87 before tuning on dev. (2.87 after the fixes in ADR 0009.)
  - Claude names the skill when drafting, so the heuristic is only the suggestion's placeholder.
  - A local LLM wasn't evaluated: none is installed, and disk space is short.

## Consequences

- `method_version` is `stdlib-2026-10-19`. Existing databases keep their patterns; new turns use the fused matcher.
- The real held-out set (`bench.label`) must confirm precision ≥ 0.85 before release. If it doesn't, the swept rule is the fallback (`"fusion": "rule"` with the sweep's `rule_params` and `"action_weighting": "none"`).
- CI replays a fixed slice of the test split through the real hooks on every push. `tests/test_shipped_matcher.py` guards basic behaviour of whatever model ships.
