"""A presence is not zero metres from itself, and the stack keeps one copy of the corridors."""
import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "temporal_features", Path(__file__).resolve().parents[1] / "scripts" / "temporal_features.py")
feat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feat)


def test_the_only_presence_is_not_zero_metres_from_itself():
    dist = feat.distance_excluding_self([[0.0, 0.0]], [[0.0, 0.0]])
    assert np.isinf(dist).all()


def test_a_reference_point_uses_the_next_presence_rather_than_itself():
    dist = feat.distance_excluding_self([[0.0, 0.0], [30.0, 0.0]], [[0.0, 0.0], [10.0, 0.0]])
    assert dist[0] == 10.0
    assert dist[1] == 20.0


def test_the_stack_keeps_the_later_corridors_once():
    later = np.arange(8, dtype=np.float32).reshape(2, 4)
    earlier = np.zeros((2, 4), dtype=np.float32)
    got = feat.stack_embedding_years(later, earlier, n_embed=2)
    assert got.shape == (2, 6)
    assert np.array_equal(got[:, :2], earlier[:, :2])
    assert np.array_equal(got[:, 2:4], later[:, :2])
    assert np.array_equal(got[:, 4:], later[:, 2:])


def test_the_recorded_stack_and_distance_stay_on_the_same_new_places():
    import json
    data = json.loads((Path(__file__).resolve().parents[1] / "outputs" / "variants" / "temporal_features.json").read_text())
    expect = {
        "heracleum": {"n": 216, "image": 73, "mean": 79, "candidates": 504, "near": 208},
        "solidago": {"n": 188, "image": 65, "mean": 63, "candidates": 446, "near": 184},
    }
    for taxon, want in expect.items():
        got = data["taxa"][taxon]
        assert got["samples_dropped_as_nodata"] == 0
        assert got["n_new_presence"] == want["n"]
        assert got["models"]["image_2024"]["block"]["top20%"]["n_captured"] == want["image"]
        assert got["models"]["mean_2023_2024"]["block"]["top20%"]["n_captured"] == want["mean"]
        assert got["models"]["stack_2023_2024"]["n_features"] == 521
        for name in ("stack_minus_2024", "distance_minus_2024"):
            gap = got["paired"][name]["top20%"]
            assert gap["boot95"][0] <= 0 <= gap["boot95"][1]
        dispersal = got["dispersal_all_new_reports"]
        assert dispersal["n_target"] == want["candidates"]
        assert dispersal["bins"][0]["target_count"] == want["near"]
    hogweed_top10 = data["taxa"]["heracleum"]["paired"]["distance_minus_2024"]["top10%"]
    assert hogweed_top10["boot95"][1] < 0


def test_wilson_covers_the_observed_share():
    low, high = feat.wilson(3, 10)
    assert 0.0 <= low <= 0.3 <= high <= 1.0
