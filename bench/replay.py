"""Replay a split chronologically and measure suggestions (SPEC 11.6–11.7).

Modes:
  runtime  drive the real hook pipeline (skill_spotter.hookrunner) with the clock set to
           each turn's timestamp: the authoritative product numbers for what ships.
  sim      online leader clustering with any pairwise scorer, plus the runtime trigger rule.
  batch    sim, plus a background job every N turns that re-clusters with a batch
           clusterer and marks crossing clusters ready (the two-tier runtime, SPEC 5.5).

A suggestion is correct when, at that moment, at least 2/3 of the pattern's members share
one repeated-task family and at least 3 of them are that family. Recall counts families
that became eligible (3+ times within 30 days, 2+ sessions) and got a correct suggestion.

    .venv/bin/python -m bench.replay --mode runtime --split test [--quick]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from . import data as D

DAY = 86400.0
WINDOW = 30 * DAY


# --- ground truth ----------------------------------------------------------------------


def eligible_families(turns: List[D.Turn], min_count=3, min_sessions=2) -> Dict[str, float]:
    """family -> time it first became eligible for a suggestion."""
    occ = defaultdict(list)
    for t in turns:
        if t.kind == "positive":
            occ[t.family].append(t)
    out = {}
    for fam, items in occ.items():
        items.sort(key=lambda t: t.ts)
        for k in range(len(items)):
            window = [x for x in items[: k + 1] if items[k].ts - x.ts <= WINDOW]
            if len(window) >= min_count and len({x.session for x in window}) >= min_sessions:
                out[fam] = items[k].ts
                break
    return out


def judge(members: List[D.Turn]) -> Optional[str]:
    """The family a suggestion correctly stands for, or None."""
    fams = Counter(m.family for m in members if m.kind == "positive")
    if not fams:
        return None
    fam, n = fams.most_common(1)[0]
    return fam if n >= 3 and n / len(members) >= 2 / 3 else None


def summarize(turns, suggestions, seconds) -> Dict[str, float]:
    eligible = eligible_families(turns)
    correct = [s for s in suggestions if s["family"]]
    found = {s["family"] for s in correct if s["family"] in eligible}
    duplicates = len(correct) - len({s["family"] for s in correct})
    occurrences = [s["occurrence"] for s in correct]
    return {
        "turns": len(turns),
        "suggestions": len(suggestions),
        "correct": len(correct),
        "precision": round(len(correct) / len(suggestions), 4) if suggestions else None,
        "eligible_families": len(eligible),
        "recall": round(len(found) / len(eligible), 4) if eligible else None,
        "median_occurrences_before_first": statistics.median(occurrences) if occurrences else None,
        "false_per_100_turns": round(
            100 * (len(suggestions) - len(correct)) / max(1, len(turns)), 3
        ),
        "duplicate_suggestions": duplicates,
        **_fragmentation(correct),
        "seconds": round(seconds, 1),
    }


def _fragmentation(correct) -> Dict[str, int]:
    """Split duplicates: the same pattern suggested again after a snooze (by design) vs
    a second pattern for an already suggested family (the matcher split the task)."""
    if not correct or "pattern" not in correct[0]:
        return {}
    by_fam = defaultdict(list)
    for s in correct:
        by_fam[s["family"]].append(s["pattern"])
    return {
        "resuggested_after_snooze": sum(len(p) - len(set(p)) for p in by_fam.values()),
        "extra_patterns_per_family": sum(len(set(p)) - 1 for p in by_fam.values()),
    }


def _occurrence(turns_so_far: List[D.Turn], family: Optional[str]) -> int:
    return sum(1 for t in turns_so_far if t.family == family and t.kind == "positive")


# --- runtime mode ------------------------------------------------------------------------


def replay_runtime(turns: List[D.Turn], settings: Optional[Dict[str, str]] = None) -> Dict:
    """Feed every turn through the real hooks; returns metrics and the suggestion log."""
    from skill_spotter import band, clock, hookrunner, paths, store

    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        old_env = os.environ.get("SKILL_SPOTTER_DATA")
        os.environ["SKILL_SPOTTER_DATA"] = tmp
        real_now = clock.now
        current = {"t": 0.0}
        clock.now = lambda: current["t"]
        try:
            if settings:
                conn = store.connect(paths.db_path(paths.data_dir()))
                for k, v in settings.items():
                    store.set_setting(conn, k, v)
                conn.close()
            by_id = {t.item_id: t for t in turns}
            last_in_session = {}
            for t in turns:
                last_in_session[t.session] = t.idx
            suggestions = []
            seen: List[D.Turn] = []

            def send(event, **fields):
                out = io.StringIO()
                hookrunner.run(
                    event,
                    stdin=io.StringIO(json.dumps({"hook_event_name": event, **fields})),
                    stdout=out,
                )
                return out.getvalue()

            for t in turns:
                current["t"] = t.ts
                base = {"session_id": t.session, "cwd": t.root, "prompt_id": t.item_id}
                send("UserPromptSubmit", prompt=t.prompt, **base)
                for k, a in enumerate(t.actions):
                    current["t"] = t.ts + 1 + k
                    send(
                        "PostToolUseFailure" if a.get("failed") else "PostToolUse",
                        tool_name=a["tool"],
                        tool_input=a.get("input") or {},
                        tool_use_id=f"{t.item_id}-{k}",
                        agent_id=a.get("agent_id"),
                        **base,
                    )
                current["t"] = t.ts + 2 + len(t.actions)
                out = send("Stop", session_crons=[], **base)
                seen.append(t)
                if out:
                    msg = json.loads(out)["systemMessage"]
                    pid = int(band.parse(msg)["id"][1:])
                    conn = store.connect(paths.db_path(paths.data_dir()))
                    member_ids = [
                        r[0]
                        for r in conn.execute(
                            "SELECT prompt_id FROM turns WHERE pattern_id = ?", (pid,)
                        )
                    ]
                    conn.close()
                    members = [by_id[m] for m in member_ids if m in by_id]
                    fam = judge(members)
                    suggestions.append(
                        {
                            "at": t.item_id,
                            "pattern": pid,
                            "family": fam,
                            "size": len(members),
                            "occurrence": _occurrence(seen, fam),
                            "message": msg,
                            "members": [m.item_id for m in members],
                        }
                    )
                if last_in_session[t.session] == t.idx:
                    send("SessionEnd", reason="other", session_id=t.session, cwd=t.root)
        finally:
            clock.now = real_now
            if old_env is None:
                os.environ.pop("SKILL_SPOTTER_DATA", None)
            else:
                os.environ["SKILL_SPOTTER_DATA"] = old_env
    return {
        "metrics": summarize(turns, suggestions, time.time() - started),
        "suggestions": suggestions,
    }


# --- sim / batch modes ---------------------------------------------------------------------


class PairScorer:
    """Fused same-task probability for arbitrary turn pairs, from fitted representations."""

    def __init__(self, turns, text_rep, action_rep, fuser, seq_rep, file_rep, hand):
        from .methods import actions as A

        self.turns, self.text, self.action, self.fuser = turns, text_rep, action_rep, fuser
        self.seq, self.files = seq_rep, file_rep
        self.n = [A.n_meaningful(t, hand) for t in turns]
        self.cache: Dict[tuple, float] = {}

    def scores(self, pairs):
        import numpy as np

        todo = [p for p in pairs if p not in self.cache]
        if todo:
            ps = [(i, j, 0, "") for i, j in todo]
            i = np.array([p[0] for p in todo])
            j = np.array([p[1] for p in todo])
            n = np.array(self.n)
            sess = np.array([t.session for t in self.turns])
            ts = np.array([t.ts for t in self.turns])
            cols = {
                "text": self.text.pair_scores(self.turns, ps),
                "action": self.action.pair_scores(self.turns, ps),
                "seq": self.seq.pair_scores(self.turns, ps),
                "files": self.files.pair_scores(self.turns, ps),
                "n_min": np.minimum(n[i], n[j]),
                "n_max": np.maximum(n[i], n[j]),
                "same_session": (sess[i] == sess[j]).astype(float),
                "log_gap_days": np.log1p(np.abs(ts[i] - ts[j]) / DAY),
            }
            preds = self.fuser.predict(cols)
            # Same text-only path as the runtime scorer (match/fused.py)
            from skill_spotter.capture import normalize_text as nt

            for k, (a, b) in enumerate(todo):
                if min(self.n[a], self.n[b]) < 2:
                    ga = nt.ngrams(nt.normalize(self.turns[a].prompt))
                    gb = nt.ngrams(nt.normalize(self.turns[b].prompt))
                    if nt.jaccard(ga, gb) >= 0.6:
                        preds[k] = 0.99
            for p, s in zip(todo, preds):
                self.cache[p] = float(s)
        return [self.cache[p] for p in pairs]


def _candidate_keys(turn, hand_fp, text_tokens):
    keys = {k for k, w in hand_fp.items() if w >= 0.25}
    keys |= {f"txt:{w}" for w in text_tokens}
    return keys


def replay_sim(
    turns,
    scorer: PairScorer,
    theta: float,
    batch_clusterer=None,
    every: int = 50,
    min_count=3,
    min_sessions=2,
    max_candidates: int = 20,
    members_per_pattern: int = 10,
) -> Dict:
    from skill_spotter.capture import normalize_text as nt
    from skill_spotter.capture.normalize_actions import normalize_action, turn_fingerprint

    started = time.time()
    fps = [
        turn_fingerprint(
            [
                normalize_action(
                    a["tool"], a.get("input") or {}, t.root, failed=bool(a.get("failed"))
                )
                for a in t.actions
            ]
        )
        for t in turns
    ]
    toks = [set(nt.normalize(t.prompt)) for t in turns]
    patterns: List[List[int]] = []
    pattern_of: Dict[int, int] = {}
    index: Dict[tuple, set] = defaultdict(set)  # (project, key) -> pattern ids
    suggested_sets: List[set] = []
    suggested_ids: Dict[str, List[int]] = {}
    state = {}  # pattern -> suggested?
    session_suggested, day_count = set(), Counter()
    ready: Dict[str, List[set]] = defaultdict(list)
    suggestions, seen = [], []

    def crosses(members, now):
        recent = [m for m in members if now - turns[m].ts <= WINDOW]
        return len(recent) >= min_count and len({turns[m].session for m in recent}) >= min_sessions

    def generic(members):
        return (
            all(
                not any(w >= 0.5 and not k.startswith("seq:") for k, w in fps[m].items())
                for m in members
            )
            and len(set.intersection(*[toks[m] for m in members])) < 2
        )

    def can_suggest(t):
        day = int(t.ts // DAY)
        return t.session not in session_suggested and day_count[day] < 3

    def do_suggest(t, members):
        session_suggested.add(t.session)
        day_count[int(t.ts // DAY)] += 1
        fam = judge([turns[m] for m in members])
        suggestions.append(
            {
                "at": t.item_id,
                "family": fam,
                "size": len(members),
                "occurrence": _occurrence(seen, fam),
                "members": [turns[m].item_id for m in members],
            }
        )

    for step, t in enumerate(turns):
        seen.append(t)
        keys = _candidate_keys(t, fps[t.idx], toks[t.idx])
        cand = set()
        for k in keys:
            cand |= index[(t.project, k)]
        cand = [c for c in cand if t.ts - turns[patterns[c][-1]].ts <= WINDOW]
        if len(cand) > max_candidates:  # same cap as the runtime: most shared keys first
            keep = set(cand)
            hits = Counter(c for k in keys for c in index[(t.project, k)] if c in keep)
            cand = [c for c, _ in hits.most_common(max_candidates)]
        best, best_s = None, -1.0
        if cand:
            pairs = [(t.idx, m) for c in cand for m in patterns[c][-members_per_pattern:]]
            s = scorer.scores(pairs)
            k = 0
            for c in cand:
                m = len(patterns[c][-members_per_pattern:])
                mean = sum(s[k : k + m]) / m
                k += m
                if mean > best_s:
                    best, best_s = c, mean
        if best is not None and best_s >= theta:
            patterns[best].append(t.idx)
            pid = best
        else:
            patterns.append([t.idx])
            pid = len(patterns) - 1
        pattern_of[t.idx] = pid
        for k in keys:
            index[(t.project, k)].add(pid)
        # online trigger
        members = patterns[pid]
        if (
            not state.get(pid)
            and crosses(members, t.ts)
            and not generic(members)
            and can_suggest(t)
        ):
            twin = None
            for q in suggested_ids.get(t.project, []):
                pairs = [(a, b) for a in members[-5:] for b in patterns[q][-5:]]
                if pairs and sum(scorer.scores(pairs)) / len(pairs) >= theta:
                    twin = q
                    break
            if twin is not None:  # same as the runtime: fold into the pattern already shown
                patterns[twin].extend(members)
                state[pid] = True
            else:
                state[pid] = True
                suggested_sets.append(set(members))
                suggested_ids.setdefault(t.project, []).append(pid)
                do_suggest(t, members)
        # background tier: re-cluster, mark crossing clusters ready, show at next turn end
        if batch_clusterer is not None:
            if ready[t.project] and can_suggest(t):
                members = sorted(ready[t.project].pop(0))
                do_suggest(t, members)
            if step and step % every == 0:
                import numpy as np

                for project in {x.project for x in seen}:
                    idx = [x.idx for x in seen if x.project == project and t.ts - x.ts <= WINDOW]
                    if len(idx) < 3:
                        continue
                    pairs = [(a, b) for a in idx for b in idx if a < b]
                    vals = scorer.scores(pairs)
                    S = np.eye(len(idx))
                    pos = {x: k for k, x in enumerate(idx)}
                    for (a, b), v in zip(pairs, vals):
                        S[pos[a], pos[b]] = S[pos[b], pos[a]] = v
                    labels = batch_clusterer.cluster(S, list(range(len(idx))))
                    for c in set(labels) - {-1}:
                        members = {idx[k] for k in np.where(labels == c)[0]}
                        if not crosses(members, t.ts) or generic(members):
                            continue
                        if any(
                            len(members & prev) / len(members) >= 0.5 for prev in suggested_sets
                        ):
                            continue
                        suggested_sets.append(members)
                        ready[project].append(members)
    return {
        "metrics": summarize(turns, suggestions, time.time() - started),
        "suggestions": suggestions,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="runtime", choices=["runtime"])
    parser.add_argument("--split", default="test")
    parser.add_argument("--quick", action="store_true", help="first 3 projects only (CI)")
    parser.add_argument("--min-precision", type=float, default=None, help="exit 1 below this (CI)")
    parser.add_argument("--min-recall", type=float, default=None, help="exit 1 below this (CI)")
    args = parser.parse_args()
    turns = D.load(args.split)
    if args.quick:
        keep = sorted({t.project for t in turns})[:3]
        turns = [t for t in turns if t.project in keep]
        for k, t in enumerate(turns):
            t.idx = k
    result = replay_runtime(turns)
    m = result["metrics"]
    print(json.dumps(m, indent=2))
    if args.min_precision is not None and (m["precision"] or 0) < args.min_precision:
        raise SystemExit(f"replay precision {m['precision']} < {args.min_precision}")
    if args.min_recall is not None and (m["recall"] or 0) < args.min_recall:
        raise SystemExit(f"replay recall {m['recall']} < {args.min_recall}")
    return result


if __name__ == "__main__":
    main()
