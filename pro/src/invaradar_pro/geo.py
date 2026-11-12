"""Геометрия без внешних зависимостей: расстояния, локальная проекция, ломаные и полосы отвода."""
from __future__ import annotations

import math

import numpy as np

R_EARTH_M = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2):
    """Расстояние по большому кругу, метры. Принимает числа или массивы."""
    la1, lo1, la2, lo2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    d = 2 * R_EARTH_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return float(d) if np.ndim(d) == 0 else d


def to_local_xy(lat, lon, lat0: float, lon0: float):
    """Равнопромежуточная проекция вокруг (lat0, lon0), метры.

    Относительная ошибка масштаба по x ≈ tg φ · Δφ: для Москвы (φ ≈ 55,75°) это 0,6 % при удалении
    на 25 км по широте. Для аудита полос в десятки метров этого достаточно; для кадастра — нет
    (там нужна МСК-50/МСК-77 через pyproj, это задача интеграции).
    """
    k = math.radians(1.0) * R_EARTH_M
    x = (np.asarray(lon, dtype=float) - lon0) * k * math.cos(math.radians(lat0))
    y = (np.asarray(lat, dtype=float) - lat0) * k
    return x, y


def polyline_length(xs, ys) -> float:
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    return float(np.hypot(np.diff(xs), np.diff(ys)).sum())


def point_to_polyline(px, py, xs, ys):
    """Для каждой точки: расстояние до ломаной и пикет (метры от начала линии)."""
    px = np.atleast_1d(np.asarray(px, float))
    py = np.atleast_1d(np.asarray(py, float))
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if xs.size < 2:
        raise ValueError("в ломаной нужно минимум две вершины")
    ax, ay, dx, dy = xs[:-1], ys[:-1], np.diff(xs), np.diff(ys)
    seg2 = dx * dx + dy * dy
    seg = np.sqrt(seg2)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    t = ((px[:, None] - ax) * dx + (py[:, None] - ay) * dy) / np.where(seg2 > 0, seg2, 1.0)
    t = np.clip(t, 0.0, 1.0)
    d = np.hypot(px[:, None] - (ax + t * dx), py[:, None] - (ay + t * dy))
    i = np.argmin(d, axis=1)
    rows = np.arange(px.size)
    return d[rows, i], cum[i] + t[rows, i] * seg[i]


def _area_below(r, h):
    """Площадь части круга радиуса r (центр в 0), лежащей ниже прямой y = h."""
    h = np.clip(h, -r, r)
    rr = np.where(r > 0, r, 1.0)
    s = r * r * np.arccos(-h / rr) + h * np.sqrt(np.maximum(r * r - h * h, 0.0))
    return np.where(r > 0, s, 0.0)


def circle_strip_overlap(r, d, half_width):
    """Площадь круга (радиус r, центр на расстоянии d от оси) внутри полосы |y| ≤ half_width.

    Очаг аппроксимирован кругом той же площади, ось полосы локально прямая. Формула точная
    для этих допущений: S(hw − d) − S(−hw − d), где S(h) = r²·arccos(−h/r) + h·√(r² − h²).
    """
    r = np.asarray(r, float)
    d = np.abs(np.asarray(d, float))
    hw = np.asarray(half_width, float)
    out = _area_below(r, hw - d) - _area_below(r, -hw - d)
    return float(out) if np.ndim(out) == 0 else out
