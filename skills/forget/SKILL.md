---
description: Delete everything skill-spotter has stored (recorded turns, patterns, settings).
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter *)
---

The user wants to delete all skill-spotter data in `${CLAUDE_PLUGIN_DATA}`. This can't be undone.

1. Ask the user to confirm (yes / no). Don't run anything before they answer.
2. Only if they confirm, run:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" forget --yes`
3. Report the command's output in one sentence.
