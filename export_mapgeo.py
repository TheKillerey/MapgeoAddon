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
import re

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
    
    # Modal execution state for background mode
    _timer = None
    _background_task = None
    _background_step = 0
    
    # Export options
    export_version: IntProperty(
        name="Mapgeo Version",
        description="Version of mapgeo format to export",
        default=18,
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
            ('CUSTOM', "Custom", "Use custom-created bucket grids from the scene"),
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
        # Check execution mode for progress display
        settings = context.scene.mapgeo_settings
        show_progress = (settings.execution_mode == 'BACKGROUND')
        
        try:
            if show_progress:
                context.window_manager.progress_begin(0, 100)
                context.window_manager.progress_update(5)
            
            # Update settings
            settings.last_export_path = self.filepath
            settings.export_version = self.export_version
            
            if show_progress:
                context.window_manager.progress_update(10)
            
            # Get objects to export (exclude bucket grid objects)
            if self.export_selected_only:
                objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
            else:
                objects = [obj for obj in context.scene.objects if obj.type == 'MESH']
            
            # Filter out bucket grid related objects
            objects = [obj for obj in objects if not obj.get("is_bucket_grid") and not obj.get("is_bucket_grid_bounds")]
            
            # Also exclude objects in bucket grid collections
            objects = [obj for obj in objects if not any(col.get("is_bucket_grid_collection") for col in obj.users_collection)]
            
            if show_progress:
                context.window_manager.progress_update(20)
            
            # Find meshes from the _Meshes subcollection only
            # (excludes Fog, Sun, Particles, etc.)
            root_name = settings.root_collection_name if hasattr(settings, 'root_collection_name') and settings.root_collection_name else "rey_map"
            
            def collect_collection_meshes(collection, output):
                for col_obj in collection.objects:
                    if col_obj.type == 'MESH':
                        output.add(col_obj)
                for child in collection.children:
                    collect_collection_meshes(child, output)
            
            # Only collect from _Meshes subcollection
            meshes_col = bpy.data.collections.get(f"{root_name}_Meshes")
            if meshes_col:
                collected_meshes = set()
                collect_collection_meshes(meshes_col, collected_meshes)
                objects = [obj for obj in objects if obj in collected_meshes]
                print(f"Exporting from '{meshes_col.name}': {len(objects)} mesh objects")
            elif bpy.data.collections.get(root_name):
                # Fallback: root exists but no _Meshes child — use root
                root_collection = bpy.data.collections.get(root_name)
                collected_meshes = set()
                collect_collection_meshes(root_collection, collected_meshes)
                objects = [obj for obj in objects if obj in collected_meshes]
                print(f"Warning: No '{root_name}_Meshes' found; using root '{root_name}': {len(objects)} meshes")
            else:
                print(f"Warning: No collection '{root_name}' or '{root_name}_Meshes' found; exporting all meshes")
            
            if not objects:
                self.report({'WARNING'}, "No mesh objects to export (excluding bucket grids)")
            
            if show_progress:
                context.window_manager.progress_update(30)
            
            # Create mapgeo data
            mapgeo = self.create_mapgeo(context, objects)
            
            if show_progress:
                context.window_manager.progress_update(60)
            
            # Handle bucket grids
            if self.bucket_grid_mode == 'ORIGINAL':
                self.collect_imported_bucket_grids(context, mapgeo)
            elif self.bucket_grid_mode == 'CUSTOM':
                self.collect_custom_bucket_grids(context, mapgeo)

            if show_progress:
                context.window_manager.progress_update(75)

            if show_progress:
                context.window_manager.progress_update(85)
            
            # Write to file
            parser = mapgeo_parser.MapgeoParser()
            parser.write(self.filepath, mapgeo)
            
            if show_progress:
                context.window_manager.progress_update(100)
                context.window_manager.progress_end()
            
            self.report({'INFO'}, f"Successfully exported to {os.path.basename(self.filepath)} "
                        f"({len(objects)} meshes, {len(mapgeo.bucket_grids)} bucket grids)")
            return {'FINISHED'}
        
        except Exception as e:
            if show_progress:
                context.window_manager.progress_end()
            self.report({'ERROR'}, f"Failed to export mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

    def invoke(self, context, event):
        """Handle operator invocation - check execution mode"""
        settings = context.scene.mapgeo_settings
        
        # Always start with file browser
        context.window_manager.fileselect_add(self)
        
        # Check if background mode will be used
        if settings.execution_mode == 'BACKGROUND':
            # Will switch to modal after file selection
            return {'RUNNING_MODAL'}
        else:
            # Standard foreground execution after file selection
            return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        """Handle modal execution for background processing"""
        settings = context.scene.mapgeo_settings
        
        # If we have an active background task, process it
        if self._background_task:
            if event.type == 'TIMER':
                # Process one step of the background task
                try:
                    progress = next(self._background_task)
                    # Update progress indicator
                    context.area.header_text_set(f"Exporting: {int(progress)}%")
                    return {'RUNNING_MODAL'}
                except StopIteration:
                    # Task complete
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                    context.area.header_text_set(None)
                    self._background_task = None
                    return {'FINISHED'}
                except Exception as e:
                    # Task failed
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                    context.area.header_text_set(None)
                    self._background_task = None
                    self.report({'ERROR'}, f"Export failed: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return {'CANCELLED'}
            return {'RUNNING_MODAL'}
        
        # File browser is still open or just closed
        if not self.filepath:
            return {'RUNNING_MODAL'}
        
        # File selected - check execution mode
        if settings.execution_mode == 'BACKGROUND':
            # Start background processing with timer
            self._timer = context.window_manager.event_timer_add(0.001, window=context.window)
            self._background_task = self._execute_background(context)
            return {'RUNNING_MODAL'}
        else:
            # Execute immediately in foreground
            return self.execute(context)
    
    def _execute_background(self, context):
        """Generator function that yields progress for background execution"""
        settings = context.scene.mapgeo_settings
        
        try:
            yield 5
            
            # Update settings
            settings.last_export_path = self.filepath
            settings.export_version = self.export_version
            
            yield 10
            
            # Get objects to export
            if self.export_selected_only:
                objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
            else:
                objects = [obj for obj in context.scene.objects if obj.type == 'MESH']
            
            # Filter out bucket grid related objects
            objects = [obj for obj in objects if not obj.get("is_bucket_grid") and not obj.get("is_bucket_grid_bounds")]
            objects = [obj for obj in objects if not any(col.get("is_bucket_grid_collection") for col in obj.users_collection)]
            
            yield 20
            
            # Find meshes from the _Meshes subcollection only
            root_name = settings.root_collection_name if hasattr(settings, 'root_collection_name') and settings.root_collection_name else "rey_map"
            
            def collect_collection_meshes(collection, output):
                for col_obj in collection.objects:
                    if col_obj.type == 'MESH':
                        output.add(col_obj)
                for child in collection.children:
                    collect_collection_meshes(child, output)
            
            meshes_col = bpy.data.collections.get(f"{root_name}_Meshes")
            if meshes_col:
                collected_meshes = set()
                collect_collection_meshes(meshes_col, collected_meshes)
                objects = [obj for obj in objects if obj in collected_meshes]
            elif bpy.data.collections.get(root_name):
                root_collection = bpy.data.collections.get(root_name)
                collected_meshes = set()
                collect_collection_meshes(root_collection, collected_meshes)
                objects = [obj for obj in objects if obj in collected_meshes]
            
            if not objects:
                self.report({'WARNING'}, "No mesh objects to export (excluding bucket grids)")
            
            yield 30
            
            # Create mapgeo data (heavy part)
            mapgeo = self.create_mapgeo(context, objects)
            
            yield 60
            
            # Handle bucket grids
            if self.bucket_grid_mode == 'ORIGINAL':
                self.collect_imported_bucket_grids(context, mapgeo)
            elif self.bucket_grid_mode == 'CUSTOM':
                self.collect_custom_bucket_grids(context, mapgeo)
            
            yield 75
            
            yield 85
            
            # Write to file
            parser = mapgeo_parser.MapgeoParser()
            parser.write(self.filepath, mapgeo)
            
            yield 95
            
            self.report({'INFO'}, f"Successfully exported to {os.path.basename(self.filepath)} "
                        f"({len(objects)} meshes, {len(mapgeo.bucket_grids)} bucket grids)")
            
            yield 100
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    
    def create_mapgeo(self, context, objects) -> mapgeo_parser.MapgeoFile:
        """Create mapgeo data structure from Blender objects"""
        
        mapgeo = mapgeo_parser.MapgeoFile()
        mapgeo.version = self.export_version
        
        # Check if we have cached VB descriptions from import (for structure preservation)
        have_vb_cache = bool(import_mapgeo._imported_vb_descriptions_cache)
        
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
                
                # Get stream layout from cached import data
                decl_count = obj.get("vertex_declaration_count", 1)
                decl_id = obj.get("vertex_declaration_id", -1)
                stream_elements_json = obj.get("vb_stream_elements", "")
                
                # Try to parse stream elements
                stream_elements = None
                if stream_elements_json and have_vb_cache and decl_count > 1:
                    try:
                        stream_elements = json.loads(stream_elements_json)
                    except (json.JSONDecodeError, TypeError):
                        stream_elements = None
                
                if stream_elements and len(stream_elements) == decl_count and decl_count > 1:
                    # Multi-stream: create separate vertex buffers per stream
                    vertex_buffers = self.create_multi_stream_vertex_buffers(mesh, obj, stream_elements)
                    first_vb_id = len(mapgeo.vertex_buffers)
                    vb_ids = []
                    for vb in vertex_buffers:
                        vb_ids.append(len(mapgeo.vertex_buffers))
                        mapgeo.vertex_buffers.append(vb)
                    
                    # Create index buffer (inherit mesh visibility for environment layering)
                    ib_visibility = obj.get("visibility_layer", obj.get("mapgeo_visibility",
                                            mapgeo_parser.EnvironmentVisibility.ALL_LAYERS))
                    index_buffer = self.create_index_buffer(mesh, visibility=ib_visibility, obj=obj)
                    index_buffer_id = len(mapgeo.index_buffers)
                    mapgeo.index_buffers.append(index_buffer)
                    
                    # Create mesh entry with multi-stream layout
                    mesh_entry = self.create_mesh_entry(mesh, obj, first_vb_id, index_buffer_id)
                    mesh_entry.vertex_buffer_ids = vb_ids
                    mesh_entry.vertex_declaration_count = decl_count
                    # vertex_declaration_id will be set later during description assignment
                    mesh_entry.vertex_declaration_id = decl_id  # Use original decl_id for now
                else:
                    # Single-stream: create one vertex buffer (original behavior)
                    vertex_buffer = self.create_vertex_buffer(mesh, obj)
                    vertex_buffer_id = len(mapgeo.vertex_buffers)
                    mapgeo.vertex_buffers.append(vertex_buffer)
                    
                    # Create index buffer (inherit mesh visibility for environment layering)
                    ib_visibility = obj.get("visibility_layer", obj.get("mapgeo_visibility",
                                            mapgeo_parser.EnvironmentVisibility.ALL_LAYERS))
                    index_buffer = self.create_index_buffer(mesh, visibility=ib_visibility, obj=obj)
                    index_buffer_id = len(mapgeo.index_buffers)
                    mapgeo.index_buffers.append(index_buffer)
                    
                    # Create mesh entry
                    mesh_entry = self.create_mesh_entry(mesh, obj, vertex_buffer_id, index_buffer_id)
                
                # Validate vertex count consistency (prevent crashes from buffer overruns)
                first_vb = mapgeo.vertex_buffers[mesh_entry.vertex_buffer_ids[0]] if mesh_entry.vertex_buffer_ids else None
                if first_vb and mesh_entry.vertex_count != first_vb.vertex_count:
                    print(f"ERROR: Vertex count mismatch for {obj.name}: mesh_entry claims {mesh_entry.vertex_count} but vertex_buffer has {first_vb.vertex_count}")
                    print(f"  Correcting mesh_entry to match vertex_buffer")
                    mesh_entry.vertex_count = first_vb.vertex_count
                
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
        
        # Restore vertex buffer descriptions from import cache or deduplicate
        if have_vb_cache:
            # Use the ORIGINAL descriptions from import - preserves exact game structure
            mapgeo.vertex_buffer_descriptions = []
            for desc_data in import_mapgeo._imported_vb_descriptions_cache:
                elements = []
                offset = 0
                for elem_data in desc_data["elements"]:
                    elem = mapgeo_parser.VertexElement(
                        name=elem_data["name"],
                        format=elem_data["format"],
                        offset=offset
                    )
                    elements.append(elem)
                    # Calculate offset for next element
                    fmt_sizes = {0: 4, 1: 8, 2: 12, 3: 16, 4: 4, 5: 4, 6: 4, 7: 4, 8: 6, 9: 8, 10: 2, 11: 3, 12: 4}
                    offset += fmt_sizes.get(elem_data["format"], 4)
                desc = mapgeo_parser.VertexBufferDescription(
                    usage=desc_data["usage"],
                    elements=elements
                )
                mapgeo.vertex_buffer_descriptions.append(desc)
            print(f"Restored {len(mapgeo.vertex_buffer_descriptions)} VB descriptions from import cache")
            
            # For multi-stream meshes, vertex_declaration_id was already set to the original value.
            # For single-stream meshes, we need to find the right description.
            # Build description lookup by element names
            desc_lookup = {}
            for desc_idx, desc in enumerate(mapgeo.vertex_buffer_descriptions):
                key = tuple(e.name for e in desc.elements)
                desc_lookup[key] = desc_idx
            
            for mesh_entry in mapgeo.meshes:
                if mesh_entry.vertex_declaration_count > 1:
                    # Multi-stream: vertex_declaration_id already set from import cache
                    # Verify it's valid
                    if mesh_entry.vertex_declaration_id + mesh_entry.vertex_declaration_count <= len(mapgeo.vertex_buffer_descriptions):
                        pass  # Valid
                    else:
                        print(f"WARNING: Invalid multi-stream decl_id {mesh_entry.vertex_declaration_id} + count {mesh_entry.vertex_declaration_count}")
                else:
                    # Single-stream: find matching description
                    vb_id = mesh_entry.vertex_buffer_ids[0] if mesh_entry.vertex_buffer_ids else 0
                    if vb_id < len(mapgeo.vertex_buffers):
                        vb = mapgeo.vertex_buffers[vb_id]
                        if vb.description:
                            key = tuple(e.name for e in vb.description.elements)
                            if key in desc_lookup:
                                mesh_entry.vertex_declaration_id = desc_lookup[key]
                            else:
                                # Description not in cache - add it
                                new_idx = len(mapgeo.vertex_buffer_descriptions)
                                mapgeo.vertex_buffer_descriptions.append(vb.description)
                                desc_lookup[key] = new_idx
                                mesh_entry.vertex_declaration_id = new_idx
                                print(f"Added new VB description {new_idx} for uncached format: {key}")
        else:
            # No cache: deduplicate descriptions (original behavior)
            unique_descs = []
            desc_key_to_idx = {}
            vb_to_desc_idx = {}
            
            for vb_idx, vb in enumerate(mapgeo.vertex_buffers):
                if vb.description is None:
                    continue
                desc_key = (vb.description.usage, tuple(
                    (e.name, e.format) for e in vb.description.elements
                ))
                if desc_key not in desc_key_to_idx:
                    desc_key_to_idx[desc_key] = len(unique_descs)
                    unique_descs.append(vb.description)
                vb_to_desc_idx[vb_idx] = desc_key_to_idx[desc_key]
            
            mapgeo.vertex_buffer_descriptions = unique_descs
            print(f"Deduplicated VB descriptions: {len(mapgeo.vertex_buffers)} -> {len(unique_descs)}")
            
            for mesh_entry in mapgeo.meshes:
                vb_id = mesh_entry.vertex_buffer_ids[0] if mesh_entry.vertex_buffer_ids else 0
                if vb_id in vb_to_desc_idx:
                    mesh_entry.vertex_declaration_id = vb_to_desc_idx[vb_id]
        
        return mapgeo
    
    def create_multi_stream_vertex_buffers(self, mesh, obj, stream_elements) -> list:
        """Create multiple vertex buffers for multi-stream vertex layouts.
        
        Args:
            mesh: Blender mesh data
            obj: Blender object (for custom properties)
            stream_elements: List of lists, e.g. [[0,2], [7]] where numbers are VertexElementName values.
                             Each inner list defines which elements go into that stream's vertex buffer.
        
        Returns:
            List of VertexBuffer objects, one per stream.
        """
        # Get element format from cached descriptions
        decl_id = obj.get("vertex_declaration_id", 0)
        
        # Build per-element format lookup from cached descriptions
        elem_format_by_stream = []
        for stream_idx, elem_names in enumerate(stream_elements):
            desc_idx = decl_id + stream_idx
            elem_formats = {}
            if desc_idx < len(import_mapgeo._imported_vb_descriptions_cache):
                cached_desc = import_mapgeo._imported_vb_descriptions_cache[desc_idx]
                for ed in cached_desc["elements"]:
                    elem_formats[ed["name"]] = ed["format"]
            else:
                # Fallback: use default formats
                default_formats = {
                    0: 2,   # POSITION -> XYZ_FLOAT32
                    2: 2,   # NORMAL -> XYZ_FLOAT32
                    4: 4,   # PRIMARY_COLOR -> BGRA_PACKED8888
                    7: 1,   # TEXCOORD0 -> XY_FLOAT32
                    12: 2,  # TEXCOORD5 -> XYZ_FLOAT32
                    14: 1,  # TEXCOORD7 -> XY_FLOAT32
                }
                for en in elem_names:
                    elem_formats[en] = default_formats.get(en, 2)
            elem_format_by_stream.append(elem_formats)
        
        # Prepare shared data that elements may need
        vertex_count = len(mesh.vertices)
        uv_layer = mesh.uv_layers.active if mesh.uv_layers else None
        lightmap_uv_layer = mesh.uv_layers.get("LightmapUV")
        tc5_attr = mesh.attributes.get("TEXCOORD5")
        raw_normals_attr = mesh.attributes.get("raw_normals")
        
        color_attr = None
        if self.export_vertex_colors:
            if mesh.color_attributes and len(mesh.color_attributes) > 0:
                color_attr = mesh.color_attributes.active_color
            elif mesh.vertex_colors:
                color_attr = mesh.vertex_colors.active
        
        # Build vert_to_loops map (for UV and color lookups)
        vert_to_loops = {}
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                loop = mesh.loops[loop_idx]
                vert_idx = loop.vertex_index
                if vert_idx not in vert_to_loops:
                    vert_to_loops[vert_idx] = []
                vert_to_loops[vert_idx].append(loop_idx)
        
        # Create one VB per stream
        result_vbs = []
        for stream_idx, elem_names in enumerate(stream_elements):
            elem_formats = elem_format_by_stream[stream_idx]
            
            # Build elements list for this stream's description
            elements = []
            offset = 0
            for en in elem_names:
                fmt = elem_formats.get(en, 2)  # default XYZ_FLOAT32
                elem = mapgeo_parser.VertexElement(name=en, format=fmt, offset=offset)
                elements.append(elem)
                offset += mapgeo_parser.VertexElement.get_format_size(fmt)
            
            desc = mapgeo_parser.VertexBufferDescription(
                usage=0,  # Static
                elements=elements
            )
            vertex_size = desc.get_vertex_size()
            vertex_data = bytearray(vertex_size * vertex_count)
            
            # Write vertex data for this stream
            for vert_idx, vert in enumerate(mesh.vertices):
                buf_offset = vert_idx * vertex_size
                current_offset = 0
                
                for en in elem_names:
                    fmt = elem_formats.get(en, 2)
                    elem_size = mapgeo_parser.VertexElement.get_format_size(fmt)
                    write_pos = buf_offset + current_offset
                    
                    if en == 0:  # POSITION
                        local_pos = vert.co
                        struct.pack_into('<fff', vertex_data, write_pos,
                                       local_pos.x, local_pos.z, local_pos.y)
                    
                    elif en == 2:  # NORMAL
                        if raw_normals_attr and vert_idx < len(raw_normals_attr.data):
                            rn = raw_normals_attr.data[vert_idx].vector
                            struct.pack_into('<fff', vertex_data, write_pos,
                                           rn.x, rn.z, rn.y)
                        else:
                            n = vert.normal
                            struct.pack_into('<fff', vertex_data, write_pos,
                                           n.x, n.z, n.y)
                    
                    elif en == 4:  # PRIMARY_COLOR
                        if color_attr and vert_idx in vert_to_loops and vert_to_loops[vert_idx]:
                            loop_idx = vert_to_loops[vert_idx][0]
                            color = color_attr.data[loop_idx].color
                            r = int(color[0] * 255)
                            g = int(color[1] * 255)
                            b = int(color[2] * 255)
                            a = int(color[3] * 255) if len(color) > 3 else 255
                            struct.pack_into('<BBBB', vertex_data, write_pos, b, g, r, a)
                        else:
                            struct.pack_into('<BBBB', vertex_data, write_pos, 255, 255, 255, 255)
                    
                    elif en == 7:  # TEXCOORD0
                        if uv_layer and vert_idx in vert_to_loops and vert_to_loops[vert_idx]:
                            loop_idx = vert_to_loops[vert_idx][0]
                            uv = uv_layer.data[loop_idx].uv
                            struct.pack_into('<ff', vertex_data, write_pos, uv[0], 1.0 - uv[1])
                        else:
                            struct.pack_into('<ff', vertex_data, write_pos, 0.0, 0.0)
                    
                    elif en == 12:  # TEXCOORD5
                        if tc5_attr and vert_idx < len(tc5_attr.data):
                            vec = tc5_attr.data[vert_idx].vector
                            struct.pack_into('<fff', vertex_data, write_pos,
                                           vec[0], vec[2], vec[1])
                        else:
                            struct.pack_into('<fff', vertex_data, write_pos, 0.0, 0.0, 0.0)
                    
                    elif en == 14:  # TEXCOORD7
                        if lightmap_uv_layer and vert_idx in vert_to_loops and vert_to_loops[vert_idx]:
                            loop_idx = vert_to_loops[vert_idx][0]
                            uv = lightmap_uv_layer.data[loop_idx].uv
                            struct.pack_into('<ff', vertex_data, write_pos, uv[0], 1.0 - uv[1])
                        else:
                            struct.pack_into('<ff', vertex_data, write_pos, 0.0, 0.0)
                    
                    current_offset += elem_size
            
            vb = mapgeo_parser.VertexBuffer(
                description=desc,
                data=bytes(vertex_data),
                vertex_count=vertex_count
            )
            result_vbs.append(vb)
        
        return result_vbs
    
    def create_vertex_buffer(self, mesh, obj) -> mapgeo_parser.VertexBuffer:
        """Create vertex buffer from mesh"""
        
        # Define vertex elements
        elements = []
        offset = 0
        
        # Check if mesh has TEXCOORD5 attribute (bush animation anchor data)
        has_texcoord5 = "TEXCOORD5" in mesh.attributes
        
        # Check if mesh has LightmapUV layer (TEXCOORD7)
        has_lightmap_uv = "LightmapUV" in mesh.uv_layers
        
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
        
        # TEXCOORD7 (lightmap UV - XY_FLOAT32)
        if has_lightmap_uv:
            elements.append(mapgeo_parser.VertexElement(
                mapgeo_parser.VertexElementName.TEXCOORD7,
                mapgeo_parser.VertexElementFormat.XY_FLOAT32,
                offset
            ))
            offset += 8
        
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
        
        # Get LightmapUV layer (TEXCOORD7)
        lightmap_uv_layer = mesh.uv_layers.get("LightmapUV") if has_lightmap_uv else None
        
        # Get TEXCOORD5 attribute
        tc5_attr = mesh.attributes.get("TEXCOORD5") if has_texcoord5 else None
        
        # Get raw_normals attribute (render region meshes store non-unit normals)
        raw_normals_attr = mesh.attributes.get("raw_normals")
        
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
                if raw_normals_attr and vert_idx < len(raw_normals_attr.data):
                    # Use preserved raw normals (render region meshes have non-unit normals)
                    rn = raw_normals_attr.data[vert_idx].vector
                    # raw_normals are stored in Blender coords (X, Z_mapgeo, Y_mapgeo)
                    # Swap back: Blender(X, Y, Z) -> Mapgeo(X, Z, Y)
                    struct.pack_into('<fff', vertex_data, offset + current_offset,
                                   rn.x, rn.z, rn.y)
                else:
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
            
            # TEXCOORD7 - lightmap UV
            if lightmap_uv_layer:
                # Get first loop for this vertex
                if vert_idx in vert_to_loops and len(vert_to_loops[vert_idx]) > 0:
                    loop_idx = vert_to_loops[vert_idx][0]
                    uv = lightmap_uv_layer.data[loop_idx].uv
                    # Flip V coordinate
                    struct.pack_into('<ff', vertex_data, offset + current_offset,
                                   uv[0], 1.0 - uv[1])
                else:
                    struct.pack_into('<ff', vertex_data, offset + current_offset, 0.0, 0.0)
                current_offset += 8
        
        return mapgeo_parser.VertexBuffer(
            description=description,
            data=bytes(vertex_data),
            vertex_count=vertex_count
        )
    
    def create_index_buffer(self, mesh, visibility=None, obj=None) -> mapgeo_parser.IndexBuffer:
        """Create index buffer from mesh.
        
        If the mesh has a 'mapgeo_prim_idx' face attribute (stored during import for
        multi-primitive meshes), faces are written grouped by primitive index to
        preserve original primitive boundaries. Otherwise faces are written in
        polygon order.
        """
        if visibility is None:
            visibility = mapgeo_parser.EnvironmentVisibility.ALL_LAYERS
        
        index_count = len(mesh.polygons) * 3
        index_data = bytearray(index_count * 2)  # U16 format
        
        # Check for stored primitive index attribute
        prim_attr = mesh.attributes.get("mapgeo_prim_idx")
        has_prim_order = prim_attr is not None and obj is not None and "mapgeo_prim_materials" in obj
        
        if has_prim_order:
            # Group faces by their original primitive index and write in prim order
            prim_faces = {}  # prim_idx -> list of poly_idx
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly_idx < len(prim_attr.data):
                    pi = prim_attr.data[poly_idx].value
                else:
                    pi = 0
                prim_faces.setdefault(pi, []).append(poly_idx)
            
            idx = 0
            for pi in sorted(prim_faces.keys()):
                for poly_idx in prim_faces[pi]:
                    poly = mesh.polygons[poly_idx]
                    if len(poly.vertices) != 3:
                        continue
                    v0, v1, v2 = poly.vertices
                    struct.pack_into('<H', index_data, idx * 2, v0)
                    struct.pack_into('<H', index_data, (idx + 1) * 2, v2)
                    struct.pack_into('<H', index_data, (idx + 2) * 2, v1)
                    idx += 3
        else:
            idx = 0
            for poly in mesh.polygons:
                if len(poly.vertices) != 3:
                    print(f"Warning: Non-triangle face found (vertices: {len(poly.vertices)})")
                    continue
                
                # Reverse winding order: Blender faces were reversed on import
                v0, v1, v2 = poly.vertices
                struct.pack_into('<H', index_data, idx * 2, v0)
                struct.pack_into('<H', index_data, (idx + 1) * 2, v2)
                struct.pack_into('<H', index_data, (idx + 2) * 2, v1)
                idx += 3
        
        return mapgeo_parser.IndexBuffer(
            data=bytes(index_data),
            format=0,  # U16
            index_count=idx,
            visibility=visibility
        )
    
    def create_mesh_entry(self, mesh, obj, vertex_buffer_id, index_buffer_id) -> mapgeo_parser.Mesh:
        """Create mesh entry"""
        
        mesh_entry = mapgeo_parser.Mesh()
        
        # Get quality and visibility from custom properties (set during import)
        # Try both old property names (mapgeo_*) and new names (*) for compatibility
        raw_quality = obj.get("quality", obj.get("mapgeo_quality", int(self.default_quality)))
        # Quality is a uint8 bitmask. 31 = standard 5 quality levels, 255 = all bits (render regions).
        mesh_entry.quality = max(0, min(255, int(raw_quality)))
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
        
        # Compute the League-space transform matrix first (needed for world-space bounding volumes).
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
        
        if mesh.vertices:
            # Convert local vertex positions to League coords: Blender(X, Y, Z) -> Mapgeo(X, Z, Y)
            local_positions = []
            for v in mesh.vertices:
                local_positions.append((v.co.x, v.co.z, v.co.y))
            
            min_x = min(p[0] for p in local_positions)
            min_y = min(p[1] for p in local_positions)
            min_z = min(p[2] for p in local_positions)
            max_x = max(p[0] for p in local_positions)
            max_y = max(p[1] for p in local_positions)
            max_z = max(p[2] for p in local_positions)
            
            # Bounding box in local space (same coordinate space as vertex data).
            # The game applies the transform_matrix at runtime to get world bounds.
            mesh_entry.bounding_box = mapgeo_parser.BoundingBox(
                min=(min_x, min_y, min_z),
                max=(max_x, max_y, max_z)
            )
            
            # Bounding sphere from local AABB
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            center_z = (min_z + max_z) / 2
            center = Vector((center_x, center_y, center_z))
            
            corners = [
                Vector((min_x, min_y, min_z)), Vector((max_x, min_y, min_z)),
                Vector((min_x, max_y, min_z)), Vector((max_x, max_y, min_z)),
                Vector((min_x, min_y, max_z)), Vector((max_x, min_y, max_z)),
                Vector((min_x, max_y, max_z)), Vector((max_x, max_y, max_z)),
            ]
            
            radius = max(
                (c - center).length 
                for c in corners
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
        # Check for stored multi-primitive data from import
        prim_attr = mesh.attributes.get("mapgeo_prim_idx")
        has_stored_prims = prim_attr is not None and "mapgeo_prim_materials" in obj
        
        if has_stored_prims:
            # Use stored primitive boundaries (preserves same-material multi-prim meshes)
            prim_mat_names = json.loads(obj["mapgeo_prim_materials"])
            
            # Group faces by stored primitive index
            prim_faces = {}  # prim_idx -> list of poly_idx
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly_idx < len(prim_attr.data):
                    pi = prim_attr.data[poly_idx].value
                else:
                    pi = 0
                prim_faces.setdefault(pi, []).append(poly_idx)
            
            current_index = 0
            for pi in sorted(prim_faces.keys()):
                poly_indices = prim_faces[pi]
                index_count = len(poly_indices) * 3
                
                # Use stored material name if available, fall back to face material
                if pi < len(prim_mat_names):
                    mat_name = prim_mat_names[pi]
                else:
                    # Fallback: use material from first face in this group
                    first_poly = mesh.polygons[poly_indices[0]]
                    mat_idx = first_poly.material_index
                    mat_name = mesh.materials[mat_idx].name if mat_idx < len(mesh.materials) and mesh.materials[mat_idx] else "Default"
                
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
        else:
            # Fallback: group by material name (original behavior)
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
        """Collect bucket grids from scene data (stored on BucketGrid collections)"""
        
        # Find all bucket grid collections in the scene
        bucket_grid_collections = []
        scene_col_names = {c.name for c in self._get_all_collections(context)}
        for col in bpy.data.collections:
            if col.get("is_bucket_grid_collection") and col.get("bucket_data_json"):
                # Skip custom bucket grid collections — those are handled by collect_custom_bucket_grids
                if col.get("is_custom_bucket_grid"):
                    continue
                # Verify collection is actually linked to the scene (not orphaned)
                if col.name in scene_col_names:
                    bucket_grid_collections.append(col)
        
        if not bucket_grid_collections:
            print("No bucket grid collections found in scene")
            return
        
        total_grids = 0
        seen_hashes = set()  # Track non-zero hashes to prevent duplicates
        skipped = 0
        for col in bucket_grid_collections:
            try:
                bucket_data_json = col.get("bucket_data_json", "[]")
                bucket_grids_data = json.loads(bucket_data_json)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"  ERROR parsing bucket_data_json from collection '{col.name}': {e}")
                continue
            
            print(f"Found {len(bucket_grids_data)} bucket grid(s) in collection '{col.name}'")
            
            # Reconstruct BucketGrid objects from stored JSON data
            for grid_data in bucket_grids_data:
                grid = self._reconstruct_grid_from_json(grid_data)
                if grid is not None:
                    # Deduplicate by non-zero path_hash
                    if grid.path_hash != 0:
                        if grid.path_hash in seen_hashes:
                            print(f"  Skipping duplicate bucket grid (hash: {hex(grid.path_hash)})")
                            skipped += 1
                            continue
                        seen_hashes.add(grid.path_hash)
                    mapgeo.bucket_grids.append(grid)
                    total_grids += 1
                    print(f"  Exported bucket grid (hash: {hex(grid.path_hash)})")
        
        if skipped:
            print(f"WARNING: Skipped {skipped} duplicate bucket grid(s)")
        print(f"Total bucket grids exported from scene: {total_grids}")
    
    def _get_all_collections(self, context):
        """Get all collections linked to the scene (recursively)"""
        result = []
        def recurse(col):
            result.append(col)
            for child in col.children:
                recurse(child)
        recurse(context.scene.collection)
        return result
    
    def collect_custom_bucket_grids(self, context, mapgeo: mapgeo_parser.MapgeoFile):
        """Collect bucket grids for export.
        
        Strategy:
        1. Load custom grids from custom bucket grid collections
        2. If custom grids exist, export them directly (they contain YOUR geometry)
        3. If no custom grids, fall back to imported grids from reference collection
        
        Custom grids are created by the "Create Custom Bucket Grid" operator
        which already sets the correct hash field placement:
        - render_region hash → path_hash field (v18=0)
        - baron/visibility hash → v18 field (path_hash=0)
        """
        scene_col_names = {c.name for c in self._get_all_collections(context)}
        
        # ── Step 1: Load custom grids ──
        custom_grids = []  # List of (identifier, BucketGrid)
        
        for col in bpy.data.collections:
            if (col.get("is_custom_bucket_grid") 
                and col.get("bucket_data_json")
                and col.name in scene_col_names):
                try:
                    bucket_data_json = col.get("bucket_data_json", "[]")
                    grids_data = json.loads(bucket_data_json)
                    col_hash_type = col.get("hash_type", "")
                    
                    for grid_data in grids_data:
                        grid = self._reconstruct_grid_from_json(grid_data)
                        if grid is None:
                            continue

                        # Normalize hash field placement based on collection type.
                        # This protects export correctness even if legacy/stale custom
                        # collections have path_hash/v18 incorrectly placed.
                        # Correct format: render_region → v18 (path_hash=0), baron → path_hash (v18=0)
                        v18_uint = struct.unpack('<I', struct.pack('<f', grid.unknown_v18_float))[0]
                        if col_hash_type == 'render_region':
                            if grid.path_hash != 0 and v18_uint == 0:
                                grid.unknown_v18_float = struct.unpack('<f', struct.pack('<I', grid.path_hash))[0]
                                grid.path_hash = 0
                                v18_uint = struct.unpack('<I', struct.pack('<f', grid.unknown_v18_float))[0]
                        elif col_hash_type == 'baron':
                            if grid.path_hash == 0 and v18_uint != 0:
                                grid.path_hash = v18_uint
                                grid.unknown_v18_float = 0.0
                                v18_uint = 0
                        elif col_hash_type == 'master':
                            grid.path_hash = 0
                            grid.unknown_v18_float = 0.0
                            v18_uint = 0
                        
                        # Determine identifier: path_hash if non-zero, else v18
                        cid = grid.path_hash
                        if cid == 0:
                            cid_v18 = v18_uint
                            if cid_v18 != 0:
                                cid = cid_v18
                        
                        custom_grids.append((cid, grid))

                        print(f"  Custom grid: hash={cid:08X} "
                              f"(path_hash={grid.path_hash:08X} v18={v18_uint:08X}) "
                              f"flags={grid.flags} bps={grid.buckets_per_side} "
                              f"verts={len(grid.vertices)} idx={len(grid.indices)}")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"  ERROR parsing custom bucket_data_json: {e}")
        
        if custom_grids:
            # Ensure a valid master grid exists.
            # League expects one grid with path_hash=0 and v18=0 that has
            # flags bit 0 set and face_visibility_flags for every face.
            # Pick the zero-zero grid with the LARGEST bounds area as master,
            # since multiple visibility_layer groups can produce zero-zero grids.
            master_grid = None
            zero_zero_ids = set()  # Track all zero-zero grid ids to skip extras
            master_candidates = []
            for cid, cgrid in custom_grids:
                v18_uint = struct.unpack('<I', struct.pack('<f', cgrid.unknown_v18_float))[0]
                if cgrid.path_hash == 0 and v18_uint == 0:
                    bounds_area = (cgrid.max_x - cgrid.min_x) * (cgrid.max_z - cgrid.min_z)
                    master_candidates.append((bounds_area, id(cgrid), cgrid))
                    zero_zero_ids.add(id(cgrid))
            
            if master_candidates:
                # Sort by bounds area descending, pick largest
                master_candidates.sort(key=lambda x: x[0], reverse=True)
                _, _, master_grid = master_candidates[0]
                zero_zero_ids.discard(id(master_grid))  # Don't skip the chosen master
                if len(master_candidates) > 1:
                    print(f"  Found {len(master_candidates)} zero-zero grids, "
                          f"picked largest (area={master_candidates[0][0]:.0f}) as master")

            if master_grid is None and custom_grids:
                # No explicit zero-id grid: synthesize master from largest custom grid
                # so the engine always has a valid master visibility grid.
                _, source_grid = max(custom_grids, key=lambda item: len(item[1].indices))
                master_grid = mapgeo_parser.BucketGrid()
                master_grid.path_hash = 0
                master_grid.unknown_v18_float = 0.0
                master_grid.min_x = source_grid.min_x
                master_grid.min_z = source_grid.min_z
                master_grid.max_x = source_grid.max_x
                master_grid.max_z = source_grid.max_z
                master_grid.bucket_size_x = source_grid.bucket_size_x
                master_grid.bucket_size_z = source_grid.bucket_size_z
                master_grid.buckets_per_side = source_grid.buckets_per_side
                master_grid.is_disabled = False
                master_grid.flags = 1
                master_grid.max_stickout_x = source_grid.max_stickout_x
                master_grid.max_stickout_z = source_grid.max_stickout_z
                master_grid.vertices = list(source_grid.vertices)
                master_grid.indices = list(source_grid.indices)
                master_grid.buckets = [list(row) for row in source_grid.buckets]
                master_face_count = len(master_grid.indices) // 3
                master_grid.face_visibility_flags = [255] * master_face_count
                print(f"  SYNTHESIZED master grid from largest custom grid: "
                      f"bps={master_grid.buckets_per_side} "
                      f"verts={len(master_grid.vertices)} idx={len(master_grid.indices)} "
                      f"fvf={len(master_grid.face_visibility_flags)}")
            elif master_grid is not None:
                # Enforce required master-grid metadata
                master_grid.flags |= 1
                master_face_count = len(master_grid.indices) // 3
                if len(master_grid.face_visibility_flags) != master_face_count:
                    master_grid.face_visibility_flags = [255] * master_face_count
                print(f"  ENFORCED master grid metadata: "
                      f"bps={master_grid.buckets_per_side} "
                      f"verts={len(master_grid.vertices)} idx={len(master_grid.indices)} "
                      f"fvf={len(master_grid.face_visibility_flags)}")

            # Export custom grids directly — they contain your scene's geometry.
            # Keep master grid first for Riot-style ordering.
            exported_count = 0
            exported_ids = set()   # Python object identity (prevent same object twice)
            seen_cids = set()     # Hash-based dedup (prevent duplicate identifiers)
            skipped_dupes = 0
            if master_grid is not None:
                mapgeo.bucket_grids.append(master_grid)
                exported_ids.add(id(master_grid))
                exported_count += 1

            for cid, cgrid in custom_grids:
                if id(cgrid) in exported_ids:
                    continue
                # Skip duplicate zero-zero grids (only master should have path_hash=0/v18=0)
                if id(cgrid) in zero_zero_ids:
                    print(f"  Skipping non-master zero-zero grid "
                          f"(bounds={cgrid.min_x:.0f},{cgrid.min_z:.0f}-{cgrid.max_x:.0f},{cgrid.max_z:.0f})")
                    skipped_dupes += 1
                    continue
                # Deduplicate by identifier (non-zero hashes only)
                if cid != 0 and cid in seen_cids:
                    v18_uint = struct.unpack('<I', struct.pack('<f', cgrid.unknown_v18_float))[0]
                    print(f"  Skipping duplicate bucket grid (id={cid:#010x}, "
                          f"path_hash={cgrid.path_hash:#010x}, v18={v18_uint:#010x})")
                    skipped_dupes += 1
                    continue
                if cid != 0:
                    seen_cids.add(cid)
                mapgeo.bucket_grids.append(cgrid)
                exported_count += 1
            
            if skipped_dupes:
                print(f"WARNING: Skipped {skipped_dupes} duplicate bucket grid(s)")
            print(f"Total bucket grids exported: {exported_count} (custom)")
            return
        
        # ── Step 2: No custom grids — fall back to imported grids ──
        imported_grids = []
        
        for col in bpy.data.collections:
            if (col.get("is_bucket_grid_collection") 
                and not col.get("is_custom_bucket_grid")
                and col.get("bucket_data_json")
                and col.name in scene_col_names):
                try:
                    bucket_data_json = col.get("bucket_data_json", "[]")
                    grids_data = json.loads(bucket_data_json)
                    print(f"No custom grids — using {len(grids_data)} imported grid(s) from '{col.name}' as fallback")
                    
                    for grid_data in grids_data:
                        grid = self._reconstruct_grid_from_json(grid_data)
                        if grid is not None:
                            imported_grids.append(grid)
                            
                            v18_bytes = struct.pack('<f', grid.unknown_v18_float)
                            v18_uint = struct.unpack('<I', v18_bytes)[0]
                            print(f"  Imported grid: hash={grid.path_hash:08X} v18={v18_uint:08X} "
                                  f"flags={grid.flags} bps={grid.buckets_per_side} "
                                  f"verts={len(grid.vertices)}")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"  ERROR parsing imported bucket_data_json: {e}")
        
        if imported_grids:
            seen_hashes = set()
            deduped_count = 0
            for grid in imported_grids:
                if grid.path_hash != 0:
                    if grid.path_hash in seen_hashes:
                        print(f"  Skipping duplicate imported grid (hash: {hex(grid.path_hash)})")
                        continue
                    seen_hashes.add(grid.path_hash)
                mapgeo.bucket_grids.append(grid)
                deduped_count += 1
            print(f"Total bucket grids exported: {deduped_count} (imported fallback)")
        else:
            print("WARNING: No bucket grids found (no custom or imported grids)")
    
    def _reconstruct_grid_from_json(self, grid_data):
        """Reconstruct a BucketGrid object from stored JSON data."""
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
            
            # unknown_v18_float is stored as hex string, convert back to float
            unknown_v18_str = grid_data.get("unknown_v18_float", "00000000")
            if isinstance(unknown_v18_str, str):
                uint_value = int(unknown_v18_str, 16)
                grid.unknown_v18_float = struct.unpack('<f', struct.pack('<I', uint_value))[0]
            else:
                grid.unknown_v18_float = float(unknown_v18_str)
            grid.max_stickout_x = grid_data.get("max_stickout_x", 0.0)
            grid.max_stickout_z = grid_data.get("max_stickout_z", 0.0)
            
            # Restore vertices and indices
            grid.vertices = [tuple(v) for v in grid_data.get("vertices", [])]
            grid.indices = grid_data.get("indices", [])
            grid.face_visibility_flags = grid_data.get("face_visibility_flags", [])
            
            # Restore bucket structure
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
            
            return grid
        except Exception as e:
            print(f"  ERROR reconstructing grid: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def bucket_grid_from_object(self, obj):
        """Convert a custom bucket grid object back to BucketGrid data structure"""
        
        grid = mapgeo_parser.BucketGrid()
        
        # Retrieve metadata
        grid.min_x = obj.get("bounds_min_x", 0.0)
        grid.min_z = obj.get("bounds_min_z", 0.0)
        grid.max_x = obj.get("bounds_max_x", 0.0)
        grid.max_z = obj.get("bounds_max_z", 0.0)
        grid.bucket_size_x = obj.get("bucket_size_x", 512.0)
        grid.bucket_size_z = obj.get("bucket_size_z", 512.0)
        grid.buckets_per_side = int(obj.get("buckets_per_side", 1))
        grid.path_hash = int(obj.get("path_hash", "00000000"), 16) if isinstance(obj.get("path_hash"), str) else int(obj.get("path_hash", 0))
        
        # unknown_v18_float is stored as hex string, convert back to float
        unknown_v18_str = obj.get("unknown_v18_float", "00000000")
        if isinstance(unknown_v18_str, str):
            uint_value = int(unknown_v18_str, 16)
            grid.unknown_v18_float = struct.unpack('<f', struct.pack('<I', uint_value))[0]
        else:
            grid.unknown_v18_float = float(unknown_v18_str)
        grid.is_disabled = obj.get("is_disabled", False)
        grid.flags = int(obj.get("flags", 0))
        grid.max_stickout_x = obj.get("stickout_x", 0.0)
        grid.max_stickout_z = obj.get("stickout_z", 0.0)

        if grid.path_hash == 0:
            name_match = re.match(r"BucketGrid_([0-9A-Fa-f]{8})", obj.name)
            if name_match:
                try:
                    grid.path_hash = int(name_match.group(1), 16)
                except ValueError:
                    pass
        
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
        max_vertex_idx = 0
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                v0, v1, v2 = poly.vertices[0], poly.vertices[1], poly.vertices[2]
                for vert_idx in (v0, v1, v2):
                    max_vertex_idx = max(max_vertex_idx, vert_idx)
                    if vert_idx > 65535:
                        print(f"WARNING: Vertex index {vert_idx} in {obj.name} exceeds ushort max (65535)")
                        print(f"  → This bucket grid has {len(mesh.vertices)} total vertices (limit: 65535)")
                        print(f"  → Consider reducing bucket size or splitting mesh by visibility_layer")
                # Reverse winding to account for Y/Z swap handedness
                grid.indices.extend([
                    min(v0, 65535),
                    min(v2, 65535),
                    min(v1, 65535),
                ])
            else:
                print(f"WARNING: Non-triangle face in bucket grid {obj.name}")
        
        if max_vertex_idx > 65535:
            print(f"  → Max vertex index was {max_vertex_idx}, clamped indices to 65535")
            print(f"  → Exported grid may have visual/structural issues in-game")
        
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
