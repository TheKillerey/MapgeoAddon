"""
League of Legends Project Manager for Blender
Manages mod projects with WAD extraction, map loading, and asset editing.

Provides a unified workflow:
1. Select a project folder (extracted WAD or mod folder)
2. Auto-detect League of Legends installation for base assets
3. Choose which map/variant to load
4. Load mapgeo + materials (from mod or base game) 
5. Edit and reload
"""

import bpy
import copy
import json
import os
import re
import shutil
import struct
import tempfile
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty, IntProperty,
    CollectionProperty, PointerProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList
from pathlib import Path


# ============================================================================
# Constants — Known Map IDs
# ============================================================================

MAP_NAMES = {
    "Map11": "Summoner's Rift",
    "Map12": "Howling Abyss",
    "Map21": "Nexus Blitz",
    "Map22": "Teamfight Tactics",
    "Map30": "Arena",
    "Map33": "Swarm",
    "Map35": "ARAM 2v2v2v2",
}

# Known League install paths (Windows)
LEAGUE_INSTALL_CANDIDATES = [
    r"C:\Riot Games\League of Legends",
    r"D:\Riot Games\League of Legends",
    r"E:\Riot Games\League of Legends",
    r"C:\Program Files\Riot Games\League of Legends",
    r"C:\Program Files (x86)\Riot Games\League of Legends",
    r"D:\Program Files\Riot Games\League of Legends",
]

# Standard WAD subpath from League install
MAPS_WAD_SUBPATH = os.path.join("Game", "DATA", "FINAL", "Maps", "Shipping")

# Known field hashes for StaticMaterialDef (FNV-1a 32-bit)
HASH_NAME = 0x8d39bde6          # "name"
HASH_MAT_TYPE = 0x5127f14d      # material type (u32)
HASH_SAMPLER_VALUES = 0x0a6f0eb5
HASH_PARAM_VALUES = 0xd0ab46b8
HASH_SWITCH_VALUES = 0xdd7ddb9d
HASH_SHADER_MACROS = 0xe6d67ded
HASH_TECHNIQUES = 0x844f384e
HASH_CHILD_TECHNIQUES = 0x9330e6b6

# Sampler sub-fields
HASH_TEXTURE_NAME = 0xb311d4ef   # textureName
HASH_SAMPLER_NAME_LEGACY = 0x02e7fb4c  # samplerName (legacy)
HASH_TEXTURE_PATH = 0xf0a363e3   # texturePath
HASH_ADDRESS_U = 0x111ec6d2
HASH_ADDRESS_V = 0x101ec53f
HASH_ADDRESS_W = 0x0f1ec3ac

# Param sub-fields
HASH_PARAM_VALUE = 0x425ed3ca    # value (vec4)

# Switch sub-fields
HASH_SWITCH_ON = 0x72d1c564      # "on" (bool)
HASH_SWITCH_GROUP = 0x5fb91e8c    # "group" (optional string)

# Technique sub-fields
HASH_TECHNIQUE_NAME = 0x8d39bde6  # same as name
HASH_PASSES = 0x917e428e

# Pass sub-fields
HASH_SHADER = 0xc5ac22aa
HASH_BLEND_ENABLE = 0x38579b90
HASH_CULL_ENABLE = 0x2346bd76
HASH_SRC_COLOR_BLEND = 0x1ebe0e59
HASH_SRC_ALPHA_BLEND = 0x0dbbba93
HASH_DST_COLOR_BLEND = 0x6df4a57b
HASH_DST_ALPHA_BLEND = 0x7cf711b1
HASH_WRITE_MASK = 0x78d0a46c
HASH_PASS_SHADER_MACROS = 0xe6d67ded
HASH_PARENT_NAME = 0xb696a5fe     # "parentName" (for childTechniques)

# Type hash for StaticMaterialDef
HASH_STATIC_MATERIAL_DEF = 0xff9d3409


# ============================================================================
# League Installation Detection
# ============================================================================

def find_league_install() -> str:
    """Auto-detect League of Legends installation directory."""
    # Check common paths
    for path in LEAGUE_INSTALL_CANDIDATES:
        if os.path.isdir(path):
            wad_dir = os.path.join(path, MAPS_WAD_SUBPATH)
            if os.path.isdir(wad_dir):
                return path
    
    # Try Windows registry
    try:
        import winreg
        for root_key in [winreg.HKLM, winreg.HKCU]:
            for sub_path in [
                r"SOFTWARE\WOW6432Node\Riot Games, Inc\League of Legends",
                r"SOFTWARE\Riot Games, Inc\League of Legends",
                r"SOFTWARE\Riot Games\League of Legends",
            ]:
                try:
                    key = winreg.OpenKey(root_key, sub_path)
                    location, _ = winreg.QueryValueEx(key, "Location")
                    winreg.CloseKey(key)
                    if location and os.path.isdir(location):
                        return location
                except (FileNotFoundError, OSError):
                    continue
    except ImportError:
        pass
    
    return ""


def get_maps_wad_dir(league_path: str) -> str:
    """Get the Maps WAD directory from a League install path."""
    if not league_path:
        return ""
    wad_dir = os.path.join(league_path, MAPS_WAD_SUBPATH)
    return wad_dir if os.path.isdir(wad_dir) else ""


def discover_available_wads(wad_dir: str) -> list[dict]:
    """
    Discover available WAD files in the maps directory.
    Returns list of dicts with 'map_id', 'display_name', 'wad_path', 'wad_type'.
    """
    if not wad_dir or not os.path.isdir(wad_dir):
        return []
    
    wads = []
    for fname in os.listdir(wad_dir):
        fpath = os.path.join(wad_dir, fname)
        if not os.path.isfile(fpath):
            continue
        
        # Match WAD files: Map11.wad, Map11.wad.client, Map11LEVELS.wad, etc.
        name_lower = fname.lower()
        if '.wad' not in name_lower:
            continue
        
        # Determine map ID and type
        base = fname.split('.')[0]  # "Map11" or "Map11LEVELS" or "Common"
        
        if base.lower().startswith('common'):
            map_id = "Common"
            wad_type = "client" if ".wad.client" in fname else "base"
            if "LEVELS" in base:
                wad_type = "levels"
        else:
            # Extract map ID (e.g., "Map11" from "Map11LEVELS")
            map_id = base.replace("LEVELS", "")
            if "LEVELS" in base:
                wad_type = "levels"
            elif ".wad.client" in fname:
                wad_type = "client"
            else:
                wad_type = "base"
        
        display = MAP_NAMES.get(map_id, map_id)
        wads.append({
            'map_id': map_id,
            'display_name': display,
            'wad_path': fpath,
            'wad_type': wad_type,
            'filename': fname,
        })
    
    return sorted(wads, key=lambda w: (w['map_id'], w['wad_type']))


# ============================================================================
# Active Map Skin Detection (from Riot WAD)
# ============================================================================

# Field/type hashes for map skin detection
HASH_MAP_SKINS = 0x2ed3b95d          # "mapSkins" field in map .bin

def get_active_map_skins_from_wad(league_path: str, map_id: str, count: int = 2) -> list[str]:
    """
    Read the map .bin file from the Riot WAD to determine the currently active
    map skins.  Riot stores all available skins in a ``mapSkins`` list; the
    last *count* entries are the ones the live client currently uses.

    Args:
        league_path: Path to the League of Legends installation.
        map_id: Map ID, e.g. "map11".
        count: Number of skins to return from the end of the list (default 2).

    Returns:
        List of skin variant names (e.g. ["Sodapop_SRS", "ContentCapture"]).
        Empty list on failure.
    """
    import tempfile
    import shutil

    wad_dir = get_maps_wad_dir(league_path)
    if not wad_dir:
        return []

    # Normalise: "map11" → "Map11"
    map_id_title = map_id[0].upper() + map_id[1:] if map_id else map_id

    # --- locate the WAD file ---
    wad_path = ""
    for fname in os.listdir(wad_dir):
        fl = fname.lower()
        prefix = map_id_title.lower()
        if not fl.startswith(prefix):
            continue
        remainder = fl[len(prefix):]
        if remainder.startswith('.') and not remainder.startswith('.wad'):
            continue  # locale WAD
        if 'levels' in fl:
            continue
        if '.wad' not in fl:
            continue
        candidate = os.path.join(wad_dir, fname)
        if not wad_path or '.wad.client' in fl:
            wad_path = candidate  # prefer .wad.client
    if not wad_path:
        print(f"[Project Manager] No WAD found for {map_id_title}")
        return []

    # --- open the WAD and locate  data/maps/shipping/<mapid>/<mapid>.bin ---
    try:
        from . import wad_tool
    except ImportError:
        from wad_tool import xxhash64_path, parse_wad, read_entry_data
        wad_tool = None

    bin_path_str = f"data/maps/shipping/{map_id.lower()}/{map_id.lower()}.bin"
    target_hash = wad_tool.xxhash64_path(bin_path_str) if wad_tool else xxhash64_path(bin_path_str)

    try:
        tmp_wad = None
        try:
            wad = (wad_tool.parse_wad if wad_tool else parse_wad)(wad_path)
        except PermissionError:
            tmp_wad = os.path.join(tempfile.gettempdir(), os.path.basename(wad_path))
            shutil.copy2(wad_path, tmp_wad)
            wad = (wad_tool.parse_wad if wad_tool else parse_wad)(tmp_wad)
    except Exception as e:
        print(f"[Project Manager] Failed to parse WAD for skin detection: {e}")
        return []
    finally:
        # Clean up temporary WAD copy if created
        if tmp_wad and os.path.isfile(tmp_wad):
            try:
                os.remove(tmp_wad)
            except OSError:
                pass

    target_entry = None
    for entry in wad.entries:
        if entry.path_hash == target_hash:
            target_entry = entry
            break

    if target_entry is None:
        print(f"[Project Manager] {bin_path_str} not found in WAD")
        return []

    # --- decompress & parse the .bin ---
    try:
        raw_data = (wad_tool.read_entry_data if wad_tool else read_entry_data)(wad, target_entry)
    except Exception as e:
        print(f"[Project Manager] Failed to read {bin_path_str}: {e}")
        return []

    tmp_bin = os.path.join(tempfile.gettempdir(), f"{map_id.lower()}_skin_detect.bin")
    try:
        with open(tmp_bin, 'wb') as f:
            f.write(raw_data)

        from . import propertybin_parser
        parsed = propertybin_parser.parse_bin(tmp_bin)
    except Exception as e:
        print(f"[Project Manager] Failed to parse {bin_path_str}: {e}")
        return []
    finally:
        try:
            os.remove(tmp_bin)
        except OSError:
            pass

    # --- find mapSkins list and resolve the last N entries ---
    skin_link_hashes = []
    for entry in parsed.get('entries', []):
        for field in entry.get('fields', []):
            if field.get('name_hash_int') == HASH_MAP_SKINS:
                # values is a list of struct-link dicts with 'value' = "0x....." hash
                for v in field.get('values', []):
                    if isinstance(v, dict):
                        skin_link_hashes.append(v.get('value', ''))
                    elif isinstance(v, str):
                        skin_link_hashes.append(v)
                break
        if skin_link_hashes:
            break

    if not skin_link_hashes:
        print(f"[Project Manager] mapSkins field not found in {bin_path_str}")
        return []

    # Take the last N link hashes
    last_hashes = set(skin_link_hashes[-count:])

    # Resolve each link hash → entry path_hash → name field
    skin_names = []
    for entry in parsed.get('entries', []):
        if entry.get('path_hash') in last_hashes:
            for field in entry.get('fields', []):
                if field.get('name_hash_int') == HASH_NAME:
                    skin_names.append(field.get('value', ''))
                    break

    # Maintain original order (last entries first)
    ordered = []
    for lh in skin_link_hashes[-count:]:
        for entry in parsed.get('entries', []):
            if entry.get('path_hash') == lh:
                for field in entry.get('fields', []):
                    if field.get('name_hash_int') == HASH_NAME:
                        ordered.append(field.get('value', ''))
                        break
                break

    if ordered:
        print(f"[Project Manager] Active map skins for {map_id}: {ordered}")
        return ordered

    print(f"[Project Manager] Could not resolve skin names from mapSkins")
    return skin_names


def _get_wad_cache_root() -> str:
    """Return a stable, persistent directory for WAD extraction caches.

    Uses the Blender user config directory so the cache survives across
    Blender sessions (unlike bpy.app.tempdir which changes every launch).
    """
    cache_root = os.path.join(
        bpy.utils.resource_path('USER'), "mapgeo_addon", "wad_cache"
    )
    os.makedirs(cache_root, exist_ok=True)
    return cache_root


def _rmtree_long_path(path: str):
    """Remove a directory tree, handling Windows long paths (>260 chars).

    WAD extraction can create files whose absolute path exceeds MAX_PATH.
    Standard shutil.rmtree fails on those.  We use the ``\\\\?\\`` extended-
    length prefix on Windows so the OS accepts the full path.
    """
    if os.name == 'nt':
        abs_path = os.path.abspath(path)
        if not abs_path.startswith('\\\\?\\'):
            abs_path = '\\\\?\\' + abs_path
        shutil.rmtree(abs_path)
    else:
        shutil.rmtree(path)


def _clean_wad_cache_dir(cache_dir: str):
    """Remove an existing WAD cache directory to free disk space before re-extraction."""
    import shutil
    if os.path.isdir(cache_dir):
        try:
            _rmtree_long_path(cache_dir)
            print(f"[Project Manager] Cleaned old WAD cache: {cache_dir}")
        except Exception as e:
            print(f"[Project Manager] Failed to clean cache {cache_dir}: {e}")


def clean_all_wad_caches():
    """Remove all WAD extraction caches.
    
    Cleans both the current stable cache location and any leftover caches
    in old Blender temp directories.
    Returns the number of cache directories removed.
    """
    import shutil
    removed = 0

    # Clean the stable cache location
    cache_root = _get_wad_cache_root()
    if os.path.isdir(cache_root):
        for name in os.listdir(cache_root):
            sub = os.path.join(cache_root, name)
            if os.path.isdir(sub):
                try:
                    _rmtree_long_path(sub)
                    removed += 1
                except Exception as e:
                    print(f"[Project Manager] Failed to remove {sub}: {e}")

    # Also clean any old session-temp caches (legacy location)
    old_cache = os.path.join(bpy.app.tempdir, "league_wad_cache")
    if os.path.isdir(old_cache):
        try:
            _rmtree_long_path(old_cache)
            removed += 1
            print(f"[Project Manager] Cleaned legacy temp cache: {old_cache}")
        except Exception as e:
            print(f"[Project Manager] Failed to remove legacy cache: {e}")

    if removed:
        print(f"[Project Manager] Cleaned {removed} WAD cache(s)")
    return removed


def _cleanup_stale_temp_caches():
    """Remove league_wad_cache folders left in old Blender temp directories.
    
    Blender creates a new temp dir each session (e.g. blender_a32076/).
    Previous sessions may have left WAD caches behind — clean them up.
    Only removes caches from directories that are NOT the current session.
    """
    import shutil
    try:
        current_temp = bpy.app.tempdir.rstrip(os.sep)
        parent = os.path.dirname(current_temp)
        if not os.path.isdir(parent):
            return
        removed = 0
        for name in os.listdir(parent):
            if not name.startswith("blender_"):
                continue
            candidate = os.path.join(parent, name)
            # Skip the current session's temp dir
            if candidate.rstrip(os.sep) == current_temp:
                continue
            wad_cache = os.path.join(candidate, "league_wad_cache")
            if os.path.isdir(wad_cache):
                try:
                    _rmtree_long_path(wad_cache)
                    removed += 1
                except Exception:
                    pass
        if removed:
            print(f"[Project Manager] Cleaned {removed} stale WAD cache(s) from old Blender temp dirs")
    except Exception:
        pass  # Non-critical — don't break addon startup


def _ensure_riot_wad_cache(league_path: str, map_id: str) -> str:
    """Extract the Riot WAD for a map into a cache directory and return the cache path.
    
    Returns empty string on failure.
    """
    wad_dir = get_maps_wad_dir(league_path)
    if not wad_dir:
        return ""
    
    map_id_title = map_id[0].upper() + map_id[1:] if map_id else map_id
    
    # Find WAD candidates
    wad_candidates = []
    for fname in os.listdir(wad_dir):
        fname_lower = fname.lower()
        map_prefix = map_id_title.lower()
        if not fname_lower.startswith(map_prefix):
            continue
        if '.wad' not in fname_lower:
            continue
        if 'level' in fname_lower:
            continue
        remainder = fname_lower[len(map_prefix):]
        if remainder.startswith('.') and not remainder.startswith('.wad'):
            continue
        wad_candidates.append(os.path.join(wad_dir, fname))
    
    wad_candidates.sort(key=lambda p: (0 if '.wad.client' in p.lower() else 1))
    if not wad_candidates:
        return ""
    
    cache_dir = os.path.join(_get_wad_cache_root(), map_id_title)
    
    # Detect incomplete cache: directory exists but lacks the expected data subdir
    if os.path.isdir(cache_dir):
        expected_subdir = os.path.join(cache_dir, "data", "maps", "mapgeometry")
        if not os.path.isdir(expected_subdir):
            print(f"[Project Manager] WAD cache looks incomplete, re-extracting: {cache_dir}")
            try:
                _rmtree_long_path(cache_dir)
            except Exception as e:
                print(f"[Project Manager] Failed to clean incomplete cache: {e}")
    
    if not os.path.isdir(cache_dir):
        try:
            from . import wad_tool
            import shutil
            import tempfile
            wad_path = wad_candidates[0]
            print(f"[Project Manager] Extracting Riot base WAD: {wad_path}")
            
            tmp_wad = None
            try:
                wad = wad_tool.parse_wad(wad_path)
            except PermissionError:
                print(f"[Project Manager] Permission denied, copying WAD to temp...")
                tmp_wad = os.path.join(tempfile.gettempdir(), os.path.basename(wad_path))
                shutil.copy2(wad_path, tmp_wad)
                wad = wad_tool.parse_wad(tmp_wad)
            
            wad_tool.extract_wad(wad, cache_dir)
            
            # Clean up temporary WAD copy
            if tmp_wad and os.path.isfile(tmp_wad):
                try:
                    os.remove(tmp_wad)
                except OSError:
                    pass
        except Exception as e:
            print(f"[Project Manager] Failed to extract Riot WAD: {e}")
            return ""
    
    return cache_dir


def _ensure_riot_levels_wad_cache(league_path: str, map_id: str) -> str:
    """Extract the LEVELS WAD (e.g. Map11LEVELS.wad.client) into a cache directory.
    
    Contains lightmaps, grass tint textures, and other map-level data.
    Returns the cache directory path, or empty string on failure.
    """
    wad_dir = get_maps_wad_dir(league_path)
    if not wad_dir:
        return ""
    
    map_id_title = map_id[0].upper() + map_id[1:] if map_id else map_id
    map_id_lower = map_id.lower()
    
    # Find LEVELS WAD candidates (e.g. Map11LEVELS.wad.client)
    wad_candidates = []
    for fname in os.listdir(wad_dir):
        fname_lower = fname.lower()
        if not fname_lower.startswith(map_id_title.lower()):
            continue
        if '.wad' not in fname_lower:
            continue
        if 'level' not in fname_lower:
            continue
        wad_candidates.append(os.path.join(wad_dir, fname))
    
    # Prefer .wad.client over plain .wad
    wad_candidates.sort(key=lambda p: (0 if '.wad.client' in p.lower() else 1))
    if not wad_candidates:
        return ""
    
    cache_dir = os.path.join(_get_wad_cache_root(), f"{map_id_title}LEVELS")
    
    # Detect incomplete cache: directory exists but lacks the levels subdir
    if os.path.isdir(cache_dir):
        expected_subdir = os.path.join(cache_dir, "levels")
        data_subdir = os.path.join(cache_dir, "data", "levels")
        if not os.path.isdir(expected_subdir) and not os.path.isdir(data_subdir):
            print(f"[Project Manager] LEVELS cache looks incomplete, re-extracting: {cache_dir}")
            try:
                _rmtree_long_path(cache_dir)
            except Exception as e:
                print(f"[Project Manager] Failed to clean incomplete LEVELS cache: {e}")
    
    if not os.path.isdir(cache_dir):
        try:
            from . import wad_tool
            import shutil
            import tempfile
            wad_path = wad_candidates[0]
            print(f"[Project Manager] Extracting Riot LEVELS WAD: {wad_path}")
            
            # Pre-register known LEVELS paths so hash resolution works
            _preregister_levels_hashes(wad_tool, map_id_lower)
            
            tmp_wad = None
            try:
                wad = wad_tool.parse_wad(wad_path)
            except PermissionError:
                print(f"[Project Manager] Permission denied, copying LEVELS WAD to temp...")
                tmp_wad = os.path.join(tempfile.gettempdir(), os.path.basename(wad_path))
                shutil.copy2(wad_path, tmp_wad)
                wad = wad_tool.parse_wad(tmp_wad)
            
            wad_tool.extract_wad(wad, cache_dir)
            print(f"[Project Manager] LEVELS WAD extracted to: {cache_dir}")
            
            # Clean up temporary WAD copy
            if tmp_wad and os.path.isfile(tmp_wad):
                try:
                    os.remove(tmp_wad)
                except OSError:
                    pass
        except Exception as e:
            print(f"[Project Manager] Failed to extract Riot LEVELS WAD: {e}")
            return ""
    
    return cache_dir


def _preregister_levels_hashes(wad_tool, map_id_lower: str):
    """Pre-register known LEVELS WAD file paths so extraction resolves them properly.
    
    The LEVELS WAD contains lightmaps, grass tint, lightgrid, and info files.
    We generate all likely path patterns and register their XXHash64.
    """
    # Known variant suffixes used in LEVELS files
    variant_suffixes = [
        '', '_srx', '_base_srx',
        # Dragon variants
        '_srx.srt_2024_strategy_differentiation_preseason',
        '_srx.cloud', '_srx.hextech', '_srx.chemtech',
        '_srx.infernal', '_srx.mountain', '_srx.ocean', '_srx.void',
    ]
    
    # Known file patterns in LEVELS WADs
    # levels/<mapid>/info/<filename>
    info_dir = f"levels/{map_id_lower}/info"
    
    paths = set()
    
    # Grass tint textures
    for suffix in variant_suffixes:
        for ext in ['.dds', '.tex']:
            paths.add(f"{info_dir}/grasstint{suffix}{ext}")
    
    # Lightgrid files
    for suffix in ['', '_srx', '_base_srx']:
        paths.add(f"{info_dir}/base{suffix}.lightgrid.bin")
        paths.add(f"{info_dir}/{map_id_lower}{suffix}.lightgrid.bin")
    
    # Lightmap textures
    for suffix in variant_suffixes:
        for ext in ['.dds', '.tex']:
            paths.add(f"{info_dir}/lightmap{suffix}{ext}")
            paths.add(f"{info_dir}/rma_lightmap{suffix}{ext}")
    
    # Additional info files
    paths.add(f"{info_dir}/maplight_rma.bin")
    paths.add(f"{info_dir}/lightgrid.bin")
    paths.add(f"{info_dir}/mapdata.bin")
    
    # Also try data/levels/ prefix variant
    data_paths = set()
    for p in paths:
        data_paths.add(f"data/{p}")
    paths.update(data_paths)
    
    # Register all paths
    registered = 0
    for p in paths:
        h = wad_tool.xxhash64_path(p)
        if h not in wad_tool._custom_hashes:
            wad_tool._custom_hashes[h] = p
            registered += 1
    
    if registered:
        print(f"[Project Manager] Pre-registered {registered} LEVELS path hashes for {map_id_lower}")


def get_riot_wad_variants(league_path: str, map_id: str) -> list[dict]:
    """Scan Riot's WAD cache for all mapgeo/materials.bin variants.
    
    Returns list of dicts: {'name': str, 'mapgeo': str, 'materials': str, 'mat_format': str}
    Extracts the WAD if not yet cached.
    """
    cache_dir = _ensure_riot_wad_cache(league_path, map_id)
    if not cache_dir:
        return []
    
    variants = {}  # name -> dict
    
    mapgeo_base = os.path.join(cache_dir, "data", "maps", "mapgeometry")
    if not os.path.isdir(mapgeo_base):
        return []
    
    for dir_name in os.listdir(mapgeo_base):
        search_dir = os.path.join(mapgeo_base, dir_name)
        if not os.path.isdir(search_dir):
            continue
        
        for fname in os.listdir(search_dir):
            fpath = os.path.join(search_dir, fname)
            if not os.path.isfile(fpath):
                continue
            
            if fname.endswith('.mapgeo'):
                base = fname[:-len('.mapgeo')]
                if base not in variants:
                    variants[base] = {'name': base, 'mapgeo': '', 'materials': '', 'mat_format': ''}
                variants[base]['mapgeo'] = fpath
            elif fname.endswith('.materials.bin'):
                base = fname[:-len('.materials.bin')]
                if base not in variants:
                    variants[base] = {'name': base, 'mapgeo': '', 'materials': '', 'mat_format': ''}
                variants[base]['materials'] = fpath
                variants[base]['mat_format'] = 'bin'
    
    result = sorted(variants.values(), key=lambda v: v['name'].lower())
    if result:
        print(f"[Project Manager] Found {len(result)} variant(s) in Riot WAD: {[v['name'] for v in result]}")
    return result


# ============================================================================
# Project Folder Validation
# ============================================================================

def _strip_wad_suffix(name: str) -> str:
    """Strip .wad.client / .wad suffixes from a folder name to get the map id."""
    n = name
    for suffix in ['.wad.client', '.wad']:
        if n.lower().endswith(suffix):
            n = n[:-len(suffix)]
    return n


def _extract_map_id(name: str) -> str:
    """Extract the core map ID (e.g. 'map11') from a folder name.
    
    Handles: map11, map11_disabled, Map11.wad.client, map11_disabled.wad.client, etc.
    """
    stripped = _strip_wad_suffix(name)
    m = re.match(r'(map\d+)', stripped, re.IGNORECASE)
    if m:
        return m.group(1)
    if stripped.lower() == 'common':
        return 'Common'
    return stripped


def _is_wad_folder_name(name: str) -> bool:
    """Check if a folder name looks like a WAD folder (map11.wad.client, Map11.wad, map11, etc.)."""
    stripped = _strip_wad_suffix(name).lower()
    # Accept known map IDs or anything that starts with 'map'
    if stripped.lower().startswith('map') or stripped.lower() == 'common':
        return True
    return False


def _scan_wad_contents(folder: str, result: dict, exclude_keyword: str = ""):
    """Scan a single extracted-WAD folder for mapgeo, materials, and assets."""
    _excl = exclude_keyword.strip().lower() if exclude_keyword else ''
    
    def _excluded(name: str) -> bool:
        return bool(_excl and _excl in name.lower())
    
    data_dir = os.path.join(folder, "data")
    assets_dir = os.path.join(folder, "assets")

    if os.path.isdir(data_dir):
        result['has_data'] = True
    if os.path.isdir(assets_dir):
        result['has_assets'] = True

    # Scan data/maps/mapgeometry/<mapid>/
    mapgeo_base = os.path.join(data_dir, "maps", "mapgeometry")
    if os.path.isdir(mapgeo_base):
        for map_dir_name in os.listdir(mapgeo_base):
            map_dir = os.path.join(mapgeo_base, map_dir_name)
            if not os.path.isdir(map_dir):
                continue
            # Skip excluded map directories
            if _excluded(map_dir_name):
                continue
            if not result['map_id']:
                result['map_id'] = map_dir_name
            for fname in os.listdir(map_dir):
                fpath = os.path.join(map_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                # Skip excluded files
                if _excluded(fname):
                    continue
                if fname.endswith('.mapgeo'):
                    result['mapgeo_files'].append((fname, fpath))
                elif fname.endswith('.materials.bin'):
                    result['materials_bin_files'].append((fname, fpath))

    # Count asset types
    if os.path.isdir(assets_dir):
        for root, dirs, files in os.walk(assets_dir):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext:
                    result['asset_types'][ext] = result['asset_types'].get(ext, 0) + 1


def validate_project_folder(folder: str, exclude_keyword: str = "") -> dict:
    """
    Validate a project/mod folder and detect its contents.
    
    Args:
        folder: Path to the project folder.
        exclude_keyword: If set, skip any folder or file whose name contains
                         this keyword (case-insensitive).
    
    Accepted folder structures:
    1. Directly an extracted WAD:  folder/data/  folder/assets/
    2. Named like map11.wad.client/ or map11.wad/ — same as (1)
    3. A parent folder containing WAD subfolders (map11/, map11.wad/, map11.wad.client/)
    
    Returns dict with:
        valid: bool
        map_id: str (e.g. "map11")
        mapgeo_files: list of (name, full_path) tuples
        materials_files: list of (name, full_path) tuples  
        has_assets: bool
        has_data: bool
        errors: list of str
        warnings: list of str
    """
    result = {
        'valid': False,
        'map_id': '',
        'mapgeo_files': [],
        'materials_files': [],
        'materials_bin_files': [],
        'has_assets': False,
        'has_data': False,
        'errors': [],
        'warnings': [],
        'asset_types': {},  # ext -> count
    }
    
    if not folder or not os.path.isdir(folder):
        result['errors'].append("Folder does not exist")
        return result
    
    # Normalize exclude keyword
    _excl = exclude_keyword.strip().lower() if exclude_keyword else ''
    
    # Helper: check if a name should be excluded
    def _excluded(name: str) -> bool:
        return bool(_excl and _excl in name.lower())
    
    # ── Strategy 1: The folder itself is an extracted WAD ──
    data_dir = os.path.join(folder, "data")
    assets_dir = os.path.join(folder, "assets")
    
    # Check if the project folder itself is excluded
    folder_name = os.path.basename(folder.rstrip('/\\'))
    if _excluded(folder_name):
        result['warnings'].append(f"Project folder '{folder_name}' matches exclude keyword")
        return result
    
    if os.path.isdir(data_dir) or os.path.isdir(assets_dir):
        # This folder directly contains data/ or assets/ — it's a WAD root
        _scan_wad_contents(folder, result, exclude_keyword=_excl)
        
        # Try to derive map_id from folder name
        if not result['map_id']:
            folder_name = os.path.basename(folder.rstrip('/\\'))
            result['map_id'] = _extract_map_id(folder_name)
    
    # ── Strategy 2: Check for WAD-named subfolders ──
    if not result['mapgeo_files'] and not result['has_assets']:
        for entry in os.listdir(folder):
            entry_path = os.path.join(folder, entry)
            if not os.path.isdir(entry_path):
                continue
            
            # Check if subfolder looks like a WAD folder or has data/assets inside
            sub_data = os.path.join(entry_path, "data")
            sub_assets = os.path.join(entry_path, "assets")
            is_wad = os.path.isdir(sub_data) or os.path.isdir(sub_assets) or _is_wad_folder_name(entry)
            
            # Always extract map_id from WAD-like folders, even if excluded
            if is_wad and not result['map_id']:
                result['map_id'] = _extract_map_id(entry)
            
            # Skip excluded folders for content scanning
            if _excluded(entry):
                continue
            
            if is_wad:
                _scan_wad_contents(entry_path, result, exclude_keyword=_excl)
    
    # ── Strategy 3: Deep scan — look for mapgeo files anywhere ──
    if not result['mapgeo_files'] and not result['has_assets']:
        depth_limit = folder.count(os.sep) + 6
        for root, dirs, files in os.walk(folder):
            if root.count(os.sep) > depth_limit:
                dirs.clear()
                continue
            # Prune excluded directories
            if _excl:
                dirs[:] = [d for d in dirs if not _excluded(d)]
            for f in files:
                if f.endswith('.mapgeo'):
                    result['mapgeo_files'].append((f, os.path.join(root, f)))
                elif f.endswith('.materials.bin'):
                    result['materials_bin_files'].append((f, os.path.join(root, f)))
    
    # ── Final validation ──
    if result['mapgeo_files'] or result['materials_bin_files']:
        result['valid'] = True
    elif result['has_assets']:
        result['valid'] = True
        result['warnings'].append("No mapgeo/materials found — asset-only project")
    elif result['map_id']:
        # We detected a map ID (e.g. from an excluded WAD folder) — valid for Riot base loading
        result['valid'] = True
        result['warnings'].append("No local mapgeo/materials — Riot base may provide them")
    else:
        result['errors'].append(
            "No valid WAD structure found. Expected: a folder with data/ and/or assets/ inside, "
            "or subfolders named like map11.wad.client / map11.wad / map11"
        )
    
    return result


# ============================================================================
# Materials.bin → Material Dict Converter
# ============================================================================

def _get_field_by_hash(fields: list, name_hash: int):
    """Find a field in a list of field dicts by its name_hash_int."""
    for f in fields:
        if f.get('name_hash_int') == name_hash:
            return f
    return None


def _get_embedded_field_by_hash(embedded_fields: list, name_hash: int):
    """Find a field in embedded struct fields by name_hash_int."""
    for f in embedded_fields:
        if f.get('name_hash_int') == name_hash:
            return f
    return None


def convert_bin_entry_to_material_dict(entry: dict) -> dict | None:
    """
    Convert a propertybin entry (from parse_bin) to the material dict format
    that MaterialLoader uses.
    
    Returns None if entry is not a StaticMaterialDef.
    """
    if entry.get('type_hash') != f"0x{HASH_STATIC_MATERIAL_DEF:08x}":
        return None
    
    fields = entry.get('fields', [])
    
    # Get material name
    name_field = _get_field_by_hash(fields, HASH_NAME)
    name = name_field['value'] if name_field else f"0x{entry.get('path_hash', '00000000')}"
    
    # Material type
    type_field = _get_field_by_hash(fields, HASH_MAT_TYPE)
    mat_type = type_field['value'] if type_field else 0
    
    mat = {
        '__type': 'StaticMaterialDef',
        'name': name,
        'type': mat_type,
        'samplerValues': [],
        'paramValues': [],
        'switchValues': [],
        'switches': {},
        'shaderMacros': {},
        'techniques': [],
        'childTechniques': [],
        'shader': '',
        'blendEnable': False,
        'cullEnable': False,
    }
    
    # Parse samplers
    sampler_field = _get_field_by_hash(fields, HASH_SAMPLER_VALUES)
    if sampler_field:
        for sampler_entry in sampler_field.get('values', []):
            sampler_fields = sampler_entry.get('fields', [])
            tex_name_f = _get_embedded_field_by_hash(sampler_fields, HASH_TEXTURE_NAME)
            if not tex_name_f:
                tex_name_f = _get_embedded_field_by_hash(sampler_fields, HASH_SAMPLER_NAME_LEGACY)
            tex_path_f = _get_embedded_field_by_hash(sampler_fields, HASH_TEXTURE_PATH)
            addr_u_f = _get_embedded_field_by_hash(sampler_fields, HASH_ADDRESS_U)
            addr_v_f = _get_embedded_field_by_hash(sampler_fields, HASH_ADDRESS_V)
            addr_w_f = _get_embedded_field_by_hash(sampler_fields, HASH_ADDRESS_W)
            
            sampler = {
                'textureName': tex_name_f['value'] if tex_name_f else '',
                'TextureName': tex_name_f['value'] if tex_name_f else '',
                'texturePath': tex_path_f['value'] if tex_path_f else '',
            }
            if addr_u_f:
                sampler['addressU'] = addr_u_f['value']
            if addr_v_f:
                sampler['addressV'] = addr_v_f['value']
            if addr_w_f:
                sampler['addressW'] = addr_w_f['value']
            
            mat['samplerValues'].append(sampler)
    
    # Parse param values
    param_field = _get_field_by_hash(fields, HASH_PARAM_VALUES)
    if param_field:
        for param_entry in param_field.get('values', []):
            param_fields = param_entry.get('fields', [])
            pname_f = _get_embedded_field_by_hash(param_fields, HASH_NAME)
            pval_f = _get_embedded_field_by_hash(param_fields, HASH_PARAM_VALUE)
            
            param = {
                'name': pname_f['value'] if pname_f else '',
                'value': list(pval_f['value']) if pval_f else [0, 0, 0, 0],
            }
            mat['paramValues'].append(param)
    
    # Parse switches
    switch_field = _get_field_by_hash(fields, HASH_SWITCH_VALUES)
    if switch_field:
        for switch_entry in switch_field.get('values', []):
            sw_fields = switch_entry.get('fields', [])
            sw_name_f = _get_embedded_field_by_hash(sw_fields, HASH_NAME)
            sw_on_f = _get_embedded_field_by_hash(sw_fields, HASH_SWITCH_ON)
            sw_group_f = _get_embedded_field_by_hash(sw_fields, HASH_SWITCH_GROUP)
            
            sw_name = sw_name_f['value'] if sw_name_f else ''
            sw_on = sw_on_f['value'] if sw_on_f else True
            sw_group = sw_group_f['value'] if sw_group_f else None
            
            sw_entry = {'name': sw_name, 'on': sw_on}
            if sw_group:
                sw_entry['group'] = sw_group
            mat['switchValues'].append(sw_entry)
            if sw_name:
                mat['switches'][sw_name] = sw_on
    
    # Parse shader macros (map type)
    macros_field = _get_field_by_hash(fields, HASH_SHADER_MACROS)
    if macros_field:
        # Map fields have key-value pairs
        value = macros_field.get('value', {})
        if isinstance(value, dict):
            mat['shaderMacros'] = value
        elif isinstance(value, list):
            # Sometimes map comes as list of pairs
            for pair in value:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    mat['shaderMacros'][str(pair[0])] = str(pair[1])
    
    # Parse techniques
    techniques_field = _get_field_by_hash(fields, HASH_TECHNIQUES)
    if techniques_field:
        for tech_entry in techniques_field.get('values', []):
            tech_fields = tech_entry.get('fields', [])
            tech_name_f = _get_embedded_field_by_hash(tech_fields, HASH_NAME)
            # Try modern passes layout first, fall back to legacy
            passes_f = _get_embedded_field_by_hash(tech_fields, HASH_PASSES)
            if not passes_f:
                passes_f = _get_embedded_field_by_hash(tech_fields, HASH_PASSES_LEGACY)
            
            technique = {
                'name': tech_name_f['value'] if tech_name_f else '',
                'passes': [],
            }
            
            if passes_f:
                for pass_entry in passes_f.get('values', []):
                    pass_fields = pass_entry.get('fields', [])
                    shader_f = (_get_embedded_field_by_hash(pass_fields, HASH_SHADER)
                                or _get_embedded_field_by_hash(pass_fields, HASH_SHADER_LEGACY))
                    blend_f = (_get_embedded_field_by_hash(pass_fields, HASH_BLEND_ENABLE)
                               or _get_embedded_field_by_hash(pass_fields, HASH_BLEND_ENABLE_LEGACY))
                    cull_f = _get_embedded_field_by_hash(pass_fields, HASH_CULL_ENABLE)
                    src_color_f = (_get_embedded_field_by_hash(pass_fields, HASH_SRC_COLOR_BLEND)
                                   or _get_embedded_field_by_hash(pass_fields, HASH_SRC_COLOR_BLEND_LEGACY))
                    src_alpha_f = (_get_embedded_field_by_hash(pass_fields, HASH_SRC_ALPHA_BLEND)
                                   or _get_embedded_field_by_hash(pass_fields, HASH_SRC_ALPHA_BLEND_LEGACY))
                    dst_color_f = (_get_embedded_field_by_hash(pass_fields, HASH_DST_COLOR_BLEND)
                                   or _get_embedded_field_by_hash(pass_fields, HASH_DST_COLOR_BLEND_LEGACY))
                    dst_alpha_f = (_get_embedded_field_by_hash(pass_fields, HASH_DST_ALPHA_BLEND)
                                   or _get_embedded_field_by_hash(pass_fields, HASH_DST_ALPHA_BLEND_LEGACY))
                    
                    write_mask_f = _get_embedded_field_by_hash(pass_fields, HASH_WRITE_MASK)
                    pass_macros_f = _get_embedded_field_by_hash(pass_fields, HASH_PASS_SHADER_MACROS)
                    
                    pass_data = {
                        'shader': shader_f['value'] if shader_f else '',
                        'blendEnable': blend_f['value'] if blend_f else False,
                        'cullEnable': cull_f['value'] if cull_f else False,
                        'srcColorBlendFactor': src_color_f['value'] if src_color_f else 1,
                        'srcAlphaBlendFactor': src_alpha_f['value'] if src_alpha_f else 1,
                        'dstColorBlendFactor': dst_color_f['value'] if dst_color_f else 0,
                        'dstAlphaBlendFactor': dst_alpha_f['value'] if dst_alpha_f else 0,
                    }
                    if write_mask_f:
                        pass_data['writeMask'] = write_mask_f['value']
                    if pass_macros_f:
                        macros_val = pass_macros_f.get('value', {})
                        if isinstance(macros_val, dict) and macros_val:
                            pass_data['shaderMacros'] = macros_val
                    technique['passes'].append(pass_data)
                    
                    # Extract top-level shader info from first technique/pass
                    if not mat['shader'] and pass_data['shader']:
                        mat['shader'] = pass_data['shader']
                        mat['blendEnable'] = pass_data['blendEnable']
                        mat['cullEnable'] = pass_data['cullEnable']
            
            mat['techniques'].append(technique)
    
    # Parse child techniques
    child_tech_field = _get_field_by_hash(fields, HASH_CHILD_TECHNIQUES)
    if child_tech_field:
        for child_entry in child_tech_field.get('values', []):
            child_fields = child_entry.get('fields', [])
            child_name_f = _get_embedded_field_by_hash(child_fields, HASH_NAME)
            parent_name_f = _get_embedded_field_by_hash(child_fields, HASH_PARENT_NAME)
            child_macros_f = _get_embedded_field_by_hash(child_fields, HASH_SHADER_MACROS)
            
            child = {
                'name': child_name_f['value'] if child_name_f else '',
                'parentName': parent_name_f['value'] if parent_name_f else '',
                'shaderMacros': {},
            }
            if child_macros_f:
                macros_val = child_macros_f.get('value', {})
                if isinstance(macros_val, dict):
                    child['shaderMacros'] = macros_val
                elif isinstance(macros_val, list):
                    for pair in macros_val:
                        if isinstance(pair, (list, tuple)) and len(pair) == 2:
                            child['shaderMacros'][str(pair[0])] = str(pair[1])
            
            mat['childTechniques'].append(child)
    
    return mat


def load_materials_from_bin(bin_path: str) -> dict[str, dict]:
    """
    Load materials from a raw .materials.bin file.
    Parses with propertybin_parser and converts to the same dict format
    that MaterialLoader uses.
    
    Returns:
        dict of material_name -> material_data
    """
    from . import propertybin_parser
    
    try:
        data = propertybin_parser.parse_bin(bin_path)
    except Exception as e:
        print(f"[Project Manager] Failed to parse {bin_path}: {e}")
        return {}
    
    materials = {}
    for entry in data.get('entries', []):
        mat = convert_bin_entry_to_material_dict(entry)
        if mat:
            materials[mat['name']] = mat
    
    print(f"[Project Manager] Loaded {len(materials)} materials from {os.path.basename(bin_path)}")
    return materials


# ============================================================================
# Map Settings from .bin (Sun, Fog, Bake, Lighting)
# ============================================================================

# Type hashes (FNV-1a 32-bit lowercase)
HASH_MAP_SUN_PROPERTIES   = 0x169a2f9c  # MapSunProperties
HASH_MAP_BAKE_PROPERTIES  = 0x6a4a3409  # MapBakeProperties
HASH_MAP_LIGHTING_V2      = 0xdca35419  # MapLightingV2
HASH_MAP_CONTAINER        = 0xdde8c114  # MapContainer
HASH_MAP_CONTAINER_ITEMS  = 0x1bf51169  # MapContainer embedded items list

# MapSunProperties field hashes
HASH_SUN_COLOR            = 0x664a1f44  # sunColor
HASH_SUN_DIRECTION        = 0xe1907cf6  # sunDirection
HASH_SKY_LIGHT_COLOR      = 0x0a65794d  # skyLightColor
HASH_HORIZON_COLOR        = 0xfd3d43af  # horizonColor
HASH_GROUND_COLOR         = 0x583befe1  # groundColor
HASH_SKY_LIGHT_SCALE      = 0xb39b0430  # skyLightScale
HASH_LIGHTMAP_COLOR_SCALE = 0x986a4d5c  # lightMapColorScale
HASH_FOG_ENABLED          = 0x00849744  # fogEnabled
HASH_FOG_COLOR            = 0x023b1fce  # fogColor
HASH_FOG_ALT_COLOR        = 0x4896f2da  # fogAlternateColor
HASH_FOG_START_END        = 0x72a72173  # fogStartAndEnd

# MapBakeProperties field hashes
HASH_LIGHT_GRID_SIZE      = 0x469be1a2  # lightGridSize
HASH_LIGHT_GRID_FILE      = 0x7561b09e  # lightGridFileName
HASH_RMA_GRID_TEX         = 0x9cf064e5  # RmaStaticLightGridTexturePath
HASH_RMA_GRID_SCALE       = 0x7ab8b646  # RmaStaticLightGridIntensityScale
HASH_GRID_FULLBRIGHT      = 0x5c6a0e0c  # lightGridCharacterFullBrightIntensity

# MapLightingV2 field hashes
HASH_MIN_ENV_CONTRIBUTION = 0xee91017d  # MinimumEnvironmentColorContribution


def load_map_settings_from_bin(bin_path: str) -> dict:
    """
    Load map-level settings (sun, fog, bake, lighting) from a binary .bin file.
    Scans all entries for MapSunProperties, MapBakeProperties, MapLightingV2.
    
    Returns:
        dict with keys like sun_color, fog_color, lightmap_color_scale, etc.
        Empty dict if no map settings entries are found.
    """
    from . import propertybin_parser
    
    try:
        data = propertybin_parser.parse_bin(bin_path)
    except Exception as e:
        print(f"[Project Manager] Failed to parse {bin_path} for map settings: {e}")
        return {}
    
    settings = {}
    
    for entry in data.get('entries', []):
        type_hash_str = entry.get('type_hash', '')
        fields = entry.get('fields', [])
        
        # Convert type hash string to int for comparison
        try:
            type_hash_int = int(type_hash_str, 16) if type_hash_str.startswith('0x') else 0
        except ValueError:
            continue
        
        if type_hash_int == HASH_MAP_SUN_PROPERTIES:
            _parse_sun_properties(fields, settings)
        elif type_hash_int == HASH_MAP_BAKE_PROPERTIES:
            _parse_bake_properties(fields, settings)
        elif type_hash_int == HASH_MAP_LIGHTING_V2:
            _parse_lighting_v2(fields, settings)
        elif type_hash_int == HASH_MAP_CONTAINER:
            _parse_map_container(fields, settings)
    
    if settings:
        print(f"[Project Manager] Loaded map settings from {os.path.basename(bin_path)}: {list(settings.keys())}")
    
    return settings


def _parse_sun_properties(fields: list, settings: dict):
    """Extract MapSunProperties fields into normalized settings dict."""
    field_map = {
        HASH_SUN_COLOR:            ('sun_color',            [1, 1, 1, 1]),
        HASH_SUN_DIRECTION:        ('sun_direction',        [0, 1, 0]),
        HASH_SKY_LIGHT_COLOR:      ('sky_light_color',      [1, 1, 1, 1]),
        HASH_HORIZON_COLOR:        ('horizon_color',        [1, 1, 1, 1]),
        HASH_GROUND_COLOR:         ('ground_color',         [1, 1, 1, 1]),
        HASH_SKY_LIGHT_SCALE:      ('sky_light_scale',      1.0),
        HASH_LIGHTMAP_COLOR_SCALE: ('lightmap_color_scale', 1.0),
        HASH_FOG_ENABLED:          ('fog_enabled',          True),
        HASH_FOG_COLOR:            ('fog_color',            [0, 0, 0, 1]),
        HASH_FOG_ALT_COLOR:        ('fog_alternate_color',  [0, 0, 0, 1]),
        HASH_FOG_START_END:        ('fog_start_end',        [0, -10000]),
    }
    for f in fields:
        h = f.get('name_hash_int', 0)
        if h in field_map:
            key, default = field_map[h]
            val = f.get('value', default)
            # Ensure list types are proper lists
            if isinstance(default, list) and not isinstance(val, list):
                if hasattr(val, '__iter__'):
                    val = list(val)
            settings[key] = val


def _parse_bake_properties(fields: list, settings: dict):
    """Extract MapBakeProperties fields into normalized settings dict."""
    field_map = {
        HASH_LIGHT_GRID_SIZE:  ('light_grid_size',                    256),
        HASH_LIGHT_GRID_FILE:  ('light_grid_file',                    ''),
        HASH_RMA_GRID_TEX:     ('rma_light_grid_texture',             ''),
        HASH_RMA_GRID_SCALE:   ('rma_light_grid_intensity_scale',     1.0),
        HASH_GRID_FULLBRIGHT:  ('light_grid_fullbright',              0.5),
    }
    for f in fields:
        h = f.get('name_hash_int', 0)
        if h in field_map:
            key, default = field_map[h]
            settings[key] = f.get('value', default)


def _parse_lighting_v2(fields: list, settings: dict):
    """Extract MapLightingV2 fields into normalized settings dict."""
    for f in fields:
        if f.get('name_hash_int', 0) == HASH_MIN_ENV_CONTRIBUTION:
            settings['min_env_color_contribution'] = f.get('value', 0.8)


# Known sun/bake field hashes for detecting embedded items in MapContainer
_SUN_FIELD_HASHES = {
    HASH_SUN_COLOR, HASH_SUN_DIRECTION, HASH_SKY_LIGHT_COLOR,
    HASH_HORIZON_COLOR, HASH_GROUND_COLOR, HASH_SKY_LIGHT_SCALE,
    HASH_LIGHTMAP_COLOR_SCALE, HASH_FOG_ENABLED, HASH_FOG_COLOR,
    HASH_FOG_ALT_COLOR, HASH_FOG_START_END,
}
_BAKE_FIELD_HASHES = {
    HASH_LIGHT_GRID_SIZE, HASH_LIGHT_GRID_FILE, HASH_RMA_GRID_TEX,
    HASH_RMA_GRID_SCALE, HASH_GRID_FULLBRIGHT,
}
_LIGHTING_FIELD_HASHES = {HASH_MIN_ENV_CONTRIBUTION}


def _parse_map_container(fields: list, settings: dict):
    """Extract sun/bake/lighting from MapContainer's embedded items list."""
    for f in fields:
        if f.get('name_hash_int', 0) != HASH_MAP_CONTAINER_ITEMS:
            continue
        items = f.get('values', [])
        for item in items:
            item_fields = item.get('fields', [])
            if not item_fields:
                continue
            item_hashes = {sf.get('name_hash_int', 0) for sf in item_fields}
            if item_hashes & _SUN_FIELD_HASHES:
                _parse_sun_properties(item_fields, settings)
            elif item_hashes & _BAKE_FIELD_HASHES:
                _parse_bake_properties(item_fields, settings)
            elif item_hashes & _LIGHTING_FIELD_HASHES:
                _parse_lighting_v2(item_fields, settings)
        break


# ============================================================================
# Map Variant Item for UI List
# ============================================================================

class ProjectMapVariant(PropertyGroup):
    """A map variant (e.g. base, arcade, bloom) found in the project."""
    name: StringProperty(name="Name")
    mapgeo_path: StringProperty(name="Mapgeo Path")
    materials_path: StringProperty(name="Materials Path")
    materials_format: StringProperty(name="Format", default="bin")
    materials_bin_path: StringProperty(name="Bin Path", default="")
    has_mapgeo: BoolProperty(default=False)
    has_materials: BoolProperty(default=False)


class ProjectAssetSummary(PropertyGroup):
    """Summary of an asset type found in the project."""
    extension: StringProperty(name="Extension")
    count: IntProperty(name="Count")


# ============================================================================
# Blender Properties
# ============================================================================

class ProjectSettings(PropertyGroup):
    """Project Manager settings stored on the Scene."""
    
    project_folder: StringProperty(
        name="Project Folder",
        description="Path to the extracted WAD / mod project folder",
        subtype='DIR_PATH',
        default="",
    )
    
    league_install: StringProperty(
        name="League Install",
        description="Path to League of Legends installation (auto-detected)",
        subtype='DIR_PATH',
        default="",
    )
    
    league_detected: BoolProperty(
        name="Auto-detected",
        default=False,
    )
    
    is_valid_project: BoolProperty(
        name="Valid Project",
        default=False,
    )
    
    project_map_id: StringProperty(
        name="Map ID",
        default="",
    )
    
    selected_variant_index: IntProperty(
        name="Selected Variant",
        default=0,
    )
    
    use_riot_base: BoolProperty(
        name="Load Base from Riot",
        description="When mod doesn't include mapgeo/materials, load them from Riot's game files",
        default=True,
    )
    
    use_exclude_keyword: BoolProperty(
        name="Exclude by Keyword",
        description="Skip map variants whose name contains the exclude keyword",
        default=False,
    )
    
    exclude_keyword: StringProperty(
        name="Exclude Keyword",
        description="Variants containing this word (case-insensitive) will be hidden from the list",
        default="disabled",
    )
    
    status_message: StringProperty(
        name="Status",
        default="",
    )
    
    # Lists
    map_variants: CollectionProperty(type=ProjectMapVariant)
    asset_summary: CollectionProperty(type=ProjectAssetSummary)
    
    # Tracking what's loaded
    loaded_variant: StringProperty(default="")
    loaded_mapgeo_path: StringProperty(default="")
    loaded_materials_path: StringProperty(default="")
    loaded_materials_format: StringProperty(default="")
    
    # Materials format preference
    materials_format_pref: EnumProperty(
        name="Materials Format",
        description="Materials format to load",
        items=[
            ('BIN', ".bin", "Load .materials.bin"),
        ],
        default='BIN',
    )
    
    # Prey format
    prey_dir: StringProperty(
        name="Prey Directory",
        description="Directory containing .prey.* split files",
        default="",
    )
    has_prey: BoolProperty(
        name="Has Prey Files",
        description="Whether .prey.* files exist for the loaded materials",
        default=False,
    )
    use_prey_on_export: BoolProperty(
        name="Rebuild from .prey on Export",
        description="When exporting, rebuild .materials.bin from .prey files first, then merge Blender edits on top",
        default=True,
    )
    materials_update_reference_path: StringProperty(
        name="Reference Materials Bin",
        description="Riot materials.bin used as the template when upgrading legacy material samplers/switches",
        subtype='FILE_PATH',
        default="",
    )
    materials_update_target_path: StringProperty(
        name="Target Materials Bin",
        description="Legacy .materials.bin file to update",
        subtype='FILE_PATH',
        default="",
    )
    
    # Export settings
    export_mapgeo: BoolProperty(
        name="Export Mapgeo",
        description="Export .mapgeo geometry file",
        default=True,
    )
    export_materials: BoolProperty(
        name="Export Materials",
        description="Export .materials.bin file",
        default=True,
    )
    export_version: IntProperty(
        name="Mapgeo Version",
        description="Version of mapgeo format to export",
        default=18,
        min=13,
        max=18,
    )


# ============================================================================
# Operators
# ============================================================================

class PROJECT_OT_detect_league(Operator):
    """Auto-detect League of Legends installation"""
    bl_idname = "project.detect_league"
    bl_label = "Detect League Install"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        settings = context.scene.project_settings
        found = find_league_install()
        if found:
            settings.league_install = found
            settings.league_detected = True
            self.report({'INFO'}, f"Found League at: {found}")
        else:
            settings.league_detected = False
            self.report({'WARNING'}, "League of Legends installation not found")
        return {'FINISHED'}


class PROJECT_OT_validate_project(Operator):
    """Validate and scan the project folder"""
    bl_idname = "project.validate_project"
    bl_label = "Scan Project"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        settings = context.scene.project_settings
        folder = bpy.path.abspath(settings.project_folder)
        
        if not folder:
            self.report({'ERROR'}, "No project folder selected")
            return {'CANCELLED'}
        
        info = validate_project_folder(
            folder,
            exclude_keyword=settings.exclude_keyword.strip() if settings.use_exclude_keyword else ""
        )
        
        # Clear previous data
        settings.map_variants.clear()
        settings.asset_summary.clear()
        settings.is_valid_project = info['valid']
        settings.project_map_id = info.get('map_id', '')
        
        if info['errors']:
            settings.status_message = "; ".join(info['errors'])
            self.report({'ERROR'}, settings.status_message)
            return {'CANCELLED'}
        
        # Build map variant list
        # Group by base name: "base.mapgeo" + "base.materials.bin" = one variant
        variant_map = {}  # base_name -> variant data
        
        # Add mapgeo files
        for name, path in info['mapgeo_files']:
            base = name.replace('.mapgeo', '')
            if base not in variant_map:
                variant_map[base] = {'mapgeo': '', 'bin_path': '', 'py_path': ''}
            variant_map[base]['mapgeo'] = path
        
        # Add materials.bin files
        for name, path in info['materials_bin_files']:
            base = name.replace('.materials.bin', '')
            if base not in variant_map:
                variant_map[base] = {'mapgeo': '', 'bin_path': ''}
            variant_map[base]['bin_path'] = path
        
        # Resolve preferred format
        pref = settings.materials_format_pref  # BIN
        
        # Populate UI list (apply exclude keyword filter)
        exclude_kw = ''
        if settings.use_exclude_keyword and settings.exclude_keyword.strip():
            exclude_kw = settings.exclude_keyword.strip().lower()
        
        skipped = 0
        for base_name in sorted(variant_map.keys()):
            if exclude_kw and exclude_kw in base_name.lower():
                skipped += 1
                continue
            vdata = variant_map[base_name]
            item = settings.map_variants.add()
            item.name = base_name
            item.mapgeo_path = vdata['mapgeo']
            item.materials_bin_path = vdata['bin_path']
            item.materials_path = vdata['bin_path']
            item.materials_format = 'bin'
            item.has_mapgeo = bool(vdata['mapgeo'])
            item.has_materials = bool(vdata['bin_path'])
        
        # If no local variants have a mapgeo, add all Riot WAD variants
        has_any_mapgeo = any(v.has_mapgeo for v in settings.map_variants)
        if not has_any_mapgeo and settings.use_riot_base and settings.project_map_id:
            league_path = bpy.path.abspath(settings.league_install)
            if league_path:
                riot_variants = get_riot_wad_variants(league_path, settings.project_map_id)
                existing_names = {v.name.lower() for v in settings.map_variants}
                added = 0
                for rv in riot_variants:
                    if rv['name'].lower() not in existing_names:
                        item = settings.map_variants.add()
                        item.name = rv['name']
                        item.mapgeo_path = rv['mapgeo']
                        # Riot WAD only has .bin
                        item.materials_bin_path = rv['materials']
                        item.materials_path = rv['materials']
                        item.materials_format = 'bin'
                        item.has_mapgeo = bool(rv['mapgeo'])
                        item.has_materials = bool(rv['materials'])
                        added += 1
                if added:
                    print(f"[Project Manager] Added {added} Riot WAD variant(s)")
        
        # Asset summary
        for ext, count in sorted(info.get('asset_types', {}).items(), 
                                  key=lambda x: -x[1]):
            item = settings.asset_summary.add()
            item.extension = ext
            item.count = count
        
        warnings = info.get('warnings', [])
        n_variants = len(settings.map_variants)
        n_assets = sum(a.count for a in settings.asset_summary)
        status = f"{n_variants} variant(s), {n_assets} assets"
        if skipped:
            status += f" ({skipped} excluded)"
        if warnings:
            status += f" | {'; '.join(warnings)}"
        settings.status_message = status
        
        self.report({'INFO'}, f"Project scanned: {status}")
        return {'FINISHED'}


def clean_scene():
    """Remove all objects and orphaned data from the scene before loading a new map."""
    import bpy

    # ── 1. Delete every object in the scene ──
    # Override context so this works regardless of mode
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=True)

    # ── 2. Remove non-default collections first ──
    scene = bpy.context.scene
    for child in list(scene.collection.children):
        scene.collection.children.unlink(child)
        bpy.data.collections.remove(child)

    # ── 3. Force-remove ALL data-blocks (not just orphans) ──
    # Order matters: meshes reference materials, materials reference images, etc.
    collections_to_purge = [
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.textures,
        bpy.data.images,
        bpy.data.node_groups,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.curves,
        bpy.data.armatures,
        bpy.data.worlds,
        bpy.data.particles,
        bpy.data.actions,
    ]
    for collection in collections_to_purge:
        for block in list(collection):
            collection.remove(block)

    # ── 4. Final recursive orphan purge to catch anything remaining ──
    # This catches data-blocks with fake users or circular references
    for _ in range(3):
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    print("[Project Manager] Scene cleaned")


class PROJECT_OT_load_map(Operator):
    """Load the selected map variant into Blender"""
    bl_idname = "project.load_map"
    bl_label = "Load Map"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.project_settings
        
        if not settings.map_variants:
            self.report({'ERROR'}, "No map variants found. Scan the project first.")
            return {'CANCELLED'}
        
        idx = settings.selected_variant_index
        if idx < 0 or idx >= len(settings.map_variants):
            self.report({'ERROR'}, "Invalid variant selection")
            return {'CANCELLED'}
        
        variant = settings.map_variants[idx]
        mapgeo_path = variant.mapgeo_path
        
        # Resolve materials path (bin only)
        materials_path = variant.materials_bin_path
        mat_format = 'bin'
        
        # If mod doesn't have mapgeo/materials, try to load from Riot base
        if settings.use_riot_base:
            riot_base = self._find_riot_base_files(settings, variant.name)
            if not mapgeo_path and riot_base.get('mapgeo'):
                mapgeo_path = riot_base['mapgeo']
                print(f"[Project Manager] Using Riot base mapgeo: {mapgeo_path}")
            if not materials_path and riot_base.get('materials'):
                materials_path = riot_base['materials']
                mat_format = riot_base.get('mat_format', 'bin')
                print(f"[Project Manager] Using Riot base materials: {materials_path}")
        
        if not mapgeo_path:
            self.report({'ERROR'}, f"No .mapgeo file found for variant '{variant.name}' (not in mod or Riot base)")
            return {'CANCELLED'}
        
        if not os.path.exists(mapgeo_path):
            self.report({'ERROR'}, f"Mapgeo file not found: {mapgeo_path}")
            return {'CANCELLED'}
        
        # ── Handle materials ──
        # Pass .materials.bin directly — the material loader reads it natively
        effective_materials_path = materials_path
        
        # ── Clean the scene before importing ──
        try:
            clean_scene()
        except Exception as e:
            print(f"[Project Manager] Warning: Scene cleanup had issues: {e}")

        # ── Configure mapgeo settings and import ──
        mapgeo_settings = context.scene.mapgeo_settings
        
        # Set materials path
        if effective_materials_path:
            mapgeo_settings.materials_file_path = effective_materials_path
            mapgeo_settings.use_linked_materials = False  # We set it explicitly
        else:
            # Try linked materials mode
            mapgeo_settings.use_linked_materials = True
        
        # Set assets folder from project — check project root, WAD subfolders,
        # and walk up from the materials/mapgeo file to find an 'assets' sibling.
        project_folder = bpy.path.abspath(settings.project_folder)
        assets_folder = os.path.join(project_folder, "assets")
        if not os.path.isdir(assets_folder):
            # Check WAD subfolders (e.g. map11.wad.client/assets/)
            for entry in os.listdir(project_folder):
                candidate = os.path.join(project_folder, entry, "assets")
                if os.path.isdir(candidate):
                    assets_folder = candidate
                    break
        if not os.path.isdir(assets_folder):
            # Walk up from materials or mapgeo path to find an 'assets' sibling
            ref_path = materials_path or mapgeo_path or ""
            cur = os.path.dirname(ref_path) if ref_path else ""
            project_norm = os.path.normcase(os.path.normpath(project_folder))
            while cur:
                cur_norm = os.path.normcase(os.path.normpath(cur))
                # Stop if we've walked above the project folder
                if not cur_norm.startswith(project_norm):
                    break
                candidate = os.path.join(cur, "assets")
                if os.path.isdir(candidate):
                    assets_folder = candidate
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
        if os.path.isdir(assets_folder):
            mapgeo_settings.assets_folder = assets_folder
            print(f"[Project Manager] Assets folder: {assets_folder}")
        else:
            print(f"[Project Manager] No assets/ folder found in project — textures may be missing")
        
        # Set levels folder — needed for grass tint textures, lightmaps, etc.
        # 1. Check project folder for local levels/ directory
        # 2. Check WAD subfolders for levels/
        # 3. Fall back to Riot LEVELS WAD cache
        levels_folder = ""
        map_id = settings.project_map_id
        
        # Search in project folder first
        for levels_candidate in [
            os.path.join(project_folder, "levels"),
            os.path.join(project_folder, "data", "levels"),
        ]:
            if os.path.isdir(levels_candidate):
                levels_folder = levels_candidate
                break
        
        # Check WAD subfolders (e.g. map11.wad.client/levels/ or map11LEVELS.wad.client/levels/)
        if not levels_folder:
            for entry in os.listdir(project_folder):
                for sub in ["levels", os.path.join("data", "levels")]:
                    candidate = os.path.join(project_folder, entry, sub)
                    if os.path.isdir(candidate):
                        levels_folder = candidate
                        break
                if levels_folder:
                    break
        
        # Fall back to Riot LEVELS WAD cache
        if not levels_folder and settings.use_riot_base and map_id:
            league_path = bpy.path.abspath(settings.league_install)
            if league_path:
                levels_cache = _ensure_riot_levels_wad_cache(league_path, map_id)
                if levels_cache:
                    # The LEVELS WAD extracts to <cache>/levels/<mapid>/info/
                    levels_root = os.path.join(levels_cache, "levels")
                    if os.path.isdir(levels_root):
                        levels_folder = levels_root
                    elif os.path.isdir(os.path.join(levels_cache, "data", "levels")):
                        levels_folder = os.path.join(levels_cache, "data", "levels")
                    else:
                        # Use the cache root itself — files might be at varying depths
                        levels_folder = levels_cache
        
        if levels_folder:
            mapgeo_settings.levels_folder = levels_folder
            print(f"[Project Manager] Levels folder: {levels_folder}")
        
        # Also set Riot WAD cache assets as fallback for unmodified textures
        if settings.use_riot_base and map_id:
            league_path = bpy.path.abspath(settings.league_install)
            if league_path:
                main_cache = _ensure_riot_wad_cache(league_path, map_id)
                if main_cache:
                    riot_assets = os.path.join(main_cache, "assets")
                    if os.path.isdir(riot_assets):
                        if os.path.isdir(assets_folder):
                            # Project has local assets — Riot is fallback
                            mapgeo_settings.custom_assets_folder = riot_assets
                            print(f"[Project Manager] Riot assets (fallback): {riot_assets}")
                        else:
                            # No local assets — Riot is primary
                            mapgeo_settings.assets_folder = riot_assets
                            print(f"[Project Manager] Using Riot base assets folder: {riot_assets}")
        
        # Find map file (map*.py / map*.bin) for grass tint — check project, then Riot WAD cache
        map_file_path = ""
        map_id_lower = map_id.lower() if map_id else ""
        if map_id_lower:
            # Search in project folder and WAD subfolders
            search_dirs = [project_folder]
            for entry in os.listdir(project_folder):
                sub = os.path.join(project_folder, entry)
                if os.path.isdir(sub):
                    search_dirs.append(sub)
            
            for search_dir in search_dirs:
                for sub_path in [
                    os.path.join("data", "maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
                    os.path.join("data", "maps", "shipping", map_id_lower, f"{map_id_lower}.py"),
                    os.path.join("maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
                    os.path.join("maps", "shipping", map_id_lower, f"{map_id_lower}.py"),
                ]:
                    candidate = os.path.join(search_dir, sub_path)
                    if os.path.isfile(candidate):
                        map_file_path = candidate
                        break
                if map_file_path:
                    break
            
            # Fall back to Riot WAD cache
            if not map_file_path and settings.use_riot_base:
                league_path = bpy.path.abspath(settings.league_install)
                if league_path:
                    riot_cache = _ensure_riot_wad_cache(league_path, map_id)
                    if riot_cache:
                        for sub_path in [
                            os.path.join("data", "maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
                            os.path.join("maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
                        ]:
                            candidate = os.path.join(riot_cache, sub_path)
                            if os.path.isfile(candidate):
                                map_file_path = candidate
                                break
        
        if map_file_path:
            mapgeo_settings.map_py_path = map_file_path
            print(f"[Project Manager] Map file (grass tint): {map_file_path}")
        
        # ── Compute custom hashes from .bin files in project ──
        if materials_path and os.path.isfile(materials_path):
            try:
                from . import community_hashes, propertybin_parser
                community_hashes.clear_custom_hashes()
                bin_data = propertybin_parser.parse_bin(materials_path)
                n_hashes = community_hashes.compute_custom_hashes(bin_data)
                if n_hashes:
                    print(f"[Project Manager] Auto-computed {n_hashes} custom hashes")
            except Exception as e:
                print(f"[Project Manager] Custom hash computation failed: {e}")

        # ── Ensure prey files exist (convert if needed) ──
        prey_dir = ""
        prey_base = ""
        if materials_path and os.path.isfile(materials_path):
            prey_dir = _get_prey_dir(materials_path)
            prey_base = _get_prey_base_name(materials_path)

            if not _prey_files_exist(materials_path):
                # Auto-convert to prey before loading
                try:
                    from . import prey_format
                    prey_format.bin_to_prey(materials_path, prey_dir, prey_base)
                    # Supplement from sibling .py (legacy support)
                    py_sibling = prey_format.find_py_sibling(prey_dir)
                    if py_sibling:
                        prey_format.supplement_prey_from_py(prey_dir, prey_base, py_sibling)
                    print(f"[Project Manager] Auto-converted to prey: {prey_dir}")
                except Exception as e:
                    print(f"[Project Manager] Prey auto-convert failed: {e}")
                    prey_dir = ""
                    prey_base = ""

        # ── Set prey routing on mapgeo settings (before import) ──
        if prey_dir and prey_base and os.path.isfile(
                os.path.join(prey_dir, f"{prey_base}.prey.materials")):
            mapgeo_settings.prey_materials_dir = prey_dir
            mapgeo_settings.prey_materials_base = prey_base
        else:
            mapgeo_settings.prey_materials_dir = ""
            mapgeo_settings.prey_materials_base = ""
        
        # Import the mapgeo
        try:
            bpy.ops.import_scene.mapgeo('EXEC_DEFAULT', filepath=mapgeo_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import mapgeo: {e}")
            return {'CANCELLED'}
        
        # Track what's loaded
        settings.loaded_variant = variant.name
        settings.loaded_mapgeo_path = mapgeo_path
        settings.loaded_materials_path = materials_path
        settings.loaded_materials_format = mat_format
        if materials_path and materials_path.endswith('.materials.bin'):
            settings.materials_update_target_path = materials_path
        if not settings.materials_update_reference_path:
            default_ref = _resolve_default_reference_materials(settings)
            if default_ref:
                settings.materials_update_reference_path = default_ref
        settings.status_message = f"Loaded: {variant.name}"
        
        # Store prey state
        if prey_dir and prey_base:
            settings.prey_dir = prey_dir
            settings.has_prey = True
        else:
            settings.prey_dir = ""
            settings.has_prey = False
        
        self.report({'INFO'}, f"Loaded map variant: {variant.name}")
        return {'FINISHED'}
    
    def _find_riot_base_files(self, settings, variant_name: str) -> dict:
        """Find mapgeo/materials from Riot's game installation for a given variant."""
        result = {'mapgeo': '', 'materials': '', 'mat_format': ''}
        
        league_path = bpy.path.abspath(settings.league_install)
        if not league_path:
            return result
        
        map_id = settings.project_map_id
        if not map_id:
            return result
        
        cache_dir = _ensure_riot_wad_cache(league_path, map_id)
        if not cache_dir:
            return result
        
        # Search the cache for mapgeo/materials matching variant_name
        mapgeo_base = os.path.join(cache_dir, "data", "maps", "mapgeometry")
        if not os.path.isdir(mapgeo_base):
            return result
        
        for dir_name in os.listdir(mapgeo_base):
            search_dir = os.path.join(mapgeo_base, dir_name)
            if not os.path.isdir(search_dir):
                continue
            
            # Try exact match
            mapgeo_file = os.path.join(search_dir, f"{variant_name}.mapgeo")
            materials_bin = os.path.join(search_dir, f"{variant_name}.materials.bin")
            
            if os.path.exists(mapgeo_file):
                result['mapgeo'] = mapgeo_file
            if os.path.exists(materials_bin):
                result['materials'] = materials_bin
                result['mat_format'] = 'bin'
            
            if result['mapgeo']:
                break
            
            # Try case-insensitive fallback
            try:
                existing_files = {f.lower(): f for f in os.listdir(search_dir)}
                mapgeo_key = f"{variant_name}.mapgeo".lower()
                materials_key = f"{variant_name}.materials.bin".lower()
                
                if mapgeo_key in existing_files:
                    result['mapgeo'] = os.path.join(search_dir, existing_files[mapgeo_key])
                if materials_key in existing_files:
                    result['materials'] = os.path.join(search_dir, existing_files[materials_key])
                    result['mat_format'] = 'bin'
                
                if result['mapgeo']:
                    break
            except OSError:
                pass
        
        return result


class PROJECT_OT_reload_map(Operator):
    """Reload the currently loaded map (re-reads files from disk)"""
    bl_idname = "project.reload_map"
    bl_label = "Reload Map"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.project_settings
        
        if not settings.loaded_variant:
            self.report({'WARNING'}, "No map currently loaded")
            return {'CANCELLED'}
        
        # Re-import by triggering load_map (which handles cleanup internally)
        bpy.ops.project.load_map('EXEC_DEFAULT')
        
        self.report({'INFO'}, f"Reloaded: {settings.loaded_variant}")
        return {'FINISHED'}


class PROJECT_OT_open_project(Operator):
    """Open a project folder using the file browser"""
    bl_idname = "project.open_project"
    bl_label = "Open Project Folder"
    bl_options = {'REGISTER'}
    
    directory: StringProperty(
        name="Project Directory",
        subtype='DIR_PATH',
    )
    
    def execute(self, context):
        settings = context.scene.project_settings
        settings.project_folder = self.directory
        
        # Auto-scan (ignore CANCELLED — validation errors are shown in the panel)
        try:
            bpy.ops.project.validate_project()
        except RuntimeError:
            pass
        
        # Auto-detect League if not already set
        if not settings.league_install:
            try:
                bpy.ops.project.detect_league()
            except RuntimeError:
                pass
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================================
# Export Helpers
# ============================================================================

def _update_bin_material_from_blender(entry: dict, blender_mat) -> bool:
    """Update a propertybin StaticMaterialDef entry's fields from a Blender material.

    Reads the JSON custom properties stored on the Blender material
    (samplers, parameters, switches, shader_macros, techniques, child_techniques)
    and patches the corresponding fields in the propertybin entry.

    Returns True if any field was actually changed.
    """
    import json as _json

    fields = entry.get('fields', [])
    changed = False

    # --- Samplers ---
    samplers_json = blender_mat.get("samplers")
    if samplers_json:
        try:
            samplers_data = _json.loads(samplers_json)
        except (ValueError, TypeError):
            samplers_data = None

        if samplers_data is not None:
            sampler_field = _get_field_by_hash(fields, HASH_SAMPLER_VALUES)
            if sampler_field:
                existing = sampler_field.get('values', [])
                # Build lookup by textureName hash
                existing_by_name = {}
                for sv in existing:
                    sf = sv.get('fields', [])
                    tn = _get_embedded_field_by_hash(sf, HASH_TEXTURE_NAME)
                    if tn:
                        existing_by_name[tn['value']] = sv

                for s in samplers_data:
                    tex_name = s.get('textureName', '')
                    tex_path = s.get('texturePath', '')
                    sv_entry = existing_by_name.get(tex_name)
                    if sv_entry:
                        sf = sv_entry.get('fields', [])
                        tp = _get_embedded_field_by_hash(sf, HASH_TEXTURE_PATH)
                        if tp and tp['value'] != tex_path:
                            tp['value'] = tex_path
                            changed = True
                        # Update address modes if present
                        for addr_key, addr_hash in [('addressU', HASH_ADDRESS_U),
                                                     ('addressV', HASH_ADDRESS_V),
                                                     ('addressW', HASH_ADDRESS_W)]:
                            if addr_key in s:
                                af = _get_embedded_field_by_hash(sf, addr_hash)
                                if af and af['value'] != s[addr_key]:
                                    af['value'] = s[addr_key]
                                    changed = True

    # --- Params ---
    params_json = blender_mat.get("parameters")
    if params_json:
        try:
            params_data = _json.loads(params_json)
        except (ValueError, TypeError):
            params_data = None

        if params_data is not None:
            param_field = _get_field_by_hash(fields, HASH_PARAM_VALUES)
            if param_field:
                existing = param_field.get('values', [])
                existing_by_name = {}
                for pv in existing:
                    pf = pv.get('fields', [])
                    pn = _get_embedded_field_by_hash(pf, HASH_NAME)
                    if pn:
                        existing_by_name[pn['value']] = pv

                for p in params_data:
                    p_name = p.get('name', '')
                    p_value = p.get('value')
                    pv_entry = existing_by_name.get(p_name)
                    if pv_entry and p_value is not None:
                        pf = pv_entry.get('fields', [])
                        vf = _get_embedded_field_by_hash(pf, HASH_PARAM_VALUE)
                        if vf:
                            new_val = tuple(p_value[:4]) if isinstance(p_value, (list, tuple)) else p_value
                            if isinstance(vf['value'], (list, tuple)):
                                old_val = tuple(vf['value'])
                            else:
                                old_val = vf['value']
                            if old_val != new_val:
                                vf['value'] = list(new_val) if isinstance(new_val, tuple) else new_val
                                changed = True

    # --- Switches ---
    switches_json = blender_mat.get("switches")
    if switches_json:
        try:
            switches_data = _json.loads(switches_json)
        except (ValueError, TypeError):
            switches_data = None

        if switches_data is not None:
            switch_field = _get_field_by_hash(fields, HASH_SWITCH_VALUES)
            if switch_field:
                existing = switch_field.get('values', [])
                existing_by_name = {}
                for sv in existing:
                    sf = sv.get('fields', [])
                    sn = _get_embedded_field_by_hash(sf, HASH_NAME)
                    if sn:
                        existing_by_name[sn['value']] = sv

                for s in switches_data:
                    s_name = s.get('name', '')
                    s_on = s.get('on', True)
                    sv_entry = existing_by_name.get(s_name)
                    if sv_entry:
                        sf = sv_entry.get('fields', [])
                        on_f = _get_embedded_field_by_hash(sf, HASH_SWITCH_ON)
                        if on_f and on_f['value'] != s_on:
                            on_f['value'] = s_on
                            changed = True

    # --- Techniques (shader path + blend) ---
    techniques_json = blender_mat.get("techniques")
    if techniques_json:
        try:
            techniques_data = _json.loads(techniques_json)
        except (ValueError, TypeError):
            techniques_data = None

        if techniques_data:
            tech_field = _get_field_by_hash(fields, HASH_TECHNIQUES)
            if tech_field:
                for bl_tech in techniques_data:
                    bl_tech_name = bl_tech.get('name', '')
                    bl_passes = bl_tech.get('passes', [])

                    # Find matching technique in bin by name
                    for bin_tech in tech_field.get('values', []):
                        tfields = bin_tech.get('fields', []) if isinstance(bin_tech, dict) else []
                        name_f = _get_embedded_field_by_hash(tfields, HASH_TECHNIQUE_NAME)
                        bin_tech_name = name_f['value'] if name_f else ''
                        if bin_tech_name != bl_tech_name:
                            continue

                        # Try modern layout first, then legacy
                        _BLEND_HASH_SETS = {
                            HASH_PASSES: {
                                'blendEnable': HASH_BLEND_ENABLE,
                                'srcColorBlendFactor': HASH_SRC_COLOR_BLEND,
                                'srcAlphaBlendFactor': HASH_SRC_ALPHA_BLEND,
                                'dstColorBlendFactor': HASH_DST_COLOR_BLEND,
                                'dstAlphaBlendFactor': HASH_DST_ALPHA_BLEND,
                            },
                            HASH_PASSES_LEGACY: {
                                'blendEnable': HASH_BLEND_ENABLE_LEGACY,
                                'srcColorBlendFactor': HASH_SRC_COLOR_BLEND_LEGACY,
                                'srcAlphaBlendFactor': HASH_SRC_ALPHA_BLEND_LEGACY,
                                'dstColorBlendFactor': HASH_DST_COLOR_BLEND_LEGACY,
                                'dstAlphaBlendFactor': HASH_DST_ALPHA_BLEND_LEGACY,
                            },
                        }
                        for passes_hash, shader_hash in [
                            (HASH_PASSES, HASH_SHADER),
                            (HASH_PASSES_LEGACY, HASH_SHADER_LEGACY),
                        ]:
                            passes_f = _get_embedded_field_by_hash(tfields, passes_hash)
                            if not passes_f:
                                continue

                            blend_hashes = _BLEND_HASH_SETS[passes_hash]
                            bin_passes = passes_f.get('values', [])
                            for i, bl_pass in enumerate(bl_passes):
                                if i >= len(bin_passes):
                                    break
                                pfields = bin_passes[i].get('fields', []) if isinstance(bin_passes[i], dict) else []
                                shader_f = _get_embedded_field_by_hash(pfields, shader_hash)
                                if not shader_f:
                                    continue

                                new_shader = bl_pass.get('shader', '')
                                if not new_shader:
                                    continue

                                # Legacy ObjectLink: convert path to FNV-1a hash
                                if shader_hash == HASH_SHADER_LEGACY:
                                    if new_shader.startswith('Shaders/') or new_shader.startswith('shaders/'):
                                        from . import propertybin_parser as _pbp
                                        new_val = "0x%08x" % _pbp.fnv1a_32(new_shader)
                                    else:
                                        new_val = new_shader  # already a hash string
                                else:
                                    new_val = new_shader  # modern: store as path string

                                if shader_f['value'] != new_val:
                                    shader_f['value'] = new_val
                                    changed = True

                                # Update blend settings using correct hashes for this layout
                                # Type IDs: blendEnable = 1 (bool), blend factors = 7 (u32)
                                _BLEND_TYPE_IDS = {
                                    'blendEnable': 1,
                                    'srcColorBlendFactor': 7,
                                    'srcAlphaBlendFactor': 7,
                                    'dstColorBlendFactor': 7,
                                    'dstAlphaBlendFactor': 7,
                                }
                                # Build alternate hash lookup (prey writes modern
                                # blend hashes inside legacy passes containers)
                                _ALT_BLEND = {
                                    'blendEnable': (HASH_BLEND_ENABLE, HASH_BLEND_ENABLE_LEGACY),
                                    'srcColorBlendFactor': (HASH_SRC_COLOR_BLEND, HASH_SRC_COLOR_BLEND_LEGACY),
                                    'srcAlphaBlendFactor': (HASH_SRC_ALPHA_BLEND, HASH_SRC_ALPHA_BLEND_LEGACY),
                                    'dstColorBlendFactor': (HASH_DST_COLOR_BLEND, HASH_DST_COLOR_BLEND_LEGACY),
                                    'dstAlphaBlendFactor': (HASH_DST_ALPHA_BLEND, HASH_DST_ALPHA_BLEND_LEGACY),
                                }
                                for bl_key, bin_hash in blend_hashes.items():
                                    if bl_key not in bl_pass:
                                        continue
                                    bl_val = bl_pass[bl_key]
                                    # Try primary hash first, then alternate
                                    bf = _get_embedded_field_by_hash(pfields, bin_hash)
                                    if not bf:
                                        alt_hashes = _ALT_BLEND.get(bl_key, ())
                                        for ah in alt_hashes:
                                            if ah != bin_hash:
                                                bf = _get_embedded_field_by_hash(pfields, ah)
                                                if bf:
                                                    break
                                    if bf:
                                        if bf['value'] != bl_val:
                                            bf['value'] = bl_val
                                            changed = True
                                    else:
                                        # Field doesn't exist in bin — create it
                                        new_field = {
                                            "name_hash": "0x%08x" % bin_hash,
                                            "name_hash_int": bin_hash,
                                            "type": _BLEND_TYPE_IDS.get(bl_key, 7),
                                            "value": bl_val,
                                        }
                                        pfields.append(new_field)
                                        changed = True

                            break  # found matching passes layout

    return changed


def _blender_to_transform(obj) -> list:
    """Build a 16-float mtx44 (column-major) from Blender object transform.

    Applies the Blender→Game coordinate swap (Y↔Z).
    Particle objects use identity scale (display scale is visual-only).
    """
    import math
    from mathutils import Matrix, Euler

    loc = obj.location
    rot = obj.rotation_euler
    scl = obj.scale

    # Particle objects have an artificial display scale (e.g. 50) — ignore it
    is_particle = obj.get("is_particle_system", False)
    if is_particle:
        scl_x, scl_y, scl_z = 1.0, 1.0, 1.0
    else:
        scl_x, scl_y, scl_z = scl.x, scl.y, scl.z

    # Blender loc (x, y, z) → Game (x, z, y)
    tx, ty, tz = loc.x, loc.z, loc.y
    sx, sy, sz = scl_x, scl_z, scl_y

    # Build rotation matrix with Y/Z swap: Blender euler → game basis
    euler = Euler((rot.x, rot.z, rot.y), 'XYZ')
    rot_mat = euler.to_matrix()

    # Apply scale to rotation columns and produce column-major mtx44
    m = [0.0] * 16
    for c in range(3):
        s = [sx, sy, sz][c]
        m[c * 4 + 0] = rot_mat[0][c] * s
        m[c * 4 + 1] = rot_mat[1][c] * s
        m[c * 4 + 2] = rot_mat[2][c] * s
        m[c * 4 + 3] = 0.0
    m[12], m[13], m[14], m[15] = tx, ty, tz, 1.0
    return m


def _update_bin_particles(entries: list) -> int:
    """Update MapPlaceableContainer items from Blender particle objects.

    Matches each bin item to its Blender counterpart using
    (container_name, system_link) and updates transform, visibility
    flags, and visibility controller.

    Returns the number of particle items updated.
    """
    from . import particles_materials as pm

    TYPE_MPC = pm._BIN_TYPE_MAP_PLACEABLE_CONTAINER
    TYPE_MPC_HEX = f"0x{TYPE_MPC:08x}"

    particle_objs = pm.collect_particle_objects(bpy.context, selected_only=False)
    if not particle_objs:
        return 0

    # Build lookup: (container, system, name) → list of Blender objects
    # Multiple objects may share the same system inside a container,
    # so we pop them in order.
    from collections import defaultdict
    lookup = defaultdict(list)
    for obj in sorted(particle_objs, key=lambda o: o.name):
        cname = obj.get("particle_container", "")
        system = obj.get("particle_system", "")
        name_val = obj.get("particle_name_value", "")
        lookup[(cname, system, name_val)].append(obj)

    updated = 0

    for entry in entries:
        if entry.get('type_hash') != TYPE_MPC_HEX:
            continue

        fields = entry.get('fields', [])
        name_f = _get_field_by_hash(fields, pm._BIN_HASH_NAME)
        container_name = name_f['value'] if name_f else entry.get('path_hash', '')

        items_f = _get_field_by_hash(fields, pm._BIN_HASH_ITEMS)
        if not items_f:
            continue

        # Iterate the actual pairs (preserve order & keys)
        if 'pairs' in items_f:
            item_structs = [
                p['value'] for p in items_f['pairs']
                if isinstance(p, dict) and 'value' in p
            ]
        else:
            item_structs = items_f.get('values', [])

        for item_struct in item_structs:
            item_class = item_struct.get('class_hash', '')
            try:
                item_class_int = int(item_class, 16) if item_class and item_class.startswith('0x') else 0
            except ValueError:
                continue
            if item_class_int not in pm._BIN_PARTICLE_TYPE_HASHES:
                continue

            item_fields = item_struct.get('fields', [])
            if not item_fields:
                continue

            # Get system link and name for matching
            system_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_SYSTEM)
            system_link = ''
            if system_f:
                sv = system_f.get('value', '')
                system_link = str(sv) if sv else ''

            name_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_NAME)
            name_val = ''
            if name_f:
                nv = name_f.get('value', '')
                name_val = str(nv) if nv else ''

            # Find matching Blender object (try full key first, fall back to without name)
            key = (container_name, system_link, name_val)
            candidates = lookup.get(key)
            if not candidates:
                key = (container_name, system_link, '')
                candidates = lookup.get(key)
            if not candidates:
                continue
            obj = candidates.pop(0)

            # --- Update transform ---
            transform_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_TRANSFORM)
            if transform_f:
                new_mtx = _blender_to_transform(obj)
                if transform_f.get('value') != new_mtx:
                    transform_f['value'] = new_mtx
                    updated += 1

            # --- Update visibility flags ---
            vis_flags_val = obj.get("particle_visibility_flags",
                                    obj.get("visibility_layer"))
            if vis_flags_val is not None:
                vis_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_VISIBILITY_FLAGS)
                if vis_f:
                    new_val = int(vis_flags_val)
                    if vis_f.get('value') != new_val:
                        vis_f['value'] = new_val

            # --- Update visibility controller ---
            vis_ctrl_val = obj.get("particle_visibility_controller",
                                   obj.get("baron_hash", ""))
            if vis_ctrl_val:
                vis_ctrl_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_VISIBILITY_CONTROLLER)
                if vis_ctrl_f:
                    ctrl_clean = str(vis_ctrl_val).strip()
                    if not ctrl_clean.startswith("0x"):
                        ctrl_clean = f"0x{ctrl_clean.lower()}"
                    if vis_ctrl_f.get('value') != ctrl_clean:
                        vis_ctrl_f['value'] = ctrl_clean

    return updated


def _collect_scene_map_settings() -> dict:
    """Collect map settings (sun, fog, bake, lighting) from the Blender scene.

    Reads data from the MapSun light object (custom properties) and the
    active World object (custom properties set during import).
    Returns a dict compatible with the keys used by load_map_settings_from_bin().
    """
    settings = {}

    # --- Sun light object ---
    for obj in bpy.context.scene.objects:
        if obj.type == 'LIGHT' and obj.data and obj.data.type == 'SUN':
            if "sun_direction_league" in obj:
                settings['sun_direction'] = list(obj["sun_direction_league"])
            if "sun_color" in obj:
                settings['sun_color'] = list(obj["sun_color"])
            break  # only use first sun

    # --- World custom properties ---
    world = bpy.context.scene.world
    if world:
        _map = {
            'fog_enabled':                       'fog_enabled',
            'fog_color_value':                   'fog_color',
            'fog_start_end':                     'fog_start_end',
            'fog_alternate_color':               'fog_alternate_color',
            'lightmap_color_scale':              'lightmap_color_scale',
            'bake_light_grid_size':              'light_grid_size',
            'bake_light_grid_file':              'light_grid_file',
            'bake_rma_light_grid_texture':       'rma_light_grid_texture',
            'bake_rma_light_grid_intensity_scale': 'rma_light_grid_intensity_scale',
            'bake_light_grid_fullbright_intensity': 'light_grid_fullbright',
            'lighting_v2_min_env_color_contribution': 'min_env_color_contribution',
        }
        for world_key, settings_key in _map.items():
            if world_key in world:
                val = world[world_key]
                # Convert IDPropertyArray to plain list
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    val = list(val)
                settings[settings_key] = val

        # Hemisphere colors from world nodes (stored during import)
        for prop, key in [
            ('sky_light_color', 'sky_light_color'),
            ('horizon_color', 'horizon_color'),
            ('ground_color', 'ground_color'),
            ('sky_light_scale', 'sky_light_scale'),
        ]:
            if prop in world:
                val = world[prop]
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    val = list(val)
                settings[key] = val

    return settings


def _build_sun_entry(settings: dict) -> dict:
    """Build a MapSunProperties bin entry dict from collected settings."""
    fields = []

    # (hash, settings_key, bin_type, default)
    field_defs = [
        (HASH_SUN_COLOR,            'sun_color',            13, None),   # vec4
        (HASH_SUN_DIRECTION,        'sun_direction',        12, None),   # vec3
        (HASH_SKY_LIGHT_COLOR,      'sky_light_color',      13, None),   # vec4
        (HASH_HORIZON_COLOR,        'horizon_color',        13, None),   # vec4
        (HASH_GROUND_COLOR,         'ground_color',         13, None),   # vec4
        (HASH_SKY_LIGHT_SCALE,      'sky_light_scale',      10, None),   # f32
        (HASH_LIGHTMAP_COLOR_SCALE, 'lightmap_color_scale', 10, None),   # f32
        (HASH_FOG_ENABLED,          'fog_enabled',           1, None),   # bool
        (HASH_FOG_COLOR,            'fog_color',            13, None),   # vec4
        (HASH_FOG_ALT_COLOR,        'fog_alternate_color',  13, None),   # vec4
        (HASH_FOG_START_END,        'fog_start_end',        11, None),   # vec2
    ]

    for hash_val, key, type_id, default in field_defs:
        val = settings.get(key, default)
        if val is None:
            continue
        fields.append({
            "name_hash": f"0x{hash_val:08x}",
            "type": type_id,
            "value": val,
        })

    if not fields:
        return None

    return {
        "path_hash": f"0x{HASH_MAP_SUN_PROPERTIES:08x}",
        "type_hash": f"0x{HASH_MAP_SUN_PROPERTIES:08x}",
        "fields": fields,
    }


def _build_bake_entry(settings: dict) -> dict:
    """Build a MapBakeProperties bin entry dict from collected settings."""
    fields = []

    field_defs = [
        (HASH_LIGHT_GRID_SIZE,  'light_grid_size',                 7, None),   # u32
        (HASH_LIGHT_GRID_FILE,  'light_grid_file',                16, None),   # string
        (HASH_RMA_GRID_TEX,     'rma_light_grid_texture',         16, None),   # string
        (HASH_RMA_GRID_SCALE,   'rma_light_grid_intensity_scale', 10, None),   # f32
        (HASH_GRID_FULLBRIGHT,  'light_grid_fullbright',          10, None),   # f32
    ]

    for hash_val, key, type_id, default in field_defs:
        val = settings.get(key, default)
        if val is None:
            continue
        fields.append({
            "name_hash": f"0x{hash_val:08x}",
            "type": type_id,
            "value": val,
        })

    return {
        "path_hash": f"0x{HASH_MAP_BAKE_PROPERTIES:08x}",
        "type_hash": f"0x{HASH_MAP_BAKE_PROPERTIES:08x}",
        "fields": fields,
    }


def _build_lighting_v2_entry(settings: dict) -> dict:
    """Build a MapLightingV2 bin entry dict from collected settings."""
    val = settings.get('min_env_color_contribution')
    if val is None:
        return None

    return {
        "path_hash": f"0x{HASH_MAP_LIGHTING_V2:08x}",
        "type_hash": f"0x{HASH_MAP_LIGHTING_V2:08x}",
        "fields": [{
            "name_hash": f"0x{HASH_MIN_ENV_CONTRIBUTION:08x}",
            "type": 10,
            "value": val,
        }],
    }


def _update_bin_map_settings(entries: list):
    """Update or inject MapSunProperties / MapBakeProperties / MapLightingV2
    in the bin entries list from Blender scene data.
    Skips injection if the properties already live inside a MapContainer entry."""
    scene_settings = _collect_scene_map_settings()
    if not scene_settings:
        return

    sun_hash_str = f"0x{HASH_MAP_SUN_PROPERTIES:08x}"
    bake_hash_str = f"0x{HASH_MAP_BAKE_PROPERTIES:08x}"
    lighting_hash_str = f"0x{HASH_MAP_LIGHTING_V2:08x}"
    container_hash_str = "0xdde8c114"

    existing = {sun_hash_str: None, bake_hash_str: None, lighting_hash_str: None}
    has_map_container = False
    for entry in entries:
        th = entry.get('type_hash', '')
        if th in existing:
            existing[th] = entry
        elif th == container_hash_str:
            # MapContainer with embedded items — check for sun/bake/lighting
            has_map_container = True
            for f in entry.get('fields', []):
                for v in f.get('values', []):
                    ch = v.get('class_hash', '')
                    if ch == sun_hash_str and existing[sun_hash_str] is None:
                        existing[sun_hash_str] = "embedded"
                    elif ch == bake_hash_str and existing[bake_hash_str] is None:
                        existing[bake_hash_str] = "embedded"
                    elif ch == lighting_hash_str and existing[lighting_hash_str] is None:
                        existing[lighting_hash_str] = "embedded"

    builders = [
        (sun_hash_str,      _build_sun_entry),
        (bake_hash_str,     _build_bake_entry),
        (lighting_hash_str, _build_lighting_v2_entry),
    ]

    for type_hash_str, builder in builders:
        new_entry = builder(scene_settings)
        if new_entry is None:
            continue
        old = existing[type_hash_str]
        if old == "embedded":
            # Properties live inside MapContainer — don't create standalone
            continue
        elif old is not None:
            # Update existing standalone entry's fields
            old['fields'] = new_entry['fields']
            print(f"[Project Export] Updated {type_hash_str} with {len(new_entry['fields'])} field(s)")
        else:
            entries.append(new_entry)
            print(f"[Project Export] Injected {type_hash_str} with {len(new_entry['fields'])} field(s)")


def _export_materials_bin_merge(source_bin_path: str, output_bin_path: str) -> int:
    """Export Blender materials and particles merged into an existing .materials.bin.

    Parses the original .materials.bin, updates StaticMaterialDef entries
    with values from Blender materials, updates MapPlaceableContainer items
    with particle transforms/visibility from Blender objects, preserves
    everything else, and writes back as .materials.bin.

    Returns the total number of entries updated (materials + particles).
    """
    from . import propertybin_parser

    data = propertybin_parser.parse_bin(source_bin_path)
    entries = data.get('entries', [])

    # ── Update materials ──
    blender_mats = {}
    for mat in bpy.data.materials:
        league_name = mat.get('league_material_name')
        if league_name:
            blender_mats[league_name] = mat

    mat_updated = 0
    for entry in entries:
        if entry.get('type_hash') != f"0x{HASH_STATIC_MATERIAL_DEF:08x}":
            continue
        fields = entry.get('fields', [])
        name_field = _get_field_by_hash(fields, HASH_NAME)
        if not name_field:
            continue
        mat_name = name_field['value']
        bmat = blender_mats.get(mat_name)
        if not bmat:
            continue
        if _update_bin_material_from_blender(entry, bmat):
            mat_updated += 1

    # ── Update particles ──
    particle_updated = _update_bin_particles(entries)

    # ── Update GdsMapObject entries ──
    from . import map_objects_import
    mo_updated = map_objects_import.update_bin_map_objects(entries)

    # ── Update / inject map settings (sun, fog, bake, lighting) ──
    _update_bin_map_settings(entries)

    propertybin_parser.write_bin(data, output_bin_path)

    total = mat_updated + particle_updated + mo_updated
    if particle_updated or mo_updated:
        print(f"[Project Export] Updated {mat_updated} material(s), {particle_updated} particle(s), {mo_updated} map object(s)")
    return total


def _resolve_default_reference_materials(settings) -> str:
    """Resolve a default Riot reference materials path for the current map."""
    map_id = (settings.project_map_id or "").lower()
    league_path = bpy.path.abspath(settings.league_install) if settings.league_install else ""
    if map_id == "map11" and league_path and os.path.isdir(league_path):
        base_candidate = os.path.join(
            league_path,
            "Game", "DATA", "FINAL", "Maps", "Shipping", "Map11.wad",
            "data", "maps", "mapgeometry", "map11", "base.materials.bin",
        )
        if os.path.isfile(base_candidate):
            return base_candidate

        sodapop_candidate = os.path.join(
            league_path,
            "Game", "DATA", "FINAL", "Maps", "Shipping", "Map11.wad",
            "data", "maps", "mapgeometry", "map11", "sodapop_srs.materials.bin",
        )
        if os.path.isfile(sodapop_candidate):
            return sodapop_candidate
    return ""


def _normalize_legacy_texture_path(value: str) -> str:
    """Normalize legacy sampler path text without importing reference values."""
    if not value:
        return ""
    return str(value).strip().replace('\\', '/')


def _material_name_from_entry(entry: dict) -> str:
    fields = entry.get('fields', [])
    name_field = _get_field_by_hash(fields, HASH_NAME)
    return str(name_field.get('value', '') if name_field else '')


def _parse_hash32(value) -> int | None:
    """Parse hex/int-ish hash values into int, returning None on failure."""
    try:
        if isinstance(value, int):
            return value & 0xFFFFFFFF
        s = str(value).strip()
        if not s:
            return None
        if s.lower().startswith('0x'):
            return int(s, 16) & 0xFFFFFFFF
        return int(s) & 0xFFFFFFFF
    except Exception:
        return None


# Manual overrides for old shader hashes that don't match any template path
# (renamed shaders, removed Environment/ prefix shaders, etc.)
_SHADER_HASH_OVERRIDES = {
    0x2af09534: "Shaders/StaticMesh/DefaultEnv_Flat",    # Shaders/Environment/DefaultEnv
    0x820e2bef: "Shaders/StaticMesh/DefaultEnv_Glow",    # shaders/staticmesh/env_glow
    0xcb5aa63a: "Shaders/StaticMesh/Hologram",           # Hologram_Layered
}

# Default fallback shader when hash can't be resolved
_DEFAULT_FALLBACK_SHADER = "Shaders/StaticMesh/DefaultEnv_Flat"


def _build_shader_template_lookup() -> dict:
    """Return shader hash/path lookup from shader_templates_data.json.

    Hashes each template path with multiple prefix variants (StaticMesh/,
    Environment/) and in both original case and lowercase, so old bins
    with Environment/ or case-different hashes can be resolved.
    """
    from . import propertybin_parser

    path = os.path.join(os.path.dirname(__file__), 'shader_templates_data.json')
    if not os.path.isfile(path):
        return {'by_path': {}, 'by_hash': {}}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {'by_path': {}, 'by_hash': {}}

    by_path = {}
    by_hash = {}

    def _add(variant, tpl_path):
        try:
            h = propertybin_parser.fnv1a_32(variant)
            if h not in by_hash:
                by_hash[h] = tpl_path
        except Exception:
            pass

    for shader_path, tpl in data.items():
        if not isinstance(shader_path, str) or not isinstance(tpl, dict):
            continue
        by_path[shader_path] = tpl

        # Hash with multiple prefix and case variants
        short = tpl.get('short_name', '')
        variants = [shader_path]
        if short:
            variants.append(f"Shaders/StaticMesh/{short}")
            variants.append(f"Shaders/Environment/{short}")
        for v in list(variants):
            variants.append(v.lower())
        for v in set(variants):
            _add(v, shader_path)

    # Apply manual overrides
    for h, tpl_path in _SHADER_HASH_OVERRIDES.items():
        by_hash[h] = tpl_path

    return {'by_path': by_path, 'by_hash': by_hash}


# Old-format technique pass field hashes (different from modern)
HASH_PASSES_LEGACY = 0x623cd25c     # Old pass list field (modern uses 0x917e428e)
HASH_SHADER_LEGACY = 0x355d5568     # Old shader ObjectLink (modern uses 0xc5ac22aa)
HASH_BLEND_ENABLE_LEGACY = 0x23b75597
HASH_SRC_COLOR_BLEND_LEGACY = 0x22c0c7d0
HASH_SRC_ALPHA_BLEND_LEGACY = 0xa0958d01
HASH_DST_COLOR_BLEND_LEGACY = 0xbe0abbf5
HASH_DST_ALPHA_BLEND_LEGACY = 0x7385e534


def _get_material_shader_value(entry: dict):
    """Extract first pass shader value from a StaticMaterialDef entry.

    Handles both modern (HASH_PASSES/HASH_SHADER) and legacy
    (HASH_PASSES_LEGACY/HASH_SHADER_LEGACY) field layouts.
    """
    fields = entry.get('fields', [])
    tech_f = _get_field_by_hash(fields, HASH_TECHNIQUES)
    if not tech_f:
        return None

    for tech in tech_f.get('values', []):
        tfields = tech.get('fields', []) if isinstance(tech, dict) else []

        # Try modern layout first, then legacy
        for passes_hash, shader_hash in [
            (HASH_PASSES, HASH_SHADER),
            (HASH_PASSES_LEGACY, HASH_SHADER_LEGACY),
        ]:
            passes_f = _get_embedded_field_by_hash(tfields, passes_hash)
            if not passes_f:
                continue
            for p in passes_f.get('values', []):
                pfields = p.get('fields', []) if isinstance(p, dict) else []
                shader_f = _get_embedded_field_by_hash(pfields, shader_hash)
                if shader_f and shader_f.get('value'):
                    return shader_f.get('value')
    return None


def _resolve_material_shader_path(entry: dict, shader_lookup: dict) -> str:
    """Resolve material shader to template path (direct path or hash)."""
    shader_val = _get_material_shader_value(entry)
    if not shader_val:
        return ''

    sval = str(shader_val)
    if sval.startswith('Shaders/'):
        return sval

    h = _parse_hash32(shader_val)
    if h is None:
        return ''

    return shader_lookup.get('by_hash', {}).get(h, '')


def _get_switch_struct_class_hash(entries: list) -> str:
    """Find an existing switch struct class hash to preserve binary style."""
    default_hash = '0x00000000'
    for e in entries:
        if e.get('type_hash') != f"0x{HASH_STATIC_MATERIAL_DEF:08x}":
            continue
        sf = _get_field_by_hash(e.get('fields', []), HASH_SWITCH_VALUES)
        if not sf:
            continue
        for sv in sf.get('values', []):
            ch = sv.get('class_hash')
            if ch:
                return ch
    return default_hash


def _ensure_template_switches(entry: dict, tpl: dict, switch_class_hash: str) -> int:
    """Ensure material contains switch definitions from shader template."""
    if not tpl:
        return 0

    tpl_switches = tpl.get('switches') or []
    if not isinstance(tpl_switches, list) or not tpl_switches:
        return 0

    fields = entry.get('fields', [])
    switch_f = _get_field_by_hash(fields, HASH_SWITCH_VALUES)
    if switch_f is None:
        switch_f = {
            'name_hash': f"0x{HASH_SWITCH_VALUES:08x}",
            'name_hash_int': HASH_SWITCH_VALUES,
            'type': 0x80,
            'value_type': 0x83,
            'values': [],
        }
        fields.append(switch_f)

    values = switch_f.setdefault('values', [])
    existing = set()
    for sw in values:
        sfields = sw.get('fields', []) if isinstance(sw, dict) else []
        n = _get_embedded_field_by_hash(sfields, HASH_NAME)
        if n and n.get('value'):
            existing.add(str(n['value']).lower())

    added = 0
    for ts in tpl_switches:
        if not isinstance(ts, dict):
            continue
        name = str(ts.get('name') or '').strip()
        if not name:
            continue
        key = name.lower()
        if key in existing:
            continue

        on_val = ts.get('on', False)
        switch_struct = {
            'type': 0x83,
            'class_hash': switch_class_hash,
            'fields': [
                {
                    'name_hash': f"0x{HASH_NAME:08x}",
                    'name_hash_int': HASH_NAME,
                    'type': 16,
                    'value': name,
                },
                {
                    'name_hash': f"0x{HASH_SWITCH_ON:08x}",
                    'name_hash_int': HASH_SWITCH_ON,
                    'type': 1,
                    'value': bool(on_val),
                },
            ],
        }
        values.append(switch_struct)
        existing.add(key)
        added += 1

    return added


def _normalize_particle_entry_defaults(entries: list) -> int:
    """Normalize common particle fields in MapPlaceableContainer items."""
    from . import particles_materials as pm

    changed = 0
    for entry in entries:
        if entry.get('_preserve_raw'):
            continue
        if entry.get('type_hash') != f"0x{pm._BIN_TYPE_MAP_PLACEABLE_CONTAINER:08x}":
            continue
        fields = entry.get('fields', [])
        items_f = _get_field_by_hash(fields, pm._BIN_HASH_ITEMS)
        if not items_f:
            continue

        item_structs = []
        if 'pairs' in items_f:
            for pair in items_f.get('pairs', []):
                if isinstance(pair, dict) and isinstance(pair.get('value'), dict):
                    item_structs.append(pair['value'])
        else:
            item_structs.extend(items_f.get('values', []))

        for item in item_structs:
            class_hash = _parse_hash32(item.get('class_hash'))
            if class_hash not in pm._BIN_PARTICLE_TYPE_HASHES:
                continue

            item_fields = item.get('fields', [])
            vis_flags_f = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_VISIBILITY_FLAGS)
            if vis_flags_f is None:
                item_fields.append({
                    'name_hash': f"0x{pm._BIN_HASH_VISIBILITY_FLAGS:08x}",
                    'name_hash_int': pm._BIN_HASH_VISIBILITY_FLAGS,
                    'type': 3,
                    'value': 1,
                })
                changed += 1
            else:
                try:
                    v = int(vis_flags_f.get('value', 1))
                except Exception:
                    v = 1
                v = max(0, min(255, v))
                if vis_flags_f.get('value') != v:
                    vis_flags_f['value'] = v
                    changed += 1

            xf = pm._bin_get_embedded_field(item_fields, pm._BIN_HASH_TRANSFORM)
            if xf and isinstance(xf.get('value'), list) and len(xf['value']) != 16:
                xf['value'] = (xf['value'] + [0.0] * 16)[:16]
                changed += 1

    return changed


# ── VFX entry migration ─────────────────────────────────────────────────
_VFX_OLD_TEXTURE_HASH = 0x38344d14      # Old emitter texture field (gone in modern)
_VFX_NEW_TEXTURE_HASH = 0x3c6468f4      # Modern emitter texture field
_VFX_TEXTURE_FIELD_HASHES = {           # All field hashes that carry texture paths
    0x38344d14, 0x3c6468f4, 0x2f2e99f2, 0x5da05f9b,
    0x99a7180f, 0xb56e8811, 0xe672d557, 0xffa711fb,
}


def _migrate_vfx_entry_fields(entry: dict) -> tuple[int, int]:
    """Migrate VfxSystemDefinitionData entry in-place.

    1. Rename field 0x38344d14 → 0x3c6468f4  (old texture → modern texture)
    2. Rewrite .dds → .tex on all texture path strings

    Returns (fields_renamed, ext_fixed) counts.
    """
    fields_renamed = 0
    ext_fixed = 0

    old_hash_str = f"0x{_VFX_OLD_TEXTURE_HASH:08x}"
    new_hash_str = f"0x{_VFX_NEW_TEXTURE_HASH:08x}"
    tex_hash_strs = {f"0x{h:08x}" for h in _VFX_TEXTURE_FIELD_HASHES}

    def _walk(node):
        nonlocal fields_renamed, ext_fixed
        if not isinstance(node, dict):
            return
        nh = node.get("name_hash", "")

        # 1) Field hash rename
        if nh == old_hash_str:
            node["name_hash"] = new_hash_str
            if "name_hash_int" in node:
                node["name_hash_int"] = _VFX_NEW_TEXTURE_HASH
            fields_renamed += 1

        # 2) .dds → .tex on texture string fields
        cur_hash = node.get("name_hash", "")
        if cur_hash in tex_hash_strs:
            v = node.get("value", "")
            if isinstance(v, str) and v.lower().endswith(".dds"):
                node["value"] = v[:-4] + ".tex"
                ext_fixed += 1

        # Recurse
        for f in node.get("fields") or []:
            _walk(f)
        for v in node.get("values") or []:
            _walk(v)
        for p in node.get("pairs") or []:
            _walk(p.get("key", {}))
            _walk(p.get("value", {}))
        if isinstance(node.get("value"), dict):
            _walk(node["value"])

    for f in entry.get("fields", []):
        _walk(f)

    return fields_renamed, ext_fixed


def _bump_prop_version_header_only(src_path: str, dst_path: str, new_version: int) -> bool:
    """Set PROP header version in-place without reserializing entry payloads."""
    try:
        with open(src_path, 'rb') as f:
            blob = bytearray(f.read())
        if len(blob) < 8:
            return False

        # PTCH wrapper stores PROP header at offset 8.
        if blob[:4] == b'PTCH':
            if len(blob) < 16 or blob[8:12] != b'PROP':
                return False
            version_off = 12
        elif blob[:4] == b'PROP':
            version_off = 4
        else:
            return False

        blob[version_off:version_off + 4] = int(new_version).to_bytes(4, 'little', signed=False)
        with open(dst_path, 'wb') as f:
            f.write(blob)
        return True
    except Exception:
        return False


def _migrate_legacy_sampler_field(dst_sampler_field: dict, ref_sampler_field: dict | None,
                                  template_sampler_name: str = "") -> bool:
    """Patch one sampler struct from legacy layout into modern layout.

    The updater intentionally avoids pulling texture values from the reference
    file. It only migrates schema (slot name) and preserves existing texture
    value information from the legacy material itself.

    template_sampler_name: When provided (from shader template), used as the
    semantic name for this slot instead of the hardcoded 'DiffuseTexture'
    fallback.
    """
    if not isinstance(dst_sampler_field, dict):
        return False

    dst_fields = dst_sampler_field.get('fields', [])
    dst_name_f = _get_embedded_field_by_hash(dst_fields, HASH_TEXTURE_NAME)
    legacy_name_f = _get_embedded_field_by_hash(dst_fields, HASH_SAMPLER_NAME_LEGACY)
    dst_path_f = _get_embedded_field_by_hash(dst_fields, HASH_TEXTURE_PATH)

    changed = False

    # Case A: Both textureName and samplerName exist (old format).
    #   samplerName = semantic name (e.g. "DiffuseTexture")
    #   textureName = texture path (e.g. "ASSETS/.../texture.dds")
    #   → Move path to texturePath, set textureName to template/semantic name,
    #     and remove the legacy samplerName field.
    if dst_name_f and legacy_name_f:
        old_tex_val = str(dst_name_f.get('value', '') or '')
        looks_like_path = '/' in old_tex_val or '\\' in old_tex_val
        if looks_like_path:
            new_path = _normalize_legacy_texture_path(old_tex_val)

            # Determine semantic name for this slot
            ref_name = template_sampler_name or str(legacy_name_f.get('value', '') or '') or "DiffuseTexture"
            if isinstance(ref_sampler_field, dict):
                ref_fields = ref_sampler_field.get('fields', [])
                rn = _get_embedded_field_by_hash(ref_fields, HASH_TEXTURE_NAME)
                if rn is None:
                    rn = _get_embedded_field_by_hash(ref_fields, HASH_SAMPLER_NAME_LEGACY)
                if rn and rn.get('value'):
                    ref_name = str(rn.get('value'))

            # Set textureName to semantic name
            dst_name_f['value'] = ref_name

            # Create or update texturePath
            if dst_path_f is None:
                dst_path_f = {
                    'name_hash': f"0x{HASH_TEXTURE_PATH:08x}",
                    'type': 16,
                    'value': new_path,
                    'name_hash_int': HASH_TEXTURE_PATH,
                }
                dst_fields.append(dst_path_f)
            else:
                dst_path_f['value'] = new_path

            # Remove legacy samplerName field
            dst_fields[:] = [f for f in dst_fields
                             if f.get('name_hash_int') != HASH_SAMPLER_NAME_LEGACY]
            return True
        # If textureName doesn't look like a path, fall through to standard logic.

    # Case B: Only samplerName exists (no textureName) — rewrite hash.
    if not dst_name_f and legacy_name_f:
        legacy_name_f['name_hash'] = f"0x{HASH_TEXTURE_NAME:08x}"
        legacy_name_f['name_hash_int'] = HASH_TEXTURE_NAME
        dst_name_f = legacy_name_f
        changed = True

    if not dst_name_f:
        return False

    old_name = str(dst_name_f.get('value', '') or '')
    old_path = str(dst_path_f.get('value', '') or '') if dst_path_f else ''
    legacy_source = old_path or old_name

    looks_legacy = (not old_path.strip()) and ('/' in old_name or '\\' in old_name)
    if not looks_legacy:
        return changed

    # Determine the correct semantic name for this sampler slot.
    # Priority: template name > reference name > fallback "DiffuseTexture"
    ref_name = template_sampler_name or "DiffuseTexture"
    if isinstance(ref_sampler_field, dict):
        ref_fields = ref_sampler_field.get('fields', [])
        rn = _get_embedded_field_by_hash(ref_fields, HASH_TEXTURE_NAME)
        if rn is None:
            rn = _get_embedded_field_by_hash(ref_fields, HASH_SAMPLER_NAME_LEGACY)
        if rn and rn.get('value'):
            ref_name = str(rn.get('value'))

    new_path = _normalize_legacy_texture_path(legacy_source)

    if dst_name_f.get('value') != ref_name:
        dst_name_f['value'] = ref_name
        changed = True

    if dst_path_f is None:
        dst_path_f = {
            'name_hash': f"0x{HASH_TEXTURE_PATH:08x}",
            'type': 16,
            'value': new_path,
            'name_hash_int': HASH_TEXTURE_PATH,
        }
        dst_fields.append(dst_path_f)
        changed = True
    elif dst_path_f.get('value') != new_path:
        dst_path_f['value'] = new_path
        changed = True

    return changed


def _apply_reference_material_update(dst_entry: dict, ref_entry: dict) -> tuple[int, int]:
    """Apply sampler + switch migration from one reference material entry."""
    dst_fields = dst_entry.get('fields', [])
    ref_fields = ref_entry.get('fields', [])

    samplers_migrated = 0
    switches_added = 0

    # --- Migrate legacy sampler layout ---
    dst_sampler_f = _get_field_by_hash(dst_fields, HASH_SAMPLER_VALUES)
    ref_sampler_f = _get_field_by_hash(ref_fields, HASH_SAMPLER_VALUES)
    if dst_sampler_f and ref_sampler_f:
        dst_values = dst_sampler_f.get('values', [])
        ref_values = ref_sampler_f.get('values', [])
        for i, dst_sampler in enumerate(dst_values):
            ref_sampler = ref_values[i] if i < len(ref_values) else None
            if _migrate_legacy_sampler_field(dst_sampler, ref_sampler):
                samplers_migrated += 1

    # --- Add missing switches from reference ---
    dst_switch_f = _get_field_by_hash(dst_fields, HASH_SWITCH_VALUES)
    ref_switch_f = _get_field_by_hash(ref_fields, HASH_SWITCH_VALUES)
    if dst_switch_f and ref_switch_f:
        dst_values = dst_switch_f.get('values', [])
        ref_values = ref_switch_f.get('values', [])

        have = set()
        for sw in dst_values:
            sf = sw.get('fields', []) if isinstance(sw, dict) else []
            name_f = _get_embedded_field_by_hash(sf, HASH_NAME)
            if name_f and name_f.get('value'):
                have.add(str(name_f['value']).lower())

        for ref_sw in ref_values:
            rf = ref_sw.get('fields', []) if isinstance(ref_sw, dict) else []
            name_f = _get_embedded_field_by_hash(rf, HASH_NAME)
            if not name_f or not name_f.get('value'):
                continue
            key = str(name_f['value']).lower()
            if key in have:
                continue
            dst_values.append(copy.deepcopy(ref_sw))
            have.add(key)
            switches_added += 1

    return samplers_migrated, switches_added


def update_legacy_materials_bin(target_bin_path: str, reference_bin_path: str | None = None, output_bin_path: str | None = None) -> dict:
    """Upgrade legacy bins using internal migration rules and templates.

    reference_bin_path is optional; when provided, it can still be used for
    name-matched fallback switch migration.
    """
    from . import propertybin_parser

    target_data = propertybin_parser.parse_bin(target_bin_path)
    reference_data = None
    if reference_bin_path and os.path.isfile(reference_bin_path):
        reference_data = propertybin_parser.parse_bin(reference_bin_path)

    shader_lookup = _build_shader_template_lookup()
    switch_class_hash = _get_switch_struct_class_hash(target_data.get('entries', []))

    ref_by_name = {}
    if reference_data:
        for entry in reference_data.get('entries', []):
            if entry.get('type_hash') != f"0x{HASH_STATIC_MATERIAL_DEF:08x}":
                continue
            name = _material_name_from_entry(entry)
            if name:
                ref_by_name[name.lower()] = entry

    materials_seen = 0
    matched = 0
    samplers_migrated = 0
    switches_added = 0
    particle_values_updated = 0
    vfx_total = 0
    vfx_fields_renamed = 0
    vfx_ext_fixed = 0

    for entry in target_data.get('entries', []):
        if entry.get('_preserve_raw'):
            continue
        th = entry.get('type_hash', '')

        # --- VFX entry migration: field rename + .dds → .tex ---
        if th == '0x45cd899f':
            fr, ef = _migrate_vfx_entry_fields(entry)
            vfx_total += 1
            vfx_fields_renamed += fr
            vfx_ext_fixed += ef
            continue

        if th != f"0x{HASH_STATIC_MATERIAL_DEF:08x}":
            continue
        materials_seen += 1

        # 1) Resolve shader template FIRST so sampler names are available.
        shader_path = _resolve_material_shader_path(entry, shader_lookup)
        tpl = shader_lookup.get('by_path', {}).get(shader_path, {}) if shader_path else {}
        tpl_samplers = tpl.get('samplers', []) if isinstance(tpl, dict) else []

        # 2) Internal legacy sampler schema fix — uses template names per slot.
        dst_fields = entry.get('fields', [])
        dst_sampler_f = _get_field_by_hash(dst_fields, HASH_SAMPLER_VALUES)
        if dst_sampler_f:
            for i, dst_sampler in enumerate(dst_sampler_f.get('values', [])):
                tpl_name = ""
                if i < len(tpl_samplers) and isinstance(tpl_samplers[i], dict):
                    tpl_name = str(tpl_samplers[i].get('name', ''))
                if _migrate_legacy_sampler_field(dst_sampler, None, tpl_name):
                    samplers_migrated += 1

        # 3) Template-driven switch additions based on shader.
        switches_added += _ensure_template_switches(entry, tpl, switch_class_hash)

        # 4) Optional reference-based fallback additions.
        name = _material_name_from_entry(entry)
        ref_entry = ref_by_name.get(name.lower()) if name else None
        if not ref_entry:
            continue
        matched += 1
        _sm, sw = _apply_reference_material_update(entry, ref_entry)
        switches_added += sw

    # 5) Particle normalization pass.
    particle_values_updated = _normalize_particle_entry_defaults(target_data.get('entries', []))

    # 5) Bump bin version to latest supported (v3).
    old_version = int(target_data.get('version', 2) or 2)
    raw_preserved_entries = sum(1 for e in target_data.get('entries', []) if e.get('_preserve_raw'))
    out_path = output_bin_path or target_bin_path
    header_only_bump = False

    if raw_preserved_entries > 0:
        # Legacy-heavy files are kept byte-exact and only header version is
        # bumped to avoid lossy rewrites.
        target_version = max(old_version, 3)
        if target_version != old_version:
            if not _bump_prop_version_header_only(target_bin_path, out_path, target_version):
                raise RuntimeError("Failed header-only version bump")
            header_only_bump = True
            target_data['version'] = target_version
        else:
            # No bump needed; keep source untouched.
            if out_path != target_bin_path:
                import shutil
                shutil.copy2(target_bin_path, out_path)
            target_data['version'] = old_version
    else:
        target_data['version'] = max(old_version, 3)
        propertybin_parser.write_bin(target_data, out_path)

    return {
        'materials_total': materials_seen,
        'materials_matched': matched,
        'samplers_migrated': samplers_migrated,
        'switches_added': switches_added,
        'particle_values_updated': particle_values_updated,
        'vfx_total': vfx_total,
        'vfx_fields_renamed': vfx_fields_renamed,
        'vfx_ext_fixed': vfx_ext_fixed,
        'version_from': old_version,
        'version_to': target_data['version'],
        'raw_preserved_entries': raw_preserved_entries,
        'header_only_bump': header_only_bump,
        'output_path': out_path,
    }


class PROJECT_OT_export_mapgeo(Operator):
    """Export the mapgeo back to the project folder"""
    bl_idname = "project.export_mapgeo"
    bl_label = "Export Mapgeo"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings

        if not settings.loaded_mapgeo_path:
            self.report({'ERROR'}, "No mapgeo loaded — load a map variant first")
            return {'CANCELLED'}

        output_path = settings.loaded_mapgeo_path
        if not output_path:
            self.report({'ERROR'}, "No mapgeo output path")
            return {'CANCELLED'}

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            bpy.ops.export_scene.mapgeo('EXEC_DEFAULT', filepath=output_path, export_version=settings.export_version, bucket_grid_mode='ORIGINAL')
        except Exception as e:
            self.report({'ERROR'}, f"Mapgeo export failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported mapgeo → {os.path.basename(output_path)}")
        return {'FINISHED'}


class PROJECT_OT_export_materials(Operator):
    """Export materials back to the project folder"""
    bl_idname = "project.export_materials"
    bl_label = "Export Materials"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings

        source_path = settings.loaded_materials_path
        if not source_path:
            self.report({'ERROR'}, "No materials file loaded — load a map variant first")
            return {'CANCELLED'}

        if not os.path.isfile(source_path):
            self.report({'ERROR'}, f"Source materials file not found: {source_path}")
            return {'CANCELLED'}

        output_path = source_path  # Overwrite in-place
        fmt = settings.loaded_materials_format

        # If prey files exist and user wants to rebuild, do it first
        if settings.has_prey and settings.use_prey_on_export and settings.prey_dir:
            base = _get_prey_base_name(source_path)
            manifest = os.path.join(settings.prey_dir, f"{base}.prey.manifest")
            if os.path.isfile(manifest):
                try:
                    from . import prey_format
                    bin_output = source_path
                    if not bin_output.endswith('.materials.bin'):
                        bin_output = os.path.splitext(bin_output)[0] + '.materials.bin'
                    prey_format.prey_to_bin(settings.prey_dir, base, bin_output)
                    # Use the rebuilt bin as the source for merging
                    source_path = bin_output
                    output_path = bin_output
                    fmt = 'bin'
                    print(f"[Project Export] Rebuilt .materials.bin from .prey files")
                except Exception as e:
                    print(f"[Project Export] Warning: prey rebuild failed, using original: {e}")

        try:
            count = _export_materials_bin_merge(source_path, output_path)

            self.report({'INFO'}, f"Exported {count} material(s) → {os.path.basename(output_path)}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Materials export failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class PROJECT_OT_cleanup_materials(Operator):
    """Remove materials not used by any mesh in the scene"""
    bl_idname = "project.cleanup_materials"
    bl_label = "Cleanup Unused Materials"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Collect all material names actually used by mesh objects
        used_materials = set()
        for obj in context.scene.objects:
            if obj.type == 'MESH' and obj.data:
                for slot in obj.material_slots:
                    if slot.material:
                        used_materials.add(slot.material.name)

        # Find league materials that are not used by any mesh
        to_remove = []
        for mat in bpy.data.materials:
            if mat.get("league_material_name") and mat.name not in used_materials:
                to_remove.append(mat)

        if not to_remove:
            self.report({'INFO'}, "No unused materials found")
            return {'FINISHED'}

        count = len(to_remove)
        for mat in to_remove:
            bpy.data.materials.remove(mat)

        self.report({'INFO'}, f"Removed {count} unused material(s)")
        return {'FINISHED'}


class PROJECT_OT_export_all(Operator):
    """Export mapgeo/material outputs back to the project."""
    bl_idname = "project.export_all"
    bl_label = "Export All"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        results = []

        if settings.export_mapgeo and settings.loaded_mapgeo_path:
            ret = bpy.ops.project.export_mapgeo()
            if ret == {'FINISHED'}:
                results.append('mapgeo')

        if settings.export_materials and settings.loaded_materials_path:
            ret = bpy.ops.project.export_materials()
            if ret == {'FINISHED'}:
                results.append('materials')

        if not results:
            self.report({'WARNING'}, "Nothing to export — load a map variant first")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported: {', '.join(results)}")
        return {'FINISHED'}


class PROJECT_OT_extract_riot_wad(Operator):
    """Extract a Riot WAD file for base assets"""
    bl_idname = "project.extract_riot_wad"
    bl_label = "Extract Riot WAD"
    bl_options = {'REGISTER'}
    
    map_id: StringProperty(name="Map ID", default="")
    
    def execute(self, context):
        settings = context.scene.project_settings
        league_path = bpy.path.abspath(settings.league_install)
        
        if not league_path:
            self.report({'ERROR'}, "League installation path not set")
            return {'CANCELLED'}
        
        wad_dir = get_maps_wad_dir(league_path)
        if not wad_dir:
            self.report({'ERROR'}, "Maps WAD directory not found")
            return {'CANCELLED'}
        
        # Find WAD file
        map_id = self.map_id or settings.project_map_id
        if not map_id:
            self.report({'ERROR'}, "No map ID specified")
            return {'CANCELLED'}
        
        wad_path = ""
        for fname in os.listdir(wad_dir):
            fname_lower = fname.lower()
            map_lower = map_id.lower()
            if not fname_lower.startswith(map_lower):
                continue
            if '.wad' not in fname_lower or 'levels' in fname_lower:
                continue
            # Skip language WADs (e.g. Map11.en_US.wad.client)
            remainder = fname_lower[len(map_lower):]
            if remainder.startswith('.') and not remainder.startswith('.wad'):
                continue
            # Prefer .wad.client over plain .wad
            if not wad_path or '.wad.client' in fname_lower:
                wad_path = os.path.join(wad_dir, fname)
        
        if not wad_path:
            self.report({'ERROR'}, f"WAD file not found for {map_id}")
            return {'CANCELLED'}
        
        # Extract
        from . import wad_tool
        import shutil
        import tempfile
        try:
            cache_dir = os.path.join(_get_wad_cache_root(), map_id)
            
            # Clean previous cache to avoid stale files and disk bloat
            _clean_wad_cache_dir(cache_dir)
            
            # Try direct read; copy to temp on permission error
            tmp_wad = None
            try:
                wad = wad_tool.parse_wad(wad_path)
            except PermissionError:
                self.report({'WARNING'}, "Permission denied, copying WAD to temp...")
                tmp_wad = os.path.join(tempfile.gettempdir(), os.path.basename(wad_path))
                shutil.copy2(wad_path, tmp_wad)
                wad = wad_tool.parse_wad(tmp_wad)
            
            extracted, failed = wad_tool.extract_wad(wad, cache_dir)
            self.report({'INFO'}, f"Extracted {extracted} files ({failed} failed) to temp cache")
            
            # Clean up temporary WAD copy
            if tmp_wad and os.path.isfile(tmp_wad):
                try:
                    os.remove(tmp_wad)
                except OSError:
                    pass
        except Exception as e:
            self.report({'ERROR'}, f"WAD extraction failed: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}


class PROJECT_OT_clean_wad_cache(Operator):
    """Clean all extracted WAD caches to free disk space"""
    bl_idname = "project.clean_wad_cache"
    bl_label = "Clean WAD Cache"
    bl_options = {'REGISTER'}

    def execute(self, context):
        removed = clean_all_wad_caches()
        if removed:
            self.report({'INFO'}, f"Removed {removed} WAD cache(s)")
        else:
            self.report({'INFO'}, "No WAD caches to clean")
        return {'FINISHED'}


# ============================================================================
# Prey Format Operators
# ============================================================================

def _resolve_mat_format(bin_path: str, py_path: str, pref: str) -> tuple:
    """Resolve which materials path/format to use based on preference.

    Returns (path, format_str) e.g. ('/path/to/x.materials.bin', 'bin').
    """
    if pref == 'BIN':
        if bin_path:
            return bin_path, 'bin'
        if py_path:
            return py_path, 'py'
    elif pref == 'PY':
        if py_path:
            return py_path, 'py'
        if bin_path:
            return bin_path, 'bin'
    else:  # AUTO — prefer py
        if py_path:
            return py_path, 'py'
        if bin_path:
            return bin_path, 'bin'
    return '', ''


def _get_prey_dir(materials_path: str) -> str:
    """Return the _prey/ directory path next to the materials file."""
    mat_dir = os.path.dirname(materials_path)
    return os.path.join(mat_dir, "_prey")


def _get_prey_base_name(materials_path: str) -> str:
    """Return the base name for prey files from a materials path."""
    fname = os.path.basename(materials_path)
    return fname.replace('.materials.bin', '')


def _prey_files_exist(materials_path: str) -> bool:
    """Check if .prey.* files already exist for this materials file."""
    prey_dir = _get_prey_dir(materials_path)
    base = _get_prey_base_name(materials_path)
    manifest = os.path.join(prey_dir, f"{base}.prey.manifest")
    return os.path.isfile(manifest)


class PROJECT_OT_convert_to_prey(Operator):
    """Convert .materials.bin to editable .prey.* JSON files"""
    bl_idname = "project.convert_to_prey"
    bl_label = "Convert to .prey"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        mat_path = settings.loaded_materials_path
        if not mat_path or not os.path.isfile(mat_path):
            self.report({'ERROR'}, "No materials file loaded")
            return {'CANCELLED'}

        prey_dir = _get_prey_dir(mat_path)
        base = _get_prey_base_name(mat_path)

        try:
            from . import prey_format
            result = prey_format.bin_to_prey(mat_path, prey_dir, base)
            # Supplement from sibling .py if available (legacy support)
            py_sibling = prey_format.find_py_sibling(prey_dir)
            if py_sibling:
                added = prey_format.supplement_prey_from_py(prey_dir, base, py_sibling)
                if added:
                    self.report({'INFO'}, f"Supplemented {added} map entries from .py sibling")

            settings.prey_dir = prey_dir
            settings.has_prey = True

            count = len(result) - 1  # exclude manifest
            self.report({'INFO'}, f"Created {count} .prey files in _prey/")
        except Exception as e:
            self.report({'ERROR'}, f"Prey conversion failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        return {'FINISHED'}


class PROJECT_OT_rebuild_from_prey(Operator):
    """Rebuild .materials.bin from .prey.* files (overwrites the original)"""
    bl_idname = "project.rebuild_from_prey"
    bl_label = "Rebuild .bin from .prey"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        mat_path = settings.loaded_materials_path
        prey_dir = settings.prey_dir

        if not prey_dir or not os.path.isdir(prey_dir):
            self.report({'ERROR'}, "No .prey directory found")
            return {'CANCELLED'}

        base = _get_prey_base_name(mat_path)
        manifest = os.path.join(prey_dir, f"{base}.prey.manifest")
        if not os.path.isfile(manifest):
            self.report({'ERROR'}, "Prey manifest not found — convert first")
            return {'CANCELLED'}

        # Determine output path — always write .materials.bin
        out_path = mat_path
        if not out_path.endswith('.materials.bin'):
            out_path = os.path.splitext(out_path)[0] + '.materials.bin'

        try:
            from . import prey_format
            prey_format.prey_to_bin(prey_dir, base, out_path)

            # Update loaded path if format changed
            if out_path != mat_path:
                settings.loaded_materials_path = out_path
                settings.loaded_materials_format = 'bin'

            self.report({'INFO'}, f"Rebuilt {os.path.basename(out_path)} from .prey files")
        except Exception as e:
            self.report({'ERROR'}, f"Prey rebuild failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        return {'FINISHED'}


class PROJECT_OT_open_prey_folder(Operator):
    """Open the _prey/ folder in the system file browser"""
    bl_idname = "project.open_prey_folder"
    bl_label = "Open Prey Folder"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        prey_dir = settings.prey_dir

        if not prey_dir or not os.path.isdir(prey_dir):
            self.report({'ERROR'}, "No .prey directory found")
            return {'CANCELLED'}

        import subprocess
        subprocess.Popen(['explorer', os.path.normpath(prey_dir)])
        return {'FINISHED'}


class PROJECT_OT_update_legacy_materials(Operator):
    """Upgrade legacy sampler/switch layout in a .materials.bin using Riot reference data."""
    bl_idname = "project.update_legacy_materials"
    bl_label = "Update Legacy Materials"
    bl_options = {'REGISTER'}

    create_backup: BoolProperty(
        name="Create .bak",
        description="Create a .bak copy before writing upgraded materials",
        default=True,
    )

    def execute(self, context):
        settings = context.scene.project_settings
        target_path = settings.loaded_materials_path
        if not target_path:
            target_path = bpy.path.abspath(settings.materials_update_target_path) if settings.materials_update_target_path else ""
        if not target_path or not os.path.isfile(target_path):
            self.report({'ERROR'}, "No target materials file set")
            return {'CANCELLED'}
        if not target_path.endswith('.materials.bin'):
            self.report({'ERROR'}, "Legacy updater currently supports .materials.bin only")
            return {'CANCELLED'}

        settings.materials_update_target_path = target_path

        reference_path = bpy.path.abspath(settings.materials_update_reference_path) if settings.materials_update_reference_path else ""
        if not reference_path:
            reference_path = _resolve_default_reference_materials(settings)
            if reference_path:
                settings.materials_update_reference_path = reference_path
        if reference_path and not os.path.isfile(reference_path):
            reference_path = ""

        try:
            if self.create_backup:
                backup = target_path + ".bak"
                import shutil
                shutil.copy2(target_path, backup)

            result = update_legacy_materials_bin(target_path, reference_path or None, target_path)
            vfx_msg = ""
            if result.get('vfx_total'):
                vfx_msg = f", vfx {result['vfx_total']} (renamed {result['vfx_fields_renamed']}, .dds→.tex {result['vfx_ext_fixed']})"
            self.report(
                {'INFO'},
                (
                    f"Legacy update: materials {result['materials_total']}, samplers {result['samplers_migrated']}, "
                    f"switches {result['switches_added']}, particles {result['particle_values_updated']}{vfx_msg}, "
                    f"v{result['version_from']}→v{result['version_to']}, "
                    f"raw-preserved {result['raw_preserved_entries']}, "
                    f"header-only={result['header_only_bump']}"
                ),
            )
            print(f"[Legacy Updater] target={target_path}")
            print(f"[Legacy Updater] reference={reference_path}")
            print(f"[Legacy Updater] {result}")
        except Exception as e:
            self.report({'ERROR'}, f"Legacy update failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        return {'FINISHED'}


class PROJECT_OT_pick_legacy_reference(Operator):
    """Pick reference .materials.bin file for legacy updater."""
    bl_idname = "project.pick_legacy_reference"
    bl_label = "Pick Reference Materials Bin"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.project_settings
        settings.materials_update_reference_path = self.filepath
        self.report({'INFO'}, f"Reference set: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PROJECT_OT_pick_legacy_target(Operator):
    """Pick target legacy .materials.bin file to update."""
    bl_idname = "project.pick_legacy_target"
    bl_label = "Pick Target Materials Bin"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.project_settings
        settings.materials_update_target_path = self.filepath
        self.report({'INFO'}, f"Target set: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class VIEW3D_PT_league_tools_legacy_materials(Panel):
    """Legacy materials updater in the League Tools sidebar tab."""
    bl_label = "Legacy Materials Updater"
    bl_idname = "VIEW3D_PT_league_tools_legacy_materials"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_order = 70
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, "project_settings", None)
        if settings is None:
            layout.label(text="Project settings not available", icon='ERROR')
            return

        box = layout.box()
        box.label(text="Reference File (Optional)", icon='FILE')

        row = box.row(align=True)
        row.prop(settings, "materials_update_reference_path", text="")
        row.operator("project.pick_legacy_reference", text="", icon='FILEBROWSER')

        ref_path = bpy.path.abspath(settings.materials_update_reference_path) if settings.materials_update_reference_path else ""
        if ref_path and os.path.isfile(ref_path):
            box.label(text=os.path.basename(ref_path), icon='CHECKMARK')
        else:
            box.label(text="Optional: enable name-matched fallback", icon='INFO')

        box.separator(factor=0.35)
        box.label(text="Target File", icon='FILE')
        target_row = box.row(align=True)
        target_row.prop(settings, "materials_update_target_path", text="")
        target_row.operator("project.pick_legacy_target", text="", icon='FILEBROWSER')

        target = settings.loaded_materials_path
        if not target:
            target = bpy.path.abspath(settings.materials_update_target_path) if settings.materials_update_target_path else ""
        if target and target.endswith('.materials.bin') and os.path.isfile(target):
            box.label(text=f"Target: {os.path.basename(target)}", icon='FILE')
        else:
            box.label(text="Target: pick a .materials.bin file", icon='ERROR')

        act = layout.row(align=True)
        act.scale_y = 1.2
        act.operator("project.update_legacy_materials", text="Update Legacy .bin", icon='FILE_REFRESH')


class PROJECT_OT_save_all_to_prey(Operator):
    """Save current Blender edits into .prey files only (no bin/py rebuild)."""
    bl_idname = "project.save_all_to_prey"
    bl_label = "Save All to .prey"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        mat_path = settings.loaded_materials_path

        if not mat_path or not os.path.isfile(mat_path):
            self.report({'ERROR'}, "No materials file loaded")
            return {'CANCELLED'}

        prey_dir = settings.prey_dir
        if not prey_dir:
            prey_dir = _get_prey_dir(mat_path)
        os.makedirs(prey_dir, exist_ok=True)
        settings.prey_dir = prey_dir

        if not prey_dir or not os.path.isdir(prey_dir):
            self.report({'ERROR'}, "No .prey directory found")
            return {'CANCELLED'}

        base = _get_prey_base_name(mat_path)

        # Bootstrap prey files on first save so Save All always has targets.
        manifest = os.path.join(prey_dir, f"{base}.prey.manifest")
        if not os.path.isfile(manifest):
            try:
                from . import prey_format
                prey_format.bin_to_prey(mat_path, prey_dir, base)
                py_sibling = prey_format.find_py_sibling(prey_dir)
                if py_sibling:
                    prey_format.supplement_prey_from_py(prey_dir, base, py_sibling)
                settings.has_prey = True
            except Exception as e:
                self.report({'ERROR'}, f"Failed to create .prey files: {e}")
                import traceback
                traceback.print_exc()
                return {'CANCELLED'}

        saved = []
        map_changed = False
        mats_changed = 0
        vfx_changed = 0
        vfx_defs_changed = 0

        # 1. Sync sun/fog/bake → .prey.map
        scene_settings = PROJECT_OT_sync_scene_to_prey._read_scene_settings(context)
        if scene_settings:
            try:
                from . import prey_format
                if prey_format.save_prey_map_settings(prey_dir, base, scene_settings):
                    map_changed = True
                    saved.append('map (sun/fog)')
            except Exception as e:
                print(f"[Save All] Warning: sun/fog save failed: {e}")

        # 2. Save material edits → .prey.materials
        try:
            from . import prey_format
            mats_changed = prey_format.save_prey_materials(prey_dir, base)
            if mats_changed:
                saved.append(f'materials ({mats_changed})')
        except Exception as e:
            print(f"[Save All] Warning: material save failed: {e}")

        # 3. Save particle transforms → .prey.vfx
        try:
            from . import prey_format
            vfx_changed = prey_format.save_prey_vfx_transforms(prey_dir, base)
            if vfx_changed:
                saved.append(f'vfx ({vfx_changed})')
        except Exception as e:
            print(f"[Save All] Warning: vfx save failed: {e}")

        # 3b. Save GdsMapObject transforms → .prey.vfx
        mo_changed = 0
        try:
            from . import prey_format
            mo_changed = prey_format.save_prey_gds_transforms(prey_dir, base)
            if mo_changed:
                saved.append(f'map objects ({mo_changed})')
        except Exception as e:
            print(f"[Save All] Warning: map objects save failed: {e}")

        # 4. Save VFX definition edits → .prey.vfx
        try:
            from . import prey_format
            vfx_defs_changed = prey_format.save_prey_vfx_definitions(prey_dir, base)
            if vfx_defs_changed:
                saved.append(f'vfx_defs ({vfx_defs_changed})')
        except Exception as e:
            print(f"[Save All] Warning: vfx definition save failed: {e}")

        if saved:
            self.report({'INFO'}, f"Saved to .prey: {', '.join(saved)}")
        else:
            self.report({'WARNING'},
                        f"Nothing to save (.prey) | map={1 if map_changed else 0}, "
                        f"materials={mats_changed}, vfx={vfx_changed}, vfx_defs={vfx_defs_changed}")
            return {'CANCELLED'}

        return {'FINISHED'}


class PROJECT_OT_sync_scene_to_prey(Operator):
    """Save current Sun/Fog/World settings from Blender scene back to .prey files"""
    bl_idname = "project.sync_scene_to_prey"
    bl_label = "Save Scene Settings to .prey"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.project_settings
        prey_dir = settings.prey_dir
        mat_path = settings.loaded_materials_path

        if not prey_dir or not os.path.isdir(prey_dir):
            self.report({'ERROR'}, "No .prey directory found")
            return {'CANCELLED'}

        base = _get_prey_base_name(mat_path)
        scene_settings = self._read_scene_settings(context)

        if not scene_settings:
            self.report({'WARNING'}, "No sun/fog/world properties found in scene")
            return {'CANCELLED'}

        try:
            from . import prey_format
            if prey_format.save_prey_map_settings(prey_dir, base, scene_settings):
                self.report({'INFO'}, "Saved scene settings to .prey.map")
            else:
                self.report({'WARNING'}, "No .prey.map file found to update")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save scene settings: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        return {'FINISHED'}

    @staticmethod
    def _read_scene_settings(context) -> dict:
        """Read sun/fog/world properties from the Blender scene."""
        s = {}

        # --- Sun light ---
        for obj in context.scene.objects:
            if obj.type == 'LIGHT' and obj.data.type == 'SUN' and obj.name.startswith("MapSun"):
                sun_dir = obj.get("sun_direction_league")
                if sun_dir:
                    s["sun_direction"] = list(sun_dir)
                sun_col = obj.get("sun_color")
                if sun_col:
                    s["sun_color"] = list(sun_col)
                break

        # --- World ---
        world = context.scene.world
        if world:
            if "sky_light_color" in world:
                s["sky_light_color"] = list(world["sky_light_color"])
            if "sky_light_scale" in world:
                s["sky_light_scale"] = float(world["sky_light_scale"])
            if "horizon_color" in world:
                s["horizon_color"] = list(world["horizon_color"])
            if "ground_color" in world:
                s["ground_color"] = list(world["ground_color"])
            if "lightmap_color_scale" in world:
                s["lightmap_color_scale"] = float(world["lightmap_color_scale"])
            if "fog_enabled" in world:
                s["fog_enabled"] = bool(world["fog_enabled"])
            if "fog_color_value" in world:
                s["fog_color"] = list(world["fog_color_value"])
            if "fog_start_end" in world:
                s["fog_start_end"] = list(world["fog_start_end"])
            if "fog_alternate_color" in world:
                s["fog_alternate_color"] = list(world["fog_alternate_color"])
            # Bake properties
            if "bake_light_grid_size" in world:
                s["light_grid_size"] = int(world["bake_light_grid_size"])
            if "bake_light_grid_file" in world:
                s["light_grid_file"] = str(world["bake_light_grid_file"])
            if "bake_rma_light_grid_texture" in world:
                s["rma_light_grid_texture"] = str(world["bake_rma_light_grid_texture"])
            if "bake_rma_light_grid_intensity_scale" in world:
                s["rma_light_grid_intensity_scale"] = float(world["bake_rma_light_grid_intensity_scale"])
            if "bake_light_grid_fullbright_intensity" in world:
                s["light_grid_fullbright"] = float(world["bake_light_grid_fullbright_intensity"])
            # LightingV2
            if "lighting_v2_min_env_color_contribution" in world:
                s["min_env_color_contribution"] = float(world["lighting_v2_min_env_color_contribution"])

        return s


# ============================================================================
# Create Project
# ============================================================================

def _get_source_map_items(self, context):
    """EnumProperty callback: list available source maps from Riot install."""
    items = []
    for map_id, display in sorted(MAP_NAMES.items(), key=lambda x: x[0]):
        items.append((map_id, f"{display} ({map_id})", f"Use {display} as source"))
    return items or [("NONE", "No maps found", "")]


def _get_variant_items(self, context):
    """EnumProperty callback: list variants available for the chosen source map."""
    items = []
    settings = context.scene.project_settings
    league_path = bpy.path.abspath(settings.league_install)
    if not league_path:
        league_path = find_league_install()
    map_id = self.source_map
    if league_path and map_id and map_id != "NONE":
        try:
            variants = get_riot_wad_variants(league_path, map_id)
            for v in variants:
                vname = v['name']
                items.append((vname, vname, f"Variant: {vname}"))
        except Exception:
            pass
    return items or [("base", "base", "Default base variant")]


class PROJECT_OT_create_project(Operator):
    """Create a new League map project with customizable content"""
    bl_idname = "project.create_project"
    bl_label = "Create Project"
    bl_options = {'REGISTER', 'UNDO'}

    project_name: StringProperty(
        name="Project Name",
        description="Name for the new project folder",
        default="MyMapProject",
    )

    project_folder: StringProperty(
        name="Location",
        description="Parent folder where the project will be created",
        subtype='DIR_PATH',
        default="",
    )

    project_type: EnumProperty(
        name="Project Type",
        description="What content to include",
        items=[
            ('EMPTY', "Empty",
             "Empty mapgeo (no meshes). Materials.bin cleaned of material definitions "
             "— keeps particles, VFX, containers, map settings (sun, fog, lighting)"),
            ('SEMI', "Semi",
             "Normal mapgeo and materials.bin copied from source. "
             "No assets or data folder"),
            ('FULLY', "Full",
             "Complete project with all files: mapgeo, materials.bin, "
             "assets (textures), data and levels folders"),
        ],
        default='EMPTY',
    )

    source_map: EnumProperty(
        name="Source Map",
        description="Which League map to use as source",
        items=_get_source_map_items,
    )

    source_variant: EnumProperty(
        name="Variant",
        description="Which map variant to use as source",
        items=_get_variant_items,
    )

    def invoke(self, context, event):
        # Auto-detect League install if needed
        settings = context.scene.project_settings
        if not settings.league_install:
            detected = find_league_install()
            if detected:
                settings.league_install = detected
                settings.league_detected = True
        # Default project folder to something sensible
        if not self.project_folder:
            self.project_folder = bpy.path.abspath(settings.project_folder) or ""
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout

        # Info header
        box = layout.box()
        box.label(text="New League Map Project", icon='FILE_NEW')

        col = layout.column(align=True)
        col.prop(self, "project_name")
        col.prop(self, "project_folder")

        layout.separator()
        layout.prop(self, "project_type")

        # Description of selected type
        desc_box = layout.box()
        if self.project_type == 'EMPTY':
            desc_box.label(text="Copies mapgeo + materials.bin from source.", icon='INFO')
            desc_box.label(text="No asset textures or level data.")
            desc_box.label(text="Replace geometry from Blender, then export.")
        elif self.project_type == 'SEMI':
            desc_box.label(text="Copies mapgeo + materials.bin from source.", icon='INFO')
            desc_box.label(text="No asset textures or level data copied.")
        else:
            desc_box.label(text="Full copy: mapgeo, materials, assets,", icon='INFO')
            desc_box.label(text="data and levels folders from source WAD.")

        layout.separator()
        layout.prop(self, "source_map")
        layout.prop(self, "source_variant")

    @classmethod
    def poll(cls, context):
        settings = context.scene.project_settings
        league_path = bpy.path.abspath(settings.league_install) if settings.league_install else ""
        return bool(league_path) or bool(find_league_install())

    def execute(self, context):
        import shutil

        settings = context.scene.project_settings
        league_path = bpy.path.abspath(settings.league_install)
        if not league_path:
            league_path = find_league_install()
        if not league_path:
            self.report({'ERROR'}, "League installation not found. Set it in Project Manager.")
            return {'CANCELLED'}

        if not self.project_name.strip():
            self.report({'ERROR'}, "Project name is empty")
            return {'CANCELLED'}

        parent = bpy.path.abspath(self.project_folder)
        if not parent or not os.path.isdir(parent):
            self.report({'ERROR'}, f"Location folder does not exist: {parent}")
            return {'CANCELLED'}

        project_dir = os.path.join(parent, self.project_name.strip())
        if os.path.exists(project_dir):
            self.report({'ERROR'}, f"Folder already exists: {project_dir}")
            return {'CANCELLED'}

        map_id = self.source_map
        variant_name = self.source_variant

        # ── Ensure WAD cache ──
        cache_dir = _ensure_riot_wad_cache(league_path, map_id)
        if not cache_dir:
            self.report({'ERROR'}, f"Failed to extract Riot WAD for {map_id}")
            return {'CANCELLED'}

        # Locate source files in cache
        map_id_lower = map_id.lower()
        mapgeo_dir = os.path.join(cache_dir, "data", "maps", "mapgeometry")
        src_mapgeo = ""
        src_materials = ""
        if os.path.isdir(mapgeo_dir):
            for d in os.listdir(mapgeo_dir):
                sub = os.path.join(mapgeo_dir, d)
                if not os.path.isdir(sub):
                    continue
                mg = os.path.join(sub, f"{variant_name}.mapgeo")
                mb = os.path.join(sub, f"{variant_name}.materials.bin")
                if os.path.isfile(mg):
                    src_mapgeo = mg
                if os.path.isfile(mb):
                    src_materials = mb
                if src_mapgeo and src_materials:
                    break

        if not src_mapgeo and not src_materials:
            self.report({'ERROR'},
                        f"Source files not found for variant '{variant_name}' in {map_id}")
            return {'CANCELLED'}

        # ── Create project folder structure ──
        # Add the map subfolder (e.g. MyProject/Map11/) so the project
        # validator finds it via its WAD-subfolder scan.
        map_id_title = map_id[0].upper() + map_id[1:] if map_id else map_id
        map_root = os.path.join(project_dir, map_id_title)
        try:
            os.makedirs(map_root, exist_ok=True)
        except OSError as e:
            self.report({'ERROR'}, f"Cannot create folder: {e}")
            return {'CANCELLED'}

        # Derive the inner mapgeo path: <Map>/data/maps/mapgeometry/<mapid_lower>/
        inner_mapgeo_dir = os.path.join(
            map_root, "data", "maps", "mapgeometry", map_id_lower)
        os.makedirs(inner_mapgeo_dir, exist_ok=True)

        dst_mapgeo = os.path.join(inner_mapgeo_dir, f"{variant_name}.mapgeo")
        dst_materials = os.path.join(inner_mapgeo_dir, f"{variant_name}.materials.bin")

        created_files = []

        # ────────────────────── EMPTY ──────────────────────
        if self.project_type == 'EMPTY':
            # Copy mapgeo + materials.bin as-is to preserve all structural
            # data (bucket grids, render regions, materials referenced by
            # meshes). The map loads identically to source but without
            # asset textures — user replaces geometry from Blender.
            if src_mapgeo and os.path.isfile(src_mapgeo):
                shutil.copy2(src_mapgeo, dst_mapgeo)
                created_files.append("mapgeo")
            if src_materials and os.path.isfile(src_materials):
                shutil.copy2(src_materials, dst_materials)
                created_files.append("materials.bin")

        # ────────────────────── SEMI ──────────────────────
        elif self.project_type == 'SEMI':
            if src_mapgeo and os.path.isfile(src_mapgeo):
                shutil.copy2(src_mapgeo, dst_mapgeo)
                created_files.append("mapgeo")
            if src_materials and os.path.isfile(src_materials):
                shutil.copy2(src_materials, dst_materials)
                created_files.append("materials.bin")

        # ────────────────────── FULLY ──────────────────────
        elif self.project_type == 'FULLY':
            # Copy entire data/ tree from cache
            src_data = os.path.join(cache_dir, "data")
            dst_data = os.path.join(map_root, "data")
            if os.path.isdir(src_data):
                shutil.copytree(src_data, dst_data, dirs_exist_ok=True)
                created_files.append("data/")

            # Copy assets/ tree from cache
            src_assets = os.path.join(cache_dir, "assets")
            dst_assets = os.path.join(map_root, "assets")
            if os.path.isdir(src_assets):
                shutil.copytree(src_assets, dst_assets, dirs_exist_ok=True)
                created_files.append("assets/")

            # Extract LEVELS WAD if available
            levels_cache = _ensure_riot_levels_wad_cache(league_path, map_id)
            if levels_cache and os.path.isdir(levels_cache):
                # LEVELS WAD has data/levels/<mapid>/ and possibly assets/
                src_levels_data = os.path.join(levels_cache, "data")
                if os.path.isdir(src_levels_data):
                    shutil.copytree(src_levels_data, dst_data, dirs_exist_ok=True)
                    created_files.append("levels data/")
                src_levels_assets = os.path.join(levels_cache, "assets")
                if os.path.isdir(src_levels_assets):
                    shutil.copytree(src_levels_assets, dst_assets, dirs_exist_ok=True)
                    created_files.append("levels assets/")

        # ── Point project manager at new project ──
        settings.project_folder = project_dir
        try:
            bpy.ops.project.validate_project()
        except RuntimeError:
            pass

        map_display = MAP_NAMES.get(map_id, map_id)
        self.report({'INFO'},
                     f"Created {self.project_type} project '{self.project_name}' "
                     f"from {map_display}/{variant_name}: {', '.join(created_files)}")
        return {'FINISHED'}





class PROJECT_UL_variant_list(UIList):
    """UIList for map variants."""
    bl_idname = "PROJECT_UL_variant_list"
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Name with status icons
            name_row = row.row(align=True)
            name_row.label(text=item.name)
            
            # Status indicators
            if item.has_mapgeo:
                row.label(text="", icon='MESH_DATA')
            else:
                row.label(text="", icon='ERROR')
            
            if item.has_materials:
                row.label(text="", icon='MATERIAL')
            else:
                row.label(text="", icon='GHOST_DISABLED')
        
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name)


class VIEW3D_PT_project_manager(Panel):
    """Project Manager panel in the LoL Mapgeo sidebar."""
    bl_label = "Project Manager"
    bl_idname = "VIEW3D_PT_project_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_order = 0  # Show at top

    def draw_header(self, context):
        layout = self.layout
        icon_id = 0
        try:
            import sys
            addon_module = sys.modules.get(__package__)
            if addon_module and hasattr(addon_module, 'get_custom_icon_id'):
                icon_id = int(addon_module.get_custom_icon_id("mapgeo_addon_icon") or 0)
        except Exception:
            icon_id = 0

        if icon_id > 0:
            layout.label(text="", icon_value=icon_id)
        else:
            layout.label(text="", icon='WORLD_DATA')
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.project_settings
        
        # ── Project Folder ──
        box = layout.box()
        box.label(text="Project Folder", icon='FILE_FOLDER')
        
        row = box.row(align=True)
        row.prop(settings, "project_folder", text="")
        row.operator("project.open_project", text="", icon='FILEBROWSER')
        
        # Create Project button
        row = box.row(align=True)
        row.operator("project.create_project", text="Create Project", icon='FILE_NEW')
        
        if settings.project_folder:
            row = box.row(align=True)
            row.operator("project.validate_project", text="Scan", icon='VIEWZOOM')
            
            if settings.is_valid_project:
                row.label(text="", icon='CHECKMARK')
            elif settings.status_message and "error" in settings.status_message.lower():
                row.label(text="", icon='ERROR')
        
        # ── League Installation ──
        box = layout.box()
        box.label(text="League Installation", icon='DISC')
        
        row = box.row(align=True)
        row.prop(settings, "league_install", text="")
        row.operator("project.detect_league", text="", icon='VIEWZOOM')
        
        if settings.league_detected:
            box.label(text="Auto-detected", icon='CHECKMARK')
        elif settings.league_install:
            if os.path.isdir(bpy.path.abspath(settings.league_install)):
                box.label(text="Manual path set", icon='CHECKMARK')
            else:
                box.label(text="Path not found!", icon='ERROR')
        
        box.prop(settings, "use_riot_base")
        
        # ── Exclude Keyword ──
        row = box.row(align=True)
        row.prop(settings, "use_exclude_keyword", text="")
        sub = row.row(align=True)
        sub.enabled = settings.use_exclude_keyword
        sub.prop(settings, "exclude_keyword", text="Exclude")
        
        # Clean WAD cache button
        row = box.row(align=True)
        row.operator("project.clean_wad_cache", text="Clean WAD Cache", icon='TRASH')
        
        # ── Map Variants ──
        if settings.is_valid_project:
            box = layout.box()
            header_row = box.row()
            header_row.label(text="Map Variants", icon='WORLD')
            if settings.project_map_id:
                map_display = MAP_NAMES.get(settings.project_map_id, 
                              MAP_NAMES.get("Map" + settings.project_map_id.replace("map", ""), 
                              settings.project_map_id))
                header_row.label(text=f"({map_display})")
            
            if settings.map_variants:
                box.template_list(
                    "PROJECT_UL_variant_list", "",
                    settings, "map_variants",
                    settings, "selected_variant_index",
                    rows=min(len(settings.map_variants), 8),
                    maxrows=12,
                )
                
                # Show selected variant details
                idx = settings.selected_variant_index
                if 0 <= idx < len(settings.map_variants):
                    variant = settings.map_variants[idx]
                    detail_box = box.box()
                    
                    if variant.has_mapgeo:
                        detail_box.label(text=f"Mapgeo: {os.path.basename(variant.mapgeo_path)}", icon='MESH_DATA')
                    else:
                        detail_box.label(text="Mapgeo: (from Riot base)" if settings.use_riot_base else "Mapgeo: MISSING", 
                                        icon='INFO' if settings.use_riot_base else 'ERROR')
                    
                    if variant.has_materials:
                        mat_label = os.path.basename(variant.materials_path)
                        detail_box.label(text=f"Materials: {mat_label} [{variant.materials_format}]", icon='MATERIAL')
                    else:
                        detail_box.label(text="Materials: (from Riot base)" if settings.use_riot_base else "Materials: MISSING",
                                        icon='INFO' if settings.use_riot_base else 'ERROR')
                    

                
                # Load / Reload buttons
                action_row = box.row(align=True)
                action_row.scale_y = 1.5
                action_row.operator("project.load_map", text="Load Map", icon='IMPORT')
                
                if settings.loaded_variant:
                    action_row.operator("project.reload_map", text="", icon='FILE_REFRESH')

            else:
                box.label(text="No map variants found", icon='INFO')
        
        # ── Asset Summary ──
        if settings.asset_summary:
            box = layout.box()
            box.label(text="Assets", icon='ASSET_MANAGER')
            
            col = box.column(align=True)
            for asset in settings.asset_summary:
                if asset.count > 0:
                    col.label(text=f"{asset.extension}: {asset.count} files")
        
        # ── Export ──
        if settings.loaded_variant:
            box = layout.box()
            box.label(text="Export", icon='EXPORT')
            
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(settings, "export_mapgeo", toggle=True, icon='MESH_DATA')
            row.prop(settings, "export_materials", toggle=True, icon='MATERIAL')
            
            col.prop(settings, "export_version", text="Mapgeo Version")
            
            # Show target paths
            detail = box.column(align=True)
            detail.scale_y = 0.75
            if settings.export_mapgeo and settings.loaded_mapgeo_path:
                detail.label(text=f"→ {os.path.basename(settings.loaded_mapgeo_path)}", icon='FILE')
            if settings.export_materials and settings.loaded_materials_path:
                detail.label(text=f"→ {os.path.basename(settings.loaded_materials_path)}", icon='FILE')
            
            box.separator(factor=0.5)
            
            box.operator("project.cleanup_materials", text="Cleanup Unused Materials", icon='BRUSH_DATA')
            
            # ── Prey Format ──
            if settings.loaded_materials_path:
                box.separator(factor=0.5)
                prey_box = box.box()
                prey_header = prey_box.row()
                prey_header.label(text=".prey Format", icon='FILE_TEXT')
                
                if settings.has_prey:
                    prey_header.label(text="", icon='CHECKMARK')
                    prey_box.prop(settings, "use_prey_on_export")
                    
                    prey_row = prey_box.row(align=True)
                    prey_row.operator("project.convert_to_prey", text="Re-convert", icon='FILE_REFRESH')
                    prey_row.operator("project.open_prey_folder", text="", icon='FILEBROWSER')
                    
                    save_row = prey_box.row(align=True)
                    save_row.scale_y = 1.3
                    save_row.operator("project.save_all_to_prey",
                                      text="Save All to .prey", icon='FILE_TICK')
                else:
                    prey_box.operator("project.convert_to_prey", text="Convert to .prey", icon='FILE_TEXT')
            
            box.separator(factor=0.5)
            
            export_row = box.row(align=True)
            export_row.scale_y = 1.5
            export_row.operator("project.export_all", text="Export to Project", icon='EXPORT')
        
        # ── Status ──
        if settings.status_message:
            box = layout.box()
            if settings.loaded_variant:
                box.label(text=f"Loaded: {settings.loaded_variant}", icon='CHECKMARK')
            else:
                box.label(text=settings.status_message, icon='INFO')


# ============================================================================
# Registration
# ============================================================================

classes = (
    ProjectMapVariant,
    ProjectAssetSummary,
    ProjectSettings,
    PROJECT_OT_detect_league,
    PROJECT_OT_validate_project,
    PROJECT_OT_load_map,
    PROJECT_OT_reload_map,
    PROJECT_OT_open_project,
    PROJECT_OT_create_project,
    PROJECT_OT_export_mapgeo,
    PROJECT_OT_export_materials,
    PROJECT_OT_cleanup_materials,
    PROJECT_OT_export_all,
    PROJECT_OT_extract_riot_wad,
    PROJECT_OT_clean_wad_cache,
    PROJECT_OT_convert_to_prey,
    PROJECT_OT_rebuild_from_prey,
    PROJECT_OT_open_prey_folder,
    PROJECT_OT_update_legacy_materials,
    PROJECT_OT_pick_legacy_reference,
    PROJECT_OT_pick_legacy_target,
    PROJECT_OT_save_all_to_prey,
    PROJECT_OT_sync_scene_to_prey,
    PROJECT_UL_variant_list,
    VIEW3D_PT_project_manager,
    VIEW3D_PT_league_tools_legacy_materials,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.project_settings = PointerProperty(type=ProjectSettings)
    
    # Clean up old WAD caches left in stale Blender temp directories
    _cleanup_stale_temp_caches()
    
    print("[Project Manager] Registered")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, 'project_settings'):
        del bpy.types.Scene.project_settings
    print("[Project Manager] Unregistered")
