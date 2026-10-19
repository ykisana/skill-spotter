---
description: Run skill-spotter's background re-clustering now (merges split patterns, finds ready suggestions).
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter *)
---

!`${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" train`

Tell the user the result above in one or two sentences (projects scanned, patterns merged, patterns ready to suggest). Don't run other commands.
