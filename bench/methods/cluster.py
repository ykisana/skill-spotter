"""Clustering candidates (SPEC 11.2, clustering row).

All clusterers work per project on a precomputed same-task score matrix S (n x n, in
[0, 1]); ``theta`` is the score threshold that counts as "same task". Output: one cluster
id per turn, -1 for noise (a one-off). Singletons are reported as noise too.
"""

from __future__ import annotations

from typing import List

import numpy as np

from .base import register


def _relabel(labels) -> np.ndarray:
    """Singletons -> -1; others renumbered from 0."""
    labels = np.asarray(labels)
    out = np.full(len(labels), -1)
    nxt = 0
    for value in np.unique(labels):
        if value < 0:
            continue
        members = np.where(labels == value)[0]
        if len(members) >= 2:
            out[members] = nxt
            nxt += 1
    return out


class Clusterer:
    name = "base"
    batch = True

    def __init__(self, theta: float = 0.5, **kw):
        self.theta = theta
        self.kw = kw

    def cluster(self, S: np.ndarray, order: List[int]) -> np.ndarray:
        raise NotImplementedError


@register("cluster", "leader")
class Leader(Clusterer):
    """Online baseline: in time order, join the cluster with the highest mean score to its
    (last 10) members if >= theta, else start a new cluster. Incremental by design."""

    name = "leader"
    batch = False

    def cluster(self, S, order):
        labels = np.full(len(S), -1)
        clusters: List[List[int]] = []
        for i in order:
            best, best_score = -1, -1.0
            for c, members in enumerate(clusters):
                s = float(np.mean(S[i, members[-10:]]))
                if s > best_score:
                    best, best_score = c, s
            if best >= 0 and best_score >= self.theta:
                clusters[best].append(i)
                labels[i] = best
            else:
                clusters.append([i])
                labels[i] = len(clusters) - 1
        return _relabel(labels)


@register("cluster", "components")
class Components(Clusterer):
    """Connected components of the graph of pairs scoring >= theta."""

    name = "components"

    def cluster(self, S, order):
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components

        A = csr_matrix((self.theta <= S) & ~np.eye(len(S), dtype=bool))
        _, labels = connected_components(A, directed=False)
        return _relabel(labels)


class _Agglo(Clusterer):
    linkage = "average"

    def cluster(self, S, order):
        from sklearn.cluster import AgglomerativeClustering

        if len(S) < 2:
            return np.full(len(S), -1)
        D = 1.0 - S
        np.fill_diagonal(D, 0.0)
        model = AgglomerativeClustering(
            n_clusters=None,
            metric="precomputed",
            linkage=self.linkage,
            distance_threshold=1.0 - self.theta,
        )
        return _relabel(model.fit_predict(D))


@register("cluster", "agglomerative_average")
class AggloAverage(_Agglo):
    name = "agglomerative_average"
    linkage = "average"


@register("cluster", "agglomerative_complete")
class AggloComplete(_Agglo):
    name = "agglomerative_complete"
    linkage = "complete"


@register("cluster", "dbscan")
class DBSCANCluster(Clusterer):
    name = "dbscan"

    def cluster(self, S, order):
        from sklearn.cluster import DBSCAN

        D = np.clip(1.0 - S, 0, 1)
        np.fill_diagonal(D, 0.0)
        return _relabel(
            DBSCAN(
                eps=1.0 - self.theta,
                min_samples=self.kw.get("min_samples", 2),
                metric="precomputed",
            ).fit_predict(D)
        )


@register("cluster", "hdbscan")
class HDBSCANCluster(Clusterer):
    """No preset cluster count; labels one-offs as noise."""

    name = "hdbscan"

    def cluster(self, S, order):
        from sklearn.cluster import HDBSCAN

        if len(S) < 3:
            return np.full(len(S), -1)
        D = np.clip(1.0 - S, 0, 1)
        np.fill_diagonal(D, 0.0)
        model = HDBSCAN(
            min_cluster_size=self.kw.get("min_cluster_size", 2),
            min_samples=self.kw.get("min_samples", 1),
            metric="precomputed",
            allow_single_cluster=False,
            # cluster_selection_epsilon crashes sklearn 1.9 with precomputed distances; HDBSCAN
            # picks clusters by density alone, so theta only applies through the scores.
        )
        labels = model.fit_predict(D)
        # drop clusters whose members aren't similar enough on average (theta)
        for c in set(labels) - {-1}:
            members = np.where(labels == c)[0]
            sub = S[np.ix_(members, members)]
            if (sub.sum() - len(members)) / max(1, len(members) * (len(members) - 1)) < self.theta:
                labels[members] = -1
        return _relabel(labels)


@register("cluster", "louvain")
class Louvain(Clusterer):
    """Louvain communities on the kNN graph (edges >= theta, top-k per node).
    (Leiden needs igraph/leidenalg; Louvain is its close stdlib-of-networkx relative.)"""

    name = "louvain"

    def cluster(self, S, order):
        import networkx as nx

        k = self.kw.get("k", 10)
        G = nx.Graph()
        G.add_nodes_from(range(len(S)))
        for i in range(len(S)):
            row = S[i].copy()
            row[i] = -1
            for j in np.argsort(-row)[:k]:
                if row[j] >= self.theta:
                    G.add_edge(i, int(j), weight=float(row[j]))
        labels = np.full(len(S), -1)
        for c, members in enumerate(nx.community.louvain_communities(G, weight="weight", seed=0)):
            for m in members:
                labels[m] = c
        return _relabel(labels)


@register("cluster", "kmeans_reference")
class KMeansReference(Clusterer):
    """Reference only: spectral embedding of S + k-means with k = true number of groups
    (which a real system never knows). Shows the ceiling of a k-given method."""

    name = "kmeans_reference"

    def cluster(self, S, order):
        from sklearn.cluster import KMeans
        from sklearn.manifold import spectral_embedding

        k = max(2, min(self.kw.get("k", 2), len(S) - 1))
        emb = spectral_embedding(
            np.clip(S, 0, 1) + 1e-6, n_components=min(16, len(S) - 1), random_state=0
        )
        return _relabel(KMeans(n_clusters=k, n_init=4, random_state=0).fit_predict(emb))
