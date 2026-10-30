"""Treatment prescriptions per hotspot: biology of the species × legal constraints × cultural heritage.

Every rule cites its basis (wording checked on 30.10.2026: Water Code as amended 04.08.2026, СанПиН 2.1.3684-21 as
amended by Resolution No. 2 of the Chief Sanitary Doctor of 12.02.2026, in force from 10.03.2026). The prescription
is advisory: a person signs the work order.

* Water protection zones (Water Code of the Russian Federation, art. 65). Inside them both aerial measures against
  harmful organisms (part 15, item 3) and any application of pesticides and agrochemicals (part 15, item 6) are
  prohibited; СанПиН 2.1.3684-21 item 273(2) repeats the pesticide ban. Inside a zone only mechanical methods are
  allowed. Width depends on the water body:
    - rivers and streams by length from source to mouth (part 4): < 10 km → 50 m, 10–50 km → 100 m, ≥ 50 km → 200 m;
      the length of the connected river network inside the study area is used as a lower bound, so long rivers
      such as the Moskva get 200 m and the Yauza or Setun 100 m;
    - lakes and reservoirs (part 6): 50 m, except water bodies smaller than 0.5 km², which have no zone of their own
      unless they are part of a river;
    - sources of rivers and streams (part 5): 50 m radius; technical water (pools, wastewater, sewage basins) has no
      zone; rivers in closed collectors have no zone (part 10) — not modelled, so the rule errs on the safe side.
  Production should replace this with the State Water Register and the zone boundaries approved for Moscow.
* Aerial application of pesticides keeps at least 2 km (manned aircraft) or 700 m (unmanned aircraft systems) from
  settlements, drinking-water sources, nature reserves, national parks, zakazniks and fishery water bodies
  (СанПиН 2.1.3684-21 item 282). A hotspot inside a settlement is at distance 0. Inside settlements green spaces
  are treated with ground boom or knapsack sprayers only (item 273(3)). So in Moscow the drone finds and outlines
  stands, and a ground crew treats them. Settlements: locality boundaries plus residential land use
  (invaradar.layers); water bodies with a protection zone stand in for fishery water bodies.
* Ground application: residents are notified through the media at least 5 calendar days ahead, warning signs stand at
  the entrances (item 272); inside settlements spot treatment runs before 7:00 or after 22:00 in calm weather
  (item 273(4)). The work order carries these conditions.
* Children: pesticides are banned on the territories of children's organisations (СанПиН item 273(2));
  playgrounds and anything within 100 m of a kindergarten, school or playground are a precaution of this system,
  not a statutory distance → no pesticides, first in the queue.
* Protected natural areas: ООПТ regimes restrict chemicals, and Mosprirodа mows Heracleum on Moscow's ООПТ up to
  10 times a season → mechanical methods only. Parks get the same treatment as a precaution of this system. Proxy
  here: Overture parks, natural monuments and nature reserves; production uses the official ООПТ layer.
* Cultural heritage within 50 m: earthworks need heritage clearance (Federal Law 73-ФЗ) → no digging of root
  collars or rhizomes; cutting, umbel removal or covering instead.

Biology:
* Heracleum sosnowskyi flowers once and dies after seeding, so cutting the root collar 5–10 cm below ground kills
  the plant (manual work, practical for small stands; stands above ~0.5 ha get repeated mowing every 3–4 weeks
  instead, with root-collar cutting at the edges); removing umbels before seed set (by late July) stops the seed rain; most seeds germinate the next
  spring and a few per cent survive 2–3 years, while mown rosettes postpone flowering → 5 seasons of follow-up.
* Solidago spreads by rhizomes: mowing twice a season (late May–June and before flowering in August) depletes them
  over several years; seed heads must be removed before September.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np

from .layers import child_facilities, child_organisations, settlements

CHILD_M = 100.0
AERIAL_UAV_M = 700.0          # СанПиН 2.1.3684-21 item 282 for unmanned aircraft systems (since 10.03.2026)
AERIAL_MANNED_M = 2000.0      # the same item for manned aircraft; kept for reference, the system plans drones only
HERITAGE_M = 50.0
LARGE_STAND_M2 = 5_000.0      # above ~0.5 ha manual root-collar cutting is impractical: repeated mowing instead
RESERVE_M = 200.0
LAKE_MIN_KM2 = 0.5
CONNECT_M = 30.0

RIVER_LINES = {"river"}
SMALL_LINES = {"stream", "canal", "ditch", "drain"}
STANDING = {"lake", "reservoir", "pond", "oxbow", "water", "bay", "lagoon", "river", "canal", "stream", "moat"}
NO_ZONE = {"swimming_pool", "reflecting_pool", "wastewater", "sewage", "basin", "water_storage", "fountain"}

PROTECTED_LANDUSE = {"park", "natural_monument", "nature_reserve", "protected_area", "national_park"}
RESERVE_PLACES = {"nature_reserve", "national_park"}
HERITAGE_PLACES = {"historic_site", "monument"}


def river_width_m(length_m: float) -> float:
    """Water Code art. 65 part 4."""
    if length_m >= 50_000:
        return 200.0
    if length_m >= 10_000:
        return 100.0
    return 50.0


def watercourse_lengths(lines: gpd.GeoDataFrame) -> np.ndarray:
    """Length (m) of the watercourse each line belongs to.

    OSM-derived waterways are digitised in the direction of flow, so lines form a directed network. At every
    confluence the incoming branch with the longest path to its source continues the main stem (Hack's rule of
    thumb); the others end there as tributaries. A watercourse is a chain of segments joined this way, and every
    segment gets the total length of its chain. Rivers cut by the study-area edge get a lower bound.
    """
    from shapely import get_coordinates

    key = lambda xy: (round(float(xy[0])), round(float(xy[1])))  # 1 m snapping
    heads, tails, length = [], [], lines.length.to_numpy()
    for geom in lines.geometry:
        parts = list(getattr(geom, "geoms", [geom]))
        heads.append(key(get_coordinates(parts[0])[0]))
        tails.append(key(get_coordinates(parts[-1])[-1]))
    n = len(heads)
    into: dict = {}
    for e in range(n):
        into.setdefault(tails[e], []).append(e)
    up = np.full(n, -1.0)  # longest path from a source to the end of each segment

    def longest(e: int, seen: set) -> float:
        if up[e] >= 0:
            return up[e]
        # Pop the path on the way back: a source shared by two branches must stay visible to both.
        seen.add(e)
        try:
            prev = [longest(f, seen) for f in into.get(heads[e], []) if f not in seen]
            up[e] = length[e] + (max(prev) if prev else 0.0)
            return up[e]
        finally:
            seen.discard(e)

    import sys
    sys.setrecursionlimit(max(10_000, 4 * n))
    for e in range(n):
        longest(e, set())
    main_in = {node: max(es, key=lambda f: up[f]) for node, es in into.items()}
    out_of: dict = {}
    for e in range(n):
        out_of.setdefault(heads[e], []).append(e)
    # follow each segment downstream while it is the main stem at the next confluence
    nxt = np.full(n, -1)
    for e in range(n):
        if main_in.get(tails[e]) == e:
            down = out_of.get(tails[e], [])
            if down:
                nxt[e] = max(down, key=lambda f: length[f])
    has_parent = np.zeros(n, bool)
    has_parent[nxt[nxt >= 0]] = True
    total = np.zeros(n)
    done = np.zeros(n, bool)
    for start in list(np.where(~has_parent)[0]) + list(range(n)):
        if done[start]:
            continue
        chain, e = [], start
        while e >= 0 and not done[e] and e not in chain:
            chain.append(e)
            e = nxt[e]
        total[chain] = length[chain].sum() + (total[e] if e >= 0 and done[e] else 0.0)
        done[chain] = True
    return total


def water_zones(water: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    """Water features with the statutory zone width in metres (`zone_m`, 0 = no zone of its own)."""
    w = water.to_crs(crs).reset_index(drop=True)
    cls = w["class"].astype(str)
    is_line = w.geom_type.str.contains("Line")
    zone = np.zeros(len(w))

    # rivers: each watercourse traced along the network, width from its length
    riv = w[is_line & cls.isin(RIVER_LINES)]
    if len(riv):
        lengths = watercourse_lengths(riv)
        zone[riv.index.to_numpy()] = [river_width_m(x) for x in lengths]

    zone[(is_line & cls.isin(SMALL_LINES)).to_numpy()] = 50.0
    zone[((w.geom_type == "Point") & (cls == "spring")).to_numpy()] = 50.0

    # standing water and river areas: a river's width if connected to it, 50 m for lakes ≥ 0.5 km², else none
    poly = w.geom_type.str.contains("Polygon") & cls.isin(STANDING) & ~cls.isin(NO_ZONE)
    if poly.any():
        P = w[poly]
        lake = (P.area / 1e6 >= LAKE_MIN_KM2).to_numpy()
        zone[P.index.to_numpy()[lake]] = 50.0
        lines = w[is_line & (zone > 0)].assign(zone_m=zone[(is_line & (zone > 0)).to_numpy()])
        if len(lines):
            near = gpd.sjoin_nearest(P[["geometry"]], lines[["geometry", "zone_m"]], max_distance=CONNECT_M)
            best = near.groupby(level=0)["zone_m"].max()
            zone[best.index.to_numpy()] = np.maximum(zone[best.index.to_numpy()], best.to_numpy())
    return w.assign(zone_m=zone)


def _near(g: gpd.GeoDataFrame, layer: gpd.GeoDataFrame | None, dist: float) -> np.ndarray:
    if layer is None or len(layer) == 0:
        return np.zeros(len(g), bool)
    lay = layer.to_crs(g.crs)
    j = gpd.sjoin_nearest(g[["geometry"]].reset_index(), lay[["geometry"]], how="left", distance_col="d",
                          max_distance=max(dist, 0.01))
    hit = j.dropna(subset=["d"]).groupby("index").size()
    out = np.zeros(len(g), bool)
    out[hit.index.to_numpy()] = True
    return out


def prescribe(h: gpd.GeoDataFrame, taxon: str, water, landuse, places, localities=None) -> gpd.GeoDataFrame:
    g = h.reset_index(drop=True).copy()
    lu_cls = landuse["class"].astype(str)
    pc = places["basic_category"].astype(str)
    protected = landuse[lu_cls.isin(PROTECTED_LANDUSE)]
    reserves = places[pc.isin(RESERVE_PLACES)]
    heritage = places[pc.isin(HERITAGE_PLACES)]

    wz = water_zones(water, g.crs)
    zone_hit = np.zeros(len(g))
    for width in sorted(set(wz.zone_m[wz.zone_m > 0])):
        inside = _near(g, wz[wz.zone_m == width], width)
        zone_hit[inside] = np.maximum(zone_hit[inside], width)
    g["water_zone_m"] = zone_hit
    g["in_water_zone"] = zone_hit > 0
    g["in_protected"] = _near(g, protected, 0.0) | _near(g, reserves, RESERVE_M)
    g["child_org_territory"] = _near(g, child_organisations(landuse, g.crs), 0.0)
    g["near_children"] = _near(g, child_facilities(places, landuse, g.crs), CHILD_M)
    g["near_heritage"] = _near(g, heritage, HERITAGE_M)
    g["in_settlement"] = _near(g, settlements(landuse, localities, g.crs), 0.0)
    g["near_settlement_uav"] = _near(g, settlements(landuse, localities, g.crs), AERIAL_UAV_M)
    g["near_reserve_or_water_uav"] = _near(g, reserves, AERIAL_UAV_M) | _near(g, wz[wz.zone_m > 0], AERIAL_UAV_M)

    methods, basis = [], []
    for r in g.itertuples():
        b = []
        chem_ok = not (r.in_water_zone or r.in_protected or r.near_children)
        aerial_ok = chem_ok and not (r.near_settlement_uav or r.near_reserve_or_water_uav)
        dig_ok = not r.near_heritage
        if r.in_water_zone:
            b.append(f"ВК РФ ст. 65 ч. 15 п. 3 и 6: водоохранная зона {r.water_zone_m:.0f} м, пестициды и авиаобработка "
                     "запрещены")
        if r.child_org_territory:
            b.append("СанПиН 2.1.3684-21 п. 273: территория детской организации, пестициды запрещены")
        elif r.near_children:
            b.append("дети ≤100 м: без пестицидов (правило осторожности системы), первым в очереди")
        if r.in_protected:
            b.append("ООПТ / парк: только механические методы")
        if chem_ok and not aerial_ok:
            where = "в населённом пункте" if r.in_settlement else "ближе 700 м к жилью, водоёму или ООПТ"
            b.append(f"СанПиН 2.1.3684-21 п. 282, 273: {where} обработка с дрона запрещена, только наземная")
        if r.near_heritage:
            b.append("73-ФЗ: без земляных работ")
        ground = ("наземная точечная обработка ранцевым опрыскивателем по контуру очага (СанПиН п. 272–273: "
                  "оповещение за 5 дней, знаки, до 7 или после 22 ч в безветрие); ")
        large = getattr(r, "area_m2", 0.0) >= LARGE_STAND_M2
        if taxon == "heracleum":
            if large:
                m = ("многократный покос каждые 3–4 недели с мая по сентябрь, зонтики срезать и вывезти до конца июля"
                     + ("; подрезка корневой шейки на краях очага и в малых куртинах" if dig_ok else "; без перекопки"))
            elif dig_ok:
                m = "подрезка корневой шейки на 5–10 см ниже земли + удаление зонтиков до конца июля"
            else:
                m = "удаление зонтиков до конца июля + укрывной материал, без перекопки"
            if aerial_ok:
                m = "точечное опрыскивание с дрона по контурам (СанПиН п. 282–286); " + m
            elif chem_ok:
                m = ground + m
        else:
            m = "покос дважды: конец мая–июнь и до цветения в августе; удаление соцветий до сентября"
            if dig_ok:
                m += "; выборка корневищ на малых куртинах"
            if aerial_ok:
                m = "точечная обработка по контурам (с дрона допустимо, СанПиН п. 282–286); " + m
            elif chem_ok:
                m = "при необходимости " + ground + m
        methods.append(m)
        basis.append("; ".join(b) if b else "ограничений не найдено")
    g["method"] = methods
    g["legal_basis"] = basis
    g["follow_up_years"] = 5 if taxon == "heracleum" else 3
    return g


def summarize(P: gpd.GeoDataFrame) -> dict:
    """Counts for the report and the deck; every hotspot falls into exactly one of the three method classes."""
    drone = P.method.str.contains("с дрона")
    ground = P.method.str.contains("наземная точечная")
    chem_ok = ~(P.in_water_zone | P.in_protected | P.near_children)
    out = {
        "hotspots": int(len(P)),
        "in_water_zone_no_pesticides": int(P.in_water_zone.sum()),
        "water_zone_by_width_m": {str(int(k)): int(v)
                                  for k, v in P.water_zone_m[P.in_water_zone].value_counts().sort_index().items()},
        "in_protected_mechanical": int(P.in_protected.sum()),
        "child_org_territory": int(P.child_org_territory.sum()),
        "near_children_100m": int(P.near_children.sum()),
        "near_heritage_no_digging": int(P.near_heritage.sum()),
        "in_settlement": int(P.in_settlement.sum()),
        "aerial_blocked_uav_700m": int((chem_ok & (P.near_settlement_uav | P.near_reserve_or_water_uav)).sum()),
        "drone_spraying_allowed": int(drone.sum()),
        "ground_spot_treatment": int(ground.sum()),
        "mechanical_only": int((~drone & ~ground).sum()),
    }
    if "inside_aoa" in P:
        out["share_hotspots_inside_aoa"] = round(float(P.inside_aoa.mean()), 3)
    if "d_child_m" in P:
        out["near_children_300m"] = int((P.d_child_m <= 300).sum())
    assert out["drone_spraying_allowed"] + out["ground_spot_treatment"] + out["mechanical_only"] == len(P)
    return out
