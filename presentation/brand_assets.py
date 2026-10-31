"""Фирменные фоны презентаций в палитре Экологической премии Москвы (ecopremia.moscow).

Палитра снята с CSS сайта премии: изумрудный #00906A, мятный #2CA982, глубокий #00664C, фиолетовый #8968AA.
Логотипы и гербы не используются: презентация подаётся командой, а не от имени города.

* brand_cover.png  — изумрудный градиент с мягкими светлыми «лентами», как на главной сайта премии;
* brand_light.png  — едва заметная мятная дымка для светлых слайдов;
* overlay_left.png, overlay_bottom.png, fade_forest.png — те же альфа-градиенты, перекрашенные в глубокий изумрудный;
* contours_dark.png, umbel_light.png — перекраска уже нарисованных линий (горизонтали по ЦМР, зонтик) в мятный и белый.

    python brand_assets.py          # пишет в assets/
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

A = Path(__file__).resolve().parent / "assets"
DEEP = (0, 102, 76)        # #00664C
EMERALD = (0, 144, 106)    # #00906A
MINT = (44, 169, 130)      # #2CA982
LIGHT = (207, 239, 227)    # #CFEFE3
CREAM = (246, 245, 230)    # #F6F5E6


def ribbons(w, h, seed, strength):
    """Мягкие диагональные ленты: сумма гауссовых полос вдоль синусоид, размытая до «стекла»."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    xx /= w; yy /= h
    f = np.zeros((h, w))
    for _ in range(5):
        a, ph, amp, off, wid = rng.uniform(1.2, 2.6), rng.uniform(0, 6.3), rng.uniform(0.08, 0.22), rng.uniform(-0.2, 1.2), rng.uniform(0.04, 0.11)
        centre = off - 0.6 * xx + amp * np.sin(a * np.pi * xx + ph)
        f += np.exp(-((yy - centre) ** 2) / (2 * wid ** 2)) * rng.uniform(0.5, 1.0)
    f = np.clip(f / f.max(), 0, 1) ** 1.3 * strength
    return f


def cover(path, w=2000, h=1125):
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    t = np.clip(0.55 * xx / w + 0.45 * yy / h, 0, 1)[..., None]
    base = (1 - t) * np.array(EMERALD) + t * np.array(DEEP)
    rib = ribbons(w, h, 3, 0.55)[..., None]
    img = base * (1 - rib) + np.array(LIGHT) * rib
    im = Image.fromarray(img.astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(6))
    im.save(path, optimize=True)


def light(path, w=1600, h=900):
    rib = ribbons(w, h, 11, 0.22)[..., None]
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    glow = np.exp(-(((xx / w - 1.0) ** 2) / 0.10 + ((yy / h) ** 2) / 0.18))[..., None] * 0.18
    paper = np.array([248, 250, 246], float)
    img = paper * (1 - rib - glow) + np.array(LIGHT) * rib + np.array(CREAM) * glow
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(4)).save(path, quality=90)


def recolor_alpha(path, rgb):
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im)[..., 3]
    out = np.dstack([np.full(a.shape, c, np.uint8) for c in rgb] + [a])
    Image.fromarray(out, "RGBA").save(path, optimize=True)


def recolor_lines(path, rgb):
    """Линии на прозрачном фоне: цвет меняется, яркость штриха остаётся в альфе."""
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im)[..., 3]
    out = np.dstack([np.full(a.shape, c, np.uint8) for c in rgb] + [a])
    Image.fromarray(out, "RGBA").quantize(colors=48, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)


if __name__ == "__main__":
    cover(A / "brand_cover.png")
    light(A / "brand_light.jpg")
    for f in ("overlay_left.png", "overlay_bottom.png", "fade_forest.png"):
        recolor_alpha(A / f, DEEP)
    recolor_lines(A / "contours_dark.png", LIGHT)
    recolor_lines(A / "umbel_light.png", (255, 255, 255))
    print("brand assets written to", A)
