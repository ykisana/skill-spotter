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


GENERIC_NOUNS = frozenset(
    """commit commits result results change changes code file files repo repository branch
    thing things stuff tag tags latest last previous current new week today yesterday time
    times way bit project""".split()
)


def _edited_stems(tokens: Mapping[str, float]) -> List[str]:
    stems = []
    for token, weight in sorted(tokens.items(), key=lambda x: -x[1]):
        if token.startswith("edit:") and weight >= 0.5:
            stem = os.path.splitext(os.path.basename(token[5:]))[0].lower()
            stems.extend(re.split(r"[^a-z0-9]+", stem))
    return [s for s in stems if s]


def from_words(
    words: Mapping[str, float],
    order_hint: Sequence[str] = (),
    *,
    first_words: Mapping[str, float] = None,
    tokens: Mapping[str, float] = None,
) -> Optional[str]:
    """verb + object (+ qualifier).

    - object: a consistent prompt word that names the file the task edits, else the most
      consistent non-generic word;
    - verb: the prompts' consistent first word if it's a verb, else "update" when the task
      edits that file;
    - qualifier: the word just before the object in the latest prompt, if consistent
      (e.g. "weekly changelog").
    """
    strong = {w: f for w, f in words.items() if f >= 0.5 and w not in _FILLER}
    if not strong:
        return None
    edited = _edited_stems(tokens or {})
    objects = [w for w in edited if w in strong and w not in _VERB_SET]
    from_file = bool(objects)
    if not objects:
        objects = sorted(
            (w for w in strong if w not in _VERB_SET and w not in GENERIC_NOUNS),
            key=lambda w: (-strong[w], order_hint.index(w) if w in order_hint else 999, w),
        )
    if not objects:
        return None
    obj = objects[0]
    verb = None
    for word, frac in sorted((first_words or {}).items(), key=lambda x: -x[1]):
        if frac >= 0.5 and word in _VERB_SET:
            verb = word
            break
    if verb is None and from_file:
        verb = "update"
    qualifier = None
    if obj in order_hint:
        i = order_hint.index(obj)
        before = order_hint[i - 1] if i > 0 else None
        if before and strong.get(before, 0) >= 0.8 and before not in _VERB_SET | GENERIC_NOUNS:
            qualifier = before
    picked = [w for w in (verb, qualifier, obj) if w]
    return _kebab(picked) or None


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
        from_words(
            representative.get("words", {}),
            order_hint,
            first_words=representative.get("first", {}),
            tokens=representative.get("tokens", {}),
        )
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
