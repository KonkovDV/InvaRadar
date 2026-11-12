"""Light GeoJSON for the web map (web/index.html, GitHub Pages): the top hotspots of each species by priority,
as points with the work-order fields, plus the straight-line district tour.
usage: export_web.py [--top 3000]   (after prescribe.py and render_maps.py)"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd

from invaradar.config import OUT, ROOT
from invaradar.management import method_class

ap = argparse.ArgumentParser(); ap.add_argument("--top", type=int, default=3000)
a = ap.parse_args()
web = ROOT / "web" / "data"; web.mkdir(parents=True, exist_ok=True)


summary = {}
for taxon in ("heracleum", "solidago"):
    P = gpd.read_parquet(OUT / taxon / "hotspots_prescribed_2025.parquet").sort_values("priority", ascending=False)
    top = P.head(a.top).copy()
    pts = gpd.GeoDataFrame({
        "rank": top["rank"].astype(int),
        "priority": top.priority.round(1),
        "area_m2": top.area_m2.round(0).astype(int),
        "d_child_m": top.d_child_m.round(0).astype(int),
        "water_zone_m": top.water_zone_m.astype(int),
        "inside_aoa": top.inside_aoa.astype(bool),
        "cls": top.method.map(method_class),
        "jurisdiction": top.jurisdiction.astype(str),
        "listed_species_act": top.listed_species_act.astype(str),
        "method": top.method,
        "basis": top.legal_basis,
    }, geometry=gpd.points_from_xy(top.lon, top.lat), crs=4326)
    pts.to_file(web / f"{taxon}_top.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    s = json.load(open(OUT / taxon / "enrich_summary.json"))["prescriptions"]
    summary[taxon] = {"hotspots": s["hotspots"], "shown": len(pts), "mechanical": s["mechanical_only"],
                      "ground": s["ground_spot_treatment"], "drone": s["drone_spraying_allowed"],
                      "near_children_100m": s["near_children_100m"]}
route = gpd.read_file(OUT / "heracleum" / "route_district_2025.geojson")
route.to_file(web / "route_district.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
json.dump(summary, open(web / "summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False))
