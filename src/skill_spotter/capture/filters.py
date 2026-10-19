"""Which prompts are worth recording (SPEC section 9.1)."""

from __future__ import annotations

import re
from typing import Iterable, Optional

MIN_WORDS = 4

_PASTED_BLOCK = re.compile(
    r"^<pasted_content id=\"([^\"]*)\">\n.*?^</pasted_content id=\"\1\">\n?", re.S | re.M
)
# Messages Claude Code itself injects as a "prompt": background task reports,
# cross-session messages, scheduled-task wrappers. They start with a tag line.
_AUTOMATIC_PREFIX = re.compile(r"^\s*<([a-z][a-z0-9_\-]*)(\s[^>]*)?>", re.I)


def strip_pasted(prompt: str) -> str:
    """Remove pasted blocks: they're data the user brought along, not the task itself."""
    return _PASTED_BLOCK.sub(" ", prompt).strip()


def looks_automatic(prompt: str, scheduled_prompts: Iterable[str] = ()) -> bool:
    """True for turns Claude Code started on its own rather than the user typing them."""
    if _AUTOMATIC_PREFIX.match(prompt):
        return True
    text = prompt.strip()
    for scheduled in scheduled_prompts:
        scheduled = scheduled.strip()
        if not scheduled:
            continue
        # Stop input caps cron prompts at 1000 chars with a "… [+N chars]" marker.
        head = scheduled.split("… [+")[0].strip()
        if text == scheduled or (head and text.startswith(head)):
            return True
    return False


def skip_reason(
    prompt: Optional[str],
    *,
    previous_prompt: Optional[str] = None,
    seconds_since_previous: Optional[float] = None,
    scheduled_prompts: Iterable[str] = (),
) -> Optional[str]:
    """Why a prompt shouldn't be recorded, or None to record it."""
    if not isinstance(prompt, str):
        return "no prompt"
    if looks_automatic(prompt, scheduled_prompts):
        return "automatic"
    text = strip_pasted(prompt)
    if text.startswith("/"):
        return "slash command"
    if len(text.split()) < MIN_WORDS:
        return "too short"
    if (
        previous_prompt is not None
        and seconds_since_previous is not None
        and seconds_since_previous <= 600
        and text == strip_pasted(previous_prompt)
    ):
        return "repeat"  # e.g. a /loop re-submitting the same prompt
    return None
