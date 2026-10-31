"""Protocols reimplemented from KonkovDV/expds-koz3.

Nothing here is imported from that repository or from EhimenNathan/EXpedition.
The published InvaRadar map is unchanged: these functions are not features of the
265-dimensional LightGBM, and they do not rewrite outputs/.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def local_relief(elevation_m: np.ndarray, res_m: float, window_m: float) -> np.ndarray:
    """Elevation minus the local mean.

    The KOZ-3 lidar branch uses this instead of a hillshade: a mound on a slope
    stays a mound, and rotating the tile does not change the channels. `window_m`
    is the side of the averaging square. At a 10 m grid, 80 m and 300 m are the
    same physical idea as the 8 m and 30 m windows on a 0.5 m lidar DEM.
    """
    if res_m <= 0 or window_m <= 0:
        raise ValueError("res_m and window_m must be positive")
    cells = max(1, int(round(window_m / res_m)))
    if cells % 2 == 0:
        cells += 1
    z = np.asarray(elevation_m, dtype=np.float64)
    mean = ndimage.uniform_filter(z, size=cells, mode="nearest")
    return z - mean


def scene_percentile(scores: np.ndarray) -> np.ndarray:
    """Rank each finite score inside this scene only.

    Geophysics sheets in KOZ-3 are not comparable after contrast stretch, so a
    find's confidence is its rank on its own sheet. The same rule applies to one
    drone frame or one satellite tile: do not pool raw scores across scenes.
    """
    s = np.asarray(scores, dtype=np.float64)
    out = np.full(s.shape, np.nan)
    finite = np.isfinite(s)
    n = int(finite.sum())
    if n == 0:
        return out
    order = np.sort(s[finite])
    out[finite] = np.searchsorted(order, s[finite], side="left") / n
    return out


def best_fbeta_threshold(y: np.ndarray, scores: np.ndarray, beta: float = 1.0) -> tuple[float, float]:
    """Threshold on this set only, and the F-beta it reaches. Higher score is a positive."""
    labels = np.asarray(y).astype(int)
    p = np.asarray(scores, dtype=np.float64)
    if len(labels) == 0:
        return 0.5, 0.0
    best_t, best_f = float(np.max(p)), -1.0
    b2 = beta * beta
    for t in np.unique(p):
        pred = p >= t
        tp = int(np.sum(pred & (labels == 1)))
        fp = int(np.sum(pred & (labels == 0)))
        fn = int(np.sum(~pred & (labels == 1)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        denom = b2 * precision + recall
        f = (1.0 + b2) * precision * recall / denom if denom else 0.0
        if f > best_f:
            best_t, best_f = float(t), float(f)
    return best_t, best_f


def nested_thresholds(groups: dict[str, tuple[np.ndarray, np.ndarray]], beta: float = 1.0) -> dict[str, float]:
    """Threshold for each group, fit only on the other groups.

    KOZ-3 sweeps a site-family threshold on the other families and does not move
    it to chase the public leaderboard. Fitting the threshold on the same group
    that is then reported is the optimistic number, not this one.
    """
    if len(groups) < 2:
        raise ValueError("nested thresholds need at least two groups")
    chosen = {}
    for name in groups:
        ys, ps = [], []
        for other, (y, scores) in groups.items():
            if other == name:
                continue
            ys.append(np.asarray(y).astype(int))
            ps.append(np.asarray(scores, dtype=np.float64))
        chosen[name] = best_fbeta_threshold(np.concatenate(ys), np.concatenate(ps), beta)[0]
    return chosen


def fbeta_at(y: np.ndarray, scores: np.ndarray, threshold: float, beta: float = 1.0) -> float:
    labels = np.asarray(y).astype(int)
    pred = np.asarray(scores, dtype=np.float64) >= threshold
    tp = int(np.sum(pred & (labels == 1)))
    fp = int(np.sum(pred & (labels == 0)))
    fn = int(np.sum(~pred & (labels == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1.0 + b2) * precision * recall / denom if denom else 0.0
