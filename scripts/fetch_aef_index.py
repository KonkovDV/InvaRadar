"""Download the AlphaEarth Foundations tile index (GeoParquet) into $INVARADAR_CACHE/aef/.

The public bucket gs://alphaearth_foundations holds annual 64-band COGs for 2017–2025 (CC BY 4.0, "The AlphaEarth
Foundations Satellite Embedding dataset is produced by Google and Google DeepMind."). The index lists every tile
with its UTM bounds, so the pipeline fetches only the 1024 × 1024 blocks that cover the study area.
usage: fetch_aef_index.py
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from invaradar.config import AEF_INDEX

URL = "https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/aef_index.parquet"
AEF_INDEX.parent.mkdir(parents=True, exist_ok=True)
urllib.request.urlretrieve(URL, AEF_INDEX)
print("AEF index:", AEF_INDEX, AEF_INDEX.stat().st_size // 1024, "KB")
