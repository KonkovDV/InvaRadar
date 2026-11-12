"""Эмбеддинги AlphaEarth Foundations в точках: прямое чтение публичных COG (CC BY 4.0) без GDAL.

Файл — BigTIFF 8192×8192, 64 канала int8, PlanarConfiguration = 2 (каждый канал отдельно),
плитки 1024×1024, сжатие ZSTD, привязка через ModelTransformationTag (ориентация «юг вверх»).
Для точки нужен вектор из 64 значений. Поэтому на каждый пространственный блок с точками читаются
64 плитки — параллельными запросами по диапазону байт. В кэше хранятся только векторы точек.

Деквантование — официальное: sign(v)·(v/127,5)²; −128 — нет данных.
"""
from __future__ import annotations

import math
import struct
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import zstandard

GCS = "https://storage.googleapis.com/alphaearth_foundations/"
NODATA = -128
_V = np.arange(-128, 128, dtype=np.float32)
LUT = (np.sign(_V) * (_V / 127.5) ** 2).astype(np.float32)


def dequantize(raw: np.ndarray) -> np.ndarray:
    return LUT[np.asarray(raw, dtype=np.int8).astype(np.int16) + 128]


class Cog:
    def __init__(self, url: str, session: requests.Session):
        self.url, self.s = url, session
        h = session.get(url, headers={"Range": "bytes=0-262143"}, timeout=120).content
        if h[:2] != b"II" or struct.unpack("<H", h[2:4])[0] != 43:
            raise ValueError("ожидался BigTIFF little-endian")
        off = struct.unpack("<Q", h[8:16])[0]
        n = struct.unpack("<Q", h[off:off + 8])[0]
        tags = {}
        for i in range(n):
            e = h[off + 8 + 20 * i: off + 28 + 20 * i]
            tag, typ, cnt = struct.unpack("<HHQ", e[:12])
            tags[tag] = (typ, cnt, e[12:20])

        def short(t):
            return struct.unpack("<H", tags[t][2][:2])[0]

        self.width, self.height = short(256), short(257)
        self.tw, self.th = short(322), short(323)
        self.bands = short(277)
        assert short(284) == 2 and short(259) == 50000, "ожидались отдельные каналы и ZSTD"
        o = struct.unpack("<Q", tags[324][2])[0]
        c = struct.unpack("<Q", tags[325][2])[0]
        ntiles = tags[324][1]
        self.offs = np.frombuffer(h[o:o + 8 * ntiles], dtype="<u8")
        cnt_type = tags[325][0]
        self.cnts = (np.frombuffer(h[c:c + 8 * ntiles], dtype="<u8") if cnt_type == 16
                     else np.frombuffer(h[c:c + 4 * ntiles], dtype="<u4")).astype(np.int64)
        mo = struct.unpack("<Q", tags[34264][2])[0]
        M = np.frombuffer(h[mo:mo + 128], dtype="<f8").reshape(4, 4)
        self.x0, self.dx, self.y0, self.dy = M[0, 3], M[0, 0], M[1, 3], M[1, 1]
        self.across = math.ceil(self.width / self.tw)
        self.down = math.ceil(self.height / self.th)

    def rowcol(self, x, y):
        col = np.floor((np.asarray(x) - self.x0) / self.dx).astype(np.int64)
        row = np.floor((np.asarray(y) - self.y0) / self.dy).astype(np.int64)
        ok = (col >= 0) & (col < self.width) & (row >= 0) & (row < self.height)
        return row, col, ok

    def _tile(self, band: int, br: int, bc: int) -> np.ndarray:
        i = band * self.across * self.down + br * self.across + bc
        a, n = int(self.offs[i]), int(self.cnts[i])
        for _attempt in range(6):
            try:
                raw = self.s.get(self.url, headers={"Range": f"bytes={a}-{a + n - 1}"}, timeout=180).content
                if len(raw) == n:
                    break
            except requests.RequestException:
                pass
        else:
            raise OSError(f"не скачалась плитка {i}")
        out = zstandard.ZstdDecompressor().decompress(raw, max_output_size=self.tw * self.th)
        return np.frombuffer(out, dtype=np.int8).reshape(self.th, self.tw)

    def read_points(self, rows, cols, threads: int = 32) -> np.ndarray:
        """Векторы (n, 64) int8 для точек одного файла; читаются только блоки, где есть точки."""
        out = np.full((len(rows), self.bands), NODATA, dtype=np.int8)
        br, bc = rows // self.th, cols // self.tw
        for key in sorted(set(zip(br.tolist(), bc.tolist()))):
            m = (br == key[0]) & (bc == key[1])
            r_in, c_in = rows[m] - key[0] * self.th, cols[m] - key[1] * self.tw
            with ThreadPoolExecutor(threads) as ex:
                tiles = list(ex.map(lambda b: self._tile(b, key[0], key[1]), range(self.bands)))
            out[m] = np.stack([t[r_in, c_in] for t in tiles], axis=1)
        return out


def embeddings_at(x, y, year: int, tiles: pd.DataFrame, crs: str = "EPSG:32637", threads: int = 32,
                  log=print) -> np.ndarray:
    """(n, 64) int8 для точек в UTM; −128 — нет данных или точка вне покрытия."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    out = np.full((len(x), 64), NODATA, dtype=np.int8)
    s = requests.Session()
    s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=threads, pool_maxsize=threads))
    sel = tiles[(tiles.year == year) & (tiles.crs == crs)]
    for _, t in sel.iterrows():
        url = GCS + t.path.split("gs://alphaearth_foundations/")[1]
        cog = Cog(url, s)
        rows, cols, ok = cog.rowcol(x, y)
        todo = ok & (out[:, 0] == NODATA)
        if todo.any():
            nb = len(set(zip((rows[todo] // cog.th).tolist(), (cols[todo] // cog.tw).tolist())))
            log(f"  {year}: файл {url.rsplit('/', 1)[-1]} — точек {int(todo.sum())}, блоков {nb}")
            out[todo] = cog.read_points(rows[todo], cols[todo], threads)
    return out
