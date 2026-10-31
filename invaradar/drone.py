"""UAV module: orthomosaic → per-pixel invasive-plant mask → georeferenced polygons → spot-spraying mission.

This module is not called by the work-order pipeline (`scripts/pipeline.py`, `scripts/requeue.py`,
`scripts/prescribe.py`). `DinoProbeSegmenter` and `spray_mission` do not write a method, a route, or a
signature into a work order. The published ROC AUC is the leave-one-camera-out figure in
`outputs/drone/benchmark.json`. The probe file saved for deployment is fit on all cameras. Tests in
`tests/test_drone.py` exercise `BloomIndexSegmenter` on a synthetic image, not DINOv2.

The segmentation backend is pluggable:
  * `BloomIndexSegmenter` — training-free baseline for the flowering window (Heracleum: white compound umbels,
    late June–July; Solidago: yellow panicles, August–September), the approach shown to work on ordinary RGB
    cameras by Savin et al. 2021. Used to bootstrap labels in the first flights.
  * `DinoProbeSegmenter` — frozen DINOv2 ViT-S/14 patch features (Apache-2.0) + linear probe trained on real
    aerial photos of Heracleum from the Moscow region (scripts/drone_benchmark.py, leave-one-camera-out);
    works on leaves and rosettes, not only on flowers.
  * `TorchSegmenter` — any trained model (RF-DETR-Seg / SegFormer / U-Net exported to TorchScript or ONNX),
    trained on expert-verified masks from pilot flights.
Optional canopy-height gating (photogrammetric or LiDAR nDSM) is off unless phenophase is flowering.
InvaRadar does not use the lidar relief channels from expds-koz3; those are a separate tested function
in invaradar.survey_protocol and are not part of this segmenter.
"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.windows import Window
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString, shape


@dataclass
class BloomIndexSegmenter:
    """Bright, low-saturation (white umbels) or yellow, saturated (goldenrod) blobs of plant-organ size."""
    species: str = "heracleum"
    gsd_m: float = 0.03

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        x = rgb.astype(np.float32) / 255.0
        r, g, b = x[0], x[1], x[2]
        mx, mn = x.max(0), x.min(0)
        sat = (mx - mn) / np.maximum(mx, 1e-6)
        if self.species == "heracleum":
            score = np.clip((mx - 0.70) / 0.25, 0, 1) * np.clip((0.25 - sat) / 0.25, 0, 1)
            organ_m = 0.4  # umbel diameter 0.3–0.8 m
        else:
            yellow = np.clip((r + g) / 2 - b, 0, 1)
            score = np.clip((yellow - 0.25) / 0.3, 0, 1) * np.clip((sat - 0.35) / 0.4, 0, 1)
            organ_m = 0.25
        k = max(3, int(organ_m / self.gsd_m) | 1)
        dens = ndimage.uniform_filter(score, k)                          # organ scale (one umbel / panicle)
        stand = ndimage.uniform_filter(score, max(3, int(2.0 / self.gsd_m) | 1))  # stand scale, 2 m window
        # a stand = at least ~10 % of the ground covered by flowers within 2 m
        return np.maximum(np.clip(dens / 0.3, 0, 1), np.clip(stand / 0.10, 0, 1))


class DinoProbeSegmenter:
    """Per-pixel probability from DINOv2 patch tokens and the linear probe saved by scripts/drone_benchmark.py."""

    MEAN = np.array([0.485, 0.456, 0.406], np.float32)[:, None, None]
    STD = np.array([0.229, 0.224, 0.225], np.float32)[:, None, None]

    def __init__(self, probe: str = "outputs/drone/dinov2s_probe.joblib"):
        import joblib
        import timm
        import torch
        p = joblib.load(probe)
        self.torch, self.width = torch, p["width"]
        self.w, self.b, self.threshold = p["coef"][0], float(p["intercept"][0]), p["threshold"]
        self.context = p.get("context", 0)
        self.net = timm.create_model(p["model"], pretrained=True, num_classes=0, dynamic_img_size=True).eval()

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        _, h, w = rgb.shape
        hp, wp = max(1, round(h * self.width / w / 14)), self.width // 14
        x = self.torch.from_numpy(rgb[None].astype(np.float32) / 255.0)
        x = self.torch.nn.functional.interpolate(x, size=(hp * 14, wp * 14), mode="bilinear", antialias=True)
        x = (x - self.torch.from_numpy(self.MEAN)) / self.torch.from_numpy(self.STD)
        with self.torch.no_grad():
            tok = self.net.forward_features(x)[0, self.net.num_prefix_tokens:].numpy()
        tok /= np.linalg.norm(tok, axis=1, keepdims=True)
        if self.context:  # same 3×3 neighbourhood mean as in training
            k = self.context
            ctx = ndimage.uniform_filter(tok.reshape(hp, wp, -1), size=(k, k, 1), mode="nearest").reshape(hp * wp, -1)
            tok = np.hstack([tok, ctx / np.linalg.norm(ctx, axis=1, keepdims=True)])
        p = 1.0 / (1.0 + np.exp(-(tok @ self.w + self.b)))
        p = p.reshape(hp, wp).astype(np.float32)
        return ndimage.zoom(p, (h / p.shape[0], w / p.shape[1]), order=1)[:h, :w]


class TorchSegmenter:
    """Wraps a TorchScript model returning per-pixel logits (B, 1, H, W) for a normalised RGB batch."""

    def __init__(self, path: str, device: str = "cpu"):
        import torch
        self.torch = torch
        self.m = torch.jit.load(path, map_location=device).eval()
        self.device = device

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        t = self.torch.from_numpy(rgb[None].astype(np.float32) / 255.0).to(self.device)
        with self.torch.no_grad():
            return self.torch.sigmoid(self.m(t))[0, 0].cpu().numpy()


def apply_height_gate(prob: np.ndarray, height: np.ndarray, height_range=(1.2, 4.5),
                      phenophase: str = "rosette") -> np.ndarray:
    """Keep the 1.2–4.5 m gate for flowering stems only. A spring rosette is shorter than 1 m."""
    if phenophase != "flowering":
        return prob
    lo, hi = height_range
    return prob * np.clip((height - lo + 0.5) / 0.5, 0, 1) * np.clip((hi + 1.0 - height) / 1.0, 0, 1)


def segment_orthomosaic(path: str, segmenter, tile: int = 2048, overlap: int = 256, ndsm: str | None = None,
                        height_range=(1.2, 4.5), phenophase: str = "rosette") -> tuple[np.ndarray, rasterio.Affine, object]:
    """Sliding-window inference with overlap blending; returns (score, transform, crs).

    The 1.2–4.5 m height gate is for flowering stems. Spring rosettes are shorter than 1 m,
    so the gate is off unless phenophase is \"flowering\".
    """
    with rasterio.open(path) as ds:
        H, W = ds.height, ds.width
        prob = np.zeros((H, W), np.float32); wsum = np.zeros((H, W), np.float32)
        step = tile - overlap
        win = np.outer(np.hanning(tile) + 1e-3, np.hanning(tile) + 1e-3).astype(np.float32)
        for r0 in range(0, max(H - overlap, 1), step):
            for c0 in range(0, max(W - overlap, 1), step):
                h, w = min(tile, H - r0), min(tile, W - c0)
                rgb = ds.read([1, 2, 3], window=Window(c0, r0, w, h))
                p = segmenter(rgb)
                ww = win[:h, :w]
                prob[r0:r0 + h, c0:c0 + w] += p * ww; wsum[r0:r0 + h, c0:c0 + w] += ww
        prob /= np.maximum(wsum, 1e-6)
        transform, crs = ds.transform, ds.crs
    if ndsm and phenophase == "flowering":
        with rasterio.open(ndsm) as hs:
            z = hs.read(1, out_shape=(H, W), resampling=rasterio.enums.Resampling.bilinear)
        prob = apply_height_gate(prob, z, height_range, phenophase)
    return prob, transform, crs


def polygonize(prob: np.ndarray, transform, crs, thr: float = 0.5, min_area_m2: float = 1.0,
               close_m: float = 0.5) -> gpd.GeoDataFrame:
    px = abs(transform.a)
    mask = prob >= thr
    k = max(1, int(round(close_m / px)))
    mask = ndimage.binary_closing(mask, structure=np.ones((2 * k + 1, 2 * k + 1)))
    lab, n = ndimage.label(mask)
    geoms, ids = [], []
    for g, v in shapes(lab.astype(np.int32), mask=lab > 0, transform=transform, connectivity=8):
        geoms.append(shape(g)); ids.append(int(v))
    gdf = gpd.GeoDataFrame({"cid": ids}, geometry=geoms, crs=crs).dissolve("cid").reset_index()
    gdf["area_m2"] = gdf.area
    gdf = gdf[gdf.area_m2 >= min_area_m2].reset_index(drop=True)
    gdf["mean_prob"] = [float(prob[lab == c].mean()) for c in gdf.cid]
    return gdf


def spray_mission(polys: gpd.GeoDataFrame, swath_m: float = 4.0, buffer_m: float = 1.0,
                  rate_l_per_ha: float = 10.0) -> tuple[gpd.GeoDataFrame, dict]:
    """Boustrophedon passes clipped to each buffered stand (spot treatment instead of blanket spraying)."""
    lines, total_area = [], 0.0
    for geom in polys.geometry.buffer(buffer_m):
        total_area += geom.area
        minx, miny, maxx, maxy = geom.bounds
        ys = np.arange(miny + swath_m / 2, maxy, swath_m)
        segs = []
        for i, yv in enumerate(ys):
            seg = LineString([(minx - 1, yv), (maxx + 1, yv)]).intersection(geom)
            if seg.is_empty:
                continue
            parts = list(seg.geoms) if isinstance(seg, MultiLineString) else [seg]
            for p in parts:
                segs.append(p if i % 2 == 0 else LineString(p.coords[::-1]))
        if segs:
            lines.append(MultiLineString(segs))
    gdf = gpd.GeoDataFrame({"stand": range(len(lines))}, geometry=lines, crs=polys.crs)
    stats = {"stands": int(len(polys)), "treated_area_m2": round(total_area, 1),
             "tank_mix_l": round(total_area / 1e4 * rate_l_per_ha, 2),
             "pass_length_m": round(float(gdf.length.sum()), 1)}
    return gdf, stats
