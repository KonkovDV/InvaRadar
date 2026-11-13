"""Ретро-прогноз без утечки по времени на реальных данных (docs/11, исследование 1; аудит A-02).

**Что сравниваем.** Одни и те же метки, разные годы признаков:
- обучение — находки iNaturalist до 31.12.2024 плюс фон целевой группы (другие сосудистые) того же периода;
- проверка — находки 2025–2026 годов дальше 500 м от старых (новые места);
- признаки — эмбеддинг AlphaEarth пикселя 10 м (64 значения) за 2023, 2024 или 2025 год.

Если признаки 2025 года заметно лучше 2024-го на находках 2025–2026 годов, то снимок «видит» уже
выросшие заросли: это утечка, а не прогноз.

**Дополнительные сравнения:**
- близость к старым находкам — базовая модель распространения;
- сочетание близости и модели;
- ограничено ли распространение расстоянием: распределение расстояний от новых находок до старых
  против фона новых наблюдений других растений.

**Упрощение относительно InvaRadar** — только 64 признака пикселя, без окон 50/150/450 м, коридоров
и рельефа. Поэтому абсолютные доли ниже, чем у полной модели. Сравнение лет при этом честное.

Запуск: `INVARADAR_PRO_CACHE=/путь python analysis/realdata/retro_forecast.py`
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
from aef_points import GCS, NODATA, dequantize, embeddings_at  # noqa: E402
from fetch_inat import fetch_all  # noqa: E402
from invaradar_pro.sampling import wilson_ci  # noqa: E402
from invaradar_pro.validation import (  # noqa: E402
    capture_at_area,
    capture_report,
    combine_model_and_proximity,
    nearest_dist,
    retro_forecast_verdict,
)

BOX = (381000.0, 6147000.0, 446000.0, 6212000.0)  # STUDY_BOX InvaRadar, EPSG:32637
CUT, END = "2024-12-31", "2026-11-07"
YEARS = (2023, 2024, 2025)
LGB = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.5, reg_lambda=1.0, random_state=0, verbose=-1)
BINS = [0, 250, 500, 1000, 2000, 5000, 1e9]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def tiles_for_box(cache: Path) -> pd.DataFrame:
    f = cache / "aef_tiles_box.csv"
    if f.exists():
        return pd.read_csv(f)
    import requests
    idx = cache / "aef_index.parquet"
    if not idx.exists():
        log("индекс AlphaEarth")
        idx.write_bytes(requests.get(GCS + "satellite_embedding/v1/annual/aef_index.parquet", timeout=600).content)
    df = pd.read_parquet(idx, columns=["path", "year", "crs", "utm_west", "utm_south", "utm_east", "utm_north"])
    sel = df[(df.crs == "EPSG:32637") & (df.utm_west < BOX[2]) & (df.utm_east > BOX[0]) & (df.utm_south < BOX[3])
             & (df.utm_north > BOX[1]) & df.year.isin(YEARS)]
    sel.to_csv(f, index=False)
    return sel


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df.acc.notna() & (df.acc <= 50) & df.observed_on.notna()].copy()
    x, y = Transformer.from_crs(4326, 32637, always_xy=True).transform(df.lon.values, df.lat.values)
    df["x"], df["y"] = x, y
    df = df[(df.x >= BOX[0]) & (df.x < BOX[2]) & (df.y >= BOX[1]) & (df.y < BOX[3])]
    key = np.floor(df.x / 10).astype(np.int64) * 10_000_000 + np.floor(df.y / 10).astype(np.int64)
    return df.loc[~key.duplicated()].reset_index(drop=True)


def blocks5km(x, y):
    return (np.floor((np.asarray(x) - BOX[0]) / 5000) * 100 + np.floor((np.asarray(y) - BOX[1]) / 5000)).astype(int)


def main() -> dict:
    cache = Path(os.environ.get("INVARADAR_PRO_CACHE", ROOT / "analysis" / "cache"))
    cache.mkdir(parents=True, exist_ok=True)
    to_ll = Transformer.from_crs(32637, 4326, always_xy=True)
    corners = [to_ll.transform(x, y) for x in (BOX[0], BOX[2]) for y in (BOX[1], BOX[3])]
    lons, lats = zip(*corners)
    data = fetch_all((min(lats), min(lons), max(lats), max(lons)), cache, log=log)

    bg_old = clean(pd.concat([data[f"bg_{y}"] for y in range(2014, 2025)], ignore_index=True))
    bg_old = bg_old[bg_old.observed_on <= CUT].reset_index(drop=True)
    bg_new = clean(pd.concat([data["bg_2025"], data["bg_2026"]], ignore_index=True))
    bg_new = bg_new[(bg_new.observed_on > CUT) & (bg_new.observed_on <= END)].reset_index(drop=True)
    rng = np.random.default_rng(0)
    land = np.column_stack([rng.uniform(BOX[0], BOX[2], 40_000), rng.uniform(BOX[1], BOX[3], 40_000)])

    sets, pts = {}, [land, bg_old[["x", "y"]].to_numpy()]
    for taxon in ("heracleum", "solidago"):
        p = clean(data[taxon])
        old = p[p.observed_on <= CUT].reset_index(drop=True)
        new = p[(p.observed_on > CUT) & (p.observed_on <= END)].reset_index(drop=True)
        d_new = nearest_dist(new[["x", "y"]].to_numpy(), old[["x", "y"]].to_numpy())
        far = new[d_new > 500].reset_index(drop=True)
        sets[taxon] = {"old": old, "new": new, "far": far, "d_new": d_new}
        pts += [old[["x", "y"]].to_numpy(), far[["x", "y"]].to_numpy()]
        log(f"{taxon}: старых {len(old)}, новых {len(new)}, из них дальше 500 м {len(far)}")
    allpts = np.vstack(pts)
    np.save(cache / "points_xy.npy", allpts)

    tiles = tiles_for_box(cache)
    emb = {}
    for year in YEARS:
        f = cache / f"aef_{year}_points.npy"
        if f.exists() and np.load(f, mmap_mode="r").shape[0] == len(allpts):
            emb[year] = np.load(f)
            continue
        log(f"AlphaEarth {year}: {len(allpts)} точек")
        e = embeddings_at(allpts[:, 0], allpts[:, 1], year, tiles, log=log)
        np.save(f, e)
        emb[year] = e

    # индексы групп в allpts
    n_land, n_bg = len(land), len(bg_old)
    off = n_land + n_bg
    idx = {"land": np.arange(n_land), "bg": np.arange(n_land, off)}
    for taxon in ("heracleum", "solidago"):
        n_old, n_far = len(sets[taxon]["old"]), len(sets[taxon]["far"])
        idx[f"{taxon}_old"] = np.arange(off, off + n_old)
        idx[f"{taxon}_far"] = np.arange(off + n_old, off + n_old + n_far)
        off += n_old + n_far

    results = {"box_epsg32637": BOX, "cut": CUT, "end": END, "features": "AlphaEarth pixel embedding, 64 dims",
               "lgb": LGB, "background_old": int(n_bg), "background_new": int(len(bg_new)), "taxa": {}}
    for taxon in ("heracleum", "solidago"):
        S = sets[taxon]
        old_xy = S["old"][["x", "y"]].to_numpy()
        bg_ok = nearest_dist(allpts[idx["bg"]], old_xy) > 30  # фон дальше 30 м от находок этого вида
        far_xy = allpts[idx[f"{taxon}_far"]]
        blocks = blocks5km(far_xy[:, 0], far_xy[:, 1])
        tres = {"n_old": int(len(S["old"])), "n_new": int(len(S["new"])), "n_new_far": int(len(S["far"])),
                "by_year": {}}
        scores = {}
        for year in YEARS:
            E = emb[year]
            valid = E[:, 0] != NODATA
            tr_idx = np.concatenate([idx[f"{taxon}_old"], idx["bg"][bg_ok]])
            tr_idx = tr_idx[valid[tr_idx]]
            y = np.isin(tr_idx, idx[f"{taxon}_old"]).astype(int)
            w = (y == 0).sum() / max((y == 1).sum(), 1)
            m = lgb.LGBMClassifier(**LGB, scale_pos_weight=float(w))
            m.fit(dequantize(E[tr_idx]), y)
            land_i = idx["land"][valid[idx["land"]]]
            far_i = idx[f"{taxon}_far"]
            far_ok = valid[far_i]
            s_land = m.predict_proba(dequantize(E[land_i]))[:, 1]
            s_far = np.full(len(far_i), -np.inf)
            s_far[far_ok] = m.predict_proba(dequantize(E[far_i[far_ok]]))[:, 1]
            scores[year] = (s_land, s_far)
            rep = capture_report(s_far, s_land, blocks=blocks, n_boot=2000, seed=year)
            tres["by_year"][str(year)] = {"capture": rep, "verdict_top20": retro_forecast_verdict(rep),
                                          "n_train_pos": int(y.sum()), "n_train_bg": int((y == 0).sum())}
            log(f"{taxon} {year}: top10 {rep['top10%']['capture']:.3f}, top20 {rep['top20%']['capture']:.3f}")
        # утечка: 2025 против 2024 на тех же проверочных точках, парный блочный бутстрэп
        ub = np.unique(blocks)
        gi = [np.where(blocks == b)[0] for b in ub]
        diffs = []
        for _ in range(2000):
            sel = np.concatenate([gi[j] for j in rng.integers(0, len(ub), len(ub))])
            diffs.append(capture_at_area(scores[2025][1][sel], scores[2025][0], 0.2)
                         - capture_at_area(scores[2024][1][sel], scores[2024][0], 0.2))
        d0 = (capture_at_area(scores[2025][1], scores[2025][0], 0.2) - capture_at_area(scores[2024][1], scores[2024][0], 0.2))
        tres["leakage_2025_minus_2024_top20"] = {"diff": round(float(d0), 4),
                                                 "boot95": [round(float(v), 4) for v in np.percentile(diffs, [2.5, 97.5])]}
        # близость к старым находкам и сочетание с моделью 2024 года
        prox_land = -nearest_dist(allpts[idx["land"]], old_xy)
        prox_far = -nearest_dist(far_xy, old_xy)
        tres["proximity"] = capture_report(prox_far, prox_land, blocks=blocks, n_boot=2000, seed=7)
        s_land24, s_far24 = scores[2024]
        land_valid = emb[2024][idx["land"], 0] != NODATA
        far_valid = np.isfinite(s_far24)
        comb_far, comb_land = combine_model_and_proximity(
            s_land24, s_far24, prox_land, prox_far, land_valid, far_valid)
        tres["combined_2024_plus_proximity"] = capture_report(
            comb_far, comb_land, blocks=blocks[far_valid], n_boot=2000, seed=8)
        # ограничено ли распространение расстоянием: новые находки вида против новых наблюдений других растений
        d_t = S["d_new"]
        d_b = nearest_dist(bg_new[["x", "y"]].to_numpy(), old_xy)
        rows = []
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            xt, xb = int(((d_t >= lo) & (d_t < hi)).sum()), int(((d_b >= lo) & (d_b < hi)).sum())
            st, sb = xt / max(len(d_t), 1), xb / max(len(d_b), 1)
            rows.append({"from_m": lo, "to_m": None if hi > 1e8 else hi, "target_share": round(st, 4),
                         "target_ci95": [round(v, 4) for v in wilson_ci(xt, len(d_t))], "background_share": round(sb, 4),
                         "relative_risk": round(st / sb, 2) if sb > 0 else None})
        tres["dispersal_distance"] = {"median_target_m": float(np.median(d_t)), "median_background_m": float(np.median(d_b)),
                                      "bins": rows}
        results["taxa"][taxon] = tres
    out = ROOT / "analysis" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "retro_forecast.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log("готово:", out / "retro_forecast.json")
    return results


if __name__ == "__main__":
    main()
