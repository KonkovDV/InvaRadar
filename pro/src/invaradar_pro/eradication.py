"""Доказательное закрытие очага: байесовская оценка «очаг ещё жив» и оптимальная остановка контроля.

Проблема (Regan et al., 2006, Ecology Letters 9:759–766): ликвидацию обычно объявляют по произволу —
по сроку жизни банка семян или по фиксированному порогу уверенности. Правильнее считать, когда
ожидаемая стоимость ещё одного сезона контроля превышает ожидаемый ущерб от ошибочного закрытия.

Модель — скрытая марковская цепь с двумя состояниями: «жив» (растения или живой банк семян) и «нет».
- После приёмки работ: P(жив) = p0. Он выше, если семена успели осыпаться.
- Осмотр: если очаг жив, его видят с вероятностью d. Бригада видит лучше, чем житель.
  Чистый осмотр: p ← p(1 − d) / (1 − p·d).
- Между сезонами: p ← ρ·p + r·(1 − p). ρ — доля, которая доживает до следующего сезона
  (банк семян гигантского борщевика короткоживущий: около 90% семян прорастает в первую зиму,
  через 5 лет выживает меньше 1% — Moravcová et al., 2006; Preslia, 2018).
  r — занос извне; берётся из spread.py.
- Остановка (закрытие) стоит p·C_esc: ожидаемый ущерб, если очаг жив и уйдёт без контроля.
- Сезон контроля стоит C_s; находка — C_t на повторную обработку и возврат к p0.

Оптимальная политика (стохастическое динамическое программирование по убеждению p) имеет вид
порога: закрывать, когда p < p*. Для сравнения есть близорукое правило: продолжать, пока
p·D·C_esc > C_s, где D — вероятность найти очаг за сезон.

Параметры по умолчанию — оценки [оценка], их нужно откалибровать на полевых данных.
Ориентир практики: департамент охраны среды штата Нью-Йорк (NYS DEC) объявляет участок
ликвидированным после трёх лет подряд без растений (1 369 участков на 2025 год).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DETECT_BY_ROLE = {"botanist": 0.85, "inspector": 0.75, "crew": 0.70, "citizen": 0.40, "model": 0.50}


@dataclass(frozen=True)
class ClosureParams:
    p0_no_seed: float = 0.60
    p0_seeded: float = 0.90
    rho_no_seed: float = 0.50
    rho_seeded: float = 0.80
    reinvasion: float = 0.02
    emergence: float = 0.60          # P(живой очаг даст видимые растения в этом сезоне): спящие семена не видны
    p_max: float = 0.05
    cost_season: float = 3_000.0     # ₽: два осмотра за сезон
    cost_escape: float = 120_000.0   # ₽: повторная обработка разросшегося очага и вред
    cost_treat: float = 20_000.0     # ₽: повторная обработка найденного очага
    discount: float = 0.95
    detect: dict = field(default_factory=lambda: dict(DETECT_BY_ROLE))

    @classmethod
    def from_policy(cls, policy: dict | None) -> ClosureParams:
        return cls(**(policy or {}))


def update_clean(p: float, d: float) -> float:
    return p * (1 - d) / (1 - p * d)


def predict(p: float, rho: float, r: float) -> float:
    return rho * p + r * (1 - p)


def belief_after(history: list[tuple[int, str, bool]], treated_season: int, seeded: bool,
                 prm: ClosureParams = ClosureParams()) -> float:
    """P(очаг жив) после истории контроля [(сезон, роль, отрастание), ...] начиная с сезона работ.

    Осмотры одного сезона объединяются: P(увидеть | жив) = всход × (1 − Π(1 − d_i)).
    Всход учитывает, что живой банк семян может «молчать» весь сезон.
    """
    p = prm.p0_seeded if seeded else prm.p0_no_seed
    rho = prm.rho_seeded if seeded else prm.rho_no_seed
    by_season: dict[int, list[float]] = {}
    for s, role, regrowth in history:
        if regrowth:
            return 1.0
        if s >= treated_season:
            by_season.setdefault(int(s), []).append(prm.detect.get(role, 0.5))
    season = treated_season
    for s in sorted(by_season):
        while season < s:
            p = predict(p, rho, prm.reinvasion)
            season += 1
        miss = float(np.prod([1 - d for d in by_season[s]]))
        p = update_clean(p, prm.emergence * (1 - miss))
    return p


def season_detection(d: float, surveys: int) -> float:
    return 1 - (1 - d) ** surveys


def optimal_threshold(prm: ClosureParams = ClosureParams(), seeded: bool = False, d: float = 0.70,
                      surveys: int = 2, grid: int = 2001, iters: int = 2000) -> dict:
    """Итерация ценности по убеждению p ∈ [0, 1]; возвращает порог p* и правило «сколько чистых сезонов»."""
    D = prm.emergence * season_detection(d, surveys)
    rho = prm.rho_seeded if seeded else prm.rho_no_seed
    p0 = prm.p0_seeded if seeded else prm.p0_no_seed
    ps = np.linspace(0.0, 1.0, grid)
    post = np.where(ps * D < 1, ps * (1 - D) / np.maximum(1 - ps * D, 1e-12), 0.0)
    nxt = rho * post + prm.reinvasion * (1 - post)
    V = ps * prm.cost_escape
    for _ in range(iters):
        v_reset = np.interp(predict(p0, rho, prm.reinvasion), ps, V)
        cont = prm.cost_season + prm.discount * (ps * D * (prm.cost_treat + v_reset)
                                                 + (1 - ps * D) * np.interp(nxt, ps, V))
        V_new = np.minimum(ps * prm.cost_escape, cont)
        if np.max(np.abs(V_new - V)) < 1e-6:
            V = V_new
            break
        V = V_new
    stop = ps * prm.cost_escape <= cont
    if not stop[0]:
        p_star = 0.0
    elif stop.all():
        p_star = 1.0
    else:
        p_star = float(ps[np.argmax(~stop)])  # закрывать, когда убеждение в начале сезона ниже p*
    # сколько сезонов контроля (включая сезон работ) до порога
    p, n = p0, 0
    while p >= p_star and n < 50:
        p = predict(update_clean(p, D), rho, prm.reinvasion)
        n += 1
    myopic = prm.cost_season / (D * prm.cost_escape)
    return {"p_star": round(p_star, 4), "seasons_including_treatment_year": n,
            "clean_seasons_after_treatment": max(n - 1, 0), "season_detection": round(D, 4),
            "myopic_threshold": round(myopic, 4),
            "stationary_without_surveys": round(prm.reinvasion / (1 - rho + prm.reinvasion), 4)}


def closure_check(followups: list[tuple[int, str, bool]], treated_season: int, seeded: bool,
                  prm: ClosureParams = ClosureParams()) -> dict:
    """Убеждение после контроля и на начало следующего сезона; ok — можно закрывать по доказательствам."""
    p_now = belief_after(followups, treated_season, seeded, prm)
    rho = prm.rho_seeded if seeded else prm.rho_no_seed
    p_next = predict(p_now, rho, prm.reinvasion) if p_now < 1 else 1.0
    return {"p_now": round(p_now, 4), "p_next": round(p_next, 4), "p_max": prm.p_max, "ok": p_next <= prm.p_max}


def feasibility(area_m2: float | None) -> dict:
    """Осуществимость ликвидации по площади очага (обзоры Rejmánek & Pitcairn, 2002, IUCN SSC OP 27).

    Ликвидация очагов меньше 1 га обычно удаётся. Для 1–1 000 га — примерно от четверти до трети
    программ. Больше 1 000 га — редко. Это ориентир для выбора стратегии (ликвидация или сдерживание),
    а не вероятность для конкретного очага.
    """
    if area_m2 is None:
        return {"class": "неизвестно", "strategy": "уточнить площадь на месте"}
    ha = area_m2 / 10_000
    if ha < 1:
        return {"class": "< 1 га", "strategy": "ликвидация: обычно удаётся", "indicative": "высокая"}
    if ha <= 100:
        return {"class": "1–100 га", "strategy": "ликвидация возможна, но успех около трети программ", "indicative": "≈ 1/3"}
    if ha <= 1000:
        return {"class": "100–1 000 га", "strategy": "сдерживание границ и ликвидация малых сателлитов", "indicative": "≈ 1/4"}
    return {"class": "> 1 000 га", "strategy": "сдерживание и защита людей; ликвидация редко реальна", "indicative": "редко"}
