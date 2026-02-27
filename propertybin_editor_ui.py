"""
League Tools – PropertyBin (.bin) Editor for Blender
Provides UI for importing, viewing, editing, and exporting League .bin files.

PropertyBin is the modern configuration format used by League for materials,
character configs, gameplay definitions, and other structured data.
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

from . import propertybin_parser as pbp
from . import community_hashes


# ============================================================================
# Hash name resolution
# ============================================================================

# Well-known class/field hashes from community research
_WELL_KNOWN_HASHES: dict[int, str] = {}

# Common class type hashes
_KNOWN_TYPES = {
    # Materials
    "StaticMaterialDef": None,
    "StaticMaterialShaderParamDef": None,
    "StaticMaterialSwitchDef": None,
    "StaticMaterialPassDef": None,
    "StaticMaterialTechniqueDef": None,
    # Map
    "MapContainer": None,
    "MapPlaceableContainer": None,
    "MapParticle": None,
    "MapLocator": None,
    "MapPointLight": None,
    "SunProperties": None,
    "VfxSystemDefinitionData": None,
    # Gameplay
    "SpellObject": None,
    "CharacterRecord": None,
    "ItemData": None,
    # Visibility
    "ChildMapVisibilityController": None,
    "MapVisibilityFlagDefinition": None,
}

# Common field name hashes
_KNOWN_FIELDS = [
    "mName", "mPath", "mHash", "mValue", "mType",
    "mTextureName", "mTexturePath", "mSamplerName",
    "mShader", "mBlendEnable", "mCullEnable",
    "mSrcColorBlendFactor", "mDstColorBlendFactor",
    "mSrcAlphaBlendFactor", "mDstAlphaBlendFactor",
    "mPosition", "mRotation", "mScale",
    "mColor", "mIntensity", "mRadius",
    "mParticlePath", "mFlags", "mQuality",
    "mChildVisibilityFlags", "mSwitchValues",
    "mParamValues", "mSamplerValues", "mTechniques",
    "mPasses", "mChildTechniques", "mShaderMacros",
    "mDynamicMaterial", "mSubmeshName",
    "mWriteMask", "mGroupName", "mOn",
    "mAddressU", "mAddressV", "mAddressW",
    "startDistance", "endDistance",
    "sunDirection", "sunColor", "skyColor",
    "fogColor", "fogStartDistance", "fogEndDistance",
    "fogEnabled", "fogAlternateColor",
]


def _build_hash_lookup():
    """Pre-compute hash table for well-known names."""
    # Class type hashes
    for name in _KNOWN_TYPES:
        h = pbp.fnv1a_32(name)
        _WELL_KNOWN_HASHES[h] = name
        _KNOWN_TYPES[name] = h

    # Field name hashes
    for name in _KNOWN_FIELDS:
        h = pbp.fnv1a_32(name)
        _WELL_KNOWN_HASHES[h] = name


_build_hash_lookup()


def resolve_hash(hash_str: str) -> str:
    """Try to resolve a hash string like '0x12345678' to a known name."""
    try:
        h = int(hash_str, 16)
    except (ValueError, TypeError):
        return ""
    # Check local well-known hashes first, then CommunityDragon
    name = _WELL_KNOWN_HASHES.get(h, "")
    if not name:
        name = community_hashes.resolve(h)
    return name


def resolve_type_hash(hash_str: str) -> str:
    """Resolve specifically as a type/class hash."""
    try:
        h = int(hash_str, 16)
    except (ValueError, TypeError):
        return ""
    name = _WELL_KNOWN_HASHES.get(h, "")
    if not name:
        name = community_hashes.resolve_type(h)
    if not name:
        name = community_hashes.resolve(h)
    return name


def resolve_entry_hash(hash_str: str) -> str:
    """Resolve specifically as an entry path hash."""
    try:
        h = int(hash_str, 16)
    except (ValueError, TypeError):
        return ""
    name = community_hashes.resolve_entry(h)
    if not name:
        name = community_hashes.resolve(h)
    if not name:
        name = _WELL_KNOWN_HASHES.get(h, "")
    return name


def resolve_field_hash(hash_str: str) -> str:
    """Resolve specifically as a field name hash."""
    try:
        h = int(hash_str, 16)
    except (ValueError, TypeError):
        return ""
    name = _WELL_KNOWN_HASHES.get(h, "")
    if not name:
        name = community_hashes.resolve_field(h)
    if not name:
        name = community_hashes.resolve(h)
    return name


# ============================================================================
# Property Groups
# ============================================================================

class PropBinNodeItem(PropertyGroup):
    """A flattened tree node for display in the UI list."""
    depth: IntProperty(name="Depth", default=0)
    path_key: StringProperty(name="Path")
    name_hash: StringProperty(name="Hash")
    resolved_name: StringProperty(name="Name")
    type_id: IntProperty(name="TypeID", default=0)
    type_label: StringProperty(name="Type")
    value_display: StringProperty(name="Value")
    is_leaf: BoolProperty(name="IsLeaf", default=True)
    is_container: BoolProperty(name="IsContainer", default=False)
    entry_index: IntProperty(name="EntryIdx", default=-1)


class PropBinEntryItem(PropertyGroup):
    """A top-level entry in the .bin file."""
    path_hash: StringProperty(name="Path Hash")
    type_hash: StringProperty(name="Type Hash")
    resolved_type: StringProperty(name="Type Name")
    resolved_path: StringProperty(name="Path Name")
    field_count: IntProperty(name="Fields", default=0)
    total_fields: IntProperty(name="Total Fields", default=0)


class PropBinSettings(PropertyGroup):
    """Settings for the PropertyBin editor."""
    filepath: StringProperty(
        name="File Path",
        subtype='FILE_PATH',
        default="",
    )
    is_loaded: BoolProperty(name="Loaded", default=False)

    entries: CollectionProperty(type=PropBinEntryItem, name="Entries")
    active_entry_index: IntProperty(name="Active Entry", default=0)

    nodes: CollectionProperty(type=PropBinNodeItem, name="Nodes")
    active_node_index: IntProperty(name="Active Node", default=0)

    filter_text: StringProperty(
        name="Filter",
        description="Filter entries by hash, type, or resolved name",
        default="",
    )

    show_resolved_only: BoolProperty(
        name="Named Only",
        description="Show only entries with resolved type names",
        default=False,
    )

    # Stored parsed data as JSON for round-trip export
    raw_data_json: StringProperty(name="Raw Data", default="")

    # Info
    info_version: IntProperty(name="Version", default=0)
    info_linked: IntProperty(name="Linked Files", default=0)
    info_entries: IntProperty(name="Entry Count", default=0)
    info_magic: StringProperty(name="Magic", default="")


# ============================================================================
# UIList
# ============================================================================

class PROPBIN_UL_entry_list(UIList):
    """UIList for PropertyBin entries."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Type name or hash
            type_text = item.resolved_type if item.resolved_type else item.type_hash
            row.label(text=type_text, icon='FILE_BLEND')

            # Path
            path_text = item.resolved_path if item.resolved_path else item.path_hash
            sub = row.row()
            sub.scale_x = 1.2
            sub.label(text=path_text)

            # Field count
            sub2 = row.row()
            sub2.alignment = 'RIGHT'
            sub2.label(text=f"{item.field_count}f")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        settings = context.scene.propbin_settings

        # Build filtered + sorted lists
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))

        filter_text = settings.filter_text.lower()
        show_resolved = settings.show_resolved_only

        for i, item in enumerate(items):
            if show_resolved and not item.resolved_type:
                flt_flags[i] = 0
                continue

            if filter_text:
                searchable = f"{item.path_hash} {item.type_hash} {item.resolved_type} {item.resolved_path}".lower()
                if filter_text not in searchable:
                    flt_flags[i] = 0

        return flt_flags, flt_neworder


class PROPBIN_UL_node_list(UIList):
    """UIList for field nodes (tree view) of the selected entry."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Indentation
            indent = "    " * item.depth
            if item.is_container:
                prefix = indent + "▼ "
            elif item.is_leaf:
                prefix = indent + "  "
            else:
                prefix = indent + "▶ "

            # Name
            name_text = item.resolved_name if item.resolved_name else item.name_hash
            row.label(text=f"{prefix}{name_text}")

            # Type badge
            sub = row.row()
            sub.scale_x = 0.4
            sub.label(text=item.type_label)

            # Value
            sub2 = row.row()
            sub2.scale_x = 1.5
            val_text = item.value_display
            if len(val_text) > 50:
                val_text = val_text[:47] + "..."
            sub2.label(text=val_text)


# ============================================================================
# Operators
# ============================================================================

class PROPBIN_OT_import(Operator):
    """Import a PropertyBin (.bin) file"""
    bl_idname = "propbin.import_file"
    bl_label = "Import PropertyBin"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.propbin_settings

        try:
            bin_data = pbp.parse_bin(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Parse error: {e}")
            return {'CANCELLED'}

        # Store raw data for editing / re-export
        settings.raw_data_json = json.dumps(bin_data, ensure_ascii=False)
        settings.filepath = self.filepath
        settings.is_loaded = True
        settings.info_version = bin_data.get("version", 0)
        settings.info_linked = len(bin_data.get("linked_files", []))
        settings.info_entries = len(bin_data.get("entries", []))
        settings.info_magic = bin_data.get("magic", "")

        # Populate entry list
        _populate_entries(settings, bin_data)

        self.report({'INFO'}, f"Loaded {settings.info_entries} entries from {Path(self.filepath).name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PROPBIN_OT_export(Operator):
    """Export the loaded PropertyBin data to a .bin file"""
    bl_idname = "propbin.export_file"
    bl_label = "Export PropertyBin"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.propbin_settings
        if not settings.is_loaded or not settings.raw_data_json:
            self.report({'ERROR'}, "No data loaded")
            return {'CANCELLED'}

        try:
            bin_data = json.loads(settings.raw_data_json)
            pbp.write_bin(bin_data, self.filepath)
            self.report({'INFO'}, f"Exported to {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export error: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        if context.scene.propbin_settings.filepath:
            self.filepath = context.scene.propbin_settings.filepath
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PROPBIN_OT_clear(Operator):
    """Clear loaded PropertyBin data"""
    bl_idname = "propbin.clear_data"
    bl_label = "Clear"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.propbin_settings
        settings.entries.clear()
        settings.nodes.clear()
        settings.raw_data_json = ""
        settings.filepath = ""
        settings.is_loaded = False
        settings.info_version = 0
        settings.info_linked = 0
        settings.info_entries = 0
        settings.info_magic = ""
        self.report({'INFO'}, "Cleared PropertyBin data")
        return {'FINISHED'}


class PROPBIN_OT_select_entry(Operator):
    """Load fields for the selected entry"""
    bl_idname = "propbin.select_entry"
    bl_label = "View Entry"
    bl_options = {'REGISTER'}

    entry_index: IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.propbin_settings
        if not settings.raw_data_json:
            return {'CANCELLED'}

        idx = settings.active_entry_index
        bin_data = json.loads(settings.raw_data_json)
        entries = bin_data.get("entries", [])

        if idx < 0 or idx >= len(entries):
            return {'CANCELLED'}

        entry = entries[idx]
        _populate_nodes(settings, entry)

        return {'FINISHED'}


class PROPBIN_OT_edit_value(Operator):
    """Edit a leaf value in the selected entry"""
    bl_idname = "propbin.edit_value"
    bl_label = "Edit Value"
    bl_options = {'REGISTER', 'UNDO'}

    new_value: StringProperty(name="New Value", default="")

    def execute(self, context):
        settings = context.scene.propbin_settings
        if not settings.raw_data_json:
            return {'CANCELLED'}

        node_idx = settings.active_node_index
        if node_idx < 0 or node_idx >= len(settings.nodes):
            return {'CANCELLED'}

        node = settings.nodes[node_idx]
        if not node.is_leaf:
            self.report({'WARNING'}, "Cannot directly edit container nodes")
            return {'CANCELLED'}

        # Parse the JSON data, find and update the value
        bin_data = json.loads(settings.raw_data_json)
        entry_idx = settings.active_entry_index
        entries = bin_data.get("entries", [])

        if entry_idx < 0 or entry_idx >= len(entries):
            return {'CANCELLED'}

        entry = entries[entry_idx]

        # Navigate to the field using the path
        try:
            field_ref = _find_field_by_path(entry["fields"], node.path_key)
            if field_ref is None:
                self.report({'ERROR'}, f"Field not found: {node.path_key}")
                return {'CANCELLED'}

            # Parse new value
            new_val = pbp.parse_leaf_value(node.type_id, self.new_value)
            field_ref["value"] = new_val

            # Update stored JSON
            settings.raw_data_json = json.dumps(bin_data, ensure_ascii=False)

            # Refresh node display
            node.value_display = pbp._format_leaf_value(field_ref)

            self.report({'INFO'}, f"Updated {node.name_hash}")
        except Exception as e:
            self.report({'ERROR'}, f"Edit failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        settings = context.scene.propbin_settings
        node_idx = settings.active_node_index
        if 0 <= node_idx < len(settings.nodes):
            self.new_value = settings.nodes[node_idx].value_display
        return context.window_manager.invoke_props_dialog(self)


class PROPBIN_OT_hash_lookup(Operator):
    """Calculate FNV-1a hash or look up a known hash"""
    bl_idname = "propbin.hash_lookup"
    bl_label = "Hash Calculator"
    bl_options = {'REGISTER'}

    input_text: StringProperty(name="Name or Hash", default="")

    def execute(self, context):
        text = self.input_text.strip()
        if not text:
            return {'CANCELLED'}

        if text.startswith('0x'):
            # Reverse lookup
            resolved = resolve_hash(text)
            if resolved:
                self.report({'INFO'}, f"{text} = {resolved}")
            else:
                self.report({'INFO'}, f"{text}: no known name")
        else:
            # Forward hash
            h = pbp.fnv1a_32(text)
            self.report({'INFO'}, f"{text} = 0x{h:08x}")

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class PROPBIN_OT_add_hash_names(Operator):
    """Load additional hash names from a text file (CommunityDragon format, hash=name, or JSON)"""
    bl_idname = "propbin.add_hash_names"
    bl_label = "Load Hash Names"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.txt;*.json;*.hashes", options={'HIDDEN'})

    def execute(self, context):
        count = 0
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            if content.startswith('{'):
                # JSON format: {"hash_hex": "name", ...} or {"name": hash_int, ...}
                data = json.loads(content)
                for k, v in data.items():
                    if k.startswith('0x'):
                        _WELL_KNOWN_HASHES[int(k, 16)] = str(v)
                        count += 1
                    else:
                        _WELL_KNOWN_HASHES[int(v) if isinstance(v, int) else int(v, 16)] = k
                        count += 1
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        # Format: 0xHASH=name or name=0xHASH
                        parts = line.split('=', 1)
                        if parts[0].strip().startswith('0x'):
                            _WELL_KNOWN_HASHES[int(parts[0].strip(), 16)] = parts[1].strip()
                        else:
                            h = pbp.fnv1a_32(parts[0].strip())
                            _WELL_KNOWN_HASHES[h] = parts[0].strip()
                        count += 1
                    else:
                        # CommunityDragon format: hex_hash name
                        # (no 0x prefix, space or tab separated)
                        parts = line.split(None, 1)
                        if len(parts) < 2:
                            continue
                        hex_part = parts[0]
                        name_part = parts[1]
                        # Strip optional 0x prefix
                        if hex_part.startswith('0x') or hex_part.startswith('0X'):
                            hex_part = hex_part[2:]
                        try:
                            h = int(hex_part, 16)
                            _WELL_KNOWN_HASHES[h] = name_part
                            # Also add to community hashes unified dict
                            community_hashes._all_hashes[h] = name_part
                            count += 1
                        except ValueError:
                            continue

            self.report({'INFO'}, f"Loaded {count} hash names from {Path(self.filepath).name}")

            # Refresh entries if loaded
            settings = context.scene.propbin_settings
            if settings.is_loaded and settings.raw_data_json:
                bin_data = json.loads(settings.raw_data_json)
                _populate_entries(settings, bin_data)

        except Exception as e:
            self.report({'ERROR'}, f"Failed to load hash names: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PROPBIN_OT_download_community_hashes(Operator):
    """Download latest hash dictionaries from CommunityDragon GitHub"""
    bl_idname = "propbin.download_community_hashes"
    bl_label = "Download Community Hashes"
    bl_options = {'REGISTER'}

    categories: EnumProperty(
        name="Category",
        items=[
            ('bin', "Bin Hashes", "PropertyBin hashes (entries, fields, types, binhashes)"),
            ('all', "All Hashes", "All hashes including game strings (larger download)"),
        ],
        default='bin',
    )

    def execute(self, context):
        self.report({'INFO'}, "Downloading hashes from CommunityDragon...")

        try:
            count = community_hashes.download_hashes(self.categories)
            stats = community_hashes.get_stats()

            self.report(
                {'INFO'},
                f"Downloaded {count} file(s). "
                f"Total hashes: {stats['total']:,} "
                f"(types: {stats['bintypes']:,}, fields: {stats['binfields']:,}, "
                f"entries: {stats['binentries']:,}, binhash: {stats['binhashes']:,})"
            )

            # Refresh entries if loaded
            settings = context.scene.propbin_settings
            if settings.is_loaded and settings.raw_data_json:
                bin_data = json.loads(settings.raw_data_json)
                _populate_entries(settings, bin_data)
                # Also refresh nodes if any are displayed
                if len(settings.nodes) > 0:
                    idx = settings.active_entry_index
                    entries = bin_data.get("entries", [])
                    if 0 <= idx < len(entries):
                        _populate_nodes(settings, entries[idx])

        except Exception as e:
            self.report({'ERROR'}, f"Download failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "categories")

        stats = community_hashes.get_stats()
        if stats['total'] > 0:
            box = layout.box()
            box.label(text=f"Currently loaded: {stats['total']:,} hashes")
            age = community_hashes.get_cache_age()
            if age is not None:
                if age < 24:
                    box.label(text=f"Cache age: {age:.1f} hours")
                else:
                    box.label(text=f"Cache age: {age / 24:.1f} days")
        else:
            layout.label(text="No hashes cached yet. Download will fetch ~30MB.")


class PROPBIN_OT_reload_community_hashes(Operator):
    """Reload cached community hashes from disk"""
    bl_idname = "propbin.reload_community_hashes"
    bl_label = "Reload Cached Hashes"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Force reload
        community_hashes._loaded_files.clear()
        community_hashes.bin_entries.clear()
        community_hashes.bin_fields.clear()
        community_hashes.bin_hashes.clear()
        community_hashes.bin_types.clear()
        community_hashes.game_hashes.clear()
        community_hashes._all_hashes.clear()

        count = community_hashes.load_cached_hashes("all")

        if count > 0:
            self.report({'INFO'}, f"Reloaded {count:,} hash entries from cache")

            # Refresh entries if loaded
            settings = context.scene.propbin_settings
            if settings.is_loaded and settings.raw_data_json:
                bin_data = json.loads(settings.raw_data_json)
                _populate_entries(settings, bin_data)
                if len(settings.nodes) > 0:
                    idx = settings.active_entry_index
                    entries = bin_data.get("entries", [])
                    if 0 <= idx < len(entries):
                        _populate_nodes(settings, entries[idx])
        else:
            self.report({'WARNING'}, "No cached hash files found. Use 'Download Community Hashes' first.")

        return {'FINISHED'}


class PROPBIN_OT_remove_entry(Operator):
    """Remove the selected entry from the bin data"""
    bl_idname = "propbin.remove_entry"
    bl_label = "Remove Entry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.propbin_settings
        if not settings.raw_data_json:
            return {'CANCELLED'}

        idx = settings.active_entry_index
        bin_data = json.loads(settings.raw_data_json)
        entries = bin_data.get("entries", [])

        if idx < 0 or idx >= len(entries):
            self.report({'ERROR'}, "Invalid entry index")
            return {'CANCELLED'}

        removed = entries.pop(idx)
        bin_data["entry_count"] = len(entries)
        settings.raw_data_json = json.dumps(bin_data, ensure_ascii=False)
        settings.info_entries = len(entries)

        _populate_entries(settings, bin_data)
        settings.nodes.clear()

        self.report({'INFO'}, f"Removed entry {removed.get('path_hash', '?')}")
        return {'FINISHED'}


class PROPBIN_OT_duplicate_entry(Operator):
    """Duplicate the selected entry"""
    bl_idname = "propbin.duplicate_entry"
    bl_label = "Duplicate Entry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.propbin_settings
        if not settings.raw_data_json:
            return {'CANCELLED'}

        idx = settings.active_entry_index
        bin_data = json.loads(settings.raw_data_json)
        entries = bin_data.get("entries", [])

        if idx < 0 or idx >= len(entries):
            return {'CANCELLED'}

        import copy
        new_entry = copy.deepcopy(entries[idx])
        # Modify path hash slightly to avoid collision
        old_hash = int(new_entry["path_hash"], 16)
        new_entry["path_hash"] = f"0x{(old_hash + 1) & 0xFFFFFFFF:08x}"

        entries.insert(idx + 1, new_entry)
        bin_data["entry_count"] = len(entries)
        settings.raw_data_json = json.dumps(bin_data, ensure_ascii=False)
        settings.info_entries = len(entries)

        _populate_entries(settings, bin_data)

        self.report({'INFO'}, f"Duplicated entry as {new_entry['path_hash']}")
        return {'FINISHED'}


# ============================================================================
# Helper Functions
# ============================================================================

def _populate_entries(settings, bin_data: dict):
    """Fill the entries collection from parsed data."""
    settings.entries.clear()
    for entry in bin_data.get("entries", []):
        item = settings.entries.add()
        item.path_hash = entry.get("path_hash", "0x00000000")
        item.type_hash = entry.get("type_hash", "0x00000000")
        item.resolved_type = resolve_type_hash(item.type_hash)
        item.resolved_path = resolve_entry_hash(item.path_hash)
        fields = entry.get("fields", [])
        item.field_count = len(fields) if fields else 0
        item.total_fields = pbp.count_fields_recursive(fields)


def _populate_nodes(settings, entry: dict):
    """Flatten entry fields into the node list for display."""
    settings.nodes.clear()
    fields = entry.get("fields", [])
    if not fields:
        return

    flat = pbp.flatten_fields(fields)
    for fn in flat:
        item = settings.nodes.add()
        item.depth = fn["depth"]
        item.path_key = fn["path"]
        item.name_hash = fn["name_hash"]
        item.resolved_name = resolve_field_hash(fn["name_hash"]) if fn["name_hash"].startswith("0x") else fn["name_hash"]
        item.type_id = fn["type"]
        item.type_label = fn["type_name"]
        item.is_leaf = fn["is_leaf"]
        item.is_container = fn["is_container"]

        # Enhance value display: resolve hash/link values to names
        val_display = fn.get("value_display", "")
        if item.is_leaf and val_display.startswith("0x") and item.type_id in (
            pbp.TYPE_HASH, pbp.TYPE_LINK,
        ):
            resolved = resolve_hash(val_display)
            if resolved:
                val_display = f"{resolved}  ({val_display})"

        # Resolve class_hash in struct/embedded/container element displays
        node_ref = fn.get("node_ref")
        if node_ref and isinstance(node_ref, dict):
            class_hash = node_ref.get("class_hash", "")
            if class_hash and class_hash.startswith("0x") and class_hash in val_display:
                resolved_class = resolve_type_hash(class_hash)
                if resolved_class:
                    val_display = val_display.replace(class_hash, resolved_class)

        item.value_display = val_display


def _find_field_by_path(fields: list, path: str):
    """Navigate field tree by dot-separated path to find the target node."""
    if not fields or not path:
        return None

    parts = path.split(".", 1)
    target_hash = parts[0]
    remaining = parts[1] if len(parts) > 1 else ""

    for field in fields:
        fh = field.get("name_hash", "")
        if fh == target_hash:
            if not remaining:
                return field

            # Check for array index in remaining path
            if remaining.startswith("["):
                idx_end = remaining.index("]")
                idx = int(remaining[1:idx_end])
                rest_after_idx = remaining[idx_end + 1:]
                if rest_after_idx.startswith("."):
                    rest_after_idx = rest_after_idx[1:]

                # Container element
                if "values" in field and idx < len(field["values"]):
                    elem = field["values"][idx]
                    if not rest_after_idx:
                        return elem
                    if elem.get("fields"):
                        return _find_field_by_path(elem["fields"], rest_after_idx)

                # Map pair
                if "pairs" in field and idx < len(field["pairs"]):
                    pair_val = field["pairs"][idx]["value"]
                    if not rest_after_idx:
                        return pair_val
                    if pair_val.get("fields"):
                        return _find_field_by_path(pair_val["fields"], rest_after_idx)

                return None

            # Nested struct/embedded
            sub_fields = field.get("fields")
            if sub_fields:
                return _find_field_by_path(sub_fields, remaining)

    return None


# ============================================================================
# UI Panels
# ============================================================================

class VIEW3D_PT_propbin_panel(Panel):
    """PropertyBin Editor - Main Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "PropertyBin Editor"
    bl_idname = "VIEW3D_PT_propbin_panel"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.propbin_settings

        # Header
        layout.label(text="Property Bin (.bin) Editor", icon='FILE_BLEND')
        layout.separator()

        # File operations
        box = layout.box()
        box.label(text="File Operations", icon='FILE')

        col = box.column(align=True)
        col.operator("propbin.import_file", text="Import .bin File", icon='IMPORT')

        if settings.is_loaded:
            col.operator("propbin.export_file", text="Export .bin File", icon='EXPORT')
            row = col.row(align=True)
            row.operator("propbin.clear_data", text="Clear", icon='TRASH')

        # Tools
        box = layout.box()
        box.label(text="Tools", icon='TOOL_SETTINGS')
        box.operator("propbin.hash_lookup", text="Hash Calculator", icon='COLLECTION_COLOR_03')
        box.operator("propbin.add_hash_names", text="Load Hash File", icon='SORTALPHA')

        # Community Hashes
        box = layout.box()
        box.label(text="Community Hashes", icon='WORLD')

        stats = community_hashes.get_stats()
        if stats['total'] > 0:
            col = box.column(align=True)
            col.label(text=f"Loaded: {stats['total']:,} hashes")

            detail_parts = []
            if stats['bintypes'] > 0:
                detail_parts.append(f"T:{stats['bintypes']:,}")
            if stats['binfields'] > 0:
                detail_parts.append(f"F:{stats['binfields']:,}")
            if stats['binentries'] > 0:
                detail_parts.append(f"E:{stats['binentries']:,}")
            if stats['binhashes'] > 0:
                detail_parts.append(f"H:{stats['binhashes']:,}")
            if detail_parts:
                col.label(text="  ".join(detail_parts))

            age = community_hashes.get_cache_age()
            if age is not None:
                if age < 24:
                    col.label(text=f"Cache: {age:.1f}h old")
                else:
                    col.label(text=f"Cache: {age / 24:.1f}d old")

        row = box.row(align=True)
        row.operator("propbin.download_community_hashes", text="Download Latest", icon='URL')
        row.operator("propbin.reload_community_hashes", text="", icon='FILE_REFRESH')

        # File Info
        if settings.is_loaded:
            box = layout.box()
            box.label(text="File Info", icon='INFO')
            col = box.column(align=True)
            col.label(text=f"Format: {settings.info_magic} v{settings.info_version}")
            col.label(text=f"Entries: {settings.info_entries}")
            col.label(text=f"Linked Files: {settings.info_linked}")
            col.label(text=f"File: {Path(settings.filepath).name}")


class VIEW3D_PT_propbin_entries_panel(Panel):
    """PropertyBin Editor - Entries Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Bin Entries"
    bl_idname = "VIEW3D_PT_propbin_entries_panel"
    bl_parent_id = "VIEW3D_PT_propbin_panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.propbin_settings.is_loaded

    def draw(self, context):
        layout = self.layout
        settings = context.scene.propbin_settings

        # Filter row
        row = layout.row(align=True)
        row.prop(settings, "filter_text", text="", icon='VIEWZOOM')
        row.prop(settings, "show_resolved_only", text="", icon='CHECKMARK', toggle=True)

        # Entry list
        layout.template_list(
            "PROPBIN_UL_entry_list", "",
            settings, "entries",
            settings, "active_entry_index",
            rows=8,
        )

        # Actions
        row = layout.row(align=True)
        row.operator("propbin.select_entry", text="View Fields", icon='HIDE_OFF')
        row.operator("propbin.duplicate_entry", text="", icon='DUPLICATE')
        row.operator("propbin.remove_entry", text="", icon='TRASH')


class VIEW3D_PT_propbin_fields_panel(Panel):
    """PropertyBin Editor - Field Detail Panel"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'League Tools'
    bl_label = "Entry Fields"
    bl_idname = "VIEW3D_PT_propbin_fields_panel"
    bl_parent_id = "VIEW3D_PT_propbin_panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.propbin_settings
        return settings.is_loaded and len(settings.nodes) > 0

    def draw(self, context):
        layout = self.layout
        settings = context.scene.propbin_settings

        # Entry header
        if 0 <= settings.active_entry_index < len(settings.entries):
            entry = settings.entries[settings.active_entry_index]
            box = layout.box()
            col = box.column(align=True)
            type_text = entry.resolved_type or entry.type_hash
            col.label(text=f"Type: {type_text}")
            path_text = entry.resolved_path or entry.path_hash
            col.label(text=f"Path: {path_text}")
            col.label(text=f"Fields: {entry.field_count} (total: {entry.total_fields})")

        # Node list (tree view)
        layout.template_list(
            "PROPBIN_UL_node_list", "",
            settings, "nodes",
            settings, "active_node_index",
            rows=12,
        )

        # Selected node detail + edit
        if 0 <= settings.active_node_index < len(settings.nodes):
            node = settings.nodes[settings.active_node_index]
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"Hash: {node.name_hash}")
            if node.resolved_name:
                col.label(text=f"Name: {node.resolved_name}")
            col.label(text=f"Type: {node.type_label} ({node.type_id})")
            col.label(text=f"Value: {node.value_display}")

            if node.is_leaf:
                col.separator()
                col.operator("propbin.edit_value", text="Edit Value", icon='GREASEPENCIL')


# ============================================================================
# Registration
# ============================================================================

_classes = (
    PropBinNodeItem,
    PropBinEntryItem,
    PropBinSettings,
    PROPBIN_UL_entry_list,
    PROPBIN_UL_node_list,
    PROPBIN_OT_import,
    PROPBIN_OT_export,
    PROPBIN_OT_clear,
    PROPBIN_OT_select_entry,
    PROPBIN_OT_edit_value,
    PROPBIN_OT_hash_lookup,
    PROPBIN_OT_add_hash_names,
    PROPBIN_OT_download_community_hashes,
    PROPBIN_OT_reload_community_hashes,
    PROPBIN_OT_remove_entry,
    PROPBIN_OT_duplicate_entry,
    VIEW3D_PT_propbin_panel,
    VIEW3D_PT_propbin_entries_panel,
    VIEW3D_PT_propbin_fields_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.propbin_settings = bpy.props.PointerProperty(type=PropBinSettings)
    print("[PropertyBin] Editor registered")


def unregister():
    del bpy.types.Scene.propbin_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    print("[PropertyBin] Editor unregistered")
