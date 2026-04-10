"""
League Tools - SCO/SCB Static Mesh Importer for Blender
Imports legacy League of Legends .sco (text) and .scb (binary) static mesh files.

SCO = Static Collision Object (text format)
SCB = Static Collision Binary (binary format)

These are map props, structures, and other static objects used in older League maps.
"""

import bpy
import bmesh
import struct
import os
from pathlib import Path
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup, Panel, Operator, UIList
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector


# ============================================================================
# SCO Parser (text format)
# ============================================================================

class SCOMesh:
    """Parsed SCO mesh data"""
    __slots__ = ('name', 'central_point', 'pivot_point',
                 'vertices', 'faces', 'uvs', 'materials', 'source_path')

    def __init__(self):
        self.name = ""
        self.central_point = (0.0, 0.0, 0.0)
        self.pivot_point = (0.0, 0.0, 0.0)
        self.vertices = []       # list of (x, y, z)
        self.faces = []          # list of (v0, v1, v2)
        self.uvs = []            # list of ((u0,v0), (u1,v1), (u2,v2)) per face
        self.materials = []      # list of material name per face
        self.source_path = ""


def parse_sco(filepath: str) -> list:
    """
    Parse an SCO text file. Can contain multiple objects.

    SCO format:
        [ObjectBegin]
        Name= mesh_name
        CentralPoint= x y z
        PivotPoint= x y z          (optional)
        Verts= count
        x y z
        ...
        Faces= count
        3   v0 v1 v2   material   u0 v0 u1 v1 u2 v2
        ...
        [ObjectEnd]
    """
    meshes = []

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == '[ObjectBegin]':
            mesh = SCOMesh()
            mesh.source_path = filepath
            i += 1

            while i < len(lines):
                line = lines[i].strip()

                if line == '[ObjectEnd]':
                    meshes.append(mesh)
                    break

                if line.startswith('Name='):
                    mesh.name = line.split('=', 1)[1].strip()

                elif line.startswith('CentralPoint='):
                    parts = line.split('=', 1)[1].strip().split()
                    mesh.central_point = tuple(float(x) for x in parts[:3])

                elif line.startswith('PivotPoint='):
                    parts = line.split('=', 1)[1].strip().split()
                    mesh.pivot_point = tuple(float(x) for x in parts[:3])

                elif line.startswith('Verts='):
                    vert_count = int(line.split('=', 1)[1].strip())
                    for v in range(vert_count):
                        i += 1
                        parts = lines[i].strip().split()
                        mesh.vertices.append((float(parts[0]), float(parts[1]), float(parts[2])))

                elif line.startswith('Faces='):
                    face_count = int(line.split('=', 1)[1].strip())
                    for fi in range(face_count):
                        i += 1
                        parts = lines[i].strip().split()
                        # Format: 3  v0 v1 v2  material  u0 v0 u1 v1 u2 v2
                        # First token is vertex count per face (always 3)
                        idx0, idx1, idx2 = int(parts[1]), int(parts[2]), int(parts[3])
                        mat_name = parts[4]
                        u0, uv0 = float(parts[5]), float(parts[6])
                        u1, uv1 = float(parts[7]), float(parts[8])
                        u2, uv2 = float(parts[9]), float(parts[10])

                        mesh.faces.append((idx0, idx1, idx2))
                        mesh.uvs.append(((u0, uv0), (u1, uv1), (u2, uv2)))
                        mesh.materials.append(mat_name)

                i += 1
        i += 1

    return meshes


# ============================================================================
# SCB Parser (binary format)
# ============================================================================

class SCBMesh:
    """Parsed SCB mesh data"""
    __slots__ = ('name', 'central_point', 'pivot_point',
                 'vertices', 'faces', 'uvs', 'materials',
                 'vertex_colors', 'bounding_box',
                 'version_major', 'version_minor', 'source_path')

    def __init__(self):
        self.name = ""
        self.central_point = (0.0, 0.0, 0.0)
        self.pivot_point = (0.0, 0.0, 0.0)
        self.vertices = []       # list of (x, y, z)
        self.faces = []          # list of (v0, v1, v2)
        self.uvs = []            # list of ((u0,v0), (u1,v1), (u2,v2)) per face
        self.materials = []      # list of material name per face
        self.vertex_colors = []  # list of (r, g, b, a) per vertex (0-255)
        self.bounding_box = None # (min_xyz, max_xyz)
        self.version_major = 0
        self.version_minor = 0
        self.source_path = ""


def parse_scb(filepath: str) -> list:
    """
    Parse an SCB binary file.

    SCB format (v3.2):
        Header:
            char[8]   magic = "r3d2Mesh"
            uint16    major (3)
            uint16    minor (2)
            char[128] name (null-terminated, padded)
            uint32    vertex_count
            uint32    face_count
            uint32    flags (bit 0 = has vertex colors)
            float[6]  bounding_box (minX, minY, minZ, maxX, maxY, maxZ)
            uint32    vertex_type_flag (usually 0)
        Vertices:
            float3 * vertex_count
        Vertex Colors (if flags & 1):
            uint8[4] * vertex_count (BGRA order)
        Central Point:
            float3
        Faces:
            uint32[3]  indices
            char[64]   material (null-terminated, padded)
            float[6]   UVs (u0, v0, u1, v1, u2, v2)

    SCB format (v2.x):
        Header:
            char[8]   magic = "r3d2Mesh"
            uint16    major (2)
            uint16    minor
            char[128] name
            uint32    vertex_count
            uint32    face_count
            uint32    flags
            float[6]  bounding_box
        Vertices:
            float3 * vertex_count
        Vertex Colors (if flags & 1):
            uint8[4] * vertex_count
        Central Point:
            float3
        Faces:
            uint32[3]  indices
            char[64]   material
            float[6]   UVs
    """
    meshes = []

    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 12:
        print(f"[SCB] File too small: {filepath}")
        return meshes

    # Read magic
    magic = data[0:8]
    if magic != b'r3d2Mesh':
        print(f"[SCB] Invalid magic: {magic} in {filepath}")
        return meshes

    mesh = SCBMesh()
    mesh.source_path = filepath

    offset = 8

    # Version
    mesh.version_major, mesh.version_minor = struct.unpack_from('<HH', data, offset)
    offset += 4

    # Name (128 bytes, null-terminated)
    name_bytes = data[offset:offset + 128]
    mesh.name = name_bytes.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
    offset += 128

    # Vertex count, face count
    vertex_count, face_count = struct.unpack_from('<II', data, offset)
    offset += 8

    # Flags
    flags = struct.unpack_from('<I', data, offset)[0]
    offset += 4
    has_vertex_colors = bool(flags & 1)

    # Bounding box (6 floats)
    bbox = struct.unpack_from('<6f', data, offset)
    mesh.bounding_box = (bbox[0:3], bbox[3:6])
    offset += 24

    # v3+ has an extra uint32 (vertex type flag)
    if mesh.version_major >= 3:
        _vertex_type = struct.unpack_from('<I', data, offset)[0]
        offset += 4

    # Vertices
    for _ in range(vertex_count):
        x, y, z = struct.unpack_from('<3f', data, offset)
        mesh.vertices.append((x, y, z))
        offset += 12

    # Vertex colors (if present)
    if has_vertex_colors:
        for _ in range(vertex_count):
            b_val, g_val, r_val, a_val = struct.unpack_from('<4B', data, offset)
            mesh.vertex_colors.append((r_val, g_val, b_val, a_val))
            offset += 4

    # Central point
    cx, cy, cz = struct.unpack_from('<3f', data, offset)
    mesh.central_point = (cx, cy, cz)
    offset += 12

    # Faces
    for _ in range(face_count):
        idx0, idx1, idx2 = struct.unpack_from('<3I', data, offset)
        offset += 12

        # Material name (64 bytes, null-terminated)
        mat_bytes = data[offset:offset + 64]
        mat_name = mat_bytes.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
        offset += 64

        # UVs (6 floats: u0, v0, u1, v1, u2, v2)
        u0, v0, u1, v1, u2, v2 = struct.unpack_from('<6f', data, offset)
        offset += 24

        mesh.faces.append((idx0, idx1, idx2))
        mesh.uvs.append(((u0, v0), (u1, v1), (u2, v2)))
        mesh.materials.append(mat_name)

    if not mesh.name:
        mesh.name = Path(filepath).stem

    meshes.append(mesh)
    return meshes


# ============================================================================
# SCO/SCB Writer (export support)
# ============================================================================

def write_scb(mesh_data, filepath: str, version_major=3, version_minor=2):
    """
    Write mesh data to SCB binary format.

    mesh_data: SCBMesh or SCOMesh (or any object with the same attributes)
    """
    with open(filepath, 'wb') as f:
        # Magic
        f.write(b'r3d2Mesh')

        # Version
        f.write(struct.pack('<HH', version_major, version_minor))

        # Name (128 bytes)
        name_bytes = mesh_data.name.encode('utf-8')[:127]
        f.write(name_bytes + b'\x00' * (128 - len(name_bytes)))

        vertex_count = len(mesh_data.vertices)
        face_count = len(mesh_data.faces)
        has_colors = hasattr(mesh_data, 'vertex_colors') and len(mesh_data.vertex_colors) > 0
        flags = 1 if has_colors else 0

        # Vertex count, face count, flags
        f.write(struct.pack('<III', vertex_count, face_count, flags))

        # Bounding box
        if mesh_data.vertices:
            xs = [v[0] for v in mesh_data.vertices]
            ys = [v[1] for v in mesh_data.vertices]
            zs = [v[2] for v in mesh_data.vertices]
            f.write(struct.pack('<6f', min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
        else:
            f.write(struct.pack('<6f', 0, 0, 0, 0, 0, 0))

        # Vertex type flag (v3+)
        if version_major >= 3:
            f.write(struct.pack('<I', 0))

        # Vertices
        for vx, vy, vz in mesh_data.vertices:
            f.write(struct.pack('<3f', vx, vy, vz))

        # Vertex colors
        if has_colors:
            for r, g, b, a in mesh_data.vertex_colors:
                f.write(struct.pack('<4B', b, g, r, a))  # BGRA order

        # Central point
        f.write(struct.pack('<3f', *mesh_data.central_point))

        # Faces
        for i, (idx0, idx1, idx2) in enumerate(mesh_data.faces):
            f.write(struct.pack('<3I', idx0, idx1, idx2))
            mat = mesh_data.materials[i] if i < len(mesh_data.materials) else "default"
            mat_bytes = mat.encode('utf-8')[:63]
            f.write(mat_bytes + b'\x00' * (64 - len(mat_bytes)))
            uv = mesh_data.uvs[i] if i < len(mesh_data.uvs) else ((0, 0), (0, 0), (0, 0))
            f.write(struct.pack('<6f', uv[0][0], uv[0][1], uv[1][0], uv[1][1], uv[2][0], uv[2][1]))


def write_sco(mesh_data, filepath: str):
    """Write mesh data to SCO text format."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('[ObjectBegin]\n')
        f.write(f'Name= {mesh_data.name}\n')
        f.write(f'CentralPoint= {mesh_data.central_point[0]:.6f} {mesh_data.central_point[1]:.6f} {mesh_data.central_point[2]:.6f}\n')
        if hasattr(mesh_data, 'pivot_point'):
            f.write(f'PivotPoint= {mesh_data.pivot_point[0]:.6f} {mesh_data.pivot_point[1]:.6f} {mesh_data.pivot_point[2]:.6f}\n')

        f.write(f'Verts= {len(mesh_data.vertices)}\n')
        for vx, vy, vz in mesh_data.vertices:
            f.write(f'{vx:.6f} {vy:.6f} {vz:.6f}\n')

        f.write(f'Faces= {len(mesh_data.faces)}\n')
        for i, (idx0, idx1, idx2) in enumerate(mesh_data.faces):
            mat = mesh_data.materials[i] if i < len(mesh_data.materials) else "default"
            uv = mesh_data.uvs[i] if i < len(mesh_data.uvs) else ((0, 0), (0, 0), (0, 0))
            f.write(f'3\t{idx0} {idx1} {idx2}\t{mat}\t'
                    f'{uv[0][0]:.6f} {uv[0][1]:.6f} '
                    f'{uv[1][0]:.6f} {uv[1][1]:.6f} '
                    f'{uv[2][0]:.6f} {uv[2][1]:.6f}\n')

        f.write('[ObjectEnd]\n')


# ============================================================================
# Blender Mesh Builder
# ============================================================================

def _build_blender_mesh(mesh_data, collection, apply_rotation=True, import_colors=True):
    """
    Build a Blender mesh object from parsed SCO/SCB data.

    Args:
        mesh_data: SCOMesh or SCBMesh
        collection: Blender collection to link the object into
        apply_rotation: Convert from League (Y-up right-hand) to Blender (Z-up) coords
        import_colors: Import vertex colors if available

    Returns:
        The created Blender object
    """
    name = mesh_data.name or Path(mesh_data.source_path).stem
    bl_mesh = bpy.data.meshes.new(name)
    bl_obj = bpy.data.objects.new(name, bl_mesh)

    # Transform vertices: League is left-handed Y-up, Blender is right-handed Z-up
    # Swap Y and Z, negate X to go from left-hand to right-hand
    if apply_rotation:
        verts = [(-v[0], v[2], v[1]) for v in mesh_data.vertices]
    else:
        verts = list(mesh_data.vertices)

    # Build faces — reverse winding if we applied the coordinate flip
    if apply_rotation:
        faces = [(f[0], f[2], f[1]) for f in mesh_data.faces]
    else:
        faces = list(mesh_data.faces)

    # Create mesh data
    bl_mesh.from_pydata(verts, [], faces)

    # Validate
    bl_mesh.validate(verbose=False, clean_customdata=False)
    bl_mesh.update()

    # ----- UV Layer ----- (bulk foreach_set for performance)
    if mesh_data.uvs:
        uv_layer = bl_mesh.uv_layers.new(name="UVMap")
        n_loops = len(bl_mesh.loops)
        uv_flat = [0.0] * (n_loops * 2)
        loop_offset = 0
        for fi, poly in enumerate(bl_mesh.polygons):
            if fi >= len(mesh_data.uvs):
                break
            face_uvs = mesh_data.uvs[fi]
            for li, loop_idx in enumerate(poly.loop_indices):
                if li >= len(face_uvs):
                    break
                # If winding was reversed, UV order must match
                uv_idx = [0, 2, 1][li] if apply_rotation else li
                u, v = face_uvs[uv_idx]
                uv_flat[loop_idx * 2] = u
                uv_flat[loop_idx * 2 + 1] = 1.0 - v  # Flip V for Blender
        uv_layer.data.foreach_set("uv", uv_flat)

    # ----- Materials -----
    # Collect unique material names and assign per-face
    mat_map = {}  # name -> slot index
    if mesh_data.materials:
        for mat_name in mesh_data.materials:
            if mat_name not in mat_map:
                slot_idx = len(mat_map)
                mat_map[mat_name] = slot_idx
                bl_mat = bpy.data.materials.get(mat_name)
                if bl_mat is None:
                    bl_mat = bpy.data.materials.new(mat_name)
                    bl_mat.use_nodes = True
                bl_mesh.materials.append(bl_mat)

        for fi, poly in enumerate(bl_mesh.polygons):
            if fi < len(mesh_data.materials):
                poly.material_index = mat_map.get(mesh_data.materials[fi], 0)

    # ----- Vertex Colors ----- (bulk foreach_set for performance)
    if import_colors and hasattr(mesh_data, 'vertex_colors') and mesh_data.vertex_colors:
        color_layer = bl_mesh.color_attributes.new(
            name="VertexColor",
            type='BYTE_COLOR',
            domain='CORNER'
        )
        n_loops = len(bl_mesh.loops)
        loop_vi = [0] * n_loops
        bl_mesh.loops.foreach_get("vertex_index", loop_vi)
        vc_count = len(mesh_data.vertex_colors)
        color_flat = [0.0] * (n_loops * 4)
        for i, vi in enumerate(loop_vi):
            if vi < vc_count:
                r, g, b, a = mesh_data.vertex_colors[vi]
                base = i * 4
                color_flat[base] = r / 255.0
                color_flat[base + 1] = g / 255.0
                color_flat[base + 2] = b / 255.0
                color_flat[base + 3] = a / 255.0
        color_layer.data.foreach_set("color", color_flat)

    # ----- Custom properties (metadata) -----
    bl_obj["league_sco_scb"] = True
    bl_obj["league_central_point"] = list(mesh_data.central_point)
    if hasattr(mesh_data, 'pivot_point'):
        bl_obj["league_pivot_point"] = list(mesh_data.pivot_point)
    bl_obj["league_source_format"] = "SCB" if isinstance(mesh_data, SCBMesh) else "SCO"

    # ----- Smooth shading -----
    for poly in bl_mesh.polygons:
        poly.use_smooth = True

    bl_mesh.update()

    # Link to collection
    collection.objects.link(bl_obj)

    return bl_obj


def _extract_mesh_from_blender(bl_obj):
    """
    Extract mesh data from a Blender object back into an SCBMesh for export.
    """
    mesh_data = SCBMesh()
    bl_mesh = bl_obj.data

    mesh_data.name = bl_obj.name
    mesh_data.central_point = tuple(bl_obj.get("league_central_point", (0, 0, 0)))

    # Use evaluated mesh to include modifiers
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = bl_obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.data

    # Ensure mesh has proper data
    eval_mesh.calc_loop_triangles()

    # Get UV layer
    uv_layer = eval_mesh.uv_layers.active

    # Get vertex color layer
    color_attr = None
    if eval_mesh.color_attributes:
        color_attr = eval_mesh.color_attributes.active_color

    # Transform back: Blender Z-up right-hand -> League Y-up left-hand
    # Blender vert (-x, z, y) -> League vert (x, y, z), so reverse: (x, y, z) = (-bx, bz, by)
    for v in eval_mesh.vertices:
        mesh_data.vertices.append((-v.co.x, v.co.z, v.co.y))

    # Vertex colors
    if color_attr and color_attr.domain == 'CORNER':
        # Need per-vertex colors — average from corners
        vert_colors = {}
        for poly in eval_mesh.polygons:
            for loop_idx in poly.loop_indices:
                vi = eval_mesh.loops[loop_idx].vertex_index
                c = color_attr.data[loop_idx].color
                if vi not in vert_colors:
                    vert_colors[vi] = []
                vert_colors[vi].append(c)

        for vi in range(len(eval_mesh.vertices)):
            if vi in vert_colors:
                cols = vert_colors[vi]
                avg = [sum(c[ch] for c in cols) / len(cols) for ch in range(4)]
                mesh_data.vertex_colors.append(
                    (int(avg[0] * 255), int(avg[1] * 255), int(avg[2] * 255), int(avg[3] * 255))
                )
            else:
                mesh_data.vertex_colors.append((255, 255, 255, 255))

    # Build faces + UVs
    # Triangulate first via bmesh
    bm = bmesh.new()
    bm.from_mesh(eval_mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(eval_mesh)
    bm.free()

    eval_mesh.update()
    uv_layer = eval_mesh.uv_layers.active

    for poly in eval_mesh.polygons:
        loops = list(poly.loop_indices)
        if len(loops) != 3:
            continue

        # Reverse winding for League left-hand coords
        idx0 = eval_mesh.loops[loops[0]].vertex_index
        idx1 = eval_mesh.loops[loops[2]].vertex_index
        idx2 = eval_mesh.loops[loops[1]].vertex_index
        mesh_data.faces.append((idx0, idx1, idx2))

        # Material
        if poly.material_index < len(eval_mesh.materials) and eval_mesh.materials[poly.material_index]:
            mesh_data.materials.append(eval_mesh.materials[poly.material_index].name)
        else:
            mesh_data.materials.append("default")

        # UVs — reverse V, reverse winding order
        if uv_layer:
            uv0 = uv_layer.data[loops[0]].uv
            uv1 = uv_layer.data[loops[2]].uv
            uv2 = uv_layer.data[loops[1]].uv
            mesh_data.uvs.append((
                (uv0[0], 1.0 - uv0[1]),
                (uv1[0], 1.0 - uv1[1]),
                (uv2[0], 1.0 - uv2[1]),
            ))
        else:
            mesh_data.uvs.append(((0, 0), (0, 0), (0, 0)))

    return mesh_data


# ============================================================================
# Blender Operators
# ============================================================================

class SCOSCB_OT_import(Operator, ImportHelper):
    """Import League of Legends SCO/SCB static mesh files"""
    bl_idname = "sco_scb.import_file"
    bl_label = "Import SCO/SCB"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default="*.sco;*.scb",
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
        description="Import vertex colors from SCB files",
        default=True,
    )

    create_collection: BoolProperty(
        name="Create Collection",
        description="Place imported meshes in a new collection",
        default=True,
    )

    def execute(self, context):
        import_count = 0
        errors = []

        # Determine target collection
        if self.create_collection:
            coll_name = "SCO/SCB Import"
            coll = bpy.data.collections.get(coll_name)
            if coll is None:
                coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(coll)
        else:
            coll = context.scene.collection

        # Import each selected file
        for file_elem in self.files:
            filepath = os.path.join(self.directory, file_elem.name)
            ext = Path(filepath).suffix.lower()

            try:
                if ext == '.sco':
                    meshes = parse_sco(filepath)
                elif ext == '.scb':
                    meshes = parse_scb(filepath)
                else:
                    errors.append(f"Unknown extension: {file_elem.name}")
                    continue

                for mesh in meshes:
                    _build_blender_mesh(
                        mesh, coll,
                        apply_rotation=self.apply_rotation,
                        import_colors=self.import_vertex_colors,
                    )
                    import_count += 1
                    print(f"[SCO/SCB] Imported: {mesh.name} ({len(mesh.vertices)} verts, {len(mesh.faces)} faces)")

            except Exception as e:
                errors.append(f"{file_elem.name}: {e}")
                print(f"[SCO/SCB] Error importing {file_elem.name}: {e}")

        if errors:
            self.report({'WARNING'}, f"Imported {import_count} mesh(es) with {len(errors)} error(s)")
        else:
            self.report({'INFO'}, f"Imported {import_count} mesh(es)")

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "apply_rotation")
        layout.prop(self, "import_vertex_colors")
        layout.prop(self, "create_collection")


class SCOSCB_OT_export(Operator):
    """Export selected Blender mesh(es) as SCB/SCO file(s)"""
    bl_idname = "sco_scb.export_file"
    bl_label = "Export SCO/SCB"
    bl_options = {'REGISTER'}

    filepath: StringProperty(
        subtype='FILE_PATH',
    )

    export_format: EnumProperty(
        name="Format",
        items=[
            ('SCB', "SCB (Binary)", "Export as binary SCB file"),
            ('SCO', "SCO (Text)", "Export as text SCO file"),
        ],
        default='SCB',
    )

    filter_glob: StringProperty(
        default="*.scb;*.sco",
        options={'HIDDEN'},
    )

    def execute(self, context):
        selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        export_count = 0
        base_path = Path(self.filepath)

        for obj in selected:
            try:
                mesh_data = _extract_mesh_from_blender(obj)

                if len(selected) == 1:
                    out_path = str(base_path)
                else:
                    ext = '.scb' if self.export_format == 'SCB' else '.sco'
                    out_path = str(base_path.parent / (obj.name + ext))

                if self.export_format == 'SCB':
                    write_scb(mesh_data, out_path)
                else:
                    write_sco(mesh_data, out_path)

                export_count += 1
                print(f"[SCO/SCB] Exported: {obj.name} -> {out_path}")

            except Exception as e:
                self.report({'WARNING'}, f"Failed to export {obj.name}: {e}")
                print(f"[SCO/SCB] Export error for {obj.name}: {e}")

        self.report({'INFO'}, f"Exported {export_count} mesh(es) as {self.export_format}")
        return {'FINISHED'}

    def invoke(self, context, event):
        selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if selected:
            ext = '.scb' if self.export_format == 'SCB' else '.sco'
            self.filepath = selected[0].name + ext
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SCOSCB_OT_batch_import(Operator):
    """Batch import all SCO/SCB files from a folder"""
    bl_idname = "sco_scb.batch_import"
    bl_label = "Batch Import SCO/SCB Folder"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(
        subtype='DIR_PATH',
    )

    apply_rotation: BoolProperty(
        name="Convert Coordinates",
        description="Convert from League Y-up left-hand to Blender Z-up right-hand",
        default=True,
    )

    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        default=True,
    )

    include_subfolders: BoolProperty(
        name="Include Subfolders",
        description="Recursively search subfolders for SCO/SCB files",
        default=True,
    )

    filter_glob: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    def execute(self, context):
        folder = Path(self.directory)
        if not folder.is_dir():
            self.report({'ERROR'}, f"Not a valid directory: {self.directory}")
            return {'CANCELLED'}

        coll = bpy.data.collections.new(f"SCO/SCB - {folder.name}")
        context.scene.collection.children.link(coll)

        pattern = '**/*' if self.include_subfolders else '*'
        files = list(folder.glob(f'{pattern}.sco')) + list(folder.glob(f'{pattern}.scb'))

        import_count = 0
        for filepath in sorted(files):
            try:
                ext = filepath.suffix.lower()
                if ext == '.sco':
                    meshes = parse_sco(str(filepath))
                else:
                    meshes = parse_scb(str(filepath))

                for mesh in meshes:
                    _build_blender_mesh(
                        mesh, coll,
                        apply_rotation=self.apply_rotation,
                        import_colors=self.import_vertex_colors,
                    )
                    import_count += 1

            except Exception as e:
                print(f"[SCO/SCB] Error importing {filepath.name}: {e}")

        self.report({'INFO'}, f"Batch imported {import_count} mesh(es) from {len(files)} file(s)")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SCOSCB_OT_import_map_folder(Operator):
    """Import all SCO/SCB meshes from a League map folder (auto-detect structure)"""
    bl_idname = "sco_scb.import_map_folder"
    bl_label = "Import Map Meshes"
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

    filter_glob: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    def execute(self, context):
        folder = Path(self.directory)
        if not folder.is_dir():
            self.report({'ERROR'}, f"Not a valid directory: {self.directory}")
            return {'CANCELLED'}

        # Typical League map folder structure:
        # MapXX/scene/  - main map geometry (NVR/SCO/SCB)
        # MapXX/data/   - additional data
        # Or flat structure with sco/scb files

        search_dirs = [folder]
        scene_dir = folder / "scene"
        if scene_dir.is_dir():
            search_dirs.append(scene_dir)
        data_dir = folder / "data"
        if data_dir.is_dir():
            search_dirs.append(data_dir)

        # Also check typical prop/object subdirs
        for sub in ['objects', 'props', 'meshes', 'models']:
            sub_dir = folder / sub
            if sub_dir.is_dir():
                search_dirs.append(sub_dir)

        coll = bpy.data.collections.new(f"Map Meshes - {folder.name}")
        context.scene.collection.children.link(coll)

        import_count = 0
        seen_files = set()

        for search_dir in search_dirs:
            for ext in ['*.sco', '*.scb']:
                for filepath in sorted(search_dir.rglob(ext)):
                    if filepath in seen_files:
                        continue
                    seen_files.add(filepath)

                    try:
                        if filepath.suffix.lower() == '.sco':
                            meshes = parse_sco(str(filepath))
                        else:
                            meshes = parse_scb(str(filepath))

                        for mesh in meshes:
                            _build_blender_mesh(
                                mesh, coll,
                                apply_rotation=self.apply_rotation,
                                import_colors=self.import_vertex_colors,
                            )
                            import_count += 1

                    except Exception as e:
                        print(f"[SCO/SCB] Error: {filepath.name}: {e}")

        self.report({'INFO'}, f"Imported {import_count} map mesh(es) from {len(seen_files)} file(s)")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SCOSCB_OT_info_selected(Operator):
    """Show info about the selected SCO/SCB object"""
    bl_idname = "sco_scb.info_selected"
    bl_label = "Mesh Info"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        mesh = obj.data
        info_parts = [
            f"Name: {obj.name}",
            f"Vertices: {len(mesh.vertices)}",
            f"Faces: {len(mesh.polygons)}",
            f"Materials: {len(mesh.materials)}",
            f"UV Layers: {len(mesh.uv_layers)}",
        ]

        if obj.get("league_sco_scb"):
            info_parts.append(f"Format: {obj.get('league_source_format', 'Unknown')}")
            cp = obj.get("league_central_point")
            if cp:
                info_parts.append(f"Central Point: ({cp[0]:.2f}, {cp[1]:.2f}, {cp[2]:.2f})")

        if mesh.color_attributes:
            info_parts.append(f"Vertex Colors: {len(mesh.color_attributes)} layer(s)")

        self.report({'INFO'}, " | ".join(info_parts))
        return {'FINISHED'}


# ============================================================================
# Property Groups
# ============================================================================

class ScoScbSettings(PropertyGroup):
    """Settings for SCO/SCB importer panel"""
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
        description="Import vertex colors from SCB files",
        default=True,
    )
    export_format: EnumProperty(
        name="Export Format",
        items=[
            ('SCB', "SCB (Binary)", "Export as binary SCB"),
            ('SCO', "SCO (Text)", "Export as text SCO"),
        ],
        default='SCB',
    )


# ============================================================================
# UI Panels (League Tools tab)
# ============================================================================

class VIEW3D_PT_sco_scb_panel(Panel):
    """SCO/SCB Static Mesh Tools"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "SCO/SCB Mesh Tools"
    bl_idname = "VIEW3D_PT_sco_scb_panel"
    bl_order = 50
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sco_scb_settings

        # Header
        layout.label(text="Static Mesh Import/Export", icon='MESH_DATA')
        layout.separator()

        # Import section
        box = layout.box()
        box.label(text="Import", icon='IMPORT')

        col = box.column(align=True)
        col.operator("sco_scb.import_file", text="Import SCO/SCB File(s)", icon='FILE')
        col.operator("sco_scb.batch_import", text="Batch Import Folder", icon='FILE_FOLDER')
        col.operator("sco_scb.import_map_folder", text="Import Map Folder", icon='WORLD')

        # Import options
        box2 = box.box()
        box2.label(text="Import Options", icon='PREFERENCES')
        box2.prop(settings, "apply_rotation")
        box2.prop(settings, "import_vertex_colors")

        layout.separator()

        # Export section
        box = layout.box()
        box.label(text="Export", icon='EXPORT')

        col = box.column(align=True)
        col.prop(settings, "export_format")
        col.operator("sco_scb.export_file", text="Export Selected", icon='EXPORT')

        layout.separator()

        # Info section
        obj = context.active_object
        if obj and obj.type == 'MESH':
            box = layout.box()
            box.label(text="Selected Mesh Info", icon='INFO')

            mesh = obj.data
            col = box.column(align=True)
            col.label(text=f"Name: {obj.name}")
            col.label(text=f"Vertices: {len(mesh.vertices)}")
            col.label(text=f"Faces: {len(mesh.polygons)}")
            col.label(text=f"Materials: {len(mesh.materials)}")

            if obj.get("league_sco_scb"):
                col.label(text=f"Format: {obj.get('league_source_format', '?')}")
                cp = obj.get("league_central_point")
                if cp:
                    col.label(text=f"Origin: ({cp[0]:.1f}, {cp[1]:.1f}, {cp[2]:.1f})")

            col.operator("sco_scb.info_selected", text="Full Info", icon='QUESTION')


# ============================================================================
# File Menu Integration
# ============================================================================

def menu_func_import(self, context):
    self.layout.operator(SCOSCB_OT_import.bl_idname,
                         text="League SCO/SCB Mesh (.sco/.scb)")


def menu_func_export(self, context):
    self.layout.operator(SCOSCB_OT_export.bl_idname,
                         text="League SCO/SCB Mesh (.sco/.scb)")


# ============================================================================
# Registration
# ============================================================================

_classes = (
    ScoScbSettings,
    SCOSCB_OT_import,
    SCOSCB_OT_export,
    SCOSCB_OT_batch_import,
    SCOSCB_OT_import_map_folder,
    SCOSCB_OT_info_selected,
    VIEW3D_PT_sco_scb_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.sco_scb_settings = bpy.props.PointerProperty(type=ScoScbSettings)

    # Add to File menu
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

    print("[SCO/SCB] Mesh tools registered")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    del bpy.types.Scene.sco_scb_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    print("[SCO/SCB] Mesh tools unregistered")
