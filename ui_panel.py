"""
UI Panel for Mapgeo Addon
Sidebar panels for layer management and import/export settings
"""

import bpy
import json
import os
from bpy.types import Panel, UIList

from .texture_utils import TexConverter, resolve_texture_path


def _material_items(self, context):
    items = [("", "(No Material)", "Leave material unchanged")]
    for mat in bpy.data.materials:
        items.append((mat.name, mat.name, ""))
    return items


def _get_diffuse_sampler_entry(samplers):
    sampler_names = {
        "diffusetexture",
        "diffuse_texture",
        "baked_diffuse_texture",
        "colortexture",
        "_maintex",
    }
    for sampler in samplers:
        name = (sampler.get("textureName") or "").lower()
        if name in sampler_names:
            return sampler
    return None


def _update_material_diffuse_node(mat, texture_path, assets_folder):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return False

    nodes = mat.node_tree.nodes
    diffuse_node = None

    for node in nodes:
        if node.type != 'TEX_IMAGE':
            continue
        for link in node.outputs.get('Color', []).links:
            if link.to_node and link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name == 'Base Color':
                diffuse_node = node
                break
        if diffuse_node:
            break

    if diffuse_node is None:
        for node in nodes:
            if node.type == 'TEX_IMAGE':
                diffuse_node = node
                break

    if diffuse_node is None:
        return False

    resolved_path = resolve_texture_path(texture_path, assets_folder) if assets_folder else None
    if not resolved_path:
        return False

    converter = TexConverter()
    png_path = None
    if resolved_path.lower().endswith('.dds'):
        png_path = converter.convert_dds_to_png(resolved_path)
    else:
        png_path = converter.convert_tex_to_png(resolved_path)

    if not png_path:
        return False

    try:
        img = bpy.data.images.load(png_path, check_existing=True)
        diffuse_node.image = img
        return True
    except Exception:
        return False



class MAPGEO_OT_setup_mesh(bpy.types.Operator):
    """Setup wizard to assign mapgeo properties for selected meshes"""
    bl_idname = "mapgeo.setup_mesh"
    bl_label = "Mapgeo Setup Wizard"
    bl_description = "Assign mapgeo fields for selected meshes in one dialog"
    bl_options = {'REGISTER', 'UNDO'}

    set_visibility_layer: bpy.props.BoolProperty(
        name="Set Dragon Layer",
        default=True
    )
    visibility_mode: bpy.props.EnumProperty(
        name="Visibility Mode",
        description="How to apply the dragon layer value",
        items=[
            ('REPLACE', "Replace", "Replace existing visibility_layer"),
            ('ADD', "Add", "Add bits to existing visibility_layer"),
        ],
        default='REPLACE'
    )
    layer_base: bpy.props.BoolProperty(name="Base", default=True)
    layer_inferno: bpy.props.BoolProperty(name="Inferno", default=True)
    layer_mountain: bpy.props.BoolProperty(name="Mountain", default=True)
    layer_ocean: bpy.props.BoolProperty(name="Ocean", default=True)
    layer_cloud: bpy.props.BoolProperty(name="Cloud", default=True)
    layer_hextech: bpy.props.BoolProperty(name="Hextech", default=True)
    layer_chemtech: bpy.props.BoolProperty(name="Chemtech", default=True)
    layer_void: bpy.props.BoolProperty(name="Void", default=True)

    set_quality: bpy.props.BoolProperty(
        name="Set Quality",
        default=True
    )
    quality: bpy.props.IntProperty(
        name="Quality Bitmask",
        description="Quality visibility bitmask (0-31 typical, 31 = all levels)",
        default=31,
        min=0,
        max=255
    )

    set_bush: bpy.props.BoolProperty(
        name="Set Bush Flag",
        default=False
    )
    is_bush: bpy.props.BoolProperty(
        name="Is Bush",
        default=False
    )

    set_baron_hash: bpy.props.BoolProperty(
        name="Set Baron Hash",
        default=False
    )
    baron_hash: bpy.props.StringProperty(
        name="Baron Hash",
        description="Baron hash in hex format (8 characters, no 0x prefix)",
        default="00000000",
        maxlen=8
    )

    set_baron_layers: bpy.props.BoolProperty(
        name="Set Baron Layers",
        default=False
    )
    baron_base: bpy.props.BoolProperty(name="Base", default=True)
    baron_cup: bpy.props.BoolProperty(name="Cup", default=False)
    baron_tunnel: bpy.props.BoolProperty(name="Tunnel", default=False)
    baron_upgraded: bpy.props.BoolProperty(name="Upgraded", default=False)
    baron_parent_mode: bpy.props.EnumProperty(
        name="Parent Mode",
        description="Baron visibility mode",
        items=[
            ('1', "Visible", "Visible on listed baron states"),
            ('3', "Not Visible", "Hidden on listed baron states"),
        ],
        default='1'
    )

    set_render_region_hash: bpy.props.BoolProperty(
        name="Set Render Region Hash",
        default=False
    )
    render_region_hash: bpy.props.StringProperty(
        name="Render Region Hash",
        description="Render region hash in hex format (8 characters, no 0x prefix)",
        default="00000000",
        maxlen=8
    )

    set_render_flags: bpy.props.BoolProperty(
        name="Set Render Flags",
        default=False
    )
    render_flags: bpy.props.IntProperty(
        name="Render Flags",
        description="Render flags value (U16)",
        default=0,
        min=0,
        max=65535
    )

    set_layer_transition: bpy.props.BoolProperty(
        name="Set Layer Transition",
        default=False
    )
    layer_transition_behavior: bpy.props.IntProperty(
        name="Layer Transition",
        description="Layer transition behavior value",
        default=0,
        min=0,
        max=255
    )

    set_backface_culling: bpy.props.BoolProperty(
        name="Set Backface Culling",
        default=False
    )
    disable_backface_culling: bpy.props.BoolProperty(
        name="Disable Backface Culling",
        default=False
    )

    set_material: bpy.props.BoolProperty(
        name="Set Material",
        default=False
    )
    material_name: bpy.props.EnumProperty(
        name="Material",
        description="Assign material to selected meshes",
        items=_material_items
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Assign Mapgeo Properties", icon='OUTLINER_DATA_MESH')

        box = layout.box()
        row = box.row()
        row.prop(self, "set_visibility_layer")
        if self.set_visibility_layer:
            row = box.row()
            row.prop(self, "visibility_mode", expand=True)
            grid = box.grid_flow(columns=4, align=True)
            grid.prop(self, "layer_base")
            grid.prop(self, "layer_inferno")
            grid.prop(self, "layer_mountain")
            grid.prop(self, "layer_ocean")
            grid.prop(self, "layer_cloud")
            grid.prop(self, "layer_hextech")
            grid.prop(self, "layer_chemtech")
            grid.prop(self, "layer_void")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_quality")
        if self.set_quality:
            box.prop(self, "quality")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_bush")
        if self.set_bush:
            box.prop(self, "is_bush")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_baron_hash")
        if self.set_baron_hash:
            box.prop(self, "baron_hash")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_baron_layers")
        if self.set_baron_layers:
            grid = box.grid_flow(columns=4, align=True)
            grid.prop(self, "baron_base")
            grid.prop(self, "baron_cup")
            grid.prop(self, "baron_tunnel")
            grid.prop(self, "baron_upgraded")
            box.prop(self, "baron_parent_mode")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_render_region_hash")
        if self.set_render_region_hash:
            box.prop(self, "render_region_hash")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_render_flags")
        if self.set_render_flags:
            box.prop(self, "render_flags")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_layer_transition")
        if self.set_layer_transition:
            box.prop(self, "layer_transition_behavior")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_backface_culling")
        if self.set_backface_culling:
            box.prop(self, "disable_backface_culling")

        box = layout.box()
        row = box.row()
        row.prop(self, "set_material")
        if self.set_material:
            box.prop(self, "material_name")

    def execute(self, context):
        def update_layer_collections(obj, visibility_mask):
            layer_map = {
                1: "Base", 2: "Inferno", 4: "Mountain", 8: "Ocean",
                16: "Cloud", 32: "Hextech", 64: "Chemtech", 128: "Void"
            }
            for flag, name in layer_map.items():
                for coll in bpy.data.collections:
                    if coll.name.endswith(f"_{name}"):
                        if visibility_mask & flag:
                            if obj.name not in coll.objects:
                                coll.objects.link(obj)
                        else:
                            if obj.name in coll.objects:
                                coll.objects.unlink(obj)

        count = 0
        warn_no_baron_hash = False

        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            if self.set_visibility_layer:
                new_mask = 0
                if self.layer_base:
                    new_mask |= 1
                if self.layer_inferno:
                    new_mask |= 2
                if self.layer_mountain:
                    new_mask |= 4
                if self.layer_ocean:
                    new_mask |= 8
                if self.layer_cloud:
                    new_mask |= 16
                if self.layer_hextech:
                    new_mask |= 32
                if self.layer_chemtech:
                    new_mask |= 64
                if self.layer_void:
                    new_mask |= 128
                if self.visibility_mode == 'ADD':
                    new_mask = obj.get("visibility_layer", 0) | new_mask
                obj["visibility_layer"] = new_mask
                update_layer_collections(obj, new_mask)

            if self.set_quality:
                obj["quality"] = int(self.quality)

            if self.set_bush:
                obj["is_bush"] = bool(self.is_bush)

            if self.set_baron_hash:
                try:
                    int(self.baron_hash, 16)
                except ValueError:
                    self.report({'ERROR'}, "Invalid Baron Hash: use 8 hex characters")
                    return {'CANCELLED'}
                obj["baron_hash"] = self.baron_hash.upper()

            if self.set_baron_layers:
                baron_layers = []
                if self.baron_base:
                    baron_layers.append(1)
                if self.baron_cup:
                    baron_layers.append(2)
                if self.baron_tunnel:
                    baron_layers.append(4)
                if self.baron_upgraded:
                    baron_layers.append(8)
                obj["baron_layers_decoded"] = str(baron_layers)
                obj["baron_parent_mode"] = int(self.baron_parent_mode)

                current_hash = obj.get("baron_hash", "00000000")
                if current_hash == "00000000":
                    warn_no_baron_hash = True

            if self.set_render_region_hash:
                try:
                    int(self.render_region_hash, 16)
                except ValueError:
                    self.report({'ERROR'}, "Invalid Render Region Hash: use 8 hex characters")
                    return {'CANCELLED'}
                obj["render_region_hash"] = self.render_region_hash.upper()

            if self.set_render_flags:
                obj["render_flags"] = int(self.render_flags)

            if self.set_layer_transition:
                obj["layer_transition_behavior"] = int(self.layer_transition_behavior)

            if self.set_backface_culling:
                obj["disable_backface_culling"] = int(self.disable_backface_culling)

            if self.set_material and self.material_name:
                mat = bpy.data.materials.get(self.material_name)
                if mat:
                    if obj.data.materials:
                        obj.data.materials[0] = mat
                    else:
                        obj.data.materials.append(mat)

            count += 1

        # Trigger visibility update to show/hide based on current filter
        settings = context.scene.mapgeo_settings
        if hasattr(settings, 'dragon_layer_filter'):
            from . import update_environment_visibility
            update_environment_visibility(settings, context)

        if warn_no_baron_hash:
            self.report({'WARNING'}, "Baron layers set but baron_hash is 00000000; visibility filter will ignore baron layers")
        self.report({'INFO'}, f"Applied mapgeo settings to {count} mesh objects")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)


class VIEW3D_PT_mapgeo_panel(Panel):
    """Main Mapgeo Tools Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Mapgeo Tools"
    bl_idname = "VIEW3D_PT_mapgeo_panel"
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.mapgeo_settings
        
        # Version info
        addon_version = "0.2.0"
        layout.label(text=f"Version {addon_version}", icon='INFO')
        layout.separator()
        
        # Quick Actions
        box = layout.box()
        box.label(text="Quick Actions", icon='IMPORT')
        
        col = box.column(align=True)
        col.operator("import_scene.mapgeo", text="Import Mapgeo", icon='IMPORT')
        col.operator("export_scene.mapgeo", text="Export Mapgeo", icon='EXPORT')
        col.operator("mapgeo.setup_mesh", text="Setup Wizard", icon='PREFERENCES')
        
        # Info section
        layout.separator()
        box = layout.box()
        box.label(text="Scene Info", icon='INFO')
        
        # Count mesh objects
        mesh_count = len([obj for obj in context.scene.objects if obj.type == 'MESH'])
        box.label(text=f"Mesh Objects: {mesh_count}")
        
        # Count selected meshes
        selected_count = len([obj for obj in context.selected_objects if obj.type == 'MESH'])
        box.label(text=f"Selected Meshes: {selected_count}")
        
        # Last paths
        if settings.last_import_path:
            box.label(text=f"Last Import: ...{settings.last_import_path[-30:]}", icon='FILE_FOLDER')


class VIEW3D_PT_mapgeo_layers_panel(Panel):
    """Layer Management Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Layer Management"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.mapgeo_settings
        
        # Environment visibility filters (League engine style)
        box = layout.box()
        box.label(text="Environment State", icon='WORLD')
        
        col = box.column(align=True)
        col.label(text="Dragon Variation:", icon='OUTLINER_DATA_MESH')
        col.prop(settings, "dragon_layer_filter", text="")
        
        col.separator()
        col.label(text="Baron Pit State:", icon='LIGHTPROBE_VOLUME')
        col.prop(settings, "baron_layer_filter", text="")
        
        col.separator()
        row = col.row(align=True)
        row.operator("mapgeo.show_all", text="Show All", icon='HIDE_OFF')
        row.operator("mapgeo.show_not_used", text="Show Not Used", icon='GHOST_ENABLED')
        
        col.separator()
        info_box = col.box()
        info_box.label(text="ℹ League Engine Logic:", icon='INFO')
        info_box.label(text="• AllLayers (255) always visible")
        info_box.label(text="• Baron Hash uses referenced layers")
        info_box.label(text="• Switch between variations")
        
        # Layer operations
        layout.separator()
        
        # Custom mesh initialization
        box = layout.box()
        box.label(text="Custom Mesh Setup", icon='MESH_CUBE')
        row = box.row()
        row.scale_y = 1.2
        row.operator("mapgeo.setup_mesh", text="Open Setup Wizard", icon='PREFERENCES')
        row = box.row()
        row.operator("mapgeo.initialize_custom_mesh", text="Quick Initialize", icon='CHECKMARK')
        box.label(text="Wizard sets all mapgeo fields", icon='INFO')
        
        layout.separator()
        
        box = layout.box()
        box.label(text="Layer Operations", icon='OUTLINER_DATA_MESH')
        
        # Get active object's visibility layer for state display
        active_obj = context.active_object
        visibility = active_obj.get("visibility_layer", 0) if active_obj and active_obj.type == 'MESH' else 0
        
        layer_info = [
            (1, "Base"), (2, "Inferno"), (3, "Mountain"), (4, "Ocean"),
            (5, "Cloud"), (6, "Hextech"), (7, "Chemtech"), (8, "Void"),
        ]
        
        col = box.column(align=True)
        for layer_num, name in layer_info[:4]:
            flag = 1 << (layer_num - 1)
            is_assigned = bool(visibility & flag)
            icon = 'CHECKMARK' if is_assigned else 'X'
            op = col.operator("mapgeo.assign_layer", text=f"Layer {layer_num} ({name})", icon=icon, depress=is_assigned)
            op.layer = layer_num
        
        col = box.column(align=True)
        for layer_num, name in layer_info[4:]:
            flag = 1 << (layer_num - 1)
            is_assigned = bool(visibility & flag)
            icon = 'CHECKMARK' if is_assigned else 'X'
            op = col.operator("mapgeo.assign_layer", text=f"Layer {layer_num} ({name})", icon=icon, depress=is_assigned)
            op.layer = layer_num
        
        layout.separator()
        
        # Quality settings
        box = layout.box()
        box.label(text="Quality Settings (0-255)", icon='MODIFIER')
        
        col = box.column(align=True)
        col.label(text="Quality Levels (Bitmask):", icon='PRESET')
        row = col.row(align=True)
        row.operator("mapgeo.set_quality", text="Very Low").quality = 1
        row.operator("mapgeo.set_quality", text="Low").quality = 2
        row.operator("mapgeo.set_quality", text="Medium").quality = 4
        row = col.row(align=True)
        row.operator("mapgeo.set_quality", text="High").quality = 8
        row.operator("mapgeo.set_quality", text="Very High").quality = 16
        
        col.separator()
        col.operator("mapgeo.set_quality", text="Custom Quality...", icon='PROPERTIES')
        
        layout.separator()
        
        # Bush Assignment
        box = layout.box()
        box.label(text="Bush Assignment", icon='OUTLINER_OB_FORCE_FIELD')
        
        col = box.column(align=True)
        op = col.operator("mapgeo.assign_bush", text="Assign Bush to Selected")
        op.enable = True
        op = col.operator("mapgeo.assign_bush", text="Remove Bush from Selected")
        op.enable = False
        
        layout.separator()
        
        # Baron Hash Assignment
        box = layout.box()
        box.label(text="Baron Hash Assignment", icon='LIGHTPROBE_VOLUME')
        
        col = box.column(align=True)
        col.operator("mapgeo.assign_baron_hash", text="Assign Baron Hash to Selected", icon='ADD')
        
        layout.separator()
        
        # Render Region Hash Assignment
        box = layout.box()
        box.label(text="Render Region Hash Assignment", icon='MESH_GRID')
        
        col = box.column(align=True)
        col.prop(settings, "show_render_regions", text="Show Render Regions", toggle=True, icon='HIDE_OFF' if settings.show_render_regions else 'HIDE_ON')
        col.separator()
        col.operator("mapgeo.assign_render_region_hash", text="Assign Render Region Hash to Selected", icon='ADD')
        
        # Bucket Grid Section
        layout.separator()
        box = layout.box()
        box.label(text="Bucket Grid", icon='MESH_GRID')
        
        col = box.column(align=True)
        col.prop(settings, "show_bucket_grid", text="Show Bucket Grid", toggle=True, icon='HIDE_OFF' if settings.show_bucket_grid else 'HIDE_ON')
        col.separator()
        col.operator("mapgeo.toggle_bucket_grid_selectable", text="Toggle Selectable", icon='RESTRICT_SELECT_OFF')
        col.separator()
        col.operator("mapgeo.create_bucket_grid", text="Create Custom Bucket Grid", icon='ADD')
        
        # Show bucket grid info
        bg_count = 0
        for col_item in bpy.data.collections:
            if col_item.get("is_bucket_grid_collection"):
                bg_count = col_item.get("bucket_grid_count", 0)
                break
        if bg_count > 0:
            box.label(text=f"Grids in scene: {bg_count}", icon='INFO')
        
        # Point Light Section (Custom Feature)
        layout.separator()
        box = layout.box()
        box.label(text="Point Lights (Custom Feature)", icon='LIGHT_POINT')
        
        # Warning box
        warning_box = box.box()
        warning_box.alert = True
        warning_box.label(text="⚠️ NOT used in official maps!", icon='ERROR')
        warning_box.label(text="For custom/modded maps only")
        
        col = box.column(align=True)
        col.operator("mapgeo.add_point_light", text="Add Point Light to Selected", icon='LIGHT_POINT')
        col.operator("mapgeo.remove_point_light_from_selected", text="Remove from Selected", icon='X')
        col.separator()
        col.operator("mapgeo.export_point_lights", text="Export Lights to JSON", icon='EXPORT')
        
        # Show point light count
        light_count = sum(1 for obj in context.scene.objects if obj.type == 'MESH' and obj.get("point_light_enabled", False))
        if light_count > 0:
            box.label(text=f"Meshes with lights: {light_count}", icon='INFO')
        
        box.label(text="Research: stationary_light field unused", icon='INFO')


class VIEW3D_PT_mapgeo_import_panel(Panel):
    """Import Settings Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Import Settings"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.mapgeo_settings
        
        box = layout.box()
        box.label(text="Import Options", icon='PREFERENCES')
        
        col = box.column(align=True)
        col.prop(settings, "import_materials", text="Materials")
        col.prop(settings, "import_vertex_colors", text="Vertex Colors")
        col.prop(settings, "import_uvs", text="UV Coordinates")
        col.prop(settings, "import_normals", text="Normals")
        col.prop(settings, "import_lightmaps", text="Lightmaps")
        col.prop(settings, "import_bucket_grid", text="Bucket Grid")
        col.prop(settings, "merge_vertices", text="Merge Vertices")
        
        # Materials and Assets
        layout.separator()
        box = layout.box()
        box.label(text="Materials & Textures", icon='MATERIAL')
        
        col = box.column(align=True)
        col.prop(settings, "assets_folder", text="Assets Folder")
        col.prop(settings, "levels_folder", text="Levels Folder")
        col.prop(settings, "materials_json_path", text="Materials (.json/.py)")
        col.prop(settings, "map_py_path", text="Map File (.py/.json)")

        col.separator()
        col.operator("mapgeo.import_materials_file", text="Import Materials File", icon='IMPORT')
        
        # Testing Quick Set Buttons
        col.separator()
        test_box = col.box()
        test_box.label(text="Testing Paths:", icon='EXPERIMENTAL')
        test_col = test_box.column(align=True)
        test_col.operator("mapgeo.set_test_paths", text="Set Test Paths (Map11)", icon='FILEBROWSER')
        
        if settings.assets_folder and settings.materials_json_path:
            box.label(text="✓ Materials enabled", icon='CHECKMARK')
            if settings.map_py_path:
                box.label(text="✓ Map file set (grass tint)", icon='CHECKMARK')
        else:
            box.label(text="Set paths to load materials", icon='INFO')
        
        # Supported formats help
        box.separator()
        box.label(text="Supported:", icon='FILE')
        box.label(text="  .materials.bin.json / .materials.py")
        box.label(text="  map*.py / map*.json (grass tint)")


class VIEW3D_PT_mapgeo_export_panel(Panel):
    """Export Settings Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Export Settings"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.mapgeo_settings
        
        box = layout.box()
        box.label(text="Export Options", icon='PREFERENCES')
        
        col = box.column(align=True)
        col.prop(settings, "export_version", text="Version")
        col.prop(settings, "optimize_meshes", text="Optimize Meshes")
        
        layout.separator()
        
        # Export info
        box = layout.box()
        box.label(text="Format Information", icon='INFO')
        box.label(text=f"Mapgeo Version: {settings.export_version}")
        
        if settings.export_version >= 18:
            box.label(text="• Latest format", icon='CHECKMARK')
        elif settings.export_version >= 17:
            box.label(text="• Current format", icon='CHECKMARK')
        else:
            box.label(text="• Legacy format", icon='ERROR')


class VIEW3D_PT_mapgeo_properties_panel(Panel):
    """Mesh Properties Viewer/Editor Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Mesh Properties"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'
    
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            return
        
        # Baron Hash System (takes priority over layer system)
        has_baron_hash = "baron_hash" in obj and obj["baron_hash"] != "00000000"
        
        if has_baron_hash:
            box = layout.box()
            box.label(text="Baron Visibility Controller", icon='LIGHTPROBE_VOLUME')
            
            row = box.row()
            row.label(text="Hash:", icon='INFO')
            row.label(text=obj["baron_hash"])
            
            # Warning that this overrides layer system
            row = box.row()
            row.label(text="⚠ Overrides Dragon Layer System", icon='ERROR')
            
            # Show parent mode if available
            if "baron_parent_mode" in obj:
                parent_mode = obj["baron_parent_mode"]
                mode_text = "Not Visible" if parent_mode == 3 else "Visible" if parent_mode == 1 else f"Mode {parent_mode}"
                row = box.row()
                row.label(text=f"Parent Mode: {mode_text}")
            
            # Show decoded Baron Layers (Baron pit states)
            if "baron_layers_decoded" in obj:
                info_box = box.box()
                info_box.label(text="Baron Pit Layers:", icon='MESH_CUBE')
                
                # Parse the stored list
                import ast
                try:
                    baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                    layer_names = {1: "Base", 2: "Cup", 4: "Tunnel", 8: "Upgraded"}
                    for layer_bit in baron_layers:
                        row = info_box.row()
                        row.label(text=f"  • {layer_names.get(layer_bit, f'Custom ({layer_bit})')}", icon='CHECKMARK')
                except:
                    pass
            
            # Show decoded Dragon Layers (which dragon layers affect this)
            if "baron_dragon_layers_decoded" in obj:
                info_box = box.box()
                info_box.label(text="Referenced Dragon Layers:", icon='OUTLINER_DATA_MESH')
                
                # Parse the stored list
                import ast
                try:
                    dragon_layers = ast.literal_eval(obj["baron_dragon_layers_decoded"])
                    layer_names = {1: "Base", 2: "Inferno", 4: "Mountain", 8: "Ocean", 
                                   16: "Cloud", 32: "Hextech", 64: "Chemtech", 128: "Void"}
                    for layer_bit in dragon_layers:
                        row = info_box.row()
                        row.label(text=f"  • {layer_names.get(layer_bit, f'Bit {layer_bit}')}", icon='CHECKMARK')
                except:
                    pass
            
            # Info about baron system
            if "baron_layers_decoded" not in obj and "baron_dragon_layers_decoded" not in obj:
                info_box = box.box()
                info_box.label(text="Baron Hash System (4 states):", icon='WORDWRAP_ON')
                info_box.label(text="• Base (default)")
                info_box.label(text="• Cup (bit 1)")
                info_box.label(text="• Tunnel (bit 2)")
                info_box.label(text="• Upgraded (bit 3)")
                info_box.label(text="Load materials.bin.json to decode")
            
            layout.separator()
        
        # Visibility Layers (Dragon/Elemental System)
        if "visibility_layer" in obj:
            box = layout.box()
            
            if has_baron_hash:
                box.label(text="Dragon Layers (Inactive - Baron Hash Active)", icon='RESTRICT_VIEW_OFF')
            else:
                box.label(text="Dragon Layer System", icon='RESTRICT_VIEW_OFF')
            
            visibility = obj["visibility_layer"]
            
            grid = box.grid_flow(columns=4, align=True)
            layer_names = [
                (1, "Base"), (2, "Inferno"), (4, "Mountain"), (8, "Ocean"),
                (16, "Cloud"), (32, "Hextech"), (64, "Chemtech"), (128, "Void")
            ]
            
            for flag, name in layer_names:
                is_visible = bool(visibility & flag)
                icon = 'CHECKMARK' if is_visible else 'BLANK1'
                grid.label(text=f"{name}", icon=icon)
        
        # Quality
        if "quality" in obj:
            box = layout.box()
            box.label(text="Quality", icon='MODIFIER')
            
            quality = obj["quality"]
            
            row = box.row()
            row.label(text=f"Value: {quality} / 255")
        
        # Bush Flag
        if "is_bush" in obj:
            box = layout.box()
            box.label(text="Bush Assignment", icon='OUTLINER_OB_FORCE_FIELD')
            
            row = box.row()
            row.prop(obj, '["is_bush"]', text="Is Bush?", toggle=True)
            
            # Operator to toggle bush
            row = box.row()
            op = row.operator("mapgeo.toggle_bush", text="Toggle Bush Flag")
        
        # Render Flags (read-only display)
        if "render_flags" in obj:
            layout.separator()
            box = layout.box()
            box.label(text="Render Flags", icon='SHADING_RENDERED')
            render_flags = obj["render_flags"]
            row = box.row()
            row.label(text=f"Value: 0x{render_flags:04X}")
        
        # Render Region Hash
        if "render_region_hash" in obj:
            layout.separator()
            box = layout.box()
            box.label(text="Render Region Hash", icon='MESH_GRID')
            row = box.row()
            region_hash = obj["render_region_hash"]
            row.label(text=f"{region_hash}")

        # Material texture overrides
        mat = obj.active_material if obj else None
        if mat:
            layout.separator()
            box = layout.box()
            box.label(text="Material Textures", icon='TEXTURE')
            row = box.row()
            row.label(text=f"Material: {mat.name}")

            current_path = ""
            if "samplers" in mat:
                try:
                    samplers = json.loads(mat["samplers"])
                    sampler = _get_diffuse_sampler_entry(samplers)
                    if sampler:
                        current_path = sampler.get("texturePath", "")
                except Exception:
                    current_path = ""

            if current_path:
                box.label(text=f"Diffuse: {current_path}")
            else:
                box.label(text="Diffuse: (not set)")

            settings = context.scene.mapgeo_settings
            col = box.column(align=True)
            col.prop(settings, "material_diffuse_tex_path", text="Diffuse .tex")
            col.operator("mapgeo.set_diffuse_texture", text="Apply Diffuse", icon='CHECKMARK')



class MAPGEO_OT_initialize_custom_mesh(bpy.types.Operator):
    """Initialize selected custom meshes with mapgeo properties for layer system"""
    bl_idname = "mapgeo.initialize_custom_mesh"
    bl_label = "Initialize for Mapgeo"
    bl_description = "Set up custom meshes with required properties for layer visibility system"
    bl_options = {'REGISTER', 'UNDO'}
    
    visibility_layer: bpy.props.EnumProperty(
        name="Dragon Layer",
        description="Which dragon/elemental variation this mesh should appear on",
        items=[
            ('0', "All Layers (0)", "Visible on all dragon variations"),
            ('1', "Base Only (1)", "Visible only on Base map"),
            ('2', "Inferno Only (2)", "Visible only on Inferno drake"),
            ('4', "Mountain Only (4)", "Visible only on Mountain drake"),
            ('8', "Ocean Only (8)", "Visible only on Ocean drake"),
            ('16', "Cloud Only (16)", "Visible only on Cloud drake"),
            ('32', "Hextech Only (32)", "Visible only on Hextech drake"),
            ('64', "Chemtech Only (64)", "Visible only on Chemtech drake"),
            ('128', "Void Only (128)", "Visible only on Void drake"),
            ('255', "All Layers (255)", "Visible on all dragon variations"),
        ],
        default='255'
    )
    
    quality: bpy.props.EnumProperty(
        name="Quality Levels",
        description="Which quality settings this mesh should appear on (bitmask)",
        items=[
            ('31', "All Levels (31)", "Visible at all quality settings"),
            ('1', "Very Low Only", "Visible only at Very Low quality"),
            ('2', "Low Only", "Visible only at Low quality"),
            ('4', "Medium Only", "Visible only at Medium quality"),
            ('8', "High Only", "Visible only at High quality"),
            ('16', "Very High Only", "Visible only at Very High quality"),
        ],
        default='31'
    )
    
    def execute(self, context):
        count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Initialize essential mapgeo properties
                obj["visibility_layer"] = int(self.visibility_layer)
                obj["quality"] = int(self.quality)
                obj["layer_transition_behavior"] = 0
                obj["render_flags"] = 0
                obj["disable_backface_culling"] = 0
                count += 1
        
        # Trigger visibility update to show/hide based on current filter
        settings = context.scene.mapgeo_settings
        if hasattr(settings, 'dragon_layer_filter'):
            from . import update_environment_visibility
            update_environment_visibility(settings, context)
        
        self.report({'INFO'}, f"Initialized {count} custom meshes for mapgeo layer system")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


# Operators for layer management
class MAPGEO_OT_assign_layer(bpy.types.Operator):
    """Toggle layer assignment for selected objects"""
    bl_idname = "mapgeo.assign_layer"
    bl_label = "Assign to Layer"
    bl_options = {'REGISTER', 'UNDO'}
    
    layer: bpy.props.IntProperty(default=1, min=1, max=8)
    
    def execute(self, context):
        count = 0
        enabled_count = 0
        
        # Calculate layer flag (layers 1-8 map to bits 0-7)
        layer_flag = 1 << (self.layer - 1)
        
        # Layer names for collection lookup
        layer_names = {
            1: "Base", 2: "Inferno", 3: "Mountain", 4: "Ocean",
            5: "Cloud", 6: "Hextech", 7: "Chemtech", 8: "Void"
        }
        target_layer_name = layer_names[self.layer]
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Get current visibility layers
                current_visibility = obj.get("visibility_layer", 0)
                
                # Toggle the layer bit
                new_visibility = current_visibility ^ layer_flag
                obj["visibility_layer"] = new_visibility
                
                # Update collection links
                # Find layer collections by checking all collections
                for coll in bpy.data.collections:
                    # Check if this is a layer collection
                    if coll.name.endswith(f"_{target_layer_name}"):
                        # Check if object should be in this collection
                        if new_visibility & layer_flag:
                            # Add to collection if not already there
                            if obj.name not in coll.objects:
                                coll.objects.link(obj)
                                enabled_count += 1
                        else:
                            # Remove from collection if present
                            if obj.name in coll.objects:
                                coll.objects.unlink(obj)
                
                count += 1
        
        # Trigger visibility update to apply layer filters immediately
        settings = context.scene.mapgeo_settings
        if hasattr(settings, 'dragon_layer_filter'):
            # This will update viewport visibility based on current filters
            from . import update_environment_visibility
            update_environment_visibility(settings, context)
        
        # Report status
        if enabled_count > 0:
            self.report({'INFO'}, f"Added {enabled_count} objects to {target_layer_name} layer (visibility updated)")
        else:
            self.report({'INFO'}, f"Removed {count} objects from {target_layer_name} layer (visibility updated)")
        
        return {'FINISHED'}


class MAPGEO_OT_set_quality(bpy.types.Operator):
    """Set quality level for selected objects"""
    bl_idname = "mapgeo.set_quality"
    bl_label = "Set Quality"
    bl_options = {'REGISTER', 'UNDO'}
    
    quality: bpy.props.IntProperty(
        name="Quality",
        description="Quality level (0-255)",
        default=127,
        min=0,
        max=255
    )
    
    def execute(self, context):
        count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["quality"] = self.quality
                count += 1
        
        self.report({'INFO'}, f"Set quality to {self.quality} for {count} objects")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MAPGEO_OT_toggle_bush(bpy.types.Operator):
    """Toggle bush render flag for selected objects"""
    bl_idname = "mapgeo.toggle_bush"
    bl_label = "Toggle Bush Flag"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        count = 0
        enabled_count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Toggle or initialize bush flag
                current = obj.get("is_bush", False)
                obj["is_bush"] = not current
                if not current:
                    enabled_count += 1
                count += 1
        
        self.report({'INFO'}, f"Toggled bush flag: {enabled_count} enabled, {count-enabled_count} disabled")
        return {'FINISHED'}


class MAPGEO_OT_assign_bush(bpy.types.Operator):
    """Assign bush flag to selected objects"""
    bl_idname = "mapgeo.assign_bush"
    bl_label = "Assign Bush"
    bl_options = {'REGISTER', 'UNDO'}
    
    enable: bpy.props.BoolProperty(default=True)
    
    def execute(self, context):
        count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["is_bush"] = self.enable
                count += 1
        
        status = "enabled" if self.enable else "disabled"
        self.report({'INFO'}, f"Bush flag {status} for {count} objects")
        return {'FINISHED'}


class MAPGEO_OT_assign_baron_hash(bpy.types.Operator):
    """Assign baron hash to selected objects and decode visibility from materials file"""
    bl_idname = "mapgeo.assign_baron_hash"
    bl_label = "Assign Baron Hash"
    bl_options = {'REGISTER', 'UNDO'}
    
    baron_hash: bpy.props.StringProperty(
        name="Baron Hash",
        description="Baron hash in hex format (8 characters, no 0x prefix)",
        default="00000001",
        maxlen=8
    )
    
    def execute(self, context):
        # Validate hex input
        if len(self.baron_hash) != 8:
            self.report({'ERROR'}, "Baron hash must be exactly 8 hex characters")
            return {'CANCELLED'}
        
        try:
            int(self.baron_hash, 16)
        except ValueError:
            self.report({'ERROR'}, "Invalid hex format. Use characters 0-9 and A-F only")
            return {'CANCELLED'}
        
        hash_upper = self.baron_hash.upper()
        
        # Try to decode baron hash from materials file
        settings = context.scene.mapgeo_settings
        materials_path = settings.materials_json_path if hasattr(settings, 'materials_json_path') else ""
        
        baron_parser = None
        controller = None
        if materials_path and os.path.exists(materials_path):
            try:
                from . import baron_hash_parser
                baron_parser = baron_hash_parser.MaterialsBinParser(materials_path)
                controller = baron_parser.decode_baron_hash(hash_upper)
            except Exception as e:
                self.report({'WARNING'}, f"Could not decode baron hash from materials file: {e}")
        
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["baron_hash"] = hash_upper
                
                if controller:
                    # Store decoded baron layers
                    if controller.baron_layers:
                        baron_layers_list = sorted(list(controller.baron_layers))
                        obj["baron_layers_decoded"] = str(baron_layers_list)
                    else:
                        obj["baron_layers_decoded"] = "[]"
                    
                    # Store decoded dragon layers
                    if controller.dragon_layers:
                        dragon_layers_list = sorted(list(controller.dragon_layers))
                        obj["baron_dragon_layers_decoded"] = str(dragon_layers_list)
                    else:
                        obj["baron_dragon_layers_decoded"] = "[]"
                    
                    # Store parent mode
                    obj["baron_parent_mode"] = controller.parent_mode
                
                count += 1
        
        # Trigger visibility update
        if hasattr(settings, 'dragon_layer_filter'):
            from . import update_environment_visibility
            update_environment_visibility(settings, context)
        
        if controller:
            self.report({'INFO'}, f"Assigned baron hash {hash_upper} to {count} objects (decoded from materials file)")
        elif not materials_path:
            self.report({'WARNING'}, f"Assigned baron hash {hash_upper} to {count} objects — set Materials path in Import Settings to decode visibility")
        else:
            self.report({'WARNING'}, f"Assigned baron hash {hash_upper} to {count} objects — could not decode, visibility may not update correctly")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MAPGEO_OT_assign_render_region_hash(bpy.types.Operator):
    """Assign render region hash to selected objects"""
    bl_idname = "mapgeo.assign_render_region_hash"
    bl_label = "Assign Render Region Hash"
    bl_options = {'REGISTER', 'UNDO'}
    
    render_region_hash: bpy.props.StringProperty(
        name="Render Region Hash",
        description="Render region hash in hex format (8 characters, no 0x prefix)",
        default="00000001",
        maxlen=8
    )
    
    def execute(self, context):
        # Validate hex input
        if len(self.render_region_hash) != 8:
            self.report({'ERROR'}, "Render region hash must be exactly 8 hex characters")
            return {'CANCELLED'}
        
        try:
            int(self.render_region_hash, 16)
        except ValueError:
            self.report({'ERROR'}, "Invalid hex format. Use characters 0-9 and A-F only")
            return {'CANCELLED'}
        
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["render_region_hash"] = self.render_region_hash.upper()
                count += 1
        
        self.report({'INFO'}, f"Assigned render region hash {self.render_region_hash.upper()} to {count} objects")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MAPGEO_OT_set_diffuse_texture(bpy.types.Operator):
    """Update diffuse texture in the selected object's material"""
    bl_idname = "mapgeo.set_diffuse_texture"
    bl_label = "Set Diffuse Texture"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.mapgeo_settings
        tex_path = settings.material_diffuse_tex_path
        
        if not tex_path:
            self.report({'ERROR'}, "No texture path specified")
            return {'CANCELLED'}
        
        # Get active object and material
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}
        
        mat = obj.active_material
        if not mat:
            self.report({'ERROR'}, "Active object has no active material")
            return {'CANCELLED'}
        
        # Update sampler JSON
        if "samplers" in mat:
            try:
                samplers = json.loads(mat["samplers"])
                sampler = _get_diffuse_sampler_entry(samplers)
                
                if not sampler:
                    # Create new sampler entry
                    sampler = {
                        "textureName": "DiffuseTexture",
                        "texturePath": tex_path if tex_path.lower().endswith(('.tex', '.dds', '.png')) else tex_path + '.tex',
                        "addressU": 0,
                        "addressV": 0,
                        "addressW": 0
                    }
                    samplers.append(sampler)
                else:
                    # Update existing sampler
                    sampler["texturePath"] = tex_path if tex_path.lower().endswith(('.tex', '.dds', '.png')) else tex_path + '.tex'
                
                mat["samplers"] = json.dumps(samplers)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to update sampler: {str(e)}")
                return {'CANCELLED'}
        else:
            self.report({'WARNING'}, "Material has no samplers data")
        
        # Update material node
        if _update_material_diffuse_node(mat, tex_path, settings.assets_folder):
            self.report({'INFO'}, "Diffuse texture updated successfully")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Diffuse texture updated in data but failed to load image node")
            return {'FINISHED'}


class MAPGEO_OT_set_test_paths(bpy.types.Operator):
    """Set test paths for Map11 materials and assets (for testing only)"""
    bl_idname = "mapgeo.set_test_paths"
    bl_label = "Set Test Paths"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.mapgeo_settings
        
        # Set testing paths
        # Note: If using Map11LEVELS.wad (separate file), adjust paths accordingly
        # Levels folder should point to where grass tint textures live (will search recursively)
        settings.assets_folder = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\assets"
        settings.levels_folder = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\levels"
        settings.materials_json_path = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\data\maps\mapgeometry\map11\base_srx.materials.bin.json"
        settings.map_py_path = ""
        
        self.report({'INFO'}, "Test paths set for Map11")
        return {'FINISHED'}


class MAPGEO_OT_show_all(bpy.types.Operator):
    """Make all mesh objects visible (ignoring layer filters)"""
    bl_idname = "mapgeo.show_all"
    bl_label = "Show All"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        count = 0
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                obj.hide_viewport = False
                obj.hide_render = False
                try:
                    obj.hide_set(False)
                except:
                    pass
                count += 1
        
        self.report({'INFO'}, f"Showing all {count} mesh objects")
        return {'FINISHED'}


class MAPGEO_OT_toggle_bucket_grid_selectable(bpy.types.Operator):
    """Toggle whether bucket grid objects are selectable"""
    bl_idname = "mapgeo.toggle_bucket_grid_selectable"
    bl_label = "Toggle Bucket Grid Selectable"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        count = 0
        any_locked = False
        for obj in context.scene.objects:
            if obj.get("is_bucket_grid") or obj.get("is_bucket_grid_bounds"):
                if obj.hide_select:
                    any_locked = True
                count += 1
        
        # Toggle: if any are locked, unlock all; otherwise lock all
        new_state = any_locked  # True = make selectable (hide_select=False), opposite
        for obj in context.scene.objects:
            if obj.get("is_bucket_grid") or obj.get("is_bucket_grid_bounds"):
                obj.hide_select = not new_state
        
        status = "selectable" if new_state else "locked"
        self.report({'INFO'}, f"Bucket grid objects now {status} ({count} objects)")
        return {'FINISHED'}


class MAPGEO_OT_create_bucket_grid(bpy.types.Operator):
    """Create a custom bucket grid from the current mesh objects in the scene"""
    bl_idname = "mapgeo.create_bucket_grid"
    bl_label = "Create Custom Bucket Grid"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Constants for bucket grid generation
    TARGET_GRID_SIZE = 32  # Target ~32x32 grids like riot does
    MAX_GRID_SIZE = 64  # Absolute maximum grid size to prevent freezing
    MIN_BUCKET_SIZE = 100.0  # Minimum bucket size
    MAX_BUCKET_SIZE = 1000.0  # Maximum bucket size
    
    bucket_size: bpy.props.FloatProperty(
        name="Bucket Size",
        description="Size of each bucket cell in world units",
        default=500.0,
        min=MIN_BUCKET_SIZE,
        max=MAX_BUCKET_SIZE
    )
    
    height: bpy.props.FloatProperty(
        name="Height",
        description="Height (Z coordinate) for the flat bounding box plane",
        default=0.0
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "bucket_size")
        layout.prop(self, "height")
    
    def execute(self, context):
        import mathutils
        import bmesh
        from collections import defaultdict
        
        # Keywords to ignore when creating bucket grids
        ignore_keywords = ['sun', 'fog', 'render', 'region', 'bush']
        
        # Collect mesh objects grouped by visibility_layer
        objects_by_layer = defaultdict(list)
        
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            if obj.get("is_bucket_grid") or obj.get("is_bucket_grid_bounds"):
                continue
                
            # Skip objects in bucket grid collections
            in_bucket_collection = False
            for col in obj.users_collection:
                if col.get("is_bucket_grid_collection"):
                    in_bucket_collection = True
                    break
            if in_bucket_collection:
                continue
            
            # Skip bushes and render region meshes (by custom properties)
            if obj.get("is_bush", False):
                continue
            if obj.get("render_region_hash"):
                continue
            
            # Skip objects with ignored keywords in name (fallback)
            obj_name_lower = obj.name.lower()
            should_ignore = any(keyword in obj_name_lower for keyword in ignore_keywords)
            if should_ignore:
                continue
            
            # Group by visibility_layer
            visibility_layer = obj.get("visibility_layer", 0)
            objects_by_layer[visibility_layer].append(obj)
        
        if not objects_by_layer:
            self.report({'WARNING'}, "No valid mesh objects found to create bucket grid from")
            return {'CANCELLED'}
        
        # Find parent collection for bucket grids
        parent_collection = context.scene.collection
        for col in bpy.data.collections:
            if "_Meshes" in col.name:
                # Find the parent of the _Meshes collection
                for parent_col in bpy.data.collections:
                    if col.name in [c.name for c in parent_col.children]:
                        parent_collection = parent_col
                        break
                break
        
        # Remove existing custom bucket grid collections
        to_remove = []
        for col in bpy.data.collections:
            if col.get("is_bucket_grid_collection") and col.get("is_custom_bucket_grid"):
                to_remove.append(col)
        
        for col in to_remove:
            for obj in list(col.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(col)
        
        # Process each visibility layer separately
        total_grids_created = 0
        
        for visibility_layer in sorted(objects_by_layer.keys()):
            mesh_objects = objects_by_layer[visibility_layer]
            
            # Calculate scene bounds from layer's mesh objects
            all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
            all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
            
            for obj in mesh_objects:
                # Use world-space bounding box
                for corner in obj.bound_box:
                    world_co = obj.matrix_world @ mathutils.Vector(corner)
                    all_min.x = min(all_min.x, world_co.x)
                    all_min.y = min(all_min.y, world_co.y)
                    all_min.z = min(all_min.z, world_co.z)
                    all_max.x = max(all_max.x, world_co.x)
                    all_max.y = max(all_max.y, world_co.y)
                    all_max.z = max(all_max.z, world_co.z)
            
            # Bucket grid uses X/Y plane in Blender (mapgeo X/Z horizontal → Blender X/Y horizontal)
            # Blender: X/Y is horizontal ground plane, Z is up
            bucket_size = self.bucket_size
            
            # Calculate grid dimensions (using X and Y for horizontal plane)
            # Expand bounds slightly to ensure all geometry is contained
            min_x = all_min.x - 1.0
            min_y = all_min.y - 1.0
            max_x = all_max.x + 1.0
            max_y = all_max.y + 1.0
            
            range_x = max_x - min_x
            range_y = max_y - min_y
            
            # Calculate buckets_per_side based on the larger dimension (square grid)
            max_range = max(range_x, range_y)
            buckets_per_side = max(1, int((max_range / bucket_size) + 0.5))
            
            # Cap at maximum grid size to prevent freezing
            if buckets_per_side > self.MAX_GRID_SIZE:
                buckets_per_side = self.MAX_GRID_SIZE
                bucket_size = max_range / buckets_per_side
            
            # Collect all triangles in world space from mesh objects
            all_triangles = []  # List of (v0, v1, v2, source_obj)
            
            for obj in mesh_objects:
                # Get mesh in world space
                depsgraph = context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.to_mesh()
                
                if not mesh.polygons:
                    eval_obj.to_mesh_clear()
                    continue
                
                mesh.calc_loop_triangles()
                
                # Transform to world space
                matrix = obj.matrix_world
                for tri in mesh.loop_triangles:
                    v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                    v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                    v2 = matrix @ mesh.vertices[tri.vertices[2]].co
                    all_triangles.append((v0.copy(), v1.copy(), v2.copy(), obj))
                
                eval_obj.to_mesh_clear()
            
            if not all_triangles:
                continue  # Skip this layer if no triangles
            
            # Build 2D bucket grid structure
            # Each bucket stores: list of triangle indices that touch it
            bucket_triangles = [[[] for _ in range(buckets_per_side)] for _ in range(buckets_per_side)]
            
            # Determine which bucket each triangle belongs to
            for tri_idx, (v0, v1, v2, obj) in enumerate(all_triangles):
                # Find bounding box of triangle in X/Y plane (Blender horizontal)
                tri_min_x = min(v0.x, v1.x, v2.x)
                tri_max_x = max(v0.x, v1.x, v2.x)
                tri_min_y = min(v0.y, v1.y, v2.y)
                tri_max_y = max(v0.y, v1.y, v2.y)
                
                # Convert to bucket indices
                bucket_min_x = max(0, int((tri_min_x - min_x) / bucket_size))
                bucket_max_x = min(buckets_per_side - 1, int((tri_max_x - min_x) / bucket_size))
                bucket_min_y = max(0, int((tri_min_y - min_y) / bucket_size))
                bucket_max_y = min(buckets_per_side - 1, int((tri_max_y - min_y) / bucket_size))
                
                # Determine if triangle is fully inside one bucket or sticks out
                # For simplicity: if it touches only one bucket, it's inside; otherwise it's sticking out
                touches_single_bucket = (bucket_min_x == bucket_max_x and bucket_min_y == bucket_max_y)
                
                # Add triangle to all buckets it touches
                for by in range(bucket_min_y, bucket_max_y + 1):
                    for bx in range(bucket_min_x, bucket_max_x + 1):
                        bucket_triangles[by][bx].append((tri_idx, touches_single_bucket))
            
            # Build unified vertex and index buffers with base_vertex offsets
            all_vertices = []  # Global vertex buffer
            all_indices = []   # Global index buffer
            bucket_data = [[None for _ in range(buckets_per_side)] for _ in range(buckets_per_side)]
            
            for bz in range(buckets_per_side):
                for bx in range(buckets_per_side):
                    tri_list = bucket_triangles[bz][bx]
                    if not tri_list:
                        # Empty bucket
                        bucket_data[bz][bx] = {
                            'base_vertex': 0,
                            'start_index': len(all_indices),
                            'inside_face_count': 0,
                            'sticking_out_face_count': 0
                        }
                        continue
                
                # Build local vertex list for this bucket (deduplication)
                    local_verts = []
                    vertex_map = {}  # maps (tri_idx, vert_idx_in_tri) -> local_vert_idx
                    local_indices = []
                    inside_count = 0
                    sticking_out_count = 0
                    
                    for tri_idx, is_inside in tri_list:
                        v0, v1, v2, obj = all_triangles[tri_idx]
                        
                        # Add vertices (with deduplication)
                        def get_or_add_vertex(v, key):
                            if key not in vertex_map:
                                vertex_map[key] = len(local_verts)
                                local_verts.append(v)
                            return vertex_map[key]
                        
                        idx0 = get_or_add_vertex(v0, (tri_idx, 0))
                        idx1 = get_or_add_vertex(v1, (tri_idx, 1))
                        idx2 = get_or_add_vertex(v2, (tri_idx, 2))
                        
                        # Add face (note: Blender uses CCW, but we'll reverse on import)
                        local_indices.extend([idx0, idx1, idx2])
                        
                        if is_inside:
                            inside_count += 1
                        else:
                            sticking_out_count += 1
                    
                    # Store bucket data
                    base_vertex = len(all_vertices)
                    start_index = len(all_indices)
                    
                    bucket_data[bz][bx] = {
                        'base_vertex': base_vertex,
                        'start_index': start_index,
                        'inside_face_count': inside_count,
                        'sticking_out_face_count': sticking_out_count
                    }
                    
                    # Append to global buffers
                    all_vertices.extend(local_verts)
                    all_indices.extend(local_indices)
            
            # Create bucket grid mesh (unified mesh with all geometry)
            layer_suffix = f"_L{visibility_layer}" if visibility_layer != 0 else ""
            grid_mesh = bpy.data.meshes.new(f"CustomBucketGrid{layer_suffix}_Mesh")
            
            # Build faces from indices with base_vertex offsets
            faces = []
            for bz in range(buckets_per_side):
                for bx in range(buckets_per_side):
                    bucket = bucket_data[bz][bx]
                    face_count = bucket['inside_face_count'] + bucket['sticking_out_face_count']
                    start_idx = bucket['start_index']
                    base_vertex = bucket['base_vertex']
                    
                    for i in range(face_count):
                        idx_pos = start_idx + (i * 3)
                        v0 = all_indices[idx_pos] + base_vertex
                        v1 = all_indices[idx_pos + 1] + base_vertex
                        v2 = all_indices[idx_pos + 2] + base_vertex
                        faces.append((v0, v1, v2))
            
            # Convert vertices to tuples
            verts = [(v.x, v.y, v.z) for v in all_vertices]
            
            grid_mesh.from_pydata(verts, [], faces)
            grid_mesh.update()
            
            # Create new bucket grid collection
            bg_col_name = f"Custom_BucketGrid{layer_suffix}"
            bg_collection = bpy.data.collections.new(bg_col_name)
            parent_collection.children.link(bg_collection)
            bg_collection["is_bucket_grid_collection"] = True
            bg_collection["is_custom_bucket_grid"] = True
            bg_collection["bucket_grid_count"] = 1
            bg_collection["visibility_layer"] = visibility_layer
            
            # Create bucket grid object
            grid_obj = bpy.data.objects.new(f"CustomBucketGrid{layer_suffix}_Mesh", grid_mesh)
            bg_collection.objects.link(grid_obj)
            
            # Apply crimson red material (matching imported bucket grids)
            mat_name = f"BucketGrid_CustomMaterial{layer_suffix}"
            if mat_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[mat_name])
            
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            mat.blend_method = 'BLEND'
            mat.show_transparent_back = False
            
            nodes = mat.node_tree.nodes
            nodes.clear()
            
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            bsdf.inputs['Base Color'].default_value = (0.935752, 0.055, 0.0, 1.0)  # Vermillion
            bsdf.inputs['Alpha'].default_value = 0.04
            
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (200, 0)
            
            mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            
            grid_mesh.materials.append(mat)
            
            # Store metadata on object
            grid_obj["is_bucket_grid"] = True
            grid_obj["is_custom_bucket_grid"] = True
            grid_obj["visibility_layer"] = visibility_layer
            grid_obj["bounds_min_x"] = min_x
            grid_obj["bounds_min_y"] = min_y
            grid_obj["bounds_max_x"] = max_x
            grid_obj["bounds_max_y"] = max_y
            grid_obj["bucket_size_x"] = bucket_size
            grid_obj["bucket_size_z"] = bucket_size
            grid_obj["buckets_per_side"] = buckets_per_side
            grid_obj["bounds_height"] = self.height
            
            # Store bucket data as JSON for export
            bucket_data_json = []
            for bz in range(buckets_per_side):
                row = []
                for bx in range(buckets_per_side):
                    bucket = bucket_data[bz][bx]
                    row.append({
                        'base_vertex': bucket['base_vertex'],
                        'start_index': bucket['start_index'],
                        'inside_face_count': bucket['inside_face_count'],
                        'sticking_out_face_count': bucket['sticking_out_face_count']
                    })
                bucket_data_json.append(row)
            
            import json
            grid_obj["bucket_data"] = json.dumps(bucket_data_json)
            grid_obj["vertex_count"] = len(all_vertices)
            grid_obj["index_count"] = len(all_indices)
            
            # Create bounding box visual (flat on X/Y plane at specified Z height)
            bbox_mesh = bpy.data.meshes.new(f"CustomBucketGrid{layer_suffix}_Bounds")
            z_height = self.height
            
            # Single horizontal rectangle on X/Y plane at specified Z height
            bbox_verts = [
                (min_x, min_y, z_height),
                (max_x, min_y, z_height),
                (max_x, max_y, z_height),
                (min_x, max_y, z_height),
            ]
            bbox_edges = [
                (0, 1), (1, 2), (2, 3), (3, 0),
            ]
            bbox_mesh.from_pydata(bbox_verts, bbox_edges, [])
            bbox_mesh.update()
            
            bbox_obj = bpy.data.objects.new(f"CustomBucketGrid{layer_suffix}_Bounds", bbox_mesh)
            bg_collection.objects.link(bbox_obj)
            
            # Apply vermillion material to bounding box
            bbox_mat_name = f"BucketGrid_CustomBounds{layer_suffix}"
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
            bbox_bsdf.inputs['Alpha'].default_value = 0.04
            
            bbox_output = bbox_nodes.new(type='ShaderNodeOutputMaterial')
            bbox_output.location = (200, 0)
            
            bbox_mat.node_tree.links.new(bbox_bsdf.outputs['BSDF'], bbox_output.inputs['Surface'])
            
            bbox_mesh.materials.append(bbox_mat)
            bbox_obj.hide_select = True
            bbox_obj["is_bucket_grid_bounds"] = True
            bbox_obj["is_custom_bucket_grid"] = True
            bbox_obj["visibility_layer"] = visibility_layer
            
            # Count populated buckets for this layer
            populated_buckets = sum(1 for row in bucket_data for bucket in row if bucket['inside_face_count'] + bucket['sticking_out_face_count'] > 0)
            
            total_grids_created += 1
        
        # Show the bucket grid collections
        settings = context.scene.mapgeo_settings
        settings.show_bucket_grid = True
        
        self.report({'INFO'}, 
            f"Created {total_grids_created} custom bucket grid(s) for layers: "
            f"{', '.join(str(layer) for layer in sorted(objects_by_layer.keys()))}")
        return {'FINISHED'}


class MAPGEO_OT_show_not_used(bpy.types.Operator):
    """Show only objects not assigned to any visibility layer (visibility_layer == 0 and no baron hash)"""
    bl_idname = "mapgeo.show_not_used"
    bl_label = "Show Not Used"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        used_count = 0
        unused_count = 0
        
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                visibility_layer = obj.get("visibility_layer", 0)
                has_baron_hash = ("baron_hash" in obj and obj["baron_hash"] != "00000000")
                
                # Object is "used" if it has a visibility layer or a baron hash
                is_used = (visibility_layer != 0) or has_baron_hash
                
                if is_used:
                    obj.hide_viewport = True
                    obj.hide_render = True
                    used_count += 1
                else:
                    obj.hide_viewport = False
                    obj.hide_render = False
                    try:
                        obj.hide_set(False)
                    except:
                        pass
                    unused_count += 1
        
        self.report({'INFO'}, f"Showing {unused_count} unused objects ({used_count} hidden)")
        return {'FINISHED'}


class MAPGEO_OT_add_point_light(bpy.types.Operator):
    """Add a Blender Point Light linked to selected mesh (Custom feature - not used in official maps)"""
    bl_idname = "mapgeo.add_point_light"
    bl_label = "Add Point Light"
    bl_description = "Add a point light to selected mesh (Custom/Modded feature only)"
    bl_options = {'REGISTER', 'UNDO'}
    
    light_color: bpy.props.FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        default=(1.0, 0.95, 0.8),
        min=0.0,
        max=1.0,
        description="Light color"
    )
    
    light_intensity: bpy.props.FloatProperty(
        name="Intensity",
        default=500.0,
        min=0.0,
        description="Light intensity (power in Watts for Blender)"
    )
    
    light_radius: bpy.props.FloatProperty(
        name="Radius",
        default=5.0,
        min=0.0,
        description="Light influence radius"
    )
    
    offset_z: bpy.props.FloatProperty(
        name="Z Offset",
        default=2.0,
        description="Z offset from mesh origin"
    )
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)
    
    def execute(self, context):
        created_lights = 0
        
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            
            # Create light data
            light_data = bpy.data.lights.new(name=f"{obj.name}_PointLight", type='POINT')
            light_data.energy = self.light_intensity
            light_data.color = self.light_color
            light_data.shadow_soft_size = self.light_radius
            
            # Create light object
            light_obj = bpy.data.objects.new(name=f"{obj.name}_PointLight", object_data=light_data)
            light_obj.location = obj.location.copy()
            light_obj.location.z += self.offset_z
            
            # Link to same collection as mesh
            for collection in obj.users_collection:
                collection.objects.link(light_obj)
            
            # Parent to mesh
            light_obj.parent = obj
            
            # Store light properties on mesh
            obj["point_light_enabled"] = True
            obj["point_light_color"] = list(self.light_color)
            obj["point_light_intensity"] = self.light_intensity
            obj["point_light_radius"] = self.light_radius
            obj["point_light_offset_z"] = self.offset_z
            
            created_lights += 1
        
        if created_lights > 0:
            self.report({'INFO'}, f"Created {created_lights} point light(s)")
        else:
            self.report({'WARNING'}, "No mesh objects selected")
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MAPGEO_OT_remove_point_light_from_selected(bpy.types.Operator):
    """Remove point lights from selected meshes"""
    bl_idname = "mapgeo.remove_point_light_from_selected"
    bl_label = "Remove Point Lights"
    bl_description = "Remove point lights from selected meshes"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(
            obj.type == 'MESH' and obj.get("point_light_enabled", False) 
            for obj in context.selected_objects
        )
    
    def execute(self, context):
        removed_lights = 0
        removed_objects = 0
        
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            
            if not obj.get("point_light_enabled", False):
                continue
            
            # Find and remove child light objects
            for child in obj.children[:]:  # Copy list to avoid modification during iteration
                if child.type == 'LIGHT':
                    bpy.data.objects.remove(child, do_unlink=True)
                    removed_objects += 1
            
            # Remove properties
            for key in ["point_light_enabled", "point_light_color", "point_light_intensity", 
                       "point_light_radius", "point_light_offset_z"]:
                if key in obj:
                    del obj[key]
            
            removed_lights += 1
        
        if removed_lights > 0:
            self.report({'INFO'}, f"Removed point light data from {removed_lights} mesh(es), deleted {removed_objects} light object(s)")
        else:
            self.report({'WARNING'}, "No meshes with point lights selected")
        
        return {'FINISHED'}


class MAPGEO_OT_export_point_lights(bpy.types.Operator):
    """Export point lights to JSON file (for custom/modded maps)"""
    bl_idname = "mapgeo.export_point_lights"
    bl_label = "Export Point Lights to JSON"
    bl_description = "Export point light data to companion JSON file"
    bl_options = {'REGISTER'}
    
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    
    def execute(self, context):
        import json
        
        lights_data = []
        
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            
            if not obj.get("point_light_enabled", False):
                continue
            
            light_data = {
                "mesh_name": obj.name,
                "type": "point",
                "position": list(obj.location),
                "color": obj.get("point_light_color", [1.0, 1.0, 1.0]),
                "intensity": obj.get("point_light_intensity", 500.0),
                "radius": obj.get("point_light_radius", 5.0),
                "offset_z": obj.get("point_light_offset_z", 0.0)
            }
            lights_data.append(light_data)
        
        if not lights_data:
            self.report({'WARNING'}, "No point lights to export")
            return {'CANCELLED'}
        
        # Write JSON
        output = {
            "version": 1,
            "note": "Custom point light data - not used in official League maps",
            "lights": lights_data
        }
        
        with open(self.filepath, 'w') as f:
            json.dump(output, f, indent=2)
        
        self.report({'INFO'}, f"Exported {len(lights_data)} point light(s) to {self.filepath}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# Register classes
classes = (
    VIEW3D_PT_mapgeo_panel,
    VIEW3D_PT_mapgeo_layers_panel,
    VIEW3D_PT_mapgeo_import_panel,
    VIEW3D_PT_mapgeo_export_panel,
    VIEW3D_PT_mapgeo_properties_panel,
    MAPGEO_OT_setup_mesh,
    MAPGEO_OT_initialize_custom_mesh,
    MAPGEO_OT_assign_layer,
    MAPGEO_OT_set_quality,
    MAPGEO_OT_toggle_bush,
    MAPGEO_OT_assign_bush,
    MAPGEO_OT_assign_baron_hash,
    MAPGEO_OT_assign_render_region_hash,
    MAPGEO_OT_set_diffuse_texture,
    MAPGEO_OT_set_test_paths,
    MAPGEO_OT_show_all,
    MAPGEO_OT_show_not_used,
    MAPGEO_OT_toggle_bucket_grid_selectable,
    MAPGEO_OT_create_bucket_grid,
    MAPGEO_OT_add_point_light,
    MAPGEO_OT_remove_point_light_from_selected,
    MAPGEO_OT_export_point_lights,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
