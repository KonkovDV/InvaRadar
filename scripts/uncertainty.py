"""Confidence intervals for the headline metrics, from the features cached by pipeline.py.

Re-fits the same spatial block cross-validation and forward-in-time models as pipeline.py (same parameters, same
folds) and attaches 95 % intervals:

* spatial CV — cluster bootstrap over the 5 km blocks (presences inside one block are not independent, so
  whole blocks are resampled; 2 000 replicates, percentile intervals);
* forward-in-time test — Wilson score interval for a binomial proportion (the new reports are scattered across
  the city and are at least 100 m from any earlier report).

Also reports the lift over random search (capture / area share) with the same intervals.
usage: uncertainty.py heracleum
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lightgbm as lgb
import numpy as np
from scipy.spatial import cKDTree
from sklearn.model_selection import GroupKFold

from invaradar.config import OUT, TAXA
from invaradar.samples import build, load_obs, plant_taxa

taxon = sys.argv[1]
od = OUT / taxon
tmp = od / "tmp"
S = build(load_obs(), TAXA[taxon]["ids"], plant_taxa())
F = np.fromfile(tmp / "pts.f32", "<f4")
F = F.reshape(-1, F.size // (len(S) + 40000))
X, XL = F[:len(S)], F[len(S):]
ok = ~np.isnan(X[:, 0])
S, X = S[ok].reset_index(drop=True), X[ok]
XL = XL[~np.isnan(XL[:, 0])]
y = S.label.to_numpy()
xy = S[["x", "y"]].to_numpy()
yr = S.year.fillna(0).to_numpy()

P = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_child_samples=20, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0, verbose=-1, n_jobs=4)


def fit(Xt, yt):
    return lgb.train({**P, "scale_pos_weight": (yt == 0).sum() / max(yt.sum(), 1)}, lgb.Dataset(Xt, yt), 300)


KS = (1, 5, 10, 20)
groups = (xy[:, 0] // 5000).astype(int) * 100003 + (xy[:, 1] // 5000).astype(int)
rk = np.zeros(len(y))
for tr, te in GroupKFold(5).split(X, y, groups):
    m = fit(X[tr], y[tr])
    land = np.sort(m.predict(XL, raw_score=True))
    rk[te] = np.searchsorted(land, m.predict(X[te], raw_score=True)) / len(land)

pos = y == 1
r_pos, g_pos = rk[pos], groups[pos]
blocks, inv = np.unique(g_pos, return_inverse=True)
hits = {k: np.bincount(inv, weights=(r_pos >= 1 - k / 100), minlength=len(blocks)) for k in KS}
cnt = np.bincount(inv, minlength=len(blocks))
rng = np.random.default_rng(20261029)
boot = {k: [] for k in KS}
for _ in range(2000):
    b = rng.integers(0, len(blocks), len(blocks))
    n = cnt[b].sum()
    for k in KS:
        boot[k].append(hits[k][b].sum() / n)


def ci(est, lo, hi, k):
    return {"estimate": round(float(est), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "lift": round(float(est / (k / 100)), 2), "lift_ci95": [round(float(lo / (k / 100)), 2),
                                                                    round(float(hi / (k / 100)), 2)]}


out = {"taxon": taxon, "n_presence": int(pos.sum()), "n_blocks_with_presence": int(len(blocks)),
       "spatial_cv": {f"capture@{k}%area": ci(hits[k].sum() / cnt.sum(), *np.percentile(boot[k], [2.5, 97.5]), k)
                      for k in KS},
       "spatial_cv_method": "cluster bootstrap over 5 km blocks, 2000 replicates, percentile 95% CI"}

tr = yr <= 2024
te_pos = (yr >= 2025) & (y == 1)
d, _ = cKDTree(xy[tr & (y == 1)]).query(xy[te_pos])
new = np.where(te_pos)[0][d > 100]
m = fit(X[tr], y[tr])
land = np.sort(m.predict(XL, raw_score=True))
r_new = np.searchsorted(land, m.predict(X[new], raw_score=True)) / len(land)


def wilson(x, n, z=1.959964):
    p = x / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


out["temporal_test"] = {f"capture@{k}%area": ci((r_new >= 1 - k / 100).mean(),
                                                 *wilson((r_new >= 1 - k / 100).sum(), len(r_new)), k)
                        for k in KS}
out["temporal_test"]["n_new_presence"] = int(len(new))
out["temporal_method"] = "Wilson score 95% CI"
json.dump(out, open(od / "uncertainty.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
