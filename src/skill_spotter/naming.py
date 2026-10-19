"""Suggest a skill name for a pattern (SPEC section 9.4).

Kebab-case, at most 3 words: a verb plus the most consistent object words from the
pattern's prompts, else words from its most distinctive action. Claude refines the name
when drafting; this only needs to be a sensible default that doesn't collide.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Mapping, Optional, Sequence, Set

VERBS = (
    "write update create generate deploy release publish ship run fix add bump upgrade review "
    "summarize sync build test check clean cleanup migrate rollback restart backup refresh "
    "triage draft prepare rebase merge tag archive export import seed lint format audit "
    "rotate provision scaffold analyze report notify post send open close label"
).split()
_VERB_SET = set(VERBS)

# Names Claude Code already uses for built-in commands.
BUILTIN_COMMANDS = frozenset(
    """add-dir agents bashes bug clear compact config context cost doctor exit export help
    hooks ide init install-github-app login logout mcp memory model output-style permissions
    plugin pr-comments release-notes resume review rewind security-review status statusline
    terminal-setup todos upgrade usage vim loop goal schedule fast effort theme feedback
    reload-skills skills plan tasks agents remote-control artifacts""".split()
)

_FILLER = {"thing", "stuff", "something", "code", "file", "files", "please", "quick"}


def _kebab(words: Iterable[str]) -> str:
    cleaned = [re.sub(r"[^a-z0-9]+", "-", w.lower()).strip("-") for w in words]
    name = "-".join(w for w in cleaned if w)
    return re.sub(r"-{2,}", "-", name)[:40].strip("-")


def from_words(words: Mapping[str, float], order_hint: Sequence[str] = ()) -> Optional[str]:
    """Verb + up to two object words that appear in most of the pattern's prompts,
    ordered as they appear in ``order_hint`` (usually the latest prompt)."""
    ranked = sorted(
        ((w, f) for w, f in words.items() if w not in _FILLER and f >= 0.5),
        key=lambda x: (-x[1], x[0]),
    )
    verbs = [w for w, _ in ranked if w in _VERB_SET]
    nouns = [w for w, _ in ranked if w not in _VERB_SET]
    if not nouns:
        return None
    picked = nouns[:2]
    position = {w: i for i, w in reversed(list(enumerate(order_hint)))}
    picked.sort(key=lambda w: position.get(w, len(position)))
    if verbs:
        picked.insert(0, verbs[0])
    return _kebab(picked[:3]) or None


def from_tokens(tokens: Mapping[str, float]) -> Optional[str]:
    """Fallback: words from the strongest non-generic action token."""
    best = sorted(
        ((t, w) for t, w in tokens.items() if not t.startswith(("seq:", "read:", "editdir:"))),
        key=lambda x: (-x[1], len(x[0])),
    )
    for token, _weight in best:
        kind, _, body = token.partition(":")
        if kind == "bash":
            words = [w for w in body.split() if not w.startswith("-")]
        elif kind == "mcp":
            words = body.split(":")[-1].split("(")[0].replace("_", " ").split()
        elif kind == "edit":
            stem = os.path.splitext(os.path.basename(body))[0]
            words = ["update", stem]
        else:
            words = re.split(r"[^a-zA-Z0-9]+", body)
        name = _kebab(words[:3])
        if name:
            return name
    return None


def existing_skill_names(project_root: Optional[str]) -> Set[str]:
    names: Set[str] = set()
    dirs = [os.path.expanduser("~/.claude/skills")]
    if project_root:
        dirs.append(os.path.join(project_root, ".claude", "skills"))
    for base in dirs:
        try:
            names.update(e for e in os.listdir(base) if os.path.isdir(os.path.join(base, e)))
        except OSError:
            continue
    return names


def suggest_name(
    representative: Mapping,
    project_root: Optional[str],
    taken: Iterable[str] = (),
    order_hint: Sequence[str] = (),
) -> str:
    base = (
        from_words(representative.get("words", {}), order_hint)
        or from_tokens(representative.get("tokens", {}))
        or "repeated-task"
    )
    unavailable = BUILTIN_COMMANDS | existing_skill_names(project_root) | set(taken)
    name, n = base, 2
    while name in unavailable:
        name = f"{base}-{n}"
        n += 1
    return name


def skill_dirs(project_root: Optional[str]) -> List[str]:
    dirs = []
    if project_root:
        dirs.append(os.path.join(project_root, ".claude", "skills"))
    dirs.append(os.path.expanduser("~/.claude/skills"))
    return dirs
