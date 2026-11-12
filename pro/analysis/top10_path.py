"""Путь в топ-10 демо-дня: Monte Carlo по уровням трекшна к маю 2027 года.

Факты: в топ-10 выходят «проекты, показавшие наилучшие результаты за время акселерации»
(итоги 1-го потока); в пресс-релизах финалистов всегда есть цифры — продажи, пилоты, инвестиции.
Из 100 проектов трекинга на демо-день выходят 10 (в 5-м потоке — 15).

Всё остальное — оценки [оценка], их диапазоны заданы треугольными распределениями.
Запуск: python3 analysis/top10_path.py → analysis/top10_path.json и таблица в stdout.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SEED, N = 20261107, 200_000
LEVELS = ["L0 ничего нового", "L1 только письма о намерениях", "L2 подписан пилот",
          "L3 пилот с измеренным результатом", "L4 платный договор + результат пилота"]
# P(топ-10 | топ-100, уровень): мин, мода, макс [оценка]
P10 = [(0.01, 0.02, 0.04), (0.03, 0.06, 0.10), (0.08, 0.14, 0.22), (0.20, 0.30, 0.42), (0.35, 0.50, 0.65)]

SCEN = {
    # распределение достигнутого уровня к демо-дню; концентрация Дирихле задаёт неуверенность
    "Текущая траектория (один автор, без писем)": {
        "levels": [0.20, 0.30, 0.25, 0.18, 0.07], "top100": (0.86, 0.92, 0.96), "team": 0.35, "wow": 0.5},
    "План «Путь в топ-10»": {
        "levels": [0.03, 0.12, 0.25, 0.30, 0.30], "top100": (0.92, 0.96, 0.99), "team": 0.80, "wow": 0.85},
}
TEAM_X = (1.05, 1.15, 1.25)   # команда 3–4 человека с ролями [оценка]
WOW_X = (1.00, 1.08, 1.15)    # живое демо «фото → закон → доказательство» [оценка]
CONC = 40.0


def tri(rng, t, n):
    return rng.triangular(t[0], t[1], t[2], n)


def simulate(s: dict, rng, n=N, override: dict | None = None) -> np.ndarray:
    s = {**s, **(override or {})}
    shares = rng.dirichlet(np.array(s["levels"]) * CONC, n)
    lvl = (rng.random(n)[:, None] > np.cumsum(shares, axis=1)).sum(axis=1)
    lvl = np.minimum(lvl, len(LEVELS) - 1)
    p = np.choose(lvl, [tri(rng, t, n) for t in P10])
    p = p * np.where(rng.random(n) < s["team"], tri(rng, TEAM_X, n), 1.0)
    p = p * np.where(rng.random(n) < s["wow"], tri(rng, WOW_X, n), 1.0)
    top100 = rng.random(n) < tri(rng, s["top100"], n)
    return top100 & (rng.random(n) < np.clip(p, 0, 0.9))


def main() -> dict:
    rng = np.random.default_rng(SEED)
    out = {"levels": LEVELS, "p_top10_given_level": P10, "scenarios": {}}
    for name, s in SCEN.items():
        x = simulate(s, rng)
        blocks = x[: N // 500 * 500].reshape(-1, 500).mean(axis=1)
        out["scenarios"][name] = {"P_top10": float(x.mean()), "P10_P90_of_block_means": [float(np.percentile(blocks, 10)),
                                                                                          float(np.percentile(blocks, 90))]}
    base = SCEN["План «Путь в топ-10»"]
    levers = {
        "нет платного договора до мая": {"levels": [0.03, 0.12, 0.25, 0.60, 0.00]},
        "нет пилота с результатом (только подписан)": {"levels": [0.03, 0.12, 0.85, 0.00, 0.00]},
        "автор один": {"team": 0.0},
        "нет живого демо": {"wow": 0.0},
        "слабая заявка (как сейчас)": {"top100": (0.86, 0.92, 0.96)},
    }
    p_plan = out["scenarios"]["План «Путь в топ-10»"]["P_top10"]
    out["tornado_vs_plan"] = {k: float(simulate(base, rng, override=v).mean()) - p_plan for k, v in levers.items()}
    Path(__file__).with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    r = main()
    print("| Сценарий | P(топ-10) | P10–P90 по блокам |\n|---|---|---|")
    for k, v in r["scenarios"].items():
        lo, hi = v["P10_P90_of_block_means"]
        print(f"| {k} | {v['P_top10']:.1%} | {lo:.0%}–{hi:.0%} |")
    print("\n| Что теряем, если не сделать | Изменение P(топ-10), п. п. |\n|---|---|")
    for k, v in sorted(r["tornado_vs_plan"].items(), key=lambda kv: kv[1]):
        print(f"| {k} | {v * 100:+.1f} |")
