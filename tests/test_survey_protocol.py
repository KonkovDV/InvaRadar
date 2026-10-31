"""KOZ-3 protocols reimplemented for InvaRadar: local relief, within-scene rank, nested thresholds."""
import numpy as np

from invaradar.survey_protocol import (
    best_fbeta_threshold,
    fbeta_at,
    local_relief,
    nested_thresholds,
    scene_percentile,
)


def test_a_mound_on_a_slope_survives_in_the_local_relief():
    res = 10.0
    rows, cols = 21, 21
    yy, xx = np.mgrid[:rows, :cols]
    slope = 0.2 * xx
    mound = np.zeros((rows, cols))
    mound[10, 10] = 4.0
    residual = local_relief(slope + mound, res_m=res, window_m=30.0)
    assert np.unravel_index(int(np.argmax(residual)), residual.shape) == (10, 10)
    assert residual[10, 10] > 2.0
    assert abs(residual[0, 0]) < 0.5


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
