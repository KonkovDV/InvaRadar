"""Importing a script must not parse arguments or write the published outputs."""
import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem + "_import_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_map_scripts_do_not_run_when_imported():
    for path in sorted((ROOT / "scripts").glob("*.py")):
        module = _load(f"scripts/{path.name}")
        assert callable(module.main), path.name


def test_a_fresh_export_keeps_the_city_line():
    prescribe = _load("scripts/prescribe.py")
    export = _load("scripts/export_web.py")
    assert "jurisdiction_boundary_m" in prescribe.ORDER_COLUMNS
    assert "near_jurisdiction_boundary" in prescribe.ORDER_COLUMNS
    assert "jurisdiction_boundary_m" in export.WEB_FIELDS
    assert "near_jurisdiction_boundary" in export.WEB_FIELDS
    for taxon in ("heracleum", "solidago"):
        header = (ROOT / "outputs" / taxon / "work_orders_top200_2025.csv").read_text().splitlines()[0]
        assert header.split(",") == prescribe.ORDER_COLUMNS


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
