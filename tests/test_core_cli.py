"""Smoke test of the Rust core binary (skipped when it has not been built)."""
import subprocess

import numpy as np
import pytest

from invaradar.config import core_binary
from invaradar.queue import district_stops

CORE = core_binary()


def test_the_densest_stand_starts_the_route_and_is_not_listed_twice():
    alone_then_cluster = np.array([[0.0, 0.0], [1000.0, 0.0], [1010.0, 0.0], [1000.0, 10.0]])
    centre, stops = district_stops(alone_then_cluster, radius_m=50, n=15)
    assert centre == 1 and list(stops) == [2, 3]
    cluster = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    centre, stops = district_stops(cluster, radius_m=100, n=15)
    assert centre == 0 and list(stops) == [1, 2]


@pytest.mark.skipif(not CORE.exists(), reason="build the core first: cd core-rs && cargo build --release")
def test_route_visits_every_point_once(tmp_path):
    rng = np.random.default_rng(0)
    pts = rng.uniform(0, 1000, (30, 2)).astype("<f8")
    pts.tofile(tmp_path / "p.f64")
    subprocess.run([str(CORE), "route", str(tmp_path / "p.f64"), str(tmp_path / "r.txt")], check=True)
    out = (tmp_path / "r.txt").read_text().split()
    order = [int(i) for i in out[1:]]
    assert order[0] == 0 and sorted(order) == list(range(30))
    length = sum(np.hypot(*(pts[a] - pts[b])) for a, b in zip(order, order[1:]))
    assert abs(length - float(out[0])) < 0.2
