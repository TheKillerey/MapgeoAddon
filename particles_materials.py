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
    """Extract rotation from mtx44 matrix (upper 3x3, normalized).
    
    The mtx44 is stored in column-major order:
    - Columns 0,1,2: X, Y, Z basis vectors (with scale embedded)
    - Column 3: Translation
    
    Returns Euler angles (XYZ) with Y/Z swap for Blender coordinate system.
    """
    if not transform_values or len(transform_values) < 11:
        return (0.0, 0.0, 0.0)
    
    from mathutils import Matrix, Vector
    
    # Extract the 3x3 rotation+scale part (column-major to row-major for Blender)
    # Game matrix columns (column-major):
    # [0,1,2,3] = X axis column
    # [4,5,6,7] = Y axis column
    # [8,9,10,11] = Z axis column
    
    # Convert to Blender's row-major 3x3 matrix with Y/Z swap
    mat = Matrix((
        (transform_values[0], transform_values[4], transform_values[8]),   # Row 0: X components
        (transform_values[2], transform_values[6], transform_values[10]),  # Row 1: Z components (swapped with Y)
        (transform_values[1], transform_values[5], transform_values[9])    # Row 2: Y components (swapped with Z)
    ))
    
    # Decompose to remove scale and get pure rotation
    try:
        # Get scale magnitudes from column vectors
        scale_x = Vector((mat[0][0], mat[1][0], mat[2][0])).length
        scale_y = Vector((mat[0][1], mat[1][1], mat[2][1])).length
        scale_z = Vector((mat[0][2], mat[1][2], mat[2][2])).length
        
        # Normalize to get pure rotation matrix (avoid division by zero)
        if scale_x > 0.0001 and scale_y > 0.0001 and scale_z > 0.0001:
            rot_mat = Matrix((
                (mat[0][0]/scale_x, mat[0][1]/scale_y, mat[0][2]/scale_z),
                (mat[1][0]/scale_x, mat[1][1]/scale_y, mat[1][2]/scale_z),
                (mat[2][0]/scale_x, mat[2][1]/scale_y, mat[2][2]/scale_z)
            ))
            # Convert to Euler angles
            euler = rot_mat.to_euler('XYZ')
            return (euler.x, euler.y, euler.z)
    except:
        pass
    
    return (0.0, 0.0, 0.0)


# ===================================================================
# IMPORT
# ===================================================================

def import_particles_from_materials_py(
    context,
    materials_py_path,
    cube_size=0.5,
    root_collection_name=None,
    log=None,
):
    """Import VfxSystemDefinitionData and MapParticle entries.

    Creates:
      root_Particles/
          _VFX_Definitions/        - one cube per VfxSystemDefinitionData
          <ContainerShortName>/    - one cube per MapParticle
    """
    if not materials_py_path or not os.path.exists(materials_py_path):
        return 0

    if log:
        log.info("Particles", f"Parsing {os.path.basename(materials_py_path)}")

    parsed = parse_materials_py_full(materials_py_path)
    vfx_count = len(parsed['vfx_definitions'])
    container_count = len(parsed['containers'])
    item_count = sum(len(c['items']) for c in parsed['containers'])

    if vfx_count == 0 and item_count == 0:
        if log:
            log.info("Particles", "No VFX definitions or MapParticle entries found")
        return 0

    if log:
        log.info("Particles", f"Found {vfx_count} VFX defs, {container_count} containers, {item_count} placed particles")

    baron_parser = None
    baron_decode_cache = {}
    try:
        from . import baron_hash_parser
        baron_parser = baron_hash_parser.MaterialsBinParser(materials_py_path)
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

                obj = bpy.data.objects.new(f"VFX_{safe_name}", cube_mesh)
                vfx_col.objects.link(obj)

                obj["is_vfx_definition"] = True
                obj["vfx_name"] = vfx_name
                obj["vfx_type"] = _VFX_DEF_TYPE
                obj["vfx_block_text"] = vfx_def['block_text']
                obj["particle_source"] = "materials_py"
                obj["particle_materials_path"] = materials_py_path

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
                safe_stem = re.sub(r'[^A-Za-z0-9_]+', '_', stem)
                obj_name = f"MP_{safe_stem}_{item['entry_hash'][2:].upper()}"

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

                obj["is_particle_system"] = True
                obj["particle_source"] = "materials_py"
                obj["particle_materials_path"] = materials_py_path
                obj["particle_entry_hash"] = item['entry_hash']
                obj["particle_entry_kind"] = item['entry_kind']
                obj["particle_system"] = system
                obj["particle_name_kind"] = item['name_kind']
                obj["particle_name_value"] = item['name_value']
                obj["particle_block_text"] = item['block_text']
                obj["particle_container"] = cname
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
):
    """Build materials.py text for a single MapParticle / 0x1f1f50f2 item."""
    tx, by, bz = location[0], location[1], location[2]
    sx, sy, sz = scale[0], scale[1], scale[2]
    game_ty = bz
    game_tz = by
    game_sy = sz
    game_sz = sy

    if entry_kind == '0x1f1f50f2':
        name_hash = name_value if (name_kind == 'hash' and name_value) else '0x00000000'
        vis_flags_line = f"                mVisibilityFlags: u8 = {int(visibility_flags)}\n" if visibility_flags is not None else ""
        vis_ctrl_line = f"                VisibilityController: link = {visibility_controller}\n" if visibility_controller else ""
        return (
            f"{entry_hash} = 0x1f1f50f2 {{\n"
            f"                transform: mtx44 = {{\n"
            f"                    {sx:.4f}, 0, 0, 0\n"
            f"                    0, {game_sy:.4f}, 0, 0\n"
            f"                    0, 0, {game_sz:.4f}, 0\n"
            f"                    {tx:.4f}, {game_ty:.4f}, {game_tz:.4f}, 1\n"
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
        f"                    {sx:.4f}, 0, 0, 0\n"
        f"                    0, {game_sy:.4f}, 0, 0\n"
        f"                    0, 0, {game_sz:.4f}, 0\n"
        f"                    {tx:.4f}, {game_ty:.4f}, {game_tz:.4f}, 1\n"
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
            "scale": list(obj.scale),
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
                obj.scale,
                system,
                nk,
                nv,
                visibility_flags=vflags,
                visibility_controller=vctrl,
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