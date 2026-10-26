"""Standing instructions the user repeats across prompts, offered for CLAUDE.md (ADR 0010).

Some requests aren't tasks but rules the user attaches to many different tasks: "make
sure I'm the only author, no claude", "keep it as one commit". The task matcher can't see
them: the actions differ every time and patterns are per project. This module looks at
the prompt text alone:

1. Split the prompt into sentences and keep those that read like an instruction (a cue
   such as "make sure", "never", "don't", "only" or "keep"). Questions are skipped.
2. Reduce each sentence to its key words. A word one typo away from a word seen before is
   read as that word ("athor" -> "author").
3. A pair of key words shared by 3+ such sentences, in 3+ sessions within 30 days, makes
   a rule. Rules are counted across projects: standing preferences follow the user.
4. A rule is suggested unless an instruction file Claude reads in this session (the
   editor adapter lists them) already has both words on one line.
"""

from __future__ import annotations

import itertools
import json
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from . import store
from .capture import normalize_text

WINDOW_DAYS = 30
MIN_COUNT = 3
MIN_SESSIONS = 3
MAX_WORDS = 15
MAX_TEXT = 300
MAX_FILE_BYTES = 256_000
TYPO_MIN_LEN = 5
TYPO_CUTOFF = 0.8
DAY = 86400.0

_CUE = re.compile(
    r"\b(?:make sure|ensure|always|never|don[’']?t|do not|no|not|only|keep|without|avoid|"
    r"must|should)\b",
    re.I,
)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|;\s*")
# Rules about the assistant itself are common ("no claude"), so "claude" stays a word here.
_KEEP: FrozenSet[str] = frozenset({"claude"})
# Filler that rides along in instructions without saying what the rule is about.
_FILLER = frozenset(
    """still thing anyth everyth someth noth don tho though way time lot bit know think
    well sure dont doesnt didnt isnt arent wasnt werent wont cant couldnt shouldnt wouldnt
    ive youre theyre thats whats never always keep avoid ensure must without""".split()
)
# "I'm", "don't", "else's": joined into one word first, or the normalizer reads the text
# between two apostrophes as a 'quoted string' and drops it.
_CONTRACTION = re.compile(r"(?<=\w)['’](?=\w)")


def key_words(text: str) -> List[str]:
    """The words that say what an instruction is about, normalized, in order."""
    words: List[str] = []
    for w in normalize_text.normalize(_CONTRACTION.sub("", text), _KEEP):
        if w.startswith("<") or len(w) < 3 or w in _FILLER or w in words:
            continue
        words.append(w)
    return words


def directives(prompt: Optional[str]) -> List[Tuple[str, List[str]]]:
    """Sentences of ``prompt`` that read like a standing instruction, with their key words."""
    from .capture import filters

    found = []
    for sentence in _SPLIT.split(filters.strip_pasted(prompt or "")):
        sentence = " ".join(sentence.split())
        if not sentence or sentence.endswith("?") or not _CUE.search(sentence):
            continue
        words = key_words(sentence)
        if len(words) >= 2:
            found.append((sentence[:MAX_TEXT], words[:MAX_WORDS]))
    return found


def _recent(conn: sqlite3.Connection, until: float) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT id, session_id, project_key, ts, words_json, rule_id FROM directives "
        "WHERE ts >= ? AND ts <= ?",
        (until - WINDOW_DAYS * DAY, until),
    ).fetchall()


def _fix_typos(words: List[str], vocab: Counter) -> List[str]:
    import difflib

    known = list(vocab)
    fixed: List[str] = []
    for w in words:
        if known and w not in vocab and len(w) >= TYPO_MIN_LEN:
            match = difflib.get_close_matches(w, known, 1, TYPO_CUTOFF)
            if match:
                w = match[0]
        if w not in fixed:
            fixed.append(w)
    return fixed


def record_turn(conn: sqlite3.Connection, prompt_id: str) -> List[int]:
    """Store the instructions in a recorded turn's prompt and group them into rules."""
    row = conn.execute(
        "SELECT session_id, project_key, ts_start, prompt_redacted FROM turns WHERE prompt_id = ?",
        (prompt_id,),
    ).fetchone()
    if row is None or not row["prompt_redacted"]:
        return []
    return _record(
        conn,
        prompt_id,
        row["session_id"],
        row["project_key"],
        row["ts_start"],
        row["prompt_redacted"],
    )


def _record(
    conn: sqlite3.Connection,
    prompt_id: str,
    session_id: str,
    project_key: str,
    ts: float,
    prompt: str,
) -> List[int]:
    found = directives(prompt)
    if not found:
        return []
    vocab = Counter(w for r in _recent(conn, ts) for w in json.loads(r["words_json"]))
    added = []
    for text, words in found:
        words = _fix_typos(words, vocab)
        cur = conn.execute(
            "INSERT OR IGNORE INTO directives(prompt_id, session_id, project_key, ts, text, "
            "words_json) VALUES(?, ?, ?, ?, ?, ?)",
            (prompt_id, session_id, project_key, ts, text, json.dumps(words)),
        )
        if cur.rowcount:
            added.append(cur.lastrowid)
            vocab.update(words)
    for directive_id in added:
        _group(conn, directive_id)
    return added


def _group(conn: sqlite3.Connection, directive_id: int) -> Optional[int]:
    """Attach a directive to the rule it belongs to, creating the rule once it repeats."""
    d = conn.execute("SELECT * FROM directives WHERE id = ?", (directive_id,)).fetchone()
    words = set(json.loads(d["words_json"]))
    for rule in conn.execute("SELECT id, key FROM rules").fetchall():
        if set(rule["key"].split()) <= words:
            _attach(conn, rule["id"], [directive_id], d["ts"])
            return rule["id"]
    support: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)
    for r in _recent(conn, d["ts"]):
        shared = words & set(json.loads(r["words_json"]))
        for pair in itertools.combinations(sorted(shared), 2):
            support[pair].append(r)
    best = None
    for pair, rows in support.items():
        sessions = len({r["session_id"] for r in rows})
        if len(rows) < MIN_COUNT or sessions < MIN_SESSIONS:
            continue
        if best is None or (sessions, len(rows)) > best[0]:
            best = ((sessions, len(rows)), pair, rows)
    if best is None:
        return None
    _, pair, rows = best
    # Most of these already belong to a rule found through another pair: same rule.
    owners = Counter(r["rule_id"] for r in rows if r["rule_id"] is not None)
    target = None
    if owners:
        rule_id, n = owners.most_common(1)[0]
        if n * 2 >= len(rows):
            target = rule_id
    if target is None:
        key = " ".join(pair)
        conn.execute(
            "INSERT OR IGNORE INTO rules(key, first_seen, last_seen) VALUES(?, ?, ?)",
            (key, min(r["ts"] for r in rows), d["ts"]),
        )
        target = conn.execute("SELECT id FROM rules WHERE key = ?", (key,)).fetchone()[0]
    _attach(conn, target, [r["id"] for r in rows], d["ts"])
    return target


def _attach(conn: sqlite3.Connection, rule_id: int, ids: List[int], ts: float) -> None:
    marks = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE directives SET rule_id = ? WHERE rule_id IS NULL AND id IN ({marks})",
        [rule_id, *ids],
    )
    conn.execute("UPDATE rules SET last_seen = MAX(last_seen, ?) WHERE id = ?", (ts, rule_id))


def rule_stats(conn: sqlite3.Connection, rule_id: int, now: float) -> Dict:
    """Prompts, sessions and projects behind a rule in the last 30 days."""
    rows = conn.execute(
        "SELECT prompt_id, session_id, project_key, text FROM directives "
        "WHERE rule_id = ? AND ts >= ? ORDER BY ts DESC",
        (rule_id, now - WINDOW_DAYS * DAY),
    ).fetchall()
    projects: List[str] = []
    for r in rows:
        if r["project_key"] not in projects:
            projects.append(r["project_key"])
    return {
        "count": len({r["prompt_id"] for r in rows}),
        "sessions": len({r["session_id"] for r in rows}),
        "projects": projects,
        # The shortest instruction usually states the rule with the least task around it.
        "example": min((r["text"] for r in rows), key=len) if rows else None,
    }


def _instruction_lines(files: Iterable[str]) -> List[Set[str]]:
    lines: List[Set[str]] = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(MAX_FILE_BYTES)
        except OSError:
            continue
        for line in text.splitlines():
            words = set(key_words(line))
            if len(words) >= 2:
                lines.append(words)
    return lines


def is_covered(key: str, instruction_files: Iterable[str]) -> bool:
    """True if one line of the instruction files already has every word of the rule."""
    words = set(key.split())
    return any(words <= line for line in _instruction_lines(instruction_files))


def message(rule_id: int, count: int, sessions: int, projects: int, example: Optional[str]) -> str:
    from . import suggest

    where = f"across {projects} projects" if projects > 1 else f"in {sessions} sessions"
    what = f": {suggest.quote(example)}" if example and example.strip() else ""
    return (
        f"skill-spotter: you've asked for this in {count} prompts {where}{what}. "
        f"To add it to CLAUDE.md, run /skill-spotter:rule r{rule_id}"
    )


def maybe_suggest(
    conn: sqlite3.Connection,
    project_key: str,
    session_id: str,
    instruction_files: Iterable[str],
    now: float,
) -> Optional[str]:
    """Suggest a rule that crosses the trigger and isn't in an instruction file yet."""
    from . import suggest

    if not store.is_enabled(conn):
        return None
    rows = conn.execute(
        "SELECT id, key FROM rules WHERE state = 'candidate' "
        "OR (state = 'snoozed' AND COALESCE(state_until, 0) <= ?) ORDER BY last_seen DESC",
        (now,),
    ).fetchall()
    if not rows or suggest.session_or_day_capped(conn, session_id, now):
        return None
    files = list(instruction_files)
    for rule in rows:
        stats = rule_stats(conn, rule["id"], now)
        if stats["count"] < MIN_COUNT or stats["sessions"] < MIN_SESSIONS:
            continue
        # A rule seen in one project only belongs to that project.
        if len(stats["projects"]) == 1 and stats["projects"][0] != project_key:
            continue
        if is_covered(rule["key"], files):
            continue
        conn.execute(
            "UPDATE rules SET state = 'suggested', state_until = NULL WHERE id = ?", (rule["id"],)
        )
        conn.execute(
            "INSERT INTO events(ts, type, session_id, rule_id, data_json) "
            "VALUES(?, 'suggested', ?, ?, ?)",
            (
                now,
                session_id,
                rule["id"],
                json.dumps({"count": stats["count"], "projects": len(stats["projects"])}),
            ),
        )
        return message(
            rule["id"],
            stats["count"],
            stats["sessions"],
            len(stats["projects"]),
            stats["example"],
        )
    return None


def backfill(conn: sqlite3.Connection, now: float) -> int:
    """Read instructions from turns recorded before this feature existed (background job).
    Later turns are read when they end; re-reading a turn is a no-op."""
    since = float(store.get_setting(conn, "rules_scanned_until", "0") or 0)
    rows = conn.execute(
        "SELECT prompt_id, session_id, project_key, ts_start, prompt_redacted FROM turns "
        "WHERE finalized = 1 AND ts_start > ? AND ts_start >= ? AND prompt_redacted IS NOT NULL "
        "ORDER BY ts_start",
        (since, now - WINDOW_DAYS * DAY),
    ).fetchall()
    added = 0
    for r in rows:
        added += len(
            _record(
                conn,
                r["prompt_id"],
                r["session_id"],
                r["project_key"],
                r["ts_start"],
                r["prompt_redacted"],
            )
        )
    store.set_setting(conn, "rules_scanned_until", str(now))
    return added
