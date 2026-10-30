"""Presence / target-group-background samples from iNaturalist open data.

Presence: research-grade observations of a target taxon with positional accuracy <= MAX_ACC metres.
Background ("target-group"): research-grade observations of OTHER vascular plants made by the same kind of
observers in the same places, so they share the observation bias (roads, parks, dachas) of the presences
(Phillips et al. 2009). Background points within CLEAR_M of a presence are dropped (likely unlabelled presence).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

from .config import EPSG, INAT_OBS, INAT_TAXA, STUDY_BOX

MAX_ACC = 50.0
CLEAR_M = 30.0
PLANTAE = "47126"
TRACHEOPHYTA = "211194"


def load_obs(path=INAT_OBS) -> pd.DataFrame:
    d = pd.read_csv(path, sep="\t", dtype={"taxon_id": "Int64"}, on_bad_lines="skip")
    d = d.dropna(subset=["latitude", "longitude", "taxon_id"])
    d["observed_on"] = pd.to_datetime(d["observed_on"], errors="coerce")
    d["year"] = d["observed_on"].dt.year
    d["month"] = d["observed_on"].dt.month
    return d


def plant_taxa(path=INAT_TAXA) -> set[int]:
    t = pd.read_csv(path, sep="\t", usecols=["taxon_id", "ancestry"], dtype={"ancestry": str})
    a = t["ancestry"].fillna("")
    return set(t.loc[a.str.contains(f"/{TRACHEOPHYTA}/") | a.str.endswith(f"/{TRACHEOPHYTA}"), "taxon_id"])


def to_utm(d: pd.DataFrame) -> pd.DataFrame:
    tr = Transformer.from_crs(4326, EPSG, always_xy=True)
    x, y = tr.transform(d["longitude"].to_numpy(), d["latitude"].to_numpy())
    return d.assign(x=x, y=y)


def in_box(d: pd.DataFrame, box=STUDY_BOX, margin=0.0) -> pd.DataFrame:
    w, s, e, n = box
    return d[(d.x >= w + margin) & (d.x < e - margin) & (d.y >= s + margin) & (d.y < n - margin)]


def build(d: pd.DataFrame, target_ids, plants: set[int], box=STUDY_BOX, grades=("research",),
          max_bg: int = 60000, seed: int = 0) -> pd.DataFrame:
    """→ DataFrame [x, y, year, month, label, quality_grade] deduplicated to one record per 10 m pixel and label."""
    acc = pd.to_numeric(d["positional_accuracy"], errors="coerce")
    ok = acc.notna() & (acc <= MAX_ACC)
    d = to_utm(d[ok])
    d = in_box(d, box)
    tid = d["taxon_id"].astype(int)
    pos = d[tid.isin(target_ids) & d.quality_grade.isin(grades)].assign(label=1)
    bg = d[~tid.isin(target_ids) & tid.isin(plants) & (d.quality_grade == "research")].assign(label=0)
    if len(pos):
        dist, _ = cKDTree(pos[["x", "y"]].to_numpy()).query(bg[["x", "y"]].to_numpy())
        bg = bg[dist > CLEAR_M]
    s = pd.concat([pos, bg], ignore_index=True)
    s["px"] = (s.x // 10).astype(np.int64); s["py"] = (s.y // 10).astype(np.int64)
    s = s.sort_values("observed_on").drop_duplicates(["px", "py", "label"], keep="first")
    bgi = s.index[s.label == 0]
    if len(bgi) > max_bg:
        s = s.drop(np.random.default_rng(seed).choice(bgi, len(bgi) - max_bg, replace=False))
    return s[["x", "y", "year", "month", "label", "quality_grade", "observer_id", "observed_on"]].reset_index(drop=True)
