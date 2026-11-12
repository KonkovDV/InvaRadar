import math

import numpy as np
import pytest
from invaradar_pro.calibration import isotonic_fit, pav, top_k_overlap
from invaradar_pro.corridor import Line, audit, power_zone_m
from invaradar_pro.geo import circle_strip_overlap, haversine_m, point_to_polyline, to_local_xy
from invaradar_pro.sampling import (
    binary_accuracy,
    neyman_allocation,
    sample_size_for_margin,
    stratified_proportion,
    wilson_ci,
)
from invaradar_pro.spread import (
    SpreadParams,
    capture_at,
    colonization_probability,
    corridor_proximity,
    fft_convolve,
    fit_rates,
    kernel_2dt,
    pressure,
    scale_to_expected,
)


def test_geo_basics():
    assert abs(haversine_m(55.75, 37.6, 55.76, 37.6) - 1111.95) < 0.5
    x, y = to_local_xy(55.76, 37.62, 55.75, 37.6)
    assert abs(math.hypot(x, y) - haversine_m(55.75, 37.6, 55.76, 37.62)) < 2.0
    d, ch = point_to_polyline([500, 1500], [10, -30], [0, 1000, 2000], [0, 0, 0])
    assert np.allclose(d, [10, 30]) and np.allclose(ch, [500, 1500])


def test_circle_strip_overlap_exact_and_mc():
    assert math.isclose(circle_strip_overlap(10, 0, 20), math.pi * 100, rel_tol=1e-12)
    assert circle_strip_overlap(10, 0, 0) == 0 and circle_strip_overlap(10, 100, 5) == 0
    rng = np.random.default_rng(0)
    pts = rng.uniform(-10, 10, (400_000, 2))
    inside = (pts ** 2).sum(1) <= 100
    mc = 400 * np.mean(inside & (np.abs(pts[:, 1] + 8) <= 5))  # центр в 8 м от оси, полоса ±5 м
    assert math.isclose(circle_strip_overlap(10, 8, 5), mc, rel_tol=0.02)


def test_power_zones_and_audit():
    assert [power_zone_m(k) for k in (0.4, 10, 35, 110, 220, 500, 750)] == [2, 10, 15, 20, 25, 30, 40]
    line = Line("L", "power", "демо", np.array([0.0, 5000.0]), np.array([0.0, 0.0]), half_width_m=24)
    f = audit([line], [1500, 2500, 3200], [5, 100, -30], [100, 100, 900], [90, 80, 70], ["a", "b", "c"])
    assert [(g.km_from, g.focus_ids) for g in f] == [(1.0, ["a"]), (3.0, ["c"])]
    assert f[0].area_in_zone_m2 == pytest.approx(100, rel=1e-6)


def test_kernel_and_fft():
    k = kernel_2dt(10, 25, 1.5, 100)
    assert math.isclose(k.sum(), 1.0) and np.allclose(k, k[::-1, ::-1]) and k[10, 10] == k.max()
    rng = np.random.default_rng(0)
    a, kk = rng.random((12, 15)), rng.random((5, 5))
    direct = np.zeros_like(a)
    for i in range(12):
        for j in range(15):
            for u in range(-2, 3):
                for v in range(-2, 3):
                    if 0 <= i - u < 12 and 0 <= j - v < 15:
                        direct[i, j] += a[i - u, j - v] * kk[u + 2, v + 2]
    assert np.allclose(fft_convolve(a, kk), direct)


def test_spread_fit_beats_suitability_alone():
    rng = np.random.default_rng(3)
    n = 120
    src = np.zeros((n, n))
    src[rng.integers(10, 110, 12), rng.integers(10, 110, 12)] = rng.uniform(1, 10, 12)
    yy, xx = np.mgrid[0:n, 0:n]
    corr = corridor_proximity(np.minimum(np.abs(xx * 100 - 6000), np.abs(yy * 100 - 4000)), 200)
    suit = rng.uniform(0.2, 1.0, (n, n))
    true = SpreadParams(cell_m=100, alpha=0.2, beta=0.8, radius_ldd_m=3000)
    valid = src == 0
    lam = pressure(src, suit, corr, true)
    new = (rng.random((n, n)) < colonization_probability(lam * scale_to_expected(lam, 150, valid))) & valid
    absent = valid & ~new & (rng.random((n, n)) < 0.3)
    fitted, _ = fit_rates(src, suit, corr, new, absent, SpreadParams(cell_m=100, radius_ldd_m=3000))
    model = pressure(src, suit, corr, fitted)
    assert capture_at(model, new, 0.10, valid) > 2 * capture_at(suit, new, 0.10, valid)
    assert capture_at(model, new, 0.10, valid) > 0.4


def test_isotonic_and_overlap():
    assert np.allclose(pav([1, 3, 2, 4]), [1, 2.5, 2.5, 4])
    m = isotonic_fit([0.1, 0.2, 0.3, 0.4, 0.5], [0, 1, 0, 1, 1])
    assert np.all(np.diff(m.predict(np.linspace(0, 1, 11))) >= 0)
    assert top_k_overlap([5, 4, 3, 2], [5, 3, 4, 1], 2) == 0.5


def test_sampling():
    assert sample_size_for_margin(0.5, 0.1) == 97
    lo, hi = wilson_ci(24, 90)
    assert lo < 24 / 90 < hi
    alloc = neyman_allocation(250, [0.8, 0.15, 0.03, 0.02], [0.01, 0.04, 0.12, 0.3], min_per=30)
    assert alloc.sum() == 250 and alloc.min() >= 30
    est = stratified_proportion([0.5, 0.5], [10, 10], [2, 6])
    assert math.isclose(est["p"], 0.4)
    assert math.isclose(est["se"], math.sqrt(0.25 * 0.2 * 0.8 / 9 + 0.25 * 0.6 * 0.4 / 9))
    acc = binary_accuracy([0.9, 0.1], [50, 50], [5, 25], positive_strata=[1], n_boot=500)
    assert math.isclose(acc["precision"]["est"], 0.5)
    assert math.isclose(acc["recall"]["est"], 0.05 / (0.09 + 0.05))
