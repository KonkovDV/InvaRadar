"""After pipeline.py: area of applicability (uncertainty), treatment prescriptions, field-validation design.

* AOA / dissimilarity index (Meyer & Pebesma 2021, Methods Ecol. Evol.): distance of a location to the nearest
  training sample in importance-weighted standardized feature space, divided by the mean distance between training
  samples; locations above the CV-derived threshold are outside the area where the model's error is known.
* Prescriptions are written by scripts/prescribe.py, which runs after this script.
* Field validation: stratified random sample over likelihood strata (Olofsson et al. 2014) drawn by the Rust core,
  so area and accuracy can be estimated without the citizen-science sampling bias.
usage: enrich.py heracleum
"""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from scipy.spatial import cKDTree
from sklearn.decomposition import PCA
from sklearn.model_selection import GroupKFold
from invaradar.config import EPSG, OUT, STUDY_BOX, TAXA, core_binary
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import clear_training_mask

taxon = sys.argv[1]
od = OUT / taxon; tmp = od / "tmp"
CORE = core_binary()
w, s, e, n = STUDY_BOX
summary_path = od / "enrich_summary.json"
summary = json.load(open(summary_path, encoding="utf-8")) if summary_path.exists() else {}

# ---------- 1. AOA on a 100 m grid
model = json.load(open(tmp / "model.json"))
nf = model["max_feature_idx"] + 1
gain = np.zeros(nf)
def walk(t):
    if "split_feature" in t:
        gain[t["split_feature"]] += t.get("split_gain", 0.0); walk(t["left_child"]); walk(t["right_child"])
for t in model["tree_info"]:
    walk(t["tree_structure"])
wts = gain / gain.sum()
S = build(load_obs(), TAXA[taxon]["ids"], plant_taxa())
F = np.fromfile(tmp / "pts.f32", "<f4").reshape(-1, nf)
X = F[:len(S)]; ok = ~np.isnan(X[:, 0]); S, X = S[ok].reset_index(drop=True), X[ok]
trained = clear_training_mask(S[["x", "y"]].to_numpy(), S.label.to_numpy())
S, X = S.iloc[trained].reset_index(drop=True), X[trained]
rng = np.random.default_rng(0)
keep = np.r_[np.where(S.label == 1)[0], rng.choice(np.where(S.label == 0)[0], 8000, replace=False)]
Xt, St = X[keep], S.iloc[keep].reset_index(drop=True)
mu, sd = Xt.mean(0), Xt.std(0) + 1e-9
Z = (Xt - mu) / sd * np.sqrt(wts)
pca = PCA(24, random_state=0).fit(Z); Zt = pca.transform(Z)
# d̄ = mean distance between training samples (estimated on 200 000 random pairs)
ia, ib = rng.integers(0, len(Zt), 200_000), rng.integers(0, len(Zt), 200_000)
dbar = float(np.linalg.norm(Zt[ia[ia != ib]] - Zt[ib[ia != ib]], axis=1).mean())
# The DI threshold uses block groups in feature space. It is not the map's checkerboard
# and it does not draw the 500 m ring: Meyer & Pebesma score distance to training points, not capture.
groups = (St.x // 5000).astype(int) * 100003 + (St.y // 5000).astype(int)
di_cv = np.zeros(len(Zt))
for tr, te in GroupKFold(5).split(Zt, groups=groups):
    di_cv[te] = cKDTree(Zt[tr]).query(Zt[te])[0] / dbar
# threshold = upper whisker of the cross-validated training DI (largest value <= Q3 + 1.5 IQR), as in CAST::aoa
q1, q3 = np.percentile(di_cv, [25, 75]); thr = float(di_cv[di_cv <= q3 + 1.5 * (q3 - q1)].max())
step = 100.0
xs = np.arange(w + step / 2, e, step); ys = np.arange(n - step / 2, s, -step)
gx, gy = np.meshgrid(xs, ys)
pts = np.c_[gx.ravel(), gy.ravel()].astype("<f8"); pts.tofile(tmp / "aoa.f64")
subprocess.run([str(CORE), "points", str(tmp / "grid_2025.json"), str(tmp / "aoa.f64"), str(tmp / "aoa.f32")], check=True)
G = np.fromfile(tmp / "aoa.f32", "<f4").reshape(len(pts), nf)
valid = ~np.isnan(G[:, 0])
di = np.full(len(pts), np.nan, np.float32)
di[valid] = cKDTree(Zt).query(pca.transform((G[valid] - mu) / sd * np.sqrt(wts)))[0] / dbar
(tmp / "aoa.f32").unlink()
inside = di[valid] <= thr
di_img = di.reshape(gx.shape)
with rasterio.open(od / "dissimilarity_index_100m.tif", "w", driver="GTiff", width=gx.shape[1], height=gx.shape[0],
                   count=1, dtype="float32", nodata=np.nan, crs=f"EPSG:{EPSG}", transform=from_origin(w, n, step, step),
                   compress="deflate") as ds:
    ds.write(di_img, 1); ds.update_tags(aoa_threshold=float(thr))
summary["aoa"] = {"threshold_DI": round(float(thr), 3), "share_area_inside_AOA": round(float(inside.mean()), 3),
                  "method": "Meyer & Pebesma 2021 (CAST): gain-weighted standardized features, 24 PCs, d̄ = mean pairwise distance, threshold = upper whisker of spatial-CV DI"}
print("AOA", summary["aoa"], flush=True)

# ---------- 2. prescriptions: scripts/prescribe.py (needs the dissimilarity raster written above)

# ---------- 3. stratified field-validation sample (Rust)
thr_s, nh = "0.80,0.95,0.98", "50,50,60,90"
subprocess.run([str(CORE), "strata", str(tmp / "grid_2025.json"), str(tmp / "map.u8"), str(od / "validation_sample.csv"),
                "20261029", thr_s, nh], check=True)
V = pd.read_csv(od / "validation_sample.csv")
lon, lat = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(V.x.to_numpy(), V.y.to_numpy())
gpd.GeoDataFrame(V.assign(lon=lon, lat=lat), geometry=gpd.points_from_xy(lon, lat), crs=4326) \
    .to_file(od / "validation_sample.geojson", driver="GeoJSON")
strata = V.groupby("stratum").agg(n=("x", "size"), px=("stratum_px", "first"))
strata["area_km2"] = strata.px * 1e-4
strata["weight"] = strata.px / strata.px.sum()
summary["validation_design"] = {"strata_percentile_bounds": [0, 0.80, 0.95, 0.98, 1.0],
                                "n_per_stratum": strata.n.tolist(), "area_km2": strata.area_km2.round(1).tolist(),
                                "weights": strata.weight.round(4).tolist(),
                                "estimator": "stratified proportion p = sum W_h p_h, SE = sqrt(sum W_h^2 p_h (1-p_h)/(n_h-1))"}
print("validation", summary["validation_design"], flush=True)
json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
