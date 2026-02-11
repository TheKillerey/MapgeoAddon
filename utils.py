"""
Utility functions for Mapgeo addon
"""

import bpy
from mathutils import Vector, Matrix
import struct


def calculate_bounding_sphere(vertices):
    """Calculate bounding sphere for a list of vertices"""
    if not vertices:
        return (0.0, 0.0, 0.0), 0.0
    
    # Calculate center
    center = Vector((0.0, 0.0, 0.0))
    for v in vertices:
        if isinstance(v, Vector):
            center += v
        else:
            center += Vector(v)
    center /= len(vertices)
    
    # Calculate radius
    radius = 0.0
    for v in vertices:
        if isinstance(v, Vector):
            dist = (v - center).length
        else:
            dist = (Vector(v) - center).length
        radius = max(radius, dist)
    
    return tuple(center), radius


def calculate_bounding_box(vertices):
    """Calculate axis-aligned bounding box for a list of vertices"""
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    
    for v in vertices:
        if isinstance(v, Vector):
            x, y, z = v.x, v.y, v.z
        else:
            x, y, z = v[0], v[1], v[2]
        
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        min_z = min(min_z, z)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
        max_z = max(max_z, z)
    
    return (min_x, min_y, min_z), (max_x, max_y, max_z)


def matrix_to_list(matrix):
    """Convert Blender Matrix to a flat list (row-major)"""
    result = []
    for row in matrix:
        result.extend(row)
    return result


def list_to_matrix(data):
    """Convert a flat list to Blender Matrix (row-major)"""
    if len(data) != 16:
        raise ValueError("Matrix data must have 16 elements")
    
    return Matrix([
        [data[0], data[1], data[2], data[3]],
        [data[4], data[5], data[6], data[7]],
        [data[8], data[9], data[10], data[11]],
        [data[12], data[13], data[14], data[15]]
    ])


def get_or_create_collection(name, parent=None):
    """Get or create a collection with the given name"""
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    
    collection = bpy.data.collections.new(name)
    
    if parent:
        parent.children.link(collection)
    else:
        bpy.context.scene.collection.children.link(collection)
    
    return collection


def select_objects(objects, active=None):
    """Select the given objects and optionally set one as active"""
    bpy.ops.object.select_all(action='DESELECT')
    
    for obj in objects:
        obj.select_set(True)
    
    if active and active in objects:
        bpy.context.view_layer.objects.active = active
    elif objects:
        bpy.context.view_layer.objects.active = objects[0]


def get_mesh_stats(mesh):
    """Get statistics for a mesh"""
    return {
        'vertices': len(mesh.vertices),
        'edges': len(mesh.edges),
        'faces': len(mesh.polygons),
        'triangles': sum(1 for p in mesh.polygons if len(p.vertices) == 3),
        'materials': len(mesh.materials),
        'uv_layers': len(mesh.uv_layers),
        'vertex_colors': len(mesh.vertex_colors),
    }


def validate_mesh_for_export(mesh):
    """Validate that a mesh can be exported"""
    errors = []
    warnings = []
    
    if len(mesh.vertices) == 0:
        errors.append("Mesh has no vertices")
    
    if len(mesh.polygons) == 0:
        errors.append("Mesh has no faces")
    
    # Check for non-triangular faces
    non_tris = sum(1 for p in mesh.polygons if len(p.vertices) != 3)
    if non_tris > 0:
        warnings.append(f"Mesh has {non_tris} non-triangular faces (will be triangulated)")
    
    # Check vertex count limit
    if len(mesh.vertices) > 65535:
        warnings.append("Mesh has more than 65535 vertices (may need 32-bit indices)")
    
    return errors, warnings


def create_debug_empty(name, location, size=0.5):
    """Create an empty object for debugging/visualization"""
    empty = bpy.data.objects.new(name, None)
    empty.location = location
    empty.empty_display_size = size
    empty.empty_display_type = 'SPHERE'
    return empty


def print_mapgeo_info(mapgeo):
    """Print information about a mapgeo file"""
    print("\n" + "="*60)
    print("Mapgeo File Information")
    print("="*60)
    print(f"Version: {mapgeo.version}")
    print(f"Vertex Buffers: {len(mapgeo.vertex_buffers)}")
    print(f"Index Buffers: {len(mapgeo.index_buffers)}")
    print(f"Meshes: {len(mapgeo.meshes)}")
    
    total_vertices = sum(vb.vertex_count for vb in mapgeo.vertex_buffers)
    total_indices = sum(ib.index_count for ib in mapgeo.index_buffers)
    
    print(f"Total Vertices: {total_vertices}")
    print(f"Total Indices: {total_indices}")
    print(f"Total Triangles: {total_indices // 3}")
    
    print("\nMesh Details:")
    for i, mesh in enumerate(mapgeo.meshes):
        print(f"  Mesh {i}:")
        print(f"    Quality: {mesh.quality}")
        print(f"    Visibility: {mesh.visibility}")
        print(f"    Primitives: {len(mesh.primitives)}")
        for j, prim in enumerate(mesh.primitives):
            print(f"      Primitive {j}: {prim.material} ({prim.index_count} indices)")
    
    print("="*60 + "\n")


def format_file_size(size_bytes):
    """Format byte size to human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def clamp(value, min_value, max_value):
    """Clamp a value between min and max"""
    return max(min_value, min(value, max_value))


def lerp(a, b, t):
    """Linear interpolation between a and b"""
    return a + (b - a) * t


def vector_to_tuple(vector):
    """Convert Vector to tuple"""
    return (vector.x, vector.y, vector.z)


def ensure_material(name, create_if_missing=True):
    """Get or create a material"""
    mat = bpy.data.materials.get(name)
    
    if mat is None and create_if_missing:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
    
    return mat


class ProgressTracker:
    """Simple progress tracker for long operations"""
    
    def __init__(self, total, description="Progress"):
        self.total = total
        self.current = 0
        self.description = description
    
    def update(self, increment=1):
        self.current += increment
        if self.total > 0:
            percent = (self.current / self.total) * 100
            print(f"{self.description}: {self.current}/{self.total} ({percent:.1f}%)")
    
    def finish(self):
        print(f"{self.description}: Complete!")


# Constants
LEAGUE_TO_BLENDER_SCALE = 0.01  # Adjust as needed
BLENDER_TO_LEAGUE_SCALE = 100.0
