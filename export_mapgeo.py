"""
Export Operator for Mapgeo Files
Exports Blender mesh objects to .mapgeo format
"""

import bpy
import bmesh
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector, Matrix
import struct
import os

from . import mapgeo_parser
from . import utils


class EXPORT_SCENE_OT_mapgeo(bpy.types.Operator, ExportHelper):
    """Export to League of Legends Mapgeo file"""
    bl_idname = "export_scene.mapgeo"
    bl_label = "Export Mapgeo"
    bl_options = {'REGISTER'}
    
    # File browser
    filename_ext = ".mapgeo"
    filter_glob: StringProperty(
        default="*.mapgeo",
        options={'HIDDEN'},
    )
    
    # Export options
    export_version: IntProperty(
        name="Mapgeo Version",
        description="Version of mapgeo format to export",
        default=17,
        min=13,
        max=18,
    )
    
    export_selected_only: BoolProperty(
        name="Selected Only",
        description="Export only selected objects",
        default=False,
    )
    
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers before export",
        default=True,
    )
    
    triangulate: BoolProperty(
        name="Triangulate Faces",
        description="Automatically triangulate faces",
        default=True,
    )
    
    export_normals: BoolProperty(
        name="Export Normals",
        description="Export vertex normals",
        default=True,
    )
    
    export_uvs: BoolProperty(
        name="Export UVs",
        description="Export UV coordinates",
        default=True,
    )
    
    export_vertex_colors: BoolProperty(
        name="Export Vertex Colors",
        description="Export vertex color data",
        default=True,
    )
    
    default_quality: EnumProperty(
        name="Default Quality",
        description="Default quality level for meshes",
        items=[
            ('0', "Very Low", "Very Low Quality"),
            ('1', "Low", "Low Quality"),
            ('2', "Medium", "Medium Quality"),
            ('3', "High", "High Quality"),
            ('4', "Very High", "Very High Quality"),
        ],
        default='2'
    )
    
    def execute(self, context):
        """Execute the export"""
        try:
            # Update settings
            settings = context.scene.mapgeo_settings
            settings.last_export_path = self.filepath
            settings.export_version = self.export_version
            
            # Get objects to export
            if self.export_selected_only:
                objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
            else:
                objects = [obj for obj in context.scene.objects if obj.type == 'MESH']
            
            if not objects:
                self.report({'ERROR'}, "No mesh objects to export")
                return {'CANCELLED'}
            
            # Create mapgeo data
            mapgeo = self.create_mapgeo(context, objects)
            
            # Write to file
            parser = mapgeo_parser.MapgeoParser()
            parser.write(self.filepath, mapgeo)
            
            self.report({'INFO'}, f"Successfully exported {len(objects)} objects to {os.path.basename(self.filepath)}")
            return {'FINISHED'}
        
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def create_mapgeo(self, context, objects) -> mapgeo_parser.MapgeoFile:
        """Create mapgeo data structure from Blender objects"""
        
        mapgeo = mapgeo_parser.MapgeoFile()
        mapgeo.version = self.export_version
        
        # Process each object
        for obj_idx, obj in enumerate(objects):
            try:
                # Get mesh data
                if self.apply_modifiers:
                    depsgraph = context.evaluated_depsgraph_get()
                    eval_obj = obj.evaluated_get(depsgraph)
                    mesh = eval_obj.to_mesh()
                else:
                    mesh = obj.to_mesh()
                
                if mesh is None:
                    continue
                
                # Triangulate if needed
                if self.triangulate:
                    bm = bmesh.new()
                    bm.from_mesh(mesh)
                    bmesh.ops.triangulate(bm, faces=bm.faces)
                    bm.to_mesh(mesh)
                    bm.free()
                
                # Calculate normals
                mesh.calc_normals_split()
                
                # Create vertex buffer
                vertex_buffer = self.create_vertex_buffer(mesh, obj)
                vertex_buffer_id = len(mapgeo.vertex_buffers)
                mapgeo.vertex_buffers.append(vertex_buffer)
                
                # Create index buffer
                index_buffer = self.create_index_buffer(mesh)
                index_buffer_id = len(mapgeo.index_buffers)
                mapgeo.index_buffers.append(index_buffer)
                
                # Create mesh entry
                mesh_entry = self.create_mesh_entry(mesh, obj, vertex_buffer_id, index_buffer_id)
                mapgeo.meshes.append(mesh_entry)
                
                # Clean up
                obj.to_mesh_clear()
                
                print(f"Exported object: {obj.name}")
            
            except Exception as e:
                print(f"Error exporting object {obj.name}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        return mapgeo
    
    def create_vertex_buffer(self, mesh, obj) -> mapgeo_parser.VertexBuffer:
        """Create vertex buffer from mesh"""
        
        # Define vertex elements
        elements = []
        offset = 0
        
        # Position (always include)
        elements.append(mapgeo_parser.VertexElement(
            mapgeo_parser.VertexElementName.POSITION,
            mapgeo_parser.VertexElementFormat.FLOAT3,
            offset
        ))
        offset += 12
        
        # Normal
        if self.export_normals:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.NORMAL,
                mapgeo_parser.VertexElementFormat.FLOAT3,
                offset
            ))
            offset += 12
        
        # UV0 (primary UV)
        if self.export_uvs and mesh.uv_layers:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.TEXCOORD0,
                mapgeo_parser.VertexElementFormat.FLOAT2,
                offset
            ))
            offset += 8
        
        # Vertex Color
        if self.export_vertex_colors and mesh.vertex_colors:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.PRIMARY_COLOR,
                mapgeo_parser.VertexElementFormat.UBYTE4N,
                offset
            ))
            offset += 4
        
        # Create description
        description = mapgeo_parser.VertexBufferDescription(
            usage=0,  # Static
            elements=elements
        )
        
        vertex_size = description.get_vertex_size()
        vertex_count = len(mesh.vertices)
        
        # Build vertex data
        vertex_data = bytearray(vertex_size * vertex_count)
        
        # Get UV layer
        uv_layer = mesh.uv_layers.active if mesh.uv_layers else None
        color_layer = mesh.vertex_colors.active if mesh.vertex_colors else None
        
        # Build a map from vertex index to loop indices for UVs and colors
        vert_to_loops = {}
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                loop = mesh.loops[loop_idx]
                vert_idx = loop.vertex_index
                if vert_idx not in vert_to_loops:
                    vert_to_loops[vert_idx] = []
                vert_to_loops[vert_idx].append(loop_idx)
        
        # Write vertex data
        for vert_idx, vert in enumerate(mesh.vertices):
            offset = vert_idx * vertex_size
            current_offset = 0
            
            # Position (transform to world space)
            world_pos = obj.matrix_world @ vert.co
            struct.pack_into('<fff', vertex_data, offset + current_offset,
                           world_pos.x, world_pos.y, world_pos.z)
            current_offset += 12
            
            # Normal
            if self.export_normals:
                world_normal = obj.matrix_world.to_3x3() @ vert.normal
                world_normal.normalize()
                struct.pack_into('<fff', vertex_data, offset + current_offset,
                               world_normal.x, world_normal.y, world_normal.z)
                current_offset += 12
            
            # UV
            if self.export_uvs and uv_layer:
                # Get first loop for this vertex
                if vert_idx in vert_to_loops and len(vert_to_loops[vert_idx]) > 0:
                    loop_idx = vert_to_loops[vert_idx][0]
                    uv = uv_layer.data[loop_idx].uv
                    # Flip V coordinate
                    struct.pack_into('<ff', vertex_data, offset + current_offset,
                                   uv[0], 1.0 - uv[1])
                else:
                    struct.pack_into('<ff', vertex_data, offset + current_offset, 0.0, 0.0)
                current_offset += 8
            
            # Vertex Color
            if self.export_vertex_colors and color_layer:
                if vert_idx in vert_to_loops and len(vert_to_loops[vert_idx]) > 0:
                    loop_idx = vert_to_loops[vert_idx][0]
                    color = color_layer.data[loop_idx].color
                    r = int(color[0] * 255)
                    g = int(color[1] * 255)
                    b = int(color[2] * 255)
                    a = int(color[3] * 255) if len(color) > 3 else 255
                    struct.pack_into('<BBBB', vertex_data, offset + current_offset, r, g, b, a)
                else:
                    struct.pack_into('<BBBB', vertex_data, offset + current_offset, 255, 255, 255, 255)
                current_offset += 4
        
        return mapgeo_parser.VertexBuffer(
            description=description,
            data=bytes(vertex_data),
            vertex_count=vertex_count
        )
    
    def create_index_buffer(self, mesh) -> mapgeo_parser.IndexBuffer:
        """Create index buffer from mesh"""
        
        index_count = len(mesh.polygons) * 3
        index_data = bytearray(index_count * 2)  # U16 format
        
        idx = 0
        for poly in mesh.polygons:
            if len(poly.vertices) != 3:
                print(f"Warning: Non-triangle face found (vertices: {len(poly.vertices)})")
                continue
            
            for vert_idx in poly.vertices:
                struct.pack_into('<H', index_data, idx * 2, vert_idx)
                idx += 1
        
        return mapgeo_parser.IndexBuffer(
            data=bytes(index_data),
            format=0,  # U16
            index_count=idx,
            visibility=mapgeo_parser.EnvironmentVisibility.ALL_LAYERS
        )
    
    def create_mesh_entry(self, mesh, obj, vertex_buffer_id, index_buffer_id) -> mapgeo_parser.Mesh:
        """Create mesh entry"""
        
        mesh_entry = mapgeo_parser.Mesh()
        
        # Get quality from custom property or use default
        mesh_entry.quality = obj.get("mapgeo_quality", int(self.default_quality))
        mesh_entry.visibility = obj.get("mapgeo_visibility", 
                                       mapgeo_parser.EnvironmentVisibility.ALL_LAYERS)
        
        # Calculate bounding volumes in world space
        if mesh.vertices:
            # Get all vertex positions in world space
            world_verts = [obj.matrix_world @ v.co for v in mesh.vertices]
            
            # Bounding box
            min_x = min(v.x for v in world_verts)
            min_y = min(v.y for v in world_verts)
            min_z = min(v.z for v in world_verts)
            max_x = max(v.x for v in world_verts)
            max_y = max(v.y for v in world_verts)
            max_z = max(v.z for v in world_verts)
            
            mesh_entry.bounding_box = mapgeo_parser.BoundingBox(
                min=(min_x, min_y, min_z),
                max=(max_x, max_y, max_z)
            )
            
            # Bounding sphere
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            center_z = (min_z + max_z) / 2
            center = Vector((center_x, center_y, center_z))
            
            radius = max((Vector(v) - center).length for v in world_verts)
            
            mesh_entry.bounding_sphere = mapgeo_parser.BoundingSphere(
                center=(center_x, center_y, center_z),
                radius=radius
            )
        
        # Buffer references
        mesh_entry.vertex_buffer_id = vertex_buffer_id
        mesh_entry.index_buffer_id = index_buffer_id
        
        # Create primitive(s)
        # Group by material
        material_groups = {}
        
        for poly_idx, poly in enumerate(mesh.polygons):
            mat_idx = poly.material_index
            mat_name = mesh.materials[mat_idx].name if mat_idx < len(mesh.materials) and mesh.materials[mat_idx] else "Default"
            
            if mat_name not in material_groups:
                material_groups[mat_name] = []
            
            material_groups[mat_name].append(poly_idx)
        
        # Create primitives
        current_index = 0
        for mat_name, poly_indices in material_groups.items():
            index_count = len(poly_indices) * 3
            
            # Calculate vertex range
            all_verts = set()
            for poly_idx in poly_indices:
                poly = mesh.polygons[poly_idx]
                all_verts.update(poly.vertices)
            
            min_vertex = min(all_verts) if all_verts else 0
            max_vertex = max(all_verts) if all_verts else 0
            
            primitive = mapgeo_parser.MeshPrimitive(
                material=mat_name,
                start_index=current_index,
                index_count=index_count,
                min_vertex=min_vertex,
                max_vertex=max_vertex
            )
            
            mesh_entry.primitives.append(primitive)
            current_index += index_count
        
        # Transform matrix (identity since we're transforming vertices to world space)
        mesh_entry.transform_matrix = [
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        ]
        
        return mesh_entry


def menu_func_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_mapgeo.bl_idname, text="League of Legends Mapgeo (.mapgeo)")


def register():
    bpy.utils.register_class(EXPORT_SCENE_OT_mapgeo)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(EXPORT_SCENE_OT_mapgeo)
