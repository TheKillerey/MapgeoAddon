"""
GdsMapObject Importer / Exporter — Import and export GdsMapObject entries
from League of Legends materials.bin files.

GdsMapObject entries live inside MapPlaceableContainer (MPC) entries,
alongside MapParticle items.  Each GdsMapObject item contains:
  - transform: mtx44 (16 floats, column-major)
  - name: string (e.g. "LevelProp_sru_gromp_prop12")
  - type: u8

Imported as Empty objects in Blender, mirroring the particle system approach.
"""

import json
import os
import re
import bpy
from mathutils import Matrix, Euler


# ============================================================================
# Constants
# ============================================================================

# GdsMapObject class hash (inside MPC items)
_CLASS_GDS_MAP_OBJECT = 0xda9e5c0c

# MPC type hash (same container as particles)
_TYPE_MPC = 0xb25c0a3f

# Field hashes
_HASH_ITEMS     = 0x3a79338f      # MPC items field
_HASH_MPC_NAME  = 0x8d39bde6      # name field (used for MPC container name AND GdsMapObject name)
_HASH_TRANSFORM = 0xe1ad931b      # transform: mtx44
_HASH_NAME      = 0x8d39bde6      # name: string
_HASH_TYPE      = 0x5127f14d      # type: u8


# ============================================================================
# Parsing
# ============================================================================

def parse_gds_map_objects(materials_bin_path: str) -> list:
    """Parse all GdsMapObject items from MPC entries in a materials.bin file.

    Returns list of dicts:
        {
            'container_hash': str,  # MPC entry path_hash
            'container_name': str,  # MPC container name
            'item_key': str,        # pair key hash (unique identifier)
            'name': str,            # e.g. "LevelProp_sru_gromp_prop12"
            'type': int,            # u8 value
            'transform': list,      # 16 floats (column-major mtx44)
        }
    """
    try:
        from . import propertybin_parser
    except ImportError:
        import propertybin_parser

    if not materials_bin_path or not os.path.isfile(materials_bin_path):
        return []

    try:
        data = propertybin_parser.parse_bin(materials_bin_path)
    except Exception as e:
        print(f"[MapObjects] Failed to parse {materials_bin_path}: {e}")
        return []

    mpc_hex = f"0x{_TYPE_MPC:08x}"
    class_hex = f"0x{_CLASS_GDS_MAP_OBJECT:08x}"
    results = []

    for entry in data.get('entries', []):
        if entry.get('type_hash') != mpc_hex:
            continue

        container_hash = entry.get('path_hash', '')
        fields = entry.get('fields', [])

        # Extract MPC container name
        name_f = _get_field_by_hash(fields, _HASH_MPC_NAME)
        container_name = str(name_f.get('value', '')) if name_f else container_hash

        # Find items field (map type with 'pairs')
        items_f = _get_field_by_hash(fields, _HASH_ITEMS)
        if not items_f:
            continue

        pairs = items_f.get('pairs', [])
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            value = pair.get('value', {})
            if not isinstance(value, dict):
                continue
            if value.get('class_hash') != class_hex:
                continue

            item_fields = value.get('fields', [])
            if not item_fields:
                continue

            # Extract key hash (unique identifier for this item in the MPC)
            pair_key = pair.get('key', {})
            item_key = ''
            if isinstance(pair_key, dict):
                item_key = str(pair_key.get('value', ''))
            elif isinstance(pair_key, str):
                item_key = pair_key

            name = ''
            obj_type = 0
            transform = []

            for f in item_fields:
                h = _field_hash(f)
                if h == _HASH_NAME:
                    name = str(f.get('value', ''))
                elif h == _HASH_TYPE:
                    try:
                        obj_type = int(f.get('value', 0))
                    except (ValueError, TypeError):
                        obj_type = 0
                elif h == _HASH_TRANSFORM:
                    transform = _flatten_mtx44(f.get('value'))

            results.append({
                'container_hash': container_hash,
                'container_name': container_name,
                'item_key': item_key,
                'name': name,
                'type': obj_type,
                'transform': transform,
            })

    return results


def _get_field_by_hash(fields, target_hash):
    """Find a field dict by integer name hash."""
    for f in fields:
        if _field_hash(f) == target_hash:
            return f
    return None


def _field_hash(field: dict) -> int:
    """Get the integer name hash from a field dict."""
    h = field.get('name_hash_int', 0)
    if h:
        return h
    hs = field.get('name_hash', '')
    if hs.startswith('0x'):
        try:
            return int(hs, 16)
        except ValueError:
            pass
    return 0


def _flatten_mtx44(value) -> list:
    """Flatten an mtx44 value (possibly nested lists) to 16 floats."""
    if not value:
        return []
    result = []
    if isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, (list, tuple)):
                result.extend(float(x) for x in v)
            else:
                result.append(float(v))
    return result if len(result) == 16 else []


# ============================================================================
# Transform Helpers (same conversion as particles)
# ============================================================================

def _extract_location(transform_values):
    """Game (tx, ty, tz) → Blender (tx, tz, ty)."""
    if not transform_values or len(transform_values) < 15:
        return (0.0, 0.0, 0.0)
    return (transform_values[12], transform_values[14], transform_values[13])


def _extract_rotation(transform_values):
    """Extract rotation from game mtx44 → Blender Euler (XYZ).

    Uses the Y↔Z coordinate conversion matrix.
    """
    if not transform_values or len(transform_values) < 12:
        return (0.0, 0.0, 0.0)

    tv = transform_values
    mat_league = Matrix((
        (tv[0],  tv[4],  tv[8],  0),
        (tv[1],  tv[5],  tv[9],  0),
        (tv[2],  tv[6],  tv[10], 0),
        (0,      0,      0,      1),
    ))

    conversion = Matrix((
        (1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 1, 0, 0),
        (0, 0, 0, 1),
    ))

    mat_blender = conversion @ mat_league @ conversion
    _loc, rot_quat, _scale = mat_blender.decompose()
    euler = rot_quat.to_euler('XYZ')
    return (euler.x, euler.y, euler.z)


def _extract_scale(transform_values):
    """Extract per-axis scale from mtx44, with Y↔Z swap."""
    if not transform_values or len(transform_values) < 11:
        return (1.0, 1.0, 1.0)

    import math
    tv = transform_values
    sx = math.sqrt(tv[0]**2 + tv[1]**2 + tv[2]**2)
    sy = math.sqrt(tv[4]**2 + tv[5]**2 + tv[6]**2)
    sz = math.sqrt(tv[8]**2 + tv[9]**2 + tv[10]**2)
    return (sx, sz, sy)  # Y↔Z swap


def _blender_to_transform(obj) -> list:
    """Build 16-float column-major mtx44 from Blender object transform.

    Applies Blender→Game coordinate swap (Y↔Z).
    """
    loc = obj.location
    rot = obj.rotation_euler
    scl = obj.scale

    # Blender (x, y, z) → Game (x, z, y)
    tx, ty, tz = loc.x, loc.z, loc.y
    sx, sy, sz = scl.x, scl.z, scl.y

    euler = Euler((rot.x, rot.z, rot.y), 'XYZ')
    rot_mat = euler.to_matrix()

    m = [0.0] * 16
    for c in range(3):
        s = [sx, sy, sz][c]
        m[c * 4 + 0] = rot_mat[0][c] * s
        m[c * 4 + 1] = rot_mat[1][c] * s
        m[c * 4 + 2] = rot_mat[2][c] * s
        m[c * 4 + 3] = 0.0
    m[12], m[13], m[14], m[15] = tx, ty, tz, 1.0
    return m


# ============================================================================
# Import
# ============================================================================

def import_map_objects_from_materials(
    context,
    materials_path: str,
    root_collection_name: str | None = None,
    log=None,
) -> int:
    """Import GdsMapObject entries from a materials.bin as Empty objects.

    Creates:
        {root}_MapObjects/
            <ContainerShortName>/   — one sub-collection per MPC
                MO_{name}           — one Empty per GdsMapObject

    Returns the number of objects imported.
    """
    if not materials_path or not os.path.isfile(materials_path):
        return 0

    if log:
        log.info("MapObjects", f"Parsing {os.path.basename(materials_path)}")

    entries = parse_gds_map_objects(materials_path)
    if not entries:
        if log:
            log.info("MapObjects", "No GdsMapObject entries found")
        return 0

    if log:
        log.info("MapObjects", f"Found {len(entries)} GdsMapObject entries")

    # Root collection
    settings = context.scene.mapgeo_settings
    root_name = root_collection_name or (
        settings.root_collection_name
        if hasattr(settings, 'root_collection_name') and settings.root_collection_name
        else "rey_map"
    )

    root_col = bpy.data.collections.get(root_name)
    if root_col is None:
        root_col = bpy.data.collections.new(root_name)
        context.scene.collection.children.link(root_col)

    # MapObjects parent collection
    mo_col_name = f"{root_name}_MapObjects"
    mo_col = bpy.data.collections.get(mo_col_name)
    if mo_col is None:
        mo_col = bpy.data.collections.new(mo_col_name)
        root_col.children.link(mo_col)

    # Group entries by container for sub-collections
    from collections import OrderedDict
    containers = OrderedDict()
    for entry in entries:
        ch = entry['container_hash']
        if ch not in containers:
            containers[ch] = {
                'name': entry['container_name'],
                'items': [],
            }
        containers[ch]['items'].append(entry)

    # Cache for sub-collections
    sub_col_cache = {}
    imported = 0

    for container_hash, container_data in containers.items():
        cname = container_data['name']
        short_cname = cname.rsplit('/', 1)[-1] if '/' in cname else cname
        safe_cname = re.sub(r'[^A-Za-z0-9_]+', '_', short_cname)

        sub_col_name = f"{mo_col_name}_{safe_cname}"
        sub_col = sub_col_cache.get(sub_col_name)
        if sub_col is None:
            sub_col = bpy.data.collections.get(sub_col_name)
            if sub_col is None:
                sub_col = bpy.data.collections.new(sub_col_name)
                mo_col.children.link(sub_col)
            sub_col_cache[sub_col_name] = sub_col

        for entry in container_data['items']:
            name = entry['name']
            safe_name = re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_') or 'unnamed'
            ik_short = entry['item_key'][-4:].upper() if len(entry['item_key']) > 3 else entry['item_key']
            obj_name = f"MO_{safe_name}_{ik_short}"

            obj = bpy.data.objects.new(obj_name, None)
            obj.empty_display_type = 'PLAIN_AXES'
            obj.empty_display_size = 50.0

            # Apply transform
            tv = entry['transform']
            if tv:
                obj.location = _extract_location(tv)
                obj.rotation_euler = _extract_rotation(tv)
                obj.scale = _extract_scale(tv)
            else:
                obj.location = (0.0, 0.0, 0.0)

            sub_col.objects.link(obj)

            # Custom properties
            obj["is_map_object"] = True
            obj["map_object_name"] = name
            obj["map_object_type"] = entry['type']
            obj["map_object_container"] = cname
            obj["map_object_container_hash"] = entry['container_hash']
            obj["map_object_item_key"] = entry['item_key']
            obj["map_object_materials_path"] = materials_path
            obj["_original_transform"] = json.dumps(tv) if tv else "[]"

            imported += 1

        if log:
            log.info("MapObjects", f"  Container '{short_cname}': {len(container_data['items'])} objects")

    if log:
        log.info("MapObjects", f"Imported {imported} GdsMapObject(s)")

    return imported


# ============================================================================
# Export
# ============================================================================

def collect_map_objects(context, selected_only=False):
    """Collect GdsMapObject Blender objects (is_map_object=True)."""
    source = context.selected_objects if selected_only else context.scene.objects
    return [o for o in source if o.get("is_map_object", False)]


def update_bin_map_objects(entries: list) -> int:
    """Update GdsMapObject transforms in parsed MPC bin entries from Blender objects.

    Iterates MPC entries, finds GdsMapObject items, and matches them
    to Blender objects by item_key. Returns number of items updated.
    """
    mpc_hex = f"0x{_TYPE_MPC:08x}"
    class_hex = f"0x{_CLASS_GDS_MAP_OBJECT:08x}"

    objs = collect_map_objects(bpy.context, selected_only=False)
    if not objs:
        return 0

    # Build lookup: item_key → Blender object
    lookup = {}
    for obj in objs:
        ik = obj.get("map_object_item_key", "")
        if ik:
            lookup[ik.lower()] = obj

    updated = 0

    for entry in entries:
        if entry.get('type_hash') != mpc_hex:
            continue

        fields = entry.get('fields', [])
        items_f = _get_field_by_hash(fields, _HASH_ITEMS)
        if not items_f:
            continue

        pairs = items_f.get('pairs', [])
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            value = pair.get('value', {})
            if not isinstance(value, dict):
                continue
            if value.get('class_hash') != class_hex:
                continue

            # Get item key for matching
            pair_key = pair.get('key', {})
            item_key = ''
            if isinstance(pair_key, dict):
                item_key = str(pair_key.get('value', ''))
            elif isinstance(pair_key, str):
                item_key = pair_key

            obj = lookup.get(item_key.lower())
            if not obj:
                continue

            item_fields = value.get('fields', [])
            if not item_fields:
                continue

            # Update transform
            for f in item_fields:
                if _field_hash(f) == _HASH_TRANSFORM:
                    new_mtx = _blender_to_transform(obj)
                    if f.get('value') != new_mtx:
                        f['value'] = new_mtx
                        updated += 1
                    break

            # Update name
            new_name = obj.get("map_object_name", "")
            if new_name:
                for f in item_fields:
                    if _field_hash(f) == _HASH_NAME:
                        if f.get('value') != new_name:
                            f['value'] = new_name
                        break

            # Update type
            new_type = obj.get("map_object_type")
            if new_type is not None:
                for f in item_fields:
                    if _field_hash(f) == _HASH_TYPE:
                        try:
                            new_val = int(new_type)
                        except (ValueError, TypeError):
                            break
                        if f.get('value') != new_val:
                            f['value'] = new_val
                        break

    return updated
