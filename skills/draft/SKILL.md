---
description: Save a repeated task that skill-spotter found as a reusable /skill. Usage: /skill-spotter:draft <pattern-id> [manual|auto]
argument-hint: <pattern-id> [manual|auto]
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter *)
---

Turn skill-spotter pattern `$0` into a skill the user can run with `/name`.

1. Get the pattern:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" show $0 --json`
   It lists the redacted prompts the user typed, the steps Claude took each time (`common_steps`, in order), the values that changed between runs (`varying_values`), danger flags, a suggested name and the path to write (`skill_path`). If the command fails, show its error and stop.

2. Work out the task:
   - **Fixed steps:** what happens every time (use `common_steps`; ignore exploration and failed actions).
   - **Varying parts:** what changes between runs (`varying_values`, plus differences between the prompts, such as a date range, PR number or environment). These become arguments.

3. Decide who can start the skill. If `$1` is `manual` or `auto`, use that. Otherwise ask the user exactly one question: "Should Claude be able to use this skill on its own, or only when you type /<name>?" The default is only when typed.
   If `danger` is true, the skill is always typed-only, whatever the answer.

4. Write `skill_path` with the Write tool (it creates the folders; no mkdir needed). Use the suggested name unless a clearly better short kebab-case name (max 3 words) fits; if you change it, change the folder name to match. The file contains:
   - frontmatter:
     - `description`: one line saying what it does. If model-invocable, write it for triggering: key use case first, natural phrases the user would type.
     - `disable-model-invocation: true` unless the user chose auto (and never when `danger` is true).
     - `argument-hint` and `arguments` (named) for the varying parts, if any.
   - a body of concise numbered steps that match the observed steps, using `$ARGUMENTS` or the named `$arg` placeholders where values vary;
   - if `danger` is true, an explicit step before each step in `dangerous_steps`: "Show the user what will happen and ask for confirmation before continuing."
   Keep it short (well under 100 lines). Don't copy redacted values or secrets into it.

5. Record it:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" accept $0 <the path you wrote>`

6. Tell the user: "Saved. Next time: `/<name>`". If `skills_dir_exists` was false before you wrote the file, add: "Run `/reload-skills` once so Claude Code picks it up."
