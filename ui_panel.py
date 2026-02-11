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
        
        # Environment visibility
        box = layout.box()
        box.label(text="Environment Visibility", icon='RESTRICT_VIEW_OFF')
        box.prop(settings, "environment_visibility", text="")
        
        # Layer operations
        layout.separator()
        box = layout.box()
        box.label(text="Layer Operations", icon='OUTLINER_DATA_MESH')
        
        col = box.column(align=True)
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 1").layer = 1
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 2").layer = 2
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 3").layer = 3
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 4").layer = 4
        
        col = box.column(align=True)
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 5").layer = 5
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 6").layer = 6
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 7").layer = 7
        col.operator("mapgeo.assign_layer", text="Assign Selected to Layer 8").layer = 8
        
        layout.separator()
        
        # Quality settings
        box = layout.box()
        box.label(text="Quality Settings", icon='MODIFIER')
        
        col = box.column(align=True)
        col.operator("mapgeo.set_quality", text="Very Low").quality = 0
        col.operator("mapgeo.set_quality", text="Low").quality = 1
        col.operator("mapgeo.set_quality", text="Medium").quality = 2
        col.operator("mapgeo.set_quality", text="High").quality = 3
        col.operator("mapgeo.set_quality", text="Very High").quality = 4


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
        
        # Visibility Layers
        if "mapgeo_visibility" in obj:
            box = layout.box()
            box.label(text="Visibility Layers", icon='RESTRICT_VIEW_OFF')
            
            visibility = obj["mapgeo_visibility"]
            
            grid = box.grid_flow(columns=4, align=True)
            layer_names = [
                (1, "Base"), (2, "Inferno"), (4, "Mountain"), (8, "Ocean"),
                (16, "Cloud"), (32, "Hextech"), (64, "Chemtech"), (128, "Unused")
            ]
            
            for flag, name in layer_names:
                is_visible = bool(visibility & flag)
                icon = 'CHECKMARK' if is_visible else 'BLANK1'
                grid.label(text=f"{name}", icon=icon)
        
        # Quality
        if "mapgeo_quality" in obj:
            box = layout.box()
            box.label(text="Quality Level", icon='MODIFIER')
            
            quality = obj["mapgeo_quality"]
            quality_names = ["Very Low", "Low", "Medium", "High", "Very High"]
            quality_name = quality_names[quality] if 0 <= quality < len(quality_names) else "Unknown"
            
            row = box.row()
            row.label(text=quality_name)
        
        # Bush Flag
        if "mapgeo_is_bush" in obj:
            box = layout.box()
            box.label(text="Render Flags", icon='SHADING_RENDERED')
            
            row = box.row()
            row.prop(obj, '["mapgeo_is_bush"]', text="Is Bush", toggle=True)
            
            # Operator to toggle bush
            row = box.row()
            op = row.operator("mapgeo.toggle_bush", text="Toggle Bush Flag")
        
        # Render Flags (read-only display)
        if "mapgeo_render_flags" in obj:
            render_flags = obj["mapgeo_render_flags"]
            row = box.row()
            row.label(text=f"Flags: 0x{render_flags:04X}")


# Operators for layer management
class MAPGEO_OT_assign_layer(bpy.types.Operator):
    """Assign selected objects to a visibility layer"""
    bl_idname = "mapgeo.assign_layer"
    bl_label = "Assign to Layer"
    bl_options = {'REGISTER', 'UNDO'}
    
    layer: bpy.props.IntProperty(default=1, min=1, max=8)
    
    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Set visibility flag (layers are 1-8, flags are bit 0-7)
                visibility = 1 << (self.layer - 1)  # LAYER_1 = bit 0, LAYER_2 = bit 1, etc.
                obj["mapgeo_visibility"] = visibility
                count += 1
        
        self.report({'INFO'}, f"Assigned {count} objects to layer {self.layer}")
        return {'FINISHED'}


class MAPGEO_OT_set_quality(bpy.types.Operator):
    """Set quality level for selected objects"""
    bl_idname = "mapgeo.set_quality"
    bl_label = "Set Quality"
    bl_options = {'REGISTER', 'UNDO'}
    
    quality: bpy.props.IntProperty(default=2, min=0, max=4)
    
    def execute(self, context):
        quality_names = ["Very Low", "Low", "Medium", "High", "Very High"]
        count = 0
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                obj["mapgeo_quality"] = self.quality
                count += 1
        
        self.report({'INFO'}, f"Set quality to {quality_names[self.quality]} for {count} objects")
        return {'FINISHED'}


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
                current = obj.get("mapgeo_is_bush", False)
                obj["mapgeo_is_bush"] = not current
                if not current:
                    enabled_count += 1
                count += 1
        
        self.report({'INFO'}, f"Toggled bush flag: {enabled_count} enabled, {count-enabled_count} disabled")
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
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
