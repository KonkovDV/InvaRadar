"""Коллизии текста в PDF: слова разных строк, которые наезжают друг на друга, и текст за краем листа.

    python qa/check_collisions.py InvaRadar_Ecopremia2026_podacha.pdf InvaRadar_Ecopremia2026.pdf

Основан на pdftotext -bbox-layout (poppler-utils). Сравниваются отдельные слова, а не строки целиком:
так число слева и подпись справа в одной строке таблицы не считаются наложением.
Код выхода 1, если найдена хотя бы одна проблема.
"""

import html
import re
import subprocess
import sys

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
LINE = re.compile(r'<line xMin="[\d.]+" yMin="[\d.]+" xMax="[\d.]+" yMax="[\d.]+">(.*?)</line>', re.S)


def lines_of(page: str):
    for m in LINE.finditer(page):
        words = [(float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in WORD.findall(m.group(1))]
        if words:
            yield words


def overlap(a, b) -> float:
    """Высота наложения двух слов, если они пересекаются заметно (больше трети высоты меньшего)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix > 0.5 and iy > 0.3 * min(a[3] - a[1], b[3] - b[1]):
        return iy
    return 0.0


def check(pdf: str) -> int:
    xml = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    bad = 0
    for n, page in enumerate(xml.split("<page ")[1:], 1):
        w = float(re.search(r'width="([\d.]+)"', page).group(1))
        h = float(re.search(r'height="([\d.]+)"', page).group(1))
        lines = list(lines_of(page))
        for words in lines:
            text = " ".join(x[4] for x in words)
            if min(x[0] for x in words) < 1 or min(x[1] for x in words) < 1 or \
                    max(x[2] for x in words) > w - 1 or max(x[3] for x in words) > h - 1:
                print(f"{pdf} с. {n}: текст за краем листа: {text[:70]!r}")
                bad += 1
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                hit = next(((overlap(wa, wb), wa[4], wb[4]) for wa in a for wb in b if overlap(wa, wb)), None)
                if hit:
                    print(f"{pdf} с. {n}: слова наезжают на {hit[0]:.1f} pt: {hit[1]!r} × {hit[2]!r}")
                    bad += 1
    print(f"{pdf}: проблем {bad}")
    return bad


if __name__ == "__main__":
    sys.exit(1 if sum(check(p) for p in sys.argv[1:]) else 0)
