"""Method interfaces (SPEC 11.6) and the registry.

A *representation* turns turns into features and scores pairs in [0, 1]:

    class Representer(Protocol):
        name: str
        def fit(self, turns: list[Turn]) -> None: ...
        def pair_scores(self, turns, pairs) -> np.ndarray: ...   # one score per pair

A *clusterer* assigns cluster ids (-1 = noise / one-off) from a pairwise scorer.
Methods register themselves by category so ``bench.run`` can enumerate them.
"""

from __future__ import annotations

from typing import Callable, Dict, List

REGISTRY: Dict[str, Dict[str, Callable]] = {}


def register(category: str, name: str):
    def wrap(factory):
        REGISTRY.setdefault(category, {})[name] = factory
        factory.method_name = name
        return factory

    return wrap


def names(category: str) -> List[str]:
    return list(REGISTRY.get(category, {}))


def make(category: str, name: str, **kwargs):
    return REGISTRY[category][name](**kwargs)
