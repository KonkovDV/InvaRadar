"""Связка с InvaRadar: наряды `work_orders_top200_<год>.csv` → сигналы и правовой контекст Pro.

InvaRadar (коммит cdf3b95) пишет флаги, из которых закон выбирает метод: водоохранная зона,
ООПТ, территория детской организации, расстояние до детей, ОКН, населённый пункт, ЗСО, юрисдикция.
Pro пересчитывает метод своими YAML-правилами и сверяет инварианты с исходным нарядом.
"""
from __future__ import annotations

import csv
from pathlib import Path

BOOL = {"true": True, "false": False, "1": True, "0": False}
FLOAT_COLS = ("priority", "lat", "lon", "area_m2", "mean_rank", "water_zone_m", "d_child_m")
BOOL_COLS = ("inside_aoa", "in_protected", "child_org_territory", "near_children", "near_heritage",
             "in_settlement", "in_zso")


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_work_orders(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for c in FLOAT_COLS:
                if c in r:
                    r[c] = _float(r[c])
            for c in BOOL_COLS:
                if c in r:
                    r[c] = BOOL.get(str(r[c]).strip().lower())
            r["rank"] = int(r["rank"]) if r.get("rank") else None
            rows.append(r)
    return rows


def law_context(row: dict, taxon: str, **extra) -> dict:
    """Контекст для LawEngine. Чего нет в наряде InvaRadar — None (правила откажут в безопасную сторону)."""
    jur = (row.get("jurisdiction") or "unknown").strip() or "unknown"
    ctx = {
        "taxon": taxon,
        "area_m2": row.get("area_m2"),
        "water_zone_m": row.get("water_zone_m"),
        "in_protected": row.get("in_protected"),
        "child_org_territory": row.get("child_org_territory"),
        "d_child_m": row.get("d_child_m"),
        "near_heritage": row.get("near_heritage"),
        "in_settlement": row.get("in_settlement"),
        "in_zso": row.get("in_zso"),
        "jurisdiction": jur,
        "holder_type": None,
        "d_settlement_m": None, "d_drinking_water_m": None, "d_protected_m": None, "d_fishery_water_m": None,
    }
    ctx.update(extra)
    return ctx


def signal_payload(row: dict, taxon: str) -> dict:
    return {
        "source": "invaradar",
        "taxon": taxon,
        "lat": row["lat"], "lon": row["lon"], "area_m2": row.get("area_m2"),
        "priority": row.get("priority"), "mean_rank": row.get("mean_rank"), "inside_aoa": row.get("inside_aoa"),
        "upstream": {"rank": row.get("rank"), "method": row.get("method"), "legal_basis": row.get("legal_basis"),
                     "status": row.get("status"), "commit": "cdf3b95"},
    }
