"""Сводка ретро-прогноза для научного отчёта: analysis/results/retro_forecast.json → Markdown."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fmt_ci(c: dict) -> str:
    lo, hi = c.get("block_boot95", c["wilson95"])
    return f"{c['capture']:.1%} ({lo:.1%}–{hi:.1%})".replace(".", ",")


def summarize(r: dict) -> str:
    L = ["| Вид | Признаки / модель | Новых мест (> 500 м) | Верхние 10% площади | Верхние 20% площади (95% ДИ, блоки 5 км) | Вердикт по правилу |",
         "|---|---|---|---|---|---|"]
    for tx, t in r["taxa"].items():
        for y, v in t["by_year"].items():
            c = v["capture"]
            L.append(f"| {tx} | AlphaEarth {y} | {t['n_new_far']} | {fmt_ci(c['top10%'])} | {fmt_ci(c['top20%'])} | {v['verdict_top20']} |")
        L.append(f"| {tx} | близость к старым находкам | {t['n_new_far']} | {fmt_ci(t['proximity']['top10%'])} | "
                 f"{fmt_ci(t['proximity']['top20%'])} | — |")
        L.append(f"| {tx} | AlphaEarth 2024 + близость | {t['n_new_far']} | {fmt_ci(t['combined_2024_plus_proximity']['top10%'])} | "
                 f"{fmt_ci(t['combined_2024_plus_proximity']['top20%'])} | — |")
    L += ["", "| Вид | Утечка: доля в верхних 20% (2025 − 2024) | 95% ДИ (парный блочный бутстрэп) | Обучение: находок / фона |", "|---|---|---|---|"]
    for tx, t in r["taxa"].items():
        lk = t["leakage_2025_minus_2024_top20"]
        b = t["by_year"]["2024"]
        L.append(f"| {tx} | {lk['diff']:+.3f} | {lk['boot95'][0]:+.3f} … {lk['boot95'][1]:+.3f} | {b['n_train_pos']} / {b['n_train_bg']} |")
    L += ["", "| Вид | Расстояние от новой находки до старой (медиана) | То же для новых наблюдений других растений | Относительный риск по корзинам |", "|---|---|---|---|"]
    for tx, t in r["taxa"].items():
        dd = t["dispersal_distance"]
        rr = "; ".join(f"{b['from_m']}–{b['to_m'] or '∞'} м: {b['relative_risk']}" for b in dd["bins"])
        L.append(f"| {tx} | {dd['median_target_m']:.0f} м | {dd['median_background_m']:.0f} м | {rr} |")
    return "\n".join(L)


if __name__ == "__main__":
    f = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "analysis" / "results" / "retro_forecast.json"
    print(summarize(json.loads(f.read_text(encoding="utf-8"))))
