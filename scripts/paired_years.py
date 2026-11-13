"""Compare the 2024 and 2025 AlphaEarth images on the same new places.

The temporal split is the one the map uses: train on labels through 2024, and count a
2025–2026 presence only when it is more than 500 m from an older presence. Hogweed keeps
terrain. Goldenrod does not. Each image is fit on that same training split. The difference
is the 2025 capture minus the 2024 capture, with a block bootstrap of the new places.
The landscape behind each capture is that image's own landscape and is not resampled.

This does not write outputs/<taxon>/ and does not replace the 6 November metrics.
After the fit it records whether the temporal capture and ROC AUC match the files
already stored for each image.

Usage: python scripts/paired_years.py
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from invaradar.aef import AEFIndex, BlockCache, block_jobs, prefetch
from invaradar.config import (
    AEF_CACHE,
    AEF_INDEX,
    DATA,
    EPSG,
    INAT_OBS,
    OUT,
    STUDY_BOX,
    TAXA,
    core_binary,
)
from invaradar.model import fit_map
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import (
    block_groups,
    capture_rates,
    landscape_percentile,
    paired_area_difference,
    temporal_sets,
)

CORE = core_binary()
RES = 10.0
YEARS = (2024, 2025)
SEGMENT_NAMES = ("road_major", "road_minor", "rail", "water", "power")
# Hogweed keeps the terrain features. Goldenrod's published and 2024 runs do not.
TERRAIN = {"heracleum": True, "solidago": False}


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def grid_for(year: int, jobs, cache: BlockCache, terrain: bool) -> dict:
    west, south, east, north = STUDY_BOX
    width = int((east - west) / RES)
    height = int((north - south) / RES)
    blocks = []
    for path, row, col, x0, y0 in jobs:
        tile = Path(path).stem
        blocks.append([str(cache.path(year, tile, row, col)), x0, y0])
    grid = {
        "w": west, "n": north, "width": width, "height": height, "res": RES,
        "blocks": blocks,
        "segments": [str(DATA / "segments" / f"{name}.f32") for name in SEGMENT_NAMES],
    }
    if terrain:
        grid["dem"] = str(DATA / "dem_10m.f32")
    return grid


def features(year: int, xy: np.ndarray, jobs, cache: BlockCache, terrain: bool, work: Path) -> np.ndarray:
    work.mkdir(parents=True, exist_ok=True)
    grid_path = work / f"grid_{year}_{'terrain' if terrain else 'noterrain'}.json"
    pts_path = work / "pts.f64"
    out_path = work / f"feat_{year}_{'terrain' if terrain else 'noterrain'}.f32"
    json.dump(grid_for(year, jobs, cache, terrain), grid_path.open("w", encoding="utf-8"))
    np.asarray(xy, dtype="<f8").tofile(pts_path)
    subprocess.run([str(CORE), "points", str(grid_path), str(pts_path), str(out_path)], check=True)
    table = np.fromfile(out_path, dtype="<f4")
    if table.size % len(xy) != 0:
        raise RuntimeError(f"feature file length {table.size} is not a multiple of {len(xy)} points")
    return table.reshape(len(xy), -1)


def finite_rows(table: np.ndarray) -> np.ndarray:
    return np.isfinite(table[:, 0])


def column_check(left: np.ndarray, right: np.ndarray) -> dict:
    """Corridors and terrain must not change with the embedding year. The first 256 columns should."""
    return {
        "width": int(left.shape[1]),
        "corridors_identical": bool(np.array_equal(left[:, 256:261], right[:, 256:261])),
        "terrain_identical": bool(np.array_equal(left[:, 261:265], right[:, 261:265])),
        "terrain_all_zero": bool(np.all(left[:, 261:265] == 0) and np.all(right[:, 261:265] == 0)),
        "embeddings_identical": bool(np.array_equal(left[:, :256], right[:, :256])),
        "nodata_rows_2024": int((~np.isfinite(left[:, 0])).sum()),
        "nodata_rows_2025": int((~np.isfinite(right[:, 0])).sum()),
    }


def stored_match(taxon: str, got: dict) -> dict:
    """Whether this refit landed on the temporal numbers already stored for each image."""
    published = json.loads((OUT / taxon / "metrics.json").read_text(encoding="utf-8"))["temporal_test"]
    variant = json.loads((OUT / "variants" / f"{taxon}_retro2024" / "metrics.json").read_text(encoding="utf-8"))["temporal_test"]
    return {
        "capture20_2024_equals_retro2024": got["by_year"]["2024"]["capture"]["capture@20%area"] == variant["capture@20%area"],
        "capture20_2025_equals_published": got["by_year"]["2025"]["capture"]["capture@20%area"] == published["capture@20%area"],
        "auc_2024_equals_retro2024": got["by_year"]["2024"]["roc_auc_vs_background"] == variant["roc_auc_vs_background"],
        "auc_2025_equals_published": got["by_year"]["2025"]["roc_auc_vs_background"] == published["roc_auc_vs_background"],
    }


def main() -> None:
    if not CORE.is_file():
        raise SystemExit(f"build the core first: {CORE}")
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
    out = {"protocol": {
        "map_year": 2025,
        "embedding_years": list(YEARS),
        "difference": "capture of the 2025 image minus capture of the 2024 image",
        "split": "train on years through 2024; a 2025-2026 presence is new only outside 500 m of an older presence",
        "blocks": "5 km groups of the new places, drawn with replacement; the landscape is not resampled",
        "n_boot": 2000,
        "seed": 0,
        "landscape_points": 40000,
        "landscape_seed": 0,
        "published_6_nov_metrics": "not overwritten",
        "stored_2024_variant": "compared after the fit; see agreement_with_stored_files",
        "terrain_without_dem": "the core still writes four terrain columns, and they are zero",
    }, "taxa": {}}
    obs = INAT_OBS.stat()
    out["observation_file"] = {
        "name": INAT_OBS.name, "bytes": obs.st_size,
        "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(obs.st_mtime)),
    }
    for taxon in ("heracleum", "solidago"):
        log(f"{taxon}: samples")
        frame = build(samples, TAXA[taxon]["ids"], plants)
        terrain = TERRAIN[taxon]
        rng = np.random.default_rng(0)
        west, south, east, north = STUDY_BOX
        landscape_xy = np.column_stack([
            rng.uniform(west, east, 40000), rng.uniform(south, north, 40000),
        ])
        sample_xy = frame[["x", "y"]].to_numpy()
        xy = np.vstack([sample_xy, landscape_xy])
        tables = {}
        for year in YEARS:
            log(f"{taxon}: features for {year}, terrain={terrain}")
            tables[year] = features(year, xy, jobs[year], cache, terrain, work / taxon)
        sample_ok = finite_rows(tables[2024][:len(frame)]) & finite_rows(tables[2025][:len(frame)])
        kept = frame.loc[sample_ok].reset_index(drop=True)
        labels = kept.label.to_numpy()
        coordinates = kept[["x", "y"]].to_numpy()
        years_observed = kept.year.to_numpy()
        train, new, background = temporal_sets(coordinates, labels, years_observed)
        blocks = block_groups(coordinates[new])
        taxon_result = {
            "terrain": terrain,
            "features": int(tables[2024].shape[1]),
            "samples_dropped_as_nodata_on_either_image": int((~sample_ok).sum()),
            "presence": int(labels.sum()),
            "background": int((labels == 0).sum()),
            "n_new_candidates": int(((years_observed >= 2025) & (labels == 1)).sum()),
            "n_new_presence": int(len(new)),
            "n_temporal_background": int(len(background)),
            "n_blocks": int(len(np.unique(blocks))),
            "by_year": {},
        }
        ranks = {}
        for year in YEARS:
            table = tables[year][:len(sample_xy)][sample_ok]
            land = tables[year][len(sample_xy):]
            land = land[finite_rows(land)]
            model = fit_map(table[train], labels[train])
            land_scores = np.sort(model.predict(land))
            new_scores = model.predict(table[new])
            background_scores = model.predict(table[background])
            ranks[year] = landscape_percentile(land_scores, new_scores)
            both = np.r_[new_scores, background_scores]
            truth = np.r_[np.ones(len(new_scores)), np.zeros(len(background_scores))]
            taxon_result["by_year"][str(year)] = {
                "n_landscape": int(len(land)),
                "n_train_presence": int(labels[train].sum()),
                "n_train_background": int((labels[train] == 0).sum()),
                "roc_auc_vs_background": float(roc_auc_score(truth, both)),
                "capture": capture_rates(ranks[year]),
            }
            log(f"{taxon} {year}: capture@20% {taxon_result['by_year'][str(year)]['capture']['capture@20%area']:.4f}")
        paired = {}
        for percent in (1, 5, 10, 20):
            paired[f"top{percent}%"] = paired_area_difference(
                ranks[2025], ranks[2024], blocks, percent=percent, n_boot=2000, seed=0,
            )
        taxon_result["paired_2025_minus_2024"] = paired
        taxon_result["columns"] = column_check(tables[2024], tables[2025])
        taxon_result["agreement_with_stored_files"] = stored_match(taxon, taxon_result)
        diff = paired["top20%"]
        log(f"{taxon}: 2025−2024 at 20% = {diff['diff']:.4f} "
            f"[{diff['boot95'][0]:.4f}, {diff['boot95'][1]:.4f}]")
        out["taxa"][taxon] = taxon_result
    destination = OUT / "variants" / "paired_2025_minus_2024.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {destination} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
