"""Copernicus DEM GLO-30 (ESA, open) → the 10 m study grid (bilinear), as raw f32 for the Rust core + GeoTIFF."""
import glob
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from invaradar.config import DATA, EPSG, SCRATCH, STUDY_BOX


def main():
    w, s, e, n = STUDY_BOX; RES = 10.0
    width, height = int((e - w) / RES), int((n - s) / RES)
    srcs = [rasterio.open(f) for f in sorted(glob.glob(str(SCRATCH / "dem" / "*.tif")))]
    mosaic, tr = merge(srcs)
    dst = np.zeros((height, width), np.float32)
    reproject(mosaic[0].astype(np.float32), dst, src_transform=tr, src_crs=srcs[0].crs,
              dst_transform=from_origin(w, n, RES, RES), dst_crs=f"EPSG:{EPSG}", resampling=Resampling.bilinear)
    dst.astype("<f4").tofile(DATA / "dem_10m.f32")
    with rasterio.open(DATA / "dem_10m.tif", "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="float32", crs=f"EPSG:{EPSG}", transform=from_origin(w, n, RES, RES),
                       compress="deflate") as ds:
        ds.write(dst, 1)
    print("DEM 10 m:", dst.shape, "elev min/median/max", float(dst.min()), float(np.median(dst)), float(dst.max()))


if __name__ == "__main__":
    main()
