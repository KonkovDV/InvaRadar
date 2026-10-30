"""AlphaEarth Foundations (Google DeepMind) annual satellite embeddings: block-wise access and caching.

The public COGs (gs://alphaearth_foundations, CC-BY 4.0) are 8192x8192x64 int8, band-interleaved, 1024x1024
blocks, stored south-up (positive y pixel size). We cache whole 1024x1024x64 blocks as int8 .npy, so a block is
fetched from the network once and reused for training-sample extraction and wall-to-wall prediction.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

GCS = "https://storage.googleapis.com/alphaearth_foundations/"
BLOCK = 1024
RES = 10.0
NODATA = -128

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tiff")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "8")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
# behind a TLS-inspecting proxy, point GDAL's curl at its CA bundle: INVARADAR_CA_BUNDLE=/path/to/ca.pem
if os.environ.get("INVARADAR_CA_BUNDLE"):
    os.environ.setdefault("CURL_CA_BUNDLE", os.environ["INVARADAR_CA_BUNDLE"])


_V = np.arange(-128, 128, dtype=np.float32)
_LUT = (np.sign(_V) * (_V / 127.5) ** 2).astype(np.float32)


def dequantize(raw: np.ndarray) -> np.ndarray:
    """int8 → float32 in [-1, 1] (official mapping: sign(v) * (v / 127.5)^2), via a 256-entry lookup table."""
    return _LUT[np.asarray(raw, dtype=np.int8).astype(np.int16) + 128]


class AEFIndex:
    def __init__(self, index_parquet: str | Path):
        self.df = pd.read_parquet(index_parquet, columns=[
            "path", "year", "utm_zone", "crs", "utm_west", "utm_south", "utm_east", "utm_north"])

    def tiles(self, year: int, epsg: int, west: float, south: float, east: float, north: float) -> pd.DataFrame:
        d = self.df
        m = (d.year == year) & (d.crs == f"EPSG:{epsg}") & (d.utm_west < east) & (d.utm_east > west) \
            & (d.utm_south < north) & (d.utm_north > south)
        return d[m]


class BlockCache:
    """Caches 1024x1024x64 int8 blocks; key = (year, tile basename, block row, block col)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _ds(self, url: str):
        import rasterio
        cache = getattr(self._local, "ds", None)
        if cache is None:
            cache = self._local.ds = {}
        if url not in cache:
            cache[url] = rasterio.open("/vsicurl/" + url)
        return cache[url]

    def path(self, year, tile, br, bc) -> Path:
        return self.root / str(year) / f"{tile}_{br:02d}_{bc:02d}.npy"

    def get(self, year: int, gs_path: str, br: int, bc: int) -> np.ndarray:
        tile = Path(gs_path).stem
        p = self.path(year, tile, br, bc)
        if p.exists():
            return np.load(p, mmap_mode="r")
        from rasterio.windows import Window
        url = GCS + gs_path.split("gs://alphaearth_foundations/")[1]
        ds = self._ds(url)
        arr = ds.read(window=Window(bc * BLOCK, br * BLOCK, BLOCK, BLOCK), boundless=True, fill_value=NODATA)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp.npy")
        np.save(tmp, arr.astype(np.int8))
        os.replace(tmp, p)
        return np.load(p, mmap_mode="r")


def block_jobs(index: AEFIndex, year: int, epsg: int, box):
    """All (gs_path, br, bc, x0, y0) blocks intersecting box = (west, south, east, north) in UTM metres.
    x0/y0 = coordinates of the block's first pixel corner (south-west corner, rows increase northwards)."""
    west, south, east, north = box
    jobs = []
    for _, t in index.tiles(year, epsg, *box).iterrows():
        span = BLOCK * RES
        c0 = int(max(0, (west - t.utm_west) // span)); c1 = int(min(7, (east - t.utm_west - 1e-6) // span))
        r0 = int(max(0, (south - t.utm_south) // span)); r1 = int(min(7, (north - t.utm_south - 1e-6) // span))
        for br in range(r0, r1 + 1):
            for bc in range(c0, c1 + 1):
                jobs.append((t.path, br, bc, t.utm_west + bc * span, t.utm_south + br * span))
    return jobs


def prefetch(cache: BlockCache, year: int, jobs, workers: int = 8, log=print):
    done = [0]

    def one(j):
        cache.get(year, j[0], j[1], j[2])
        done[0] += 1
        if done[0] % 5 == 0 or done[0] == len(jobs):
            log(f"  AEF {year}: {done[0]}/{len(jobs)} blocks")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, jobs))
