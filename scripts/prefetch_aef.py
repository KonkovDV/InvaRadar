"""Prefetch AlphaEarth embedding blocks for the study area into data/aef_cache."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from invaradar.aef import AEFIndex, BlockCache, block_jobs, prefetch
from invaradar.config import AEF_INDEX, AEF_CACHE, EPSG, STUDY_BOX

years = [int(y) for y in sys.argv[1:]] or [2025]
idx = AEFIndex(AEF_INDEX)
cache = BlockCache(AEF_CACHE)
for y in years:
    jobs = block_jobs(idx, y, EPSG, STUDY_BOX)
    print(f"year {y}: {len(jobs)} blocks", flush=True)
    prefetch(cache, y, jobs, workers=8, log=lambda s: print(s, flush=True))
