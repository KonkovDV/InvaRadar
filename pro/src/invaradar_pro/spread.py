"""Прогноз появления новых очагов: давление семян × пригодность местообитания.

Модель на сетке. Интенсивность появления нового очага в клетке x за год:

    λ(x) = S(x) · [ α · (K_loc ∗ F)(x) + β · C(x) · (K_ldd ∗ (F · C))(x) ]

    S — пригодность (ранг карты ИнваРадар, 0–1);
    F — источники: площадь известных очагов в клетке;
    K_loc — локальное ядро разлёта семян (у борщевика основная масса — в нескольких метрах от растения);
    K_ldd — ядро дальнего заноса: вода, техника, грунт, покос вдоль дорог;
    C — близость коридора (дороги, вода, ЛЭП): exp(−d / L).

Вероятность появления за T лет: P = 1 − exp(−T·λ). Ядро — 2Dt (Clark et al., 1999):
f(r) = p / (π·u) · (1 + r²/u)^−(p+1); тяжёлый хвост задаёт параметр p.

Важно: при выборке «находки против фона» абсолютный уровень λ не определяется,
надёжны только ранги. Абсолютные вероятности даёт случайная полевая выборка (sampling.py).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

_LOG10_SCALE = np.arange(-3.0, 5.01, 0.25)


def kernel_2dt(cell_m: float, u_m2: float, p: float, radius_m: float) -> np.ndarray:
    r = max(1, int(np.ceil(radius_m / cell_m)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(float) * cell_m
    r2 = xx * xx + yy * yy
    k = p / (np.pi * u_m2) * (1.0 + r2 / u_m2) ** (-(p + 1.0)) * cell_m * cell_m
    k[r2 > radius_m * radius_m] = 0.0
    return k / k.sum()  # масса за радиусом перераспределена; дальний занос — отдельное слагаемое


def fft_convolve(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Свёртка 'same' через БПФ; ядро нечётного размера с центром в середине."""
    s = (a.shape[0] + k.shape[0] - 1, a.shape[1] + k.shape[1] - 1)
    full = np.fft.irfft2(np.fft.rfft2(a, s) * np.fft.rfft2(k, s), s)
    r0, r1 = k.shape[0] // 2, k.shape[1] // 2
    return np.clip(full[r0:r0 + a.shape[0], r1:r1 + a.shape[1]], 0.0, None)


def corridor_proximity(dist_m: np.ndarray, length_m: float = 200.0) -> np.ndarray:
    return np.exp(-np.asarray(dist_m, float) / length_m)


@dataclass(frozen=True)
class SpreadParams:
    cell_m: float = 50.0
    u_local_m2: float = 25.0      # масштаб 2Dt: медиана разлёта ~ первые метры [оценка по литературе]
    p_local: float = 1.5
    radius_local_m: float = 150.0
    u_ldd_m2: float = 250_000.0   # дальний занос: сотни метров — километры вдоль коридоров [оценка]
    p_ldd: float = 1.0
    radius_ldd_m: float = 3_000.0
    alpha: float = 1.0
    beta: float = 1.0
    years: float = 1.0


def pressure(sources: np.ndarray, suitability: np.ndarray, corridor: np.ndarray, prm: SpreadParams) -> np.ndarray:
    k_loc = kernel_2dt(prm.cell_m, prm.u_local_m2, prm.p_local, prm.radius_local_m)
    k_ldd = kernel_2dt(prm.cell_m, prm.u_ldd_m2, prm.p_ldd, prm.radius_ldd_m)
    local = fft_convolve(sources, k_loc)
    ldd = fft_convolve(sources * corridor, k_ldd) * corridor
    return suitability * (prm.alpha * local + prm.beta * ldd)


def colonization_probability(lam: np.ndarray, years: float = 1.0) -> np.ndarray:
    return 1.0 - np.exp(-years * lam)


def capture_at(scores: np.ndarray, targets: np.ndarray, k: float, valid: np.ndarray | None = None) -> float:
    """Доля целевых клеток (новых находок), попавших в верхние k доли площади по оценке."""
    s = np.asarray(scores, float)
    t = np.asarray(targets, bool)
    v = np.ones_like(t) if valid is None else np.asarray(valid, bool)
    if not t[v].any():
        return float("nan")
    order = np.argsort(-s[v], kind="stable")
    n_top = max(1, int(round(k * v.sum())))
    top = np.zeros(v.sum(), bool)
    top[order[:n_top]] = True
    return float(top[t[v]].mean())


def capture_curve(scores, targets, ks=(0.01, 0.05, 0.10, 0.20), valid=None) -> dict[str, float]:
    return {f"top{int(k * 100)}%": capture_at(scores, targets, k, valid) for k in ks}


def bernoulli_loglik(prob: np.ndarray, present: np.ndarray, absent: np.ndarray, eps: float = 1e-9) -> float:
    p = np.clip(prob, eps, 1 - eps)
    return float(np.log(p[present]).sum() + np.log(1 - p[absent]).sum())


def fit_rates(sources, suitability, corridor, present, absent, base: SpreadParams,
              shares=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0), log10_scale=_LOG10_SCALE):
    """Максимум бернуллиевского правдоподобия по доле дальнего заноса и общему масштабу.

    λ линейна по α и β, поэтому свёртки считаются один раз, а перебор идёт только по точкам выборки:
    α = s·(1 − w), β = s·w. При выборке «находки против фона» надёжна доля w, а не уровень s.
    """
    k_loc = kernel_2dt(base.cell_m, base.u_local_m2, base.p_local, base.radius_local_m)
    k_ldd = kernel_2dt(base.cell_m, base.u_ldd_m2, base.p_ldd, base.radius_ldd_m)
    local = (suitability * fft_convolve(sources, k_loc))
    ldd = (suitability * fft_convolve(sources * corridor, k_ldd) * corridor)
    pres, absn = np.asarray(present, bool), np.asarray(absent, bool)
    lp, la = local[pres], local[absn]
    dp, da = ldd[pres], ldd[absn]
    best = (-np.inf, base)
    for w in shares:
        for ls in log10_scale:
            s = 10.0 ** ls
            pp = colonization_probability(s * ((1 - w) * lp + w * dp), base.years)
            pa = colonization_probability(s * ((1 - w) * la + w * da), base.years)
            ll = float(np.log(np.clip(pp, 1e-12, 1)).sum() + np.log(np.clip(1 - pa, 1e-12, 1)).sum())
            if ll > best[0]:
                best = (ll, replace(base, alpha=s * (1 - w), beta=s * w))
    return best[1], best[0]


def scale_to_expected(lam: np.ndarray, target: float, valid: np.ndarray, years: float = 1.0) -> float:
    """Множитель s, при котором ожидаемое число новых клеток Σ(1 − e^(−s·λ)) равно target (бисекция)."""
    lv = lam[valid]
    lo, hi = 1e-9, 1e9
    for _ in range(200):
        mid = np.sqrt(lo * hi)
        if np.sum(1 - np.exp(-mid * years * lv)) < target:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))
