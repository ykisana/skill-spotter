# 0008: M5–M8 — live-session findings, mod band, packaging

- Status: accepted
- Date: 2026-10-19
- Milestones: M5–M8

## Live checks in real Claude Code sessions (2.1.282, Haiku/Sonnet doing the work)

| Check | Result |
|---|---|
| Same task, 3 wordings, 3 sessions (changelog) | suggested at the 3rd, as specified (M1) |
| `/skill-spotter:draft p1` | wrote a working manual-only skill; `/update-changelog` then did the task |
| Lifecycle | snooze at session end; acceptance via `ConfigChange` (long session) and via scan (short session); `used` counted |
| 3-prompt workflow × 3 sessions, phrased differently each time | one suggestion, but for the one step that matched every time (`/patch-version`) |
| `/skill-spotter:draft w4` (workflow seeded through the hooks) | one `/cut-release` skill with all three steps and a `bump` argument; workflow accepted |
| `skill-spotter verify` on a model-invocable skill | trigger precision 0.57–0.67, recall 1.0, F1 0.73–0.80 over 8 prompts |
| Background job with extras (local venv as `extras/`) | merged a split pattern with jina embeddings; embeddings cached in `vectors` |
| Marketplace install (isolated config dir) | `skill-spotter@skill-spotter` installed and enabled |

What the live runs changed:

1. **Text-only path restored in the fused scorer.** Exploration-only repeats ("list the commits since the last tag", only `git log`) have no meaningful actions, and the learned weights give text little weight. They never matched until the rule's text-only path (fewer than 2 meaningful actions and text Jaccard ≥ 0.6) came back. The lab replay mirrors it, so M4 parity holds.
2. **Workflow naming:** steps are named after their patterns, so the message reads `/gh-pr-list → /write-entry-changelog → /open-pull-version`, not `/p1 → /p2 → /p3`. The draft skill handles `wN`.

## Known limitations (to tune with real labelled data, `bench.label`)

- Paraphrased questions with no meaningful actions don't match (text Jaccard < 0.6).
- A single-edit step phrased very differently can split. In the live workflow run, one of three changelog steps scored about 0.6, under θ = 0.7, because of the "few actions" gate that blocks the `psql` false matches. The background job merges some of these.
- Because of both, multi-prompt workflows phrased differently every time may surface as their most consistent step instead of the whole workflow. The design still yields one suggestion, not one per step.

## M7: mod band

`hooks/register.ts`, declared through `modules` in `hooks/hooks.json`:
- **On session start:** it registers the session (`skill-spotter band register`). `Stop` then queues suggestions for it instead of printing a `systemMessage`.
- **After each turn:** it fetches the queued suggestion (`band pending`) and draws it above the prompt with **[Create /name]**, which fills `/skill-spotter:draft pN`, and **[Not now]**, which snoozes.
- **Validation so far:** `claude plugin validate` (2.1.282) parses the module and lists its hooks and calls, and the Python hand-off has tests.
- **Not yet run live:** mods need Claude Code v2.1.287+, and this machine has 2.1.282. On older versions the module doesn't load, nothing registers, and the `systemMessage` path is unchanged.

## Packaging

- **CLI shim moved to `scripts/`:** claude.ai and Cowork refuse plugins with a top-level `bin/` (ADR 0001).
- **Marketplace:** `.claude-plugin/marketplace.json` lists the plugin from the repo root (`source: "./"`).
- **Install size:** a GitHub install clones committed files only, about 15 MB, mostly lab data. A local-path marketplace copies the whole working folder, including the git-ignored `.venv` and model caches, about 1.3 GB here. Moving the plugin into `plugins/claude-code/` (ADR 0003) would slim the install; it's deferred to the Cursor work.
- **Name check (October 2026):** `skill-spotter` is free on PyPI and npm. GitHub has unrelated "SkillSpotter" projects (a computer-vision paper, a careers app). No Claude plugin or skill of that name was found in skill directories.
