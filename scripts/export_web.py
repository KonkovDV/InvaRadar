"""Light GeoJSON for the web map (web/index.html, GitHub Pages): the top hotspots of each species by priority,
as points with the work-order fields, plus the district tour. The tour is the road line when
outputs/heracleum/route_district_roads_2025.geojson exists, and the straight line until then.
usage: export_web.py [--top 3000]   (after prescribe.py and render_maps.py)"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd

from invaradar.config import OUT, ROOT
from invaradar.management import method_class

# The popup reads the city-line distance. A fresh export has to keep the same fields the page already shows.
WEB_FIELDS = ("rank", "priority", "area_m2", "d_child_m", "water_zone_m", "inside_aoa", "cls", "jurisdiction",
              "jurisdiction_boundary_m", "near_jurisdiction_boundary", "listed_species_act", "method", "basis")


def route_for_web():
    """The site draws the road tour once it has been computed, and the straight line until then."""
    road = OUT / "heracleum" / "route_district_roads_2025.geojson"
    if road.exists():
        return road
    return OUT / "heracleum" / "route_district_2025.geojson"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--top", type=int, default=3000)
    a = ap.parse_args()
    web = ROOT / "web" / "data"; web.mkdir(parents=True, exist_ok=True)

    summary = {}
    for taxon in ("heracleum", "solidago"):
        table = gpd.read_parquet(OUT / taxon / "hotspots_prescribed_2025.parquet")
        table = table.sort_values("priority", ascending=False)
        top = table.head(a.top).copy()
        columns = {
            "rank": top["rank"].astype(int),
            "priority": top.priority.round(1),
            "area_m2": top.area_m2.round(0).astype(int),
            "d_child_m": top.d_child_m.round(0).astype(int),
            "water_zone_m": top.water_zone_m.astype(int),
            "inside_aoa": top.inside_aoa.astype(bool),
            "cls": top.method.map(method_class),
            "jurisdiction": top.jurisdiction.astype(str),
            "jurisdiction_boundary_m": top.jurisdiction_boundary_m.round(2),
            "near_jurisdiction_boundary": top.near_jurisdiction_boundary.astype(bool),
            "listed_species_act": top.listed_species_act.astype(str),
            "method": top.method,
            "basis": top.legal_basis,
        }
        missing = set(WEB_FIELDS) - set(columns)
        if missing:
            raise SystemExit(f"web export is missing {sorted(missing)}")
        pts = gpd.GeoDataFrame(columns, geometry=gpd.points_from_xy(top.lon, top.lat), crs=4326)
        pts.to_file(web / f"{taxon}_top.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
        s = json.load(open(OUT / taxon / "enrich_summary.json"))["prescriptions"]
        summary[taxon] = {"hotspots": s["hotspots"], "shown": len(pts), "mechanical": s["mechanical_only"],
                          "ground": s["ground_spot_treatment"], "drone": s["drone_spraying_allowed"],
                          "near_children_100m": s["near_children_100m"]}
    route = gpd.read_file(route_for_web())
    route.to_file(web / "route_district.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    json.dump(summary, open(web / "summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
