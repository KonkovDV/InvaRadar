"""The district crew follows roads. These cases use a few lines, not the city extract."""
import importlib.util
import json
from pathlib import Path

from shapely.geometry import LineString, Point

from invaradar.road_route import open_tour, route_stops

ROOT = Path(__file__).resolve().parents[1]


def test_nearest_neighbour_then_two_opt_untangles_the_middle():
    # NN walks 0-1-2-3-4. Reversing the middle pair is shorter: 0-1-3-2-4.
    distance = [
        [0, 1, 10, 10, 10],
        [1, 0, 3, 3, 100],
        [10, 3, 0, 1, 2],
        [10, 3, 1, 0, 10],
        [10, 100, 2, 10, 0],
    ]
    order = open_tour(distance)
    assert order[0] == 0
    assert order == [0, 1, 3, 2, 4]
    length = sum(distance[order[i]][order[i + 1]] for i in range(4))
    assert length == 1 + 3 + 1 + 2


def test_a_crossing_is_a_junction_and_the_walk_is_separate():
    roads = [LineString([(0, 0), (100, 0)]), LineString([(50, -40), (50, 40)])]
    # The second stop sits a metre off the crossing, so the drive is not the straight line.
    out = route_stops([Point(0, 0), Point(51, 40)], roads)
    assert out["order"] == [0, 1]
    assert abs(out["driving_m"] - 90) < 0.05
    assert abs(out["access_m"][1] - 1) < 0.05
    assert abs(out["line"].length - (out["driving_m"] + out["access_m"][0] + out["access_m"][1])) < 0.1


def test_a_short_fragment_does_not_steal_the_stop_from_the_long_road():
    roads = [LineString([(0, 0), (50, 0), (100, 0)]), LineString([(0, 5), (1, 5)])]
    out = route_stops([Point(0, 6), Point(100, 0)], roads)
    # The stub is one metre from the first stop. The connected road is six metres away.
    assert abs(out["access_m"][0] - 6) < 0.05
    assert abs(out["driving_m"] - 100) < 0.05


def test_the_road_order_skips_a_euclidean_neighbour_behind_a_detour():
    # Stop 1 is five metres from the depot and only reachable the long way around.
    # Stop 2 is eighty metres away on a direct road.
    roads = [
        LineString([(0, 0), (0, 100), (200, 100), (200, 0), (5, 0)]),
        LineString([(0, 0), (0, -10), (80, -10)]),
    ]
    out = route_stops([Point(0, 0), Point(5, 0), Point(80, -10)], roads)
    assert out["order"] == [0, 2, 1]
    assert out["driving_m"] > out["straight_m"]


def test_the_south_moscow_road_tour_is_the_line_on_the_map():
    record = json.loads((ROOT / "outputs" / "heracleum" / "route_district_roads.json").read_text(encoding="utf-8"))
    assert record["driving_km"] == 31.57
    assert record["straight_km"] == 18.05
    assert record["access_m"] == 1334.6
    assert record["max_access_m"] == 265.2
    assert record["stops"] == 15
    assert record["order"][0] == 0
    assert record["oneway_known"] is False
    web = json.loads((ROOT / "web" / "data" / "route_district.geojson").read_text(encoding="utf-8"))
    assert web["features"][0]["properties"]["driving_km"] == 31.57
    assert "service" not in record["classes"]
    spec = importlib.util.spec_from_file_location("export_web_route", ROOT / "scripts" / "export_web.py")
    export = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export)
    assert export.route_for_web().name == "route_district_roads_2025.geojson"
