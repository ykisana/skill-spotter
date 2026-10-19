"""The method chosen by the Method Lab, for the runtime (SPEC 11.8 → M4). Standard library.

``config/method.json`` (written by ``bench.select``) names the text and action
representations and the fusion. This module computes the same pair features the lab
used and fuses them:

- text: ``word_jaccard`` (1-2-gram Jaccard) or ``bm25`` (symmetric, self-normalised)
- action: ``hier_idf_jaccard`` or ``hier_jaccard_noidf`` over turn fingerprints
- seq: LCS similarity of the meaningful action sequence; files: Jaccard of edited files
- n_min / n_max meaningful actions, same session, log time gap in days
- fusion: ``logreg`` (p = sigmoid(w·z + b), z standardised) or the ``rule``

A turn is compared with the last ``members`` turns of each candidate pattern; the
pattern's score is the mean. ``theta`` decides membership.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from . import baseline

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
DAY = 86400.0


def load_config(extras: bool = False) -> Dict[str, Any]:
    override = os.environ.get("SKILL_SPOTTER_METHOD_CONFIG")  # bench sweeps and tests
    names = ("method.extras.json", "method.json") if extras else ("method.json",)
    candidates = ([Path(override)] if override else []) + [CONFIG_DIR / n for n in names]
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                continue
    return {
        "fusion": "rule",
        "text": "word_jaccard",
        "actions": "hier_idf_jaccard[hand]",
        "theta": None,
    }


def lcs_similarity(x: List[str], y: List[str]) -> float:
    if not x or not y:
        return 0.0
    prev = [0] * (len(y) + 1)
    for a in x:
        cur = [0]
        for j, b in enumerate(y, 1):
            cur.append(prev[j - 1] + 1 if a == b else max(prev[j], cur[j - 1]))
        prev = cur
    return 2.0 * prev[-1] / (len(x) + len(y))


def jaccard_sets(a, b) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class BM25Stats:
    """Per-project document frequencies of normalized words, for BM25."""

    def __init__(
        self, df: Mapping[str, int], n_docs: int, avg_len: float, k1: float = 1.2, b: float = 0.75
    ):
        self.df, self.n, self.avg = df, max(1, n_docs), max(1.0, avg_len)
        self.k1, self.b = k1, b

    def idf(self, w: str) -> float:
        c = self.df.get(w, 0)
        return math.log(1 + (self.n - c + 0.5) / (c + 0.5))

    def score(self, query: List[str], doc: List[str]) -> float:
        tf = Counter(doc)
        dl = len(doc) or 1
        s = 0.0
        for w in set(query):
            f = tf.get(w)
            if f:
                s += (
                    self.idf(w)
                    * f
                    * (self.k1 + 1)
                    / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
                )
        return s

    def similarity(self, a: List[str], b: List[str]) -> float:
        if not a or not b:
            return 0.0
        sa, sb = self.score(a, a), self.score(b, b)
        if not sa or not sb:
            return 0.0
        return min(1.0, 0.5 * (self.score(a, b) / sa + self.score(b, a) / sb))


class FusedScorer:
    """Pairwise same-task probability between stored turns."""

    def __init__(self, config: Mapping[str, Any]):
        self.config = dict(config)
        self.text = config.get("text", "word_jaccard")
        self.action = (config.get("actions") or "hier_idf_jaccard[hand]").split("[")[0]
        self.fusion = config.get("fusion", "rule")
        lr = config.get("logreg") or {}
        self.lr = lr if lr.get("coef") else None
        if self.fusion == "logreg" and not self.lr:
            self.fusion = "rule"
        self.theta = float(config.get("theta") or 0.5)
        self.batch_theta = float(config.get("batch_theta") or self.theta)
        self.members = int(config.get("members_per_pattern") or 10)
        self.max_candidates = int(config.get("max_candidates") or 20)
        self.idf_weight = None
        self.bm25: Optional[BM25Stats] = None

    # --- context (project statistics) ----------------------------------------------
    def bind(self, conn, project_key: str, words=None) -> None:
        """Load the project statistics the features need (IDF for actions, BM25 df for
        ``words``, or all words if None)."""
        from .. import patterns as P

        total = P.n_turns(conn, project_key)
        if self.action.startswith("hier_idf_jaccard"):
            cache: Dict[str, float] = {}

            def weight(token, _cache=cache):
                if token not in _cache:
                    row = conn.execute(
                        "SELECT df FROM token_df WHERE project_key = ? AND token = ?",
                        (project_key, token),
                    ).fetchone()
                    _cache[token] = baseline.idf(row[0] if row else 0, total)
                return _cache[token]

            self.idf_weight = weight
        if self.text == "bm25":
            if words is None:
                rows = conn.execute(
                    "SELECT token, df FROM token_df WHERE project_key = ? AND token LIKE 'w:%'",
                    (project_key,),
                ).fetchall()
            else:
                keys = [f"w:{w}" for w in set(words)]
                rows = []
                for start in range(0, len(keys), 500):
                    chunk = keys[start : start + 500]
                    rows += conn.execute(
                        f"SELECT token, df FROM token_df WHERE project_key = ? "
                        f"AND token IN ({','.join('?' * len(chunk))})",
                        [project_key, *chunk],
                    ).fetchall()
            df = {r[0][2:]: r[1] for r in rows}
            stats = conn.execute(
                "SELECT n_turns, text_len FROM project_stats WHERE project_key = ?", (project_key,)
            ).fetchone()
            n = stats[0] if stats else 0
            avg = (stats[1] / n) if stats and n else 8.0
            self.bm25 = BM25Stats(df, n, avg)

    # --- per-turn data ------------------------------------------------------------------
    @staticmethod
    def turn_data(row: Mapping[str, Any]) -> Dict[str, Any]:
        fp = json.loads(row["fingerprint_json"] or "{}")
        try:
            extra = json.loads(row["seq_json"] or "[]")
        except (IndexError, KeyError):
            extra = []
        tokens = (row["prompt_norm"] or "").split()
        return {
            "fp": fp,
            "seq": extra or [],
            "files": {t for t in fp if t.startswith("edit:")},
            "tokens": tokens,
            "grams": set(tokens) | {f"{a} {b}" for a, b in zip(tokens, tokens[1:])},
            "n": row["n_meaningful_actions"] or 0,
            "session": row["session_id"],
            "ts": row["ts_end"] or row["ts_start"],
        }

    def load(self, conn, prompt_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        out = {}
        for start in range(0, len(prompt_ids), 500):
            chunk = prompt_ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            for row in conn.execute(
                "SELECT prompt_id, fingerprint_json, prompt_norm, n_meaningful_actions, seq_json, "
                f"session_id, ts_start, ts_end FROM turns WHERE prompt_id IN ({marks})",
                chunk,
            ):
                out[row["prompt_id"]] = self.turn_data(row)
        return out

    # --- scoring ------------------------------------------------------------------------
    def features(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, float]:
        if self.text == "bm25" and self.bm25 is not None:
            text = self.bm25.similarity(a["tokens"], b["tokens"])
        else:
            text = jaccard_sets(a["grams"], b["grams"])
        use_idf = self.action.startswith("hier_idf_jaccard") and self.idf_weight is not None
        weight = self.idf_weight if use_idf else (lambda t: 1.0)
        fa, fb = a["fp"], b["fp"]
        if self.action.endswith("_meaningful"):
            fa, fb = baseline.meaningful(fa), baseline.meaningful(fb)
        action = baseline.weighted_jaccard(fa, fb, weight)
        return {
            "text": text,
            "action": action,
            "seq": lcs_similarity(a["seq"], b["seq"]),
            "files": jaccard_sets(a["files"], b["files"]),
            "n_min": float(min(a["n"], b["n"])),
            "n_max": float(max(a["n"], b["n"])),
            "same_session": 1.0 if a["session"] == b["session"] else 0.0,
            "log_gap_days": math.log1p(abs((a["ts"] or 0) - (b["ts"] or 0)) / DAY),
            "action_x_text": action * text,
            "few_actions": 1.0 if min(a["n"], b["n"]) < 3 else 0.0,
        }

    def score(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
        f = self.features(a, b)
        if self.fusion == "logreg":
            lr = self.lr
            z = lr["intercept"]
            for name, mean, scale, coef in zip(lr["features"], lr["mean"], lr["scale"], lr["coef"]):
                z += coef * (f[name] - mean) / (scale or 1.0)
            return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))
        params = {**baseline.DEFAULTS, **(self.config.get("rule_params") or {})}
        s = baseline.score(f["action"], f["text"], params)
        passes = baseline.same_task(f["action"], f["text"], int(f["n_min"]), params)
        return 0.5 + 0.5 * min(1.0, s) if passes else 0.495 * min(1.0, s)

    @staticmethod
    def quick_reject(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        """Pairs sharing no strong action token and no word can't be the same task."""
        if any(w >= 0.25 and t in b["fp"] for t, w in a["fp"].items()):
            return False
        return not (set(a["tokens"]) & set(b["tokens"]))


def load_scorer(extras: bool = False) -> FusedScorer:
    return FusedScorer(load_config(extras))


def online_params() -> Dict[str, Any]:
    """Parameters for the online leader matcher (patterns.best_match): the same-task rule's
    thresholds and how action tokens are weighted ("idf" or "none")."""
    config = load_config()
    params = {**baseline.DEFAULTS, **(config.get("rule_params") or {})}
    params["action_weighting"] = config.get("action_weighting", "idf")
    return params
