---
description: Install skill-spotter's optional background dependencies (numpy, scikit-learn, fastembed; about 400 MB) for better batch clustering.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter *)
---

This downloads about 400 MB from PyPI, plus an embedding model from Hugging Face, into `${CLAUDE_PLUGIN_DATA}/extras`. It is the only network access skill-spotter makes, and only the background job uses these packages; hooks never import them.

1. Ask the user to confirm (yes / no). Don't run anything before they answer.
2. Only if they confirm, run:
   `${CLAUDE_PLUGIN_ROOT}/scripts/skill-spotter --data-dir "${CLAUDE_PLUGIN_DATA}" extras --yes`
3. Report the result in one sentence. To undo later: `skill-spotter extras --remove`.
