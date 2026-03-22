"""
League Tools – Map Porter for Blender

Ports one League map to another by:
  1. Copying + renaming the .mapgeo file
  2. Merging materials.bin files:
     - Takes ALL entries from SOURCE in their original order
     - Replaces the mapContainer entry in-place with TARGET's mapContainer
       (so the game recognises the file as the target map slot)
  3. (Optional) Patching map11.bin – replaces the target MapSkin's fields
     with the source MapSkin's fields so that the engine activates the
     source map's particles, grass-tint, VFX links, and sound banks.
"""

import os
import re
import shutil

import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, BoolProperty, EnumProperty

from . import propertybin_parser
from . import mapgeo_parser

# ============================================================================
# Constants
# ============================================================================

# Type hash for mapContainer — the only entry swapped from target
HASH_MAP_CONTAINER = 0xdde8c114

# Type hash for MapPlaceableContainer
HASH_MPC = 0xb25c0a3f

# Embedded class hash for MapParticle placement items inside MPCs.
# These reference VFX definitions via link fields.  All 15 unique VFX
# targets from milkshake's 1082 items resolve in the merged file, so
# they MUST be kept — they are the snow particle placements.
CLASS_MAP_PARTICLE_ALT = "0x1f1f50f2"

# Known type hashes for reporting
_TYPE_LABELS = {
    0xff9d3409: "StaticMaterialDef",
    0xb25c0a3f: "MapPlaceableContainer",
    0x1f1f50f2: "MapParticle (alt)",
    0x45cd899f: "VfxSystemDefinitionData",
    0xdde8c114: "mapContainer",
    0xcd19ef3c: "MapSkin",
}

# mapContainer field hashes
MC_FIELD_CHUNKS  = "0x5e0e1da3"   # type 134 (map) – chunk references
MC_FIELD_GEO_PATH = "0xcc5e808a"  # type 16 – geometry path string

# ── MapSkin constants ──
# Type hash for MapSkin entries in map11.bin
HASH_MAP_SKIN = 0xcd19ef3c

# MapSkin field hashes
MAPSKIN_NAME       = "0x8d39bde6"   # type 16 – skin name (e.g. "Milkshake_SRS")
MAPSKIN_GEO_PATH   = "0x960efd81"   # type 16 – geometry path (e.g. "Maps/MapGeometry/Map11/Milkshake_SRS")

# ── Music override constants ──
# Type hash for MapAudioMusicOverride entries in map11.bin
HASH_MUSIC_OVERRIDE = 0xf2b58198
# Field: list of sound bank definitions (type 129)
MUSIC_FIELD_BANKS   = "0xf8f29f92"
# Field: condition/mutator link (type 17) – determines when the override activates
MUSIC_FIELD_COND    = "0xe4ba733d"


# ============================================================================
# Helpers
# ============================================================================

def _type_hash_int(entry: dict) -> int:
    """Return the type_hash of a bin entry as an integer."""
    th = entry.get("type_hash", "0x0")
    if isinstance(th, str):
        return int(th, 16) if th.startswith("0x") else int(th)
    return int(th)


def _is_map_container(entry: dict) -> bool:
    """True if the entry is a mapContainer."""
    return _type_hash_int(entry) == HASH_MAP_CONTAINER


def _is_mpc(entry: dict) -> bool:
    """True if the entry is a MapPlaceableContainer."""
    return _type_hash_int(entry) == HASH_MPC


def _strip_particle_alt_from_mpc(entry: dict) -> int:
    """
    Remove embedded 0x1f1f50f2 (MapParticle alt) items from an MPC entry.

    MPC entries have a single field (type 134 = map) whose ``pairs`` list
    contains ``{key, value}`` dicts.  Each ``value`` is an embedded struct
    with a ``class_hash``.  We filter out pairs whose ``class_hash``
    matches ``CLASS_MAP_PARTICLE_ALT``.

    Returns the number of pairs removed.
    """
    removed = 0
    for field in entry.get("fields", []):
        if field.get("type") != 134:
            continue
        pairs = field.get("pairs")
        if not isinstance(pairs, list):
            continue
        original_len = len(pairs)
        field["pairs"] = [
            p for p in pairs
            if not (
                isinstance(p, dict)
                and isinstance(p.get("value"), dict)
                and p["value"].get("class_hash") == CLASS_MAP_PARTICLE_ALT
            )
        ]
        removed += original_len - len(field["pairs"])
    return removed


def _basename_no_ext(filepath: str, ext: str) -> str:
    """
    Strip the given extension (case-insensitive) from a filename.
    e.g. 'sodapop_srs.materials.bin' → 'sodapop_srs'
    """
    name = os.path.basename(filepath)
    low = name.lower()
    if low.endswith(ext.lower()):
        return name[: len(name) - len(ext)]
    # Fallback: strip last extension
    return os.path.splitext(name)[0]


# Regex to match Characters/xxx/Skins/SkinN paths
_SKIN_PATH_RE = re.compile(r'(Characters/[^/]+/Skins/Skin)(\d+)')


def _collect_all_strings(obj, depth=0):
    """Recursively collect all string values from a nested structure."""
    strings = []
    if depth > 20:
        return strings
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strings.extend(_collect_all_strings(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            strings.extend(_collect_all_strings(item, depth + 1))
    return strings


def _extract_skin_refs(entry):
    """
    Extract character skin references from an MPC entry.
    Returns dict of {character_name: set of skin_numbers}.
    """
    refs = {}
    for s in _collect_all_strings(entry):
        m = _SKIN_PATH_RE.search(s)
        if m:
            char_name = s.split('/')[1]  # Characters/<name>/Skins/SkinN
            skin_num = int(m.group(2))
            refs.setdefault(char_name, set()).add(skin_num)
    return refs


def _build_skin_mapping(src_entries, tgt_only_entries):
    """
    Build a skin mapping from target-only MPC skins → source MPC skins.

    For each character that appears in source MPCs AND target-only MPCs
    with *different* skin numbers, builds a sorted mapping:
    target_skin_N → source_skin_N (paired by sorted order).

    Returns:
      skin_map: dict {character_name: {old_skin_num: new_skin_num}}
      report: list of human-readable strings describing the mapping
    """
    # Collect skin refs from all source MPC entries
    src_skins = {}  # char_name → set of skin nums
    for e in src_entries:
        if _is_mpc(e):
            for char, skins in _extract_skin_refs(e).items():
                src_skins.setdefault(char, set()).update(skins)

    # Collect skin refs from target-only MPC entries
    tgt_skins = {}
    for e in tgt_only_entries:
        if _is_mpc(e):
            for char, skins in _extract_skin_refs(e).items():
                tgt_skins.setdefault(char, set()).update(skins)

    skin_map = {}
    report = []

    for char in sorted(tgt_skins.keys()):
        tgt_set = tgt_skins[char]
        src_set = src_skins.get(char, set())

        # Only characters that differ need mapping
        if tgt_set == src_set:
            continue

        # Find skins that are in target-only but NOT in source
        extra_tgt = sorted(tgt_set - src_set)
        # Find skins that are in source but NOT in target-only
        extra_src = sorted(src_set - tgt_set)

        if not extra_tgt or not extra_src:
            continue

        if len(extra_tgt) != len(extra_src):
            report.append(
                f"  WARNING: {char} skin count mismatch "
                f"(target-only={extra_tgt}, source={extra_src}) — skipped"
            )
            continue

        # Pair by sorted order
        char_map = {}
        for old, new in zip(extra_tgt, extra_src):
            char_map[old] = new
        skin_map[char] = char_map
        report.append(f"  {char}: {char_map}")

    return skin_map, report


def _apply_skin_mapping(obj, skin_map, depth=0):
    """
    Recursively walk a data structure and replace character skin paths
    according to skin_map.

    skin_map: {character_name: {old_skin_num: new_skin_num}}

    Returns the number of replacements made.
    """
    if depth > 30:
        return 0
    count = 0

    if isinstance(obj, dict):
        for key in list(obj.keys()):
            val = obj[key]
            if isinstance(val, str):
                m = _SKIN_PATH_RE.search(val)
                if m:
                    char_name = val.split('/')[1]
                    skin_num = int(m.group(2))
                    if char_name in skin_map and skin_num in skin_map[char_name]:
                        new_num = skin_map[char_name][skin_num]
                        obj[key] = _SKIN_PATH_RE.sub(
                            lambda mm: mm.group(1) + str(new_num), val
                        )
                        count += 1
            else:
                count += _apply_skin_mapping(val, skin_map, depth + 1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                m = _SKIN_PATH_RE.search(item)
                if m:
                    char_name = item.split('/')[1]
                    skin_num = int(m.group(2))
                    if char_name in skin_map and skin_num in skin_map[char_name]:
                        new_num = skin_map[char_name][skin_num]
                        obj[i] = _SKIN_PATH_RE.sub(
                            lambda mm: mm.group(1) + str(new_num), item
                        )
                        count += 1
            else:
                count += _apply_skin_mapping(item, skin_map, depth + 1)
    return count


def _derive_map_name_from_materials(materials_path: str) -> str:
    """
    Derive the map base name from a materials file path.
    e.g. 'sodapop_srs.materials.bin' → 'sodapop_srs'
    """
    name = os.path.basename(materials_path)
    for suffix in (".materials.bin",):
        if name.lower().endswith(suffix):
            return name[: len(name) - len(suffix)]
    # Fallback
    return os.path.splitext(os.path.splitext(name)[0])[0]


def _extract_mapgeo_material_names(mapgeo_path: str) -> set[str]:
    """Extract all material names referenced by primitives in a .mapgeo file."""
    names = set()
    if not mapgeo_path or not os.path.isfile(mapgeo_path):
        return names

    parser = mapgeo_parser.MapgeoParser()
    mapgeo = parser.read(mapgeo_path)
    for mesh in mapgeo.meshes:
        for prim in mesh.primitives:
            mat = (prim.material or "").strip()
            if mat:
                names.add(mat)
    return names


# ============================================================================
# MapSkin helpers
# ============================================================================

def _get_mapskin_field(entry: dict, name_hash: str):
    """Return the field dict with the given name_hash, or None."""
    for f in entry.get("fields", []):
        if f.get("name_hash") == name_hash:
            return f
    return None


def _get_mapskin_field_value(entry: dict, name_hash: str, default=None):
    """Return the *value* of the field with the given name_hash."""
    f = _get_mapskin_field(entry, name_hash)
    if f is not None:
        return f.get("value", default)
    return default


def _is_map_skin(entry: dict) -> bool:
    """True if the entry is a MapSkin."""
    return _type_hash_int(entry) == HASH_MAP_SKIN


def _find_map_skins_by_geo_path(entries: list, map_name: str) -> list:
    """
    Return all MapSkin entries whose geometry-path field contains *map_name*
    (case-insensitive substring match).
    """
    results = []
    needle = map_name.lower()
    for e in entries:
        if not _is_map_skin(e):
            continue
        geo = _get_mapskin_field_value(e, MAPSKIN_GEO_PATH, "")
        if needle in geo.lower():
            results.append(e)
    return results


import copy as _copy


def _find_music_override(entries: list, map_name: str):
    """
    Find the music override entry (type 0xf2b58198) whose sound bank
    names contain *map_name* (case-insensitive).

    Each override's ``0xf8f29f92`` field lists sound bank structs.
    We check the name string (field ``0x8d39bde6``) of each bank
    for a match.

    Returns the entry dict, or None.
    """
    needle = map_name.lower().replace("_srs", "")  # e.g. "milkshake"
    for e in entries:
        if _type_hash_int(e) != HASH_MUSIC_OVERRIDE:
            continue
        # Check the sound bank names inside field 0xf8f29f92
        banks_field = None
        for f in e.get("fields", []):
            if f.get("name_hash") == MUSIC_FIELD_BANKS:
                banks_field = f
                break
        if not banks_field:
            continue
        # Scan bank names for the map keyword
        for bank in banks_field.get("values", []):
            if not isinstance(bank, dict):
                continue
            for bf in bank.get("fields", []):
                if bf.get("name_hash") == "0x8d39bde6" and bf.get("type") == 16:
                    bank_name = bf.get("value", "")
                    if needle in bank_name.lower():
                        return e
    return None


def _swap_music_override(entries: list, source_map_name: str,
                         target_map_name: str) -> dict:
    """
    Swap the condition/activation links between source and target music
    overrides so the game loads the **source's** music banks when the
    **target** season is active.

    Each MapAudioMusicOverride (type 0xf2b58198) has:
      • ``0xf8f29f92`` – list of Wwise sound bank definitions
      • ``0xe4ba733d`` – condition/mutator link (determines when it activates)

    Instead of replacing the heavy bank definitions (which can cause Wwise
    state mismatches), we swap only the lightweight condition links:
      • Source override gets target's condition → activates on target season
      • Target override gets source's condition → dormant (source season over)

    This way the source's bank definitions stay intact (correct file paths,
    event registrations, Wwise states) and simply activate at the right time.

    Returns a result dict with keys:
      - swapped: bool
      - source_bank: str (first bank name from source)
      - target_bank: str (first bank name from target)
      - error: str (only on failure)
    """
    src_override = _find_music_override(entries, source_map_name)
    tgt_override = _find_music_override(entries, target_map_name)

    if not src_override:
        return {"swapped": False,
                "error": f"No music override found for source '{source_map_name}'"}
    if not tgt_override:
        return {"swapped": False,
                "error": f"No music override found for target '{target_map_name}'"}
    if src_override is tgt_override:
        return {"swapped": False,
                "error": "Source and target resolved to the same music override"}

    # Find the condition link fields
    src_cond = None
    tgt_cond = None
    for f in src_override.get("fields", []):
        if f.get("name_hash") == MUSIC_FIELD_COND:
            src_cond = f
            break
    for f in tgt_override.get("fields", []):
        if f.get("name_hash") == MUSIC_FIELD_COND:
            tgt_cond = f
            break

    if not src_cond or not tgt_cond:
        return {"swapped": False,
                "error": "Missing condition link field on music override(s)"}

    # Get descriptive names for reporting
    def _first_bank_name(override):
        for f in override.get("fields", []):
            if f.get("name_hash") == MUSIC_FIELD_BANKS:
                for bank in f.get("values", []):
                    if isinstance(bank, dict):
                        for bf in bank.get("fields", []):
                            if bf.get("name_hash") == "0x8d39bde6":
                                return bf.get("value", "?")
        return "?"

    source_bank_name = _first_bank_name(src_override)
    target_bank_name = _first_bank_name(tgt_override)

    # Swap the condition link values
    src_cond["value"], tgt_cond["value"] = tgt_cond["value"], src_cond["value"]

    return {
        "swapped": True,
        "source_bank": source_bank_name,
        "target_bank": target_bank_name,
    }


def merge_map11_bin(
    map11_path: str,
    source_map_name: str,
    target_map_name: str,
    output_path: str,
    swap_music: bool = False,
) -> dict:
    """
    Patch the MapSkin entries in *map11.bin* so that every MapSkin
    currently pointing at the **target** map slot receives the **source**
    map's skin settings (particle lists, VFX links, GrassTint, etc.).

    Fields that are **kept** from the target:
      • ``0x8d39bde6``  – skin name  (e.g. "Sodapop_SRS" / "SR_Seasonal_Map")
      • ``0x960efd81``  – geometry path  (our merged files live there)

    All other fields are deep-copied from the source MapSkin.

    Returns a summary dict.
    """
    data = propertybin_parser.parse_bin(map11_path)
    entries = data.get("entries", [])

    # ── Find source skin (by geometry-path containing source name) ──
    src_skins = _find_map_skins_by_geo_path(entries, source_map_name)
    if not src_skins:
        return {"error": f"No MapSkin found for source '{source_map_name}'"}
    # Use the first match (the primary skin for that map)
    src_skin = src_skins[0]
    src_skin_name = _get_mapskin_field_value(src_skin, MAPSKIN_NAME, "?")

    # ── Find target skins (all MapSkins whose geo-path matches target) ──
    tgt_skins = _find_map_skins_by_geo_path(entries, target_map_name)
    if not tgt_skins:
        return {"error": f"No MapSkin found for target '{target_map_name}'"}

    patched_names = []

    for tgt_skin in tgt_skins:
        # Save the fields we want to preserve from the target
        tgt_name_field = _copy.deepcopy(_get_mapskin_field(tgt_skin, MAPSKIN_NAME))
        tgt_geo_field  = _copy.deepcopy(_get_mapskin_field(tgt_skin, MAPSKIN_GEO_PATH))
        original_name  = _get_mapskin_field_value(tgt_skin, MAPSKIN_NAME, "?")

        # Deep-copy ALL fields from source onto target
        tgt_skin["fields"] = _copy.deepcopy(src_skin.get("fields", []))

        # Restore the target's name and geometry-path fields
        if tgt_name_field is not None:
            for i, f in enumerate(tgt_skin["fields"]):
                if f.get("name_hash") == MAPSKIN_NAME:
                    tgt_skin["fields"][i] = tgt_name_field
                    break
        if tgt_geo_field is not None:
            for i, f in enumerate(tgt_skin["fields"]):
                if f.get("name_hash") == MAPSKIN_GEO_PATH:
                    tgt_skin["fields"][i] = tgt_geo_field
                    break

        patched_names.append(original_name)

    # Count character skin overrides from source for reporting
    src_skin_overrides = 0
    src_vfx_links = 0
    for f in src_skin.get("fields", []):
        if f.get("name_hash") == "0x2d3285eb":
            src_skin_overrides = len(f.get("values", []))
        elif f.get("name_hash") == "0x92a53e77":
            src_vfx_links = len(f.get("values", []))

    # ── Swap music override (opt-in) ──
    # Swap condition links between source and target music overrides
    # so the source's music banks load when the target season is active.
    # The source .bnk/.wpk files must exist in the game WAD.
    music_result = {"swapped": False, "skipped": True}
    if swap_music:
        music_result = _swap_music_override(entries, source_map_name, target_map_name)

    # ── Write modified map11.bin ──
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    propertybin_parser.write_bin(data, output_path)

    return {
        "source_skin": src_skin_name,
        "patched_skins": patched_names,
        "total_mapskins": sum(1 for e in entries if _is_map_skin(e)),
        "skin_overrides": src_skin_overrides,
        "vfx_links": src_vfx_links,
        "music_swap": music_result,
    }


def _get_mc_chunks_field(mc_entry: dict):
    """Return the chunks map field from a mapContainer entry, or None."""
    for f in mc_entry.get("fields", []):
        if f.get("name_hash") == MC_FIELD_CHUNKS:
            return f
    return None


def _merge_mc_chunks(src_mc: dict, tgt_mc: dict):
    """
    Merge the mapContainer chunks field so the target mapContainer
    references the source map's MPC entries.

    Both mapContainers have a chunks field (type 134 = map) whose pairs
    are ``{key: hash, value: hash/link}``.  Shared chunk *keys* in both
    maps refer to equivalent logical chunks but point to different MPC
    entries.  We must:

      1. For every chunk key that exists in **both** source and target:
         replace the target's value with the source's value (so the game
         loads the source's MPC, which is present in the merged file).
      2. For every chunk key that exists **only in source**: append it
         to the target's chunks (these are milkshake-only chunks like
         snowdown particles, train, etc. that sodapop doesn't have).
      3. Keep chunk keys that exist only in target unchanged (they
         reference target-only MPCs that we already appended).

    Mutates *tgt_mc* in-place and returns ``(tgt_mc, merged, added)``.
    """
    src_chunks = _get_mc_chunks_field(src_mc)
    tgt_chunks = _get_mc_chunks_field(tgt_mc)

    if not src_chunks or not tgt_chunks:
        return tgt_mc, 0, 0

    src_pairs = src_chunks.get("pairs", [])
    tgt_pairs = tgt_chunks.get("pairs", [])

    if not src_pairs:
        return tgt_mc, 0, 0

    # Index source pairs by their key value
    src_by_key = {}
    for pair in src_pairs:
        key = pair.get("key", {})
        key_val = key.get("value", "") if isinstance(key, dict) else str(key)
        src_by_key[key_val] = pair

    # Index target pairs by their key value, for quick lookup
    tgt_key_set = set()
    for pair in tgt_pairs:
        key = pair.get("key", {})
        key_val = key.get("value", "") if isinstance(key, dict) else str(key)
        tgt_key_set.add(key_val)

    merged = 0
    added = 0

    # 1. Replace shared chunk values: target value → source value
    for i, pair in enumerate(tgt_pairs):
        key = pair.get("key", {})
        key_val = key.get("value", "") if isinstance(key, dict) else str(key)
        if key_val in src_by_key:
            src_pair = src_by_key[key_val]
            src_val = src_pair.get("value", {})
            tgt_val = pair.get("value", {})
            # Compare the value references
            src_ref = src_val.get("value", "") if isinstance(src_val, dict) else str(src_val)
            tgt_ref = tgt_val.get("value", "") if isinstance(tgt_val, dict) else str(tgt_val)
            if src_ref != tgt_ref:
                # Replace with source's value (deep copy to avoid aliasing)
                tgt_pairs[i] = _copy.deepcopy(src_pair)
                merged += 1

    # 2. Append source-only chunks
    for key_val, src_pair in src_by_key.items():
        if key_val not in tgt_key_set:
            tgt_pairs.append(_copy.deepcopy(src_pair))
            added += 1

    return tgt_mc, merged, added


def merge_materials_bin(
    source_materials_path: str,
    target_materials_path: str,
    output_path: str,
    required_material_names: set[str] | None = None,
) -> dict:
    """
    Merge two materials.bin files:
      - Takes ALL entries from SOURCE in their original order
        (preserving the exact entry and type-hash ordering the engine expects)
      - Adds TARGET-only entries (entries in target but not source) so that
        the swapped mapContainer's references all resolve
      - Replaces the mapContainer entry in-place with TARGET's mapContainer
        so the game recognises the file as the target map slot
      - Keeps all 0x1f1f50f2 (MapParticle) placements in MPCs intact
        (their VFX link targets all resolve in the merged file)
      - linked_files from source (union with target if any differ)
      - magic/version from source

    Returns a summary dict with counts.
    """
    src_data = propertybin_parser.parse_bin(source_materials_path)
    tgt_data = propertybin_parser.parse_bin(target_materials_path)

    src_entries = list(src_data.get("entries", []))
    tgt_entries = tgt_data.get("entries", [])

    # Collect path_hashes present in source
    src_path_set = {e["path_hash"] for e in src_entries}

    # Find target-only entries (exist in target but not in source).
    # These are needed because the swapped mapContainer (and the game
    # engine) may reference them.  Skip the mapContainer entry itself
    # since we swap that separately.
    tgt_only = [
        e for e in tgt_entries
        if e["path_hash"] not in src_path_set and not _is_map_container(e)
    ]

    # ── Patch character skins in target-only MPC entries ──
    # The source (e.g. milkshake) MPCs reference snowdown skins while
    # the target-only MPCs reference standard skins.  The swapped
    # mapContainer will reference the target-only MPCs, so we must
    # update their skin paths to match the source's skin numbers.
    skin_map, skin_report = _build_skin_mapping(src_entries, tgt_only)
    skin_replacements = 0
    if skin_map:
        for e in tgt_only:
            if _is_mpc(e):
                skin_replacements += _apply_skin_mapping(e, skin_map)

    # Merge source entries with target-only entries.
    # Preserve the exact source ordering (including its natural type-hash
    # interleaving) and append target-only entries at the end.
    # Both originals already have interleaved type groups — this is the
    # expected PROP format.
    if tgt_only:
        src_entries.extend(tgt_only)

    tgt_only_count = len(tgt_only)

    # Find mapContainers in both source and target
    src_mc = None
    for e in src_entries:
        if _is_map_container(e):
            src_mc = e
            break

    tgt_mc = None
    for e in tgt_entries:
        if _is_map_container(e):
            tgt_mc = e
            break

    # ── Merge mapContainer chunks ──
    # The target mapContainer's chunks field references target MPCs,
    # but our merged file uses source MPCs as the base.  We must:
    #   1. For shared chunk keys: replace target MPC refs with source refs
    #   2. For source-only chunk keys: add them to the target chunks
    # This ensures the game loads the source's snow particles, structures,
    # trains, shopkeepers, etc.
    chunks_merged = 0
    chunks_added = 0
    if tgt_mc and src_mc:
        tgt_mc, chunks_merged, chunks_added = _merge_mc_chunks(
            src_mc, tgt_mc
        )

    # Replace mapContainer in source entries (in-place at same index)
    mc_swapped = False
    if tgt_mc:
        for i, e in enumerate(src_entries):
            if _is_map_container(e):
                src_entries[i] = tgt_mc
                mc_swapped = True
                break

    # NOTE: 0x1f1f50f2 (MapParticle) placements in MPCs are kept intact.
    # Research confirmed all 15 unique VFX link targets from milkshake's
    # 1082 particle placements resolve within the merged file.  These are
    # the snow particle placements — stripping them removes all snow.

    # Merge linked_files (source first, then any target-only additions)
    src_linked = src_data.get("linked_files", [])
    tgt_linked = tgt_data.get("linked_files", [])
    linked_set = set(src_linked)
    merged_linked = list(src_linked)
    for lf in tgt_linked:
        if lf not in linked_set:
            merged_linked.append(lf)
            linked_set.add(lf)

    # Construct output — preserving source structure
    merged_data = {
        "magic": src_data.get("magic", "PROP"),
        "version": src_data.get("version", 2),
        "linked_files": merged_linked,
        "entries": src_entries,
        "entry_count": len(src_entries),
    }

    # Carry over patch entries from source if present
    if "patch_entries" in src_data:
        merged_data["patch_entries"] = src_data["patch_entries"]

    # ── Defensive material coverage pass ──
    # Some maps can crash if any mapgeo primitive material string has no
    # matching StaticMaterialDef. Ensure required names resolve in output.
    injected_missing_materials = 0
    unresolved_material_names = []
    if required_material_names:
        merged_name_set = set()
        merged_path_set = set(e.get("path_hash", "") for e in src_entries)

        for e in src_entries:
            if _type_hash_int(e) != 0xff9d3409:
                continue
            for f in e.get("fields", []):
                if f.get("name_hash") == "0x8d39bde6" or f.get("name_hash_int") == 0x8d39bde6:
                    merged_name_set.add(str(f.get("value", "")).strip().lower())
                    break

        # Build lookup from both source and target by material name
        lookup_by_name = {}
        for e in list(src_data.get("entries", [])) + list(tgt_data.get("entries", [])):
            if _type_hash_int(e) != 0xff9d3409:
                continue
            mat_name = ""
            for f in e.get("fields", []):
                if f.get("name_hash") == "0x8d39bde6" or f.get("name_hash_int") == 0x8d39bde6:
                    mat_name = str(f.get("value", "")).strip()
                    break
            if mat_name:
                lookup_by_name.setdefault(mat_name.lower(), e)

        for mat_name in sorted(required_material_names):
            key = mat_name.strip().lower()
            if not key or key in merged_name_set:
                continue
            candidate = lookup_by_name.get(key)
            if candidate is None:
                unresolved_material_names.append(mat_name)
                continue
            p_hash = candidate.get("path_hash", "")
            if p_hash and p_hash in merged_path_set:
                # Hash already present; skip duplicate insertion.
                continue

            src_entries.append(_copy.deepcopy(candidate))
            injected_missing_materials += 1
            merged_name_set.add(key)
            if p_hash:
                merged_path_set.add(p_hash)

        merged_data["entries"] = src_entries
        merged_data["entry_count"] = len(src_entries)

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    propertybin_parser.write_bin(merged_data, output_path)

    # Build type summary for report
    from collections import Counter
    type_counts = Counter()
    for e in src_entries:
        th = _type_hash_int(e)
        label = _TYPE_LABELS.get(th, f"0x{th:08x}")
        type_counts[label] += 1

    return {
        "total_entries": len(src_entries),
        "mc_swapped": mc_swapped,
        "linked_files_total": len(merged_linked),
        "type_summary": dict(type_counts),
        "target_only_added": tgt_only_count,
        "skin_replacements": skin_replacements,
        "skin_report": skin_report,
        "chunks_merged": chunks_merged,
        "chunks_added": chunks_added,
        "injected_missing_materials": injected_missing_materials,
        "unresolved_material_names": unresolved_material_names,
    }


# ============================================================================
# Operator: Port Map
# ============================================================================

class MAPPORTER_OT_port_map(Operator):
    """Port a source map onto a target map slot"""
    bl_idname = "mapporter.port_map"
    bl_label = "Port Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.map_porter_settings
        src_mapgeo = bpy.path.abspath(settings.source_mapgeo)
        src_materials = bpy.path.abspath(settings.source_materials)
        tgt_materials = bpy.path.abspath(settings.target_materials)
        map11_bin = bpy.path.abspath(settings.map11_bin)
        out_dir = bpy.path.abspath(settings.output_directory)

        # --- Validation ---
        errors = []
        if not src_materials or not os.path.isfile(src_materials):
            errors.append("Source materials.bin not found")
        if not tgt_materials or not os.path.isfile(tgt_materials):
            errors.append("Target materials.bin not found")
        if not out_dir:
            errors.append("Output directory not set")

        if errors:
            self.report({'ERROR'}, " | ".join(errors))
            return {'CANCELLED'}

        os.makedirs(out_dir, exist_ok=True)

        source_map_name = _derive_map_name_from_materials(src_materials)
        target_map_name = _derive_map_name_from_materials(tgt_materials)
        report_lines = [f"Map Porter: porting '{source_map_name}' → '{target_map_name}'"]

        required_material_names = set()
        if src_mapgeo and os.path.isfile(src_mapgeo):
            try:
                required_material_names = _extract_mapgeo_material_names(src_mapgeo)
                report_lines.append(
                    f"Source mapgeo materials: {len(required_material_names)}"
                )
            except Exception as e:
                report_lines.append(f"WARNING: Could not scan source mapgeo materials: {e}")

        # --- 1. Merge materials.bin ---
        try:
            out_materials = os.path.join(out_dir, f"{target_map_name}.materials.bin")
            summary = merge_materials_bin(
                src_materials,
                tgt_materials,
                out_materials,
                required_material_names=required_material_names,
            )
            mc_status = "swapped" if summary["mc_swapped"] else "NOT FOUND in target"
            report_lines.append(
                f"Materials.bin: {summary['total_entries']} entries, "
                f"mapContainer {mc_status}"
            )
            if summary.get("target_only_added", 0) > 0:
                report_lines.append(
                    f"  • Added {summary['target_only_added']} target-only entries"
                )
            if summary.get("skin_replacements", 0) > 0:
                report_lines.append(
                    f"  • Patched {summary['skin_replacements']} character skin paths "
                    f"in target-only MPCs"
                )
                for sr in summary.get("skin_report", []):
                    report_lines.append(f"    {sr}")
            cm = summary.get("chunks_merged", 0)
            ca = summary.get("chunks_added", 0)
            if cm or ca:
                report_lines.append(
                    f"  • mapContainer chunks: {cm} redirected to source, "
                    f"{ca} source-only added"
                )
            im = summary.get("injected_missing_materials", 0)
            if im:
                report_lines.append(
                    f"  • Injected {im} missing material definition(s) required by source mapgeo"
                )
            unresolved = summary.get("unresolved_material_names", [])
            if unresolved:
                report_lines.append(
                    f"  • WARNING unresolved materials ({len(unresolved)}):"
                )
                for m in unresolved[:25]:
                    report_lines.append(f"    - {m}")
            if summary["type_summary"]:
                for label, count in sorted(summary["type_summary"].items()):
                    report_lines.append(f"  • {label}: {count}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to merge materials.bin: {e}")
            return {'CANCELLED'}

        # --- 2. Patch map11.bin (optional) ---
        if map11_bin and os.path.isfile(map11_bin):
            try:
                out_map11 = os.path.join(out_dir, os.path.basename(map11_bin))
                m11_result = merge_map11_bin(
                    map11_bin, source_map_name, target_map_name, out_map11,
                    swap_music=settings.swap_music,
                )
                if "error" in m11_result:
                    self.report({'WARNING'}, f"map11.bin: {m11_result['error']}")
                    report_lines.append(f"map11.bin: WARNING – {m11_result['error']}")
                else:
                    patched = ", ".join(m11_result["patched_skins"])
                    report_lines.append(
                        f"map11.bin: patched {len(m11_result['patched_skins'])} MapSkin(s) "
                        f"with '{m11_result['source_skin']}' settings → [{patched}]"
                    )
                    if m11_result.get("skin_overrides", 0) > 0:
                        report_lines.append(
                            f"  • {m11_result['skin_overrides']} character skin overrides "
                            f"(shopkeeper, turrets, nexus, inhibitor, baron, minions)"
                        )
                    if m11_result.get("vfx_links", 0) > 0:
                        report_lines.append(
                            f"  • {m11_result['vfx_links']} VFX override link(s)"
                        )
                    music = m11_result.get("music_swap", {})
                    if music.get("swapped"):
                        report_lines.append(
                            f"  • Music swapped: {music['target_bank']} → {music['source_bank']}"
                        )
                    elif music.get("error"):
                        report_lines.append(f"  • Music swap: {music['error']}")
            except Exception as e:
                self.report({'WARNING'}, f"map11.bin patch failed: {e}")
                report_lines.append(f"map11.bin: FAILED – {e}")

        # --- 3. Copy + rename mapgeo (optional) ---
        if src_mapgeo and os.path.isfile(src_mapgeo):
            try:
                out_mapgeo = os.path.join(out_dir, f"{target_map_name}.mapgeo")
                shutil.copy2(src_mapgeo, out_mapgeo)
                report_lines.append(
                    f"Mapgeo: copied '{os.path.basename(src_mapgeo)}' → '{os.path.basename(out_mapgeo)}'"
                )
            except Exception as e:
                self.report({'WARNING'}, f"Mapgeo copy failed: {e}")
                report_lines.append(f"Mapgeo: FAILED – {e}")
        else:
            report_lines.append("Mapgeo: skipped (no source mapgeo specified)")

        # --- Done ---
        for line in report_lines:
            print(f"[Map Porter] {line}")
        self.report({'INFO'}, report_lines[0] + f" — {summary['total_entries']} entries written")
        return {'FINISHED'}


# ============================================================================
# Operator: Pick Source Mapgeo
# ============================================================================

class MAPPORTER_OT_pick_source_mapgeo(Operator):
    """Select the source .mapgeo file to port"""
    bl_idname = "mapporter.pick_source_mapgeo"
    bl_label = "Select Source Mapgeo"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.mapgeo", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.map_porter_settings.source_mapgeo = self.filepath
        return {'FINISHED'}


# ============================================================================
# Operator: Pick Source Materials
# ============================================================================

class MAPPORTER_OT_pick_source_materials(Operator):
    """Select the source materials file (.materials.bin)"""
    bl_idname = "mapporter.pick_source_materials"
    bl_label = "Select Source Materials"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.map_porter_settings.source_materials = self.filepath
        return {'FINISHED'}


# ============================================================================
# Operator: Pick Target Materials
# ============================================================================

class MAPPORTER_OT_pick_target_materials(Operator):
    """Select the target materials file (.materials.bin) to merge into"""
    bl_idname = "mapporter.pick_target_materials"
    bl_label = "Select Target Materials"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.map_porter_settings.target_materials = self.filepath
        return {'FINISHED'}


# ============================================================================
# Operator: Pick Output Directory
# ============================================================================

class MAPPORTER_OT_pick_output_dir(Operator):
    """Select the output directory for ported files"""
    bl_idname = "mapporter.pick_output_dir"
    bl_label = "Select Output Directory"

    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.map_porter_settings.output_directory = self.directory
        return {'FINISHED'}


# ============================================================================
# Operator: Pick Map11.bin
# ============================================================================

class MAPPORTER_OT_pick_map11(Operator):
    """Select map11.bin (or equivalent) for MapSkin patching"""
    bl_idname = "mapporter.pick_map11"
    bl_label = "Select map11.bin"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.map_porter_settings.map11_bin = self.filepath
        return {'FINISHED'}


# ============================================================================
# Settings PropertyGroup
# ============================================================================

class MapPorterSettings(PropertyGroup):
    source_mapgeo: StringProperty(
        name="Source Mapgeo",
        description="Path to the source .mapgeo file (the map to port)",
        subtype='FILE_PATH',
    )
    source_materials: StringProperty(
        name="Source Materials",
        description="Path to the source .materials.bin file (the map to port)",
        subtype='FILE_PATH',
    )
    target_materials: StringProperty(
        name="Target Materials",
        description="Path to the target .materials.bin file (the map slot to port into)",
        subtype='FILE_PATH',
    )
    map11_bin: StringProperty(
        name="map11.bin",
        description="Path to map11.bin (or equivalent) for MapSkin patching. "
                    "Copies source map's particle lists, VFX links, GrassTint, "
                    "and sound banks onto the target's MapSkin entries",
        subtype='FILE_PATH',
    )
    output_directory: StringProperty(
        name="Output Directory",
        description="Directory where the ported files will be saved",
        subtype='DIR_PATH',
    )
    copy_mapgeo: BoolProperty(
        name="Copy Mapgeo",
        description="Copy and rename the source .mapgeo to the output directory",
        default=True,
    )
    swap_music: BoolProperty(
        name="Swap Music",
        description="Swap the music activation triggers so the source map's "
                    "background music & ambience plays instead of the target's. "
                    "Requires source .bnk/.wpk files in the game WAD",
        default=True,
    )


# ============================================================================
# Panel
# ============================================================================

class VIEW3D_PT_map_porter(Panel):
    """Map Porter panel in the League Tools sidebar."""
    bl_label = "Map Porter"
    bl_idname = "VIEW3D_PT_map_porter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_order = 80
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.map_porter_settings

        # ── Info ──
        box = layout.box()
        box.label(text="Port one map onto another map slot", icon='FILE_REFRESH')
        col = box.column(align=True)
        col.label(text="All entries from SOURCE (preserving order).")
        col.label(text="Only mapContainer swapped from TARGET.")

        # ── Source Map ──
        box = layout.box()
        box.label(text="Source Map (map to port)", icon='EXPORT')

        # Source Mapgeo
        row = box.row(align=True)
        row.prop(settings, "source_mapgeo", text="")
        row.operator("mapporter.pick_source_mapgeo", text="", icon='FILE_FOLDER')
        if settings.source_mapgeo:
            name = os.path.basename(bpy.path.abspath(settings.source_mapgeo))
            box.label(text=f"  Mapgeo: {name}", icon='MESH_DATA')

        # Source Materials
        row = box.row(align=True)
        row.prop(settings, "source_materials", text="")
        row.operator("mapporter.pick_source_materials", text="", icon='FILE_FOLDER')
        if settings.source_materials:
            name = os.path.basename(bpy.path.abspath(settings.source_materials))
            box.label(text=f"  Materials: {name}", icon='MATERIAL')

        # ── Target Map ──
        box = layout.box()
        box.label(text="Target Map (slot to port into)", icon='IMPORT')

        # Target Materials
        row = box.row(align=True)
        row.prop(settings, "target_materials", text="")
        row.operator("mapporter.pick_target_materials", text="", icon='FILE_FOLDER')
        if settings.target_materials:
            name = os.path.basename(bpy.path.abspath(settings.target_materials))
            box.label(text=f"  Materials: {name}", icon='MATERIAL')
            map_name = _derive_map_name_from_materials(
                bpy.path.abspath(settings.target_materials)
            )
            box.label(text=f"  Target name: {map_name}", icon='INFO')

        # ── map11.bin (optional) ──
        box = layout.box()
        box.label(text="MapSkin Patch (optional)", icon='GHOST_ENABLED')
        col = box.column(align=True)
        col.label(text="Copies source skin's particles, VFX links,")
        col.label(text="GrassTint & sounds onto the target MapSkin.")

        row = box.row(align=True)
        row.prop(settings, "map11_bin", text="")
        row.operator("mapporter.pick_map11", text="", icon='FILE_FOLDER')
        if settings.map11_bin:
            name = os.path.basename(bpy.path.abspath(settings.map11_bin))
            box.label(text=f"  File: {name}", icon='FILE')

        # ── Output ──
        box = layout.box()
        box.label(text="Output", icon='FILE_FOLDER')

        row = box.row(align=True)
        row.prop(settings, "output_directory", text="")
        row.operator("mapporter.pick_output_dir", text="", icon='FILE_FOLDER')

        box.prop(settings, "copy_mapgeo")
        box.prop(settings, "swap_music")

        # ── Port Button ──
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5

        can_port = bool(settings.source_materials and settings.target_materials
                        and settings.output_directory)
        row.enabled = can_port
        row.operator("mapporter.port_map", text="Port Map", icon='FILE_REFRESH')

        if not can_port:
            layout.label(text="Set source materials, target materials, and output directory",
                         icon='ERROR')


# ============================================================================
# Registration
# ============================================================================

_classes = [
    MapPorterSettings,
    MAPPORTER_OT_pick_source_mapgeo,
    MAPPORTER_OT_pick_source_materials,
    MAPPORTER_OT_pick_target_materials,
    MAPPORTER_OT_pick_output_dir,
    MAPPORTER_OT_pick_map11,
    MAPPORTER_OT_port_map,
    VIEW3D_PT_map_porter,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.map_porter_settings = bpy.props.PointerProperty(type=MapPorterSettings)
    print("[Map Porter] Registered")


def unregister():
    del bpy.types.Scene.map_porter_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    print("[Map Porter] Unregistered")
