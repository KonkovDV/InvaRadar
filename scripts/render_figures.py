"""Scientific figures for the deck and the docs (after pipeline.py and enrich.py):

* terrain_hand_twi.png   — HAND and TWI over a hillshade, Moskva valley near Kolomenskoye (12 × 9 km)
* aoa_heracleum.png      — dissimilarity index and the area of applicability of the Heracleum model
* validation_design.png  — the 250 stratified field-validation points over the likelihood strata
usage: render_figures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LightSource, LinearSegmentedColormap, ListedColormap

from invaradar.config import DATA, OUT, STUDY_BOX
from invaradar.style import FOREST, HOT, INK, MOSS, MUTED, PAPER, RUST, scale_bar, use_fonts


def main():
    use_fonts()
    fig_dir = OUT / "figures"
    fig_dir.mkdir(exist_ok=True)
    w, s, e, n = STUDY_BOX


    def clean(ax):
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)


    # ---------------- terrain: HAND and TWI
    H = W = 6500
    T = np.memmap(DATA / "dem_10m.f32.terrain-v2.f32", dtype="<f4", mode="r", shape=(H, W, 4))
    r0, c0, h, wd = 3600, 3300, 900, 1200
    z = np.array(T[r0:r0 + h, c0:c0 + wd, 0])
    twi = np.array(T[r0:r0 + h, c0:c0 + wd, 2])
    hand = np.array(T[r0:r0 + h, c0:c0 + wd, 3])
    hs = LightSource(azdeg=315, altdeg=40).hillshade(z, vert_exag=3, dx=10, dy=10)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), dpi=220)
    fig.patch.set_facecolor(PAPER)
    cm_hand = LinearSegmentedColormap.from_list("hand", ["#1F5F86", "#6FA3BF", "#DCE6DF", PAPER])
    cm_twi = LinearSegmentedColormap.from_list("twi", [PAPER, "#B7CFC0", MOSS, FOREST])
    for ax, data, cm, vmin, vmax, title in [(axes[0], hand, cm_hand, 0, 25, "HAND, м — высота над ближайшим водотоком"),
                                             (axes[1], twi, cm_twi, 4, 14, "TWI = ln(a / tg $\\beta$) — где копится влага")]:
        ax.imshow(hs, cmap="gray", vmin=0, vmax=1, extent=(0, wd * 10, 0, h * 10))
        im = ax.imshow(data, cmap=cm, vmin=vmin, vmax=vmax, alpha=0.72, extent=(0, wd * 10, 0, h * 10))
        clean(ax)
        ax.set_title(title, loc="left", fontsize=12.5, color=INK, pad=8)
        cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.015)
        cb.outline.set_visible(False)
        cb.ax.tick_params(labelsize=9, colors=MUTED)
        scale_bar(ax, 400, 500, 2000, "2 км")
    plt.tight_layout()
    fig.savefig(fig_dir / "terrain_hand_twi.png", facecolor=PAPER)
    plt.close(fig)

    # ---------------- AOA (Meyer & Pebesma 2021)
    with rasterio.open(OUT / "heracleum" / "dissimilarity_index_100m.tif") as ds:
        di = ds.read(1)
        thr = float(ds.tags()["aoa_threshold"])
    _ = json.load(open(OUT / "heracleum" / "enrich_summary.json"))["aoa"]
    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=220)
    fig.patch.set_facecolor(PAPER)
    cm_di = LinearSegmentedColormap.from_list("di", [PAPER, "#C9D9CE", "#7FA08C", MOSS])
    im = ax.imshow(np.ma.masked_invalid(np.minimum(di, thr)), cmap=cm_di, vmin=0, vmax=thr, extent=(w, e, s, n))
    out = np.ma.masked_where(~(di > thr), np.ones_like(di))
    ax.imshow(out, cmap=ListedColormap([RUST]), extent=(w, e, s, n), interpolation="nearest")
    clean(ax)
    scale_bar(ax, w + 2500, s + 2500, 10000, "10 км")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.015, ticks=[0, thr / 2, thr])
    cb.ax.set_yticklabels(["0", f"{thr / 2:.2f}", f"{thr:.2f} = порог"])
    cb.outline.set_visible(False); cb.ax.tick_params(labelsize=9, colors=MUTED)
    fig.savefig(fig_dir / "aoa_heracleum.png", bbox_inches="tight", pad_inches=0.05, facecolor=PAPER)
    plt.close(fig)

    # ---------------- stratified validation design (Olofsson et al. 2014)
    with rasterio.open(OUT / "heracleum" / "likelihood_2025.tif") as ds:
        a = ds.read(1, out_shape=(1625, 1625))
    v = np.where(a == 255, np.nan, a / 250.0)
    strata = np.digitize(v, [0.80, 0.95, 0.98])
    V = pd.read_csv(OUT / "heracleum" / "validation_sample.csv")
    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=220)
    fig.patch.set_facecolor(PAPER)
    cm_st = ListedColormap(["#EEF2EC", HOT[0], HOT[1], HOT[3]])
    ax.imshow(np.ma.masked_where(np.isnan(v), strata), cmap=cm_st, vmin=-0.5, vmax=3.5, extent=(w, e, s, n),
              interpolation="nearest")
    marks = {0: ("o", MUTED), 1: ("o", "#9A6512"), 2: ("D", RUST), 3: ("D", INK)}
    for k, (mk, col) in marks.items():
        q = V[V.stratum == k]
        ax.scatter(q.x, q.y, s=16, marker=mk, c=col, edgecolors="white", linewidths=0.5, zorder=5)
    clean(ax)
    scale_bar(ax, w + 2500, s + 2500, 10000, "10 км")
    fig.savefig(fig_dir / "validation_design.png", bbox_inches="tight", pad_inches=0.05, facecolor=PAPER)
    plt.close(fig)
    print("figures written to", fig_dir)

    # ---------------- UAV module on the synthetic 3 cm orthomosaic of tests/test_drone.py
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_drone import make_ortho  # noqa: E402

    from invaradar.drone import BloomIndexSegmenter, polygonize, segment_orthomosaic, spray_mission  # noqa: E402

    with tempfile.TemporaryDirectory() as td:
        ortho = Path(td) / "ortho.tif"
        _, gsd = make_ortho(str(ortho))
        prob, tr, crs = segment_orthomosaic(str(ortho), BloomIndexSegmenter("heracleum", gsd), tile=512, overlap=64)
        polys = polygonize(prob, tr, crs, thr=0.5, min_area_m2=2.0)
        plan, stats = spray_mission(polys)
        with rasterio.open(ortho) as ds:
            rgb = ds.read().transpose(1, 2, 0)
            b = ds.bounds
    fig, ax = plt.subplots(figsize=(7, 7), dpi=200)
    fig.patch.set_facecolor(PAPER)
    ax.imshow(rgb, extent=(b.left, b.right, b.bottom, b.top))
    polys.boundary.plot(ax=ax, color="#E0A030", lw=2.2)
    plan.plot(ax=ax, color="#F4F6F1", lw=0.9, alpha=0.95)
    ax.set_xlim(b.left, b.right); ax.set_ylim(b.bottom, b.top); clean(ax)
    scale_bar(ax, b.left + 2, b.bottom + 2, 10, "10 м", color="#F4F6F1")
    fig.savefig(fig_dir / "drone_demo.png", bbox_inches="tight", pad_inches=0, facecolor=PAPER)
    plt.close(fig)
    json.dump({"note": "эскиз на ортофотоплане из tests/test_drone.py, не аэрофото Сколтеха",
               "stands_found": int(len(polys)), "area_m2": round(float(polys.area_m2.sum()), 1), **stats},
              open(fig_dir / "drone_demo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("drone demo", stats)


if __name__ == "__main__":
    main()
