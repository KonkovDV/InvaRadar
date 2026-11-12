"""Мощность и объём выборки для предрегистрированных исследований (docs/11).

- Две доли (H6, H7: отрастание и доля нарядов): аналитическая формула и проверка Монте-Карло.
- Разность разностей для долей (пилот против сравнения, до и после): Монте-Карло.
- Ширина интервала для доли в слое (H4).
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()


def n_two_proportions(p1: float, p2: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Объём на группу для двустороннего z-теста двух долей (формула Флейса без поправки на непрерывность)."""
    za, zb = _N.inv_cdf(1 - alpha / 2), _N.inv_cdf(power)
    pb = (p1 + p2) / 2
    num = (za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p1 - p2) ** 2)


def power_two_proportions(p1: float, p2: float, n: int, alpha: float = 0.05) -> float:
    za = _N.inv_cdf(1 - alpha / 2)
    pb = (p1 + p2) / 2
    se0 = math.sqrt(2 * pb * (1 - pb) / n)
    se1 = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n)
    return _N.cdf((abs(p1 - p2) - za * se0) / se1)


def simulate_did_power(p_base: float, rel_reduction: float, n_pilot: int, n_control: int, drift: float = 0.0,
                       n_sims: int = 4000, alpha: float = 0.05, seed: int = 0) -> float:
    """Мощность теста разности разностей для долей: пилот снижает долю на rel_reduction, общий сдвиг drift."""
    rng = np.random.default_rng(seed)
    za = _N.inv_cdf(1 - alpha / 2)
    pp0, pc0 = p_base, p_base
    pp1 = max(0.0, (p_base + drift) * (1 - rel_reduction))
    pc1 = max(0.0, p_base + drift)
    hits = 0
    for _ in range(n_sims):
        a0, a1 = rng.binomial(n_pilot, pp0) / n_pilot, rng.binomial(n_pilot, pp1) / n_pilot
        b0, b1 = rng.binomial(n_control, pc0) / n_control, rng.binomial(n_control, pc1) / n_control
        did = (a1 - a0) - (b1 - b0)
        var = sum(p * (1 - p) / n for p, n in ((a0, n_pilot), (a1, n_pilot), (b0, n_control), (b1, n_control)))
        if var > 0 and abs(did) / math.sqrt(var) > za:
            hits += 1
    return hits / n_sims


def ci_half_width(p: float, n: int, z: float = 1.959963984540054) -> float:
    return z * math.sqrt(p * (1 - p) / n)
