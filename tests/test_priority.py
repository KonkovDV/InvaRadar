"""Hotspot priority: closer to children and spread corridors means higher priority, all else equal."""
import geopandas as gpd
from shapely.geometry import LineString, Point

from invaradar.priority import add_priority, assign_queues

CRS = 32637


def test_priority_rises_near_children_and_corridors():
    hot = gpd.GeoDataFrame({"mean_rank": [0.99, 0.99, 0.99]},
                           geometry=[Point(0, 0).buffer(20), Point(5_000, 0).buffer(20), Point(10_000, 5_000).buffer(20)],
                           crs=CRS)
    hot["area_m2"] = hot.area
    places = gpd.GeoDataFrame({"basic_category": ["preschool"]}, geometry=[Point(50, 0)], crs=CRS)
    roads = gpd.GeoDataFrame({"subtype": ["road", "rail"]},
                             geometry=[LineString([(5_000, -100), (5_000, 100)]), LineString([(20_000, 0), (20_001, 0)])],
                             crs=CRS)
    water = gpd.GeoDataFrame(geometry=[LineString([(30_000, 0), (30_001, 0)])], crs=CRS)
    infra = gpd.GeoDataFrame(geometry=[LineString([(40_000, 0), (40_001, 0)])], crs=CRS)
    g = add_priority(hot, places, roads, water, infra)
    by_x = g.set_index(g.geometry.centroid.x.round())
    assert by_x.loc[0, "priority"] > by_x.loc[5_000, "priority"] > by_x.loc[10_000, "priority"]
    assert list(g["rank"]) == [1, 2, 3]


def test_playground_territory_counts_as_child_facility():
    hot = gpd.GeoDataFrame({"mean_rank": [0.99]}, geometry=[Point(0, 0).buffer(20)], crs=CRS)
    hot["area_m2"] = hot.area
    places = gpd.GeoDataFrame({"basic_category": ["preschool"]}, geometry=[Point(5_000, 0)], crs=CRS)
    landuse = gpd.GeoDataFrame({"class": ["playground"], "subtype": ["recreation"]},
                               geometry=[Point(60, 0).buffer(10)], crs=CRS)
    empty = gpd.GeoDataFrame({"subtype": []}, geometry=[], crs=CRS)
    without = add_priority(hot, places, empty, empty, empty)
    with_lu = add_priority(hot, places, empty, empty, empty, landuse)
    assert round(without.d_child_m[0]) == 4_980 and round(with_lu.d_child_m[0]) == 30
    assert with_lu.d_sensitive_m[0] <= with_lu.d_child_m[0]
    assert with_lu.priority[0] > without.priority[0]


def test_safety_ignores_area_and_containment_prefers_a_small_isolated_stand():
    g = gpd.GeoDataFrame(
        {
            "mean_rank": [0.99, 0.99, 0.99],
            "area_m2": [300.0, 200_000.0, 400.0],
            "d_child_m": [40.0, 40.0, 5_000.0],
            "exposure": [0.9, 0.9, 0.2],
            "spread": [0.2, 0.2, 0.95],
        },
        geometry=[Point(0, 0).buffer(5), Point(80, 0).buffer(30), Point(3_000, 0).buffer(8)],
        crs=CRS,
    )
    q = assign_queues(g)
    assert q.safety_score[0] == q.safety_score[1] > q.safety_score[2]
    assert q.containment_rank[2] == 1 and q.containment_score[1] == 0
    assert q.programme_rank[1] == 1 and q.programme_score[0] == 0
