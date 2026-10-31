"""End-to-end run for one taxon: samples → Rust features → LightGBM (spatial CV + forward-in-time test) →
Rust wall-to-wall map → Rust hotspots → priorities → Rust route.  usage: pipeline.py heracleum [--year 2025]"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy.spatial import cKDTree
from shapely.geometry import shape
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from invaradar.aef import AEFIndex, BlockCache, block_jobs
from invaradar.config import AEF_CACHE, AEF_INDEX, DATA, EPSG, OUT, STUDY_BOX, TAXA, TERRAIN_FEATURES, core_binary
from invaradar.priority import HOT_PCT, MIN_PX
from invaradar.queue import build_queue, load_context
from invaradar.samples import build, load_obs, plant_taxa

CORE = core_binary()
ap = argparse.ArgumentParser(); ap.add_argument("taxon"); ap.add_argument("--year", type=int, default=2025)
ap.add_argument("--top", type=int, default=25)
ap.add_argument("--no-terrain", action="store_true",
                help="drop DEM features (chosen per species by the forward-in-time test)")
ap.add_argument("--variant", default="", help="write to outputs/variants/<taxon>_<variant> instead of outputs/<taxon>")
a = ap.parse_args()
od = OUT / a.taxon if not a.variant else OUT / "variants" / f"{a.taxon}_{a.variant}"
od.mkdir(parents=True, exist_ok=True); tmp = od / "tmp"; tmp.mkdir(exist_ok=True)
t0 = time.time()
log = lambda *s: print(f"[{time.time() - t0:6.1f}s]", *s, flush=True)
w, s, e, n = STUDY_BOX; RES = 10.0
W, H = int((e - w) / RES), int((n - s) / RES)


def core(*args):
    subprocess.run([str(CORE), *map(str, args)], check=True)


# ---- grid description for the Rust core (blocks + corridor segments in pixel space)
def segments():
    out = []
    seg_dir = DATA / "segments"; seg_dir.mkdir(exist_ok=True)
    ov = DATA / "overture"
    roads = gpd.read_parquet(ov / "roads.parquet")
    major = {"motorway", "trunk", "primary", "secondary", "tertiary"}
    layers = {"road_major": roads[(roads.subtype == "road") & roads["class"].isin(major)],
              "road_minor": roads[(roads.subtype == "road") & ~roads["class"].isin(major)],
              "rail": roads[roads.subtype == "rail"],
              "water": gpd.read_parquet(ov / "water.parquet"),
              "power": gpd.read_parquet(ov / "infra.parquet")}
    for k, g in layers.items():
        p = seg_dir / f"{k}.f32"
        if not p.exists():
            g = g.to_crs(EPSG).geometry.boundary.where(g.geom_type.str.contains("Polygon"), g.to_crs(EPSG).geometry)
            from shapely import get_coordinates, get_parts
            q = []
            for geom in get_parts(g.dropna().values):
                for part in get_parts(geom):
                    xy = get_coordinates(part)
                    if len(xy) < 2:
                        continue
                    c = (xy[:, 0] - w) / RES; r = (n - xy[:, 1]) / RES
                    q.append(np.c_[c[:-1], r[:-1], c[1:], r[1:]])
            np.concatenate(q).astype("<f4").tofile(p)
        out.append(str(p))
    return out


jobs = block_jobs(AEFIndex(AEF_INDEX), a.year, EPSG, STUDY_BOX)
cache = BlockCache(AEF_CACHE)
for j in jobs:
    cache.get(a.year, j[0], j[1], j[2])
grid = {"w": w, "n": n, "width": W, "height": H, "res": RES,
        "blocks": [[str(cache.path(a.year, Path(j[0]).stem, j[1], j[2])), j[3], j[4]] for j in jobs],
        "segments": segments(), **({} if a.no_terrain else {"dem": str(DATA / "dem_10m.f32")})}
gpath = tmp / f"grid_{a.year}.json"; json.dump(grid, open(gpath, "w"))

# ---- samples + landscape points → Rust features
S = build(load_obs(), TAXA[a.taxon]["ids"], plant_taxa())
rng = np.random.default_rng(0)
LXY = np.c_[rng.uniform(w, e, 40000), rng.uniform(s, n, 40000)]
xy_all = np.vstack([S[["x", "y"]].to_numpy(), LXY]).astype("<f8")
xy_all.tofile(tmp / "pts.f64")
core("points", gpath, tmp / "pts.f64", tmp / "pts.f32")
F = np.fromfile(tmp / "pts.f32", "<f4").reshape(len(xy_all), -1)
X, XL = F[:len(S)], F[len(S):]
ok = ~np.isnan(X[:, 0]); S, X = S[ok].reset_index(drop=True), X[ok]
XL = XL[~np.isnan(XL[:, 0])]
y = S.label.to_numpy(); xy = S[["x", "y"]].to_numpy(); yr = S.year.fillna(0).to_numpy()
log("samples", int(y.sum()), "presence /", int((y == 0).sum()), "background; features", X.shape[1])

P = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_child_samples=20, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0, verbose=-1, n_jobs=4)
NR = 300


def fit(Xt, yt):
    return lgb.train({**P, "scale_pos_weight": (yt == 0).sum() / max(yt.sum(), 1)}, lgb.Dataset(Xt, yt), NR)


def capture(ranks):
    return {f"capture@{k}%area": float((ranks >= 1 - k / 100).mean()) for k in (1, 5, 10, 20)}


# spatial block CV (5 km blocks)
groups = (xy[:, 0] // 5000).astype(int) * 100003 + (xy[:, 1] // 5000).astype(int)
oof = np.zeros(len(y)); rk = np.zeros(len(y))
for tr, te in GroupKFold(5).split(X, y, groups):
    m = fit(X[tr], y[tr])
    oof[te] = m.predict(X[te], raw_score=True)
    land = np.sort(m.predict(XL, raw_score=True))
    rk[te] = np.searchsorted(land, oof[te]) / len(land)
metrics = {"taxon": a.taxon, "embedding_year": a.year, "features": int(X.shape[1]), "terrain": not a.no_terrain,
           "samples": {"presence": int(y.sum()), "background": int((y == 0).sum())},
           "spatial_cv": {"roc_auc_vs_background": float(roc_auc_score(y, oof)), **capture(rk[y == 1])}}
log("spatial CV", json.dumps(metrics["spatial_cv"]))

# Label split, not a forecast from an earlier image. Every point uses the same AlphaEarth year
# (`--year`, default 2025). A 2025–2026 presence is "new" only when it is more than 100 m from a
# presence with year <= 2024. Features still include the 450 m mean, so that buffer does not
# separate the test point from training context. Stored metrics are this protocol.
tr = yr <= 2024; te_pos = (yr >= 2025) & (y == 1)
d, _ = cKDTree(xy[tr & (y == 1)]).query(xy[te_pos]); new = np.where(te_pos)[0][d > 100]
te_bg = np.where((yr >= 2025) & (y == 0))[0]
m = fit(X[tr], y[tr]); land = np.sort(m.predict(XL, raw_score=True))
pp, pb = m.predict(X[new], raw_score=True), m.predict(X[te_bg], raw_score=True)
metrics["temporal_test"] = {"n_new_presence": int(len(new)),
                            "roc_auc_vs_background": float(roc_auc_score(np.r_[np.ones(len(pp)), np.zeros(len(pb))], np.r_[pp, pb])),
                            **capture(np.searchsorted(land, pp) / len(land))}
log("temporal", json.dumps(metrics["temporal_test"]))

# final model → JSON for the Rust evaluator; parity check on 2 000 points
final = fit(X, y)
json.dump(final.dump_model(), open(tmp / "model.json", "w"))
land = final.predict(XL, raw_score=True); land.astype("<f8").tofile(tmp / "land.f64")
chk = xy[:2000].astype("<f8"); chk.tofile(tmp / "chk.f64")
core("score", gpath, tmp / "model.json", tmp / "chk.f64", tmp / "chk_score.f64")
rs = np.fromfile(tmp / "chk_score.f64", "<f8"); ps = final.predict(X[:2000], raw_score=True)
metrics["rust_parity_max_abs_diff"] = float(np.nanmax(np.abs(rs - ps)))
log("Rust vs LightGBM max |diff|", metrics["rust_parity_max_abs_diff"])
imp = final.feature_importance("gain"); grp = {"pixel": imp[:64].sum(), "50m": imp[64:128].sum(),
      "150m": imp[128:192].sum(), "450m": imp[192:256].sum(), "corridors": imp[256:261].sum(),
      "terrain": imp[261:].sum()}
metrics["terrain_importance"] = {k: round(float(v / imp.sum()), 4) for k, v in zip(TERRAIN_FEATURES, imp[261:265])}
metrics["importance_share"] = {k: round(float(v / imp.sum()), 3) for k, v in grp.items()}

# ---- wall-to-wall map (Rust) → GeoTIFF
core("predict", gpath, tmp / "model.json", tmp / "land.f64", tmp / "map.u8")
img = np.fromfile(tmp / "map.u8", np.uint8).reshape(H, W)
prof = dict(driver="COG", width=W, height=H, count=1, dtype="uint8", nodata=255, crs=f"EPSG:{EPSG}",
            transform=from_origin(w, n, RES, RES), compress="ZSTD", predictor=2, blocksize=512,
            overview_resampling="nearest")
with rasterio.open(od / f"likelihood_{a.year}.tif", "w", **prof) as ds:  # Cloud Optimized GeoTIFF
    ds.write(img, 1)
    ds.update_tags(units="landscape percentile x250 (0-250), 255 = no data", taxon=a.taxon,
                   model="LightGBM on AlphaEarth Foundations embeddings + corridors" + ("" if a.no_terrain else " + terrain"))
log("map written")

# ---- hotspots (Rust) → polygons → priority → route (Rust)
core("hotspots", gpath, tmp / "map.u8", HOT_PCT, MIN_PX, tmp / "labels.i32", tmp / "hot.csv")
lab = np.fromfile(tmp / "labels.i32", "<i4").reshape(H, W)
st = pd.read_csv(tmp / "hot.csv")
geoms = {}
for g, v in shapes(lab, mask=lab > 0, transform=prof["transform"], connectivity=8):
    geoms.setdefault(int(v), []).append(shape(g))
from shapely.ops import unary_union
st["geometry"] = [unary_union(geoms[i]) for i in st.hid]
Hs = gpd.GeoDataFrame(st, geometry="geometry", crs=EPSG); Hs["area_m2"] = Hs.area
metrics["hotspots"] = build_queue(Hs, od, a.year, a.top, load_context())
json.dump(metrics, open(od / "metrics.json", "w"), ensure_ascii=False, indent=2)
log("done", json.dumps(metrics["hotspots"], ensure_ascii=False))
