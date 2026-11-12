"""Сквозное демо: реальные очаги из нарядов InvaRadar 2025 и синтетические события сезонов 2027–2030.

Что показывает демо (то же, что на демо-дне):
1. сигнал карты → осмотр (сухие прошлогодние стебли в апреле, ИИ-проверка фото жителя) → двойник отклонён;
2. закон в наряде: Москва по полигону идёт дальше, область и неизвестная юрисдикция — к юристу; химия у воды заблокирована;
3. агент не может подписать наряд — только человек;
4. подрядчик сдаёт фото, повтор фото с другого очага пойман, работа возвращена;
5. контроль 5 сезонов: рецидив возвращает очаг в работу, закрытие — только после чистых сезонов;
6. аудит ЛЭП и дороги по километрам, прогноз новых очагов, расчёт полевой выборки.
Все даты после ноября 2026 года и все действия людей — синтетические.
"""
from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from .agent_tools import dispatch
from .calibration import isotonic_fit
from .corridor import Line, audit, summarize, write_csv
from .events import EventLog
from .evidence import check_pair, check_photo, read_photo, strip_metadata, synth_photo, verdict
from .geo import to_local_xy
from .kpi import compute
from .law import LawEngine
from .report import case_passport, program_report
from .sampling import binary_accuracy, neyman_allocation, stratified_proportion
from .spread import (
    SpreadParams,
    capture_curve,
    colonization_probability,
    corridor_proximity,
    fft_convolve,
    fit_rates,
    pressure,
    scale_to_expected,
)
from .upstream import law_context, read_work_orders, signal_payload
from .workflow import CaseStore, TransitionError, followup_schedule

DATA = Path(__file__).resolve().parents[2] / "data" / "sample"


def H(i: str, role: str, name: str | None = None) -> dict:
    return {"id": i, "role": role, "kind": "human", **({"name": name} if name else {})}


MODEL = {"id": "invaradar-1.2", "role": "model", "kind": "system"}
AGENT = {"id": "agent-dispatcher", "role": "agent", "kind": "agent"}
SYSTEM = {"id": "system", "role": "system", "kind": "system"}
INSPECTOR = H("insp-01", "inspector", "Инспектор (демо)")
LAWYER = H("law-01", "lawyer", "Юрист (демо)")
CREW = H("crew-07", "crew")
CITIZEN = H("cit-123", "citizen")
CONTRACTOR = H("ctr-01", "contractor")
HOLDERS = ["municipal", "legal_entity", "servitude", "citizen"]


def _at(d: date, hour: int = 10) -> str:
    return datetime(d.year, d.month, d.day, hour, tzinfo=UTC).isoformat(timespec="seconds")


def _dt(d: date, hour: int = 10) -> datetime:
    return datetime(d.year, d.month, d.day, hour)


class Demo:
    def __init__(self, out: Path, taxon: str, seed: int):
        self.out = out
        self.taxon = taxon
        self.engine = LawEngine()
        (out / "events.jsonl").unlink(missing_ok=True)
        self.log = EventLog(out / "events.jsonl")
        self.store = CaseStore(self.log, self.engine.taxa, self.engine)
        self.photos = out / "photos"
        self.photos.mkdir(parents=True, exist_ok=True)
        self.seen: list[tuple[int, str, str]] = []
        self.story: list[str] = []
        self.seed = seed
        self.k = 0

    def photo(self, cid: str, tag: str, lat: float, lon: float, when: datetime, reuse: bytes | None = None):
        self.k += 1
        data = reuse if reuse is not None else synth_photo(lat, lon, when, self.seed * 1000 + self.k)
        (self.photos / f"{cid}_{tag}.jpg").write_bytes(strip_metadata(data))
        return data, read_photo(data)

    def act(self, cid: str, et: str, actor: dict, payload: dict, d: date, note: str | None = None) -> bool:
        try:
            self.store.act(cid, et, actor, payload, at=_at(d))
            return True
        except TransitionError as err:
            self.story.append(f"- {d} · {cid}: заблокировано «{et}» ({actor['role']}): {err}")
            return False

    def accept(self, cid: str, d: date) -> bool:
        """Приёмка: при вердикте «нужна проверка» инспектор сравнивает снимки вручную и пишет обоснование."""
        v = self.store.case(cid).evidence_verdict
        if v == "needs_review":
            self.story.append(f"- {d} · {cid}: хеши фото похожи на чужой снимок — инспектор сравнил вручную и принял с обоснованием")
            return self.act(cid, "work_accepted", INSPECTOR,
                            {"override_reason": "ручное сравнение: разные сцены, совпадение хешей случайное"}, d)
        return self.act(cid, "work_accepted", INSPECTOR, {}, d)

    def report_work(self, cid: str, row: dict, method: str, d: date, seed_ok: bool, reuse: bytes | None = None) -> bytes:
        lat, lon = row["lat"], row["lon"]
        radius = float(np.sqrt((row.get("area_m2") or 0) / np.pi))
        _, before = self.photo(cid, f"before_{d}", lat + 0.00005, lon, _dt(d, 9))
        after_bytes, after = self.photo(cid, f"after_{d}", lat + 0.00005, lon + 0.00005, _dt(d, 17), reuse=reuse)
        case = self.store.case(cid)
        start = case.order["approved_at"][:10]
        checks = (check_photo(before, focus_lat=lat, focus_lon=lon, radius_m=radius, start=start, end=case.order["due"],
                              seen=self.seen)
                  + check_photo(after, focus_lat=lat, focus_lon=lon, radius_m=radius, start=start, end=case.order["due"],
                                seen=self.seen)
                  + check_pair(before, after))
        v = verdict(checks)
        herb = "pesticide" in self.engine.groups(method)
        ok = self.act(cid, "work_reported", CONTRACTOR, {
            "method_used": method, "seed_set_prevented": seed_ok, "verdict": v,
            "evidence": [{"kind": "before", **before.to_dict()}, {"kind": "after", **after.to_dict()}],
            "checks": [c.to_dict() for c in checks], "treated_area_m2": row.get("area_m2"),
            "herbicide_l": round((row.get("area_m2") or 0) / 10_000 * 2.0, 2) if herb else 0.0}, d)
        if ok and v == "pass":
            self.seen += [(before.dhash, before.sha256, f"{cid}/before", before.phash),
                          (after.dhash, after.sha256, f"{cid}/after", after.phash)]
        return after_bytes


def run_demo(out_dir: str | Path, taxon: str = "heracleum", n: int = 8, seed: int = 7,
             csv_path: str | Path | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    D = Demo(out, taxon, seed)
    eng, store = D.engine, D.store
    rows = read_work_orders(csv_path or DATA / f"{taxon}_work_orders_top200_2025.csv")[:n]
    d0 = date(2027, 4, 20)
    ids = []
    shared_after: bytes | None = None
    herb_block_done = False
    boom_block_done = False

    for i, row in enumerate(rows):
        cid = f"{taxon[:3].upper()}-2025-{row['rank']:03d}"
        ids.append(cid)
        lat, lon = row["lat"], row["lon"]
        D.act(cid, "signal_received", MODEL, signal_payload(row, taxon), d0)
        D.act(cid, "field_check_assigned", AGENT, {"assignee": CREW["id"]}, d0 + timedelta(days=2))
        d_check = d0 + timedelta(days=7 + i % 5)
        _, ph = D.photo(cid, "check", lat, lon, _dt(d_check))
        if i == 3:
            D.act(cid, "field_result", CREW, {"present": False, "photos": [ph.sha256], "verified_by": "crew",
                                              "note": "борщевик сибирский — местный вид-двойник"}, d_check)
            D.story.append(f"- {d_check} · {cid}: двойник (борщевик сибирский), очаг отклонён, метка уходит в обучение")
            continue
        if i == 1:
            D.act(cid, "field_result", MODEL, {"present": True, "photos": [ph.sha256], "verified_by": "ai_photo",
                                               "confidence": 0.94, "reporter": CITIZEN["id"]}, d_check)
        else:
            D.act(cid, "field_result", CREW, {"present": True, "photos": [ph.sha256], "verified_by": "crew",
                                              "phenology": "сухие прошлогодние стебли и розетки"}, d_check)
        holder = HOLDERS[i % len(HOLDERS)]
        ctx = law_context(row, taxon, holder_type=holder)
        dec = eng.decide(ctx).to_dict()
        D.act(cid, "order_drafted", AGENT, {"context": ctx, "decision": dec}, d_check + timedelta(days=1))
        if dec.get("requires_legal_review"):
            # An oblast row, a protected Moscow row, or goldenrod stays with the lawyer.
            # The demo does not relabel them as Moscow city.
            D.story.append(f"- {d_check + timedelta(days=1)} · {cid}: наряд ждёт юриста "
                           f"({', '.join(dec.get('flags') or ['review'])}), демо не подменяет юрисдикцию")
            continue
        d_ap = d_check + timedelta(days=5)
        due = (d_ap + timedelta(days=45)).isoformat()
        if i == 0:
            r = dispatch("approve_order", {"case_id": cid, "method": dec["recommended"][0], "due": due}, AGENT, store, eng)
            D.story.append(f"- {d_ap} · {cid}: агент попросил утвердить наряд → {r['status']}: нужна подпись человека")
        if "ground_herbicide_spot" in dec["prohibited"] and not herb_block_done:
            D.act(cid, "order_approved", INSPECTOR, {"signer": INSPECTOR["name"], "method": "ground_herbicide_spot",
                                                     "due": due}, d_ap)
            herb_block_done = True
        if "ground_herbicide_boom" in dec["prohibited"] and not boom_block_done:
            D.act(cid, "order_approved", INSPECTOR, {"signer": INSPECTOR["name"], "method": "ground_herbicide_boom",
                                                     "due": due}, d_ap)
            boom_block_done = True
        method = dec["recommended"][0]
        D.act(cid, "order_approved", INSPECTOR, {"signer": INSPECTOR["name"], "method": method, "due": due}, d_ap)
        d_w = d_ap + timedelta(days=10)
        D.act(cid, "work_started", CONTRACTOR, {}, d_w)
        d_r = d_w + timedelta(days=7)
        if i == 4 and "ground_herbicide_boom" in dec["prohibited"]:
            D.act(cid, "work_reported", CONTRACTOR, {"method_used": "ground_herbicide_boom", "evidence": [{}],
                                                     "checks": [{"name": "place", "ok": False, "detail": "тест"}],
                                                     "seed_set_prevented": True}, d_r)
        if i == 2 and shared_after is not None:
            D.report_work(cid, row, method, d_r, True, reuse=shared_after)
            D.act(cid, "work_rejected", INSPECTOR, {"reason": "фото «после» уже принято по другому очагу"}, d_r + timedelta(days=2))
            D.story.append(f"- {d_r} · {cid}: повтор фото с другого очага пойман, работы возвращены")
            d_r = d_r + timedelta(days=6)
        after = D.report_work(cid, row, method, d_r, seed_ok=(i != 6))
        if i == 5:
            D.act(cid, "work_rejected", INSPECTOR, {"reason": "фото не подтверждает контур очага"}, d_r + timedelta(days=2))
            D.story.append(f"- {d_r} · {cid}: первая сдача возвращена, контур на фото не совпал с очагом")
            d_r = d_r + timedelta(days=6)
            after = D.report_work(cid, row, method, d_r, seed_ok=True)
        if i == 0:
            shared_after = after
        d_acc = d_r + timedelta(days=3)
        if i == 0:
            D.act(cid, "work_accepted", CONTRACTOR, {}, d_acc)  # подрядчик пробует принять сам — блок
        D.accept(cid, d_acc)
        sched = followup_schedule(d_acc, taxon, eng.taxa)
        D.act(cid, "monitoring_scheduled", SYSTEM, {"schedule": sched}, d_acc)
        for j, s in enumerate(sched):
            ds = date.fromisoformat(s)
            if ds.year > 2030:
                break
            _, fp = D.photo(cid, f"followup_{s}", lat, lon, _dt(ds))
            regrowth = (i == 5 and j == 1)
            who = CITIZEN if j % 2 else CREW
            D.act(cid, "followup", who, {"season": ds.year, "regrowth": regrowth, "photos": [fp.sha256]}, ds)
            if regrowth:
                D.story.append(f"- {ds} · {cid}: отрастание после подрезки → рецидив, очаг снова в работе")
                D.act(cid, "order_drafted", AGENT, {"context": ctx, "decision": dec}, ds + timedelta(days=1))
                D.act(cid, "order_approved", INSPECTOR, {"signer": INSPECTOR["name"], "method": method,
                                                         "due": (ds + timedelta(days=30)).isoformat()}, ds + timedelta(days=2))
                D.act(cid, "work_started", CONTRACTOR, {}, ds + timedelta(days=5))
                D.report_work(cid, row, method, ds + timedelta(days=9), True)
                d2 = ds + timedelta(days=11)
                D.accept(cid, d2)
                D.act(cid, "monitoring_scheduled", SYSTEM, {"schedule": followup_schedule(d2, taxon, eng.taxa)}, d2)
                for s2 in followup_schedule(d2, taxon, eng.taxa):
                    ds2 = date.fromisoformat(s2)
                    if ds2.year > 2030:
                        break
                    _, fp2 = D.photo(cid, f"followup2_{s2}", lat, lon, _dt(ds2))
                    D.act(cid, "followup", CREW, {"season": ds2.year, "regrowth": False, "photos": [fp2.sha256]}, ds2)
                break
        # One confirmed city case stays in monitoring so the journal shows an open focus.
        if i == 0:
            D.act(cid, "case_closed", INSPECTOR, {}, date(2030, 9, 1))

    # --- отчёты --------------------------------------------------------------------------------
    pdir = out / "passports"
    pdir.mkdir(exist_ok=True)
    cases = store.cases()
    for cid, c in cases.items():
        (pdir / f"{cid}.md").write_text(case_passport(c, eng), encoding="utf-8")
    kpi = compute(store, today="2030-12-31")
    (out / "kpi.json").write_text(json.dumps(kpi, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "story.md").write_text("# Что произошло в демо\n\n" + "\n".join(D.story) + "\n", encoding="utf-8")
    (out / "report.md").write_text(program_report(kpi, "Демо-программа 2027–2030 (синтетические события)"),
                                   encoding="utf-8")
    corridor = corridor_demo(out, taxon)
    spread = spread_demo(out, taxon, seed)
    samp = sampling_demo(out, seed)
    transparency = transparency_demo(out, D.log)
    closure = closure_demo(out, eng, taxon)
    summary = {"cases": len(cases), "states": {k: str(v.state) for k, v in cases.items()}, "kpi": kpi,
               "corridor": corridor, "spread": spread, "sampling": samp, "transparency": transparency,
               "closure": closure, "chain_ok": D.log.verify()[0], "story": D.story}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def transparency_demo(out: Path, log: EventLog) -> dict:
    """Подписанная голова дерева Меркла и проверяемые доказательства (RFC 9162)."""
    from .merkle import leaf_hash, signed_tree_head, verify_consistency, verify_inclusion
    tree = log.merkle()
    n = len(tree)
    seq = next(e.seq for e in log if e.type == "work_accepted")
    mid = n // 2
    inc = tree.inclusion_proof(seq)
    con = tree.consistency_proof(mid)
    res = {"sth": signed_tree_head(tree, b"demo-key-not-secret", "2030-12-31T00:00:00Z"),
           "inclusion": {"seq": seq, "leaf_hash": leaf_hash(log.leaf_bytes(seq)).hex(), "proof": [p.hex() for p in inc],
                         "verified": verify_inclusion(leaf_hash(log.leaf_bytes(seq)), seq, n, inc, tree.root())},
           "consistency": {"old_size": mid, "old_root": tree.root(mid).hex(), "new_size": n,
                           "proof": [p.hex() for p in con],
                           "verified": verify_consistency(mid, n, tree.root(mid), tree.root(), con)},
           "note": "Доказательство включения — log2(n) хешей: подрядчику не нужен весь журнал, чтобы проверить свою приёмку"}
    (out / "transparency.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"tree_size": n, "root": res["sth"]["root"], "inclusion_ok": res["inclusion"]["verified"],
            "consistency_ok": res["consistency"]["verified"], "proof_len": len(inc)}


def closure_demo(out: Path, eng: LawEngine, taxon: str) -> dict:
    """Сколько чистых сезонов оптимально (Regan et al., 2006): чувствительность к ущербу и осыпанию семян."""
    from .eradication import ClosureParams, optimal_threshold
    base = eng.taxa[taxon].get("closure", {})
    rows = []
    for seeded in (False, True):
        for ce in (30_000.0, 120_000.0, 300_000.0):
            r = optimal_threshold(ClosureParams.from_policy({**base, "cost_escape": ce}), seeded=seeded)
            rows.append({"seeded": seeded, "cost_escape_rub": ce, **r})
    (out / "closure_thresholds.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rows": len(rows), "no_seed_120k": next(r["clean_seasons_after_treatment"] for r in rows
                                                     if not r["seeded"] and r["cost_escape_rub"] == 120_000.0)}


def _foci(taxon: str):
    rows = read_work_orders(DATA / f"{taxon}_work_orders_top200_2025.csv")
    lat = np.array([r["lat"] for r in rows])
    lon = np.array([r["lon"] for r in rows])
    lat0, lon0 = float(lat.mean()), float(lon.mean())
    x, y = to_local_xy(lat, lon, lat0, lon0)
    return rows, x, y


def _synthetic_line(x, y, a: int, b: int, band: float = 1500.0, k: int = 8, offset=(0.0, 0.0)):
    """Почти прямая линия от очага a до очага b через k очагов, лежащих в полосе ±band от прямой."""
    ax, ay, bx, by = x[a], y[a], x[b], y[b]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = ((x - ax) * dx + (y - ay) * dy) / L2
    perp = np.abs((x - ax) * dy - (y - ay) * dx) / np.sqrt(L2)
    idx = np.where((t > 0.02) & (t < 0.98) & (perp < band))[0]
    idx = idx[np.argsort(t[idx])]
    if len(idx) > k:
        idx = idx[np.linspace(0, len(idx) - 1, k).round().astype(int)]
    px = np.concatenate([[ax], x[idx] + offset[0], [bx]])
    py = np.concatenate([[ay], y[idx] + offset[1], [by]])
    return px, py


def corridor_demo(out: Path, taxon: str) -> dict:
    """Синтетическая ВЛ 110 кВ и дорога, проложенные через реальные очаги. Владельцы — условные."""
    rows, x, y = _foci(taxon)
    lx, ly = _synthetic_line(x, y, int(np.argmin(x)), int(np.argmax(x)), offset=(6.0, -5.0))
    rx, ry = _synthetic_line(x, y, int(np.argmin(y)), int(np.argmax(y)), offset=(4.0, -3.0))
    lines = [Line("VL-110-demo", "power", "Сетевая компания (демо)", lx, ly, voltage_kv=110),
             Line("ROAD-demo", "road", "Дорожная служба (демо)", rx, ry)]
    f = audit(lines, x, y, [r["area_m2"] for r in rows], [r["priority"] for r in rows], [r["rank"] for r in rows])
    write_csv(f, out / "corridor_audit.csv")
    s = summarize(lines, f)
    md = ["# Аудит линейных объектов (синтетические линии через реальные очаги InvaRadar)", "",
          "| Линия | Владелец | Длина, км | Километров с очагами | Очагов | Площадь в зоне, м² |", "|---|---|---|---|---|---|"]
    md += [f"| {r['line_id']} | {r['owner']} | {r['length_km']} | {r['segments_with_foci']} | {r['foci']} | {r['area_in_zone_m2']} |"
           for r in s]
    md += ["", "| Линия | Км | Полоса, м | Очагов | Площадь в зоне, м² | Макс. приоритет | Ранги очагов |", "|---|---|---|---|---|---|---|"]
    md += [f"| {g.line_id} | {g.km_from:.0f}–{g.km_to:.0f} | ±{g.half_width_m:.0f} | {g.n_foci} | {g.area_in_zone_m2:.0f} | "
           f"{g.max_priority:.1f} | {', '.join(g.focus_ids)} |" for g in f]
    (out / "corridor_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"lines": s, "segments_with_foci": len(f)}


def spread_demo(out: Path, taxon: str, seed: int) -> dict:
    """Проверка метода на синтетике с известной истиной: источники — реальные очаги, остальное синтетика."""
    rng = np.random.default_rng(seed)
    rows, x, y = _foci(taxon)
    cell = 100.0
    x0, y0 = x.min() - 3000, y.min() - 3000
    nx = int((x.max() + 3000 - x0) // cell) + 1
    ny = int((y.max() + 3000 - y0) // cell) + 1
    src = np.zeros((ny, nx))
    np.add.at(src, (((y - y0) // cell).astype(int), ((x - x0) // cell).astype(int)),
              np.array([r["area_m2"] for r in rows]) / 10_000)
    g = np.exp(-0.5 * (np.arange(-30, 31) / 10.0) ** 2)
    smooth = fft_convolve(rng.normal(size=(ny, nx)), np.outer(g, g) / np.outer(g, g).sum())
    suit = (smooth - smooth.min()) / (np.ptp(smooth) + 1e-12)
    yy, xx = np.mgrid[0:ny, 0:nx]
    d_road = np.minimum(np.abs((xx * cell) % 8000 - 4000), np.abs((yy * cell) % 9000 - 4500))
    corr = corridor_proximity(d_road, 200.0)
    true = SpreadParams(cell_m=cell, alpha=0.25, beta=0.75, radius_ldd_m=3000.0)
    valid = src == 0
    lam = pressure(src, suit, corr, true)
    p_true = colonization_probability(lam * scale_to_expected(lam, 400.0, valid))
    new = (rng.random(p_true.shape) < p_true) & valid
    absent = np.zeros_like(new)
    absent.flat[rng.choice(new.size, 20000, replace=False)] = True
    absent &= valid & ~new
    fitted, ll = fit_rates(src, suit, corr, new, absent, SpreadParams(cell_m=cell, radius_ldd_m=3000.0))
    model = pressure(src, suit, corr, fitted)
    near = fft_convolve(src, np.ones((21, 21)))
    share_true = true.beta / (true.alpha + true.beta)
    share_fit = fitted.beta / (fitted.alpha + fitted.beta)
    res = {"grid": [ny, nx], "cell_m": cell, "new_cells": int(new.sum()),
           "ldd_share_true": round(share_true, 3), "ldd_share_fitted": round(share_fit, 3), "loglik": round(ll, 2),
           "capture_model": capture_curve(model, new, valid=valid),
           "capture_suitability_only": capture_curve(suit, new, valid=valid),
           "capture_distance_only": capture_curve(near, new, valid=valid),
           "note": "Синтетика с известной истиной: проверяет код и метод, не биологию. Реальная проверка — ретро-прогноз "
                   "находок 2025–2026 по очагам до 2024 года и полевая выборка."}
    (out / "spread_demo.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def sampling_demo(out: Path, seed: int) -> dict:
    """План и оценка полевой выборки по 4 слоям ранга InvaRadar. Ответы с земли — симуляция."""
    with (DATA / "heracleum_validation_sample.csv").open(encoding="utf-8") as fh:
        v = list(csv.DictReader(fh))
    strata = sorted({int(r["stratum"]) for r in v})
    W = np.array([float(next(r["stratum_px"] for r in v if int(r["stratum"]) == s)) for s in strata])
    n_now = np.array([sum(int(r["stratum"]) == s for r in v) for s in strata])
    p_guess = np.array([0.01, 0.04, 0.12, 0.30])
    alloc = neyman_allocation(250, W, p_guess, min_per=30)
    rng = np.random.default_rng(seed)
    x = rng.binomial(n_now, p_guess)
    est = stratified_proportion(W, n_now, x)
    acc = binary_accuracy(W, n_now, x, positive_strata=[3])
    ranks = np.concatenate([rng.uniform(lo, hi, k) for (lo, hi), k in zip([(0, .8), (.8, .95), (.95, .98), (.98, 1)], n_now)])
    ys = np.concatenate([rng.random(k) < p for k, p in zip(n_now, p_guess)])
    iso = isotonic_fit(ranks, ys.astype(float))
    res = {"strata_weights": (W / W.sum()).round(4).tolist(), "n_current": n_now.tolist(),
           "neyman_250": alloc.tolist(), "simulated_positives": x.tolist(),
           "prevalence": {"p": round(est["p"], 4), "se": round(est["se"], 4)},
           "hotspot_precision": acc["precision"], "hotspot_recall": acc["recall"],
           "p_confirm_at_rank": {str(r): round(float(iso.predict(r)), 3) for r in (0.5, 0.9, 0.97, 0.99)},
           "note": "Ответы с земли сгенерированы; после полевого сезона сюда подставляются реальные."}
    (out / "sampling_demo.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    return res
