//! invaradar_core — the compute core of InvaRadar, multithreaded with rayon.
//!
//! Subcommands (all I/O is little-endian raw binaries + small text files written by the Python glue):
//!   points   <grid.json> <points.f64> <out.f32>          features at UTM points (N x F, NaN row = no data)
//!   predict  <grid.json> <model.json> <land.f64> <out.u8> wall-to-wall landscape-percentile map (x250, 255 = no data)
//!   score    <grid.json> <model.json> <points.f64> <out.f64> raw GBDT scores at points (parity check vs LightGBM)
//!   hotspots <grid.json> <map.u8> <thr> <min_px> <labels.i32> <stats.csv>
//!   route    <points.f64> <out.txt>                       open tour from the first point (NN + 2-opt)
//!
//!   strata   <grid.json> <map.u8> <out.csv> <seed> <thr1,thr2,...> <n1,n2,...>  stratified random validation sample
//!
//! Features per 10 m pixel (F = 265), identical for training points and for the map:
//!   [0,64)    AlphaEarth embedding of the pixel
//!   [64,128)  valid-weighted mean over 5x5 px (50 m)
//!   [128,192) mean over 3x3 cells of 50 m (150 m)
//!   [192,256) mean over 9x9 cells of 50 m (450 m)
//!   [256,261) ln(1 + distance in m) to major roads, minor roads, railways, water edges, power lines
//!   [261,265) terrain from Copernicus DEM: elevation (m), slope (deg, Horn 1981), topographic wetness index
//!             TWI = ln(a / tan b) with D8 flow accumulation on the depression-filled DEM, HAND (m)
//!
//! Window statistics at the edge of the study grid use replicate (nearest) padding, the same for points and map.

// Index loops over pixels and bands are the clearest form for these numeric kernels.
#![allow(clippy::needless_range_loop)]

use anyhow::{Context, Result, bail};
use rayon::prelude::*;
use serde_json::Value;
use std::fs;
use std::io::Write;
use std::time::Instant;

const B: usize = 64; // embedding channels
const BLK: usize = 1024; // AEF block size (px)
const CELL: usize = 5; // 50 m coarse cell
const NCOR: usize = 5;
const NTER: usize = 4;
const F: usize = 4 * B + NCOR + NTER;
const NODATA: i8 = -128;

fn lut() -> [f32; 256] {
    let mut t = [0f32; 256];
    for (i, v) in t.iter_mut().enumerate() {
        let q = i as f32 - 128.0;
        *v = q.signum() * (q / 127.5) * (q / 127.5);
    }
    t[0] = 0.0;
    t
}

// ---------------------------------------------------------------- grid & mosaic

struct Grid {
    w: f64,
    n: f64,
    width: usize,
    height: usize,
    res: f64,
    blocks: Vec<(String, f64, f64)>, // npy path, x0 (west), y0 (south); rows stored south-up
    segments: Vec<String>,           // per corridor layer: f32 quadruples (c0, r0, c1, r1) in px
    dem: Option<String>,             // f32 elevation on the study grid (H x W), north-up
}

fn read_grid(p: &str) -> Result<Grid> {
    let v: Value = serde_json::from_str(&fs::read_to_string(p)?)?;
    let f = |k: &str| v[k].as_f64().with_context(|| format!("grid.{k}"));
    let blocks = v["blocks"]
        .as_array()
        .context("blocks")?
        .iter()
        .map(|b| {
            Ok((
                b[0].as_str().context("block path")?.to_string(),
                b[1].as_f64().context("block x0")?,
                b[2].as_f64().context("block y0")?,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    let segments = v["segments"]
        .as_array()
        .context("segments")?
        .iter()
        .map(|s| Ok(s.as_str().context("segment path")?.to_string()))
        .collect::<Result<Vec<_>>>()?;
    let dem = v["dem"].as_str().map(|x| x.to_string());
    Ok(Grid {
        w: f("w")?,
        n: f("n")?,
        width: f("width")? as usize,
        height: f("height")? as usize,
        res: f("res")?,
        blocks,
        segments,
        dem,
    })
}

fn npy_data(bytes: &[u8]) -> Result<&[u8]> {
    if &bytes[..6] != b"\x93NUMPY" {
        bail!("not an npy file");
    }
    let (hl, off) = if bytes[6] == 1 {
        (u16::from_le_bytes([bytes[8], bytes[9]]) as usize, 10)
    } else {
        (
            u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]) as usize,
            12,
        )
    };
    Ok(&bytes[off + hl..])
}

/// North-up, pixel-interleaved int8 mosaic (H x W x 64) of the study grid.
fn mosaic(g: &Grid) -> Result<Vec<i8>> {
    let (h, w) = (g.height, g.width);
    let mut m = vec![NODATA; h * w * B];
    let span = BLK as f64 * g.res;
    for (path, x0, y0) in &g.blocks {
        let file = fs::File::open(path).with_context(|| path.clone())?;
        let mm = unsafe { memmap2::Mmap::map(&file)? };
        let d = npy_data(&mm)?;
        let top = ((g.n - (y0 + span)) / g.res).round() as i64;
        let left = ((x0 - g.w) / g.res).round() as i64;
        // block row br (south-up) → mosaic row top + (BLK-1-br)
        let rows: Vec<(usize, usize)> = (0..BLK)
            .filter_map(|br| {
                let r = top + (BLK - 1 - br) as i64;
                (r >= 0 && (r as usize) < h).then_some((br, r as usize))
            })
            .collect();
        let c0 = left.max(0) as usize;
        let c1 = ((left + BLK as i64).min(w as i64)).max(0) as usize;
        if c1 <= c0 {
            continue;
        }
        let mrows: Vec<&mut [i8]> = {
            // split mosaic into row slices we can write in parallel
            let mut out = Vec::with_capacity(rows.len());
            let base = m.as_mut_ptr();
            for &(_, r) in &rows {
                out.push(unsafe { std::slice::from_raw_parts_mut(base.add(r * w * B), w * B) });
            }
            out
        };
        rows.par_iter()
            .zip(mrows.into_par_iter())
            .for_each(|(&(br, _), row)| {
                for c in c0..c1 {
                    let bc = (c as i64 - left) as usize;
                    let px = &mut row[c * B..(c + 1) * B];
                    for b in 0..B {
                        px[b] = d[(b * BLK + br) * BLK + bc] as i8;
                    }
                }
            });
    }
    Ok(m)
}

// ---------------------------------------------------------------- multi-scale context

struct Ctx {
    m: Vec<i8>,
    lut: [f32; 256],
    hc: usize,
    wc: usize,
    ms3: Vec<f32>, // (hc*wc, 64)
    ms9: Vec<f32>,
    dist: Vec<Vec<f32>>, // NCOR x (H*W), metres
    terr: Vec<f32>,      // (H*W, NTER)
    h: usize,
    w: usize,
}

fn coarse(m: &[i8], lut: &[f32; 256], h: usize, w: usize) -> (Vec<f32>, Vec<f32>, usize, usize) {
    let (hc, wc) = (h.div_ceil(CELL), w.div_ceil(CELL));
    let mut sum = vec![0f32; hc * wc * B];
    let mut cnt = vec![0f32; hc * wc];
    sum.par_chunks_mut(wc * B)
        .zip(cnt.par_chunks_mut(wc))
        .enumerate()
        .for_each(|(rc, (srow, crow))| {
            for r in rc * CELL..((rc + 1) * CELL).min(h) {
                for c in 0..w {
                    let px = &m[(r * w + c) * B..(r * w + c + 1) * B];
                    if px[0] == NODATA {
                        continue;
                    }
                    let cc = c / CELL;
                    crow[cc] += 1.0;
                    let s = &mut srow[cc * B..(cc + 1) * B];
                    for b in 0..B {
                        s[b] += lut[(px[b] as i16 + 128) as usize];
                    }
                }
            }
        });
    (sum, cnt, hc, wc)
}

fn window_mean(sum: &[f32], cnt: &[f32], hc: usize, wc: usize, k: usize) -> Vec<f32> {
    let h = (k / 2) as i64;
    let mut out = vec![0f32; hc * wc * B];
    out.par_chunks_mut(wc * B)
        .enumerate()
        .for_each(|(r, orow)| {
            for c in 0..wc {
                let mut acc = [0f32; B];
                let mut n = 0f32;
                for dr in -h..=h {
                    let rr = (r as i64 + dr).clamp(0, hc as i64 - 1) as usize;
                    for dc in -h..=h {
                        let cc = (c as i64 + dc).clamp(0, wc as i64 - 1) as usize;
                        let i = rr * wc + cc;
                        n += cnt[i];
                        let s = &sum[i * B..(i + 1) * B];
                        for b in 0..B {
                            acc[b] += s[b];
                        }
                    }
                }
                let o = &mut orow[c * B..(c + 1) * B];
                if n > 0.0 {
                    for b in 0..B {
                        o[b] = acc[b] / n;
                    }
                }
            }
        });
    out
}

/// Exact Euclidean distance transform (Felzenszwalb & Huttenlocher), returns metres.
fn edt(mask: &[u8], h: usize, w: usize, res: f32) -> Vec<f32> {
    const INF: f32 = 1e20;
    fn dt1(f: &[f32], d: &mut [f32], v: &mut [usize], z: &mut [f32]) {
        let n = f.len();
        let mut k = 0usize;
        v[0] = 0;
        z[0] = -INF;
        z[1] = INF;
        for q in 1..n {
            loop {
                let p = v[k];
                let s = ((f[q] + (q * q) as f32) - (f[p] + (p * p) as f32))
                    / (2.0 * q as f32 - 2.0 * p as f32);
                if s <= z[k] && k > 0 {
                    k -= 1;
                    continue;
                }
                k += 1;
                v[k] = q;
                z[k] = s;
                z[k + 1] = INF;
                break;
            }
        }
        k = 0;
        for q in 0..n {
            while z[k + 1] < q as f32 {
                k += 1;
            }
            let p = v[k];
            let dq = q as f32 - p as f32;
            d[q] = dq * dq + f[p];
        }
    }
    let mut g = vec![0f32; h * w];
    // columns
    let cols: Vec<Vec<f32>> = (0..w)
        .into_par_iter()
        .map(|c| {
            let f: Vec<f32> = (0..h)
                .map(|r| if mask[r * w + c] != 0 { 0.0 } else { INF })
                .collect();
            let mut d = vec![0f32; h];
            let (mut v, mut z) = (vec![0usize; h], vec![0f32; h + 1]);
            dt1(&f, &mut d, &mut v, &mut z);
            d
        })
        .collect();
    for (c, col) in cols.iter().enumerate() {
        for r in 0..h {
            g[r * w + c] = col[r];
        }
    }
    // rows
    g.par_chunks_mut(w).for_each(|row| {
        let f = row.to_vec();
        let (mut v, mut z) = (vec![0usize; w], vec![0f32; w + 1]);
        dt1(&f, row, &mut v, &mut z);
        for x in row.iter_mut() {
            *x = x.sqrt() * res;
        }
    });
    g
}

fn rasterize_segments(path: &str, h: usize, w: usize) -> Result<Vec<u8>> {
    let bytes = fs::read(path).with_context(|| path.to_string())?;
    let s: Vec<f32> = bytes
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect();
    let mut m = vec![0u8; h * w];
    for q in s.chunks_exact(4) {
        let (c0, r0, c1, r1) = (q[0], q[1], q[2], q[3]);
        let len = ((c1 - c0).abs().max((r1 - r0).abs()) * 2.0).ceil().max(1.0) as usize;
        for i in 0..=len {
            let t = i as f32 / len as f32;
            let (c, r) = (c0 + t * (c1 - c0), r0 + t * (r1 - r0));
            if c >= 0.0 && r >= 0.0 && (c as usize) < w && (r as usize) < h {
                m[r as usize * w + c as usize] = 1;
            }
        }
    }
    Ok(m)
}

/// Terrain features are the slowest part of the context and depend only on the DEM, so they are computed once
/// and kept next to it (`<dem>.terrain-v2.f32`, H*W*NTER little-endian f32). Delete the file after changing the DEM.
fn cached_terrain(dem: &str, g: &Grid) -> Result<Vec<f32>> {
    let cache = format!("{dem}.terrain-v2.f32");
    let n = g.height * g.width * NTER;
    if fs::metadata(&cache).is_ok_and(|m| m.len() as usize == n * 4) {
        return read_f32(&cache);
    }
    let t = terrain(&read_f32(dem)?, g.height, g.width, g.res as f32);
    write_bytes(
        &cache,
        &t.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<u8>>(),
    )?;
    Ok(t)
}

fn build_context(g: &Grid) -> Result<Ctx> {
    let t = Instant::now();
    let lut = lut();
    let m = mosaic(g)?;
    eprintln!(
        "[core] mosaic {}x{} in {:.1}s",
        g.width,
        g.height,
        t.elapsed().as_secs_f32()
    );
    let (sum, cnt, hc, wc) = coarse(&m, &lut, g.height, g.width);
    let ms3 = window_mean(&sum, &cnt, hc, wc, 3);
    let ms9 = window_mean(&sum, &cnt, hc, wc, 9);
    eprintln!(
        "[core] multiscale context in {:.1}s",
        t.elapsed().as_secs_f32()
    );
    let dist = g
        .segments
        .iter()
        .map(|p| {
            Ok(edt(
                &rasterize_segments(p, g.height, g.width)?,
                g.height,
                g.width,
                g.res as f32,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    eprintln!(
        "[core] corridor distances in {:.1}s",
        t.elapsed().as_secs_f32()
    );
    let terr = match &g.dem {
        Some(p) => cached_terrain(p, g)?,
        None => vec![0f32; g.height * g.width * NTER],
    };
    eprintln!("[core] terrain in {:.1}s", t.elapsed().as_secs_f32());
    Ok(Ctx {
        m,
        lut,
        hc,
        wc,
        ms3,
        ms9,
        dist,
        terr,
        h: g.height,
        w: g.width,
    })
}

impl Ctx {
    #[inline]
    fn px(&self, r: usize, c: usize) -> &[i8] {
        &self.m[(r * self.w + c) * B..(r * self.w + c + 1) * B]
    }

    /// Column sum of 5 rows (r-2..=r+2, clamped) at column c, accumulated in fixed order.
    #[inline]
    fn colsum(&self, r: usize, c: usize, acc: &mut [f32; B]) -> f32 {
        let mut n = 0f32;
        *acc = [0f32; B];
        for dr in -2i64..=2 {
            let rr = (r as i64 + dr).clamp(0, self.h as i64 - 1) as usize;
            let p = self.px(rr, c);
            if p[0] == NODATA {
                continue;
            }
            n += 1.0;
            for b in 0..B {
                acc[b] += self.lut[(p[b] as i16 + 128) as usize];
            }
        }
        n
    }

    /// Fill features for pixel (r, c) given the 5x5 local sum; returns false for a no-data pixel.
    #[inline]
    fn finish(&self, r: usize, c: usize, loc: &[f32; B], nloc: f32, out: &mut [f32]) -> bool {
        let p = self.px(r, c);
        if p[0] == NODATA {
            out.iter_mut().for_each(|x| *x = f32::NAN);
            return false;
        }
        for b in 0..B {
            out[b] = self.lut[(p[b] as i16 + 128) as usize];
            out[B + b] = if nloc > 0.0 { loc[b] / nloc } else { 0.0 };
        }
        let ci = (r / CELL).min(self.hc - 1) * self.wc + (c / CELL).min(self.wc - 1);
        out[2 * B..3 * B].copy_from_slice(&self.ms3[ci * B..(ci + 1) * B]);
        out[3 * B..4 * B].copy_from_slice(&self.ms9[ci * B..(ci + 1) * B]);
        for k in 0..NCOR {
            out[4 * B + k] = (1.0 + self.dist[k][r * self.w + c]).ln();
        }
        let ti = (r * self.w + c) * NTER;
        out[4 * B + NCOR..F].copy_from_slice(&self.terr[ti..ti + NTER]);
        true
    }

    fn point(&self, r: usize, c: usize, out: &mut [f32]) -> bool {
        let mut loc = [0f32; B];
        let mut n = 0f32;
        let mut cs = [0f32; B];
        for dc in -2i64..=2 {
            let cc = (c as i64 + dc).clamp(0, self.w as i64 - 1) as usize;
            n += self.colsum(r, cc, &mut cs);
            for b in 0..B {
                loc[b] += cs[b];
            }
        }
        self.finish(r, c, &loc, n, out)
    }
}

// ---------------------------------------------------------------- terrain & hydrology

fn read_f32(p: &str) -> Result<Vec<f32>> {
    let b = fs::read(p).with_context(|| p.to_string())?;
    Ok(b.chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
        .collect())
}

const NB8: [(i64, i64, f32); 8] = [
    (-1, -1, std::f32::consts::SQRT_2),
    (-1, 0, 1.0),
    (-1, 1, std::f32::consts::SQRT_2),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (1, -1, std::f32::consts::SQRT_2),
    (1, 0, 1.0),
    (1, 1, std::f32::consts::SQRT_2),
];

/// Depression filling, Priority-Flood + epsilon (Barnes, Lehman & Mulla 2014, Computers & Geosciences 62:117).
/// Every pit is raised to its spill level and flats get a one-ulp gradient, so each cell has a strictly lower
/// neighbour on the way to the grid edge and D8 flow never stops inside the study area.
fn fill_depressions(z: &[f32], h: usize, w: usize) -> Vec<f32> {
    use std::cmp::Ordering;
    use std::collections::{BinaryHeap, VecDeque};
    #[derive(PartialEq)]
    struct Cell(f32, u32);
    impl Eq for Cell {}
    impl Ord for Cell {
        // reversed: BinaryHeap pops the lowest elevation first; ties broken by index for determinism
        fn cmp(&self, o: &Self) -> Ordering {
            o.0.total_cmp(&self.0).then_with(|| o.1.cmp(&self.1))
        }
    }
    impl PartialOrd for Cell {
        fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
            Some(self.cmp(o))
        }
    }
    let mut f = z.to_vec();
    let mut closed = vec![false; h * w];
    let mut open = BinaryHeap::new();
    let mut pit: VecDeque<u32> = VecDeque::new();
    for r in 0..h {
        for c in 0..w {
            if r == 0 || c == 0 || r + 1 == h || c + 1 == w {
                let i = r * w + c;
                closed[i] = true;
                open.push(Cell(f[i], i as u32));
            }
        }
    }
    while let Some(i) = pit.pop_front().or_else(|| open.pop().map(|c| c.1)) {
        let i = i as usize;
        let (r, c) = ((i / w) as i64, (i % w) as i64);
        for (dr, dc, _) in NB8 {
            let (rr, cc) = (r + dr, c + dc);
            if rr < 0 || cc < 0 || rr >= h as i64 || cc >= w as i64 {
                continue;
            }
            let j = rr as usize * w + cc as usize;
            if closed[j] {
                continue;
            }
            closed[j] = true;
            let up = f[i].next_up();
            if f[j] <= up {
                f[j] = up;
                pit.push_back(j as u32);
            } else {
                open.push(Cell(f[j], j as u32));
            }
        }
    }
    f
}

/// Contributing area (in cells) that turns a flow path into a channel for HAND: 10 000 cells = 1 km².
const STREAM_CELLS: f32 = 10_000.0;

/// Terrain block (H*W x NTER): elevation (m), slope (deg), TWI, HAND (m).
///
/// * slope — Horn (1981) on the original DEM;
/// * TWI = ln(a / tan b), a = specific catchment area from D8 flow accumulation (O'Callaghan & Mark 1984) on the
///   depression-filled DEM (Beven & Kirkby 1979);
/// * HAND — height above the nearest drainage reached along the D8 flow path (Rennó et al. 2008; Nobre et al.
///   2011); drainage = cells with at least `STREAM_CELLS` of upslope area. Paths leaving the grid are referenced
///   to the edge cell they exit through.
fn terrain(z: &[f32], h: usize, w: usize, res: f32) -> Vec<f32> {
    let at = |r: i64, c: i64| {
        z[(r.clamp(0, h as i64 - 1) as usize) * w + c.clamp(0, w as i64 - 1) as usize]
    };
    // slope, Horn (1981)
    let mut slope = vec![0f32; h * w];
    slope.par_chunks_mut(w).enumerate().for_each(|(r, row)| {
        let r = r as i64;
        for c in 0..w as i64 {
            let (a, b, cc) = (at(r - 1, c - 1), at(r - 1, c), at(r - 1, c + 1));
            let (d, f) = (at(r, c - 1), at(r, c + 1));
            let (g, hh, i) = (at(r + 1, c - 1), at(r + 1, c), at(r + 1, c + 1));
            let dzdx = ((cc + 2.0 * f + i) - (a + 2.0 * d + g)) / (8.0 * res);
            let dzdy = ((g + 2.0 * hh + i) - (a + 2.0 * b + cc)) / (8.0 * res);
            row[c as usize] = (dzdx * dzdx + dzdy * dzdy).sqrt().atan();
        }
    });
    // D8 on the filled DEM: steepest-descent receiver of every cell, then accumulation from highest to lowest
    let n = h * w;
    let fz = fill_depressions(z, h, w);
    let recv: Vec<u32> = (0..n)
        .into_par_iter()
        .map(|i| {
            let (r, c) = ((i / w) as i64, (i % w) as i64);
            let mut best = 0f32;
            let mut bj = u32::MAX;
            for (dr, dc, dd) in NB8 {
                let (rr, cc) = (r + dr, c + dc);
                if rr < 0 || cc < 0 || rr >= h as i64 || cc >= w as i64 {
                    continue;
                }
                let j = rr as usize * w + cc as usize;
                let drop = (fz[i] - fz[j]) / dd;
                if drop > best {
                    best = drop;
                    bj = j as u32;
                }
            }
            bj
        })
        .collect();
    let mut order: Vec<u32> = (0..n as u32).collect();
    order.par_sort_unstable_by(|a, b| fz[*b as usize].total_cmp(&fz[*a as usize]).then(a.cmp(b)));
    let mut acc = vec![1f32; n];
    for &i in &order {
        let j = recv[i as usize];
        if j != u32::MAX {
            acc[j as usize] += acc[i as usize];
        }
    }
    // HAND: walk the cells from lowest to highest, so a cell's receiver already knows its drainage elevation
    let mut drain_z = vec![0f32; n];
    for &i in order.iter().rev() {
        let i = i as usize;
        let j = recv[i];
        drain_z[i] = if acc[i] >= STREAM_CELLS || j == u32::MAX {
            fz[i]
        } else {
            drain_z[j as usize]
        };
    }
    let mut out = vec![0f32; n * NTER];
    out.par_chunks_mut(NTER).enumerate().for_each(|(i, o)| {
        let tanb = slope[i].tan().max(0.001);
        o[0] = z[i];
        o[1] = slope[i].to_degrees();
        o[2] = (acc[i] * res / tanb).ln();
        o[3] = (fz[i] - drain_z[i]).max(0.0);
    });
    out
}

// ---------------------------------------------------------------- GBDT (LightGBM dump_model JSON)

#[derive(Clone, Copy)]
struct Node {
    feat: u32, // u32::MAX = leaf
    thr: f64,  // threshold or leaf value
    left: u32,
    right: u32,
    default_left: bool,
    missing: u8, // 0 None, 1 Zero, 2 NaN
}

struct Forest {
    nodes: Vec<Node>,
    roots: Vec<u32>,
}

fn load_forest(p: &str) -> Result<Forest> {
    let v: Value = serde_json::from_str(&fs::read_to_string(p)?)?;
    let mut nodes = Vec::new();
    let mut roots = Vec::new();
    fn add(n: &Value, nodes: &mut Vec<Node>) -> u32 {
        let id = nodes.len() as u32;
        if let Some(lv) = n.get("leaf_value") {
            nodes.push(Node {
                feat: u32::MAX,
                thr: lv.as_f64().unwrap(),
                left: 0,
                right: 0,
                default_left: true,
                missing: 0,
            });
            return id;
        }
        let missing = match n["missing_type"].as_str().unwrap_or("None") {
            "Zero" => 1,
            "NaN" => 2,
            _ => 0,
        };
        assert_eq!(
            n["decision_type"].as_str().unwrap_or("<="),
            "<=",
            "only numerical splits supported"
        );
        nodes.push(Node {
            feat: n["split_feature"].as_u64().unwrap() as u32,
            thr: n["threshold"].as_f64().unwrap(),
            left: 0,
            right: 0,
            default_left: n["default_left"].as_bool().unwrap_or(true),
            missing,
        });
        let l = add(&n["left_child"], nodes);
        let r = add(&n["right_child"], nodes);
        nodes[id as usize].left = l;
        nodes[id as usize].right = r;
        id
    }
    for t in v["tree_info"].as_array().context("tree_info")? {
        roots.push(add(&t["tree_structure"], &mut nodes));
    }
    Ok(Forest { nodes, roots })
}

impl Forest {
    #[inline]
    fn raw(&self, x: &[f32]) -> f64 {
        let mut s = 0f64;
        for &root in &self.roots {
            let mut i = root as usize;
            loop {
                let n = &self.nodes[i];
                if n.feat == u32::MAX {
                    s += n.thr;
                    break;
                }
                let v = x[n.feat as usize] as f64;
                let go_left = if v.is_nan() {
                    match n.missing {
                        2 => n.default_left,
                        1 => n.default_left,
                        _ => 0.0 <= n.thr,
                    }
                } else if n.missing == 1 && v == 0.0 {
                    n.default_left
                } else {
                    v <= n.thr
                };
                i = if go_left { n.left } else { n.right } as usize;
            }
        }
        s
    }
}

// ---------------------------------------------------------------- helpers

fn read_f64(p: &str) -> Result<Vec<f64>> {
    let b = fs::read(p).with_context(|| p.to_string())?;
    Ok(b.chunks_exact(8)
        .map(|c| f64::from_le_bytes(c.try_into().unwrap()))
        .collect())
}

fn write_bytes(p: &str, b: &[u8]) -> Result<()> {
    let tmp = format!("{p}.tmp");
    fs::write(&tmp, b)?;
    fs::rename(tmp, p)?;
    Ok(())
}

fn xy_to_rc(g: &Grid, x: f64, y: f64) -> Option<(usize, usize)> {
    let r = ((g.n - y) / g.res).floor();
    let c = ((x - g.w) / g.res).floor();
    (r >= 0.0 && c >= 0.0 && (r as usize) < g.height && (c as usize) < g.width)
        .then_some((r as usize, c as usize))
}

fn points_features(g: &Grid, ctx: &Ctx, xy: &[f64]) -> Vec<f32> {
    let n = xy.len() / 2;
    let mut out = vec![f32::NAN; n * F];
    out.par_chunks_mut(F).enumerate().for_each(|(i, o)| {
        if let Some((r, c)) = xy_to_rc(g, xy[2 * i], xy[2 * i + 1]) {
            ctx.point(r, c, o);
        }
    });
    out
}

// ---------------------------------------------------------------- commands

fn cmd_points(a: &[String]) -> Result<()> {
    let g = read_grid(&a[0])?;
    let ctx = build_context(&g)?;
    let xy = read_f64(&a[1])?;
    let t = Instant::now();
    let f = points_features(&g, &ctx, &xy);
    let bytes: Vec<u8> = f.iter().flat_map(|v| v.to_le_bytes()).collect();
    write_bytes(&a[2], &bytes)?;
    eprintln!(
        "[core] {} point features ({} each) in {:.2}s",
        xy.len() / 2,
        F,
        t.elapsed().as_secs_f32()
    );
    Ok(())
}

fn cmd_score(a: &[String]) -> Result<()> {
    let g = read_grid(&a[0])?;
    let forest = load_forest(&a[1])?;
    let ctx = build_context(&g)?;
    let xy = read_f64(&a[2])?;
    let f = points_features(&g, &ctx, &xy);
    let s: Vec<f64> = f
        .par_chunks(F)
        .map(|x| {
            if x[0].is_nan() {
                f64::NAN
            } else {
                forest.raw(x)
            }
        })
        .collect();
    write_bytes(
        &a[3],
        &s.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<u8>>(),
    )?;
    Ok(())
}

fn cmd_predict(a: &[String]) -> Result<()> {
    let g = read_grid(&a[0])?;
    let forest = load_forest(&a[1])?;
    let mut land = read_f64(&a[2])?;
    land.sort_by(|x, y| x.partial_cmp(y).unwrap());
    let ctx = build_context(&g)?;
    let t = Instant::now();
    let (h, w) = (g.height, g.width);
    let mut out = vec![255u8; h * w];
    out.par_chunks_mut(w).enumerate().for_each(|(r, orow)| {
        // column sums for the row, then a 5-wide horizontal window (same summation order as Ctx::point)
        let mut cs = vec![[0f32; B]; w];
        let mut cn = vec![0f32; w];
        for c in 0..w {
            cn[c] = ctx.colsum(r, c, &mut cs[c]);
        }
        let mut feat = vec![0f32; F];
        for c in 0..w {
            let mut loc = [0f32; B];
            let mut n = 0f32;
            for dc in -2i64..=2 {
                let cc = (c as i64 + dc).clamp(0, w as i64 - 1) as usize;
                n += cn[cc];
                for b in 0..B {
                    loc[b] += cs[cc][b];
                }
            }
            if !ctx.finish(r, c, &loc, n, &mut feat) {
                continue;
            }
            let s = forest.raw(&feat);
            let rank = land.partition_point(|&v| v < s) as f64 / land.len() as f64;
            orow[c] = (rank * 250.0).round() as u8;
        }
    });
    write_bytes(&a[3], &out)?;
    eprintln!(
        "[core] predicted {} px with {} trees in {:.1}s",
        h * w,
        forest.roots.len(),
        t.elapsed().as_secs_f32()
    );
    Ok(())
}

fn cmd_hotspots(a: &[String]) -> Result<()> {
    let g = read_grid(&a[0])?;
    let map = fs::read(&a[1])?;
    let thr: f64 = a[2].parse()?;
    let min_px: usize = a[3].parse()?;
    let (h, w) = (g.height, g.width);
    let t8 = (thr * 250.0).ceil() as u8;
    let hot = |i: usize| map[i] != 255 && map[i] >= t8;
    // union-find, 8-connectivity
    let mut parent: Vec<u32> = (0..(h * w) as u32).collect();
    fn find(p: &mut [u32], mut x: u32) -> u32 {
        while p[x as usize] != x {
            p[x as usize] = p[p[x as usize] as usize];
            x = p[x as usize];
        }
        x
    }
    for r in 0..h {
        for c in 0..w {
            let i = r * w + c;
            if !hot(i) {
                continue;
            }
            let mut nb = Vec::with_capacity(4);
            if c > 0 {
                nb.push(i - 1);
            }
            if r > 0 {
                nb.push(i - w);
                if c > 0 {
                    nb.push(i - w - 1);
                }
                if c + 1 < w {
                    nb.push(i - w + 1);
                }
            }
            for j in nb {
                if hot(j) {
                    let (a1, b1) = (find(&mut parent, i as u32), find(&mut parent, j as u32));
                    if a1 != b1 {
                        parent[a1.max(b1) as usize] = a1.min(b1);
                    }
                }
            }
        }
    }
    struct St {
        n: usize,
        sum: f64,
        max: u8,
        sr: f64,
        sc: f64,
    }
    let mut stats: std::collections::HashMap<u32, St> = std::collections::HashMap::new();
    let mut root_of = vec![u32::MAX; h * w];
    for i in 0..h * w {
        if hot(i) {
            let r = find(&mut parent, i as u32);
            root_of[i] = r;
            let e = stats.entry(r).or_insert(St {
                n: 0,
                sum: 0.0,
                max: 0,
                sr: 0.0,
                sc: 0.0,
            });
            e.n += 1;
            e.sum += map[i] as f64 / 250.0;
            e.max = e.max.max(map[i]);
            e.sr += (i / w) as f64;
            e.sc += (i % w) as f64;
        }
    }
    let mut keep: Vec<(u32, &St)> = stats
        .iter()
        .filter(|(_, s)| s.n >= min_px)
        .map(|(k, s)| (*k, s))
        .collect();
    keep.sort_by_key(|(k, _)| *k);
    let ids: std::collections::HashMap<u32, i32> = keep
        .iter()
        .enumerate()
        .map(|(i, (k, _))| (*k, i as i32 + 1))
        .collect();
    let labels: Vec<u8> = root_of
        .iter()
        .map(|r| {
            if *r == u32::MAX {
                0
            } else {
                *ids.get(r).unwrap_or(&0)
            }
        })
        .flat_map(|v: i32| v.to_le_bytes())
        .collect();
    write_bytes(&a[4], &labels)?;
    let mut f = fs::File::create(&a[5])?;
    writeln!(f, "hid,n_px,mean_rank,max_rank,cx,cy")?;
    for (k, s) in &keep {
        let (cr, cc) = (s.sr / s.n as f64 + 0.5, s.sc / s.n as f64 + 0.5);
        writeln!(
            f,
            "{},{},{:.4},{:.4},{:.1},{:.1}",
            ids[k],
            s.n,
            s.sum / s.n as f64,
            s.max as f64 / 250.0,
            g.w + cc * g.res,
            g.n - cr * g.res
        )?;
    }
    eprintln!(
        "[core] {} hotspots (>= {} px, rank >= {})",
        keep.len(),
        min_px,
        thr
    );
    Ok(())
}

/// Stratified random sample of validation pixels (Olofsson et al. 2014): strata are bins of the landscape
/// percentile, n_h pixels drawn uniformly without replacement in each (reservoir sampling, fixed seed).
fn cmd_strata(a: &[String]) -> Result<()> {
    let g = read_grid(&a[0])?;
    let map = fs::read(&a[1])?;
    let mut seed: u64 = a[3].parse::<u64>()?.max(1); // xorshift64 stays at 0 forever if seeded with 0
    let thr: Vec<f64> = a[4].split(',').map(|x| x.parse().unwrap()).collect();
    let nh: Vec<usize> = a[5].split(',').map(|x| x.parse().unwrap()).collect();
    if nh.len() != thr.len() + 1 {
        bail!(
            "need one sample size per stratum ({} strata)",
            thr.len() + 1
        );
    }
    let mut rnd = || {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        seed
    };
    let k = nh.len();
    let mut count = vec![0u64; k];
    let mut res: Vec<Vec<usize>> = nh.iter().map(|&n| Vec::with_capacity(n)).collect();
    for (i, &v) in map.iter().enumerate() {
        if v == 255 {
            continue;
        }
        let p = v as f64 / 250.0;
        let s = thr.iter().filter(|&&t| p >= t).count();
        count[s] += 1;
        if res[s].len() < nh[s] {
            res[s].push(i);
        } else {
            let j = (rnd() % count[s]) as usize;
            if j < nh[s] {
                res[s][j] = i;
            }
        }
    }
    let mut f = fs::File::create(&a[2])?;
    writeln!(f, "stratum,x,y,stratum_px")?;
    for s in 0..k {
        for &i in &res[s] {
            let (r, c) = (i / g.width, i % g.width);
            writeln!(
                f,
                "{},{:.1},{:.1},{}",
                s,
                g.w + (c as f64 + 0.5) * g.res,
                g.n - (r as f64 + 0.5) * g.res,
                count[s]
            )?;
        }
    }
    eprintln!("[core] strata px {:?}", count);
    Ok(())
}

/// Open tour from point 0 through all points: nearest neighbour, then 2-opt until no move shortens it.
/// Besides the classic exchange of two inner edges, the tail of the tour may be reversed (the end is free).
fn open_tour(p: &[f64]) -> (Vec<usize>, f64) {
    let n = p.len() / 2;
    if n == 0 {
        return (Vec::new(), 0.0);
    }
    let d = |i: usize, j: usize| {
        ((p[2 * i] - p[2 * j]).powi(2) + (p[2 * i + 1] - p[2 * j + 1]).powi(2)).sqrt()
    };
    let mut order = vec![0usize];
    let mut left: Vec<usize> = (1..n).collect();
    while !left.is_empty() {
        let last = *order.last().unwrap();
        let (k, _) = left
            .iter()
            .enumerate()
            .min_by(|a, b| d(last, *a.1).total_cmp(&d(last, *b.1)))
            .unwrap();
        order.push(left.swap_remove(k));
    }
    let mut improved = true;
    while improved {
        improved = false;
        for i in 1..n.saturating_sub(1) {
            for k in i + 1..n {
                let (a1, b1, c1) = (order[i - 1], order[i], order[k]);
                let gain = if k + 1 < n {
                    let d1 = order[k + 1];
                    d(a1, b1) + d(c1, d1) - d(a1, c1) - d(b1, d1)
                } else {
                    d(a1, b1) - d(a1, c1)
                };
                if gain > 1e-6 {
                    order[i..=k].reverse();
                    improved = true;
                }
            }
        }
    }
    let len = order.windows(2).map(|w2| d(w2[0], w2[1])).sum();
    (order, len)
}

fn cmd_route(a: &[String]) -> Result<()> {
    let (order, len) = open_tour(&read_f64(&a[0])?);
    let mut f = fs::File::create(&a[1])?;
    writeln!(f, "{len:.1}")?;
    for o in order {
        writeln!(f, "{o}")?;
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        bail!("usage: invaradar_core <points|predict|score|hotspots|route|strata> ...");
    }
    let t = Instant::now();
    let r = match args[1].as_str() {
        "points" => cmd_points(&args[2..]),
        "predict" => cmd_predict(&args[2..]),
        "score" => cmd_score(&args[2..]),
        "hotspots" => cmd_hotspots(&args[2..]),
        "route" => cmd_route(&args[2..]),
        "strata" => cmd_strata(&args[2..]),
        c => bail!("unknown command {c}"),
    };
    eprintln!(
        "[core] {} done in {:.1}s",
        args[1],
        t.elapsed().as_secs_f32()
    );
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rng(seed: &mut u64) -> f64 {
        *seed ^= *seed << 13;
        *seed ^= *seed >> 7;
        *seed ^= *seed << 17;
        (*seed >> 11) as f64 / (1u64 << 53) as f64
    }

    #[test]
    fn dequantization_matches_the_aef_formula() {
        let t = lut();
        assert_eq!(t[128], 0.0); // q = 0
        assert_eq!(t[0], 0.0); // q = -128 is no-data
        let hi = (127.0f32 / 127.5).powi(2);
        assert!((t[255] - hi).abs() < 1e-7);
        assert!((t[1] + hi).abs() < 1e-7);
        assert!(
            t.windows(2).skip(1).all(|w| w[0] <= w[1]),
            "monotonic for q > -128"
        );
    }

    #[test]
    fn edt_equals_brute_force() {
        let (h, w) = (37, 53);
        let mut s = 7u64;
        let mask: Vec<u8> = (0..h * w).map(|_| (rng(&mut s) < 0.03) as u8).collect();
        let d = edt(&mask, h, w, 10.0);
        let feats: Vec<(usize, usize)> = (0..h * w)
            .filter(|&i| mask[i] == 1)
            .map(|i| (i / w, i % w))
            .collect();
        for i in 0..h * w {
            let (r, c) = (i / w, i % w);
            let best = feats
                .iter()
                .map(|&(fr, fc)| {
                    ((fr as f64 - r as f64).powi(2) + (fc as f64 - c as f64).powi(2)).sqrt()
                })
                .fold(f64::INFINITY, f64::min);
            assert!(
                (d[i] as f64 - best * 10.0).abs() < 1e-2,
                "pixel {i}: {} vs {}",
                d[i],
                best * 10.0
            );
        }
    }

    #[test]
    fn priority_flood_fills_pits_and_drains_everything() {
        // a bowl with a pit in the centre and a lower notch on the east edge
        let (h, w) = (21, 21);
        let mut z = vec![0f32; h * w];
        for r in 0..h {
            for c in 0..w {
                let (dr, dc) = (r as f32 - 10.0, c as f32 - 10.0);
                z[r * w + c] = 100.0 + (dr * dr + dc * dc).sqrt();
            }
        }
        z[10 * w + 10] = 90.0; // pit below everything around it
        z[10 * w + 20] = 95.0; // outlet
        let f = fill_depressions(&z, h, w);
        assert!(
            f.iter().zip(&z).all(|(a, b)| a >= b),
            "filling never lowers the surface"
        );
        assert!(
            f[10 * w + 10] > 100.0,
            "the pit is raised to its spill level"
        );
        for r in 1..h - 1 {
            for c in 1..w - 1 {
                let i = r * w + c;
                let lower = NB8.iter().any(|&(dr, dc, _)| {
                    f[(r as i64 + dr) as usize * w + (c as i64 + dc) as usize] < f[i]
                });
                assert!(lower, "cell ({r},{c}) has no lower neighbour after filling");
            }
        }
    }

    #[test]
    fn terrain_on_a_tilted_valley() {
        // V-shaped valley draining north: z = 0.1*|c - 25| + 0.01*r, 10 m cells
        let (h, w, res) = (120, 51, 10.0);
        let z: Vec<f32> = (0..h * w)
            .map(|i| 0.1 * ((i % w) as f32 - 25.0).abs() + 0.01 * (i / w) as f32)
            .collect();
        let t = terrain(&z, h, w, res);
        let px = |r: usize, c: usize, k: usize| t[(r * w + c) * NTER + k];
        // slope on the valley side: atan(sqrt(0.01^2 + 0.001^2)) ≈ 0.574 deg
        let expect = ((0.1f32 / res).powi(2) + (0.01f32 / res).powi(2))
            .sqrt()
            .atan()
            .to_degrees();
        assert!(
            (px(60, 10, 1) - expect).abs() < 0.02,
            "slope {}",
            px(60, 10, 1)
        );
        // TWI grows towards the valley floor, HAND grows away from it
        assert!(px(60, 25, 2) > px(60, 5, 2));
        assert!(px(60, 5, 3) >= px(60, 15, 3) && px(60, 15, 3) >= px(60, 24, 3));
        assert!(t.chunks(NTER).all(|o| o[3] >= 0.0 && o[2].is_finite()));
    }

    #[test]
    fn forest_follows_lightgbm_missing_rules() {
        let js = r#"{"tree_info":[{"tree_structure":{"split_feature":0,"threshold":0.5,"decision_type":"<=",
            "default_left":false,"missing_type":"NaN","left_child":{"leaf_value":1.0},
            "right_child":{"leaf_value":-1.0}}}]}"#;
        let p = std::env::temp_dir().join("invaradar_forest_test.json");
        fs::write(&p, js).unwrap();
        let f = load_forest(p.to_str().unwrap()).unwrap();
        assert_eq!(f.raw(&[0.2]), 1.0);
        assert_eq!(f.raw(&[0.9]), -1.0);
        assert_eq!(
            f.raw(&[f32::NAN]),
            -1.0,
            "NaN goes to the default (right) branch"
        );
    }

    #[test]
    fn two_opt_untangles_and_never_loses_to_nearest_neighbour() {
        // points on a zig-zag where greedy NN crosses itself
        let mut s = 11u64;
        let pts: Vec<f64> = (0..60)
            .flat_map(|_| [rng(&mut s) * 1000.0, rng(&mut s) * 1000.0])
            .collect();
        let (order, len) = open_tour(&pts);
        assert_eq!(order[0], 0);
        let mut seen = order.clone();
        seen.sort();
        assert_eq!(seen, (0..60).collect::<Vec<_>>());
        // no 2-opt move left
        let d = |i: usize, j: usize| {
            ((pts[2 * i] - pts[2 * j]).powi(2) + (pts[2 * i + 1] - pts[2 * j + 1]).powi(2)).sqrt()
        };
        for i in 1..59 {
            for k in i + 1..59 {
                let g = d(order[i - 1], order[i]) + d(order[k], order[k + 1])
                    - d(order[i - 1], order[k])
                    - d(order[i], order[k + 1]);
                assert!(g <= 1e-6);
            }
        }
        assert!(len > 0.0);
        assert_eq!(open_tour(&[]).0.len(), 0);
        assert_eq!(open_tour(&[1.0, 2.0]), (vec![0], 0.0));
    }
}
