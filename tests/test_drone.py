"""Pipeline check of the UAV module on a synthetic 3 cm orthomosaic: meadow + two flowering stands."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from rasterio.transform import from_origin

from invaradar.drone import BloomIndexSegmenter, apply_height_gate, polygonize, segment_orthomosaic, spray_mission


def make_ortho(path, n=1500, gsd=0.03, seed=0):
    rng = np.random.default_rng(seed)
    img = np.empty((3, n, n), np.uint8)
    img[0] = rng.integers(60, 90, (n, n)); img[1] = rng.integers(110, 150, (n, n)); img[2] = rng.integers(50, 80, (n, n))
    yy, xx = np.mgrid[:n, :n]
    stands = [(400, 400, 150), (1100, 900, 220)]  # centre row, col, radius (px)
    for cr, cc, rad in stands:
        for _ in range(int(rad * rad / 300)):
            a, r = rng.uniform(0, 2 * np.pi), rad * np.sqrt(rng.uniform())
            ur, uc = int(cr + r * np.sin(a)), int(cc + r * np.cos(a))
            m = (yy - ur) ** 2 + (xx - uc) ** 2 <= (0.2 / gsd) ** 2      # umbel, 0.4 m across
            img[:, m] = rng.integers(225, 250)
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=3, dtype="uint8", crs="EPSG:32637",
                       transform=from_origin(410000, 6180000, gsd, gsd)) as ds:
        ds.write(img)
    return stands, gsd


def test_a_tied_f_keeps_the_higher_threshold():
    from invaradar.survey_protocol import best_fbeta_threshold
    from scripts.drone_benchmark import fbeta_threshold

    y = np.array([0, 0, 0])
    scores = np.array([0.2, 0.5, 0.9])
    assert fbeta_threshold(y, scores, 1.0) == best_fbeta_threshold(y, scores, 1.0)[0] == 0.9


def test_pipeline(tmp_path):
    tmp = str(Path(tmp_path) / "test_ortho.tif")
    stands, gsd = make_ortho(tmp)
    prob, tr, crs = segment_orthomosaic(tmp, BloomIndexSegmenter("heracleum", gsd), tile=512, overlap=64)
    polys = polygonize(prob, tr, crs, thr=0.5, min_area_m2=2.0)
    true_area = sum(np.pi * (r * gsd) ** 2 for _, _, r in stands)
    plan, stats = spray_mission(polys)
    print(f"stands found {len(polys)} (true 2); area {polys.area_m2.sum():.1f} m2 (true {true_area:.1f}); plan {stats}")
    assert len(polys) == 2
    assert 0.5 < polys.area_m2.sum() / true_area < 1.5
    assert stats["tank_mix_l"] > 0


def test_rosette_keeps_pixels_shorter_than_a_flowering_stem():
    prob = np.ones(4, np.float32)
    height = np.array([0.5, 1.0, 2.0, 6.0], np.float32)
    rosette = apply_height_gate(prob, height, phenophase="rosette")
    flowering = apply_height_gate(prob, height, phenophase="flowering")
    assert np.allclose(rosette, 1.0)
    assert flowering[0] == 0.0 and flowering[2] == 1.0 and flowering[3] == 0.0


if __name__ == "__main__":
    test_pipeline(Path("outputs"))
