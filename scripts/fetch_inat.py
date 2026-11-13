"""iNaturalist open data (AWS Open Data bucket) → the files the pipeline needs, in $INVARADAR_CACHE/inat/.

* taxa.csv.gz       — taxonomy (to tell vascular plants from everything else);
* obs_region.tsv    — every observation in 53.5–57.5° N, 34.5–41.0° E plus all observations of the target taxa
                      anywhere (the national export is ~10 GB gzip, so it is streamed with resumable HTTP ranges and
                      filtered on the fly);
* photo_obs.csv, photos_sel.tsv — the sample for the citizen-photo verifier: research-grade observations of the two
                      invasive groups and their look-alikes, one per observer-day, and their photo records.
usage: fetch_inat.py [obs|photos|all]
"""
import os
import sys
import time
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from invaradar.config import INAT_OBS, INAT_TAXA, TAXA

BUCKET = "https://inaturalist-open-data.s3.amazonaws.com"
OUT = INAT_OBS.parent
TARGET = {str(i) for t in TAXA.values() for i in t["ids"]}
BOX = (53.5, 57.5, 34.5, 41.0)
CHUNK = 256 * 1024 * 1024

PHOTO_GROUPS = {
    "heracleum": [499936, 1557658, 130228],
    "solidago": [67808, 83073],
    "umbel_lookalike": [163682, 1455203, 158380, 124544, 51741, 59778, 52998, 76610, 62336, 55733, 485621, 57824,
                        765394, 1665961, 52821, 1105043, 63134],
    "yellow_lookalike": [118850, 55971, 54521, 62498, 56077, 53207],
}
PHOTO_CAP = {"heracleum": 3500, "solidago": 3500, "umbel_lookalike": 3500, "yellow_lookalike": 2500}


def _chunks(url):
    total = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60).headers["Content-Length"])
    pos = 0
    while pos < total:
        end = min(pos + CHUNK, total) - 1
        for attempt in range(8):
            try:
                req = urllib.request.Request(url, headers={"Range": f"bytes={pos}-{end}"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    while b := r.read(1 << 20):
                        pos += len(b)
                        yield b
                break
            except Exception as e:  # resume from the last byte received
                print("retry", pos, e, file=sys.stderr, flush=True)
                time.sleep(2 * (attempt + 1))
                end = min(pos + CHUNK, total) - 1
        print(f"  {url.rsplit('/', 1)[1]}: {pos / total:.1%}", flush=True)


def stream_filter(url, out, keep):
    """Decode a (multi-member) gzip CSV while downloading it and keep the header plus rows where keep(fields)."""
    d, buf, first, n, k = zlib.decompressobj(31), b"", True, 0, 0
    with open(f"{out}.part", "w") as fo:
        for b in _chunks(url):
            data = d.decompress(b)
            while d.unused_data:
                rest, d = d.unused_data, zlib.decompressobj(31)
                data += d.decompress(rest)
            *lines, buf = (buf + data).split(b"\n")
            for ln in lines:
                s = ln.decode("utf-8", "replace")
                if first:
                    fo.write(s + "\n"); first = False; continue
                n += 1
                if keep(s.split("\t")):
                    fo.write(s + "\n"); k += 1
    os.replace(f"{out}.part", out)
    print(f"{out}: kept {k} of {n} rows", flush=True)


def in_region(f):
    if len(f) < 6:
        return False
    if f[5] in TARGET:
        return True
    try:
        la, lo = float(f[2]), float(f[3])
    except ValueError:
        return False
    return BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]


def fetch_obs():
    OUT.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(f"{BUCKET}/taxa.csv.gz", INAT_TAXA)
    stream_filter(f"{BUCKET}/observations.csv.gz", INAT_OBS, in_region)


def fetch_photos():
    d = pd.read_csv(INAT_OBS, sep="\t", dtype={"taxon_id": "Int64"}, on_bad_lines="skip")
    d = d[d.quality_grade == "research"].dropna(subset=["taxon_id"])
    t = d.taxon_id.astype(int)
    rows = []
    for g, ids in PHOTO_GROUPS.items():
        x = d[t.isin(ids)].drop_duplicates(["observer_id", "observed_on", "taxon_id"])
        x = x.sample(min(PHOTO_CAP[g], len(x)), random_state=0)
        rows.append(x.assign(group=g)[["observation_uuid", "observer_id", "taxon_id", "latitude", "longitude",
                                       "observed_on", "group"]])
    r = pd.concat(rows)
    r.to_csv(OUT / "photo_obs.csv", index=False)
    ids = set(r.observation_uuid)
    stream_filter(f"{BUCKET}/photos.csv.gz", OUT / "photos_sel.tsv", lambda f: len(f) > 2 and f[2] in ids)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("obs", "all"):
        fetch_obs()
    if what in ("photos", "all"):
        fetch_photos()


if __name__ == "__main__":
    main()
