"""Pure computations behind a map snapshot. No database, no model calls.

Clustering: UMAP to 10 dimensions (cosine), then k-means. ``k`` is chosen
from a range by silhouette in the UMAP space. A separate 2-d UMAP fit gives
display coordinates only; nothing is computed from them except the density
shading, which is labelled as such.

Honesty about the result, as learned in Parallax:

- Silhouette is reported in both spaces. UMAP separates clusters that
  overlap heavily in the original embedding space (Parallax: 0.40 vs 0.067;
  the server on the same 7,113-observation library at k=14: 0.46 vs 0.046).
- The null is a structure-free dataset (each embedding dimension permuted
  independently across rows, so marginals survive and covariance does not),
  clustered the same way. A label-shuffle null is too easy to beat to mean
  anything. The null is checked in tests to fail on data with no structure.
- Identity across snapshots uses centroids in the original space. UMAP
  coordinates move whenever the input changes by a single row.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

SEED = 42
UMAP_DIMS = 10
UMAP_NEIGHBORS = 15
MIN_OBSERVATIONS = 30
LINEAGE_MAX_DISTANCE = 0.15
CROSS_SOURCE_MAX_SHARE = 0.70
CROSS_SOURCE_MIN_SIZE = 10  # below this, "several sources" is sampling noise
NULL_REPS = 5
# A second null keeps the library's mean and covariance but has no clusters: a
# single Gaussian blob. The column-permutation null destroys covariance, so any
# correlated embedding set beats it; against this one, the Parallax library
# scored z about 2.9, not 24. Below this z the map says its clusters may
# be cuts through one continuous cloud.
COVARIANCE_NULL_MIN_Z = 2.0
# k is chosen among the TOP_K_CANDIDATES best silhouettes, preferring one whose
# clusters survive re-clustering an 80% subsample (mean adjusted Rand index).
TOP_K_CANDIDATES = 3
STABILITY_SUBSAMPLES = 5
STABILITY_FRACTION = 0.8
STABLE_ARI = 0.75
SILHOUETTE_SAMPLE = 2000
DENSITY_GRID = 96

# Words the judge prompt pushes into every summary. Parallax's cluster
# keywords were dominated by them ("specific", "concrete", "signal"), which
# describes the prompt, not the cluster.
PROMPT_VOCABULARY = frozenset("""
    post posts user users author describes described shares shared reports reported
    discusses discussed mentions mentioned claims claimed notes noted says said asks asked
    specific concrete concretely detail details detailed signal signals observation
    observations item items suggests suggesting indicates indicating shows showing
    evidence example examples approach approaches pattern patterns rather including
    matters matter worth significant particularly potentially potential likely
    real actual actually generally broader across specific without also well one two
    argues argue argued arguing proposes proposed proposing highlights highlighted
""".split())  # noqa: SIM905 - a word list reads better as text


def fingerprint(ids: list[int], model: str) -> str:
    h = hashlib.sha256(model.encode())
    for i in sorted(ids):
        h.update(f",{i}".encode())
    return h.hexdigest()


def k_range(n: int) -> tuple[int, int]:
    """Candidate cluster counts for ``n`` observations."""
    hi = max(4, min(24, int(math.sqrt(n / 2))))
    lo = max(2, min(4, n // MIN_OBSERVATIONS))
    return lo, max(lo, hi)


def _umap(x: np.ndarray, dims: int, min_dist: float) -> np.ndarray:
    import umap

    reducer = umap.UMAP(
        n_components=dims,
        n_neighbors=min(UMAP_NEIGHBORS, len(x) - 1),
        metric="cosine",
        min_dist=min_dist,
        random_state=SEED,
        n_jobs=1,
    )
    return reducer.fit_transform(x).astype(np.float32)


def _silhouette(x: np.ndarray, labels: np.ndarray, metric: str) -> float:
    from sklearn.metrics import silhouette_score

    if len(set(labels.tolist())) < 2:
        return 0.0
    sample = min(SILHOUETTE_SAMPLE, len(x))
    return float(silhouette_score(x, labels, metric=metric, sample_size=sample,
                                  random_state=SEED))


def _kmeans(x: np.ndarray, k: int, n_init: int = 10) -> np.ndarray:
    from sklearn.cluster import KMeans

    return KMeans(k, n_init=n_init, random_state=SEED).fit_predict(x)


def structure_null(x: np.ndarray, k: int, reps: int = NULL_REPS) -> dict:
    """Silhouette of k-means on structure-free versions of ``x``, vs the real data."""
    rng = np.random.default_rng(SEED)
    values = []
    for _ in range(reps):
        null = np.column_stack([rng.permutation(x[:, j]) for j in range(x.shape[1])])
        null /= np.linalg.norm(null, axis=1, keepdims=True) + 1e-12
        values.append(_silhouette(null, _kmeans(null, k, n_init=4), "cosine"))
    real = _silhouette(x, _kmeans(x, k, n_init=4), "cosine")
    mean, sd = float(np.mean(values)), float(np.std(values))
    cov_mean, cov_sd = _covariance_null(x, k, reps, rng)
    cov_z = round((real - cov_mean) / cov_sd, 1) if cov_sd > 0 else None
    return {
        "method": "k-means on column-permuted embeddings (native space, cosine)",
        "reps": reps,
        "null_mean": round(mean, 5),
        "null_sd": round(sd, 5),
        "real": round(real, 5),
        "z": round((real - mean) / sd, 1) if sd > 0 else None,
        "covariance_method": "k-means on one Gaussian with the library's mean and covariance",
        "covariance_null_mean": round(cov_mean, 5),
        "covariance_null_sd": round(cov_sd, 5),
        "covariance_z": cov_z,
        "clustered": cov_z is not None and cov_z >= COVARIANCE_NULL_MIN_Z,
    }


def _covariance_null(x: np.ndarray, k: int, reps: int, rng) -> tuple[float, float]:
    """Silhouette of k-means on samples from one Gaussian shaped like ``x``."""
    mean = x.mean(axis=0)
    eigvals, eigvecs = np.linalg.eigh(np.cov(x, rowvar=False))
    scale = eigvecs * np.sqrt(np.clip(eigvals, 0, None))  # decomposed once, not per sample
    values = []
    for _ in range(reps):
        blob = mean + rng.standard_normal((len(x), len(mean))) @ scale.T
        blob /= np.linalg.norm(blob, axis=1, keepdims=True) + 1e-12
        values.append(_silhouette(blob, _kmeans(blob, k, n_init=4), "cosine"))
    return float(np.mean(values)), float(np.std(values))


def _stability(reduced: np.ndarray, labels: np.ndarray, k: int) -> float:
    """Mean adjusted Rand index between ``labels`` and k-means on 80% subsamples."""
    from sklearn.metrics import adjusted_rand_score

    rng = np.random.default_rng(SEED)
    n = len(reduced)
    scores = []
    for _ in range(STABILITY_SUBSAMPLES):
        idx = rng.choice(n, size=max(k + 1, int(n * STABILITY_FRACTION)), replace=False)
        scores.append(adjusted_rand_score(labels[idx], _kmeans(reduced[idx], k, n_init=4)))
    return float(np.mean(scores))


@dataclass
class Clustering:
    labels: np.ndarray
    coords: np.ndarray  # 2-d display coordinates, scaled to [0, 1]
    k: int
    quality: dict
    params: dict


@dataclass
class KSelection:
    reduced: np.ndarray  # the 10-d UMAP embedding k was chosen in
    lo: int
    hi: int
    by_k: dict  # k -> (silhouette in UMAP space, labels)
    stability: dict  # k -> mean ARI, for the best few
    k: int


def select_k(x: np.ndarray, hi_cap: int | None = None) -> KSelection:
    """Choose k: UMAP to 10 dimensions, k-means over ``k_range``, then the best
    silhouettes preferring one stable under subsampling. ``hi_cap`` clamps the
    range for small groups (compaction)."""
    n = len(x)
    reduced = _umap(x, UMAP_DIMS, min_dist=0.0)
    lo, hi = k_range(n)
    if hi_cap is not None:
        hi = max(2, min(hi, hi_cap))
        lo = min(lo, hi)
    by_k = {}
    for k in range(lo, hi + 1):
        by_k[k] = (_silhouette(reduced, labels := _kmeans(reduced, k), "euclidean"), labels)
    # Silhouette alone was nearly flat over k on some libraries and landed on the
    # ends of the range; among the best few, prefer one that is stable.
    ranked = sorted(by_k, key=lambda k: (-round(by_k[k][0], 4), k))[:TOP_K_CANDIDATES]
    stability = {k: round(_stability(reduced, by_k[k][1], k), 3) for k in ranked}
    stable = [k for k in ranked if stability[k] >= STABLE_ARI]
    best_k = stable[0] if stable else max(ranked, key=lambda k: stability[k])
    return KSelection(reduced, lo, hi, by_k, stability, best_k)


def cluster(x: np.ndarray) -> Clustering:
    n = len(x)
    if n < MIN_OBSERVATIONS:
        raise ValueError(f"need at least {MIN_OBSERVATIONS} observations to map, have {n}")
    sel = select_k(x)
    lo, hi, by_k, stability, best_k = sel.lo, sel.hi, sel.by_k, sel.stability, sel.k
    labels = by_k[best_k][1]
    coords = display_scale(_umap(x, 2, min_dist=0.1))
    quality = {
        "k_range": [lo, hi],
        "silhouette_by_k": {str(k): round(v[0], 4) for k, v in by_k.items()},
        "silhouette_umap": round(by_k[best_k][0], 4),
        "stability_by_k": {str(k): v for k, v in stability.items()},
        "silhouette_native": round(_silhouette(x, labels, "cosine"), 4),
        "structure_null": structure_null(x, best_k),
    }
    params = {
        "technique": "umap+kmeans",
        "umap": {"n_components": UMAP_DIMS, "n_neighbors": min(UMAP_NEIGHBORS, n - 1),
                 "metric": "cosine", "min_dist": 0.0, "random_state": SEED},
        "display_umap": {"n_components": 2, "min_dist": 0.1, "random_state": SEED},
        "kmeans": {"n_init": 10, "random_state": SEED},
        "k_selection": (f"of the {TOP_K_CANDIDATES} best silhouettes in UMAP space, the best "
                        f"with subsample stability (ARI) >= {STABLE_ARI}, else the most stable"),
    }
    return Clustering(labels.astype(int), coords.astype(np.float32), best_k, quality, params)


def display_scale(coords: np.ndarray) -> np.ndarray:
    """Scale so the 1st-99th percentile box maps to [0, 1].

    Min-max scaling lets a handful of outlying points squash everything else
    into a corner. Points beyond the box keep their true relative position and
    are simply off the initial frame; nothing is clamped or hidden.
    """
    lo = np.percentile(coords, 1, axis=0)
    hi = np.percentile(coords, 99, axis=0)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    return ((coords - lo) / span).astype(np.float32)


def centroids(x: np.ndarray, labels: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros((k, x.shape[1]), dtype=np.float32)
    for c in range(k):
        mean = x[labels == c].mean(axis=0)
        out[c] = mean / (np.linalg.norm(mean) or 1.0)
    return out


def match_lineages(
    current: np.ndarray, previous: np.ndarray, max_distance: float = LINEAGE_MAX_DISTANCE
) -> dict[int, int]:
    """Greedy one-to-one match of current to previous centroids (cosine distance).

    Returns {current index: previous index}. Unmatched current clusters start
    new lineages; unmatched previous ones end. Splits and merges therefore show
    up as an ending plus a beginning, never as a silently continued identity.
    """
    if len(current) == 0 or len(previous) == 0:
        return {}
    distance = 1.0 - current @ previous.T
    pairs = sorted(
        (float(distance[i, j]), i, j)
        for i in range(len(current)) for j in range(len(previous))
        if distance[i, j] <= max_distance
    )
    used_i, used_j, out = set(), set(), {}
    for _, i, j in pairs:
        if i not in used_i and j not in used_j:
            out[i] = j
            used_i.add(i)
            used_j.add(j)
    return out


def platform(label: str) -> str:
    """The platform a source label belongs to: every subreddit is one Reddit, every
    HN feed or query one Hacker News; any other source is its own."""
    low = label.lower()
    if low.startswith(("r/", "reddit")):
        return "reddit"
    if low.startswith(("hn ", "hn:", "hn search", "hackernews", "hacker news")):
        return "hacker news"
    return label


def source_mix(sources: list[str], origins: list[str | None] | None = None,
               ) -> tuple[dict[str, int], float, bool]:
    """Counts per source, the largest source's share, and whether the cluster is
    cross-source: no single source, and no single platform, above 70% (#45: 8 of 9
    cross-source clusters in the Parallax library were 78-93% Reddit, spread over
    subreddits), and, when ``origins`` are given (one per entry, None when
    unknown), no single origin above 70% either (#35: a vendor's blog, docs and
    changelog are one voice however many sources carry them)."""
    counts: dict[str, int] = {}
    platforms: dict[str, int] = {}
    for s in sources:
        counts[s] = counts.get(s, 0) + 1
        platforms[platform(s)] = platforms.get(platform(s), 0) + 1
    total = sum(counts.values()) or 1
    max_share = max(counts.values(), default=0) / total
    max_platform = max(platforms.values(), default=0) / total
    max_origin = max(Counter(o for o in origins or () if o).values(), default=0) / total
    cross = (len(counts) >= 2 and max_share <= CROSS_SOURCE_MAX_SHARE
             and max_platform <= CROSS_SOURCE_MAX_SHARE and max_origin <= CROSS_SOURCE_MAX_SHARE
             and total >= CROSS_SOURCE_MIN_SIZE)
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return ordered, round(max_share, 4), cross


# Words may contain . + # - inside ("claude.md", "c++", "gpt-4o") but not end in . or -.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+.#-]*[A-Za-z0-9+#]")


def keywords(texts_by_cluster: list[list[str]], top: int = 8) -> list[list[str]]:
    """Distinctive terms per cluster: TF-IDF over one document per cluster."""
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

    docs = [" ".join(texts) for texts in texts_by_cluster]
    if not any(d.strip() for d in docs):
        return [[] for _ in docs]
    stop = sorted(set(ENGLISH_STOP_WORDS) | PROMPT_VOCABULARY)
    vec = TfidfVectorizer(
        stop_words=stop, ngram_range=(1, 2), max_df=0.6 if len(docs) > 2 else 1.0,
        min_df=1, sublinear_tf=True, token_pattern=_WORD.pattern, lowercase=True,
    )
    try:
        matrix = vec.fit_transform(docs)
    except ValueError:
        return [[] for _ in docs]
    terms = np.array(vec.get_feature_names_out())
    out = []
    for row in range(matrix.shape[0]):
        weights = matrix[row].toarray().ravel()
        order = sorted(range(len(terms)), key=lambda i: (-weights[i], terms[i]))
        chosen: list[str] = []
        for i in order:
            if weights[i] <= 0 or len(chosen) >= top:
                break
            term = terms[i]
            if any(term in c or c in term for c in chosen):
                continue
            chosen.append(term)
        out.append(chosen)
    return out


def density_grid(coords: np.ndarray, size: int = DENSITY_GRID) -> list[list[float]]:
    """Gaussian KDE of the 2-d display coordinates on a size x size grid, max = 1.

    This is a smoothed histogram of where points sit in the display projection.
    It is not a spectrum and says nothing the points themselves do not.
    """
    n = len(coords)
    grid = np.zeros((size, size), dtype=np.float64)
    if n == 0:
        return grid.tolist()
    coords = coords[(coords >= 0).all(axis=1) & (coords <= 1).all(axis=1)]
    n = len(coords)
    if n == 0:
        return grid.tolist()
    bandwidth = max(1.06 * float(coords.std()) * n ** (-1 / 5), 0.01)
    axis = (np.arange(size) + 0.5) / size
    for lo in range(0, n, 2048):
        chunk = coords[lo:lo + 2048]
        gx = np.exp(-((axis[None, :] - chunk[:, 0:1]) ** 2) / (2 * bandwidth ** 2))
        gy = np.exp(-((axis[None, :] - chunk[:, 1:2]) ** 2) / (2 * bandwidth ** 2))
        grid += gy.T @ gx
    grid /= grid.max() or 1.0
    return np.round(grid, 4).tolist()


def representatives(x: np.ndarray, labels: np.ndarray, centers: np.ndarray, ids: np.ndarray,
                    per_cluster: int = 5) -> list[list[int]]:
    """Observations nearest each centroid in the original space (not the 2-d display)."""
    out = []
    for c in range(len(centers)):
        members = np.nonzero(labels == c)[0]
        order = members[np.argsort(-(x[members] @ centers[c]))][:per_cluster]
        out.append([int(ids[i]) for i in order])
    return out
