"""Hotspots → survey queue and a straight-line visiting order; shared by scripts/pipeline.py and scripts/requeue.py."""
from __future__ import annotations

import subprocess
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point

from .config import DATA, EPSG, core_binary
from .priority import add_priority

CORE = core_binary()
DEPOT_LONLAT = (37.6176, 55.7520)  # route start: centre of Moscow
# `rank` follows `priority` (area still counts). The three queue ranks are separate columns, not the route.
QUEUE_COLS = ["rank", "priority", "lat", "lon", "area_m2", "mean_rank", "max_rank", "d_sensitive_m", "d_child_m",
              "d_road_m", "d_rail_m", "d_water_m", "d_power_m",
              "safety_rank", "containment_rank", "programme_rank"]


def district_stops(xy: np.ndarray, radius_m: float = 4000.0, n: int = 15) -> tuple[int, np.ndarray]:
    """Index of the densest point, and up to `n` other points in its neighbourhood.

    `xy` is ordered by priority, highest first. The centre is the point with the most
    neighbours inside `radius_m`. It starts the route and is not listed again. The stops
    keep that priority order.
    """
    xy = np.asarray(xy, dtype=np.float64)
    if len(xy) == 0:
        return 0, np.zeros(0, dtype=int)
    counts = np.fromiter((len(ix) for ix in cKDTree(xy).query_ball_point(xy, radius_m)), dtype=int, count=len(xy))
    centre = int(counts.argmax())
    dist = np.hypot(xy[:, 0] - xy[centre, 0], xy[:, 1] - xy[centre, 1])
    stops = np.flatnonzero((dist < radius_m) & (np.arange(len(xy)) != centre))[:n]
    return centre, stops


def load_context():
    ov = DATA / "overture"
    return {k: gpd.read_parquet(ov / f"{k}.parquet") for k in ("places", "roads", "water", "infra", "landuse")}


def build_queue(hs: gpd.GeoDataFrame, od: Path, year: int, top: int, ctx: dict) -> dict:
    """Score hotspots, write hotspots_<year>.(geojson|parquet), survey_queue_<year>.csv and the route over the
    `top` hotspots; return the `hotspots` block of metrics.json."""
    hs = add_priority(hs.to_crs(EPSG), ctx["places"], ctx["roads"], ctx["water"], ctx["infra"], ctx["landuse"])
    c = hs.geometry.representative_point()
    lon, lat = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(c.x.to_numpy(), c.y.to_numpy())
    hs["lon"], hs["lat"] = np.round(lon, 6), np.round(lat, 6)
    hs.to_crs(4326).to_file(od / f"hotspots_{year}.geojson", driver="GeoJSON")
    hs.to_crs(4326).to_parquet(od / f"hotspots_{year}.parquet", compression="zstd")  # GeoParquet
    hs[QUEUE_COLS].round(3).to_csv(od / f"survey_queue_{year}.csv", index=False)
    tmp = od / "tmp"; tmp.mkdir(exist_ok=True)
    depot = np.array(Transformer.from_crs(4326, EPSG, always_xy=True).transform(*DEPOT_LONLAT))
    pts = np.vstack([depot, np.c_[c.x[:top], c.y[:top]]]).astype("<f8"); pts.tofile(tmp / "route.f64")
    subprocess.run([str(CORE), "route", str(tmp / "route.f64"), str(tmp / "route.txt")], check=True)
    rt = open(tmp / "route.txt").read().split(); length = float(rt[0]); order = [int(i) for i in rt[1:]]
    line = LineString([Point(pts[i]) for i in order])
    gpd.GeoDataFrame({"length_km": [length / 1000]}, geometry=[line], crs=EPSG).to_crs(4326) \
        .to_file(od / f"route_top{top}_{year}.geojson", driver="GeoJSON")
    return {"count": int(len(hs)), "area_ha": round(float(hs.area_m2.sum() / 1e4), 1),
            "within_100m_of_child_facility": int((hs.d_child_m <= 100).sum()),
            "within_300m_of_child_facility": int((hs.d_child_m <= 300).sum()),
            "within_300m_of_sensitive_place": int((hs.d_sensitive_m <= 300).sum()),
            "route_top": top, "route_km": round(length / 1000, 1)}
