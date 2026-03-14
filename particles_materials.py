"""
Particle import/export helpers for materials.py

Handles two distinct entry types:
1. VfxSystemDefinitionData  - top-level VFX definitions stored as JSON on mesh objects
2. MapPlaceableContainer    - groups of placed MapParticle / 0x1f1f50f2 items,
                              each container becomes a Blender sub-collection
"""

import bpy
import json
import math
import os
import re
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PARTICLE_ITEM_TYPES = {"MapParticle", "0x1f1f50f2"}
_VFX_DEF_TYPE = "VfxSystemDefinitionData"
_CONTAINER_TYPE = "MapPlaceableContainer"

# ---------------------------------------------------------------------------
# Shared cube mesh
# ---------------------------------------------------------------------------

_CUBE_MESH_NAME = "Particle_Cube_Preview"


def _get_or_create_cube_mesh(size=0.5):
    mesh = bpy.data.meshes.get(_CUBE_MESH_NAME)
    if mesh is not None:
        return mesh
    mesh = bpy.data.meshes.new(_CUBE_MESH_NAME)
    h = size * 0.5
    verts = [
        (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
        (-h, -h,  h), (h, -h,  h), (h, h,  h), (-h, h,  h),
    ]
    faces = [
        (0, 1, 2, 3), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


# ===================================================================
# PARSING
# ===================================================================

def _find_brace_end(text, start):
    """Return the index of the matching closing brace, or -1."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_materials_py_full(materials_py_path):
    """Parse VfxSystemDefinitionData and MapPlaceableContainer entries.

    Returns dict with 'vfx_definitions' and 'containers'.
    """
    result = {'vfx_definitions': [], 'containers': []}

    try:
        with open(materials_py_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return result

    entry_re = re.compile(
        r'^    (?:"([^"]+)"|(0x[0-9a-fA-F]+))\s*=\s*(\w+)\s*\{',
        re.MULTILINE
    )

    for m in entry_re.finditer(content):
        entry_name = m.group(1) if m.group(1) else m.group(2)
        entry_type = m.group(3)
        brace_start = m.end() - 1
        brace_end = _find_brace_end(content, brace_start)
        if brace_end < 0:
            continue
        block_text = content[m.start():brace_end + 1]

        if entry_type == _VFX_DEF_TYPE:
            result['vfx_definitions'].append({
                'name': entry_name,
                'block_text': block_text,
            })

        elif entry_type == _CONTAINER_TYPE:
            container = {
                'container_name': entry_name,
                'block_text': block_text,
                'items': [],
            }
            _parse_container_items(block_text, container['items'])
            result['containers'].append(container)

    return result


def _parse_container_items(container_block, items_list):
    """Extract MapParticle / 0x1f1f50f2 items from a MapPlaceableContainer."""
    item_re = re.compile(
        r'(0x[0-9a-fA-F]+)\s*=\s*(MapParticle|0x1f1f50f2)\s*\{'
    )
    for m in item_re.finditer(container_block):
        entry_hash = m.group(1).lower()
        entry_kind = m.group(2)
        brace_start = m.end() - 1
        brace_end = _find_brace_end(container_block, brace_start)
        if brace_end < 0:
            continue
        item_text = container_block[m.start():brace_end + 1]

        transform_values = _extract_transform(item_text)

        visibility_flags = None
        vis_flags_match = re.search(r'mVisibilityFlags\s*:\s*u8\s*=\s*(\d+)', item_text)
        if vis_flags_match:
            try:
                visibility_flags = int(vis_flags_match.group(1))
            except Exception:
                visibility_flags = None

        visibility_controller = ""
        vis_ctrl_match = re.search(
            r'VisibilityController\s*:\s*link\s*=\s*(?:"([^"]+)"|(0x[0-9a-fA-F]+))',
            item_text,
        )
        if vis_ctrl_match:
            visibility_controller = (vis_ctrl_match.group(1) or vis_ctrl_match.group(2) or "").strip()

        sys_match = re.search(r'system\s*:\s*link\s*=\s*"([^"]+)"', item_text)
        system_link = sys_match.group(1) if sys_match else ""

        name_kind = 'string'
        name_value = ''
        ns = re.search(r'name\s*:\s*string\s*=\s*"([^"]*)"', item_text)
        nh = re.search(r'name\s*:\s*hash\s*=\s*(0x[0-9a-fA-F]+)', item_text)
        if ns:
            name_kind = 'string'
            name_value = ns.group(1)
        elif nh:
            name_kind = 'hash'
            name_value = nh.group(1).lower()

        items_list.append({
            'entry_hash': entry_hash,
            'entry_kind': entry_kind,
            'name_kind': name_kind,
            'name_value': name_value,
            'system': system_link,
            'transform_values': transform_values,
            'visibility_flags': visibility_flags,
            'visibility_controller': visibility_controller,
            'block_text': item_text,
        })


def _extract_transform(text):
    """Extract 16 floats from transform: mtx44 block."""
    tm = re.search(r'transform\s*:\s*mtx44\s*=\s*\{(.*?)\}', text, re.DOTALL)
    if not tm:
        return []
    return [float(v) for v in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', tm.group(1))]


# Legacy compat wrapper
def parse_materials_py_map_particles(materials_py_path):
    """Return flat list of all MapParticle / 0x1f1f50f2 items across all containers."""
    parsed = parse_materials_py_full(materials_py_path)
    flat = []
    for container in parsed['containers']:
        for item in container['items']:
            flat.append(item)
    return flat


# ===================================================================
# BINARY .BIN PARSING
# ===================================================================

# Type hashes (FNV-1a 32-bit lowercase)
_BIN_TYPE_MAP_PLACEABLE_CONTAINER = 0xb25c0a3f  # MapPlaceableContainer
_BIN_TYPE_MAP_PARTICLE           = 0x592ef6c3   # MapParticle
_BIN_TYPE_MAP_PARTICLE_ALT       = 0x1f1f50f2   # Alternative MapParticle hash
_BIN_TYPE_VFX_SYSTEM_DEF         = 0x45cd899f   # VfxSystemDefinitionData

# Field hashes
_BIN_HASH_NAME                   = 0x8d39bde6   # name
_BIN_HASH_ITEMS                  = 0x3a79338f   # items
_BIN_HASH_SYSTEM                 = 0x491e0a9c   # system
_BIN_HASH_TRANSFORM              = 0xe1ad931b   # transform
_BIN_HASH_VISIBILITY_FLAGS       = 0xccf79327   # mVisibilityFlags
_BIN_HASH_VISIBILITY_CONTROLLER  = 0x5150a6a1   # VisibilityController

_BIN_PARTICLE_TYPE_HASHES = {_BIN_TYPE_MAP_PARTICLE, _BIN_TYPE_MAP_PARTICLE_ALT}


def _bin_get_field(fields, name_hash_int):
    """Get a field from a list of propertybin fields by its hash."""
    if not fields:
        return None
    for f in fields:
        if f.get('name_hash_int') == name_hash_int:
            return f
    return None


def _bin_get_embedded_field(fields, name_hash_int):
    """Get an embedded/nested field (may have value or fields sub-key)."""
    if not fields:
        return None
    for f in fields:
        h = f.get('name_hash_int', 0)
        if not h:
            hs = f.get('name_hash', '')
            if hs.startswith('0x'):
                try:
                    h = int(hs, 16)
                except ValueError:
                    pass
        if h == name_hash_int:
            return f
    return None


def _bin_extract_transform(fields):
    """Extract 16 floats from a transform mtx44 field."""
    tf = _bin_get_embedded_field(fields, _BIN_HASH_TRANSFORM)
    if not tf:
        return []
    val = tf.get('value')
    if isinstance(val, (list, tuple)):
        # Flatten nested lists if needed
        result = []
        for v in val:
            if isinstance(v, (list, tuple)):
                result.extend(v)
            else:
                result.append(float(v))
        return result
    return []


def parse_materials_bin_full(bin_path):
    """Parse VfxSystemDefinitionData and MapPlaceableContainer entries from a .bin file.
    
    Returns dict with 'vfx_definitions' and 'containers' in the same format
    as parse_materials_py_full().
    """
    result = {'vfx_definitions': [], 'containers': []}

    try:
        from . import propertybin_parser
        data = propertybin_parser.parse_bin(bin_path)
    except Exception as e:
        print(f"[Particles] Failed to parse bin: {e}")
        return result

    for entry in data.get('entries', []):
        type_hash_str = entry.get('type_hash', '')
        try:
            type_hash_int = int(type_hash_str, 16) if type_hash_str.startswith('0x') else 0
        except ValueError:
            continue

        path_hash = entry.get('path_hash', '')
        fields = entry.get('fields', [])

        if type_hash_int == _BIN_TYPE_VFX_SYSTEM_DEF:
            # VfxSystemDefinitionData — extract name
            name_f = _bin_get_field(fields, _BIN_HASH_NAME)
            vfx_name = name_f['value'] if name_f else path_hash
            result['vfx_definitions'].append({
                'name': vfx_name,
                'entry_hash': path_hash,
                'entry_type_hash': type_hash_str,
                'block_text': '',  # No text repr for .bin — store entry data as custom prop later
                'bin_entry': entry,
            })

        elif type_hash_int == _BIN_TYPE_MAP_PLACEABLE_CONTAINER:
            # MapPlaceableContainer — extract items
            name_f = _bin_get_field(fields, _BIN_HASH_NAME)
            container_name = name_f['value'] if name_f else path_hash

            container = {
                'container_name': container_name,
                'container_hash': path_hash,
                'block_text': '',
                'items': [],
            }

            items_f = _bin_get_field(fields, _BIN_HASH_ITEMS)
            if items_f:
                # The items field can be type 134 (map) with 'pairs'
                # or a list type with 'values'.  Handle both.
                if 'pairs' in items_f:
                    # Map field (type 134): each pair has {key, value}
                    # where value is the embedded struct
                    pair_values = [
                        (p.get('key', {}), p.get('value', {}))
                        for p in items_f['pairs']
                        if isinstance(p, dict) and 'value' in p
                    ]
                else:
                    pair_values = [({}, v) for v in items_f.get('values', [])]

                for pair_key, item_struct in pair_values:
                    # Each item is an embedded struct with class_hash and fields
                    item_class = item_struct.get('class_hash', '')
                    item_fields = item_struct.get('fields', [])
                    if item_fields is None:
                        continue

                    try:
                        item_class_int = int(item_class, 16) if item_class and item_class.startswith('0x') else 0
                    except ValueError:
                        item_class_int = 0

                    # Only process known MapParticle types
                    if item_class_int not in _BIN_PARTICLE_TYPE_HASHES:
                        continue

                    # Extract fields
                    name_f2 = _bin_get_embedded_field(item_fields, _BIN_HASH_NAME)
                    system_f = _bin_get_embedded_field(item_fields, _BIN_HASH_SYSTEM)
                    vis_flags_f = _bin_get_embedded_field(item_fields, _BIN_HASH_VISIBILITY_FLAGS)
                    vis_ctrl_f = _bin_get_embedded_field(item_fields, _BIN_HASH_VISIBILITY_CONTROLLER)

                    name_value = ''
                    name_kind = 'string'
                    if name_f2:
                        nv = name_f2.get('value', '')
                        if isinstance(nv, str):
                            if nv.startswith('0x'):
                                name_kind = 'hash'
                                name_value = nv.lower()
                            else:
                                name_value = nv

                    system_link = ''
                    if system_f:
                        sv = system_f.get('value', '')
                        system_link = str(sv) if sv else ''

                    transform_values = _bin_extract_transform(item_fields)

                    visibility_flags = None
                    if vis_flags_f:
                        vf = vis_flags_f.get('value')
                        if vf is not None:
                            visibility_flags = int(vf)

                    visibility_controller = ''
                    if vis_ctrl_f:
                        vc = vis_ctrl_f.get('value', '')
                        visibility_controller = str(vc) if vc else ''

                    # Prefer the map key hash (stable) as entry_hash.
                    entry_hash = ''
                    if isinstance(pair_key, dict):
                        kv = pair_key.get('value', '')
                        if kv:
                            entry_hash = str(kv).lower()
                    if not entry_hash:
                        # Fallback for list-typed items
                        entry_hash = f"0x{hash(str(item_struct)) & 0xFFFFFFFF:08x}"

                    container['items'].append({
                        'entry_hash': entry_hash,
                        'entry_kind': f"0x{item_class_int:08x}" if item_class_int else 'MapParticle',
                        'name_kind': name_kind,
                        'name_value': name_value,
                        'system': system_link,
                        'transform_values': transform_values,
                        'visibility_flags': visibility_flags,
                        'visibility_controller': visibility_controller,
                        'block_text': '',
                    })

            result['containers'].append(container)

    vfx_count = len(result['vfx_definitions'])
    item_count = sum(len(c['items']) for c in result['containers'])
    if vfx_count or item_count:
        print(f"[Particles] Parsed from .bin: {vfx_count} VFX defs, {len(result['containers'])} containers, {item_count} particles")

    return result


def parse_materials_full(materials_path):
    """Parse particle data from a .bin materials file.
    
    Returns dict with 'vfx_definitions' and 'containers'.
    """
    if not materials_path or not os.path.exists(materials_path):
        return {'vfx_definitions': [], 'containers': []}
    
    return parse_materials_bin_full(materials_path)


# ===================================================================
# TRANSFORM Helpers
# ===================================================================

def extract_particle_location_from_transform(transform_values):
    """Game (tx, ty, tz) -> Blender (tx, tz, ty)."""
    if not transform_values or len(transform_values) < 15:
        return (0.0, 0.0, 0.0)
    tx = transform_values[12]
    ty = transform_values[13]
    tz = transform_values[14]
    return (tx, tz, ty)


def extract_particle_scale_from_transform(transform_values):
    """Extract per-axis scale from mtx44 diagonal, Y/Z swap."""
    if not transform_values or len(transform_values) < 11:
        return (1.0, 1.0, 1.0)
    sx = transform_values[0]
    sy = transform_values[5]
    sz = transform_values[10]
    return (sx, sz, sy)


def extract_particle_rotation_from_transform(transform_values):
    """Extract rotation from game mtx44 → Blender Euler (XYZ).
    
    Uses the same conversion matrix approach as mapgeo import:
    mat_blender = conversion @ mat_league @ conversion
    where conversion swaps Y↔Z axes.
    """
    if not transform_values or len(transform_values) < 12:
        return (0.0, 0.0, 0.0)
    
    from mathutils import Matrix
    
    tv = transform_values
    # Build row-major 4x4 from column-major flat list (rotation part only)
    mat_league = Matrix((
        (tv[0],  tv[4],  tv[8],  0),
        (tv[1],  tv[5],  tv[9],  0),
        (tv[2],  tv[6],  tv[10], 0),
        (0,      0,      0,      1)
    ))
    
    # Y↔Z coordinate conversion (self-inverse)
    conversion = Matrix((
        (1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 1, 0, 0),
        (0, 0, 0, 1)
    ))
    
    mat_blender = conversion @ mat_league @ conversion
    _loc, rot_quat, _scale = mat_blender.decompose()
    euler = rot_quat.to_euler('XYZ')
    return (euler.x, euler.y, euler.z)


# ===================================================================
# IMPORT
# ===================================================================

def import_particles_from_materials(
    context,
    materials_path,
    cube_size=0.5,
    root_collection_name=None,
    log=None,
):
    """Import VfxSystemDefinitionData and MapParticle entries from .py or .bin.

    Creates:
      root_Particles/
          _VFX_Definitions/        - one cube per VfxSystemDefinitionData
          <ContainerShortName>/    - one cube per MapParticle
    """
    if not materials_path or not os.path.exists(materials_path):
        return 0

    if log:
        log.info("Particles", f"Parsing {os.path.basename(materials_path)}")

    parsed = parse_materials_full(materials_path)
    is_bin = materials_path.lower().endswith('.bin')
    vfx_count = len(parsed['vfx_definitions'])
    container_count = len(parsed['containers'])
    item_count = sum(len(c['items']) for c in parsed['containers'])

    if vfx_count == 0 and item_count == 0:
        if log:
            log.info("Particles", "No VFX definitions or MapParticle entries found")
        return 0

    if log:
        log.info("Particles", f"Found {vfx_count} VFX defs, {container_count} containers, {item_count} placed particles")

    # --- Hash resolution setup ---
    _resolve_entry = None
    _resolve_type = None
    _resolve_any = None
    try:
        from . import community_hashes
        _resolve_entry = community_hashes.resolve_entry
        _resolve_type = community_hashes.resolve_type
        _resolve_any = community_hashes.resolve
    except Exception:
        pass

    def _try_resolve(hash_str, resolver):
        """Attempt to resolve a 0x... hash string, return resolved or original."""
        if not resolver or not hash_str or not hash_str.startswith('0x'):
            return hash_str
        try:
            return resolver(int(hash_str, 16)) or hash_str
        except (ValueError, TypeError):
            return hash_str

    # Build VFX entry_hash → name lookup for cross-referencing system links
    _vfx_name_lookup = {}
    for vd in parsed['vfx_definitions']:
        eh = vd.get('entry_hash', '')
        nm = vd.get('name', '')
        if eh and nm:
            _vfx_name_lookup[eh.lower()] = nm

    # Pre-resolve VFX definition names that are still hashes
    for vd in parsed['vfx_definitions']:
        nm = vd.get('name', '')
        if nm.startswith('0x'):
            resolved = _try_resolve(nm, _resolve_entry)
            if resolved != nm:
                vd['name'] = resolved
                _vfx_name_lookup[vd.get('entry_hash', '').lower()] = resolved

    # Pre-resolve container names and particle fields
    for container in parsed['containers']:
        cn = container.get('container_name', '')
        if cn.startswith('0x'):
            resolved = _try_resolve(cn, _resolve_entry)
            if resolved != cn:
                container['container_name'] = resolved
        for item in container.get('items', []):
            # Resolve system link via VFX lookup, then community_hashes
            sys_val = item.get('system', '')
            if sys_val.startswith('0x'):
                vfx_resolved = _vfx_name_lookup.get(sys_val.lower())
                if vfx_resolved:
                    item['system'] = vfx_resolved
                else:
                    entry_resolved = _try_resolve(sys_val, _resolve_entry)
                    if entry_resolved != sys_val:
                        item['system'] = entry_resolved
            # Resolve name_value when it's a hash
            if item.get('name_kind') == 'hash' and item.get('name_value', '').startswith('0x'):
                resolved = _try_resolve(item['name_value'], _resolve_any)
                if resolved != item['name_value']:
                    item['name_value'] = resolved
                    item['name_kind'] = 'resolved'
            # Resolve entry_kind type hash
            ek = item.get('entry_kind', '')
            if ek.startswith('0x'):
                resolved = _try_resolve(ek, _resolve_type)
                if resolved != ek:
                    item['entry_kind'] = resolved

    baron_parser = None
    baron_decode_cache = {}
    try:
        from . import baron_hash_parser
        baron_parser = baron_hash_parser.MaterialsBinParser(materials_path)
    except Exception:
        baron_parser = None

    cube_mesh = _get_or_create_cube_mesh(cube_size)

    # Root collections
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

    particles_col_name = f"{root_name}_Particles"
    particles_col = bpy.data.collections.get(particles_col_name)
    if particles_col is None:
        particles_col = bpy.data.collections.new(particles_col_name)
        root_col.children.link(particles_col)

    imported = 0
    total = vfx_count + item_count
    wm = context.window_manager
    wm.progress_begin(0, max(total, 1))

    try:
        # --- 1) VFX Raw Particles (use cube mesh — few objects) ---
        if vfx_count > 0:
            vfx_col_name = f"{particles_col_name}_VFX_Definitions"
            vfx_col = bpy.data.collections.get(vfx_col_name)
            if vfx_col is None:
                vfx_col = bpy.data.collections.new(vfx_col_name)
                particles_col.children.link(vfx_col)

            for vfx_def in parsed['vfx_definitions']:
                vfx_name = vfx_def['name']
                short_name = vfx_name.rsplit('/', 1)[-1] if '/' in vfx_name else vfx_name
                safe_name = re.sub(r'[^A-Za-z0-9_]+', '_', short_name)
                # Trim trailing underscores from sanitization
                safe_name = safe_name.strip('_') or safe_name

                obj = bpy.data.objects.new(f"VFX_{safe_name}", cube_mesh)
                vfx_col.objects.link(obj)

                obj["is_vfx_definition"] = True
                obj["vfx_name"] = vfx_name
                obj["vfx_type"] = _VFX_DEF_TYPE
                obj["vfx_block_text"] = vfx_def['block_text']
                if vfx_def.get('entry_hash'):
                    obj["vfx_entry_hash"] = str(vfx_def['entry_hash'])
                if vfx_def.get('entry_type_hash'):
                    obj["vfx_entry_type_hash"] = str(vfx_def['entry_type_hash'])
                bin_entry = vfx_def.get('bin_entry')
                if isinstance(bin_entry, dict):
                    try:
                        fields_str = json.dumps(bin_entry.get('fields', []))
                        obj["vfx_fields_json"] = fields_str
                        obj["_vfx_fields_snapshot"] = fields_str
                    except Exception:
                        pass
                obj["particle_source"] = "materials_bin" if is_bin else "materials_py"
                obj["particle_materials_path"] = materials_path

                imported += 1
                if imported % 100 == 0 or imported == total:
                    if log:
                        log.info("Particles", f"Progress: {imported}/{total}")
                    wm.progress_update(imported)

            if log:
                log.info("Particles", f"VFX definitions: {vfx_count} imported")

        # --- 2) MapParticles grouped by container (use Empties — fast) ---
        for container in parsed['containers']:
            cname = container['container_name']
            short_cname = cname.rsplit('/', 1)[-1] if '/' in cname else cname
            safe_cname = re.sub(r'[^A-Za-z0-9_]+', '_', short_cname)

            sub_col_name = f"{particles_col_name}_{safe_cname}"
            sub_col = bpy.data.collections.get(sub_col_name)
            if sub_col is None:
                sub_col = bpy.data.collections.new(sub_col_name)
                particles_col.children.link(sub_col)

            for item in container['items']:
                system = item.get('system', '')
                stem = system.rsplit('/', 1)[-1] if system else item['entry_hash']
                safe_stem = re.sub(r'[^A-Za-z0-9_]+', '_', stem).strip('_') or stem
                eh_short = item['entry_hash'][2:6].upper() if len(item['entry_hash']) > 5 else item['entry_hash']
                obj_name = f"MP_{safe_stem}_{eh_short}"

                # Empty objects are much faster than mesh objects for bulk import
                obj = bpy.data.objects.new(obj_name, None)
                obj.empty_display_type = 'SPHERE'
                obj.empty_display_size = cube_size
                obj.location = extract_particle_location_from_transform(
                    item.get('transform_values', [])
                )
                raw_scale = extract_particle_scale_from_transform(
                    item.get('transform_values', [])
                )
                obj.scale = (50.0, 50.0, 50.0)
                obj.rotation_euler = extract_particle_rotation_from_transform(
                    item.get('transform_values', [])
                )

                sub_col.objects.link(obj)

                # Store original transform for dirty tracking
                obj["_original_transform"] = json.dumps(
                    item.get('transform_values', [])
                )

                obj["is_particle_system"] = True
                obj["particle_source"] = "materials_bin" if is_bin else "materials_py"
                obj["particle_materials_path"] = materials_path
                obj["particle_entry_hash"] = item['entry_hash']
                obj["particle_entry_kind"] = item['entry_kind']
                obj["particle_system"] = system
                obj["particle_name_kind"] = item['name_kind']
                obj["particle_name_value"] = item['name_value']
                obj["particle_block_text"] = item['block_text']
                obj["particle_container"] = cname
                if container.get('container_hash'):
                    obj["particle_container_hash"] = str(container['container_hash']).lower()
                obj["particle_container_short"] = short_cname

                visibility_flags = item.get('visibility_flags')
                visibility_controller = item.get('visibility_controller', '')
                if visibility_flags is not None:
                    obj["particle_visibility_flags"] = int(visibility_flags)
                    obj["visibility_layer"] = int(visibility_flags)

                if visibility_controller:
                    ctrl_clean = visibility_controller.strip().lower()
                    if ctrl_clean.startswith("0x"):
                        ctrl_clean = ctrl_clean[2:]
                    obj["particle_visibility_controller"] = ctrl_clean.upper()
                    obj["baron_hash"] = ctrl_clean.upper()

                    if baron_parser:
                        if ctrl_clean in baron_decode_cache:
                            decoded = baron_decode_cache[ctrl_clean]
                        else:
                            try:
                                decoded = baron_parser.decode_baron_hash(ctrl_clean)
                            except Exception:
                                decoded = None
                            baron_decode_cache[ctrl_clean] = decoded

                        if decoded is not None:
                            if getattr(decoded, 'baron_layers', None):
                                obj["baron_layers_decoded"] = str(sorted(list(decoded.baron_layers)))
                            if getattr(decoded, 'dragon_layers', None):
                                obj["baron_dragon_layers_decoded"] = str(sorted(list(decoded.dragon_layers)))
                            obj["baron_parent_mode"] = int(getattr(decoded, 'parent_mode', 1) or 1)

                imported += 1
                if imported % 100 == 0 or imported == total:
                    if log:
                        log.info("Particles", f"Progress: {imported}/{total}")
                    wm.progress_update(imported)

            if log:
                log.info("Particles", f"  Container '{short_cname}': {len(container['items'])} items")

    finally:
        wm.progress_end()

    if log:
        log.info("Particles", f"Import complete: {imported} objects")
    return imported


# Backward-compat alias
import_particles_from_materials_py = import_particles_from_materials


# ===================================================================
# EXPORT helpers
# ===================================================================

def collect_particle_objects(context, selected_only=False):
    """Collect MapParticle objects (is_particle_system=True). Works with mesh or empty."""
    source = context.selected_objects if selected_only else context.scene.objects
    return [o for o in source if o.get("is_particle_system", False)]


def collect_vfx_definition_objects(context, selected_only=False):
    """Collect VfxSystemDefinitionData objects (is_vfx_definition=True)."""
    source = context.selected_objects if selected_only else context.scene.objects
    return [o for o in source if o.get("is_vfx_definition", False)]


def _normalize_entry_hash(entry_hash, idx):
    if not entry_hash:
        return f"0x{(0x90000000 + idx):08x}"
    if isinstance(entry_hash, int):
        return f"0x{entry_hash:08x}"
    return str(entry_hash).lower()


def _build_game_matrix_text(location, scale, rotation=None):
    """Build the 4-row mtx44 text block for a game transform matrix.
    
    Converts Blender location/rotation/scale to game coordinates using
    the same conversion matrix approach as mapgeo export.
    """
    from mathutils import Matrix, Euler

    loc_x, loc_y, loc_z = location[0], location[1], location[2]
    scl_x, scl_y, scl_z = scale[0], scale[1], scale[2]

    # Build Blender 4x4 matrix
    if rotation and any(abs(r) > 1e-7 for r in rotation):
        rot_euler = Euler((rotation[0], rotation[1], rotation[2]), 'XYZ')
        mat_rot = rot_euler.to_matrix().to_4x4()
    else:
        mat_rot = Matrix.Identity(4)

    mat_loc = Matrix.Translation((loc_x, loc_y, loc_z))
    mat_scale = Matrix.Diagonal((scl_x, scl_y, scl_z, 1.0))
    mat_blender = mat_loc @ mat_rot @ mat_scale

    # Y↔Z coordinate conversion (self-inverse)
    conversion = Matrix((
        (1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 1, 0, 0),
        (0, 0, 0, 1)
    ))
    mat_league = conversion @ mat_blender @ conversion

    # Flatten to column-major
    m = [
        mat_league[0][0], mat_league[1][0], mat_league[2][0], mat_league[3][0],
        mat_league[0][1], mat_league[1][1], mat_league[2][1], mat_league[3][1],
        mat_league[0][2], mat_league[1][2], mat_league[2][2], mat_league[3][2],
        mat_league[0][3], mat_league[1][3], mat_league[2][3], mat_league[3][3],
    ]

    # Format as 4 rows (column-major → row 0 is m[0,4,8,12] etc.)
    return (
        f"{m[0]:.4f}, {m[4]:.4f}, {m[8]:.4f}, {m[12]:.4f}\n"
        f"                    {m[1]:.4f}, {m[5]:.4f}, {m[9]:.4f}, {m[13]:.4f}\n"
        f"                    {m[2]:.4f}, {m[6]:.4f}, {m[10]:.4f}, {m[14]:.4f}\n"
        f"                    {m[3]:.4f}, {m[7]:.4f}, {m[11]:.4f}, {m[15]:.4f}"
    )


def build_particle_entry_text(
    entry_hash,
    entry_kind,
    location,
    scale,
    system_link,
    name_kind,
    name_value,
    visibility_flags=None,
    visibility_controller="",
    rotation=None,
):
    """Build materials.py text for a single MapParticle / 0x1f1f50f2 item."""
    mtx_text = _build_game_matrix_text(location, scale, rotation)

    if entry_kind == '0x1f1f50f2':
        name_hash = name_value if (name_kind == 'hash' and name_value) else '0x00000000'
        vis_flags_line = f"                mVisibilityFlags: u8 = {int(visibility_flags)}\n" if visibility_flags is not None else ""
        vis_ctrl_line = f"                VisibilityController: link = {visibility_controller}\n" if visibility_controller else ""
        return (
            f"{entry_hash} = 0x1f1f50f2 {{\n"
            f"                transform: mtx44 = {{\n"
            f"                    {mtx_text}\n"
            f"                }}\n"
            f"                name: hash = {name_hash}\n"
            f"{vis_flags_line}"
            f"                0xbbe68da1: bool = false\n"
            f"                Vfx: embed = 0x82b49579 {{\n"
            f"                    system: link = \"{system_link}\"\n"
            f"                }}\n"
            f"{vis_ctrl_line}"
            f"            }}"
        )

    name_string = name_value if (name_kind == 'string' and name_value) else system_link.rsplit('/', 1)[-1]
    vis_flags_line = f"                mVisibilityFlags: u8 = {int(visibility_flags)}\n" if visibility_flags is not None else ""
    vis_ctrl_line = f"                VisibilityController: link = {visibility_controller}\n" if visibility_controller else ""
    return (
        f"{entry_hash} = MapParticle {{\n"
        f"                transform: mtx44 = {{\n"
        f"                    {mtx_text}\n"
        f"                }}\n"
        f"                name: string = \"{name_string}\"\n"
        f"{vis_flags_line}"
        f"                system: link = \"{system_link}\"\n"
        f"{vis_ctrl_line}"
        f"            }}"
    )


def build_particle_snippet(
    entry_hash,
    entry_kind,
    location,
    scale,
    system_link,
    name_kind,
    name_value,
    visibility_flags=None,
    visibility_controller="",
    rotation=None,
):
    """Build snippet for manual export display."""
    raw_text = build_particle_entry_text(
        entry_hash,
        entry_kind,
        location,
        scale,
        system_link,
        name_kind,
        name_value,
        visibility_flags=visibility_flags,
        visibility_controller=visibility_controller,
        rotation=rotation,
    )
    lines = raw_text.split('\n')
    if not lines:
        return raw_text
    snippet_lines = [f"    {lines[0]}"]
    snippet_lines.extend(lines[1:])
    return "\n".join(snippet_lines)


def build_particle_export_entries(particle_objects):
    """Build export data for MapParticle objects."""
    export_entries = []
    for idx, obj in enumerate(particle_objects):
        system_link = obj.get("particle_system", "")
        if not system_link:
            continue
        entry_hash = _normalize_entry_hash(obj.get("particle_entry_hash"), idx)
        entry_kind = obj.get("particle_entry_kind", "MapParticle")
        name_kind = obj.get("particle_name_kind", "string")
        name_value = obj.get("particle_name_value", "")
        export_entries.append({
            "entry_hash": entry_hash,
            "entry_kind": entry_kind,
            "system": system_link,
            "name_kind": name_kind,
            "name_value": name_value,
            "location": list(obj.location),
            "scale": [1.0, 1.0, 1.0],  # Display scale is visual-only, export identity
            "rotation_euler": list(obj.rotation_euler),
            "container": obj.get("particle_container", ""),
            "visibility_flags": obj.get("particle_visibility_flags", obj.get("visibility_layer", None)),
            "visibility_controller": obj.get("particle_visibility_controller", obj.get("baron_hash", "")),
        })
    return export_entries


def build_particle_material_map(particle_objects):
    """Build system->material mapping for particle objects."""
    material_map = {}
    for obj in particle_objects:
        if not obj.active_material:
            continue
        entry_hash = _normalize_entry_hash(obj.get("particle_entry_hash"), 0)
        system_link = obj.get("particle_system", "")
        stem = system_link.rsplit('/', 1)[-1] if system_link else ""
        material_map[entry_hash] = obj.active_material.name
        if system_link:
            material_map[system_link] = obj.active_material.name
        if stem:
            material_map[stem] = obj.active_material.name
    return material_map


def update_other_entries_with_particles(other_entries, entry_order, context=None, particle_objects=None):
    """Inject/replace particle container + VFX entries into other_entries for export.

    Rebuilds MapPlaceableContainer blocks from Blender object state.
    Preserves VFX definition blocks from is_vfx_definition objects.
    """
    context = context or bpy.context
    if particle_objects is None:
        particle_objects = collect_particle_objects(context, selected_only=False)
    vfx_objects = collect_vfx_definition_objects(context, selected_only=False)

    if not particle_objects and not vfx_objects:
        return other_entries, entry_order

    new_other = dict(other_entries) if isinstance(other_entries, dict) else {}

    # Remove old container/VFX entries
    for name, (etype, _) in list(new_other.items()):
        if etype in (_CONTAINER_TYPE, _VFX_DEF_TYPE):
            del new_other[name]

    # Rebuild VFX definitions
    vfx_entries_order = []
    for obj in sorted(vfx_objects, key=lambda o: o.name):
        vfx_name = obj.get("vfx_name", "")
        block_text = obj.get("vfx_block_text", "")
        if vfx_name and block_text:
            new_other[vfx_name] = (_VFX_DEF_TYPE, block_text)
            vfx_entries_order.append((vfx_name, _VFX_DEF_TYPE))

    # Rebuild MapPlaceableContainers
    containers_map = OrderedDict()
    for obj in sorted(particle_objects, key=lambda o: o.name):
        cname = obj.get("particle_container", "")
        if not cname:
            cname = "__ungrouped__"
        if cname not in containers_map:
            containers_map[cname] = []
        containers_map[cname].append(obj)

    container_entries_order = []
    for cname, objects in containers_map.items():
        lines = []
        indent = "    "
        if cname.startswith('"') or cname == "__ungrouped__":
            header_name = cname
        else:
            header_name = f'"{cname}"'
        lines.append(f'{indent}{header_name} = {_CONTAINER_TYPE} {{')
        lines.append(f'{indent}    items: map[hash,pointer] = {{')

        for obj in objects:
            eh = obj.get("particle_entry_hash", "0x00000000")
            ek = obj.get("particle_entry_kind", "MapParticle")
            system = obj.get("particle_system", "")
            nk = obj.get("particle_name_kind", "string")
            nv = obj.get("particle_name_value", "")
            vflags = obj.get("particle_visibility_flags", obj.get("visibility_layer", None))
            vctrl = obj.get("particle_visibility_controller", obj.get("baron_hash", ""))
            if isinstance(vctrl, str) and vctrl:
                vctrl = vctrl.strip()
                if not vctrl.startswith("0x"):
                    vctrl = f"0x{vctrl.lower()}"
            item_text = build_particle_entry_text(
                eh,
                ek,
                obj.location,
                (1.0, 1.0, 1.0),  # Display scale is visual-only, export identity
                system,
                nk,
                nv,
                visibility_flags=vflags,
                visibility_controller=vctrl,
                rotation=tuple(obj.rotation_euler),
            )
            lines.append(f'{indent}        {item_text}')

        lines.append(f'{indent}    }}')
        lines.append(f'{indent}}}')

        container_block = '\n'.join(lines)
        key = cname if cname != "__ungrouped__" else "__particles_ungrouped__"
        new_other[key] = (_CONTAINER_TYPE, container_block)
        container_entries_order.append((key, _CONTAINER_TYPE))

    # Update entry_order
    if entry_order is not None:
        entry_order = [e for e in entry_order if e[1] not in (_CONTAINER_TYPE, _VFX_DEF_TYPE)]
        insert_idx = len(entry_order)
        entry_order[insert_idx:insert_idx] = vfx_entries_order + container_entries_order

    return new_other, entry_order