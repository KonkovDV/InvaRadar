"""UAV module on real aerial photos: frozen DINOv2 patch features + linear probe, leave-one-camera-out.

Data: open Heracleum dataset (Menshchikov et al., IEEE Trans. Computers 70(8), 2021;
github.com/DLopatkin/Heracleum-Dataset) — 263 aerial photos of Heracleum sosnowskyi from the Moscow region
taken by three cameras (DJI Mavic Pro FC220, DJI Phantom 3 FC300S, Xiaomi Yi), with per-pixel masks.
The images are not redistributed; clone the dataset and pass its folder.

Protocol (no leakage): every camera is held out in turn, the probe and its thresholds are fitted on the other two
cameras only (max F1 — balanced; max F2 — scouting, a missed stand costs more than an extra check). Metrics: patch ROC AUC and AP, pixel IoU / Dice /
precision / recall of the upsampled probability map, image-level detection, object recall for stands ≥ 0.05% frame.

    python scripts/drone_benchmark.py /path/to/Heracleum-Dataset
"""
import json
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from PIL import Image
from scipy import ndimage
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from invaradar.config import OUT, SCRATCH  # noqa: E402

WIDTH, PATCH = 896, 14
MODEL = "vit_small_patch14_dinov2.lvd142m"  # Apache-2.0
CAMERAS = {"FC220": "DJI Mavic Pro", "FC300S": "DJI Phantom 3", "YDXJ 1": "Xiaomi Yi"}


def camera(img: Image.Image) -> str:
    model = str(img.getexif().get(272, "")).split("\x00")[0].strip()
    return model if model in CAMERAS else "other"


def load(path_img: Path, path_mask: Path):
    img = Image.open(path_img).convert("RGB")
    cam = camera(img)
    h = int(round(img.height * WIDTH / img.width / PATCH)) * PATCH
    rgb = np.asarray(img.resize((WIDTH, h), Image.BILINEAR), np.float32) / 255.0
    m = np.asarray(Image.open(path_mask).convert("L").resize((WIDTH, h), Image.NEAREST)) > 0
    return rgb, m, cam


def extract(root: Path, cache: Path):
    if cache.exists():
        return dict(np.load(cache, allow_pickle=True))
    import timm
    import torch
    torch.set_num_threads(os.cpu_count() or 4)
    net = timm.create_model(MODEL, pretrained=True, num_classes=0, dynamic_img_size=True).eval()
    mean = np.array([0.485, 0.456, 0.406], np.float32); std = np.array([0.229, 0.224, 0.225], np.float32)
    feats, fracs, cams, shapes, masks = [], [], [], [], []
    files = sorted((root / "images").glob("*.jpg"))
    t0 = time.time()
    for i, f in enumerate(files):
        rgb, m, cam = load(f, root / "masks" / (f.stem + ".png"))
        x = torch.from_numpy(((rgb - mean) / std).transpose(2, 0, 1)[None])
        with torch.no_grad():
            tok = net.forward_features(x)[0, net.num_prefix_tokens:].numpy().astype(np.float16)
        hp, wp = rgb.shape[0] // PATCH, rgb.shape[1] // PATCH
        frac = m.reshape(hp, PATCH, wp, PATCH).mean((1, 3)).astype(np.float16)
        feats.append(tok); fracs.append(frac.ravel()); cams.append(cam); shapes.append((hp, wp))
        masks.append(np.packbits(m))
        if i % 25 == 0:
            print(f"{i}/{len(files)} {time.time() - t0:.0f}s", flush=True)
    d = {"feats": np.array(feats, dtype=object), "fracs": np.array(fracs, dtype=object), "cams": np.array(cams),
         "shapes": np.array(shapes), "masks": np.array(masks, dtype=object), "files": np.array([f.stem for f in files])}
    np.savez(cache, **d)
    return d


def norm(x):
    x = x.astype(np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def with_context(tok, hp, wp):
    """Patch token + mean of its 3×3 neighbourhood (both L2-normalised): a stand is judged with its surroundings."""
    t = norm(tok)
    ctx = ndimage.uniform_filter(t.reshape(hp, wp, -1), size=(3, 3, 1), mode="nearest").reshape(hp * wp, -1)
    return np.hstack([t, norm(ctx)])


def fbeta_threshold(y, p, beta):
    pr, rc, th = precision_recall_curve(y, p)
    f = (1 + beta**2) * pr * rc / np.maximum(beta**2 * pr + rc, 1e-9)
    return float(th[np.argmax(f[:-1])])


def fit(X, y, seed=0):
    """Logistic probe; thresholds max F1 (balanced) and max F2 (scouting: a missed stand costs more than a check)."""
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(y); neg = np.flatnonzero(~y)
    neg = rng.choice(neg, min(len(neg), 4 * len(pos)), replace=False)
    idx = np.concatenate([pos, neg])
    clf = LogisticRegression(C=2.0, class_weight="balanced", max_iter=3000)
    clf.fit(X[idx], y[idx])
    p = clf.predict_proba(X)[:, 1]
    return clf, {"f1": fbeta_threshold(y, p, 1.0), "f2": fbeta_threshold(y, p, 2.0)}


def upsample(p, hp, wp):
    return ndimage.zoom(p.reshape(hp, wp), PATCH, order=1)


KEYS = ["inter", "union", "fp", "fn", "obj", "obj_hit", "img_pos_hit", "img_pos", "img_neg_ok", "img_neg"]


def score(st):
    tp = st["inter"]
    return {"pixel_iou": round(tp / max(st["union"], 1), 3),
            "pixel_dice": round(2 * tp / max(2 * tp + st["fp"] + st["fn"], 1), 3),
            "pixel_precision": round(tp / max(tp + st["fp"], 1), 3),
            "pixel_recall": round(tp / max(tp + st["fn"], 1), 3),
            "stand_recall": round(st["obj_hit"] / max(st["obj"], 1), 3), "stands": st["obj"],
            "images_with_hogweed_detected": f'{st["img_pos_hit"]}/{st["img_pos"]}',
            "empty_images_clean": f'{st["img_neg_ok"]}/{st["img_neg"]}'}


def accumulate(st, gt, prob, thr):
    pm = prob >= thr
    st["inter"] += int((gt & pm).sum()); st["union"] += int((gt | pm).sum())
    st["fp"] += int((pm & ~gt).sum()); st["fn"] += int((gt & ~pm).sum())
    lab, k = ndimage.label(gt)
    if k:
        sizes = ndimage.sum(gt, lab, range(1, k + 1))
        hit = np.asarray(ndimage.maximum(pm, lab, range(1, k + 1)))
        big = sizes >= 0.0005 * gt.size
        st["obj"] += int(big.sum()); st["obj_hit"] += int((hit[big] > 0).sum())
    if gt.mean() > 0.0005:
        st["img_pos"] += 1; st["img_pos_hit"] += int(pm.mean() > 0.0005)
    else:
        st["img_neg"] += 1; st["img_neg_ok"] += int(pm.mean() <= 0.0005)


def main(root):
    root = Path(root)
    d = extract(root, SCRATCH / "drone_skoltech_dinov2s.npz")
    cams = d["cams"]; n = len(cams)
    X = [with_context(f, *d["shapes"][i]) for i, f in enumerate(d["feats"])]
    F = [f.astype(np.float32) for f in d["fracs"]]
    res = {"dataset": "Heracleum dataset, Moscow region (Menshchikov et al. 2021), 263 aerial photos, 3 cameras",
           "backbone": f"{MODEL} (frozen, Apache-2.0), {WIDTH}px wide input, 14px patches",
           "probe": "L2-normalised patch token + 3×3 context mean → logistic regression",
           "operating_points": "thresholds chosen on the training cameras only: f1 = max F1 (balanced), "
                               "f2 = max F2 (scouting, recall-weighted)",
           "protocol": "leave-one-camera-out", "folds": {}}
    pooled = {"y": [], "p": [], "f1": dict.fromkeys(KEYS, 0), "f2": dict.fromkeys(KEYS, 0)}
    examples = {}
    for held in sorted(set(cams)):
        tr = [i for i in range(n) if cams[i] != held]; te = [i for i in range(n) if cams[i] == held]
        clf, thr = fit(np.concatenate([X[i] for i in tr]), np.concatenate([F[i] for i in tr]) >= 0.5)
        ys, ps = [], []
        st = {"f1": dict.fromkeys(KEYS, 0), "f2": dict.fromkeys(KEYS, 0)}
        for i in te:
            p = clf.predict_proba(X[i])[:, 1]
            ys.append(F[i] >= 0.5); ps.append(p)
            hp, wp = d["shapes"][i]
            gt = np.unpackbits(d["masks"][i])[: hp * PATCH * wp * PATCH].reshape(hp * PATCH, wp * PATCH).astype(bool)
            prob = upsample(p, hp, wp)
            for op in st:
                accumulate(st[op], gt, prob, thr[op])
            if held not in examples and 0.05 < gt.mean() < 0.3:
                examples[held] = (d["files"][i], prob, thr["f2"])
        y = np.concatenate(ys); p = np.concatenate(ps)
        fold = {"camera": CAMERAS.get(held, held), "images": len(te), "patches": int(len(y)),
                "patch_roc_auc": round(float(roc_auc_score(y, p)), 3),
                "patch_ap": round(float(average_precision_score(y, p)), 3),
                "thresholds": {k: round(v, 3) for k, v in thr.items()},
                "f1": score(st["f1"]), "f2": score(st["f2"])}
        res["folds"][held] = fold
        print(json.dumps(fold, ensure_ascii=False), flush=True)
        pooled["y"].append(y); pooled["p"].append(p)
        for op in ("f1", "f2"):
            for k in KEYS:
                pooled[op][k] += st[op][k]
    y = np.concatenate(pooled["y"]); p = np.concatenate(pooled["p"])
    res["pooled"] = {"images": n, "patch_roc_auc": round(float(roc_auc_score(y, p)), 3),
                     "patch_ap": round(float(average_precision_score(y, p)), 3),
                     "f1": score(pooled["f1"]), "f2": score(pooled["f2"]),
                     "note": "pooled over held-out cameras, each scored by a probe that never saw that camera"}
    # final probe on all cameras for deployment (invaradar.drone.DinoProbeSegmenter)
    clf, thr = fit(np.concatenate(X), np.concatenate(F) >= 0.5)
    out = Path(OUT) / "drone"; out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": MODEL, "width": WIDTH, "context": 3, "coef": clf.coef_.astype(np.float32),
                 "intercept": clf.intercept_, "threshold": thr["f2"], "thresholds": thr}, out / "dinov2s_probe.joblib")
    res["deployed_probe"] = {"file": "outputs/drone/dinov2s_probe.joblib",
                             "thresholds": {k: round(v, 3) for k, v in thr.items()}}
    (out / "benchmark.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res["pooled"], ensure_ascii=False, indent=1))
    figure(root, examples, out)


def figure(root, examples, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cams = [c for c in CAMERAS if c in examples]
    fig, ax = plt.subplots(1, len(cams), figsize=(5.2 * len(cams), 3.4), dpi=150)
    ax = np.atleast_1d(ax)
    for a, c in zip(ax, cams, strict=True):
        stem, prob, thr = examples[c]
        rgb, m, _ = load(root / "images" / f"{stem}.jpg", root / "masks" / f"{stem}.png")
        a.imshow(rgb[: prob.shape[0], : prob.shape[1]])
        a.contour(m[: prob.shape[0], : prob.shape[1]], levels=[0.5], colors=["#FFFFFF"], linewidths=1.0)
        a.contourf(prob >= thr, levels=[0.5, 1.5], colors=["#E0A030"], alpha=0.45)
        a.set_title(f"{CAMERAS[c]}: камера не участвовала в обучении", fontsize=9)
        a.axis("off")
    fig.tight_layout()
    fig.savefig(Path(OUT) / "figures" / "drone_real.png", bbox_inches="tight")


if __name__ == "__main__":
    main(sys.argv[1])
