"""The 265-feature comparisons that the 2024-versus-2025 file does not contain.

Same samples, same 40,000 landscape points, and the same temporal split as
``scripts/paired_years.py``. This adds the 2023 image, the mean of the 2023 and
2024 embedding columns, distance to an older presence, and that distance averaged
with the 2024 image's rank. Hogweed keeps terrain. Goldenrod does not.

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

from invaradar.aef import AEFIndex, BlockCache, block_jobs, prefetch
from invaradar.config import AEF_CACHE, AEF_INDEX, EPSG, INAT_OBS, OUT, STUDY_BOX, TAXA
from invaradar.model import fit_map
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import (
    block_capture,
    block_groups,
    capture_rates,
    landscape_percentile,
    paired_area_difference,
    temporal_sets,
)

_spec = importlib.util.spec_from_file_location("paired_years", Path(__file__).with_name("paired_years.py"))
paired = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paired)

YEARS = (2023, 2024, 2025)
EMBEDDING_COLUMNS = 256


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def mean_embedding_columns(left: np.ndarray, right: np.ndarray, n_embed: int = EMBEDDING_COLUMNS) -> np.ndarray:
    """Mean of the embedding columns. Corridors and terrain are copied from the left year."""
    left = np.asarray(left)
    right = np.asarray(right)
    if left.shape != right.shape or left.shape[-1] < n_embed:
        raise ValueError("the two years need the same columns")
    out = np.array(left, dtype=np.float32, copy=True)
    out[..., :n_embed] = (left[..., :n_embed] + right[..., :n_embed]) * np.float32(0.5)
    return out


def nearest_distance(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Metres from each query point to the nearest reference point."""
    if len(reference) == 0:
        raise ValueError("an older presence is required")
    dist, _ = cKDTree(np.asarray(reference, dtype=np.float64)).query(np.asarray(query, dtype=np.float64), k=1)
    return np.asarray(dist, dtype=np.float64)


def load_features(year: int, xy: np.ndarray, jobs, cache: BlockCache, terrain: bool, work: Path) -> np.ndarray:
    kind = "terrain" if terrain else "noterrain"
    path = work / f"feat_{year}_{kind}.f32"
    width = 265
    if path.is_file() and path.stat().st_size == len(xy) * width * 4:
        log(f"features {year} from {path.name}")
        return np.fromfile(path, dtype="<f4").reshape(len(xy), width)
    log(f"features {year} from the core")
    return paired.features(year, xy, jobs, cache, terrain, work)


def ranks_against(land_scores: np.ndarray, new_scores: np.ndarray) -> np.ndarray:
    return landscape_percentile(np.sort(np.asarray(land_scores, dtype=float)), new_scores)


def level_block(ranks: np.ndarray, blocks: np.ndarray) -> dict:
    out = {}
    for percent in (1, 5, 10, 20):
        out[f"top{percent}%"] = block_capture(ranks, blocks, percent=percent, n_boot=2000, seed=0)
    return out


def main() -> None:
    if not paired.CORE.is_file():
        raise SystemExit(f"build the core first: {paired.CORE}")
    started = time.time()
    index = AEFIndex(AEF_INDEX)
    jobs = {year: block_jobs(index, year, EPSG, STUDY_BOX) for year in YEARS}
    cache = BlockCache(AEF_CACHE)
    for year in YEARS:
        log(f"cache {year}: {len(jobs[year])} blocks")
        prefetch(cache, year, jobs[year], workers=4, log=log)
    samples = load_obs()
    plants = plant_taxa()
    work = OUT / "variants" / "paired_years_work"
    obs = INAT_OBS.stat()
    out = {
        "protocol": {
            "map_year": 2025,
            "embedding_years": list(YEARS),
            "mean_2023_2024": "mean of the first 256 columns; corridors and terrain copied from 2024",
            "proximity": "negative distance to a presence from 2024 or earlier; the landscape is the same 40000 points",
            "combined": "mean of the 2024 image rank and the proximity rank, then ranked again on that mean",
            "split": "train on years through 2024; a 2025-2026 presence is new only outside 500 m of an older presence",
            "points_kept": "a sample row is kept only when 2023, 2024 and 2025 are all finite",
            "n_boot": 2000,
            "seed": 0,
            "published_6_nov_metrics": "not overwritten",
        },
        "observation_file": {
            "name": INAT_OBS.name, "bytes": obs.st_size,
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(obs.st_mtime)),
        },
        "taxa": {},
    }
    for taxon in ("heracleum", "solidago"):
        log(f"{taxon}: samples")
        frame = build(samples, TAXA[taxon]["ids"], plants)
        terrain = paired.TERRAIN[taxon]
        rng = np.random.default_rng(0)
        west, south, east, north = STUDY_BOX
        landscape_xy = np.column_stack([
            rng.uniform(west, east, 40000), rng.uniform(south, north, 40000),
        ])
        sample_xy = frame[["x", "y"]].to_numpy()
        xy = np.vstack([sample_xy, landscape_xy])
        tables = {
            year: load_features(year, xy, jobs[year], cache, terrain, work / taxon)
            for year in YEARS
        }
        sample_ok = np.logical_and.reduce([
            paired.finite_rows(tables[year][:len(frame)]) for year in YEARS
        ])
        kept = frame.loc[sample_ok].reset_index(drop=True)
        labels = kept.label.to_numpy()
        coordinates = kept[["x", "y"]].to_numpy()
        years_observed = kept.year.to_numpy()
        train, new, background = temporal_sets(coordinates, labels, years_observed)
        blocks = block_groups(coordinates[new])
        old = coordinates[(years_observed <= 2024) & (labels == 1)]
        taxon_result = {
            "terrain": terrain,
            "samples_dropped_as_nodata_on_any_image": int((~sample_ok).sum()),
            "presence": int(labels.sum()),
            "n_new_candidates": int(((years_observed >= 2025) & (labels == 1)).sum()),
            "n_new_presence": int(len(new)),
            "n_older_presence": int(len(old)),
            "n_blocks": int(len(np.unique(blocks))),
            "by_year": {},
        }
        fitted = {}
        for year in YEARS:
            table = tables[year][:len(sample_xy)][sample_ok]
            land = tables[year][len(sample_xy):]
            land = land[paired.finite_rows(land)]
            model = fit_map(table[train], labels[train])
            land_scores = model.predict(land)
            new_scores = model.predict(table[new])
            background_scores = model.predict(table[background])
            ranks = ranks_against(land_scores, new_scores)
            both = np.r_[new_scores, background_scores]
            truth = np.r_[np.ones(len(new_scores)), np.zeros(len(background_scores))]
            fitted[year] = {"model": model, "ranks": ranks, "land_rows": land, "land_scores": land_scores}
            taxon_result["by_year"][str(year)] = {
                "n_landscape": int(len(land)),
                "roc_auc_vs_background": float(roc_auc_score(truth, both)),
                "capture": capture_rates(ranks),
                "block": level_block(ranks, blocks),
            }
            top = taxon_result["by_year"][str(year)]["block"]["top20%"]
            log(f"{taxon} {year}: {top['n_captured']}/{top['n']} at 20%")
        averaged = mean_embedding_columns(tables[2023], tables[2024])
        avg_sample = averaged[:len(sample_xy)][sample_ok]
        avg_land = averaged[len(sample_xy):]
        avg_land = avg_land[paired.finite_rows(avg_land)]
        model = fit_map(avg_sample[train], labels[train])
        avg_ranks = ranks_against(model.predict(avg_land), model.predict(avg_sample[new]))
        taxon_result["mean_2023_2024"] = {
            "corridors_copied_from_2024": bool(np.array_equal(averaged[:, 256:261], tables[2024][:, 256:261])),
            "terrain_copied_from_2024": bool(np.array_equal(averaged[:, 261:265], tables[2024][:, 261:265])),
            "capture": capture_rates(avg_ranks),
            "block": level_block(avg_ranks, blocks),
        }
        prox_sample = nearest_distance(coordinates, old)
        prox_land = nearest_distance(landscape_xy, old)
        prox_new = -prox_sample[new]
        prox_ranks = ranks_against(-prox_land, prox_new)
        taxon_result["proximity_to_older_presence"] = {
            "median_new_m": float(np.median(prox_sample[new])),
            "median_temporal_background_m": float(np.median(prox_sample[background])),
            "capture": capture_rates(prox_ranks),
            "block": level_block(prox_ranks, blocks),
            "note": "new places are already farther than 500 m from an older presence, so the top of a proximity map can lie inside that ring",
        }
        # One forest for 2024. Both ranks use the landscape points that image can score.
        land_model = fitted[2024]["land_scores"]
        land_mask = paired.finite_rows(tables[2024][len(sample_xy):])
        prox_reference = -prox_land[land_mask]
        if len(land_model) != len(prox_reference):
            raise RuntimeError(f"{taxon}: the 2024 landscape and the proximity landscape differ")
        prox_for_pair = ranks_against(prox_reference, prox_new)
        land_model_pct = landscape_percentile(np.sort(land_model), land_model)
        land_prox_pct = landscape_percentile(np.sort(prox_reference), prox_reference)
        comb_land = 0.5 * land_model_pct + 0.5 * land_prox_pct
        comb_new = 0.5 * fitted[2024]["ranks"] + 0.5 * prox_for_pair
        comb_ranks = ranks_against(comb_land, comb_new)
        taxon_result["combined_2024_plus_proximity"] = {
            "capture": capture_rates(comb_ranks),
            "block": level_block(comb_ranks, blocks),
        }
        pairs = {
            "2025_minus_2024": (fitted[2025]["ranks"], fitted[2024]["ranks"]),
            "2025_minus_2023": (fitted[2025]["ranks"], fitted[2023]["ranks"]),
            "2024_minus_2023": (fitted[2024]["ranks"], fitted[2023]["ranks"]),
            "mean_minus_2024": (avg_ranks, fitted[2024]["ranks"]),
            "2024_minus_proximity": (fitted[2024]["ranks"], prox_ranks),
            "combined_minus_2024": (comb_ranks, fitted[2024]["ranks"]),
        }
        taxon_result["paired"] = {
            name: {
                f"top{percent}%": paired_area_difference(left, right, blocks, percent=percent, n_boot=2000, seed=0)
                for percent in (1, 5, 10, 20)
            }
            for name, (left, right) in pairs.items()
        }
        top = taxon_result["by_year"]["2023"]["block"]["top20%"]
        diff = taxon_result["paired"]["2025_minus_2023"]["top20%"]
        log(f"{taxon}: 2023 {top['n_captured']}/{top['n']}; "
            f"2025−2023 {diff['diff']:.4f} [{diff['boot95'][0]:.4f}, {diff['boot95'][1]:.4f}]")
        taxon_result["agreement_with_stored_files"] = paired.stored_match(taxon, {
            "by_year": {
                "2024": {"capture": taxon_result["by_year"]["2024"]["capture"],
                         "roc_auc_vs_background": taxon_result["by_year"]["2024"]["roc_auc_vs_background"]},
                "2025": {"capture": taxon_result["by_year"]["2025"]["capture"],
                         "roc_auc_vs_background": taxon_result["by_year"]["2025"]["roc_auc_vs_background"]},
            }
        })
        out["taxa"][taxon] = taxon_result
    destination = OUT / "variants" / "temporal_rest.json"
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {destination} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
