import io
from datetime import datetime

import numpy as np
from invaradar_pro.evidence import (
    check_pair,
    check_photo,
    read_photo,
    satellite_did,
    strip_metadata,
    synth_photo,
    verdict,
)
from PIL import Image

LAT, LON = 55.576, 37.555
T = datetime(2027, 6, 1, 10, 0)


def test_exif_roundtrip():
    m = read_photo(synth_photo(LAT, LON, T, 1))
    assert abs(m.lat - LAT) < 1e-5 and abs(m.lon - LON) < 1e-5
    assert m.taken_at == "2027-06-01T10:00:00" and len(m.sha256) == 64


def test_place_time_and_duplicates():
    data = synth_photo(LAT, LON, T, 2)
    m = read_photo(data)
    ok = check_photo(m, focus_lat=LAT, focus_lon=LON, start="2027-05-20", end="2027-06-30")
    assert verdict(ok) == "pass"
    far = check_photo(m, focus_lat=LAT + 0.01, focus_lon=LON, start="2027-05-20", end="2027-06-30")
    assert verdict(far) == "fail" and far[0].name == "gps"
    late = check_photo(m, focus_lat=LAT, focus_lon=LON, start="2027-06-02", end="2027-06-30")
    assert [c.ok for c in late if c.name == "time"] == [False]
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    img.resize((int(img.width * 0.9), int(img.height * 0.9))).save(buf, "JPEG", quality=60)
    recompressed = read_photo(buf.getvalue())
    dup = check_photo(recompressed, focus_lat=LAT, focus_lon=LON, seen=[(m.dhash, m.sha256, "очаг-7/после")])
    assert [c.ok for c in dup if c.name == "unique"] == [False]


def test_missing_gps_needs_review_and_strip():
    m = read_photo(synth_photo(None, None, None, 3))
    assert verdict(check_photo(m, focus_lat=LAT, focus_lon=LON)) == "needs_review"
    stripped = read_photo(strip_metadata(synth_photo(LAT, LON, T, 4)))
    assert stripped.lat is None and stripped.taken_at is None


def test_pair_and_satellite():
    b = read_photo(synth_photo(LAT, LON, T, 5))
    a = read_photo(synth_photo(LAT + 0.0001, LON, datetime(2027, 6, 1, 17), 6))
    assert verdict(check_pair(b, a)) == "pass"
    assert verdict(check_pair(a, b)) == "fail"
    rng = np.random.default_rng(0)
    before = 0.6 + rng.normal(0, 0.01, (20, 20))
    inside = np.zeros((20, 20), bool)
    inside[5:10, 5:10] = True
    after = before + 0.05
    after[inside] -= 0.25
    assert satellite_did(before, after, inside).ok is True
    assert satellite_did(before, before + 0.05, inside).ok is None
