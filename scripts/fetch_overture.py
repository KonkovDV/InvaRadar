"""Fetch exposure (schools, kindergartens, hospitals, playgrounds, parks) and corridor layers
(roads, railways, rivers/streams, power lines) for the study area from Overture Maps."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pyarrow.compute as pc
from pyproj import Transformer
from invaradar import overture
from invaradar.config import DATA, EPSG, STUDY_BOX

tr = Transformer.from_crs(EPSG, 4326, always_xy=True)
w, s = tr.transform(STUDY_BOX[0], STUDY_BOX[1]); e, n = tr.transform(STUDY_BOX[2], STUDY_BOX[3])
bb = (w - 0.02, s - 0.02, e + 0.02, n + 0.02)
out = DATA / "overture"; out.mkdir(parents=True, exist_ok=True)

SENSITIVE = ["school", "elementary_school", "high_school", "middle_school", "preschool", "kindergarten",
             "child_care_and_day_care", "day_care_preschool", "hospital", "playground", "park", "college_university",
             "medical_center", "public_school", "private_school", "children_hospital", "dog_park", "campground",
             "community_center", "sports_club_and_league", "beach", "nature_reserve", "botanical_garden"]

jobs = {
    "places": ("places", "place", ["id", "names", "taxonomy", "basic_category", "geometry", "bbox"], None),
    "roads": ("transportation", "segment", ["id", "subtype", "class", "geometry", "bbox"],
              pc.field("subtype").isin(["road", "rail"])),
    "water": ("base", "water", ["id", "subtype", "class", "geometry", "bbox"], None),
    "infra": ("base", "infrastructure", ["id", "subtype", "class", "geometry", "bbox"],
              pc.field("class").isin(["power_line", "minor_line", "cable", "power_tower", "pylon"])),
    "landuse": ("base", "land_use", ["id", "subtype", "class", "geometry", "bbox"], None),
    # settlement boundaries (cities, towns, villages): СанПиН 2.1.3684-21 п. 282 measures aerial distances from them
    "settlements": ("divisions", "division_area", ["id", "subtype", "class", "names", "geometry", "bbox"],
                    pc.field("subtype") == "locality"),
}
for name in (sys.argv[1:] or jobs):
    theme, typ, cols, flt = jobs[name]
    t = time.time()
    tab = overture.read(theme, typ, bb, cols, flt)
    g = overture.to_gdf(tab).drop(columns=["bbox"])
    for c in g.columns:
        if g[c].dtype == object and c != "geometry":
            g[c] = g[c].astype(str)
    g.to_parquet(out / f"{name}.parquet")
    print(name, len(g), f"{time.time() - t:.0f}s", flush=True)
