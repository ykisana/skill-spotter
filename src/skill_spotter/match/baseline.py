"""Baseline similarity and the same-task rule (SPEC section 5.3).

- Action similarity: IDF-weighted Jaccard over action tokens, so near-universal
  actions (``git status``, reads) carry little weight.
- Text similarity: Jaccard over normalized word 1–2-grams.
- Same task if ``action >= 0.7``, or ``action >= 0.5 and text >= 0.2``, or the turn has
  fewer than 2 meaningful actions and ``text >= 0.6``.

Thresholds are parameters so the Method Lab (M3) can tune them; see ``DEFAULTS``.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Mapping

DEFAULTS: Dict[str, float] = {
    "action_strong": 0.7,
    "action_weak": 0.5,
    "text_with_weak_action": 0.2,
    "text_only": 0.6,
    "few_actions": 2,
    "text_weight_in_score": 0.25,
    # M3 findings (ADR 0006): an action-only match between turns with few meaningful
    # actions also needs a little text agreement ("psql -c ..." for unrelated questions),
    # and only meaningful tokens count towards action similarity.
    "text_gate": 0.08,
    "text_gate_below_actions": 3,
    "meaningful_min_weight": 0.25,
}


def meaningful(tokens: Mapping[str, float], min_weight: float = 0.25) -> Dict[str, float]:
    """Drop L1 command names and low-value exploration tokens (weights below
    ``min_weight``): identical sets of those (two Grep-only turns) said nothing about the task."""
    return {t: w for t, w in tokens.items() if w >= min_weight}


def idf(df: int, n_turns: int) -> float:
    """Smoothed inverse document frequency; always >= 1."""
    return math.log((n_turns + 1) / (df + 1)) + 1.0


def weighted_jaccard(
    a: Mapping[str, float], b: Mapping[str, float], weight_of: Callable[[str], float]
) -> float:
    if not a or not b:
        return 0.0
    num = den = 0.0
    for token in a.keys() | b.keys():
        wa, wb = a.get(token, 0.0), b.get(token, 0.0)
        w = weight_of(token)
        num += min(wa, wb) * w
        den += max(wa, wb) * w
    return num / den if den else 0.0


def text_similarity(grams: set, pattern_text: Mapping[str, float]) -> float:
    """Jaccard between a turn's n-grams and a pattern's (fractional) n-gram profile."""
    if not grams or not pattern_text:
        return 0.0
    num = sum(pattern_text.get(g, 0.0) for g in grams)
    den = len(grams) + sum(f for g, f in pattern_text.items() if g not in grams)
    return num / den if den else 0.0


def same_task(
    action_sim: float, text_sim: float, n_meaningful: int, params: Mapping[str, float] = DEFAULTS
) -> bool:
    gate = params.get("text_gate", 0.0)
    if action_sim >= params["action_strong"] and (
        n_meaningful >= params.get("text_gate_below_actions", 0) or text_sim >= gate
    ):
        return True
    if action_sim >= params["action_weak"] and text_sim >= params["text_with_weak_action"]:
        return True
    return n_meaningful < params["few_actions"] and text_sim >= params["text_only"]


def score(action_sim: float, text_sim: float, params: Mapping[str, float] = DEFAULTS) -> float:
    return action_sim + params["text_weight_in_score"] * text_sim
