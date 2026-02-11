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

from . import mapgeo_parser
from . import utils
from . import material_loader as mat_loader
from . import baron_hash_parser


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
            
            # Import into Blender
            self.import_mapgeo(context, mapgeo)
            
            # Update visibility based on current dragon/baron layer filters
            from . import __init__ as addon_init
            addon_init.update_environment_visibility(None, context)
            
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
        baron_state_names = {
            0: "BaronBase",
            1: "BaronCup",
            2: "BaronTunnel",
            3: "BaronUpgraded"
        }
        baron_collections = {}
        for state_idx, state_name in baron_state_names.items():
            baron_col = bpy.data.collections.new(f"{collection_name}_{state_name}")
            collection.children.link(baron_col)
            baron_collections[state_idx] = baron_col
        
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
        settings = context.scene.mapgeo_settings
        
        if settings.materials_json_path and os.path.exists(settings.materials_json_path):
            if settings.assets_folder and os.path.exists(settings.assets_folder):
                print(f"  Loading materials from: {os.path.basename(settings.materials_json_path)}")
                print(f"  Assets folder: {settings.assets_folder}")
                
                material_loader = mat_loader.MaterialLoader(settings.assets_folder)
                materials_db = material_loader.load_materials_from_json(settings.materials_json_path)
                
                # Initialize baron hash parser for visibility decoding
                baron_parser = baron_hash_parser.MaterialsBinParser(settings.materials_json_path)
                print(f"  Baron hash parser initialized")
            else:
                print(f"  Warning: Assets folder not set or doesn't exist")
                print(f"  Materials will be created without textures")
        else:
            print(f"  No materials JSON specified - using simple materials")
        
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
                vertices, normals, uvs, colors = self.parse_vertex_buffer(
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
                        _, sec_normals, sec_uvs, sec_colors = self.parse_vertex_buffer(
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
                if uvs:
                    for uv_idx, uv_data in enumerate(uvs):
                        if uv_data and len(uv_data) > 0:
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
                
                # Assign materials
                material_mapping = {}  # Maps primitive index to material slot
                if self.import_materials:
                    for prim_idx, prim in enumerate(mesh_data.primitives):
                        mat_name = prim.material if prim.material else "Default"
                        
                        if mat_name not in materials:
                            # Try to load from materials database first
                            if material_loader and materials_db:
                                mat = material_loader.get_or_create_material(mat_name, materials_db)
                                materials[mat_name] = mat
                            else:
                                # Fallback to simple material
                                materials[mat_name] = self.create_material(mat_name)
                        
                        # Check if material is already in mesh materials
                        mat_slot_idx = -1
                        for idx, mat_slot in enumerate(bl_mesh.materials):
                            if mat_slot == materials[mat_name]:
                                mat_slot_idx = idx
                                break
                        
                        if mat_slot_idx == -1:
                            bl_mesh.materials.append(materials[mat_name])
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
                # This provides better organization for meshes with baron visibility
                if "baron_layers_decoded" in obj and obj["baron_layers_decoded"]:
                    try:
                        import ast
                        baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                        for baron_state_idx in baron_layers:
                            if baron_state_idx in baron_collections:
                                baron_collections[baron_state_idx].objects.link(obj)
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
                
                # Render flags
                obj["is_bush"] = mesh_data.is_bush
                obj["render_flags"] = mesh_data.render_flags
                
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
                                print(f"      ParentMode: {controller.parent_mode} ({'AND - visible on all' if controller.parent_mode == 3 else 'OR - visible on any' if controller.parent_mode == 1 else 'Unknown'})")
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
            
            # Colors
            if color_elem:
                color = self.read_element(vertex_data, color_elem)
                if color:
                    colors.append(color)
        
        return vertices, normals, uvs, colors
    
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
