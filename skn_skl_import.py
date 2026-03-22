"""
League Tools – SKN/SKL Skinned Mesh + Skeleton Importer for Blender
Imports League of Legends .skn (SimpleSkin) and .skl (Skeleton/Rig) files.

SKN = SimpleSkin  – skinned mesh with bone weights
SKL = Skeleton    – bone hierarchy / rig

These are used for champion models, map creatures, minions, and other
animated objects in League of Legends.
"""

import bpy
import bmesh
import struct
import os
import math
from pathlib import Path
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, Panel, Operator, UIList
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Matrix, Quaternion

try:
    from .texture_utils import TexConverter, resolve_texture_path
except ImportError:
    try:
        from texture_utils import TexConverter, resolve_texture_path
    except ImportError:
        TexConverter = None
        resolve_texture_path = None


# ============================================================================
# Texture / Material Helpers
# ============================================================================

def _find_texture_in_folder(folder: Path, name_stem: str) -> str:
    """
    Search *folder* (and common sub-folders) for a texture whose stem
    matches *name_stem* (case-insensitive).  Returns the first hit or "".
    """
    search_dirs = [folder]
    for sub in ('textures', 'Textures', 'tex', 'Tex'):
        candidate = folder / sub
        if candidate.is_dir():
            search_dirs.append(candidate)
    # Also check parent (champion root may be one level up)
    parent = folder.parent
    if parent != folder:
        search_dirs.append(parent)
        for sub in ('textures', 'Textures', 'tex', 'Tex'):
            candidate = parent / sub
            if candidate.is_dir():
                search_dirs.append(candidate)

    needle = name_stem.lower()
    exts = ('.dds', '.png', '.tex', '.tga', '.jpg', '.bmp')

    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.stem.lower() == needle and f.suffix.lower() in exts:
                return str(f)
    return ""


def _collect_textures_in_folder(folder: Path) -> list:
    """
    Collect ALL texture files in *folder* and common sub-folders.
    Returns a list of Path objects sorted by preference (DDS > PNG > TEX).
    """
    exts = ('.dds', '.png', '.tex', '.tga', '.jpg', '.bmp')
    search_dirs = [folder]
    for sub in ('textures', 'Textures', 'tex', 'Tex'):
        candidate = folder / sub
        if candidate.is_dir():
            search_dirs.append(candidate)
    parent = folder.parent
    if parent != folder:
        search_dirs.append(parent)
        for sub in ('textures', 'Textures', 'tex', 'Tex'):
            candidate = parent / sub
            if candidate.is_dir():
                search_dirs.append(candidate)

    result = []
    seen = set()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() in exts and f.name.lower() not in seen:
                seen.add(f.name.lower())
                result.append(f)
    # Sort: prefer DDS > PNG > TEX, then alphabetically
    ext_order = {'.dds': 0, '.png': 1, '.tex': 2, '.tga': 3, '.jpg': 4, '.bmp': 5}
    result.sort(key=lambda p: (ext_order.get(p.suffix.lower(), 9), p.name.lower()))
    return result


def _match_texture_to_submesh(textures: list, submesh_name: str, skn_stem: str) -> str:
    """
    Try to find the best texture match for a given submesh name.
    Uses multiple matching strategies for League champion naming conventions.

    Common patterns:
    - SKN stem: "champion_base"  →  textures: "champion_base_TX_CM.dds"
    - Submesh: "Body"  →  texture might contain "body" in stem
    - Color map markers: "_TX_CM", "_diff", "_diffuse", "_color", "_base_color"
    """
    if not textures:
        return ""

    sub_lower = submesh_name.lower()
    stem_lower = skn_stem.lower()

    # Color-map keywords (prioritize these for diffuse assignment)
    color_keywords = ('_tx_cm', '_diffuse', '_diff', '_color', '_base_color',
                      '_albedo', '_basecolor', '_d.', '_col')

    # ---------- Pass 1: exact stem match ----------
    for tex in textures:
        if tex.stem.lower() == sub_lower:
            return str(tex)

    # ---------- Pass 2: submesh name contained in texture stem ----------
    for tex in textures:
        ts = tex.stem.lower()
        if sub_lower in ts:
            return str(tex)

    # ---------- Pass 3: skn_stem + color map keyword ----------
    for tex in textures:
        ts = tex.stem.lower()
        if stem_lower in ts:
            for kw in color_keywords:
                if kw in ts:
                    return str(tex)

    # ---------- Pass 4: any texture with a color map keyword ----------
    for tex in textures:
        ts = tex.stem.lower()
        for kw in color_keywords:
            if kw in ts:
                return str(tex)

    # ---------- Pass 5: any texture containing the skn stem ----------
    for tex in textures:
        ts = tex.stem.lower()
        if stem_lower in ts:
            return str(tex)

    return ""


def _setup_material_with_texture(
    mat: bpy.types.Material,
    texture_path: str,
    assets_folder: str = "",
) -> bool:
    """
    Configure *mat* with a Principled BSDF + Image Texture node.
    Returns True if a texture was loaded successfully.
    """
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Ensure output + principled exist
    output = None
    principled = None
    for n in nodes:
        if n.type == 'OUTPUT_MATERIAL':
            output = n
        elif n.type == 'BSDF_PRINCIPLED':
            principled = n
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 0)
    if principled is None:
        principled = nodes.new('ShaderNodeBsdfPrincipled')
        principled.location = (0, 0)
        if principled.inputs.get('Emission Strength'):
            principled.inputs['Emission Strength'].default_value = 0.0
    # Link principled → output if not already
    if not any(l.to_node == output for l in principled.outputs['BSDF'].links):
        links.new(principled.outputs['BSDF'], output.inputs['Surface'])

    if not texture_path:
        return False

    # Try to load image
    img = None
    converter = TexConverter() if TexConverter else None

    if texture_path.lower().endswith('.tex') and converter:
        try:
            img = converter.load_tex_as_blender_image(texture_path)
        except Exception as e:
            print(f"[SKN/SKL] TEX load failed: {e}")
    else:
        try:
            img = bpy.data.images.load(texture_path, check_existing=True)
        except Exception as e:
            print(f"[SKN/SKL] Image load failed: {e}")

    if not img:
        return False

    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.location = (-400, 0)
    tex_node.image = img
    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
    links.new(tex_node.outputs['Alpha'], principled.inputs['Alpha'])

    # Set alpha blend mode (Blender 4.x+: blend_method removed, use alpha_threshold)
    try:
        mat.blend_method = 'CLIP'
    except AttributeError:
        pass  # Blender 5.0+ removed blend_method

    print(f"[SKN/SKL] Loaded texture: {Path(texture_path).name} → {mat.name}")
    return True


# ============================================================================
# SKN Parser (SimpleSkin binary format)
# ============================================================================

SKN_MAGIC = 0x00112233


class SKNSubmesh:
    """A submesh / material range within an SKN file."""
    __slots__ = ('name', 'start_vertex', 'vertex_count',
                 'start_index', 'index_count')

    def __init__(self):
        self.name = ""
        self.start_vertex = 0
        self.vertex_count = 0
        self.start_index = 0
        self.index_count = 0


class SKNVertex:
    """A single vertex in an SKN file."""
    __slots__ = ('position', 'bone_indices', 'bone_weights',
                 'normal', 'uv', 'color', 'tangent')

    def __init__(self):
        self.position = (0.0, 0.0, 0.0)
        self.bone_indices = (0, 0, 0, 0)
        self.bone_weights = (0.0, 0.0, 0.0, 0.0)
        self.normal = (0.0, 0.0, 0.0)
        self.uv = (0.0, 0.0)
        self.color = None       # (R, G, B, A) 0-255 or None
        self.tangent = None     # (x, y, z, w) or None


class SKNMesh:
    """Parsed SKN mesh data."""
    __slots__ = ('version_major', 'version_minor',
                 'submeshes', 'vertices', 'indices',
                 'vertex_type', 'bounding_box', 'bounding_sphere',
                 'source_path')

    def __init__(self):
        self.version_major = 0
        self.version_minor = 1
        self.submeshes = []     # list[SKNSubmesh]
        self.vertices = []      # list[SKNVertex]
        self.indices = []       # list[int] (triangle indices)
        self.vertex_type = 0    # 0=Basic, 1=Color, 2=Tangent
        self.bounding_box = None
        self.bounding_sphere = None
        self.source_path = ""


def parse_skn(filepath: str) -> SKNMesh:
    """Parse an SKN (SimpleSkin) binary file."""
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 8:
        raise ValueError(f"SKN file too small: {filepath}")

    magic = struct.unpack_from('<I', data, 0)[0]
    if magic != SKN_MAGIC:
        raise ValueError(f"Invalid SKN magic 0x{magic:08X} (expected 0x{SKN_MAGIC:08X})")

    major, minor = struct.unpack_from('<HH', data, 4)
    mesh = SKNMesh()
    mesh.version_major = major
    mesh.version_minor = minor
    mesh.source_path = filepath

    offset = 8

    if major == 0:
        # Version 0 — no submeshes, no vertex type info
        index_count, vertex_count = struct.unpack_from('<ii', data, offset)
        offset += 8
        mesh.vertex_type = 0  # always Basic

        # Default single submesh
        sub = SKNSubmesh()
        sub.name = "Base"
        sub.start_vertex = 0
        sub.vertex_count = vertex_count
        sub.start_index = 0
        sub.index_count = index_count
        mesh.submeshes.append(sub)

    elif major == 2:
        # Version 2 — has submeshes, no vertex type
        range_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        for _ in range(range_count):
            sub = SKNSubmesh()
            name_bytes = data[offset:offset + 64]
            sub.name = name_bytes.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
            offset += 64
            sub.start_vertex, sub.vertex_count, sub.start_index, sub.index_count = \
                struct.unpack_from('<iiii', data, offset)
            offset += 16
            mesh.submeshes.append(sub)

        index_count, vertex_count = struct.unpack_from('<ii', data, offset)
        offset += 8
        mesh.vertex_type = 0  # always Basic

    elif major == 4:
        # Version 4 — full header
        range_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        for _ in range(range_count):
            sub = SKNSubmesh()
            name_bytes = data[offset:offset + 64]
            sub.name = name_bytes.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
            offset += 64
            sub.start_vertex, sub.vertex_count, sub.start_index, sub.index_count = \
                struct.unpack_from('<iiii', data, offset)
            offset += 16
            mesh.submeshes.append(sub)

        flags = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        index_count, vertex_count = struct.unpack_from('<ii', data, offset)
        offset += 8
        vertex_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        mesh.vertex_type = struct.unpack_from('<I', data, offset)[0]
        offset += 4

        # Bounding box (24 bytes)
        bbox = struct.unpack_from('<6f', data, offset)
        mesh.bounding_box = (bbox[0:3], bbox[3:6])
        offset += 24

        # Bounding sphere (16 bytes)
        bsphere = struct.unpack_from('<4f', data, offset)
        mesh.bounding_sphere = (bsphere[0:3], bsphere[3])
        offset += 16

    else:
        raise ValueError(f"Unknown SKN version {major}.{minor}")

    # ---- Read index buffer ----
    for _ in range(index_count):
        idx = struct.unpack_from('<H', data, offset)[0]
        mesh.indices.append(idx)
        offset += 2

    # ---- Read vertex buffer ----
    has_color = mesh.vertex_type >= 1
    has_tangent = mesh.vertex_type >= 2

    for _ in range(vertex_count):
        v = SKNVertex()
        # Position (12 bytes)
        v.position = struct.unpack_from('<3f', data, offset)
        offset += 12
        # Bone indices (4 bytes)
        v.bone_indices = struct.unpack_from('<4B', data, offset)
        offset += 4
        # Bone weights (16 bytes)
        v.bone_weights = struct.unpack_from('<4f', data, offset)
        offset += 16
        # Normal (12 bytes)
        v.normal = struct.unpack_from('<3f', data, offset)
        offset += 12
        # UV (8 bytes)
        v.uv = struct.unpack_from('<2f', data, offset)
        offset += 8

        if has_color:
            b, g, r, a = struct.unpack_from('<4B', data, offset)
            v.color = (r, g, b, a)
            offset += 4

        if has_tangent:
            v.tangent = struct.unpack_from('<4f', data, offset)
            offset += 16

        mesh.vertices.append(v)

    print(f"[SKN] Parsed v{major}.{minor}: {len(mesh.vertices)} verts, "
          f"{index_count // 3} tris, {len(mesh.submeshes)} submesh(es)")

    return mesh


# ============================================================================
# SKL Parser (Skeleton / Rig)
# ============================================================================

LEGACY_MAGIC = b'r3d2sklt'
NEW_FORMAT_TOKEN = 0x22FD4FC3


class SKLJoint:
    """A single joint / bone."""
    __slots__ = ('id', 'name', 'parent_id', 'radius',
                 'local_translation', 'local_rotation', 'local_scale',
                 'inverse_bind_translation', 'inverse_bind_rotation', 'inverse_bind_scale',
                 'global_matrix')

    def __init__(self):
        self.id = 0
        self.name = ""
        self.parent_id = -1
        self.radius = 2.0
        self.local_translation = (0.0, 0.0, 0.0)
        self.local_rotation = (0.0, 0.0, 0.0, 1.0)  # (x, y, z, w)
        self.local_scale = (1.0, 1.0, 1.0)
        self.inverse_bind_translation = (0.0, 0.0, 0.0)
        self.inverse_bind_rotation = (0.0, 0.0, 0.0, 1.0)
        self.inverse_bind_scale = (1.0, 1.0, 1.0)
        self.global_matrix = None  # only set for legacy format


class SKLSkeleton:
    """Parsed skeleton data."""
    __slots__ = ('joints', 'influences', 'name', 'asset_name',
                 'version', 'is_legacy', 'source_path')

    def __init__(self):
        self.joints = []        # list[SKLJoint]
        self.influences = []    # list[int] — bone remap table
        self.name = ""
        self.asset_name = ""
        self.version = 0
        self.is_legacy = False
        self.source_path = ""


def parse_skl(filepath: str) -> SKLSkeleton:
    """Parse an SKL (Skeleton) file — auto-detects legacy vs new format."""
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 12:
        raise ValueError(f"SKL file too small: {filepath}")

    # Detect format by checking byte 4-8 for the new-format token
    token = struct.unpack_from('<I', data, 4)[0]
    if token == NEW_FORMAT_TOKEN:
        return _parse_skl_new(data, filepath)
    else:
        return _parse_skl_legacy(data, filepath)


def _parse_skl_legacy(data: bytes, filepath: str) -> SKLSkeleton:
    """Parse legacy SKL format (magic 'r3d2sklt', versions 1–2)."""
    magic = data[0:8]
    if magic != LEGACY_MAGIC:
        raise ValueError(f"Invalid legacy SKL magic: {magic}")

    skel = SKLSkeleton()
    skel.is_legacy = True
    skel.source_path = filepath

    version = struct.unpack_from('<I', data, 8)[0]
    skel.version = version
    _skeleton_id = struct.unpack_from('<I', data, 12)[0]
    joint_count = struct.unpack_from('<I', data, 16)[0]

    offset = 20

    for i in range(joint_count):
        j = SKLJoint()
        j.id = i

        # Name (32 bytes, null-padded)
        name_bytes = data[offset:offset + 32]
        j.name = name_bytes.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
        offset += 32

        j.parent_id = struct.unpack_from('<i', data, offset)[0]
        offset += 4

        j.radius = struct.unpack_from('<f', data, offset)[0]
        offset += 4

        # Global transform — 12 floats stored column-major (3 columns × 4 rows)
        floats = struct.unpack_from('<12f', data, offset)
        offset += 48

        # Build 4×4 matrix (column-major, last column is [0,0,0,1])
        mat = Matrix((
            (floats[0], floats[4], floats[8],  0.0),
            (floats[1], floats[5], floats[9],  0.0),
            (floats[2], floats[6], floats[10], 0.0),
            (floats[3], floats[7], floats[11], 1.0),
        ))
        j.global_matrix = mat

        skel.joints.append(j)

    # Compute local transforms and inverse-bind from global matrices
    for j in skel.joints:
        if j.parent_id >= 0 and j.parent_id < len(skel.joints):
            parent_mat = skel.joints[j.parent_id].global_matrix
            local_mat = parent_mat.inverted_safe() @ j.global_matrix
        else:
            local_mat = j.global_matrix.copy()

        loc, rot, scl = local_mat.decompose()
        j.local_translation = tuple(loc)
        j.local_rotation = (rot.x, rot.y, rot.z, rot.w)
        j.local_scale = tuple(scl)

        inv_bind = j.global_matrix.inverted_safe()
        ib_loc, ib_rot, ib_scl = inv_bind.decompose()
        j.inverse_bind_translation = tuple(ib_loc)
        j.inverse_bind_rotation = (ib_rot.x, ib_rot.y, ib_rot.z, ib_rot.w)
        j.inverse_bind_scale = tuple(ib_scl)

    # Influences
    if version >= 2 and offset + 4 <= len(data):
        influences_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        for _ in range(influences_count):
            idx = struct.unpack_from('<I', data, offset)[0]
            skel.influences.append(idx & 0xFFFF)  # cast to int16 range
            offset += 4
    else:
        # Version 1: identity mapping
        skel.influences = list(range(joint_count))

    print(f"[SKL] Parsed legacy v{version}: {joint_count} joints, "
          f"{len(skel.influences)} influences")
    return skel


def _parse_skl_new(data: bytes, filepath: str) -> SKLSkeleton:
    """Parse new-format SKL (token 0x22FD4FC3, version 0)."""
    skel = SKLSkeleton()
    skel.is_legacy = False
    skel.source_path = filepath

    # Header (64 bytes)
    _file_size = struct.unpack_from('<I', data, 0)[0]
    _format_token = struct.unpack_from('<I', data, 4)[0]
    skel.version = struct.unpack_from('<I', data, 8)[0]
    _flags = struct.unpack_from('<H', data, 12)[0]
    joint_count = struct.unpack_from('<H', data, 14)[0]
    influences_count = struct.unpack_from('<I', data, 16)[0]
    joints_offset = struct.unpack_from('<i', data, 20)[0]
    _joint_indices_offset = struct.unpack_from('<i', data, 24)[0]
    influences_offset = struct.unpack_from('<i', data, 28)[0]
    name_offset = struct.unpack_from('<i', data, 32)[0]
    asset_name_offset = struct.unpack_from('<i', data, 36)[0]
    _bone_names_offset = struct.unpack_from('<i', data, 40)[0]

    # Read skeleton name
    if name_offset > 0 and name_offset < len(data):
        end = data.index(b'\x00', name_offset) if b'\x00' in data[name_offset:] else len(data)
        skel.name = data[name_offset:end].decode('utf-8', errors='replace')

    # Read asset name
    if asset_name_offset > 0 and asset_name_offset < len(data):
        end = data.index(b'\x00', asset_name_offset) if b'\x00' in data[asset_name_offset:] else len(data)
        skel.asset_name = data[asset_name_offset:end].decode('utf-8', errors='replace')

    # Read joints (100 bytes each)
    if joints_offset > 0:
        off = joints_offset
        for i in range(joint_count):
            j = SKLJoint()
            _jflags = struct.unpack_from('<H', data, off)[0]
            j.id = struct.unpack_from('<h', data, off + 2)[0]
            j.parent_id = struct.unpack_from('<h', data, off + 4)[0]
            _padding = struct.unpack_from('<h', data, off + 6)[0]
            _name_hash = struct.unpack_from('<I', data, off + 8)[0]
            j.radius = struct.unpack_from('<f', data, off + 12)[0]

            # Local transform (TRS)
            j.local_translation = struct.unpack_from('<3f', data, off + 16)
            j.local_scale = struct.unpack_from('<3f', data, off + 28)
            j.local_rotation = struct.unpack_from('<4f', data, off + 40)  # x, y, z, w

            # Inverse bind transform (TRS)
            j.inverse_bind_translation = struct.unpack_from('<3f', data, off + 56)
            j.inverse_bind_scale = struct.unpack_from('<3f', data, off + 68)
            j.inverse_bind_rotation = struct.unpack_from('<4f', data, off + 80)

            # Name — relative offset from current position
            name_rel_offset = struct.unpack_from('<i', data, off + 96)[0]
            if name_rel_offset != 0:
                # The name offset is relative to the position of the field itself
                name_abs = (off + 96) + name_rel_offset
                if 0 <= name_abs < len(data):
                    end_pos = data.index(b'\x00', name_abs) if b'\x00' in data[name_abs:] else len(data)
                    j.name = data[name_abs:end_pos].decode('utf-8', errors='replace')

            skel.joints.append(j)
            off += 100

    # Read influences
    if influences_offset > 0 and influences_count > 0:
        off = influences_offset
        for _ in range(influences_count):
            idx = struct.unpack_from('<h', data, off)[0]
            skel.influences.append(idx)
            off += 2
    else:
        # No influences — identity mapping
        skel.influences = list(range(joint_count))

    print(f"[SKL] Parsed new v{skel.version}: {joint_count} joints, "
          f"{len(skel.influences)} influences, name='{skel.name}'")
    return skel


# ============================================================================
# Blender Mesh Builder
# ============================================================================

def _build_blender_armature(
    skeleton: SKLSkeleton,
    collection: bpy.types.Collection,
    apply_rotation: bool = True,
) -> bpy.types.Object:
    """Create a Blender armature from parsed SKL data."""
    arm_name = skeleton.name or Path(skeleton.source_path).stem
    armature = bpy.data.armatures.new(arm_name)
    arm_obj = bpy.data.objects.new(arm_name, armature)
    collection.objects.link(arm_obj)

    # Make active and enter edit mode
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    # Coordinate conversion matrix (League Y-up left-hand → Blender Z-up right-hand)
    if apply_rotation:
        conv = Matrix((
            (1, 0, 0, 0),
            (0, 0, -1, 0),
            (0, 1, 0, 0),
            (0, 0, 0, 1),
        ))
    else:
        conv = Matrix.Identity(4)

    edit_bones = armature.edit_bones

    # Build a mapping from joint id to joint
    id_to_joint = {}
    for j in skeleton.joints:
        id_to_joint[j.id] = j

    # Pre-compute world positions for bone length calculation
    world_positions = {}  # joint id → Vector
    for j in skeleton.joints:
        if j.global_matrix is not None:
            wm = conv @ j.global_matrix
        else:
            wm = _compute_world_matrix(j, id_to_joint, conv)
        world_positions[j.id] = (wm.translation.copy(), wm)

    # Build children lookup for bone length heuristic
    children_map = {}  # joint id → [child ids]
    for j in skeleton.joints:
        if j.parent_id >= 0:
            children_map.setdefault(j.parent_id, []).append(j.id)

    # Determine a reasonable default bone length from the skeleton's bounding size
    if len(world_positions) >= 2:
        all_pos = [p for p, _ in world_positions.values()]
        xs = [p.x for p in all_pos]
        ys = [p.y for p in all_pos]
        zs = [p.z for p in all_pos]
        skeleton_span = max(
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
            1.0,
        )
        default_bone_len = skeleton_span * 0.03  # 3% of skeleton span
        min_bone_len = skeleton_span * 0.01       # 1% minimum
    else:
        default_bone_len = 5.0
        min_bone_len = 2.0

    # Create edit bones (first pass — create all bones)
    bone_map = {}  # joint id → EditBone
    for j in skeleton.joints:
        bone = edit_bones.new(j.name or f"bone_{j.id}")
        bone_map[j.id] = bone

        head_pos, world_mat = world_positions[j.id]
        bone.head = head_pos

        # Determine bone length:  prefer distance to first child,
        # then distance to parent, then fallback default
        bone_len = default_bone_len
        child_ids = children_map.get(j.id, [])
        if child_ids:
            # Average distance to children
            dists = []
            for cid in child_ids:
                child_pos, _ = world_positions[cid]
                d = (child_pos - head_pos).length
                if d > 0.001:
                    dists.append(d)
            if dists:
                bone_len = max(sum(dists) / len(dists) * 0.4, min_bone_len)
        elif j.parent_id >= 0 and j.parent_id in world_positions:
            parent_pos, _ = world_positions[j.parent_id]
            d = (head_pos - parent_pos).length
            if d > 0.001:
                bone_len = max(d * 0.4, min_bone_len)

        # Point tail along local Y axis of the bone
        tail_offset = world_mat.to_3x3() @ Vector((0, bone_len, 0))
        bone.tail = bone.head + tail_offset

        # Prevent zero-length bones
        if (bone.tail - bone.head).length < 0.001:
            bone.tail = bone.head + Vector((0, default_bone_len, 0))

    # Second pass — set parents
    for j in skeleton.joints:
        if j.parent_id >= 0 and j.parent_id in bone_map:
            bone_map[j.id].parent = bone_map[j.parent_id]

    bpy.ops.object.mode_set(mode='OBJECT')

    # Set display mode to make bones more visible
    armature.display_type = 'OCTAHEDRAL'

    # Store metadata
    arm_obj["league_skl"] = True
    arm_obj["league_skl_version"] = skeleton.version
    arm_obj["league_skl_legacy"] = skeleton.is_legacy
    arm_obj["league_joint_count"] = len(skeleton.joints)
    arm_obj["league_influence_count"] = len(skeleton.influences)
    arm_obj["league_source_path"] = skeleton.source_path

    return arm_obj


def _compute_world_matrix(joint: SKLJoint, id_to_joint: dict, conv: Matrix) -> Matrix:
    """Compute the world-space matrix for a joint by walking up the hierarchy."""
    # Build local matrix from TRS
    loc = Vector(joint.local_translation)
    rot = Quaternion((joint.local_rotation[3],
                      joint.local_rotation[0],
                      joint.local_rotation[1],
                      joint.local_rotation[2]))
    scl = Vector(joint.local_scale)

    local_mat = Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
    # Apply scale
    s_mat = Matrix.Identity(4)
    s_mat[0][0] = scl.x
    s_mat[1][1] = scl.y
    s_mat[2][2] = scl.z
    local_mat = local_mat @ s_mat

    # Walk up hierarchy
    world_mat = local_mat
    parent_id = joint.parent_id
    visited = set()
    while parent_id >= 0 and parent_id in id_to_joint and parent_id not in visited:
        visited.add(parent_id)
        parent = id_to_joint[parent_id]
        p_loc = Vector(parent.local_translation)
        p_rot = Quaternion((parent.local_rotation[3],
                            parent.local_rotation[0],
                            parent.local_rotation[1],
                            parent.local_rotation[2]))
        p_scl = Vector(parent.local_scale)

        p_mat = Matrix.Translation(p_loc) @ p_rot.to_matrix().to_4x4()
        ps_mat = Matrix.Identity(4)
        ps_mat[0][0] = p_scl.x
        ps_mat[1][1] = p_scl.y
        ps_mat[2][2] = p_scl.z
        p_mat = p_mat @ ps_mat

        world_mat = p_mat @ world_mat
        parent_id = parent.parent_id

    return conv @ world_mat


def _build_blender_mesh(
    skn: SKNMesh,
    skeleton: SKLSkeleton,
    collection: bpy.types.Collection,
    armature_obj: bpy.types.Object = None,
    apply_rotation: bool = True,
    import_colors: bool = True,
    split_submeshes: bool = False,
    load_textures: bool = True,
    assets_folder: str = "",
) -> list:
    """
    Build Blender mesh(es) from parsed SKN + SKL data.
    Returns list of created mesh objects.
    """

    created_objects = []

    if split_submeshes and len(skn.submeshes) > 1:
        for sub in skn.submeshes:
            obj = _build_single_submesh(
                skn, skeleton, sub, collection,
                armature_obj, apply_rotation, import_colors,
            )
            if obj:
                created_objects.append(obj)
    else:
        # Build as single mesh with material slots for each submesh
        obj = _build_unified_mesh(
            skn, skeleton, collection,
            armature_obj, apply_rotation, import_colors,
        )
        if obj:
            created_objects.append(obj)

    # ---- Load textures for materials ----
    if load_textures:
        skn_dir = Path(skn.source_path).parent
        skn_stem = Path(skn.source_path).stem

        # Collect all available textures once
        available_textures = _collect_textures_in_folder(skn_dir)
        if available_textures:
            print(f"[SKN/SKL] Found {len(available_textures)} texture(s) in {skn_dir.name}/")

        # Track which textures have been assigned to avoid duplicates
        assigned_textures = set()

        for sub in skn.submeshes:
            mat_name = sub.name or "Material"
            mat = bpy.data.materials.get(mat_name)
            if not mat:
                continue
            # Skip if material already has a texture image node
            if mat.use_nodes and any(
                n.type == 'TEX_IMAGE' and n.image for n in mat.node_tree.nodes
            ):
                continue

            try:
                tex_path = ""

                # Strategy 1: exact stem match by material name
                tex_path = _find_texture_in_folder(skn_dir, mat_name)

                # Strategy 2: smart fuzzy match against all available textures
                if not tex_path:
                    tex_path = _match_texture_to_submesh(
                        [t for t in available_textures if str(t) not in assigned_textures],
                        mat_name, skn_stem,
                    )

                # Strategy 3: use resolve_texture_path with assets_folder
                if not tex_path and assets_folder and resolve_texture_path:
                    tex_path = resolve_texture_path(mat_name, assets_folder) or ""

                # Strategy 4: fallback — first unassigned texture
                if not tex_path:
                    for t in available_textures:
                        if str(t) not in assigned_textures:
                            tex_path = str(t)
                            break

                if tex_path:
                    assigned_textures.add(tex_path)

                _setup_material_with_texture(mat, tex_path, assets_folder)

            except Exception as e:
                print(f"[SKN/SKL] Warning: texture setup failed for {mat_name}: {e}")

    return created_objects


def _build_unified_mesh(
    skn: SKNMesh,
    skeleton: SKLSkeleton,
    collection: bpy.types.Collection,
    armature_obj: bpy.types.Object,
    apply_rotation: bool,
    import_colors: bool,
) -> bpy.types.Object:
    """Build a single Blender mesh from all submeshes."""
    mesh_name = Path(skn.source_path).stem
    bm = bmesh.new()

    # Coordinate conversion
    def conv_pos(pos):
        if apply_rotation:
            return (pos[0], -pos[2], pos[1])
        return pos

    # Add all vertices
    bm_verts = []
    for v in skn.vertices:
        co = conv_pos(v.position)
        bm_verts.append(bm.verts.new(co))
    bm.verts.ensure_lookup_table()

    # Prepare material index per submesh range
    # Build a vertex-to-submesh lookup for face material assignment
    face_mat_indices = {}  # (i0, i1, i2) -> material_index
    for sub_idx, sub in enumerate(skn.submeshes):
        si = sub.start_index
        for ti in range(0, sub.index_count, 3):
            idx = si + ti
            if idx + 2 < len(skn.indices):
                i0 = skn.indices[idx]
                i1 = skn.indices[idx + 1]
                i2 = skn.indices[idx + 2]
                face_mat_indices[(i0, i1, i2)] = sub_idx

    # Build faces from index buffer
    existing_faces = set()
    for tri_start in range(0, len(skn.indices), 3):
        i0 = skn.indices[tri_start]
        i1 = skn.indices[tri_start + 1]
        i2 = skn.indices[tri_start + 2]

        if i0 == i1 or i1 == i2 or i0 == i2:
            continue  # degenerate triangle
        if i0 >= len(bm_verts) or i1 >= len(bm_verts) or i2 >= len(bm_verts):
            continue  # out of range

        face_key = tuple(sorted((i0, i1, i2)))
        if face_key in existing_faces:
            continue
        existing_faces.add(face_key)

        try:
            bm.faces.new((bm_verts[i0], bm_verts[i1], bm_verts[i2]))
        except ValueError:
            pass  # duplicate face

    bm.faces.ensure_lookup_table()

    # Create Blender mesh
    bl_mesh = bpy.data.meshes.new(mesh_name)
    bm.to_mesh(bl_mesh)
    bm.free()

    obj = bpy.data.objects.new(mesh_name, bl_mesh)
    collection.objects.link(obj)

    # ---- Materials ----
    for sub in skn.submeshes:
        mat_name = sub.name or "Material"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            mat.use_nodes = True
        bl_mesh.materials.append(mat)

    # Assign material indices to faces
    # Re-walk index buffer to map face → material slot
    face_lookup = {}
    for fi, poly in enumerate(bl_mesh.polygons):
        verts_key = tuple(sorted(poly.vertices))
        face_lookup[verts_key] = fi

    for sub_idx, sub in enumerate(skn.submeshes):
        si = sub.start_index
        for ti in range(0, sub.index_count, 3):
            idx = si + ti
            if idx + 2 < len(skn.indices):
                i0 = skn.indices[idx]
                i1 = skn.indices[idx + 1]
                i2 = skn.indices[idx + 2]
                key = tuple(sorted((i0, i1, i2)))
                if key in face_lookup:
                    bl_mesh.polygons[face_lookup[key]].material_index = sub_idx

    # ---- UVs ----
    uv_layer = bl_mesh.uv_layers.new(name="UVMap")
    for poly in bl_mesh.polygons:
        for loop_idx in poly.loop_indices:
            vert_idx = bl_mesh.loops[loop_idx].vertex_index
            if vert_idx < len(skn.vertices):
                u, v = skn.vertices[vert_idx].uv
                uv_layer.data[loop_idx].uv = (u, 1.0 - v)

    # ---- Normals ----
    normals = []
    for v in skn.vertices:
        if apply_rotation:
            normals.append((v.normal[0], -v.normal[2], v.normal[1]))
        else:
            normals.append(v.normal)
    bl_mesh.normals_split_custom_set_from_vertices(normals)

    # ---- Vertex Colors ----
    if import_colors and any(v.color is not None for v in skn.vertices):
        color_layer = bl_mesh.color_attributes.new(
            name="Color", type='BYTE_COLOR', domain='CORNER'
        )
        for poly in bl_mesh.polygons:
            for loop_idx in poly.loop_indices:
                vert_idx = bl_mesh.loops[loop_idx].vertex_index
                if vert_idx < len(skn.vertices) and skn.vertices[vert_idx].color:
                    c = skn.vertices[vert_idx].color
                    color_layer.data[loop_idx].color = (c[0] / 255.0, c[1] / 255.0,
                                                        c[2] / 255.0, c[3] / 255.0)

    # ---- Vertex Groups (Bone Weights) ----
    if skeleton:
        # Build influence remap: vertex bone_index → joint id → joint name
        influences = skeleton.influences

        # Create vertex groups for all joints
        joint_name_by_id = {}
        for j in skeleton.joints:
            joint_name_by_id[j.id] = j.name

        vgroups = {}  # joint_id → vertex group
        for j in skeleton.joints:
            vg = obj.vertex_groups.new(name=j.name)
            vgroups[j.id] = vg

        # Assign weights
        for vi, v in enumerate(skn.vertices):
            for bi in range(4):
                weight = v.bone_weights[bi]
                if weight <= 0.0:
                    continue
                bone_idx = v.bone_indices[bi]

                # Remap via influences table
                if bone_idx < len(influences):
                    joint_id = influences[bone_idx]
                else:
                    joint_id = bone_idx

                if joint_id in vgroups:
                    vgroups[joint_id].add([vi], weight, 'REPLACE')

    # ---- Parent to Armature ----
    if armature_obj:
        obj.parent = armature_obj
        modifier = obj.modifiers.new(name="Armature", type='ARMATURE')
        modifier.object = armature_obj

    # Store metadata
    obj["league_skn"] = True
    obj["league_skn_version"] = f"{skn.version_major}.{skn.version_minor}"
    obj["league_vertex_type"] = skn.vertex_type
    obj["league_submesh_count"] = len(skn.submeshes)
    obj["league_source_path"] = skn.source_path

    return obj


def _build_single_submesh(
    skn: SKNMesh,
    skeleton: SKLSkeleton,
    sub: SKNSubmesh,
    collection: bpy.types.Collection,
    armature_obj: bpy.types.Object,
    apply_rotation: bool,
    import_colors: bool,
) -> bpy.types.Object:
    """Build a single Blender mesh for one submesh range."""
    mesh_name = sub.name or "Submesh"
    bm = bmesh.new()

    def conv_pos(pos):
        if apply_rotation:
            return (pos[0], -pos[2], pos[1])
        return pos

    # Build vertex subset — remap indices
    sv = sub.start_vertex
    vert_remap = {}
    bm_verts = []
    for local_i in range(sub.vertex_count):
        global_i = sv + local_i
        if global_i >= len(skn.vertices):
            break
        v = skn.vertices[global_i]
        co = conv_pos(v.position)
        bm_verts.append(bm.verts.new(co))
        vert_remap[global_i] = local_i
    bm.verts.ensure_lookup_table()

    # Build faces
    si = sub.start_index
    existing_faces = set()
    for tri_start in range(0, sub.index_count, 3):
        idx = si + tri_start
        if idx + 2 >= len(skn.indices):
            break
        i0 = skn.indices[idx]
        i1 = skn.indices[idx + 1]
        i2 = skn.indices[idx + 2]

        if i0 not in vert_remap or i1 not in vert_remap or i2 not in vert_remap:
            continue

        li0 = vert_remap[i0]
        li1 = vert_remap[i1]
        li2 = vert_remap[i2]

        if li0 == li1 or li1 == li2 or li0 == li2:
            continue
        face_key = tuple(sorted((li0, li1, li2)))
        if face_key in existing_faces:
            continue
        existing_faces.add(face_key)

        try:
            bm.faces.new((bm_verts[li0], bm_verts[li1], bm_verts[li2]))
        except ValueError:
            pass

    bm.faces.ensure_lookup_table()

    bl_mesh = bpy.data.meshes.new(mesh_name)
    bm.to_mesh(bl_mesh)
    bm.free()

    obj = bpy.data.objects.new(mesh_name, bl_mesh)
    collection.objects.link(obj)

    # Material
    mat = bpy.data.materials.get(sub.name)
    if mat is None:
        mat = bpy.data.materials.new(sub.name or "Material")
        mat.use_nodes = True
    bl_mesh.materials.append(mat)

    # UVs
    uv_layer = bl_mesh.uv_layers.new(name="UVMap")
    for poly in bl_mesh.polygons:
        for loop_idx in poly.loop_indices:
            local_vi = bl_mesh.loops[loop_idx].vertex_index
            global_vi = sv + local_vi
            if global_vi < len(skn.vertices):
                u, v = skn.vertices[global_vi].uv
                uv_layer.data[loop_idx].uv = (u, 1.0 - v)

    # Normals
    normals = []
    for local_i in range(sub.vertex_count):
        global_i = sv + local_i
        if global_i < len(skn.vertices):
            n = skn.vertices[global_i].normal
            if apply_rotation:
                normals.append((n[0], -n[2], n[1]))
            else:
                normals.append(n)
        else:
            normals.append((0, 0, 1))
    bl_mesh.normals_split_custom_set_from_vertices(normals)

    # Vertex colors
    if import_colors:
        has_any = any(
            skn.vertices[sv + i].color is not None
            for i in range(min(sub.vertex_count, len(skn.vertices) - sv))
        )
        if has_any:
            color_layer = bl_mesh.color_attributes.new(
                name="Color", type='BYTE_COLOR', domain='CORNER'
            )
            for poly in bl_mesh.polygons:
                for loop_idx in poly.loop_indices:
                    local_vi = bl_mesh.loops[loop_idx].vertex_index
                    global_vi = sv + local_vi
                    if global_vi < len(skn.vertices) and skn.vertices[global_vi].color:
                        c = skn.vertices[global_vi].color
                        color_layer.data[loop_idx].color = (
                            c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, c[3] / 255.0
                        )

    # Vertex groups
    if skeleton:
        influences = skeleton.influences
        vgroups = {}
        for j in skeleton.joints:
            vg = obj.vertex_groups.new(name=j.name)
            vgroups[j.id] = vg

        for local_i in range(sub.vertex_count):
            global_i = sv + local_i
            if global_i >= len(skn.vertices):
                break
            v = skn.vertices[global_i]
            for bi in range(4):
                weight = v.bone_weights[bi]
                if weight <= 0.0:
                    continue
                bone_idx = v.bone_indices[bi]
                if bone_idx < len(influences):
                    joint_id = influences[bone_idx]
                else:
                    joint_id = bone_idx
                if joint_id in vgroups:
                    vgroups[joint_id].add([local_i], weight, 'REPLACE')

    # Parent to armature
    if armature_obj:
        obj.parent = armature_obj
        modifier = obj.modifiers.new(name="Armature", type='ARMATURE')
        modifier.object = armature_obj

    obj["league_skn"] = True
    obj["league_submesh_name"] = sub.name

    return obj


# ============================================================================
# Blender Operators
# ============================================================================

class SKNSKL_OT_import(Operator, ImportHelper):
    """Import League of Legends SKN/SKL skinned mesh + skeleton files"""
    bl_idname = "skn_skl.import_file"
    bl_label = "Import SKN/SKL"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default="*.skn;*.skl",
        options={'HIDDEN'},
    )

    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    directory: StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN'},
    )

    apply_rotation: BoolProperty(
        name="Convert Coordinates",
        description="Convert from League Y-up left-hand to Blender Z-up right-hand",
        default=True,
    )

    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        description="Import vertex colors if present",
        default=True,
    )

    import_skeleton: BoolProperty(
        name="Import Skeleton",
        description="Import SKL skeleton as armature (auto-finds matching .skl for .skn)",
        default=True,
    )

    load_textures: BoolProperty(
        name="Load Textures",
        description="Search for and load texture files (.dds/.png/.tex) for materials",
        default=True,
    )

    split_submeshes: BoolProperty(
        name="Split Submeshes",
        description="Create separate objects for each submesh/material",
        default=False,
    )

    create_collection: BoolProperty(
        name="Create Collection",
        description="Place imported objects in a new collection",
        default=True,
    )

    assets_folder: StringProperty(
        name="Assets Folder",
        description="Optional League assets folder for texture resolution",
        subtype='DIR_PATH',
        default="",
    )

    def execute(self, context):
        import_count = 0
        errors = []

        # Sort files: process SKL files first so armatures are ready
        skl_files = []
        skn_files = []
        for file_elem in self.files:
            ext = Path(file_elem.name).suffix.lower()
            if ext == '.skl':
                skl_files.append(file_elem.name)
            elif ext == '.skn':
                skn_files.append(file_elem.name)
            else:
                errors.append(f"Unknown extension: {file_elem.name}")

        # Target collection
        if self.create_collection:
            coll_name = "SKN/SKL Import"
            coll = bpy.data.collections.get(coll_name)
            if coll is None:
                coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(coll)
        else:
            coll = context.scene.collection

        # Track armatures by stem name
        armature_map = {}

        # Import SKL files
        for fname in skl_files:
            filepath = os.path.join(self.directory, fname)
            try:
                skeleton = parse_skl(filepath)
                arm_obj = _build_blender_armature(
                    skeleton, coll,
                    apply_rotation=self.apply_rotation,
                )
                stem = Path(fname).stem.lower()
                armature_map[stem] = (arm_obj, skeleton)
                import_count += 1
                print(f"[SKN/SKL] Imported skeleton: {fname} ({len(skeleton.joints)} joints)")
            except Exception as e:
                errors.append(f"{fname}: {e}")
                import traceback
                traceback.print_exc()

        # Import SKN files
        for fname in skn_files:
            filepath = os.path.join(self.directory, fname)
            try:
                skn = parse_skn(filepath)
                skn_stem = Path(fname).stem.lower()

                # Find matching skeleton
                arm_obj = None
                skeleton = None

                if self.import_skeleton:
                    # Try exact stem match
                    if skn_stem in armature_map:
                        arm_obj, skeleton = armature_map[skn_stem]
                    else:
                        # Auto-find: look for .skl with same stem in same directory
                        skl_path = Path(filepath).with_suffix('.skl')
                        if skl_path.exists() and skl_path.name.lower() not in [
                            f.lower() for f in skl_files
                        ]:
                            try:
                                skeleton = parse_skl(str(skl_path))
                                arm_obj = _build_blender_armature(
                                    skeleton, coll,
                                    apply_rotation=self.apply_rotation,
                                )
                                armature_map[skn_stem] = (arm_obj, skeleton)
                                import_count += 1
                            except Exception as e:
                                print(f"[SKN/SKL] Warning: auto-found SKL failed: {e}")

                        # Fallback: use first available armature
                        if arm_obj is None and armature_map:
                            first_key = next(iter(armature_map))
                            arm_obj, skeleton = armature_map[first_key]

                objects = _build_blender_mesh(
                    skn, skeleton, coll,
                    armature_obj=arm_obj,
                    apply_rotation=self.apply_rotation,
                    import_colors=self.import_vertex_colors,
                    split_submeshes=self.split_submeshes,
                    load_textures=self.load_textures,
                    assets_folder=self.assets_folder,
                )
                import_count += len(objects)

                for obj in objects:
                    mesh = obj.data
                    print(f"[SKN/SKL] Imported mesh: {obj.name} "
                          f"({len(mesh.vertices)} verts, {len(mesh.polygons)} faces)")

            except Exception as e:
                errors.append(f"{fname}: {e}")
                import traceback
                traceback.print_exc()

        if errors:
            self.report({'WARNING'}, f"Imported {import_count} object(s) with {len(errors)} error(s)")
        else:
            self.report({'INFO'}, f"Imported {import_count} object(s)")

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "apply_rotation")
        layout.prop(self, "import_vertex_colors")
        layout.prop(self, "import_skeleton")
        layout.prop(self, "load_textures")
        layout.prop(self, "split_submeshes")
        layout.prop(self, "create_collection")
        layout.separator()
        layout.prop(self, "assets_folder")


class SKNSKL_OT_batch_import(Operator):
    """Batch import all SKN/SKL files from a folder"""
    bl_idname = "skn_skl.batch_import"
    bl_label = "Batch Import SKN/SKL"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(
        subtype='DIR_PATH',
    )

    apply_rotation: BoolProperty(
        name="Convert Coordinates",
        default=True,
    )

    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        default=True,
    )

    import_skeleton: BoolProperty(
        name="Import Skeleton",
        default=True,
    )

    load_textures: BoolProperty(
        name="Load Textures",
        default=True,
    )

    def execute(self, context):
        if not self.directory or not os.path.isdir(self.directory):
            self.report({'ERROR'}, "Invalid directory")
            return {'CANCELLED'}

        # Create collection
        folder_name = Path(self.directory).name
        coll = bpy.data.collections.new(f"SKN/SKL - {folder_name}")
        context.scene.collection.children.link(coll)

        # Find all files
        skl_files = sorted(Path(self.directory).glob("*.skl"))
        skn_files = sorted(Path(self.directory).glob("*.skn"))

        import_count = 0
        errors = []
        armature_map = {}

        # Import skeletons first
        for skl_path in skl_files:
            try:
                skeleton = parse_skl(str(skl_path))
                arm_obj = _build_blender_armature(
                    skeleton, coll, apply_rotation=self.apply_rotation,
                )
                armature_map[skl_path.stem.lower()] = (arm_obj, skeleton)
                import_count += 1
            except Exception as e:
                errors.append(f"{skl_path.name}: {e}")

        # Import meshes
        for skn_path in skn_files:
            try:
                skn = parse_skn(str(skn_path))
                stem = skn_path.stem.lower()

                arm_obj = None
                skeleton = None
                if self.import_skeleton and stem in armature_map:
                    arm_obj, skeleton = armature_map[stem]
                elif self.import_skeleton and armature_map:
                    arm_obj, skeleton = next(iter(armature_map.values()))

                objects = _build_blender_mesh(
                    skn, skeleton, coll,
                    armature_obj=arm_obj,
                    apply_rotation=self.apply_rotation,
                    import_colors=self.import_vertex_colors,
                    load_textures=self.load_textures,
                )
                import_count += len(objects)
            except Exception as e:
                errors.append(f"{skn_path.name}: {e}")

        if errors:
            self.report({'WARNING'}, f"Imported {import_count} from {folder_name} ({len(errors)} errors)")
        else:
            self.report({'INFO'}, f"Imported {import_count} objects from {folder_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SKNSKL_OT_info_selected(Operator):
    """Show detailed info about the selected skinned mesh"""
    bl_idname = "skn_skl.info_selected"
    bl_label = "SKN/SKL Info"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type not in ('MESH', 'ARMATURE'):
            self.report({'WARNING'}, "Select a mesh or armature object")
            return {'CANCELLED'}

        info_parts = [f"Name: {obj.name}"]

        if obj.type == 'MESH':
            mesh = obj.data
            info_parts.append(f"Verts: {len(mesh.vertices)}")
            info_parts.append(f"Faces: {len(mesh.polygons)}")
            info_parts.append(f"Materials: {len(mesh.materials)}")

            if obj.vertex_groups:
                info_parts.append(f"Bone Groups: {len(obj.vertex_groups)}")

            if obj.get("league_skn_version"):
                info_parts.append(f"SKN v{obj['league_skn_version']}")

        elif obj.type == 'ARMATURE':
            arm = obj.data
            info_parts.append(f"Bones: {len(arm.bones)}")
            if obj.get("league_skl_version") is not None:
                info_parts.append(f"SKL v{obj['league_skl_version']}")
                info_parts.append(f"Legacy: {obj.get('league_skl_legacy', '?')}")

        self.report({'INFO'}, " | ".join(info_parts))
        return {'FINISHED'}


# ============================================================================
# Property Groups
# ============================================================================

class SknSklSettings(PropertyGroup):
    """Settings for SKN/SKL importer panel"""
    last_import_path: StringProperty(
        name="Last Import Path",
        subtype='DIR_PATH',
    )
    apply_rotation: BoolProperty(
        name="Convert Coordinates",
        description="Convert from League coordinate system to Blender",
        default=True,
    )
    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        description="Import vertex colors if present",
        default=True,
    )
    import_skeleton: BoolProperty(
        name="Import Skeleton",
        description="Import matching .skl file as armature",
        default=True,
    )
    load_textures: BoolProperty(
        name="Load Textures",
        description="Search for and load texture files for materials",
        default=True,
    )
    split_submeshes: BoolProperty(
        name="Split Submeshes",
        description="Create separate objects for each submesh",
        default=False,
    )
    assets_folder: StringProperty(
        name="Assets Folder",
        description="Optional League assets folder for texture resolution",
        subtype='DIR_PATH',
        default="",
    )


# ============================================================================
# UI Panel (League Tools tab)
# ============================================================================

class VIEW3D_PT_skn_skl_panel(Panel):
    """SKN/SKL Skinned Mesh Tools"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "SKN/SKL Skinned Mesh"
    bl_idname = "VIEW3D_PT_skn_skl_panel"
    bl_order = 40
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.skn_skl_settings

        # Header
        layout.label(text="Skinned Mesh Import", icon='ARMATURE_DATA')
        layout.separator()

        # Import section
        box = layout.box()
        box.label(text="Import", icon='IMPORT')

        col = box.column(align=True)
        col.operator("skn_skl.import_file", text="Import SKN/SKL File(s)", icon='FILE')
        col.operator("skn_skl.batch_import", text="Batch Import Folder", icon='FILE_FOLDER')

        # Import options
        box2 = box.box()
        box2.label(text="Import Options", icon='PREFERENCES')
        box2.prop(settings, "apply_rotation")
        box2.prop(settings, "import_vertex_colors")
        box2.prop(settings, "import_skeleton")
        box2.prop(settings, "load_textures")
        box2.prop(settings, "split_submeshes")

        # Assets folder
        box3 = box.box()
        box3.label(text="Texture Search", icon='TEXTURE')
        box3.prop(settings, "assets_folder", text="Assets Folder")

        layout.separator()

        # Info section
        obj = context.active_object
        if obj and obj.type == 'MESH' and obj.get("league_skn"):
            box = layout.box()
            box.label(text="Selected SKN Mesh", icon='INFO')

            mesh = obj.data
            col = box.column(align=True)
            col.label(text=f"Name: {obj.name}")
            col.label(text=f"Vertices: {len(mesh.vertices)}")
            col.label(text=f"Faces: {len(mesh.polygons)}")
            col.label(text=f"Materials: {len(mesh.materials)}")

            if obj.vertex_groups:
                col.label(text=f"Bone Groups: {len(obj.vertex_groups)}")

            if obj.get("league_skn_version"):
                col.label(text=f"Version: {obj['league_skn_version']}")
            if obj.get("league_vertex_type") is not None:
                vtype = {0: "Basic", 1: "Color", 2: "Tangent"}.get(
                    obj["league_vertex_type"], "Unknown"
                )
                col.label(text=f"Vertex Type: {vtype}")
            if obj.get("league_submesh_count"):
                col.label(text=f"Submeshes: {obj['league_submesh_count']}")

            col.operator("skn_skl.info_selected", text="Full Info", icon='QUESTION')

        elif obj and obj.type == 'ARMATURE' and obj.get("league_skl"):
            box = layout.box()
            box.label(text="Selected SKL Skeleton", icon='INFO')

            arm = obj.data
            col = box.column(align=True)
            col.label(text=f"Name: {obj.name}")
            col.label(text=f"Bones: {len(arm.bones)}")
            if obj.get("league_skl_version") is not None:
                col.label(text=f"Version: {obj['league_skl_version']}")
            if obj.get("league_skl_legacy") is not None:
                col.label(text=f"Format: {'Legacy' if obj['league_skl_legacy'] else 'New'}")
            if obj.get("league_joint_count"):
                col.label(text=f"Joints: {obj['league_joint_count']}")
            if obj.get("league_influence_count"):
                col.label(text=f"Influences: {obj['league_influence_count']}")

            col.operator("skn_skl.info_selected", text="Full Info", icon='QUESTION')


# ============================================================================
# File Menu Integration
# ============================================================================

def menu_func_import(self, context):
    self.layout.operator(SKNSKL_OT_import.bl_idname,
                         text="League SKN/SKL Skinned Mesh (.skn/.skl)")


# ============================================================================
# Registration
# ============================================================================

_classes = (
    SknSklSettings,
    SKNSKL_OT_import,
    SKNSKL_OT_batch_import,
    SKNSKL_OT_info_selected,
    VIEW3D_PT_skn_skl_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.skn_skl_settings = bpy.props.PointerProperty(type=SknSklSettings)

    # Add to File menu
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    print("[SKN/SKL] Skinned mesh tools registered")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    del bpy.types.Scene.skn_skl_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    print("[SKN/SKL] Skinned mesh tools unregistered")
