"""Overture Maps (open, S3 us-west-2) context layers for exposure and spread-corridor features.

Reads GeoParquet partitions with bbox-struct predicate pushdown, so only row groups intersecting the study
area are transferred.
"""
from __future__ import annotations

import os

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as pafs

RELEASE = "2026-10-21.0"
BUCKET = "overturemaps-us-west-2/release"


def _fs():
    # the AWS SDK inside pyarrow ignores HTTPS_PROXY, so pass it explicitly (corporate and cloud proxies)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = {"proxy_options": proxy} if proxy else {}
    return pafs.S3FileSystem(anonymous=True, region="us-west-2", **kw)


def read(theme: str, typ: str, bbox_wgs84, columns, extra_filter=None):
    w, s, e, n = bbox_wgs84
    d = ds.dataset(f"{BUCKET}/{RELEASE}/theme={theme}/type={typ}", filesystem=_fs(), format="parquet")
    f = (pc.field("bbox", "xmin") < e) & (pc.field("bbox", "xmax") > w) & \
        (pc.field("bbox", "ymin") < n) & (pc.field("bbox", "ymax") > s)
    if extra_filter is not None:
        f = f & extra_filter
    return d.to_table(columns=columns, filter=f)


def to_gdf(table):
    import geopandas as gpd
    from shapely import from_wkb
    df = table.to_pandas()
    df["geometry"] = from_wkb(df["geometry"])
    return gpd.GeoDataFrame(df, geometry="geometry", crs=4326)
