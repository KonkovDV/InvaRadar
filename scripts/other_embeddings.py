"""Read TESSERA and OlmoEarth on the same points as the 2024 map and fit the same forest.

The points, the split and the corridor and terrain columns come from the paired 2024 run
(outputs/variants/paired_years_work). Nothing is written under outputs/<taxon>/.

Both stores are public Zarr. The study window is copied to cache/embeddings and is not committed.
OlmoEarth v1.3 is used under the OlmoEarth Artifact License: not for military, policing or
extractive use. TESSERA is the v1.1 dClimate store.

Usage: python scripts/other_embeddings.py
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from invaradar.config import OUT, ROOT, STUDY_BOX, TAXA
from invaradar.model import fit_map
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.splits import block_groups, capture_rates, landscape_percentile, paired_area_difference, temporal_sets

RES = 10.0
HEIGHT = WIDTH = 6500
CELL = 5
WEST, SOUTH, EAST, NORTH = STUDY_BOX
if (EAST - WEST) / RES != WIDTH or (NORTH - SOUTH) / RES != HEIGHT:
    raise RuntimeError("the study box is not the 6500 by 6500 grid")
OLMO_URL = "s3://olmoearth/olmoearth-v1-3-embeddings/embeddings.zarr"
TESSERA_URL = "s3://tessera/tessera/zarr/v1.1-dclimate"
ENDPOINT = "https://data.source.coop"
YEAR = 2024
CACHE = ROOT / "cache" / "embeddings"


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def dequant_olmo(q: np.ndarray) -> np.ndarray:
    """OlmoEarth int8 to float. -128 is no embedding."""
    values = np.asarray(q).astype(np.float32)
    out = (np.abs(values) / 127.5) ** 2.0 * np.sign(values)
    out[np.asarray(q) == -128] = np.nan
    return out


def dequant_tessera(q: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """TESSERA int8 times the per-pixel scale. A non-finite scale is no embedding.

    `q` is (bands, ...). `scale` is the spatial shape of `q` without the band axis.
    """
    scale = np.asarray(scale, dtype=np.float32)
    out = np.asarray(q, dtype=np.float32) * scale
    bad = ~np.isfinite(scale)
    if bad.ndim == 0:
        if bool(bad):
            out[:] = np.nan
    else:
        out[:, bad] = np.nan
    return out


def study_rc(xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row and column on the 10 m study grid. Row 0 is the north edge."""
    xy = np.asarray(xy, dtype=np.float64)
    row = np.floor((NORTH - xy[:, 1]) / RES).astype(np.int64)
    col = np.floor((xy[:, 0] - WEST) / RES).astype(np.int64)
    return row, col


def grid_origin(transform: list[float]) -> tuple[int, int]:
    """Index of the centre of study pixel (0, 0) in a north-up UTM store."""
    scale_x, _, origin_x, _, scale_y, origin_y = transform
    x = WEST + RES / 2.0
    y = NORTH - RES / 2.0
    return int((y - origin_y) / scale_y), int((x - origin_x) / scale_x)


def window_mean(cell_sum: np.ndarray, count: np.ndarray, k: int) -> np.ndarray:
    """Valid-weighted mean of coarse cells in a k by k window. Edges are replicated, as in the core."""
    half = k // 2
    height, width, _bands = cell_sum.shape
    padded_sum = np.pad(cell_sum, ((half, half), (half, half), (0, 0)), mode="edge")
    padded_count = np.pad(count, ((half, half), (half, half)), mode="edge")
    total = np.zeros_like(cell_sum)
    seen = np.zeros(count.shape, np.float32)
    for dr in range(k):
        for dc in range(k):
            total += padded_sum[dr:dr + height, dc:dc + width]
            seen += padded_count[dr:dr + height, dc:dc + width]
    out = np.zeros_like(cell_sum)
    ok = seen > 0
    out[ok] = total[ok] / seen[ok, None]
    return out


def open_store(url: str):
    import zarr
    from obstore.store import S3Store

    zarr.config.set({"array.sharding_coalesce_max_gap_bytes": 0})
    remote = S3Store.from_url(url, endpoint=ENDPOINT, skip_signature=True)
    return zarr.open_group(zarr.storage.ObjectStore(remote, read_only=True), mode="r")


def _read_rows(url: str, group: str, year: int, bands: int, row: int, height: int, col: int, width: int):
    zone = open_store(url)[group]
    when = int(np.where(np.asarray(zone["time"][:]) == year)[0][0])
    block = zone["embeddings"][when, :bands, row:row + height, col:col + width]
    return np.array(block)


def download_window(url: str, group: str, year: int, bands: int, path: Path, workers: int = 8) -> dict:
    """Copy one year's study window to a local int8 array of shape (bands, 6500, 6500)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = path.with_suffix(".json")
    expected = bands * HEIGHT * WIDTH
    if path.exists() and path.stat().st_size == expected and stamp.exists():
        return json.loads(stamp.read_text(encoding="utf-8"))
    zone = open_store(url)[group]
    transform = [float(v) for v in zone.attrs["spatial:transform"]]
    row0, col0 = grid_origin(transform)
    if int(zone["embeddings"].shape[1]) < bands:
        raise RuntimeError(f"{group} has fewer than {bands} bands")
    array = np.memmap(path, dtype=np.int8, mode="w+", shape=(bands, HEIGHT, WIDTH))
    starts = list(range(0, HEIGHT, 128))
    log(f"{group} {year}: {len(starts)} strips, origin row {row0} col {col0}")

    def one(start: int):
        height = min(128, HEIGHT - start)
        delay = 2.0
        last = None
        for _ in range(6):
            try:
                block = _read_rows(url, group, year, bands, row0 + start, height, col0, WIDTH)
                if block.shape != (bands, height, WIDTH):
                    raise RuntimeError(f"strip shape {block.shape}")
                return start, block
            except Exception as exc:
                last = exc
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(f"{group} row {start}") from last

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, start) for start in starts]
        for future in as_completed(futures):
            start, block = future.result()
            array[:, start:start + block.shape[1]] = block
            done += 1
            if done % 5 == 0 or done == len(starts):
                log(f"{group} {year}: {done}/{len(starts)} strips")
    array.flush()
    meta = {
        "url": url, "group": group, "year": year, "bands": bands,
        "row0": row0, "col0": col0, "shape": [bands, HEIGHT, WIDTH],
        "proj": zone.attrs.get("proj:code"), "transform": transform,
    }
    stamp.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def download_scales(year: int, path: Path, workers: int = 8) -> None:
    expected = HEIGHT * WIDTH * 4
    if path.exists() and path.stat().st_size == expected:
        return
    zone = open_store(TESSERA_URL)["utm37"]
    row0, col0 = grid_origin([float(v) for v in zone.attrs["spatial:transform"]])
    when = int(np.where(np.asarray(zone["time"][:]) == year)[0][0])
    array = np.memmap(path, dtype=np.float32, mode="w+", shape=(HEIGHT, WIDTH))
    starts = list(range(0, HEIGHT, 128))

    def one(start: int):
        local = open_store(TESSERA_URL)["utm37"]
        height = min(128, HEIGHT - start)
        block = local["scales"][when, row0 + start:row0 + start + height, col0:col0 + WIDTH]
        return start, np.array(block)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed(pool.submit(one, start) for start in starts):
            start, block = future.result()
            array[start:start + block.shape[0]] = block
    array.flush()


def _slab(quantized: np.ndarray, scale: np.ndarray | None, row: int, height: int) -> np.ndarray:
    raw = np.array(quantized[:, row:row + height])
    if scale is None:
        return dequant_olmo(raw)
    return dequant_tessera(raw, np.array(scale[row:row + height]))


def four_scales(quantized: np.ndarray, scale: np.ndarray | None, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Pixel, 5x5 mean, 150 m cell mean and 450 m cell mean. NaN where the centre has no embedding."""
    bands = int(quantized.shape[0])
    cells_y, cells_x = HEIGHT // CELL, WIDTH // CELL
    cell_sum = np.zeros((cells_y, cells_x, bands), np.float32)
    count = np.zeros((cells_y, cells_x), np.float32)
    for cell_row in range(cells_y):
        slab = _slab(quantized, scale, cell_row * CELL, CELL)
        block = slab.reshape(bands, CELL, cells_x, CELL)
        valid = np.isfinite(block)
        total = np.where(valid, block, 0.0).sum(axis=(1, 3))
        cell_sum[cell_row] = np.moveaxis(total, 0, -1)
        count[cell_row] = valid[0].sum(axis=(0, 2))
    mean_150 = window_mean(cell_sum, count, 3)
    mean_450 = window_mean(cell_sum, count, 9)
    out = np.empty((len(rows), 4 * bands), np.float32)
    for index in np.argsort(rows, kind="mergesort"):
        row = int(rows[index])
        col = int(cols[index])
        row0, row1 = max(0, row - 2), min(HEIGHT, row + 3)
        col0, col1 = max(0, col - 2), min(WIDTH, col + 3)
        patch_q = np.array(quantized[:, row0:row1, col0:col1])
        if scale is None:
            patch = dequant_olmo(patch_q)
        else:
            patch = dequant_tessera(patch_q, np.array(scale[row0:row1, col0:col1]))
        if patch.shape[1] != 5 or patch.shape[2] != 5:
            patch = np.pad(patch, ((0, 0), (row0 - (row - 2), (row + 3) - row1),
                                   (col0 - (col - 2), (col + 3) - col1)), mode="edge")
        centre = patch[:, 2, 2]
        if not np.isfinite(centre).all():
            out[index] = np.nan
            continue
        valid = np.isfinite(patch[0])
        local = np.where(valid, patch, 0.0).sum(axis=(1, 2)) / valid.sum()
        out[index, :bands] = centre
        out[index, bands:2 * bands] = local
        out[index, 2 * bands:3 * bands] = mean_150[row // CELL, col // CELL]
        out[index, 3 * bands:4 * bands] = mean_450[row // CELL, col // CELL]
    return out


def load_split(taxon: str):
    work = OUT / "variants" / "paired_years_work" / taxon
    points = np.fromfile(work / "pts.f64", dtype="<f8").reshape(-1, 2)
    name = "feat_2024_terrain.f32" if taxon == "heracleum" else "feat_2024_noterrain.f32"
    alpha = np.fromfile(work / name, dtype="<f4").reshape(len(points), -1)
    frame = build(load_obs(), TAXA[taxon]["ids"], plant_taxa())
    sample = frame[["x", "y"]].to_numpy()
    if sample.shape != points[:len(sample)].shape or not np.allclose(sample, points[:len(sample)]):
        raise RuntimeError(f"{taxon}: the saved points are not the current observation sample")
    return points, alpha, frame


def evaluate(features: np.ndarray, labels: np.ndarray, train, new, background, land: np.ndarray) -> tuple[dict, np.ndarray]:
    model = fit_map(features[train], labels[train])
    land_scores = np.sort(model.predict(land))
    new_scores = model.predict(features[new])
    background_scores = model.predict(features[background])
    ranks = landscape_percentile(land_scores, new_scores)
    both = np.r_[new_scores, background_scores]
    truth = np.r_[np.ones(len(new_scores)), np.zeros(len(background_scores))]
    summary = {
        "n_features": int(features.shape[1]),
        "n_landscape": int(len(land)),
        "n_new": int(len(new)),
        "roc_auc_vs_background": float(roc_auc_score(truth, both)),
        "capture": capture_rates(ranks),
    }
    return summary, ranks


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def fit_one(name: str, embedding: np.ndarray, context: np.ndarray, frame, sample_xy: np.ndarray) -> tuple[dict, np.ndarray]:
    table = np.concatenate([embedding, context], axis=1)
    n_sample = len(frame)
    sample = table[:n_sample]
    land = table[n_sample:]
    ok = np.isfinite(sample[:, 0])
    land_ok = np.isfinite(land[:, 0])
    labels = frame.label.to_numpy()
    years = frame.year.to_numpy()
    train, new, background = temporal_sets(sample_xy[ok], labels[ok], years[ok])
    summary, ranks = evaluate(sample[ok], labels[ok], train, new, background, land[land_ok])
    summary["samples_kept"] = int(ok.sum())
    summary["samples_dropped"] = int((~ok).sum())
    summary["n_blocks"] = int(len(np.unique(block_groups(sample_xy[ok][new]))))
    log(f"  {name}: kept {int(ok.sum())} new {len(new)} capture@20 {summary['capture']['capture@20%area']:.4f}")
    return summary, ranks


def shared_difference(name: str, embedding: np.ndarray, alpha_embedding: np.ndarray, context: np.ndarray,
                      frame, sample_xy: np.ndarray) -> dict:
    """Paired capture on the places where both embeddings exist."""
    n_sample = len(frame)
    both = np.isfinite(embedding[:n_sample, 0]) & np.isfinite(alpha_embedding[:n_sample, 0])
    labels = frame.label.to_numpy()
    years = frame.year.to_numpy()
    train, new, background = temporal_sets(sample_xy[both], labels[both], years[both])
    blocks = block_groups(sample_xy[both][new])
    sides = {}
    ranks = {}
    for side, block in ((name, embedding), ("alphaearth", alpha_embedding)):
        table = np.concatenate([block, context], axis=1)
        land = table[n_sample:]
        land = land[np.isfinite(land[:, 0])]
        summary, rank = evaluate(table[:n_sample][both], labels[both], train, new, background, land)
        sides[side] = summary
        ranks[side] = rank
    diffs = {}
    for percent in (1, 5, 10, 20):
        diffs[f"top{percent}%"] = paired_area_difference(
            ranks[name], ranks["alphaearth"], blocks, percent=percent, n_boot=2000, seed=0)
    top = diffs["top20%"]
    log(f"  {name}−alphaearth @20% {top['diff']:.4f} [{top['boot95'][0]:.4f}, {top['boot95'][1]:.4f}]")
    return {"n_new": int(len(new)), "n_blocks": int(len(np.unique(blocks))), "sides": sides, "minus_alphaearth": diffs}


def main() -> None:
    started = time.time()
    CACHE.mkdir(parents=True, exist_ok=True)
    olmo_path = CACHE / "olmoearth_v1_3_utm37_2024_b64.i8"
    tessera_path = CACHE / "tessera_v1_1_dclimate_utm37_2024_b128.i8"
    scale_path = CACHE / "tessera_v1_1_dclimate_utm37_2024_scale.f32"
    log("OlmoEarth window")
    olmo_meta = download_window(OLMO_URL, "utm37", YEAR, 64, olmo_path)
    log("TESSERA window")
    tessera_meta = download_window(TESSERA_URL, "utm37", YEAR, 128, tessera_path, workers=6)
    log("TESSERA scales")
    download_scales(YEAR, scale_path, workers=6)
    olmo = np.memmap(olmo_path, dtype=np.int8, mode="r", shape=(64, HEIGHT, WIDTH))
    tessera = np.memmap(tessera_path, dtype=np.int8, mode="r", shape=(128, HEIGHT, WIDTH))
    tessera_scale = np.memmap(scale_path, dtype=np.float32, mode="r", shape=(HEIGHT, WIDTH))
    report = {
        "protocol": {
            "year": YEAR,
            "split": "train through 2024; a 2025-2026 presence counts only outside 500 m of an older presence",
            "forest": "invaradar.model.fit_map",
            "landscape": "the 40 000 points stored with the paired 2024 run",
            "scales": "pixel, valid-weighted 5x5, then 3x3 and 9x9 means of the 50 m cells, replicate edges",
            "context": "the 2024 corridor and terrain columns, unchanged",
            "olmoearth": "v1.3, bands 0:64, published dequantization",
            "tessera": "v1.1 dClimate, 128 bands times the per-pixel scale",
            "published_map": "not overwritten",
            "license_olmoearth": "OlmoEarth Artifact License; not for military, policing or extractive use",
            "stores": {"olmoearth": olmo_meta, "tessera": tessera_meta},
        },
        "taxa": {},
    }
    for taxon in ("heracleum", "solidago"):
        log(f"{taxon}")
        points, alpha, frame = load_split(taxon)
        rows, cols = study_rc(points)
        inside = (rows >= 0) & (rows < HEIGHT) & (cols >= 0) & (cols < WIDTH)
        if not bool(inside.all()):
            raise RuntimeError(f"{taxon}: {int((~inside).sum())} points fall outside the study grid")
        log(f"{taxon}: OlmoEarth scales")
        olmo_embedding = four_scales(olmo, None, rows, cols)
        log(f"{taxon}: TESSERA scales")
        tessera_embedding = four_scales(tessera, tessera_scale, rows, cols)
        alpha_embedding = alpha[:, :256]
        context = alpha[:, 256:]
        sample_xy = points[:len(frame)]
        alone = {}
        for name, embedding in (("alphaearth", alpha_embedding), ("olmoearth", olmo_embedding), ("tessera", tessera_embedding)):
            alone[name], _ranks = fit_one(f"{taxon} {name}", embedding, context, frame, sample_xy)
        report["taxa"][taxon] = {
            "alone": alone,
            "olmoearth_minus_alphaearth": shared_difference(
                "olmoearth", olmo_embedding, alpha_embedding, context, frame, sample_xy),
            "tessera_minus_alphaearth": shared_difference(
                "tessera", tessera_embedding, alpha_embedding, context, frame, sample_xy),
        }
    destination = OUT / "variants" / "other_embeddings_2024.json"
    destination.write_text(json.dumps(plain(report), ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote {destination} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
