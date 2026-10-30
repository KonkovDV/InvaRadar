"""Copy the scientific figures from outputs/figures into assets/ in deck-friendly sizes and formats.
usage: python prepare_assets.py   (after scripts/render_maps.py and scripts/render_figures.py)"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
F, A = ROOT / "outputs" / "figures", Path(__file__).resolve().parent / "assets"
for name, fmt in [("terrain_hand_twi", "JPEG"), ("aoa_heracleum", "JPEG"),
                  ("heracleum_city", "PNG"), ("heracleum_district", "PNG"), ("validation_design", "PNG")]:
    im = Image.open(F / f"{name}.png").convert("RGB")
    im.thumbnail((2400, 2400), Image.LANCZOS)
    if fmt == "JPEG":
        im.save(A / f"{name}.jpg", quality=90, optimize=True)
    else:
        im.quantize(colors=200, method=Image.Quantize.MEDIANCUT).save(A / f"{name}.png", optimize=True)
    print(name, im.size)
