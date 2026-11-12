"""Все числа научного отчёта (docs/10) — одной командой: `make reproduce`.

Пересчитываются:
- формальная проверка права;
- сверка с InvaRadar;
- демо (KPI, синтетический заноc, закрытие, журнал);
- мощность исследований;
- путь в топ-10.

Результаты, которым нужна сеть (ретро-прогноз, бенчмарк фото), берутся из `analysis/results/*.json`,
если они уже посчитаны (`make realdata`). Итог: `analysis/results/paper_numbers.json` и `TABLES.md`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "analysis"))

from invaradar_pro.cli import check_upstream  # noqa: E402
from invaradar_pro.demo import run_demo  # noqa: E402
from invaradar_pro.law import LawEngine  # noqa: E402
from invaradar_pro.law_check import run as law_check  # noqa: E402
from invaradar_pro.power import n_two_proportions, simulate_did_power  # noqa: E402
from invaradar_pro.sampling import sample_size_for_margin  # noqa: E402
from invaradar_pro.upstream import read_work_orders  # noqa: E402

RES = ROOT / "analysis" / "results"


def main() -> dict:
    RES.mkdir(parents=True, exist_ok=True)
    eng = LawEngine()
    out: dict = {}
    lc = law_check(eng)
    out["law_check"] = {k: v for k, v in lc.items() if k != "counterexamples"}
    out["consistency"] = {t: check_upstream(read_work_orders(ROOT / "data" / "sample" / f"{t}_work_orders_top200_2025.csv"), t, eng)
                          for t in ("heracleum", "solidago")}
    with tempfile.TemporaryDirectory() as tmp:
        s = run_demo(Path(tmp) / "demo")
        out["demo"] = {"states": s["states"], "kpi": {k: v for k, v in s["kpi"].items() if k not in ("chain_head",)},
                       "spread": {k: s["spread"][k] for k in ("new_cells", "ldd_share_true", "ldd_share_fitted",
                                                              "capture_model", "capture_suitability_only",
                                                              "capture_distance_only")},
                       "transparency": s["transparency"]}
        out["closure_thresholds"] = json.loads((Path(tmp) / "demo" / "closure_thresholds.json").read_text(encoding="utf-8"))
    out["power"] = {
        "H4_points_per_stratum_for_pm10pp_at_p0.3": sample_size_for_margin(0.3, 0.10),
        "H6_relapse_0.30_to_0.24_n_per_arm": n_two_proportions(0.30, 0.24),
        "H6_did_power_n200_vs_200": simulate_did_power(0.30, 0.20, 200, 200),
        "H6_did_power_n600_vs_600": simulate_did_power(0.30, 0.20, 600, 600),
        "H7_herbicide_any_use_0.6_to_0.42_n_per_arm": n_two_proportions(0.60, 0.42),
        "H6_relapse_0.30_to_0.15_n_per_arm": n_two_proportions(0.30, 0.15),
        "H6_did_power_50pct_n200_vs_200": simulate_did_power(0.30, 0.50, 200, 200),
    }
    import top10_path  # noqa: E402
    t = top10_path.main()
    out["top10"] = {k: v["P_top10"] for k, v in t["scenarios"].items()} | {"tornado": t["tornado_vs_plan"]}
    for name in ("retro_forecast", "evidence_bench"):
        f = RES / f"{name}.json"
        out[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else "не запускалось: make realdata"
    if isinstance(out.get("evidence_bench"), dict):
        for h in out["evidence_bench"]["hashes"].values():
            h.pop("curve", None)
    (RES / "paper_numbers.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    (RES / "TABLES.md").write_text(tables(out), encoding="utf-8")
    return out


def tables(o: dict) -> str:
    L = ["# Таблицы научного отчёта (сгенерировано `analysis/reproduce.py`)", ""]
    lc = o["law_check"]
    L += ["## Формальная проверка права", "",
          f"Контекстов: {lc['contexts']}; пар монотонности: {lc['monotonicity_pairs']}; свойства: {lc['properties']}; "
          f"обязанности: {lc['obligations']}; правила без решающих контекстов: {lc['never_decisive']}", ""]
    L += ["## Сверка с InvaRadar", ""] + [f"- {t}: строк {c['rows']}, ошибок {len(c['errors'])}, к юристу {c['legal_review']}"
                                          for t, c in o["consistency"].items()] + [""]
    L += ["## Закрытие очага (Regan et al., 2006)", "", "| Осыпание семян | Ущерб, ₽ | p* | Чистых сезонов |", "|---|---|---|---|"]
    L += [f"| {'да' if r['seeded'] else 'нет'} | {r['cost_escape_rub']:.0f} | {r['p_star']} | {r['clean_seasons_after_treatment']} |"
          for r in o["closure_thresholds"]] + [""]
    rf = o.get("retro_forecast")
    if isinstance(rf, dict):
        L += ["## Пиксельный ряд 2023–2025 (iNaturalist + AlphaEarth, 64 канала)", "",
              "2023 и 2024 — ретро-прогноз: эмбеддинг раньше меток. 2025 — тот же снимок, что и у части меток "
              "(same_image), это не прогноз и не повтор карты на 265 признаках. Правило вердикта прежнее.", "",
              "| Вид | Признаки | Новых мест | Верхние 10% | Верхние 20% (блочный 95% ДИ) | Вердикт |", "|---|---|---|---|---|---|"]
        for tx, r in rf["taxa"].items():
            for y, v in r["by_year"].items():
                c = v["capture"]
                verdict = v["verdict_top20"]
                if str(y) == "2025":
                    verdict = {
                        "прогноз подтверждён: лучше случайного обхода": "тот же снимок: лучше случайного обхода (не прогноз)",
                        "сильный прогноз: нижняя граница выше удвоенной случайной доли": "тот же снимок: сильный сигнал (не прогноз)",
                        "не подтверждён: интервал включает случайный обход": "тот же снимок: интервал включает случайный обход (не прогноз)",
                    }.get(verdict, verdict)
                L.append(f"| {tx} | {y} | {r['n_new_far']} | {c['top10%']['capture']:.3f} | {c['top20%']['capture']:.3f} "
                         f"({c['top20%']['block_boot95'][0]:.3f}–{c['top20%']['block_boot95'][1]:.3f}) | {verdict} |")
            p = r["proximity"]["top20%"]
            cb = r["combined_2024_plus_proximity"]["top20%"]
            lk = r["leakage_2025_minus_2024_top20"]
            L.append(f"| {tx} | близость к старым | {r['n_new_far']} | {r['proximity']['top10%']['capture']:.3f} | "
                     f"{p['capture']:.3f} | — |")
            L.append(f"| {tx} | 2024 + близость | {r['n_new_far']} | {r['combined_2024_plus_proximity']['top10%']['capture']:.3f} | "
                     f"{cb['capture']:.3f} | — |")
            L.append(f"| {tx} | утечка 2025−2024, верхние 20% | | | {lk['diff']:+.3f} ({lk['boot95'][0]:+.3f}…{lk['boot95'][1]:+.3f}) | |")
        L.append("")
    eb = o.get("evidence_bench")
    if isinstance(eb, dict):
        L += ["## Повторное использование фото: бенчмарк на реальных снимках", "",
              f"Снимков: {eb['n_photos']}; сочетание порогов: {eb['combined_or']}; текущие строгие пороги: {eb['current_thresholds']}", ""]
    L += ["## Мощность", "", f"{o['power']}", "", "## Путь в топ-10", "", f"{o['top10']}", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
    print((RES / "TABLES.md").read_text(encoding="utf-8")[:3000])
