"""Commercial photo training keeps CC0 and CC BY and drops NC, ND and SA."""
from invaradar.photo_license import commercial_photo_license


def test_only_cc0_and_cc_by_may_train_a_municipal_model():
    assert commercial_photo_license("CC0")
    assert commercial_photo_license("cc-by")
    assert commercial_photo_license("CC BY 4.0")
    assert commercial_photo_license("CC-BY-NC") is False
    assert commercial_photo_license("CC-BY-SA") is False
    assert commercial_photo_license("CC-BY-ND") is False
    assert commercial_photo_license("CC-BY-NC-SA") is False
    assert commercial_photo_license("") is False
    assert commercial_photo_license(None) is False
