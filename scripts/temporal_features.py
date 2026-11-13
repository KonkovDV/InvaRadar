"""Two feature constructions the year-mean did not test.

Both use the cached 2023 and 2024 tables and the same temporal split. The first
puts the two embedding blocks side by side and keeps one copy of the corridors
and the terrain. The second adds ln(1 + metres to the nearest other presence
from 2024 or earlier) as one more column. A presence is not given distance zero
to itself.

The published 6 November metrics are not written.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from sklearn.metrics import roc_auc_score

from invaradar.config import INAT_OBS, OUT, STUDY_BOX, TAXA
from invaradar.model import fit_map
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import block_groups, capture_rates, paired_area_difference, temporal_sets

_spec = importlib.util.spec_from_file_location("temporal_rest", Path(__file__).with_name("temporal_rest.py"))
rest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rest)

EMBEDDING_COLUMNS = 256
BINS = (0, 250, 500, 1000, 2000, 5000, 10**9)


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def stack_embedding_years(later: np.ndarray, earlier: np.ndarray, n_embed: int = EMBEDDING_COLUMNS) -> np.ndarray:
    """Earlier embedding, then the later one, then corridors and terrain from the later year."""
    later = np.asarray(later)
    earlier = np.asarray(earlier)
    if later.shape != earlier.shape or later.shape[-1] < n_embed:
        raise ValueError("the two years need the same columns")
    return np.concatenate([earlier[..., :n_embed], later[..., :n_embed], later[..., n_embed:]], axis=-1)


def distance_excluding_self(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Metres to the nearest reference point. A point that is itself a reference uses the next one."""
    query = np.asarray(query, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    if len(reference) == 0:
        raise ValueError("an older presence is required")
    k = 2 if len(reference) > 1 else 1
    dist, _ = cKDTree(reference).query(query, k=k)
    dist = np.asarray(dist, dtype=np.float64)
    if k == 1:
        # The only recorded presence is this point. There is no other plant to measure.
        return np.where(np.atleast_1d(dist) <= 1e-6, np.inf, np.atleast_1d(dist))
    return np.where(dist[:, 0] <= 1e-6, dist[:, 1], dist[:, 0])


def append_column(table: np.ndarray, column: np.ndarray) -> np.ndarray:
    values = np.asarray(column, dtype=np.float32).reshape(-1, 1)
    if len(values) != len(table):
        raise ValueError("the column must have one value per row")
    return np.concatenate([np.asarray(table, dtype=np.float32), values], axis=1)


def wilson(count: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = count / total
    den = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / den
    half = z * (p * (1.0 - p) / total + z * z / (4.0 * total * total)) ** 0.5 / den
    return [float(centre - half), float(centre + half)]


def distance_bins(target: np.ndarray, background: np.ndarray, edges=BINS) -> list[dict]:
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        xt = int(np.sum((target >= lo) & (target < hi)))
        xb = int(np.sum((background >= lo) & (background < hi)))
        st = xt / max(len(target), 1)
        sb = xb / max(len(background), 1)
        rows.append({
            "from_m": int(lo),
            "to_m": None if hi > 1e8 else int(hi),
            "target_count": xt,
            "background_count": xb,
            "target_share": st,
            "target_wilson95": wilson(xt, len(target)),
            "background_share": sb,
            "relative_risk": None if sb == 0 else st / sb,
        })
    return rows


def fit_one(table: np.ndarray, train, labels, new, background, land_rows):
    model = fit_map(table[train], labels[train])
    land_scores = model.predict(land_rows)
    new_scores = model.predict(table[new])
    background_scores = model.predict(table[background])
    ranks = rest.ranks_against(land_scores, new_scores)
    truth = np.r_[np.ones(len(new_scores)), np.zeros(len(background_scores))]
    gain = model.feature_importance(importance_type="gain")
    total = float(gain.sum())
    return {
        "ranks": ranks,
        "roc_auc_vs_background": float(roc_auc_score(truth, np.r_[new_scores, background_scores])),
        "capture": capture_rates(ranks),
        "distance_gain_share": None if total == 0 else float(gain[-1] / total),
        "n_features": int(table.shape[1]),
    }


def main() -> None:
    started = time.time()
    samples = load_obs()
    plants = plant_taxa()
    work = OUT / "variants" / "paired_years_work"
    obs = INAT_OBS.stat()
    out = {
        "protocol": {
            "stack": "2023 embedding, then 2024 embedding, then corridors and terrain copied from 2024",
            "distance_feature": "ln(1 + metres to the nearest other presence from 2024 or earlier); a presence is not distance zero to itself",
            "same_split_as": "scripts/temporal_rest.py",
            "published_6_nov_metrics": "not overwritten",
        },
        "observation_file": {
            "name": INAT_OBS.name, "bytes": obs.st_size,
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(obs.st_mtime)),
        },
        "taxa": {},
    }
    for taxon in ("heracleum", "solidago"):
        log(taxon)
        frame = build(samples, TAXA[taxon]["ids"], plants)
        terrain = rest.paired.TERRAIN[taxon]
        rng = np.random.default_rng(0)
        west, south, east, north = STUDY_BOX
        landscape_xy = np.column_stack([
            rng.uniform(west, east, 40000), rng.uniform(south, north, 40000),
        ])
        sample_xy = frame[["x", "y"]].to_numpy()
        xy = np.vstack([sample_xy, landscape_xy])
        tables = {
            year: rest.load_features(year, xy, None, None, terrain, work / taxon)
            for year in (2023, 2024)
        }
        sample_ok = rest.paired.finite_rows(tables[2023][:len(frame)]) & rest.paired.finite_rows(tables[2024][:len(frame)])
        kept = frame.loc[sample_ok].reset_index(drop=True)
        labels = kept.label.to_numpy()
        coordinates = kept[["x", "y"]].to_numpy()
        years_observed = kept.year.to_numpy()
        train, new, background = temporal_sets(coordinates, labels, years_observed)
        blocks = block_groups(coordinates[new])
        old_mask = (years_observed <= 2024) & (labels == 1)
        old = coordinates[old_mask]
        sample_distance = distance_excluding_self(coordinates, old)
        land_mask = rest.paired.finite_rows(tables[2024][len(sample_xy):]) & rest.paired.finite_rows(tables[2023][len(sample_xy):])
        land_distance = distance_excluding_self(landscape_xy[land_mask], old)
        base_2024 = tables[2024][:len(sample_xy)][sample_ok]
        base_2023 = tables[2023][:len(sample_xy)][sample_ok]
        land_2024 = tables[2024][len(sample_xy):][land_mask]
        land_2023 = tables[2023][len(sample_xy):][land_mask]
        built = {
            "image_2024": (base_2024, land_2024),
            "mean_2023_2024": (
                rest.mean_embedding_columns(base_2024, base_2023),
                rest.mean_embedding_columns(land_2024, land_2023),
            ),
            "stack_2023_2024": (
                stack_embedding_years(base_2024, base_2023),
                stack_embedding_years(land_2024, land_2023),
            ),
            "image_2024_plus_distance": (
                append_column(base_2024, np.log1p(sample_distance)),
                append_column(land_2024, np.log1p(land_distance)),
            ),
            "stack_plus_distance": (
                append_column(stack_embedding_years(base_2024, base_2023), np.log1p(sample_distance)),
                append_column(stack_embedding_years(land_2024, land_2023), np.log1p(land_distance)),
            ),
        }
        fitted = {}
        taxon_result = {
            "samples_dropped_as_nodata": int((~sample_ok).sum()),
            "n_new_presence": int(len(new)),
            "n_new_candidates": int(((years_observed >= 2025) & (labels == 1)).sum()),
            "models": {},
        }
        for name, (sample, land) in built.items():
            got = fit_one(sample, train, labels, new, background, land)
            got["block"] = {
                f"top{percent}%": rest.block_capture(got["ranks"], blocks, percent=percent, n_boot=2000, seed=0)
                for percent in (5, 10, 20)
            }
            if not name.endswith("distance"):
                got.pop("distance_gain_share")
            fitted[name] = got["ranks"]
            top = got["block"]["top20%"]
            log(f"  {name}: {top['n_captured']}/{top['n']}")
            taxon_result["models"][name] = {k: v for k, v in got.items() if k != "ranks"}
        pairs = {
            "stack_minus_2024": ("stack_2023_2024", "image_2024"),
            "stack_minus_mean": ("stack_2023_2024", "mean_2023_2024"),
            "distance_minus_2024": ("image_2024_plus_distance", "image_2024"),
            "stack_distance_minus_2024": ("stack_plus_distance", "image_2024"),
        }
        taxon_result["paired"] = {
            name: {
                f"top{percent}%": paired_area_difference(
                    fitted[left], fitted[right], blocks, percent=percent, n_boot=2000, seed=0)
                for percent in (5, 10, 20)
            }
            for name, (left, right) in pairs.items()
        }
        new_candidates = (years_observed >= 2025) & (labels == 1)
        new_background = (years_observed >= 2025) & (labels == 0)
        target = sample_distance[new_candidates]
        other = sample_distance[new_background]
        taxon_result["dispersal_all_new_reports"] = {
            "n_target": int(len(target)),
            "n_background": int(len(other)),
            "median_target_m": float(np.median(target)),
            "median_background_m": float(np.median(other)),
            "bins": distance_bins(target, other),
            "note": "all 2025-2026 reports in the map sample, including those inside 500 m of an older presence",
        }
        out["taxa"][taxon] = taxon_result
    destination = OUT / "variants" / "temporal_features.json"
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {destination} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
