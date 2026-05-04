"""
League Tools – Map11.bin Bulk Editor

Loads a map11.bin file, lists all MapSkin entries, and lets the user
bulk-edit the key fields (Map Container, Objects CFG, Particles INI,
Grass Tint Texture) across all or selected MapSkins so that every map
skin loads from a specific map configuration.
"""

import copy
import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import propertybin_parser

# ============================================================================
# Constants – MapSkin field hashes
# ============================================================================

HASH_MAP_SKIN       = "0xcd19ef3c"

FIELD_NAME          = "0x8d39bde6"   # skin name  (string)
FIELD_GEO_PATH      = "0x960efd81"   # mMapContainerLink  (string)
FIELD_OBJECTS_CFG    = "0xe1281da0"   # Objects CFG path  (string)
FIELD_NAVGRID       = "0x63242493"   # NavGrid / AIPath  (string)
FIELD_CUBEMAP       = "0xd0a4e40b"   # Env CubeMap  (string)
FIELD_PARTICLES_INI  = "0x9e14bd6f"  # Particles INI path  (string)
FIELD_GRASS_TINT    = "0xbac3a0fa"   # GrassTint texture  (string)


# ============================================================================
# Helpers
# ============================================================================

def _get_field_value(entry, field_hash, default=""):
    """Return the string value of a MapSkin field, or *default*."""
    for f in entry.get("fields", []):
        if f.get("name_hash") == field_hash and "value" in f:
            return f["value"]
    return default


def _set_field_value(entry, field_hash, new_value):
    """Set the string value of an existing MapSkin field.  Returns True if found."""
    for f in entry.get("fields", []):
        if f.get("name_hash") == field_hash and "value" in f:
            f["value"] = new_value
            return True
    return False


# ============================================================================
# Property Groups
# ============================================================================

class Map11SkinItem(PropertyGroup):
    """One row in the MapSkin list."""
    name: StringProperty(name="Name")
    selected: BoolProperty(name="", default=True)
    geo_path: StringProperty(name="Map Container")
    objects_cfg: StringProperty(name="Objects CFG")
    particles_ini: StringProperty(name="Particles INI")
    grass_tint: StringProperty(name="Grass Tint Texture")
    # internal index into the parsed entries list
    entry_index: IntProperty()


class Map11EditorSettings(PropertyGroup):
    map11_path: StringProperty(
        name="map11.bin",
        description="Path to the map11.bin file to edit",
        subtype='FILE_PATH',
    )
    # Bulk replacement values
    bulk_geo_path: StringProperty(
        name="Map Container",
        description="Map container path to apply (e.g. Maps/MapGeometry/Map11/Base_SRX)",
    )
    bulk_objects_cfg: StringProperty(
        name="Objects CFG",
        description="Objects CFG filename to apply (e.g. ASSETS/Maps/Deprecated/Map11/CFG/objectcfg_SRX.cfg)",
    )
    bulk_particles_ini: StringProperty(
        name="Particles INI",
        description="Particles INI path to apply (e.g. ASSETS/Maps/Particles/Deprecated/Map11/Particles_SRX.ini)",
    )
    bulk_grass_tint: StringProperty(
        name="Grass Tint",
        description="Grass tint texture to apply (e.g. ASSETS/Maps/Info/Map11/GrassTint_SRX.tex)",
    )
    active_skin_index: IntProperty()


# ============================================================================
# UIList
# ============================================================================

class MAP11_UL_skin_list(UIList):
    bl_idname = "MAP11_UL_skin_list"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="")
        row.label(text=item.name)
        if item.geo_path:
            sub = row.row()
            sub.scale_x = 0.5
            sub.label(text=item.geo_path.rsplit("/", 1)[-1] if "/" in item.geo_path else item.geo_path)


# ============================================================================
# Operators
# ============================================================================

class MAP11EDITOR_OT_pick_file(Operator):
    """Browse for a map11.bin file"""
    bl_idname = "map11editor.pick_file"
    bl_label = "Pick map11.bin"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.map11_editor_settings
        settings.map11_path = self.filepath
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MAP11EDITOR_OT_load(Operator):
    """Load MapSkin entries from the selected map11.bin"""
    bl_idname = "map11editor.load"
    bl_label = "Load map11.bin"

    def execute(self, context):
        settings = context.scene.map11_editor_settings
        path = bpy.path.abspath(settings.map11_path)

        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, "Please select a valid map11.bin file")
            return {'CANCELLED'}

        try:
            data = propertybin_parser.parse_bin(path)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to parse: {exc}")
            return {'CANCELLED'}

        entries = data.get("entries", [])

        # Store parsed data on the scene for later save
        # We store the JSON-serialisable data on the operator context via a
        # module-level cache so we don't pollute the blend file.
        _cache["parsed_data"] = data
        _cache["source_path"] = path

        # Populate the UI list
        skin_list = context.scene.map11_skin_list
        skin_list.clear()

        for idx, entry in enumerate(entries):
            if entry.get("type_hash") != HASH_MAP_SKIN:
                continue

            item = skin_list.add()
            item.entry_index = idx
            item.name = _get_field_value(entry, FIELD_NAME, f"Skin_{idx}")
            item.geo_path = _get_field_value(entry, FIELD_GEO_PATH, "")
            item.objects_cfg = _get_field_value(entry, FIELD_OBJECTS_CFG, "")
            item.particles_ini = _get_field_value(entry, FIELD_PARTICLES_INI, "")
            item.grass_tint = _get_field_value(entry, FIELD_GRASS_TINT, "")

        # Pre-fill bulk fields from the "Default" skin if available
        for item in skin_list:
            if item.name == "Default":
                settings.bulk_geo_path = item.geo_path
                settings.bulk_objects_cfg = item.objects_cfg
                settings.bulk_particles_ini = item.particles_ini
                settings.bulk_grass_tint = item.grass_tint
                break

        self.report({'INFO'}, f"Loaded {len(skin_list)} MapSkin entries")
        return {'FINISHED'}


class MAP11EDITOR_OT_apply_bulk(Operator):
    """Apply bulk values to all selected MapSkins"""
    bl_idname = "map11editor.apply_bulk"
    bl_label = "Apply to Selected"
    bl_description = "Overwrite the four key fields on every checked MapSkin with the values above"

    def execute(self, context):
        settings = context.scene.map11_editor_settings
        skin_list = context.scene.map11_skin_list

        count = 0
        for item in skin_list:
            if not item.selected:
                continue
            if settings.bulk_geo_path:
                item.geo_path = settings.bulk_geo_path
            if settings.bulk_objects_cfg:
                item.objects_cfg = settings.bulk_objects_cfg
            if settings.bulk_particles_ini:
                item.particles_ini = settings.bulk_particles_ini
            if settings.bulk_grass_tint:
                item.grass_tint = settings.bulk_grass_tint
            count += 1

        self.report({'INFO'}, f"Applied bulk values to {count} skins")
        return {'FINISHED'}


class MAP11EDITOR_OT_select_all(Operator):
    """Select or deselect all MapSkin entries"""
    bl_idname = "map11editor.select_all"
    bl_label = "Select All"
    bl_description = "Toggle selection of all MapSkins"

    select: BoolProperty(default=True)

    def execute(self, context):
        for item in context.scene.map11_skin_list:
            item.selected = self.select
        return {'FINISHED'}


class MAP11EDITOR_OT_copy_from_selected(Operator):
    """Copy fields from the active skin to the bulk edit fields"""
    bl_idname = "map11editor.copy_from_selected"
    bl_label = "Copy from Active"
    bl_description = "Fill the bulk edit fields with the active skin's current values"

    def execute(self, context):
        settings = context.scene.map11_editor_settings
        skin_list = context.scene.map11_skin_list
        idx = settings.active_skin_index

        if idx < 0 or idx >= len(skin_list):
            self.report({'WARNING'}, "No skin selected")
            return {'CANCELLED'}

        item = skin_list[idx]
        settings.bulk_geo_path = item.geo_path
        settings.bulk_objects_cfg = item.objects_cfg
        settings.bulk_particles_ini = item.particles_ini
        settings.bulk_grass_tint = item.grass_tint

        self.report({'INFO'}, f"Copied values from '{item.name}'")
        return {'FINISHED'}


class MAP11EDITOR_OT_save(Operator):
    """Write modified MapSkin values back to map11.bin"""
    bl_idname = "map11editor.save"
    bl_label = "Save map11.bin"
    bl_description = "Write all changes back to the original map11.bin file (creates a .bak backup)"

    def execute(self, context):
        data = _cache.get("parsed_data")
        source_path = _cache.get("source_path")

        if data is None or source_path is None:
            self.report({'ERROR'}, "No data loaded – load a map11.bin first")
            return {'CANCELLED'}

        skin_list = context.scene.map11_skin_list
        entries = data.get("entries", [])

        # Apply UI values back into the parsed data
        updated = 0
        for item in skin_list:
            idx = item.entry_index
            if idx < 0 or idx >= len(entries):
                continue
            entry = entries[idx]

            changed = False
            if item.geo_path:
                changed |= _set_field_value(entry, FIELD_GEO_PATH, item.geo_path)
            if item.objects_cfg:
                changed |= _set_field_value(entry, FIELD_OBJECTS_CFG, item.objects_cfg)
            if item.particles_ini:
                changed |= _set_field_value(entry, FIELD_PARTICLES_INI, item.particles_ini)
            if item.grass_tint:
                changed |= _set_field_value(entry, FIELD_GRASS_TINT, item.grass_tint)
            if changed:
                updated += 1

        # Create backup
        bak_path = source_path + ".bak"
        if not os.path.exists(bak_path):
            try:
                import shutil
                shutil.copy2(source_path, bak_path)
            except OSError:
                pass

        try:
            propertybin_parser.write_bin(data, source_path)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to write: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Saved {updated} modified skins to {os.path.basename(source_path)}")
        return {'FINISHED'}


# Module-level cache for the parsed data (avoids polluting blend file)
_cache: dict = {}


# ============================================================================
# Panel
# ============================================================================

class VIEW3D_PT_map11_editor(Panel):
    """Map11.bin Bulk Editor panel in the League Tools sidebar."""
    bl_label = "Map11 Editor"
    bl_idname = "VIEW3D_PT_map11_editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_order = 85
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.map11_editor_settings
        skin_list = context.scene.map11_skin_list

        # ── File picker ──
        box = layout.box()
        box.label(text="Bulk edit MapSkin entries in map11.bin", icon='MODIFIER')

        row = box.row(align=True)
        row.prop(settings, "map11_path", text="")
        row.operator("map11editor.pick_file", text="", icon='FILE_FOLDER')

        row = box.row(align=True)
        row.operator("map11editor.load", text="Load", icon='IMPORT')

        if not skin_list:
            return

        # ── MapSkin list ──
        box = layout.box()
        row = box.row()
        row.label(text=f"MapSkins ({len(skin_list)})", icon='MESH_GRID')

        row = box.row()
        row.template_list(
            "MAP11_UL_skin_list", "",
            context.scene, "map11_skin_list",
            settings, "active_skin_index",
            rows=6,
        )

        row = box.row(align=True)
        op = row.operator("map11editor.select_all", text="Select All")
        op.select = True
        op = row.operator("map11editor.select_all", text="Deselect All")
        op.select = False

        # ── Active skin details ──
        idx = settings.active_skin_index
        if 0 <= idx < len(skin_list):
            item = skin_list[idx]
            detail = box.box()
            detail.label(text=f"Active: {item.name}", icon='OUTLINER_OB_ARMATURE')
            col = detail.column(align=True)
            col.prop(item, "geo_path", text="Container")
            col.prop(item, "objects_cfg", text="Objects CFG")
            col.prop(item, "particles_ini", text="Particles INI")
            col.prop(item, "grass_tint", text="Grass Tint")

        # ── Bulk edit ──
        box = layout.box()
        box.label(text="Bulk Replacement Values", icon='TOOL_SETTINGS')

        col = box.column(align=True)
        col.prop(settings, "bulk_geo_path", text="Container")
        col.prop(settings, "bulk_objects_cfg", text="Objects CFG")
        col.prop(settings, "bulk_particles_ini", text="Particles INI")
        col.prop(settings, "bulk_grass_tint", text="Grass Tint")

        row = box.row(align=True)
        row.operator("map11editor.copy_from_selected", text="Copy from Active", icon='COPYDOWN')
        row.operator("map11editor.apply_bulk", text="Apply to Selected", icon='CHECKMARK')

        # ── Save ──
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5
        row.operator("map11editor.save", text="Save map11.bin", icon='FILE_TICK')


# ============================================================================
# Registration
# ============================================================================

classes = (
    Map11SkinItem,
    Map11EditorSettings,
    MAP11_UL_skin_list,
    MAP11EDITOR_OT_pick_file,
    MAP11EDITOR_OT_load,
    MAP11EDITOR_OT_apply_bulk,
    MAP11EDITOR_OT_select_all,
    MAP11EDITOR_OT_copy_from_selected,
    MAP11EDITOR_OT_save,
    VIEW3D_PT_map11_editor,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.map11_editor_settings = bpy.props.PointerProperty(
        type=Map11EditorSettings
    )
    bpy.types.Scene.map11_skin_list = bpy.props.CollectionProperty(
        type=Map11SkinItem
    )


def unregister():
    if hasattr(bpy.types.Scene, "map11_skin_list"):
        del bpy.types.Scene.map11_skin_list
    if hasattr(bpy.types.Scene, "map11_editor_settings"):
        del bpy.types.Scene.map11_editor_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
