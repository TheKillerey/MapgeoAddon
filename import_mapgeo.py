"""
Import Operator for Mapgeo Files
Imports .mapgeo files into Blender as mesh objects
"""

import bpy
import bmesh
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Matrix
import struct
import os
import json

from . import mapgeo_parser
from . import utils
from . import material_loader as mat_loader
from . import baron_hash_parser

# Module-level cache for imported bucket grids (persists in Blender session)
_imported_bucket_grids_cache = {}

# Module-level cache for imported sampler defs (persists in Blender session)
_imported_sampler_defs_cache = []


class IMPORT_SCENE_OT_mapgeo(bpy.types.Operator, ImportHelper):
    """Import League of Legends Mapgeo file"""
    bl_idname = "import_scene.mapgeo"
    bl_label = "Import Mapgeo"
    bl_options = {'REGISTER', 'UNDO'}
    
    # File browser filter
    filename_ext = ".mapgeo"
    filter_glob: StringProperty(
        default="*.mapgeo",
        options={'HIDDEN'},
    )
    
    # Import options
    import_materials: BoolProperty(
        name="Import Materials",
        description="Create materials from mapgeo data",
        default=True,
    )
    
    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        description="Import vertex color data",
        default=True,
    )
    
    import_normals: BoolProperty(
        name="Import Normals",
        description="Import custom vertex normals",
        default=True,
    )
    
    import_lightmaps: BoolProperty(
        name="Import Lightmaps",
        description="Load baked lightmap textures and multiply with diffuse for Riot-accurate lighting",
        default=True,
    )
    
    import_bucket_grid: BoolProperty(
        name="Import Bucket Grid",
        description="Import bucket grid scene graph data for spatial partitioning visualization",
        default=True,
    )
    
    merge_by_layer: BoolProperty(
        name="Group by Layer",
        description="Group meshes by visibility layer",
        default=False,
    )
    
    scale_factor: bpy.props.FloatProperty(
        name="Scale",
        description="Scale factor for import",
        default=1.0,
        min=0.001,
        max=1000.0,
    )
    
    def execute(self, context):
        """Execute the import"""
        try:
            # Update settings
            settings = context.scene.mapgeo_settings
            settings.last_import_path = self.filepath
            
            # Parse the mapgeo file
            parser = mapgeo_parser.MapgeoParser()
            mapgeo = parser.read(self.filepath)
            
            # Cache sampler defs for export round-trip
            global _imported_sampler_defs_cache
            _imported_sampler_defs_cache = [
                {"index": sd.index, "name": sd.name}
                for sd in mapgeo.sampler_defs
            ]
            if _imported_sampler_defs_cache:
                print(f"Cached {len(_imported_sampler_defs_cache)} sampler defs for export")
            
            # Import into Blender
            self.import_mapgeo(context, mapgeo)
            
            # Update visibility based on current dragon/baron layer filters
            try:
                import sys
                addon_module = sys.modules.get(__package__)
                if addon_module and hasattr(addon_module, 'update_environment_visibility'):
                    settings = context.scene.mapgeo_settings
                    addon_module.update_environment_visibility(settings, context)
                else:
                    print("Warning: update_environment_visibility not found in addon module")
            except Exception as e:
                print(f"Warning: Could not update visibility: {e}")
            
            # Set viewport clipping for large maps
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.clip_start = 10.01
                            space.clip_end = 1e+07
            
            self.report({'INFO'}, f"Successfully imported {os.path.basename(self.filepath)}")
            return {'FINISHED'}
        
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def import_mapgeo(self, context, mapgeo: mapgeo_parser.MapgeoFile):
        """Import mapgeo data into Blender"""
        
        # Create a collection for this mapgeo
        collection_name = os.path.splitext(os.path.basename(self.filepath))[0]
        collection = bpy.data.collections.new(collection_name)
        context.scene.collection.children.link(collection)
        
        # Create a "Meshes" sub-collection to hold all actual mesh objects
        meshes_collection = bpy.data.collections.new(f"{collection_name}_Meshes")
        collection.children.link(meshes_collection)
        
        # Layer names for Summoner's Rift
        layer_names = {
            mapgeo_parser.EnvironmentVisibility.LAYER_1: "Base",
            mapgeo_parser.EnvironmentVisibility.LAYER_2: "Inferno",
            mapgeo_parser.EnvironmentVisibility.LAYER_3: "Mountain",
            mapgeo_parser.EnvironmentVisibility.LAYER_4: "Ocean",
            mapgeo_parser.EnvironmentVisibility.LAYER_5: "Cloud",
            mapgeo_parser.EnvironmentVisibility.LAYER_6: "Hextech",
            mapgeo_parser.EnvironmentVisibility.LAYER_7: "Chemtech",
            mapgeo_parser.EnvironmentVisibility.LAYER_8: "Void",
        }
        
        # Always create layer collections for organization
        layer_collections = {}
        for layer_flag, layer_name in layer_names.items():
            layer_col = bpy.data.collections.new(f"{collection_name}_{layer_name}")
            collection.children.link(layer_col)
            layer_collections[layer_flag] = layer_col
        
        # Create baron state collections for baron hash visibility
        # Use bit values (1, 2, 4, 8) to match the 0x8bff8cdf property in materials.bin
        baron_state_names = {
            1: "BaronBase",
            2: "BaronCup",
            4: "BaronTunnel",
            8: "BaronUpgraded"
        }
        baron_collections = {}
        for state_bit, state_name in baron_state_names.items():
            baron_col = bpy.data.collections.new(f"{collection_name}_{state_name}")
            collection.children.link(baron_col)
            baron_collections[state_bit] = baron_col
        
        print(f"Importing {len(mapgeo.meshes)} meshes from {collection_name}")
        print(f"  Vertex buffers: {len(mapgeo.vertex_buffers)}")
        print(f"  Index buffers: {len(mapgeo.index_buffers)}")
        print(f"  Vertex buffer descriptions: {len(mapgeo.vertex_buffer_descriptions)}")
        print(f"  Created layer collections for multi-layer support")
        print(f"  Created baron state collections for baron hash support")
        
        # Store materials
        materials = {}
        
        # Load materials from JSON if available
        materials_db = {}
        material_loader = None
        baron_parser = None
        map_settings = {}
        settings = context.scene.mapgeo_settings
        
        if settings.materials_json_path and os.path.exists(settings.materials_json_path):
            if settings.assets_folder and os.path.exists(settings.assets_folder):
                print(f"  Loading materials from: {os.path.basename(settings.materials_json_path)}")
                print(f"  Assets folder: {settings.assets_folder}")
                
                material_loader = mat_loader.MaterialLoader(
                    assets_folder=settings.assets_folder,
                    levels_folder=settings.levels_folder if hasattr(settings, 'levels_folder') else "",
                    map_py_path=settings.map_py_path if hasattr(settings, 'map_py_path') else "",
                    dragon_layer=settings.dragon_layer_filter if hasattr(settings, 'dragon_layer_filter') else "LAYER_1",
                )
                materials_db = material_loader.load_materials(settings.materials_json_path)
                
                # Load map settings (sun, lightmap, fog)
                map_settings = material_loader.load_map_settings(settings.materials_json_path)
                
                # Initialize baron hash parser for visibility decoding
                baron_parser = baron_hash_parser.MaterialsBinParser(settings.materials_json_path)
                print(f"  Baron hash parser initialized")
            else:
                print(f"  Warning: Assets folder not set or doesn't exist")
                print(f"  Materials will be created without textures")
        else:
            print(f"  No materials JSON specified - using simple materials")
        
        # Get lightmap color scale from map settings
        lightmap_color_scale = map_settings.get('lightmap_color_scale', 1.0) if map_settings else 1.0
        
        # Import each mesh
        imported_count = 0
        for mesh_idx, mesh_data in enumerate(mapgeo.meshes):
            try:
                # Create Blender mesh
                mesh_name = f"{collection_name}_mesh_{mesh_idx:03d}"
                bl_mesh = bpy.data.meshes.new(mesh_name)
                
                # Validate vertex buffer IDs
                if not mesh_data.vertex_buffer_ids:
                    print(f"Warning: Mesh {mesh_idx} has no vertex buffers")
                    continue
                
                # Get the first vertex buffer (main geometry)
                vb_id = mesh_data.vertex_buffer_ids[0]
                if vb_id >= len(mapgeo.vertex_buffers):
                    print(f"Warning: Invalid vertex buffer ID {vb_id}")
                    continue
                
                if mesh_data.index_buffer_id >= len(mapgeo.index_buffers):
                    print(f"Warning: Invalid index buffer ID {mesh_data.index_buffer_id}")
                    continue
                
                # Get vertex buffer and its description
                vertex_buffer = mapgeo.vertex_buffers[vb_id]
                desc_id = mesh_data.vertex_declaration_id
                if desc_id >= len(mapgeo.vertex_buffer_descriptions):
                    print(f"Warning: Invalid vertex declaration ID {desc_id}")
                    continue
                
                vb_description = mapgeo.vertex_buffer_descriptions[desc_id]
                index_buffer = mapgeo.index_buffers[mesh_data.index_buffer_id]
                
                # Parse vertex data from primary buffer
                vertices, normals, uvs, colors, texcoord5_data = self.parse_vertex_buffer(
                    vertex_buffer, vb_description, mesh_data, mesh_idx
                )
                
                # Check if UVs are in a secondary vertex buffer
                # IMPORTANT: Each vertex buffer can have its own vertex description!
                # Use vertex_declaration_id + buffer_index for each buffer
                if len(mesh_data.vertex_buffer_ids) > 1:
                    for sec_vb_idx in range(1, len(mesh_data.vertex_buffer_ids)):
                        sec_vb_id = mesh_data.vertex_buffer_ids[sec_vb_idx]
                        sec_desc_id = mesh_data.vertex_declaration_id + sec_vb_idx
                        
                        if sec_vb_id >= len(mapgeo.vertex_buffers):
                            continue
                        if sec_desc_id >= len(mapgeo.vertex_buffer_descriptions):
                            continue
                            
                        sec_vb = mapgeo.vertex_buffers[sec_vb_id]
                        sec_desc = mapgeo.vertex_buffer_descriptions[sec_desc_id]
                        
                        # Parse secondary buffer
                        _, sec_normals, sec_uvs, sec_colors, sec_tc5 = self.parse_vertex_buffer(
                            sec_vb, sec_desc, mesh_data, -1
                        )
                        
                        # Merge data from secondary buffer
                        if sec_normals and not normals:
                            normals = sec_normals
                        for uv_idx, uv_data in enumerate(sec_uvs):
                            if uv_data and not uvs[uv_idx]:
                                uvs[uv_idx] = uv_data
                        if sec_colors and not colors:
                            colors = sec_colors
                        if sec_tc5 and not texcoord5_data:
                            texcoord5_data = sec_tc5
                
                # Parse index data with material assignments
                faces, face_materials = self.parse_index_buffer(index_buffer, mesh_data)
                
                if not vertices:
                    print(f"  ! Mesh {mesh_idx}: No vertices parsed (vb_id={vb_id}, desc_id={desc_id})")
                    continue
                    
                if not faces:
                    print(f"  ! Mesh {mesh_idx}: No faces parsed (ib_id={mesh_data.index_buffer_id})")
                    continue
                
                # Create mesh
                bl_mesh.from_pydata(vertices, [], faces)
                bl_mesh.update()
                
                # Apply normals - Blender 5.0+ automatically uses custom normals when set
                if self.import_normals and normals:
                    bl_mesh.normals_split_custom_set_from_vertices(normals)
                
                # Create UV layers
                uv_channels_created = 0
                has_lightmap_uv = False
                if uvs:
                    for uv_idx, uv_data in enumerate(uvs):
                        if uv_data and len(uv_data) > 0:
                            # TEXCOORD7 (index 7) is the lightmap UV channel
                            if uv_idx == 7:
                                uv_layer = bl_mesh.uv_layers.new(name="LightmapUV")
                                has_lightmap_uv = True
                                
                                # Apply scale+bias transform from BakedLight channel
                                # finalUV = rawUV * Scale + Bias
                                lm_scale = (1.0, 1.0)
                                lm_bias = (0.0, 0.0)
                                if mesh_data.baked_light:
                                    lm_scale = mesh_data.baked_light.scale
                                    lm_bias = mesh_data.baked_light.bias
                                
                                for face_idx, face in enumerate(bl_mesh.polygons):
                                    for loop_idx in face.loop_indices:
                                        loop = bl_mesh.loops[loop_idx]
                                        vert_idx = loop.vertex_index
                                        if vert_idx < len(uv_data):
                                            raw_u, raw_v = uv_data[vert_idx]
                                            # Apply scale+bias, keeping the V-flip already applied
                                            # Note: raw_v is already flipped (1.0 - v) from parse_vertex_buffer
                                            # We need to un-flip, apply transform, then re-flip
                                            orig_v = 1.0 - raw_v
                                            final_u = raw_u * lm_scale[0] + lm_bias[0]
                                            final_v = orig_v * lm_scale[1] + lm_bias[1]
                                            uv_layer.data[loop_idx].uv = (final_u, 1.0 - final_v)
                            else:
                                uv_layer = bl_mesh.uv_layers.new(name=f"UVMap{uv_idx}" if uv_idx > 0 else "UVMap")
                                for face_idx, face in enumerate(bl_mesh.polygons):
                                    for loop_idx in face.loop_indices:
                                        loop = bl_mesh.loops[loop_idx]
                                        vert_idx = loop.vertex_index
                                        if vert_idx < len(uv_data):
                                            uv_layer.data[loop_idx].uv = uv_data[vert_idx]
                            uv_channels_created += 1
                
                # Create vertex colors (Blender 5.0+ uses color attributes)
                if self.import_vertex_colors and colors:
                    color_attr = bl_mesh.color_attributes.new(
                        name="Color",
                        type='BYTE_COLOR',
                        domain='CORNER'
                    )
                    for face in bl_mesh.polygons:
                        for loop_idx in face.loop_indices:
                            loop = bl_mesh.loops[loop_idx]
                            vert_idx = loop.vertex_index
                            if vert_idx < len(colors):
                                # Ensure we have RGBA (4 components)
                                col = colors[vert_idx]
                                if len(col) == 3:
                                    color_attr.data[loop_idx].color = (*col, 1.0)
                                else:
                                    color_attr.data[loop_idx].color = col[:4]
                
                # TEXCOORD5 - bush animation anchor positions (3D per-vertex data)
                # Store as a vertex-domain float vector attribute for round-trip export
                if texcoord5_data and len(texcoord5_data) > 0:
                    # Store as a vector attribute on the mesh (per-vertex, 3 floats)
                    tc5_attr = bl_mesh.attributes.new(name="TEXCOORD5", type='FLOAT_VECTOR', domain='POINT')
                    for vert_idx in range(min(len(texcoord5_data), len(bl_mesh.vertices))):
                        tc5_attr.data[vert_idx].vector = texcoord5_data[vert_idx]
                
                # Assign materials
                material_mapping = {}  # Maps primitive index to material slot
                
                # Get per-mesh lightmap texture path (only if lightmaps enabled)
                mesh_lightmap_texture = None
                if self.import_lightmaps and has_lightmap_uv and mesh_data.baked_light and mesh_data.baked_light.texture:
                    mesh_lightmap_texture = mesh_data.baked_light.texture
                
                # Build texture overrides dict: sampler_name -> texture_path
                # Maps per-mesh texture overrides using file-level sampler_defs
                mesh_texture_overrides = {}
                if mesh_data.texture_overrides:
                    for override in mesh_data.texture_overrides:
                        # Find sampler name by index
                        for sampler_def in mapgeo.sampler_defs:
                            if sampler_def.index == override.index:
                                mesh_texture_overrides[sampler_def.name] = override.texture
                                break
                    if mesh_texture_overrides and imported_count <= 5:
                        print(f"    Texture overrides: {mesh_texture_overrides}")
                
                # Get per-mesh baked paint UV transform
                baked_paint_scale = mesh_data.baked_paint_scale
                baked_paint_bias = mesh_data.baked_paint_bias
                
                if self.import_materials:
                    for prim_idx, prim in enumerate(mesh_data.primitives):
                        mat_name = prim.material if prim.material else "Default"
                        
                        # Build cache key that includes lightmap and texture override info
                        mat_cache_key = mat_name
                        if mesh_lightmap_texture:
                            import hashlib
                            lm_hash = hashlib.md5(mesh_lightmap_texture.encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_name}__lm__{lm_hash}"
                        if mesh_texture_overrides:
                            import hashlib
                            override_hash = hashlib.md5(str(sorted(mesh_texture_overrides.items())).encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_cache_key}__to__{override_hash}"
                        if baked_paint_scale != (1.0, 1.0) or baked_paint_bias != (0.0, 0.0):
                            import hashlib
                            bp_hash = hashlib.md5(f"{baked_paint_scale}{baked_paint_bias}".encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_cache_key}__bp__{bp_hash}"
                        
                        if mat_cache_key not in materials:
                            # Try to load from materials database first
                            if material_loader and materials_db:
                                mat = material_loader.get_or_create_material(
                                    mat_name, materials_db,
                                    lightmap_texture=mesh_lightmap_texture,
                                    lightmap_color_scale=lightmap_color_scale,
                                    texture_overrides=mesh_texture_overrides,
                                    baked_paint_scale=baked_paint_scale,
                                    baked_paint_bias=baked_paint_bias
                                )
                                materials[mat_cache_key] = mat
                            else:
                                # Fallback to simple material
                                materials[mat_cache_key] = self.create_material(mat_name)
                        
                        # Check if material is already in mesh materials
                        mat_slot_idx = -1
                        for idx, mat_slot in enumerate(bl_mesh.materials):
                            if mat_slot == materials[mat_cache_key]:
                                mat_slot_idx = idx
                                break
                        
                        if mat_slot_idx == -1:
                            bl_mesh.materials.append(materials[mat_cache_key])
                            mat_slot_idx = len(bl_mesh.materials) - 1
                        
                        material_mapping[prim_idx] = mat_slot_idx
                    
                    # Assign face materials
                    if len(material_mapping) > 0:
                        for face_idx, face in enumerate(bl_mesh.polygons):
                            if face_idx < len(face_materials):
                                prim_idx = face_materials[face_idx]
                                if prim_idx in material_mapping:
                                    face.material_index = material_mapping[prim_idx]
                
                # Create object
                obj = bpy.data.objects.new(mesh_name, bl_mesh)
                
                # Link object to main Meshes collection (this owns the object data)
                meshes_collection.objects.link(obj)
                
                # Link to layer-specific collections based on visibility flags
                if mesh_data.visibility:
                    for layer_flag, layer_col in layer_collections.items():
                        if mesh_data.visibility & layer_flag:
                            layer_col.objects.link(obj)
                
                # Link to baron state collections if baron hash is decoded
                # baron_layers_decoded contains bit values (1, 2, 4, 8, etc.)
                # This provides better organization for meshes with baron visibility
                if "baron_layers_decoded" in obj and obj["baron_layers_decoded"]:
                    try:
                        import ast
                        baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                        for baron_state_bit in baron_layers:
                            if baron_state_bit in baron_collections:
                                baron_collections[baron_state_bit].objects.link(obj)
                    except Exception as e:
                        print(f"    Warning: Could not link mesh to baron collections: {e}")
                
                # Apply transform
                matrix = self.convert_transform_matrix(mesh_data.transform_matrix)
                obj.matrix_world = matrix
                
                # Apply scale
                obj.scale *= self.scale_factor
                
                # Store essential custom properties for mapgeo export
                
                # Visibility and quality
                obj["visibility_layer"] = int(mesh_data.visibility)
                obj["quality"] = int(mesh_data.quality)
                
                # Render flags, layer transition behavior, backface culling
                obj["layer_transition_behavior"] = mesh_data.layer_transition_behavior
                obj["render_flags"] = mesh_data.render_flags
                obj["disable_backface_culling"] = int(mesh_data.disable_backface_culling)
                
                # Lightmap data - store scale/bias for all channels for round-trip
                if mesh_data.baked_light:
                    if mesh_data.baked_light.texture:
                        obj["lightmap_texture"] = mesh_data.baked_light.texture
                    obj["lightmap_scale"] = list(mesh_data.baked_light.scale)
                    obj["lightmap_bias"] = list(mesh_data.baked_light.bias)
                if mesh_data.stationary_light:
                    if mesh_data.stationary_light.texture:
                        obj["stationary_light_texture"] = mesh_data.stationary_light.texture
                    obj["stationary_light_scale"] = list(mesh_data.stationary_light.scale)
                    obj["stationary_light_bias"] = list(mesh_data.stationary_light.bias)
                
                # Baked paint scale/bias (version 17+)
                if mesh_data.baked_paint_scale != (1.0, 1.0) or mesh_data.baked_paint_bias != (0.0, 0.0):
                    obj["baked_paint_scale"] = list(mesh_data.baked_paint_scale)
                    obj["baked_paint_bias"] = list(mesh_data.baked_paint_bias)
                
                # Version-specific fields (hex without 0x prefix)
                if mesh_data.unknown_version18_int:
                    obj["render_region_hash"] = f"{mesh_data.unknown_version18_int:08X}"  # Hex without 0x
                if mesh_data.visibility_controller_path_hash:
                    # Baron Hash System: When set (non-zero), this OVERRIDES the dragon layer system
                    # The hash references a ChildMapVisibilityController in materials.bin
                    # which defines complex visibility behavior combining multiple dragon layers
                    # See baron_hash_system.md for full documentation
                    baron_hash_str = f"{mesh_data.visibility_controller_path_hash:08X}"
                    obj["baron_hash"] = baron_hash_str  # Hex without 0x
                    
                    # Decode baron hash to determine actual layer visibility
                    if baron_parser:
                        try:
                            controller = baron_parser.decode_baron_hash(baron_hash_str)
                            
                            # Store decoded baron layers (if any)
                            if controller.baron_layers:
                                # Convert set to sorted list for storage
                                baron_layers_list = sorted(list(controller.baron_layers))
                                obj["baron_layers_decoded"] = str(baron_layers_list)
                            
                            # Store decoded dragon layers (if any)
                            if controller.dragon_layers:
                                # Convert set to sorted list for storage
                                dragon_layers_list = sorted(list(controller.dragon_layers))
                                obj["baron_dragon_layers_decoded"] = str(dragon_layers_list)
                            
                            # Store parent mode for reference
                            obj["baron_parent_mode"] = controller.parent_mode
                            
                            if imported_count <= 5:
                                print(f"    Baron Hash {baron_hash_str}:")
                                print(f"      ParentMode: {controller.parent_mode} ({'Not Visible on this layer' if controller.parent_mode == 3 else 'Visible on this layer' if controller.parent_mode == 1 else 'Unknown'})")
                                if controller.baron_layers:
                                    baron_names = [baron_hash_parser.get_baron_layer_name(l) for l in controller.baron_layers]
                                    print(f"      Baron Layers: {', '.join(baron_names)}")
                                if controller.dragon_layers:
                                    dragon_names = [baron_hash_parser.get_dragon_layer_name(l) for l in controller.dragon_layers]
                                    print(f"      Dragon Layers: {', '.join(dragon_names)}")
                        except Exception as e:
                            print(f"    Warning: Could not decode baron hash {baron_hash_str}: {e}")
                
                imported_count += 1
                if imported_count <= 5 or imported_count % 100 == 0:
                    uv_info = f", {uv_channels_created} UV" if uv_channels_created > 0 else ", no UV"
                    print(f"  ✓ Imported mesh {mesh_idx}: {len(vertices)} verts, {len(faces)} faces{uv_info}")
            
            except Exception as e:
                print(f"  ✗ Error importing mesh {mesh_idx}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue        
        
        print(f"\n✓ Successfully imported {imported_count}/{len(mapgeo.meshes)} meshes")
        
        # Print layer statistics
        print(f"\nLayer Distribution:")
        for layer_flag, layer_col in layer_collections.items():
            layer_name = layer_names[layer_flag]
            mesh_count = len(layer_col.objects)
            print(f"  {layer_name}: {mesh_count} meshes")
        
        # Import bucket grids
        if self.import_bucket_grid and mapgeo.bucket_grids:
            self.import_bucket_grids(context, collection, collection_name, mapgeo)
        
        # Store bucket grid raw data on the collection for export
        if mapgeo.bucket_grids:
            collection["has_bucket_grids"] = True
            collection["bucket_grid_count"] = len(mapgeo.bucket_grids)
            # Store source file for potential re-read on export
            collection["source_mapgeo_path"] = self.filepath
        
        # Store planar reflector data on the collection for export
        if mapgeo.planar_reflectors:
            collection["has_planar_reflectors"] = True
            collection["planar_reflector_count"] = len(mapgeo.planar_reflectors)
        
        # Create scene lighting from map settings (Sun, World ambient)
        if self.import_lightmaps and map_settings:
            self.create_scene_lighting(context, collection, map_settings)
            
    def import_bucket_grids(self, context, parent_collection, collection_name, mapgeo):
        """
        Import bucket grid scene graph data as visual wireframe meshes.
        
        Creates a separate collection for bucket grid visualization with:
        - Wireframe mesh objects for each bucket grid's simplified geometry
        - Bounding box empties showing grid extents
        - Custom properties storing metadata for export
        """
        import json
        
        scale = self.scale_factor
        
        # Create bucket grid collection separate from _Meshes
        bg_col_name = f"{collection_name}_BucketGrid"
        bg_collection = bpy.data.collections.new(bg_col_name)
        parent_collection.children.link(bg_collection)
        
        # Tag the collection for identification
        bg_collection["is_bucket_grid_collection"] = True
        bg_collection["bucket_grid_count"] = len(mapgeo.bucket_grids)
        
        total_verts = 0
        total_faces = 0
        
        for grid_idx, grid in enumerate(mapgeo.bucket_grids):
            if grid.is_disabled:
                print(f"  Bucket grid {grid_idx}: disabled, skipping visual")
                continue
            
            if not grid.vertices or not grid.indices:
                print(f"  Bucket grid {grid_idx}: no geometry, skipping visual")
                continue
            
            # --- Create mesh from bucket grid geometry ---
            grid_name = f"BucketGrid_{grid_idx:03d}"
            if grid.path_hash:
                grid_name = f"BucketGrid_{grid.path_hash:08X}"
            
            mesh = bpy.data.meshes.new(grid_name)
            
            # Scale vertices and swap Y/Z (mapgeo Y-up → Blender Z-up)
            verts = [(v[0] * scale, v[2] * scale, v[1] * scale) for v in grid.vertices]
            
            # Build face list from indices with base_vertex offsets per bucket
            # Buckets use local indexing - must add base_vertex to each index
            faces = []
            for bucket_row in grid.buckets:
                for bucket in bucket_row:
                    face_count = bucket.inside_face_count + bucket.sticking_out_face_count
                    if face_count == 0:
                        continue
                    
                    # Process indices for this bucket
                    start_idx = bucket.start_index
                    for i in range(face_count):
                        idx_pos = start_idx + (i * 3)
                        if idx_pos + 2 < len(grid.indices):
                            # Apply base_vertex offset and reverse winding for Y/Z swap
                            v0 = grid.indices[idx_pos] + bucket.base_vertex
                            v1 = grid.indices[idx_pos + 1] + bucket.base_vertex
                            v2 = grid.indices[idx_pos + 2] + bucket.base_vertex
                            # Reverse winding order for coordinate system handedness
                            faces.append((v0, v2, v1))
            
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            
            total_verts += len(verts)
            total_faces += len(faces)
            
            # Create object
            obj = bpy.data.objects.new(grid_name, mesh)
            bg_collection.objects.link(obj)
            
            # Create or get material with crimson red color and transparency
            mat_name = f"{grid_name}_Material"
            # Check if material exists and remove it to ensure fresh creation
            if mat_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[mat_name])
            
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            mat.blend_method = 'BLEND'  # Enable transparency
            
            # Set up material nodes
            nodes = mat.node_tree.nodes
            nodes.clear()
            
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            bsdf.inputs['Base Color'].default_value = (0.935752, 0.055, 0.0, 1.0)  # Crimson red
            bsdf.inputs['Alpha'].default_value = 0.04  # 96% transparent (4% opaque)
            
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (300, 0)
            
            mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            
            # Assign material to mesh
            if mesh.materials:
                mesh.materials[0] = mat
            else:
                mesh.materials.append(mat)
            
            # Set display as wireframe for visual clarity
            obj.display_type = 'WIRE'
            obj.show_wire = True
            obj.show_all_edges = True
            obj.color = (0.86, 0.08, 0.24, 0.8)  # Object color for viewport
            
            # Make non-selectable by default to avoid accidental edits
            obj.hide_select = True
            
            # Store metadata as custom properties for export
            obj["is_bucket_grid"] = True
            obj["bucket_grid_index"] = grid_idx
            obj["path_hash"] = f"{grid.path_hash:08X}" if grid.path_hash else "00000000"
            obj["bounds_min_x"] = grid.min_x
            obj["bounds_min_z"] = grid.min_z
            obj["bounds_max_x"] = grid.max_x
            obj["bounds_max_z"] = grid.max_z
            obj["bucket_size_x"] = grid.bucket_size_x
            obj["bucket_size_z"] = grid.bucket_size_z
            obj["stickout_x"] = grid.max_stickout_x
            obj["stickout_z"] = grid.max_stickout_z
            obj["buckets_per_side"] = grid.buckets_per_side
            obj["is_disabled"] = grid.is_disabled
            obj["flags"] = grid.flags
            if grid.unknown_v18_float is not None:
                obj["unknown_v18_float"] = grid.unknown_v18_float
            
            # Store face visibility flags if present
            if grid.face_visibility_flags:
                vis_hex = bytes(grid.face_visibility_flags).hex()
                obj["face_visibility_flags_hex"] = vis_hex
            
            # Store serialized bucket grid data in module cache for export
            global _imported_bucket_grids_cache
            
            grid_json = {
                "index": grid_idx,
                "path_hash": grid.path_hash,
                "min_x": grid.min_x,
                "min_z": grid.min_z,
                "max_x": grid.max_x,
                "max_z": grid.max_z,
                "bucket_size_x": grid.bucket_size_x,
                "bucket_size_z": grid.bucket_size_z,
                "buckets_per_side": grid.buckets_per_side,
                "is_disabled": grid.is_disabled,
                "flags": grid.flags,
                "unknown_v18_float": grid.unknown_v18_float,
                "max_stickout_x": grid.max_stickout_x,
                "max_stickout_z": grid.max_stickout_z,
                "vertices": [(v[0], v[1], v[2]) for v in grid.vertices],
                "indices": grid.indices,
                "buckets": [
                    [
                        {
                            "max_stickout_x": b.max_stickout_x,
                            "max_stickout_z": b.max_stickout_z,
                            "start_index": b.start_index,
                            "base_vertex": b.base_vertex,
                            "inside_face_count": b.inside_face_count,
                            "sticking_out_face_count": b.sticking_out_face_count
                        }
                        for b in row
                    ]
                    for row in grid.buckets
                ],
                "face_visibility_flags": grid.face_visibility_flags,
            }
            _imported_bucket_grids_cache[grid_idx] = grid_json
            print(f"  Cached bucket grid {grid_idx}")
            
            # --- Create bounding box wireframe ---
            bbox_name = f"{grid_name}_Bounds"
            bbox_mesh = bpy.data.meshes.new(bbox_name)
            
            min_x = grid.min_x * scale
            min_y = grid.min_z * scale  # mapgeo Z → Blender Y
            max_x = grid.max_x * scale
            max_y = grid.max_z * scale  # mapgeo Z → Blender Y
            
            # Flat rectangle on X-Y plane, thin Z slab (mapgeo Y-up → Blender Z-up)
            z_low = -0.1 * scale
            z_high = 0.1 * scale
            
            bbox_verts = [
                (min_x, min_y, z_low),
                (max_x, min_y, z_low),
                (max_x, max_y, z_low),
                (min_x, max_y, z_low),
                (min_x, min_y, z_high),
                (max_x, min_y, z_high),
                (max_x, max_y, z_high),
                (min_x, max_y, z_high),
            ]
            bbox_edges = [
                (0,1),(1,2),(2,3),(3,0),
                (4,5),(5,6),(6,7),(7,4),
                (0,4),(1,5),(2,6),(3,7),
            ]
            bbox_mesh.from_pydata(bbox_verts, bbox_edges, [])
            bbox_mesh.update()
            
            # Create or get material for bounding box
            bbox_mat_name = f"{bbox_name}_Material"
            # Check if material exists and remove it to ensure fresh creation
            if bbox_mat_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[bbox_mat_name])
            
            bbox_mat = bpy.data.materials.new(name=bbox_mat_name)
            bbox_mat.use_nodes = True
            bbox_mat.blend_method = 'BLEND'
            
            bbox_nodes = bbox_mat.node_tree.nodes
            bbox_nodes.clear()
            
            bbox_bsdf = bbox_nodes.new(type='ShaderNodeBsdfPrincipled')
            bbox_bsdf.location = (0, 0)
            bbox_bsdf.inputs['Base Color'].default_value = (0.935752, 0.055, 0.0, 1.0)  # Vermillion
            bbox_bsdf.inputs['Alpha'].default_value = 0.05
            
            bbox_output = bbox_nodes.new(type='ShaderNodeOutputMaterial')
            bbox_output.location = (300, 0)
            
            bbox_mat.node_tree.links.new(bbox_bsdf.outputs['BSDF'], bbox_output.inputs['Surface'])
            
            if bbox_mesh.materials:
                bbox_mesh.materials[0] = bbox_mat
            else:
                bbox_mesh.materials.append(bbox_mat)
            
            bbox_obj = bpy.data.objects.new(bbox_name, bbox_mesh)
            bg_collection.objects.link(bbox_obj)
            bbox_obj.display_type = 'WIRE'
            bbox_obj.color = (0.935752, 0.055, 0.0, 0.05)  # Match material color
            bbox_obj.hide_select = True
            bbox_obj["is_bucket_grid_bounds"] = True
            bbox_obj["bucket_grid_index"] = grid_idx
        
        # Store per-grid bucket data as JSON on the collection for export
        bucket_data_list = []
        for grid_idx, grid in enumerate(mapgeo.bucket_grids):
            grid_data = {
                "index": grid_idx,
                "path_hash": grid.path_hash if grid.path_hash else 0,
                "unknown_v18_float": grid.unknown_v18_float,
                "bounds": [grid.min_x, grid.min_z, grid.max_x, grid.max_z],
                "stickout": [grid.max_stickout_x, grid.max_stickout_z],
                "bucket_size": [grid.bucket_size_x, grid.bucket_size_z],
                "buckets_per_side": grid.buckets_per_side,
                "is_disabled": grid.is_disabled,
                "flags": grid.flags,
            }
            if grid.buckets:
                cells = []
                for row in grid.buckets:
                    row_cells = []
                    for b in row:
                        row_cells.append({
                            "max_stickout_x": b.max_stickout_x,
                            "max_stickout_z": b.max_stickout_z,
                            "start_index": b.start_index,
                            "base_vertex": b.base_vertex,
                            "inside_face_count": b.inside_face_count,
                            "sticking_out_face_count": b.sticking_out_face_count,
                        })
                    cells.append(row_cells)
                grid_data["buckets"] = cells
            bucket_data_list.append(grid_data)
        
        bg_collection["bucket_data_json"] = json.dumps(bucket_data_list)
        
        # Hide the bucket grid collection by default in the viewport
        view_layer = context.view_layer
        def find_layer_collection(layer_col, name):
            if layer_col.name == name:
                return layer_col
            for child in layer_col.children:
                result = find_layer_collection(child, name)
                if result:
                    return result
            return None
        
        layer_col = find_layer_collection(view_layer.layer_collection, bg_col_name)
        if layer_col:
            layer_col.hide_viewport = True
        
        print(f"\n✓ Imported {len(mapgeo.bucket_grids)} bucket grid(s): {total_verts} verts, {total_faces} faces")
        print(f"  Collection '{bg_col_name}' created (hidden by default)")
    
    def create_scene_lighting(self, context, collection, map_settings):
        """
        Create scene lighting objects from MapSunProperties + MapBakeProperties.
        
        Sets up:
        - Sun light with direction/color from sunDirection/sunColor
        - World environment with hemisphere gradient ambient lighting:
            skyLightColor  = ambient light from above (sky dome)
            horizonColor   = ambient light from the sides (horizon ring)
            groundColor    = ambient light bounced from below (ground plane)
          These form a 3-color hemisphere used by League's ambient lighting system.
        - Fog as Volume Scatter on World (from fogColor, fogStartAndEnd)
        - MapBakeProperties stored as custom properties
        
        Lightmapped materials use Emission (not affected by scene lights).
        Non-lightmapped materials (NO_BAKED_LIGHTING) respond to these lights.
        """
        import math
        from mathutils import Vector
        
        collection_name = collection.name
        
        # Create Lighting collection
        lighting_col = bpy.data.collections.new(f"{collection_name}_Lighting")
        collection.children.link(lighting_col)
        
        # --- Sun Light ---
        sun_direction = map_settings.get('sun_direction')
        sun_color = map_settings.get('sun_color', [1, 1, 1, 1])
        
        if sun_direction:
            sun_data = bpy.data.lights.new(name="MapSun", type='SUN')
            sun_data.color = (sun_color[0], sun_color[1], sun_color[2])
            sun_data.energy = 2.0  # Reasonable energy for non-lightmapped materials
            
            sun_obj = bpy.data.objects.new("MapSun", sun_data)
            lighting_col.objects.link(sun_obj)
            
            # Convert League sun direction to Blender rotation
            # League: X-right, Y-up, Z-forward → sunDirection = direction from surface to sun
            # Blender: X-right, Y-forward, Z-up → swap Y and Z
            league_dir = Vector(sun_direction)
            blender_dir = Vector((league_dir.x, league_dir.z, league_dir.y))
            
            # Sun light faces along its local -Z axis
            # Point -Z toward the surface = -blender_dir direction
            target_dir = -blender_dir.normalized()
            rotation = target_dir.to_track_quat('-Z', 'Y')
            sun_obj.rotation_euler = rotation.to_euler()
            
            # Store original sun properties as custom properties
            sun_obj["sun_direction_league"] = list(sun_direction)
            sun_obj["sun_color"] = list(sun_color)
            
            print(f"  ✓ Created Sun light: dir={sun_direction}, color=({sun_color[0]:.3f}, {sun_color[1]:.3f}, {sun_color[2]:.3f})")
        
        # --- World Environment (ambient lighting + fog) ---
        # League uses a 3-color hemisphere ambient lighting system:
        #   skyLightColor  = light color from directly above (sky dome top)
        #   horizonColor   = light color from the sides (horizon ring, ~90° from zenith)
        #   groundColor    = light color from below (ground bounce, reflected light)
        # These blend based on surface normal direction to create soft ambient lighting.
        sky_color = map_settings.get('sky_light_color', [0.5, 0.5, 0.6, 1])
        sky_scale = map_settings.get('sky_light_scale', 1.0)
        horizon_color = map_settings.get('horizon_color', [0.6, 0.7, 0.8, 1])
        ground_color = map_settings.get('ground_color', [0.3, 0.3, 0.4, 1])
        
        world = bpy.data.worlds.new(name=f"{collection_name}_World")
        context.scene.world = world
        world.use_nodes = True
        
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        nodes.clear()
        
        # --- Surface: gradient background (ambient hemisphere lighting) ---
        output_node = nodes.new('ShaderNodeOutputWorld')
        output_node.location = (600, 0)
        
        bg_node = nodes.new('ShaderNodeBackground')
        bg_node.location = (400, 0)
        bg_node.inputs['Strength'].default_value = sky_scale
        bg_node.label = f"Ambient (scale={sky_scale})"
        
        links.new(bg_node.outputs['Background'], output_node.inputs['Surface'])
        
        # Color Ramp: ground(0) → horizon(0.5) → sky(1.0) based on world normal Z
        ramp_node = nodes.new('ShaderNodeValToRGB')
        ramp_node.location = (100, 0)
        ramp_node.label = "Hemisphere Gradient"
        
        ramp = ramp_node.color_ramp
        ramp.elements[0].position = 0.0
        ramp.elements[0].color = (ground_color[0], ground_color[1], ground_color[2], 1.0)
        ramp.elements[1].position = 1.0
        ramp.elements[1].color = (sky_color[0], sky_color[1], sky_color[2], 1.0)
        horizon_stop = ramp.elements.new(0.5)
        horizon_stop.color = (horizon_color[0], horizon_color[1], horizon_color[2], 1.0)
        
        links.new(ramp_node.outputs['Color'], bg_node.inputs['Color'])
        
        # Map Range: convert Z normal from [-1, 1] to [0, 1]
        map_range_node = nodes.new('ShaderNodeMapRange')
        map_range_node.location = (-100, 0)
        map_range_node.inputs['From Min'].default_value = -1.0
        map_range_node.inputs['From Max'].default_value = 1.0
        map_range_node.inputs['To Min'].default_value = 0.0
        map_range_node.inputs['To Max'].default_value = 1.0
        
        links.new(map_range_node.outputs['Result'], ramp_node.inputs['Fac'])
        
        # Separate XYZ → Z component of normal
        sep_xyz_node = nodes.new('ShaderNodeSeparateXYZ')
        sep_xyz_node.location = (-300, 0)
        links.new(sep_xyz_node.outputs['Z'], map_range_node.inputs['Value'])
        
        # Texture Coordinate → Normal
        geom_node = nodes.new('ShaderNodeTexCoord')
        geom_node.location = (-500, 0)
        links.new(geom_node.outputs['Normal'], sep_xyz_node.inputs['Vector'])
        
        # Store world properties
        world["sky_light_color"] = list(sky_color)
        world["sky_light_scale"] = sky_scale
        world["horizon_color"] = list(horizon_color)
        world["ground_color"] = list(ground_color)
        
        print(f"  ✓ Created World ambient: sky=({sky_color[0]:.3f}, {sky_color[1]:.3f}, {sky_color[2]:.3f}), "
              f"horizon=({horizon_color[0]:.3f}, {horizon_color[1]:.3f}, {horizon_color[2]:.3f}), "
              f"ground=({ground_color[0]:.3f}, {ground_color[1]:.3f}, {ground_color[2]:.3f}), scale={sky_scale}")
        
        # --- Volume: Fog (as mesh cube with volume scatter material) ---
        fog_enabled = map_settings.get('fog_enabled', True)
        fog_color = map_settings.get('fog_color')
        fog_start_end = map_settings.get('fog_start_end')
        
        if fog_enabled and fog_color and fog_start_end:
            # fogStartAndEnd values are signed distances (negative = active range)
            fog_start = abs(fog_start_end[0])
            fog_end = abs(fog_start_end[1])
            
            if fog_end > fog_start and fog_end > 0:
                fog_density = 3.0 / fog_end
                
                # Create a large cube mesh to hold the fog volume
                # Size it to cover the entire map with generous padding
                fog_size = fog_end * 2.0  # Large enough to encompass the map
                
                import bmesh
                fog_mesh = bpy.data.meshes.new("MapFog_Mesh")
                bm = bmesh.new()
                bmesh.ops.create_cube(bm, size=fog_size)
                bm.to_mesh(fog_mesh)
                bm.free()
                
                fog_obj = bpy.data.objects.new("MapFog", fog_mesh)
                lighting_col.objects.link(fog_obj)
                
                # Center the fog volume over the map (approximate center)
                # League maps are roughly centered around origin, offset Y (Blender) for height
                fog_obj.location = (0, 0, fog_size * 0.25)  # Slightly above ground
                fog_obj.display_type = 'BOUNDS'  # Show as wireframe box in viewport
                
                # Create volume scatter material
                fog_mat = bpy.data.materials.new(name="MapFog_Volume")
                fog_mat.use_nodes = True
                fog_nodes = fog_mat.node_tree.nodes
                fog_links = fog_mat.node_tree.links
                fog_nodes.clear()
                
                fog_output = fog_nodes.new('ShaderNodeOutputMaterial')
                fog_output.location = (300, 0)
                
                vol_scatter = fog_nodes.new('ShaderNodeVolumeScatter')
                vol_scatter.location = (0, 0)
                vol_scatter.inputs['Color'].default_value = (
                    fog_color[0], fog_color[1], fog_color[2], 1.0
                )
                vol_scatter.inputs['Density'].default_value = fog_density
                vol_scatter.label = f"Fog (density={fog_density:.6f})"
                
                fog_links.new(vol_scatter.outputs['Volume'], fog_output.inputs['Volume'])
                
                fog_mesh.materials.append(fog_mat)
                
                # Store fog properties on the fog object
                fog_obj["fog_color"] = list(fog_color)
                fog_obj["fog_density"] = fog_density
                fog_obj["fog_start"] = fog_start
                fog_obj["fog_end"] = fog_end
                
                fog_alt_color = map_settings.get('fog_alternate_color')
                if fog_alt_color:
                    fog_obj["fog_alternate_color"] = list(fog_alt_color)
                
                # Configure EEVEE volumetrics
                eevee = context.scene.eevee
                eevee.volumetric_start = max(1.0, fog_start * 0.1)
                eevee.volumetric_end = fog_end * 1.5
                
                print(f"  ✓ Created Fog mesh volume: color=({fog_color[0]:.3f}, {fog_color[1]:.3f}, {fog_color[2]:.3f}), "
                      f"density={fog_density:.6f}, range=[{fog_start:.0f}, {fog_end:.0f}], size={fog_size:.0f}")
            else:
                print(f"  ℹ Fog skipped: invalid range [{fog_start_end[0]}, {fog_start_end[1]}]")
        elif not fog_enabled:
            print(f"  ℹ Fog disabled in map settings")
        
        # --- Store MapSunProperties on World object (visible in World > Custom Properties) ---
        world["fog_enabled"] = fog_enabled
        if fog_color:
            world["fog_color_value"] = list(fog_color)
        if fog_start_end:
            world["fog_start_end"] = list(fog_start_end)
        fog_alt = map_settings.get('fog_alternate_color')
        if fog_alt:
            world["fog_alternate_color"] = list(fog_alt)
        
        lightmap_scale = map_settings.get('lightmap_color_scale', 1.0)
        world["lightmap_color_scale"] = lightmap_scale
        
        # --- Store MapBakeProperties on World object ---
        light_grid_size = map_settings.get('light_grid_size')
        if light_grid_size is not None:
            world["bake_light_grid_size"] = light_grid_size
        
        light_grid_file = map_settings.get('light_grid_file')
        if light_grid_file:
            world["bake_light_grid_file"] = light_grid_file
        
        rma_texture = map_settings.get('rma_light_grid_texture')
        if rma_texture:
            world["bake_rma_light_grid_texture"] = rma_texture
        
        rma_scale = map_settings.get('rma_light_grid_intensity_scale')
        if rma_scale is not None:
            world["bake_rma_light_grid_intensity_scale"] = rma_scale
        
        light_grid_fullbright = map_settings.get('light_grid_fullbright')
        if light_grid_fullbright is not None:
            world["bake_light_grid_fullbright_intensity"] = light_grid_fullbright
        
        # --- Store MapLightingV2 on World object ---
        min_env = map_settings.get('min_env_color_contribution')
        if min_env is not None:
            world["lighting_v2_min_env_color_contribution"] = min_env
        
        print(f"  ✓ Stored all map properties on World ({world.name}) custom properties")
    
    def parse_vertex_buffer(self, vb: mapgeo_parser.VertexBuffer, vb_description: mapgeo_parser.VertexBufferDescription, mesh_data, mesh_idx: int = -1):
        """Parse vertex buffer data"""
        vertices = []
        normals = []
        uvs = [[] for _ in range(8)]  # Support up to 8 UV channels
        colors = []
        
        vertex_size = vb_description.get_vertex_size()
        if vertex_size == 0:
            return vertices, normals, uvs, colors
        
        # Use mesh vertex count as it's the authoritative source
        vertex_count = mesh_data.vertex_count
        if vertex_count * vertex_size > len(vb.data):
            vertex_count = len(vb.data) // vertex_size
        
        # Find element offsets
        position_elem = None
        normal_elem = None
        color_elem = None
        uv_elems = {}
        
        # Check if this buffer has UV coordinates
        has_uvs = any(mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7 
                      for elem in vb_description.elements)
        
        # Debug: log vertex declaration for first few meshes and meshes without UVs
        should_log = (mesh_idx >= 0 and mesh_idx < 3) or (mesh_idx in [199, 1] and not has_uvs)
        if should_log:
            print(f"    Mesh {mesh_idx} vertex buffer description: {len(vb_description.elements)} elements, stride={vertex_size}")
            for elem in vb_description.elements:
                elem_name_str = f"ElementName.{elem.name}"
                if elem.name == mapgeo_parser.VertexElementName.POSITION:
                    elem_name_str = "POSITION"
                elif elem.name == mapgeo_parser.VertexElementName.NORMAL:
                    elem_name_str = "NORMAL"
                elif elem.name == mapgeo_parser.VertexElementName.PRIMARY_COLOR:
                    elem_name_str = "PRIMARY_COLOR"
                elif elem.name == mapgeo_parser.VertexElementName.SECONDARY_COLOR:
                    elem_name_str = "SECONDARY_COLOR"
                elif elem.name == mapgeo_parser.VertexElementName.FOG_COORDINATE:
                    elem_name_str = "FOG_COORDINATE"
                elif elem.name == mapgeo_parser.VertexElementName.BLEND_INDEX:
                    elem_name_str = "BLEND_INDEX"
                elif elem.name == mapgeo_parser.VertexElementName.BLEND_WEIGHT:
                    elem_name_str = "BLEND_WEIGHT"
                elif mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7:
                    elem_name_str = f"TEXCOORD{elem.name - mapgeo_parser.VertexElementName.TEXCOORD0}"
                print(f"      {elem_name_str}: format={elem.format}, offset={elem.offset}, size={elem.get_size()}")
        
        for elem in vb_description.elements:
            if elem.name == mapgeo_parser.VertexElementName.POSITION:
                position_elem = elem
            elif elem.name == mapgeo_parser.VertexElementName.NORMAL:
                normal_elem = elem
            elif elem.name == mapgeo_parser.VertexElementName.PRIMARY_COLOR:
                color_elem = elem
            elif mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7:
                uv_idx = elem.name - mapgeo_parser.VertexElementName.TEXCOORD0
                uv_elems[uv_idx] = elem
        
        # Identify TEXCOORD5 specially (3-component animation data, NOT a UV map)
        texcoord5_elem = uv_elems.pop(5, None)
        texcoord5_data = []  # Will hold (x, y, z) per vertex in League coords
        
        # Initialize only the UV channels that exist
        uvs = [[] for _ in range(8)]
        
        # Parse vertices
        for i in range(vertex_count):
            offset = i * vertex_size
            vertex_data = vb.data[offset:offset + vertex_size]
            
            # Position
            if position_elem:
                pos = self.read_element(vertex_data, position_elem)
                if pos:
                    # League of Legends coordinate system conversion
                    # League: X-right, Y-up, Z-forward (towards top of map)
                    # Blender: X-right, Y-forward, Z-up
                    # To orient correctly: swap Y and Z
                    vertices.append((pos[0], pos[2], pos[1]))
                else:
                    vertices.append((0, 0, 0))  # Fallback
            
            # Normal
            if normal_elem:
                norm = self.read_element(vertex_data, normal_elem)
                if norm:
                    # Apply same coordinate system conversion as positions
                    normals.append((norm[0], norm[2], norm[1]))
            
            # UVs - only append to channels that have elements
            for uv_idx, uv_elem in uv_elems.items():
                uv = self.read_element(vertex_data, uv_elem)
                if uv and len(uv) >= 2:
                    # Flip V coordinate for Blender
                    uvs[uv_idx].append((uv[0], 1.0 - uv[1]))
                else:
                    # Add default UV if reading failed but element exists
                    uvs[uv_idx].append((0.0, 0.0))
            
            # TEXCOORD5 - animation anchor positions (3 floats, NOT a UV)
            if texcoord5_elem:
                tc5 = self.read_element(vertex_data, texcoord5_elem)
                if tc5 and len(tc5) >= 3:
                    # Store raw League coordinates (coordinate swap happens on import to Blender)
                    # League(X, Y, Z) -> Blender(X, Z, Y)
                    texcoord5_data.append((tc5[0], tc5[2], tc5[1]))
                else:
                    texcoord5_data.append((0.0, 0.0, 0.0))
            
            # Colors
            if color_elem:
                color = self.read_element(vertex_data, color_elem)
                if color:
                    colors.append(color)
        
        return vertices, normals, uvs, colors, texcoord5_data
    
    def read_element(self, data: bytes, elem: mapgeo_parser.VertexElement):
        """Read a single vertex element"""
        try:
            offset = elem.offset
            fmt = elem.format
            
            if fmt == 0:  # X_FLOAT32
                return struct.unpack_from('<f', data, offset)
            elif fmt == 1:  # XY_FLOAT32
                return struct.unpack_from('<ff', data, offset)
            elif fmt == 2:  # XYZ_FLOAT32
                return struct.unpack_from('<fff', data, offset)
            elif fmt == 3:  # XYZW_FLOAT32
                return struct.unpack_from('<ffff', data, offset)
            elif fmt == 4:  # BGRA_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return (values[2]/255.0, values[1]/255.0, values[0]/255.0, values[3]/255.0)  # BGRA -> RGBA
            elif fmt == 5:  # ZYXW_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return (values[2]/255.0, values[1]/255.0, values[0]/255.0, values[3]/255.0)
            elif fmt == 6:  # RGBA_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 7:  # XY_PACKED1616 - 16-bit float (Half precision)
                return struct.unpack_from('<ee', data, offset)  # 'e' = 16-bit float
            elif fmt == 8:  # XYZ_PACKED161616 - 16-bit float (Half precision)
                return struct.unpack_from('<eee', data, offset)
            elif fmt == 9:  # XYZW_PACKED16161616 - 16-bit float (Half precision)
                return struct.unpack_from('<eeee', data, offset)
            elif fmt == 10:  # XY_PACKED88
                values = struct.unpack_from('<BB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 11:  # XYZ_PACKED888
                values = struct.unpack_from('<BBB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 12:  # XYZW_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return tuple(v / 255.0 for v in values)
        except Exception as e:
            # Debug: log what failed
            print(f"    ! Failed to read element at offset {offset}, format {fmt}: {e}")
        
        return None
    
    def parse_index_buffer(self, ib: mapgeo_parser.IndexBuffer, mesh_data):
        """Parse index buffer into faces with material assignments"""
        faces = []
        face_materials = []  # Track which primitive each face belongs to
        
        # Parse all primitives
        for prim_idx, prim in enumerate(mesh_data.primitives):
            index_size = 2  # U16
            
            for i in range(0, prim.index_count, 3):
                idx_offset = (prim.start_index + i) * index_size
                
                if idx_offset + index_size * 3 > len(ib.data):
                    break
                
                i0 = struct.unpack_from('<H', ib.data, idx_offset)[0]
                i1 = struct.unpack_from('<H', ib.data, idx_offset + index_size)[0]
                i2 = struct.unpack_from('<H', ib.data, idx_offset + index_size * 2)[0]
                
                faces.append((i0, i1, i2))
                face_materials.append(prim_idx)  # Track which primitive this face belongs to
        
        return faces, face_materials
    
    def create_material(self, name: str):
        """Create a Blender material"""
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            
            # Basic setup with Principled BSDF
            if mat.node_tree:
                nodes = mat.node_tree.nodes
                nodes.clear()
                
                # Add Principled BSDF
                bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                bsdf.location = (0, 0)
                
                # Add Output
                output = nodes.new('ShaderNodeOutputMaterial')
                output.location = (300, 0)
                
                # Link
                mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        
        return mat
    
    def convert_transform_matrix(self, matrix_list):
        """Convert 16-float list to Blender Matrix with coordinate system conversion"""
        # Mapgeo stores matrices in row-major order
        # Build the matrix from League's coordinate system
        mat_league = Matrix([
            [matrix_list[0], matrix_list[4], matrix_list[8], matrix_list[12]],
            [matrix_list[1], matrix_list[5], matrix_list[9], matrix_list[13]],
            [matrix_list[2], matrix_list[6], matrix_list[10], matrix_list[14]],
            [matrix_list[3], matrix_list[7], matrix_list[11], matrix_list[15]]
        ])
        
        # League: X-right, Y-up, Z-forward
        # Blender: X-right, Y-forward, Z-up
        # Conversion: swap Y and Z axes
        conversion = Matrix([
            [1, 0, 0, 0],  # Blender X = League X
            [0, 0, 1, 0],  # Blender Y = League Z
            [0, 1, 0, 0],  # Blender Z = League Y
            [0, 0, 0, 1]
        ])
        
        # Apply conversion
        mat_blender = conversion @ mat_league @ conversion.inverted()
        return mat_blender


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_mapgeo.bl_idname, text="League of Legends Mapgeo (.mapgeo)")


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_mapgeo)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_mapgeo)
