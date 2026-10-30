"""AlphaEarth Foundations int8 → float dequantisation."""
import numpy as np

from invaradar.aef import dequantize


def test_dequantize_matches_official_formula():
    v = np.arange(-127, 128, dtype=np.int8)
    expect = np.sign(v.astype(np.float32)) * (v.astype(np.float32) / 127.5) ** 2
    assert np.allclose(dequantize(v), expect, atol=1e-7)
    assert dequantize(np.array([0], np.int8))[0] == 0.0
    assert np.all(np.diff(dequantize(v)) >= 0)
