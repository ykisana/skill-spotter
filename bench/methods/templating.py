"""Command templating candidates (SPEC 11.2, first row).

Every templater turns one tool call into the runtime's token shape: {token: weight} with
L1/L2/L3 levels for Bash, plus ``primary``, ``template`` and ``low``. Only Bash differs
between templaters; other tools always use the runtime normalizer, so comparisons isolate
the command-templating choice.

- hand:     the runtime's rules file (baseline)
- drain:    minimal stdlib Drain (fixed-depth parse tree, similarity threshold)
- drain3:   the Drain3 library
- entropy:  per-position value entropy learned from the data (identity vs value)
- fig:      Fig autocomplete specs (subcommand tree, options that take arguments)
- lsh:      LogLSHD-style grouping: MinHash LSH buckets, template = shared tokens
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from skill_spotter.capture import normalize_actions as na
from skill_spotter.capture import rules

from .base import register

WILD = "<*>"
_VALUE_TOKEN = re.compile(
    r"^(?:-?\d+(?:\.\d+)?[smhdkKMG%]?|[0-9a-f]{7,40}|\S*/\S*|\S+\.\w{1,5}|https?://\S+|\S*\s\S*|.*[=:].*|\d{4}-\d{2}-\d{2}.*)$"
)


def simple_commands(command: str) -> List[List[str]]:
    """Shell words of each simple command, with env assignments and wrappers stripped."""
    out = []
    for words in na.split_commands(command):
        words = list(words)
        while words and na._ENV_ASSIGN.match(words[0]):
            words.pop(0)
        while words and os.path.basename(words[0]) in rules.WRAPPERS:
            words.pop(0)
        if words:
            words[0] = words[0] if words[0] in rules.CLI_RULES else os.path.basename(words[0])
            out.append(words)
    return out


def mask(word: str) -> str:
    return WILD if _VALUE_TOKEN.match(word) else word


def hierarchy(words: List[str]) -> Tuple[Dict[str, float], str, str, bool]:
    """Template words (wildcards already removed or kept) -> L1/L2/L3 tokens."""
    words = [w for w in words if w != WILD]
    if not words:
        return {}, "", "", True
    cmd = words[0]
    subs = []
    for w in words[1:]:
        if w.startswith("-") or len(subs) >= 2:
            break
        subs.append(w)
    flags = sorted({w for w in words[1:] if w.startswith("-") and w not in rules.NOISE_FLAGS})
    l2 = " ".join([cmd] + subs)
    l3 = l2 + ("" if not flags else " " + " ".join(flags))
    low = (
        cmd in rules.LOW_VALUE_COMMANDS or " ".join([cmd] + subs[:1]) in rules.LOW_VALUE_SUBCOMMANDS
    )
    tokens = {f"bash:{cmd}": na.L1, f"bash:{l2}": na.L2}
    tokens[f"bash:{l3}"] = max(tokens.get(f"bash:{l3}", 0), na.L3)
    if low:
        tokens = {t: w * na.LOW_FACTOR for t, w in tokens.items()}
    return tokens, f"bash:{l2}", l3, low


class Templater:
    name = "base"

    def fit(self, commands: List[str]) -> None:
        pass

    def bash_parts(self, words: List[str]) -> List[str]:
        raise NotImplementedError

    def action(self, action: Dict[str, Any], root: str) -> Dict[str, Any]:
        tool, tool_input = action["tool"], action.get("input") or {}
        failed = bool(action.get("failed"))
        if tool != "Bash":
            return na.normalize_action(tool, tool_input, root, failed=failed)
        tokens: Dict[str, float] = {}
        templates, primaries, lows = [], [], []
        for words in simple_commands(str(tool_input.get("command") or "")):
            t, primary, template, low = hierarchy(self.bash_parts(words))
            for k, w in t.items():
                tokens[k] = max(tokens.get(k, 0.0), w)
            if template:
                templates.append(template)
                primaries.append((primary, low))
                lows.append(low)
        if failed:
            tokens = {k: w * na.FAILED_FACTOR for k, w in tokens.items()}
        meaningful = [p for p, low in primaries if not low]
        return {
            "tool": "Bash",
            "tokens": tokens,
            "primary": (meaningful or [p for p, _ in primaries] or [None])[0],
            "template": " ; ".join(templates),
            "low": not meaningful,
            "failed": failed,
            "danger": False,
            "values": [],
        }


@register("templating", "hand")
class HandRules(Templater):
    name = "hand"

    def action(self, action, root):
        return na.normalize_action(
            action["tool"], action.get("input") or {}, root, failed=bool(action.get("failed"))
        )


@register("templating", "drain")
class MiniDrain(Templater):
    """Drain (He et al., 2017): route by length and first tokens, merge into the most
    similar template above a threshold, generalising differing positions to <*>."""

    name = "drain"

    def __init__(self, depth: int = 2, threshold: float = 0.5):
        self.depth, self.threshold = depth, threshold
        self.groups: Dict[tuple, List[List[str]]] = defaultdict(list)

    def _key(self, words):
        head = tuple(w if not _VALUE_TOKEN.match(w) else WILD for w in words[: self.depth])
        return (len(words),) + head

    def _match(self, words):
        best, best_sim = None, -1.0
        for template in self.groups[self._key(words)]:
            same = sum(1 for a, b in zip(template, words) if a == b and a != WILD)
            sim = same / len(words)
            if sim > best_sim:
                best, best_sim = template, sim
        return best if best_sim >= self.threshold else None

    def _add(self, words):
        words = [mask(w) for w in words]
        template = self._match(words)
        if template is None:
            self.groups[self._key(words)].append(list(words))
            return words
        for i, (a, b) in enumerate(zip(template, words)):
            if a != b:
                template[i] = WILD
        return template

    def fit(self, commands):
        for cmd in commands:
            for words in simple_commands(cmd):
                self._add(words)

    def bash_parts(self, words):
        masked = [mask(w) for w in words]
        template = self._match(masked)
        return list(template) if template else masked


@register("templating", "drain3")
class Drain3Templater(Templater):
    name = "drain3"

    def __init__(self, sim_th: float = 0.5, depth: int = 4):
        from drain3 import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig

        config = TemplateMinerConfig()
        config.drain_sim_th = sim_th
        config.drain_depth = depth
        config.profiling_enabled = False
        self.miner = TemplateMiner(config=config)

    def fit(self, commands):
        for cmd in commands:
            for words in simple_commands(cmd):
                self.miner.add_log_message(" ".join(mask(w).replace(" ", "_") for w in words))

    def bash_parts(self, words):
        line = " ".join(mask(w).replace(" ", "_") for w in words)
        cluster = self.miner.match(line)
        template = cluster.get_template() if cluster else line
        return [w for w in template.split() if w not in ("<*>", "<:*:>")]


@register("templating", "entropy")
class EntropyTyping(Templater):
    """Learn, per (command, position-after-subcommands), whether values repeat (identity:
    keep) or are mostly new (value: wildcard), and which flags are followed by values."""

    name = "entropy"

    def __init__(self, max_ratio: float = 0.25, min_count: int = 4):
        self.max_ratio, self.min_count = max_ratio, min_count
        self.pos_values: Dict[tuple, Counter] = defaultdict(Counter)
        self.flag_next: Dict[tuple, Counter] = defaultdict(Counter)

    def fit(self, commands):
        for cmd in commands:
            for words in simple_commands(cmd):
                pos = 0
                for i, w in enumerate(words[1:], 1):
                    if w.startswith("-"):
                        nxt = words[i + 1] if i + 1 < len(words) else None
                        if nxt is not None and not nxt.startswith("-"):
                            self.flag_next[(words[0], w)][nxt] += 1
                        continue
                    self.pos_values[(words[0], pos)][w] += 1
                    pos += 1

    def _is_identity(self, key):
        counter = self.pos_values.get(key)
        if not counter:
            return False
        total = sum(counter.values())
        return total >= self.min_count and len(counter) / total <= self.max_ratio

    def _takes_value(self, key):
        counter = self.flag_next.get(key)
        if not counter:
            return False
        total = sum(counter.values())
        return total >= self.min_count and len(counter) / total > self.max_ratio

    def bash_parts(self, words):
        out = [words[0]]
        pos, skip = 0, False
        for i, w in enumerate(words[1:], 1):
            if skip:
                skip = False
                continue
            if w.startswith("-"):
                out.append(w.split("=")[0])
                skip = "=" not in w and self._takes_value((words[0], w))
                continue
            if self._is_identity((words[0], pos)) and not _VALUE_TOKEN.match(w):
                out.append(w)
            pos += 1
        return out


@register("templating", "fig")
class FigSpecs(Templater):
    """Walk Fig's subcommand tree; keep options, drop the arguments of options that take
    one, and drop positionals. Commands without a spec keep only their name."""

    name = "fig"
    SPECS = Path(__file__).resolve().parent / "fig" / "specs.json"

    def __init__(self):
        self.specs = json.loads(self.SPECS.read_text())

    @staticmethod
    def _find(items, word):
        for item in items:
            if word in item["names"]:
                return item
        return None

    def bash_parts(self, words):
        spec = self.specs.get(words[0])
        out = [words[0]]
        if spec is None:
            return out
        stack, skip = [spec], False
        for w in words[1:]:
            if skip:
                skip = False
                continue
            if w.startswith("-"):
                flag = w.split("=")[0]
                opt = None
                for s in reversed(stack):
                    opt = self._find(s["options"], flag)
                    if opt:
                        break
                out.append(flag)
                skip = bool(opt and opt["takesArg"] and "=" not in w)
                continue
            sub = self._find(stack[-1]["subcommands"], w)
            if sub:
                out.append(w)
                stack.append(sub)
        return out


@register("templating", "lsh")
class LSHGroups(Templater):
    """LogLSHD-style (2025): MinHash LSH over word shingles groups similar commands; the
    group template keeps tokens present in most members at the same position."""

    name = "lsh"

    def __init__(self, threshold: float = 0.6, num_perm: int = 64, keep_share: float = 0.6):
        from datasketch import MinHash, MinHashLSH

        self.MinHash = MinHash
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.num_perm, self.keep_share = num_perm, keep_share
        self.members: Dict[str, List[List[str]]] = {}
        self.template: Dict[str, List[str]] = {}

    def _mh(self, words):
        mh = self.MinHash(num_perm=self.num_perm)
        for w in words:
            mh.update(w.encode())
        for a, b in zip(words, words[1:]):
            mh.update(f"{a} {b}".encode())
        return mh

    def fit(self, commands):
        n = 0
        for cmd in commands:
            for words in simple_commands(cmd):
                masked = [mask(w) for w in words]
                mh = self._mh(masked)
                hits = [h for h in self.lsh.query(mh) if self.members[h][0][0] == masked[0]]
                if hits:
                    self.members[hits[0]].append(masked)
                else:
                    key = f"g{n}"
                    n += 1
                    self.lsh.insert(key, mh)
                    self.members[key] = [masked]
        for key, group in self.members.items():
            length = Counter(len(g) for g in group).most_common(1)[0][0]
            rows = [g for g in group if len(g) == length]
            template = []
            for i in range(length):
                word, count = Counter(r[i] for r in rows).most_common(1)[0]
                template.append(word if count / len(rows) >= self.keep_share else WILD)
            self.template[key] = template

    def bash_parts(self, words):
        masked = [mask(w) for w in words]
        hits = [h for h in self.lsh.query(self._mh(masked)) if self.members[h][0][0] == masked[0]]
        if not hits:
            return masked
        template = self.template[hits[0]]
        if len(template) != len(masked):
            return [w for w in template if w != WILD]
        return [t if t == m else WILD for t, m in zip(template, masked)] or masked


def all_commands(turns) -> List[str]:
    return [
        a["input"]["command"]
        for t in turns
        for a in t.actions
        if a["tool"] == "Bash" and a.get("input", {}).get("command")
    ]


def entropy_bits(counter: Counter) -> float:
    total = sum(counter.values())
    return -sum(c / total * math.log2(c / total) for c in counter.values()) if total else 0.0
