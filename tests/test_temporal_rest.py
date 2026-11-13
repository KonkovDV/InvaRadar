"""The mean of two embedding years keeps the corridors and the terrain."""
import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "temporal_rest", Path(__file__).resolve().parents[1] / "scripts" / "temporal_rest.py")
rest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rest)


def test_the_mean_averages_only_the_embedding_columns():
    left = np.arange(8, dtype=np.float32).reshape(2, 4)
    right = np.array([[4, 0, 0, 9], [0, 2, 8, 1]], dtype=np.float32)
    got = rest.mean_embedding_columns(left, right, n_embed=2)
    assert np.allclose(got[:, :2], (left[:, :2] + right[:, :2]) / 2)
    assert np.array_equal(got[:, 2:], left[:, 2:])
    try:
        rest.mean_embedding_columns(left, right[:, :3], n_embed=2)
    except ValueError:
        pass
    else:
        raise AssertionError("different shapes must be rejected")


def test_the_recorded_file_keeps_2023_on_the_same_places_as_2024_and_2025():
    import json
    data = json.loads((Path(__file__).resolve().parents[1] / "outputs" / "variants" / "temporal_rest.json").read_text())
    earlier = json.loads((Path(__file__).resolve().parents[1] / "outputs" / "variants" / "paired_2025_minus_2024.json").read_text())
    expect = {"heracleum": (216, 73, 75), "solidago": (188, 65, 78)}
    for taxon, (n, early, late) in expect.items():
        got = data["taxa"][taxon]
        assert got["samples_dropped_as_nodata_on_any_image"] == 0
        assert got["n_new_presence"] == n
        assert all(got["agreement_with_stored_files"].values())
        assert got["by_year"]["2023"]["block"]["top20%"]["n_captured"] == early
        assert got["by_year"]["2024"]["block"]["top20%"]["n_captured"] == early
        assert got["by_year"]["2025"]["block"]["top20%"]["n_captured"] == late
        assert got["proximity_to_older_presence"]["block"]["top10%"]["n_captured"] == 0
        assert got["mean_2023_2024"]["corridors_copied_from_2024"] is True
        fresh = got["paired"]["2025_minus_2024"]["top20%"]
        stored = earlier["taxa"][taxon]["paired_2025_minus_2024"]["top20%"]
        assert fresh["diff"] == stored["diff"] and fresh["boot95"] == stored["boot95"]
        mean_gap = got["paired"]["mean_minus_2024"]["top20%"]
        assert mean_gap["boot95"][0] <= 0 <= mean_gap["boot95"][1]


def test_distance_is_zero_on_the_reference_point_itself():
    dist = rest.nearest_distance([[0.0, 0.0], [3.0, 4.0]], [[0.0, 0.0]])
    assert dist[0] == 0.0 and dist[1] == 5.0
