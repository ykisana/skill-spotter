# 0005: Method Lab survey, additions and setup

- Status: accepted
- Date: 2026-10-19
- Milestone: M3

## Survey (SPEC 11.3)

- **Small CPU embedding models (MTEB, October 2026):**
  - MongoDB `mdbr-leaf-mt` (23M) leads MTEB v2 (Eng) among models of 30M parameters or fewer: 63.97, ahead of gte-small 63.22, arctic-embed-s 61.59, e5-small-v2 61.32 and all-MiniLM-L6-v2 59.03.
  - `mdbr-leaf-ir` leads retrieval benchmarks for models of 100M or fewer.
  - Snowflake arctic-embed-xs/s and bge-small-en-v1.5 are the well-tested fallbacks.
  - Model2Vec `potion-base-32M` reaches about 93% of MiniLM's average MTEB score, much faster.
- **Log template mining (Loghub-2.0, ISSTA'24):** Drain still has the best grouping accuracy among classic parsers. The 2025 non-LLM LogLSHD (MinHash LSH grouping plus DTW template extraction) reports about 15% higher accuracy and 73% less time than Drain. LLM parsers (LibreLog, LILAC) are out of scope: they cost tokens or need a local LLM.
- **Clustering short texts and token sets:** HDBSCAN, agglomerative clustering with a distance threshold, and community detection on kNN graphs remain the standard choices. Leiden needs igraph/leidenalg, so its close relative Louvain (in networkx) stands in.

## Added to the registry

| Category | Added | Why |
|---|---|---|
| Text | `leaf_mt` (mdbr-leaf-mt), `arctic_xs`, `arctic_s`, `jina_small`, `nomic_q`, `model2vec_potion32m` | top small models at survey time, all via fastembed/ONNX |
| Templating | `lsh` (LogLSHD-style LSH grouping) | best recent non-LLM parser |
| Actions | `hier_jaccard_noidf` | ablation of the IDF weighting |
| Clustering | `louvain` | in place of Leiden (no igraph) |

## Not evaluated, and why

- **Contrastively fine-tuned embedder** (spec stretch goal): dropped for v1. The dataset is small, and the synthetic phrasing would make fine-tuning overfit to model-written text.
- **Local cross-encoder rerank:** not evaluated; the borderline band is too small to matter on synthetic data (see results).
- **Small local LLM for naming (Ollama/llama.cpp):** neither is installed and the machine has about 15 GB of disk free. Naming is compared against a Claude reference instead.
- **e5-small / gte-small:** not packaged by fastembed 0.9; mdbr-leaf-mt and bge-small cover that tier.

## Setup decisions

- **Environment:** the lab runs in a project-local `.venv` (git-ignored). Exact versions are in `bench/requirements.txt`; the `bench` extra in `pyproject.toml` lists them unpinned. Models and caches go in `bench/.cache/` (git-ignored, about 0.6 GB).
- **Fig specs:** command-name subcommand trees and "option takes an argument" flags were extracted once from `@withfig/autocomplete` 2.692.3 into `bench/methods/fig/specs.json` (88 commands, 0.9 MB) with its MIT license file. Only the benchmark uses them.
- **Generation:**
  - It runs headless: `claude -p --tools "" --no-session-persistence --output-format json`, with Sonnet for families and Haiku for one-offs and the audit.
  - Replies are cached by sha256(model + prompt) in `bench/data/raw/` and committed. They're synthetic with no user data, so the dataset rebuilds without new calls.
  - Broken JSON replies are salvaged item by item and retried up to twice with a changed prompt.
- **Templating evaluated two ways:** grouping accuracy, using each generated call's source step, and the end-to-end pairwise quality of the baseline action similarity built on each templater.
- **Two replay modes:**
  - `runtime` drives the real hook pipeline with a moved clock. This is authoritative for what ships, and what M4's tolerance check uses.
  - `sim` / `batch` evaluate any scorer and clusterer, including background-tier re-clustering every 50 turns.
- **Sequence mining (PrefixSpan, SPADE, n-grams) moves to M5.** It needs multi-turn workflow data, which dataset v1 doesn't have; M5 extends the dataset and evaluates them there.
