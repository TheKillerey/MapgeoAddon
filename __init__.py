"""
League of Legends Mapgeo Addon for Blender 5.0
Author: TheKillerey
Description: A comprehensive tool to import, edit, and export League of Legends .mapgeo files
"""

bl_info = {
    "name": "Rey's Mapgeo Blender Addon",
    "author": "TheKillerey",
    "version": (0, 1, 1),
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
    """Update object visibility based on selected dragon and baron layer filters (League engine logic)"""
    dragon_filter = self.dragon_layer_filter
    baron_filter = self.baron_layer_filter
    
    # Map dragon layer enum values to layer flags
    dragon_layer_flags = {
        'LAYER_1': 1 << 0,  # Base
        'LAYER_2': 1 << 1,  # Inferno
        'LAYER_3': 1 << 2,  # Mountain
        'LAYER_4': 1 << 3,  # Ocean
        'LAYER_5': 1 << 4,  # Cloud
        'LAYER_6': 1 << 5,  # Hextech
        'LAYER_7': 1 << 6,  # Chemtech
        'LAYER_8': 1 << 7,  # Void
    }
    
    # Map baron layer enum values to bit values (not indices)
    # These bit values match the 0x8bff8cdf property in materials.bin
    baron_layer_bits = {
        'BARON_BASE': 1,    # Bit 0
        'BARON_CUP': 2,     # Bit 1
        'BARON_TUNNEL': 4,  # Bit 2
        'BARON_UPGRADED': 8  # Bit 3
    }
    
    # Get current filter values
    current_dragon_flag = dragon_layer_flags.get(dragon_filter, 1)  # Default to Base if not found
    current_baron_bit = baron_layer_bits.get(baron_filter, 1)  # Default to Base if not found
    
    # Track how many objects were shown/hidden
    visible_count = 0
    hidden_count = 0
    
    # Update visibility for all mesh objects (League engine logic)
    for obj in context.scene.objects:
        if obj.type == 'MESH':
            should_be_visible = False
            
            has_baron_hash = "baron_hash" in obj and obj["baron_hash"] != "00000000"
            visibility_layer = obj.get("visibility_layer", 0)
            
            # STEP 1: Check dragon layer visibility
            dragon_visible = False
            
            # Baron hash OVERRIDES dragon layer system when it has dragon_layers
            if has_baron_hash and "baron_dragon_layers_decoded" in obj:
                # Use dragon layers from baron hash (OVERRIDE mode)
                # ParentMode applies here too (mode 3 = NOT visible on listed layers)
                try:
                    import ast
                    dragon_layers = ast.literal_eval(obj["baron_dragon_layers_decoded"])
                    parent_mode = obj.get("baron_parent_mode", 1)
                    
                    if len(dragon_layers) > 0:
                        # Check if current dragon flag is in baron's dragon layers
                        is_in_list = (1 in dragon_layers) or (current_dragon_flag in dragon_layers)
                        
                        if parent_mode == 3:
                            dragon_visible = not is_in_list  # NOT visible on listed layers
                        else:
                            dragon_visible = is_in_list  # Visible on listed layers
                    else:
                        # Empty dragon layers - not visible on any dragon variation
                        dragon_visible = False
                except:
                    # Parse error - fallback to visibility_layer
                    if visibility_layer == 0 or visibility_layer == 255:
                        dragon_visible = True
                    elif visibility_layer & 1:
                        dragon_visible = True
                    elif visibility_layer & current_dragon_flag:
                        dragon_visible = True
            else:
                # No baron hash or no dragon layers in baron hash - use visibility_layer
                if visibility_layer == 0 or visibility_layer == 255:
                    # 0 = no dragon layer restriction (always visible)
                    # 255 = AllLayers (always visible)
                    dragon_visible = True
                elif visibility_layer & 1:
                    # Base layer (bit 0) - always visible on all dragon maps (foundation)
                    dragon_visible = True
                elif visibility_layer & current_dragon_flag:
                    # Current dragon layer flag is set - visible on this dragon variation
                    dragon_visible = True
            
            # STEP 2: Check baron pit state
            baron_visible = True  # Default: visible on all baron states
            
            if has_baron_hash and "baron_layers_decoded" in obj:
                # baron_layers_decoded contains bit values (1, 2, 4, 8, etc.)
                try:
                    import ast
                    baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                    parent_mode = obj.get("baron_parent_mode", 1)  # Default to Visible mode
                    
                    # Check if current baron bit is in the list
                    is_in_list = (current_baron_bit in baron_layers)
                    
                    # Apply ParentMode logic:
                    # Mode 1 (Visible): visible if current state IS in the list
                    # Mode 3 (Not Visible): visible if current state is NOT in the list
                    if parent_mode == 3:
                        baron_visible = not is_in_list  # Inverted: visible when NOT in list
                    else:
                        baron_visible = is_in_list  # Normal: visible when in list
                except:
                    baron_visible = True  # Parse error - default to visible
            
            # Final visibility: must pass BOTH dragon check AND baron check
            should_be_visible = dragon_visible and baron_visible
            
            # Update viewport and render visibility
            obj.hide_viewport = not should_be_visible
            obj.hide_render = not should_be_visible
            
            if should_be_visible:
                visible_count += 1
            else:
                hidden_count += 1
    
    # Print feedback
    dragon_name = {
        'LAYER_1': 'Base',
        'LAYER_2': 'Inferno',
        'LAYER_3': 'Mountain',
        'LAYER_4': 'Ocean',
        'LAYER_5': 'Cloud',
        'LAYER_6': 'Hextech',
        'LAYER_7': 'Chemtech',
        'LAYER_8': 'Void',
    }.get(dragon_filter, 'Base')
    
    baron_name = {
        'BARON_BASE': 'Base',
        'BARON_CUP': 'Cup',
        'BARON_TUNNEL': 'Tunnel',
        'BARON_UPGRADED': 'Upgraded'
    }.get(baron_filter, 'Base')
    
    print(f"Showing - Dragon: {dragon_name}, Baron: {baron_name} | {visible_count} visible, {hidden_count} hidden")

    # Update grass tint textures for the new dragon layer
    try:
        from . import material_loader as mat_loader
        mat_loader.MaterialLoader.update_grass_tint_for_dragon(self)
    except Exception as e:
        print(f"[GrassTint] Could not update grass tint on layer switch: {e}")


def update_render_region_visibility(self, context):
    """Toggle visibility of render region objects"""
    show_regions = self.show_render_regions
    
    # Show or hide all objects with render_region_hash
    count = 0
    for obj in context.scene.objects:
        if obj.type == 'MESH' and "render_region_hash" in obj:
            obj.hide_set(not show_regions)
            obj.hide_viewport = not show_regions
            obj.hide_render = not show_regions
            count += 1
    
    status = "shown" if show_regions else "hidden"
    print(f"Render regions {status} ({count} objects)")


def update_bucket_grid_visibility(self, context):
    """Toggle visibility of bucket grid collections in the viewport"""
    show_grids = self.show_bucket_grid
    view_layer = context.view_layer
    
    def find_layer_collections(layer_col, results=None):
        if results is None:
            results = []
        col = layer_col.collection
        if col.get("is_bucket_grid_collection"):
            results.append(layer_col)
        for child in layer_col.children:
            find_layer_collections(child, results)
        return results
    
    bg_layer_cols = find_layer_collections(view_layer.layer_collection)
    
    for lc in bg_layer_cols:
        lc.hide_viewport = not show_grids
    
    status = "shown" if show_grids else "hidden"
    print(f"Bucket grids {status} ({len(bg_layer_cols)} collections)")

# Property Groups for storing mapgeo data
class MapgeoLayerItem(PropertyGroup):
    """Represents a layer in the mapgeo file"""
    name: StringProperty(name="Layer Name", default="Layer")
    visibility: BoolProperty(name="Visible", default=True)
    quality: IntProperty(
        name="Quality",
        description="Quality level (0-255)",
        default=127,
        min=0,
        max=255
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
    
    import_lightmaps: BoolProperty(
        name="Import Lightmaps",
        description="Load baked lightmap textures and multiply with diffuse for Riot-accurate lighting",
        default=True
    )
    
    import_bucket_grid: BoolProperty(
        name="Import Bucket Grid",
        description="Import bucket grid scene graph data for spatial partitioning visualization",
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
        default=18,
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
    
    levels_folder: StringProperty(
        name="Levels Folder",
        description="Path to the LEVELS folder (e.g. levels/map11/info/) for grass tint and other map-level textures",
        default="",
        subtype='DIR_PATH'
    )
    
    materials_json_path: StringProperty(
        name="Materials File Path",
        description="Path to the .materials.bin.json or .materials.py file",
        default="",
        subtype='FILE_PATH'
    )
    
    map_py_path: StringProperty(
        name="Map File Path",
        description="Path to the map*.py or map*.json file containing MapSkin definitions for grass tint textures",
        default="",
        subtype='FILE_PATH'
    )
    
    # Visibility filters (League engine style)
    dragon_layer_filter: EnumProperty(
        name="Dragon Layer",
        description="Current dragon/elemental variation",
        items=[
            ('LAYER_1', "Base", "Base map (default)"),
            ('LAYER_2', "Inferno", "Inferno drake variation"),
            ('LAYER_3', "Mountain", "Mountain drake variation"),
            ('LAYER_4', "Ocean", "Ocean drake variation"),
            ('LAYER_5', "Cloud", "Cloud drake variation"),
            ('LAYER_6', "Hextech", "Hextech drake variation"),
            ('LAYER_7', "Chemtech", "Chemtech drake variation"),
            ('LAYER_8', "Void", "Void drake variation"),
        ],
        default='LAYER_1',
        update=update_environment_visibility
    )
    
    baron_layer_filter: EnumProperty(
        name="Baron Layer",
        description="Current baron pit state",
        items=[
            ('BARON_BASE', "Base", "Default baron pit"),
            ('BARON_CUP', "Cup", "Baron Cup variation"),
            ('BARON_TUNNEL', "Tunnel", "Baron Tunnel variation"),
            ('BARON_UPGRADED', "Upgraded", "Baron Upgraded variation"),
        ],
        default='BARON_BASE',
        update=update_environment_visibility
    )
    
    # Render region visibility toggle
    show_render_regions: BoolProperty(
        name="Show Render Regions",
        description="Show or hide render region meshes",
        default=True,
        update=update_render_region_visibility
    )
    
    # Bucket grid visibility toggle
    show_bucket_grid: BoolProperty(
        name="Show Bucket Grid",
        description="Show or hide bucket grid visualization meshes",
        default=False,
        update=update_bucket_grid_visibility
    )

# Classes to register
classes = (
    MapgeoLayerItem,
    MapgeoSettings,
    import_mapgeo.IMPORT_SCENE_OT_mapgeo,
    export_mapgeo.EXPORT_SCENE_OT_mapgeo,
    ui_panel.MAPGEO_OT_setup_mesh,
    ui_panel.MAPGEO_OT_initialize_custom_mesh,
    ui_panel.MAPGEO_OT_assign_layer,
    ui_panel.MAPGEO_OT_set_quality,
    ui_panel.MAPGEO_OT_toggle_bush,
    ui_panel.MAPGEO_OT_assign_bush,
    ui_panel.MAPGEO_OT_assign_baron_hash,
    ui_panel.MAPGEO_OT_assign_render_region_hash,
    ui_panel.MAPGEO_OT_set_test_paths,
    ui_panel.MAPGEO_OT_show_all,
    ui_panel.MAPGEO_OT_show_not_used,
    ui_panel.MAPGEO_OT_toggle_bucket_grid_selectable,
    ui_panel.MAPGEO_OT_create_bucket_grid,
    ui_panel.VIEW3D_PT_mapgeo_panel,
    ui_panel.VIEW3D_PT_mapgeo_layers_panel,
    ui_panel.VIEW3D_PT_mapgeo_import_panel,
    ui_panel.VIEW3D_PT_mapgeo_export_panel,
    ui_panel.VIEW3D_PT_mapgeo_properties_panel,
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
    
    print("Rey's Mapgeo Blender Addon registered successfully")

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
    
    print("Rey's Mapgeo Blender Addon unregistered")

if __name__ == "__main__":
    register()
