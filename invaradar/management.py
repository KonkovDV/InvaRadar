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
      zone; rivers in closed collectors have no zone (part 10) — this case is not separated, so a collector may
      still receive a zone;
    - canals (part 9): the zone equals the canal's right-of-way. This repository has no right-of-way layer, so a
      canal is not given a river-length width;
    - ditches and drains stay at 50 m as a caution of this system. Part 9 does not name them.
  Production should replace this with the State Water Register and the zone boundaries approved for Moscow.
* Aerial application of pesticides keeps at least 2 km (manned aircraft) or 700 m (unmanned aircraft systems) from
  settlements, drinking-water sources, nature reserves, national parks, zakazniks and fishery water bodies
  (СанПиН 2.1.3684-21 item 282). A hotspot inside a settlement is at distance 0. Inside settlements green spaces
  are treated with ground boom or knapsack sprayers only (item 273(3)).   So in Moscow the drone finds and outlines
  stands, and a ground crew treats them. Settlements: locality boundaries plus residential land use
  (invaradar.layers). A statutory water-protection zone stands in for a fishery water body.
  The 50 m ditch caution does not: it is not that zone and it does not create the 700 m aerial buffer.
* Ground application: residents are notified through the media at least 5 calendar days ahead and warning signs stand
  at the entrances (item 272). Inside a settlement, item 273(4) also requires the treatment before 07:00 or after
  22:00, in calm weather. That clock time is written into the order.
* Children: pesticides are banned on the territories of children's organisations (СанПиН item 273(2));
  playgrounds and anything within 100 m of a kindergarten, school or playground are a precaution of this system,
  not a statutory distance → no pesticides. Their place in the safety queue is a separate rank. The straight-line
  visit order follows the combined priority score, which still includes area.
* Protected natural areas: ООПТ regimes restrict chemicals, and Mosprirodа mows Heracleum on Moscow's ООПТ up to
  10 times a season → mechanical methods only. Parks get the same treatment as a precaution of this system. Proxy
  here: Overture parks, natural monuments and nature reserves; production uses the official ООПТ layer.
* Cultural heritage within 50 m: earthworks need heritage clearance (Federal Law 73-ФЗ) → no digging of root
  collars or rhizomes; cutting, umbel removal or covering instead.

Biology:
* Heracleum sosnowskyi flowers once and dies after seeding, so cutting the root collar 10–15 cm below ground
  (up to 20 cm on a large plant) kills the plant (manual work, practical for small stands; stands above ~0.5 ha
  are mown at least every 2 weeks from May to September, with root-collar cutting at the edges); umbels are cut
  by late July and again in August and destroyed, because seed ripens on a cut umbel; soil from the stand is not
  hauled away and machines are cleaned on site; most seeds germinate the next spring and a few per cent survive
  2–3 years, while mown rosettes postpone flowering → 5 seasons of follow-up, with a check 3–4 weeks after the cut.
* Solidago spreads by rhizomes: mowing twice a season (late May–June and before flowering in August) depletes them
  over several years; seed heads must be removed before September. Rhizomes and soil stay on the stand, and
  machines are cleaned there.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from .layers import child_facilities, child_organisations, settlements
from .legal import listed_act
from .priority import SAFETY_CHILD_M

CHILD_M = 100.0
AERIAL_UAV_M = 700.0          # СанПиН 2.1.3684-21 item 282 for unmanned aircraft systems (since 10.03.2026)
AERIAL_MANNED_M = 2000.0      # the same item for manned aircraft; kept for reference, the system plans drones only
HERITAGE_M = 50.0
LARGE_STAND_M2 = 5_000.0      # above ~0.5 ha manual root-collar cutting is impractical: repeated mowing instead
COLLAR = "подрезка корневой шейки на 10–15 см, у крупных растений до 20 см"
RESERVE_M = 200.0
LAKE_MIN_KM2 = 0.5
CONNECT_M = 30.0

RIVER_LINES = {"river"}
LENGTH_LINES = {"river", "stream"}  # Water Code art. 65 part 4: width follows length. Canals are part 9, not this set.
CANAL_CLASS = {"canal"}             # art. 65 part 9: zone width is the right-of-way, which these layers do not carry
DITCH_LINES = {"ditch", "drain"}    # 50 m as a caution of this system; part 9 does not name ditches
STANDING = {"lake", "reservoir", "pond", "oxbow", "water", "bay", "lagoon", "river", "stream", "moat"}
NO_ZONE = {"swimming_pool", "reflecting_pool", "wastewater", "sewage", "basin", "water_storage", "fountain"}

FARM_LANDUSE = {"farmyard", "animal_keeping", "farm"}
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
    thumb); the others end there as tributaries. At a fork the main stem follows the outgoing branch with the
    longest path down to a mouth, not the longest first segment. A watercourse is a chain of segments joined this
    way, and every segment gets the total length of its chain. Rivers cut by the study-area edge get a lower bound.
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
    down_len = np.full(n, -1.0)  # longest path from this segment down to a mouth, including itself

    def down_longest(e: int, seen: set) -> float:
        if down_len[e] >= 0:
            return down_len[e]
        seen.add(e)
        try:
            nxts = [down_longest(f, seen) for f in out_of.get(tails[e], []) if f not in seen]
            down_len[e] = length[e] + (max(nxts) if nxts else 0.0)
            return down_len[e]
        finally:
            seen.discard(e)

    for e in range(n):
        down_longest(e, set())
    # The main incoming continues downstream. At a fork, take the branch with the longest remaining path.
    nxt = np.full(n, -1)
    for e in range(n):
        if main_in.get(tails[e]) == e:
            down = out_of.get(tails[e], [])
            if down:
                nxt[e] = max(down, key=lambda f: down_len[f])
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

    # rivers and streams: width from the length of the watercourse (art. 65 part 4)
    net = w[is_line & cls.isin(LENGTH_LINES)]
    if len(net):
        lengths = watercourse_lengths(net)
        zone[net.index.to_numpy()] = [river_width_m(x) for x in lengths]
    # ditches and drains: 50 m as a caution of this system. Part 9 names canals, not ditches.
    ditch = (is_line & cls.isin(DITCH_LINES)).to_numpy()
    zone[ditch] = 50.0
    note = np.full(len(w), "", dtype=object)
    note[ditch] = "правило осторожности системы: 50 м, пока нет официальной полосы; норма о полосе отвода канала сюда не относится"
    # canals: art. 65 part 9. No right-of-way in the layer, so no river-length width and no invented width.
    canal = cls.isin(CANAL_CLASS).to_numpy()
    note[canal] = ("ВК РФ ст. 65 ч. 9: ширина равна полосе отвода; официальной полосы в данных нет, "
                   "ширина по длине реки не назначается")
    zone[((w.geom_type == "Point") & (cls == "spring")).to_numpy()] = 50.0

    # standing water and river areas: a river's width if connected to it, 50 m for lakes ≥ 0.5 km², else none
    poly = w.geom_type.str.contains("Polygon") & cls.isin(STANDING) & ~cls.isin(NO_ZONE)
    if poly.any():
        P = w[poly]
        lake = (P.area / 1e6 >= LAKE_MIN_KM2).to_numpy()
        zone[P.index.to_numpy()[lake]] = 50.0
        lines = w[is_line & (zone > 0)].assign(zone_m=zone[(is_line & (zone > 0)).to_numpy()])
        if len(lines):
            # Every line within CONNECT_M, not only the nearest. A ditch 10 m away must not hide a river 20 m away:
            # the water body takes the wider zone (Water Code art. 65: a lake on a river keeps the river's width).
            near = gpd.sjoin(P[["geometry"]], lines[["geometry", "zone_m"]], predicate="dwithin", distance=CONNECT_M)
            if len(near):
                best = near.groupby(level=0)["zone_m"].max()
                zone[best.index.to_numpy()] = np.maximum(zone[best.index.to_numpy()], best.to_numpy())
    return w.assign(zone_m=zone, zone_note=note)


def _jurisdiction(g: gpd.GeoDataFrame, regions) -> np.ndarray:
    out = np.full(len(g), "unknown", dtype=object)
    if regions is None or len(regions) == 0 or "jurisdiction" not in regions.columns:
        return out
    pts = gpd.GeoDataFrame(geometry=g.geometry.representative_point(), crs=g.crs)
    joined = gpd.sjoin(pts, regions.to_crs(g.crs)[["jurisdiction", "geometry"]], how="left", predicate="within")
    hit = joined.groupby(level=0)["jurisdiction"].first()
    for i, value in hit.items():
        if isinstance(value, str):
            out[int(i)] = value
    return out


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


def prescribe(h: gpd.GeoDataFrame, taxon: str, water, landuse, places, localities=None,
              zso=None, regions=None) -> gpd.GeoDataFrame:
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
    # СанПиН item 282: 700 m from fishery waters. A statutory zone stands in for that.
    # A ditch's 50 m caution is not a fishery water and does not grow into a 700 m ban.
    statutory_water = wz[(wz.zone_m > 0) & ~wz["class"].astype(str).isin(DITCH_LINES)]
    g["near_reserve_or_water_uav"] = _near(g, reserves, AERIAL_UAV_M) | _near(g, statutory_water, AERIAL_UAV_M)
    farms = landuse[lu_cls.isin(FARM_LANDUSE)] if "class" in landuse else landuse.iloc[0:0]
    g["near_farm_uav"] = _near(g, farms, AERIAL_UAV_M)
    g["in_zso"] = _near(g, zso, 0.0)
    g["jurisdiction"] = _jurisdiction(g, regions)
    g["listed_species_act"] = [listed_act(j, taxon) for j in g["jurisdiction"]]

    methods, basis = [], []
    for r in g.itertuples():
        b = []
        chem_ok = not (r.in_water_zone or r.in_protected or r.near_children or r.in_zso)
        aerial_ok = chem_ok and not (r.near_settlement_uav or r.near_reserve_or_water_uav or r.near_farm_uav)
        dig_ok = not r.near_heritage
        if r.in_water_zone:
            b.append(f"ВК РФ ст. 65 ч. 15 п. 3 и 6: водоохранная зона {r.water_zone_m:.0f} м, пестициды и авиаобработка "
                     "запрещены")
        if r.child_org_territory:
            b.append("СанПиН 2.1.3684-21 п. 273: территория детской организации, пестициды запрещены")
        elif r.near_children:
            b.append(f"дети ≤{CHILD_M:.0f} м: без пестицидов (правило осторожности системы); "
                     "ранг очереди безопасности отдельный, порядок объезда — по общему баллу")
        if r.in_zso:
            b.append("зона санитарной охраны водозабора: пестициды запрещены, пока режим пояса не уточнён по акту ЗСО")
        if r.in_protected:
            b.append("ООПТ / парк: только механические методы")
        if chem_ok and not aerial_ok:
            where = "в населённом пункте" if r.in_settlement else (
                f"ближе {AERIAL_UAV_M:.0f} м к жилью, водоёму со статусной зоной или ООПТ")
            b.append(f"СанПиН 2.1.3684-21 п. 282, 273: {where} обработка с дрона запрещена, только наземная")
        if chem_ok and r.in_settlement:
            b.append("СанПиН 2.1.3684-21 п. 273: очаговая обработка в населённом пункте до 7:00 или после 22:00, "
                     "в безветренную погоду")
        if r.near_heritage:
            b.append(f"73-ФЗ ст. 36: земляные работы на объекте наследия требуют согласования; {HERITAGE_M:.0f} м — правило осторожности системы, в законе этого расстояния нет")
        chem_tail = ("препарат только из Государственного каталога, с регламентом для несельскохозяйственных земель; "
                     "норма, кратность и срок выхода людей — по регламенту; оповещение владельцев пасек в радиусе 7 км "
                     "(ст. 16 490-ФЗ); ")
        hours = ("СанПиН 2.1.3684-21 п. 273: в населённом пункте очаговая обработка до 7:00 или после 22:00, "
                 "в безветренную погоду; ") if r.in_settlement else ""
        ground = ("наземная точечная обработка ранцевым опрыскивателем по контуру очага (СанПиН п. 272: "
                  "оповещение за 5 дней, знаки); " + hours + chem_tail)
        ppe = ("; СИЗ: влагонепроницаемая одежда, перчатки, защита глаз; работать в пасмурную погоду или вечером; "
               "при попадании сока — смыть водой с мылом, кожу беречь от солнца 48 ч; "
               "срезанные зонтики не оставлять на участке — семена дозревают, в герметичных мешках на уничтожение; "
               "грунт с очага не вывозить; технику и обувь очистить на участке; "
               "повторный осмотр через 3–4 недели; после работ подсеять злаки без глубокой обработки почвы")
        large = getattr(r, "area_m2", 0.0) >= LARGE_STAND_M2
        if taxon == "heracleum":
            cut = "зонтики срезать до конца июля и повторно вторичные в августе"
            if large:
                m = ("покос не реже 1 раза в 2 недели с мая по сентябрь, до 8–10 раз за сезон (многократный покос), " + cut
                     + (f"; {COLLAR} на краях очага и в малых куртинах" if dig_ok else "; без перекопки"))
            elif dig_ok:
                m = f"{COLLAR} ниже земли + " + cut
            else:
                m = cut + " + укрывной материал, без перекопки"
            m += ppe + "; наблюдение 5 сезонов"
            if aerial_ok:
                m = ("точечное опрыскивание с дрона по контурам, если регламент препарата допускает БАС, есть "
                     f"разрешение на использование воздушного пространства и люди с животными не ближе {AERIAL_UAV_M:.0f} м; "
                     + chem_tail + m)
            elif chem_ok:
                m = ground + m
        else:
            m = "покос дважды: конец мая–июнь и до цветения в августе; удаление соцветий до сентября; наблюдение 5 сезонов"
            if dig_ok:
                m += "; выборка корневищ на малых куртинах"
            m += "; корневища и грунт с очага не вывозить и не компостировать; технику и обувь очистить на участке"
            if aerial_ok:
                m = ("точечная обработка по контурам (с дрона — только при допуске БАС в регламенте, разрешении "
                     f"на использование воздушного пространства и дистанции {AERIAL_UAV_M:.0f} м до людей и животных); " + chem_tail + m)
            elif chem_ok:
                m = "при необходимости " + ground + m
        methods.append(m + "; осмотр до работ: уничтожение только после подтверждения вида")
        basis.append("; ".join(b) if b else "ограничений по открытым слоям не найдено; вид подтвердить на месте")
    g["method"] = methods
    g["legal_basis"] = basis
    # A person signs the order. The program only marks a draft and leaves the signer empty.
    # 369-ПП is written by listed_act only when a jurisdiction polygon is passed in `regions`.
    g["status"] = "candidate"
    g["signed_by"] = ""
    g["follow_up_years"] = 5
    return g


def method_class(text: str) -> str:
    """One label for an order: drone, ground or mechanical.

    The web map and the published counts both use this, so a phrase change cannot
    put a stand in two classes or in different classes on the two surfaces.
    """
    wording = str(text)
    drone = "с дрона" in wording
    ground = "наземная точечная" in wording
    if drone and ground:
        raise ValueError("an order cannot name both a drone spray and a ground spray")
    if drone:
        return "drone"
    if ground:
        return "ground"
    return "mechanical"


def summarize(P: gpd.GeoDataFrame) -> dict:
    """Counts for the report and the deck; every hotspot falls into exactly one of the three method classes."""
    classes = P.method.map(method_class)
    drone = classes.eq("drone")
    ground = classes.eq("ground")
    chem_ok = ~(P.in_water_zone | P.in_protected | P.near_children)
    if "in_zso" in P.columns:
        chem_ok = chem_ok & ~P.in_zso
    uav_block = P.near_settlement_uav | P.near_reserve_or_water_uav
    if "near_farm_uav" in P.columns:
        uav_block = uav_block | P.near_farm_uav
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
        "aerial_blocked_uav_700m": int((chem_ok & uav_block).sum()),
        "drone_spraying_allowed": int(drone.sum()),
        "ground_spot_treatment": int(ground.sum()),
        "mechanical_only": int((~drone & ~ground).sum()),
    }
    if "inside_aoa" in P:
        out["share_hotspots_inside_aoa"] = round(float(P.inside_aoa.mean()), 3)
    if "d_child_m" in P:
        out["near_children_300m"] = int((P.d_child_m <= SAFETY_CHILD_M).sum())
    assert out["drone_spraying_allowed"] + out["ground_spot_treatment"] + out["mechanical_only"] == len(P)
    return out


def split_survey_units(gdf: gpd.GeoDataFrame, cell_m: float = 100.0) -> gpd.GeoDataFrame:
    """Cut each stand into survey units no wider than `cell_m`. A 100 m cell is at most 1 ha."""
    rows = []
    for i, row in gdf.reset_index(drop=True).iterrows():
        geom = row.geometry
        minx, miny, maxx, maxy = geom.bounds
        x0 = np.floor(minx / cell_m) * cell_m
        y0 = np.floor(miny / cell_m) * cell_m
        parent = row["hid"] if "hid" in gdf.columns else int(i)
        for x in np.arange(x0, maxx, cell_m):
            for y in np.arange(y0, maxy, cell_m):
                piece = geom.intersection(box(x, y, x + cell_m, y + cell_m))
                if piece.is_empty or piece.area < 1.0:
                    continue
                rows.append({"parent_hid": parent, "area_m2": float(piece.area), "geometry": piece})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)
