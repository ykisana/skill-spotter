---
description: Show skill-spotter's detected patterns, pending suggestions and the skills you created from them.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter *)
---

!`${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" status`

Show the skill-spotter status output above to the user as-is, in a code block. Don't add commentary or run other commands.
