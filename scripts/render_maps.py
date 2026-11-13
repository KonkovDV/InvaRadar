"""Static maps for the deck and the plan: city-wide likelihood + a district zoom with the daily survey route."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, Point
from invaradar.config import DATA, EPSG, INAT_OBS, OUT, STUDY_BOX, TAXA, core_binary
from invaradar.queue import district_stops
from invaradar.samples import build, load_obs, plant_taxa
from invaradar.style import HOT, INK, PAPER, WATER_LIGHT, scale_bar, use_fonts


def main():
    use_fonts()
    taxon = sys.argv[1] if len(sys.argv) > 1 else "heracleum"
    od = OUT / taxon; fig_dir = OUT / "figures"; fig_dir.mkdir(exist_ok=True)
    CORE = core_binary()
    BG, WATER = PAPER, WATER_LIGHT
    cmap = LinearSegmentedColormap.from_list("hog", HOT)
    with rasterio.open(od / "likelihood_2025.tif") as ds:
        a = ds.read(1)
    w, s, e, n = STUDY_BOX
    k = 4
    h2, w2 = a.shape[0] // k, a.shape[1] // k
    v = np.where(a == 255, 0, a)[:h2 * k, :w2 * k].reshape(h2, k, w2, k).max((1, 3)) / 250.0
    ov = DATA / "overture"
    water = gpd.read_parquet(ov / "water.parquet").to_crs(EPSG)
    roads = gpd.read_parquet(ov / "roads.parquet")
    roads = roads[(roads.subtype == "road") & roads["class"].isin(["motorway", "trunk", "primary"])].to_crs(EPSG)
    H = gpd.read_file(od / "hotspots_2025.geojson").to_crs(EPSG)


    def base(ax, ext):
        ax.set_facecolor(BG)
        water[water.geom_type.str.contains("Polygon")].plot(ax=ax, color=WATER, lw=0)
        water[~water.geom_type.str.contains("Polygon")].plot(ax=ax, color=WATER, lw=0.6)
        roads.plot(ax=ax, color="#C9D2CE", lw=0.5)
        ax.set_xlim(ext[0], ext[2]); ax.set_ylim(ext[1], ext[3]); ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel("")
        for sp in ax.spines.values():
            sp.set_visible(False)


    # 1) city-wide map
    fig, ax = plt.subplots(figsize=(12, 12), dpi=150); fig.patch.set_facecolor(BG)
    base(ax, STUDY_BOX)
    m = np.ma.masked_less(v, 0.90)
    ax.imshow(m, extent=(w, w + w2 * k * 10, n - h2 * k * 10, n), cmap=cmap, vmin=0.90, vmax=1.0, interpolation="nearest", zorder=3)
    ax.set_xlim(w, e); ax.set_ylim(s, n); ax.set_xlabel(""); ax.set_ylabel("")
    scale_bar(ax, w + 2500, s + 2500, 10000, "10 км")
    fig.savefig(fig_dir / f"{taxon}_city.png", bbox_inches="tight", pad_inches=0, facecolor=BG)
    plt.close(fig)

    # 2) district zoom: densest 8-km neighbourhood of the top-300 priority hotspots → top 15 there → route (Rust)
    top = H.sort_values("priority", ascending=False).head(300).copy()
    c = np.c_[top.geometry.representative_point().x, top.geometry.representative_point().y]
    centre_i, stop_i = district_stops(c)
    centre = c[centre_i]
    near = top.iloc[stop_i]
    pc = np.c_[near.geometry.representative_point().x, near.geometry.representative_point().y]
    pts = np.vstack([centre, pc]).astype("<f8"); pts.tofile(od / "tmp" / "droute.f64")
    subprocess.run([str(CORE), "route", str(od / "tmp" / "droute.f64"), str(od / "tmp" / "droute.txt")], check=True)
    rt = open(od / "tmp" / "droute.txt").read().split(); length = float(rt[0]); order = [int(i) for i in rt[1:]]
    line = LineString([Point(pts[i]) for i in order])
    gpd.GeoDataFrame({"length_km": [length / 1000], "stops": [len(order) - 1]}, geometry=[line], crs=EPSG).to_crs(4326) \
        .to_file(od / "route_district_2025.geojson", driver="GeoJSON")
    ext = (centre[0] - 4500, centre[1] - 4500, centre[0] + 4500, centre[1] + 4500)
    if INAT_OBS.exists():
        S = build(load_obs(), TAXA[taxon]["ids"], plant_taxa())
        P = S[S.label == 1]
    else:  # no 10 GB export on disk: the reports inside the window from the public API
        from invaradar.inat_api import reports_in_window
        P = reports_in_window(TAXA[taxon]["ids"], ext)
    fig, ax = plt.subplots(figsize=(12, 12), dpi=150); fig.patch.set_facecolor(BG)
    base(ax, ext)
    r0, r1 = int((n - ext[3]) / 10), int((n - ext[1]) / 10); c0, c1 = int((ext[0] - w) / 10), int((ext[2] - w) / 10)
    sub = np.where(a[r0:r1, c0:c1] == 255, 0, a[r0:r1, c0:c1]) / 250.0
    ax.imshow(np.ma.masked_less(sub, 0.90), extent=(ext[0], ext[2], ext[1], ext[3]), cmap=cmap, vmin=0.9, vmax=1.0,
              interpolation="nearest", zorder=3, alpha=0.9)
    H.cx[ext[0]:ext[2], ext[1]:ext[3]].boundary.plot(ax=ax, color="#7A1E12", lw=0.5, zorder=4)
    ax.scatter(P.x, P.y, s=14, c=INK, marker="o", zorder=5, edgecolors=BG, linewidths=0.5)
    xs, ys = line.xy; ax.plot(xs, ys, color="#1F6F8B", lw=2.2, zorder=6)
    ax.scatter(pc[:, 0], pc[:, 1], s=120, facecolors="#1F6F8B", edgecolors=BG, linewidths=1.5, zorder=7)
    ax.scatter([centre[0]], [centre[1]], s=220, marker="s", c=INK, zorder=8)
    ax.set_xlim(ext[0], ext[2]); ax.set_ylim(ext[1], ext[3]); ax.set_xlabel(""); ax.set_ylabel("")
    scale_bar(ax, ext[0] + 400, ext[1] + 400, 2000, "2 км")
    fig.savefig(fig_dir / f"{taxon}_district.png", bbox_inches="tight", pad_inches=0, facecolor=BG)
    plt.close(fig)
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(EPSG, 4326, always_xy=True).transform(*centre)
    info = {"district_centre_lat": round(lat, 5), "district_centre_lon": round(lon, 5), "stops": len(order) - 1,
            "reports_source": "iNaturalist open data export" if INAT_OBS.exists() else "iNaturalist API",
            "route_km": round(length / 1000, 1), "known_reports_in_view": int(((P.x > ext[0]) & (P.x < ext[2]) & (P.y > ext[1]) & (P.y < ext[3])).sum())}
    json.dump(info, open(od / "district_route.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
