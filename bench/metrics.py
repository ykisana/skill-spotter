"""Metrics from SPEC 11.7."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

import numpy as np


def best_f1_threshold(y: np.ndarray, s: np.ndarray, min_precision: float = 0.0) -> float:
    """Threshold maximising F1 (subject to a precision floor if given)."""
    order = np.argsort(-s)
    y_sorted, s_sorted = y[order], s[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / max(1, y.sum())
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-9)
    f1[precision < min_precision] = -1
    k = int(np.argmax(f1))
    return float(s_sorted[k])


def pairwise(y: np.ndarray, s: np.ndarray, threshold: float) -> Dict[str, float]:
    from sklearn.metrics import average_precision_score

    pred = s >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "pr_auc": round(float(average_precision_score(y, s)), 4) if 0 < y.sum() < len(y) else None,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
        "threshold": round(threshold, 4),
    }


def by_group(y, s, threshold, groups: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """Recall per positive tier, false-positive rate per negative type."""
    out = {}
    groups = np.asarray(groups)
    for g in sorted(set(groups)):
        mask = groups == g
        pred = s[mask] >= threshold
        if y[mask].all():
            out[g] = {"recall": round(float(pred.mean()), 4), "n": int(mask.sum())}
        else:
            out[g] = {"false_positive_rate": round(float(pred.mean()), 4), "n": int(mask.sum())}
    return out


def bcubed(labels_true: Sequence[str], labels_pred: Sequence[int]) -> Dict[str, float]:
    """B-cubed precision/recall/F1; predicted noise (-1) counts as its own singleton."""
    pred = [f"n{i}" if p < 0 else f"c{p}" for i, p in enumerate(labels_pred)]
    by_pred, by_true = defaultdict(list), defaultdict(list)
    for i, (t, p) in enumerate(zip(labels_true, pred)):
        by_pred[p].append(i)
        by_true[t].append(i)
    P = R = 0.0
    for i, (t, p) in enumerate(zip(labels_true, pred)):
        same_pred = by_pred[p]
        same_true = by_true[t]
        correct = sum(1 for j in same_pred if labels_true[j] == t)
        P += correct / len(same_pred)
        R += correct / len(same_true)
    n = len(pred)
    P, R = P / n, R / n
    return {
        "bcubed_p": round(P, 4),
        "bcubed_r": round(R, 4),
        "bcubed_f1": round(2 * P * R / (P + R), 4) if P + R else 0.0,
    }


def clustering(
    labels_true: List[str], labels_pred: List[int], kinds: List[str]
) -> Dict[str, float]:
    from sklearn import metrics as M

    pred_unique = [
        p if p >= 0 else -(i + 10) for i, p in enumerate(labels_pred)
    ]  # noise = singletons
    out = {
        "ari": round(float(M.adjusted_rand_score(labels_true, pred_unique)), 4),
        "nmi": round(float(M.normalized_mutual_info_score(labels_true, pred_unique)), 4),
        "v_measure": round(float(M.v_measure_score(labels_true, pred_unique)), 4),
    }
    out.update(bcubed(labels_true, labels_pred))
    singles = [p for p, k in zip(labels_pred, kinds) if k != "positive"]
    out["oneoffs_left_alone"] = round(sum(1 for p in singles if p < 0) / max(1, len(singles)), 4)
    return out


def percentile(values: List[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")
