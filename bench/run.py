"""Run the Method Lab: score every registered method on dev, check on test (SPEC 11.6).

    .venv/bin/python -m bench.run [--stages text,templating,actions,fusion,cluster]

Stages build on each other: fusion uses the best text and action representations, and
clustering uses the best fusion. Two tracks run side by side:
  - stdlib: methods the online tier could run (no third-party packages)
  - extras: anything, for the background tier
Results go to bench/results/results.jsonl (one JSON object per line).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict

import numpy as np

from . import data as D
from . import metrics as M
from .methods import actions as A  # noqa: F401  (registers methods)
from .methods import cluster as C  # noqa: F401
from .methods import fusion as F  # noqa: F401  (registers methods)
from .methods import templating as T
from .methods import text as X  # noqa: F401
from .methods.base import REGISTRY, make

RESULTS = Path(__file__).resolve().parent / "results"
STDLIB_TEXT = {"word_jaccard", "bm25", "simhash"}  # implementable without third-party code
STDLIB_ACTIONS = {
    "hier_idf_jaccard",
    "hier_jaccard_noidf",
    "seq_edit",
    "seq_lcs",
    "seq_dtw",
    "fileset",
}
STDLIB_TEMPLATERS = {"hand", "drain", "entropy", "fig"}
STDLIB_FUSION = {"rule", "linear", "logreg"}  # logreg inference is a dot product
STDLIB_CLUSTER = {"leader", "components"}


class Lab:
    def __init__(self, reuse: bool = False):
        self.reuse = reuse
        self.dev = D.load("dev")
        self.test = D.load("test")
        self.pairs = {"dev": D.make_pairs(self.dev), "test": D.make_pairs(self.test)}
        self.turns = {"dev": self.dev, "test": self.test}
        RESULTS.mkdir(exist_ok=True)
        self.out = open(RESULTS / "results.jsonl", "a")
        self.stamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    def log(self, **rec):
        rec["run"] = self.stamp
        self.out.write(json.dumps(rec) + "\n")
        self.out.flush()

    def y(self, split):
        return np.array([p[2] for p in self.pairs[split]])

    def groups(self, split):
        return [D.difficulty_of(p, self.turns[split]) for p in self.pairs[split]]

    def evaluate_scores(self, stage, method, scores: Dict[str, np.ndarray], extra=None, track=None):
        thr = M.best_f1_threshold(self.y("dev"), scores["dev"])
        thr90 = M.best_f1_threshold(self.y("dev"), scores["dev"], min_precision=0.9)
        res = {}
        for split in ("dev", "test"):
            res[split] = M.pairwise(self.y(split), scores[split], thr)
            res[split]["at_p90"] = M.pairwise(self.y(split), scores[split], thr90)
        res["test_by_tier"] = M.by_group(self.y("test"), scores["test"], thr, self.groups("test"))
        for split in ("dev", "test"):  # for PR curves in the report
            np.save(self.cache_path(stage, method, split), scores[split])
        self.log(stage=stage, method=method, track=track, **res, **(extra or {}))
        print(
            f"{stage:10s} {method:40s} dev AP {res['dev']['pr_auc']}  test AP {res['test']['pr_auc']}  "
            f"test F1 {res['test']['f1']}  (thr {thr:.3f})"
        )
        return res

    # --- stage: text ----------------------------------------------------------------
    def text(self):
        out = {}
        for name in REGISTRY["text"]:
            started = time.time()
            if self.reuse and all(
                self.cache_path("text", name, s).exists() for s in ("dev", "test")
            ):
                scores = {s: np.load(self.cache_path("text", name, s)) for s in ("dev", "test")}
                out[name] = self.evaluate_scores(
                    "text",
                    name,
                    scores,
                    {"reused": True},
                    "stdlib" if name in STDLIB_TEXT else "extras",
                )
                continue
            try:
                scores = {}
                for split in ("dev", "test"):
                    rep = make("text", name)
                    rep.fit(self.turns[split])
                    scores[split] = rep.pair_scores(self.turns[split], self.pairs[split])
            except Exception as exc:  # noqa: BLE001
                print(f"text {name} failed: {exc}")
                self.log(stage="text", method=name, error=str(exc))
                continue
            track = "stdlib" if name in STDLIB_TEXT else "extras"
            out[name] = self.evaluate_scores(
                "text", name, scores, {"seconds": round(time.time() - started, 1)}, track
            )
            np.save(self.cache_path("text", name, "dev"), scores["dev"])
            np.save(self.cache_path("text", name, "test"), scores["test"])
        return out

    def cache_path(self, stage, name, split):
        path = RESULTS.parent / ".cache" / "scores"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{stage}-{name}-{split}.npy"

    # --- stage: templating ------------------------------------------------------------
    def templating(self):
        """Grouping accuracy: calls generated from the same trace step should share a
        template, calls from different steps shouldn't (pairs within each family)."""
        import random

        rng = random.Random(3)
        for name in REGISTRY["templating"]:
            started = time.time()
            try:
                templater = make("templating", name)
                templater.fit(T.all_commands(self.dev))
            except Exception as exc:  # noqa: BLE001
                print(f"templating {name} failed: {exc}")
                self.log(stage="templating", method=name, error=str(exc))
                continue
            results = {}
            for split in ("dev", "test"):
                by_family = defaultdict(list)
                for t in self.turns[split]:
                    if t.kind != "positive":
                        continue
                    for a in t.actions:
                        if a["tool"] == "Bash" and a.get("src") and not a.get("failed"):
                            norm = templater.action(a, t.root)
                            by_family[t.family].append((a["src"], norm["template"]))
                tp = fp = fn = tn = 0
                for calls in by_family.values():
                    for _ in range(min(400, len(calls) * 4)):
                        (s1, t1), (s2, t2) = rng.choice(calls), rng.choice(calls)
                        same_src, same_t = s1 == s2, t1 == t2
                        tp += same_src and same_t
                        fn += same_src and not same_t
                        fp += (not same_src) and same_t
                        tn += (not same_src) and not same_t
                p = tp / (tp + fp) if tp + fp else 0.0
                r = tp / (tp + fn) if tp + fn else 0.0
                results[split] = {
                    "group_precision": round(p, 4),
                    "group_recall": round(r, 4),
                    "group_f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
                }
            track = "stdlib" if name in STDLIB_TEMPLATERS else "extras"
            self.log(
                stage="templating",
                method=name,
                track=track,
                seconds=round(time.time() - started, 1),
                **results,
            )
            print(f"templating {name:12s} dev {results['dev']}  test {results['test']}")

    # --- stage: actions ---------------------------------------------------------------
    def actions(self, templaters=None, reps=None):
        out = {}
        for tname in templaters or REGISTRY["templating"]:
            for aname in reps or REGISTRY["actions"]:
                if tname != "hand" and aname not in ("hier_idf_jaccard",):
                    continue  # templater comparison only on the baseline representation
                key = f"{aname}[{tname}]"
                started = time.time()
                if self.reuse and all(
                    self.cache_path("actions", key, s).exists() for s in ("dev", "test")
                ):
                    scores = {
                        s: np.load(self.cache_path("actions", key, s)) for s in ("dev", "test")
                    }
                    track = (
                        "stdlib"
                        if aname in STDLIB_ACTIONS and tname in STDLIB_TEMPLATERS
                        else "extras"
                    )
                    out[key] = self.evaluate_scores("actions", key, scores, {"reused": True}, track)
                    continue
                try:
                    scores = {}
                    for split in ("dev", "test"):
                        templater = make("templating", tname)
                        templater.fit(T.all_commands(self.turns[split]))
                        rep = make("actions", aname, templater=templater)
                        rep.fit(self.turns[split])
                        scores[split] = rep.pair_scores(self.turns[split], self.pairs[split])
                except Exception as exc:  # noqa: BLE001
                    print(f"actions {key} failed: {exc}")
                    self.log(stage="actions", method=key, error=str(exc))
                    continue
                track = (
                    "stdlib" if aname in STDLIB_ACTIONS and tname in STDLIB_TEMPLATERS else "extras"
                )
                out[key] = self.evaluate_scores(
                    "actions", key, scores, {"seconds": round(time.time() - started, 1)}, track
                )
                np.save(self.cache_path("actions", key, "dev"), scores["dev"])
                np.save(self.cache_path("actions", key, "test"), scores["test"])
        return out

    # --- stage: fusion ----------------------------------------------------------------
    def pair_columns(self, split, text_name, action_name):
        turns, pairs = self.turns[split], self.pairs[split]
        hand = T.HandRules()
        n = np.array([A.n_meaningful(t, hand) for t in turns])
        cols = {
            "text": np.load(self.cache_path("text", text_name, split)),
            "action": np.load(self.cache_path("actions", action_name, split)),
            "seq": np.load(self.cache_path("actions", "seq_lcs[hand]", split)),
            "files": np.load(self.cache_path("actions", "fileset[hand]", split)),
        }
        i = np.array([p[0] for p in pairs])
        j = np.array([p[1] for p in pairs])
        cols["n_min"] = np.minimum(n[i], n[j])
        cols["n_max"] = np.maximum(n[i], n[j])
        sess = np.array([t.session for t in turns])
        ts = np.array([t.ts for t in turns])
        cols["same_session"] = (sess[i] == sess[j]).astype(float)
        cols["log_gap_days"] = np.log1p(np.abs(ts[i] - ts[j]) / 86400.0)
        return cols

    def fusion(self, text_by_track, action_by_track):
        best = {}
        for track in ("stdlib", "extras"):
            tname, aname = text_by_track[track], action_by_track[track]
            cols = {s: self.pair_columns(s, tname, aname) for s in ("dev", "test")}
            for fname in REGISTRY["fusion"]:
                if track == "stdlib" and fname not in STDLIB_FUSION:
                    continue
                fuser = make("fusion", fname)
                fuser.fit(cols["dev"], self.y("dev"))
                scores = {s: fuser.predict(cols[s]) for s in ("dev", "test")}
                extra = {"text": tname, "action": aname}
                if hasattr(fuser, "coefficients"):
                    extra["coefficients"] = fuser.coefficients()
                    extra["export"] = fuser.export()
                if hasattr(fuser, "w"):
                    extra["w_text"] = round(float(fuser.w), 3)
                res = self.evaluate_scores("fusion", f"{fname}<{track}>", scores, extra, track)
                if track not in best or (res["dev"]["pr_auc"] or 0) > best[track][1]:
                    best[track] = (fname, res["dev"]["pr_auc"] or 0, fuser)
        return best

    # --- stage: clustering -----------------------------------------------------------
    def build_scorer(self, split, track, text_name, action_name, fuser):
        from .replay import PairScorer

        turns = self.turns[split]
        hand = T.HandRules()
        text_rep = make("text", text_name)
        text_rep.fit(turns)
        tname, aname = action_name.split("[")[1].rstrip("]"), action_name.split("[")[0]
        templater = make("templating", tname)
        templater.fit(T.all_commands(turns))
        action_rep = make("actions", aname, templater=templater)
        action_rep.fit(turns)
        seq = make("actions", "seq_lcs", templater=hand)
        files = make("actions", "fileset", templater=hand)
        return PairScorer(turns, text_rep, action_rep, fuser, seq, files, hand)

    def project_matrices(self, split, scorer):
        out = []
        for project in sorted({t.project for t in self.turns[split]}):
            idx = [t.idx for t in self.turns[split] if t.project == project]
            pairs = [(a, b) for k, a in enumerate(idx) for b in idx[k + 1 :]]
            vals = scorer.scores(pairs)
            S = np.eye(len(idx))
            pos = {x: k for k, x in enumerate(idx)}
            for (a, b), v in zip(pairs, vals):
                S[pos[a], pos[b]] = S[pos[b], pos[a]] = v
            out.append((idx, S))
        return out

    def cluster(self, fusion_best, text_by_track, action_by_track):
        chosen = {}
        for track in ("stdlib", "extras"):
            fname, _ap, fuser = fusion_best[track]
            mats = {
                s: self.project_matrices(
                    s,
                    self.build_scorer(
                        s, track, text_by_track[track], action_by_track[track], fuser
                    ),
                )
                for s in ("dev", "test")
            }
            for cname in REGISTRY["cluster"]:
                if track == "stdlib" and cname not in STDLIB_CLUSTER:
                    continue
                best = None
                try:
                    self._cluster_eval("dev", mats["dev"][:1], cname, 0.5)
                except Exception as exc:  # noqa: BLE001
                    print(f"cluster {cname} failed: {exc}")
                    self.log(stage="cluster", method=f"{cname}<{track}>", error=str(exc))
                    continue
                for theta in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
                    res = self._cluster_eval("dev", mats["dev"], cname, theta)
                    if best is None or res["bcubed_f1"] > best[1]["bcubed_f1"]:
                        best = (theta, res)
                    if cname == "kmeans_reference":
                        break
                theta = best[0]
                test = self._cluster_eval("test", mats["test"], cname, theta)
                self.log(
                    stage="cluster",
                    method=f"{cname}<{track}>",
                    track=track,
                    theta=theta,
                    fusion=fname,
                    dev=best[1],
                    test=test,
                )
                print(
                    f"cluster    {cname + '<' + track + '>':40s} theta {theta}  dev B3-F1 {best[1]['bcubed_f1']}  "
                    f"test B3-F1 {test['bcubed_f1']}  ARI {test['ari']}  one-offs alone {test['oneoffs_left_alone']}"
                )
                chosen.setdefault(track, {})[cname] = (theta, test)
        return chosen

    def _cluster_eval(self, split, mats, cname, theta):
        turns = self.turns[split]
        labels_true, labels_pred, kinds = [], [], []
        offset = 0
        for idx, S in mats:
            kw = {}
            if cname == "kmeans_reference":
                kw["k"] = (
                    sum(1 for c in Counter(turns[i].label for i in idx).values() if c >= 2) or 2
                )
            clusterer = make("cluster", cname, theta=theta, **kw)
            order = sorted(range(len(idx)), key=lambda k: turns[idx[k]].ts)
            labels = clusterer.cluster(S, order)
            labels_pred += [int(x) + offset if x >= 0 else -1 for x in labels]
            offset += (max(labels) + 1) if len(labels) and max(labels) >= 0 else 0
            labels_true += [turns[i].label for i in idx]
            kinds += [turns[i].kind for i in idx]
        return M.clustering(labels_true, labels_pred, kinds)

    # --- stage: replay -------------------------------------------------------------------
    def replay(
        self,
        fusion_best,
        text_by_track,
        action_by_track,
        batch_names=("hdbscan", "agglomerative_average"),
    ):
        from .replay import replay_runtime, replay_sim

        for split in ("dev", "test"):
            res = replay_runtime(self.turns[split])
            self.log(
                stage="replay",
                method="runtime<baseline>",
                track="stdlib",
                split=split,
                **res["metrics"],
            )
            print(f"replay     runtime<baseline> {split}: {res['metrics']}")
        for track in ("stdlib", "extras"):
            fname, _ap, fuser = fusion_best[track]
            scorers = {
                s: self.build_scorer(s, track, text_by_track[track], action_by_track[track], fuser)
                for s in ("dev", "test")
            }
            grid = []
            for theta in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
                m = replay_sim(self.dev, scorers["dev"], theta)["metrics"]
                grid.append((theta, m))
            ok = [g for g in grid if (g[1]["precision"] or 0) >= 0.9] or grid
            theta = max(ok, key=lambda g: (g[1]["recall"] or 0, g[1]["precision"] or 0))[0]
            for split in ("dev", "test"):
                m = replay_sim(self.turns[split], scorers[split], theta)["metrics"]
                self.log(
                    stage="replay",
                    method=f"sim:{fname}+leader<{track}>",
                    track=track,
                    split=split,
                    theta=theta,
                    dev_grid=[(t, g["precision"], g["recall"]) for t, g in grid],
                    **m,
                )
                print(f"replay     sim:{fname}+leader<{track}> {split} theta {theta}: {m}")
            if track == "extras":
                for cname in batch_names:
                    for split in ("dev", "test"):
                        clusterer = make("cluster", cname, theta=theta)
                        m = replay_sim(
                            self.turns[split], scorers[split], theta, batch_clusterer=clusterer
                        )["metrics"]
                        self.log(
                            stage="replay",
                            method=f"batch:{fname}+leader+{cname}<{track}>",
                            track=track,
                            split=split,
                            theta=theta,
                            **m,
                        )
                        print(f"replay     batch:{fname}+{cname}<{track}> {split}: {m}")


def pick_best(results: Dict[str, dict], allowed: set) -> str:
    candidates = {k: v for k, v in results.items() if k.split("[")[0] in allowed or k in allowed}
    return max(candidates, key=lambda k: candidates[k]["dev"]["pr_auc"] or 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", default="text,templating,actions,fusion")
    parser.add_argument("--reuse", action="store_true", help="load cached text/action scores")
    args = parser.parse_args()
    stages = args.stages.split(",")
    lab = Lab(reuse=args.reuse)
    print(
        f"dev: {len(lab.dev)} turns, {len(lab.pairs['dev'])} pairs; test: {len(lab.test)} turns, {len(lab.pairs['test'])} pairs"
    )
    text = lab.text() if "text" in stages else {}
    if "templating" in stages:
        lab.templating()
    acts = lab.actions() if "actions" in stages else {}
    if "fusion" in stages and text and acts:
        text_best = {"stdlib": pick_best(text, STDLIB_TEXT), "extras": pick_best(text, set(text))}
        act_best = {
            "stdlib": pick_best(
                {k: v for k, v in acts.items() if k.endswith("[hand]")}, STDLIB_ACTIONS
            ),
            "extras": pick_best(acts, {k.split("[")[0] for k in acts}),
        }
        print("best text:", text_best, "best actions:", act_best)
        best = lab.fusion(text_best, act_best)
        lab.log(
            stage="selection_inputs",
            text=text_best,
            actions=act_best,
            fusion={k: v[0] for k, v in best.items()},
        )
        if "cluster" in stages:
            lab.cluster(best, text_best, act_best)
        if "replay" in stages:
            lab.replay(best, text_best, act_best)


if __name__ == "__main__":
    main()
