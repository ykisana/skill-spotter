"""Background-tier scorer with optional dependencies (config/method.extras.json).

Only ``background.job`` imports this, and only when ``<data dir>/extras`` holds numpy,
scikit-learn and fastembed (installed by ``skill-spotter extras``). Hooks never do.

Text similarity is the cosine of prompt embeddings (cached in the ``vectors`` table);
the other features are the stdlib ones; a gradient-boosted model trained in the Method
Lab (config/model.extras.pkl) fuses them. Pairs are scored in batches.
"""

from __future__ import annotations

import pickle
from typing import Dict, List

from ..match import fused

MODEL_IDS = {
    "jina_small": "jinaai/jina-embeddings-v2-small-en",
    "bge_small": "BAAI/bge-small-en-v1.5",
    "minilm_l6": "sentence-transformers/all-MiniLM-L6-v2",
}


class ExtrasScorer(fused.FusedScorer):
    def __init__(self, config, model_path, cache_dir):
        super().__init__({**config, "fusion": "rule"})
        self.linear = None
        if model_path is not None:
            with open(model_path, "rb") as f:
                bundle = pickle.load(f)
            self.model = bundle["model"]
            self.feature_names = bundle["features"]
        else:  # a linear fuser shipped as coefficients in the config
            self.linear = config["logreg"]
            self.feature_names = self.linear["features"]
        self.embed_name = config.get("text", "jina_small")
        self.cache_dir = cache_dir
        self.batch_theta = float(config.get("batch_theta") or config.get("theta") or 0.9)
        self._embedder = None

    def _embed(self, texts: List[str]):
        import numpy as np
        from fastembed import TextEmbedding

        if self._embedder is None:
            self._embedder = TextEmbedding(
                MODEL_IDS[self.embed_name],
                cache_dir=str(self.cache_dir),
                local_files_only=True,
                threads=2,
            )
        X = np.array(list(self._embedder.embed(texts, batch_size=64)), dtype=np.float32)
        return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    def load(self, conn, prompt_ids):
        import numpy as np

        data = super().load(conn, prompt_ids)
        method = f"embed:{self.embed_name}"
        have = {}
        for start in range(0, len(prompt_ids), 500):
            chunk = prompt_ids[start : start + 500]
            for owner, dim, blob in conn.execute(
                f"SELECT owner_id, dim, blob FROM vectors WHERE owner_type = 'turn' AND method = ? "
                f"AND owner_id IN ({','.join('?' * len(chunk))})",
                [method, *chunk],
            ):
                have[owner] = np.frombuffer(blob, dtype=np.float32, count=dim)
        missing = [p for p in prompt_ids if p not in have and p in data]
        if missing:
            texts = {
                r[0]: r[1] or ""
                for r in conn.execute(
                    "SELECT prompt_id, prompt_redacted FROM turns "
                    f"WHERE prompt_id IN ({','.join('?' * len(missing))})",
                    missing,
                )
            }
            X = self._embed([texts.get(p, "") for p in missing])
            conn.executemany(
                "INSERT OR REPLACE INTO vectors(owner_type, owner_id, method, dim, blob) "
                "VALUES('turn', ?, ?, ?, ?)",
                [(p, method, X.shape[1], X[i].tobytes()) for i, p in enumerate(missing)],
            )
            have.update({p: X[i] for i, p in enumerate(missing)})
        for p, d in data.items():
            d["vec"] = have.get(p)
        return data

    def score_many(self, pairs: List[tuple]) -> List[float]:
        import numpy as np

        rows = []
        for a, b in pairs:
            f = self.features(a, b)
            if a.get("vec") is not None and b.get("vec") is not None:
                f["text"] = float(max(0.0, min(1.0, float(np.dot(a["vec"], b["vec"])))))
                f["action_x_text"] = f["action"] * f["text"]
            rows.append([f[name] for name in self.feature_names])
        if not rows:
            return []
        X = np.array(rows)
        if self.linear is not None:
            lr = self.linear
            z = ((X - np.array(lr["mean"])) / np.array(lr["scale"])) @ np.array(lr["coef"]) + lr[
                "intercept"
            ]
            return [float(p) for p in 1.0 / (1.0 + np.exp(-z))]
        return [float(p) for p in self.model.predict_proba(X)[:, 1]]

    def score(self, a, b) -> float:
        return self.score_many([(a, b)])[0]


def load(base, config_dir) -> ExtrasScorer | None:
    import json

    config_path = config_dir / "method.extras.json"
    model_path = config_dir / "model.extras.pkl"
    if not config_path.is_file():
        return None
    config: Dict = json.loads(config_path.read_text())
    if config.get("fusion") == "gbt" and not model_path.is_file():
        return None
    return ExtrasScorer(
        config, model_path if config.get("fusion") == "gbt" else None, base / "extras" / "models"
    )
