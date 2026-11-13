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


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--year", type=int, default=2025)
    a = ap.parse_args()
    year = a.year
    dist = ROOT / "dist" / "release"; dist.mkdir(parents=True, exist_ok=True)

    assets = {}
    for taxon in ("heracleum", "solidago"):
        od = OUT / taxon
        assets[f"invaradar_{taxon}_likelihood_{year}_10m_cog.tif"] = od / f"likelihood_{year}.tif"
        assets[f"invaradar_{taxon}_hotspots_prescribed_{year}.parquet"] = od / f"hotspots_prescribed_{year}.parquet"
        assets[f"invaradar_{taxon}_hotspots_prescribed_{year}.geojson"] = od / f"hotspots_prescribed_{year}.geojson"
        assets[f"invaradar_{taxon}_dissimilarity_index_100m.tif"] = od / "dissimilarity_index_100m.tif"
    for variant in ("heracleum_no_terrain", "solidago_terrain"):
        od = OUT / "variants" / variant
        assets[f"invaradar_variant_{variant}_likelihood_{year}_10m_cog.tif"] = od / f"likelihood_{year}.tif"
        assets[f"invaradar_variant_{variant}_hotspots_{year}.parquet"] = od / f"hotspots_{year}.parquet"

    sums = {}
    for name, src in assets.items():
        if not src.exists():
            sys.exit(f"missing {src}: run the pipeline (make all) or requeue.py + prescribe.py first")
        shutil.copyfile(src, dist / name)
        sums[name] = sha256(dist / name)

    for item_path in (ROOT / "stac").glob("*.json"):
        item = json.load(open(item_path, encoding="utf-8"))
        for asset in item.get("assets", {}).values():
            name = asset["href"].removeprefix("./")
            if name in sums:
                asset["file:size"] = (dist / name).stat().st_size
                asset["file:checksum"] = "1220" + sums[name]
        taxon = item.get("properties", {}).get("invaradar:taxon")
        if taxon:
            key = "heracleum" if taxon.startswith("Heracleum") else "solidago"
            pres = json.load(open(OUT / key / "enrich_summary.json", encoding="utf-8"))["prescriptions"]
            item["properties"]["invaradar:hotspots"] = pres["hotspots"]
            item["properties"]["invaradar:prescriptions"] = {k: pres[k] for k in (
                "drone_spraying_allowed", "ground_spot_treatment", "mechanical_only", "in_water_zone_no_pesticides")}
        json.dump(item, open(item_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        shutil.copyfile(item_path, dist / item_path.name)

    with open(dist / "SHA256SUMS", "w") as fo:
        for name in sorted(sums):
            fo.write(f"{sums[name]}  {name}\n")
    print(f"{len(sums)} assets + STAC in {dist}")


if __name__ == "__main__":
    main()
