"""
navgrid.py
==========
Parser for League of Legends ``.aimesh_ngrid`` navigation-grid files and
PNG bakers for heightmap / walkability textures.

The navgrid is the game's ground truth for walkability: a regular XZ grid
of cells (cell size is usually 50 game units) where every cell stores the
terrain height at its centre plus a vision/pathing flag bitfield.

Verified against ``aipath_srx.aimesh_ngrid`` (version 7.1, Summoner's Rift,
295x296 cells):

    u8   major            (7)
    u16  minor            (1)
    f32  min_pos[3]       world-space grid minimum  (x, y, z; y = height)
    f32  max_pos[3]       world-space grid maximum
    f32  cell_size        (50.0)
    u32  cell_count_x
    u32  cell_count_z
    48B  cells[x*z]       row-major, z-major order (index = z * count_x + x)
           +0  f32 center_height   <- the only field we need
           +4  u32 session_id
           ... pathfinding scratch data ...
    u16  vision_pathing_flags[x*z]
    ...  region layers / hint data (not parsed)

Flag bits (vision pathing layer):
    0x01  HAS_GRASS      brush
    0x02  NOT_PASSABLE   wall / out of bounds
    0x04  BUSY
    0x08  TARGETTED
    0x10  MARKED
    0x20  PATHED_ON
    0x40  SEE_THROUGH
    0x80  vision-related (set on many walkable jungle cells)

A cell is walkable iff ``not (flags & 0x02)``.

This module is bpy-free so it can be unit-tested outside Blender.
"""

import json
import os
import struct
import zlib

FLAG_GRASS        = 0x01
FLAG_NOT_PASSABLE = 0x02
FLAG_SEE_THROUGH  = 0x40

_CELL_STRIDE_V7 = 48
_HEADER_FMT = "<3f3ffII"


class NavGrid:
    """Parsed navgrid: world bounds, cell grid, heights and flags."""

    __slots__ = ("source_path", "major", "minor", "min_pos", "max_pos",
                 "cell_size", "count_x", "count_z", "heights", "flags")

    def __init__(self):
        self.source_path = ""
        self.major = 0
        self.minor = 0
        self.min_pos = (0.0, 0.0, 0.0)
        self.max_pos = (0.0, 0.0, 0.0)
        self.cell_size = 50.0
        self.count_x = 0
        self.count_z = 0
        self.heights = []   # f32 per cell, row-major (z * count_x + x)
        self.flags = []     # u16 per cell

    # convenience -----------------------------------------------------------
    @property
    def cell_count(self):
        return self.count_x * self.count_z

    def is_walkable(self, idx):
        return not (self.flags[idx] & FLAG_NOT_PASSABLE)

    def is_brush(self, idx):
        return bool(self.flags[idx] & FLAG_GRASS)

    def walkable_fraction(self):
        if not self.flags:
            return 0.0
        walk = sum(1 for f in self.flags if not (f & FLAG_NOT_PASSABLE))
        return walk / len(self.flags)

    def height_range(self, walkable_only=False):
        """(z_lo, z_hi) over cell heights. Optionally only walkable cells."""
        if walkable_only:
            vals = [h for h, f in zip(self.heights, self.flags)
                    if not (f & FLAG_NOT_PASSABLE)]
        else:
            vals = self.heights
        if not vals:
            return 0.0, 1.0
        return min(vals), max(vals)


def parse(path):
    """Parse an .aimesh_ngrid file. Raises ValueError on unsupported data."""
    with open(path, "rb") as fh:
        data = fh.read()

    if len(data) < 40:
        raise ValueError("File too small to be a navgrid")

    g = NavGrid()
    g.source_path = path
    g.major = data[0]
    off = 1
    if g.major != 2:
        g.minor = struct.unpack_from("<H", data, off)[0]
        off += 2

    if g.major != 7:
        raise ValueError(
            f"Unsupported navgrid version {g.major}.{g.minor} "
            f"(only version 7 is implemented)")

    (mx, my, mz, Mx, My, Mz,
     g.cell_size, g.count_x, g.count_z) = struct.unpack_from(_HEADER_FMT, data, off)
    off += struct.calcsize(_HEADER_FMT)
    g.min_pos = (mx, my, mz)
    g.max_pos = (Mx, My, Mz)

    n = g.count_x * g.count_z
    if n <= 0 or n > 50_000_000:
        raise ValueError(f"Implausible cell count {g.count_x}x{g.count_z}")
    need = off + n * _CELL_STRIDE_V7 + n * 2
    if len(data) < need:
        raise ValueError(
            f"File truncated: need {need} bytes for {n} cells, have {len(data)}")

    # Heights: f32 at +0 of every 48-byte cell.
    g.heights = list(struct.unpack(
        f"<{n}f", b"".join(
            data[off + i * _CELL_STRIDE_V7: off + i * _CELL_STRIDE_V7 + 4]
            for i in range(n))))
    off += n * _CELL_STRIDE_V7

    g.flags = list(struct.unpack_from(f"<{n}H", data, off))
    return g


# ─── PNG writing (pure python, no PIL dependency) ───────────────────────────

def _png_chunk(tag, payload):
    c = tag + payload
    return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c))


def _write_png(path, width, height, raw_rows, bit_depth, color_type):
    """raw_rows: iterable of bytes objects, one per row, WITHOUT filter byte."""
    raw = b"".join(b"\x00" + bytes(r) for r in raw_rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                             bit_depth, color_type, 0, 0, 0))
           + _png_chunk(b"IDAT", zlib.compress(raw, 6))
           + _png_chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


# ─── Sampling helpers ────────────────────────────────────────────────────────

def _bilinear_height(grid, fx, fz):
    """Sample cell heights bilinearly. fx/fz are in cell units (cell centres
    at integer coordinates)."""
    xc, zc = grid.count_x, grid.count_z
    x0 = int(fx)
    z0 = int(fz)
    if x0 < 0: x0 = 0
    if z0 < 0: z0 = 0
    if x0 > xc - 2: x0 = xc - 2
    if z0 > zc - 2: z0 = zc - 2
    tx = fx - x0
    tz = fz - z0
    if tx < 0.0: tx = 0.0
    elif tx > 1.0: tx = 1.0
    if tz < 0.0: tz = 0.0
    elif tz > 1.0: tz = 1.0
    h = grid.heights
    base = z0 * xc + x0
    h00 = h[base]
    h10 = h[base + 1]
    h01 = h[base + xc]
    h11 = h[base + xc + 1]
    return (h00 * (1 - tx) * (1 - tz) + h10 * tx * (1 - tz)
            + h01 * (1 - tx) * tz + h11 * tx * tz)


# ─── Bakers ──────────────────────────────────────────────────────────────────

def bake_heightmap_png(grid, path, scale=4, smooth=True,
                       z_lo=None, z_hi=None):
    """16-bit grayscale heightmap PNG. Returns (z_lo, z_hi) used.

    Image rows run from max Z (top) to min Z (bottom) so the result is
    oriented like the in-game minimap. Pixel (0,0) = world (min_x, max_z).
    """
    if z_lo is None or z_hi is None:
        a_lo, a_hi = grid.height_range()
        if z_lo is None: z_lo = a_lo
        if z_hi is None: z_hi = a_hi
    rng = max(z_hi - z_lo, 1e-6)

    w = grid.count_x * scale
    h = grid.count_z * scale
    rows = []
    inv = 1.0 / scale
    for py in range(h):
        # py=0 → top of image → largest z
        fz = (h - 1 - py) * inv if smooth else (grid.count_z - 1 - py // scale)
        row = bytearray(w * 2)
        if smooth:
            for px in range(w):
                hv = _bilinear_height(grid, px * inv, fz)
                v = int(max(0.0, min(1.0, (hv - z_lo) / rng)) * 65535)
                row[px * 2] = v >> 8
                row[px * 2 + 1] = v & 0xFF
        else:
            zz = int(fz)
            base = zz * grid.count_x
            for cx in range(grid.count_x):
                hv = grid.heights[base + cx]
                v = int(max(0.0, min(1.0, (hv - z_lo) / rng)) * 65535)
                hi, lo = v >> 8, v & 0xFF
                for s in range(scale):
                    px = cx * scale + s
                    row[px * 2] = hi
                    row[px * 2 + 1] = lo
        rows.append(bytes(row))
    _write_png(path, w, h, rows, 16, 0)  # grayscale 16-bit
    return z_lo, z_hi


WALKABLE_RGB = (255, 255, 255)
WALL_RGB     = (255, 0, 0)
BRUSH_RGB    = (0, 200, 0)


def bake_walkable_png(grid, path, scale=4, mark_brush=True):
    """RGB walkability mask: white = walkable, red = wall, green = brush."""
    w = grid.count_x * scale
    h = grid.count_z * scale
    rows = []
    for zz in range(grid.count_z - 1, -1, -1):
        row = bytearray()
        base = zz * grid.count_x
        for xx in range(grid.count_x):
            f = grid.flags[base + xx]
            if f & FLAG_NOT_PASSABLE:
                px = WALL_RGB
            elif mark_brush and (f & FLAG_GRASS):
                px = BRUSH_RGB
            else:
                px = WALKABLE_RGB
            row += bytes(px) * scale
        rb = bytes(row)
        for _ in range(scale):
            rows.append(rb)
    _write_png(path, w, h, rows, 8, 2)  # RGB 8-bit


def bake_combined_png(grid, path, scale=4, smooth=True, mark_brush=True,
                      z_lo=None, z_hi=None):
    """RGB map: walkable cells get a white→black height gradient, walls are
    solid red, brush solid green. Same colour language as the legacy baker."""
    if z_lo is None or z_hi is None:
        a_lo, a_hi = grid.height_range(walkable_only=True)
        if z_lo is None: z_lo = a_lo
        if z_hi is None: z_hi = a_hi
    rng = max(z_hi - z_lo, 1e-6)

    w = grid.count_x * scale
    h = grid.count_z * scale
    inv = 1.0 / scale
    rows = []
    for py in range(h):
        zz = grid.count_z - 1 - py // scale
        base = zz * grid.count_x
        row = bytearray(w * 3)
        for px in range(w):
            xx = px // scale
            f = grid.flags[base + xx]
            if f & FLAG_NOT_PASSABLE:
                r, gch, b = WALL_RGB
            elif mark_brush and (f & FLAG_GRASS):
                r, gch, b = BRUSH_RGB
            else:
                if smooth:
                    fz = (h - 1 - py) * inv
                    hv = _bilinear_height(grid, px * inv, fz)
                else:
                    hv = grid.heights[base + xx]
                g8 = int(max(0.0, min(1.0, (hv - z_lo) / rng)) * 255)
                r = gch = b = g8
            o = px * 3
            row[o] = r
            row[o + 1] = gch
            row[o + 2] = b
        rows.append(bytes(row))
    _write_png(path, w, h, rows, 8, 2)
    return z_lo, z_hi


def write_meta_json(grid, path, scale, z_lo, z_hi, outputs):
    """Sidecar JSON so external generators (e.g. Minecraft) can map
    pixels back to world space and real heights."""
    meta = {
        "source": os.path.basename(grid.source_path),
        "navgrid_version": f"{grid.major}.{grid.minor}",
        "world_min": list(grid.min_pos),   # (x, y=height, z)
        "world_max": list(grid.max_pos),
        "cell_size": grid.cell_size,
        "cells_x": grid.count_x,
        "cells_z": grid.count_z,
        "pixels_per_cell": scale,
        "image_width": grid.count_x * scale,
        "image_height": grid.count_z * scale,
        "orientation": "pixel (0,0) = world (min_x, max_z); rows go from max_z down to min_z (minimap-style, north up)",
        "height_encoding": {
            "z_black": z_lo,
            "z_white": z_hi,
            "formula": "world_height = z_black + (pixel_value / pixel_max) * (z_white - z_black)",
        },
        "walkable_fraction": round(grid.walkable_fraction(), 4),
        "colors": {
            "walkable": list(WALKABLE_RGB),
            "wall": list(WALL_RGB),
            "brush": list(BRUSH_RGB),
        },
        "outputs": outputs,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def bake_all(grid, base_path, scale=4, smooth=True, mark_brush=True,
             z_lo=None, z_hi=None):
    """Bake height + walkable + combined PNGs and a meta JSON.

    base_path may end in .png; outputs are written as
    <base>_height.png, <base>_walkable.png, <base>_combined.png, <base>_meta.json
    Returns the meta dict.
    """
    base, ext = os.path.splitext(base_path)
    if ext.lower() != ".png":
        base = base_path
    p_height   = base + "_height.png"
    p_walkable = base + "_walkable.png"
    p_combined = base + "_combined.png"
    p_meta     = base + "_meta.json"

    z_lo, z_hi = bake_heightmap_png(grid, p_height, scale=scale,
                                    smooth=smooth, z_lo=z_lo, z_hi=z_hi)
    bake_walkable_png(grid, p_walkable, scale=scale, mark_brush=mark_brush)
    bake_combined_png(grid, p_combined, scale=scale, smooth=smooth,
                      mark_brush=mark_brush, z_lo=z_lo, z_hi=z_hi)
    return write_meta_json(grid, p_meta, scale, z_lo, z_hi, {
        "height": os.path.basename(p_height),
        "walkable": os.path.basename(p_walkable),
        "combined": os.path.basename(p_combined),
    })
