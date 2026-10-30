"""Project-wide paths and study-area constants.

Paths can be moved with environment variables, so the repository stays small and the large inputs
(AlphaEarth block cache, iNaturalist dumps) can live on another disk:
  INVARADAR_DATA     prepared inputs: DEM, Overture layers, photos (default ./data)
  INVARADAR_CACHE    downloaded raw data: AEF index and blocks, iNaturalist exports (default ./cache)
  INVARADAR_OUT      results (default ./outputs)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def core_binary() -> Path:
    """Path of the release binary. Cargo appends .exe on Windows."""
    name = "invaradar_core.exe" if sys.platform == "win32" else "invaradar_core"
    return ROOT / "core-rs" / "target" / "release" / name
DATA = Path(os.environ.get("INVARADAR_DATA", ROOT / "data"))
OUT = Path(os.environ.get("INVARADAR_OUT", ROOT / "outputs"))
SCRATCH = Path(os.environ.get("INVARADAR_CACHE", ROOT / "cache"))

AEF_INDEX = SCRATCH / "aef" / "aef_index.parquet"
AEF_CACHE = SCRATCH / "aef_cache"
INAT_OBS = SCRATCH / "inat" / "obs_region.tsv"
INAT_TAXA = SCRATCH / "inat" / "taxa.csv.gz"

EPSG = 32637  # WGS 84 / UTM 37N — Moscow
# Moscow (inside and around MKAD) + inner Moscow-oblast belt, UTM 37N metres: west, south, east, north
STUDY_BOX = (381000.0, 6147000.0, 446000.0, 6212000.0)

TAXA = {
    "heracleum": {"ids": [499936, 1557658, 130228], "ru": "Борщевик Сосновского (компл. H. mantegazzianum)"},
    "solidago": {"ids": [67808, 83073], "ru": "Золотарник канадский / гигантский"},
}

TERRAIN_FEATURES = ["elevation", "slope", "twi", "hand"]
