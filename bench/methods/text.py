"""Prompt -> features -> similarity (SPEC 11.2, text row). Scores are in [0, 1]."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import List

import numpy as np

from skill_spotter.capture import normalize_text as nt

from .base import register

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "emb"


def _norm_tokens(turn) -> List[str]:
    if "norm" not in turn.cache:
        turn.cache["norm"] = nt.normalize(turn.prompt)
    return turn.cache["norm"]


class TextRep:
    name = "base"
    vector_based = False

    def fit(self, turns) -> None:
        pass

    def score(self, a, b) -> float:
        raise NotImplementedError

    def pair_scores(self, turns, pairs) -> np.ndarray:
        return np.array([self.score(turns[i], turns[j]) for i, j, *_ in pairs], dtype=float)


@register("text", "word_jaccard")
class WordJaccard(TextRep):
    """Baseline: runtime normalization, word 1-2-gram Jaccard."""

    name = "word_jaccard"

    def score(self, a, b):
        return nt.jaccard(nt.ngrams(_norm_tokens(a)), nt.ngrams(_norm_tokens(b)))


class _Matrix(TextRep):
    """Representations with one row vector per turn; similarity = cosine, clipped at 0."""

    vector_based = True

    def __init__(self):
        self.X = None
        self.index = {}

    def vectors(self, turns):
        raise NotImplementedError

    def fit(self, turns):
        self.X = self.vectors(turns)
        self.index = {t.idx: k for k, t in enumerate(turns)}

    def row(self, turn):
        return self.X[self.index[turn.idx]]

    def pair_scores(self, turns, pairs):
        a = np.array([self.index[i] for i, j, *_ in pairs])
        b = np.array([self.index[j] for i, j, *_ in pairs])
        X = self.X
        if hasattr(X, "multiply"):  # sparse, rows L2-normalised
            sims = np.asarray(X[a].multiply(X[b]).sum(axis=1)).ravel()
        else:
            sims = np.einsum("ij,ij->i", X[a], X[b])
        return np.clip(sims, 0.0, 1.0)

    def score(self, a, b):
        return float(np.clip(self._dot(self.row(a), self.row(b)), 0, 1))

    @staticmethod
    def _dot(u, v):
        if hasattr(u, "multiply"):
            return float(u.multiply(v).sum())
        return float(np.dot(u, v))


@register("text", "tfidf_word")
class TfidfWord(_Matrix):
    name = "tfidf_word"

    def vectors(self, turns):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(analyzer=lambda doc: list(nt.ngrams(doc)), sublinear_tf=True)
        return self.vec.fit_transform([_norm_tokens(t) for t in turns])


@register("text", "tfidf_char")
class TfidfChar(_Matrix):
    """Character 3-5-grams within word boundaries: robust to typos and inflection."""

    name = "tfidf_char"

    def vectors(self, turns):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True
        )
        return self.vec.fit_transform([t.prompt for t in turns])


@register("text", "bm25")
class BM25(TextRep):
    """Symmetric, self-normalised BM25: mean of bm25(a,b)/bm25(a,a) and bm25(b,a)/bm25(b,b)."""

    name = "bm25"

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b

    def fit(self, turns):
        docs = [_norm_tokens(t) for t in turns]
        self.n = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(1, len(docs))
        df = Counter(w for d in docs for w in set(d))
        self.idf = {w: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def _bm25(self, query, doc):
        tf = Counter(doc)
        dl = len(doc) or 1
        s = 0.0
        for w in set(query):
            if w in tf:
                f = tf[w]
                s += (
                    self.idf.get(w, 0.0)
                    * f
                    * (self.k1 + 1)
                    / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                )
        return s

    def score(self, a, b):
        ta, tb = _norm_tokens(a), _norm_tokens(b)
        if not ta or not tb:
            return 0.0
        sa, sb = self._bm25(ta, ta), self._bm25(tb, tb)
        if not sa or not sb:
            return 0.0
        return min(1.0, 0.5 * (self._bm25(ta, tb) / sa + self._bm25(tb, ta) / sb))


@register("text", "minhash")
class MinHashText(TextRep):
    name = "minhash"

    def __init__(self, num_perm: int = 128):
        self.num_perm = num_perm

    def _mh(self, turn):
        if "minhash" not in turn.cache:
            from datasketch import MinHash

            mh = MinHash(num_perm=self.num_perm)
            for g in nt.ngrams(_norm_tokens(turn)):
                mh.update(g.encode())
            turn.cache["minhash"] = mh
        return turn.cache["minhash"]

    def score(self, a, b):
        if not _norm_tokens(a) or not _norm_tokens(b):
            return 0.0
        return float(self._mh(a).jaccard(self._mh(b)))


@register("text", "simhash")
class SimHash(TextRep):
    """64-bit SimHash over IDF-weighted normalized words; similarity = 1 - hamming/64."""

    name = "simhash"

    def fit(self, turns):
        df = Counter(w for t in turns for w in set(_norm_tokens(t)))
        n = len(turns)
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}

    def _hash(self, turn):
        if "simhash" not in turn.cache:
            v = [0.0] * 64
            for w in nt.ngrams(_norm_tokens(turn)):
                h = int(hashlib.md5(w.encode()).hexdigest()[:16], 16)
                weight = self.idf.get(w, 1.0) if " " not in w else 0.5
                for bit in range(64):
                    v[bit] += weight if h >> bit & 1 else -weight
            turn.cache["simhash"] = sum(1 << bit for bit in range(64) if v[bit] > 0)
        return turn.cache["simhash"]

    def score(self, a, b):
        if not _norm_tokens(a) or not _norm_tokens(b):
            return 0.0
        return 1.0 - bin(self._hash(a) ^ self._hash(b)).count("1") / 64.0


def _cached_embeddings(model_key: str, texts: List[str], encode) -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(("\n".join(texts)).encode()).hexdigest()[:16]
    path = CACHE / f"{model_key.replace('/', '_')}-{digest}.npy"
    if path.exists():
        return np.load(path)
    X = np.asarray(encode(texts), dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    np.save(path, X)
    return X


class _Embedder(_Matrix):
    model_id = ""
    key = ""

    def encode(self, texts):
        raise NotImplementedError

    def text_of(self, turn):
        return turn.prompt

    def vectors(self, turns):
        return _cached_embeddings(
            self.key or self.model_id, [self.text_of(t) for t in turns], self.encode
        )


@register("text", "model2vec_potion8m")
class Potion8M(_Embedder):
    name = "model2vec_potion8m"
    model_id = "minishlab/potion-base-8M"

    def encode(self, texts):
        from model2vec import StaticModel

        return StaticModel.from_pretrained(self.model_id).encode(texts)


@register("text", "model2vec_potion32m")
class Potion32M(Potion8M):
    name = "model2vec_potion32m"
    model_id = "minishlab/potion-base-32M"


class _FastEmbed(_Embedder):
    def encode(self, texts):
        from fastembed import TextEmbedding

        model = TextEmbedding(self.model_id, cache_dir=str(CACHE.parent / "fastembed"), threads=4)
        return np.array(list(model.embed(texts, batch_size=64)))


def _fastembed(name: str, model_id: str):
    cls = type(name, (_FastEmbed,), {"name": name, "model_id": model_id})
    register("text", name)(cls)
    return cls


MiniLM = _fastembed("minilm_l6", "sentence-transformers/all-MiniLM-L6-v2")
BgeSmall = _fastembed("bge_small", "BAAI/bge-small-en-v1.5")
ArcticXS = _fastembed("arctic_xs", "snowflake/snowflake-arctic-embed-xs")
ArcticS = _fastembed("arctic_s", "snowflake/snowflake-arctic-embed-s")
JinaSmall = _fastembed("jina_small", "jinaai/jina-embeddings-v2-small-en")
NomicQ = _fastembed("nomic_q", "nomic-ai/nomic-embed-text-v1.5-Q")


@register("text", "leaf_mt")
class LeafMT(_FastEmbed):
    """MongoDB mdbr-leaf-mt (23M): best <=30M model on MTEB v2 (Eng) at survey time.
    Not built into fastembed; registered as a custom ONNX model."""

    name = "leaf_mt"
    model_id = "MongoDB/mdbr-leaf-mt"

    def encode(self, texts):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        from huggingface_hub import snapshot_download

        # A flat local copy: ONNX refuses external weight files reached through the HF
        # cache's symlinked blobs ("external data path escapes model directory").
        local = CACHE.parent / "leaf-mt"
        snapshot_download(
            self.model_id,
            local_dir=str(local),
            allow_patterns=["onnx/model.onnx", "onnx/model.onnx_data", "*.json", "*.txt"],
        )
        try:
            TextEmbedding.add_custom_model(
                model=self.model_id,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=self.model_id),
                dim=384,
                model_file="onnx/model.onnx",
                additional_files=["onnx/model.onnx_data"],
            )
        except ValueError:
            pass  # already registered
        model = TextEmbedding(self.model_id, specific_model_path=str(local), threads=4)
        return np.array(list(model.embed(texts, batch_size=64)))
