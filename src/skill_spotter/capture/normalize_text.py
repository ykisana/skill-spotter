"""Normalize prompt text so rephrasings of one task look alike (SPEC section 5.3).

Pipeline: lowercase → placeholders for values → developer synonyms → tokens →
stop-words out → light stemming. ``ngrams`` turns the result into 1–2-grams.
"""

from __future__ import annotations

import re
from typing import List, Set

_PLACEHOLDERS = [
    ("<url>", re.compile(r"\b(?:https?|ftp|ssh|git)://\S+|\bwww\.\S+")),
    ("<str>", re.compile(r"\"[^\"\n]{1,200}\"|'[^'\n]{3,200}'|`[^`\n]{1,200}`")),
    (
        "<date>",
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}(?::\d{2})?z?)?\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
        ),
    ),
    (
        "<path>",
        re.compile(
            r"(?:~|\.{1,2})?/[\w.\-/]+|\b[\w\-]+(?:/[\w.\-]+)+|\b[\w\-]+\.(?:py|js|ts|tsx|jsx|md|json|ya?ml|toml|go|rs|rb|java|kt|swift|sh|sql|txt|csv|html|css|lock)\b"
        ),
    ),
    ("<ref>", re.compile(r"(?:\B#\d+\b|\b[a-z]{2,10}-\d+\b|\bv?\d+\.\d+(?:\.\d+)*(?:-[\w.]+)?\b)")),
    ("<hash>", re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")),
    ("<num>", re.compile(r"\b\d+(?:\.\d+)?\b")),
]

# Multi-word phrases first, then single words. Values are canonical tokens.
_PHRASES = [
    ("release notes", "changelog"),
    ("change log", "changelog"),
    ("pull requests", "pr"),
    ("pull request", "pr"),
    ("merge requests", "pr"),
    ("merge request", "pr"),
    ("unit tests", "test"),
    ("test suite", "test"),
    ("type check", "typecheck"),
    ("type-check", "typecheck"),
    ("roll back", "rollback"),
    ("clean up", "cleanup"),
    ("set up", "setup"),
]
_WORDS = {
    "prs": "pr",
    "mrs": "pr",
    "mr": "pr",
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "db": "database",
    "repo": "repository",
    "repos": "repository",
    "docs": "documentation",
    "doc": "documentation",
    "deps": "dependency",
    "dependencies": "dependency",
    "bump": "upgrade",
    "upgrade": "upgrade",
    "env": "environment",
    "envs": "environment",
    "prod": "production",
    "stg": "staging",
    "msg": "message",
    "config": "configuration",
    "cfg": "configuration",
    "ci": "ci",
    "fix": "fix",
    "bugfix": "fix",
    "summarise": "summarize",
    "summary": "summarize",
    "summarize": "summarize",
}

STOP_WORDS = frozenset(
    """a an the and or but if then else of to in on at by for with from into onto
    about over under up down out off is are was were be been being am do does did done
    doing have has had having i me my we our us you your it its this that these those
    there here what which who whom whose when where why how can could would should will
    shall may might must please pls just also too very really so some any all each every
    more most other such only own same than now get got let lets let's make sure ok okay
    hey hi thanks thank need want like go going again new one two via per as not no
    yes run claude say hello thx""".split()
)

_TOKEN = re.compile(r"<[a-z]+>|[a-z][a-z0-9_]*")


def _stem(word: str) -> str:
    if word.startswith("<") or len(word) <= 3:
        return word
    for suffix, replacement, min_len in (
        ("ies", "y", 5),
        ("sses", "ss", 5),
        ("ing", "", 6),
        ("ed", "", 5),
        ("es", "", 5),
        ("s", "", 4),
    ):
        if word.endswith(suffix) and len(word) >= min_len:
            if suffix == "s" and word.endswith(("ss", "us", "is")):
                continue
            if suffix == "es" and not word.endswith(("ches", "shes", "xes", "zes", "sses")):
                continue
            stem = word[: len(word) - len(suffix)] + replacement
            # "running" -> "runn" -> "run"
            if (
                suffix in ("ing", "ed")
                and len(stem) > 3
                and stem[-1] == stem[-2]
                and stem[-1] not in "lsz"
            ):
                stem = stem[:-1]
            return stem
    return word


def normalize(text: str) -> List[str]:
    """Normalized tokens for ``text``, in order."""
    text = text.lower()
    for placeholder, pattern in _PLACEHOLDERS:
        text = pattern.sub(f" {placeholder} ", text)
    for phrase, canonical in _PHRASES:
        text = text.replace(phrase, canonical)
    tokens = []
    for raw in _TOKEN.findall(text):
        word = _WORDS.get(raw, raw)
        if word in STOP_WORDS:
            continue
        stemmed = _stem(word)
        stemmed = _WORDS.get(stemmed, stemmed)
        if stemmed not in STOP_WORDS:  # "running" -> "run", which is a stop-word
            tokens.append(stemmed)
    return tokens


def content_words(text: str) -> List[str]:
    """Lowercase non-stop-words without stemming or placeholders, for naming skills."""
    words = []
    lowered = text.lower()
    for _placeholder, pattern in _PLACEHOLDERS:
        lowered = pattern.sub(" ", lowered)
    for raw in re.findall(r"[a-z][a-z\-]*[a-z]", lowered):
        if raw not in STOP_WORDS and len(raw) > 2:
            words.append(raw)
    return words


def ngrams(tokens: List[str]) -> Set[str]:
    """Word 1-grams and 2-grams."""
    grams = set(tokens)
    grams.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return grams


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
