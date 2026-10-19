# Method Lab results

Run `2026-10-19T13:07:29` on the synthetic v1 dataset ([dataset card](../../bench/data/dataset_card.md)). Reproduce with `.venv/bin/python -m bench.run --stages text,templating,actions,fusion,cluster,replay`, then `bench.scale`, `bench.naming`, `bench.select`, `bench.report`.

**Caveat:** synthetic traces come from templates, so action similarity is easier here than on real
sessions. The real held-out check (SPEC 11.5) is still pending; the configs are provisional until it passes.

## Dataset
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

## Pairwise: text

![text PR curves](pr_text.png)

| method | track | dev PR-AUC | test PR-AUC | test P | test R | test F1 | P@0.9 recall (test) |
|---|---|---|---|---|---|---|---|
| jina_small | extras | 0.528 | 0.563 | 0.490 | 0.677 | 0.569 | 0.000 |
| bge_small | extras | 0.527 | 0.558 | 0.433 | 0.748 | 0.548 | 0.001 |
| leaf_mt | extras | 0.513 | 0.552 | 0.445 | 0.714 | 0.549 | 0.001 |
| nomic_q | extras | 0.509 | 0.546 | 0.468 | 0.681 | 0.554 | 0.001 |
| minilm_l6 | extras | 0.500 | 0.520 | 0.430 | 0.752 | 0.547 | 0.000 |
| model2vec_potion32m | extras | 0.475 | 0.509 | 0.405 | 0.709 | 0.515 | 0.001 |
| model2vec_potion8m | extras | 0.467 | 0.508 | 0.409 | 0.696 | 0.515 | 0.001 |
| tfidf_char | extras | 0.456 | 0.505 | 0.443 | 0.716 | 0.547 | 0.001 |
| bm25 | stdlib | 0.443 | 0.490 | 0.458 | 0.595 | 0.518 | 0.001 |
| tfidf_word | extras | 0.438 | 0.477 | 0.417 | 0.687 | 0.519 | 0.000 |
| word_jaccard | stdlib | 0.413 | 0.448 | 0.368 | 0.831 | 0.510 | 0.006 |
| minhash | extras | 0.406 | 0.436 | 0.368 | 0.827 | 0.510 | 0.000 |
| arctic_s | extras | 0.360 | 0.372 | 0.339 | 0.599 | 0.433 | 0.000 |
| arctic_xs | extras | 0.357 | 0.370 | 0.327 | 0.678 | 0.441 | 0.001 |
| simhash | stdlib | 0.336 | 0.367 | 0.312 | 0.510 | 0.387 | 0.001 |

## Command templating

Grouping accuracy: calls generated from the same trace step should get the same template.

| templater | dev group F1 | test group F1 | test precision | test recall |
|---|---|---|---|---|
| hand | 0.905 | 0.852 | 0.889 | 0.818 |
| drain | 0.841 | 0.862 | 0.908 | 0.821 |
| drain3 | 0.851 | 0.870 | 0.869 | 0.871 |
| entropy | 0.871 | 0.890 | 0.957 | 0.832 |
| fig | 0.867 | 0.837 | 0.840 | 0.834 |
| lsh | 0.855 | 0.873 | 0.945 | 0.811 |

## Pairwise: actions

![action PR curves](pr_actions.png)

| method | track | dev PR-AUC | test PR-AUC | test P | test R | test F1 | P@0.9 recall (test) |
|---|---|---|---|---|---|---|---|
| hier_idf_jaccard[entropy] | stdlib | 0.842 | 0.874 | 0.826 | 0.947 | 0.882 | 0.360 |
| hier_idf_jaccard[fig] | stdlib | 0.845 | 0.870 | 0.819 | 0.909 | 0.862 | 0.364 |
| hier_idf_jaccard[lsh] | extras | 0.835 | 0.860 | 0.824 | 0.912 | 0.866 | 0.325 |
| hier_jaccard_noidf[hand] | stdlib | 0.846 | 0.858 | 0.836 | 0.857 | 0.846 | 0.330 |
| hier_idf_jaccard[drain] | stdlib | 0.834 | 0.856 | 0.831 | 0.907 | 0.867 | 0.337 |
| tfidf_templates[hand] | extras | 0.835 | 0.851 | 0.762 | 0.868 | 0.811 | 0.326 |
| hier_idf_jaccard[hand] | stdlib | 0.832 | 0.847 | 0.810 | 0.861 | 0.834 | 0.330 |
| hier_idf_jaccard[drain3] | extras | 0.821 | 0.846 | 0.822 | 0.905 | 0.861 | 0.071 |
| hier_jaccard_meaningful[hand] | extras | 0.770 | 0.784 | 0.786 | 0.885 | 0.833 | 0.330 |
| hier_idf_jaccard_meaningful[hand] | extras | 0.767 | 0.780 | 0.803 | 0.861 | 0.831 | 0.330 |
| embed_templates[hand] | extras | 0.740 | 0.761 | 0.728 | 0.908 | 0.808 | 0.150 |
| seq_edit[hand] | stdlib | 0.713 | 0.728 | 0.835 | 0.818 | 0.827 | 0.330 |
| seq_dtw[hand] | stdlib | 0.713 | 0.728 | 0.832 | 0.821 | 0.826 | 0.330 |
| seq_lcs[hand] | stdlib | 0.700 | 0.717 | 0.645 | 0.901 | 0.752 | 0.330 |
| fileset[hand] | stdlib | 0.372 | 0.354 | 0.643 | 0.356 | 0.459 | 0.284 |

## Fusion

Inputs: text = {'stdlib': 'bm25', 'extras': 'jina_small'}, actions = {'stdlib': 'hier_jaccard_noidf[hand]', 'extras': 'hier_jaccard_noidf[hand]'}.

![fusion PR curves](pr_fusion.png)

| method | track | dev PR-AUC | test PR-AUC | test P | test R | test F1 | P@0.9 recall (test) |
|---|---|---|---|---|---|---|---|
| logreg<extras> | extras | 0.962 | 0.971 | 0.941 | 0.886 | 0.913 | 0.886 |
| logreg_monotone<extras> | extras | 0.960 | 0.971 | 0.932 | 0.883 | 0.907 | 0.883 |
| logreg<stdlib> | stdlib | 0.962 | 0.970 | 0.933 | 0.899 | 0.916 | 0.899 |
| logreg_monotone<stdlib> | stdlib | 0.959 | 0.970 | 0.963 | 0.858 | 0.907 | 0.858 |
| gbt<extras> | extras | 0.999 | 0.969 | 0.938 | 0.902 | 0.920 | 0.902 |
| rule<stdlib> | stdlib | 0.860 | 0.879 | 0.820 | 0.881 | 0.849 | 0.338 |
| linear<extras> | extras | 0.864 | 0.874 | 0.830 | 0.870 | 0.850 | 0.330 |
| linear<stdlib> | stdlib | 0.856 | 0.870 | 0.823 | 0.875 | 0.848 | 0.330 |
| rule<extras> | extras | 0.700 | 0.724 | 0.865 | 0.767 | 0.813 | 0.390 |

- `logreg<stdlib>` coefficients (standardised features): `{'text': 0.442, 'action': 2.313, 'seq': 0.987, 'files': -0.292, 'action_x_text': -0.44, 'few_actions': -2.269}`
- `logreg_monotone<stdlib>` coefficients (standardised features): `{'text': 0.17, 'action': 1.469, 'seq': 1.183, 'files': 0.0, 'action_x_text': 0.0, 'few_actions': -1.994}`
- `logreg<extras>` coefficients (standardised features): `{'text': 0.498, 'action': 2.734, 'seq': 0.971, 'files': -0.294, 'action_x_text': -0.728, 'few_actions': -2.229}`
- `logreg_monotone<extras>` coefficients (standardised features): `{'text': 0.359, 'action': 0.938, 'seq': 0.989, 'files': 0.0, 'action_x_text': 0.692, 'few_actions': -1.972}`

Test breakdown by pair type for `logreg<stdlib>`:

| pair type | n | recall / false-positive rate |
|---|---|---|
| hard_different | 808 | FP rate 0.007 |
| hard_related | 708 | FP rate 0.021 |
| heavy | 567 | recall 0.898 |
| light | 38 | recall 0.895 |
| param | 187 | recall 0.898 |
| random_oneoff | 2635 | FP rate 0.000 |
| random_other_task | 767 | FP rate 0.003 |
| shared_command | 1701 | FP rate 0.051 |
| terse | 568 | recall 0.908 |
| typo | 341 | recall 0.886 |

## Clustering

| clusterer | track | theta | test B3-F1 | B3-P | B3-R | ARI | NMI | V | one-offs left alone |
|---|---|---|---|---|---|---|---|---|---|
| louvain<extras> | extras | 0.8 | 0.989 | 0.989 | 0.988 | 0.926 | 0.997 | 0.997 | 0.985 |
| agglomerative_average<extras> | extras | 0.7 | 0.988 | 0.994 | 0.981 | 0.917 | 0.997 | 0.997 | 0.987 |
| components<stdlib> | stdlib | 0.8 | 0.987 | 0.996 | 0.978 | 0.901 | 0.997 | 0.997 | 0.992 |
| leader<extras> | extras | 0.6 | 0.985 | 0.990 | 0.981 | 0.909 | 0.997 | 0.997 | 0.980 |
| components<extras> | extras | 0.9 | 0.985 | 0.985 | 0.986 | 0.867 | 0.996 | 0.996 | 0.990 |
| dbscan<extras> | extras | 0.9 | 0.985 | 0.985 | 0.986 | 0.867 | 0.996 | 0.996 | 0.990 |
| agglomerative_complete<extras> | extras | 0.6 | 0.983 | 0.991 | 0.975 | 0.885 | 0.996 | 0.996 | 0.981 |
| leader<stdlib> | stdlib | 0.8 | 0.982 | 0.996 | 0.969 | 0.862 | 0.996 | 0.996 | 0.992 |
| hdbscan<extras> | extras | 0.5 | 0.956 | 0.996 | 0.920 | 0.553 | 0.990 | 0.990 | 0.993 |
| kmeans_reference<extras> | extras | 0.3 | 0.048 | 0.024 | 1.000 | 0.011 | 0.529 | 0.529 | 0.000 |

## Replay (product metrics)

Chronological replay with the trigger rule (3+ times, 2+ sessions, 30 days, 1 per session, 3 per day). `runtime<baseline>` drives the real hook code.

| method | split | suggestions | precision | recall | median occurrences before first | false / 100 turns | duplicates |
|---|---|---|---|---|---|---|---|
| runtime<baseline> | dev | 1 | 1.000 | 0.017 | 3 | 0.000 | 0 |
| runtime<baseline> | test | 0 | – | 0.000 | – | 0.000 | 0 |
| sim:logreg_monotone+leader<stdlib> | dev | 64 | 0.969 | 0.950 | 3.000 | 0.052 | 5 |
| sim:logreg_monotone+leader<stdlib> | test | 41 | 1.000 | 0.974 | 3 | 0.000 | 4 |
| sim:logreg+leader<stdlib> | dev | 66 | 0.955 | 0.950 | 3 | 0.078 | 6 |
| sim:logreg+leader<stdlib> | test | 43 | 0.977 | 0.974 | 3.000 | 0.038 | 5 |
| sim:gbt+leader<extras> | dev | 61 | 0.984 | 1.000 | 3.000 | 0.026 | 0 |
| sim:gbt+leader<extras> | test | 38 | 0.947 | 0.895 | 3.000 | 0.077 | 2 |
| batch:gbt+leader+hdbscan<extras> | dev | 177 | 0.983 | 1.000 | 7.000 | 0.078 | 114 |
| batch:gbt+leader+hdbscan<extras> | test | 108 | 0.972 | 0.947 | 7 | 0.115 | 69 |
| batch:gbt+leader+agglomerative_average<extras> | dev | 166 | 0.982 | 1.000 | 7 | 0.078 | 103 |
| batch:gbt+leader+agglomerative_average<extras> | test | 94 | 0.957 | 0.947 | 7.000 | 0.153 | 54 |
| sim:logreg_monotone+leader<extras> | dev | 69 | 0.927 | 0.983 | 3.000 | 0.130 | 5 |
| sim:logreg_monotone+leader<extras> | test | 42 | 1.000 | 0.974 | 3.000 | 0.000 | 5 |

## Lookup

Can the matcher find an earlier turn of the same task? Recall@10 on test, latency with the index padded to 100k vectors (bge-small embeddings for vector methods).

| method | recall@10 | p50 ms | p95 ms |
|---|---|---|---|
| brute_force | 0.851 | 8.351 | 8.550 |
| inverted_index | 0.644 | 0.010 | 0.022 |
| minhash_lsh | 0.434 | 0.018 | 0.027 |
| hnswlib | 0.851 | 0.310 | 0.408 |
| faiss_hnsw | 0.848 | 0.056 | 0.107 |
| sqlite_vec | – | this Python's sqlite3 can't load extensions (python.org macOS builds); not measured | |

## Scale (runtime)

10,000 turns / 103,601 actions / 9,162 patterns in one database (74.2 MB, built in 1792.4 s). Stop hook with that database: p50 289.3 ms, p95 750.1 ms. Measured at a 1-minute load average of 260; under the same load the Stop hook with an empty database took 173.0 ms (p50), so most of this is machine load, not database size.

## Naming

Judge scores (1-5, blind, Claude Sonnet) over 38 test families: runtime heuristic 2.66 (0.368 rated 4+), Claude reference 4.84. Exact match 0.158. Local LLM: not evaluated (no Ollama/llama.cpp; disk nearly full). Claude refines the name when drafting, so the heuristic only needs to be a sensible default.

## Ablation: what each change did (real-hook replay)

| matcher | dev P | dev R | test P | test R | test false / 100 turns |
|---|---|---|---|---|---|
| rule, M1 baseline (before ADR 0006) | 0.651 | 0.883 | 0.671 | 0.868 | 1.07 |
| + meaningful-only actions, text gate, no double suggestions | 1.000 | 0.017 | – | 0.000 | 0.000 |
| + swept rule `{"action_weighting": "none", "action_strong": 0.55, "action_weak": 0.4, "text_gate": 0.08}` | 0.906 | 0.967 | 0.899 | 0.947 | 0.268 |
| **chosen: logreg fusion + leader (runtime)** | 0.978 | 0.967 | 1.000 | 0.974 | 0.000 |

M4 check, the shipped runtime vs the lab's simulation of the same method (tolerance 0.05): dev difference {'precision': 0.0092, 'recall': 0.0167}, test difference {'precision': 0.0, 'recall': 0.0}.

## Multi-turn workflow mining (M5)

15 planted workflows (2-4 steps, 3-6 sessions each, noise turns between steps) among 181 sessions. Found = reported as a frequent sequence (support >= 3).

| method | found | recall | false workflows | reported | seconds |
|---|---|---|---|---|---|
| ngram_contiguous | 7/15 | 0.467 | 0 | 24 | 0.001 |
| ngram_gap1 (runtime) | 15/15 | 1.000 | 0 | 47 | 0.003 |
| prefixspan | 15/15 | 1.000 | 2 | 60 | 0.004 |
| spade | 15/15 | 1.000 | 2 | 60 | 0.013 |

## Chosen: stdlib (online tier)

```json
{
  "fusion": "logreg_monotone",
  "text": "bm25",
  "actions": "hier_jaccard_noidf[hand]",
  "clusterer": "leader",
  "theta": 0.7,
  "logreg": {
    "features": [
      "text",
      "action",
      "seq",
      "files",
      "action_x_text",
      "few_actions"
    ],
    "mean": [
      0.09461264788063502,
      0.21449655092938802,
      0.2892970533023837,
      0.09345437717770055,
      0.03979813914172222,
      0.657469512195122
    ],
    "scale": [
      0.13992638659192944,
      0.30703726352414284,
      0.3678686558641414,
      0.2819684119361196,
      0.09223838376463267,
      0.4745559542120504
    ],
    "coef": [
      0.16993304409502483,
      1.4688296733773736,
      1.1826898638705396,
      0.0,
      0.0,
      -1.994342896752602
    ],
    "intercept": -3.9522341071319076
  },
  "track": "stdlib",
  "method_version": "stdlib-2026-10-19",
  "evidence": {
    "precision": 1.0,
    "recall": 0.9737,
    "median_occurrences_before_first": 3,
    "false_per_100_turns": 0.0,
    "duplicate_suggestions": 4
  },
  "selected_from_run": "2026-10-19T13:07:29",
  "real_holdout": "pending: run bench.label export/pairs/label/eval (SPEC 11.5)"
}
```

## Chosen: with extras (background tier)

```json
{
  "fusion": "logreg_monotone",
  "text": "jina_small",
  "actions": "hier_jaccard_noidf[hand]",
  "clusterer": "leader",
  "theta": 0.7,
  "logreg": {
    "features": [
      "text",
      "action",
      "seq",
      "files",
      "action_x_text",
      "few_actions"
    ],
    "mean": [
      0.750003926260624,
      0.21449655092938802,
      0.2892970533023837,
      0.09345437717770055,
      0.17014858809154007,
      0.657469512195122
    ],
    "scale": [
      0.057317773542056395,
      0.30703726352414284,
      0.3678686558641414,
      0.2819684119361196,
      0.2481916713409849,
      0.4745559542120504
    ],
    "coef": [
      0.3589506290455501,
      0.9383795595221465,
      0.9888898847480261,
      0.0,
      0.6917166881107906,
      -1.9717347414957642
    ],
    "intercept": -3.981001828032598
  },
  "track": "extras",
  "method_version": "extras-2026-10-19",
  "evidence": {
    "precision": 1.0,
    "recall": 0.9737,
    "median_occurrences_before_first": 3.0,
    "false_per_100_turns": 0.0,
    "duplicate_suggestions": 5
  },
  "selected_from_run": "2026-10-19T13:07:29",
  "real_holdout": "pending: run bench.label export/pairs/label/eval (SPEC 11.5)"
}
```
