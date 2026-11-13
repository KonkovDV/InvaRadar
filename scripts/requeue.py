"""Rebuild the survey queue and the route from existing hotspot polygons, without retraining the model.

Use it after changing the context layers or the priority formula. Hotspots are read from the pipeline output
(hotspots_<year>.parquet) or from a release asset (--from invaradar_<taxon>_hotspots_prescribed_<year>.parquet);
only the geometry and the model columns are kept, everything else is recomputed. Updates the `hotspots` block of
metrics.json.
usage: requeue.py heracleum [--from FILE] [--variant NAME] [--year 2025] [--top 25]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd

from invaradar.config import EPSG, OUT
from invaradar.queue import build_queue, load_context

MODEL_COLS = ["hid", "n_px", "mean_rank", "max_rank", "cx", "cy", "area_m2", "geometry"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("taxon"); ap.add_argument("--from", dest="src")
    ap.add_argument("--year", type=int, default=2025); ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--variant", default="", help="outputs/variants/<taxon>_<variant> instead of outputs/<taxon>")
    a = ap.parse_args()
    od = OUT / a.taxon if not a.variant else OUT / "variants" / f"{a.taxon}_{a.variant}"
    src = Path(a.src) if a.src else od / f"hotspots_{a.year}.parquet"
    hs = gpd.read_parquet(src)[MODEL_COLS].to_crs(EPSG).sort_values("hid").reset_index(drop=True)
    block = build_queue(hs, od, a.year, a.top, load_context())
    mpath = od / "metrics.json"
    metrics = json.load(open(mpath, encoding="utf-8"))
    metrics["hotspots"] = block
    json.dump(metrics, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(block, ensure_ascii=False))


if __name__ == "__main__":
    main()
