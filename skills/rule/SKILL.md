---
description: Add a standing instruction skill-spotter found (rN) to CLAUDE.md, so you stop repeating it. Usage: /skill-spotter:rule <rN>
argument-hint: <rN>
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter *)
---

Turn skill-spotter rule `$0` into one standing instruction in a CLAUDE.md file. A rule is something the user keeps adding to different requests ("make sure I'm the only author, no claude"), not a task.

1. Get the rule:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" show $0 --json`
   It lists what the user said each time (`instructions[].said`, with the surrounding prompt in `in_prompt`), how many prompts, sessions and projects, the suggested `scope` and `target_path`, and both `targets`. If the command fails, show its error and stop.

2. Write the instruction: what the user wants every time, as one or two short imperative sentences.
   - Keep only what the `said` lines have in common. Where several add the same detail (for example "keep their existing commits"), include it.
   - Make it general: no PR numbers, URLs, project names or one-off task details.
   - Start with a short topic label when it helps, like `Commits: ...`.

3. Ask the user exactly one question, showing the instruction you wrote: should it go in their personal file (`targets.personal`, all projects) or this project's file (`targets.project`, if not null)? Recommend `scope`; default to `target_path`. If they edit the wording in their answer, use theirs.

4. Add it to the chosen file:
   - If the file exists, Read it first. If it already has an instruction about the same thing, update that line instead of adding a second one.
   - Otherwise add it as a `- ` bullet at the end, under a `# Preferences` heading if the file doesn't have a suitable section.
   - If the file doesn't exist, Write it with the heading and the bullet.
   Don't change anything else in the file.

5. Record it:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" accept $0 <the file you changed>`

6. Tell the user: "Added to `<file>`. Claude Code reads it at the start of every session."
