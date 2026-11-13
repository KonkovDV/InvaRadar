"""Честная проверка карты и ретро-прогноза (аудит A-02) плюс диагностика пространственной кросс-проверки.

1. Ретро-прогноз: признаки года T (например, эмбеддинг AlphaEarth 2024), метки до T — обучение;
   новые места T+1…T+2 дальше min_dist от старых меток — проверка. Метрика — доля новых мест
   в верхних k долях площади (ранги по случайным точкам ландшафта), с интервалом Уилсона
   и блочным бутстрэпом.
2. Диагностика NNDM (Milà et al., 2022; kNNDM — Linnenbrink et al., 2024, GMD 17:5897).
   Кросс-проверка честна, если распределение расстояний «проверочная точка → ближайшая обучающая»
   похоже на распределение «точка карты → ближайшая обучающая». Сравнение — по W1 (Вассерштейн-1).
3. Карта точности по дизайну. Её даёт только вероятностная выборка (sampling.py; Wadoux et al., 2021;
   Stehman & Foody, 2019), а не кросс-проверка на сгущённых данных граждан.
"""
from __future__ import annotations

import numpy as np

from .sampling import wilson_ci


def nearest_dist(a_xy, b_xy, chunk: int = 2048) -> np.ndarray:
    a = np.asarray(a_xy, float)
    b = np.asarray(b_xy, float)
    out = np.empty(len(a))
    for i in range(0, len(a), chunk):
        d2 = ((a[i:i + chunk, None, :] - b[None, :, :]) ** 2).sum(-1)
        out[i:i + chunk] = np.sqrt(d2.min(axis=1))
    return out


def new_sites_mask(new_xy, old_xy, min_dist: float) -> np.ndarray:
    """Новые места: дальше min_dist от любой старой метки (у InvaRadar — 500 м, шире окна признака 450 м)."""
    return nearest_dist(new_xy, old_xy) > min_dist


def percentile_in(landscape, scores) -> np.ndarray:
    """Share of the landscape at or below each score. The landscape is sorted here."""
    ref = np.sort(np.asarray(landscape, float))
    return np.searchsorted(ref, np.asarray(scores, float), side="right") / len(ref)


def combine_model_and_proximity(model_land, model_far, prox_land, prox_far, land_valid, far_valid):
    """Average the two ranks on one landscape.

    The model landscape is already the rows where the image exists. Proximity uses
    those same rows as its reference, not the points the image could not score.
    A new place without an image is left out of the capture.
    """
    model_land = np.asarray(model_land, float)
    model_far = np.asarray(model_far, float)
    prox_land = np.asarray(prox_land, float)
    prox_far = np.asarray(prox_far, float)
    land_valid = np.asarray(land_valid, bool)
    far_valid = np.asarray(far_valid, bool)
    if len(model_land) != int(land_valid.sum()):
        raise ValueError("the model landscape must already be the valid rows")
    if len(model_far) != len(far_valid) or len(prox_far) != len(far_valid):
        raise ValueError("far scores must have one value per new place")
    if len(prox_land) != len(land_valid):
        raise ValueError("proximity must have one value per landscape point")
    if len(model_land) == 0:
        raise ValueError("the image scored no landscape point")
    reference = prox_land[land_valid]
    kept = model_far[far_valid]
    comb_land = 0.5 * percentile_in(model_land, model_land) + 0.5 * percentile_in(reference, reference)
    comb_far = 0.5 * percentile_in(model_land, kept) + 0.5 * percentile_in(reference, prox_far[far_valid])
    return comb_far, comb_land


def capture_at_area(target_scores, landscape_scores, k: float) -> float:
    thr = np.quantile(np.asarray(landscape_scores, float), 1 - k)
    return float(np.mean(np.asarray(target_scores, float) >= thr))


def capture_report(target_scores, landscape_scores, ks=(0.01, 0.05, 0.10, 0.20), blocks=None,
                   n_boot: int = 2000, seed: int = 0) -> dict:
    t = np.asarray(target_scores, float)
    out = {}
    rng = np.random.default_rng(seed)
    for k in ks:
        c = capture_at_area(t, landscape_scores, k)
        x = int(round(c * len(t)))
        row = {"capture": round(c, 4), "lift": round(c / k, 2), "wilson95": tuple(round(v, 4) for v in wilson_ci(x, len(t)))}
        if blocks is not None:
            b = np.asarray(blocks)
            ub = np.unique(b)
            idx = [np.where(b == u)[0] for u in ub]
            boots = []
            for _ in range(n_boot):
                pick = rng.integers(0, len(ub), len(ub))
                sel = np.concatenate([idx[j] for j in pick])
                boots.append(capture_at_area(t[sel], landscape_scores, k))
            row["block_boot95"] = tuple(round(float(v), 4) for v in np.percentile(boots, [2.5, 97.5]))
        out[f"top{int(round(k * 100))}%"] = row
    return out


def retro_forecast_verdict(report: dict, key: str = "top20%") -> str:
    """Предрегистрированное правило (docs/11): прогноз подтверждён, если нижняя граница 95% ДИ выше k."""
    k = float(key.strip("top%")) / 100
    lo = report[key].get("block_boot95", report[key]["wilson95"])[0]
    if lo > 2 * k:
        return "сильный прогноз: нижняя граница выше удвоенной случайной доли"
    if lo > k:
        return "прогноз подтверждён: лучше случайного обхода"
    return "не подтверждён: интервал включает случайный обход"


def wasserstein1(a, b) -> float:
    a = np.sort(np.asarray(a, float))
    b = np.sort(np.asarray(b, float))
    q = np.linspace(0, 1, 513)[1:-1]
    return float(np.mean(np.abs(np.quantile(a, q) - np.quantile(b, q))))


def nndm_diagnostic(pred_xy, train_xy, cv_test_to_train_dist) -> dict:
    """Сравнение распределений расстояний: точка карты → обучение и проверка → обучение (вне фолда)."""
    d_pred = nearest_dist(pred_xy, train_xy)
    d_cv = np.asarray(cv_test_to_train_dist, float)
    w1 = wasserstein1(d_pred, d_cv)
    return {"pred_median_m": float(np.median(d_pred)), "cv_median_m": float(np.median(d_cv)),
            "w1_m": round(w1, 1), "w1_relative": round(w1 / max(np.median(d_pred), 1e-9), 3),
            "verdict": "кросс-проверка похожа на условия карты" if w1 <= 0.25 * np.median(d_pred)
            else "кросс-проверка не похожа на условия карты: нужна kNNDM или вероятностная выборка"}
