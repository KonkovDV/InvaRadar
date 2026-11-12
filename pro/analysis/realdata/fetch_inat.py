"""Находки iNaturalist для ретро-прогноза: целевые виды и фон целевой группы (другие сосудистые).

Фильтры, как в InvaRadar:
- только исследовательский уровень;
- открытая геоприватность (без загрублённых координат);
- точность координат ≤ 50 м (проверяется при анализе).

Логины наблюдателей не сохраняются. Запросы — не чаще 1 в секунду, по возрастанию id.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

API = "https://api.inaturalist.org/v1/observations"
TARGETS = {"heracleum": "499936,1557658,130228", "solidago": "67808,83073"}
TRACHEOPHYTA = "211194"


def fetch(params: dict, max_n: int | None = None, pause: float = 1.0, log=print) -> pd.DataFrame:
    rows, last = [], 0
    s = requests.Session()
    s.headers["User-Agent"] = "invaradar-pro-research/0.3"
    while True:
        p = {**params, "quality_grade": "research", "geoprivacy": "open", "taxon_geoprivacy": "open",
             "order_by": "id", "order": "asc", "per_page": 200, "id_above": last}
        for attempt in range(8):
            r = s.get(API, params=p, timeout=120)
            if r.status_code == 200:
                break
            time.sleep(min(60, 2 ** attempt))
        else:
            raise OSError(f"iNaturalist API: {r.status_code}")
        res = r.json().get("results", [])
        if not res:
            break
        for o in res:
            loc = o.get("location")
            if not loc:
                continue
            lat, lon = (float(v) for v in loc.split(","))
            rows.append({"id": o["id"], "observed_on": o.get("observed_on"), "lat": lat, "lon": lon,
                         "acc": o.get("positional_accuracy"), "taxon_id": (o.get("taxon") or {}).get("id")})
        last = res[-1]["id"]
        if max_n and len(rows) >= max_n:
            break
        time.sleep(pause)
    log(f"  получено {len(rows)}")
    return pd.DataFrame(rows)


def fetch_all(bbox: tuple[float, float, float, float], cache: Path, log=print) -> dict[str, pd.DataFrame]:
    """bbox = (южная широта, западная долгота, северная широта, восточная долгота)."""
    cache.mkdir(parents=True, exist_ok=True)
    geo = {"swlat": bbox[0], "swlng": bbox[1], "nelat": bbox[2], "nelng": bbox[3]}
    out = {}
    jobs = {name: {"taxon_id": ids} for name, ids in TARGETS.items()}
    excl = ",".join(TARGETS.values())
    for y in range(2014, 2025):  # фон до 2024 года включительно: до 3 000 в год
        jobs[f"bg_{y}"] = ({"taxon_id": TRACHEOPHYTA, "without_taxon_id": excl, "year": y}, 3000)
    for y in (2025, 2026):  # фон новых лет — для проверки, ограничено ли распространение расстоянием
        jobs[f"bg_{y}"] = ({"taxon_id": TRACHEOPHYTA, "without_taxon_id": excl, "year": y}, 6000)
    for name, spec in jobs.items():
        f = cache / f"inat_{name}.parquet"
        if f.exists():
            out[name] = pd.read_parquet(f)
            continue
        params, max_n = (spec, None) if isinstance(spec, dict) else spec
        log(f"iNaturalist: {name}")
        df = fetch({**params, **geo}, max_n=max_n, log=log)
        df.to_parquet(f)
        out[name] = df
    return out
