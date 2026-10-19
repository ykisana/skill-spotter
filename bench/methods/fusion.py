"""Fusion of text and action similarity into one same-task score (SPEC 11.2, fusion row).

Features per pair: text similarity, action similarity, sequence similarity, file overlap,
min/max meaningful-action counts, same session, log time gap. Learned fusers are trained
on dev pairs only.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from skill_spotter.match import baseline

from .base import register

# Content features only. Timeline features (same session, time gap) and raw action counts
# were dropped after M3: the model learned the synthetic generator's timeline from them
# ("same session = different task"), which would mislead on real use (ADR 0007).
FEATURES = ["text", "action", "seq", "files", "action_x_text", "few_actions"]


def derived(cols: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Interaction features: action similarity means more when text agrees, and turns with
    few meaningful actions need text (mirrored in skill_spotter.match.fused)."""
    cols = dict(cols)
    cols["action_x_text"] = cols["action"] * cols["text"]
    cols["few_actions"] = (cols["n_min"] < 3).astype(float)
    return cols


def feature_matrix(cols: Dict[str, np.ndarray]) -> np.ndarray:
    cols = derived(cols)
    return np.column_stack([cols[f] for f in FEATURES])


class Fuser:
    name = "base"

    def fit(self, cols, y) -> None:
        pass

    def predict(self, cols) -> np.ndarray:
        raise NotImplementedError


@register("fusion", "rule")
class Rule(Fuser):
    """Runtime baseline: the same-task rule; passing pairs score action + 0.25*text."""

    name = "rule"

    def __init__(self, **params):
        self.params = {**baseline.DEFAULTS, **params}

    def predict(self, cols):
        out = np.zeros(len(cols["text"]))
        for k, (a, t, n) in enumerate(zip(cols["action"], cols["text"], cols["n_min"])):
            if baseline.same_task(a, t, int(n), self.params):
                out[k] = 0.5 + 0.5 * min(1.0, baseline.score(a, t, self.params))
            else:
                out[k] = 0.5 * min(1.0, baseline.score(a, t, self.params)) * 0.99
        return out


@register("fusion", "linear")
class Linear(Fuser):
    """w*text + (1-w)*action, w chosen on dev by PR-AUC."""

    name = "linear"

    def fit(self, cols, y):
        from sklearn.metrics import average_precision_score

        best = (-1, 0.5)
        for w in np.linspace(0, 1, 21):
            ap = average_precision_score(y, w * cols["text"] + (1 - w) * cols["action"])
            best = max(best, (ap, w))
        self.w = best[1]

    def predict(self, cols):
        return self.w * cols["text"] + (1 - self.w) * cols["action"]


@register("fusion", "logreg")
class LogReg(Fuser):
    name = "logreg"

    def fit(self, cols, y):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self.model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
        self.model.fit(feature_matrix(cols), y)

    def predict(self, cols):
        return self.model.predict_proba(feature_matrix(cols))[:, 1]

    def coefficients(self):
        lr = self.model[-1]
        return dict(zip(FEATURES, [round(float(c), 3) for c in lr.coef_[0]]))

    def export(self):
        """Everything the stdlib runtime needs: p = sigmoid(sum(w * (x - mean) / scale) + b)."""
        scaler, lr = self.model[0], self.model[-1]
        return {
            "features": FEATURES,
            "mean": [float(x) for x in scaler.mean_],
            "scale": [float(x) for x in scaler.scale_],
            "coef": [float(x) for x in lr.coef_[0]],
            "intercept": float(lr.intercept_[0]),
        }


@register("fusion", "gbt")
class GradientBoosted(Fuser):
    name = "gbt"

    def fit(self, cols, y):
        from sklearn.ensemble import HistGradientBoostingClassifier

        self.model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, random_state=0
        )
        self.model.fit(feature_matrix(cols), y)

    def predict(self, cols):
        return self.model.predict_proba(feature_matrix(cols))[:, 1]


@register("fusion", "logreg_monotone")
class MonotoneLogReg(Fuser):
    """Logistic regression whose similarity weights are constrained to be >= 0, so more
    agreement in text, actions, sequence or files can never lower the score. The plain
    logreg learned a negative action x text weight on synthetic data (paraphrased repeats
    rarely overlap in words) and then rejected near-identical real prompts (ADR 0007).
    Fitted with L-BFGS-B; inference is the same dot product as logreg."""

    name = "logreg_monotone"
    MONOTONE = {"text", "action", "seq", "files", "action_x_text"}

    def fit(self, cols, y):
        from scipy.optimize import minimize

        X = feature_matrix(cols)
        self.mean = X.mean(axis=0)
        self.scale = X.std(axis=0) + 1e-9
        Z = (X - self.mean) / self.scale
        y = np.asarray(y, dtype=float)
        n, d = Z.shape

        def loss(w):
            b, coef = w[0], w[1:]
            z = Z @ coef + b
            p = 1.0 / (1.0 + np.exp(-z))
            value = np.mean(np.logaddexp(0.0, z) - y * z) + 1e-3 * np.sum(coef**2)
            grad = np.concatenate([[np.mean(p - y)], Z.T @ (p - y) / n + 2e-3 * coef])
            return value, grad

        bounds = [(None, None)] + [
            (0.0, None) if f in self.MONOTONE else (None, None) for f in FEATURES
        ]
        result = minimize(loss, np.zeros(d + 1), jac=True, bounds=bounds, method="L-BFGS-B")
        self.intercept, self.coef = float(result.x[0]), result.x[1:]

    def predict(self, cols):
        Z = (feature_matrix(cols) - self.mean) / self.scale
        return 1.0 / (1.0 + np.exp(-(Z @ self.coef + self.intercept)))

    def coefficients(self):
        return dict(zip(FEATURES, [round(float(c), 3) for c in self.coef]))

    def export(self):
        return {
            "features": FEATURES,
            "mean": [float(x) for x in self.mean],
            "scale": [float(x) for x in self.scale],
            "coef": [float(x) for x in self.coef],
            "intercept": self.intercept,
        }
