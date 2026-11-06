"""Honest spatial and temporal splits.

The widest feature is a 450 m mean (9 coarse cells of 50 m). A check that sits
inside that window is not a new place: the training row and the test row share
the same context. KOZ-3 keeps a held-out site farther than the sensor footprint
and does not fit a threshold on the group it then reports. The same two rules
are used here.

`build()` no longer deletes background before the split. Each fold deletes
background only next to the presences on its own side. The 500 m ring is drawn
around test presences only, which is the presence-background rule in blockCV:
a test background point is not a reason to delete the neighbourhood.
Folds are a checkerboard of 5 km blocks, so adjacent blocks are not in the
same fold and the ring still separates their edges.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .samples import CLEAR_M

WINDOW_M = 450.0
# One extra 50 m cell so the two windows do not share a coarse cell.
PURGE_M = WINDOW_M + 50.0
BLOCK_M = 5000.0


def block_groups(xy: np.ndarray, block_m: float = BLOCK_M) -> np.ndarray:
    xy = np.asarray(xy, dtype=np.float64)
    return (xy[:, 0] // block_m).astype(np.int64) * 100003 + (xy[:, 1] // block_m).astype(np.int64)


def _farther_than(query_xy: np.ndarray, ref_xy: np.ndarray, dist_m: float) -> np.ndarray:
    """True where query is strictly farther than dist_m from every reference point."""
    if len(query_xy) == 0:
        return np.zeros(0, dtype=bool)
    if len(ref_xy) == 0:
        return np.ones(len(query_xy), dtype=bool)
    dist, _ = cKDTree(np.asarray(ref_xy, dtype=np.float64)).query(np.asarray(query_xy, dtype=np.float64), k=1)
    return dist > dist_m


def purge_train(xy: np.ndarray, train: np.ndarray, test: np.ndarray, purge_m: float = PURGE_M) -> np.ndarray:
    """Training indices that are outside the footprint of every test row."""
    train = np.asarray(train, dtype=int)
    test = np.asarray(test, dtype=int)
    if len(train) == 0 or len(test) == 0:
        return train
    return train[_farther_than(xy[train], xy[test], purge_m)]


def drop_background_near(xy: np.ndarray, y: np.ndarray, idx: np.ndarray, presence_xy: np.ndarray,
                         clear_m: float = CLEAR_M) -> np.ndarray:
    """Drop background rows in `idx` that sit within clear_m of `presence_xy`. Presences stay."""
    idx = np.asarray(idx, dtype=int)
    if len(idx) == 0:
        return idx
    labels = np.asarray(y).astype(int)
    pos = idx[labels[idx] == 1]
    bg = idx[labels[idx] == 0]
    if len(bg) == 0:
        return idx
    keep_bg = bg[_farther_than(xy[bg], presence_xy, clear_m)]
    return np.concatenate([pos, keep_bg])


def prepare_fold(xy: np.ndarray, y: np.ndarray, train: np.ndarray, test: np.ndarray,
                 purge_m: float = PURGE_M, clear_m: float = CLEAR_M) -> tuple[np.ndarray, np.ndarray]:
    """One spatial fold.

    The ring is drawn around test presences only (blockCV presence-background).
    Background within clear_m of a presence is then dropped on each side separately.
    """
    y = np.asarray(y).astype(int)
    test = np.asarray(test, dtype=int)
    test_presence_idx = test[y[test] == 1] if len(test) else test
    train = purge_train(xy, train, test_presence_idx, purge_m)
    train_presence = xy[train][y[train] == 1] if len(train) else np.zeros((0, 2))
    test_presence = xy[test_presence_idx] if len(test_presence_idx) else np.zeros((0, 2))
    train = drop_background_near(xy, y, train, train_presence, clear_m)
    test = drop_background_near(xy, y, test, test_presence, clear_m)
    return train, test


def iter_spatial_folds(xy: np.ndarray, y: np.ndarray, n_splits: int = 5, block_m: float = BLOCK_M,
                       purge_m: float = PURGE_M, clear_m: float = CLEAR_M):
    """Checkerboard of square blocks. Adjacent blocks fall in different folds."""
    xy = np.asarray(xy, dtype=np.float64)
    bx = np.floor(xy[:, 0] / block_m).astype(np.int64)
    by = np.floor(xy[:, 1] / block_m).astype(np.int64)
    fold = np.mod(bx + by, n_splits)
    for k in range(n_splits):
        test = np.flatnonzero(fold == k)
        if len(test) == 0:
            continue
        train = np.flatnonzero(fold != k)
        yield prepare_fold(xy, y, train, test, purge_m, clear_m)


def boyce_index(presence_ranks, n_bins: int = 10):
    """Continuous Boyce index: Spearman correlation of rank bin vs presence/area.

    Hirzel et al. 2006. `presence_ranks` are landscape percentiles in [0, 1].
    Equal-width bins make the expected share of area 1/n_bins, which is how a
    percentile map is defined. Returns None when a bin ratio cannot be ranked.
    """
    from scipy.stats import spearmanr

    ranks = np.asarray(presence_ranks, dtype=float)
    ranks = ranks[np.isfinite(ranks)]
    if len(ranks) < n_bins:
        return None
    ranks = np.clip(ranks, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ratio = np.empty(n_bins)
    mids = np.empty(n_bins)
    for i in range(n_bins):
        upper = ranks <= edges[i + 1] if i == n_bins - 1 else ranks < edges[i + 1]
        sel = (ranks >= edges[i]) & upper
        ratio[i] = sel.mean() * n_bins
        mids[i] = 0.5 * (edges[i] + edges[i + 1])
    if np.allclose(ratio, ratio[0]):
        return None
    result = spearmanr(mids, ratio)
    value = getattr(result, "statistic", None)
    if value is None:
        value = result.correlation
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def clear_training_mask(xy: np.ndarray, y: np.ndarray, clear_m: float = CLEAR_M) -> np.ndarray:
    """Rows for the deployed model: every presence, and background farther than clear_m from all of them."""
    y = np.asarray(y).astype(int)
    xy = np.asarray(xy, dtype=np.float64)
    keep = np.ones(len(y), dtype=bool)
    bg = np.flatnonzero(y == 0)
    presence = xy[y == 1]
    if len(bg) and len(presence):
        keep[bg] = _farther_than(xy[bg], presence, clear_m)
    return keep


def temporal_sets(xy: np.ndarray, y: np.ndarray, year: np.ndarray,
                  purge_m: float = PURGE_M, clear_m: float = CLEAR_M) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Train on years <= 2024. A 2025–2026 presence is new only outside the feature window of an older presence.

    Training rows inside that window of a new presence are dropped. Background scored against the new
    presences is also outside the window of the older presences, and not within clear_m of any presence.
    """
    xy = np.asarray(xy, dtype=np.float64)
    y = np.asarray(y).astype(int)
    year = np.asarray(year)
    old_pos = np.flatnonzero((year <= 2024) & (y == 1))
    new_cand = np.flatnonzero((year >= 2025) & (y == 1))
    new = new_cand[_farther_than(xy[new_cand], xy[old_pos], purge_m)] if len(new_cand) else new_cand
    train = np.flatnonzero(year <= 2024)
    train = purge_train(xy, train, new, purge_m)
    train_presence = xy[train][y[train] == 1] if len(train) else np.zeros((0, 2))
    train = drop_background_near(xy, y, train, train_presence, clear_m)
    te_bg = np.flatnonzero((year >= 2025) & (y == 0))
    te_bg = te_bg[_farther_than(xy[te_bg], xy[y == 1], clear_m)] if len(te_bg) else te_bg
    te_bg = te_bg[_farther_than(xy[te_bg], xy[old_pos], purge_m)] if len(te_bg) else te_bg
    return train, new, te_bg
