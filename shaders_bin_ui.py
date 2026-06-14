"""shaders_bin_ui.py — Experimental Shaders.bin Catalog UI
=========================================================
Blender operators and panel for loading and browsing the Shaders.bin
catalog.  The catalog provides authoritative shader metadata from the
game's CustomShaderDef registry: parameter names, static switches (with
their on-by-default state), texture slots (with default paths), feature
defines, and the feature mask.

This is an EXPERIMENTAL feature surfaced as a collapsible sub-panel
under the League Material panel in the Properties editor.

Usage
-----
1. In the "Shader Catalog [EXP]" panel, set the path to either:
   - Your Shaders.wad / Shaders.wad.client  (e.g. …\DATA\FINAL\Shaders\Shaders.wad)
   - Or a standalone shaders.bin you extracted beforehand
2. Click "Load Catalog".
3. Select any League material — the panel shows the catalog metadata for
   that shader.
4. Use "Apply Missing Defaults" to fill in any texture samplers whose
   default paths are defined in the catalog but absent from the material.

Reference: https://github.com/LeagueToolkit/shader-tools
"""

import bpy
import json
import os
from bpy.props import StringProperty
from bpy.types import Operator, Panel


# ── Scene properties ───────────────────────────────────────────────────────────

def _register_properties() -> None:
    bpy.types.Scene.shaders_bin_path = StringProperty(
        name="Shaders.wad / shaders.bin",
        description=(
            "Path to Shaders.wad, Shaders.wad.client, or a standalone shaders.bin "
            "extracted from the game.  Used by the Shader Catalog panel."
        ),
        default="",
        subtype="FILE_PATH",
    )


def _unregister_properties() -> None:
    try:
        del bpy.types.Scene.shaders_bin_path
    except Exception:
        pass


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_current_shader(mat) -> str:
    """Return the first shader path from the material's techniques JSON, or ''."""
    try:
        techs = json.loads(mat.get("techniques", "[]"))
        if techs and techs[0].get("passes"):
            return techs[0]["passes"][0].get("shader", "")
    except Exception:
        pass
    return ""


def _import_sbr():
    """Import shaders_bin_reader, supporting both package and standalone runs."""
    try:
        from . import shaders_bin_reader as sbr
        return sbr
    except ImportError:
        import shaders_bin_reader as sbr
        return sbr


# ── Operator: Load catalog ─────────────────────────────────────────────────────

class MAPGEO_OT_load_shaders_bin_catalog(Operator):
    """Parse shaders.bin (or extract it from Shaders.wad) and build the catalog"""
    bl_idname = "mapgeo.load_shaders_bin_catalog"
    bl_label  = "Load Catalog"
    bl_description = (
        "Parse shaders.bin — or extract it automatically from Shaders.wad / "
        "Shaders.wad.client — and build an in-memory catalog of shader metadata"
    )

    def execute(self, context):
        path = context.scene.shaders_bin_path.strip()
        if not path:
            self.report({'ERROR'}, "No path set — browse to shaders.bin or Shaders.wad first")
            return {'CANCELLED'}

        if not os.path.isfile(path):
            self.report({'ERROR'}, f"File not found: {path}")
            return {'CANCELLED'}

        sbr = _import_sbr()
        try:
            lower = path.lower()
            if lower.endswith(".wad") or lower.endswith(".wad.client"):
                count = sbr.load_catalog_from_wad(path)
            else:
                count = sbr.load_catalog_from_bin_file(path)
        except Exception as ex:
            self.report({'ERROR'}, f"Failed to load catalog: {ex}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Shaders.bin: loaded {count} shader entries")
        return {'FINISHED'}


# ── Operator: Auto-detect Shaders.wad ─────────────────────────────────────────

class MAPGEO_OT_find_shaders_wad(Operator):
    """Try to auto-detect Shaders.wad from the League of Legends install"""
    bl_idname = "mapgeo.find_shaders_wad"
    bl_label  = "Auto-detect"
    bl_description = (
        "Search common League of Legends install locations for Shaders.wad "
        "and fill the path field"
    )

    def execute(self, context):
        sbr = _import_sbr()
        found = sbr.find_default_wad_path()
        if found:
            context.scene.shaders_bin_path = found
            self.report({'INFO'}, f"Found: {found}")
        else:
            self.report({'WARNING'}, "Shaders.wad not found in common locations")
        return {'FINISHED'}


# ── Operator: Apply missing default textures ───────────────────────────────────

class MAPGEO_OT_apply_catalog_defaults(Operator):
    """Add sampler entries for texture slots that are in the catalog but absent from this material"""
    bl_idname = "mapgeo.apply_catalog_defaults"
    bl_label  = "Apply Missing Defaults"
    bl_description = (
        "For each texture slot defined in the Shaders.bin catalog that is not yet "
        "present on this material, add a sampler entry with the catalog's default "
        "texture path"
    )

    def execute(self, context):
        mat = context.material
        if not mat:
            self.report({'ERROR'}, "No active material")
            return {'CANCELLED'}

        sbr = _import_sbr()
        if not sbr.is_catalog_loaded():
            self.report({'ERROR'}, "Catalog not loaded — load Shaders.bin first")
            return {'CANCELLED'}

        shader_path = _get_current_shader(mat)
        if not shader_path:
            self.report({'ERROR'}, "No shader on this material")
            return {'CANCELLED'}

        entry = sbr.get_shader_entry(shader_path)
        if not entry:
            self.report({'WARNING'}, f"Shader not in catalog: {shader_path}")
            return {'CANCELLED'}

        try:
            samplers = json.loads(mat.get("samplers", "[]"))
        except Exception:
            samplers = []

        existing = {s.get("textureName", "").lower() for s in samplers}
        added = 0
        for tex in entry.textures:
            if tex.name.lower() in existing:
                continue
            if not tex.default_path:
                continue
            samplers.append({
                "textureName": tex.name,
                "texturePath": tex.default_path,
                "addressU": 1,
                "addressV": 1,
                "addressW": 1,
            })
            added += 1

        if added:
            mat["samplers"] = json.dumps(samplers)
            self.report({'INFO'}, f"Added {added} default texture sampler(s) from catalog")
        else:
            self.report({'INFO'}, "No new defaults to add (all slots already present or no defaults defined)")

        return {'FINISHED'}


# ── Panel: Shader Catalog (Experimental) ──────────────────────────────────────

class MATERIAL_PT_league_shader_catalog(Panel):
    """EXPERIMENTAL — Shaders.bin live catalog viewer"""
    bl_label        = "Shader Catalog  [EXP]"
    bl_idname       = "MATERIAL_PT_league_shader_catalog"
    bl_space_type   = 'PROPERTIES'
    bl_region_type  = 'WINDOW'
    bl_context      = "material"
    bl_parent_id    = "MATERIAL_PT_league_properties"
    bl_options      = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.material and context.material.get("league_material_name")

    def draw_header(self, context):
        self.layout.label(icon='EXPERIMENTAL')

    def draw(self, context):
        layout = self.layout
        mat    = context.material
        sbr    = _import_sbr()

        # ── Catalog load controls ──────────────────────────────────────────────
        load_box = layout.box()
        col = load_box.column(align=True)

        if sbr.is_catalog_loaded():
            col.label(
                text=f"Catalog: {sbr.catalog_size()} shaders loaded",
                icon='CHECKMARK',
            )
            src = sbr.catalog_source() or ""
            col.label(text=os.path.basename(src) or src, icon='FILE')
        else:
            col.label(text="Catalog not loaded", icon='INFO')

        row = col.row(align=True)
        row.prop(context.scene, "shaders_bin_path", text="")
        row.operator("mapgeo.find_shaders_wad", text="", icon='VIEWZOOM')
        col.operator("mapgeo.load_shaders_bin_catalog", icon='IMPORT')

        if not sbr.is_catalog_loaded():
            return

        # ── Current shader lookup ──────────────────────────────────────────────
        shader_path = _get_current_shader(mat)
        if not shader_path:
            layout.label(text="No shader on this material", icon='QUESTION')
            return

        entry = sbr.get_shader_entry(shader_path)
        short_name = shader_path.rsplit("/", 1)[-1]

        if not entry:
            layout.label(
                text=f"Not in catalog: {short_name}",
                icon='ERROR',
            )
            return

        layout.label(text=short_name, icon='NODE_MATERIAL')

        # ── Parameters ────────────────────────────────────────────────────────
        if entry.parameters:
            p_box = layout.box()
            p_box.label(text=f"Parameters  ({len(entry.parameters)})", icon='PREFERENCES')
            col = p_box.column(align=True)
            for name in entry.parameters:
                col.label(text=name)

        # ── Static Switches ───────────────────────────────────────────────────
        if entry.switches:
            sw_box = layout.box()
            sw_box.label(text=f"Static Switches  ({len(entry.switches)})", icon='PANEL_CLOSE')
            col = sw_box.column(align=True)
            for sw in entry.switches:
                row = col.row(align=True)
                icon = 'CHECKBOX_HLT' if sw.on_by_default else 'CHECKBOX_DEHLT'
                row.label(text=sw.name, icon=icon)
                if sw.on_by_default:
                    row.label(text="on by default")

        # ── Textures ──────────────────────────────────────────────────────────
        if entry.textures:
            tex_box = layout.box()
            tex_box.label(text=f"Texture Slots  ({len(entry.textures)})", icon='TEXTURE')
            col = tex_box.column(align=True)
            for tex in entry.textures:
                col.label(text=tex.name, icon='IMAGE_DATA')
                if tex.default_path:
                    col.label(text=f"  {tex.default_path}")
            tex_box.operator("mapgeo.apply_catalog_defaults", icon='ADD')

        # ── Feature Mask ──────────────────────────────────────────────────────
        if entry.feature_mask:
            layout.label(
                text=f"Feature Mask: 0x{entry.feature_mask:08X}",
                icon='MOD_MASK',
            )

        # ── Feature Defines ───────────────────────────────────────────────────
        if entry.feature_defines:
            fd_box = layout.box()
            fd_box.label(
                text=f"Feature Defines  ({len(entry.feature_defines)})",
                icon='DRIVER_TRANSFORM',
            )
            col = fd_box.column(align=True)
            items = list(entry.feature_defines.items())
            for k, v in items[:20]:
                col.label(text=f"{k}  →  {v}")
            if len(items) > 20:
                col.label(text=f"  … and {len(items) - 20} more")


# ── Registration ───────────────────────────────────────────────────────────────

_classes = (
    MAPGEO_OT_load_shaders_bin_catalog,
    MAPGEO_OT_find_shaders_wad,
    MAPGEO_OT_apply_catalog_defaults,
    MATERIAL_PT_league_shader_catalog,
)


def register() -> None:
    _register_properties()
    for cls in _classes:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass


def unregister() -> None:
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _unregister_properties()
