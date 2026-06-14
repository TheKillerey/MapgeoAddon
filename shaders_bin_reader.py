"""shaders_bin_reader.py — Experimental Shaders.bin catalog reader
================================================================
Reads the game's Shaders.bin (inside Shaders.wad.client) using the
existing propertybin_parser, building a catalog of CustomShaderDef
entries with:

  • per-shader parameter names
  • static switches (name + on_by_default)
  • texture slots (name + optional default path)
  • feature defines (feature name → preprocessor define string)
  • feature mask (u32)

This is an EXPERIMENTAL module — it provides authoritative live data
from the game's shader registry, complementing the pre-extracted
shader_templates_data.json.

Reference: https://github.com/LeagueToolkit/shader-tools
           (shaders_bin.rs — CustomShaderDef structure and field hashes)
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional


# ── FNV-1a helper ──────────────────────────────────────────────────────────────

def _fnv1a_lower(text: str) -> int:
    """FNV-1a 32-bit hash of the lowercased text (matches LoL property bin hashing)."""
    h = 0x811C9DC5
    for c in text.lower():
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# ── Pre-computed field hashes for Shaders.bin ──────────────────────────────────
# Each name is lowercased before hashing (same as hash_lower() in shader-tools).
_H_ENTRIES          = _fnv1a_lower("entries")            # top-level entries MAP
_H_OBJECT_PATH      = _fnv1a_lower("objectpath")         # "ObjectPath"
_H_PARAMETERS       = _fnv1a_lower("parameters")         # "Parameters"
_H_STATIC_SWITCHES  = _fnv1a_lower("staticswitches")     # "StaticSwitches"
_H_TEXTURES         = _fnv1a_lower("textures")           # "Textures"
_H_FEATURE_DEFINES  = _fnv1a_lower("featuredefines")     # "FeatureDefines"
_H_FEATURE_MASK     = _fnv1a_lower("featuremask")        # "FeatureMask"
_H_NAME             = _fnv1a_lower("name")               # "Name"
_H_ON_BY_DEFAULT    = _fnv1a_lower("onbydefault")        # "OnByDefault"
_H_DEFAULT_TEX_PATH = _fnv1a_lower("defaulttexturepath") # "DefaultTexturePath"

# Propertybin type constants (mirrors propertybin_parser.py)
_TYPE_BOOL       = 1
_TYPE_U32        = 7
_TYPE_STRING     = 16
_TYPE_HASH       = 17
_TYPE_CONTAINER  = 0x80   # 128
_TYPE_CONTAINER2 = 0x81   # 129
_TYPE_EMBEDDED   = 0x83   # 131
_TYPE_MAP        = 0x86   # 134


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class StaticSwitchInfo:
    """A static shader switch definition."""
    name: str
    on_by_default: bool = False


@dataclass
class TextureSlotInfo:
    """A shader texture slot definition."""
    name: str
    default_path: Optional[str] = None


@dataclass
class ShaderCatalogEntry:
    """Authoritative metadata for a single CustomShaderDef from Shaders.bin."""
    object_path: str
    parameters: list = field(default_factory=list)       # list[str]
    switches: list = field(default_factory=list)          # list[StaticSwitchInfo]
    textures: list = field(default_factory=list)          # list[TextureSlotInfo]
    feature_defines: dict = field(default_factory=dict)   # str -> str
    feature_mask: int = 0


# ── Module-level catalog cache ─────────────────────────────────────────────────

_catalog: dict = {}           # lowercase object_path -> ShaderCatalogEntry
_catalog_source: Optional[str] = None   # filepath that was loaded


# ── Internal parsing helpers ───────────────────────────────────────────────────

def _field_by_hash(fields: list, h: int) -> Optional[dict]:
    """Find the first field in a fields list whose name_hash_int equals h."""
    for f in fields:
        if f.get("name_hash_int") == h:
            return f
    return None


def _parse_shader_def(embed: dict) -> Optional[ShaderCatalogEntry]:
    """
    Parse a CustomShaderDef embedded struct (from propertybin_parser output)
    into a ShaderCatalogEntry.  Returns None if required fields are absent.
    """
    fields = embed.get("fields") or []

    # ── ObjectPath (required) ──────────────────────────────────────────────────
    op_field = _field_by_hash(fields, _H_OBJECT_PATH)
    if not op_field:
        return None
    object_path = str(op_field.get("value", "")).strip()
    if not object_path:
        return None

    # ── Parameters — Container<Embedded{Name}> ────────────────────────────────
    parameters: list = []
    params_field = _field_by_hash(fields, _H_PARAMETERS)
    if params_field and params_field.get("type") in (_TYPE_CONTAINER, _TYPE_CONTAINER2):
        for item in params_field.get("values", []):
            item_fields = item.get("fields") or []
            name_f = _field_by_hash(item_fields, _H_NAME)
            if name_f:
                parameters.append(str(name_f.get("value", "")))

    # ── StaticSwitches — Container<Embedded{Name, OnByDefault}> ───────────────
    switches: list = []
    sw_field = _field_by_hash(fields, _H_STATIC_SWITCHES)
    if sw_field and sw_field.get("type") in (_TYPE_CONTAINER, _TYPE_CONTAINER2):
        for item in sw_field.get("values", []):
            item_fields = item.get("fields") or []
            name_f = _field_by_hash(item_fields, _H_NAME)
            obd_f  = _field_by_hash(item_fields, _H_ON_BY_DEFAULT)
            if name_f:
                switches.append(StaticSwitchInfo(
                    name=str(name_f.get("value", "")),
                    on_by_default=bool(obd_f.get("value", False)) if obd_f else False,
                ))

    # ── Textures — Container<Embedded{Name, DefaultTexturePath?}> ─────────────
    textures: list = []
    tex_field = _field_by_hash(fields, _H_TEXTURES)
    if tex_field and tex_field.get("type") in (_TYPE_CONTAINER, _TYPE_CONTAINER2):
        for item in tex_field.get("values", []):
            item_fields = item.get("fields") or []
            name_f = _field_by_hash(item_fields, _H_NAME)
            dtp_f  = _field_by_hash(item_fields, _H_DEFAULT_TEX_PATH)
            if name_f:
                textures.append(TextureSlotInfo(
                    name=str(name_f.get("value", "")),
                    default_path=str(dtp_f.get("value")) if dtp_f else None,
                ))

    # ── FeatureDefines — Map<key, String> ─────────────────────────────────────
    feature_defines: dict = {}
    fd_field = _field_by_hash(fields, _H_FEATURE_DEFINES)
    if fd_field and fd_field.get("type") == _TYPE_MAP:
        for pair in fd_field.get("pairs", []):
            k_node = pair.get("key", {})
            v_node = pair.get("value", {})
            # Keys may be strings or hashes
            k_raw = k_node.get("value", "")
            k = str(k_raw) if k_raw else ""
            v = str(v_node.get("value", ""))
            if k:
                feature_defines[k] = v

    # ── FeatureMask — U32 ─────────────────────────────────────────────────────
    fm_field = _field_by_hash(fields, _H_FEATURE_MASK)
    feature_mask = int(fm_field.get("value", 0)) if fm_field else 0

    return ShaderCatalogEntry(
        object_path=object_path,
        parameters=parameters,
        switches=switches,
        textures=textures,
        feature_defines=feature_defines,
        feature_mask=feature_mask,
    )


def _parse_from_bin_data(raw: bytes) -> list:
    """
    Parse raw Shaders.bin bytes into a list of ShaderCatalogEntry objects.
    Writes to a temporary file because propertybin_parser.parse_bin() needs a path.

    Structure (confirmed from live Shaders.wad.client inspection):
    Each top-level bin entry IS a CustomShaderDef directly — there is no
    "entries" MAP wrapper.  We parse every top-level entry that has an
    ObjectPath field.
    """
    try:
        from . import propertybin_parser
        parse_bin = propertybin_parser.parse_bin
    except ImportError:
        import propertybin_parser
        parse_bin = propertybin_parser.parse_bin

    # Write to a temp file so parse_bin can open it by path
    fd, tmp_path = tempfile.mkstemp(suffix=".bin", prefix="shaders_bin_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        data = parse_bin(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    entries: list = []
    for top_entry in data.get("entries", []):
        # Each top-level entry IS a CustomShaderDef (no wrapper MAP).
        # Synthesise a fake "embedded" node so _parse_shader_def can consume it.
        fake_embed = {
            "type": _TYPE_EMBEDDED,
            "class_hash": top_entry.get("type_hash", "0x00000000"),
            "fields": top_entry.get("fields") or [],
        }
        result = _parse_shader_def(fake_embed)
        if result:
            entries.append(result)

    return entries


# ── Public API ────────────────────────────────────────────────────────────────

def load_catalog_from_bin_file(bin_path: str) -> int:
    """
    Load the Shaders.bin catalog from a raw .bin file.
    Returns the number of shader entries loaded.
    Raises IOError / ValueError on parse failure.
    """
    global _catalog, _catalog_source
    with open(bin_path, "rb") as fh:
        raw = fh.read()
    entries = _parse_from_bin_data(raw)
    _catalog = {e.object_path.lower(): e for e in entries}
    _catalog_source = bin_path
    print(f"[Shaders.bin] Loaded {len(_catalog)} shader entries from: {bin_path}")
    return len(_catalog)


def load_catalog_from_wad(wad_path: str) -> int:
    """
    Load the Shaders.bin catalog from inside a Shaders.wad / Shaders.wad.client.
    The bin is expected at the WAD path 'data/shaders/shaders.bin'.
    Returns the number of shader entries loaded.
    Raises FileNotFoundError if the bin is absent from the WAD.
    """
    global _catalog, _catalog_source

    try:
        from . import wad_tool
        parse_wad       = wad_tool.parse_wad
        read_entry_data = wad_tool.read_entry_data
        xxhash64_path   = wad_tool.xxhash64_path
    except ImportError:
        import wad_tool
        parse_wad       = wad_tool.parse_wad
        read_entry_data = wad_tool.read_entry_data
        xxhash64_path   = wad_tool.xxhash64_path

    target_hash = xxhash64_path("data/shaders/shaders.bin")
    wad = parse_wad(wad_path)

    for entry in wad.entries:
        if entry.path_hash == target_hash:
            raw = read_entry_data(wad, entry)
            entries = _parse_from_bin_data(raw)
            _catalog = {e.object_path.lower(): e for e in entries}
            _catalog_source = wad_path
            print(f"[Shaders.bin] Loaded {len(_catalog)} shader entries from WAD: {wad_path}")
            return len(_catalog)

    raise FileNotFoundError(
        f"'data/shaders/shaders.bin' (hash {target_hash:016x}) not found in: {wad_path}"
    )


def get_shader_entry(shader_path: str) -> Optional[ShaderCatalogEntry]:
    """
    Look up a shader by its ObjectPath (case-insensitive).
    e.g. "Shaders/StaticMesh/DefaultEnv_Flat"
    Returns None if the catalog is not loaded or the shader is not present.
    """
    return _catalog.get(shader_path.lower())


def is_catalog_loaded() -> bool:
    """Return True if the catalog has been loaded and contains entries."""
    return bool(_catalog)


def catalog_size() -> int:
    """Return the number of entries in the in-memory catalog."""
    return len(_catalog)


def catalog_source() -> Optional[str]:
    """Return the source file path used to build the catalog (or None)."""
    return _catalog_source


def clear_catalog() -> None:
    """Clear the in-memory catalog."""
    global _catalog, _catalog_source
    _catalog = {}
    _catalog_source = None


def find_default_wad_path() -> Optional[str]:
    """
    Search common League of Legends install directories for Shaders.wad.
    Returns the first existing path found, or None if not found.
    """
    candidates = [
        r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Shaders\Shaders.wad",
        r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Shaders\Shaders.wad.client",
        r"D:\Riot Games\League of Legends\Game\DATA\FINAL\Shaders\Shaders.wad",
        r"D:\Riot Games\League of Legends\Game\DATA\FINAL\Shaders\Shaders.wad.client",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None
