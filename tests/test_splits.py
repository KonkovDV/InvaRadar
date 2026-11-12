"""The check must sit outside the feature window, and a test plant must not edit the training set."""
import json
import os

import numpy as np
import pandas as pd
from pyproj import Transformer

from invaradar.config import OUT
from invaradar.samples import CLEAR_M, build
from invaradar.splits import (
    BLOCK_M,
    CAPTURE_LEVELS,
    PURGE_M,
    WINDOW_M,
    boyce_index,
    boyce_ratios,
    feature_year,
    iter_spatial_folds,
    landscape_percentile,
    prepare_fold,
    presence_spacing,
    read_rank_cache,
    temporal_sets,
)


def test_a_rank_cache_is_used_only_when_it_matches_this_sample(tmp_path):
    p = tmp_path / "rk.f64"
    assert read_rank_cache(p, 3) is None
    np.array([0.1, np.nan, -0.0], "<f8").tofile(p)
    got = read_rank_cache(p, 3)
    assert got is not None and got[0] == 0.1 and np.isnan(got[1]) and np.signbit(got[2])
    assert read_rank_cache(p, 2) is None
    newer = tmp_path / "pts.f32"
    newer.write_bytes(b"x")
    # The feature dump is newer than the ranks, so the ranks belong to an older run.
    os.utime(newer, (p.stat().st_mtime + 10, p.stat().st_mtime + 10))
    assert read_rank_cache(p, 3, newer) is None


def test_the_southern_edge_of_a_cell_belongs_to_the_cell_south_of_it():
    from invaradar.config import STUDY_BOX
    from invaradar.samples import study_pixel
    west, _south, _east, north = STUDY_BOX
    _col, row_inside = study_pixel(west + 5, north - 5)
    _col, row_edge = study_pixel(west + 5, north - 10)
    _col, row_south = study_pixel(west + 5, north - 10 - 1e-6)
    assert int(row_inside) == 0 and int(row_edge) == 1 and int(row_south) == 1


def test_one_forest_serves_the_map_and_the_intervals_and_capture_is_the_top_share():
    from invaradar.model import MAP_PARAMS, MAP_TREES
    from invaradar.splits import capture_rates
    assert MAP_TREES == 300 and MAP_PARAMS["learning_rate"] == 0.05 and MAP_PARAMS["num_leaves"] == 15
    rates = capture_rates([0.5, 0.99, np.nan])
    assert rates["capture@1%area"] == 0.5 and rates["capture@10%area"] == 0.5
    assert capture_rates([])["capture@10%area"] is None


def test_the_published_map_uses_this_protocol_and_the_top_bin_is_the_capture():
    for taxon in ("heracleum", "solidago"):
        metrics = json.loads((OUT / taxon / "metrics.json").read_text(encoding="utf-8"))
        protocol = metrics["protocol"]
        assert protocol["block_m"] == BLOCK_M
        assert protocol["purge_m"] == PURGE_M
        assert protocol["window_m"] == WINDOW_M
        assert protocol["clear_m"] == CLEAR_M
        assert PURGE_M > WINDOW_M
        capture = metrics["spatial_cv"]["capture@10%area"]
        top_bin = metrics["spatial_cv"]["boyce_ratio"][-1]
        assert top_bin == round(capture / 0.10, 3)


def test_the_interval_file_is_the_same_run_as_the_map():
    for taxon in ("heracleum", "solidago"):
        metrics = json.loads((OUT / taxon / "metrics.json").read_text(encoding="utf-8"))
        intervals = json.loads((OUT / taxon / "uncertainty.json").read_text(encoding="utf-8"))
        assert intervals["n_presence"] == metrics["samples"]["presence"]
        temporal = metrics["temporal_test"]
        assert temporal["n_new_presence"] + temporal["n_new_inside_ring"] == temporal["n_new_candidates"]
        for key in ("n_new_presence", "n_new_candidates", "n_new_inside_ring"):
            assert intervals["temporal_test"][key] == temporal[key]
        ratios = metrics["spatial_cv"]["boyce_ratio"]
        assert abs(sum(ratios) - 10) < 0.01
        assert abs(sum(metrics["importance_share"].values()) - 1) < 0.01
        if metrics["terrain"]:
            assert metrics["importance_share"]["terrain"] > 0
        else:
            assert metrics["importance_share"]["terrain"] == 0
        for k in CAPTURE_LEVELS:
            for block in ("spatial_cv", "temporal_test"):
                published = intervals[block][f"capture@{k}%area"]
                assert published["estimate"] == round(metrics[block][f"capture@{k}%area"], 4)
                assert published["lift"] == round(published["estimate"] / (k / 100), 2)


def test_a_missing_score_is_not_reported_as_the_top_of_the_map():
    land = np.array([0.1, 0.4, 0.9])
    got = landscape_percentile(land, [0.4, np.nan, 0.95])
    assert got[0] == np.searchsorted(land, 0.4) / 3
    assert np.isnan(got[1])
    assert got[2] == 1.0


def test_a_training_ring_inside_the_feature_window_is_dropped_and_each_side_clears_its_own_background():
    xy = np.array([
        [0.0, 0.0],       # training presence
        [20.0, 0.0],      # background 20 m from that presence: cleared on the training side
        [200.0, 0.0],     # background outside 30 m and outside the 500 m purge
        [9600.0, 0.0],    # 400 m from the test presence: inside the purge, not a training row
        [10000.0, 0.0],   # test presence
        [10020.0, 0.0],   # background 20 m from the test presence: cleared on the test side only
    ])
    y = np.array([1, 0, 0, 0, 1, 0])
    train, test = prepare_fold(xy, y, np.array([0, 1, 2, 3]), np.array([4, 5]))
    assert set(train.tolist()) == {0, 2}
    assert set(test.tolist()) == {4}
    assert PURGE_M == 500.0


def test_a_test_background_point_does_not_delete_the_training_neighbourhood():
    xy = np.array([[0.0, 0.0], [400.0, 0.0], [500.0, 0.0], [20000.0, 0.0]])
    y = np.array([1, 0, 0, 1])
    train, _test = prepare_fold(xy, y, np.array([0, 1]), np.array([2, 3]))
    assert 1 in set(train.tolist())


def test_adjacent_blocks_fall_in_different_checkerboard_folds():
    xy = np.array([[0.0, 0.0], [5000.0, 0.0], [0.0, 5000.0], [5000.0, 5000.0]])
    held = [set(te.tolist()) for _tr, te in iter_spatial_folds(xy, np.ones(4), n_splits=2, purge_m=1, clear_m=1)]
    assert {0, 3} in held
    assert {1, 2} in held


def test_boyce_is_high_when_presences_occupy_the_top_of_the_percentile_map():
    top = boyce_index(np.linspace(0.8, 0.99, 40))
    bottom = boyce_index(np.linspace(0.01, 0.2, 40))
    assert top is not None and bottom is not None
    assert top > 0.4 and bottom < 0 and top > bottom


def _ranks_with_ratios(ratios):
    parts = [np.linspace(i / 10 + 0.002, (i + 1) / 10 - 0.002, int(r * 30)) for i, r in enumerate(ratios)]
    return np.concatenate(parts)


def test_boyce_orders_the_bins_and_does_not_measure_the_slope():
    gentle_r = np.linspace(0.7, 1.3, 10)
    steep_r = np.linspace(0.2, 1.8, 10)
    gentle, steep = boyce_index(_ranks_with_ratios(gentle_r)), boyce_index(_ranks_with_ratios(steep_r))
    assert gentle > 0.95 and steep > 0.95
    got = boyce_ratios(_ranks_with_ratios(steep_r))
    assert got[0] < 1 < got[-1] and got[-1] > boyce_ratios(_ranks_with_ratios(gentle_r))[-1]
    # A spike in one bin ties the empty bins, so the index is not 1 even though the top is full.
    assert boyce_index(np.full(40, 0.97)) < 0.8


def test_spacing_separates_a_clump_inside_one_block_from_a_neighbour_across_the_edge():
    clump = np.array([[100.0, 100.0], [180.0, 100.0], [100.0, 180.0]])
    across = np.array([[5100.0, 100.0], [5180.0, 100.0], [5100.0, 180.0]])
    xy = np.vstack([clump, across])
    info = presence_spacing(xy, np.ones(len(xy)))
    assert info["share_nearest_within_purge"] == 1.0
    assert info["share_other_fold_within_purge"] == 0.0
    assert info["share_other_fold_between_purge_and_block"] == 1.0


def test_a_2025_plant_inside_the_window_of_an_older_one_is_not_a_new_site():
    xy = np.array([[0.0, 0.0], [200.0, 0.0], [800.0, 0.0], [900.0, 0.0], [820.0, 0.0]])
    y = np.array([1, 1, 1, 0, 0])
    year = np.array([2020, 2025, 2025, 2025, 2025])
    _train, new, background = temporal_sets(xy, y, year)
    assert list(new) == [2]
    assert 3 in background
    assert 4 not in background


def test_a_presence_owns_its_pixel_and_a_neighbour_thirty_metres_away_is_kept_until_the_split():
    to_lonlat = Transformer.from_crs(32637, 4326, always_xy=True)

    def row(x, y, taxon):
        lon, lat = to_lonlat.transform(x, y)
        return {"latitude": lat, "longitude": lon, "taxon_id": taxon, "quality_grade": "research",
                "positional_accuracy": 10, "observed_on": "2024-06-01", "year": 2024, "month": 6,
                "observer_id": 1}

    box = (399000.0, 6170000.0, 401000.0, 6190000.0)
    plant = row(400000, 6180000, 499936)
    other = dict(plant)
    other["taxon_id"] = 47126
    kept = build(pd.DataFrame([plant, other]), {499936}, {47126}, box=box)
    assert list(kept.label) == [1]

    apart = pd.DataFrame([row(400000, 6180000, 499936), row(400040, 6180000, 47126)])
    both = build(apart, {499936}, {47126}, box=box)
    assert sorted(both.label) == [0, 1]


def test_an_earlier_embedding_year_is_a_retro_forecast_and_the_default_is_the_map_year():
    assert feature_year(2025, None) == (2025, "same_image")
    assert feature_year(2025, 2024) == (2024, "retro_forecast")
    assert feature_year(2024, 2024) == (2024, "same_image")
