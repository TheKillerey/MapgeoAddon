"""
League of Legends Mapgeo Addon for Blender 5.0
Author: TheKillerey
Description: A comprehensive tool to import, edit, and export League of Legends .mapgeo files
"""

bl_info = {
    "name": "League of Legends Mapgeo Tools",
    "author": "TheKillerey",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "File > Import-Export, View3D > Sidebar > LoL Mapgeo",
    "description": "Import, edit and export League of Legends .mapgeo files (Riot's map format)",
    "warning": "",
    "doc_url": "https://github.com/LeagueToolkit/LeagueToolkit",
    "category": "Import-Export",
}

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
    FloatProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup

# Import addon modules
from . import (
    mapgeo_parser,
    import_mapgeo,
    export_mapgeo,
    ui_panel,
    utils,
)

# Callback function for environment visibility
def update_environment_visibility(self, context):
    """Update object visibility based on selected environment layer"""
    selected_layer = self.environment_visibility
    
    # Map enum values to layer flags
    layer_flags = {
        'ALL': 0xFF,  # All layers (255)
        'LAYER_1': 1 << 0,  # 0b00000001
        'LAYER_2': 1 << 1,  # 0b00000010
        'LAYER_3': 1 << 2,  # 0b00000100
        'LAYER_4': 1 << 3,  # 0b00001000
        'LAYER_5': 1 << 4,  # 0b00010000
        'LAYER_6': 1 << 5,  # 0b00100000
        'LAYER_7': 1 << 6,  # 0b01000000
        'LAYER_8': 1 << 7,  # 0b10000000
    }
    
    selected_flag = layer_flags.get(selected_layer, 0xFF)
    
    # Track how many objects were shown/hidden
    visible_count = 0
    hidden_count = 0
    
    # Update visibility for all mesh objects with mapgeo_visibility property
    for obj in context.scene.objects:
        if obj.type == 'MESH' and "mapgeo_visibility" in obj:
            obj_visibility = obj.get("mapgeo_visibility", 255)
            
            # Check if the object's visibility includes the selected layer
            # For 'ALL', show everything
            # For specific layer, show if that layer bit is set in the object's visibility
            if selected_layer == 'ALL':
                should_be_visible = True
            else:
                # Check if the selected layer bit is set in the object's visibility flags
                should_be_visible = bool(obj_visibility & selected_flag)
            
            # Update viewport and render visibility
            obj.hide_viewport = not should_be_visible
            obj.hide_render = not should_be_visible
            
            if should_be_visible:
                visible_count += 1
            else:
                hidden_count += 1
    
    # Print feedback
    if selected_layer == 'ALL':
        print(f"Showing all layers: {visible_count} meshes visible")
    else:
        layer_names = {
            'LAYER_1': 'Base',
            'LAYER_2': 'Inferno',
            'LAYER_3': 'Mountain',
            'LAYER_4': 'Ocean',
            'LAYER_5': 'Cloud',
            'LAYER_6': 'Hextech',
            'LAYER_7': 'Chemtech',
            'LAYER_8': 'Unused'
        }
        layer_name = layer_names.get(selected_layer, selected_layer)
        print(f"Showing {layer_name} layer: {visible_count} meshes visible, {hidden_count} meshes hidden")

# Property Groups for storing mapgeo data
class MapgeoLayerItem(PropertyGroup):
    """Represents a layer in the mapgeo file"""
    name: StringProperty(name="Layer Name", default="Layer")
    visibility: BoolProperty(name="Visible", default=True)
    quality: EnumProperty(
        name="Quality",
        items=[
            ('VERY_LOW', "Very Low", "Very Low Quality"),
            ('LOW', "Low", "Low Quality"),
            ('MEDIUM', "Medium", "Medium Quality"),
            ('HIGH', "High", "High Quality"),
            ('VERY_HIGH', "Very High", "Very High Quality"),
        ],
        default='MEDIUM'
    )

class MapgeoSettings(PropertyGroup):
    """Main settings for mapgeo addon"""
    
    # Import Settings
    import_materials: BoolProperty(
        name="Import Materials",
        description="Import materials from mapgeo",
        default=True
    )
    
    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        description="Import vertex color data",
        default=True
    )
    
    import_uvs: BoolProperty(
        name="Import UVs",
        description="Import UV coordinates",
        default=True
    )
    
    import_normals: BoolProperty(
        name="Import Normals",
        description="Import vertex normals",
        default=True
    )
    
    merge_vertices: BoolProperty(
        name="Merge Vertices",
        description="Merge duplicate vertices",
        default=True
    )
    
    # Export Settings
    export_version: IntProperty(
        name="Mapgeo Version",
        description="Version of mapgeo format to export",
        default=17,
        min=13,
        max=18
    )
    
    optimize_meshes: BoolProperty(
        name="Optimize Meshes",
        description="Optimize mesh data during export",
        default=True
    )
    
    # Layer Management
    layers: CollectionProperty(type=MapgeoLayerItem)
    active_layer_index: IntProperty(default=0)
    
    # File paths
    last_import_path: StringProperty(
        name="Last Import Path",
        description="Last imported mapgeo file path",
        default="",
        subtype='FILE_PATH'
    )
    
    last_export_path: StringProperty(
        name="Last Export Path",
        description="Last exported mapgeo file path",
        default="",
        subtype='FILE_PATH'
    )
    
    # Assets and Materials
    assets_folder: StringProperty(
        name="Assets Folder",
        description="Path to the ASSETS folder containing textures",
        default="",
        subtype='DIR_PATH'
    )
    
    materials_json_path: StringProperty(
        name="Materials JSON Path",
        description="Path to the .materials.bin.json file",
        default="",
        subtype='FILE_PATH'
    )
    
    # Visibility flags
    environment_visibility: EnumProperty(
        name="Environment Visibility",
        description="Filter meshes by visibility layer",
        items=[
            ('ALL', "All Layers", "Show all layers (all meshes visible)"),
            ('LAYER_1', "Layer 1 - Base", "Show Base layer"),
            ('LAYER_2', "Layer 2 - Inferno", "Show Inferno layer"),
            ('LAYER_3', "Layer 3 - Mountain", "Show Mountain layer"),
            ('LAYER_4', "Layer 4 - Ocean", "Show Ocean layer"),
            ('LAYER_5', "Layer 5 - Cloud", "Show Cloud layer"),
            ('LAYER_6', "Layer 6 - Hextech", "Show Hextech layer"),
            ('LAYER_7', "Layer 7 - Chemtech", "Show Chemtech layer"),
            ('LAYER_8', "Layer 8 - Unused", "Show Unused layer"),
        ],
        default='ALL',
        update=update_environment_visibility
    )

# Classes to register
classes = (
    MapgeoLayerItem,
    MapgeoSettings,
    import_mapgeo.IMPORT_SCENE_OT_mapgeo,
    export_mapgeo.EXPORT_SCENE_OT_mapgeo,
    ui_panel.MAPGEO_OT_assign_layer,
    ui_panel.MAPGEO_OT_set_quality,
    ui_panel.VIEW3D_PT_mapgeo_panel,
    ui_panel.VIEW3D_PT_mapgeo_layers_panel,
    ui_panel.VIEW3D_PT_mapgeo_import_panel,
    ui_panel.VIEW3D_PT_mapgeo_export_panel,
)

def menu_func_import(self, context):
    self.layout.operator(import_mapgeo.IMPORT_SCENE_OT_mapgeo.bl_idname, 
                        text="League of Legends Mapgeo (.mapgeo)")

def menu_func_export(self, context):
    self.layout.operator(export_mapgeo.EXPORT_SCENE_OT_mapgeo.bl_idname,
                        text="League of Legends Mapgeo (.mapgeo)")

def register():
    """Register all addon classes and handlers"""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Register properties
    bpy.types.Scene.mapgeo_settings = bpy.props.PointerProperty(type=MapgeoSettings)
    
    # Add menu entries
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    
    print("League of Legends Mapgeo Tools registered successfully")

def unregister():
    """Unregister all addon classes and handlers"""
    # Remove menu entries
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    
    # Unregister properties
    del bpy.types.Scene.mapgeo_settings
    
    # Unregister classes (in reverse order)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print("League of Legends Mapgeo Tools unregistered")

if __name__ == "__main__":
    register()
