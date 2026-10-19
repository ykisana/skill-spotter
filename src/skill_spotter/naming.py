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
    "rotate provision scaffold analyze report notify post send open close label skip squash "
    "dump tail debug profile onboard resolve shard reset revert restore promote cut regenerate "
    "rerun retry upload download install remove delete rename split scale patch benchmark "
    "measure monitor investigate reproduce document translate validate verify compare diff "
    "cherry-pick backport snapshot rollout"
).split()
# Inflected or noun forms that point at a verb ("rolled back", "deployment").
VERB_FORMS = {
    "deploying": "deploy",
    "deployed": "deploy",
    "deployment": "deploy",
    "deploys": "deploy",
    "rolling": "rollback",
    "revert": "revert",
    "rerunning": "rerun",
    "bumping": "bump",
    "updating": "update",
    "updated": "update",
    "generating": "generate",
    "regenerating": "regenerate",
    "release": "release",
    "releasing": "release",
    "migrating": "migrate",
    "migration": "migrate",
    "squashing": "squash",
    "tailing": "tail",
    "debugging": "debug",
    "profiling": "profile",
    "resolving": "resolve",
    "reviewing": "review",
    "syncing": "sync",
    "fixing": "fix",
    "summary": "summarize",
    "summarizing": "summarize",
    "cleaning": "clean",
    "testing": "test",
}
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
    thing things stuff latest last previous current new week today yesterday time
    times way bit project""".split()
)


def _edited_stems(tokens: Mapping[str, float]) -> List[str]:
    stems = []
    for token, weight in sorted(tokens.items(), key=lambda x: -x[1]):
        if token.startswith("edit:") and weight >= 0.5:
            stem = os.path.splitext(os.path.basename(token[5:]))[0].lower()
            stems.extend(re.split(r"[^a-z0-9]+", stem))
    return [s for s in stems if s]


def _action_words(tokens: Mapping[str, float]):
    """(command names, other words) from the task's strongest Bash/MCP tokens."""
    commands, words = set(), []
    for token, weight in sorted(tokens.items(), key=lambda x: -x[1]):
        if weight < 0.5:
            continue
        kind, _, body = token.partition(":")
        if kind == "bash":
            parts = [w for w in body.split() if not w.startswith("-")]
            if parts:
                commands.add(parts[0])
                words.extend(w.lower() for w in parts[1:] if w.isalpha())
        elif kind == "mcp":
            words.extend(re.split(r"[^a-z]+", body.split(":")[-1].split("(")[0].lower()))
    return commands, [w for w in dict.fromkeys(words) if w]


def _verb(word: str) -> Optional[str]:
    word = VERB_FORMS.get(word, word)
    return word if word in _VERB_SET else None


def from_words(
    words: Mapping[str, float],
    order_hint: Sequence[str] = (),
    *,
    first_words: Mapping[str, float] = None,
    tokens: Mapping[str, float] = None,
) -> Optional[str]:
    """verb + (qualifier) + object, tuned against a blind Claude judge (bench.naming).

    - verb: the verb most prompts start with (at least 30% of them); else "update" when the
      object is the edited file; else a verb among the commands' subcommands;
    - object: the edited file's name if the prompts mention it, else a word the prompts
      share with the commands, else the most consistent non-generic word;
    - qualifier: one more consistent word (>= 60%), ordered as in the latest prompt.
    """
    tokens = tokens or {}
    medium = {w: f for w, f in words.items() if f >= 0.25 and w not in _FILLER}
    strong = {w: f for w, f in medium.items() if f >= 0.4}
    commands, action_words = _action_words(tokens)
    position = {w: i for i, w in reversed(list(enumerate(order_hint)))}

    # A verb counts only where prompts start with it (imperative phrasing): "deploy api ...".
    # Verbs elsewhere are often nouns in context ("since the last tag").
    verb, verb_word = None, None
    candidates = [(f, w) for w, f in (first_words or {}).items() if f >= 0.3 and _verb(w)]
    if candidates:
        _, verb_word = max(candidates)
        verb = _verb(verb_word)
    command_verb = next(((v, w) for w in action_words for v in [_verb(w)] if v), (None, None))

    edited = _edited_stems(tokens)

    def usable(w):
        return w not in GENERIC_NOUNS and w != verb_word and _verb(w) != verb and w not in commands

    objects = [w for w in edited if w in strong and usable(w)]
    if not objects:
        objects = [w for w in action_words if w in strong and usable(w)]
    if not objects:
        objects = sorted(
            (w for w in strong if usable(w) and not _verb(w)),
            key=lambda w: (-strong[w], position.get(w, 99), w),
        )
    if not objects:
        return None
    obj = objects[0]
    if verb is None:
        if obj in edited:
            verb = "update"
        elif command_verb[0] and command_verb[1] != obj:
            verb = command_verb[0]

    qualifier = None
    rest = sorted(
        (w for w in strong if w != obj and usable(w) and not _verb(w) and strong[w] >= 0.6),
        key=lambda w: (-strong[w], position.get(w, 99)),
    )
    if rest:
        qualifier = rest[0]
    parts = [qualifier, obj] if qualifier else [obj]
    parts.sort(key=lambda w: position.get(w, 99))
    picked = ([verb] if verb else []) + parts
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
