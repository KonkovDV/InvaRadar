"""Download the deck photos (originals, CC BY / CC0) from the iNaturalist open-data bucket into assets/.

Photo ids, licences and authors are listed in assets/CREDITS.csv; every photo shown in the deck is credited on the
slide and on the credits slide. usage: python fetch_photos.py
"""
import csv
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

A = Path(__file__).resolve().parent / "assets"
for r in csv.DictReader(open(A / "CREDITS.csv")):
    assert r["license"] in {"CC0", "CC-BY"}, r
    out = A / r["file"]
    for size in ("original", "large"):
        for ext in ("jpg", "jpeg", "png"):
            try:
                urllib.request.urlretrieve(
                    f"https://inaturalist-open-data.s3.amazonaws.com/photos/{r['photo_id']}/{size}.{ext}", out)
                break
            except Exception:
                continue
        if out.exists():
            break
    im = ImageOps.exif_transpose(Image.open(out)).convert("RGB")
    im.thumbnail((2000, 2000), Image.LANCZOS)
    im.save(out, quality=84, optimize=True, progressive=True)
    print(r["file"], im.size, r["license"], r["observer_name"] or r["observer_login"])
