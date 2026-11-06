"""Small fallback for maps: research-grade observations of a taxon in a window, from the public iNaturalist API.

The pipeline itself trains on the open-data export (scripts/fetch_inat.py, ~10 GB); figures that only need the
citizen reports inside a map window can use this instead when the export is not on disk.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import pandas as pd
from pyproj import Transformer

from .config import EPSG
from .samples import MAX_ACC, study_pixel

API = "https://api.inaturalist.org/v1/observations"


def reports_in_window(taxon_ids, ext_utm, d2: str | None = None) -> pd.DataFrame:
    """→ DataFrame [x, y, observed_on] in UTM, positional accuracy <= MAX_ACC, one record per 10 m pixel."""
    tr = Transformer.from_crs(EPSG, 4326, always_xy=True)
    w, s = tr.transform(ext_utm[0], ext_utm[1]); e, n = tr.transform(ext_utm[2], ext_utm[3])
    rows, id_above = [], 0
    while True:
        q = {"taxon_id": ",".join(map(str, taxon_ids)), "quality_grade": "research", "swlat": s, "swlng": w,
             "nelat": n, "nelng": e, "per_page": 200, "order_by": "id", "order": "asc", "id_above": id_above}
        if d2:
            q["d2"] = d2
        req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(q)}", headers={"User-Agent": "invaradar"})
        page = json.load(urllib.request.urlopen(req, timeout=60))["results"]
        if not page:
            break
        for o in page:
            acc = o.get("positional_accuracy")
            if o.get("geojson") and acc is not None and acc <= MAX_ACC:
                lon, lat = o["geojson"]["coordinates"]
                rows.append((lon, lat, o.get("observed_on")))
        id_above = page[-1]["id"]
        time.sleep(1.0)  # API etiquette: about one request per second
    d = pd.DataFrame(rows, columns=["lon", "lat", "observed_on"])
    x, y = Transformer.from_crs(4326, EPSG, always_xy=True).transform(d.lon.to_numpy(), d.lat.to_numpy())
    d = d.assign(x=x, y=y)
    px, py = study_pixel(d.x.to_numpy(), d.y.to_numpy())
    d = d.assign(px=px, py=py).drop_duplicates(["px", "py"])
    return d[["x", "y", "observed_on"]].reset_index(drop=True)
