"""Download the first photo (medium, <=500 px) of each selected iNaturalist observation.

Reads photo_obs.csv + photos_sel.tsv written by fetch_inat.py photos and writes
data/photos/<group>/<photo_id>.jpg. Only CC0 and CC BY are kept (audit I-03):
CC BY-NC, ND and SA photos are not training data for a model a city can ship.
"""
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from invaradar.config import DATA, SCRATCH
from invaradar.photo_license import commercial_photo_license


def select_commercial(obs: pd.DataFrame, photos: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """One photo per observation, restricted to CC0 and CC BY. Returns (rows, dropped)."""
    ph = photos.sort_values("position").drop_duplicates("observation_uuid")
    merged = obs.merge(ph[["observation_uuid", "photo_id", "extension", "license"]], on="observation_uuid")
    keep = merged["license"].map(commercial_photo_license)
    return merged.loc[keep].reset_index(drop=True), int((~keep).sum())


def main() -> None:
    src = SCRATCH / "inat"
    obs = pd.read_csv(src / "photo_obs.csv")
    ph = pd.read_csv(src / "photos_sel.tsv", sep="\t")
    chosen, dropped = select_commercial(obs, ph)
    out = DATA / "photos"
    out.mkdir(parents=True, exist_ok=True)
    chosen.to_csv(out / "index.csv", index=False)
    print("license filter kept", len(chosen), "dropped", dropped)

    def get(r):
        p = out / r.group / f"{r.photo_id}.jpg"
        if p.exists():
            return 1
        p.parent.mkdir(exist_ok=True)
        url = f"https://inaturalist-open-data.s3.amazonaws.com/photos/{r.photo_id}/medium.{r.extension}"
        for _ in range(3):
            try:
                p.write_bytes(urllib.request.urlopen(url, timeout=30).read())
                return 1
            except Exception:
                pass
        return 0

    with ThreadPoolExecutor(24) as ex:
        ok = sum(ex.map(get, chosen.itertuples()))
    print("photos", ok, "of", len(chosen), chosen.group.value_counts().to_dict())


if __name__ == "__main__":
    main()
