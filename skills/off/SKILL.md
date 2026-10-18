---
description: Pause skill-spotter suggestions. Recording continues so patterns aren't lost; use /skill-spotter:forget to delete data.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter *)
---

!`${CLAUDE_PLUGIN_ROOT}/bin/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" off`

Tell the user the line above in one sentence. Don't run other commands.
