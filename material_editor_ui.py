"""
League Material Editor UI — Blender Properties Panel
Full CRUD for samplers, parameters, switches, macros, and techniques.
Texture edits propagate to the viewport in real-time.
"""

import bpy
import json
import os
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    StringProperty, IntProperty, FloatProperty, BoolProperty,
    CollectionProperty, FloatVectorProperty, EnumProperty,
)
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

try:
    from texture_utils import TexConverter, resolve_texture_path
except ImportError:
    TexConverter = None
    resolve_texture_path = None

try:
    from league_material_enums import (
        MATERIAL_SWITCHES, SHADER_MACROS, SHADER_MACRO_VALUES,
        SAMPLER_TEXTURE_NAMES, SHADER_LINKS,
        PARAMS_ALL, PARAM_TOP_USED,
        PARAMS_ALPHA, PARAMS_COLOR, PARAMS_BLOOM_GLOW, PARAMS_EMISSION,
        PARAMS_DIFFUSE_TEXTURE, PARAMS_SCROLL_ROTATE, PARAMS_DEFORM_WAVE,
        PARAMS_BEND_FOLIAGE, PARAMS_DISTANCE_SEETHROUGH, PARAMS_TRANSITION,
        PARAMS_SPECULAR, PARAMS_FLOW_WATER, PARAMS_DISTORTION, PARAMS_MASK,
        PARAMS_GRADIENT, PARAMS_NOISE, PARAMS_WORLD_OFFSET,
        PARAMS_TRANSLATION_MOVEMENT, PARAMS_FRESNEL, PARAMS_FOG,
        PARAMS_FLIPBOOK, PARAMS_SCANLINE_GLITCH, PARAMS_XYZ_OFFSET,
        PARAMS_UV_AXIS_MASK, PARAMS_LAYER_SYSTEM, PARAMS_MISCELLANEOUS,
    )
    _HAS_ENUMS = True
except ImportError:
    _HAS_ENUMS = False
    MATERIAL_SWITCHES = []
    SHADER_MACROS = []
    SHADER_MACRO_VALUES = {}
    SAMPLER_TEXTURE_NAMES = []
    SHADER_LINKS = []
    PARAMS_ALL = []
    PARAM_TOP_USED = []

# ============================================================================
# Constants
# ============================================================================

# Parameter names that represent colours (used for label hints)
_COLOR_KEYWORDS = {
    "color", "colour", "tint", "glow", "bloom", "shadow", "sun",
    "emission", "overlay", "ripple", "reflection", "refraction",
    "glass", "water", "wave", "prismatic", "specular", "rim",
    "diffuse", "ambient", "starting_color", "switch_color",
    "maincolor", "highcolor", "lowcolor", "undercolor",
}

# Sampler types — full 71 from research + custom option
_SAMPLER_TYPES = SAMPLER_TEXTURE_NAMES[:] if SAMPLER_TEXTURE_NAMES else [
    ("DiffuseTexture", "DiffuseTexture", "Main diffuse / albedo"),
]
_SAMPLER_TYPES.append(("CUSTOM", "Custom...", "Type a custom name"))

# Switch items for dropdown
_SWITCH_ITEMS = MATERIAL_SWITCHES[:] if MATERIAL_SWITCHES else [
    ("NEW_SWITCH", "NEW_SWITCH", "Custom switch"),
]

# Macro items for dropdown
_MACRO_ITEMS = SHADER_MACROS[:] if SHADER_MACROS else [
    ("NO_BAKED_LIGHTING", "NO_BAKED_LIGHTING", "Disable baked lighting"),
]

# Shader links for technique editing
_SHADER_ITEMS = SHADER_LINKS[:] if SHADER_LINKS else [
    ("Shaders/StaticMesh/DefaultEnv_Flat", "DefaultEnv_Flat", "Default flat"),
]
_SHADER_ITEMS.append(("CUSTOM", "Custom...", "Type a custom shader path"))

# Parameter categories for the Add Parameter dropdown
_PARAM_CATEGORIES = [
    ("TOP", "Most Used", "Top ~90 most used parameters"),
    ("ALPHA", "Alpha & Blending", "Alpha, clip, opacity"),
    ("COLOR", "Color & Tint", "Color, tint, blend"),
    ("BLOOM", "Bloom & Glow", "Bloom, glow, radial"),
    ("EMISSION", "Emission", "Emissive lighting"),
    ("DIFFUSE", "Diffuse & Texture", "Texture tiling, offset"),
    ("SCROLL", "Scroll & Rotate", "UV scroll/rotation speed"),
    ("DEFORM", "Deform & Wave", "Wave, deformation"),
    ("BEND", "Bend & Foliage", "Foliage, wind, bending"),
    ("DISTANCE", "Distance", "See-through, scale"),
    ("TRANSITION", "Transition", "Transition effects"),
    ("SPECULAR", "Specular", "Specular highlights"),
    ("FLOW", "Flow & Water", "Flow maps, water"),
    ("DISTORTION", "Distortion", "UV distortion"),
    ("MASK", "Mask", "Mask parameters"),
    ("GRADIENT", "Gradient", "Gradient effects"),
    ("NOISE", "Noise", "Noise generation"),
    ("WORLD", "World Offset", "World-space offsets"),
    ("TRANSLATE", "Translation", "Translation/movement"),
    ("FRESNEL", "Fresnel", "Fresnel effects"),
    ("FOG", "Fog", "Fog / depth fog"),
    ("FLIPBOOK", "Flipbook", "Flipbook animation"),
    ("SCANLINE", "Scanline & Glitch", "Scanlines, glitch, pixelate"),
    ("XYZ", "XYZ Offset", "Per-axis offsets"),
    ("UV_AXIS", "UV Axis Mask", "UV axis mask params"),
    ("LAYER", "Layer System", "Multi-layer blending"),
    ("MISC", "Miscellaneous", "Other/uncategorized"),
]

def _get_param_items_for_category(category):
    """Return the parameter enum items for a given category key."""
    _CAT_MAP = {
        "TOP": PARAM_TOP_USED,
        "ALPHA": PARAMS_ALPHA if _HAS_ENUMS else [],
        "COLOR": PARAMS_COLOR if _HAS_ENUMS else [],
        "BLOOM": PARAMS_BLOOM_GLOW if _HAS_ENUMS else [],
        "EMISSION": PARAMS_EMISSION if _HAS_ENUMS else [],
        "DIFFUSE": PARAMS_DIFFUSE_TEXTURE if _HAS_ENUMS else [],
        "SCROLL": PARAMS_SCROLL_ROTATE if _HAS_ENUMS else [],
        "DEFORM": PARAMS_DEFORM_WAVE if _HAS_ENUMS else [],
        "BEND": PARAMS_BEND_FOLIAGE if _HAS_ENUMS else [],
        "DISTANCE": PARAMS_DISTANCE_SEETHROUGH if _HAS_ENUMS else [],
        "TRANSITION": PARAMS_TRANSITION if _HAS_ENUMS else [],
        "SPECULAR": PARAMS_SPECULAR if _HAS_ENUMS else [],
        "FLOW": PARAMS_FLOW_WATER if _HAS_ENUMS else [],
        "DISTORTION": PARAMS_DISTORTION if _HAS_ENUMS else [],
        "MASK": PARAMS_MASK if _HAS_ENUMS else [],
        "GRADIENT": PARAMS_GRADIENT if _HAS_ENUMS else [],
        "NOISE": PARAMS_NOISE if _HAS_ENUMS else [],
        "WORLD": PARAMS_WORLD_OFFSET if _HAS_ENUMS else [],
        "TRANSLATE": PARAMS_TRANSLATION_MOVEMENT if _HAS_ENUMS else [],
        "FRESNEL": PARAMS_FRESNEL if _HAS_ENUMS else [],
        "FOG": PARAMS_FOG if _HAS_ENUMS else [],
        "FLIPBOOK": PARAMS_FLIPBOOK if _HAS_ENUMS else [],
        "SCANLINE": PARAMS_SCANLINE_GLITCH if _HAS_ENUMS else [],
        "XYZ": PARAMS_XYZ_OFFSET if _HAS_ENUMS else [],
        "UV_AXIS": PARAMS_UV_AXIS_MASK if _HAS_ENUMS else [],
        "LAYER": PARAMS_LAYER_SYSTEM if _HAS_ENUMS else [],
        "MISC": PARAMS_MISCELLANEOUS if _HAS_ENUMS else [],
    }
    return _CAT_MAP.get(category, PARAM_TOP_USED)

_BLEND_FACTORS = {
    0: "ZERO", 1: "ONE", 2: "SRC_COLOR", 3: "INV_SRC_COLOR",
    4: "SRC_ALPHA", 5: "INV_SRC_ALPHA", 6: "DST_ALPHA",
    7: "INV_DST_ALPHA", 8: "DST_COLOR", 9: "INV_DST_COLOR",
    10: "SRC_ALPHA_SAT",
}


# ============================================================================
# Shader Template Data (loaded from JSON extracted from 9,509 game materials)
# ============================================================================

_SHADER_TEMPLATES = {}
_SHADER_TEMPLATE_ITEMS = []

try:
    _tpl_path = Path(__file__).parent / "shader_templates_data.json"
    if _tpl_path.exists():
        with open(_tpl_path, "r", encoding="utf-8") as _f:
            _SHADER_TEMPLATES = json.load(_f)

        # Build enum items sorted by material count (most used first)
        _sorted = sorted(
            _SHADER_TEMPLATES.items(),
            key=lambda x: -x[1].get("material_count", 0),
        )
        for _path, _tpl in _sorted:
            _short = _tpl.get("short_name", _path.rsplit("/", 1)[-1])
            _cnt = _tpl.get("material_count", 0)
            _samp = len(_tpl.get("samplers", []))
            _parm = len(_tpl.get("parameters", []))
            _sw = len(_tpl.get("switches", []))
            _desc = f"{_cnt} materials | {_samp} samplers, {_parm} params, {_sw} switches"
            _SHADER_TEMPLATE_ITEMS.append((_path, _short, _desc))
except Exception:
    pass

if not _SHADER_TEMPLATE_ITEMS:
    _SHADER_TEMPLATE_ITEMS = [
        ("Shaders/StaticMesh/DefaultEnv_Flat", "DefaultEnv_Flat", "Default flat"),
    ]

# ============================================================================
# Property Groups
# ============================================================================

class MAPGEO_MaterialParameterProperty(PropertyGroup):
    param_name: StringProperty(name="Name", default="")
    value_x: FloatProperty(name="X", default=0.0)
    value_y: FloatProperty(name="Y", default=0.0)
    value_z: FloatProperty(name="Z", default=0.0)
    value_w: FloatProperty(name="W", default=0.0)


class MAPGEO_MaterialSwitchProperty(PropertyGroup):
    switch_name: StringProperty(name="Name", default="")
    enabled: BoolProperty(name="On", default=False)


class MAPGEO_MaterialEditorProperties(PropertyGroup):
    selected_shader: StringProperty(name="Shader", default="")
    material_name: StringProperty(name="Material Name", default="New_Material")
    parameters: CollectionProperty(type=MAPGEO_MaterialParameterProperty)
    parameter_index: IntProperty(default=0)
    switches: CollectionProperty(type=MAPGEO_MaterialSwitchProperty)
    switch_index: IntProperty(default=0)


# ============================================================================
# Helpers
# ============================================================================

def _is_color_param(name: str) -> bool:
    """Heuristic: does *name* look like it stores a colour?"""
    lower = name.lower().replace("_", "")
    for kw in _COLOR_KEYWORDS:
        if kw.replace("_", "") in lower:
            return True
    return False


def _param_labels(name: str):
    """Return (label0 ... label3) for a parameter depending on its name."""
    if _is_color_param(name):
        return ("R", "G", "B", "A")
    return ("X", "Y", "Z", "W")


def _tag_redraw(context):
    """Force PROPERTIES and 3D-viewport areas to repaint."""
    for area in context.screen.areas:
        if area.type in ('PROPERTIES', 'VIEW_3D'):
            area.tag_redraw()


def _fmt(v, width=6):
    """Format a float to 4 decimals."""
    return f"{v:.4f}"


def _sync_sampler_texture(mat, sampler_index, texture_path):
    """
    Update the JSON sampler path AND try to push the corresponding
    PNG into the Blender node-tree so the viewport reflects the change.

    Returns (success: bool, message: str).
    """
    if not mat or "samplers" not in mat:
        return False, "Material has no samplers"

    try:
        samplers = json.loads(mat["samplers"])
        if not (0 <= sampler_index < len(samplers)):
            return False, f"Invalid sampler index {sampler_index}"

        if not texture_path:
            return False, "Path cannot be empty"

        tex_path = texture_path
        if not tex_path.lower().endswith(('.tex', '.dds', '.png')):
            tex_path += '.tex'

        # Resolve the on-disk file ------------------------------------------
        assets_folder = None
        custom_assets_folder = None
        prioritize_custom = False
        if hasattr(bpy.context.scene, 'mapgeo_settings'):
            assets_folder = bpy.context.scene.mapgeo_settings.assets_folder
            custom_assets_folder = bpy.context.scene.mapgeo_settings.custom_assets_folder
            prioritize_custom = bpy.context.scene.mapgeo_settings.prioritize_custom_assets

        resolved_path = None
        if (assets_folder or custom_assets_folder) and resolve_texture_path:
            resolved_path = resolve_texture_path(tex_path, assets_folder, custom_assets_folder, prioritize_custom)
            if not resolved_path and tex_path.lower().startswith('assets/'):
                resolved_path = resolve_texture_path(tex_path[7:], assets_folder, custom_assets_folder, prioritize_custom)
            if not resolved_path:
                # Manual fallback check - try both folders
                for folder in [assets_folder, custom_assets_folder]:
                    if not folder:
                        continue
                    test = os.path.join(
                        folder,
                        tex_path.replace('ASSETS/', '').replace('/', os.sep),
                    )
                    base = test.rsplit('.', 1)[0] if '.' in test else test
                    for ext in ('.tex', '.dds', '.png'):
                        if os.path.exists(base + ext):
                            resolved_path = base + ext
                            break
                    if resolved_path:
                        break
                        break
        elif os.path.exists(tex_path):
            resolved_path = tex_path

        # Write the JSON ----------------------------------------------------
        old_path = samplers[sampler_index].get('texturePath', '')
        samplers[sampler_index]["texturePath"] = tex_path
        mat["samplers"] = json.dumps(samplers)
        message = f"Path: '{old_path}' -> '{tex_path}'"

        # Push into Blender node tree --------------------------------------
        if resolved_path and TexConverter:
            try:
                converter = TexConverter()
                png_path = None
                low = resolved_path.lower()
                if low.endswith('.dds'):
                    png_path = converter.convert_dds_to_png(resolved_path)
                else:
                    png_path = converter.convert_tex_to_png(resolved_path)

                if png_path and os.path.exists(png_path):
                    if mat.use_nodes and mat.node_tree:
                        # Try to find the correct image node.
                        # First look for a node whose label matches the sampler name.
                        sampler_name = samplers[sampler_index].get('textureName', '')
                        target_node = None
                        for node in mat.node_tree.nodes:
                            if node.type == 'TEX_IMAGE':
                                if node.label == sampler_name:
                                    target_node = node
                                    break
                        # Fallback: first TEX_IMAGE node
                        if target_node is None:
                            for node in mat.node_tree.nodes:
                                if node.type == 'TEX_IMAGE':
                                    target_node = node
                                    break
                        if target_node:
                            img = bpy.data.images.load(png_path, check_existing=True)
                            target_node.image = img
                            message += f" | viewport updated ({os.path.basename(png_path)})"
                        else:
                            message += " | no image node found"
                else:
                    message += " | conversion failed"
            except Exception as exc:
                message += f" | node update error: {exc}"
        elif not resolved_path:
            message += " | path not resolved (will export correctly)"

        return True, message
    except Exception as exc:
        return False, f"Error: {exc}"


# ============================================================================
# Operators - File Import / Export / Management
# ============================================================================

class MAPGEO_OT_import_materials_file(Operator):
    """Import materials from a League .materials.py file"""
    bl_idname = "mapgeo.import_materials_file"
    bl_label = "Import Materials File"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        try:
            from import_materials_blender import import_materials_from_file
            mats = import_materials_from_file(self.filepath, create_textures=True)
            self.report({'INFO'}, f"Imported {len(mats)} materials")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MAPGEO_OT_assign_material_to_mesh(Operator):
    """Assign material to the active mesh"""
    bl_idname = "mapgeo.assign_material_to_mesh"
    bl_label = "Assign Material"
    bl_options = {'REGISTER', 'UNDO'}

    material_name: StringProperty()

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh first")
            return {'CANCELLED'}
        mat = bpy.data.materials.get(self.material_name)
        if not mat:
            self.report({'ERROR'}, f"Material '{self.material_name}' not found")
            return {'CANCELLED'}
        try:
            from import_materials_blender import assign_material_to_object
            assign_material_to_object(obj, mat)
        except Exception:
            if mat.name not in [s.material.name for s in obj.material_slots if s.material]:
                obj.data.materials.append(mat)
        self.report({'INFO'}, f"Assigned '{self.material_name}'")
        return {'FINISHED'}


class MAPGEO_OT_create_material_from_template(Operator):
    """Create a new League material from a shader template (91 shaders, extracted from 9,509 game materials)"""
    bl_idname = "mapgeo.create_material_from_template"
    bl_label = "Create from Shader Template"
    bl_options = {'REGISTER', 'UNDO'}

    shader_template: EnumProperty(
        name="Shader",
        items=_SHADER_TEMPLATE_ITEMS,
        description="Select a shader — material will be pre-populated with its typical samplers, parameters, switches, and macros",
    )
    new_name: StringProperty(name="Material Name", default="New_Material")
    include_low_freq: BoolProperty(
        name="Include Rare Properties",
        default=False,
        description="Also include parameters/switches that appear in <10% of materials using this shader",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "shader_template")
        layout.prop(self, "new_name")
        layout.prop(self, "include_low_freq")

        # Show template preview
        tpl = _SHADER_TEMPLATES.get(self.shader_template)
        if tpl:
            box = layout.box()
            box.label(text="Template Preview:", icon='INFO')
            threshold = 0 if self.include_low_freq else 10

            samplers = [s for s in tpl.get("samplers", []) if s.get("frequency", 0) >= threshold]
            params = [p for p in tpl.get("parameters", []) if p.get("frequency", 0) >= threshold]
            switches = [s for s in tpl.get("switches", []) if s.get("frequency", 0) >= threshold]
            macros = tpl.get("macros", {})
            blend = tpl.get("blend", {})

            col = box.column(align=True)
            col.label(text=f"Samplers: {len(samplers)}", icon='IMAGE_DATA')
            for s in samplers[:6]:
                col.label(text=f"    {s['name']} ({s['frequency']:.0f}%)")
            if len(samplers) > 6:
                col.label(text=f"    ... +{len(samplers) - 6} more")

            col.separator()
            col.label(text=f"Parameters: {len(params)}", icon='SETTINGS')
            for p in params[:6]:
                v = p.get("value", [0,0,0,0])
                col.label(text=f"    {p['name']} = [{v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f}, {v[3]:.2f}]")
            if len(params) > 6:
                col.label(text=f"    ... +{len(params) - 6} more")

            col.separator()
            col.label(text=f"Switches: {len(switches)}", icon='CHECKBOX_HLT')
            for s in switches[:6]:
                state = "ON" if s.get("on") else "OFF"
                col.label(text=f"    {s['name']} = {state}")
            if len(switches) > 6:
                col.label(text=f"    ... +{len(switches) - 6} more")

            if macros:
                col.separator()
                col.label(text=f"Macros: {len(macros)}", icon='SCRIPT')
                for mn, mv in list(macros.items())[:4]:
                    col.label(text=f"    {mn} = {mv}")

            if blend.get("blendEnable"):
                col.separator()
                src = _BLEND_FACTORS.get(blend.get("srcColorBlendFactor", 1), "?")
                dst = _BLEND_FACTORS.get(blend.get("dstColorBlendFactor", 0), "?")
                col.label(text=f"Blend: {src} -> {dst}", icon='MOD_OPACITY')

    def execute(self, context):
        tpl = _SHADER_TEMPLATES.get(self.shader_template)
        if not tpl:
            self.report({'ERROR'}, f"Template not found for: {self.shader_template}")
            return {'CANCELLED'}

        threshold = 0 if self.include_low_freq else 10

        # Create new material
        mat = bpy.data.materials.new(name=self.new_name)
        mat.use_nodes = True
        short_name = tpl.get("short_name", self.shader_template.rsplit("/", 1)[-1])

        # League metadata
        mat["league_material_name"] = self.new_name
        mat["league_material_type"] = "StaticMaterialDef"

        # Samplers
        samplers = []
        for s in tpl.get("samplers", []):
            if s.get("frequency", 0) >= threshold:
                samplers.append({
                    "textureName": s["name"],
                    "texturePath": "",
                    "addressU": s.get("addressU", 1),
                    "addressV": s.get("addressV", 1),
                    "addressW": s.get("addressW", 1),
                })
        mat["samplers"] = json.dumps(samplers)

        # Parameters
        params = []
        for p in tpl.get("parameters", []):
            if p.get("frequency", 0) >= threshold:
                params.append({
                    "name": p["name"],
                    "value": p.get("value", [0, 0, 0, 0]),
                })
        mat["parameters"] = json.dumps(params)

        # Switches
        switches = []
        for s in tpl.get("switches", []):
            if s.get("frequency", 0) >= threshold:
                switches.append({
                    "name": s["name"],
                    "on": s.get("on", False),
                })
        mat["switches"] = json.dumps(switches)

        # Macros
        mat["shader_macros"] = json.dumps(tpl.get("macros", {}))

        # Techniques
        blend = tpl.get("blend", {})
        technique = {
            "name": "normal",
            "passes": [{
                "shader": self.shader_template,
                "blendEnable": blend.get("blendEnable", False),
                "srcColorBlendFactor": blend.get("srcColorBlendFactor", 1),
                "dstColorBlendFactor": blend.get("dstColorBlendFactor", 0),
                "srcAlphaBlendFactor": blend.get("srcAlphaBlendFactor", 1),
                "dstAlphaBlendFactor": blend.get("dstAlphaBlendFactor", 0),
            }],
        }
        mat["techniques"] = json.dumps([technique])

        # Child techniques
        children = tpl.get("child_techniques", [])
        if children:
            child_list = []
            for cn in children:
                child_list.append({
                    "name": cn,
                    "parentName": "normal",
                    "shaderMacros": {"ENV_TRANSITION": "1"} if cn == "env_transition" else {},
                })
            mat["child_techniques"] = json.dumps(child_list)
        else:
            mat["child_techniques"] = json.dumps([])

        _tag_redraw(context)
        self.report(
            {'INFO'},
            f"Created '{mat.name}' from {short_name} template "
            f"({len(samplers)} samplers, {len(params)} params, {len(switches)} switches)",
        )
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)


class MAPGEO_OT_duplicate_material(Operator):
    """Duplicate an existing League material as a new one"""
    bl_idname = "mapgeo.duplicate_material"
    bl_label = "Duplicate Material"
    bl_options = {'REGISTER', 'UNDO'}

    source_material: StringProperty(name="Source")
    new_name: StringProperty(name="New Name", default="New_Material")

    def execute(self, context):
        tmpl = bpy.data.materials.get(self.source_material)
        if not tmpl:
            self.report({'ERROR'}, "Source material not found")
            return {'CANCELLED'}
        new = tmpl.copy()
        new.name = self.new_name
        self.report({'INFO'}, f"Created '{new.name}' (duplicated from '{tmpl.name}')")
        return {'FINISHED'}


class MAPGEO_OT_export_materials_to_file(Operator):
    """Export all League materials to .materials.py"""
    bl_idname = "mapgeo.export_materials_to_file"
    bl_label = "Export Materials"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', default="materials.py")

    def execute(self, context):
        try:
            from export_materials_blender import export_blender_materials_to_league
            n = export_blender_materials_to_league(self.filepath)
            self.report({'INFO'}, f"Exported {n} materials")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MAPGEO_OT_export_materials_merge_file(Operator):
    """Export materials merged with an existing .materials.py file (preserves VFX, containers, etc.)"""
    bl_idname = "mapgeo.export_materials_merge_file"
    bl_label = "Export Materials (Merge)"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        import os
        try:
            from export_materials_blender import export_blender_materials_merge
            source = self.filepath
            if not os.path.isfile(source):
                self.report({'ERROR'}, f"Source file not found: {source}")
                return {'CANCELLED'}
            base, ext = os.path.splitext(source)
            output = f"{base}_export{ext}"
            n = export_blender_materials_merge(source, output)
            self.report({'INFO'}, f"Exported {n} materials merged with {os.path.basename(source)} -> {os.path.basename(output)}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MAPGEO_OT_view_material_properties(Operator):
    """Print all League properties of the active material to the console"""
    bl_idname = "mapgeo.view_material_properties"
    bl_label = "View Properties"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        if not obj or not obj.data or not obj.data.materials:
            self.report({'ERROR'}, "No material on active object")
            return {'CANCELLED'}
        mat = obj.data.materials[0]
        keys = [
            'league_material_name', 'league_material_type',
            'samplers', 'parameters', 'switches',
            'shader_macros', 'techniques', 'child_techniques',
        ]
        print(f"\n{'=' * 72}\n  {mat.name}\n{'=' * 72}")
        for k in keys:
            if k not in mat:
                continue
            v = mat[k]
            if isinstance(v, str) and k != 'league_material_name':
                try:
                    v = json.loads(v)
                    print(f"\n{k}:\n{json.dumps(v, indent=2)}")
                except Exception:
                    print(f"{k}: {v}")
            else:
                print(f"{k}: {v}")
        self.report({'INFO'}, "Printed to console")
        return {'FINISHED'}


# ============================================================================
# Operators - Samplers
# ============================================================================

class MAPGEO_OT_add_sampler(Operator):
    """Add a texture sampler to this material"""
    bl_idname = "mapgeo.add_sampler"
    bl_label = "Add Sampler"
    bl_options = {'REGISTER', 'UNDO'}

    sampler_type: EnumProperty(
        name="Sampler Type", items=_SAMPLER_TYPES, default="DiffuseTexture",
        description="Select from 71 known League sampler types",
    )
    custom_name: StringProperty(name="Custom Name", default="NewSampler")
    texture_path: StringProperty(name="Texture Path", default="")
    address_u: IntProperty(name="Address U", default=1, min=0, max=4)
    address_v: IntProperty(name="Address V", default=1, min=0, max=4)
    address_w: IntProperty(name="Address W", default=1, min=0, max=4)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "sampler_type")
        if self.sampler_type == "CUSTOM":
            layout.prop(self, "custom_name")
        layout.prop(self, "texture_path", icon='FILE_IMAGE')
        row = layout.row(align=True)
        row.label(text="Address Mode:")
        row.prop(self, "address_u", text="U")
        row.prop(self, "address_v", text="V")
        row.prop(self, "address_w", text="W")

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        tex_name = self.custom_name if self.sampler_type == "CUSTOM" else self.sampler_type
        tex_path = self.texture_path
        if tex_path and not tex_path.lower().endswith(('.tex', '.dds', '.png')):
            tex_path += '.tex'
        samplers = json.loads(mat.get("samplers", "[]"))
        samplers.append({
            "textureName": tex_name,
            "texturePath": tex_path,
            "addressU": self.address_u,
            "addressV": self.address_v,
            "addressW": self.address_w,
        })
        mat["samplers"] = json.dumps(samplers)

        # Try to sync viewport
        if tex_path:
            _sync_sampler_texture(mat, len(samplers) - 1, tex_path)

        _tag_redraw(context)
        self.report({'INFO'}, f"Added sampler '{tex_name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)


class MAPGEO_OT_edit_sampler(Operator):
    """Edit an existing sampler (texture path syncs to viewport)"""
    bl_idname = "mapgeo.edit_sampler"
    bl_label = "Edit Sampler"
    bl_options = {'REGISTER', 'UNDO'}

    sampler_index: IntProperty()
    texture_name: StringProperty(name="Sampler Name")
    texture_path: StringProperty(name="Texture Path")
    address_u: IntProperty(name="U", min=0, max=4)
    address_v: IntProperty(name="V", min=0, max=4)
    address_w: IntProperty(name="W", min=0, max=4)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "texture_name")
        layout.prop(self, "texture_path", icon='FILE_IMAGE')
        row = layout.row(align=True)
        row.label(text="Address Mode:")
        row.prop(self, "address_u")
        row.prop(self, "address_v")
        row.prop(self, "address_w")

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        samplers = json.loads(mat.get("samplers", "[]"))
        if not (0 <= self.sampler_index < len(samplers)):
            return {'CANCELLED'}
        samplers[self.sampler_index].update({
            "textureName": self.texture_name,
            "addressU": self.address_u,
            "addressV": self.address_v,
            "addressW": self.address_w,
        })
        mat["samplers"] = json.dumps(samplers)

        ok, msg = _sync_sampler_texture(mat, self.sampler_index, self.texture_path)
        _tag_redraw(context)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}

    def invoke(self, context, event):
        mat = context.material
        try:
            s = json.loads(mat["samplers"])[self.sampler_index]
            self.texture_name = s.get("textureName", "")
            self.texture_path = s.get("texturePath", "")
            self.address_u = s.get("addressU", 1)
            self.address_v = s.get("addressV", 1)
            self.address_w = s.get("addressW", 1)
        except Exception:
            pass
        return context.window_manager.invoke_props_dialog(self, width=520)


class MAPGEO_OT_remove_sampler(Operator):
    """Remove a sampler from this material"""
    bl_idname = "mapgeo.remove_sampler"
    bl_label = "Remove Sampler"
    bl_options = {'REGISTER', 'UNDO'}

    sampler_index: IntProperty()

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        samplers = json.loads(mat.get("samplers", "[]"))
        if 0 <= self.sampler_index < len(samplers):
            removed = samplers.pop(self.sampler_index)
            mat["samplers"] = json.dumps(samplers)
            _tag_redraw(context)
            self.report({'INFO'}, f"Removed '{removed.get('textureName', '?')}'")
            return {'FINISHED'}
        return {'CANCELLED'}


class MAPGEO_OT_browse_sampler_texture(Operator):
    """Pick a texture file from disk and assign it to a sampler"""
    bl_idname = "mapgeo.browse_sampler_texture"
    bl_label = "Browse Texture"
    bl_options = {'REGISTER', 'UNDO'}

    sampler_index: IntProperty()
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.tex;*.dds;*.png;*.tga;*.jpg", options={'HIDDEN'})

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        ok, msg = _sync_sampler_texture(mat, self.sampler_index, self.filepath)
        _tag_redraw(context)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================================
# Operators - Parameters (vec4)
# ============================================================================

def _get_param_items_cb(self, context):
    """Dynamic callback for parameter enum items based on selected category."""
    items = _get_param_items_for_category(self.param_category)
    if not items:
        return [("NewParam", "NewParam", "Custom parameter")]
    return items


class MAPGEO_OT_add_parameter(Operator):
    """Add a shader parameter (vec4) from the League template library (627 params)"""
    bl_idname = "mapgeo.add_parameter"
    bl_label = "Add Parameter"
    bl_options = {'REGISTER', 'UNDO'}

    param_category: EnumProperty(
        name="Category",
        items=_PARAM_CATEGORIES,
        default="TOP",
        description="Parameter category (627 params in 26 groups)",
    )
    param_name: EnumProperty(
        name="Parameter",
        items=_get_param_items_cb,
        description="Select a known League parameter",
    )
    value_x: FloatProperty(name="X / R", default=0.0, step=1, precision=4)
    value_y: FloatProperty(name="Y / G", default=0.0, step=1, precision=4)
    value_z: FloatProperty(name="Z / B", default=0.0, step=1, precision=4)
    value_w: FloatProperty(name="W / A", default=0.0, step=1, precision=4)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "param_category")
        layout.prop(self, "param_name")
        box = layout.box()
        box.label(text="Value (vec4):")
        col = box.column(align=True)
        lbl = _param_labels(self.param_name)
        col.prop(self, "value_x", text=lbl[0])
        col.prop(self, "value_y", text=lbl[1])
        col.prop(self, "value_z", text=lbl[2])
        col.prop(self, "value_w", text=lbl[3])

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        params = json.loads(mat.get("parameters", "[]"))
        params.append({
            "name": self.param_name,
            "value": [self.value_x, self.value_y, self.value_z, self.value_w],
        })
        mat["parameters"] = json.dumps(params)
        _tag_redraw(context)
        self.report({'INFO'}, f"Added '{self.param_name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)


class MAPGEO_OT_edit_parameter(Operator):
    """Edit a shader parameter name and vec4 value"""
    bl_idname = "mapgeo.edit_parameter"
    bl_label = "Edit Parameter"
    bl_options = {'REGISTER', 'UNDO'}

    param_index: IntProperty()
    param_name: StringProperty(name="Name")
    value_x: FloatProperty(name="X / R", step=1, precision=4)
    value_y: FloatProperty(name="Y / G", step=1, precision=4)
    value_z: FloatProperty(name="Z / B", step=1, precision=4)
    value_w: FloatProperty(name="W / A", step=1, precision=4)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "param_name")
        box = layout.box()
        box.label(text="Value (vec4):")
        col = box.column(align=True)
        lbl = _param_labels(self.param_name)
        col.prop(self, "value_x", text=lbl[0])
        col.prop(self, "value_y", text=lbl[1])
        col.prop(self, "value_z", text=lbl[2])
        col.prop(self, "value_w", text=lbl[3])

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        params = json.loads(mat.get("parameters", "[]"))
        if not (0 <= self.param_index < len(params)):
            return {'CANCELLED'}
        params[self.param_index] = {
            "name": self.param_name,
            "value": [self.value_x, self.value_y, self.value_z, self.value_w],
        }
        mat["parameters"] = json.dumps(params)
        _tag_redraw(context)
        self.report({'INFO'}, f"Updated '{self.param_name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        mat = context.material
        try:
            p = json.loads(mat["parameters"])[self.param_index]
            self.param_name = p.get("name", "")
            v = p.get("value")
            if v and len(v) >= 4:
                self.value_x, self.value_y, self.value_z, self.value_w = v[0], v[1], v[2], v[3]
            elif v and len(v) >= 1:
                self.value_x = v[0]
                self.value_y = v[1] if len(v) > 1 else 0.0
                self.value_z = v[2] if len(v) > 2 else 0.0
                self.value_w = v[3] if len(v) > 3 else 0.0
            else:
                self.value_x = self.value_y = self.value_z = self.value_w = 0.0
        except Exception:
            pass
        return context.window_manager.invoke_props_dialog(self, width=400)


class MAPGEO_OT_remove_parameter(Operator):
    """Remove a shader parameter"""
    bl_idname = "mapgeo.remove_parameter"
    bl_label = "Remove Parameter"
    bl_options = {'REGISTER', 'UNDO'}

    param_index: IntProperty()

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        params = json.loads(mat.get("parameters", "[]"))
        if 0 <= self.param_index < len(params):
            removed = params.pop(self.param_index)
            mat["parameters"] = json.dumps(params)
            _tag_redraw(context)
            self.report({'INFO'}, f"Removed '{removed.get('name', '?')}'")
            return {'FINISHED'}
        return {'CANCELLED'}


# ============================================================================
# Operators - Switches
# ============================================================================

class MAPGEO_OT_add_switch(Operator):
    """Add a boolean switch from the League template library (180 switches)"""
    bl_idname = "mapgeo.add_switch"
    bl_label = "Add Switch"
    bl_options = {'REGISTER', 'UNDO'}

    switch_name: EnumProperty(
        name="Switch",
        items=_SWITCH_ITEMS,
        description="Select from 180 known League material switches",
    )
    enabled: BoolProperty(name="Enabled", default=False)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "switch_name")
        layout.prop(self, "enabled")

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        switches = json.loads(mat.get("switches", "[]"))
        # Check for duplicates
        existing = {s.get("name") for s in switches}
        if self.switch_name in existing:
            self.report({'WARNING'}, f"Switch '{self.switch_name}' already exists")
            return {'CANCELLED'}
        switches.append({"name": self.switch_name, "on": self.enabled})
        mat["switches"] = json.dumps(switches)
        _tag_redraw(context)
        self.report({'INFO'}, f"Added switch '{self.switch_name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


class MAPGEO_OT_toggle_switch(Operator):
    """Toggle a switch on / off"""
    bl_idname = "mapgeo.toggle_switch"
    bl_label = "Toggle Switch"
    bl_options = {'REGISTER', 'UNDO'}

    switch_index: IntProperty()

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        switches = json.loads(mat.get("switches", "[]"))
        if 0 <= self.switch_index < len(switches):
            switches[self.switch_index]["on"] = not switches[self.switch_index].get("on", False)
            mat["switches"] = json.dumps(switches)
            _tag_redraw(context)
            state = "ON" if switches[self.switch_index]["on"] else "OFF"
            self.report({'INFO'}, f"{switches[self.switch_index]['name']} -> {state}")
            return {'FINISHED'}
        return {'CANCELLED'}


class MAPGEO_OT_remove_switch(Operator):
    """Remove a switch"""
    bl_idname = "mapgeo.remove_switch"
    bl_label = "Remove Switch"
    bl_options = {'REGISTER', 'UNDO'}

    switch_index: IntProperty()

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        switches = json.loads(mat.get("switches", "[]"))
        if 0 <= self.switch_index < len(switches):
            removed = switches.pop(self.switch_index)
            mat["switches"] = json.dumps(switches)
            _tag_redraw(context)
            self.report({'INFO'}, f"Removed '{removed.get('name', '?')}'")
            return {'FINISHED'}
        return {'CANCELLED'}


# ============================================================================
# Operators - Shader Macros
# ============================================================================

class MAPGEO_OT_add_macro(Operator):
    """Add a shader macro from the League template library (14 macros)"""
    bl_idname = "mapgeo.add_macro"
    bl_label = "Add Macro"
    bl_options = {'REGISTER', 'UNDO'}

    macro_name: EnumProperty(
        name="Macro",
        items=_MACRO_ITEMS,
        description="Select from 14 known League shader macros",
    )
    macro_value: StringProperty(name="Value", default="1")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "macro_name")
        layout.prop(self, "macro_value")
        # Show known values hint
        if _HAS_ENUMS and self.macro_name in SHADER_MACRO_VALUES:
            vals = SHADER_MACRO_VALUES[self.macro_name]
            if vals:
                layout.label(text=f"Known values: {', '.join(vals)}", icon='INFO')

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        macros = json.loads(mat.get("shader_macros", "{}"))
        if self.macro_name in macros:
            self.report({'WARNING'}, f"Macro '{self.macro_name}' already exists — updating value")
        macros[self.macro_name] = self.macro_value
        mat["shader_macros"] = json.dumps(macros)
        _tag_redraw(context)
        self.report({'INFO'}, f"Added macro '{self.macro_name}' = '{self.macro_value}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


class MAPGEO_OT_edit_macro(Operator):
    """Edit a shader macro value"""
    bl_idname = "mapgeo.edit_macro"
    bl_label = "Edit Macro"
    bl_options = {'REGISTER', 'UNDO'}

    macro_name: StringProperty()
    macro_value: StringProperty(name="Value")

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        macros = json.loads(mat.get("shader_macros", "{}"))
        macros[self.macro_name] = self.macro_value
        mat["shader_macros"] = json.dumps(macros)
        _tag_redraw(context)
        self.report({'INFO'}, f"'{self.macro_name}' = '{self.macro_value}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        try:
            macros = json.loads(context.material["shader_macros"])
            self.macro_value = str(macros.get(self.macro_name, ""))
        except Exception:
            pass
        return context.window_manager.invoke_props_dialog(self)


class MAPGEO_OT_remove_macro(Operator):
    """Remove a shader macro"""
    bl_idname = "mapgeo.remove_macro"
    bl_label = "Remove Macro"
    bl_options = {'REGISTER', 'UNDO'}

    macro_name: StringProperty()

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        macros = json.loads(mat.get("shader_macros", "{}"))
        if self.macro_name in macros:
            del macros[self.macro_name]
            mat["shader_macros"] = json.dumps(macros)
            _tag_redraw(context)
            self.report({'INFO'}, f"Removed '{self.macro_name}'")
            return {'FINISHED'}
        return {'CANCELLED'}


# ============================================================================
# Operators - Techniques
# ============================================================================

class MAPGEO_OT_add_technique(Operator):
    """Add a rendering technique with a shader from the template library"""
    bl_idname = "mapgeo.add_technique"
    bl_label = "Add Technique"
    bl_options = {'REGISTER', 'UNDO'}

    technique_name: StringProperty(name="Technique Name", default="normal")
    shader_select: EnumProperty(
        name="Shader",
        items=_SHADER_ITEMS,
        description="Select from 91 known League shaders",
    )
    custom_shader: StringProperty(name="Custom Shader Path", default="")
    blend_enable: BoolProperty(name="Blend Enable", default=False)
    src_color: IntProperty(name="Src Color", min=0, max=10, default=1)
    dst_color: IntProperty(name="Dst Color", min=0, max=10, default=0)
    src_alpha: IntProperty(name="Src Alpha", min=0, max=10, default=1)
    dst_alpha: IntProperty(name="Dst Alpha", min=0, max=10, default=0)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "technique_name")
        layout.separator()
        layout.label(text="Pass Shader:")
        layout.prop(self, "shader_select")
        if self.shader_select == "CUSTOM":
            layout.prop(self, "custom_shader")
        box = layout.box()
        box.label(text="Blend Settings:")
        box.prop(self, "blend_enable")
        if self.blend_enable:
            col = box.column(align=True)
            col.prop(self, "src_color", text=f"Src Color ({_BLEND_FACTORS.get(self.src_color, '?')})")
            col.prop(self, "dst_color", text=f"Dst Color ({_BLEND_FACTORS.get(self.dst_color, '?')})")
            col.prop(self, "src_alpha", text=f"Src Alpha ({_BLEND_FACTORS.get(self.src_alpha, '?')})")
            col.prop(self, "dst_alpha", text=f"Dst Alpha ({_BLEND_FACTORS.get(self.dst_alpha, '?')})")

    def execute(self, context):
        mat = context.material
        if not mat:
            return {'CANCELLED'}
        techniques = json.loads(mat.get("techniques", "[]"))
        shader = self.custom_shader if self.shader_select == "CUSTOM" else self.shader_select
        new_tech = {
            "name": self.technique_name,
            "passes": [{
                "shader": shader,
                "blendEnable": self.blend_enable,
                "srcColorBlendFactor": self.src_color,
                "dstColorBlendFactor": self.dst_color,
                "srcAlphaBlendFactor": self.src_alpha,
                "dstAlphaBlendFactor": self.dst_alpha,
            }],
        }
        techniques.append(new_tech)
        mat["techniques"] = json.dumps(techniques)
        _tag_redraw(context)
        self.report({'INFO'}, f"Added technique '{self.technique_name}' with shader '{shader.rsplit('/', 1)[-1]}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=480)


class MAPGEO_OT_edit_technique_pass(Operator):
    """Edit shader and blend settings for a technique pass"""
    bl_idname = "mapgeo.edit_technique_pass"
    bl_label = "Edit Pass"
    bl_options = {'REGISTER', 'UNDO'}

    technique_index: IntProperty()
    pass_index: IntProperty()
    shader_select: EnumProperty(
        name="Shader",
        items=_SHADER_ITEMS,
        description="Select from 91 known League shaders",
    )
    custom_shader: StringProperty(name="Custom Shader Path", default="")
    apply_template: BoolProperty(
        name="Apply Shader Template",
        description="Update samplers, parameters, switches, and macros from the shader template. Keeps existing DiffuseTexture path",
        default=True,
    )
    blend_enable: BoolProperty(name="Blend Enable", default=False)
    src_color: IntProperty(name="Src Color Factor", min=0, max=10, default=1)
    dst_color: IntProperty(name="Dst Color Factor", min=0, max=10, default=0)
    src_alpha: IntProperty(name="Src Alpha Factor", min=0, max=10, default=1)
    dst_alpha: IntProperty(name="Dst Alpha Factor", min=0, max=10, default=0)

    # Track original shader to detect changes
    _original_shader: str = ""

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "shader_select")
        if self.shader_select == "CUSTOM":
            layout.prop(self, "custom_shader")

        # Show template option when shader changed and template exists
        new_shader = self.custom_shader if self.shader_select == "CUSTOM" else self.shader_select
        shader_changed = new_shader != self._original_shader
        has_template = new_shader in _SHADER_TEMPLATES

        if shader_changed and has_template:
            box = layout.box()
            box.prop(self, "apply_template", icon='FILE_REFRESH')
            if self.apply_template:
                tpl = _SHADER_TEMPLATES[new_shader]
                samp = len(tpl.get("samplers", []))
                parm = len(tpl.get("parameters", []))
                sw = len(tpl.get("switches", []))
                box.label(text=f"Template: {samp} samplers, {parm} params, {sw} switches", icon='INFO')
                box.label(text="DiffuseTexture path will be preserved", icon='IMAGE_DATA')

        box = layout.box()
        box.label(text="Blend Settings:")
        box.prop(self, "blend_enable")
        if self.blend_enable:
            col = box.column(align=True)
            col.prop(self, "src_color", text=f"Src Color ({_BLEND_FACTORS.get(self.src_color, '?')})")
            col.prop(self, "dst_color", text=f"Dst Color ({_BLEND_FACTORS.get(self.dst_color, '?')})")
            col.prop(self, "src_alpha", text=f"Src Alpha ({_BLEND_FACTORS.get(self.src_alpha, '?')})")
            col.prop(self, "dst_alpha", text=f"Dst Alpha ({_BLEND_FACTORS.get(self.dst_alpha, '?')})")

    def execute(self, context):
        mat = context.material
        if not mat or "techniques" not in mat:
            return {'CANCELLED'}
        techniques = json.loads(mat["techniques"])
        if not (0 <= self.technique_index < len(techniques)):
            return {'CANCELLED'}
        passes = techniques[self.technique_index].get("passes", [])
        if not (0 <= self.pass_index < len(passes)):
            return {'CANCELLED'}
        shader = self.custom_shader if self.shader_select == "CUSTOM" else self.shader_select
        shader_changed = shader != self._original_shader

        # Update the pass
        existing = passes[self.pass_index]
        passes[self.pass_index] = {
            "shader": shader,
            "blendEnable": self.blend_enable,
            "srcColorBlendFactor": self.src_color,
            "dstColorBlendFactor": self.dst_color,
            "srcAlphaBlendFactor": self.src_alpha,
            "dstAlphaBlendFactor": self.dst_alpha,
        }
        # Carry forward fields not exposed in the UI
        for key in ("cullEnable", "writeMask", "shaderMacros"):
            if key in existing:
                passes[self.pass_index][key] = existing[key]
        techniques[self.technique_index]["passes"] = passes
        mat["techniques"] = json.dumps(techniques)

        # Apply shader template if shader changed and user opted in
        if shader_changed and self.apply_template and shader in _SHADER_TEMPLATES:
            self._apply_shader_template(mat, shader)

        _tag_redraw(context)
        if shader_changed and self.apply_template and shader in _SHADER_TEMPLATES:
            self.report({'INFO'}, f"Pass updated — shader template applied for {shader.rsplit('/', 1)[-1]}")
        else:
            self.report({'INFO'}, "Pass updated")
        return {'FINISHED'}

    def _apply_shader_template(self, mat, shader_path):
        """Apply shader template data to material, preserving DiffuseTexture path"""
        tpl = _SHADER_TEMPLATES[shader_path]

        # --- Preserve existing DiffuseTexture path ---
        diffuse_path = ""
        try:
            old_samplers = json.loads(mat.get("samplers", "[]"))
            for s in old_samplers:
                if s.get("textureName") == "DiffuseTexture" and s.get("texturePath"):
                    diffuse_path = s["texturePath"]
                    break
        except Exception:
            pass

        # --- Samplers ---
        samplers = []
        for s in tpl.get("samplers", []):
            sampler = {
                "textureName": s["name"],
                "texturePath": "",
                "addressU": s.get("addressU"),
                "addressV": s.get("addressV"),
                "addressW": s.get("addressW"),
            }
            # Restore diffuse texture path
            if s["name"] == "DiffuseTexture" and diffuse_path:
                sampler["texturePath"] = diffuse_path
            samplers.append(sampler)
        mat["samplers"] = json.dumps(samplers)

        # --- Parameters ---
        params = []
        for p in tpl.get("parameters", []):
            params.append({
                "name": p["name"],
                "value": p.get("value", [0, 0, 0, 0]),
            })
        mat["parameters"] = json.dumps(params)

        # --- Switches ---
        switches = []
        for s in tpl.get("switches", []):
            switches.append({
                "name": s["name"],
                "on": s.get("on", False),
            })
        mat["switches"] = json.dumps(switches)

        # --- Material-level shader macros ---
        mat["shader_macros"] = json.dumps(tpl.get("macros", {}))

        # --- Blend settings (update technique pass too) ---
        blend = tpl.get("blend", {})
        try:
            techniques = json.loads(mat.get("techniques", "[]"))
            if techniques and techniques[self.technique_index].get("passes"):
                p = techniques[self.technique_index]["passes"][self.pass_index]
                p["blendEnable"] = blend.get("blendEnable", False)
                p["srcColorBlendFactor"] = blend.get("srcColorBlendFactor", 1)
                p["dstColorBlendFactor"] = blend.get("dstColorBlendFactor", 0)
                p["srcAlphaBlendFactor"] = blend.get("srcAlphaBlendFactor", 1)
                p["dstAlphaBlendFactor"] = blend.get("dstAlphaBlendFactor", 0)
                mat["techniques"] = json.dumps(techniques)
        except Exception:
            pass

        # --- Child techniques ---
        children = tpl.get("child_techniques", [])
        if children:
            child_list = []
            for cn in children:
                child_list.append({
                    "name": cn,
                    "parentName": "normal",
                    "shaderMacros": {"ENV_TRANSITION": "1"} if cn == "env_transition" else {},
                })
            mat["child_techniques"] = json.dumps(child_list)
        else:
            mat["child_techniques"] = json.dumps([])
        self.report({'INFO'}, "Pass updated")
        return {'FINISHED'}

    def invoke(self, context, event):
        mat = context.material
        try:
            tech = json.loads(mat["techniques"])[self.technique_index]
            p = tech["passes"][self.pass_index]
            current_shader = p.get("shader", "")
            self._original_shader = current_shader
            # Try to match to a known shader
            found = False
            for item in _SHADER_ITEMS:
                if item[0] == current_shader:
                    self.shader_select = current_shader
                    found = True
                    break
            if not found:
                self.shader_select = "CUSTOM"
                self.custom_shader = current_shader
            self.blend_enable = p.get("blendEnable", False)
            self.src_color = p.get("srcColorBlendFactor", 1)
            self.dst_color = p.get("dstColorBlendFactor", 0)
            self.src_alpha = p.get("srcAlphaBlendFactor", 1)
            self.dst_alpha = p.get("dstAlphaBlendFactor", 0)
        except Exception:
            self._original_shader = ""
        return context.window_manager.invoke_props_dialog(self, width=480)


# ============================================================================
# Panels - Material Properties > League  (sub-panel hierarchy)
# ============================================================================

class MATERIAL_PT_league_properties(Panel):
    """League Material Properties - parent panel"""
    bl_label = "League Material"
    bl_idname = "MATERIAL_PT_league_properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.material and context.material.get("league_material_name")

    def draw(self, context):
        # Header-only parent; children contain the real content
        pass


# --- Info sub-panel -------------------------------------------------------

class MATERIAL_PT_league_info(Panel):
    """Material name, type, and shader overview"""
    bl_label = "Material Info"
    bl_idname = "MATERIAL_PT_league_info"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"

    def draw(self, context):
        layout = self.layout
        mat = context.material

        col = layout.column(align=True)
        col.label(text=mat.get("league_material_name", "---"), icon='MATERIAL')
        col.label(text=f"Type: {mat.get('league_material_type', 0)}")

        # Show shader from first technique if available
        shader = ""
        try:
            techs = json.loads(mat.get("techniques", "[]"))
            if techs and techs[0].get("passes"):
                shader = techs[0]["passes"][0].get("shader", "")
        except Exception:
            pass
        if shader:
            col.label(text=f"Shader: {shader.rsplit('/', 1)[-1]}", icon='NODE_MATERIAL')
            col.label(text=f"  {shader}")

        # Quick stats
        row = layout.row()
        try:
            n_samp = len(json.loads(mat.get("samplers", "[]")))
            n_par = len(json.loads(mat.get("parameters", "[]")))
            n_sw = len(json.loads(mat.get("switches", "[]")))
            row.label(text=f"{n_samp} samplers  |  {n_par} params  |  {n_sw} switches")
        except Exception:
            pass


# --- Samplers sub-panel ---------------------------------------------------

class MATERIAL_PT_league_samplers(Panel):
    """Texture samplers with path editing and viewport sync"""
    bl_label = "Samplers"
    bl_idname = "MATERIAL_PT_league_samplers"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material
        try:
            samplers = json.loads(mat.get("samplers", "[]"))
        except Exception:
            layout.label(text="Error reading samplers", icon='ERROR')
            return

        if not samplers:
            layout.label(text="No samplers", icon='INFO')
        else:
            for i, s in enumerate(samplers):
                box = layout.box()
                # Header row: name + buttons
                header = box.row()
                header.label(text=s.get("textureName", "?"), icon='TEXTURE')
                header.operator("mapgeo.edit_sampler", text="", icon='GREASEPENCIL').sampler_index = i
                header.operator("mapgeo.browse_sampler_texture", text="", icon='FILEBROWSER').sampler_index = i
                header.operator("mapgeo.remove_sampler", text="", icon='TRASH').sampler_index = i
                # Path
                path = s.get("texturePath", "")
                box.label(text=path if path else "(no path)", icon='FILE_IMAGE')
                # Address modes
                addr = f"U={s.get('addressU', 1)}  V={s.get('addressV', 1)}  W={s.get('addressW', 1)}"
                box.label(text=addr, icon='UV')

        layout.operator("mapgeo.add_sampler", text="Add Sampler", icon='ADD')


# --- Parameters sub-panel -------------------------------------------------

class MATERIAL_PT_league_parameters(Panel):
    """Shader parameters (vec4) with proper float editing"""
    bl_label = "Parameters"
    bl_idname = "MATERIAL_PT_league_parameters"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material
        try:
            params = json.loads(mat.get("parameters", "[]"))
        except Exception:
            layout.label(text="Error reading parameters", icon='ERROR')
            return

        if not params:
            layout.label(text="No parameters", icon='INFO')
        else:
            for i, p in enumerate(params):
                name = p.get("name", "?")
                value = p.get("value")

                box = layout.box()
                # Header
                header = box.row()
                header.label(text=name, icon='PREFERENCES')
                header.operator("mapgeo.edit_parameter", text="", icon='GREASEPENCIL').param_index = i
                header.operator("mapgeo.remove_parameter", text="", icon='TRASH').param_index = i

                # Value row
                if value and isinstance(value, (list, tuple)):
                    lbl = _param_labels(name)
                    row = box.row(align=True)
                    for j, (l, v) in enumerate(zip(lbl, value)):
                        row.label(text=f"{l}: {_fmt(v)}")
                else:
                    box.label(text="value not set - click edit to define", icon='QUESTION')

        layout.operator("mapgeo.add_parameter", text="Add Parameter", icon='ADD')


# --- Switches sub-panel ---------------------------------------------------

class MATERIAL_PT_league_switches(Panel):
    """Boolean shader switches"""
    bl_label = "Switches"
    bl_idname = "MATERIAL_PT_league_switches"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material
        try:
            switches = json.loads(mat.get("switches", "[]"))
        except Exception:
            layout.label(text="Error reading switches", icon='ERROR')
            return

        if not switches:
            layout.label(text="No switches", icon='INFO')
        else:
            for i, sw in enumerate(switches):
                row = layout.row(align=True)
                is_on = sw.get("on", False)
                name = sw.get("name", "?")
                if is_on:
                    op = row.operator("mapgeo.toggle_switch", text=name, icon='CHECKMARK', depress=True)
                else:
                    op = row.operator("mapgeo.toggle_switch", text=name, icon='X', depress=False)
                op.switch_index = i
                row.operator("mapgeo.remove_switch", text="", icon='TRASH').switch_index = i

        layout.operator("mapgeo.add_switch", text="Add Switch", icon='ADD')


# --- Shader Macros sub-panel ----------------------------------------------

class MATERIAL_PT_league_macros(Panel):
    """Compile-time shader macro definitions"""
    bl_label = "Shader Macros"
    bl_idname = "MATERIAL_PT_league_macros"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material
        try:
            macros = json.loads(mat.get("shader_macros", "{}"))
        except Exception:
            layout.label(text="Error reading macros", icon='ERROR')
            return

        if not macros:
            layout.label(text="No macros", icon='INFO')
        else:
            for name, val in macros.items():
                row = layout.row(align=True)
                row.label(text=name, icon='SCRIPT')
                row.label(text=str(val))
                op = row.operator("mapgeo.edit_macro", text="", icon='GREASEPENCIL')
                op.macro_name = name
                op = row.operator("mapgeo.remove_macro", text="", icon='TRASH')
                op.macro_name = name

        layout.operator("mapgeo.add_macro", text="Add Macro", icon='ADD')


# --- Techniques sub-panel -------------------------------------------------

class MATERIAL_PT_league_techniques(Panel):
    """Rendering techniques and passes (shader, blending)"""
    bl_label = "Techniques"
    bl_idname = "MATERIAL_PT_league_techniques"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material

        # --- Main Techniques ---
        try:
            techniques = json.loads(mat.get("techniques", "[]"))
        except Exception:
            techniques = []

        if techniques:
            for ti, tech in enumerate(techniques):
                box = layout.box()
                box.label(text=f"Technique: {tech.get('name', '?')}", icon='RENDERLAYERS')
                passes = tech.get("passes", [])
                for pi, p in enumerate(passes):
                    pbox = box.box()
                    row = pbox.row()
                    shader = p.get("shader", "")
                    short = shader.rsplit("/", 1)[-1] if shader else "(none)"
                    row.label(text=f"Pass {pi}: {short}", icon='NODE_MATERIAL')
                    op = row.operator("mapgeo.edit_technique_pass", text="", icon='GREASEPENCIL')
                    op.technique_index = ti
                    op.pass_index = pi

                    blend = p.get("blendEnable", False)
                    if blend:
                        src = _BLEND_FACTORS.get(p.get("srcColorBlendFactor", 1), "?")
                        dst = _BLEND_FACTORS.get(p.get("dstColorBlendFactor", 0), "?")
                        pbox.label(text=f"Blend: {src} -> {dst}", icon='MOD_OPACITY')
        else:
            layout.label(text="No techniques", icon='INFO')

        layout.operator("mapgeo.add_technique", text="Add Technique", icon='ADD')

        # --- Child Techniques ---
        try:
            children = json.loads(mat.get("child_techniques", "[]"))
        except Exception:
            children = []

        if children:
            layout.separator()
            layout.label(text="Child Techniques:", icon='OUTLINER_OB_GROUP_INSTANCE')
            for ct in children:
                box = layout.box()
                box.label(text=ct.get("name", "?"), icon='LINKED')
                box.label(text=f"Parent: {ct.get('parentName', '?')}")
                macros = ct.get("shaderMacros", {})
                if macros:
                    for mn, mv in macros.items():
                        box.label(text=f"  {mn} = {mv}", icon='SCRIPT')


# ============================================================================
# 3D-Viewport Sidebar Panel
# ============================================================================

class VIEW3D_PT_mapgeo_material_editor_panel(Panel):
    """League Material Editor - 3D Viewport sidebar"""
    bl_label = "Materials Setup"
    bl_idname = "VIEW3D_PT_mapgeo_material_editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        # Import
        box = layout.box()
        box.label(text="Import / Export", icon='FILE_FOLDER')
        box.operator("mapgeo.import_materials_file", text="Import Materials", icon='IMPORT')
        box.operator("mapgeo.export_materials_to_file", text="Export Materials Only", icon='EXPORT')
        box.operator("mapgeo.export_materials_merge_file", text="Export with .materials.py", icon='FILE_BLEND')

        # Material assignment
        box = layout.box()
        box.label(text="Material Management", icon='MATERIAL')
        obj = context.active_object
        if obj and obj.type == 'MESH':
            col = box.column(align=True)
            if bpy.data.materials:
                col.prop_search(
                    context.scene, "mat_editor_search",
                    bpy.data, "materials", text="Material",
                )
                row = col.row(align=True)
                row.operator(
                    "mapgeo.assign_material_to_mesh",
                    text="Assign", icon='MATERIAL_DATA',
                ).material_name = getattr(context.scene, "mat_editor_search", "")
                row.operator("mapgeo.view_material_properties", text="Console", icon='CONSOLE')
        else:
            box.label(text="Select a mesh", icon='ERROR')

        # Create from shader template
        box = layout.box()
        box.label(text="Create Material", icon='ADD')
        col = box.column(align=True)
        col.operator(
            "mapgeo.create_material_from_template",
            text="Create from Shader Template", icon='PRESET_NEW',
        )

        # Duplicate existing
        if bpy.data.materials:
            box = layout.box()
            box.label(text="Duplicate Material", icon='DUPLICATE')
            col = box.column(align=True)
            col.prop_search(
                context.scene, "mat_template_search",
                bpy.data, "materials", text="Source",
            )
            col.prop(context.scene, "mat_new_name", text="Name")
            op = col.operator(
                "mapgeo.duplicate_material",
                text="Duplicate", icon='COPYDOWN',
            )
            op.source_material = getattr(context.scene, "mat_template_search", "")
            op.new_name = getattr(context.scene, "mat_new_name", "New_Material")

        # Quick tip
        box = layout.box()
        box.label(text="Tip: Edit properties in", icon='INFO')
        box.label(text="Properties > Material tab")


# ============================================================================
# Registration
# ============================================================================

def register_material_editor_properties():
    for cls in (MAPGEO_MaterialParameterProperty, MAPGEO_MaterialSwitchProperty, MAPGEO_MaterialEditorProperties):
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    if not hasattr(bpy.types.Scene, "mapgeo_material_props"):
        bpy.types.Scene.mapgeo_material_props = bpy.props.PointerProperty(type=MAPGEO_MaterialEditorProperties)
    if not hasattr(bpy.types.Scene, "mat_editor_search"):
        bpy.types.Scene.mat_editor_search = bpy.props.StringProperty(name="Material", default="")
    if not hasattr(bpy.types.Scene, "mat_template_search"):
        bpy.types.Scene.mat_template_search = bpy.props.StringProperty(name="Template", default="")
    if not hasattr(bpy.types.Scene, "mat_new_name"):
        bpy.types.Scene.mat_new_name = bpy.props.StringProperty(name="New Name", default="New_Material")


def unregister_material_editor_properties():
    for attr in ("mapgeo_material_props", "mat_editor_search", "mat_template_search", "mat_new_name"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in (MAPGEO_MaterialEditorProperties, MAPGEO_MaterialSwitchProperty, MAPGEO_MaterialParameterProperty):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


material_editor_classes = (
    # Property groups (must register first)
    MAPGEO_MaterialParameterProperty,
    MAPGEO_MaterialSwitchProperty,
    MAPGEO_MaterialEditorProperties,
    # File / management operators
    MAPGEO_OT_import_materials_file,
    MAPGEO_OT_assign_material_to_mesh,
    MAPGEO_OT_create_material_from_template,
    MAPGEO_OT_duplicate_material,
    MAPGEO_OT_export_materials_to_file,
    MAPGEO_OT_export_materials_merge_file,
    MAPGEO_OT_view_material_properties,
    # Sampler operators
    MAPGEO_OT_add_sampler,
    MAPGEO_OT_edit_sampler,
    MAPGEO_OT_remove_sampler,
    MAPGEO_OT_browse_sampler_texture,
    # Parameter operators
    MAPGEO_OT_add_parameter,
    MAPGEO_OT_edit_parameter,
    MAPGEO_OT_remove_parameter,
    # Switch operators
    MAPGEO_OT_add_switch,
    MAPGEO_OT_toggle_switch,
    MAPGEO_OT_remove_switch,
    # Macro operators
    MAPGEO_OT_add_macro,
    MAPGEO_OT_edit_macro,
    MAPGEO_OT_remove_macro,
    # Technique operators
    MAPGEO_OT_add_technique,
    MAPGEO_OT_edit_technique_pass,
    # Panels (parent first, then children)
    MATERIAL_PT_league_properties,
    MATERIAL_PT_league_info,
    MATERIAL_PT_league_samplers,
    MATERIAL_PT_league_parameters,
    MATERIAL_PT_league_switches,
    MATERIAL_PT_league_macros,
    MATERIAL_PT_league_techniques,
    # 3D viewport sidebar
    VIEW3D_PT_mapgeo_material_editor_panel,
)


def register():
    register_material_editor_properties()
    for cls in material_editor_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass


def unregister():
    for cls in reversed(material_editor_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    unregister_material_editor_properties()


if __name__ == "__main__":
    register()
