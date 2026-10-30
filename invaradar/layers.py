"""Context layers shared by the survey queue (priority.py) and the treatment rules (management.py).

One definition per layer, so the queue and the work orders count the same kindergartens, schools and
playgrounds and the same settlements.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

# children: Overture places (points) and land use (territories of kindergartens and schools, playgrounds)
CHILD_PLACES = {"preschool", "elementary_school", "middle_school", "high_school", "playground"}
CHILD_LANDUSE = {"playground", "kindergarten", "school"}
# territories of children's organisations, where СанПиН 2.1.3684-21 п. 273 bans pesticides outright
CHILD_ORG_LANDUSE = {"kindergarten", "school"}


def _geoms(*layers: gpd.GeoDataFrame | None, crs) -> gpd.GeoDataFrame:
    parts = [g[["geometry"]].to_crs(crs) for g in layers if g is not None and len(g)]
    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs)


def child_facilities(places: gpd.GeoDataFrame | None, landuse: gpd.GeoDataFrame | None, crs) -> gpd.GeoDataFrame:
    """Kindergartens, schools and playgrounds as points and territories."""
    p = None if places is None else places[places["basic_category"].astype(str).isin(CHILD_PLACES)]
    lu = None if landuse is None else landuse[landuse["class"].astype(str).isin(CHILD_LANDUSE)]
    return _geoms(p, lu, crs=crs)


def child_organisations(landuse: gpd.GeoDataFrame | None, crs) -> gpd.GeoDataFrame:
    """Territories of kindergartens and schools."""
    lu = None if landuse is None else landuse[landuse["class"].astype(str).isin(CHILD_ORG_LANDUSE)]
    return _geoms(lu, crs=crs)


def settlements(landuse: gpd.GeoDataFrame | None, localities: gpd.GeoDataFrame | None, crs) -> gpd.GeoDataFrame:
    """Settlements (населённые пункты): locality boundaries plus residential land use.

    Overture also tags some administrative districts of New Moscow as localities ("Краснопахорский район"); they hold
    fields and forest, not a single settlement, so names with «район» are dropped and their villages are taken
    from residential land use instead.
    """
    loc = None
    if localities is not None and len(localities):
        name = localities["names"].astype(str)
        loc = localities[~name.str.contains("район", case=False)]
        if "class" in loc:
            loc = loc[loc["class"].astype(str) == "land"]
    res = None if landuse is None else landuse[landuse["subtype"].astype(str) == "residential"]
    return _geoms(loc, res, crs=crs)
