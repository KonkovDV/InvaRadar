"""Geometry of the TESSERA and OlmoEarth window, and the recorded comparison. The stores are not contacted."""
import importlib.util
import json
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "other_embeddings.py"
_SPEC = importlib.util.spec_from_file_location("other_embeddings_under_test", _PATH)
other = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(other)


def test_the_known_moscow_pixel_lands_on_the_store_index():
    # A point checked against both stores: UTM 37N, OlmoEarth row 332360 col 41338,
    # TESSERA v1.1 row 315976 col 24954.
    xy = np.array([[413380.72, 6179118.15]])
    row, col = other.study_rc(xy)
    assert (int(row[0]), int(col[0])) == (3288, 3238)
    olmo_row, olmo_col = other.grid_origin([10, 0.0, 0, 0.0, -10, 9502720])
    tessera_row, tessera_col = other.grid_origin([10, 0, 163840.0, 0, -10, 9338880.0])
    assert (olmo_row + 3288, olmo_col + 3238) == (332360, 41338)
    assert (tessera_row + 3288, tessera_col + 3238) == (315976, 24954)


def test_olmo_nodata_does_not_enter_the_square():
    values = other.dequant_olmo(np.array([-128, 0, 127], np.int8))
    assert np.isnan(values[0]) and values[1] == 0
    assert values[2] == np.float32((127 / 127.5) ** 2)


def test_tessera_scale_marks_a_missing_pixel():
    raw = np.array([[2, -4], [-4, 8]], np.int8)
    scale = np.array([0.5, np.inf], np.float32)
    values = other.dequant_tessera(raw, scale)
    assert values[0, 0] == 1 and values[1, 0] == -2
    assert np.isnan(values[:, 1]).all()


def test_the_recorded_2024_comparison_matches_the_alphaearth_refit():
    path = Path(__file__).resolve().parents[1] / "outputs" / "variants" / "other_embeddings_2024.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    expect = {
        "heracleum": {"n": 216, "alpha": 73, "olmo": 91, "tessera": 87},
        "solidago": {"n": 188, "alpha": 65, "olmo": 85, "tessera": 66},
    }
    for taxon, counts in expect.items():
        block = data["taxa"][taxon]
        alone = block["alone"]
        assert alone["alphaearth"]["samples_dropped"] == 0
        assert alone["olmoearth"]["n_features"] == 265
        assert alone["tessera"]["n_features"] == 521
        for name, count in (("alphaearth", counts["alpha"]), ("olmoearth", counts["olmo"]), ("tessera", counts["tessera"])):
            share = alone[name]["capture"]["capture@20%area"]
            assert round(share * counts["n"]) == count
        olmo = block["olmoearth_minus_alphaearth"]["minus_alphaearth"]["top20%"]["boot95"]
        tessera = block["tessera_minus_alphaearth"]["minus_alphaearth"]["top20%"]["boot95"]
        assert olmo[0] > 0
        assert tessera[0] <= 0 <= tessera[1]


def test_a_coarse_window_weights_pixels_not_empty_cells():
    # Two cells. The first has one pixel of value 4 and one empty. The second is empty.
    # A 1-wide window is just the cell mean: 4.
    cell_sum = np.array([[[4.0]], [[0.0]]], np.float32)
    count = np.array([[1.0], [0.0]], np.float32)
    got = other.window_mean(cell_sum, count, 1)
    assert got[0, 0, 0] == 4
    assert got[1, 0, 0] == 0
