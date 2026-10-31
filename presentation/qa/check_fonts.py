"""Каждый текстовый фрагмент PPTX набран шрифтом, в котором есть все его символы.

    python qa/check_fonts.py InvaRadar_Ecopremia2026_podacha.pptx InvaRadar_Ecopremia2026.pptx

Символ, которого нет в заданном шрифте, LibreOffice и PowerPoint подставят из другого шрифта. В подаче это нарушает
требование Положения «только Arial, Calibri или Verdana», в полной версии — ломает фирменную типографику.
Шрифты ищутся в fonts/ рядом со скриптами, в ~/.local/share/fonts и /usr/share/fonts. Код выхода 1 при находке.
"""

import collections
import glob
import os
import re
import sys
import zipfile

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_FILES = (glob.glob(os.path.join(HERE, "..", "fonts", "*.ttf")) + glob.glob(os.path.expanduser("~/.local/share/fonts/*.ttf"))
              + glob.glob("/usr/share/fonts/truetype/*/*.ttf"))


def cmaps() -> dict:
    out = collections.defaultdict(set)
    for f in FONT_FILES:
        try:
            font = TTFont(f, lazy=True)
            names = {n.toUnicode() for n in font["name"].names if n.nameID in (1, 4, 16)}
            chars = set(font.getBestCmap())
        except Exception:  # noqa: BLE001 — битый или нестандартный файл просто пропускаем
            continue
        for name in names:
            out[name] |= chars
    return out


def check(pptx: str, cm: dict) -> int:
    missing = collections.defaultdict(set)
    z = zipfile.ZipFile(pptx)
    for part in z.namelist():
        if not re.match(r"ppt/slides/slide\d+\.xml$", part):
            continue
        slide = int(re.search(r"\d+", part.rsplit("/", 1)[-1]).group())
        for run in re.findall(r"<a:r>(.*?)</a:r>", z.read(part).decode("utf8"), re.S):
            face = re.search(r'<a:latin typeface="([^"]+)"', run)
            face = face.group(1) if face else "?"
            text = "".join(re.findall(r"<a:t>([^<]*)</a:t>", run))
            if not text.strip():
                continue
            if face not in cm:
                missing[(face, "шрифт не найден")].add(slide)
                continue
            for ch in text:
                if ord(ch) > 127 and ch != " " and ord(ch) not in cm[face]:
                    missing[(face, f"{ch!r} U+{ord(ch):04X}")].add(slide)
    for (face, what), slides in sorted(missing.items()):
        print(f"{pptx}: {face}: {what} — слайды {sorted(slides)}")
    print(f"{pptx}: проблем {len(missing)}")
    return len(missing)


if __name__ == "__main__":
    fonts = cmaps()
    sys.exit(1 if sum(check(p, fonts) for p in sys.argv[1:]) else 0)
