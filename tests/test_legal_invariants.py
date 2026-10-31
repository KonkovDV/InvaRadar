"""Invariants of the published artifacts.

The shipped work-order tables are the top 200 hotspots per species, and the web map is the top 3,000.
These tests read those files, not a freshly prescribed city, so a pipeline re-run that breaks a rule
inside the published tables or desynchronises the map fails CI. They do not re-check every hotspot
in the unreleased GeoParquet.
"""
import csv
import json

import pytest

from invaradar.config import OUT, ROOT

TAXA = ("heracleum", "solidago")
CHEM = ("опрыск", "с дрона", "точечная обработка")


def orders(taxon):
    with open(OUT / taxon / "work_orders_top200_2025.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def flag(v):
    return str(v).strip().lower() == "true"


def load(path):
    return json.loads((path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("taxon", TAXA)
def test_no_chemistry_where_the_law_or_children_forbid_it(taxon):
    for r in orders(taxon):
        banned = float(r["water_zone_m"]) > 0 or flag(r["in_protected"]) or flag(r["child_org_territory"]) \
            or flag(r["near_children"])
        if banned:
            assert not any(w in r["method"] for w in CHEM), (r["rank"], r["method"])


@pytest.mark.parametrize("taxon", TAXA)
def test_no_drone_spraying_inside_settlements(taxon):
    for r in orders(taxon):
        if flag(r["in_settlement"]):
            assert "с дрона" not in r["method"], (r["rank"], r["method"])


@pytest.mark.parametrize("taxon", TAXA)
def test_no_digging_near_heritage(taxon):
    for r in orders(taxon):
        if flag(r["near_heritage"]):
            assert "ниже земли" not in r["method"] and "выборка корневищ" not in r["method"], r["rank"]
            assert "корневой шейки" not in r["method"], r["rank"]


@pytest.mark.parametrize("taxon", TAXA)
def test_every_restriction_is_cited(taxon):
    for r in orders(taxon):
        if float(r["water_zone_m"]) > 0:
            assert "ВК РФ ст. 65" in r["legal_basis"]
        if flag(r["child_org_territory"]):
            assert "СанПиН 2.1.3684-21 п. 273" in r["legal_basis"]
        if flag(r["near_heritage"]):
            assert "73-ФЗ" in r["legal_basis"]


@pytest.mark.parametrize("taxon", TAXA)
def test_reported_numbers_are_consistent(taxon):
    m = load(OUT / taxon / "metrics.json")["hotspots"]
    p = load(OUT / taxon / "enrich_summary.json")["prescriptions"]
    assert p["drone_spraying_allowed"] + p["ground_spot_treatment"] + p["mechanical_only"] == p["hotspots"] == m["count"]
    assert p["child_org_territory"] <= p["near_children_100m"] <= p["near_children_300m"]
    assert m["within_100m_of_child_facility"] == p["near_children_100m"]
    assert m["within_300m_of_child_facility"] == p["near_children_300m"]
    assert p["in_water_zone_no_pesticides"] <= p["mechanical_only"]
    assert sum(p["water_zone_by_width_m"].values()) == p["in_water_zone_no_pesticides"]


@pytest.mark.parametrize("taxon", TAXA)
def test_web_map_matches_the_results(taxon):
    w = load(ROOT / "web" / "data" / "summary.json")[taxon]
    p = load(OUT / taxon / "enrich_summary.json")["prescriptions"]
    assert (w["hotspots"], w["mechanical"], w["ground"], w["drone"], w["near_children_100m"]) == \
        (p["hotspots"], p["mechanical_only"], p["ground_spot_treatment"], p["drone_spraying_allowed"],
         p["near_children_100m"])
    pts = load(ROOT / "web" / "data" / f"{taxon}_top.geojson")["features"]
    assert len(pts) == w["shown"]
    for f in pts:
        q = f["properties"]
        if q["water_zone_m"] > 0:
            assert q["cls"] == "mechanical" and "ВК РФ ст. 65" in q["basis"]
