"""Quick label-quality experiments on cached Rust features (3-fold spatial CV, 150 trees)."""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.spatial import cKDTree
from invaradar.config import OUT, TAXA
from invaradar.model import fit_map
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import iter_spatial_folds, landscape_percentile
taxon = sys.argv[1]
tmp = OUT / taxon / "tmp"
obs = load_obs(); plants = plant_taxa()
S = build(obs, TAXA[taxon]["ids"], plants)
F = np.fromfile(tmp / "pts.f32", "<f4"); F = F.reshape(-1, F.size // (len(S) + 40000))
X, XL = F[:len(S)], F[len(S):]
ok = ~np.isnan(X[:, 0]); S, X = S[ok].reset_index(drop=True), X[ok]; XL = XL[~np.isnan(XL[:, 0])]
y = S.label.to_numpy(); xy = S[["x", "y"]].to_numpy()
# persistence: distinct research-grade observers of this sample within 30 m (build() already dropped other grades)
pos = S[y == 1]
tree = cKDTree(pos[["x", "y"]].to_numpy())
nb = tree.query_ball_point(pos[["x", "y"]].to_numpy(), 30)
nobs = np.array([pos.observer_id.iloc[i].nunique() for i in nb])
persist = np.zeros(len(S), bool); persist[np.where(y == 1)[0][nobs >= 2]] = True
print("presences", int(y.sum()), "persistent (>=2 observers within 30 m)", int(persist.sum()))
def run(cols, mask_train_pos=None, name=""):
    rk = np.full(len(y), np.nan)
    for tr, te in iter_spatial_folds(xy, y, n_splits=3):
        if mask_train_pos is not None and len(tr):
            tr = tr[(y[tr] == 0) | mask_train_pos[tr]]
        if len(te) == 0 or y[tr].sum() == 0 or (y[tr] == 0).sum() == 0:
            continue
        # Same leaves and subsampling as the map. Fewer trees and a higher rate: this is not the published forest.
        m = fit_map(X[tr][:, cols], y[tr], trees=150, learning_rate=0.08)
        land = np.sort(m.predict(XL[:, cols], raw_score=True))
        rk[te] = landscape_percentile(land, m.predict(X[te][:, cols], raw_score=True))
    out = {}
    for lab, sel in [("all", y == 1), ("persistent", persist), ("single", (y == 1) & ~persist)]:
        r = rk[sel]
        r = r[np.isfinite(r)]
        out[lab] = {f"@{k}%": round(float((r >= 1 - k / 100).mean()), 3) if len(r) else None for k in (1, 5, 10, 20)}
    print(name, json.dumps(out)); return out
A = list(range(128)); MS = list(range(256)); ALL = list(range(X.shape[1]))
res = {"aef_pixel+50m": run(A, name="aef_pixel+50m"),
       "aef_multiscale": run(MS, name="aef_multiscale"),
       "all_features": run(ALL, name="all"),
       # Same 265 features as all_features, so the training filter is not confounded with the window set.
       "all_features_train_on_persistent": run(ALL, persist, name="all_train_persistent"),
       "multiscale_train_on_persistent": run(MS, persist, name="ms_train_persistent")}
json.dump({"n_presence": int(y.sum()), "n_persistent": int(persist.sum()), "results": res},
          open(OUT / taxon / "exp_labels.json", "w", encoding="utf-8"), indent=1)
