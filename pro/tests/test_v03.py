import io
import shutil

import yaml
from invaradar_pro.evidence import check_photo, dhash, hamming, phash, read_photo, synth_photo
from invaradar_pro.law import RULES_DIR, LawEngine
from invaradar_pro.law_check import run
from invaradar_pro.power import n_two_proportions, power_two_proportions, simulate_did_power
from PIL import Image, ImageEnhance

# --- формальная проверка права ---------------------------------------------------------------

def test_law_model_check_all_properties_hold():
    r = run()
    assert r["contexts"] == 3 ** 6 * 3 * 3 * 3 * 3 * 3
    assert all(v == "ok" for v in r["properties"].values()) and r["obligations"] == "ok"


def test_law_model_check_catches_removed_fail_safe(tmp_path):
    d = tmp_path / "rules"
    shutil.copytree(RULES_DIR, d)
    fed = yaml.safe_load((d / "federal.yaml").read_text(encoding="utf-8"))
    fed["rules"] = [r for r in fed["rules"] if r["id"] != "heritage-unknown"]
    (d / "federal.yaml").write_text(yaml.safe_dump(fed, allow_unicode=True), encoding="utf-8")
    r = run(LawEngine(d))
    assert r["properties"]["P4"] == "FAIL"
    ex = r["counterexamples"]["P4"][0]
    assert ex["field"] == "near_heritage" and set(ex["extra"]) <= {"root_cut", "digging"}


# --- pHash ----------------------------------------------------------------------------------

def _variants(data: bytes):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    out = []
    for f in (lambda x: x.resize((x.width // 2, x.height // 2)), lambda x: ImageEnhance.Brightness(x).enhance(1.2)):
        b = io.BytesIO()
        f(im).save(b, "JPEG", quality=50)
        out.append(Image.open(io.BytesIO(b.getvalue())))
    return im, out


def test_phash_robust_and_discriminative():
    a, va = _variants(synth_photo(55.6, 37.6, None, 11, size=(320, 240)))
    b, _ = _variants(synth_photo(55.6, 37.6, None, 12, size=(320, 240)))
    for v in va:
        assert hamming(phash(a), phash(v)) <= 10
    assert hamming(phash(a), phash(b)) > 10 and hamming(dhash(a), dhash(b)) > 6


def test_duplicate_caught_by_phash_seen_entry():
    m1 = read_photo(synth_photo(55.6, 37.6, None, 21, size=(320, 240)))
    im = Image.open(io.BytesIO(synth_photo(55.6, 37.6, None, 21, size=(320, 240))))
    buf = io.BytesIO()
    ImageEnhance.Brightness(im.convert("RGB")).enhance(1.25).save(buf, "JPEG", quality=40)
    m2 = read_photo(buf.getvalue())
    chk = check_photo(m2, focus_lat=55.6, focus_lon=37.6, seen=[(m1.dhash, m1.sha256, "очаг-1/после", m1.phash)])
    assert [c.ok for c in chk if c.name == "unique"] == [False]


# --- мощность -----------------------------------------------------------------------------------

def test_power_formulas():
    assert n_two_proportions(0.5, 0.4) == 388
    assert abs(power_two_proportions(0.5, 0.4, 388) - 0.80) < 0.01
    p = simulate_did_power(0.3, 0.2, n_pilot=1000, n_control=1000, n_sims=1500)
    assert 0.5 < p < 1.0
    assert simulate_did_power(0.3, 0.0, 300, 300, n_sims=1500) < 0.08
