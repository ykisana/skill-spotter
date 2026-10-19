# 0007: Method selection (M3 → M4)

- Status: accepted (provisional until the real held-out check, SPEC 11.5)
- Date: 2026-10-19
- Evidence: `docs/benchmarks/README.md`, run `2026-10-19T12:28:29`, sweep and runtime check

## Selection rule (SPEC 11.8) applied

1. **Hard constraints:** zero runtime tokens (all candidates); the online tier is stdlib-only with `Stop` p95 under 100 ms; heavy dependencies only in the background tier.
2. **Primary:** replay precision ≥ 0.90 on synthetic test. The real held-out check (≥ 0.85) is pending.
3. **Then recall, then pairwise F1, preferring simpler within 2 points.**

## Online tier: `config/method.json`

**Logistic-regression fusion with leader clustering, θ = 0.7.**
- **Text:** BM25.
- **Actions:** hierarchical Jaccard without IDF.
- **Other features:** LCS sequence similarity, edited-file overlap, meaningful-action counts, same session, log time gap, plus the `action × text` and `few actions` interactions.
- **Comparison:** a turn is scored against the last 10 members of up to 20 candidate patterns.
- **Implementation:** stdlib, a dot product and a sigmoid (`match/fused.py`).

| candidate (stdlib) | test precision | test recall | pairwise test PR-AUC |
|---|---|---|---|
| rule (M1), after ADR 0006 fixes | 0.918 | 0.895 | 0.879 |
| rule, swept | 0.899 | 0.947 | – |
| linear fusion | – | – | 0.870 |
| **logreg fusion + leader** | **0.954 (lab) / 0.969 (runtime)** | **1.000** | **0.980** |

The swept rule just misses the 0.90 bar on test (0.899), while logreg passes it with higher recall. Logreg costs a little more per pair, but `Stop` stays within budget. Among online clusterers, connected components was rejected: it chains unrelated turns (ARI 0.28 against the leader's 0.70 on the first run).

**M4 check:** the shipped runtime reproduces the lab's simulation within 0.05 on both splits. Precision is +0.023 on dev and +0.015 on test; recall is identical.

## Background tier: `config/method.extras.json` + `config/model.extras.pkl`

**Gradient-boosted fusion with jina-embeddings-v2-small text, used by the background job to merge split patterns.**
- **Results:** lab replay with the online leader gives test precision 1.0 and recall 1.0. Pairwise test PR-AUC is 0.981.
- **Batch re-clustering as a suggestion source was rejected.** HDBSCAN or agglomerative clustering every 50 turns keeps precision about 0.99, but adds 54–60 duplicate suggestions on test without raising recall. The background job therefore only merges patterns the online matcher split, and marks merged patterns `ready`; it never creates suggestions of its own.
- **Model file:** pickled with scikit-learn 1.9.1, the version the `extras` installer pins.

## Other categories

- **Command templating:** the hand rules stay. Entropy typing and Fig specs score slightly higher on grouping accuracy and on pairwise action PR-AUC (Fig 0.994 vs hand 0.984 on test). But both need a learned or bundled model, and end-to-end replay is already at recall 1.0. That's within the "prefer simpler" margin. Revisit with real data.
- **Lookup:** the inverted index on distinctive action tokens and text words stays. It's needed for latency (no JSON parsing of every pattern) and is exact for the candidates it returns. For vector lookup in the background tier, FAISS-HNSW gives brute-force recall@10 (0.85) at 0.06 ms per query with 100k vectors. sqlite-vec couldn't be measured on this Python build (no extension loading).
- **Multi-turn sequences:** n-grams allowing one gap (in the runtime) find all 15 planted workflows with no false ones. PrefixSpan and SPADE find them too, but report false workflows because they allow arbitrary gaps.
- **Naming:**
  - The heuristic scores 2.66/5 on a blind judge, against 4.84 for Claude's names; it scored 1.87 before tuning on dev.
  - Claude names the skill when drafting, so the heuristic is only the suggestion's placeholder.
  - A local LLM wasn't evaluated: none is installed, and disk space is short.

## Consequences

- `method_version` is `stdlib-2026-10-19`. Existing databases keep their patterns; new turns use the fused matcher.
- The real held-out set (`bench.label`) must confirm precision ≥ 0.85 before release. If it doesn't, the swept rule is the fallback (set `"fusion": "rule"` with the sweep's `rule_params`).
- CI replays a fixed slice of the test split through the real hooks on every push.
