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
import json

from . import mapgeo_parser
from . import utils
from . import import_mapgeo


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
        description="Default quality bitmask for meshes (each bit enables a quality level)",
        items=[
            ('31', "All Levels (31)", "Visible at all quality settings (Very Low to Very High)"),
            ('1', "Very Low Only (1)", "Visible only at Very Low quality"),
            ('2', "Low Only (2)", "Visible only at Low quality"),
            ('4', "Medium Only (4)", "Visible only at Medium quality"),
            ('8', "High Only (8)", "Visible only at High quality"),
            ('16', "Very High Only (16)", "Visible only at Very High quality"),
        ],
        default='31'
    )
    
    bucket_grid_mode: EnumProperty(
        name="Bucket Grid Mode",
        description="Which bucket grid to include in export",
        items=[
            ('NONE', "None", "Do not export bucket grids"),
            ('ORIGINAL', "Original (Recommended)", "Use Riot's original imported bucket grids"),
            ('CUSTOM', "Custom (Experimental - May crash game)", "Use custom-created bucket grids (UNTESTED - may break!)"),
        ],
        default='ORIGINAL'
    )
    
    def draw(self, context):
        """Draw export options"""
        layout = self.layout
        layout.prop(self, "export_version")
        layout.prop(self, "bucket_grid_mode")
        layout.separator()
        layout.label(text="Mesh Options:")
        layout.prop(self, "export_selected_only")
        layout.prop(self, "apply_modifiers")
        layout.prop(self, "triangulate")
        layout.prop(self, "export_normals")
        layout.prop(self, "export_uvs")
        layout.prop(self, "export_vertex_colors")
        layout.prop(self, "default_quality")
    
    def execute(self, context):
        """Execute the export"""
        try:
            # Update settings
            settings = context.scene.mapgeo_settings
            settings.last_export_path = self.filepath
            settings.export_version = self.export_version
            
            # Get objects to export (exclude bucket grid objects)
            if self.export_selected_only:
                objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
            else:
                objects = [obj for obj in context.scene.objects if obj.type == 'MESH']
            
            # Filter out bucket grid related objects
            objects = [obj for obj in objects if not obj.get("is_bucket_grid") and not obj.get("is_bucket_grid_bounds")]
            
            # Also exclude objects in bucket grid collections
            objects = [obj for obj in objects if not any(col.get("is_bucket_grid_collection") for col in obj.users_collection)]
            
            # If we have a known import source, only export meshes from that collection
            if settings.last_import_path:
                def collect_collection_meshes(collection, output):
                    for col_obj in collection.objects:
                        if col_obj.type == 'MESH':
                            output.add(col_obj)
                    for child in collection.children:
                        collect_collection_meshes(child, output)
                
                source_collections = [
                    col for col in bpy.data.collections
                    if col.get("source_mapgeo_path") == settings.last_import_path
                ]
                
                if source_collections:
                    collected_meshes = set()
                    for source_col in source_collections:
                        collect_collection_meshes(source_col, collected_meshes)
                    objects = [obj for obj in objects if obj in collected_meshes]
                else:
                    print("Warning: No source collection found for last_import_path; exporting all meshes")
            
            if not objects:
                self.report({'WARNING'}, "No mesh objects to export (excluding bucket grids)")
            
            # Create mapgeo data
            mapgeo = self.create_mapgeo(context, objects)
            
            # Handle bucket grids
            if self.bucket_grid_mode == 'ORIGINAL':
                self.collect_imported_bucket_grids(context, mapgeo)
            elif self.bucket_grid_mode == 'CUSTOM':
                self.collect_custom_bucket_grids(context, mapgeo)
                self.report({'WARNING'}, "Exporting CUSTOM bucket grids - UNTESTED, may crash the game!")
            
            # Write to file
            parser = mapgeo_parser.MapgeoParser()
            parser.write(self.filepath, mapgeo)
            
            self.report({'INFO'}, f"Successfully exported to {os.path.basename(self.filepath)} "
                        f"({len(objects)} meshes, {len(mapgeo.bucket_grids)} bucket grids)")
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
                eval_obj = None
                if self.apply_modifiers:
                    depsgraph = context.evaluated_depsgraph_get()
                    eval_obj = obj.evaluated_get(depsgraph)
                    mesh = eval_obj.to_mesh()
                else:
                    mesh = obj.data
                
                if mesh is None or not mesh.vertices:
                    continue
                
                # Triangulate if needed
                if self.triangulate:
                    bm = bmesh.new()
                    bm.from_mesh(mesh)
                    bmesh.ops.triangulate(bm, faces=bm.faces)
                    bm.to_mesh(mesh)
                    bm.free()
                
                # Update mesh (calculates normals, etc.)
                mesh.update()
                
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
                
                # Validate vertex count consistency (prevent crashes from buffer overruns)
                if mesh_entry.vertex_count != vertex_buffer.vertex_count:
                    print(f"ERROR: Vertex count mismatch for {obj.name}: mesh_entry claims {mesh_entry.vertex_count} but vertex_buffer has {vertex_buffer.vertex_count}")
                    print(f"  Correcting mesh_entry to match vertex_buffer")
                    mesh_entry.vertex_count = vertex_buffer.vertex_count
                
                mapgeo.meshes.append(mesh_entry)
                
                # Clean up if we created a temporary mesh
                if eval_obj is not None:
                    eval_obj.to_mesh_clear()
                
                print(f"Exported object: {obj.name}")
            
            except Exception as e:
                print(f"ERROR exporting object {obj.name}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        # Populate sampler_defs from import cache
        sampler_defs_data = list(import_mapgeo._imported_sampler_defs_cache)
        if sampler_defs_data:
            for sd in sampler_defs_data:
                mapgeo.sampler_defs.append(
                    mapgeo_parser.SamplerDef(index=sd["index"], name=sd["name"])
                )
            print(f"Restored {len(mapgeo.sampler_defs)} sampler defs from import cache")
        else:
            # Fallback: standard sampler defs for League maps
            mapgeo.sampler_defs.append(mapgeo_parser.SamplerDef(index=0, name="BAKED_DIFFUSE_TEXTURE"))
            mapgeo.sampler_defs.append(mapgeo_parser.SamplerDef(index=1, name="BAKED_DIFFUSE_TEXTURE_ALPHA"))
            print("No sampler defs cache found, using default sampler defs")
        
        # Deduplicate vertex buffer descriptions
        # Each VB has its own description, but many are identical;
        # collect unique descriptions and remap vertex_declaration_id on meshes
        unique_descs = []
        desc_key_to_idx = {}  # maps desc_key -> index in unique_descs
        vb_to_desc_idx = {}   # maps vertex_buffer_id -> index in unique_descs
        
        for vb_idx, vb in enumerate(mapgeo.vertex_buffers):
            if vb.description is None:
                continue
            # Build a hashable key from the description's elements
            desc_key = (vb.description.usage, tuple(
                (e.name, e.format) for e in vb.description.elements
            ))
            if desc_key not in desc_key_to_idx:
                desc_key_to_idx[desc_key] = len(unique_descs)
                unique_descs.append(vb.description)
            vb_to_desc_idx[vb_idx] = desc_key_to_idx[desc_key]
        
        # Store deduplicated descriptions on the mapgeo object
        mapgeo.vertex_buffer_descriptions = unique_descs
        print(f"Deduplicated VB descriptions: {len(mapgeo.vertex_buffers)} -> {len(unique_descs)}")
        
        # Update mesh vertex_declaration_id to point to deduplicated description index
        for mesh_entry in mapgeo.meshes:
            vb_id = mesh_entry.vertex_buffer_id
            if vb_id in vb_to_desc_idx:
                mesh_entry.vertex_declaration_id = vb_to_desc_idx[vb_id]
            # vertex_declaration_count stays 1
        
        return mapgeo
    
    def create_vertex_buffer(self, mesh, obj) -> mapgeo_parser.VertexBuffer:
        """Create vertex buffer from mesh"""
        
        # Define vertex elements
        elements = []
        offset = 0
        
        # Check if mesh has TEXCOORD5 attribute (bush animation anchor data)
        has_texcoord5 = "TEXCOORD5" in mesh.attributes
        
        # Check for vertex color attribute
        color_attr = None
        if self.export_vertex_colors:
            # Check Blender 5.0+ color_attributes first, then legacy vertex_colors
            if mesh.color_attributes and len(mesh.color_attributes) > 0:
                color_attr = mesh.color_attributes.active_color
            elif mesh.vertex_colors:
                color_attr = mesh.vertex_colors.active
        
        # Position (always include)
        elements.append(mapgeo_parser.VertexElement(
            mapgeo_parser.VertexElementName.POSITION,
            mapgeo_parser.VertexElementFormat.XYZ_FLOAT32,
            offset
        ))
        offset += 12
        
        # Normal
        if self.export_normals:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.NORMAL,
                mapgeo_parser.VertexElementFormat.XYZ_FLOAT32,
                offset
            ))
            offset += 12
        
        # PRIMARY_COLOR (BGRA format to match League's native format)
        if color_attr:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.PRIMARY_COLOR,
                mapgeo_parser.VertexElementFormat.BGRA_PACKED8888,
                offset
            ))
            offset += 4
        
        # UV0 (primary UV)
        if self.export_uvs and mesh.uv_layers:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.TEXCOORD0,
                mapgeo_parser.VertexElementFormat.XY_FLOAT32,
                offset
            ))
            offset += 8
        
        # TEXCOORD5 (bush animation anchors - XYZ_FLOAT32)
        if has_texcoord5:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.TEXCOORD5,
                mapgeo_parser.VertexElementFormat.XYZ_FLOAT32,
                offset
            ))
            offset += 12
        
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
        
        # Get TEXCOORD5 attribute
        tc5_attr = mesh.attributes.get("TEXCOORD5") if has_texcoord5 else None
        
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
            
            # Position in LOCAL space (not world space)
            # The transform matrix on the mesh entry handles world positioning
            # Import swaps: Mapgeo(X, Y_height, Z) -> Blender(X, Z_height, Y)
            # Export reverses: Blender(X, Y, Z) -> Mapgeo(X, Z, Y)
            local_pos = vert.co
            struct.pack_into('<fff', vertex_data, offset + current_offset,
                           local_pos.x, local_pos.z, local_pos.y)
            current_offset += 12
            
            # Normal in LOCAL space (same coordinate swap as position)
            if self.export_normals:
                local_normal = vert.normal
                struct.pack_into('<fff', vertex_data, offset + current_offset,
                               local_normal.x, local_normal.z, local_normal.y)
                current_offset += 12
            
            # Vertex Color in BGRA format (League native)
            if color_attr:
                if vert_idx in vert_to_loops and len(vert_to_loops[vert_idx]) > 0:
                    loop_idx = vert_to_loops[vert_idx][0]
                    color = color_attr.data[loop_idx].color
                    r = int(color[0] * 255)
                    g = int(color[1] * 255)
                    b = int(color[2] * 255)
                    a = int(color[3] * 255) if len(color) > 3 else 255
                    # Write as BGRA (blue, green, red, alpha)
                    struct.pack_into('<BBBB', vertex_data, offset + current_offset, b, g, r, a)
                else:
                    struct.pack_into('<BBBB', vertex_data, offset + current_offset, 255, 255, 255, 255)
                current_offset += 4
            
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
            
            # TEXCOORD5 - bush animation anchor positions
            if tc5_attr:
                vec = tc5_attr.data[vert_idx].vector
                # Blender(X, Y, Z) -> Mapgeo(X, Z, Y) coordinate swap
                struct.pack_into('<fff', vertex_data, offset + current_offset,
                               vec[0], vec[2], vec[1])
                current_offset += 12
        
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
        
        # Get quality and visibility from custom properties (set during import)
        # Try both old property names (mapgeo_*) and new names (*) for compatibility
        raw_quality = obj.get("quality", obj.get("mapgeo_quality", int(self.default_quality)))
        # Quality is a BITMASK (0-31), not enum. Clamp to valid range to prevent crashes
        mesh_entry.quality = max(0, min(31, int(raw_quality)))
        if raw_quality != mesh_entry.quality:
            print(f"WARNING: Object {obj.name} had invalid quality {raw_quality}, clamped to {mesh_entry.quality}")
        mesh_entry.visibility = obj.get("visibility_layer", obj.get("mapgeo_visibility", 
                                                                    mapgeo_parser.EnvironmentVisibility.ALL_LAYERS))
        mesh_entry.layer_transition_behavior = obj.get("layer_transition_behavior", 0)
        mesh_entry.render_flags = obj.get("render_flags", 0)
        mesh_entry.disable_backface_culling = bool(obj.get("disable_backface_culling", 0))
        
        # Version 18+ render region hash (visibility culling)
        if "render_region_hash" in obj:
            try:
                mesh_entry.unknown_version18_int = int(obj["render_region_hash"], 16)
            except (ValueError, TypeError):
                mesh_entry.unknown_version18_int = 0
        
        # Version 15+ baron hash (visibility controller)
        if "baron_hash" in obj:
            try:
                mesh_entry.visibility_controller_path_hash = int(obj["baron_hash"], 16)
            except (ValueError, TypeError):
                mesh_entry.visibility_controller_path_hash = 0
        
        # Calculate bounding volumes in LOCAL space (matching vertex buffer data)
        # The C# reference computes bbox from vertex buffer positions which are in local space
        # The transform matrix handles world positioning separately
        if mesh.vertices:
            # Bounding box from local-space vertices with Y/Z swap for mapgeo format
            # Blender(X, Y, Z) -> Mapgeo(X, Z, Y)
            min_x = min(v.co.x for v in mesh.vertices)
            min_y = min(v.co.z for v in mesh.vertices)  # Blender Z -> Mapgeo Y (height)
            min_z = min(v.co.y for v in mesh.vertices)  # Blender Y -> Mapgeo Z
            max_x = max(v.co.x for v in mesh.vertices)
            max_y = max(v.co.z for v in mesh.vertices)  # Blender Z -> Mapgeo Y (height)
            max_z = max(v.co.y for v in mesh.vertices)  # Blender Y -> Mapgeo Z
            
            mesh_entry.bounding_box = mapgeo_parser.BoundingBox(
                min=(min_x, min_y, min_z),
                max=(max_x, max_y, max_z)
            )
            
            # Bounding sphere (also in local space)
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            center_z = (min_z + max_z) / 2
            center = Vector((center_x, center_y, center_z))
            
            radius = max(
                (Vector((v.co.x, v.co.z, v.co.y)) - center).length 
                for v in mesh.vertices
            )
            
            mesh_entry.bounding_sphere = mapgeo_parser.BoundingSphere(
                center=(center_x, center_y, center_z),
                radius=radius
            )
        
        # Buffer references
        mesh_entry.vertex_buffer_id = vertex_buffer_id
        mesh_entry.vertex_declaration_id = vertex_buffer_id
        mesh_entry.vertex_declaration_count = 1
        mesh_entry.vertex_buffer_ids = [vertex_buffer_id]
        mesh_entry.vertex_count = len(mesh.vertices)
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
        
        mesh_entry.index_count = current_index
        
        # Convert Blender matrix_world back to League coordinate system
        # Import does: mat_blender = conversion @ mat_league @ conversion.inverted()
        # Export reverses: mat_league = conversion.inverted() @ mat_blender @ conversion
        conversion = Matrix([
            [1, 0, 0, 0],  # Blender X = League X
            [0, 0, 1, 0],  # Blender Y = League Z
            [0, 1, 0, 0],  # Blender Z = League Y
            [0, 0, 0, 1]
        ])
        mat_league = conversion.inverted() @ obj.matrix_world @ conversion
        
        # Convert to flat list in the same order the file stores it
        # Import reads: matrix_list[col*4+row] style (column-major in flat list)
        # So we write columns sequentially
        mesh_entry.transform_matrix = [
            mat_league[0][0], mat_league[1][0], mat_league[2][0], mat_league[3][0],  # col 0
            mat_league[0][1], mat_league[1][1], mat_league[2][1], mat_league[3][1],  # col 1
            mat_league[0][2], mat_league[1][2], mat_league[2][2], mat_league[3][2],  # col 2
            mat_league[0][3], mat_league[1][3], mat_league[2][3], mat_league[3][3],  # col 3
        ]
        
        # Reconstruct light channels from stored properties
        baked_light = mapgeo_parser.LightChannel()
        if "lightmap_texture" in obj:
            baked_light.texture = obj["lightmap_texture"]
        if "lightmap_scale" in obj:
            baked_light.scale = tuple(obj["lightmap_scale"])
        if "lightmap_bias" in obj:
            baked_light.bias = tuple(obj["lightmap_bias"])
        mesh_entry.baked_light = baked_light
        
        stationary_light = mapgeo_parser.LightChannel()
        if "stationary_light_texture" in obj:
            stationary_light.texture = obj["stationary_light_texture"]
        if "stationary_light_scale" in obj:
            stationary_light.scale = tuple(obj["stationary_light_scale"])
        if "stationary_light_bias" in obj:
            stationary_light.bias = tuple(obj["stationary_light_bias"])
        mesh_entry.stationary_light = stationary_light
        
        # Baked paint scale/bias  
        if "baked_paint_scale" in obj:
            mesh_entry.baked_paint_scale = tuple(obj["baked_paint_scale"])
        if "baked_paint_bias" in obj:
            mesh_entry.baked_paint_bias = tuple(obj["baked_paint_bias"])
        
        return mesh_entry
    
    def collect_imported_bucket_grids(self, context, mapgeo: mapgeo_parser.MapgeoFile):
        """Collect bucket grids from imported data (stored in module cache)"""
        
        # Retrieve bucket grids from module cache (populated during import)
        bucket_grids_data = list(import_mapgeo._imported_bucket_grids_cache.values())
        
        if not bucket_grids_data:
            print("No imported bucket grids found in cache")
            return
        
        print(f"Found {len(bucket_grids_data)} imported bucket grid(s) in cache")
        
        # Reconstruct BucketGrid objects from cached data
        for grid_data in bucket_grids_data:
            try:
                grid = mapgeo_parser.BucketGrid()
                grid.path_hash = grid_data.get("path_hash", 0)
                grid.min_x = grid_data.get("min_x", 0.0)
                grid.min_z = grid_data.get("min_z", 0.0)
                grid.max_x = grid_data.get("max_x", 0.0)
                grid.max_z = grid_data.get("max_z", 0.0)
                grid.bucket_size_x = grid_data.get("bucket_size_x", 512.0)
                grid.bucket_size_z = grid_data.get("bucket_size_z", 512.0)
                grid.buckets_per_side = int(grid_data.get("buckets_per_side", 1))
                grid.is_disabled = grid_data.get("is_disabled", False)
                grid.flags = int(grid_data.get("flags", 0))
                grid.unknown_v18_float = grid_data.get("unknown_v18_float", 0.0)
                grid.max_stickout_x = grid_data.get("max_stickout_x", 0.0)
                grid.max_stickout_z = grid_data.get("max_stickout_z", 0.0)
                
                # Restore vertices and indices
                grid.vertices = [tuple(v) for v in grid_data.get("vertices", [])]
                grid.indices = grid_data.get("indices", [])
                grid.face_visibility_flags = grid_data.get("face_visibility_flags", [])
                
                # Restore buckets
                for row_data in grid_data.get("buckets", []):
                    row = []
                    for bucket_data in row_data:
                        bucket = mapgeo_parser.GeometryBucket(
                            max_stickout_x=float(bucket_data.get("max_stickout_x", 0.0)),
                            max_stickout_z=float(bucket_data.get("max_stickout_z", 0.0)),
                            start_index=int(bucket_data.get("start_index", 0)),
                            base_vertex=int(bucket_data.get("base_vertex", 0)),
                            inside_face_count=int(bucket_data.get("inside_face_count", 0)),
                            sticking_out_face_count=int(bucket_data.get("sticking_out_face_count", 0))
                        )
                        row.append(bucket)
                    grid.buckets.append(row)
                
                mapgeo.bucket_grids.append(grid)
                print(f"  Exported imported bucket grid (hash: {hex(grid.path_hash)})")
            except Exception as e:
                print(f"  ERROR reconstructing bucket grid: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def collect_custom_bucket_grids(self, context, mapgeo: mapgeo_parser.MapgeoFile):
        """Collect bucket grids from custom-created data (EXPERIMENTAL)"""
        
        custom_bucket_grid_objects = []
        
        for obj in context.scene.objects:
            # Find custom bucket grid meshes
            if obj.get("is_bucket_grid") and obj.get("is_custom_bucket_grid"):
                custom_bucket_grid_objects.append(obj)
        
        if not custom_bucket_grid_objects:
            print("No custom bucket grids found")
            return
        
        print(f"Found {len(custom_bucket_grid_objects)} custom bucket grid mesh(es)")
        print("WARNING: Custom bucket grids are EXPERIMENTAL and untested in-game!")
        
        # Convert custom bucket grids to BucketGrid data structures
        for grid_obj in custom_bucket_grid_objects:
            try:
                bucket_grid = self.bucket_grid_from_object(grid_obj)
                if bucket_grid:
                    mapgeo.bucket_grids.append(bucket_grid)
                    print(f"  Exported custom bucket grid: {grid_obj.name}")
            except Exception as e:
                print(f"  ERROR exporting bucket grid {grid_obj.name}: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def bucket_grid_from_object(self, obj):
        """Convert a custom bucket grid object back to BucketGrid data structure"""
        
        grid = mapgeo_parser.BucketGrid()
        
        # Retrieve metadata
        grid.min_x = obj.get("bounds_min_x", 0.0)
        grid.min_z = obj.get("bounds_min_y", 0.0)  # Note: Y in Blender is Z in mapgeo
        grid.max_x = obj.get("bounds_max_x", 0.0)
        grid.max_z = obj.get("bounds_max_y", 0.0)
        grid.bucket_size_x = obj.get("bucket_size_x", 512.0)
        grid.bucket_size_z = obj.get("bucket_size_z", 512.0)
        grid.buckets_per_side = int(obj.get("buckets_per_side", 1))
        grid.path_hash = int(obj.get("path_hash", "00000000"), 16) if isinstance(obj.get("path_hash"), str) else int(obj.get("path_hash", 0))
        grid.unknown_v18_float = obj.get("unknown_v18_float", 0.0)
        grid.is_disabled = obj.get("is_disabled", False)
        grid.flags = int(obj.get("flags", 0))
        grid.max_stickout_x = obj.get("stickout_x", 0.0)
        grid.max_stickout_z = obj.get("stickout_z", 0.0)
        
        # Ensure buckets_per_side is valid for ushort
        if grid.buckets_per_side > 65535:
            print(f"WARNING: buckets_per_side {grid.buckets_per_side} exceeds ushort max (65535)")
            grid.buckets_per_side = 65535
        elif grid.buckets_per_side < 0:
            grid.buckets_per_side = 1
        
        # Get mesh data
        mesh = obj.data
        if not mesh or not mesh.vertices or not mesh.polygons:
            print(f"Skipping empty bucket grid mesh: {obj.name}")
            return None
        
        # Convert vertices from Blender to mapgeo format (X/Y/Z → X/Z/Y swap back)
        # The vertices in Blender are already in world space from import
        # We need to swap back: Blender(X,Y,Z) → Mapgeo(X,Z,Y) for vertical
        grid.vertices = []
        for vert in mesh.vertices:
            # Blender (X, Y, Z) with Z=up → Mapgeo(X, Y=height, Z)
            # So we need: (x, z, y) in mapgeo format
            grid.vertices.append((vert.co.x, vert.co.z, vert.co.y))
        
        # Get indices - they should be triangulated
        grid.indices = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                for vert_idx in poly.vertices:
                    if vert_idx > 65535:
                        print(f"WARNING: Vertex index {vert_idx} exceeds ushort max in bucket grid {obj.name}")
                    grid.indices.append(min(vert_idx, 65535))
            else:
                print(f"WARNING: Non-triangle face in bucket grid {obj.name}")
        
        # Reconstruct bucket data from stored JSON
        bucket_data_json = obj.get("bucket_data")
        if bucket_data_json:
            try:
                bucket_data = json.loads(bucket_data_json)
                grid.buckets = []
                
                for row_data in bucket_data:
                    row = []
                    for bucket_info in row_data:
                        inside_count = int(bucket_info.get('inside_face_count', 0))
                        sticking_count = int(bucket_info.get('sticking_out_face_count', 0))
                        
                        # Clamp to ushort range
                        if inside_count > 65535:
                            print(f"WARNING: inside_face_count {inside_count} exceeds ushort max")
                            inside_count = 65535
                        if sticking_count > 65535:
                            print(f"WARNING: sticking_out_face_count {sticking_count} exceeds ushort max")
                            sticking_count = 65535
                        
                        bucket = mapgeo_parser.GeometryBucket(
                            max_stickout_x=float(bucket_info.get('max_stickout_x', 0.0)),
                            max_stickout_z=float(bucket_info.get('max_stickout_z', 0.0)),
                            start_index=int(bucket_info.get('start_index', 0)),
                            base_vertex=int(bucket_info.get('base_vertex', 0)),
                            inside_face_count=inside_count,
                            sticking_out_face_count=sticking_count
                        )
                        row.append(bucket)
                    grid.buckets.append(row)
            except Exception as e:
                print(f"Failed to parse bucket data from {obj.name}: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        
        return grid


def menu_func_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_mapgeo.bl_idname, text="League of Legends Mapgeo (.mapgeo)")


def register():
    bpy.utils.register_class(EXPORT_SCENE_OT_mapgeo)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(EXPORT_SCENE_OT_mapgeo)
