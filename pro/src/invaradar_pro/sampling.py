"""Полевая проверка карты: стратифицированная выборка и оценки по Olofsson et al. (2014).

Слои — ранги карты (как в validation_sample.csv InvaRadar). Оценки:
- доля территории с видом: p = Σ W_h·p_h, SE = √(Σ W_h²·p_h(1−p_h)/(n_h−1));
- точность «очага» (доля подтверждённых среди точек верхних слоёв) и полнота (какую долю
  всей заражённой площади покрывают верхние слои) — с бутстрэпом по слоям.
"""
from __future__ import annotations

import math

import numpy as np

Z95 = 1.959963984540054


def sample_size_for_margin(p: float, margin: float, z: float = Z95) -> int:
    return int(math.ceil(z * z * p * (1 - p) / (margin * margin)))


def wilson_ci(x: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = x / n
    c = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo = (p + z * z / (2 * n) - c) / (1 + z * z / n)
    hi = (p + z * z / (2 * n) + c) / (1 + z * z / n)
    return (lo, hi)


def neyman_allocation(n: int, weights, p_guess, min_per: int = 10) -> np.ndarray:
    """Нейман: n_h ∝ W_h·√(p_h(1−p_h)), не меньше min_per в слое, сумма ровно n."""
    W = np.asarray(weights, float) / np.sum(weights)
    S = np.sqrt(np.clip(np.asarray(p_guess, float), 1e-6, 1 - 1e-6) * (1 - np.clip(np.asarray(p_guess, float), 1e-6, 1 - 1e-6)))
    if n < min_per * len(W):
        raise ValueError("выборка меньше минимума по слоям")
    rest = n - min_per * len(W)
    raw = rest * W * S / np.sum(W * S)
    alloc = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - alloc))[: rest - alloc.sum()]:
        alloc[i] += 1
    return alloc + min_per


def stratified_proportion(weights, n_h, x_h) -> dict:
    W = np.asarray(weights, float) / np.sum(weights)
    n = np.asarray(n_h, float)
    x = np.asarray(x_h, float)
    ph = x / n
    p = float(np.sum(W * ph))
    se = float(math.sqrt(np.sum(W * W * ph * (1 - ph) / np.maximum(n - 1, 1))))
    return {"p": p, "se": se, "ci95": (max(0.0, p - Z95 * se), min(1.0, p + Z95 * se)), "p_h": ph.tolist()}


def binary_accuracy(weights, n_h, x_h, positive_strata, n_boot: int = 4000, seed: int = 0) -> dict:
    """Точность и полнота класса «очаг» (верхние слои) с бутстрэп-интервалами."""
    W = np.asarray(weights, float) / np.sum(weights)
    n = np.asarray(n_h, int)
    x = np.asarray(x_h, int)
    pos = np.zeros(len(W), bool)
    pos[list(positive_strata)] = True

    def stats(xx):
        ph = xx / n
        prevalence = np.sum(W * ph)
        precision = np.sum(W[pos] * ph[pos]) / np.sum(W[pos])
        recall = np.sum(W[pos] * ph[pos]) / prevalence if prevalence > 0 else float("nan")
        return prevalence, precision, recall

    est = stats(x)
    rng = np.random.default_rng(seed)
    boots = np.array([stats(rng.binomial(n, x / n)) for _ in range(n_boot)])
    lo, hi = np.nanpercentile(boots, [2.5, 97.5], axis=0)
    keys = ("prevalence", "precision", "recall")
    return {k: {"est": float(e), "ci95": (float(a), float(b))} for k, e, a, b in zip(keys, est, lo, hi)}
