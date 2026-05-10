"""
LUT-based texture recoloring.

Applies a 3D LUT (.cube file) to all color/diffuse textures in a project folder,
skipping non-color maps (normals, masks, roughness, AO, height, emissive, etc.)
and any image that is grayscale.

Supports input formats:
    .dds   : DXT1 (BC1), DXT5 (BC3), BGRA8
    .tex   : same formats via TexConverter round-trip

Output is always written as BGRA8 (uncompressed) DDS / TEX with full mip chain
(box-filter downsampled). Originals are moved to a `_lut_backup/` mirror folder
beside the project root before being overwritten.
"""
from __future__ import annotations

import os
import re
import struct
import shutil
from typing import Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Filename-based skip rules (color suffixes are RE-COLORED; these are SKIPPED)
# ---------------------------------------------------------------------------

SKIP_TOKENS = {
    # Normal / bump maps
    "normal", "normals", "nrm", "norm", "bump",
    # Masks
    "mask", "msk", "masks",
    # Roughness / metallic
    "rgh", "roughness", "rough",
    "metal", "metallic", "metalness",
    # Specular
    "spec", "specular",
    # AO / ambient
    "ao", "ambient", "occlusion",
    # Height / displacement
    "height", "displacement", "disp",
    # Emissive
    "emissive", "emit", "glow", "emis",
    # Alpha / opacity
    "opacity", "alpha", "transparency",
    # Lightmap
    "lightmap", "lm",
    # Misc non-color data
    "noise",
    "data", "info",
    "ramp",
}

# Mip-prefix patterns (e.g. `2x_`, `4x_`) are stripped before token check.
_MIP_PREFIX_RX = re.compile(r"^\d+x_", re.IGNORECASE)


def should_skip_by_name(filename: str) -> bool:
    """Return True when the filename's stem contains a non-color suffix token."""
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    stem = _MIP_PREFIX_RX.sub("", stem)
    # Split on underscores; check each segment
    for seg in stem.split("_"):
        if seg in SKIP_TOKENS:
            return True
    return False


# ---------------------------------------------------------------------------
# .cube LUT parser
# ---------------------------------------------------------------------------

def parse_cube(path: str):
    """Parse a .cube LUT. Returns (size, lut[r,g,b]→RGB float32, dmin, dmax)."""
    size = None
    dmin = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    dmax = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    rows: list[list[float]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            up = s.upper()
            if up.startswith("LUT_3D_SIZE"):
                size = int(s.split()[1])
            elif up.startswith("LUT_1D_SIZE"):
                raise ValueError("1D LUTs are not supported")
            elif up.startswith("DOMAIN_MIN"):
                dmin = np.array([float(x) for x in s.split()[1:4]], dtype=np.float32)
            elif up.startswith("DOMAIN_MAX"):
                dmax = np.array([float(x) for x in s.split()[1:4]], dtype=np.float32)
            elif up.startswith("TITLE") or up.startswith("LUT_"):
                continue
            else:
                parts = s.split()
                if len(parts) >= 3:
                    try:
                        rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        pass
    if size is None:
        raise ValueError("Missing LUT_3D_SIZE in .cube file")
    arr = np.asarray(rows, dtype=np.float32)
    if arr.shape[0] != size ** 3:
        raise ValueError(f"Expected {size ** 3} LUT entries, got {arr.shape[0]}")
    # .cube row order: R varies fastest, then G, then B
    # arr[ b*s*s + g*s + r ] = (R, G, B)
    # → reshape gives lut[b, g, r, 3]; transpose to lut[r, g, b, 3]
    lut = arr.reshape((size, size, size, 3)).transpose(2, 1, 0, 3).copy()
    # Precompute a 256³ baked LUT (uint8) so per-texture recoloring becomes a
    # single fancy-index gather instead of trilinear interpolation per pixel.
    # 256³ × 3 bytes = 50 MB — paid once per LUT load, amortized over a whole
    # project's textures. Falls back to None on memory errors.
    try:
        lut256 = _bake_lut256(size, lut, dmin, dmax)
    except MemoryError:
        lut256 = None
    return size, lut, dmin, dmax, lut256


def _bake_lut256(size: int, lut: np.ndarray,
                 dmin: np.ndarray, dmax: np.ndarray) -> np.ndarray:
    """Pre-bake the LUT into a (256, 256, 256, 3) uint8 table.

    Built one R-slice at a time to bound peak memory at ~3 MB of intermediates.
    """
    out = np.empty((256, 256, 256, 3), dtype=np.uint8)
    levels = np.arange(256, dtype=np.float32) / 255.0
    gg, bb = np.meshgrid(levels, levels, indexing='ij')      # (256,256)
    plane = np.empty((256 * 256, 3), dtype=np.float32)
    plane[:, 1] = gg.ravel()
    plane[:, 2] = bb.ravel()
    extent = (dmax - dmin)
    extent = np.where(extent == 0, 1.0, extent).astype(np.float32)
    lut_flat = np.ascontiguousarray(lut.reshape(size * size * size, 3)).astype(np.float32, copy=False)
    for r in range(256):
        plane[:, 0] = levels[r]
        sampled = _apply_lut_chunk(plane, size, lut_flat, dmin, extent)
        out[r] = (np.clip(sampled, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).reshape(256, 256, 3)
    return out


def _apply_lut_chunk(rgb: np.ndarray, size: int, lut_flat: np.ndarray,
                     dmin: np.ndarray, extent: np.ndarray) -> np.ndarray:
    """Trilinear LUT sample for a flat (M, 3) chunk; returns (M, 3) float32."""
    norm = np.clip((rgb - dmin) / extent, 0.0, 1.0)
    coords = norm * (size - 1)
    i0 = coords.astype(np.int32)             # floor (non-negative)
    i1 = np.minimum(i0 + 1, size - 1)
    f = coords - i0.astype(np.float32)

    r0 = i0[:, 0]; g0 = i0[:, 1]; b0 = i0[:, 2]
    r1 = i1[:, 0]; g1 = i1[:, 1]; b1 = i1[:, 2]
    s2 = size * size
    # Flat indices into lut_flat (size**3, 3). Computed with int32 strides.
    base000 = r0 * s2 + g0 * size + b0
    base001 = base000 + 1                         # b1 = b0+1 (clipped via take)
    # Use take with separate flat indices for each corner.
    idx000 = r0 * s2 + g0 * size + b0
    idx100 = r1 * s2 + g0 * size + b0
    idx010 = r0 * s2 + g1 * size + b0
    idx110 = r1 * s2 + g1 * size + b0
    idx001 = r0 * s2 + g0 * size + b1
    idx101 = r1 * s2 + g0 * size + b1
    idx011 = r0 * s2 + g1 * size + b1
    idx111 = r1 * s2 + g1 * size + b1

    fr = f[:, 0:1]; fg = f[:, 1:2]; fb = f[:, 2:3]
    one_fr = 1.0 - fr; one_fg = 1.0 - fg; one_fb = 1.0 - fb

    # Pairwise blend along R axis (4 lookups + 4 muls each)
    c00 = lut_flat[idx000] * one_fr + lut_flat[idx100] * fr
    c10 = lut_flat[idx010] * one_fr + lut_flat[idx110] * fr
    c01 = lut_flat[idx001] * one_fr + lut_flat[idx101] * fr
    c11 = lut_flat[idx011] * one_fr + lut_flat[idx111] * fr
    # Blend along G
    c0 = c00 * one_fg + c10 * fg
    c1 = c01 * one_fg + c11 * fg
    # Blend along B
    return c0 * one_fb + c1 * fb


def apply_lut_rgb(rgb: np.ndarray, size: int, lut: np.ndarray,
                  dmin: np.ndarray, dmax: np.ndarray) -> np.ndarray:
    """Apply trilinear-sampled 3D LUT to an RGB float32 array in [0,1].

    Operates in cache-friendly chunks to avoid the ~200 MB float32 intermediate
    burst that a full-image vectorized version produces on large textures.
    """
    extent = dmax - dmin
    extent = np.where(extent == 0, 1.0, extent).astype(np.float32)
    lut_flat = np.ascontiguousarray(lut.reshape(size * size * size, 3)).astype(np.float32, copy=False)
    flat = rgb.reshape(-1, 3)
    out = np.empty_like(flat, dtype=np.float32)
    CHUNK = 262144  # ~3 MB per chunk for intermediates -> stays in L2/L3
    for i in range(0, flat.shape[0], CHUNK):
        j = min(i + CHUNK, flat.shape[0])
        out[i:j] = _apply_lut_chunk(flat[i:j], size, lut_flat, dmin, extent)
    return out.reshape(rgb.shape)


# ---------------------------------------------------------------------------
# DDS / BC decoders (vectorized) → BGRA8 numpy array
# ---------------------------------------------------------------------------

def _rgb565_to_rgb888(c: np.ndarray):
    """c: uint16 array → (r,g,b) uint8 arrays."""
    r = ((c >> 11) & 0x1F).astype(np.uint16) * 527 + 23 >> 6  # accurate scale
    g = ((c >> 5) & 0x3F).astype(np.uint16) * 259 + 33 >> 6
    b = (c & 0x1F).astype(np.uint16) * 527 + 23 >> 6
    return r.astype(np.uint8), g.astype(np.uint8), b.astype(np.uint8)


def decode_bc1(data: bytes, width: int, height: int) -> np.ndarray:
    """Decode BC1/DXT1 block-compressed data to BGRA8 array shape (h,w,4)."""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    blocks = np.frombuffer(data[: bw * bh * 8], dtype=np.uint8).reshape(bh * bw, 8)
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    r0, g0, b0 = _rgb565_to_rgb888(c0)
    r1, g1, b1 = _rgb565_to_rgb888(c1)

    # Build palette: (num_blocks, 4 entries, 4 channels BGRA)
    palette = np.zeros((blocks.shape[0], 4, 4), dtype=np.uint8)
    palette[:, 0, 0] = b0; palette[:, 0, 1] = g0; palette[:, 0, 2] = r0; palette[:, 0, 3] = 255
    palette[:, 1, 0] = b1; palette[:, 1, 1] = g1; palette[:, 1, 2] = r1; palette[:, 1, 3] = 255

    # 4-color mode: c0 > c1
    mask4 = c0 > c1
    # In 4-color mode: c2 = (2*c0 + c1)/3, c3 = (c0 + 2*c1)/3
    # NOTE: cast BOTH operands to uint16. Under NumPy 2.x NEP-50 promotion,
    # `2 * uint8(x)` stays uint8 and overflows for x > 127, producing wildly
    # wrong palette entries.
    b0_16 = b0[mask4].astype(np.uint16); b1_16 = b1[mask4].astype(np.uint16)
    g0_16 = g0[mask4].astype(np.uint16); g1_16 = g1[mask4].astype(np.uint16)
    r0_16 = r0[mask4].astype(np.uint16); r1_16 = r1[mask4].astype(np.uint16)
    palette[mask4, 2, 0] = (2 * b0_16 + b1_16) // 3
    palette[mask4, 2, 1] = (2 * g0_16 + g1_16) // 3
    palette[mask4, 2, 2] = (2 * r0_16 + r1_16) // 3
    palette[mask4, 2, 3] = 255
    palette[mask4, 3, 0] = (b0_16 + 2 * b1_16) // 3
    palette[mask4, 3, 1] = (g0_16 + 2 * g1_16) // 3
    palette[mask4, 3, 2] = (r0_16 + 2 * r1_16) // 3
    palette[mask4, 3, 3] = 255
    # 3-color + alpha mode
    m3 = ~mask4
    b0_16 = b0[m3].astype(np.uint16); b1_16 = b1[m3].astype(np.uint16)
    g0_16 = g0[m3].astype(np.uint16); g1_16 = g1[m3].astype(np.uint16)
    r0_16 = r0[m3].astype(np.uint16); r1_16 = r1[m3].astype(np.uint16)
    palette[m3, 2, 0] = (b0_16 + b1_16) // 2
    palette[m3, 2, 1] = (g0_16 + g1_16) // 2
    palette[m3, 2, 2] = (r0_16 + r1_16) // 2
    palette[m3, 2, 3] = 255
    palette[m3, 3] = 0  # transparent black

    # Indices: 4 bytes per block = 16 × 2-bit indices
    idx_bytes = blocks[:, 4:8].astype(np.uint32)
    idx_word = idx_bytes[:, 0] | (idx_bytes[:, 1] << 8) | (idx_bytes[:, 2] << 16) | (idx_bytes[:, 3] << 24)
    # Per-pixel index, shape (num_blocks, 16)
    shifts = np.arange(16, dtype=np.uint32) * 2
    idx_per_pixel = (idx_word[:, None] >> shifts) & 0x3
    # Reshape to (num_blocks, 4, 4) – index 0 = top-left, runs left→right then top→bottom
    idx_per_pixel = idx_per_pixel.reshape(blocks.shape[0], 4, 4)

    # Look up palette: out shape (num_blocks, 4, 4, 4)
    out_blocks = palette[np.arange(blocks.shape[0])[:, None, None], idx_per_pixel]

    # Reassemble image: blocks arranged in row-major (bh × bw)
    out_blocks = out_blocks.reshape(bh, bw, 4, 4, 4)
    full = out_blocks.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return full[:height, :width, :].copy()


def decode_bc3(data: bytes, width: int, height: int) -> np.ndarray:
    """Decode BC3/DXT5 block-compressed data to BGRA8 array."""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    nblocks = bh * bw
    blocks = np.frombuffer(data[: nblocks * 16], dtype=np.uint8).reshape(nblocks, 16)
    color_data = blocks[:, 8:16].tobytes()
    rgba = decode_bc1(color_data, bw * 4, bh * 4)  # safe – decoder works in block units
    # Rebuild BC1 result without crop, into block layout
    rgba = rgba[: bh * 4, : bw * 4, :].reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).copy()

    # --- decode alpha block --------------------------------------------------
    a0 = blocks[:, 0]; a1 = blocks[:, 1]
    palette_a = np.zeros((nblocks, 8), dtype=np.uint16)
    palette_a[:, 0] = a0; palette_a[:, 1] = a1
    m8 = a0 > a1
    # 8-alpha mode (cast a0/a1 to uint16 before multiplying to avoid uint8
    # overflow under NEP-50 promotion).
    a0_8 = a0[m8].astype(np.uint16); a1_8 = a1[m8].astype(np.uint16)
    palette_a[m8, 2] = (6 * a0_8 + 1 * a1_8) // 7
    palette_a[m8, 3] = (5 * a0_8 + 2 * a1_8) // 7
    palette_a[m8, 4] = (4 * a0_8 + 3 * a1_8) // 7
    palette_a[m8, 5] = (3 * a0_8 + 4 * a1_8) // 7
    palette_a[m8, 6] = (2 * a0_8 + 5 * a1_8) // 7
    palette_a[m8, 7] = (1 * a0_8 + 6 * a1_8) // 7
    # 6-alpha mode
    m6 = ~m8
    a0_6 = a0[m6].astype(np.uint16); a1_6 = a1[m6].astype(np.uint16)
    palette_a[m6, 2] = (4 * a0_6 + 1 * a1_6) // 5
    palette_a[m6, 3] = (3 * a0_6 + 2 * a1_6) // 5
    palette_a[m6, 4] = (2 * a0_6 + 3 * a1_6) // 5
    palette_a[m6, 5] = (1 * a0_6 + 4 * a1_6) // 5
    palette_a[m6, 6] = 0
    palette_a[m6, 7] = 255

    # 16 × 3-bit indices in 6 bytes (bytes 2..7) → assemble as 48-bit int (use uint64)
    a_bytes = blocks[:, 2:8].astype(np.uint64)
    a_word = (a_bytes[:, 0]
              | (a_bytes[:, 1] << 8)
              | (a_bytes[:, 2] << 16)
              | (a_bytes[:, 3] << 24)
              | (a_bytes[:, 4] << 32)
              | (a_bytes[:, 5] << 40))
    shifts = np.arange(16, dtype=np.uint64) * 3
    a_idx = (a_word[:, None] >> shifts) & 0x7
    a_idx = a_idx.reshape(nblocks, 4, 4)
    alpha_pixels = palette_a[np.arange(nblocks)[:, None, None], a_idx].astype(np.uint8)

    # Inject alpha into rgba
    alpha_pixels = alpha_pixels.reshape(bh, bw, 4, 4)
    rgba[..., 3] = alpha_pixels
    full = rgba.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return full[:height, :width, :].copy()


def decode_bgra8(data: bytes, width: int, height: int) -> np.ndarray:
    arr = np.frombuffer(data[: width * height * 4], dtype=np.uint8)
    return arr.reshape(height, width, 4).copy()


# ---------------------------------------------------------------------------
# BC1 / BC3 ENCODERS  (vectorized, bbox-endpoint quality — fast, good enough
# for diffuse re-grading)
# ---------------------------------------------------------------------------

def _to_565(c: np.ndarray) -> np.ndarray:
    """RGB int array shape (..., 3) → uint16 RGB565."""
    r = np.clip(c[..., 0] >> 3, 0, 31).astype(np.uint16)
    g = np.clip(c[..., 1] >> 2, 0, 63).astype(np.uint16)
    b = np.clip(c[..., 2] >> 3, 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _from_565(c: np.ndarray) -> np.ndarray:
    """uint16 RGB565 → RGB int array shape (..., 3) (8-bit reconstruction matching decoder)."""
    r = (((c >> 11) & 0x1F).astype(np.int32) * 527 + 23) >> 6
    g = (((c >> 5) & 0x3F).astype(np.int32) * 259 + 33) >> 6
    b = ((c & 0x1F).astype(np.int32) * 527 + 23) >> 6
    return np.stack([r, g, b], axis=-1)


def _pad_blockable(bgra: np.ndarray) -> np.ndarray:
    """Pad to multiple of 4 in both dims using edge replication."""
    h, w = bgra.shape[:2]
    ph = (4 - h % 4) % 4
    pw = (4 - w % 4) % 4
    if ph or pw:
        bgra = np.pad(bgra, ((0, ph), (0, pw), (0, 0)), mode='edge')
    return bgra


def _bgra_to_blocks_rgb(bgra: np.ndarray):
    """Reshape padded BGRA into (num_blocks, 16, 3) RGB int32 + (N,16) alpha."""
    h, w = bgra.shape[:2]
    bh, bw = h // 4, w // 4
    blocks = bgra.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 4)
    rgb = blocks[..., [2, 1, 0]].astype(np.int32)  # BGR→RGB
    alpha = blocks[..., 3].astype(np.int32)
    return rgb, alpha, bh, bw


def _quantize_collinear_bc1(rgb: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    """Fast BC1 4-color index assignment via line projection.

    Because palette entries {p0, p1, p2=(2p0+p1)/3, p3=(p0+2p1)/3} are colinear,
    nearest-neighbor in RGB == nearest position along the p0→p1 line. We project
    each pixel onto that line, snap the parameter t to {0, 1/3, 2/3, 1}, then
    map to BC1 index ordering (0=p0, 1=p1, 2=p2, 3=p3).

    rgb:  (N, 16, 3) int32
    p0/p1: (N, 3) int32
    Returns (N, 16) uint8 of BC1 indices.
    """
    direction = (p1 - p0).astype(np.float32)                 # (N, 3)
    denom = (direction * direction).sum(axis=-1)             # (N,)
    denom = np.where(denom == 0, 1.0, denom)
    diff = rgb.astype(np.float32) - p0[:, None, :].astype(np.float32)  # (N,16,3)
    t = (diff * direction[:, None, :]).sum(axis=-1) / denom[:, None]   # (N,16)
    snap = np.clip(np.round(t * 3.0).astype(np.int32), 0, 3)           # (N,16)
    # snap=0→p0(idx 0), 1→p2(idx 2), 2→p3(idx 3), 3→p1(idx 1)
    table = np.array([0, 2, 3, 1], dtype=np.uint8)
    return table[snap]


def _encode_color_block_bytes(c0_565: np.ndarray, c1_565: np.ndarray,
                              idx: np.ndarray) -> np.ndarray:
    """Pack BC color half (8 bytes per block). Returns (N, 8) uint8."""
    n = c0_565.shape[0]
    shifts = np.arange(16, dtype=np.uint32) * 2
    idx_word = (idx.astype(np.uint32) << shifts).sum(axis=-1).astype(np.uint32)
    out = np.zeros((n, 8), dtype=np.uint8)
    out[:, 0] = (c0_565 & 0xFF).astype(np.uint8)
    out[:, 1] = ((c0_565 >> 8) & 0xFF).astype(np.uint8)
    out[:, 2] = (c1_565 & 0xFF).astype(np.uint8)
    out[:, 3] = ((c1_565 >> 8) & 0xFF).astype(np.uint8)
    out[:, 4] = (idx_word & 0xFF).astype(np.uint8)
    out[:, 5] = ((idx_word >> 8) & 0xFF).astype(np.uint8)
    out[:, 6] = ((idx_word >> 16) & 0xFF).astype(np.uint8)
    out[:, 7] = ((idx_word >> 24) & 0xFF).astype(np.uint8)
    return out


def _pca_endpoints(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-block PCA-based endpoint pair.

    rgb: (N, 16, 3) int32. Returns (e_min, e_max) each (N, 3) int32 — the two
    endpoints along the dominant color axis. For uniform/low-variance blocks,
    falls back to the bbox extrema (axis-aligned) which are a better fit there.
    """
    f = rgb.astype(np.float32)
    mean = f.mean(axis=1, keepdims=True)                         # (N,1,3)
    centered = f - mean                                          # (N,16,3)
    cmin = f.min(axis=1)                                         # (N,3)
    cmax = f.max(axis=1)                                         # (N,3)

    # Power-iteration on the 3x3 covariance matrix. Seeding with the bbox
    # diagonal (cmax-cmin) converges in 1–2 iterations for typical color
    # distributions — critically, it never starts perpendicular to the data,
    # which the previous (1,1,1)/sqrt(3) seed could and produced bad endpoints
    # for some blocks.
    cov = np.einsum('nki,nkj->nij', centered, centered)          # (N,3,3)
    v = (cmax - cmin).astype(np.float32)
    n_v = np.linalg.norm(v, axis=1, keepdims=True)
    v = np.where(n_v == 0, np.array([[1.0, 0.0, 0.0]], dtype=np.float32), v / np.where(n_v == 0, 1.0, n_v))
    for _ in range(3):
        v = np.einsum('nij,nj->ni', cov, v)
        n_v = np.linalg.norm(v, axis=1, keepdims=True)
        v = v / np.where(n_v == 0, 1.0, n_v)

    # Project pixels onto the principal axis
    proj = np.einsum('nki,ni->nk', centered, v)                  # (N,16)
    p_min = proj.min(axis=1, keepdims=True)
    p_max = proj.max(axis=1, keepdims=True)
    e_min_pca = mean.squeeze(1) + p_min * v
    e_max_pca = mean.squeeze(1) + p_max * v

    # Variance check: if total variance is tiny, PCA axis is noisy — use bbox.
    total_var = (centered * centered).sum(axis=(1, 2))           # (N,)
    use_bbox = total_var < 12.0                                  # ~1 LSB² per channel per pixel
    e_min = np.where(use_bbox[:, None], cmin, e_min_pca)
    e_max = np.where(use_bbox[:, None], cmax, e_max_pca)

    e_min = np.clip(np.round(e_min), 0, 255).astype(np.int32)
    e_max = np.clip(np.round(e_max), 0, 255).astype(np.int32)
    return e_min, e_max


def _encode_color_blocks(rgb: np.ndarray):
    """rgb shape (N, 16, 3) → (N, 8) BC1-color-half bytes (always 4-color mode).

    Tries both bbox-aligned and PCA-derived endpoints per block and keeps the
    one with lower reconstruction error. PCA wins on diagonal/off-axis color
    distributions (common after LUT re-grades); bbox wins on near-axis-aligned
    distributions where PCA's noisy axis would over-extend the endpoints.
    """
    f = rgb.astype(np.float32)

    # --- Candidate A: bbox endpoints --------------------------------------
    e_min_bb = f.min(axis=1)
    e_max_bb = f.max(axis=1)

    # --- Candidate B: PCA endpoints ---------------------------------------
    e_min_pca, e_max_pca = _pca_endpoints(rgb)

    # Score each candidate by total squared reconstruction error
    err_bb = _block_error(rgb, e_min_bb, e_max_bb)
    err_pca = _block_error(rgb, e_min_pca.astype(np.float32),
                           e_max_pca.astype(np.float32))
    use_pca = err_pca < err_bb
    e_min = np.where(use_pca[:, None], e_min_pca, e_min_bb)
    e_max = np.where(use_pca[:, None], e_max_pca, e_max_bb)
    e_min = np.clip(np.round(e_min), 0, 255).astype(np.int32)
    e_max = np.clip(np.round(e_max), 0, 255).astype(np.int32)

    c_hi = _to_565(e_max)
    c_lo = _to_565(e_min)
    swap = c_hi < c_lo
    c0 = np.where(swap, c_lo, c_hi)
    c1 = np.where(swap, c_hi, c_lo)
    p0 = _from_565(c0)
    p1 = _from_565(c1)
    idx = _quantize_collinear_bc1(rgb, p0, p1)
    return _encode_color_block_bytes(c0, c1, idx)


def _block_error(rgb: np.ndarray, e_min: np.ndarray, e_max: np.ndarray) -> np.ndarray:
    """Sum-of-squared-error per block when quantized to a 4-color BC1 palette.

    rgb:  (N, 16, 3) int32; e_min/e_max: (N, 3) float32 endpoints.
    Returns (N,) float32.
    """
    p0 = e_max.astype(np.float32)
    p1 = e_min.astype(np.float32)
    direction = p1 - p0
    denom = (direction * direction).sum(axis=-1)
    denom_safe = np.where(denom == 0, 1.0, denom)
    f = rgb.astype(np.float32)
    diff = f - p0[:, None, :]
    t = (diff * direction[:, None, :]).sum(axis=-1) / denom_safe[:, None]    # (N,16)
    snap_t = np.clip(np.round(t * 3.0), 0, 3) / 3.0
    recon = p0[:, None, :] + snap_t[:, :, None] * direction[:, None, :]
    e = f - recon
    return (e * e).sum(axis=(1, 2))


def encode_bc1(bgra: np.ndarray) -> bytes:
    """Encode BGRA8 → BC1 (DXT1) bytes. Always 4-color mode (no 1-bit alpha)."""
    bgra = _pad_blockable(bgra)
    rgb, _alpha, _bh, _bw = _bgra_to_blocks_rgb(bgra)
    color_block = _encode_color_blocks(rgb)
    return color_block.tobytes()


def encode_bc3(bgra: np.ndarray) -> bytes:
    """Encode BGRA8 → BC3 (DXT5) bytes. 8-alpha mode for full alpha range."""
    bgra = _pad_blockable(bgra)
    rgb, alpha, _bh, _bw = _bgra_to_blocks_rgb(bgra)
    n = rgb.shape[0]

    # --- alpha block (8-alpha mode: a0 > a1) ---
    a_min = alpha.min(axis=1).astype(np.int32)
    a_max = alpha.max(axis=1).astype(np.int32)
    # Use a_max as a0, a_min as a1. If equal, set a1 = a0-1 if possible to keep
    # 8-alpha mode well-defined (palette collapses to single value either way).
    a0 = a_max.astype(np.uint8)
    a1 = a_min.astype(np.uint8)
    eq = a0 == a1
    # When equal and a0 > 0: nudge a1 down so we stay in 8-alpha mode
    a1 = np.where(eq & (a0 > 0), a0 - 1, a1)
    # 8-alpha mode palette: pal[k] = ((7-k)*a0 + k*a1)/7 for k in 0..7.
    # This is collinear in 1D, so nearest-neighbor == projection onto [a0,a1].
    a0_f = a0.astype(np.float32)
    a1_f = a1.astype(np.float32)
    span = a0_f - a1_f                                     # (N,) >= 0
    span_safe = np.where(span == 0, 1.0, span)
    # k in [0,7] increases as alpha goes from a0 down to a1.
    t = (a0_f[:, None] - alpha.astype(np.float32)) * 7.0 / span_safe[:, None]  # (N,16)
    k = np.clip(np.round(t).astype(np.int32), 0, 7)        # (N,16) palette slot
    # BC3 index ordering: index 0 -> a0 (k=0), index 1 -> a1 (k=7),
    # indices 2..7 -> the 6 interpolated slots (k=1..6).
    # Mapping k -> bc3_index: 0->0, 1->2, 2->3, 3->4, 4->5, 5->6, 6->7, 7->1.
    map_k_to_idx = np.array([0, 2, 3, 4, 5, 6, 7, 1], dtype=np.uint64)
    a_idx = map_k_to_idx[k]                                 # (N, 16) uint64
    # Blocks with span==0 (a0==a1 case avoided by nudge) collapse to idx 0 — fine.
    a_shifts = np.arange(16, dtype=np.uint64) * 3
    a_word = (a_idx << a_shifts).sum(axis=-1).astype(np.uint64)

    # --- color block (BC1-style, 4-color) ---
    color_block = _encode_color_blocks(rgb)

    # --- pack: alpha(8) + color(8) = 16 bytes per block ---
    out = np.zeros((n, 16), dtype=np.uint8)
    out[:, 0] = a0
    out[:, 1] = a1
    for i in range(6):
        out[:, 2 + i] = ((a_word >> np.uint64(i * 8)) & np.uint64(0xFF)).astype(np.uint8)
    out[:, 8:16] = color_block
    return out.tobytes()


# ---------------------------------------------------------------------------
# DDS file I/O
# ---------------------------------------------------------------------------

def parse_dds(data: bytes):
    """Return dict: width, height, fmt ('BC1'|'BC3'|'BGRA8'), payload (largest mip)."""
    if data[:4] != b"DDS " or struct.unpack("<I", data[4:8])[0] != 124:
        raise ValueError("Not a valid DDS file")
    flags, height, width, _pitch, _depth, mip_count = struct.unpack("<6I", data[8:32])
    pf_flags, fourcc, rgb_bits, rmask, gmask, bmask, amask = struct.unpack("<I4sIIIII", data[80:108])
    data_offset = 128
    fmt = None
    if fourcc == b"DXT1":
        fmt = "BC1"
    elif fourcc == b"DXT5":
        fmt = "BC3"
    elif fourcc == b"DX10":
        data_offset = 148
        fmt = "DX10"  # not handled here
    elif (pf_flags & 0x40) and rgb_bits == 32 and rmask == 0x00ff0000 and bmask == 0x000000ff:
        fmt = "BGRA8"
    else:
        raise ValueError(f"Unsupported DDS pixel format: fourcc={fourcc!r} bits={rgb_bits}")
    return {
        "width": width, "height": height, "mip_count": max(1, mip_count or 1),
        "fmt": fmt, "data": data[data_offset:],
    }


def build_dds(bgra_mips: list[np.ndarray], fmt: str) -> bytes:
    """Build a DDS file from a list of BGRA8 mip arrays (largest first), in `fmt`.

    fmt: 'BC1', 'BC3', or 'BGRA8'. Compressed mips are encoded per-mip.
    """
    largest = bgra_mips[0]
    h, w = largest.shape[:2]
    n_mips = len(bgra_mips)
    flags = 0x1 | 0x2 | 0x4 | 0x1000
    if n_mips > 1:
        flags |= 0x20000  # MIPMAPCOUNT
    caps = 0x1000 | (0x400000 | 0x8 if n_mips > 1 else 0)

    if fmt == 'BC1':
        flags |= 0x80000  # LINEARSIZE
        bw = (w + 3) // 4; bh = (h + 3) // 4
        pitch = bw * bh * 8  # linear-size of largest mip
        ddspf = struct.pack('<II4s20x', 32, 0x4, b'DXT1')
        payload = b''.join(encode_bc1(m) for m in bgra_mips)
    elif fmt == 'BC3':
        flags |= 0x80000
        bw = (w + 3) // 4; bh = (h + 3) // 4
        pitch = bw * bh * 16
        ddspf = struct.pack('<II4s20x', 32, 0x4, b'DXT5')
        payload = b''.join(encode_bc3(m) for m in bgra_mips)
    elif fmt == 'BGRA8':
        pitch = w * 4
        ddspf = struct.pack('<II4xLLLLL', 32, 0x41, 32,
                            0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
        payload = b''.join(m.tobytes() for m in bgra_mips)
    else:
        raise ValueError(f"Unsupported output DDS format: {fmt}")

    hdr = struct.pack('<4s7L', b'DDS ', 124, flags, h, w, pitch, 0, n_mips)
    hdr += b'\x00' * 44
    hdr += ddspf
    hdr += struct.pack('<4L', caps, 0, 0, 0)
    hdr += b'\x00' * 4
    return hdr + payload


# Backwards-compatible alias
def build_bgra8_dds(bgra_mips: list[np.ndarray]) -> bytes:
    return build_dds(bgra_mips, 'BGRA8')


def downsample_bgra8(img: np.ndarray) -> np.ndarray:
    """2×2 box-filter downsample. Pads odd dimensions by repeating the last row/col."""
    h, w = img.shape[:2]
    if h <= 1 and w <= 1:
        return img.copy()
    if h % 2:
        img = np.vstack([img, img[-1:]]); h += 1
    if w % 2:
        img = np.hstack([img, img[:, -1:]]); w += 1
    img32 = img.astype(np.uint16)
    a = img32[0::2, 0::2]
    b = img32[1::2, 0::2]
    c = img32[0::2, 1::2]
    d = img32[1::2, 1::2]
    return ((a + b + c + d + 2) // 4).astype(np.uint8)


def build_mip_chain(bgra: np.ndarray) -> list[np.ndarray]:
    chain = [bgra]
    cur = bgra
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        cur = downsample_bgra8(cur)
        chain.append(cur)
    return chain


# ---------------------------------------------------------------------------
# Grayscale detection
# ---------------------------------------------------------------------------

def is_grayscale(bgra: np.ndarray, threshold: float = 5.0) -> bool:
    """Return True if image is (near-)grayscale: mean per-pixel max-channel-delta < threshold (0..255).

    Subsamples to keep this cheap on large textures.
    """
    h, w = bgra.shape[:2]
    step = max(1, max(h, w) // 256)
    sub = bgra[::step, ::step, :3].astype(np.int16)
    mx = sub.max(axis=2)
    mn = sub.min(axis=2)
    return float((mx - mn).mean()) < threshold


# ---------------------------------------------------------------------------
# Top-level texture pipeline
# ---------------------------------------------------------------------------

def _decode_dds_largest(parsed: dict) -> Optional[np.ndarray]:
    fmt = parsed["fmt"]
    w, h = parsed["width"], parsed["height"]
    payload = parsed["data"]
    if fmt == "BC1":
        return decode_bc1(payload, w, h)
    if fmt == "BC3":
        return decode_bc3(payload, w, h)
    if fmt == "BGRA8":
        return decode_bgra8(payload, w, h)
    return None  # DX10 / unsupported


def recolor_dds_bytes(dds_bytes: bytes, lut_pack) -> Tuple[Optional[bytes], str]:
    """Recolor a DDS file. Returns (new_dds_bytes_or_None, status_string).

    Output preserves the input format (BC1 in → BC1 out, BC3 → BC3, BGRA8 → BGRA8)
    and the input mip-chain length.
    """
    parsed = parse_dds(dds_bytes)
    bgra = _decode_dds_largest(parsed)
    if bgra is None:
        return None, f"unsupported-format:{parsed['fmt']}"
    if is_grayscale(bgra):
        return None, "skip-grayscale"

    # Fast path: precomputed 256³ baked LUT — single uint8 gather per channel.
    lut256 = lut_pack[4] if len(lut_pack) >= 5 else None
    if lut256 is not None:
        r = bgra[..., 2]; g = bgra[..., 1]; b = bgra[..., 0]
        out_rgb = lut256[r, g, b]                         # (H, W, 3) uint8
        new_bgra = bgra.copy()
        new_bgra[..., 0] = out_rgb[..., 2]                # B
        new_bgra[..., 1] = out_rgb[..., 1]                # G
        new_bgra[..., 2] = out_rgb[..., 0]                # R
    else:
        # Fallback: per-pixel trilinear sampling.
        rgb = bgra[..., [2, 1, 0]].astype(np.float32) / 255.0
        size, lut, dmin, dmax = lut_pack[:4]
        rgb_new = apply_lut_rgb(rgb, size, lut, dmin, dmax)
        rgb_new = np.clip(rgb_new * 255.0 + 0.5, 0, 255).astype(np.uint8)
        new_bgra = bgra.copy()
        new_bgra[..., 0] = rgb_new[..., 2]
        new_bgra[..., 1] = rgb_new[..., 1]
        new_bgra[..., 2] = rgb_new[..., 0]

    # ------------------------------------------------------------------
    # Decide output format. Preserve input format by default, but promote
    # BC1 → BC3 when the decoded image has any non-opaque alpha (covers BC1's
    # 3-color + 1-bit-alpha mode) so we don't silently drop transparency.
    # This matches SentinelAIO's behavior of using DXT5 whenever alpha is
    # present and not all-white.
    # ------------------------------------------------------------------
    out_fmt = parsed['fmt']
    if out_fmt == 'BC1':
        if int(new_bgra[..., 3].min()) < 255:
            out_fmt = 'BC3'

    # Build mip chain matching input mip count, in the chosen format
    chain = build_mip_chain(new_bgra)
    target_mips = max(1, int(parsed.get('mip_count', 1)))
    if len(chain) > target_mips:
        chain = chain[:target_mips]
    return build_dds(chain, out_fmt), "recolored"


def recolor_file(path: str, lut_pack, backup_root: str) -> str:
    """Recolor a single .dds or .tex file in-place. Returns status string."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".dds", ".tex"):
        return "skip-ext"

    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return f"error-read:{exc}"

    # Convert .tex → DDS
    if ext == ".tex":
        try:
            from texture_utils import TexConverter
        except ImportError:
            from .texture_utils import TexConverter
        try:
            dds_in = TexConverter._tex_to_dds(raw)
        except Exception as exc:
            return f"error-tex2dds:{exc}"
    else:
        dds_in = raw

    try:
        new_dds, status = recolor_dds_bytes(dds_in, lut_pack)
    except Exception as exc:
        return f"error-recolor:{exc}"
    if new_dds is None:
        return status

    # Backup original
    rel = os.path.relpath(path, start=os.path.commonpath([path, backup_root])) \
        if backup_root else os.path.basename(path)
    backup_path = os.path.join(backup_root, rel)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)

    # Write back
    if ext == ".tex":
        try:
            from texture_utils import TexConverter
        except ImportError:
            from .texture_utils import TexConverter
        try:
            new_tex = TexConverter.dds_to_tex(new_dds)
        except Exception as exc:
            return f"error-dds2tex:{exc}"
        with open(path, "wb") as fh:
            fh.write(new_tex)
    else:
        with open(path, "wb") as fh:
            fh.write(new_dds)
    return status


def _norm_rel_path(path: str) -> str:
    """Normalize a relative asset path for case-insensitive set lookups."""
    p = path.replace("\\", "/").strip().lower()
    while p.startswith("./"):
        p = p[2:]
    return p


def recolor_folder(folder: str, lut_path: str, dry_run: bool = False,
                   progress_cb=None, workers: Optional[int] = None,
                   denylist_paths: Optional[set[str]] = None) -> dict:
    """Walk `folder`, recolor every supported color texture. Returns stats dict.

    `denylist_paths`: optional set of WAD-rooted texture paths (built from bin
    sampler data) that are known non-color maps.  Any texture whose path suffix
    matches a denylist entry is skipped.  Textures NOT in any bin (characters,
    particles, icons, grass tint …) are NOT in the denylist and are recolored.

    `workers`: number of parallel threads. Defaults to min(8, cpu_count()).
    NumPy + file I/O both release the GIL, so threading gives a real speedup
    even though `texture_utils` (with its module-level `import bpy`) prevents
    using process workers.
    """
    lut_pack = parse_cube(lut_path)
    backup_root = os.path.join(folder, "_lut_backup")
    if not dry_run:
        os.makedirs(backup_root, exist_ok=True)

    targets: list[str] = []
    index_skipped: list[str] = []
    deny = {_norm_rel_path(p) for p in denylist_paths} if denylist_paths else None
    for r, dirs, files in os.walk(folder):
        # Skip our own backup folder
        dirs[:] = [d for d in dirs if d.lower() != "_lut_backup"]
        for f in files:
            low = f.lower()
            if not low.endswith((".dds", ".tex")):
                continue
            full = os.path.join(r, f)
            if deny is not None:
                # Suffix search: strip leading path components one at a time.
                # The denylist stores WAD-rooted paths like 'assets/maps/...',
                # but files on disk may be under 'Map11/assets/maps/...' or
                # deeper. Progressively stripping the prefix finds a match.
                rel = _norm_rel_path(os.path.relpath(full, folder))
                parts = rel.split('/')
                for start in range(len(parts)):
                    cand = '/'.join(parts[start:])
                    if cand in deny or os.path.splitext(cand)[0] in deny:
                        index_skipped.append(full)
                        break
                else:
                    targets.append(full)
                continue
            targets.append(full)

    stats = {
        "total": len(targets) + len(index_skipped),
        "recolored": 0,
        "skip-name": 0,
        "skip-index": len(index_skipped),
        "skip-grayscale": 0,
        "skip-ext": 0,
        "errors": 0,
        "details": [],
    }

    if dry_run:
        stats["recolored"] = len(targets)
        return stats

    if workers is None:
        try:
            workers = min(8, max(1, (os.cpu_count() or 4)))
        except Exception:
            workers = 4

    if workers <= 1:
        # Serial path (used for tests / debugging).
        for i, path in enumerate(targets):
            if progress_cb:
                progress_cb(i, len(targets), path)
            _accumulate_stat(stats, path,
                             recolor_file(path, lut_pack, backup_root))
        return stats

    # Parallel path: ThreadPoolExecutor. submit() each task, then drain via
    # as_completed so progress callbacks fire as files finish.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(recolor_file, p, lut_pack, backup_root): p
                   for p in targets}
        done = 0
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                st = fut.result()
            except Exception as exc:                      # noqa: BLE001
                st = f"error-task:{exc}"
            _accumulate_stat(stats, p, st)
            done += 1
            if progress_cb:
                progress_cb(done, len(targets), p)
    return stats


def _accumulate_stat(stats: dict, path: str, st: str) -> None:
    if st == "recolored":
        stats["recolored"] += 1
    elif st in stats:
        stats[st] += 1
    else:
        stats["errors"] += 1
        stats["details"].append(f"{path}: {st}")
