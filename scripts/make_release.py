"""Collect the release assets into dist/release, refresh the STAC items and write SHA256SUMS.

The STAC items keep the metrics written by the pipeline; this script only updates file sizes, multihash checksums
(sha2-256, `1220` prefix) and the hotspot counts, so the catalogue always matches the files next to it.
usage: make_release.py [--year 2025]
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from invaradar.config import OUT, ROOT

ap = argparse.ArgumentParser(); ap.add_argument("--year", type=int, default=2025)
a = ap.parse_args()
Y = a.year
dist = ROOT / "dist" / "release"; dist.mkdir(parents=True, exist_ok=True)

assets = {}
for t in ("heracleum", "solidago"):
    od = OUT / t
    assets[f"invaradar_{t}_likelihood_{Y}_10m_cog.tif"] = od / f"likelihood_{Y}.tif"
    assets[f"invaradar_{t}_hotspots_prescribed_{Y}.parquet"] = od / f"hotspots_prescribed_{Y}.parquet"
    assets[f"invaradar_{t}_hotspots_prescribed_{Y}.geojson"] = od / f"hotspots_prescribed_{Y}.geojson"
    assets[f"invaradar_{t}_dissimilarity_index_100m.tif"] = od / "dissimilarity_index_100m.tif"
for v in ("heracleum_no_terrain", "solidago_terrain"):
    od = OUT / "variants" / v
    assets[f"invaradar_variant_{v}_likelihood_{Y}_10m_cog.tif"] = od / f"likelihood_{Y}.tif"
    assets[f"invaradar_variant_{v}_hotspots_{Y}.parquet"] = od / f"hotspots_{Y}.parquet"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


sums = {}
for name, src in assets.items():
    if not src.exists():
        sys.exit(f"missing {src}: run the pipeline (make all) or requeue.py + prescribe.py first")
    shutil.copyfile(src, dist / name)
    sums[name] = sha256(dist / name)

for f in (ROOT / "stac").glob("*.json"):
    item = json.load(open(f, encoding="utf-8"))
    for asset in item.get("assets", {}).values():
        name = asset["href"].removeprefix("./")
        if name in sums:
            asset["file:size"] = (dist / name).stat().st_size
            asset["file:checksum"] = "1220" + sums[name]
    taxon = item.get("properties", {}).get("invaradar:taxon")
    if taxon:
        t = "heracleum" if taxon.startswith("Heracleum") else "solidago"
        pres = json.load(open(OUT / t / "enrich_summary.json", encoding="utf-8"))["prescriptions"]
        item["properties"]["invaradar:hotspots"] = pres["hotspots"]
        item["properties"]["invaradar:prescriptions"] = {k: pres[k] for k in (
            "drone_spraying_allowed", "ground_spot_treatment", "mechanical_only", "in_water_zone_no_pesticides")}
    json.dump(item, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.copyfile(f, dist / f.name)

with open(dist / "SHA256SUMS", "w") as fo:
    for name in sorted(sums):
        fo.write(f"{sums[name]}  {name}\n")
print(f"{len(sums)} assets + STAC in {dist}")
