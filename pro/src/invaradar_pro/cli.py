"""Командная строка: invaradar-pro <команда>. Без установки: PYTHONPATH=src python -m invaradar_pro <команда>."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent_tools import tool_specs
from .corridor import Line, audit, write_csv
from .events import EventLog
from .geo import to_local_xy
from .law import LawEngine
from .upstream import law_context, read_work_orders

AERIAL_WORDS = ("бпла", "беспилот", "дрон")


def check_upstream(rows: list[dict], taxon: str, engine: LawEngine) -> dict:
    """Сверка с нарядами InvaRadar: жёсткие инварианты права плюс отличия, где Pro строже."""
    errors, stricter = [], 0
    pest = set(engine.expand(["@pesticide"]))
    for r in rows:
        d = engine.decide(law_context(r, taxon))
        tag = f"ранг {r['rank']}"
        if (r.get("water_zone_m") or 0) > 0 and not pest <= set(d.prohibited):
            errors.append(f"{tag}: водоохранная зона, а пестициды не запрещены")
        if (r.get("water_zone_m") or 0) > 0 and "65" not in (r.get("legal_basis") or ""):
            errors.append(f"{tag}: в наряде InvaRadar нет ссылки на ст. 65 ВК РФ при водоохранной зоне")
        if r.get("child_org_territory") and not pest <= set(d.prohibited):
            errors.append(f"{tag}: территория детской организации, а пестициды не запрещены")
        if r.get("in_settlement") and "aerial_uav_herbicide" not in d.prohibited:
            errors.append(f"{tag}: населённый пункт, а беспилотник не запрещён")
        if (r.get("jurisdiction") or "unknown") == "unknown" and not d.requires_legal_review:
            errors.append(f"{tag}: юрисдикция не определена, а наряд не идёт юристу")
        up_aerial = any(w in (r.get("method") or "").lower() for w in AERIAL_WORDS)
        if up_aerial and "aerial_uav_herbicide" in d.prohibited:
            stricter += 1
    return {"rows": len(rows), "errors": errors, "pro_stricter_on_uav": stricter,
            "legal_review": sum(engine.decide(law_context(r, taxon)).requires_legal_review for r in rows)}


def _lines_from_geojson(path: Path, lat0: float, lon0: float) -> list[Line]:
    gj = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, f in enumerate(gj["features"]):
        g, p = f["geometry"], f.get("properties", {})
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for j, coords in enumerate(parts):
            lon, lat = zip(*[(c[0], c[1]) for c in coords])
            x, y = to_local_xy(lat, lon, lat0, lon0)
            out.append(Line(f"{p.get('id', i)}-{j}", p.get("kind", "power"), p.get("owner", ""), x, y,
                            voltage_kv=p.get("voltage_kv"), half_width_m=p.get("half_width_m")))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="invaradar-pro", description="ИнваРадар Pro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="сквозное демо на очагах InvaRadar")
    d.add_argument("--out", default="out_demo")
    d.add_argument("--taxon", default="heracleum", choices=["heracleum", "solidago"])
    d.add_argument("--n", type=int, default=8)
    v = sub.add_parser("verify", help="проверить цепочку хешей журнала")
    v.add_argument("path")
    lw = sub.add_parser("law", help="решение по закону для очага из наряда InvaRadar")
    lw.add_argument("--csv", required=True)
    lw.add_argument("--rank", type=int, required=True)
    lw.add_argument("--taxon", default="heracleum")
    lw.add_argument("--jurisdiction")
    lw.add_argument("--holder")
    c = sub.add_parser("consistency", help="сверка инвариантов с нарядами InvaRadar")
    c.add_argument("--csv", required=True)
    c.add_argument("--taxon", default="heracleum")
    cr = sub.add_parser("corridor", help="аудит линий (GeoJSON, WGS84) по очагам из наряда")
    cr.add_argument("--lines", required=True)
    cr.add_argument("--csv", required=True)
    cr.add_argument("--out", default="corridor_audit.csv")
    sub.add_parser("tools", help="описания инструментов для ИИ-агента")
    pr = sub.add_parser("prove", help="доказательство включения события в журнал (RFC 9162)")
    pr.add_argument("path")
    pr.add_argument("--seq", type=int, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        from .demo import run_demo
        s = run_demo(a.out, a.taxon, a.n)
        print(json.dumps({"cases": s["cases"], "states": s["states"], "chain_ok": s["chain_ok"],
                          "blocked": s["kpi"]["blocked_attempts"], "out": str(Path(a.out).resolve())},
                         ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "verify":
        ok, bad = EventLog(a.path).verify()
        print("цепочка цела" if ok else f"цепочка нарушена на событии {bad}")
        return 0 if ok else 1
    if a.cmd == "prove":
        from .merkle import leaf_hash, verify_inclusion
        log = EventLog(a.path)
        tree = log.merkle()
        proof = tree.inclusion_proof(a.seq)
        ok = verify_inclusion(leaf_hash(log.leaf_bytes(a.seq)), a.seq, len(tree), proof, tree.root())
        print(json.dumps({"seq": a.seq, "tree_size": len(tree), "root": tree.root().hex(),
                          "proof": [p.hex() for p in proof], "verified": ok}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    eng = LawEngine()
    if a.cmd == "law":
        row = next(r for r in read_work_orders(a.csv) if r["rank"] == a.rank)
        extra = {k: v for k, v in (("jurisdiction", a.jurisdiction), ("holder_type", a.holder)) if v}
        print(json.dumps(eng.decide(law_context(row, a.taxon, **extra)).to_dict(), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "consistency":
        res = check_upstream(read_work_orders(a.csv), a.taxon, eng)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1 if res["errors"] else 0
    if a.cmd == "corridor":
        rows = read_work_orders(a.csv)
        lat0 = sum(r["lat"] for r in rows) / len(rows)
        lon0 = sum(r["lon"] for r in rows) / len(rows)
        x, y = to_local_xy([r["lat"] for r in rows], [r["lon"] for r in rows], lat0, lon0)
        f = audit(_lines_from_geojson(Path(a.lines), lat0, lon0), x, y, [r["area_m2"] for r in rows],
                  [r["priority"] for r in rows], [r["rank"] for r in rows])
        write_csv(f, a.out)
        print(f"участков с очагами: {len(f)} → {a.out}")
        return 0
    if a.cmd == "tools":
        print(json.dumps(tool_specs(), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
