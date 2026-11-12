"""Калибровка и порядок выездов по ожидаемой пользе.

Аудит InvaRadar: формула приоритета перемножает ранг карты, близость людей, риск распространения
и размер с весами, которые никто не калибровал. Здесь вероятность и ценность разведены:

    польза выезда = P(подтвердится | ранг) × (вред + вклад в распространение) / стоимость выезда

P(подтвердится | ранг) — изотоническая регрессия по итогам полевых проверок (монотонна по рангу,
без допущений о форме). Веса вреда задаёт заказчик явно (например, методом swing weights),
и они видны в отчёте — а не спрятаны в коэффициентах 0,4 и 0,6.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def pav(y, w=None) -> np.ndarray:
    """Pool Adjacent Violators: ближайшая неубывающая последовательность (взвешенный МНК)."""
    y = np.asarray(y, float)
    w = np.ones_like(y) if w is None else np.asarray(w, float)
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi)
        wts.append(wi)
        cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), cnt.pop()
            v1, w1, c1 = vals.pop(), wts.pop(), cnt.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
            cnt.append(c1 + c2)
    return np.repeat(vals, cnt)


@dataclass
class IsotonicModel:
    x: np.ndarray
    y: np.ndarray

    def predict(self, x) -> np.ndarray:
        return np.interp(np.asarray(x, float), self.x, self.y)


def isotonic_fit(x, y, w=None) -> IsotonicModel:
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    w = np.ones_like(y) if w is None else np.asarray(w, float)
    order = np.argsort(x, kind="stable")
    x, y, w = x[order], y[order], w[order]
    ux, inv = np.unique(x, return_inverse=True)
    sw = np.bincount(inv, weights=w)
    sy = np.bincount(inv, weights=w * y) / sw
    return IsotonicModel(ux, pav(sy, sw))


def harm_score(d_child_m, in_settlement, water_zone_m, area_m2, weights=None) -> np.ndarray:
    """Вред без вероятности: люди рядом, вода (занос по течению), размер. Веса — от заказчика."""
    w = {"child": 3.0, "settlement": 1.0, "water": 1.0, "size": 1.0, **(weights or {})}
    d_child = np.asarray(d_child_m, float)
    return (1.0 + w["child"] * np.exp(-d_child / 150.0) + w["settlement"] * np.asarray(in_settlement, float)
            + w["water"] * (np.asarray(water_zone_m, float) > 0) + w["size"] * np.log10(1.0 + np.asarray(area_m2, float) / 400.0))


def expected_value(p_confirm, harm, cost) -> np.ndarray:
    return np.asarray(p_confirm, float) * np.asarray(harm, float) / np.maximum(np.asarray(cost, float), 1e-9)


def top_k_overlap(a, b, k: int) -> float:
    ta = set(np.argsort(-np.asarray(a, float), kind="stable")[:k])
    tb = set(np.argsort(-np.asarray(b, float), kind="stable")[:k])
    return len(ta & tb) / k


def reliability(p, y, bins: int = 5) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    return [{"bin": b, "p_mean": float(p[idx == b].mean()), "y_rate": float(y[idx == b].mean()), "n": int((idx == b).sum())}
            for b in range(bins) if (idx == b).any()]


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))
