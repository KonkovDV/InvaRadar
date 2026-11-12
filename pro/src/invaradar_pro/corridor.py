"""Аудит линейных объектов для обладателей публичного сервитута и полос отвода (294-ФЗ).

Для каждой линии (ЛЭП, дорога, железная дорога, трубопровод) — пикеты по километрам:
сколько очагов задевают охранную зону или полосу, какая площадь внутри неё, где самый высокий приоритет.
Это то, что сетевой компании или дорожной службе нужно до сезона: где работать и где риск предписания.

Охранные зоны ВЛ — Правила, утв. постановлением Правительства РФ от 24.02.2009 № 160 (приложение):
расстояние от крайнего провода по обе стороны. Для дорог, железных дорог и трубопроводов ширина
берётся из документов правообладателя; значения по умолчанию ниже — допущения, их надо заменить.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .geo import circle_strip_overlap, point_to_polyline, polyline_length

# (верхний предел класса напряжения, кВ; ширина зоны от крайнего провода, м) — ПП РФ № 160
POWER_ZONE_M = [(1.0, 2.0), (20.0, 10.0), (35.0, 15.0), (110.0, 20.0), (220.0, 25.0),
                (500.0, 30.0), (750.0, 40.0), (1150.0, 55.0)]
DEFAULT_HALF_WIDTH_M = {"road": 15.0, "rail": 25.0, "pipeline": 25.0}  # допущения: заменить данными владельца
DEFAULT_WIRE_SPREAD_M = {35.0: 3.0, 110.0: 4.0, 220.0: 6.0, 500.0: 9.0}  # полуразнос крайних проводов, оценка


def power_zone_m(kv: float) -> float:
    for upper, width in POWER_ZONE_M:
        if kv <= upper:
            return width
    raise ValueError(f"напряжение {kv} кВ вне таблицы")


@dataclass
class Line:
    id: str
    kind: str              # power | road | rail | pipeline
    owner: str
    xs: np.ndarray
    ys: np.ndarray
    voltage_kv: float | None = None
    half_width_m: float | None = None

    def half_width(self) -> float:
        if self.half_width_m is not None:
            return float(self.half_width_m)
        if self.kind == "power":
            if self.voltage_kv is None:
                raise ValueError(f"у ЛЭП {self.id} не указано напряжение")
            spread = next((v for k, v in sorted(DEFAULT_WIRE_SPREAD_M.items()) if self.voltage_kv <= k), 10.0)
            return power_zone_m(self.voltage_kv) + spread
        return DEFAULT_HALF_WIDTH_M[self.kind]


@dataclass
class SegmentFinding:
    line_id: str
    owner: str
    kind: str
    km_from: float
    km_to: float
    half_width_m: float
    n_foci: int
    area_in_zone_m2: float
    max_priority: float
    focus_ids: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        d = asdict(self)
        d["focus_ids"] = ";".join(self.focus_ids)
        return d


def audit(lines: list[Line], fx, fy, area_m2, priority, ids, segment_m: float = 1000.0) -> list[SegmentFinding]:
    fx, fy = np.asarray(fx, float), np.asarray(fy, float)
    area = np.asarray(area_m2, float)
    prio = np.asarray(priority, float)
    radius = np.sqrt(np.maximum(area, 0.0) / np.pi)
    out: list[SegmentFinding] = []
    for ln in lines:
        hw = ln.half_width()
        dist, chain = point_to_polyline(fx, fy, ln.xs, ln.ys)
        hit = dist - radius <= hw
        if not hit.any():
            continue
        overlap = circle_strip_overlap(radius, dist, hw)
        seg = np.floor(chain / segment_m).astype(int)
        for s in np.unique(seg[hit]):
            m = hit & (seg == s)
            out.append(SegmentFinding(
                line_id=ln.id, owner=ln.owner, kind=ln.kind, km_from=s * segment_m / 1000.0,
                km_to=(s + 1) * segment_m / 1000.0, half_width_m=hw, n_foci=int(m.sum()),
                area_in_zone_m2=float(np.round(np.sum(overlap[m]), 1)), max_priority=float(np.max(prio[m])),
                focus_ids=[str(i) for i in np.asarray(ids)[m]]))
    out.sort(key=lambda f: (-f.max_priority, f.line_id, f.km_from))
    return out


def summarize(lines: list[Line], findings: list[SegmentFinding], segment_m: float = 1000.0) -> list[dict]:
    rows = []
    for ln in lines:
        f = [x for x in findings if x.line_id == ln.id]
        length_km = polyline_length(ln.xs, ln.ys) / 1000.0
        n_seg = max(1, int(np.ceil(length_km * 1000.0 / segment_m)))
        rows.append({"line_id": ln.id, "owner": ln.owner, "kind": ln.kind, "length_km": round(length_km, 2),
                     "segments_with_foci": len(f), "share_segments": round(len(f) / n_seg, 3),
                     "foci": sum(x.n_foci for x in f), "area_in_zone_m2": round(sum(x.area_in_zone_m2 for x in f), 1)})
    return rows


def write_csv(findings: list[SegmentFinding], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [f.to_row() for f in findings]
    cols = list(SegmentFinding.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
