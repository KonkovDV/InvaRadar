"""Moscow city and Moscow oblast polygons for the work order.

``boundaries/jurisdictions.geojson`` is a simplified geoBoundaries ADM1 extract
(ODbL, OpenStreetMap). A point outside both polygons stays ``unknown``. The
oblast list is still unverified, so the polygon only names the jurisdiction.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from .config import ROOT

BOUNDARIES = ROOT / "boundaries" / "jurisdictions.geojson"


def load_regions(path: Path | None = None) -> gpd.GeoDataFrame | None:
    """Polygons with a ``jurisdiction`` column, or None when the file is absent."""
    path = Path(path) if path is not None else BOUNDARIES
    if not path.is_file():
        return None
    regions = gpd.read_file(path)
    if regions.crs is None:
        regions = regions.set_crs(4326)
    if "jurisdiction" not in regions.columns or len(regions) == 0:
        return None
    return regions[["jurisdiction", "geometry"]].copy()
