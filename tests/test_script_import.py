"""Importing a map script must not parse arguments or write the published outputs."""
import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "scripts/pipeline.py",
    "scripts/uncertainty.py",
    "scripts/enrich.py",
    "scripts/exp_labels.py",
    "scripts/render_maps.py",
    "scripts/prefetch_aef.py",
    "scripts/fetch_overture.py",
    "scripts/train_photo_verifier.py",
    "scripts/prescribe.py",
)


def _load(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem + "_import_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_map_scripts_do_not_run_when_imported():
    for relative in SCRIPTS:
        module = _load(relative)
        assert callable(module.main)


def test_a_missing_embedding_is_left_out_of_both_ranks():
    from invaradar_pro.validation import combine_model_and_proximity, percentile_in
    model_land = np.array([0.0, 1.0])
    model_far = np.array([0.5, -np.inf])
    # The middle landscape point has no image. Its proximity must not set the rank.
    prox_land = np.array([0.0, 100.0, 1.0])
    prox_far = np.array([0.5, 50.0])
    land_valid = np.array([True, False, True])
    far_valid = np.array([True, False])
    comb_far, comb_land = combine_model_and_proximity(
        model_land, model_far, prox_land, prox_far, land_valid, far_valid)
    assert comb_land.shape == (2,)
    assert comb_far.shape == (1,)
    reference = prox_land[land_valid]
    expected = 0.5 * percentile_in(model_land, model_far[:1]) + 0.5 * percentile_in(reference, prox_far[:1])
    assert comb_far[0] == expected[0]
