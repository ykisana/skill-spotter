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

FEATURES = ["text", "action", "seq", "files", "n_min", "n_max", "same_session", "log_gap_days"]


def feature_matrix(cols: Dict[str, np.ndarray]) -> np.ndarray:
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
