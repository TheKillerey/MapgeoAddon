"""
League Tools - Troybin Particle Editor for Blender
Provides UI for importing, editing, and exporting League of Legends .troybin particle files
"""

import bpy
import os
from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
    FloatProperty,
    CollectionProperty,
    FloatVectorProperty,
)
from bpy.types import PropertyGroup, Panel, Operator, UIList
from pathlib import Path

# Import troybin parser
from . import troybin_parser


# Property Groups for storing troybin data
class TroybinPropertyItem(PropertyGroup):
    """Individual troybin property"""
    prop_hash: StringProperty(name="Hash")  # Store as hex string (0x12345678)
    prop_type: StringProperty(name="Type")
    prop_name: StringProperty(name="Name")
    
    # Value storage (use appropriate field based on type)
    value_int: IntProperty(name="Int Value")
    value_float: FloatProperty(name="Float Value")
    value_bool: BoolProperty(name="Bool Value")
    value_string: StringProperty(name="String Value")
    value_vec2: FloatVectorProperty(name="Vec2", size=2)
    value_vec3: FloatVectorProperty(name="Vec3", size=3)
    value_vec4: FloatVectorProperty(name="Vec4", size=4)
    value_color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0)
    )


class TroybinEmitterItem(PropertyGroup):
    """Particle emitter in troybin file"""
    name: StringProperty(name="Emitter Name", default="emitter")
    emitter_type: StringProperty(name="Type", default="Simple")
    property_count: IntProperty(name="Properties", default=0)


class TroybinSettings(PropertyGroup):
    """Settings for troybin editor"""
    filepath: StringProperty(
        name="File Path",
        description="Path to the troybin file",
        default="",
        subtype='FILE_PATH'
    )
    
    is_loaded: BoolProperty(
        name="File Loaded",
        description="Whether a troybin file is currently loaded",
        default=False
    )
    
    active_emitter_index: IntProperty(
        name="Active Emitter",
        description="Currently selected emitter",
        default=0
    )
    
    emitters: CollectionProperty(
        type=TroybinEmitterItem,
        name="Emitters"
    )
    
    properties: CollectionProperty(
        type=TroybinPropertyItem,
        name="Properties"
    )
    
    # Cached troybin data (stored as JSON string)
    troybin_data_json: StringProperty(
        name="Troybin Data",
        description="Cached troybin data in JSON format",
        default=""
    )
    
    # Display settings
    show_hashes: BoolProperty(
        name="Show Hashes",
        description="Show property hashes alongside names",
        default=False
    )
    
    show_all_properties: BoolProperty(
        name="Show All Properties",
        description="Show all properties (may be slow for large files)",
        default=False
    )
    
    filter_emitter: StringProperty(
        name="Filter by Emitter",
        description="Filter properties by emitter name",
        default=""
    )


# Operators
class TROYBIN_OT_import(Operator):
    """Import a League of Legends .troybin particle file"""
    bl_idname = "troybin.import_file"
    bl_label = "Import Troybin"
    bl_description = "Import a .troybin particle file"
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: StringProperty(
        name="File Path",
        description="Path to the troybin file",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    
    filter_glob: StringProperty(
        default="*.troybin",
        options={'HIDDEN'}
    )
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not self.filepath:
            self.report({'ERROR'}, "No file selected")
            return {'CANCELLED'}
        
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}
        
        try:
            # Parse troybin file
            import json
            data = troybin_parser.parse_troybin(Path(self.filepath))
            
            # Store data as JSON
            settings.troybin_data_json = json.dumps(data, indent=2)
            settings.filepath = self.filepath
            settings.is_loaded = True
            
            # Extract emitters
            settings.emitters.clear()
            emitter_names = troybin_parser.extract_group_names(data)
            
            if not emitter_names:
                emitter_names = ["default"]
            
            for name in emitter_names:
                emitter = settings.emitters.add()
                emitter.name = name
                # Count properties for this emitter (will be updated below)
                emitter.property_count = 0
            
            # Build hash map for unhashing
            hash_map = troybin_parser.build_hash_map(emitter_names)
            
            # Load properties
            settings.properties.clear()
            total_props = 0
            resolved_props = 0
            
            # Track property counts per emitter
            emitter_prop_counts = {name: 0 for name in emitter_names}
            
            for set_type, props in data.get('sets', {}).items():
                for prop_hash, prop_value in props:  # Unpack tuple (hash, value)
                    prop_item = settings.properties.add()
                    prop_item.prop_hash = f"0x{prop_hash:08X}"
                    prop_item.prop_type = set_type
                    
                    # Try to resolve name
                    resolved = hash_map.get(prop_hash, f"0x{prop_hash:08X}")
                    if resolved != f"0x{prop_hash:08X}":
                        resolved_props += 1
                    prop_item.prop_name = resolved
                    
                    # Count property for emitter
                    emitter_name = self._extract_emitter_from_name(resolved, emitter_names)
                    if emitter_name in emitter_prop_counts:
                        emitter_prop_counts[emitter_name] += 1
                    
                    # Store value based on type
                    if prop_value is not None:
                        self._store_value(prop_item, set_type, prop_value)
                    
                    total_props += 1
            
            # Update emitter property counts
            for emitter in settings.emitters:
                emitter.property_count = emitter_prop_counts.get(emitter.name, 0)
            
            self.report({'INFO'}, 
                f"Imported {os.path.basename(self.filepath)}: "
                f"{len(emitter_names)} emitter(s), "
                f"{total_props} properties ({resolved_props} resolved)"
            )
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def _extract_emitter_from_name(self, resolved_name, emitter_names):
        """Extract emitter name from resolved property name"""
        if resolved_name and ']' in resolved_name and resolved_name.startswith('['):
            # Format: [emitter_name] property
            emitter = resolved_name.split(']')[0][1:]
            if emitter in emitter_names:
                return emitter
        
        # For System properties or unresolved, return first emitter or "System"
        if resolved_name and "System" in resolved_name:
            return "System"
        
        return emitter_names[0] if emitter_names else "default"
    
    def _store_value(self, prop_item, set_type, value):
        """Store value in appropriate property field"""
        if set_type in ['Int32List', 'Int16List', 'Int8List']:
            if isinstance(value, list):
                prop_item.value_int = value[0] if value else 0
            else:
                prop_item.value_int = int(value)
        
        elif set_type in ['Float32List', 'FixedPointFloatList']:
            if isinstance(value, list):
                prop_item.value_float = value[0] if value else 0.0
            else:
                prop_item.value_float = float(value)
        
        elif set_type == 'BitList':
            prop_item.value_bool = bool(value)
        
        elif set_type in ['Float32ListVec2', 'FixedPointFloatListVec2']:
            if isinstance(value, list) and len(value) >= 2:
                prop_item.value_vec2 = [float(value[0]), float(value[1])]
            else:
                prop_item.value_vec2 = [0.0, 0.0]
        
        elif set_type in ['Float32ListVec3', 'FixedPointFloatListVec3']:
            if isinstance(value, list) and len(value) >= 3:
                prop_item.value_vec3 = [float(value[0]), float(value[1]), float(value[2])]
            else:
                prop_item.value_vec3 = [0.0, 0.0, 0.0]
        
        elif set_type in ['Float32ListVec4', 'FixedPointFloatListVec4']:
            if isinstance(value, list) and len(value) >= 4:
                prop_item.value_vec4 = [float(value[0]), float(value[1]), float(value[2]), float(value[3])]
                # If looks like color (RGBA), also store in color field
                if all(0 <= v <= 255 for v in value[:4]):
                    prop_item.value_color = [v / 255.0 for v in value[:4]]
                else:
                    prop_item.value_color = [1.0, 1.0, 1.0, 1.0]
            else:
                prop_item.value_vec4 = [0.0, 0.0, 0.0, 0.0]
                prop_item.value_color = [1.0, 1.0, 1.0, 1.0]
        
        elif set_type == 'StringList':
            prop_item.value_string = str(value) if value else ""
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class TROYBIN_OT_export(Operator):
    """Export current troybin data to file"""
    bl_idname = "troybin.export_file"
    bl_label = "Export Troybin"
    bl_description = "Export troybin data to .troybin file"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(
        name="File Path",
        description="Output path for the troybin file",
        maxlen=1024,
        subtype='FILE_PATH'
    )
    
    filter_glob: StringProperty(
        default="*.troybin",
        options={'HIDDEN'}
    )
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not settings.is_loaded:
            self.report({'ERROR'}, "No troybin file loaded")
            return {'CANCELLED'}
        
        if not self.filepath:
            self.report({'ERROR'}, "No output path specified")
            return {'CANCELLED'}
        
        try:
            import json
            
            # Rebuild data from current UI property values
            data = {
                "version": 2,
                "sets": {}
            }
            
            # Group properties by type
            for prop in settings.properties:
                if prop.prop_type not in data['sets']:
                    data['sets'][prop.prop_type] = []
                
                # Convert hash from hex string to int
                prop_hash = int(prop.prop_hash, 16)
                
                # Get value based on type
                value = self._get_property_value(prop)
                
                # Add as tuple (hash, value)
                data['sets'][prop.prop_type].append((prop_hash, value))
            
            # Write to file
            troybin_parser.write_troybin(Path(self.filepath), data)
            
            # Update cached JSON
            settings.troybin_data_json = json.dumps(data, indent=2)
            
            self.report({'INFO'}, f"Exported to {os.path.basename(self.filepath)}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def _get_property_value(self, prop):
        """Extract the appropriate value from a property based on its type"""
        prop_type = prop.prop_type
        
        if prop_type in ['Int32List', 'Int16List', 'Int8List']:
            return prop.value_int
        
        elif prop_type in ['Float32List', 'FixedPointFloatList']:
            return prop.value_float
        
        elif prop_type == 'BitList':
            return prop.value_bool
        
        elif prop_type == 'Float32ListVec2':
            return [float(prop.value_vec2[0]), float(prop.value_vec2[1])]
        
        elif prop_type in ['Float32ListVec3', 'FixedPointFloatListVec3']:
            return [float(prop.value_vec3[0]), float(prop.value_vec3[1]), float(prop.value_vec3[2])]
        
        elif prop_type == 'FixedPointFloatListVec2':
            return [float(prop.value_vec2[0]), float(prop.value_vec2[1])]
        
        elif prop_type in ['Float32ListVec4', 'FixedPointFloatListVec4']:
            # For color properties, convert from 0-1 range back to 0-255
            if 'rgba' in prop.prop_name.lower() or 'color' in prop.prop_name.lower():
                return [float(prop.value_color[0] * 255.0),
                        float(prop.value_color[1] * 255.0),
                        float(prop.value_color[2] * 255.0),
                        float(prop.value_color[3] * 255.0)]
            else:
                return [float(prop.value_vec4[0]), float(prop.value_vec4[1]), 
                        float(prop.value_vec4[2]), float(prop.value_vec4[3])]
        
        elif prop_type == 'StringList':
            return str(prop.value_string) if prop.value_string else ""
        
        else:
            # Unknown type - return a safe default based on common patterns
            print(f"Warning: Unknown property type '{prop_type}' for property '{prop.prop_name}'")
            if 'Vec4' in prop_type:
                return [0.0, 0.0, 0.0, 0.0]
            elif 'Vec3' in prop_type:
                return [0.0, 0.0, 0.0]
            elif 'Vec2' in prop_type:
                return [0.0, 0.0]
            elif 'String' in prop_type:
                return ""
            elif 'Bit' in prop_type:
                return False
            elif 'Float' in prop_type:
                return 0.0
            else:
                return 0
    
    def invoke(self, context, event):
        settings = context.scene.troybin_settings
        
        # Default to current filepath or suggest name
        if settings.filepath:
            self.filepath = settings.filepath
        else:
            self.filepath = "exported_particle.troybin"
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class TROYBIN_OT_reload(Operator):
    """Reload the current troybin file"""
    bl_idname = "troybin.reload_file"
    bl_label = "Reload"
    bl_description = "Reload the current troybin file from disk"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not settings.filepath or not settings.is_loaded:
            self.report({'ERROR'}, "No file loaded")
            return {'CANCELLED'}
        
        # Reimport current file
        bpy.ops.troybin.import_file(filepath=settings.filepath)
        return {'FINISHED'}


class TROYBIN_OT_clear(Operator):
    """Clear loaded troybin data"""
    bl_idname = "troybin.clear_data"
    bl_label = "Clear"
    bl_description = "Clear all loaded troybin data"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        settings.emitters.clear()
        settings.properties.clear()
        settings.troybin_data_json = ""
        settings.filepath = ""
        settings.is_loaded = False
        
        self.report({'INFO'}, "Cleared troybin data")
        return {'FINISHED'}


class TROYBIN_OT_create_new(Operator):
    """Create a new troybin particle from scratch"""
    bl_idname = "troybin.create_new"
    bl_label = "New Particle"
    bl_description = "Create a new empty troybin particle file"
    bl_options = {'REGISTER', 'UNDO'}
    
    emitter_name: StringProperty(
        name="Emitter Name",
        description="Name for the particle emitter",
        default="new_particle"
    )
    
    def execute(self, context):
        import json
        settings = context.scene.troybin_settings
        
        # Create minimal troybin structure using tuples (hash, value)
        data = {
            "version": 2,
            "sets": {
                "StringList": [
                    (troybin_parser.section_field_hash_proper("System", "GroupPart0"), self.emitter_name),
                    (troybin_parser.section_field_hash_proper("System", "GroupPart0Type"), "Simple")
                ],
                "Int16List": [],
                "Int8List": [],
                "BitList": [],
                "Float32ListVec3": [],
                "Float32ListVec4": []
            }
        }
        
        # Store data
        settings.troybin_data_json = json.dumps(data, indent=2)
        settings.filepath = ""
        settings.is_loaded = True
        
        # Add emitter
        settings.emitters.clear()
        emitter = settings.emitters.add()
        emitter.name = self.emitter_name
        emitter.emitter_type = "Simple"
        emitter.property_count = 2
        
        # Load properties
        settings.properties.clear()
        hash_map = troybin_parser.build_hash_map([self.emitter_name])
        for prop_hash, prop_value in data['sets']['StringList']:  # Unpack tuple
            prop_item = settings.properties.add()
            prop_item.prop_hash = f"0x{prop_hash:08X}"
            prop_item.prop_type = 'StringList'
            prop_item.prop_name = hash_map.get(
                prop_hash, f"0x{prop_hash:08X}"
            )
            prop_item.value_string = prop_value
        
        self.report({'INFO'}, f"Created new particle with emitter '{self.emitter_name}'")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class TROYBIN_OT_add_emitter(Operator):
    """Add a new emitter to the particle"""
    bl_idname = "troybin.add_emitter"
    bl_label = "Add Emitter"
    bl_description = "Add a new particle emitter"
    bl_options = {'REGISTER', 'UNDO'}
    
    emitter_name: StringProperty(
        name="Emitter Name",
        description="Name for the new emitter",
        default="new_emitter"
    )
    
    emitter_type: EnumProperty(
        name="Type",
        description="Emitter type",
        items=[
            ('Simple', 'Simple', 'Simple emitter'),
            ('Complex', 'Complex', 'Complex emitter'),
            ('Single', 'Single', 'Single particle'),
        ],
        default='Simple'
    )
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not settings.is_loaded:
            self.report({'ERROR'}, "No particle file loaded")
            return {'CANCELLED'}
        
        # Find next available GroupPart slot
        existing_count = len(settings.emitters)
        if existing_count >= 50:
            self.report({'ERROR'}, "Maximum 50 emitters allowed")
            return {'CANCELLED'}
        
        # Add emitter to list
        emitter = settings.emitters.add()
        emitter.name = self.emitter_name
        emitter.emitter_type = self.emitter_type
        emitter.property_count = 0
        
        # Add System properties for this emitter
        hash_map = troybin_parser.build_hash_map([self.emitter_name])
        
        # GroupPartN property
        prop_item = settings.properties.add()
        group_hash = troybin_parser.section_field_hash_proper("System", f"GroupPart{existing_count}")
        prop_item.prop_hash = f"0x{group_hash:08X}"
        prop_item.prop_type = 'StringList'
        prop_item.prop_name = hash_map.get(group_hash, f"[System] GroupPart{existing_count}")
        prop_item.value_string = self.emitter_name
        
        # GroupPartNType property
        prop_item = settings.properties.add()
        type_hash = troybin_parser.section_field_hash_proper("System", f"GroupPart{existing_count}Type")
        prop_item.prop_hash = f"0x{type_hash:08X}"
        prop_item.prop_type = 'StringList'
        prop_item.prop_name = hash_map.get(type_hash, f"[System] GroupPart{existing_count}Type")
        prop_item.value_string = self.emitter_type
        
        emitter.property_count = 2
        
        self.report({'INFO'}, f"Added emitter '{self.emitter_name}'")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class TROYBIN_OT_remove_emitter(Operator):
    """Remove the selected emitter"""
    bl_idname = "troybin.remove_emitter"
    bl_label = "Remove Emitter"
    bl_description = "Remove the currently selected emitter and its properties"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not settings.emitters:
            self.report({'ERROR'}, "No emitters to remove")
            return {'CANCELLED'}
        
        if settings.active_emitter_index >= len(settings.emitters):
            self.report({'ERROR'}, "Invalid emitter selection")
            return {'CANCELLED'}
        
        # Get emitter name before removing
        emitter_name = settings.emitters[settings.active_emitter_index].name
        
        # Remove properties associated with this emitter
        props_to_remove = []
        for i, prop in enumerate(settings.properties):
            if f"[{emitter_name}]" in prop.prop_name:
                props_to_remove.append(i)
        
        # Remove in reverse order to maintain indices
        for i in reversed(props_to_remove):
            settings.properties.remove(i)
        
        # Remove emitter
        settings.emitters.remove(settings.active_emitter_index)
        
        # Adjust active index
        if settings.active_emitter_index >= len(settings.emitters):
            settings.active_emitter_index = max(0, len(settings.emitters) - 1)
        
        self.report({'INFO'}, f"Removed emitter '{emitter_name}' and {len(props_to_remove)} properties")
        return {'FINISHED'}


class TROYBIN_OT_add_property(Operator):
    """Add a new property to the particle"""
    bl_idname = "troybin.add_property"
    bl_label = "Add Property"
    bl_description = "Add a new property to the selected emitter"
    bl_options = {'REGISTER', 'UNDO'}
    
    property_template: EnumProperty(
        name="Property Type",
        description="Select a property template to add",
        items=[
            ('e-life', 'e-life (Emitter Lifetime)', 'How long the emitter lasts (-1 = infinite)'),
            ('e-rate', 'e-rate (Emission Rate)', 'Particles emitted per second'),
            ('e-rgba', 'e-rgba (Emitter Color)', 'Emitter color (RGBA 0-255)'),
            ('p-life', 'p-life (Particle Lifetime)', 'How long particles last'),
            ('p-scale', 'p-scale (Particle Scale)', 'Particle size (Vec3)'),
            ('p-vel', 'p-vel (Particle Velocity)', 'Movement speed (Vec3)'),
            ('p-rotvel', 'p-rotvel (Rotation Velocity)', 'Rotation speed in degrees/sec (Vec3)'),
            ('p-offset', 'p-offset (Spawn Offset)', 'Offset from emitter position (Vec3)'),
            ('p-type', 'p-type (Particle Type)', 'Render type (0=billboard, 3=mesh, etc.)'),
            ('p-mesh', 'p-mesh (Mesh File)', 'Mesh filename (.scb)'),
            ('p-texture', 'p-texture (Texture File)', 'Texture filename (.dds)'),
            ('p-meshtex', 'p-meshtex (Mesh Texture)', 'Mesh texture filename (.dds)'),
            ('p-backfaceon', 'p-backfaceon (Backface)', 'Enable backface rendering'),
            ('rendermode', 'rendermode (Render Mode)', 'Render mode setting'),
        ],
        default='p-scale'
    )
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if not settings.is_loaded:
            self.report({'ERROR'}, "No particle file loaded")
            return {'CANCELLED'}
        
        if not settings.emitters:
            self.report({'ERROR'}, "No emitters available. Add an emitter first.")
            return {'CANCELLED'}
        
        # Get selected emitter
        if settings.active_emitter_index >= len(settings.emitters):
            emitter_name = settings.emitters[0].name
            settings.active_emitter_index = 0
        else:
            emitter_name = settings.emitters[settings.active_emitter_index].name
        
        # Property templates with type and default value
        templates = {
            'e-life': ('Int16List', -1),
            'e-rate': ('Int8List', 10),
            'e-rgba': ('Float32ListVec4', [255.0, 255.0, 255.0, 255.0]),
            'p-life': ('Int8List', 2),
            'p-scale': ('Float32ListVec3', [20.0, 20.0, 20.0]),
            'p-vel': ('Float32ListVec3', [0.0, 0.0, 0.0]),
            'p-rotvel': ('Float32ListVec3', [0.0, 0.0, 0.0]),
            'p-offset': ('Float32ListVec3', [0.0, 0.0, 0.0]),
            'p-type': ('Int8List', 0),
            'p-mesh': ('StringList', 'sphere.scb'),
            'p-texture': ('StringList', 'white.dds'),
            'p-meshtex': ('StringList', 'white.dds'),
            'p-backfaceon': ('BitList', True),
            'rendermode': ('StringList', '1'),
        }
        
        prop_name = self.property_template
        prop_type, default_value = templates[prop_name]
        
        # Calculate hash
        prop_hash = troybin_parser.section_field_hash_proper(emitter_name, prop_name)
        
        # Check if property already exists
        for prop in settings.properties:
            if prop.prop_hash == f"0x{prop_hash:08X}":
                self.report({'WARNING'}, f"Property '{prop_name}' already exists for emitter '{emitter_name}'")
                return {'CANCELLED'}
        
        # Add property
        prop_item = settings.properties.add()
        prop_item.prop_hash = f"0x{prop_hash:08X}"
        prop_item.prop_type = prop_type
        prop_item.prop_name = f"[{emitter_name}] {prop_name}"
        
        # Set default value based on type
        if prop_type in ['Int32List', 'Int16List', 'Int8List']:
            prop_item.value_int = default_value
        elif prop_type in ['Float32List', 'FixedPointFloatList']:
            prop_item.value_float = default_value
        elif prop_type == 'BitList':
            prop_item.value_bool = default_value
        elif prop_type in ['Float32ListVec2', 'FixedPointFloatListVec2']:
            prop_item.value_vec2 = default_value
        elif prop_type in ['Float32ListVec3', 'FixedPointFloatListVec3']:
            prop_item.value_vec3 = default_value
        elif prop_type in ['Float32ListVec4', 'FixedPointFloatListVec4']:
            prop_item.value_vec4 = default_value
            if 'rgba' in prop_name.lower() or 'color' in prop_name.lower():
                prop_item.value_color = [v / 255.0 for v in default_value]
        elif prop_type == 'StringList':
            prop_item.value_string = default_value
        
        # Update emitter property count
        for emitter in settings.emitters:
            if emitter.name == emitter_name:
                emitter.property_count += 1
                break
        
        self.report({'INFO'}, f"Added property '{prop_name}' to emitter '{emitter_name}'")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


class TROYBIN_OT_remove_property(Operator):
    """Remove a property from the particle"""
    bl_idname = "troybin.remove_property"
    bl_label = "Remove Property"
    bl_description = "Remove the selected property"
    bl_options = {'REGISTER', 'UNDO'}
    
    property_index: IntProperty(
        name="Property Index",
        description="Index of the property to remove",
        default=0
    )
    
    def execute(self, context):
        settings = context.scene.troybin_settings
        
        if self.property_index < 0 or self.property_index >= len(settings.properties):
            self.report({'ERROR'}, "Invalid property index")
            return {'CANCELLED'}
        
        prop_name = settings.properties[self.property_index].prop_name
        settings.properties.remove(self.property_index)
        
        self.report({'INFO'}, f"Removed property '{prop_name}'")
        return {'FINISHED'}


# UI Lists
class TROYBIN_UL_emitters(UIList):
    """UI List for particle emitters"""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='PARTICLES')
            row.label(text=f"{item.property_count} props", icon='PROPERTIES')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name)


# Panels
class VIEW3D_PT_league_tools_panel(Panel):
    """Main League Tools Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Troybin Particle Editor"
    bl_idname = "VIEW3D_PT_league_tools_panel"
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.troybin_settings
        
        # Header
        layout.label(text="League of Legends Particles", icon='PARTICLES')
        layout.separator()
        
        # File operations
        box = layout.box()
        box.label(text="File Operations", icon='FILE')
        
        col = box.column(align=True)
        col.operator("troybin.import_file", text="Import Troybin", icon='IMPORT')
        
        if settings.is_loaded:
            col.operator("troybin.export_file", text="Export Troybin", icon='EXPORT')
            
            row = box.row(align=True)
            row.operator("troybin.reload_file", text="Reload", icon='FILE_REFRESH')
            row.operator("troybin.clear_data", text="Clear", icon='TRASH')
        else:
            col.operator("troybin.create_new", text="New Particle", icon='ADD')
        
        # File info
        if settings.is_loaded:
            layout.separator()
            box = layout.box()
            box.label(text="File Info", icon='INFO')
            
            if settings.filepath:
                filename = os.path.basename(settings.filepath)
                box.label(text=f"File: {filename}")
            else:
                box.label(text="File: <New Particle>")
            
            box.label(text=f"Emitters: {len(settings.emitters)}")
            box.label(text=f"Properties: {len(settings.properties)}")


class VIEW3D_PT_league_tools_emitters(Panel):
    """Emitters Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Emitters"
    bl_parent_id = "VIEW3D_PT_league_tools_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        return context.scene.troybin_settings.is_loaded
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.troybin_settings
        
        # Emitter list
        row = layout.row()
        row.template_list(
            "TROYBIN_UL_emitters",
            "",
            settings,
            "emitters",
            settings,
            "active_emitter_index",
            rows=3
        )
        
        # Add/Remove emitter buttons
        layout.separator()
        row = layout.row(align=True)
        row.operator("troybin.add_emitter", text="Add Emitter", icon='ADD')
        if settings.emitters:
            row.operator("troybin.remove_emitter", text="Remove", icon='REMOVE')


class VIEW3D_PT_league_tools_properties(Panel):
    """Properties Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Properties"
    bl_parent_id = "VIEW3D_PT_league_tools_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        return context.scene.troybin_settings.is_loaded
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.troybin_settings
        
        # Display options
        box = layout.box()
        box.label(text="Display Options", icon='PREFERENCES')
        box.prop(settings, "show_hashes", text="Show Hashes")
        box.prop(settings, "show_all_properties", text="Show All Properties")
        
        layout.separator()
        
        # Note about editing
        info_box = layout.box()
        info_box.label(text="Properties are editable!", icon='INFO')
        info_box.label(text="Changes will be saved on export")
        
        layout.separator()
        
        # Filter by emitter
        if settings.emitters and settings.active_emitter_index < len(settings.emitters):
            active_emitter = settings.emitters[settings.active_emitter_index]
            layout.label(text=f"Emitter: {active_emitter.name}", icon='PARTICLES')
        
        # Add property button
        layout.separator()
        layout.operator("troybin.add_property", text="Add Property", icon='ADD')
        layout.separator()
        
        # Property list (simplified view)
        if not settings.properties:
            layout.label(text="No properties", icon='INFO')
            return
        
        # Group properties by type
        prop_types = {}
        for prop in settings.properties:
            if prop.prop_type not in prop_types:
                prop_types[prop.prop_type] = []
            prop_types[prop.prop_type].append(prop)
        
        # Display by type
        for prop_type, props in sorted(prop_types.items()):
            box = layout.box()
            box.label(text=f"{prop_type} ({len(props)})", icon='DOT')
            
            # Determine how many to show
            max_display = len(props) if settings.show_all_properties else min(10, len(props))
            
            # Show properties (editable)
            for i, prop in enumerate(props[:max_display]):
                # Property name with optional hash and remove button
                row = box.row()
                col = row.column()
                col.scale_x = 0.9
                if settings.show_hashes:
                    col.label(text=f"{prop.prop_hash} - {prop.prop_name}", icon='PROPERTIES')
                else:
                    col.label(text=prop.prop_name, icon='PROPERTIES')
                
                # Remove button
                col_btn = row.column()
                col_btn.scale_x = 0.5
                # Find global index of this property
                global_idx = next((idx for idx, p in enumerate(settings.properties) if p == prop), -1)
                if global_idx >= 0:
                    op = col_btn.operator("troybin.remove_property", text="", icon='X')
                    op.property_index = global_idx
                
                # Editable value based on type
                if prop_type in ['Int32List', 'Int16List', 'Int8List']:
                    box.prop(prop, "value_int", text="Value")
                
                elif prop_type in ['Float32List', 'FixedPointFloatList']:
                    box.prop(prop, "value_float", text="Value")
                
                elif prop_type == 'BitList':
                    box.prop(prop, "value_bool", text="Enabled")
                
                elif prop_type == 'Float32ListVec2':
                    box.prop(prop, "value_vec2", text="Vec2")
                
                elif prop_type in ['Float32ListVec3', 'FixedPointFloatListVec3']:
                    box.prop(prop, "value_vec3", text="Vec3")
                
                elif prop_type in ['Float32ListVec4', 'FixedPointFloatListVec4']:
                    # Check if it's a color property (common for e-rgba, p-rgba, etc.)
                    if 'rgba' in prop.prop_name.lower() or 'color' in prop.prop_name.lower():
                        box.prop(prop, "value_color", text="Color (RGBA)")
                        # Show raw values for reference
                        raw_vals = [prop.value_color[j] * 255.0 for j in range(4)]
                        box.label(text=f"Raw: [{raw_vals[0]:.1f}, {raw_vals[1]:.1f}, {raw_vals[2]:.1f}, {raw_vals[3]:.1f}]")
                    else:
                        box.prop(prop, "value_vec4", text="Vec4")
                
                elif prop_type == 'StringList':
                    box.prop(prop, "value_string", text="Value")
                
                # Add spacing between properties
                if i < max_display - 1:
                    box.separator()
            
            # Show "more" indicator if not showing all
            if not settings.show_all_properties and len(props) > max_display:
                box.separator()
                box.label(text=f"... and {len(props) - max_display} more", icon='DOWNARROW_HLT')
                box.label(text="Enable 'Show All Properties' to see more")


# Registration
classes = (
    TroybinPropertyItem,
    TroybinEmitterItem,
    TroybinSettings,
    TROYBIN_OT_import,
    TROYBIN_OT_export,
    TROYBIN_OT_reload,
    TROYBIN_OT_clear,
    TROYBIN_OT_create_new,
    TROYBIN_OT_add_emitter,
    TROYBIN_OT_remove_emitter,
    TROYBIN_OT_add_property,
    TROYBIN_OT_remove_property,
    TROYBIN_UL_emitters,
    VIEW3D_PT_league_tools_panel,
    VIEW3D_PT_league_tools_emitters,
    VIEW3D_PT_league_tools_properties,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.troybin_settings = bpy.props.PointerProperty(type=TroybinSettings)
    print("[League Tools] Troybin UI registered")


def unregister():
    del bpy.types.Scene.troybin_settings
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print("[League Tools] Troybin UI unregistered")


if __name__ == "__main__":
    register()
