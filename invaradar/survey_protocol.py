"""Protocols reimplemented from KonkovDV/expds-koz3.

Nothing here is imported from that repository or from EhimenNathan/EXpedition.
The published InvaRadar map is unchanged: these functions are not features of the
265-dimensional LightGBM, and they do not rewrite outputs/.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def kernel_cells(res_m: float, window_m: float) -> int:
    """Nearest odd cell count to `window_m / res_m`.

    An even count has no center cell. On a tie the narrower window wins, so an
    80 m request on a 10 m grid is 7 cells (70 m), not 9 cells (90 m).
    """
    if res_m <= 0 or window_m <= 0:
        raise ValueError("res_m and window_m must be positive")
    raw = window_m / res_m
    nearest = max(1, int(round(raw)))
    if nearest % 2 == 1:
        return nearest
    lower = max(1, nearest - 1)
    upper = nearest + 1
    if abs(lower - raw) <= abs(upper - raw):
        return lower
    return upper


def local_relief(elevation_m: np.ndarray, res_m: float, window_m: float) -> np.ndarray:
    """Elevation minus the local mean in a centered square.

    The KOZ-3 lidar branch uses this instead of a hillshade: a mound on a slope
    stays a mound, and a square kernel is unchanged by a quarter turn. Missing
    heights stay missing and do not pull the mean toward zero.
    """
    cells = kernel_cells(res_m, window_m)
    z = np.asarray(elevation_m, dtype=np.float64)
    valid = np.isfinite(z)
    if valid.all():
        mean = ndimage.uniform_filter(z, size=cells, mode="nearest")
        return z - mean
    filled = np.where(valid, z, 0.0)
    total = ndimage.uniform_filter(filled, size=cells, mode="constant", cval=0.0)
    count = ndimage.uniform_filter(valid.astype(np.float64), size=cells, mode="constant", cval=0.0)
    mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    out = np.full_like(z, np.nan)
    out[valid] = z[valid] - mean[valid]
    return out


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
    labels = np.asarray(y).astype(int).ravel()
    p = np.asarray(scores, dtype=np.float64).ravel()
    if labels.shape != p.shape:
        raise ValueError("labels and scores must have the same length")
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
        # Equal F keeps the higher threshold: fewer false positives, not more flags.
        if f >= best_f:
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
            labels = np.asarray(y).astype(int).ravel()
            values = np.asarray(scores, dtype=np.float64).ravel()
            if labels.shape != values.shape:
                raise ValueError(f"group {other!r} has {len(labels)} labels and {len(values)} scores")
            ys.append(labels)
            ps.append(values)
        chosen[name] = best_fbeta_threshold(np.concatenate(ys), np.concatenate(ps), beta)[0]
    return chosen


def fbeta_at(y: np.ndarray, scores: np.ndarray, threshold: float, beta: float = 1.0) -> float:
    labels = np.asarray(y).astype(int).ravel()
    values = np.asarray(scores, dtype=np.float64).ravel()
    if labels.shape != values.shape:
        raise ValueError("labels and scores must have the same length")
    pred = values >= threshold
    tp = int(np.sum(pred & (labels == 1)))
    fp = int(np.sum(pred & (labels == 0)))
    fn = int(np.sum(~pred & (labels == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1.0 + b2) * precision * recall / denom if denom else 0.0
