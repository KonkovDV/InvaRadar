"""Схема для слайда «Дрон»: как модуль БПЛА видит снимок — сетка патчей и отмеченные патчи с соцветиями.

Слайд показывает схему на открытом снимке iNaturalist (CC BY, автор — в assets/CREDITS.csv). Кадры аэрофото в комплект не входят. Это иллюстрация принципа, а не результат модели:
патч отмечается по доле светлых малонасыщенных пикселей, как белые зонтики выглядят сверху.

    python make_drone_scheme.py assets/umbel_leaves.jpg assets/drone_patches.jpg
"""

import sys

import numpy as np
from PIL import Image, ImageDraw


def main(src: str, dst: str, cells: int = 16) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, int((h - side) * 0.25), (w - side) // 2 + side, int((h - side) * 0.25) + side))
    im = im.resize((1200, 1200), Image.LANCZOS)
    a = np.asarray(im).astype(float) / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    white = (mx > 0.78) & ((mx - mn) < 0.22)  # светлое и малонасыщенное — соцветия зонтика

    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    step = im.size[0] / cells
    for r in range(cells):
        for c in range(cells):
            y0, x0 = int(r * step), int(c * step)
            y1, x1 = int((r + 1) * step), int((c + 1) * step)
            if white[y0:y1, x0:x1].mean() > 0.12:
                d.rectangle([x0, y0, x1, y1], fill=(224, 160, 48, 120), outline=(224, 160, 48, 255), width=3)
    for i in range(cells + 1):
        p = int(i * step)
        d.line([(p, 0), (p, im.size[1])], fill=(255, 255, 255, 90), width=2)
        d.line([(0, p), (im.size[0], p)], fill=(255, 255, 255, 90), width=2)
    out = Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")
    out.save(dst, quality=88)
    print("written", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
