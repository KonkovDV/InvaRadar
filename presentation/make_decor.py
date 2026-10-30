"""Decorative layers of the deck, drawn from project data rather than stock art:

* contours_dark.png — 5 m contour lines of Moscow from the project's Copernicus DEM (data/dem_10m.tif);
* umbel_light.png   — line drawing of a compound umbel of Heracleum (procedural);
* overlay_left.png, overlay_bottom.png — forest-green alpha gradients for text on photos (pptxgenjs has no
  gradient fills).
usage: python make_decor.py
"""
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]
A = Path(__file__).resolve().parent / "assets"
sys.path.insert(0, str(ROOT))
from invaradar.config import DATA  # noqa: E402


def save_quantized(fig, path, colors=64):
    fig.savefig(path, transparent=True)
    plt.close(fig)
    Image.open(path).quantize(colors=colors, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)


# contour lines of the study area
with rasterio.open(DATA / "dem_10m.tif") as ds:
    z = gaussian_filter(ds.read(1, out_shape=(1300, 1300)), 9)
fig = plt.figure(figsize=(9, 9), dpi=200)
ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
lv = np.arange(np.floor(z.min() / 5) * 5, z.max(), 5)
ax.contour(z[::-1], levels=lv[lv % 25 != 0], colors="#86A894", linewidths=0.5, alpha=0.5)
ax.contour(z[::-1], levels=lv[lv % 25 == 0], colors="#86A894", linewidths=1.1, alpha=0.7)
save_quantized(fig, A / "contours_dark.png")

# compound umbel
rng = np.random.default_rng(7)


def bez(p0, p1, p2, n=30):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2


color, lw = "#EDE8D6", 1.0
fig = plt.figure(figsize=(8.1, 9.45), dpi=200)
ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_aspect("equal")
t = np.linspace(0, 1, 60)
ax.plot(0.035 * np.sin(t * 2.2), -1.95 * t, color=color, lw=2.4, solid_capstyle="round")
for side in (0.22, 0.09):
    c = bez(np.array([0.03, -1.35]), np.array([side, -1.05]), np.array([0.05, -0.80]))
    ax.plot(c[:, 0], c[:, 1], color=color, lw=0.8)
apex = np.zeros(2)
n = 34
for a, L in zip(np.linspace(np.radians(16), np.radians(164), n) + rng.normal(0, 0.03, n),
                0.95 + 0.12 * np.sin(np.linspace(0, np.pi, n)) + rng.normal(0, 0.03, n)):
    end = apex + L * np.array([np.cos(a) * 1.15, np.sin(a) * 0.55 + 0.25])
    c = bez(apex, apex + 0.5 * L * np.array([np.cos(a) * 0.9, np.sin(a) * 0.6 + 0.2]), end, 24)
    ax.plot(c[:, 0], c[:, 1], color=color, lw=0.7, alpha=0.9)
    for a2 in np.linspace(np.radians(12), np.radians(168), 14) + rng.normal(0, 0.05, 14):
        f = end + (0.13 + rng.normal(0, 0.012)) * np.array([np.cos(a2), np.sin(a2) * 0.55 + 0.35])
        ax.plot([end[0], f[0]], [end[1], f[1]], color=color, lw=0.33, alpha=0.85)
        ax.add_patch(plt.Circle(f, 0.011, facecolor=color, edgecolor="none"))
ax.set_xlim(-1.35, 1.35); ax.set_ylim(-2.0, 1.15)
save_quantized(fig, A / "umbel_light.png", 48)


# gradients
def gradient(alpha, path):
    rgba = np.dstack([np.full(alpha.shape, 15, np.uint8), np.full(alpha.shape, 42, np.uint8),
                      np.full(alpha.shape, 34, np.uint8), (alpha * 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)


x = np.linspace(0, 1, 2000)
gradient(np.tile(np.where(x < 0.5, 0.97, np.clip(1 - (x - 0.5) / 0.42, 0, 1) ** 1.5 * 0.97), (1125, 1)),
         A / "overlay_left.png")
y = np.linspace(0, 1, 600)[:, None]
gradient(np.tile(np.clip((y - 0.35) / 0.65, 0, 1) ** 1.4 * 0.85, (1, 800)), A / "overlay_bottom.png")
print("decor written to", A)
