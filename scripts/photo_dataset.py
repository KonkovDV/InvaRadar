"""Download the first photo (medium, <=500 px) of each selected iNaturalist observation (open-licensed bucket).
Reads photo_obs.csv + photos_sel.tsv written by fetch_inat.py photos; writes data/photos/<group>/<photo_id>.jpg."""
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from invaradar.config import DATA, SCRATCH

src = SCRATCH / "inat"
obs = pd.read_csv(src / "photo_obs.csv")
ph = pd.read_csv(src / "photos_sel.tsv", sep="\t")
ph = ph.sort_values("position").drop_duplicates("observation_uuid")
m = obs.merge(ph[["observation_uuid", "photo_id", "extension", "license"]], on="observation_uuid")
out = DATA / "photos"; out.mkdir(parents=True, exist_ok=True)
m.to_csv(out / "index.csv", index=False)


def get(r):
    p = out / r.group / f"{r.photo_id}.jpg"
    if p.exists():
        return 1
    p.parent.mkdir(exist_ok=True)
    url = f"https://inaturalist-open-data.s3.amazonaws.com/photos/{r.photo_id}/medium.{r.extension}"
    for _ in range(3):
        try:
            p.write_bytes(urllib.request.urlopen(url, timeout=30).read()); return 1
        except Exception:
            pass
    return 0


with ThreadPoolExecutor(24) as ex:
    ok = sum(ex.map(get, m.itertuples()))
print("photos", ok, "of", len(m), m.group.value_counts().to_dict())
