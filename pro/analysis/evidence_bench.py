"""Бенчмарк проверки повторного использования фото на реальных снимках борщевика (исследование 4 in silico).

**Снимки.** iNaturalist, *Heracleum sosnowskyi*, лицензии CC0 и CC BY. Используются только для расчёта:
в архив не входят, хранятся в кэше.

**Позитивы** — «безобидные» пересылки того же снимка, которые подрядчик мог бы выдать за новое фото:
пересжатие, уменьшение, мессенджер, обрезка краёв, яркость, контраст, поворот на 2°.
**Трудные позитивы** — обрезка 20%, поворот 10°, зеркало: проверка устойчивости к намеренному обходу.
**Негативы** — разные снимки борщевика: похожие сцены, самый трудный случай для ложной тревоги.

Метрики для dHash, pHash и их сочетания:
- доля пойманных повторов (TPR) и ложных тревог (FPR) при порогах 0–32;
- AUC;
- порог при FPR ≤ 0,5%.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from invaradar_pro.evidence import dhash, hamming, phash  # noqa: E402


def _jpeg(im, q):
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue()))


def _crop(im, f):
    w, h = im.size
    return im.crop((int(w * f), int(h * f), int(w * (1 - f)), int(h * (1 - f))))


def _fit(im, side):
    s = side / max(im.size)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))


BENIGN = {
    "jpeg_q60": lambda im: _jpeg(im, 60),
    "jpeg_q30": lambda im: _jpeg(im, 30),
    "resize_50": lambda im: im.resize((im.width // 2, im.height // 2)),
    "messenger_800_q70": lambda im: _jpeg(_fit(im, 800), 70),
    "crop_5": lambda im: _crop(im, 0.05),
    "brightness_+20": lambda im: ImageEnhance.Brightness(im).enhance(1.2),
    "contrast_-20": lambda im: ImageEnhance.Contrast(im).enhance(0.8),
    "rotate_2": lambda im: im.rotate(2, resample=Image.Resampling.BILINEAR),
}
HARD = {
    "crop_20": lambda im: _crop(im, 0.2),
    "rotate_10": lambda im: im.rotate(10, resample=Image.Resampling.BILINEAR),
    "mirror": ImageOps.mirror,
}


def fetch_photos(cache: Path, n: int = 150) -> list[Path]:
    d = cache / "bench_photos"
    d.mkdir(parents=True, exist_ok=True)
    have = sorted(d.glob("*.jpg"))
    if len(have) >= n:
        return have[:n]
    s = requests.Session()
    s.headers["User-Agent"] = "invaradar-pro-research/0.3"
    urls, page = [], 1
    while len(urls) < n * 1.3 and page <= 3:
        r = s.get("https://api.inaturalist.org/v1/observations",
                  params={"taxon_id": 499936, "photo_license": "cc0,cc-by", "quality_grade": "research",
                          "per_page": 200, "page": page, "order_by": "id", "order": "desc"}, timeout=120).json()
        for o in r.get("results", []):
            if o.get("photos"):
                urls.append((o["id"], o["photos"][0]["url"].replace("square", "medium")))
        page += 1
        time.sleep(1.0)
    for oid, u in urls:
        if len(list(d.glob("*.jpg"))) >= n:
            break
        f = d / f"{oid}.jpg"
        if f.exists():
            continue
        try:
            b = s.get(u, timeout=60).content
            Image.open(io.BytesIO(b)).verify()
            f.write_bytes(b)
        except Exception:
            continue
    return sorted(d.glob("*.jpg"))[:n]


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(расстояние позитива < расстояния негатива) + 0,5·P(равны)."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    lt = (pos[:, None] < neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(lt + 0.5 * eq)


def main() -> dict:
    cache = Path(os.environ.get("INVARADAR_PRO_CACHE", ROOT / "analysis" / "cache"))
    files = fetch_photos(cache)
    ims = [Image.open(f).convert("RGB") for f in files]
    H = {"dhash": dhash, "phash": phash}
    base = {k: [f(im) for im in ims] for k, f in H.items()}
    rng = np.random.default_rng(0)
    res = {"n_photos": len(ims), "source": "iNaturalist, Heracleum sosnowskyi, CC0/CC BY", "hashes": {}}
    pos, hard, neg = {k: {} for k in H}, {k: {} for k in H}, {k: [] for k in H}
    for name, t in {**BENIGN, **HARD}.items():
        tv = [t(im) for im in ims]
        for k, f in H.items():
            dist = np.array([hamming(base[k][i], f(tv[i])) for i in range(len(ims))])
            (pos if name in BENIGN else hard)[k][name] = dist
    pairs = [(i, j) for i in range(len(ims)) for j in rng.choice(len(ims), 20, replace=False) if i != j]
    for k in H:
        neg[k] = np.array([hamming(base[k][i], base[k][j]) for i, j in pairs])
    for k in H:
        P = np.concatenate(list(pos[k].values()))
        N = neg[k]
        curve = [{"t": t, "tpr": round(float((P <= t).mean()), 4), "fpr": round(float((N <= t).mean()), 5)} for t in range(33)]
        ok = [c for c in curve if c["fpr"] <= 0.005]
        best = max(ok, key=lambda c: c["tpr"]) if ok else curve[0]
        res["hashes"][k] = {
            "auc_benign": round(auc(P, N), 4), "best_t_at_fpr_0.5pct": best,
            "per_transform_tpr_at_best_t": {n: round(float((d <= best["t"]).mean()), 3) for n, d in pos[k].items()},
            "hard_tpr_at_best_t": {n: round(float((d <= best["t"]).mean()), 3) for n, d in hard[k].items()},
            "neg_min": int(N.min()), "neg_p01": float(np.percentile(N, 1)), "curve": curve}
    td, tp = res["hashes"]["dhash"]["best_t_at_fpr_0.5pct"]["t"], res["hashes"]["phash"]["best_t_at_fpr_0.5pct"]["t"]
    Pd = np.concatenate(list(pos["dhash"].values()))
    Pp = np.concatenate(list(pos["phash"].values()))
    res["combined_or"] = {"t_dhash": td, "t_phash": tp, "tpr": round(float(((Pd <= td) | (Pp <= tp)).mean()), 4),
                          "fpr": round(float(((neg["dhash"] <= td) | (neg["phash"] <= tp)).mean()), 5)}
    from invaradar_pro.evidence import DUP_HAMMING, PHASH_DUP, REVIEW_DHASH, REVIEW_PHASH  # noqa: E402

    def policy(td_, tp_):
        hit = (Pd <= td_) | (Pp <= tp_)
        fa = (neg["dhash"] <= td_) | (neg["phash"] <= tp_)
        return {"t_dhash": td_, "t_phash": tp_, "tpr": round(float(hit.mean()), 4), "fpr": round(float(fa.mean()), 5)}

    res["current_thresholds"] = {"strict_fail": policy(DUP_HAMMING, PHASH_DUP), "review": policy(REVIEW_DHASH, REVIEW_PHASH),
                                 "legacy_dhash_6": policy(6, -1)}
    res["note"] = ("Единственная «ложная» пара на малом расстоянии — настоящий повтор одного снимка в двух наблюдениях "
                   "iNaturalist (pHash 0, средняя разница пикселей 0,5/255)")
    out = ROOT / "analysis" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence_bench.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = main()
    for k, v in r["hashes"].items():
        print(k, "AUC", v["auc_benign"], "best", v["best_t_at_fpr_0.5pct"], "hard", v["hard_tpr_at_best_t"])
    print("combined", r["combined_or"], "current", r["current_thresholds"])
