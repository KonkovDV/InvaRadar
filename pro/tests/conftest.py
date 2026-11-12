from pathlib import Path

import pytest
from invaradar_pro.events import EventLog
from invaradar_pro.law import LawEngine
from invaradar_pro.workflow import CaseStore

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"

SAFE = {"taxon": "heracleum", "area_m2": 2000.0, "water_zone_m": 0.0, "in_protected": False,
        "child_org_territory": False, "d_child_m": 900.0, "near_heritage": False, "in_settlement": False,
        "in_zso": False, "jurisdiction": "moscow_city", "holder_type": "legal_entity",
        "d_settlement_m": 1500.0, "d_drinking_water_m": 2000.0, "d_protected_m": 2000.0, "d_fishery_water_m": 2000.0,
        "uav_flights_restricted": False}


@pytest.fixture(scope="session")
def engine():
    return LawEngine()


@pytest.fixture
def store(engine):
    return CaseStore(EventLog(), engine.taxa, engine)


@pytest.fixture
def safe_ctx():
    return dict(SAFE)
