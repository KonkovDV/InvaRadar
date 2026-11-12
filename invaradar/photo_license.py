"""Which iNaturalist photo licences may train a model that a city can ship.

Audit I-03: the open-data bucket also contains CC BY-NC, ND and SA photos.
A commercial municipal model keeps CC0 and CC BY only. Share-alike and
non-commercial terms stay out.
"""
from __future__ import annotations

_CC0 = {"CC0", "CC-0", "CC0-1.0", "CC-ZERO", "PUBLIC-DOMAIN"}
_CC_BY = {"CC-BY", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0"}


def commercial_photo_license(value: object) -> bool:
    """True for CC0 and CC BY, including the versioned codes iNaturalist writes."""
    text = str(value or "").strip().upper().replace("_", "-").replace(" ", "-")
    while "--" in text:
        text = text.replace("--", "-")
    if text.startswith("CCBY"):
        text = "CC-BY" + text[4:]
    return text in _CC0 or text in _CC_BY
