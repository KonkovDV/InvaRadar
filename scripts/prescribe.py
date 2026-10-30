"""After pipeline.py (or requeue.py) and enrich.py: treatment prescriptions and work orders for every hotspot.

* area of applicability: the dissimilarity index raster written by enrich.py, threshold from its `aoa_threshold` tag;
* prescriptions: invaradar.management (biology × law × heritage);
* outputs: hotspots_prescribed_<year>.(geojson|parquet), work_orders_top200_<year>.csv and the `prescriptions`
  block of enrich_summary.json.
usage: prescribe.py heracleum [--year 2025]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import rasterio

from invaradar.config import DATA, EPSG, OUT
from invaradar.management import prescribe, summarize

ap = argparse.ArgumentParser(); ap.add_argument("taxon"); ap.add_argument("--year", type=int, default=2025)
a = ap.parse_args()
od = OUT / a.taxon

H = gpd.read_parquet(od / f"hotspots_{a.year}.parquet").to_crs(EPSG)
H = H.drop(columns=[c for c in ("dissimilarity", "inside_aoa") if c in H])
with rasterio.open(od / "dissimilarity_index_100m.tif") as ds:
    thr = float(ds.tags()["aoa_threshold"])
    c = H.geometry.representative_point()
    H["dissimilarity"] = [v[0] for v in ds.sample(list(zip(c.x, c.y)))]
H["inside_aoa"] = H["dissimilarity"] <= thr

ov = DATA / "overture"
layers = {k: gpd.read_parquet(ov / f"{k}.parquet") for k in ("water", "landuse", "places")}
loc = ov / "settlements.parquet"
P = prescribe(H, a.taxon, layers["water"], layers["landuse"], layers["places"],
              gpd.read_parquet(loc) if loc.exists() else None)
P.to_crs(4326).to_file(od / f"hotspots_prescribed_{a.year}.geojson", driver="GeoJSON")
P.to_crs(4326).to_parquet(od / f"hotspots_prescribed_{a.year}.parquet", compression="zstd")
cols = ["rank", "priority", "lat", "lon", "area_m2", "mean_rank", "inside_aoa", "water_zone_m", "in_protected",
        "child_org_territory", "near_children", "d_child_m", "near_heritage", "in_settlement", "method", "legal_basis"]
P.sort_values("priority", ascending=False)[cols].head(200).round(3) \
    .to_csv(od / f"work_orders_top200_{a.year}.csv", index=False)

summary_path = od / "enrich_summary.json"
summary = json.load(open(summary_path)) if summary_path.exists() else {}
summary["prescriptions"] = summarize(P)
json.dump(summary, open(summary_path, "w"), ensure_ascii=False, indent=1)
print("prescriptions", json.dumps(summary["prescriptions"], ensure_ascii=False), flush=True)
