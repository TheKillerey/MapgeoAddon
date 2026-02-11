"""
UI Panel for Mapgeo Addon
Sidebar panels for layer management and import/export settings
"""

import bpy
from bpy.types import Panel, UIList


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
        
        # Quick Actions
        box = layout.box()
        box.label(text="Quick Actions", icon='IMPORT')
        
        col = box.column(align=True)
        col.operator("import_scene.mapgeo", text="Import Mapgeo", icon='IMPORT')
        col.operator("export_scene.mapgeo", text="Export Mapgeo", icon='EXPORT')
        
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
        info_box = col.box()
        info_box.label(text="ℹ League Engine Logic:", icon='INFO')
        info_box.label(text="• AllLayers (255) always visible")
        info_box.label(text="• Baron Hash uses referenced layers")
        info_box.label(text="• Switch between variations")
        
        # Layer operations
        layout.separator()
        box = layout.box()
        box.label(text="Layer Operations (Toggle)", icon='OUTLINER_DATA_MESH')
        
        col = box.column(align=True)
        col.operator("mapgeo.assign_layer", text="Toggle Layer 1 (Base)").layer = 1
        col.operator("mapgeo.assign_layer", text="Toggle Layer 2 (Inferno)").layer = 2
        col.operator("mapgeo.assign_layer", text="Toggle Layer 3 (Mountain)").layer = 3
        col.operator("mapgeo.assign_layer", text="Toggle Layer 4 (Ocean)").layer = 4
        
        col = box.column(align=True)
        col.operator("mapgeo.assign_layer", text="Toggle Layer 5 (Cloud)").layer = 5
        col.operator("mapgeo.assign_layer", text="Toggle Layer 6 (Hextech)").layer = 6
        col.operator("mapgeo.assign_layer", text="Toggle Layer 7 (Chemtech)").layer = 7
        col.operator("mapgeo.assign_layer", text="Toggle Layer 8 (Void)").layer = 8
        
        layout.separator()
        
        # Quality settings
        box = layout.box()
        box.label(text="Quality Settings (0-255)", icon='MODIFIER')
        
        col = box.column(align=True)
        col.label(text="Common Presets:", icon='PRESET')
        row = col.row(align=True)
        row.operator("mapgeo.set_quality", text="0").quality = 0
        row.operator("mapgeo.set_quality", text="63").quality = 63
        row.operator("mapgeo.set_quality", text="127").quality = 127
        row = col.row(align=True)
        row.operator("mapgeo.set_quality", text="191").quality = 191
        row.operator("mapgeo.set_quality", text="255").quality = 255
        
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
        col.operator("mapgeo.assign_render_region_hash", text="Assign Render Region Hash to Selected", icon='ADD')


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
        col.prop(settings, "merge_vertices", text="Merge Vertices")
        
        # Materials and Assets
        layout.separator()
        box = layout.box()
        box.label(text="Materials & Textures", icon='MATERIAL')
        
        col = box.column(align=True)
        col.prop(settings, "assets_folder", text="Assets Folder")
        col.prop(settings, "materials_json_path", text="Materials JSON")
        
        # Testing Quick Set Buttons
        col.separator()
        test_box = col.box()
        test_box.label(text="Testing Paths:", icon='EXPERIMENTAL')
        test_col = test_box.column(align=True)
        test_col.operator("mapgeo.set_test_paths", text="Set Test Paths (Map11)", icon='FILEBROWSER')
        
        if settings.assets_folder and settings.materials_json_path:
            box.label(text="✓ Materials enabled", icon='CHECKMARK')
        else:
            box.label(text="Set paths to load materials", icon='INFO')


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
                mode_text = "AND (visible on ALL)" if parent_mode == 3 else "OR (visible on ANY)" if parent_mode == 1 else f"Mode {parent_mode}"
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
                    layer_names = {0: "Base", 1: "Cup", 2: "Tunnel", 3: "Upgraded"}
                    for layer_idx in baron_layers:
                        row = info_box.row()
                        row.label(text=f"  • {layer_names.get(layer_idx, f'Unknown ({layer_idx})')}", icon='CHECKMARK')
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
        
        # Report status
        if enabled_count > 0:
            self.report({'INFO'}, f"Added {enabled_count} objects to {target_layer_name} layer")
        else:
            self.report({'INFO'}, f"Removed {count} objects from {target_layer_name} layer")
        
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
    """Assign baron hash to selected objects"""
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
        
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["baron_hash"] = self.baron_hash.upper()
                count += 1
        
        self.report({'INFO'}, f"Assigned baron hash {self.baron_hash.upper()} to {count} objects")
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


class MAPGEO_OT_set_test_paths(bpy.types.Operator):
    """Set test paths for Map11 materials and assets (for testing only)"""
    bl_idname = "mapgeo.set_test_paths"
    bl_label = "Set Test Paths"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.mapgeo_settings
        
        # Set testing paths
        settings.assets_folder = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\assets"
        settings.materials_json_path = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\data\maps\mapgeometry\map11\base_srx.materials.bin.json"
        
        self.report({'INFO'}, "Test paths set for Map11")
        return {'FINISHED'}


# Register classes
classes = (
    VIEW3D_PT_mapgeo_panel,
    VIEW3D_PT_mapgeo_layers_panel,
    VIEW3D_PT_mapgeo_import_panel,
    VIEW3D_PT_mapgeo_export_panel,
    VIEW3D_PT_mapgeo_properties_panel,
    MAPGEO_OT_assign_layer,
    MAPGEO_OT_set_quality,
    MAPGEO_OT_toggle_bush,
    MAPGEO_OT_assign_bush,
    MAPGEO_OT_assign_baron_hash,
    MAPGEO_OT_assign_render_region_hash,
    MAPGEO_OT_set_test_paths,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
