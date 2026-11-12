"""Проверка доказательств работ: место, время, повторное использование фото, пары «до/после», спутник.

Это оценка риска, а не криминалистика: EXIF можно подделать. Поэтому в промышленной версии
фото снимаются в приложении (время и координаты сервера, одноразовый код наряда в кадре),
а здесь проверяется то, что ловит самые частые нарушения: фото не с того места, не в срок,
одно фото на несколько очагов, «после» без изменений.

Персональные данные (152-ФЗ): после извлечения метаданных хранится копия без EXIF
(`strip_metadata`), в журнал пишется только SHA-256 исходного файла.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image

from .geo import haversine_m

# Пороги — по бенчмарку на 150 реальных фото борщевика (analysis/evidence_bench.py, docs/10 §5.6):
# у разных снимков похожих сцен минимальное расстояние — 22 бита для dHash и 16 для pHash.
# Строгий порог — автоматический отказ; порог проверки — кандидат на ручное сравнение.
DUP_HAMMING = 10        # dHash, строгий
REVIEW_DHASH = 18       # dHash, кандидат на проверку: ловит 100% безобидных пересылок в бенчмарке
REVIEW_PHASH = 14       # pHash, кандидат на проверку: 98,4%
MIN_VISUAL_CHANGE = 10  # «после» обязано заметно отличаться от «до»
GPS_TOL_M = 30.0        # погрешность GPS телефона в городе


@dataclass
class PhotoMeta:
    sha256: str
    lat: float | None
    lon: float | None
    taken_at: str | None
    make: str | None
    model: str | None
    dhash: int
    width: int
    height: int
    phash: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dhash"] = format(self.dhash, "016x")
        d["phash"] = format(self.phash, "016x")
        return d


@dataclass
class Check:
    name: str
    ok: bool | None   # None — проверить нельзя, решает человек
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def _num(v) -> float:
    try:
        return float(v)
    except TypeError:
        a, b = v
        return float(a) / float(b)


def _dms(v, ref) -> float | None:
    if not v:
        return None
    deg = _num(v[0]) + _num(v[1]) / 60.0 + _num(v[2]) / 3600.0
    return -deg if ref in ("S", "W") else deg


def dhash(img: Image.Image, size: int = 8) -> int:
    """Разностный перцептивный хеш: 64 бита, устойчив к пересжатию и масштабу."""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int(np.packbits(bits).tobytes().hex(), 16)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0] /= np.sqrt(2.0)
    return m


_DCT32 = _dct_matrix(32)
PHASH_DUP = 8   # pHash, строгий порог (бенчмарк: analysis/evidence_bench.py)


def phash(img: Image.Image) -> int:
    """Перцептивный хеш по DCT: 8 × 8 низших частот изображения 32 × 32, порог — медиана без постоянной составляющей.

    Устойчивее dHash к пересжатию, масштабу и яркости. Используется вместе с dHash.
    """
    g = np.asarray(img.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    low = (_DCT32 @ g @ _DCT32.T)[:8, :8].flatten()
    bits = low > np.median(low[1:])
    return int(np.packbits(bits).tobytes().hex(), 16)


def read_photo(src: str | Path | bytes) -> PhotoMeta:
    data = bytes(src) if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
    img = Image.open(io.BytesIO(data))
    img.load()
    exif = img.getexif()
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo) if exif else {}
    sub = exif.get_ifd(ExifTags.IFD.Exif) if exif else {}
    taken = None
    raw = sub.get(36867) or (exif.get(306) if exif else None)
    if raw:
        try:
            taken = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").isoformat()
        except ValueError:
            taken = None
    return PhotoMeta(sha256=hashlib.sha256(data).hexdigest(), lat=_dms(gps.get(2), gps.get(1)),
                     lon=_dms(gps.get(4), gps.get(3)), taken_at=taken,
                     make=exif.get(271) if exif else None, model=exif.get(272) if exif else None,
                     dhash=dhash(img), width=img.width, height=img.height, phash=phash(img))


def check_photo(meta: PhotoMeta, *, focus_lat: float, focus_lon: float, radius_m: float = 0.0,
                start: str | None = None, end: str | None = None, seen=(), tol_m: float = GPS_TOL_M) -> list[Check]:
    """seen — уже принятые фото других очагов и событий: [(dhash, sha256, ссылка[, phash]), ...]."""
    out: list[Check] = []
    if meta.lat is None or meta.lon is None:
        out.append(Check("gps", None, "в фото нет координат: нужна съёмка в приложении или ручная проверка"))
    else:
        d = haversine_m(meta.lat, meta.lon, focus_lat, focus_lon)
        lim = radius_m + tol_m
        out.append(Check("gps", bool(d <= lim), f"{d:.0f} м от центра очага при допуске {lim:.0f} м"))
    if meta.taken_at is None:
        out.append(Check("time", None, "нет времени съёмки"))
    else:
        t = meta.taken_at[:10]
        ok = (start is None or t >= start) and (end is None or t <= end)
        out.append(Check("time", bool(ok), f"снято {t}; окно {start or '…'} — {end or '…'}"))
    dup, near = [], []
    for item in seen:
        h, sha, ref = item[:3]
        ph = item[3] if len(item) > 3 else None
        dd = hamming(int(h), meta.dhash)
        dp = hamming(int(ph), meta.phash) if (ph is not None and meta.phash) else 64
        if sha == meta.sha256 or dd <= DUP_HAMMING or dp <= PHASH_DUP:
            dup.append(ref)
        elif dd <= REVIEW_DHASH or dp <= REVIEW_PHASH:
            near.append(ref)
    if dup:
        out.append(Check("unique", False, "совпадает с " + ", ".join(dup)))
    elif near:
        out.append(Check("unique", None, "похоже на " + ", ".join(near) + ": нужно сравнить снимки вручную"))
    else:
        out.append(Check("unique", True, "повторов не найдено"))
    return out


def check_pair(before: PhotoMeta, after: PhotoMeta, max_shift_m: float = GPS_TOL_M,
               min_change: int = MIN_VISUAL_CHANGE) -> list[Check]:
    out: list[Check] = []
    if before.taken_at and after.taken_at:
        out.append(Check("order", after.taken_at > before.taken_at, f"до {before.taken_at}, после {after.taken_at}"))
    else:
        out.append(Check("order", None, "нет времени съёмки у одного из фото"))
    if None not in (before.lat, before.lon, after.lat, after.lon):
        d = haversine_m(before.lat, before.lon, after.lat, after.lon)
        out.append(Check("same_place", bool(d <= max_shift_m), f"{d:.0f} м между точками съёмки"))
    else:
        out.append(Check("same_place", None, "нет координат у одного из фото"))
    h = hamming(before.dhash, after.dhash)
    out.append(Check("changed", True if h >= min_change else None, f"различие {h} из 64 бит"))
    return out


def satellite_did(before, after, inside, min_drop: float = 0.05) -> Check:
    """Разность разностей по индексу (белые зонтики, NDVI): очаг против окружения.

    Окружение снимает общий сезонный сдвиг и разницу освещения. Проверка только поддерживает
    решение и никогда не валит его сама: облака и фенология дают ложные сигналы.
    """
    b, a = np.asarray(before, float), np.asarray(after, float)
    m = np.asarray(inside, bool)
    if not m.any() or m.all():
        return Check("satellite", None, "нет пикселей очага или окружения")
    did = (np.nanmean(a[m]) - np.nanmean(b[m])) - (np.nanmean(a[~m]) - np.nanmean(b[~m]))
    return Check("satellite", True if did <= -min_drop else None, f"разность разностей {did:+.3f}, порог −{min_drop}")


def verdict(checks) -> str:
    if any(c.ok is False for c in checks):
        return "fail"
    if any(c.ok is None for c in checks):
        return "needs_review"
    return "pass"


def strip_metadata(data: bytes) -> bytes:
    """Копия без EXIF и прочих метаданных — для хранения и показа (152-ФЗ, минимизация)."""
    img = Image.open(io.BytesIO(data))
    img.load()
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _to_dms(v: float):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60, 4)
    return (float(d), float(m), float(s))


def synth_photo(lat: float | None, lon: float | None, when: datetime | None, seed: int, size=(96, 72)) -> bytes:
    """Синтетическое фото с EXIF — только для демо и тестов."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 256, (6, 8, 3), dtype=np.uint8)
    img = Image.fromarray(blocks).resize(size, Image.Resampling.NEAREST)
    ex = Image.Exif()
    ex[ExifTags.Base.Make] = "InvaRadarDemo"
    if lat is not None and lon is not None:
        ex[ExifTags.IFD.GPSInfo] = {1: "N" if lat >= 0 else "S", 2: _to_dms(lat),
                                    3: "E" if lon >= 0 else "W", 4: _to_dms(lon)}
    if when is not None:
        ex[ExifTags.IFD.Exif] = {36867: when.strftime("%Y:%m:%d %H:%M:%S")}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=ex.tobytes())
    return buf.getvalue()
