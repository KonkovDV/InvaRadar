"""KOZ-3 protocols reimplemented for InvaRadar: local relief, within-scene rank, nested thresholds."""
import numpy as np
import pytest

from invaradar.survey_protocol import (
    best_fbeta_threshold,
    fbeta_at,
    kernel_cells,
    local_relief,
    nested_thresholds,
    scene_percentile,
)


def test_an_eighty_metre_window_on_a_ten_metre_grid_is_seventy_not_ninety():
    assert kernel_cells(10.0, 80.0) == 7
    assert kernel_cells(10.0, 30.0) == 3


def test_a_mound_on_a_slope_survives_in_the_local_relief():
    res = 10.0
    cols = np.arange(21)
    slope = np.broadcast_to(0.2 * cols, (21, 21)).copy()
    mound = np.zeros((21, 21))
    mound[10, 10] = 4.0
    residual = local_relief(slope + mound, res_m=res, window_m=30.0)
    assert np.unravel_index(int(np.argmax(residual)), residual.shape) == (10, 10)
    assert residual[10, 10] > 2.0
    assert abs(residual[10, 2]) < 0.05


def test_a_quarter_turn_does_not_change_the_relief_of_a_square_kernel():
    z = np.zeros((15, 15))
    z[7, 7] = 3.0
    z[6, 8] = 1.0
    direct = local_relief(z, res_m=1.0, window_m=5.0)
    turned = np.rot90(local_relief(np.rot90(z), res_m=1.0, window_m=5.0), -1)
    assert np.allclose(direct, turned)


def test_a_missing_height_does_not_pull_the_neighbour_mean_to_zero():
    z = np.full((7, 7), 20.0)
    z[3, 3] = np.nan
    residual = local_relief(z, res_m=10.0, window_m=30.0)
    assert np.isnan(residual[3, 3])
    assert abs(residual[3, 4]) < 1e-9


def test_a_dim_scene_keeps_its_own_ranking():
    bright = scene_percentile([10.0, 9.0, 1.0])
    dim = scene_percentile([0.4, 0.2, 0.1])
    assert bright[0] > bright[2]
    assert dim[0] == bright[0]
    assert dim[0] > 0.5


def test_a_threshold_fit_on_the_reported_group_looks_better_than_the_nested_one():
    report_y = np.array([1, 1, 0, 0])
    report_p = np.array([0.62, 0.60, 0.40, 0.20])
    other_y = np.array([1, 1, 0, 0])
    other_p = np.array([0.99, 0.97, 0.80, 0.70])
    own_t, _ = best_fbeta_threshold(report_y, report_p)
    nested_t = nested_thresholds({"report": (report_y, report_p), "other": (other_y, other_p)})["report"]
    optimistic = fbeta_at(report_y, report_p, own_t)
    honest = fbeta_at(report_y, report_p, nested_t)
    assert optimistic > honest
    assert nested_t > own_t


def test_three_groups_are_all_used_when_the_threshold_is_fit():
    held = (np.array([1, 0]), np.array([0.5, 0.4]))
    many = (np.array([1] * 10 + [0] * 10), np.array([0.9] * 10 + [0.4] * 10))
    small = (np.array([1, 0]), np.array([0.3, 0.1]))
    chosen = nested_thresholds({"held": held, "many": many, "small": small})
    # Fitting on `small` alone would pick 0.3. The ten clear points in `many` pull the joint threshold to 0.9.
    assert chosen["held"] == 0.9


def test_equal_f_keeps_the_higher_threshold_and_rejects_a_length_mismatch():
    threshold, score = best_fbeta_threshold([0, 0, 0], [0.2, 0.5, 0.9])
    assert threshold == 0.9 and score == 0.0
    with pytest.raises(ValueError):
        best_fbeta_threshold([1, 0], [0.2])
