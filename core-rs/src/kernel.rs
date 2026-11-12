//! Bit-exact kernels for this machine's ISA.
//!
//! The host we tune for is an Intel Xeon (family 6, model 207: Emerald Rapids / Raptor Cove),
//! 4 physical cores, no hyper-threads, 48 KiB L1d and 2 MiB L2 per core, AVX-512F/BW/VL and
//! AVX2. Transparent huge pages are `madvise`, so large rasters ask for them explicitly.
//! `target-cpu=native` in `.cargo/config.toml` schedules the scalar code for that chip.
//! The vector paths below are selected at run time and compiled with `target_feature`, so a
//! core without AVX-512 still runs the AVX2 or scalar copy.
//!
//! Each of the 64 embedding bands is an independent sum. A lane therefore does the same
//! IEEE addition, in the same band order, as the scalar loop. Thresholds stay f64.
//! Promotion of a feature from f32 to f64 uses the same conversion as `as f64`.

#![allow(unsafe_op_in_unsafe_fn)]

use std::sync::Once;

pub const SCALAR: u8 = 1;
pub const AVX2: u8 = 2;
pub const AVX512: u8 = 3;

pub fn selected_isa() -> u8 {
    #[cfg(target_arch = "x86_64")]
    {
        if std::is_x86_feature_detected!("avx512f") {
            return AVX512;
        }
        if std::is_x86_feature_detected!("avx2") {
            return AVX2;
        }
    }
    SCALAR
}

/// Pin one rayon worker to one core and ask the kernel for huge pages on later allocations.
pub fn init() {
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        let n = std::thread::available_parallelism()
            .map(|p| p.get())
            .unwrap_or(1);
        let built = rayon::ThreadPoolBuilder::new()
            .num_threads(n)
            .start_handler(move |i| pin_current(i % n))
            .build_global();
        if built.is_err() {
            eprintln!("[core] rayon pool was already running; threads were not pinned");
        }
        eprintln!(
            "[core] {n} cores, isa {} (1 scalar, 2 avx2, 3 avx-512), workers pinned to cores",
            selected_isa()
        );
    });
}

fn pin_current(core: usize) {
    #[cfg(target_os = "linux")]
    unsafe {
        // 1024 CPUs, the Linux default for cpu_set_t.
        let mut bits = [0u64; 16];
        bits[core / 64] |= 1u64 << (core % 64);
        unsafe extern "C" {
            fn sched_setaffinity(pid: i32, cpusetsize: usize, mask: *const u64) -> i32;
        }
        sched_setaffinity(0, std::mem::size_of_val(&bits), bits.as_ptr());
    }
}

/// `MADV_HUGEPAGE`. No effect where the kernel is not in madvise mode, and never changes values.
pub fn advise_huge<T>(v: &[T]) {
    #[cfg(target_os = "linux")]
    {
        let len = std::mem::size_of_val(v);
        if v.is_empty() || len < 2 * 1024 * 1024 {
            return;
        }
        unsafe extern "C" {
            fn madvise(addr: *mut std::ffi::c_void, len: usize, advice: i32) -> i32;
        }
        const MADV_HUGEPAGE: i32 = 14;
        unsafe {
            madvise(v.as_ptr() as *mut std::ffi::c_void, len, MADV_HUGEPAGE);
        }
    }
}

#[inline(always)]
pub fn zero_bands<const ISA: u8>(acc: &mut [f32]) {
    debug_assert_eq!(acc.len(), 64);
    match ISA {
        AVX512 => unsafe { zero_avx512(acc) },
        AVX2 => unsafe { zero_avx2(acc) },
        _ => acc.fill(0.0),
    }
}

#[inline(always)]
pub fn accum_dequant<const ISA: u8>(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    debug_assert_eq!(acc.len(), 64);
    debug_assert_eq!(raw.len(), 64);
    match ISA {
        AVX512 => unsafe { accum_dequant_avx512(acc, raw, lut) },
        AVX2 => unsafe { accum_dequant_avx2(acc, raw, lut) },
        _ => accum_dequant_scalar(acc, raw, lut),
    }
}

#[inline(always)]
pub fn accum_bands<const ISA: u8>(acc: &mut [f32], src: &[f32]) {
    debug_assert_eq!(acc.len(), 64);
    debug_assert_eq!(src.len(), 64);
    match ISA {
        AVX512 => unsafe { accum_bands_avx512(acc, src) },
        AVX2 => unsafe { accum_bands_avx2(acc, src) },
        _ => {
            for b in 0..64 {
                acc[b] += src[b];
            }
        }
    }
}

#[inline(always)]
pub fn store_dequant<const ISA: u8>(dst: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    debug_assert_eq!(dst.len(), 64);
    debug_assert_eq!(raw.len(), 64);
    match ISA {
        AVX512 => unsafe { store_dequant_avx512(dst, raw, lut) },
        AVX2 => unsafe { store_dequant_avx2(dst, raw, lut) },
        _ => {
            for b in 0..64 {
                dst[b] = lut[(raw[b] as i16 + 128) as usize];
            }
        }
    }
}

/// `dst[b] = src[b] / n` when n > 0, else 0. Division, not a reciprocal multiply.
#[inline(always)]
pub fn store_div<const ISA: u8>(dst: &mut [f32], src: &[f32], n: f32) {
    debug_assert_eq!(dst.len(), 64);
    debug_assert_eq!(src.len(), 64);
    if n == 0.0 {
        zero_bands::<ISA>(dst);
        return;
    }
    match ISA {
        AVX512 => unsafe { store_div_avx512(dst, src, n) },
        AVX2 => unsafe { store_div_avx2(dst, src, n) },
        _ => {
            for b in 0..64 {
                dst[b] = src[b] / n;
            }
        }
    }
}

#[inline(always)]
pub fn promote<const ISA: u8>(src: &[f32], dst: &mut [f64]) {
    debug_assert_eq!(src.len(), dst.len());
    match ISA {
        AVX512 => unsafe { promote_avx512(src, dst) },
        AVX2 => unsafe { promote_avx(src, dst) },
        _ => {
            for i in 0..src.len() {
                dst[i] = src[i] as f64;
            }
        }
    }
}

fn accum_dequant_scalar(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    for b in 0..64 {
        acc[b] += lut[(raw[b] as i16 + 128) as usize];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn zero_avx512(acc: &mut [f32]) {
    use std::arch::x86_64::*;
    let z = _mm512_setzero_ps();
    for k in (0..64).step_by(16) {
        _mm512_storeu_ps(acc.as_mut_ptr().add(k), z);
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn zero_avx512(acc: &mut [f32]) {
    acc.fill(0.0);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn zero_avx2(acc: &mut [f32]) {
    use std::arch::x86_64::*;
    let z = _mm256_setzero_ps();
    for k in (0..64).step_by(8) {
        _mm256_storeu_ps(acc.as_mut_ptr().add(k), z);
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn zero_avx2(acc: &mut [f32]) {
    acc.fill(0.0);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn accum_dequant_avx512(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    use std::arch::x86_64::*;
    let add = _mm512_set1_epi32(128);
    for lane in 0..4 {
        let chunk = _mm_loadu_si128(raw.as_ptr().add(lane * 16).cast());
        let idx = _mm512_add_epi32(_mm512_cvtepi8_epi32(chunk), add);
        let g = _mm512_i32gather_ps::<4>(idx, lut.as_ptr().cast());
        let old = _mm512_loadu_ps(acc.as_ptr().add(lane * 16));
        _mm512_storeu_ps(acc.as_mut_ptr().add(lane * 16), _mm512_add_ps(old, g));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn accum_dequant_avx512(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    accum_dequant_scalar(acc, raw, lut);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn accum_dequant_avx2(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    use std::arch::x86_64::*;
    let add = _mm256_set1_epi32(128);
    for k in (0..64).step_by(8) {
        let bytes = _mm_loadl_epi64(raw.as_ptr().add(k).cast());
        let idx = _mm256_add_epi32(_mm256_cvtepi8_epi32(bytes), add);
        let g = _mm256_i32gather_ps::<4>(lut.as_ptr(), idx);
        let old = _mm256_loadu_ps(acc.as_ptr().add(k));
        _mm256_storeu_ps(acc.as_mut_ptr().add(k), _mm256_add_ps(old, g));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn accum_dequant_avx2(acc: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    accum_dequant_scalar(acc, raw, lut);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn accum_bands_avx512(acc: &mut [f32], src: &[f32]) {
    use std::arch::x86_64::*;
    for k in (0..64).step_by(16) {
        let a = _mm512_loadu_ps(acc.as_ptr().add(k));
        let b = _mm512_loadu_ps(src.as_ptr().add(k));
        _mm512_storeu_ps(acc.as_mut_ptr().add(k), _mm512_add_ps(a, b));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn accum_bands_avx512(acc: &mut [f32], src: &[f32]) {
    for b in 0..64 {
        acc[b] += src[b];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn accum_bands_avx2(acc: &mut [f32], src: &[f32]) {
    use std::arch::x86_64::*;
    for k in (0..64).step_by(8) {
        let a = _mm256_loadu_ps(acc.as_ptr().add(k));
        let b = _mm256_loadu_ps(src.as_ptr().add(k));
        _mm256_storeu_ps(acc.as_mut_ptr().add(k), _mm256_add_ps(a, b));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn accum_bands_avx2(acc: &mut [f32], src: &[f32]) {
    for b in 0..64 {
        acc[b] += src[b];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn store_dequant_avx512(dst: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    use std::arch::x86_64::*;
    let add = _mm512_set1_epi32(128);
    for lane in 0..4 {
        let chunk = _mm_loadu_si128(raw.as_ptr().add(lane * 16).cast());
        let idx = _mm512_add_epi32(_mm512_cvtepi8_epi32(chunk), add);
        let g = _mm512_i32gather_ps::<4>(idx, lut.as_ptr().cast());
        _mm512_storeu_ps(dst.as_mut_ptr().add(lane * 16), g);
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn store_dequant_avx512(dst: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    for b in 0..64 {
        dst[b] = lut[(raw[b] as i16 + 128) as usize];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn store_dequant_avx2(dst: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    use std::arch::x86_64::*;
    let add = _mm256_set1_epi32(128);
    for k in (0..64).step_by(8) {
        let bytes = _mm_loadl_epi64(raw.as_ptr().add(k).cast());
        let idx = _mm256_add_epi32(_mm256_cvtepi8_epi32(bytes), add);
        let g = _mm256_i32gather_ps::<4>(lut.as_ptr(), idx);
        _mm256_storeu_ps(dst.as_mut_ptr().add(k), g);
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn store_dequant_avx2(dst: &mut [f32], raw: &[i8], lut: &[f32; 256]) {
    for b in 0..64 {
        dst[b] = lut[(raw[b] as i16 + 128) as usize];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn store_div_avx512(dst: &mut [f32], src: &[f32], n: f32) {
    use std::arch::x86_64::*;
    let d = _mm512_set1_ps(n);
    for k in (0..64).step_by(16) {
        let a = _mm512_loadu_ps(src.as_ptr().add(k));
        _mm512_storeu_ps(dst.as_mut_ptr().add(k), _mm512_div_ps(a, d));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn store_div_avx512(dst: &mut [f32], src: &[f32], n: f32) {
    for b in 0..64 {
        dst[b] = src[b] / n;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn store_div_avx2(dst: &mut [f32], src: &[f32], n: f32) {
    use std::arch::x86_64::*;
    let d = _mm256_set1_ps(n);
    for k in (0..64).step_by(8) {
        let a = _mm256_loadu_ps(src.as_ptr().add(k));
        _mm256_storeu_ps(dst.as_mut_ptr().add(k), _mm256_div_ps(a, d));
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn store_div_avx2(dst: &mut [f32], src: &[f32], n: f32) {
    for b in 0..64 {
        dst[b] = src[b] / n;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx512f")]
unsafe fn promote_avx512(src: &[f32], dst: &mut [f64]) {
    use std::arch::x86_64::*;
    let n = src.len() / 8 * 8;
    let mut i = 0;
    while i < n {
        let p = _mm256_loadu_ps(src.as_ptr().add(i));
        let d = _mm512_cvtps_pd(p);
        _mm512_storeu_pd(dst.as_mut_ptr().add(i), d);
        i += 8;
    }
    while i < src.len() {
        dst[i] = src[i] as f64;
        i += 1;
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn promote_avx512(src: &[f32], dst: &mut [f64]) {
    for i in 0..src.len() {
        dst[i] = src[i] as f64;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx")]
unsafe fn promote_avx(src: &[f32], dst: &mut [f64]) {
    use std::arch::x86_64::*;
    let n = src.len() / 4 * 4;
    let mut i = 0;
    while i < n {
        let p = _mm_loadu_ps(src.as_ptr().add(i));
        let d = _mm256_cvtps_pd(p);
        _mm256_storeu_pd(dst.as_mut_ptr().add(i), d);
        i += 4;
    }
    while i < src.len() {
        dst[i] = src[i] as f64;
        i += 1;
    }
}

#[cfg(not(target_arch = "x86_64"))]
unsafe fn promote_avx(src: &[f32], dst: &mut [f64]) {
    for i in 0..src.len() {
        dst[i] = src[i] as f64;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lut() -> [f32; 256] {
        let mut t = [0f32; 256];
        for (i, v) in t.iter_mut().enumerate() {
            let q = i as f32 - 128.0;
            *v = q.signum() * (q / 127.5) * (q / 127.5);
        }
        t[0] = 0.0;
        t
    }

    fn sample_raw(seed: u64) -> [i8; 64] {
        let mut s = seed;
        let mut raw = [0i8; 64];
        for b in &mut raw {
            s = s.wrapping_mul(6364136223846793005).wrapping_add(1);
            *b = (s >> 33) as u8 as i8;
        }
        raw
    }

    #[test]
    fn vector_dequant_matches_scalar_bits() {
        let lut = lut();
        for seed in [1u64, 2, 9, 42, u64::MAX] {
            let raw = sample_raw(seed);
            let mut scalar = [0f32; 64];
            accum_dequant_scalar(&mut scalar, &raw, &lut);
            if std::is_x86_feature_detected!("avx2") {
                let mut got = [0f32; 64];
                unsafe { accum_dequant_avx2(&mut got, &raw, &lut) };
                for b in 0..64 {
                    assert_eq!(got[b].to_bits(), scalar[b].to_bits(), "avx2 band {b}");
                }
                let mut stored = [1f32; 64];
                unsafe { store_dequant_avx2(&mut stored, &raw, &lut) };
                for b in 0..64 {
                    assert_eq!(stored[b].to_bits(), scalar[b].to_bits(), "store avx2 {b}");
                }
            }
            if std::is_x86_feature_detected!("avx512f") {
                let mut got = [0f32; 64];
                unsafe { accum_dequant_avx512(&mut got, &raw, &lut) };
                for b in 0..64 {
                    assert_eq!(got[b].to_bits(), scalar[b].to_bits(), "avx512 band {b}");
                }
            }
        }
    }

    #[test]
    fn vector_add_div_and_promote_match_scalar_bits() {
        let mut src = [0f32; 64];
        let mut add = [0f32; 64];
        for b in 0..64 {
            src[b] = (b as f32 - 30.0) * 0.125;
            add[b] = (b as f32) * -0.5;
        }
        src[3] = f32::NAN;
        src[4] = f32::INFINITY;
        src[5] = -0.0;
        let mut scalar = add;
        for b in 0..64 {
            scalar[b] += src[b];
        }
        if std::is_x86_feature_detected!("avx512f") {
            let mut got = add;
            unsafe { accum_bands_avx512(&mut got, &src) };
            for b in 0..64 {
                assert_eq!(got[b].to_bits(), scalar[b].to_bits(), "add {b}");
            }
            let mut div = [0f32; 64];
            let mut expect = [0f32; 64];
            unsafe { store_div_avx512(&mut div, &src, 3.0) };
            for b in 0..64 {
                expect[b] = src[b] / 3.0;
                if src[b].is_nan() {
                    assert!(div[b].is_nan());
                } else {
                    assert_eq!(div[b].to_bits(), expect[b].to_bits(), "div {b}");
                }
            }
            let wide = {
                let mut s = [0f32; 265];
                for i in 0..265 {
                    s[i] = (i as f32 - 100.0) * 0.01;
                }
                s[0] = f32::NAN;
                s[1] = f32::NEG_INFINITY;
                s[264] = -0.0;
                s
            };
            let mut dst = [0f64; 265];
            unsafe { promote_avx512(&wide, &mut dst) };
            for i in 0..265 {
                let e = wide[i] as f64;
                if wide[i].is_nan() {
                    assert!(dst[i].is_nan(), "promote {i}");
                } else {
                    assert_eq!(dst[i].to_bits(), e.to_bits(), "promote {i}");
                }
            }
        }
    }
}
