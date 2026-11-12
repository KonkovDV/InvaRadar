"""Re-measure published order points against the water layer and the city boundary.

The hotspot polygons are not in git, so a point can miss a zone the polygon touched.
A new measurement may only add a restriction: the water width becomes the wider of the
two, and the distance to the city boundary becomes the smaller of the two. Jurisdiction
follows the polygon that contains the point. A point that falls in neither polygon keeps
the jurisdiction already written.

usage: python scripts/recheck_orders.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, shape

from invaradar.config import DATA, EPSG, OUT, ROOT
from invaradar.jurisdictions import load_regions
from invaradar.legal import listed_act
from invaradar.management import CANAL_CLASS, _boundary_m, _jurisdiction, _near, method_class, water_zones

MECHANICAL_STARTS = (
    "покос не реже",
    "подрезка корневой шейки",
    "зонтики срезать",
    "покос дважды",
)
CANAL_SENTENCE = (
    "ВК РФ ст. 65 ч. 9: у канала нет полосы отвода в данных, пестициды не назначаются, "
    "пока ширина неизвестна"
)
OOPT_SENTENCE = (
    "порядок 369-ПП не действует на ООПТ, а слой охраны смешивает парк и резерват — нужен юрист"
)


def flag(value) -> bool:
    return str(value).strip().lower() == "true"


def strip_chemistry(method: str) -> str:
    """Drop a drone or ground spray prefix and keep the mechanical sentence."""
    starts = [method.find(mark) for mark in MECHANICAL_STARTS if method.find(mark) >= 0]
    if not starts:
        raise ValueError("no mechanical sentence in the order")
    return method[min(starts):]


def water_sentence(width: float) -> str:
    return (
        f"ВК РФ ст. 65 ч. 15 п. 3 и 6: водоохранная зона {width:.0f} м, "
        "пестициды и авиаобработка запрещены"
    )


def measure(points: gpd.GeoDataFrame, water, regions):
    wz = water_zones(water, points.crs)
    zone = np.zeros(len(points))
    for width in sorted(set(wz.zone_m[wz.zone_m > 0])):
        inside = _near(points, wz[wz.zone_m == width], float(width))
        zone[inside] = np.maximum(zone[inside], width)
    canals = wz[wz["class"].astype(str).isin(CANAL_CLASS)]
    unknown = _near(points, canals, 50.0) & (zone == 0)
    return zone, unknown, _jurisdiction(points, regions), _boundary_m(points, regions)


def tighten(row: dict, zone: float, unknown: bool, jurisdiction: str, boundary_m: float, taxon: str) -> dict:
    out = dict(row)
    notes = []
    old_zone = float(row["water_zone_m"])
    zone = max(old_zone, float(zone))
    if zone > old_zone:
        out["water_zone_m"] = f"{zone:.0f}" if zone == int(zone) else f"{zone:.1f}"
        sentence = water_sentence(zone)
        basis = out.get("legal_basis") or out.get("basis") or ""
        if "ВК РФ ст. 65 ч. 15" in basis:
            import re
            basis = re.sub(r"водоохранная зона \d+ м", f"водоохранная зона {zone:.0f} м", basis)
        elif basis and basis != "ограничений по открытым слоям не найдено; вид подтвердить на месте":
            basis = sentence + "; " + basis
        else:
            basis = sentence
        key = "legal_basis" if "legal_basis" in out else "basis"
        out[key] = basis
        notes.append(f"water {old_zone:.0f}->{zone:.0f}")
    key = "legal_basis" if "legal_basis" in out else "basis"
    basis = out.get(key) or ""
    # A canal with no right-of-way bans pesticides only when the point is not already
    # inside a measured water zone. The polygon may have supplied that zone.
    if zone > 0 and "ст. 65 ч. 9" in basis:
        basis = "; ".join(part for part in basis.split("; ") if "ст. 65 ч. 9" not in part)
        out[key] = basis
        notes.append("canal sentence dropped: a water zone is already measured")
    elif zone == 0 and unknown and "ст. 65 ч. 9" not in basis:
        out[key] = (basis + "; " + CANAL_SENTENCE).strip("; ")
        notes.append("canal")
    old_boundary = float(row.get("jurisdiction_boundary_m") or "nan")
    if boundary_m == boundary_m and old_boundary == old_boundary:
        boundary_m = min(old_boundary, float(boundary_m))
    elif boundary_m != boundary_m:
        boundary_m = old_boundary
    if boundary_m == boundary_m and (old_boundary != old_boundary or abs(boundary_m - old_boundary) >= 0.5):
        out["jurisdiction_boundary_m"] = f"{boundary_m:.2f}"
        notes.append(f"boundary {old_boundary:.1f}->{boundary_m:.1f}")
    near = bool(boundary_m == boundary_m and boundary_m < 50)
    if "near_jurisdiction_boundary" in out and flag(out["near_jurisdiction_boundary"]) != near:
        out["near_jurisdiction_boundary"] = "True" if near else "False"
        notes.append(f"near_boundary {near}")
    if jurisdiction and jurisdiction != "unknown" and jurisdiction != row.get("jurisdiction"):
        out["jurisdiction"] = jurisdiction
        notes.append(f"jurisdiction {row.get('jurisdiction')}->{jurisdiction}")
    protected = flag(row.get("in_protected", False))
    act = listed_act(
        out.get("jurisdiction") or "unknown", taxon, protected=protected,
        boundary_m=None if boundary_m != boundary_m else float(boundary_m),
    )
    if "listed_species_act" in out and out["listed_species_act"] != act:
        out["listed_species_act"] = act
        notes.append("act")
    method_key = "method"
    banned = zone > 0 or unknown or flag(row.get("in_protected")) or flag(row.get("near_children")) \
        or flag(row.get("child_org_territory")) or flag(row.get("in_zso"))
    if banned and method_class(out[method_key]) != "mechanical":
        out[method_key] = strip_chemistry(out[method_key])
        notes.append("chemistry removed")
    out["_notes"] = notes
    return out


def points_from_rows(rows, lon_key, lat_key):
    return gpd.GeoDataFrame(
        geometry=[Point(float(r[lon_key]), float(r[lat_key])) for r in rows], crs=4326,
    ).to_crs(EPSG)


def keep_act(jurisdiction: str, taxon: str, boundary_m: float, old_act: str, new_act: str) -> str:
    """Recompute the duty, and do not drop a caution the map already stated."""
    protected = "ООПТ" in (old_act or "") or "ООПТ" in (new_act or "")
    act = listed_act(
        jurisdiction or "unknown", taxon, protected=protected,
        boundary_m=None if boundary_m != boundary_m else float(boundary_m),
    )
    if protected and "ООПТ" not in act:
        act = (act + "; " + OOPT_SENTENCE).strip("; ")
    return act


def write_geojson(path: Path, web: dict):
    """One feature per line, same header the map already uses."""
    header = [
        "{",
        '"type": "FeatureCollection",',
        f'"name": {json.dumps(web.get("name"), ensure_ascii=False)},',
        '"crs": ' + json.dumps(web["crs"], ensure_ascii=False) + ",",
        '"xy_coordinate_resolution": 1e-05,',
        '"features": [',
    ]
    feats = web["features"]
    body = []
    for i, feat in enumerate(feats):
        comma = "," if i < len(feats) - 1 else ""
        body.append(json.dumps(feat, ensure_ascii=False, separators=(", ", ": ")) + comma)
    path.write_text("\n".join(header + body + ["]", "}"]) + "\n", encoding="utf-8")


def rewrite_csv(path: Path, rows: list[dict]):
    fields = [k for k in rows[0] if k != "_notes"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fields})


def main():
    water = gpd.read_parquet(DATA / "overture" / "water.parquet")
    regions = load_regions()
    report = {}
    for taxon in ("heracleum", "solidago"):
        path = OUT / taxon / "work_orders_top200_2025.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        pts = points_from_rows(rows, "lon", "lat")
        zone, unknown, jurisdiction, boundary = measure(pts, water, regions)
        updated = [
            tighten(row, zone[i], bool(unknown[i]), jurisdiction[i], float(boundary[i]), taxon)
            for i, row in enumerate(rows)
        ]
        changed = [r for r in updated if r["_notes"]]
        rewrite_csv(path, updated)
        sample = ROOT / "pro" / "data" / "sample" / f"{taxon}_work_orders_top200_2025.csv"
        if sample.is_file():
            rewrite_csv(sample, updated)
        web_path = ROOT / "web" / "data" / f"{taxon}_top.geojson"
        web = json.loads(web_path.read_text(encoding="utf-8"))
        by_rank = {int(float(r["rank"])): r for r in updated}
        feats = web["features"]
        wpts = gpd.GeoDataFrame(
            geometry=[shape(f["geometry"]) for f in feats], crs=4326,
        ).to_crs(EPSG)
        wz, wu, wj, wb = measure(wpts, water, regions)
        web_changed = 0
        for i, feat in enumerate(feats):
            props = feat["properties"]
            rank = int(props["rank"])
            before = json.dumps(props, ensure_ascii=False, sort_keys=True)
            old_act = props.get("listed_species_act") or ""
            old_boundary = float(props.get("jurisdiction_boundary_m") or "nan")
            if rank in by_rank:
                src = by_rank[rank]
                props["water_zone_m"] = int(float(src["water_zone_m"]))
                props["jurisdiction"] = src["jurisdiction"]
                props["method"] = src["method"]
                props["basis"] = src["legal_basis"]
                props["cls"] = method_class(src["method"])
                boundary = float(src["jurisdiction_boundary_m"])
                if old_boundary == old_boundary:
                    boundary = min(old_boundary, boundary)
                props["jurisdiction_boundary_m"] = round(boundary, 2)
                props["near_jurisdiction_boundary"] = boundary < 50
                props["listed_species_act"] = keep_act(
                    props["jurisdiction"], taxon, boundary, old_act, src["listed_species_act"],
                )
            else:
                row = {
                    "water_zone_m": props["water_zone_m"],
                    "jurisdiction_boundary_m": props.get("jurisdiction_boundary_m", "nan"),
                    "near_jurisdiction_boundary": props.get("near_jurisdiction_boundary", False),
                    "jurisdiction": props.get("jurisdiction", "unknown"),
                    "listed_species_act": old_act,
                    "method": props["method"],
                    "basis": props["basis"],
                    "in_protected": "ООПТ" in old_act,
                    "near_children": props["d_child_m"] <= 100,
                    "child_org_territory": False,
                    "in_zso": False,
                }
                done = tighten(row, wz[i], bool(wu[i]), wj[i], float(wb[i]), taxon)
                if done["_notes"]:
                    props["water_zone_m"] = int(float(done["water_zone_m"]))
                    props["basis"] = done["basis"]
                    props["method"] = done["method"]
                    props["cls"] = method_class(done["method"])
                    props["jurisdiction"] = done["jurisdiction"]
                    boundary = float(done["jurisdiction_boundary_m"])
                    props["jurisdiction_boundary_m"] = round(boundary, 2)
                    props["near_jurisdiction_boundary"] = boundary < 50
                    props["listed_species_act"] = keep_act(
                        props["jurisdiction"], taxon, boundary, old_act, done["listed_species_act"],
                    )
            if json.dumps(props, ensure_ascii=False, sort_keys=True) != before:
                web_changed += 1
        write_geojson(web_path, web)
        report[taxon] = {
            "orders": len(rows),
            "orders_changed": len(changed),
            "order_notes": {r["rank"]: r["_notes"] for r in changed},
            "web_features_touched": web_changed,
        }
        print(taxon, "orders changed", len(changed), "web touches", web_changed, flush=True)
    out = OUT / "recheck_top200.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
