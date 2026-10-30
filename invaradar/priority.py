"""Priority of hotspots: likelihood x human exposure x spread potential x size.

Hotspots (connected components of the top 2 % of the landscape, >= 4 pixels) and the daily route (nearest
neighbour + 2-opt) are computed by the Rust core; this module only scores them. Every factor is transparent:
the operator sees each distance and multiplier in the survey queue.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np

from .layers import child_facilities

HOT_PCT = 0.98         # pixel must outrank 98 % of the study area
MIN_PX = 4             # >= 400 m^2
SENSITIVE = {"preschool", "place_of_learning", "education", "specialty_school", "college_university", "hospital",
             "health_care", "outpatient_care_facility", "park", "playground", "sport_or_fitness_facility",
             "sports_and_recreation", "social_or_community_service", "campground", "beach"}


def _dist(gdf, layer, mask=None):
    l = layer if layer is None or mask is None else layer[mask]
    if l is None or len(l) == 0:
        return np.full(len(gdf), np.inf)
    l = l.to_crs(gdf.crs)
    j = gpd.sjoin_nearest(gdf[["geometry"]].reset_index(), l[["geometry"]], how="left", distance_col="d")
    return j.groupby("index")["d"].min().reindex(range(len(gdf))).to_numpy()


def add_priority(gdf: gpd.GeoDataFrame, places, roads, water, infra, landuse=None) -> gpd.GeoDataFrame:
    """Score hotspots. `landuse` adds the territories of kindergartens, schools and playgrounds to the child layer,
    the same layer the treatment rules use (invaradar.layers)."""
    g = gdf.reset_index(drop=True).copy()
    cat = places["basic_category"].astype(str)
    g["d_child_m"] = _dist(g, child_facilities(places, landuse, g.crs))
    g["d_sensitive_m"] = np.minimum(_dist(g, places, cat.isin(SENSITIVE)), g["d_child_m"])  # children are sensitive too
    g["d_road_m"] = _dist(g, roads, roads["subtype"] == "road")
    g["d_rail_m"] = _dist(g, roads, roads["subtype"] == "rail")
    g["d_water_m"] = _dist(g, water)
    g["d_power_m"] = _dist(g, infra)
    exposure = np.maximum(np.exp(-g.d_sensitive_m / 300.0), np.exp(-g.d_child_m / 500.0))
    spread = np.maximum.reduce([np.exp(-g.d_road_m / 100.0), np.exp(-g.d_rail_m / 100.0),
                                np.exp(-g.d_water_m / 100.0), np.exp(-g.d_power_m / 50.0)])
    size = np.clip(np.log10(g.area_m2 / 100.0) / 2.0, 0, 1)  # 100 m^2 → 0, 10 000 m^2 → 1
    g["exposure"] = exposure; g["spread"] = spread; g["size_f"] = size
    g["priority"] = 100 * g.mean_rank * (0.4 + 0.6 * exposure) * (0.6 + 0.4 * spread) * (0.5 + 0.5 * size)
    g = g.sort_values("priority", ascending=False).reset_index(drop=True)
    g["rank"] = np.arange(1, len(g) + 1)
    return g
