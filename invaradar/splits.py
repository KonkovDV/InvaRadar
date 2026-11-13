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
Folds are a checkerboard of 5 km blocks, so blocks that share a side fall in
different folds. The ring is wider than the 450 m feature window.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from .samples import CLEAR_M

WINDOW_M = 450.0
# One extra 50 m cell so the two windows do not share a coarse cell.
PURGE_M = WINDOW_M + 50.0
BLOCK_M = 5000.0


def presence_spacing(xy, y, purge_m: float = PURGE_M, block_m: float = BLOCK_M, n_splits: int = 5, gps_m: float = 50.0):
    """How tightly the presences cluster, relative to the ring and the block.

    `share_other_fold_between_purge_and_block` is the share of presences whose
    nearest presence in another fold lies outside the feature ring and inside
    one block. Those pairs do not share a 450 m window, and they are still not
    independent draws.
    """
    pos = np.asarray(xy, dtype=np.float64)[np.asarray(y).astype(int) == 1]
    n = len(pos)
    if n < 3:
        return None
    fold = np.mod(np.floor(pos[:, 0] / block_m) + np.floor(pos[:, 1] / block_m), n_splits)
    delta = pos[:, None, :] - pos[None, :, :]
    dist = np.hypot(delta[:, :, 0], delta[:, :, 1])
    np.fill_diagonal(dist, np.inf)
    nearest = dist.min(axis=1)
    other = dist.copy()
    other[fold[:, None] == fold[None, :]] = np.inf
    nearest_other = other.min(axis=1)

    def share(mask):
        return round(float(np.mean(mask)), 3)

    return {
        "n": int(n),
        "nearest_m_p50": round(float(np.median(nearest)), 1),
        "nearest_m_p90": round(float(np.quantile(nearest, 0.9)), 1),
        "share_nearest_within_gps": share(nearest <= gps_m),
        "share_nearest_within_purge": share(nearest <= purge_m),
        "share_other_fold_within_purge": share(nearest_other <= purge_m),
        "share_other_fold_between_purge_and_block": share((nearest_other > purge_m) & (nearest_other <= block_m)),
    }


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


CAPTURE_LEVELS = (1, 5, 10, 20)


def above_area_share(ranks, percent: float) -> np.ndarray:
    """True where a finite landscape percentile falls in the top `percent` of area."""
    return np.isfinite(ranks) & (np.asarray(ranks, dtype=float) >= 1 - percent / 100)


def capture_rates(ranks, levels=CAPTURE_LEVELS) -> dict:
    """Share of finite ranks in the top 1, 5, 10 and 20 percent of the map."""
    finite = np.asarray(ranks, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return {f"capture@{k}%area": None for k in levels}
    return {f"capture@{k}%area": float(above_area_share(finite, k).mean()) for k in levels}


def paired_area_difference(ranks_a, ranks_b, blocks, percent: float = 20.0,
                           n_boot: int = 2000, seed: int = 0) -> dict:
    """Capture difference on the same points, with a block bootstrap.

    ``ranks_a[i] - ranks_b[i]`` is one place seen by two maps. A place that is
    missing on either map is dropped from both, so the pair stays aligned. The
    landscape threshold is already inside the ranks and is not resampled. Blocks
    are drawn with replacement. The reported difference is capture(a) minus capture(b).
    """
    a = np.asarray(ranks_a, dtype=float).ravel()
    b = np.asarray(ranks_b, dtype=float).ravel()
    groups = np.asarray(blocks).ravel()
    if a.shape != b.shape or a.shape != groups.shape:
        raise ValueError("ranks and blocks must have the same length")
    if n_boot < 1:
        raise ValueError("n_boot must be positive")
    ok = np.isfinite(a) & np.isfinite(b)
    a, b, groups = a[ok], b[ok], groups[ok]
    if len(a) == 0:
        return {"n": 0, "n_blocks": 0, "capture_a": None, "capture_b": None,
                "diff": None, "boot95": None, "n_boot": int(n_boot), "seed": int(seed),
                "percent": float(percent)}
    threshold = 1.0 - float(percent) / 100.0

    def share(values: np.ndarray) -> float:
        return float(np.mean(values >= threshold))

    unique, inverse = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot, dtype=float)
    n_groups = len(unique)
    for i in range(n_boot):
        chosen = rng.integers(0, n_groups, n_groups)
        sel = np.concatenate([members[j] for j in chosen])
        boots[i] = share(a[sel]) - share(b[sel])
    low, high = np.percentile(boots, [2.5, 97.5])
    return {"n": int(len(a)), "n_blocks": int(n_groups),
            "capture_a": share(a), "capture_b": share(b),
            "diff": share(a) - share(b),
            "boot95": [float(low), float(high)],
            "n_boot": int(n_boot), "seed": int(seed), "percent": float(percent)}


def block_capture(ranks, blocks, percent: float = 20.0, n_boot: int = 2000, seed: int = 0) -> dict:
    """Capture on one map, with a block bootstrap of the places.

    The landscape threshold is already inside the ranks and is not resampled.
    """
    values = np.asarray(ranks, dtype=float).ravel()
    groups = np.asarray(blocks).ravel()
    if values.shape != groups.shape:
        raise ValueError("ranks and blocks must have the same length")
    if n_boot < 1:
        raise ValueError("n_boot must be positive")
    ok = np.isfinite(values)
    values, groups = values[ok], groups[ok]
    if len(values) == 0:
        return {"n": 0, "n_blocks": 0, "capture": None, "n_captured": 0,
                "boot95": None, "n_boot": int(n_boot), "seed": int(seed), "percent": float(percent)}
    threshold = 1.0 - float(percent) / 100.0
    unique, inverse = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot, dtype=float)
    n_groups = len(unique)
    for i in range(n_boot):
        chosen = rng.integers(0, n_groups, n_groups)
        sel = np.concatenate([members[j] for j in chosen])
        boots[i] = float(np.mean(values[sel] >= threshold))
    low, high = np.percentile(boots, [2.5, 97.5])
    captured = int(np.sum(values >= threshold))
    return {"n": int(len(values)), "n_blocks": int(n_groups),
            "capture": captured / len(values), "n_captured": captured,
            "boot95": [float(low), float(high)],
            "n_boot": int(n_boot), "seed": int(seed), "percent": float(percent)}


def landscape_percentile(reference, scores) -> np.ndarray:
    """Share of a sorted reference strictly below each score.

    A non-finite score stays missing. Search would otherwise place NaN at the top
    of the reference and report it as the best percentile.
    """
    ref = np.asarray(reference, dtype=float)
    values = np.asarray(scores, dtype=float)
    out = np.full(values.shape, np.nan, dtype=float)
    ok = np.isfinite(values)
    if len(ref) and ok.any():
        out[ok] = np.searchsorted(ref, values[ok]) / len(ref)
    return out


def boyce_ratios(presence_ranks, n_bins: int = 10):
    """Predicted-to-expected ratio in equal-width bins of the landscape percentile.

    Hirzel et al. 2006. A percentile map gives each bin the same area, so the
    expected share of presences is 1/n_bins and F/E = (share of presences) × n_bins.
    The ratio does not say how steep the curve is: a gentle rise and a steep one
    can both be perfectly ordered.
    """
    ranks = np.asarray(presence_ranks, dtype=float)
    ranks = ranks[np.isfinite(ranks)]
    if len(ranks) < n_bins:
        return None
    ranks = np.clip(ranks, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ratio = np.empty(n_bins)
    for i in range(n_bins):
        upper = ranks <= edges[i + 1] if i == n_bins - 1 else ranks < edges[i + 1]
        sel = (ranks >= edges[i]) & upper
        ratio[i] = sel.mean() * n_bins
    return ratio


def boyce_index(presence_ranks, n_bins: int = 10):
    """Spearman correlation of bin midpoint vs F/E. None when the ratios do not rank.

    A value of 1 means the ten bins are strictly ordered. It is not a probability
    and it is not the share of presences in the top of the map.
    """
    from scipy.stats import spearmanr

    ratio = boyce_ratios(presence_ranks, n_bins)
    if ratio is None or np.allclose(ratio, ratio[0]):
        return None
    mids = np.linspace(0.5 / n_bins, 1.0 - 0.5 / n_bins, n_bins)
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


def feature_year(map_year: int, embedding_year: int | None = None) -> tuple[int, str]:
    """AlphaEarth year for the features, and whether the label split is a retro forecast.

    The published 6 Nov 2026 map uses one 2025 image on both sides of the year split
    (``same_image``). An earlier embedding year, with the same 2025–2026 holdout,
    is a retro forecast (audit A-02). A later embedding year is ``later_image``:
    it is not a forecast of the map year. The pixel-only numbers for the retro
    protocol are in ``pro/analysis/results/TABLES.md``.
    """
    if embedding_year is None:
        return int(map_year), "same_image"
    year = int(embedding_year)
    if year == int(map_year):
        return year, "same_image"
    if year < int(map_year):
        return year, "retro_forecast"
    return year, "later_image"


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


def read_rank_cache(path, n: int, newer_than=None) -> np.ndarray | None:
    """Little-endian f64 ranks written by pipeline.py.

    None if the file is missing, a different length, or older than `newer_than` (the feature dump).
    Uncertainty then fits the forest itself.
    """
    p = Path(path)
    try:
        rk = np.fromfile(p, "<f8")
    except OSError:
        return None
    if rk.shape != (int(n),):
        return None
    if newer_than is not None:
        src = Path(newer_than)
        try:
            if src.is_file() and src.stat().st_mtime > p.stat().st_mtime:
                return None
        except OSError:
            return None
    return rk
