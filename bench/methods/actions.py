"""Actions -> features -> similarity (SPEC 11.2, actions row). Scores are in [0, 1].

Every action representation takes a templater (see ``templating.py``), so the lab can
measure templating and action representation independently.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

import numpy as np

from skill_spotter.capture.normalize_actions import turn_fingerprint
from skill_spotter.match import baseline

from .base import register
from .text import _cached_embeddings


def normalized_actions(turn, templater) -> List[Dict]:
    key = f"actions:{templater.name}"
    if key not in turn.cache:
        turn.cache[key] = [templater.action(a, turn.root) for a in turn.actions]
    return turn.cache[key]


def fingerprint(turn, templater) -> Dict[str, float]:
    key = f"fp:{templater.name}"
    if key not in turn.cache:
        turn.cache[key] = turn_fingerprint(normalized_actions(turn, templater))
    return turn.cache[key]


def sequence(turn, templater) -> List[str]:
    """Primary keys of meaningful, successful actions, consecutive repeats collapsed."""
    key = f"seq:{templater.name}"
    if key not in turn.cache:
        seq = [
            a["primary"]
            for a in normalized_actions(turn, templater)
            if a.get("primary") and not a.get("low") and not a.get("failed")
        ]
        turn.cache[key] = [p for i, p in enumerate(seq) if i == 0 or p != seq[i - 1]]
    return turn.cache[key]


def n_meaningful(turn, templater) -> int:
    return sum(1 for a in normalized_actions(turn, templater) if a["tokens"] and not a.get("low"))


class ActionRep:
    name = "base"

    def __init__(self, templater):
        self.templater = templater

    def fit(self, turns) -> None:
        pass

    def score(self, a, b) -> float:
        raise NotImplementedError

    def pair_scores(self, turns, pairs) -> np.ndarray:
        return np.array([self.score(turns[i], turns[j]) for i, j, *_ in pairs], dtype=float)


@register("actions", "hier_idf_jaccard")
class HierIdfJaccard(ActionRep):
    """Baseline: hierarchical tokens + order bigrams, IDF-weighted Jaccard."""

    name = "hier_idf_jaccard"

    def fit(self, turns):
        df = Counter(t for turn in turns for t in fingerprint(turn, self.templater))
        n = len(turns)
        self.weight = {t: baseline.idf(c, n) for t, c in df.items()}
        self.default = baseline.idf(0, n)

    def score(self, a, b):
        return baseline.weighted_jaccard(
            fingerprint(a, self.templater),
            fingerprint(b, self.templater),
            lambda t: self.weight.get(t, self.default),
        )


@register("actions", "hier_jaccard_noidf")
class HierJaccardNoIdf(ActionRep):
    """Ablation: the baseline without IDF weighting."""

    name = "hier_jaccard_noidf"

    def score(self, a, b):
        return baseline.weighted_jaccard(
            fingerprint(a, self.templater), fingerprint(b, self.templater), lambda t: 1.0
        )


@register("actions", "tfidf_templates")
class TfidfTemplates(ActionRep):
    """TF-IDF over the fingerprint's tokens (templates + bigrams), cosine."""

    name = "tfidf_templates"

    def fit(self, turns):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(analyzer=lambda d: d, sublinear_tf=True)
        docs = [
            [
                t
                for t, w in fingerprint(x, self.templater).items()
                for _ in range(max(1, round(w * 2)))
            ]
            for x in turns
        ]
        self.X = self.vec.fit_transform(docs)
        self.index = {t.idx: k for k, t in enumerate(turns)}

    def pair_scores(self, turns, pairs):
        a = np.array([self.index[i] for i, j, *_ in pairs])
        b = np.array([self.index[j] for i, j, *_ in pairs])
        return np.clip(np.asarray(self.X[a].multiply(self.X[b]).sum(axis=1)).ravel(), 0, 1)


@register("actions", "embed_templates")
class EmbedTemplates(ActionRep):
    """Embed the serialized template sequence ("npm run build ; make deploy ; edit ...")."""

    name = "embed_templates"
    model_id = "sentence-transformers/all-MiniLM-L6-v2"

    def _text(self, turn):
        acts = [
            a for a in normalized_actions(turn, self.templater) if a["tokens"] and not a.get("low")
        ]
        return " ; ".join(a["template"] for a in acts) or "(no actions)"

    def fit(self, turns):
        from fastembed import TextEmbedding

        from .text import CACHE

        def encode(texts):
            model = TextEmbedding(
                self.model_id, cache_dir=str(CACHE.parent / "fastembed"), threads=4
            )
            return np.array(list(model.embed(texts, batch_size=64)))

        texts = [self._text(t) for t in turns]
        self.X = _cached_embeddings(f"actions-{self.templater.name}-{self.model_id}", texts, encode)
        self.empty = np.array([x == "(no actions)" for x in texts])
        self.index = {t.idx: k for k, t in enumerate(turns)}

    def pair_scores(self, turns, pairs):
        a = np.array([self.index[i] for i, j, *_ in pairs])
        b = np.array([self.index[j] for i, j, *_ in pairs])
        sims = np.clip(np.einsum("ij,ij->i", self.X[a], self.X[b]), 0, 1)
        sims[self.empty[a] | self.empty[b]] = 0.0
        return sims


def _edit_distance(x, y) -> int:
    prev = list(range(len(y) + 1))
    for i, a in enumerate(x, 1):
        cur = [i]
        for j, b in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1]


def _lcs(x, y) -> int:
    prev = [0] * (len(y) + 1)
    for a in x:
        cur = [0]
        for j, b in enumerate(y, 1):
            cur.append(prev[j - 1] + 1 if a == b else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def _dtw(x, y) -> float:
    inf = float("inf")
    d = [[inf] * (len(y) + 1) for _ in range(len(x) + 1)]
    d[0][0] = 0.0
    for i in range(1, len(x) + 1):
        for j in range(1, len(y) + 1):
            cost = 0.0 if x[i - 1] == y[j - 1] else 1.0
            d[i][j] = cost + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    return d[-1][-1]


class _Seq(ActionRep):
    def score(self, a, b):
        x, y = sequence(a, self.templater), sequence(b, self.templater)
        if not x or not y:
            return 0.0
        return self.sim(x, y)


@register("actions", "seq_edit")
class SeqEdit(_Seq):
    name = "seq_edit"

    def sim(self, x, y):
        return 1.0 - _edit_distance(x, y) / max(len(x), len(y))


@register("actions", "seq_lcs")
class SeqLCS(_Seq):
    name = "seq_lcs"

    def sim(self, x, y):
        return 2.0 * _lcs(x, y) / (len(x) + len(y))


@register("actions", "seq_dtw")
class SeqDTW(_Seq):
    name = "seq_dtw"

    def sim(self, x, y):
        return 1.0 - _dtw(x, y) / max(len(x), len(y))


@register("actions", "fileset")
class FileSet(ActionRep):
    """Jaccard of the files the turn edited."""

    name = "fileset"

    def _files(self, turn):
        return {t for t in fingerprint(turn, self.templater) if t.startswith("edit:")}

    def score(self, a, b):
        fa, fb = self._files(a), self._files(b)
        return len(fa & fb) / len(fa | fb) if fa and fb else 0.0


@register("actions", "hier_jaccard_meaningful")
class HierJaccardMeaningful(ActionRep):
    """No IDF; only meaningful tokens (weight >= 0.25) count. Turns without meaningful
    actions score 0, so text decides for them (ADR 0006)."""

    name = "hier_jaccard_meaningful"

    def score(self, a, b):
        fa = baseline.meaningful(fingerprint(a, self.templater))
        fb = baseline.meaningful(fingerprint(b, self.templater))
        return baseline.weighted_jaccard(fa, fb, lambda t: 1.0)


@register("actions", "hier_idf_jaccard_meaningful")
class HierIdfJaccardMeaningful(HierIdfJaccard):
    name = "hier_idf_jaccard_meaningful"

    def score(self, a, b):
        fa = baseline.meaningful(fingerprint(a, self.templater))
        fb = baseline.meaningful(fingerprint(b, self.templater))
        return baseline.weighted_jaccard(fa, fb, lambda t: self.weight.get(t, self.default))
