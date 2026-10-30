"""Download the Copernicus DEM GLO-30 tiles covering the study area (AWS Open Data) into $INVARADAR_CACHE/dem/.
Copernicus DEM © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the
European Union and ESA. usage: fetch_dem.py"""
import math
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyproj import Transformer

from invaradar.config import EPSG, SCRATCH, STUDY_BOX

w, s, e, n = STUDY_BOX
lon, lat = Transformer.from_crs(EPSG, 4326, always_xy=True).transform([w, e, e, w], [s, s, n, n])
out = SCRATCH / "dem"
out.mkdir(parents=True, exist_ok=True)
for la in range(math.floor(min(lat)), math.floor(max(lat)) + 1):
    for lo in range(math.floor(min(lon)), math.floor(max(lon)) + 1):
        name = f"N{la:02d}_00_E{lo:03d}_00"
        tile = f"Copernicus_DSM_COG_10_{name}_DEM"
        urllib.request.urlretrieve(f"https://copernicus-dem-30m.s3.amazonaws.com/{tile}/{tile}.tif", out / f"{name}.tif")
        print("DEM tile", name)
