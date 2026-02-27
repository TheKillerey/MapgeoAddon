"""
League Tools – CFGBin / Inibin Editor for Blender
Provides UI for importing, editing, and exporting League .cfgbin / .inibin files.

These files store game configuration data (terrain, gameplay, minion skins, etc.)
in a hashed key-value format known as Inibin v2.
"""

import bpy
import json
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

from . import cfgbin_reader

# ============================================================================
# Well-known section/property names for hash resolution
# ============================================================================

_WELL_KNOWN_KEYS: dict[str, list[str]] = {
    # Sections commonly found in terrain.inibin / game.inibin
    "HeightBlending": [
        "enable", "layer0_scale", "layer1_scale", "layer2_scale", "layer3_scale",
    ],
    "Fog": [
        "Enable", "Red", "Green", "Blue", "Start", "End",
    ],
    "General": [
        "BaseMap", "HightMap", "HeightScale", "HeightOffset",
    ],
    "Water": [
        "Enable", "Height", "Transparency", "Red", "Green", "Blue",
    ],
    "GameObjects": [
        "Minion_Blue_Caster", "Minion_Blue_Melee", "Minion_Blue_Siege", "Minion_Blue_Super",
        "Minion_Red_Caster", "Minion_Red_Melee", "Minion_Red_Siege", "Minion_Red_Super",
        "Minion_Blue_MeleeSkin", "Minion_Blue_CasterSkin", "Minion_Blue_SiegeSkin", "Minion_Blue_SuperSkin",
        "Minion_Red_MeleeSkin", "Minion_Red_CasterSkin", "Minion_Red_SiegeSkin", "Minion_Red_SuperSkin",
    ],
    "Terrain": [
        "Layer0", "Layer1", "Layer2", "Layer3", "Layer4",
        "Layer0FilePath", "Layer1FilePath", "Layer2FilePath", "Layer3FilePath",
    ],
}


def _build_well_known_hash_map() -> dict[int, str]:
    """Build a hash → readable name lookup from the well-known table."""
    hmap: dict[int, str] = {}
    for section, props in _WELL_KNOWN_KEYS.items():
        for prop in props:
            h = cfgbin_reader.sdbm_hash_lower_with_delimiter(section, prop, "*")
            hmap[h] = f"{section}*{prop}"
    return hmap


_HASH_NAMES = _build_well_known_hash_map()


# ============================================================================
# Inibin data-type helpers
# ============================================================================

# Mapping set_name → short label for display
_SET_LABELS = {
    "Int32List":                 "i32",
    "Float32List":               "f32",
    "FixedPointFloatList":       "fp8",
    "Int16List":                 "i16",
    "Int8List":                  "u8",
    "BitList":                   "bit",
    "FixedPointFloatListVec3":   "fp8×3",
    "Float32ListVec3":           "f32×3",
    "FixedPointFloatListVec2":   "fp8×2",
    "Float32ListVec2":           "f32×2",
    "FixedPointFloatListVec4":   "fp8×4",
    "Float32ListVec4":           "f32×4",
    "StringList":                "str",
}

_SET_TYPE_ITEMS = [(k, f"{_SET_LABELS.get(k, k)} ({k})", f"{k} data type")
                   for k, _flag in cfgbin_reader.INIBIN_FLAGS]


def _value_to_display(set_name: str, value) -> str:
    """Format a parsed value for human-readable display."""
    if set_name == "BitList":
        return "True" if value else "False"
    if set_name in ("FixedPointFloatList",):
        return f"{value:.1f}"
    if isinstance(value, list):
        return ", ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _display_to_value(set_name: str, text: str):
    """Parse a display string back to a native value for the given set type."""
    text = text.strip()
    if set_name == "BitList":
        return text.lower() in ("true", "1", "yes")
    if set_name == "Int32List":
        return int(text)
    if set_name == "Float32List":
        return float(text)
    if set_name == "FixedPointFloatList":
        return float(text)
    if set_name == "Int16List":
        return int(text)
    if set_name == "Int8List":
        return int(text)
    if set_name == "StringList":
        return text
    # Vector types
    if "Vec" in set_name:
        parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
        if "Float32" in set_name:
            return [float(p) for p in parts]
        else:
            return [int(round(float(p))) for p in parts]
    return text


# ============================================================================
# PropertyGroups
# ============================================================================

class CfgbinEntryItem(PropertyGroup):
    """A single key-value entry in the cfgbin file."""
    hash_hex: StringProperty(name="Hash", description="SDBM hash as 0xHHHHHHHH")
    hash_int: IntProperty(name="Hash Int", description="Hash as unsigned int (stored as signed)")
    set_name: StringProperty(name="Set", description="Data type set name")
    resolved_name: StringProperty(name="Name", description="Resolved section*property name")
    value_display: StringProperty(name="Value", description="Editable value display")
    is_modified: BoolProperty(name="Modified", default=False)


class CfgbinSettings(PropertyGroup):
    """Settings for the CFGBin editor."""
    filepath: StringProperty(
        name="File Path",
        description="Path to the loaded cfgbin/inibin file",
        default="",
        subtype='FILE_PATH',
    )

    cfg_filepath: StringProperty(
        name="CFG Path",
        description="Optional .cfg file for hash name resolution",
        default="",
        subtype='FILE_PATH',
    )

    is_loaded: BoolProperty(name="Loaded", default=False)

    entries: CollectionProperty(type=CfgbinEntryItem, name="Entries")

    active_entry_index: IntProperty(name="Active Entry", default=0)

    filter_text: StringProperty(
        name="Filter",
        description="Filter entries by name or hash",
        default="",
    )

    show_only_resolved: BoolProperty(
        name="Resolved Only",
        description="Show only entries with resolved names",
        default=False,
    )

    show_only_modified: BoolProperty(
        name="Modified Only",
        description="Show only entries that have been modified",
        default=False,
    )

    # JSON cache of the raw parsed data (for export roundtrip)
    raw_data_json: StringProperty(name="Raw Data", default="")

    # Cached external cfg hash map (JSON)
    cfg_hash_map_json: StringProperty(name="CFG Hash Map", default="")

    # New entry fields
    new_entry_hash: StringProperty(name="Hash", default="", description="Hash as hex (e.g. 0x1234ABCD) or Section*Property")
    new_entry_set: EnumProperty(name="Type", items=_SET_TYPE_ITEMS, default="Int32List")
    new_entry_value: StringProperty(name="Value", default="0")


# ============================================================================
# UIList
# ============================================================================

class CFGBIN_UL_entry_list(UIList):
    """UIList for displaying cfgbin entries."""
    bl_idname = "CFGBIN_UL_entry_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        settings = context.scene.cfgbin_settings
        entry: CfgbinEntryItem = item

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # Name / hash
            name = entry.resolved_name if entry.resolved_name else entry.hash_hex
            type_lbl = _SET_LABELS.get(entry.set_name, entry.set_name)

            sub = row.row(align=True)
            sub.scale_x = 0.15
            sub.label(text=type_lbl)

            sub = row.row(align=True)
            sub.scale_x = 0.45
            if entry.resolved_name:
                sub.label(text=entry.resolved_name, icon='CHECKMARK')
            else:
                sub.label(text=entry.hash_hex, icon='QUESTION')

            sub = row.row(align=True)
            sub.scale_x = 0.40
            sub.prop(entry, "value_display", text="", emboss=True)

            if entry.is_modified:
                row.label(text="", icon='FILE_TICK')

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=entry.hash_hex)

    def filter_items(self, context, data, propname):
        settings = context.scene.cfgbin_settings
        entries = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(entries)
        flt_neworder = list(range(len(entries)))

        filter_text = settings.filter_text.lower()

        for i, entry in enumerate(entries):
            # Apply filters
            show = True
            if settings.show_only_resolved and not entry.resolved_name:
                show = False
            if settings.show_only_modified and not entry.is_modified:
                show = False
            if filter_text:
                searchable = (entry.resolved_name + " " + entry.hash_hex + " " + entry.value_display).lower()
                if filter_text not in searchable:
                    show = False
            if not show:
                flt_flags[i] = 0

        return flt_flags, flt_neworder


# ============================================================================
# Operators
# ============================================================================

class CFGBIN_OT_import(Operator):
    """Import a CFGBin / Inibin file"""
    bl_idname = "cfgbin.import_file"
    bl_label = "Import CFGBin"
    bl_description = "Import a .cfgbin or .inibin file for editing"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.cfgbin;*.inibin", options={'HIDDEN'})

    def execute(self, context):
        path = Path(self.filepath)
        if not path.exists():
            self.report({'ERROR'}, f"File not found: {path}")
            return {'CANCELLED'}

        try:
            result = cfgbin_reader.parse_cfgbin(path)
        except Exception as e:
            self.report({'ERROR'}, f"Parse error: {e}")
            return {'CANCELLED'}

        settings = context.scene.cfgbin_settings
        settings.filepath = str(path)
        settings.is_loaded = True

        # Build hash name map from well-known + optional cfg
        hash_names = dict(_HASH_NAMES)
        if settings.cfg_filepath:
            cfg_path = Path(settings.cfg_filepath)
            if cfg_path.exists():
                try:
                    ext_map = cfgbin_reader.build_hash_name_map_from_cfg(cfg_path)
                    for h, names in ext_map.items():
                        if h not in hash_names:
                            hash_names[h] = names[0] if names else f"0x{h:08x}"
                except Exception as exc:
                    print(f"[CFGBin] Warning: failed to load cfg: {exc}")

        # Store raw data for export round-trip
        raw_for_json = {}
        for set_name, entries in result["sets"].items():
            raw_for_json[set_name] = [(h, _serialize_value(v)) for h, v in entries]
        settings.raw_data_json = json.dumps(raw_for_json)

        # Populate entries collection
        settings.entries.clear()
        for set_name, entries in result["sets"].items():
            for hash_val, value in entries:
                item = settings.entries.add()
                item.hash_hex = f"0x{hash_val:08x}"
                item.hash_int = hash_val if hash_val < 0x80000000 else hash_val - 0x100000000
                item.set_name = set_name
                item.resolved_name = hash_names.get(hash_val, "")
                item.value_display = _value_to_display(set_name, value)
                item.is_modified = False

        settings.active_entry_index = 0

        total = len(settings.entries)
        resolved = sum(1 for e in settings.entries if e.resolved_name)
        self.report({'INFO'}, f"Loaded {total} entries ({resolved} resolved) from {path.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class CFGBIN_OT_export(Operator):
    """Export CFGBin data back to binary"""
    bl_idname = "cfgbin.export_file"
    bl_label = "Export CFGBin"
    bl_description = "Export edited data to a .cfgbin / .inibin file"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.cfgbin;*.inibin", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.scene.cfgbin_settings.is_loaded

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        path = Path(self.filepath)

        # Rebuild sets dict from entries collection
        sets: dict[str, list] = {}
        for entry in settings.entries:
            sn = entry.set_name
            hash_val = int(entry.hash_hex, 16)
            value = _display_to_value(sn, entry.value_display)
            sets.setdefault(sn, []).append((hash_val, value))

        try:
            cfgbin_reader.write_cfgbin(sets, path)
        except Exception as e:
            self.report({'ERROR'}, f"Write error: {e}")
            return {'CANCELLED'}

        # Clear modified flags
        for entry in settings.entries:
            entry.is_modified = False

        self.report({'INFO'}, f"Exported {sum(len(v) for v in sets.values())} entries to {path.name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        settings = context.scene.cfgbin_settings
        if settings.filepath:
            self.filepath = settings.filepath
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class CFGBIN_OT_load_cfg(Operator):
    """Load a .cfg file for hash name resolution"""
    bl_idname = "cfgbin.load_cfg"
    bl_label = "Load CFG Names"
    bl_description = "Load a readable .cfg file to resolve hashed property names"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.cfg;*.ini", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        cfg_path = Path(self.filepath)
        if not cfg_path.exists():
            self.report({'ERROR'}, f"File not found: {cfg_path}")
            return {'CANCELLED'}

        settings.cfg_filepath = str(cfg_path)

        try:
            ext_map = cfgbin_reader.build_hash_name_map_from_cfg(cfg_path)
        except Exception as e:
            self.report({'ERROR'}, f"Parse error: {e}")
            return {'CANCELLED'}

        # Merge into well-known map
        merged = dict(_HASH_NAMES)
        for h, names in ext_map.items():
            merged[h] = names[0] if names else f"0x{h:08x}"

        # Re-resolve existing entries
        resolved_count = 0
        for entry in settings.entries:
            hash_val = int(entry.hash_hex, 16)
            name = merged.get(hash_val, "")
            if name and not entry.resolved_name:
                entry.resolved_name = name
                resolved_count += 1

        self.report({'INFO'}, f"Loaded {len(ext_map)} names from {cfg_path.name}, resolved {resolved_count} new entries")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class CFGBIN_OT_clear(Operator):
    """Clear loaded CFGBin data"""
    bl_idname = "cfgbin.clear_data"
    bl_label = "Clear"
    bl_description = "Clear all loaded CFGBin data"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.cfgbin_settings.is_loaded

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        settings.entries.clear()
        settings.filepath = ""
        settings.cfg_filepath = ""
        settings.is_loaded = False
        settings.raw_data_json = ""
        settings.cfg_hash_map_json = ""
        settings.active_entry_index = 0
        self.report({'INFO'}, "CFGBin data cleared")
        return {'FINISHED'}


class CFGBIN_OT_edit_entry(Operator):
    """Edit the value of the active entry (pops up a dialog)"""
    bl_idname = "cfgbin.edit_entry"
    bl_label = "Edit Entry"
    bl_description = "Edit the value of the selected entry"
    bl_options = {'REGISTER', 'UNDO'}

    new_value: StringProperty(name="Value")

    @classmethod
    def poll(cls, context):
        s = context.scene.cfgbin_settings
        return s.is_loaded and len(s.entries) > 0

    def invoke(self, context, event):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            self.new_value = settings.entries[idx].value_display
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        layout = self.layout
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            layout.label(text=f"Hash: {entry.hash_hex}")
            if entry.resolved_name:
                layout.label(text=f"Name: {entry.resolved_name}")
            layout.label(text=f"Type: {entry.set_name}")
            layout.separator()
            layout.prop(self, "new_value", text="Value")

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            old_val = entry.value_display
            # Validate parse
            try:
                _display_to_value(entry.set_name, self.new_value)
            except Exception as e:
                self.report({'ERROR'}, f"Invalid value: {e}")
                return {'CANCELLED'}
            entry.value_display = self.new_value
            if entry.value_display != old_val:
                entry.is_modified = True
            self.report({'INFO'}, f"Updated {entry.hash_hex}")
        return {'FINISHED'}


class CFGBIN_OT_add_entry(Operator):
    """Add a new entry to the CFGBin data"""
    bl_idname = "cfgbin.add_entry"
    bl_label = "Add Entry"
    bl_description = "Add a new key-value entry"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.cfgbin_settings.is_loaded

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        settings = context.scene.cfgbin_settings
        layout = self.layout
        layout.label(text="Add New Entry", icon='ADD')
        layout.prop(settings, "new_entry_hash", text="Hash / Name")
        layout.prop(settings, "new_entry_set", text="Type")
        layout.prop(settings, "new_entry_value", text="Value")
        layout.separator()
        layout.label(text="Hash can be hex (0x1234ABCD) or Section*Property", icon='INFO')

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        hash_input = settings.new_entry_hash.strip()
        set_name = settings.new_entry_set
        value_text = settings.new_entry_value.strip()

        # Resolve hash
        if hash_input.lower().startswith("0x"):
            try:
                hash_val = int(hash_input, 16)
            except ValueError:
                self.report({'ERROR'}, f"Invalid hex hash: {hash_input}")
                return {'CANCELLED'}
            resolved = _HASH_NAMES.get(hash_val, "")
        elif "*" in hash_input:
            parts = hash_input.split("*", 1)
            hash_val = cfgbin_reader.sdbm_hash_lower_with_delimiter(parts[0], parts[1], "*")
            resolved = hash_input
        else:
            self.report({'ERROR'}, "Hash must be hex (0x...) or Section*Property format")
            return {'CANCELLED'}

        # Validate value
        try:
            _display_to_value(set_name, value_text)
        except Exception as e:
            self.report({'ERROR'}, f"Invalid value: {e}")
            return {'CANCELLED'}

        # Check for duplicate
        hex_str = f"0x{hash_val:08x}"
        for entry in settings.entries:
            if entry.hash_hex == hex_str and entry.set_name == set_name:
                self.report({'WARNING'}, f"Entry {hex_str} already exists in {set_name}")
                return {'CANCELLED'}

        item = settings.entries.add()
        item.hash_hex = hex_str
        item.hash_int = hash_val if hash_val < 0x80000000 else hash_val - 0x100000000
        item.set_name = set_name
        item.resolved_name = resolved
        item.value_display = value_text
        item.is_modified = True

        settings.active_entry_index = len(settings.entries) - 1
        self.report({'INFO'}, f"Added entry {hex_str} ({resolved or set_name})")
        return {'FINISHED'}


class CFGBIN_OT_remove_entry(Operator):
    """Remove the selected entry"""
    bl_idname = "cfgbin.remove_entry"
    bl_label = "Remove Entry"
    bl_description = "Remove the selected entry from the data"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.cfgbin_settings
        return s.is_loaded and len(s.entries) > 0

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            removed = settings.entries[idx].hash_hex
            settings.entries.remove(idx)
            settings.active_entry_index = min(idx, len(settings.entries) - 1)
            self.report({'INFO'}, f"Removed entry {removed}")
        return {'FINISHED'}


class CFGBIN_OT_resolve_hash(Operator):
    """Manually resolve a hash by entering Section*Property"""
    bl_idname = "cfgbin.resolve_hash"
    bl_label = "Resolve Hash"
    bl_description = "Manually set the Section*Property name for the selected entry"
    bl_options = {'REGISTER', 'UNDO'}

    name_input: StringProperty(name="Section*Property", default="")

    @classmethod
    def poll(cls, context):
        s = context.scene.cfgbin_settings
        return s.is_loaded and len(s.entries) > 0

    def invoke(self, context, event):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            self.name_input = entry.resolved_name
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        layout = self.layout
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            layout.label(text=f"Hash: {entry.hash_hex}")
            layout.prop(self, "name_input", text="Name")
            layout.separator()
            # Verify: compute hash of user input and compare
            if self.name_input and "*" in self.name_input:
                parts = self.name_input.split("*", 1)
                computed = cfgbin_reader.sdbm_hash_lower_with_delimiter(parts[0], parts[1], "*")
                computed_hex = f"0x{computed:08x}"
                match = computed_hex == entry.hash_hex
                icon = 'CHECKMARK' if match else 'ERROR'
                lbl = "MATCH" if match else f"MISMATCH (got {computed_hex})"
                layout.label(text=f"Hash check: {lbl}", icon=icon)

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            if self.name_input and "*" in self.name_input:
                # Verify hash matches
                parts = self.name_input.split("*", 1)
                computed = cfgbin_reader.sdbm_hash_lower_with_delimiter(parts[0], parts[1], "*")
                computed_hex = f"0x{computed:08x}"
                if computed_hex != entry.hash_hex:
                    self.report({'WARNING'},
                                f"Hash mismatch: {self.name_input} → {computed_hex}, expected {entry.hash_hex}. Name set anyway.")
            entry.resolved_name = self.name_input
        return {'FINISHED'}


class CFGBIN_OT_hash_calculator(Operator):
    """Calculate SDBM hash for a Section*Property string"""
    bl_idname = "cfgbin.hash_calculator"
    bl_label = "Hash Calculator"
    bl_description = "Calculate the SDBM hash of a Section*Property string"
    bl_options = {'REGISTER'}

    input_text: StringProperty(name="Section*Property", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "input_text", text="Input")
        if self.input_text and "*" in self.input_text:
            parts = self.input_text.split("*", 1)
            h = cfgbin_reader.sdbm_hash_lower_with_delimiter(parts[0], parts[1], "*")
            layout.label(text=f"Hash: 0x{h:08x}", icon='INFO')
        elif self.input_text:
            h = cfgbin_reader.sdbm_hash(self.input_text.lower())
            layout.label(text=f"Raw hash: 0x{h:08x}", icon='INFO')
            layout.label(text="Use Section*Property format for inibin keys", icon='QUESTION')

    def execute(self, context):
        if self.input_text:
            if "*" in self.input_text:
                parts = self.input_text.split("*", 1)
                h = cfgbin_reader.sdbm_hash_lower_with_delimiter(parts[0], parts[1], "*")
            else:
                h = cfgbin_reader.sdbm_hash(self.input_text.lower())
            self.report({'INFO'}, f"Hash of '{self.input_text}' = 0x{h:08x}")
        return {'FINISHED'}


class CFGBIN_OT_duplicate_entry(Operator):
    """Duplicate the selected entry"""
    bl_idname = "cfgbin.duplicate_entry"
    bl_label = "Duplicate Entry"
    bl_description = "Create a copy of the selected entry"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.cfgbin_settings
        return s.is_loaded and len(s.entries) > 0

    def execute(self, context):
        settings = context.scene.cfgbin_settings
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            src = settings.entries[idx]
            item = settings.entries.add()
            item.hash_hex = src.hash_hex
            item.hash_int = src.hash_int
            item.set_name = src.set_name
            item.resolved_name = src.resolved_name
            item.value_display = src.value_display
            item.is_modified = True
            settings.active_entry_index = len(settings.entries) - 1
            self.report({'INFO'}, f"Duplicated {src.hash_hex}")
        return {'FINISHED'}


# ============================================================================
# Panels — placed in "League Tools" sidebar tab
# ============================================================================

class VIEW3D_PT_cfgbin_editor_panel(Panel):
    """CFGBin / Inibin Editor panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "CFGBin / Inibin Editor"
    bl_idname = "VIEW3D_PT_cfgbin_editor_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.cfgbin_settings

        # Header
        layout.label(text="Inibin v2 File Editor", icon='FILE_BLEND')
        layout.separator()

        # File operations
        box = layout.box()
        box.label(text="File Operations", icon='FILE')
        col = box.column(align=True)
        col.operator("cfgbin.import_file", text="Import CFGBin / Inibin", icon='IMPORT')

        if settings.is_loaded:
            col.operator("cfgbin.export_file", text="Export CFGBin / Inibin", icon='EXPORT')
            row = box.row(align=True)
            row.operator("cfgbin.clear_data", text="Clear", icon='TRASH')
            row.operator("cfgbin.load_cfg", text="Load CFG Names", icon='SORTALPHA')

        # Hash tools
        box = layout.box()
        box.label(text="Tools", icon='TOOL_SETTINGS')
        box.operator("cfgbin.hash_calculator", text="Hash Calculator", icon='STRIP_COLOR_03')

        # File info
        if settings.is_loaded:
            layout.separator()
            box = layout.box()
            box.label(text="File Info", icon='INFO')
            filename = os.path.basename(settings.filepath)
            box.label(text=f"File: {filename}")
            total = len(settings.entries)
            resolved = sum(1 for e in settings.entries if e.resolved_name)
            modified = sum(1 for e in settings.entries if e.is_modified)
            box.label(text=f"Entries: {total}  |  Resolved: {resolved}  |  Modified: {modified}")
            if settings.cfg_filepath:
                box.label(text=f"CFG: {os.path.basename(settings.cfg_filepath)}")


class VIEW3D_PT_cfgbin_entries_panel(Panel):
    """CFGBin entries list"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Entries"
    bl_idname = "VIEW3D_PT_cfgbin_entries_panel"
    bl_parent_id = "VIEW3D_PT_cfgbin_editor_panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.cfgbin_settings.is_loaded

    def draw(self, context):
        layout = self.layout
        settings = context.scene.cfgbin_settings

        # Filters
        row = layout.row(align=True)
        row.prop(settings, "filter_text", text="", icon='VIEWZOOM')
        row.prop(settings, "show_only_resolved", text="", icon='CHECKMARK', toggle=True)
        row.prop(settings, "show_only_modified", text="", icon='FILE_TICK', toggle=True)

        # Entry list
        layout.template_list(
            "CFGBIN_UL_entry_list", "",
            settings, "entries",
            settings, "active_entry_index",
            rows=12,
        )

        # Entry actions
        row = layout.row(align=True)
        row.operator("cfgbin.edit_entry", text="Edit", icon='GREASEPENCIL')
        row.operator("cfgbin.resolve_hash", text="Name", icon='SORTALPHA')
        row.operator("cfgbin.duplicate_entry", text="Dup", icon='DUPLICATE')
        row.operator("cfgbin.remove_entry", text="", icon='TRASH')

        layout.separator()
        layout.operator("cfgbin.add_entry", text="Add Entry", icon='ADD')

        # Detail view of active entry
        idx = settings.active_entry_index
        if 0 <= idx < len(settings.entries):
            entry = settings.entries[idx]
            box = layout.box()
            box.label(text="Selected Entry", icon='PROPERTIES')
            col = box.column(align=True)
            col.label(text=f"Hash: {entry.hash_hex}")
            if entry.resolved_name:
                col.label(text=f"Name: {entry.resolved_name}")
            col.label(text=f"Type: {entry.set_name} ({_SET_LABELS.get(entry.set_name, '?')})")
            col.label(text=f"Value: {entry.value_display}")
            if entry.is_modified:
                col.label(text="Status: Modified", icon='FILE_TICK')


# ============================================================================
# Helpers
# ============================================================================

def _serialize_value(v):
    """Make a value JSON-serializable."""
    if isinstance(v, list):
        return [float(x) if isinstance(x, float) else x for x in v]
    return v


# ============================================================================
# Registration
# ============================================================================

classes = (
    CfgbinEntryItem,
    CfgbinSettings,
    CFGBIN_UL_entry_list,
    CFGBIN_OT_import,
    CFGBIN_OT_export,
    CFGBIN_OT_load_cfg,
    CFGBIN_OT_clear,
    CFGBIN_OT_edit_entry,
    CFGBIN_OT_add_entry,
    CFGBIN_OT_remove_entry,
    CFGBIN_OT_resolve_hash,
    CFGBIN_OT_hash_calculator,
    CFGBIN_OT_duplicate_entry,
    VIEW3D_PT_cfgbin_editor_panel,
    VIEW3D_PT_cfgbin_entries_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cfgbin_settings = bpy.props.PointerProperty(type=CfgbinSettings)
    print("[League Tools] CFGBin Editor registered")


def unregister():
    del bpy.types.Scene.cfgbin_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[League Tools] CFGBin Editor unregistered")
