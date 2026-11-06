"""Legal rules of the treatment prescriptions: water protection zones and method choice."""
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

from invaradar.management import (
    prescribe,
    river_width_m,
    split_survey_units,
    summarize,
    water_zones,
    watercourse_lengths,
)

CRS = 32637


def line(x0, y0, x1, y1, n=10):
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    return LineString(list(zip(xs, ys)))


def test_an_order_is_drone_or_ground_or_mechanical():
    from invaradar.management import method_class
    assert method_class("точечное опрыскивание с дрона по контурам") == "drone"
    assert method_class("наземная точечная обработка ранцевым опрыскивателем") == "ground"
    assert method_class("покос не реже 1 раза в 2 недели") == "mechanical"
    with pytest.raises(ValueError):
        method_class("с дрона, а если нельзя — наземная точечная обработка")


@pytest.mark.parametrize("length,width", [(3_000, 50), (9_999, 50), (10_000, 100), (49_000, 100), (50_000, 200)])
def test_river_width_follows_water_code(length, width):
    assert river_width_m(length) == width


def network():
    # main river flows east in three segments (60 km); a 12 km tributary joins it; a 3 km stream joins the tributary
    segs = [line(0, 0, 30_000, 0), line(30_000, 0, 45_000, 0), line(45_000, 0, 60_000, 0),
            line(30_000, 12_000, 30_000, 3_000), line(30_000, 3_000, 30_000, 0),
            line(27_000, 3_000, 30_000, 3_000)]
    return gpd.GeoDataFrame({"class": ["river"] * 6, "subtype": ["river"] * 6}, geometry=segs, crs=CRS)


def test_main_stem_and_tributaries_are_separated():
    L = watercourse_lengths(network())
    assert np.allclose(L[:3], 60_000)          # the main stem keeps its full length through the confluence
    assert np.allclose(L[3:5], 12_000)         # the tributary is a watercourse of its own
    assert np.isclose(L[5], 3_000)             # the stream ends where it meets the longer branch


def test_shared_source_does_not_hand_the_main_stem_to_a_short_spur():
    """A source shared by two branches must count for both when the main stem is chosen.

    40 km of upstream splits into a 1 km spur and a ~40 km branch; they meet again.
    If the upstream walk forgets to leave a segment, the spur is measured as if it
    owned the source and the river below the reunion is given the spur's length.
    Water Code art. 65 part 4 would then assign 50 m instead of 200 m.
    """
    # Downstream is stored first, the short spur before the long branch: that is a
    # normal OSM order, and it is the order in which a depth-first walk used to
    # freeze the wrong upstream length.
    segs = [line(41_000, 0, 42_000, 0),            # downstream of the reunion
            line(40_000, 0, 41_000, 0),            # 1 km spur
            line(0, 0, 40_000, 0),                 # 40 km source
            line(40_000, 0, 40_000, 20_000),       # long branch
            line(40_000, 20_000, 41_000, 0)]       # long branch back to the reunion
    g = gpd.GeoDataFrame({"class": ["river"] * 5}, geometry=segs, crs=CRS)
    L = watercourse_lengths(g)
    assert (L > 50_000).sum() == 4
    assert (L < 2_000).sum() == 1
    assert np.allclose(L[L > 50_000], L[L > 50_000][0])


def test_water_zone_widths_for_rivers_lakes_and_ponds():
    rivers = network()
    lake = box(70_000, 0, 70_800, 800)          # 0.64 km² → 50 m
    pond = box(80_000, 0, 80_200, 200)          # 0.04 km², isolated → no zone
    on_river = box(10_000, 5, 10_100, 105)      # pond on the main river → river width
    extra = gpd.GeoDataFrame({"class": ["lake", "pond", "pond"], "subtype": ["lake", "pond", "pond"]},
                             geometry=[lake, pond, on_river], crs=CRS)
    z = water_zones(gpd.pd.concat([rivers, extra], ignore_index=True), CRS)
    assert list(z.zone_m[:3]) == [200, 200, 200]
    assert z.zone_m[3] == 100 and z.zone_m[5] == 50
    assert z.zone_m[6] == 50 and z.zone_m[7] == 0 and z.zone_m[8] == 200


def test_prescription_follows_water_code_sanpin_and_heritage():
    water = gpd.GeoDataFrame({"class": ["stream"], "subtype": ["stream"]}, geometry=[line(0, 0, 0, 5_000)], crs=CRS)
    landuse = gpd.GeoDataFrame(
        {"class": ["playground", "residential", "kindergarten"], "subtype": ["recreation", "residential", "education"]},
        geometry=[box(1_000, 0, 1_020, 20), box(5_000, 0, 5_100, 100), box(30_000, 0, 30_100, 100)], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": ["historic_site"]}, geometry=[Point(9_000, 0)], crs=CRS)
    localities = gpd.GeoDataFrame({"names": ["{'primary': 'Город'}", "{'primary': 'Новый район'}"],
                                   "class": ["land", "land"]},
                                  geometry=[box(40_000, 0, 42_000, 2_000), box(50_000, 0, 52_000, 2_000)], crs=CRS)
    hot = gpd.GeoDataFrame(geometry=[Point(30, 2_000).buffer(10),        # 0: 30 m from a stream
                                     Point(1_060, 10).buffer(10),        # 1: 40 m from a playground
                                     Point(5_600, 50).buffer(10),        # 2: 500 m from housing
                                     Point(9_030, 0).buffer(10),         # 3: 30 m from a monument
                                     Point(20_000, 0).buffer(10),        # 4: nothing within 700 m
                                     Point(30_050, 50).buffer(10),       # 5: inside a kindergarten
                                     Point(41_000, 1_000).buffer(10),    # 6: inside a town
                                     Point(51_000, 1_000).buffer(10)],   # 7: inside an administrative «район»
                           crs=CRS)
    p = prescribe(hot, "heracleum", water, landuse, places, localities)
    chem = p.method.str.contains("наземная|опрыскивание")
    # Water Code art. 65 part 15 items 3 and 6: no aerial measures and no pesticides at all inside the zone
    assert p.in_water_zone[0] and p.water_zone_m[0] == 50 and not chem[0]
    assert "п. 3 и 6" in p.legal_basis[0]
    assert p.near_children[1] and not chem[1]
    # СанПиН п. 282: unmanned aircraft keep 700 m from settlements → ground treatment only
    assert p.near_settlement_uav[2] and p.method[2].startswith("наземная точечная обработка")
    assert p.near_heritage[3] and "без перекопки" in p.method[3]
    assert p.method[4].startswith("точечное опрыскивание с дрона")
    # СанПиН п. 273: pesticides are banned on the territories of children's organisations
    assert p.child_org_territory[5] and not chem[5] and "п. 273" in p.legal_basis[5]
    assert p.in_settlement[6] and p.method[6].startswith("наземная точечная обработка")
    assert "до 7:00" in p.method[6] and "после 22:00" in p.method[6]
    assert "до 7:00" not in p.method[4]
    assert not p.in_settlement[7] and p.method[7].startswith("точечное опрыскивание с дрона")
    assert (p.follow_up_years == 5).all()
    s = summarize(p)
    assert s["drone_spraying_allowed"] + s["ground_spot_treatment"] + s["mechanical_only"] == len(p)
    assert s["in_water_zone_no_pesticides"] == 1 and s["child_org_territory"] == 1


def test_solidago_in_water_zone_is_mown_not_sprayed():
    water = gpd.GeoDataFrame({"class": ["river"], "subtype": ["river"]}, geometry=[line(0, 0, 60_000, 0)], crs=CRS)
    empty = gpd.GeoDataFrame({"class": [], "subtype": []}, geometry=[], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    hot = gpd.GeoDataFrame(geometry=[Point(10_000, 150).buffer(10)], crs=CRS)  # 150 m from a 60 km river → 200 m zone
    p = prescribe(hot, "solidago", water, empty, places)
    assert p.water_zone_m[0] == 200 and p.method[0].startswith("покос дважды")


def test_stream_width_follows_its_length_and_a_ditch_stays_narrow():
    water = gpd.GeoDataFrame({"class": ["stream", "ditch"], "subtype": ["stream", "ditch"]},
                             geometry=[line(0, 0, 15_000, 0), line(0, 500, 1_000, 500)], crs=CRS)
    z = water_zones(water, CRS)
    assert z.zone_m.iloc[0] == 100          # 15 km stream → 100 m, not a flat 50 m
    assert z.zone_m.iloc[1] == 50           # ditch: a caution of this system, not art. 65 part 9
    assert "ч. 9" not in z.zone_note.iloc[1] and z.zone_note.iloc[0] == ""


def test_a_long_canal_keeps_the_right_of_way_rule_and_not_a_river_width():
    water = gpd.GeoDataFrame({"class": ["canal"], "subtype": ["canal"]},
                             geometry=[line(0, 0, 60_000, 0)], crs=CRS)
    z = water_zones(water, CRS)
    assert z.zone_m.iloc[0] == 0
    assert "ч. 9" in z.zone_note.iloc[0] and "полосе отвода" in z.zone_note.iloc[0]


def test_a_pond_takes_the_wider_connected_river_not_the_nearer_ditch():
    """A ditch 10 m away must not hide a river 20 m away.

    sjoin_nearest would return only the ditch and leave the pond at 50 m.
    Water Code art. 65 keeps the river width for a water body connected to that river.
    """
    ditch = line(0, 0, 1_000, 0)
    river = line(0, 25, 60_000, 25)
    pond = box(8, 8, 14, 14)  # ~10 m from the ditch, ~11–17 m from the river
    water = gpd.GeoDataFrame({"class": ["ditch", "river", "pond"]}, geometry=[ditch, river, pond], crs=CRS)
    z = water_zones(water, CRS)
    assert z.zone_m.iloc[0] == 50
    assert z.zone_m.iloc[1] == 200
    assert z.zone_m.iloc[2] == 200


def test_a_ditch_caution_does_not_grow_into_the_aerial_buffer():
    """50 m around a ditch is a caution. СанПиН item 282's 700 m is for fishery waters.

    A stand 200 m from a ditch is outside the caution and may be sprayed from a drone.
    A stand 400 m from a long river is outside the 200 m zone and still inside the 700 m buffer.
    """
    empty = gpd.GeoDataFrame({"class": [], "subtype": []}, geometry=[], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    ditch = gpd.GeoDataFrame({"class": ["ditch"], "subtype": ["ditch"]},
                             geometry=[line(0, 0, 1_000, 0)], crs=CRS)
    near = gpd.GeoDataFrame(geometry=[Point(500, 200).buffer(10)], crs=CRS)
    p = prescribe(near, "heracleum", ditch, empty, places)
    assert not p.in_water_zone[0] and p.method[0].startswith("точечное опрыскивание с дрона")
    close = gpd.GeoDataFrame(geometry=[Point(500, 30).buffer(5)], crs=CRS)
    c = prescribe(close, "heracleum", ditch, empty, places)
    assert c.in_water_zone[0] and "с дрона" not in c.method[0]
    river = gpd.GeoDataFrame({"class": ["river"], "subtype": ["river"]},
                             geometry=[line(0, 0, 60_000, 0)], crs=CRS)
    buffered = gpd.GeoDataFrame(geometry=[Point(10_000, 400).buffer(10)], crs=CRS)
    r = prescribe(buffered, "heracleum", river, empty, places)
    assert not r.in_water_zone[0] and r.method[0].startswith("наземная")


def test_a_short_first_segment_does_not_steal_the_main_stem():
    """71 km stem (40 + 1 + 30) and a 5 km tributary longer than the 1 km piece.

    Choosing the longest next segment would follow the tributary and give every reach 100 m.
    Water Code art. 65 part 4 needs 200 m on the stem and 50 m on the tributary.
    """
    segs = [line(0, 0, 40_000, 0), line(40_000, 0, 41_000, 0), line(41_000, 0, 71_000, 0),
            line(40_000, 0, 40_000, 5_000)]
    g = gpd.GeoDataFrame({"class": ["river"] * 4}, geometry=segs, crs=CRS)
    L = watercourse_lengths(g)
    assert np.allclose(L[:3], 71_000)
    assert np.isclose(L[3], 5_000)
    assert river_width_m(L[0]) == 200 and river_width_m(L[3]) == 50


def test_herbicide_orders_name_apiaries_airspace_and_protective_clothing():
    water = gpd.GeoDataFrame({"class": ["stream"], "subtype": ["stream"]}, geometry=[line(0, 0, 0, 100)], crs=CRS)
    empty = gpd.GeoDataFrame({"class": [], "subtype": []}, geometry=[], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    far = gpd.GeoDataFrame(geometry=[Point(20_000, 0).buffer(10)], crs=CRS)
    p = prescribe(far, "heracleum", water, empty, places)
    assert "с дрона" in p.method[0]
    assert "воздушного пространства" in p.method[0]
    assert "перчатки" in p.method[0]
    assert "пасек" in p.method[0] and "7 км" in p.method[0]
    assert "2 недели" in p.method[0] or "герметичн" in p.method[0]
    assert p.status[0] == "candidate" and p.signed_by[0] == ""
    assert p.follow_up_years[0] == 5
    assert "наблюдение 5 сезонов" in p.method[0]
    assert p.listed_species_act[0] == "юрисдикция не определена"


def test_large_heracleum_stand_is_mown_not_dug_by_hand():
    water = gpd.GeoDataFrame({"class": [], "subtype": []}, geometry=[], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    hot = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 100), box(1_000, 0, 1_020, 20)], crs=CRS)  # 1 ha and 400 m²
    hot["area_m2"] = hot.area
    p = prescribe(hot, "heracleum", water, water, places)
    assert "многократный покос" in p.method[0] and "на краях очага" in p.method[0]
    assert "подрезка корневой шейки на 5–10 см" in p.method[1]


def test_drinking_water_zone_and_a_farm_block_chemicals():
    water = gpd.GeoDataFrame({"class": ["stream"], "subtype": ["stream"]}, geometry=[line(0, 0, 0, 80)], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    hot = gpd.GeoDataFrame(geometry=[Point(0, 0).buffer(8), Point(5_000, 0).buffer(8)], crs=CRS)
    hot["area_m2"] = hot.area
    zso = gpd.GeoDataFrame(geometry=[box(-30, -30, 30, 30)], crs=CRS)
    farms = gpd.GeoDataFrame({"class": ["farmyard"], "subtype": ["farmyard"]},
                             geometry=[Point(5_400, 0).buffer(20)], crs=CRS)
    p = prescribe(hot, "heracleum", water, farms, places, zso=zso)
    assert p.in_zso[0] and "санитарной охраны" in p.legal_basis[0]
    assert "опрыск" not in p.method[0] and "с дрона" not in p.method[0]
    assert p.near_farm_uav[1] and p.method[1].startswith("наземная точечная обработка")


def test_moscow_list_is_verified_and_the_oblast_list_is_not():
    empty = gpd.GeoDataFrame({"class": [], "subtype": []}, geometry=[], crs=CRS)
    places = gpd.GeoDataFrame({"basic_category": []}, geometry=[], crs=CRS)
    hot = gpd.GeoDataFrame(geometry=[Point(100, 100).buffer(5), Point(5_000, 100).buffer(5)], crs=CRS)
    hot["area_m2"] = hot.area
    regions = gpd.GeoDataFrame(
        {"jurisdiction": ["moscow_city", "moscow_oblast"]},
        geometry=[box(0, 0, 1_000, 1_000), box(4_000, 0, 8_000, 1_000)],
        crs=CRS,
    )
    city = prescribe(hot.iloc[[0]], "heracleum", empty, empty, places, regions=regions)
    oblast = prescribe(hot.iloc[[1]], "heracleum", empty, empty, places, regions=regions)
    outside = prescribe(hot.iloc[[0]], "acer", empty, empty, places, regions=regions)
    assert city.jurisdiction[0] == "moscow_city" and "369-ПП" in city.listed_species_act[0]
    assert "не сверен" in oblast.listed_species_act[0]
    assert outside.listed_species_act[0].startswith("вне обязательного перечня")


def test_a_five_hectare_stand_splits_into_survey_units():
    stand = gpd.GeoDataFrame({"hid": [1]}, geometry=[box(0, 0, 224, 224)], crs=CRS)
    units = split_survey_units(stand, cell_m=100)
    assert len(units) >= 5
    assert units.parent_hid.eq(1).all()
    assert abs(units.area_m2.sum() - stand.geometry.area.sum()) < 1.0
