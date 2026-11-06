"""The one forest used for the published map and for its confidence intervals.

`scripts/pipeline.py` writes the point estimates. `scripts/uncertainty.py` refits the same
forest for the intervals. Both call `fit_map`, so a change of depth or learning rate cannot
land in only one of them. The label experiment in `scripts/exp_labels.py` is a different
forest on purpose: fewer trees and a higher learning rate, and it says so at the call.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np

MAP_TREES = 300
MAP_PARAMS = dict(
    objective="binary",
    learning_rate=0.05,
    num_leaves=15,
    min_child_samples=20,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.5,
    reg_lambda=1.0,
    verbose=-1,
    n_jobs=4,
)


def fit_map(X, y, trees: int = MAP_TREES, **override):
    """Binary forest. The positive class is weighted by the background-to-presence ratio."""
    y = np.asarray(y)
    weight = float((y == 0).sum()) / max(float(np.sum(y)), 1.0)
    params = {**MAP_PARAMS, **override, "scale_pos_weight": weight}
    return lgb.train(params, lgb.Dataset(X, y), trees)
