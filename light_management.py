"""
Light Management System for MapgeoAddon
Provides UI and operators for managing lights in League maps
"""

import bpy
import json
from pathlib import Path
from bpy.types import Operator, Panel, UIList
from bpy.props import (
    FloatProperty, FloatVectorProperty, StringProperty,
    EnumProperty, BoolProperty, IntProperty
)


# ============================================================================
# Light Creation Operators
# ============================================================================

class MAPGEO_OT_create_light(Operator):
    """Create a new light in the scene"""
    bl_idname = "mapgeo.create_light"
    bl_label = "Create Light"
    bl_description = "Create a new light object"
    bl_options = {'REGISTER', 'UNDO'}
    
    light_type: EnumProperty(
        name="Light Type",
        items=[
            ('POINT', "Point Light", "Omnidirectional point light"),
            ('SPOT', "Spot Light", "Directional cone light"),
            ('SUN', "Sun Light", "Distant directional light"),
            ('AREA', "Area Light", "Area light source"),
        ],
        default='POINT'
    )
    
    light_name: StringProperty(
        name="Name",
        default="Light",
        description="Name for the light object"
    )
    
    power: FloatProperty(
        name="Power",
        default=100.0,
        min=0.0,
        description="Light power in Watts"
    )
    
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        description="Light color"
    )
    
    radius: FloatProperty(
        name="Radius",
        default=5.0,
        min=0.0,
        description="Light influence radius (Point/Spot only)"
    )
    
    spot_size: FloatProperty(
        name="Spot Size",
        default=0.785398,  # 45 degrees
        min=0.0174533,     # 1 degree
        max=3.14159,       # 180 degrees
        subtype='ANGLE',
        description="Cone angle (Spot only)"
    )
    
    spot_blend: FloatProperty(
        name="Spot Blend",
        default=0.15,
        min=0.0,
        max=1.0,
        description="Soft edge blend (Spot only)"
    )
    
    use_custom_distance: BoolProperty(
        name="Custom Distance",
        default=False,
        description="Use custom distance cutoff"
    )
    
    cutoff_distance: FloatProperty(
        name="Cutoff Distance",
        default=40.0,
        min=0.0,
        description="Light cutoff distance"
    )
    
    def execute(self, context):
        # Create light data
        light_data = bpy.data.lights.new(name=self.light_name, type=self.light_type)
        light_data.energy = self.power
        light_data.color = self.color
        
        # Type-specific properties
        if self.light_type in {'POINT', 'SPOT'}:
            light_data.shadow_soft_size = self.radius
        
        if self.light_type == 'SPOT':
            light_data.spot_size = self.spot_size
            light_data.spot_blend = self.spot_blend
        
        if self.use_custom_distance:
            light_data.use_custom_distance = True
            light_data.cutoff_distance = self.cutoff_distance
        
        # Create light object
        light_obj = bpy.data.objects.new(name=self.light_name, object_data=light_data)
        
        # Place at 3D cursor
        light_obj.location = context.scene.cursor.location.copy()
        
        # Link to active collection
        context.collection.objects.link(light_obj)
        
        # Select the new light
        bpy.ops.object.select_all(action='DESELECT')
        light_obj.select_set(True)
        context.view_layer.objects.active = light_obj
        
        # Store metadata
        light_obj["mapgeo_light"] = True
        light_obj["light_category"] = "custom"
        
        self.report({'INFO'}, f"Created {self.light_type} light: {self.light_name}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        
        layout.prop(self, "light_type")
        layout.prop(self, "light_name")
        
        layout.separator()
        layout.label(text="Light Properties:")
        layout.prop(self, "power")
        layout.prop(self, "color")
        
        if self.light_type in {'POINT', 'SPOT'}:
            layout.prop(self, "radius")
        
        if self.light_type == 'SPOT':
            layout.separator()
            layout.label(text="Spot Settings:")
            layout.prop(self, "spot_size")
            layout.prop(self, "spot_blend")
        
        layout.separator()
        layout.prop(self, "use_custom_distance")
        if self.use_custom_distance:
            layout.prop(self, "cutoff_distance")


class MAPGEO_OT_duplicate_light(Operator):
    """Duplicate selected lights"""
    bl_idname = "mapgeo.duplicate_light"
    bl_label = "Duplicate Light"
    bl_description = "Duplicate selected light objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'LIGHT' for obj in context.selected_objects)
    
    def execute(self, context):
        duplicated = 0
        
        for obj in context.selected_objects:
            if obj.type != 'LIGHT':
                continue
            
            # Duplicate object and data
            new_obj = obj.copy()
            new_obj.data = obj.data.copy()
            new_obj.location = obj.location + bpy.context.scene.cursor.location * 0.1
            
            context.collection.objects.link(new_obj)
            duplicated += 1
        
        self.report({'INFO'}, f"Duplicated {duplicated} light(s)")
        return {'FINISHED'}


class MAPGEO_OT_delete_light(Operator):
    """Delete selected lights"""
    bl_idname = "mapgeo.delete_light"
    bl_label = "Delete Light"
    bl_description = "Delete selected light objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'LIGHT' for obj in context.selected_objects)
    
    def execute(self, context):
        deleted = 0
        
        for obj in list(context.selected_objects):
            if obj.type != 'LIGHT':
                continue
            
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted += 1
        
        self.report({'INFO'}, f"Deleted {deleted} light(s)")
        return {'FINISHED'}


class MAPGEO_OT_select_lights_by_type(Operator):
    """Select all lights of a specific type"""
    bl_idname = "mapgeo.select_lights_by_type"
    bl_label = "Select Lights by Type"
    bl_description = "Select all lights of a specific type"
    bl_options = {'REGISTER', 'UNDO'}
    
    light_type: EnumProperty(
        name="Light Type",
        items=[
            ('POINT', "Point", ""),
            ('SPOT', "Spot", ""),
            ('SUN', "Sun", ""),
            ('AREA', "Area", ""),
            ('ALL', "All", ""),
        ],
        default='ALL'
    )
    
    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        
        selected = 0
        for obj in context.scene.objects:
            if obj.type != 'LIGHT':
                continue
            
            if self.light_type == 'ALL' or obj.data.type == self.light_type:
                obj.select_set(True)
                selected += 1
        
        self.report({'INFO'}, f"Selected {selected} light(s)")
        return {'FINISHED'}


class MAPGEO_OT_toggle_light_visibility(Operator):
    """Toggle visibility of all lights"""
    bl_idname = "mapgeo.toggle_light_visibility"
    bl_label = "Toggle Light Visibility"
    bl_description = "Show/hide all light objects in viewport"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        lights = [obj for obj in context.scene.objects if obj.type == 'LIGHT']
        
        if not lights:
            self.report({'INFO'}, "No lights in scene")
            return {'CANCELLED'}
        
        # Determine current state (if any visible, hide all; otherwise show all)
        any_visible = any(not obj.hide_viewport for obj in lights)
        
        for obj in lights:
            obj.hide_viewport = any_visible
            obj.hide_render = any_visible
        
        state = "hidden" if any_visible else "visible"
        self.report({'INFO'}, f"All lights are now {state}")
        return {'FINISHED'}


class MAPGEO_OT_export_lights_json(Operator):
    """Export all lights to JSON"""
    bl_idname = "mapgeo.export_lights_json"
    bl_label = "Export Lights to JSON"
    bl_description = "Export all scene lights to JSON file"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    
    def execute(self, context):
        lights_data = []
        
        for obj in context.scene.objects:
            if obj.type != 'LIGHT':
                continue
            
            light_data = {
                "name": obj.name,
                "type": obj.data.type,
                "location": list(obj.location),
                "rotation": list(obj.rotation_euler),
                "power": obj.data.energy,
                "color": list(obj.data.color),
            }
            
            # Type-specific properties
            if obj.data.type in {'POINT', 'SPOT'}:
                light_data["radius"] = obj.data.shadow_soft_size
            
            if obj.data.type == 'SPOT':
                light_data["spot_size"] = obj.data.spot_size
                light_data["spot_blend"] = obj.data.spot_blend
            
            if obj.data.use_custom_distance:
                light_data["cutoff_distance"] = obj.data.cutoff_distance
            
            # Custom properties
            if "mapgeo_light" in obj:
                light_data["mapgeo_light"] = obj["mapgeo_light"]
            if "light_category" in obj:
                light_data["light_category"] = obj["light_category"]
            
            lights_data.append(light_data)
        
        if not lights_data:
            self.report({'WARNING'}, "No lights to export")
            return {'CANCELLED'}
        
        output = {
            "version": 1,
            "note": "MapgeoAddon light export",
            "lights": lights_data
        }
        
        with open(self.filepath, 'w') as f:
            json.dump(output, f, indent=2)
        
        self.report({'INFO'}, f"Exported {len(lights_data)} light(s) to {Path(self.filepath).name}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        self.filepath = "lights.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MAPGEO_OT_import_lights_json(Operator):
    """Import lights from JSON"""
    bl_idname = "mapgeo.import_lights_json"
    bl_label = "Import Lights from JSON"
    bl_description = "Import lights from JSON file"
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    
    def execute(self, context):
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read file: {e}")
            return {'CANCELLED'}
        
        if "lights" not in data:
            self.report({'ERROR'}, "Invalid lights JSON format")
            return {'CANCELLED'}
        
        imported = 0
        
        for light_info in data["lights"]:
            try:
                light_type = light_info.get("type", "POINT")
                light_name = light_info.get("name", "ImportedLight")
                
                # Create light data
                light_data = bpy.data.lights.new(name=light_name, type=light_type)
                light_data.energy = light_info.get("power", 100.0)
                light_data.color = light_info.get("color", [1.0, 1.0, 1.0])
                
                # Type-specific
                if light_type in {'POINT', 'SPOT'} and "radius" in light_info:
                    light_data.shadow_soft_size = light_info["radius"]
                
                if light_type == 'SPOT':
                    if "spot_size" in light_info:
                        light_data.spot_size = light_info["spot_size"]
                    if "spot_blend" in light_info:
                        light_data.spot_blend = light_info["spot_blend"]
                
                if "cutoff_distance" in light_info:
                    light_data.use_custom_distance = True
                    light_data.cutoff_distance = light_info["cutoff_distance"]
                
                # Create object
                light_obj = bpy.data.objects.new(name=light_name, object_data=light_data)
                light_obj.location = light_info.get("location", [0, 0, 0])
                light_obj.rotation_euler = light_info.get("rotation", [0, 0, 0])
                
                context.collection.objects.link(light_obj)
                
                # Custom properties
                if "mapgeo_light" in light_info:
                    light_obj["mapgeo_light"] = light_info["mapgeo_light"]
                if "light_category" in light_info:
                    light_obj["light_category"] = light_info["light_category"]
                
                imported += 1
            except Exception as e:
                print(f"Failed to import light {light_info.get('name', 'unknown')}: {e}")
        
        self.report({'INFO'}, f"Imported {imported} light(s)")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================================
# UI List for Lights
# ============================================================================

class MAPGEO_UL_lights_list(UIList):
    """UIList for displaying lights in the scene"""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.type != 'LIGHT':
            return
        
        # Light type icon
        light_icons = {
            'POINT': 'LIGHT_POINT',
            'SPOT': 'LIGHT_SPOT',
            'SUN': 'LIGHT_SUN',
            'AREA': 'LIGHT_AREA',
        }
        icon = light_icons.get(item.data.type, 'LIGHT')
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "name", text="", emboss=False, icon=icon)
            
            # Show power value
            row.label(text=f"{item.data.energy:.0f}W")
            
            # Visibility toggle
            row.prop(item, "hide_viewport", text="", emboss=False)
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop(item, "name", text="", emboss=False, icon=icon)


# ============================================================================
# Light Management Panel
# ============================================================================

class VIEW3D_PT_mapgeo_lights_panel(Panel):
    """Light Management Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Light Manager"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Stats
        lights = [obj for obj in scene.objects if obj.type == 'LIGHT']
        light_counts = {
            'POINT': sum(1 for obj in lights if obj.data.type == 'POINT'),
            'SPOT': sum(1 for obj in lights if obj.data.type == 'SPOT'),
            'SUN': sum(1 for obj in lights if obj.data.type == 'SUN'),
            'AREA': sum(1 for obj in lights if obj.data.type == 'AREA'),
        }
        
        # Summary box
        box = layout.box()
        box.label(text=f"Total Lights: {len(lights)}", icon='LIGHT')
        if len(lights) > 0:
            grid = box.grid_flow(columns=2, align=True)
            if light_counts['POINT'] > 0:
                grid.label(text=f"Point: {light_counts['POINT']}", icon='LIGHT_POINT')
            if light_counts['SPOT'] > 0:
                grid.label(text=f"Spot: {light_counts['SPOT']}", icon='LIGHT_SPOT')
            if light_counts['SUN'] > 0:
                grid.label(text=f"Sun: {light_counts['SUN']}", icon='LIGHT_SUN')
            if light_counts['AREA'] > 0:
                grid.label(text=f"Area: {light_counts['AREA']}", icon='LIGHT_AREA')
        
        layout.separator()
        
        # Create light section
        box = layout.box()
        box.label(text="Create New Light", icon='ADD')
        col = box.column(align=True)
        col.operator("mapgeo.create_light", text="Create Light", icon='LIGHT_POINT')
        
        layout.separator()
        
        # Light list
        box = layout.box()
        box.label(text="Scene Lights", icon='OUTLINER_OB_LIGHT')
        
        if lights:
            # Create a temporary collection for the UI list
            row = box.row()
            row.template_list(
                "MAPGEO_UL_lights_list",
                "",
                scene,
                "objects",
                scene,
                "mapgeo_active_light_index",
                rows=5
            )
            
            # Light operations
            col = box.column(align=True)
            col.operator("mapgeo.duplicate_light", text="Duplicate", icon='DUPLICATE')
            col.operator("mapgeo.delete_light", text="Delete", icon='TRASH')
            
            layout.separator()
            
            # Selection tools
            box = layout.box()
            box.label(text="Selection Tools", icon='RESTRICT_SELECT_OFF')
            col = box.column(align=True)
            row = col.row(align=True)
            row.operator("mapgeo.select_lights_by_type", text="Point").light_type = 'POINT'
            row.operator("mapgeo.select_lights_by_type", text="Spot").light_type = 'SPOT'
            row = col.row(align=True)
            row.operator("mapgeo.select_lights_by_type", text="Sun").light_type = 'SUN'
            row.operator("mapgeo.select_lights_by_type", text="Area").light_type = 'AREA'
            col.operator("mapgeo.select_lights_by_type", text="Select All Lights").light_type = 'ALL'
            
            layout.separator()
            
            # Visibility
            box = layout.box()
            box.label(text="Visibility", icon='HIDE_OFF')
            box.operator("mapgeo.toggle_light_visibility", text="Toggle All Lights", icon='RESTRICT_VIEW_OFF')
        else:
            box.label(text="No lights in scene", icon='INFO')
        
        layout.separator()
        
        # Import/Export
        box = layout.box()
        box.label(text="Import/Export", icon='IMPORT')
        col = box.column(align=True)
        col.operator("mapgeo.export_lights_json", text="Export Lights", icon='EXPORT')
        col.operator("mapgeo.import_lights_json", text="Import Lights", icon='IMPORT')
        
        layout.separator()
        
        # Active light properties (if a light is selected)
        if context.active_object and context.active_object.type == 'LIGHT':
            obj = context.active_object
            light = obj.data
            
            box = layout.box()
            box.label(text=f"Active: {obj.name}", icon='LIGHT')
            
            col = box.column(align=True)
            col.prop(light, "type", text="Type")
            col.prop(light, "energy", text="Power")
            col.prop(light, "color", text="")
            
            if light.type in {'POINT', 'SPOT'}:
                col.separator()
                col.prop(light, "shadow_soft_size", text="Radius")
            
            if light.type == 'SPOT':
                col.separator()
                col.prop(light, "spot_size", text="Spot Size")
                col.prop(light, "spot_blend", text="Blend")
            
            col.separator()
            col.prop(light, "use_custom_distance", text="Custom Distance")
            if light.use_custom_distance:
                col.prop(light, "cutoff_distance", text="Cutoff")


# ============================================================================
# Registration
# ============================================================================

classes = (
    MAPGEO_OT_create_light,
    MAPGEO_OT_duplicate_light,
    MAPGEO_OT_delete_light,
    MAPGEO_OT_select_lights_by_type,
    MAPGEO_OT_toggle_light_visibility,
    MAPGEO_OT_export_lights_json,
    MAPGEO_OT_import_lights_json,
    MAPGEO_UL_lights_list,
    VIEW3D_PT_mapgeo_lights_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add index property for UI list
    bpy.types.Scene.mapgeo_active_light_index = IntProperty(
        name="Active Light Index",
        default=0
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    if hasattr(bpy.types.Scene, 'mapgeo_active_light_index'):
        del bpy.types.Scene.mapgeo_active_light_index


if __name__ == "__main__":
    register()
