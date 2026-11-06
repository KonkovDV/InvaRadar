"""Priority of hotspots: rank x human exposure x spread potential x size.

Hotspots (connected components of the top 2 % of the landscape, >= 4 pixels) and the straight-line order
(nearest neighbour + 2-opt) are computed by the Rust core; this module scores them and splits three queues.
Every factor is transparent: the operator sees each distance and multiplier in the survey queue.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree

from .layers import child_facilities

HOT_PCT = 0.98         # pixel must outrank 98 % of the study area
MIN_PX = 4             # >= 400 m^2
SAFETY_CHILD_M = 300.0          # safety queue; the pesticide ban is management.CHILD_M (100 m)
CONTAINMENT_MAX_M2 = 10_000.0   # at most 1 ha
CONTAINMENT_GAP_M = 500.0       # away from the nearest other stand
PROGRAMME_MIN_M2 = 10_000.0     # at least 1 ha
SENSITIVE = {"preschool", "place_of_learning", "education", "specialty_school", "college_university", "hospital",
             "health_care", "outpatient_care_facility", "park", "playground", "sport_or_fitness_facility",
             "sports_and_recreation", "social_or_community_service", "campground", "beach"}


def _dist(gdf, layer, mask=None):
    l = layer if layer is None or mask is None else layer[mask]
    if l is None or len(l) == 0:
        return np.full(len(gdf), np.inf)
    if l.crs != gdf.crs:
        l = l.to_crs(gdf.crs)
    j = gpd.sjoin_nearest(gdf[["geometry"]].reset_index(), l[["geometry"]], how="left", distance_col="d")
    return j.groupby("index")["d"].min().reindex(range(len(gdf))).to_numpy()


def add_priority(gdf: gpd.GeoDataFrame, places, roads, water, infra, landuse=None) -> gpd.GeoDataFrame:
    """Score hotspots. `landuse` adds the territories of kindergartens, schools and playgrounds to the child layer,
    the same layer the treatment rules use (invaradar.layers)."""
    g = gdf.reset_index(drop=True).copy()
    cat = places["basic_category"].astype(str)
    # Project each source once. Roads feed both the road and the rail distance.
    places_m = places.to_crs(g.crs)
    roads_m = roads.to_crs(g.crs)
    water_m = water.to_crs(g.crs)
    infra_m = infra.to_crs(g.crs)
    g["d_child_m"] = _dist(g, child_facilities(places_m, landuse, g.crs))
    g["d_sensitive_m"] = np.minimum(_dist(g, places_m, cat.isin(SENSITIVE)), g["d_child_m"])  # children are sensitive too
    g["d_road_m"] = _dist(g, roads_m, roads_m["subtype"] == "road")
    g["d_rail_m"] = _dist(g, roads_m, roads_m["subtype"] == "rail")
    g["d_water_m"] = _dist(g, water_m)
    g["d_power_m"] = _dist(g, infra_m)
    exposure = np.maximum(np.exp(-g.d_sensitive_m / 300.0), np.exp(-g.d_child_m / 500.0))
    spread = np.maximum.reduce([np.exp(-g.d_road_m / 100.0), np.exp(-g.d_rail_m / 100.0),
                                np.exp(-g.d_water_m / 100.0), np.exp(-g.d_power_m / 50.0)])
    size = np.clip(np.log10(g.area_m2 / 100.0) / 2.0, 0, 1)  # 100 m^2 → 0, 10 000 m^2 → 1
    g["exposure"] = exposure; g["spread"] = spread; g["size_f"] = size
    g["priority"] = 100 * g.mean_rank * (0.4 + 0.6 * exposure) * (0.6 + 0.4 * spread) * (0.5 + 0.5 * size)
    g = g.sort_values("priority", ascending=False).reset_index(drop=True)
    g["rank"] = np.arange(1, len(g) + 1)
    return assign_queues(g)


def _rank_positive(score: np.ndarray) -> np.ndarray:
    """1..n for positive scores, 0 where the stand is not in that queue."""
    rank = np.zeros(len(score), dtype=int)
    order = np.argsort(-score, kind="stable")
    place = 1
    for i in order:
        if score[i] <= 0:
            break
        rank[i] = place
        place += 1
    return rank


def assign_queues(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Three queues. Safety ignores area. Containment prefers small isolated stands. Programme is the large stands.

    The existing `priority` column is unchanged. The straight-line route follows that score, which includes
    area. `safety_rank` is a separate list and does not reorder the route.
    """
    g = gdf.copy()
    n = len(g)
    if n == 0:
        g["isolation_m"] = np.array([], dtype=float)
        g["safety_score"] = np.array([], dtype=float)
        g["containment_score"] = np.array([], dtype=float)
        g["programme_score"] = np.array([], dtype=float)
        g["safety_rank"] = np.array([], dtype=int)
        g["containment_rank"] = np.array([], dtype=int)
        g["programme_rank"] = np.array([], dtype=int)
        return g
    cents = g.geometry.centroid
    if n == 1:
        isolation = np.array([np.inf])
    else:
        # Nearest other centroid. The second neighbour is the first that is not the point itself.
        xy = np.column_stack([cents.x.to_numpy(), cents.y.to_numpy()])
        isolation = cKDTree(xy).query(xy, k=2)[0][:, 1]
    g["isolation_m"] = isolation
    exposure = g["exposure"].to_numpy() if "exposure" in g else np.ones(n)
    spread = g["spread"].to_numpy() if "spread" in g else np.ones(n)
    mean_rank = g["mean_rank"].to_numpy()
    child = g["d_child_m"].to_numpy() if "d_child_m" in g else np.full(n, np.inf)
    area = g["area_m2"].to_numpy()
    g["safety_score"] = np.where(child <= SAFETY_CHILD_M, mean_rank * exposure, 0.0)
    isolated = (area <= CONTAINMENT_MAX_M2) & (isolation >= CONTAINMENT_GAP_M)
    g["containment_score"] = np.where(
        isolated, mean_rank * spread * np.clip(isolation / CONTAINMENT_GAP_M, 0.0, 5.0), 0.0)
    g["programme_score"] = np.where(area >= PROGRAMME_MIN_M2, exposure, 0.0)
    g["safety_rank"] = _rank_positive(g["safety_score"].to_numpy())
    g["containment_rank"] = _rank_positive(g["containment_score"].to_numpy())
    g["programme_rank"] = _rank_positive(g["programme_score"].to_numpy())
    return g
