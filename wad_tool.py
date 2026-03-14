"""
League Tools – WAD Archive Tool for Blender
Provides UI for extracting, browsing, and repacking League .wad / .wad.client files.

WAD is League's primary archive format storing game assets:
  maps, champions, textures, configs, etc.

Supports WAD versions 1.0, 2.0, 3.0 with compression types:
  Uncompressed, GZip, Satellite (file redirect), Zstandard.

Hash Resolution:
  - CommunityDragon WAD hashes (XXHash64 path dictionaries)
  - Custom hashing from .bin files (extracts string/file paths and computes XXHash64)
  - Hashlist file support for repacking unknown paths
"""

import bpy
import os
import struct
import gzip
import hashlib
import threading
import time
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList
from pathlib import Path


# ============================================================================
# XXHash64 Implementation (pure Python, no external deps)
# ============================================================================

_XXHASH64_PRIME1 = 0x9E3779B185EBCA87
_XXHASH64_PRIME2 = 0xC2B2AE3D27D4EB4F
_XXHASH64_PRIME3 = 0x165667B19E3779F9
_XXHASH64_PRIME4 = 0x85EBCA77C2B2AE63
_XXHASH64_PRIME5 = 0x27D4EB2F165667C5
_U64 = 0xFFFFFFFFFFFFFFFF


def _rotl64(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _U64


def _round64(acc: int, inp: int) -> int:
    acc = (acc + inp * _XXHASH64_PRIME2) & _U64
    acc = _rotl64(acc, 31)
    acc = (acc * _XXHASH64_PRIME1) & _U64
    return acc


def _merge_round64(acc: int, val: int) -> int:
    val = _round64(0, val)
    acc = (acc ^ val) & _U64
    acc = (acc * _XXHASH64_PRIME1 + _XXHASH64_PRIME4) & _U64
    return acc


def xxhash64(data: bytes, seed: int = 0) -> int:
    """Compute XXHash64 of bytes with optional seed. Returns u64."""
    length = len(data)
    idx = 0
    h64 = 0

    if length >= 32:
        v1 = (seed + _XXHASH64_PRIME1 + _XXHASH64_PRIME2) & _U64
        v2 = (seed + _XXHASH64_PRIME2) & _U64
        v3 = seed & _U64
        v4 = (seed - _XXHASH64_PRIME1) & _U64

        while idx <= length - 32:
            k1 = struct.unpack_from('<Q', data, idx)[0]
            k2 = struct.unpack_from('<Q', data, idx + 8)[0]
            k3 = struct.unpack_from('<Q', data, idx + 16)[0]
            k4 = struct.unpack_from('<Q', data, idx + 24)[0]
            v1 = _round64(v1, k1)
            v2 = _round64(v2, k2)
            v3 = _round64(v3, k3)
            v4 = _round64(v4, k4)
            idx += 32

        h64 = (_rotl64(v1, 1) + _rotl64(v2, 7) + _rotl64(v3, 12) + _rotl64(v4, 18)) & _U64
        h64 = _merge_round64(h64, v1)
        h64 = _merge_round64(h64, v2)
        h64 = _merge_round64(h64, v3)
        h64 = _merge_round64(h64, v4)
    else:
        h64 = (seed + _XXHASH64_PRIME5) & _U64

    h64 = (h64 + length) & _U64

    # Process remaining 8-byte chunks
    while idx <= length - 8:
        k1 = struct.unpack_from('<Q', data, idx)[0]
        k1 = (k1 * _XXHASH64_PRIME2) & _U64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * _XXHASH64_PRIME1) & _U64
        h64 = (h64 ^ k1) & _U64
        h64 = (_rotl64(h64, 27) * _XXHASH64_PRIME1 + _XXHASH64_PRIME4) & _U64
        idx += 8

    # Process remaining 4-byte chunk
    if idx <= length - 4:
        k1 = struct.unpack_from('<I', data, idx)[0]
        h64 = (h64 ^ (k1 * _XXHASH64_PRIME1)) & _U64
        h64 = (_rotl64(h64, 23) * _XXHASH64_PRIME2 + _XXHASH64_PRIME3) & _U64
        idx += 4

    # Process remaining bytes
    while idx < length:
        h64 = (h64 ^ (data[idx] * _XXHASH64_PRIME5)) & _U64
        h64 = (_rotl64(h64, 11) * _XXHASH64_PRIME1) & _U64
        idx += 1

    # Avalanche
    h64 = (h64 ^ (h64 >> 33)) & _U64
    h64 = (h64 * _XXHASH64_PRIME2) & _U64
    h64 = (h64 ^ (h64 >> 29)) & _U64
    h64 = (h64 * _XXHASH64_PRIME3) & _U64
    h64 = (h64 ^ (h64 >> 32)) & _U64

    return h64


def xxhash64_path(path: str) -> int:
    """Compute XXHash64 of a League file path (lowercased, forward slashes)."""
    return xxhash64(path.lower().replace('\\', '/').encode('utf-8'))


# ============================================================================
# WAD Entry Types
# ============================================================================

ENTRY_UNCOMPRESSED = 0
ENTRY_GZIP = 1
ENTRY_SATELLITE = 2   # File redirect (data stored externally)
ENTRY_ZSTD = 3         # Zstandard compression
ENTRY_ZSTD_CHUNKED = 4 # Zstandard multi-frame (chunked) compression


ENTRY_TYPE_NAMES = {
    ENTRY_UNCOMPRESSED: "Raw",
    ENTRY_GZIP: "GZip",
    ENTRY_SATELLITE: "Satellite",
    ENTRY_ZSTD: "Zstd",
    ENTRY_ZSTD_CHUNKED: "ZstdChunked",
}


# ============================================================================
# WAD Data Structures
# ============================================================================

class WadEntry:
    """A single file entry in a WAD archive."""
    __slots__ = (
        'path_hash', 'offset', 'compressed_size', 'uncompressed_size',
        'entry_type', 'duplicate', 'checksum',
        'resolved_path',  # Resolved file path (or None)
    )

    def __init__(self):
        self.path_hash: int = 0
        self.offset: int = 0
        self.compressed_size: int = 0
        self.uncompressed_size: int = 0
        self.entry_type: int = 0
        self.duplicate: bool = False
        self.checksum: int = 0  # First 8 bytes of SHA-256 as u64 (v2/v3 only)
        self.resolved_path: str | None = None

    @property
    def is_compressed(self) -> bool:
        return self.entry_type in (ENTRY_GZIP, ENTRY_ZSTD, ENTRY_ZSTD_CHUNKED)

    @property
    def type_name(self) -> str:
        return ENTRY_TYPE_NAMES.get(self.entry_type, f"Unknown({self.entry_type})")

    @property
    def display_path(self) -> str:
        if self.resolved_path:
            return self.resolved_path
        return f"{self.path_hash:016x}"

    def __repr__(self):
        return f"WadEntry(hash=0x{self.path_hash:016x}, {self.type_name}, {self.compressed_size}/{self.uncompressed_size}B)"


class WadArchive:
    """Parsed WAD archive with header info and entry table."""
    __slots__ = (
        'major_version', 'minor_version', 'entries',
        'filepath', 'signature',
    )

    def __init__(self):
        self.major_version: int = 3
        self.minor_version: int = 0
        self.entries: list[WadEntry] = []
        self.filepath: str = ""
        self.signature: bytes = b''

    @property
    def version_str(self) -> str:
        return f"{self.major_version}.{self.minor_version}"


# ============================================================================
# WAD Hash Database (XXHash64 path resolution for WAD entries)
# ============================================================================

# Global WAD hash dictionaries
_wad_hashes: dict[int, str] = {}          # XXHash64 → file path
_custom_hashes: dict[int, str] = {}       # From .bin file scanning
_hashlist_hashes: dict[int, str] = {}     # From user hashlist files
_wad_hash_status: str = ""
_wad_hash_count: int = 0

# CommunityDragon WAD hash file URL
_WAD_HASH_URL = "https://raw.githubusercontent.com/CommunityDragon/Data/master/hashes/lol/hashes.game.txt"
# Split files
_WAD_HASH_URLS = [
    ("hashes.game.txt.0", "https://raw.githubusercontent.com/CommunityDragon/Data/master/hashes/lol/hashes.game.txt.0"),
    ("hashes.game.txt.1", "https://raw.githubusercontent.com/CommunityDragon/Data/master/hashes/lol/hashes.game.txt.1"),
]


def _get_wad_hash_cache_dir() -> Path:
    """Get cache directory for WAD hash files."""
    addon_dir = Path(__file__).parent
    cache_dir = addon_dir / "hashes"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def _parse_wad_hash_file(filepath: Path) -> dict[int, str]:
    """
    Parse a CommunityDragon WAD hash file.
    Format: hex_hash path   (16-char hex, XXHash64)
    """
    result = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                hex_part = parts[0]
                path_part = parts[1]
                if hex_part.startswith('0x') or hex_part.startswith('0X'):
                    hex_part = hex_part[2:]
                try:
                    h = int(hex_part, 16)
                    result[h] = path_part
                except ValueError:
                    continue
    except (IOError, OSError) as e:
        print(f"[WAD Tool] Failed to read hash file {filepath}: {e}")
    return result


def load_wad_hashes() -> int:
    """Load CommunityDragon WAD hash files from cache. Returns count loaded."""
    global _wad_hashes, _wad_hash_count
    cache_dir = _get_wad_hash_cache_dir()
    total = 0

    for filename, _ in _WAD_HASH_URLS:
        fp = cache_dir / filename
        if fp.exists():
            parsed = _parse_wad_hash_file(fp)
            _wad_hashes.update(parsed)
            total += len(parsed)
            print(f"[WAD Tool] Loaded {len(parsed)} hashes from {filename}")

    _wad_hash_count = len(_wad_hashes)
    return total


def download_wad_hashes(callback=None) -> int:
    """Download CommunityDragon WAD hash files. Returns count downloaded."""
    global _wad_hash_status
    cache_dir = _get_wad_hash_cache_dir()
    downloaded = 0

    for i, (filename, url) in enumerate(_WAD_HASH_URLS):
        _wad_hash_status = f"Downloading {filename}..."
        if callback:
            callback(_wad_hash_status, i / len(_WAD_HASH_URLS))

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'BlenderMapgeoAddon/1.0'})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
            dest = cache_dir / filename
            with open(dest, 'wb') as f:
                f.write(data)
            downloaded += 1
            print(f"[WAD Tool] Downloaded {filename}")
        except Exception as e:
            print(f"[WAD Tool] Failed to download {filename}: {e}")

    _wad_hash_status = f"Downloaded {downloaded}/{len(_WAD_HASH_URLS)} files"
    if callback:
        callback(_wad_hash_status, 1.0)

    # Reload
    load_wad_hashes()
    return downloaded


def resolve_wad_hash(hash_val: int) -> str | None:
    """
    Resolve a WAD XXHash64 to a file path.
    Checks: custom hashes → hashlist → CommunityDragon hashes.
    """
    # Custom hashes from .bin scanning have highest priority
    if hash_val in _custom_hashes:
        return _custom_hashes[hash_val]
    # Hashlist file hashes
    if hash_val in _hashlist_hashes:
        return _hashlist_hashes[hash_val]
    # CommunityDragon hashes
    if hash_val in _wad_hashes:
        return _wad_hashes[hash_val]
    return None


def get_all_wad_hashes() -> dict[int, str]:
    """Get merged dict of all known WAD hashes."""
    merged = {}
    merged.update(_wad_hashes)
    merged.update(_hashlist_hashes)
    merged.update(_custom_hashes)
    return merged


# ============================================================================
# .bin File Path Extraction (Custom Hashing)
# ============================================================================

def extract_paths_from_bin(filepath: str) -> set[str]:
    """
    Parse a .bin (PropertyBin PROP) file and extract all string/file values
    that look like file paths. These paths can be hashed with XXHash64
    to resolve WAD entry hashes.
    
    Extracts from:
      - TYPE_STRING values that contain '/' or '.'
      - TYPE_FILE values (already XXHash64 hashes, we record them)
      - linked_files list
    """
    paths = set()

    try:
        from . import propertybin_parser
        parsed = propertybin_parser.parse_bin(filepath)
    except Exception as e:
        print(f"[WAD Tool] Failed to parse bin {filepath}: {e}")
        return paths

    # Linked files
    for lf in parsed.get("linked_files", []):
        if lf and ('/' in lf or '.' in lf):
            paths.add(lf.lower().replace('\\', '/'))

    # Walk entries and extract strings
    for entry in parsed.get("entries", []):
        _extract_paths_from_fields(entry.get("fields") or [], paths)

    return paths


def _extract_paths_from_fields(fields: list, paths: set):
    """Recursively extract path-like strings from bin fields."""
    for field in fields:
        _extract_paths_from_value(field, paths)


def _extract_paths_from_value(value: dict, paths: set):
    """Extract path-like strings from a single value node."""
    if not isinstance(value, dict):
        return

    type_id = value.get("type", 0)
    val = value.get("value")

    # String values
    if type_id == 16 and isinstance(val, str):  # TYPE_STRING
        if val and ('/' in val or '.' in val):
            paths.add(val.lower().replace('\\', '/'))

    # Container/list values
    elif type_id in (0x80, 0x81):
        for elem in value.get("values", []):
            _extract_paths_from_value(elem, paths)

    # Struct/embedded values
    elif type_id in (0x82, 0x83):
        for field in value.get("fields") or []:
            _extract_paths_from_value(field, paths)

    # Optional
    elif type_id == 0x85:
        inner = value.get("value")
        if inner:
            _extract_paths_from_value(inner, paths)

    # Map
    elif type_id == 0x86:
        for pair in value.get("pairs", []):
            _extract_paths_from_value(pair.get("key", {}), paths)
            _extract_paths_from_value(pair.get("value", {}), paths)


def scan_bin_files_for_paths(folder: str, progress_callback=None) -> dict[int, str]:
    """
    Recursively scan a folder for .bin files, extract all paths,
    and compute XXHash64 for each. Returns {hash: path} dict.
    """
    global _custom_hashes
    
    bin_files = []
    folder_path = Path(folder)
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.endswith('.bin'):
                bin_files.append(os.path.join(root, f))

    all_paths: set[str] = set()
    total = len(bin_files)

    for i, bf in enumerate(bin_files):
        if progress_callback and (i % 10 == 0):
            progress_callback(f"Scanning {i}/{total}: {os.path.basename(bf)}", i / max(total, 1))

        try:
            paths = extract_paths_from_bin(bf)
            all_paths.update(paths)
        except Exception as e:
            print(f"[WAD Tool] Error scanning {bf}: {e}")

    # Compute XXHash64 for all extracted paths
    result = {}
    for p in all_paths:
        h = xxhash64_path(p)
        result[h] = p

    _custom_hashes.update(result)
    
    if progress_callback:
        progress_callback(f"Done: {len(result)} paths from {total} .bin files", 1.0)
    
    print(f"[WAD Tool] Extracted {len(result)} unique paths from {total} .bin files")
    return result


# ============================================================================
# Hashlist File Support
# ============================================================================

def load_hashlist(filepath: str) -> int:
    """
    Load a hashlist text file. Each line is a file path.
    Computes XXHash64 for each and adds to the hashlist dictionary.
    Returns number of entries loaded.
    """
    global _hashlist_hashes
    count = 0
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # If line contains a hex hash followed by a path (CD format)
                parts = line.split(None, 1)
                if len(parts) == 2:
                    hex_part = parts[0]
                    # Check if first part looks like a hex hash
                    clean_hex = hex_part.lstrip('0x').lstrip('0X')
                    if len(clean_hex) >= 8 and all(c in '0123456789abcdefABCDEF' for c in clean_hex):
                        # It's a hash + path line
                        path = parts[1]
                        try:
                            h = int(hex_part, 16) if hex_part.startswith('0x') else int(hex_part, 16)
                            _hashlist_hashes[h] = path
                            count += 1
                            continue
                        except ValueError:
                            pass

                # Otherwise treat entire line as a path, compute hash
                path = line.lower().replace('\\', '/')
                h = xxhash64_path(path)
                _hashlist_hashes[h] = path
                count += 1

    except (IOError, OSError) as e:
        print(f"[WAD Tool] Failed to read hashlist {filepath}: {e}")

    print(f"[WAD Tool] Loaded {count} entries from hashlist")
    return count


def save_hashlist(filepath: str, hashes: dict[int, str] = None):
    """
    Save resolved hashes to a hashlist file.
    Format: xxhash64_hex path (one per line).
    If hashes is None, saves all known hashes.
    """
    if hashes is None:
        hashes = get_all_wad_hashes()

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# WAD Hashlist — {len(hashes)} entries\n")
            f.write(f"# Generated by MapgeoAddon WAD Tool\n")
            for h in sorted(hashes.keys()):
                path = hashes[h]
                f.write(f"{h:016x} {path}\n")
        print(f"[WAD Tool] Saved {len(hashes)} entries to {filepath}")
    except (IOError, OSError) as e:
        print(f"[WAD Tool] Failed to save hashlist: {e}")


# ============================================================================
# WAD Parser
# ============================================================================

def parse_wad(filepath: str) -> WadArchive:
    """
    Parse a WAD archive file (.wad / .wad.client).
    Supports versions 1.0, 2.0, 3.0.
    """
    wad = WadArchive()
    wad.filepath = filepath

    with open(filepath, 'rb') as f:
        data = f.read()

    r = _WadReader(data)

    # Magic
    magic = r.read_bytes(2)
    if magic != b'RW':
        raise ValueError(f"Invalid WAD magic: {magic!r} (expected b'RW')")

    wad.major_version = r.read_u8()
    wad.minor_version = r.read_u8()

    if wad.major_version == 1:
        # v1.0: entry_header_offset(u16) + entry_header_size(u16)
        entry_hdr_offset = r.read_u16()
        entry_hdr_cell_size = r.read_u16()
        entry_count = r.read_u32()
    elif wad.major_version == 2:
        # v2.0: ecdsaLength(1) + signature(83) + checksum(8) + tocOffset(2) + tocCellSize(2) + entryCount(4)
        ecdsa_length = r.read_u8()
        wad.signature = r.read_bytes(83)
        r.read_bytes(12)  # checksum(8) + tocOffset(2) + tocCellSize(2)
        entry_count = r.read_u32()
    elif wad.major_version == 3:
        # v3.0: signature(256) + checksum(8) + entryCount(4) = 272 total header
        wad.signature = r.read_bytes(256)
        r.read_bytes(8)  # 8-byte data checksum
        entry_count = r.read_u32()
    else:
        raise ValueError(f"Unsupported WAD version: {wad.major_version}.{wad.minor_version}")

    # Read entries
    # v1 entry = 24 bytes: hash(8) + offset(4) + csize(4) + usize(4) + type(1) + dup(1) + subchunkIdx(2)
    # v2/v3 entry = 32 bytes: same as v1 + checksum(8) (first 8 bytes of SHA-256)
    for _ in range(entry_count):
        entry = WadEntry()
        entry.path_hash = r.read_u64()
        entry.offset = r.read_u32()
        entry.compressed_size = r.read_u32()
        entry.uncompressed_size = r.read_u32()

        type_sub = r.read_u8()   # bits 0-3 = compression type, bits 4-7 = subchunk count
        entry.entry_type = type_sub & 0x0F
        entry.duplicate = bool(r.read_u8())  # duplicate flag
        r.read_u16()  # start subchunk index

        if wad.major_version >= 2:
            entry.checksum = r.read_u64()  # first 8 bytes of SHA-256

        # Try to resolve path
        resolved = resolve_wad_hash(entry.path_hash)
        if resolved:
            entry.resolved_path = resolved

        wad.entries.append(entry)

    print(f"[WAD Tool] Parsed {filepath}: v{wad.version_str}, {len(wad.entries)} entries")
    return wad


def read_entry_data(wad: WadArchive, entry: WadEntry) -> bytes:
    """
    Read and decompress a single entry's data from the WAD file.
    Returns the uncompressed bytes.
    """
    with open(wad.filepath, 'rb') as f:
        f.seek(entry.offset)
        raw = f.read(entry.compressed_size)

    if entry.entry_type == ENTRY_UNCOMPRESSED:
        return raw
    elif entry.entry_type == ENTRY_GZIP:
        return gzip.decompress(raw)
    elif entry.entry_type == ENTRY_ZSTD:
        try:
            import zstandard as zstd
            dctx = zstd.ZstdDecompressor()
            return dctx.decompress(raw, max_output_size=entry.uncompressed_size)
        except ImportError:
            # Fallback: try system zstd or raise helpful error
            raise ImportError(
                "Zstandard decompression requires the 'zstandard' Python package.\n"
                "Install it in Blender's Python:\n"
                "  import subprocess, sys\n"
                "  subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'zstandard'])"
            )
    elif entry.entry_type == ENTRY_ZSTD_CHUNKED:
        try:
            import zstandard as zstd
            import io as _io
            dctx = zstd.ZstdDecompressor()
            # ZstdChunked contains multiple zstd frames concatenated together.
            # Use stream_reader with read_across_frames to decompress all frames.
            try:
                reader = dctx.stream_reader(_io.BytesIO(raw), read_across_frames=True)
                return reader.read(entry.uncompressed_size)
            except TypeError:
                # Fallback for older zstandard without read_across_frames
                return dctx.decompress(raw, max_output_size=entry.uncompressed_size)
        except ImportError:
            raise ImportError(
                "Zstandard decompression requires the 'zstandard' Python package.\n"
                "Install it in Blender's Python:\n"
                "  import subprocess, sys\n"
                "  subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'zstandard'])"
            )
    elif entry.entry_type == ENTRY_SATELLITE:
        # Satellite entries reference external files
        # The data is the path to the external file
        return raw
    else:
        raise ValueError(f"Unknown entry type: {entry.entry_type}")


# ============================================================================
# WAD Extract
# ============================================================================

def extract_wad(wad: WadArchive, output_dir: str, filter_ext: str = "",
                progress_callback=None) -> tuple[int, int]:
    """
    Extract all entries from a WAD to output_dir.
    
    Entries with resolved paths get proper file names/directories.
    Entries without resolved paths go to a "raw/" subfolder with hex hash names.
    
    Args:
        wad: Parsed WadArchive
        output_dir: Directory to extract to
        filter_ext: If set, only extract files with this extension (e.g. ".bin")
        progress_callback: Optional (status_str, progress_float) callback
    
    Returns:
        (extracted_count, failed_count)
    """
    os.makedirs(output_dir, exist_ok=True)
    extracted = 0
    failed = 0
    total = len(wad.entries)

    for i, entry in enumerate(wad.entries):
        if progress_callback and (i % 50 == 0):
            progress_callback(f"Extracting {i}/{total}...", i / max(total, 1))

        # Determine output path
        if entry.resolved_path:
            rel_path = entry.resolved_path
        else:
            # No resolved name — use hex hash in raw/ folder
            ext = _guess_extension(wad, entry)
            rel_path = f"raw/{entry.path_hash:016x}{ext}"

        # Filter by extension
        if filter_ext and not rel_path.lower().endswith(filter_ext.lower()):
            continue

        out_path = os.path.join(output_dir, rel_path)

        # Handle Windows MAX_PATH (260 char) limitation
        if os.name == 'nt':
            # Truncate overly long filenames while keeping them unique
            dir_part = os.path.dirname(out_path)
            file_part = os.path.basename(out_path)
            name, ext = os.path.splitext(file_part)
            # Windows max filename component is 255 chars; keep total path sane
            max_name = 200 - len(ext)
            if len(name) > max_name:
                name = name[:max_name] + f"_{entry.path_hash:016x}"
                file_part = name + ext
                out_path = os.path.join(dir_part, file_part)
            # Use extended-length path prefix for long absolute paths
            abs_path = os.path.abspath(out_path)
            if len(abs_path) >= 260 and not abs_path.startswith('\\\\?\\'):
                out_path = '\\\\?\\' + abs_path
            else:
                out_path = abs_path

        try:
            data = read_entry_data(wad, entry)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'wb') as f:
                f.write(data)
            extracted += 1
        except Exception as e:
            print(f"[WAD Tool] Failed to extract {entry.display_path}: {e}")
            failed += 1

    if progress_callback:
        progress_callback(f"Done: {extracted} extracted, {failed} failed", 1.0)

    print(f"[WAD Tool] Extracted {extracted} files ({failed} failed)")
    return extracted, failed


def _guess_extension(wad: WadArchive, entry: WadEntry) -> str:
    """Try to guess file extension from file header magic bytes."""
    try:
        with open(wad.filepath, 'rb') as f:
            f.seek(entry.offset)
            header = f.read(min(entry.compressed_size, 16))

        # If compressed, decompress a small chunk for detection
        if entry.entry_type == ENTRY_GZIP:
            try:
                header = gzip.decompress(header[:256] if entry.compressed_size > 256 else header)[:16]
            except Exception:
                pass
        elif entry.entry_type in (ENTRY_ZSTD, ENTRY_ZSTD_CHUNKED):
            try:
                import zstandard as zstd
                import io as _io
                dctx = zstd.ZstdDecompressor()
                sample = header[:256] if entry.compressed_size > 256 else header
                try:
                    reader = dctx.stream_reader(_io.BytesIO(sample), read_across_frames=True)
                    header = reader.read(64)[:16]
                except TypeError:
                    header = dctx.decompress(sample, max_output_size=64)[:16]
            except Exception:
                pass

        # Check common magic bytes
        if header[:4] == b'PROP':
            return '.bin'
        elif header[:4] == b'DDS ':
            return '.dds'
        elif header[:3] == b'TEX':
            return '.tex'
        elif header[:4] == b'\x89PNG':
            return '.png'
        elif header[:2] == b'BM':
            return '.bmp'
        elif header[:4] == b'OggS':
            return '.ogg'
        elif header[:4] == b'RIFF':
            return '.wem'
        elif header[:8] == b'r3d2Mesh':
            return '.scb'
        elif header[:4] == b'r3d2':
            return '.skl'
        elif header[:4] in (b'\x00\x11\x22\x33', b'\x33\x22\x11\x00'):
            return '.skn'
        elif header[:4] == b'RW\x01\x00' or header[:4] == b'RW\x02\x00' or header[:4] == b'RW\x03\x00':
            return '.wad'
        elif header[:4] == b'BKHD':
            return '.bnk'
        elif header[:4] == b'PreL':
            return '.preload'
        elif header[:2] == b'[O':
            return '.sco'
        elif header[:1] == b'{':
            return '.json'

    except Exception:
        pass

    return '.dat'


# ============================================================================
# WAD Writer / Repacker
# ============================================================================

def repack_wad(source_dir: str, output_filepath: str, version: int = 3,
               compression: str = "zstd", hashlist_path: str = "",
               progress_callback=None) -> WadArchive:
    """
    Pack a directory structure into a WAD file.
    
    Files in the source_dir are packed into the WAD.
    File paths are converted to XXHash64 hashes for the entry table.
    
    For files in raw/ subfolder: the filename IS the hex hash (no re-hashing).
    For files in a "raw/" subfolder with hex-named files, we use the hex as the hash
    so we can repack unknown files that were extracted with their hash names.
    
    Args:
        source_dir: Directory containing files to pack
        output_filepath: Output .wad file path
        version: WAD version (1, 2, or 3)
        compression: "none", "gzip", or "zstd"
        hashlist_path: Optional hashlist file for path→hash mapping
        progress_callback: Optional (status_str, progress_float) callback
    
    Returns:
        The created WadArchive object
    """
    # Load hashlist if provided
    extra_hashes = {}
    if hashlist_path and os.path.isfile(hashlist_path):
        load_hashlist(hashlist_path)

    # Merge all known hashes for reverse lookup (path → hash)
    all_hashes = get_all_wad_hashes()
    path_to_hash = {v.lower(): k for k, v in all_hashes.items()}

    # Collect files
    source_path = Path(source_dir)
    file_list: list[tuple[int, str, str]] = []  # (hash, rel_path, abs_path)

    for root, dirs, files in os.walk(source_path):
        for fname in files:
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, source_dir).replace('\\', '/')

            # Check if it's a raw/ hex-named file
            if rel_path.startswith('raw/'):
                # Try to parse hex hash from filename
                basename = os.path.splitext(os.path.basename(rel_path))[0]
                try:
                    path_hash = int(basename, 16)
                    file_list.append((path_hash, rel_path, abs_path))
                    continue
                except ValueError:
                    pass

            # Normal file — look up hash
            key = rel_path.lower()
            if key in path_to_hash:
                path_hash = path_to_hash[key]
            else:
                # Compute new hash
                path_hash = xxhash64_path(rel_path)

            file_list.append((path_hash, rel_path, abs_path))

    # Sort by hash for efficient binary search in the game
    file_list.sort(key=lambda x: x[0])

    total = len(file_list)
    if progress_callback:
        progress_callback(f"Packing {total} files...", 0.0)

    # Determine compression function
    compress_fn = _get_compress_fn(compression)
    comp_type = {"none": ENTRY_UNCOMPRESSED, "gzip": ENTRY_GZIP, "zstd": ENTRY_ZSTD}.get(compression, ENTRY_GZIP)

    # Build entry data
    entries_data: list[tuple[WadEntry, bytes]] = []
    for i, (path_hash, rel_path, abs_path) in enumerate(file_list):
        if progress_callback and (i % 50 == 0):
            progress_callback(f"Compressing {i}/{total}: {os.path.basename(abs_path)}", i / max(total, 1))

        with open(abs_path, 'rb') as f:
            raw_data = f.read()

        uncompressed_size = len(raw_data)
        compressed_data = compress_fn(raw_data)
        compressed_size = len(compressed_data)

        # If compression made it bigger, store uncompressed
        actual_type = comp_type
        actual_data = compressed_data
        if comp_type != ENTRY_UNCOMPRESSED and compressed_size >= uncompressed_size:
            actual_type = ENTRY_UNCOMPRESSED
            actual_data = raw_data
            compressed_size = uncompressed_size

        # SHA256 first 8 bytes as u64 checksum
        sha_bytes = hashlib.sha256(raw_data).digest()[:8]
        checksum = struct.unpack_from('<Q', sha_bytes, 0)[0]

        entry = WadEntry()
        entry.path_hash = path_hash
        entry.compressed_size = len(actual_data)
        entry.uncompressed_size = uncompressed_size
        entry.entry_type = actual_type
        entry.checksum = checksum
        entry.resolved_path = rel_path

        entries_data.append((entry, actual_data))

    # Write WAD file
    if progress_callback:
        progress_callback(f"Writing WAD header...", 0.95)

    wad = WadArchive()
    wad.major_version = version
    wad.minor_version = 0
    wad.filepath = output_filepath

    _write_wad(wad, entries_data, output_filepath)

    if progress_callback:
        file_size = os.path.getsize(output_filepath)
        progress_callback(f"Done: {total} files, {file_size / (1024*1024):.1f} MB", 1.0)

    print(f"[WAD Tool] Packed {total} files to {output_filepath}")
    return wad


def _get_compress_fn(compression: str):
    """Get compression function."""
    if compression == "none":
        return lambda data: data
    elif compression == "gzip":
        return lambda data: gzip.compress(data, compresslevel=6)
    elif compression == "zstd":
        try:
            import zstandard as zstd
            cctx = zstd.ZstdCompressor(level=3)
            return cctx.compress
        except ImportError:
            print("[WAD Tool] Zstandard not available, falling back to gzip")
            return lambda data: gzip.compress(data, compresslevel=6)
    return lambda data: data


def _write_wad(wad: WadArchive, entries_data: list[tuple[WadEntry, bytes]], filepath: str):
    """Write a WAD v3 file."""
    entry_count = len(entries_data)

    # Calculate header size for v3
    # Magic(2) + version(2) + signature(256) + checksum(8) + entry_count(4) = 272
    # Each v3 entry: hash(8) + offset(4) + csize(4) + usize(4) + type(1) + dup(1) + subIdx(2) + checksum(8) = 32
    header_size = 272
    toc_size = entry_count * 32
    data_start = header_size + toc_size

    # Assign offsets
    current_offset = data_start
    for entry, data in entries_data:
        entry.offset = current_offset
        current_offset += len(data)

    with open(filepath, 'wb') as f:
        # Header
        f.write(b'RW')
        f.write(struct.pack('<BB', wad.major_version, wad.minor_version))

        if wad.major_version == 3:
            # 256-byte signature (zeroed for custom WADs)
            f.write(b'\x00' * 256)
            # 8-byte data checksum (zeroed for custom WADs)
            f.write(b'\x00' * 8)
        elif wad.major_version == 2:
            # ECDSA length(1) + signature(83) + checksum(8) + tocOffset(2) + tocCellSize(2)
            f.write(struct.pack('<B', 0))
            f.write(b'\x00' * 83)
            f.write(b'\x00' * 8)   # checksum
            f.write(struct.pack('<H', 104))  # tocOffset = 104 (start of entries)
            f.write(struct.pack('<H', 32))   # tocCellSize = 32

        f.write(struct.pack('<I', entry_count))

        # Entry table
        for entry, data in entries_data:
            f.write(struct.pack('<Q', entry.path_hash))
            f.write(struct.pack('<I', entry.offset))
            f.write(struct.pack('<I', entry.compressed_size))
            f.write(struct.pack('<I', entry.uncompressed_size))
            # type(1) + duplicate(1) + subchunkIdx(2)
            type_byte = entry.entry_type & 0x0F
            dup_byte = 1 if entry.duplicate else 0
            f.write(struct.pack('<B', type_byte))
            f.write(struct.pack('<B', dup_byte))
            f.write(struct.pack('<H', 0))  # start subchunk index
            # 8-byte checksum (v2/v3)
            f.write(struct.pack('<Q', entry.checksum))

        # File data
        for entry, data in entries_data:
            f.write(data)

    wad.entries = [e for e, _ in entries_data]


# ============================================================================
# Minimal binary reader for WAD parsing
# ============================================================================

class _WadReader:
    """Minimal binary reader."""
    __slots__ = ('data', 'pos', 'size')

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.size = len(data)

    def read_bytes(self, n: int) -> bytes:
        end = self.pos + n
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def read_u8(self) -> int:
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_u16(self) -> int:
        val = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return val

    def read_u32(self) -> int:
        val = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return val

    def read_u64(self) -> int:
        val = struct.unpack_from('<Q', self.data, self.pos)[0]
        self.pos += 8
        return val


# ============================================================================
# Blender Operators
# ============================================================================

# --- Runtime state stored on the Scene ---

_active_wad: WadArchive | None = None
_extract_status: str = ""
_scan_status: str = ""


class WADEntryItem(PropertyGroup):
    """A WAD entry displayed in the UI list."""
    path_hash_hex: StringProperty(name="Hash", default="")
    display_name: StringProperty(name="Name", default="")
    entry_type: StringProperty(name="Type", default="")
    compressed_size: IntProperty(name="CSize", default=0)
    uncompressed_size: IntProperty(name="Size", default=0)
    is_resolved: BoolProperty(name="Resolved", default=False)


class WadToolSettings(PropertyGroup):
    """Settings for the WAD tool."""
    wad_filepath: StringProperty(
        name="WAD File", subtype='FILE_PATH', default="",
        description="Path to .wad / .wad.client file"
    )
    extract_dir: StringProperty(
        name="Extract To", subtype='DIR_PATH', default="",
        description="Directory to extract WAD contents"
    )
    filter_ext: StringProperty(
        name="Filter Extension", default="",
        description="Only extract files with this extension (e.g. .bin, .dds). Leave empty for all"
    )
    hashlist_path: StringProperty(
        name="Hashlist", subtype='FILE_PATH', default="",
        description="Path to hashlist text file for path resolution"
    )
    bin_scan_folder: StringProperty(
        name="Bin Scan Folder", subtype='DIR_PATH', default="",
        description="Folder to recursively scan for .bin files to extract paths for hashing"
    )
    repack_source: StringProperty(
        name="Pack Source", subtype='DIR_PATH', default="",
        description="Source directory to pack into WAD"
    )
    repack_output: StringProperty(
        name="Pack Output", subtype='FILE_PATH', default="",
        description="Output WAD file path"
    )
    repack_compression: EnumProperty(
        name="Compression",
        items=[
            ('gzip', "GZip", "GZip compression (widely compatible)"),
            ('zstd', "Zstd", "Zstandard (smaller, faster, needs zstandard package)"),
            ('none', "None", "No compression (largest)"),
        ],
        default='gzip',
        description="Compression method for repacking"
    )
    entry_list_index: IntProperty(name="Entry Index", default=0)
    show_resolved_only: BoolProperty(
        name="Resolved Only", default=False,
        description="Show only entries with resolved file names"
    )
    search_filter: StringProperty(
        name="Search", default="",
        description="Filter entries by name or hash"
    )


# ============================================================================
# WAD Operators
# ============================================================================

class WAD_OT_open(Operator):
    """Open and parse a WAD archive file"""
    bl_idname = "wad.open_wad"
    bl_label = "Open WAD"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.wad;*.wad.client", options={'HIDDEN'})

    def execute(self, context):
        global _active_wad
        
        try:
            wad = parse_wad(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse WAD: {e}")
            return {'CANCELLED'}

        _active_wad = wad
        settings = context.scene.wad_tool_settings
        settings.wad_filepath = self.filepath

        # Populate UI entry list
        _populate_entry_list(context)

        resolved = sum(1 for e in wad.entries if e.resolved_path)
        self.report({'INFO'}, f"Opened WAD v{wad.version_str}: {len(wad.entries)} entries ({resolved} resolved)")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class WAD_OT_extract(Operator):
    """Extract all files from the loaded WAD"""
    bl_idname = "wad.extract_wad"
    bl_label = "Extract WAD"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _active_wad, _extract_status
        settings = context.scene.wad_tool_settings

        if not _active_wad:
            self.report({'ERROR'}, "No WAD file loaded")
            return {'CANCELLED'}

        output_dir = bpy.path.abspath(settings.extract_dir)
        if not output_dir:
            # Default to same directory as WAD file
            output_dir = os.path.join(os.path.dirname(_active_wad.filepath), "extracted")

        filter_ext = settings.filter_ext.strip()

        def progress(status, pct):
            global _extract_status
            _extract_status = status

        try:
            extracted, failed = extract_wad(_active_wad, output_dir, filter_ext, progress)
            self.report({'INFO'}, f"Extracted {extracted} files to {output_dir} ({failed} failed)")
        except Exception as e:
            self.report({'ERROR'}, f"Extraction failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class WAD_OT_extract_selected(Operator):
    """Extract only the selected entry from the WAD"""
    bl_idname = "wad.extract_selected"
    bl_label = "Extract Selected"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _active_wad
        settings = context.scene.wad_tool_settings

        if not _active_wad:
            self.report({'ERROR'}, "No WAD file loaded")
            return {'CANCELLED'}

        idx = settings.entry_list_index
        entries_coll = context.scene.wad_entry_list
        if idx < 0 or idx >= len(entries_coll):
            self.report({'ERROR'}, "No entry selected")
            return {'CANCELLED'}

        # Find the matching WadEntry
        item = entries_coll[idx]
        hash_val = int(item.path_hash_hex, 16) if item.path_hash_hex else 0
        entry = None
        for e in _active_wad.entries:
            if e.path_hash == hash_val:
                entry = e
                break

        if not entry:
            self.report({'ERROR'}, "Entry not found in WAD")
            return {'CANCELLED'}

        output_dir = bpy.path.abspath(settings.extract_dir)
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(_active_wad.filepath), "extracted")

        # Determine output path
        if entry.resolved_path:
            rel_path = entry.resolved_path
        else:
            ext = _guess_extension(_active_wad, entry)
            rel_path = f"raw/{entry.path_hash:016x}{ext}"

        out_path = os.path.join(output_dir, rel_path)

        try:
            data = read_entry_data(_active_wad, entry)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'wb') as f:
                f.write(data)
            self.report({'INFO'}, f"Extracted: {rel_path} ({len(data)} bytes)")
        except Exception as e:
            self.report({'ERROR'}, f"Extraction failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class WAD_OT_download_hashes(Operator):
    """Download CommunityDragon WAD hash database"""
    bl_idname = "wad.download_hashes"
    bl_label = "Download WAD Hashes"
    bl_options = {'REGISTER'}

    def execute(self, context):
        def _do_download():
            count = download_wad_hashes()
            print(f"[WAD Tool] Downloaded hashes, total: {len(_wad_hashes)}")

        thread = threading.Thread(target=_do_download, daemon=True)
        thread.start()
        thread.join(timeout=300)  # Wait up to 5 min

        total = len(_wad_hashes)
        self.report({'INFO'}, f"Downloaded WAD hashes: {total:,} entries")

        # Re-resolve if WAD is loaded
        if _active_wad:
            _resolve_wad_entries(_active_wad)
            _populate_entry_list(context)

        return {'FINISHED'}


class WAD_OT_load_hashlist(Operator):
    """Load a hashlist text file for path resolution"""
    bl_idname = "wad.load_hashlist"
    bl_label = "Load Hashlist"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.txt;*.hashlist", options={'HIDDEN'})

    def execute(self, context):
        count = load_hashlist(self.filepath)
        settings = context.scene.wad_tool_settings
        settings.hashlist_path = self.filepath

        self.report({'INFO'}, f"Loaded {count} entries from hashlist")

        # Re-resolve if WAD is loaded
        if _active_wad:
            _resolve_wad_entries(_active_wad)
            _populate_entry_list(context)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class WAD_OT_save_hashlist(Operator):
    """Save all known hashes to a hashlist file"""
    bl_idname = "wad.save_hashlist"
    bl_label = "Save Hashlist"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', default="wad_hashlist.txt")
    filter_glob: StringProperty(default="*.txt;*.hashlist", options={'HIDDEN'})

    def execute(self, context):
        save_hashlist(self.filepath)
        total = len(get_all_wad_hashes())
        self.report({'INFO'}, f"Saved {total} hashes to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class WAD_OT_scan_bin_files(Operator):
    """Scan .bin files in a folder to extract file paths for hash resolution"""
    bl_idname = "wad.scan_bin_files"
    bl_label = "Scan .bin Files"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _scan_status
        settings = context.scene.wad_tool_settings
        folder = bpy.path.abspath(settings.bin_scan_folder)

        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "Please set a valid folder to scan")
            return {'CANCELLED'}

        def progress(status, pct):
            global _scan_status
            _scan_status = status

        result = scan_bin_files_for_paths(folder, progress)
        self.report({'INFO'}, f"Extracted {len(result)} paths from .bin files")

        # Re-resolve if WAD is loaded
        if _active_wad:
            _resolve_wad_entries(_active_wad)
            _populate_entry_list(context)

        return {'FINISHED'}


class WAD_OT_repack(Operator):
    """Pack a folder into a WAD archive"""
    bl_idname = "wad.repack_wad"
    bl_label = "Repack WAD"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.wad_tool_settings
        source = bpy.path.abspath(settings.repack_source)
        output = bpy.path.abspath(settings.repack_output)

        if not source or not os.path.isdir(source):
            self.report({'ERROR'}, "Pack Source folder does not exist")
            return {'CANCELLED'}

        if not output:
            self.report({'ERROR'}, "Please specify an output WAD path")
            return {'CANCELLED'}

        hashlist = bpy.path.abspath(settings.hashlist_path)
        compression = settings.repack_compression

        def progress(status, pct):
            global _extract_status
            _extract_status = status

        try:
            wad = repack_wad(source, output, version=3, compression=compression,
                            hashlist_path=hashlist, progress_callback=progress)
            file_size = os.path.getsize(output)
            self.report({'INFO'},
                       f"Packed {len(wad.entries)} files to {output} ({file_size / (1024*1024):.1f} MB)")
        except Exception as e:
            self.report({'ERROR'}, f"Repacking failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class WAD_OT_refresh_list(Operator):
    """Refresh the entry list (apply filters)"""
    bl_idname = "wad.refresh_list"
    bl_label = "Refresh"
    bl_options = {'REGISTER'}

    def execute(self, context):
        _populate_entry_list(context)
        return {'FINISHED'}


# ============================================================================
# Helpers
# ============================================================================

def _resolve_wad_entries(wad: WadArchive):
    """Re-resolve all entries in the WAD against current hash databases."""
    resolved = 0
    for entry in wad.entries:
        path = resolve_wad_hash(entry.path_hash)
        if path:
            entry.resolved_path = path
            resolved += 1
    print(f"[WAD Tool] Resolved {resolved}/{len(wad.entries)} entries")


def _populate_entry_list(context):
    """Populate the UI entry list from the active WAD."""
    global _active_wad

    entries_coll = context.scene.wad_entry_list
    entries_coll.clear()

    if not _active_wad:
        return

    settings = context.scene.wad_tool_settings
    show_resolved = settings.show_resolved_only
    search = settings.search_filter.lower().strip()

    for entry in _active_wad.entries:
        # Filter: resolved only
        if show_resolved and not entry.resolved_path:
            continue

        display = entry.display_path

        # Filter: search
        if search and search not in display.lower() and search not in f"{entry.path_hash:016x}":
            continue

        item = entries_coll.add()
        item.path_hash_hex = f"{entry.path_hash:016x}"
        item.display_name = display
        item.entry_type = entry.type_name
        item.compressed_size = entry.compressed_size
        item.uncompressed_size = entry.uncompressed_size
        item.is_resolved = entry.resolved_path is not None


# ============================================================================
# UI List
# ============================================================================

class WAD_UL_entry_list(UIList):
    """UIList for WAD entries."""
    bl_idname = "WAD_UL_entry_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if item.is_resolved:
            icon_val = 'FILE_TICK'
        else:
            icon_val = 'FILE_HIDDEN'

        row = layout.row(align=True)
        row.label(text="", icon=icon_val)
        # Show truncated path for long names
        display = item.display_name
        if len(display) > 60:
            display = "..." + display[-57:]
        row.label(text=display)

        # Size indicator
        size_kb = item.uncompressed_size / 1024
        if size_kb >= 1024:
            row.label(text=f"{size_kb/1024:.1f}MB")
        elif size_kb >= 1:
            row.label(text=f"{size_kb:.0f}KB")
        else:
            row.label(text=f"{item.uncompressed_size}B")

        row.label(text=item.entry_type)


# ============================================================================
# Panel
# ============================================================================

class VIEW3D_PT_wad_tool(Panel):
    """WAD Archive Tool panel in the League Tools sidebar."""
    bl_label = "WAD Archive Tool"
    bl_idname = "VIEW3D_PT_wad_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_order = 60

    def draw(self, context):
        layout = self.layout
        settings = context.scene.wad_tool_settings

        # ── WAD File ──
        box = layout.box()
        box.label(text="WAD File", icon='PACKAGE')

        if _active_wad:
            row = box.row()
            row.label(text=os.path.basename(_active_wad.filepath))
            row.label(text=f"v{_active_wad.version_str}")
            
            resolved = sum(1 for e in _active_wad.entries if e.resolved_path)
            total = len(_active_wad.entries)
            box.label(text=f"{total:,} entries  ({resolved:,} resolved, {total - resolved:,} hashed)")

        box.operator("wad.open_wad", icon='FILE_FOLDER')

        # ── Hash Resolution ──
        box = layout.box()
        box.label(text="Hash Resolution", icon='WORDWRAP_ON')

        row = box.row(align=True)
        row.operator("wad.download_hashes", text="Download CD Hashes", icon='URL')
        wad_count = len(_wad_hashes)
        if wad_count > 0:
            row.label(text=f"{wad_count:,}")

        row = box.row(align=True)
        row.operator("wad.load_hashlist", text="Load Hashlist", icon='TEXT')
        hl_count = len(_hashlist_hashes)
        if hl_count > 0:
            row.label(text=f"{hl_count:,}")

        row = box.row(align=True)
        row.operator("wad.save_hashlist", text="Save Hashlist", icon='EXPORT')

        # .bin scan
        box2 = box.box()
        box2.label(text="Custom Hashing (.bin scan)", icon='FILE_SCRIPT')
        box2.prop(settings, "bin_scan_folder", text="")
        row = box2.row(align=True)
        row.operator("wad.scan_bin_files", text="Scan .bin Files", icon='VIEWZOOM')
        custom_count = len(_custom_hashes)
        if custom_count > 0:
            row.label(text=f"{custom_count:,}")

        total_hashes = len(_wad_hashes) + len(_hashlist_hashes) + len(_custom_hashes)
        if total_hashes > 0:
            box.label(text=f"Total known hashes: {total_hashes:,}", icon='INFO')

        # ── Entries List ──
        if _active_wad:
            box = layout.box()
            box.label(text="Entries", icon='LINENUMBERS_ON')

            row = box.row(align=True)
            row.prop(settings, "search_filter", text="", icon='VIEWZOOM')
            row.prop(settings, "show_resolved_only", text="", icon='FILTER')
            row.operator("wad.refresh_list", text="", icon='FILE_REFRESH')

            box.template_list(
                "WAD_UL_entry_list", "",
                context.scene, "wad_entry_list",
                settings, "entry_list_index",
                rows=8, maxrows=15,
            )

            # Selected entry info
            idx = settings.entry_list_index
            entries_coll = context.scene.wad_entry_list
            if 0 <= idx < len(entries_coll):
                item = entries_coll[idx]
                info = box.column(align=True)
                info.label(text=f"Hash: {item.path_hash_hex}")
                if item.is_resolved:
                    info.label(text=f"Path: {item.display_name}")
                info.label(text=f"Type: {item.entry_type}  |  Size: {item.uncompressed_size:,}B  (compressed: {item.compressed_size:,}B)")

        # ── Extract ──
        if _active_wad:
            box = layout.box()
            box.label(text="Extract", icon='EXPORT')
            box.prop(settings, "extract_dir", text="")
            box.prop(settings, "filter_ext", text="Filter")
            row = box.row(align=True)
            row.operator("wad.extract_wad", text="Extract All", icon='EXPORT')
            row.operator("wad.extract_selected", text="Extract Selected", icon='FILEBROWSER')

        # ── Repack ──
        box = layout.box()
        box.label(text="Repack", icon='IMPORT')
        box.prop(settings, "repack_source", text="Source")
        box.prop(settings, "repack_output", text="Output")
        box.prop(settings, "repack_compression")
        box.operator("wad.repack_wad", text="Pack WAD", icon='IMPORT')


# ============================================================================
# File Menu Integration
# ============================================================================

def menu_func_import_wad(self, context):
    self.layout.operator("wad.open_wad", text="League WAD Archive (.wad)")


# ============================================================================
# Registration
# ============================================================================

_classes = [
    WADEntryItem,
    WadToolSettings,
    WAD_UL_entry_list,
    WAD_OT_open,
    WAD_OT_extract,
    WAD_OT_extract_selected,
    WAD_OT_download_hashes,
    WAD_OT_load_hashlist,
    WAD_OT_save_hashlist,
    WAD_OT_scan_bin_files,
    WAD_OT_repack,
    WAD_OT_refresh_list,
    VIEW3D_PT_wad_tool,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.wad_tool_settings = bpy.props.PointerProperty(type=WadToolSettings)
    bpy.types.Scene.wad_entry_list = CollectionProperty(type=WADEntryItem)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_wad)

    # Auto-load cached WAD hashes
    load_wad_hashes()

    print("[WAD Tool] Registered")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_wad)
    del bpy.types.Scene.wad_entry_list
    del bpy.types.Scene.wad_tool_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    print("[WAD Tool] Unregistered")
