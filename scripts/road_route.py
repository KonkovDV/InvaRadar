"""Drive the published south-Moscow stops along Overture roads.

The straight tour stays in outputs/heracleum/route_district_2025.geojson.
This writes the road line next to it and copies that line to the web map.
The extract has no one-way attribute, so each road is used in both directions.
usage: road_route.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
from shapely.geometry import Point

from invaradar.config import DATA, OUT, ROOT
from invaradar.road_route import DRIVABLE, route_stops


def main():
    straight = gpd.read_file(OUT / "heracleum" / "route_district_2025.geojson")
    vertices = list(straight.geometry.iloc[0].coords)
    stops = gpd.GeoSeries([Point(x, y) for x, y in vertices], crs=4326)
    pad = 0.04
    xs = [x for x, _y in vertices]
    ys = [y for _x, y in vertices]
    roads = gpd.read_parquet(DATA / "overture" / "roads.parquet")
    roads = roads.cx[min(xs) - pad:max(xs) + pad, min(ys) - pad:max(ys) + pad]
    roads = roads[(roads.subtype == "road") & roads["class"].isin(DRIVABLE)].to_crs(32637)
    out = route_stops(list(stops.to_crs(32637).geometry), list(roads.geometry))
    frame = gpd.GeoDataFrame(
        {
            "driving_km": [round(out["driving_m"] / 1000, 2)],
            "access_m": [round(sum(out["access_m"]), 1)],
            "straight_km": [round(out["straight_m"] / 1000, 2)],
            "stops": [len(out["order"]) - 1],
            "oneway_known": [False],
        },
        geometry=[out["line"]],
        crs=32637,
    ).to_crs(4326)
    path = OUT / "heracleum" / "route_district_roads_2025.geojson"
    frame.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
    record = {
        "stops": len(out["order"]) - 1,
        "order": out["order"],
        "driving_km": round(out["driving_m"] / 1000, 2),
        "access_m": round(sum(out["access_m"]), 1),
        "straight_km": round(out["straight_m"] / 1000, 2),
        "max_access_m": round(max(out["access_m"]), 1),
        "oneway_known": False,
        "roads": "Overture transportation segments, both directions",
        "classes": sorted(DRIVABLE),
    }
    json.dump(record, open(OUT / "heracleum" / "route_district_roads.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    web = ROOT / "web" / "data" / "route_district.geojson"
    frame.to_file(web, driver="GeoJSON", COORDINATE_PRECISION=5)
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
