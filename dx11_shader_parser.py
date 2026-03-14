"""
League of Legends DX11 Shader Cache Parser
==========================================

Parses compiled DX11 shader TOC files and their bytecode bundles from:
  ShaderCache.dx11.wad/assets/shaders/generated/shaders/staticmesh/

Format reference: https://github.com/LeagueToolkit/league-toolkit/tree/main/crates/ltk_shader/src

File structure:
  .dx11       - TOC file (Table of Contents) with shader permutation info
  .dx11_0     - Bundle 0: bytecode for shader IDs 0-99
  .dx11_100   - Bundle 1: bytecode for shader IDs 100-199
  .dx11_200   - Bundle 2: bytecode for shader IDs 200-299
  ...
"""

import struct
import os
import sys
import glob
import json
from typing import List, Tuple, Optional, Dict, Set
from collections import Counter
from itertools import product


# ─── Constants ───────────────────────────────────────────────────────────────

TOC_MAGIC = "TOC3.0"
SHADERS_PER_BUNDLE = 100

SHADER_TYPE_VERTEX = 0
SHADER_TYPE_PIXEL = 1

SHADER_TYPE_NAMES = {
    SHADER_TYPE_VERTEX: "VS",
    SHADER_TYPE_PIXEL: "PS",
}


# ─── FNV-1a Hash (lowercase) ────────────────────────────────────────────────

FNV1A_OFFSET = 0x811C9DC5
FNV1A_PRIME = 0x01000193
FNV1A_MASK = 0xFFFFFFFF


def fnv1a_lower(text: str) -> int:
    """Compute FNV-1a hash on the lowercase ASCII bytes of text."""
    h = FNV1A_OFFSET
    for c in text.lower():
        h ^= ord(c)
        h = (h * FNV1A_PRIME) & FNV1A_MASK
    return h


# ─── Data Classes ────────────────────────────────────────────────────────────

class ShaderMacroDefinition:
    """A shader preprocessor macro (name=value pair)."""

    __slots__ = ("name", "value", "hash")

    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value
        # Hash = fnv1a_lower("NAME=VALUE") or fnv1a_lower("NAME") if value is empty
        key = f"{name}={value}" if value else name
        self.hash = fnv1a_lower(key)

    def __repr__(self):
        if self.value:
            return f"{self.name}={self.value}"
        return self.name


class ShaderToc:
    """Parsed contents of a .dx11 TOC file."""

    __slots__ = (
        "name", "shader_type", "shader_count", "base_defines_count",
        "bundled_shader_count", "base_defines", "shader_hashes", "shader_ids",
    )

    def __init__(self):
        self.name: str = ""
        self.shader_type: int = 0
        self.shader_count: int = 0
        self.base_defines_count: int = 0
        self.bundled_shader_count: int = 0
        self.base_defines: List[ShaderMacroDefinition] = []
        self.shader_hashes: List[int] = []  # u64 xxh64 hashes
        self.shader_ids: List[int] = []     # u32 IDs into bundles


class ShaderInfo:
    """Summary of a single shader object (VS or PS)."""

    def __init__(self, toc: ShaderToc, bundle_dir: str):
        self.toc = toc
        self.bundle_dir = bundle_dir

    @property
    def name(self) -> str:
        return self.toc.name

    @property
    def shader_type_name(self) -> str:
        return SHADER_TYPE_NAMES.get(self.toc.shader_type, "??")

    @property
    def define_names(self) -> List[str]:
        return [d.name for d in self.toc.base_defines]

    @property
    def permutation_count(self) -> int:
        return self.toc.shader_count

    @property
    def unique_bytecode_count(self) -> int:
        return self.toc.bundled_shader_count

    def get_bundle_files(self) -> List[str]:
        """Return paths to all bundle files for this shader."""
        base = self._toc_base_path()
        pattern = f"{base}_*"
        return sorted(glob.glob(pattern))

    def load_bytecode(self, shader_id: int) -> Optional[bytes]:
        """Load the DXBC bytecode for a specific shader ID from its bundle."""
        bundle_id = SHADERS_PER_BUNDLE * (shader_id // SHADERS_PER_BUNDLE)
        index_in_bundle = shader_id % SHADERS_PER_BUNDLE

        bundle_path = f"{self._toc_base_path()}_{bundle_id}"
        if not os.path.isfile(bundle_path):
            return None

        with open(bundle_path, "rb") as f:
            data = f.read()

        off = 0
        for i in range(index_in_bundle + 1):
            if off + 4 > len(data):
                return None
            size = struct.unpack_from("<I", data, off)[0]
            off += 4
            if i == index_in_bundle:
                return data[off:off + size]
            off += size

        return None

    def load_bytecode_by_hash(self, shader_hash: int) -> Optional[bytes]:
        """Load bytecode by permutation hash (xxh64)."""
        try:
            idx = self.toc.shader_hashes.index(shader_hash)
        except ValueError:
            return None
        return self.load_bytecode(self.toc.shader_ids[idx])

    def _toc_base_path(self) -> str:
        ext = "vs.dx11" if self.toc.shader_type == SHADER_TYPE_VERTEX else "ps.dx11"
        return os.path.join(self.bundle_dir, f"{self.toc.name}.{ext}")


# ─── Binary Reading ──────────────────────────────────────────────────────────

def _read_u32(data: bytes, offset: int) -> Tuple[int, int]:
    val = struct.unpack_from("<I", data, offset)[0]
    return val, offset + 4


def _read_u64(data: bytes, offset: int) -> Tuple[int, int]:
    val = struct.unpack_from("<Q", data, offset)[0]
    return val, offset + 8


def _read_sized_string(data: bytes, offset: int) -> Tuple[str, int]:
    length, offset = _read_u32(data, offset)
    s = data[offset:offset + length].decode("utf-8")
    return s, offset + length


def _read_macro_definition(data: bytes, offset: int) -> Tuple[ShaderMacroDefinition, int]:
    name, offset = _read_sized_string(data, offset)
    value, offset = _read_sized_string(data, offset)
    return ShaderMacroDefinition(name, value), offset


# ─── TOC Parsing ─────────────────────────────────────────────────────────────

def parse_toc(data: bytes, name: str = "") -> ShaderToc:
    """Parse a .dx11 TOC file from raw bytes."""
    toc = ShaderToc()
    toc.name = name
    off = 0

    # Magic
    magic, off = _read_sized_string(data, off)
    if magic != TOC_MAGIC:
        raise ValueError(f"Invalid TOC magic: {magic!r}, expected {TOC_MAGIC!r}")

    # Header
    toc.shader_count, off = _read_u32(data, off)
    toc.base_defines_count, off = _read_u32(data, off)
    toc.bundled_shader_count, off = _read_u32(data, off)
    toc.shader_type, off = _read_u32(data, off)

    # "baseDefines" section
    section_name, off = _read_sized_string(data, off)
    assert section_name == "baseDefines", f"Expected 'baseDefines', got {section_name!r}"

    toc.base_defines = []
    for _ in range(toc.base_defines_count):
        macro, off = _read_macro_definition(data, off)
        toc.base_defines.append(macro)

    # "shaders" section
    section_name, off = _read_sized_string(data, off)
    assert section_name == "shaders", f"Expected 'shaders', got {section_name!r}"

    # u64 hashes
    toc.shader_hashes = []
    for _ in range(toc.shader_count):
        h, off = _read_u64(data, off)
        toc.shader_hashes.append(h)

    # u32 IDs
    toc.shader_ids = []
    for _ in range(toc.shader_count):
        sid, off = _read_u32(data, off)
        toc.shader_ids.append(sid)

    return toc


def parse_toc_file(filepath: str) -> ShaderToc:
    """Parse a .dx11 TOC file from disk."""
    basename = os.path.basename(filepath)
    # Strip .vs.dx11 or .ps.dx11 to get shader name
    for ext in (".vs.dx11", ".ps.dx11"):
        if basename.endswith(ext):
            name = basename[:-len(ext)]
            break
    else:
        name = basename

    with open(filepath, "rb") as f:
        data = f.read()

    return parse_toc(data, name)


# ─── Directory Scanner ───────────────────────────────────────────────────────

def scan_shader_directory(directory: str) -> Dict[str, Dict[str, ShaderInfo]]:
    """
    Scan a shader directory and parse all TOC files.
    
    Returns dict: shader_name -> {"VS": ShaderInfo, "PS": ShaderInfo}
    """
    results: Dict[str, Dict[str, ShaderInfo]] = {}

    # Find all base .dx11 TOC files (not bundle files like .dx11_0)
    for filepath in sorted(glob.glob(os.path.join(directory, "*.dx11"))):
        basename = os.path.basename(filepath)
        # Skip bundle files
        if "_" in basename.split(".dx11")[-1]:
            continue

        toc = parse_toc_file(filepath)
        info = ShaderInfo(toc, directory)

        if toc.name not in results:
            results[toc.name] = {}

        results[toc.name][info.shader_type_name] = info

    return results


# ─── Bundle Analysis ─────────────────────────────────────────────────────────

def analyze_bundle(bundle_path: str) -> List[int]:
    """Read a bundle file and return the size of each bytecode entry."""
    sizes = []
    with open(bundle_path, "rb") as f:
        data = f.read()

    off = 0
    while off + 4 <= len(data):
        size = struct.unpack_from("<I", data, off)[0]
        off += 4
        if off + size > len(data):
            break
        sizes.append(size)
        off += size

    return sizes


# ─── Permutation Validation ──────────────────────────────────────────────────

try:
    import xxhash
    _HAS_XXHASH = True
except ImportError:
    # Blender disables user site-packages by default; add it manually
    import site
    _user_site = site.getusersitepackages()
    if _user_site and _user_site not in sys.path:
        sys.path.append(_user_site)
    try:
        import xxhash
        _HAS_XXHASH = True
    except ImportError:
        _HAS_XXHASH = False


def compute_permutation_hash(defines: Dict[str, str]) -> int:
    """
    Compute the xxh64 permutation hash for a set of defines.
    
    The game concatenates sorted "NAME=VALUE" pairs (uppercase) and xxh64-hashes the result.
    Requires: pip install xxhash
    """
    if not _HAS_XXHASH:
        raise RuntimeError("xxhash package required: pip install xxhash")
    s = "".join(f"{k}={v}" for k, v in sorted(defines.items()))
    return xxhash.xxh64(s).intdigest()


def filter_defines_against_toc(
    requested_defines: Dict[str, str],
    toc: ShaderToc,
) -> Dict[str, str]:
    """
    Filter requested defines to only those matching the shader's base_defines (by hash).
    
    This replicates the game's shader lookup filtering.
    """
    base_hashes = set(d.hash for d in toc.base_defines)
    result = {}
    for name, value in requested_defines.items():
        key = f"{name}={value}" if value else name
        h = fnv1a_lower(key)
        if h in base_hashes:
            result[name] = value
    return result


def validate_permutation(
    pass_defines: Dict[str, str],
    global_defines: Dict[str, str],
    toc: ShaderToc,
) -> Tuple[bool, int, Dict[str, str]]:
    """
    Check if a set of pass + global defines produces a valid permutation.
    
    Returns (is_valid, hash, filtered_defines).
    """
    all_defines = {**global_defines, **pass_defines}
    filtered = filter_defines_against_toc(all_defines, toc)
    h = compute_permutation_hash(filtered)
    is_valid = h in set(toc.shader_hashes)
    return is_valid, h, filtered


class PermutationMap:
    """
    Pre-computed map of all valid define combinations for a shader TOC.
    
    Brute-forces all possible combinations of base_defines and records which
    xxh64 hashes exist in the TOC. Useful for validation and finding
    the nearest valid permutation.
    """

    def __init__(self, toc: ShaderToc):
        if not _HAS_XXHASH:
            raise RuntimeError("xxhash package required: pip install xxhash")

        self.toc = toc
        self._hash_set = set(toc.shader_hashes)

        # Group base_defines by name, tracking unique values
        by_name: Dict[str, List[str]] = {}
        for d in toc.base_defines:
            by_name.setdefault(d.name, []).append(d.value)

        self._define_names = sorted(by_name.keys())
        # For each define: options are None (absent) + each defined value
        self._define_options = [
            (name, [None] + by_name[name]) for name in self._define_names
        ]

        # Multi-value defines (have both =0 and =1, or multiple values)
        self.multi_value_defines = {
            name: vals for name, vals in by_name.items() if len(vals) > 1
        }

        # Build valid permutation set
        self._valid_combos: List[Dict[str, str]] = []
        self._valid_hashes: Set[int] = set()
        self._build()

    def _build(self):
        for combo in product(*(opts for _, opts in self._define_options)):
            parts = {}
            for (name, _), value in zip(self._define_options, combo):
                if value is not None:
                    parts[name] = value
            s = "".join(f"{k}={v}" for k, v in sorted(parts.items()))
            h = xxhash.xxh64(s).intdigest()
            if h in self._hash_set:
                self._valid_combos.append(parts)
                self._valid_hashes.add(h)

    @property
    def valid_count(self) -> int:
        return len(self._valid_combos)

    @property
    def unique_hash_count(self) -> int:
        return len(self._valid_hashes)

    def is_valid(self, defines: Dict[str, str]) -> bool:
        """Check if an exact set of filtered defines is a valid permutation."""
        h = compute_permutation_hash(defines)
        return h in self._valid_hashes

    def find_nearest(
        self, target_defines: Dict[str, str], max_results: int = 5
    ) -> List[Tuple[int, Dict[str, str]]]:
        """
        Find the nearest valid permutations to a target set of defines.
        
        Returns list of (distance, defines) sorted by distance.
        Distance = number of define differences (additions + removals + value changes).
        """
        target_set = set(target_defines.items())
        scored = []

        for combo in self._valid_combos:
            combo_set = set(combo.items())
            # Symmetric difference = defines that differ
            diff = len(target_set.symmetric_difference(combo_set))
            scored.append((diff, combo))

        scored.sort(key=lambda x: x[0])
        return scored[:max_results]

    def get_define_constraints(self) -> Dict[str, dict]:
        """
        Analyze which defines can coexist and which are mutually exclusive.
        
        Returns per-define statistics.
        """
        stats = {}
        total = len(self._valid_combos)

        for name in self._define_names:
            values_in_combos = Counter()
            for combo in self._valid_combos:
                v = combo.get(name, "<absent>")
                values_in_combos[v] += 1
            stats[name] = {
                "total_valid": total,
                "values": dict(values_in_combos),
            }

        return stats

    def has_superset_of(self, defines: Dict[str, str]) -> bool:
        """
        Check if ANY valid permutation is a superset of the given defines.
        
        This handles the case where the material only specifies a partial set
        of defines and the engine adds implicit/global defines at runtime.
        If a valid permutation exists that contains all user defines (possibly
        with additional engine-provided defines), the material is compatible.
        """
        target_items = set(defines.items())
        if not target_items:
            # Empty defines always valid (there's always at least one permutation)
            return bool(self._valid_combos)
        for combo in self._valid_combos:
            if target_items.issubset(combo.items()):
                return True
        return False

    def find_nearest_supersets(
        self, target_defines: Dict[str, str], max_results: int = 5
    ) -> List[Tuple[int, Dict[str, str]]]:
        """
        Find nearest valid permutations measuring only USER changes needed.
        
        Distance = number of user defines that need to be changed or removed.
        Extra defines added by the engine (present in combo but not in target)
        are free (distance 0) since the engine provides them.
        """
        target_items = set(target_defines.items())
        target_keys = set(target_defines.keys())
        scored = []

        for combo in self._valid_combos:
            combo_items = set(combo.items())
            # User defines NOT satisfied by this combo
            # (user has it but combo doesn't, or value differs)
            unmet = 0
            for k, v in target_defines.items():
                combo_v = combo.get(k)
                if combo_v is None:
                    # User define absent in combo → user must remove it
                    unmet += 1
                elif combo_v != v:
                    # Value differs → user must change it
                    unmet += 1
            scored.append((unmet, combo))

        scored.sort(key=lambda x: x[0])
        return scored[:max_results]

    def get_cooccurrence(self, define_a: str, define_b: str) -> Dict[Tuple, int]:
        """Count how often two defines' states co-occur in valid permutations."""
        counts = Counter()
        for combo in self._valid_combos:
            va = combo.get(define_a, "<absent>")
            vb = combo.get(define_b, "<absent>")
            counts[(va, vb)] += 1
        return dict(counts)


# ─── Material Validation (High-level API for Blender UI) ────────────────────

# Default engine global defines always set by the game
DEFAULT_GLOBAL_DEFINES = {
    "HARDWARE_PCF": "1",
    "MRT_SUPPORTED": "1",
}

# Cache for loaded shader data  (directory → {name → {VS/PS → ShaderInfo}})
_shader_cache: Dict[str, Dict[str, Dict[str, ShaderInfo]]] = {}

# Cache for PermutationMap instances  ((directory, short_name) → PermutationMap)
_perm_map_cache: Dict[Tuple[str, str], PermutationMap] = {}


def _get_cached_shaders(
    directory: str,
) -> Optional[Dict[str, Dict[str, ShaderInfo]]]:
    """Get or build the shader cache for a directory."""
    if directory not in _shader_cache:
        if not os.path.isdir(directory):
            return None
        _shader_cache[directory] = scan_shader_directory(directory)
    return _shader_cache[directory]


def _get_cached_perm_map(
    directory: str, short_name: str, toc: ShaderToc,
) -> PermutationMap:
    """Get or build a cached PermutationMap."""
    key = (directory, short_name)
    if key not in _perm_map_cache:
        _perm_map_cache[key] = PermutationMap(toc)
    return _perm_map_cache[key]


def clear_shader_cache():
    """Clear the cached shader data (e.g. after changing game install path)."""
    _shader_cache.clear()
    _perm_map_cache.clear()


# ─── Shader-specific required material defines ──────────────────────────────
# These defines MUST be in the material's own macros — the engine does NOT
# provide them at runtime.  Removing them causes an in-game crash.

# Exact shader name (lowercase) → required defines
_SHADER_REQUIRED_DEFINES: Dict[str, Dict[str, str]] = {
    "defaultenv_flat_alphatest":             {"DISABLE_DEPTH_FOG": "1"},
    "defaultenv_flat_alphatest_doublesided": {"DISABLE_DEPTH_FOG": "1"},
}

# Pattern-based: if the shader name contains ONE of these substrings
# (case-insensitive), the listed defines are required.
_SHADER_PATTERN_REQUIRED_DEFINES: List[Tuple[str, Dict[str, str]]] = [
    ("blend", {"NO_BAKED_LIGHTING": "1"}),
]


def _get_missing_required_defines(
    short_name: str,
    user_defines: Dict[str, str],
) -> Dict[str, str]:
    """Return any shader-specific required defines missing from user_defines."""
    missing: Dict[str, str] = {}

    # Exact match rules
    required = _SHADER_REQUIRED_DEFINES.get(short_name, {})
    for k, v in required.items():
        if user_defines.get(k) != v:
            missing[k] = v

    # Pattern-based rules
    for pattern, req in _SHADER_PATTERN_REQUIRED_DEFINES:
        if pattern in short_name:
            for k, v in req.items():
                if user_defines.get(k) != v:
                    missing[k] = v

    return missing


def validate_material_defines(
    shader_path: str,
    material_macros: Dict[str, str],
    pass_macros: Optional[Dict[str, str]] = None,
    global_defines: Optional[Dict[str, str]] = None,
    shader_directory: Optional[str] = None,
) -> Dict:
    """
    Validate a material's defines against its shader's compiled permutations.
    
    Uses exact hash matching (same as the game engine): combines globals +
    material macros + pass macros, filters against base_defines, and checks
    if the resulting xxh64 hash exists in the shader's TOC.
    
    Args:
        shader_path: Full shader path, e.g. "Shaders/StaticMesh/DefaultEnv_Flat"
        material_macros: Material-level shader macros (mat["shader_macros"])
        pass_macros: Pass-level shaderMacros (from technique pass), if any
        global_defines: Engine global defines (defaults to HARDWARE_PCF=1, MRT_SUPPORTED=1)
        shader_directory: Path to extracted shader cache directory
    
    Returns dict with:
        status: "valid" | "invalid" | "unknown_shader" | "no_cache" | "no_xxhash"
        shader_name, filtered_defines, unrecognized_defines, hash,
        base_define_names, multi_value_defines, message,
        permutation_count, bytecode_count
    """
    if not _HAS_XXHASH:
        return {
            "status": "no_xxhash",
            "message": "xxhash not installed (pip install xxhash)",
        }

    if shader_directory is None:
        shader_directory = (
            r"C:\Riot Games\League of Legends\Game\DATA\FINAL"
            r"\ShaderCache.dx11.wad\assets\shaders\generated\shaders\staticmesh"
        )

    shaders = _get_cached_shaders(shader_directory)
    if shaders is None:
        return {
            "status": "no_cache",
            "message": f"Shader cache not found: {shader_directory}",
        }

    # Extract short shader name from path: "Shaders/StaticMesh/DefaultEnv_Flat" → "defaultenv_flat"
    short_name = shader_path.rsplit("/", 1)[-1].lower()

    if short_name not in shaders or "PS" not in shaders[short_name]:
        return {
            "status": "unknown_shader",
            "shader_name": short_name,
            "message": f"Shader '{short_name}' not found in cache",
        }

    ps_info = shaders[short_name]["PS"]
    toc = ps_info.toc

    if global_defines is None:
        global_defines = dict(DEFAULT_GLOBAL_DEFINES)

    # Combine all defines: global + material macros + pass macros
    all_defines = dict(global_defines)
    all_defines.update(material_macros)
    if pass_macros:
        all_defines.update(pass_macros)

    # Filter against base_defines (only keep defines this shader knows about)
    filtered = filter_defines_against_toc(all_defines, toc)

    # Find unrecognized defines (not in base_defines)
    base_define_hashes = set(d.hash for d in toc.base_defines)
    unrecognized = {}
    for name, value in all_defines.items():
        key = f"{name}={value}" if value else name
        h = fnv1a_lower(key)
        if h not in base_define_hashes:
            unrecognized[name] = value

    # Exact hash check (same as game engine)
    h = compute_permutation_hash(filtered)
    is_valid = h in set(toc.shader_hashes)

    # Collect base define info
    by_name: Dict[str, List[str]] = {}
    for d in toc.base_defines:
        by_name.setdefault(d.name, []).append(d.value)
    multi_value = {n: vs for n, vs in by_name.items() if len(vs) > 1}

    # If exact match fails, check if the material's own defines (without
    # globals) are compatible with at least one valid permutation.
    # The game engine provides globals and context-dependent defines at
    # runtime, so we only need to verify the material's explicit defines
    # can form part of a valid permutation.
    user_defines = dict(material_macros)
    if pass_macros:
        user_defines.update(pass_macros)

    if not is_valid:
        user_filtered = filter_defines_against_toc(user_defines, toc)
        pm = _get_cached_perm_map(shader_directory, short_name, toc)
        is_valid = pm.has_superset_of(user_filtered)

    # Check shader-specific required defines that the engine won't provide
    missing_required = _get_missing_required_defines(short_name, user_defines)
    if missing_required and is_valid:
        is_valid = False
        missing_str = ", ".join(f"{k}={v}" for k, v in sorted(missing_required.items()))

    if is_valid:
        msg = "Valid — permutation found for these defines"
    elif missing_required:
        msg = f"WILL CRASH — missing required define(s): {missing_str}"
    else:
        msg = "WILL CRASH — no compiled permutation for this define combination"

    return {
        "status": "valid" if is_valid else "invalid",
        "shader_name": short_name,
        "filtered_defines": filtered,
        "unrecognized_defines": unrecognized,
        "hash": h,
        "base_define_names": sorted(by_name.keys()),
        "multi_value_defines": multi_value,
        "missing_required": missing_required,
        "message": msg,
        "permutation_count": toc.shader_count,
        "bytecode_count": toc.bundled_shader_count,
    }


def find_nearest_valid_defines(
    shader_path: str,
    material_macros: Dict[str, str],
    pass_macros: Optional[Dict[str, str]] = None,
    global_defines: Optional[Dict[str, str]] = None,
    shader_directory: Optional[str] = None,
    max_results: int = 5,
) -> Optional[List[Tuple[int, Dict[str, str], List[str]]]]:
    """
    Find nearest valid permutations when current defines are invalid.
    
    Distance measures only changes the USER needs to make to their material
    macros.  Extra engine-provided defines are not counted.
    
    Returns list of (distance, full_filtered_defines, change_descriptions) or None if 
    shader not found or permutation map can't be built.
    """
    if not _HAS_XXHASH:
        return None

    if shader_directory is None:
        shader_directory = (
            r"C:\Riot Games\League of Legends\Game\DATA\FINAL"
            r"\ShaderCache.dx11.wad\assets\shaders\generated\shaders\staticmesh"
        )

    shaders = _get_cached_shaders(shader_directory)
    if shaders is None:
        return None

    short_name = shader_path.rsplit("/", 1)[-1].lower()
    if short_name not in shaders or "PS" not in shaders[short_name]:
        return None

    ps_info = shaders[short_name]["PS"]
    toc = ps_info.toc

    if global_defines is None:
        global_defines = dict(DEFAULT_GLOBAL_DEFINES)

    all_defines = dict(global_defines)
    all_defines.update(material_macros)
    if pass_macros:
        all_defines.update(pass_macros)

    filtered = filter_defines_against_toc(all_defines, toc)

    pm = _get_cached_perm_map(shader_directory, short_name, toc)
    raw_nearest = pm.find_nearest(filtered, max_results)

    results = []
    for dist, combo in raw_nearest:
        changes = []
        all_keys = sorted(set(list(filtered.keys()) + list(combo.keys())))
        for k in all_keys:
            old_val = filtered.get(k)
            new_val = combo.get(k)
            if old_val != new_val:
                if old_val is None:
                    changes.append(f"+ {k}={new_val}")
                elif new_val is None:
                    changes.append(f"- {k}")
                else:
                    changes.append(f"  {k}: {old_val} -> {new_val}")
        results.append((dist, combo, changes))

    return results


# ─── Report Generation ───────────────────────────────────────────────────────

def generate_report(directory: str) -> str:
    """Generate a comprehensive text report of all shaders in a directory."""
    shaders = scan_shader_directory(directory)
    lines = []
    lines.append("=" * 80)
    lines.append("League of Legends DX11 Shader Cache Report")
    lines.append(f"Directory: {directory}")
    lines.append(f"Total unique shader names: {len(shaders)}")
    lines.append("=" * 80)

    # Collect all unique defines across all shaders
    all_defines = set()
    for name, types in shaders.items():
        for type_name, info in types.items():
            for d in info.toc.base_defines:
                all_defines.add(d.name)

    lines.append(f"\nAll unique base defines ({len(all_defines)}):")
    for d in sorted(all_defines):
        lines.append(f"  {d}")

    lines.append("")
    lines.append("-" * 80)
    lines.append(f"{'Shader Name':<45} {'Type':<4} {'Defines':<8} {'Perms':<8} {'Bytecodes':<10}")
    lines.append("-" * 80)

    total_perms = 0
    total_bytecodes = 0

    for name in sorted(shaders.keys()):
        types = shaders[name]
        for type_name in ["VS", "PS"]:
            if type_name not in types:
                continue
            info = types[type_name]
            t = info.toc
            lines.append(
                f"{name:<45} {type_name:<4} {t.base_defines_count:<8} "
                f"{t.shader_count:<8} {t.bundled_shader_count:<10}"
            )
            total_perms += t.shader_count
            total_bytecodes += t.bundled_shader_count

    lines.append("-" * 80)
    lines.append(f"Total: {total_perms} permutations, {total_bytecodes} unique bytecodes")
    lines.append("")

    # Detailed per-shader info
    lines.append("=" * 80)
    lines.append("DETAILED SHADER INFORMATION")
    lines.append("=" * 80)

    for name in sorted(shaders.keys()):
        types = shaders[name]
        lines.append(f"\n{'─' * 60}")
        lines.append(f"  {name}")
        lines.append(f"{'─' * 60}")

        for type_name in ["VS", "PS"]:
            if type_name not in types:
                continue
            info = types[type_name]
            t = info.toc

            lines.append(f"\n  [{type_name}] {t.shader_count} permutations, "
                         f"{t.bundled_shader_count} unique bytecodes")
            lines.append(f"  Base defines ({t.base_defines_count}):")
            for d in t.base_defines:
                lines.append(f"    {d.name} = {d.value!r}  (hash: 0x{d.hash:08x})")

            # Bundle info
            bundles = info.get_bundle_files()
            if bundles:
                total_bytes = sum(os.path.getsize(b) for b in bundles)
                lines.append(f"  Bundles: {len(bundles)} files, {total_bytes:,} bytes total")

            # ID range
            if t.shader_ids:
                lines.append(f"  Shader ID range: {min(t.shader_ids)} - {max(t.shader_ids)}")

    return "\n".join(lines)


def generate_defines_matrix(directory: str) -> str:
    """Generate a matrix showing which defines each shader uses."""
    shaders = scan_shader_directory(directory)

    # Collect all unique defines
    all_defines = sorted(set(
        d.name
        for types in shaders.values()
        for info in types.values()
        for d in info.toc.base_defines
    ))

    lines = []
    lines.append("Shader Defines Matrix (X = shader uses this define)")
    lines.append("=" * 80)

    # Header
    header = f"{'Shader':<40}"
    for d in all_defines:
        header += f" {d[:3]:>3}"
    lines.append(header)
    lines.append("-" * len(header))

    # Build legend
    abbrevs = {}
    for d in all_defines:
        abbrevs[d] = d[:3]

    for name in sorted(shaders.keys()):
        types = shaders[name]
        # Use PS defines if available, otherwise VS
        info = types.get("PS") or types.get("VS")
        if not info:
            continue

        define_names = set(d.name for d in info.toc.base_defines)
        row = f"{name:<40}"
        for d in all_defines:
            row += f" {'  X' if d in define_names else '  .'}"
        lines.append(row)

    lines.append("")
    lines.append("Legend:")
    for d in all_defines:
        lines.append(f"  {d[:3]} = {d}")

    return "\n".join(lines)


def export_shader_data_json(directory: str) -> dict:
    """Export all shader data as a JSON-serializable dict."""
    shaders = scan_shader_directory(directory)
    result = {}

    for name in sorted(shaders.keys()):
        types = shaders[name]
        shader_data = {}

        for type_name in ["VS", "PS"]:
            if type_name not in types:
                continue
            info = types[type_name]
            t = info.toc

            shader_data[type_name] = {
                "shader_count": t.shader_count,
                "base_defines_count": t.base_defines_count,
                "bundled_shader_count": t.bundled_shader_count,
                "base_defines": [
                    {"name": d.name, "value": d.value, "hash": f"0x{d.hash:08x}"}
                    for d in t.base_defines
                ],
                "bundle_files": len(info.get_bundle_files()),
                "id_range": [min(t.shader_ids), max(t.shader_ids)] if t.shader_ids else None,
            }

        result[name] = shader_data

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    DEFAULT_DIR = (
        r"C:\Riot Games\League of Legends\Game\DATA\FINAL"
        r"\ShaderCache.dx11.wad\assets\shaders\generated\shaders\staticmesh"
    )

    directory = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR

    if not os.path.isdir(directory):
        print(f"Directory not found: {directory}")
        sys.exit(1)

    print(generate_report(directory))

    # Also export JSON
    data = export_shader_data_json(directory)
    json_path = os.path.join(os.path.dirname(__file__), "dx11_shader_data.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nJSON data exported to: {json_path}")
