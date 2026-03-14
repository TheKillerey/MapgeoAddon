"""
League Material Editor UI — Blender Properties Panel
Full CRUD for samplers, parameters, switches, macros, and techniques.
Texture edits propagate to the viewport in real-time.
"""

import bpy
import json
import math
import os
import re
from bpy.types import Operator, Panel, PropertyGroup, UIList
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

try:
    from dx11_shader_parser import (
        validate_material_defines,
        find_nearest_valid_defines,
        clear_shader_cache,
    )
    _HAS_SHADER_VALIDATION = True
except ImportError:
    _HAS_SHADER_VALIDATION = False

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
_SHADER_DEFAULT_TEXTURES_BY_PATH = None
_SHADER_DEFAULT_TEXTURES_SOURCE = None
_RIOT_SHADERS_PY_DEFAULT = r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Shaders\Shaders.wad\data\shaders\shaders.py"

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

def _get_riot_shaders_py_path():
    return _RIOT_SHADERS_PY_DEFAULT if os.path.exists(_RIOT_SHADERS_PY_DEFAULT) else ""


def _load_shader_default_textures():
    global _SHADER_DEFAULT_TEXTURES_BY_PATH
    global _SHADER_DEFAULT_TEXTURES_SOURCE

    source_path = _get_riot_shaders_py_path()
    if not source_path:
        _SHADER_DEFAULT_TEXTURES_BY_PATH = {}
        _SHADER_DEFAULT_TEXTURES_SOURCE = ""
        return _SHADER_DEFAULT_TEXTURES_BY_PATH

    if _SHADER_DEFAULT_TEXTURES_BY_PATH is not None and _SHADER_DEFAULT_TEXTURES_SOURCE == source_path:
        return _SHADER_DEFAULT_TEXTURES_BY_PATH

    try:
        with open(source_path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
    except Exception:
        _SHADER_DEFAULT_TEXTURES_BY_PATH = {}
        _SHADER_DEFAULT_TEXTURES_SOURCE = source_path
        return _SHADER_DEFAULT_TEXTURES_BY_PATH

    entries = {}
    entry_pattern = re.compile(
        r'"(Shaders/StaticMesh/[^"]+)"\s*=\s*CustomShaderDef\s*\{(.*?)\n\s*objectPath\s*:\s*string\s*=\s*"\1"',
        re.DOTALL,
    )
    tex_block_pattern = re.compile(r'ShaderTexture\s*\{(.*?)\}', re.DOTALL)
    name_pattern = re.compile(r'name\s*:\s*string\s*=\s*"([^"]+)"')
    path_pattern = re.compile(r'defaultTexturePath\s*:\s*string\s*=\s*"([^"]+)"')

    for shader_path, body in entry_pattern.findall(content):
        sampler_map = {}
        for tex_block in tex_block_pattern.findall(body):
            name_match = name_pattern.search(tex_block)
            path_match = path_pattern.search(tex_block)
            if not name_match or not path_match:
                continue
            sampler_name = name_match.group(1)
            texture_path = path_match.group(1)
            sampler_map[sampler_name.lower()] = texture_path
        if sampler_map:
            entries[shader_path] = sampler_map

    _SHADER_DEFAULT_TEXTURES_BY_PATH = entries
    _SHADER_DEFAULT_TEXTURES_SOURCE = source_path
    return _SHADER_DEFAULT_TEXTURES_BY_PATH

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


def _apply_pass_material_settings(mat, pass_data):
    """Apply technique-pass blend/cull settings to Blender material preview settings.

    Uses blend factor analysis to choose the best Blender blend/render mode:
      - src=1, dst=7 (ONE/INV_DST_ALPHA) → DITHERED
      - src=6, dst=7 (DST_ALPHA/INV_DST_ALPHA) on Indicator_Faelights → BLENDED + overlap
      - src=6, dst=7 (DST_ALPHA/INV_DST_ALPHA) otherwise → BLENDED, no overlap
      - other blends → BLENDED
      - no blend → DITHERED (opaque)
    """
    if not mat or not pass_data:
        return

    blend_enabled = bool(pass_data.get("blendEnable", False))
    src_color = pass_data.get("srcColorBlendFactor", 1)
    dst_color = pass_data.get("dstColorBlendFactor", 0)
    src_alpha = pass_data.get("srcAlphaBlendFactor", 1)
    dst_alpha = pass_data.get("dstAlphaBlendFactor", 0)

    # Determine shader name for special-case handling
    shader_name = ""
    try:
        shader_name = pass_data.get("shader", "").rsplit("/", 1)[-1]
    except Exception:
        pass

    # Determine Blender blend / render mode
    if not blend_enabled:
        # No blending → always Dithered (opaque)
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'DITHERED'
        elif hasattr(mat, "blend_method"):
            mat.blend_method = 'OPAQUE'
    elif src_color == 1 and dst_color == 7:
        # ONE / INV_DST_ALPHA → Dithered
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'DITHERED'
        elif hasattr(mat, "blend_method"):
            mat.blend_method = 'HASHED'
    elif src_color == 6 and dst_color == 7 and shader_name == 'Indicator_Faelights':
        # DST_ALPHA / INV_DST_ALPHA on Faelights → Blended + overlap
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'BLENDED'
        elif hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'
    else:
        # Standard alpha blend, additive, etc. → BLENDED
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'BLENDED'
        elif hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'

    # Transparency Overlap: only for Indicator_Faelights with 6/7/6/7 blend factors
    if hasattr(mat, "use_transparency_overlap"):
        overlap_on = (
            blend_enabled and
            src_color == 6 and dst_color == 7 and
            src_alpha == 6 and dst_alpha == 7 and
            shader_name == 'Indicator_Faelights'
        )
        mat.use_transparency_overlap = overlap_on

    # Show transparent back for glass/additive shaders
    if hasattr(mat, "show_transparent_back"):
        is_additive = blend_enabled and dst_color in (1, 6)
        mat.show_transparent_back = is_additive

    if "cullEnable" in pass_data and hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = bool(pass_data.get("cullEnable"))


# ---------------------------------------------------------------------------
#  Shader category classification — maps shader short names to behaviour groups
# ---------------------------------------------------------------------------

_SHADER_CATEGORY_MAP = {
    # ── Glass / Reflection ─────────────────────────────────────────────
    "ENV_Glass":                              "glass",
    "ENV_Glass_Diffuse":                      "glass_diffuse",
    "ENV_Glass_Vertex_Offset":                "glass",
    "DefaultEnv_Glass_BlendAndReflection":    "glass_blend",
    "DefaultEnv_Flat_PlanarReflection":       "planar_reflection",
    "TFT_PlanarReflection":                   "planar_reflection",
    # ── Emissive / Glow ───────────────────────────────────────────────
    "Emissive_Basic":                         "emissive_basic",
    "ENV_GlowSign":                           "glow_sign",
    "ENV_GlowSign_Atlas":                     "glow_sign",
    "ENV_Lantern":                            "glow_mask",
    "ENV_Light_Sequence":                     "glow_mask",
    "ENV_SimpleRotate":                       "glow_mask",
    "ENV_DIffuse_Pulse":                      "glow_mask",
    "DefaultEnv_Glow":                        "glow",
    "SRX_Blend_Decal_Cloud":                  "glow_decal",
    "SRX_Blend_Chemtech_Decal":              "emissive_decal",
    # ── Water / Flow ──────────────────────────────────────────────────
    "Flowmap_River":                          "water_river",
    "FlowMap_Radial":                         "water_radial",
    "OD_FlowMap":                             "water_flow",
    "TFT_Water":                              "water",
    "SRX_Blend_Ocean":                        "water_ocean",
    "TFT_Env_Rain":                           "water_rain",
    # ── Hologram ──────────────────────────────────────────────────────
    "Hologram":                               "hologram",
    "Hologram_Rotate":                        "hologram",
    # ── Alpha Test / Cutout ───────────────────────────────────────────
    "DefaultEnv_Flat_AlphaTest":              "alpha_test",
    "DefaultEnv_Flat_AlphaTest_DoubleSided":  "alpha_test_double",
    # ── Foliage / Wind ────────────────────────────────────────────────
    "ENV_TreeCanopy":                         "foliage",
    "ENV_TreeCanopy_VertexColors":            "foliage",
    "ENV_SimpleFoliage":                      "foliage",
    "TFT_Wind_Simple":                        "foliage",
    "TFT_VertexBend":                         "foliage",
    "DefaultEnv_Flag_Wave":                   "foliage",
    "TFT_Flag_Wave":                          "foliage",
    # ── Multi-layer / Special ─────────────────────────────────────────
    "TFT_Env_Parallax":                       "parallax",
    "TFT_SparkleParallaxGlow":                "sparkle_parallax",
    "4TextureBlend_WorldProjected":           "terrain_4tex",
    "TFT_FixedUVSpace_Bloom":                "multi_layer_bloom",
    # ── Indicator ─────────────────────────────────────────────────────
    "Indicator_Faelights":                    "faelights",
    "ENV_UVGradientColorMapping":             "gradient_color",
    # ── Scrolling / Animated ──────────────────────────────────────────
    "ENV_ScrollingColor":                     "scrolling_emissive",
    "ENV_ScrollingDiffuse":                   "scrolling",
    "ENV_DarkstarBase":                       "scrolling",
    "TFT_Scrolling_Delay_Static":             "scrolling",
    "TFT_ScrollingDiffuse_Distortion":        "scrolling",
    "TFT_Screenspace_Glitch_Static":          "scrolling",
    # ── Twist / Noise ─────────────────────────────────────────────────
    "Env_TwistByNoise":                       "twist_emissive",
    "TFT_TwistByNoise":                       "twist_emissive",
    # ── Transition ────────────────────────────────────────────────────
    "DefaultEnv_Transition":                  "transition",
    "TFT_Transition_Ground":                  "transition",
    # ── Cloth ─────────────────────────────────────────────────────────
    "Cloth_Base_StaticMesh":                  "cloth",
    # ── VertexDeform ──────────────────────────────────────────────────
    "VertexDeform":                           "vertex_deform",
    # ── Flipbook ──────────────────────────────────────────────────────
    "FlickerAlpha_FlipBook":                  "flipbook_emissive",
}


def _socket_has_upstream_image(socket, max_depth=12):
    """Return True if socket has any upstream TEX_IMAGE node with a loaded image.

    Traverses through intermediate nodes (Mix, Math, Reroute, etc.) so this
    works for both direct and indirect emission wiring.
    """
    if not socket:
        return False

    stack = [(socket, 0)]
    visited = set()

    while stack:
        current_socket, depth = stack.pop()
        socket_id = id(current_socket)
        if socket_id in visited:
            continue
        visited.add(socket_id)

        if depth > max_depth:
            continue

        for link in getattr(current_socket, "links", []):
            from_node = link.from_node
            if from_node and from_node.type == 'TEX_IMAGE' and getattr(from_node, 'image', None):
                return True

            if from_node and depth < max_depth:
                for input_socket in from_node.inputs:
                    if getattr(input_socket, "is_linked", False):
                        stack.append((input_socket, depth + 1))

    return False


def _material_has_emissive_sampler(mat):
    """Check if material data contains any emissive texture sampler definition
    that is NOT a shader template texture (ASSETS/Shared/Materials/).
    
    Returns True if a real emissive sampler exists in the material data.
    This matches game behavior where emission params are only applied when
    an emissive sampler is defined with a non-template texture.
    """
    if not mat:
        return False
    
    try:
        samplers = json.loads(mat.get("samplers", "[]"))
    except Exception:
        return False
    
    # Emissive sampler names (case-insensitive)
    emissive_names = {
        "emissive_texture", "emissiontex", "emission_tex",
        "emissivetexture",
    }
    
    for sampler in samplers:
        tex_name = (sampler.get("textureName") or "").lower().strip()
        if tex_name in emissive_names:
            # Check if texture path is a shader template (not a real emissive)
            tex_path = (sampler.get("texturePath") or "").upper().replace("\\", "/")
            if "ASSETS/SHARED/MATERIALS/" in tex_path or tex_path.startswith("ASSETS/SHARED/MATERIALS/"):
                continue  # Skip shader template textures
            return True
    
    return False


def _classify_shader(shader_path):
    """Return (short_name, category) for a shader path."""
    if not shader_path:
        return "", "standard"
    short = shader_path.rsplit("/", 1)[-1]
    cat = _SHADER_CATEGORY_MAP.get(short)
    if cat:
        return short, cat
    # Keyword fallback
    low = shader_path.lower()
    if any(k in low for k in ("water", "river", "ocean", "pond", "flowwater")):
        return short, "water"
    if any(k in low for k in ("glass", "reflection")):
        return short, "glass"
    if any(k in low for k in ("glow", "emissive", "emission")):
        return short, "glow_mask"
    if any(k in low for k in ("hologram",)):
        return short, "hologram"
    if "alphatest" in low:
        return short, "alpha_test"
    return short, "standard"


# ---------------------------------------------------------------------------
#  Category-specific node graph builders
# ---------------------------------------------------------------------------

def _build_water_shader_nodes(nodes, links, output, shader_path):
    """Build a water-focused preview shader graph (Principled+Transparent+Fresnel mix)."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (120, -40)
    if principled.inputs.get("Transmission Weight"):
        principled.inputs["Transmission Weight"].default_value = 0.75
    if principled.inputs.get("Roughness"):
        principled.inputs["Roughness"].default_value = 0.08
    if principled.inputs.get("IOR"):
        principled.inputs["IOR"].default_value = 1.333

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.name = "MAPGEO_WATER_TRANSPARENT"
    transparent.location = (120, -260)

    fresnel = nodes.new("ShaderNodeLayerWeight")
    fresnel.name = "MAPGEO_WATER_FRESNEL"
    fresnel.location = (-150, -240)
    fresnel.inputs["Blend"].default_value = 0.2

    fresnel_pow = nodes.new("ShaderNodeMath")
    fresnel_pow.name = "MAPGEO_WATER_FRESNEL_POW"
    fresnel_pow.operation = 'POWER'
    fresnel_pow.location = (0, -240)
    fresnel_pow.inputs[1].default_value = 1.8

    mix_shader = nodes.new("ShaderNodeMixShader")
    mix_shader.name = "MAPGEO_WATER_MIX"
    mix_shader.location = (340, -130)

    facing_out = fresnel.outputs.get("Facing")
    pow_in = fresnel_pow.inputs[0]
    pow_out = fresnel_pow.outputs.get("Value")
    if facing_out and pow_in:
        links.new(facing_out, pow_in)
    if pow_out and mix_shader.inputs.get("Fac"):
        links.new(pow_out, mix_shader.inputs["Fac"])

    t_out = transparent.outputs.get("BSDF")
    p_out = principled.outputs.get("BSDF")
    if t_out and len(mix_shader.inputs) > 1:
        links.new(t_out, mix_shader.inputs[1])
    if p_out and len(mix_shader.inputs) > 2:
        links.new(p_out, mix_shader.inputs[2])

    m_out = mix_shader.outputs.get("Shader")
    s_in = output.inputs.get("Surface")
    if m_out and s_in:
        links.new(m_out, s_in)

    return principled


def _build_glass_shader_nodes(nodes, links, output, shader_path):
    """Build Fresnel-based glass: two colors blended by view angle."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (200, 0)
    if principled.inputs.get("Roughness"):
        principled.inputs["Roughness"].default_value = 0.1
    if principled.inputs.get("IOR"):
        principled.inputs["IOR"].default_value = 1.45
    if principled.inputs.get("Alpha"):
        principled.inputs["Alpha"].default_value = 0.3

    # Fresnel
    fresnel = nodes.new("ShaderNodeFresnel")
    fresnel.name = "MAPGEO_GLASS_FRESNEL"
    fresnel.location = (-300, 100)
    fresnel.inputs["IOR"].default_value = 1.45

    # Color mix node Glass_Color1 → Glass_Color2
    color_mix = nodes.new("ShaderNodeMix")
    color_mix.name = "MAPGEO_GLASS_COLOR_MIX"
    color_mix.data_type = 'RGBA'
    color_mix.location = (-100, 100)
    color_mix.label = "Glass Color Blend"
    links.new(fresnel.outputs["Fac"], color_mix.inputs["Factor"])
    color_mix.inputs[6].default_value = (0.1, 0.2, 0.3, 1.0)   # Glass_Color1 default
    color_mix.inputs[7].default_value = (0.2, 0.4, 0.6, 1.0)   # Glass_Color2 default
    bc = principled.inputs.get("Base Color")
    if bc:
        links.new(color_mix.outputs[2], bc)

    bsdf_out = principled.outputs.get("BSDF")
    surface_in = output.inputs.get("Surface")
    if bsdf_out and surface_in:
        links.new(bsdf_out, surface_in)

    return principled


def _build_hologram_shader_nodes(nodes, links, output, shader_path):
    """Hologram: semi-transparent emissive with base colour tint."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (200, 0)
    if principled.inputs.get("Base Color"):
        principled.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    if principled.inputs.get("Emission Color"):
        principled.inputs["Emission Color"].default_value = (0.0, 0.5, 1.0, 1.0)
    if principled.inputs.get("Emission Strength"):
        principled.inputs["Emission Strength"].default_value = 1.5
    if principled.inputs.get("Alpha"):
        principled.inputs["Alpha"].default_value = 0.5

    bsdf_out = principled.outputs.get("BSDF")
    surface_in = output.inputs.get("Surface")
    if bsdf_out and surface_in:
        links.new(bsdf_out, surface_in)
    return principled


def _build_emissive_only_nodes(nodes, links, output, shader_path):
    """Emissive_Basic: solid emissive colour, no textures."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (200, 0)
    if principled.inputs.get("Base Color"):
        principled.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    if principled.inputs.get("Emission Color"):
        principled.inputs["Emission Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    if principled.inputs.get("Emission Strength"):
        principled.inputs["Emission Strength"].default_value = 1.0

    bsdf_out = principled.outputs.get("BSDF")
    surface_in = output.inputs.get("Surface")
    if bsdf_out and surface_in:
        links.new(bsdf_out, surface_in)
    return principled


def _build_faelights_nodes(nodes, links, output, shader_path):
    """Indicator_Faelights: solid tinted emissive point."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (200, 0)
    if principled.inputs.get("Base Color"):
        principled.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    if principled.inputs.get("Emission Color"):
        principled.inputs["Emission Color"].default_value = (0.0, 1.0, 1.0, 1.0)
    if principled.inputs.get("Emission Strength"):
        principled.inputs["Emission Strength"].default_value = 2.0
    if principled.inputs.get("Alpha"):
        principled.inputs["Alpha"].default_value = 0.1

    bsdf_out = principled.outputs.get("BSDF")
    surface_in = output.inputs.get("Surface")
    if bsdf_out and surface_in:
        links.new(bsdf_out, surface_in)
    return principled


def _build_gradient_color_nodes(nodes, links, output, shader_path):
    """ENV_UVGradientColorMapping: gradient from top to bottom colour (no textures)."""
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "MAPGEO_SHADER"
    principled.label = f"Shader: {(shader_path or '(none)').rsplit('/', 1)[-1]}"
    principled.location = (400, 0)

    # UV-based gradient (V coord)
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = "MAPGEO_GRAD_TEXCOORD"
    texcoord.location = (-400, 0)
    sep_xyz = nodes.new("ShaderNodeSeparateXYZ")
    sep_xyz.name = "MAPGEO_GRAD_SEP"
    sep_xyz.location = (-200, 0)
    links.new(texcoord.outputs["UV"], sep_xyz.inputs["Vector"])

    color_ramp = nodes.new("ShaderNodeValToRGB")
    color_ramp.name = "MAPGEO_GRAD_RAMP"
    color_ramp.location = (0, 0)
    color_ramp.color_ramp.elements[0].color = (0.2, 0.3, 0.5, 1.0)
    color_ramp.color_ramp.elements[1].color = (0.6, 0.8, 1.0, 1.0)
    links.new(sep_xyz.outputs["Y"], color_ramp.inputs["Fac"])

    bc = principled.inputs.get("Base Color")
    if bc:
        links.new(color_ramp.outputs["Color"], bc)

    # Fresnel alpha
    fresnel_lw = nodes.new("ShaderNodeLayerWeight")
    fresnel_lw.name = "MAPGEO_GRAD_FRESNEL"
    fresnel_lw.location = (100, -200)
    fresnel_lw.inputs["Blend"].default_value = 0.3
    alpha_in = principled.inputs.get("Alpha")
    if alpha_in:
        links.new(fresnel_lw.outputs["Fresnel"], alpha_in)

    bsdf_out = principled.outputs.get("BSDF")
    surface_in = output.inputs.get("Surface")
    if bsdf_out and surface_in:
        links.new(bsdf_out, surface_in)
    return principled


# ---------------------------------------------------------------------------
#  Main node-graph rebuild
# ---------------------------------------------------------------------------

def _rebuild_shader_preview_nodes(mat, shader_path, assets_folder="", custom_assets_folder="", prioritize_custom=False):
    """Rebuild managed preview nodes based on shader type, using all texture inputs.

    Dispatches to category-specific builders for glass, water, hologram, emissive,
    faelights, gradient, etc.  Standard/alpha/foliage/terrain/scrolling/cloth
    variants all use Principled BSDF with appropriate sampler wiring.
    
    Args:
        mat: Blender material
        shader_path: Shader path string from material data
        assets_folder: Original Riot assets folder path
        custom_assets_folder: Custom assets folder path  
        prioritize_custom: If True, check custom folder first
    """
    if not mat:
        return

    mat.use_nodes = True
    nt = mat.node_tree
    if not nt:
        return

    nodes = nt.nodes
    links = nt.links

    # ── Preserve loaded images from old nodes ───────────────────────
    previous_images = {}
    lightmap_image = None  # Preserve lightmap separately
    for node in nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            if node.label:
                previous_images[node.label.lower()] = node.image
            # Also key by image filepath stem so loader-created (unlabeled)
            # nodes can be matched against sampler texturePath later
            if node.image.filepath:
                img_stem = os.path.splitext(os.path.basename(node.image.filepath))[0].lower()
                previous_images[f"__filepath__{img_stem}"] = node.image
            # Detect lightmap node: connected from a LightmapUV node
            for inp in node.inputs:
                for link in inp.links:
                    if (link.from_node.type == 'UVMAP' and
                            getattr(link.from_node, 'uv_map', '') == 'LightmapUV'):
                        lightmap_image = node.image

    # ── Clear all nodes except output, then reuse/create output ─────
    # Remove everything (loader-created nodes don't have MAPGEO_ prefix,
    # so we must clear all to avoid duplicates like extra Principled BSDFs)
    output = None
    for node in list(nodes):
        if node.type == 'OUTPUT_MATERIAL' and output is None:
            output = node  # keep first output
        else:
            nodes.remove(node)

    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
    output.name = "MAPGEO_OUTPUT"
    output.label = "Mapgeo Output"
    output.location = (600, 0)

    # ── Classify shader ─────────────────────────────────────────────
    short_name, category = _classify_shader(shader_path)
    shader_label = short_name or "(none)"

    # ── Dispatch to category builder ────────────────────────────────
    if category in ("water", "water_river", "water_radial", "water_flow",
                     "water_ocean", "water_rain"):
        shader_node = _build_water_shader_nodes(nodes, links, output, shader_path)
    elif category in ("glass", "glass_diffuse"):
        shader_node = _build_glass_shader_nodes(nodes, links, output, shader_path)
    elif category == "glass_blend":
        shader_node = _build_glass_shader_nodes(nodes, links, output, shader_path)
    elif category in ("hologram",):
        shader_node = _build_hologram_shader_nodes(nodes, links, output, shader_path)
    elif category == "emissive_basic":
        shader_node = _build_emissive_only_nodes(nodes, links, output, shader_path)
    elif category == "faelights":
        shader_node = _build_faelights_nodes(nodes, links, output, shader_path)
    elif category == "gradient_color":
        shader_node = _build_gradient_color_nodes(nodes, links, output, shader_path)
    else:
        # Standard Principled BSDF (covers: standard, alpha_test, foliage,
        # glow, glow_sign, glow_mask, glow_decal, emissive_decal, cloth,
        # scrolling, scrolling_emissive, twist_emissive, transition,
        # vertex_deform, planar_reflection, parallax, sparkle_parallax,
        # terrain_4tex, multi_layer_bloom, flipbook_emissive, alpha_test_double)
        shader_node = nodes.new("ShaderNodeBsdfPrincipled")
        shader_node.name = "MAPGEO_SHADER"
        shader_node.label = f"Shader: {shader_label}"
        shader_node.location = (200, 0)
        # Defaults for env art: fully rough, no specular, no emission
        if shader_node.inputs.get("Roughness"):
            shader_node.inputs["Roughness"].default_value = 1.0
        spec_in = shader_node.inputs.get("Specular IOR Level") or shader_node.inputs.get("Specular")
        if spec_in:
            spec_in.default_value = 0.0
        es_in = shader_node.inputs.get("Emission Strength")
        if es_in:
            es_in.default_value = 0.0
        bsdf_out = shader_node.outputs.get("BSDF")
        surface_in = output.inputs.get("Surface")
        if bsdf_out and surface_in:
            links.new(bsdf_out, surface_in)

    # ── Create sampler texture nodes from material JSON ─────────────
    sampler_nodes = {}
    # Track which samplers are shader templates (ASSETS/Shared/Materials/)
    # These are loaded but NOT connected to the shader
    _shader_template_samplers = set()
    try:
        samplers = json.loads(mat.get("samplers", "[]"))
    except Exception:
        samplers = []

    for idx, sampler in enumerate(samplers):
        sampler_name = (sampler.get("textureName") or f"Sampler{idx}").strip() or f"Sampler{idx}"
        tex_path = sampler.get("texturePath", "")
        
        # Detect shader template textures (ASSETS/Shared/Materials/*)
        tex_path_upper = tex_path.upper().replace("\\", "/")
        is_shader_template = "ASSETS/SHARED/MATERIALS/" in tex_path_upper or tex_path_upper.startswith("ASSETS/SHARED/MATERIALS/")
        if is_shader_template:
            _shader_template_samplers.add(sampler_name.lower())
        
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = f"MAPGEO_SAMPLER_{idx}"
        tex_node.label = sampler_name
        tex_node.location = (-620, -220 * idx)
        sampler_nodes[sampler_name.lower()] = tex_node

        # Try restoring image: first by sampler label, then by texturePath stem
        prev = previous_images.get(sampler_name.lower())
        if not prev:
            if tex_path:
                path_stem = os.path.splitext(os.path.basename(tex_path.replace("\\", "/")))[0].lower()
                prev = previous_images.get(f"__filepath__{path_stem}")
        if prev:
            tex_node.image = prev
        
        # Load texture from disk if not restored and assets folders are provided
        if not tex_node.image and (assets_folder or custom_assets_folder):
            if tex_path and resolve_texture_path:
                full_path = resolve_texture_path(tex_path, assets_folder, custom_assets_folder, prioritize_custom)
                if full_path:
                    try:
                        # Check for existing loaded image to avoid duplicates
                        norm_path = os.path.normpath(os.path.abspath(full_path))
                        existing_img = None
                        
                        if full_path.lower().endswith('.tex'):
                            # For .tex files, check by _tex_source_path custom prop
                            for img in bpy.data.images:
                                src = img.get('_tex_source_path', '')
                                if src and os.path.normpath(src) == norm_path:
                                    existing_img = img
                                    break
                            
                            if existing_img:
                                tex_node.image = existing_img
                            elif TexConverter:
                                tex_converter = TexConverter()
                                img = tex_converter.load_tex_as_blender_image(full_path)
                                if img:
                                    tex_node.image = img
                        else:
                            # For .dds/.png, check_existing=True avoids duplicates
                            img = bpy.data.images.load(full_path, check_existing=True)
                            if img:
                                tex_node.image = img
                    except Exception as e:
                        pass  # Texture loading failed, node stays empty

    # ── Shared UV TexCoord → Mapping for all sampler nodes ──────────
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = "MAPGEO_TEXCOORD"
    texcoord.location = (-1100, 60)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "MAPGEO_MAPPING"
    mapping.location = (-900, 60)
    uv_out = texcoord.outputs.get("UV")
    vec_in = mapping.inputs.get("Vector")
    if uv_out and vec_in:
        links.new(uv_out, vec_in)

    map_out = mapping.outputs.get("Vector")
    if map_out:
        for tex_node in sampler_nodes.values():
            vin = tex_node.inputs.get("Vector")
            if vin:
                links.new(map_out, vin)

    # ── Identify diffuse sampler (skip shader template textures) ────
    # Ordered list: try exact matches in priority order
    _DIFFUSE_NAMES = [
        "diffuse_texture", "diffusetexture", "baked_diffuse_texture",
        "colortexture", "_maintex", "glass_diffuse_texture",
        "bottom_texture", "scrolling_texture",
    ]
    diffuse_node = None
    # Pass 1: diffuse name with a loaded image (best match)
    for key in _DIFFUSE_NAMES:
        if key in sampler_nodes and key not in _shader_template_samplers:
            if sampler_nodes[key].image:
                diffuse_node = sampler_nodes[key]
                break
    # Pass 2: diffuse name without image (node exists but texture not loaded)
    if diffuse_node is None:
        for key in _DIFFUSE_NAMES:
            if key in sampler_nodes and key not in _shader_template_samplers:
                diffuse_node = sampler_nodes[key]
                break
    # Pass 3: any non-template sampler with a loaded image
    if diffuse_node is None:
        for sname, sn in sampler_nodes.items():
            if sn.image and sname not in _shader_template_samplers:
                diffuse_node = sn
                break

    # ── Connect diffuse → Base Color ────────────────────────────────
    if diffuse_node:
        color_input = shader_node.inputs.get("Color") or shader_node.inputs.get("Base Color")
        color_out = diffuse_node.outputs.get("Color")
        if color_input and color_out:
            links.new(color_out, color_input)

    # ── Connect diffuse alpha to shader ─────────────────────────────
    # Always connect alpha output from diffuse → Alpha input on shader
    if diffuse_node:
        alpha_input = shader_node.inputs.get("Alpha")
        alpha_out = diffuse_node.outputs.get("Alpha")
        if alpha_input and alpha_out:
            links.new(alpha_out, alpha_input)

    # ── Lightmap reconnection (preserves baked lighting across edits) ──
    # Check stored metadata or preserved lightmap image
    _lm_image = lightmap_image
    if not _lm_image and mat.get("lightmap_texture"):
        # Try to find in previous_images by filepath stem
        lm_path = mat["lightmap_texture"]
        lm_stem = os.path.splitext(os.path.basename(lm_path.replace("\\", "/")))[0].lower()
        _lm_image = previous_images.get(f"__filepath__{lm_stem}")
    
    # Also check shader macros: only apply lightmap if material uses baked lighting
    _has_baked = True
    try:
        _macros = json.loads(mat.get("shader_macros", "{}"))
        if "NO_BAKED_LIGHTING" in _macros:
            _has_baked = False
    except Exception:
        pass

    if _lm_image and _has_baked and diffuse_node and shader_node.type == 'BSDF_PRINCIPLED':
        lm_scale = mat.get("lightmap_color_scale", 1.0)

        # Create LightmapUV node
        lm_uv = nodes.new("ShaderNodeUVMap")
        lm_uv.uv_map = "LightmapUV"
        lm_uv.label = "LightmapUV"
        lm_uv.location = (-820, -400)

        # Create lightmap texture node
        lm_tex = nodes.new("ShaderNodeTexImage")
        lm_tex.image = _lm_image
        lm_tex.label = "Lightmap"
        lm_tex.location = (-620, -400)
        if _lm_image:
            _lm_image.colorspace_settings.name = 'Non-Color'
        links.new(lm_uv.outputs['UV'], lm_tex.inputs['Vector'])

        # LM × Scale
        lm_scale_node = nodes.new('ShaderNodeMix')
        lm_scale_node.data_type = 'RGBA'
        lm_scale_node.blend_type = 'MULTIPLY'
        lm_scale_node.location = (-320, -400)
        lm_scale_node.inputs['Factor'].default_value = 1.0
        lm_scale_node.label = "LM × Scale"
        links.new(lm_tex.outputs['Color'], lm_scale_node.inputs[6])
        lm_scale_node.inputs[7].default_value = (lm_scale, lm_scale, lm_scale, 1.0)

        # Diffuse × Lightmap
        lm_mix = nodes.new('ShaderNodeMix')
        lm_mix.data_type = 'RGBA'
        lm_mix.blend_type = 'MULTIPLY'
        lm_mix.location = (-100, -200)
        lm_mix.inputs['Factor'].default_value = 1.0
        lm_mix.label = "Diffuse × Lightmap"
        links.new(diffuse_node.outputs['Color'], lm_mix.inputs[6])
        links.new(lm_scale_node.outputs[2], lm_mix.inputs[7])

        # Wire to Emission
        ec_in = shader_node.inputs.get("Emission Color")
        es_in = shader_node.inputs.get("Emission Strength")
        if ec_in:
            links.new(lm_mix.outputs[2], ec_in)
        if es_in:
            es_in.default_value = 1.0
        # Reduce specular for lightmapped surfaces
        spec_in = shader_node.inputs.get("Specular IOR Level") or shader_node.inputs.get("Specular")
        if spec_in:
            spec_in.default_value = 0.0
        rough_in = shader_node.inputs.get("Roughness")
        if rough_in:
            rough_in.default_value = 1.0

    # ── Emissive / Glow texture wiring (skip shader templates) ──────
    _EMISSIVE_NAMES = {
        "emissive_texture", "emissiontex", "emission_tex",
        "emissivetexture",
    }
    emissive_tex_node = None
    for alias in _EMISSIVE_NAMES:
        if alias in sampler_nodes and alias not in _shader_template_samplers:
            emissive_tex_node = sampler_nodes[alias]
            break

    if emissive_tex_node and shader_node.type == 'BSDF_PRINCIPLED':
        # Only apply separate emissive texture if no lightmap (lightmap uses Emission)
        if not (_lm_image and _has_baked):
            ecolor = emissive_tex_node.outputs.get("Color")
            ein = shader_node.inputs.get("Emission Color") or shader_node.inputs.get("Emission")
            if ecolor and ein:
                links.new(ecolor, ein)
            estr = shader_node.inputs.get("Emission Strength")
            if estr:
                # Only enable emission when the emissive texture has an actual image loaded
                estr.default_value = 1.0 if emissive_tex_node.image else 0.0

    # ── EmissionMaskTex → controls Emission Strength (not color) ────
    # Skip if lightmap already owns the emission channel
    _EMISSION_MASK_NAME = "emissionmasktex"
    emission_mask_node = sampler_nodes.get(_EMISSION_MASK_NAME)
    if (emission_mask_node and _EMISSION_MASK_NAME not in _shader_template_samplers
            and not (_lm_image and _has_baked)):
        if shader_node.type == 'BSDF_PRINCIPLED':
            # If we have a mask but no separate emissive, use diffuse as emission color
            ein = shader_node.inputs.get("Emission Color") or shader_node.inputs.get("Emission")
            if ein and not emissive_tex_node and diffuse_node:
                links.new(diffuse_node.outputs["Color"], ein)
            # Convert mask color → grayscale → Emission Strength
            estr = shader_node.inputs.get("Emission Strength")
            if estr and emission_mask_node.image:
                mask_bw = nodes.new("ShaderNodeRGBToBW")
                mask_bw.name = "MAPGEO_EMISSION_MASK_BW"
                mask_bw.label = "Emission Mask → Strength"
                mask_bw.location = (emission_mask_node.location.x + 300,
                                    emission_mask_node.location.y)
                links.new(emission_mask_node.outputs["Color"], mask_bw.inputs["Color"])
                links.new(mask_bw.outputs["Val"], estr)

    # For glow_sign / glow_mask / glow_decal: if no separate emissive tex but we
    # have a mask texture, use the mask to modulate emission from diffuse
    # Skip if lightmap already owns the emission channel
    if (not emissive_tex_node and not (_lm_image and _has_baked)
            and category in ("glow", "glow_sign", "glow_mask", "glow_decal")):
        mask_node = None
        for mn in ("mask_texture", "mask_tex"):
            if mn in sampler_nodes and mn not in _shader_template_samplers:
                mask_node = sampler_nodes[mn]
                break
        if mask_node and shader_node.type == 'BSDF_PRINCIPLED':
            # Mask drives emission strength: brighter mask = more glow
            mask_color = mask_node.outputs.get("Color")
            ein = shader_node.inputs.get("Emission Color") or shader_node.inputs.get("Emission")
            if mask_color and ein and diffuse_node:
                # Mix diffuse × mask → Emission Color
                emit_mix = nodes.new("ShaderNodeMix")
                emit_mix.name = "MAPGEO_EMIT_MIX"
                emit_mix.data_type = 'RGBA'
                emit_mix.blend_type = 'MULTIPLY'
                emit_mix.location = (-100, -300)
                emit_mix.inputs["Factor"].default_value = 1.0
                emit_mix.label = "Diffuse × Mask → Emission"
                links.new(diffuse_node.outputs["Color"], emit_mix.inputs[6])
                links.new(mask_color, emit_mix.inputs[7])
                links.new(emit_mix.outputs[2], ein)
            estr = shader_node.inputs.get("Emission Strength")
            if estr:
                estr.default_value = 1.0

    # ── Mask texture → roughness / additional wiring ────────────────
    _MASK_NAMES = {"mask_texture", "mask_tex", "_mask", "masktexture"}
    mask_node = None
    for mn in _MASK_NAMES:
        if mn in sampler_nodes and mn not in _shader_template_samplers:
            mask_node = sampler_nodes[mn]
            break

    # ── Normal map wiring (flowing_normal_map, normal_rain_texture, etc.) ──
    _NORMAL_NAMES = {
        "flowing_normal_map", "normal_rain_texture",
        "normaltexture", "normalmap", "normal",
    }
    for alias in _NORMAL_NAMES:
        if alias in sampler_nodes and alias not in _shader_template_samplers and shader_node.inputs.get("Normal"):
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.name = "MAPGEO_NORMAL"
            normal_map.location = (-100, -450)
            ncolor = sampler_nodes[alias].outputs.get("Color")
            nin = normal_map.inputs.get("Color")
            if ncolor and nin:
                links.new(ncolor, nin)
            nout = normal_map.outputs.get("Normal")
            snin = shader_node.inputs.get("Normal")
            if nout and snin:
                links.new(nout, snin)
            break

    # ── Reflection / Specular texture ───────────────────────────────
    _REFLECTION_NAMES = {"reflection_texture", "_specular", "shinemask_texture"}
    for rn in _REFLECTION_NAMES:
        if rn in sampler_nodes and rn not in _shader_template_samplers and shader_node.inputs.get("Roughness"):
            # Use reflection map to reduce roughness
            refl_node = sampler_nodes[rn]
            refl_color = refl_node.outputs.get("Color")
            if refl_color:
                invert = nodes.new("ShaderNodeInvert")
                invert.name = "MAPGEO_REFL_INVERT"
                invert.location = (-100, -550)
                links.new(refl_color, invert.inputs.get("Color"))
                rough_in = shader_node.inputs.get("Roughness")
                if rough_in:
                    links.new(invert.outputs.get("Color"), rough_in)
            break

    # ── Noise / Scrolling overlay textures (additive or overlay mix) ──
    _OVERLAY_NAMES = {"noise_texture", "noisetexture", "scrolling_texture",
                      "scrollinga_texture", "scrollingb_texture",
                      "scrolling_texture2", "sparkle_texture",
                      "mod_texture", "decal_texture"}
    overlay_node = None
    for on in _OVERLAY_NAMES:
        if on in sampler_nodes and on not in _shader_template_samplers:
            overlay_node = sampler_nodes[on]
            break

    if overlay_node and diffuse_node and category in ("scrolling", "scrolling_emissive",
                                                       "glow_decal", "emissive_decal",
                                                       "transition"):
        # Overlay mix: blend overlay on top of diffuse via Screen blend
        overlay_mix = nodes.new("ShaderNodeMix")
        overlay_mix.name = "MAPGEO_OVERLAY_MIX"
        overlay_mix.data_type = 'RGBA'
        overlay_mix.blend_type = 'SCREEN'
        overlay_mix.location = (-200, 100)
        overlay_mix.inputs["Factor"].default_value = 0.3
        overlay_mix.label = "Overlay Mix"
        links.new(diffuse_node.outputs["Color"], overlay_mix.inputs[6])
        links.new(overlay_node.outputs["Color"], overlay_mix.inputs[7])
        bc = shader_node.inputs.get("Base Color") or shader_node.inputs.get("Color")
        if bc:
            links.new(overlay_mix.outputs[2], bc)

    # ── FlowMap / Distortion textures for water ─────────────────────
    # Flow map channels: R=flow direction X, G=flow direction Y (0.5=neutral), B=flow mask/intensity
    _FLOW_NAMES = {"flow_map", "flowmap", "distortion_texture"}
    for fn in _FLOW_NAMES:
        if fn in sampler_nodes and fn not in _shader_template_samplers and category in ("water_river", "water_radial",
                                                  "water_flow", "water_rain", "water"):
            flow_node = sampler_nodes[fn]
            if flow_node.image:
                # Separate R=dirX, G=dirY, B=mask
                sep_flow = nodes.new("ShaderNodeSeparateColor")
                sep_flow.name = "MAPGEO_FLOW_SEPARATE"
                sep_flow.location = (-300, -550)
                sep_flow.label = "Flow R=dirX G=dirY B=mask"
                fc = flow_node.outputs.get("Color")
                if fc:
                    links.new(fc, sep_flow.inputs["Color"])
                
                # Use RG as normal map (flow direction → surface distortion)
                combine_flow = nodes.new("ShaderNodeCombineColor")
                combine_flow.name = "MAPGEO_FLOW_COMBINE"
                combine_flow.location = (-100, -600)
                combine_flow.label = "Flow → Normal"
                links.new(sep_flow.outputs["Red"], combine_flow.inputs["Red"])
                links.new(sep_flow.outputs["Green"], combine_flow.inputs["Green"])
                combine_flow.inputs["Blue"].default_value = 1.0  # Z = up
                
                if shader_node.inputs.get("Normal"):
                    nm = nodes.new("ShaderNodeNormalMap")
                    nm.name = "MAPGEO_FLOW_NORMAL"
                    nm.location = (50, -600)
                    nm.label = "Flow Direction"
                    nm.inputs["Strength"].default_value = 0.3
                    links.new(combine_flow.outputs["Color"], nm.inputs["Color"])
                    links.new(nm.outputs["Normal"], shader_node.inputs["Normal"])
                
                # B channel = flow mask → can drive alpha for water boundary
                alpha_in = shader_node.inputs.get("Alpha")
                if alpha_in:
                    links.new(sep_flow.outputs["Blue"], alpha_in)
            break

    # ── Thickness / Vertex deformation mask ─────────────────────────
    _THICKNESS_NAMES = {"thickness_texture", "vertexdeformationmask"}
    for tn in _THICKNESS_NAMES:
        if tn in sampler_nodes and tn not in _shader_template_samplers and category in ("water_river", "water", "water_rain"):
            # Could drive subsurface or alpha variation
            thick_node = sampler_nodes[tn]
            if thick_node.image:
                alpha_in = shader_node.inputs.get("Alpha")
                if alpha_in:
                    links.new(thick_node.outputs["Color"], alpha_in)
            break

    # ── Category-specific tweaks ────────────────────────────────────

    # Alpha test: set clip threshold
    if category in ("alpha_test", "alpha_test_double"):
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = 0.5

    # Double sided
    if category == "alpha_test_double":
        if hasattr(mat, "use_backface_culling"):
            mat.use_backface_culling = False

    # Foliage: slight translucency, low roughness
    if category == "foliage" and shader_node.inputs.get("Roughness"):
        shader_node.inputs["Roughness"].default_value = 0.8

    # Planar reflection: reduce roughness for reflective look
    if category == "planar_reflection" and shader_node.inputs.get("Roughness"):
        shader_node.inputs["Roughness"].default_value = 0.3

    # Ocean: slightly glossy water-like surface
    if category == "water_ocean":
        if shader_node.inputs.get("Roughness"):
            shader_node.inputs["Roughness"].default_value = 0.15
        spec = shader_node.inputs.get("Specular IOR Level") or shader_node.inputs.get("Specular")
        if spec:
            spec.default_value = 0.5

    # ── VertexDeform: Grass Tint Map overlay ────────────────────────
    if category == "vertex_deform" and diffuse_node:
        # Check if USE_GRASS_TINT_MAP switch is enabled
        try:
            switches = json.loads(mat.get("switches", "[]"))
        except Exception:
            switches = []
        use_grass_tint = any(
            s.get("name") == "USE_GRASS_TINT_MAP" and s.get("on", False)
            for s in switches
        )
        if use_grass_tint:
            # Look for an existing grass tint image (loaded by material_loader during import)
            grass_tint_img = None
            for img in bpy.data.images:
                if "grasstint" in img.name.lower():
                    grass_tint_img = img
                    break

            if grass_tint_img:
                # Create world-space UV mapping for grass tint
                ws_coord = nodes.new("ShaderNodeTexCoord")
                ws_coord.name = "MAPGEO_GRASS_COORD"
                ws_coord.location = (-1100, -500)

                sep_xyz = nodes.new("ShaderNodeSeparateXYZ")
                sep_xyz.name = "MAPGEO_GRASS_SEP"
                sep_xyz.location = (-900, -500)
                links.new(ws_coord.outputs["Object"], sep_xyz.inputs["Vector"])

                # Scale to 0-1 range (typical map ~15000 units)
                map_scale = 1.0 / 15000.0
                scale_x = nodes.new("ShaderNodeMath")
                scale_x.operation = 'MULTIPLY'
                scale_x.name = "MAPGEO_GRASS_SX"
                scale_x.location = (-750, -450)
                scale_x.inputs[1].default_value = map_scale
                links.new(sep_xyz.outputs["X"], scale_x.inputs[0])

                scale_y = nodes.new("ShaderNodeMath")
                scale_y.operation = 'MULTIPLY'
                scale_y.name = "MAPGEO_GRASS_SY"
                scale_y.location = (-750, -550)
                scale_y.inputs[1].default_value = map_scale
                links.new(sep_xyz.outputs["Y"], scale_y.inputs[0])

                off_x = nodes.new("ShaderNodeMath")
                off_x.operation = 'ADD'
                off_x.name = "MAPGEO_GRASS_OX"
                off_x.location = (-600, -450)
                off_x.inputs[1].default_value = 1.0
                links.new(scale_x.outputs[0], off_x.inputs[0])

                off_y = nodes.new("ShaderNodeMath")
                off_y.operation = 'ADD'
                off_y.name = "MAPGEO_GRASS_OY"
                off_y.location = (-600, -550)
                off_y.inputs[1].default_value = 1.0
                links.new(scale_y.outputs[0], off_y.inputs[0])

                combine_xy = nodes.new("ShaderNodeCombineXYZ")
                combine_xy.name = "MAPGEO_GRASS_COMBINE"
                combine_xy.location = (-450, -500)
                links.new(off_x.outputs[0], combine_xy.inputs["X"])
                links.new(off_y.outputs[0], combine_xy.inputs["Y"])

                # Grass tint texture node
                gt_tex = nodes.new("ShaderNodeTexImage")
                gt_tex.name = "MAPGEO_GRASS_TINT"
                gt_tex.label = "Grass Tint (World UV)"
                gt_tex.location = (-300, -500)
                gt_tex.image = grass_tint_img
                links.new(combine_xy.outputs["Vector"], gt_tex.inputs["Vector"])

                # Multiply diffuse × grass tint → Base Color
                gt_mix = nodes.new("ShaderNodeMix")
                gt_mix.name = "MAPGEO_GRASS_MIX"
                gt_mix.data_type = 'RGBA'
                gt_mix.blend_type = 'MULTIPLY'
                gt_mix.location = (-100, 100)
                gt_mix.inputs["Factor"].default_value = 1.0
                gt_mix.label = "Diffuse × Grass Tint"

                # Re-wire: diffuse → grass mix → Base Color
                bc = shader_node.inputs.get("Base Color") or shader_node.inputs.get("Color")
                if bc:
                    # Remove existing diffuse → base color link
                    for link in list(links):
                        if link.to_socket == bc:
                            links.remove(link)
                    links.new(diffuse_node.outputs["Color"], gt_mix.inputs[6])
                    links.new(gt_tex.outputs["Color"], gt_mix.inputs[7])
                    links.new(gt_mix.outputs[2], bc)


def _apply_material_parameter_values(mat, shader_node, category="standard"):
    """Apply League parameter values to preview shader inputs.

    Handles per-category parameter semantics (tint ×2, glass colours,
    emissive intensity, alpha test value, water colours, etc.).
    """
    if not mat or not shader_node:
        return

    try:
        params = json.loads(mat.get("parameters", "[]"))
    except Exception:
        params = []

    by_name = {}
    for p in params:
        n = (p.get("name") or "").lower()
        v = p.get("value") or [0.0, 0.0, 0.0, 0.0]
        if n:
            by_name[n] = v

    def _get(name_lower):
        """Exact name match (case-insensitive)."""
        return by_name.get(name_lower)

    def _find(*keywords):
        """First param whose name contains any keyword."""
        for name, val in by_name.items():
            if any(k in name for k in keywords):
                return val
        return None

    # Detect whether an emissive sampler is defined in material data.
    # Match game behavior: emission params are ignored without emissive sampler.
    has_emissive_sampler = _material_has_emissive_sampler(mat)

    # ── TintColor ×2 (League convention: 0.5 = no change) ──────────
    # Handles: TintColor, BaseTex_TintColor, ColorTint, Tint, BaseTint,
    #          Diffuse_Tint, DiffuseTint, Tint_Color (non-water), Color_Multiply
    tint = (_get("tintcolor") or _get("basetex_tintcolor") or _get("colortint")
            or _get("tint") or _get("basetint") or _get("diffuse_tint")
            or _get("diffusetint"))
    # Tint_Color for SRX_Blend shaders (non-water only)
    if not tint and category not in ("water", "water_river", "water_radial",
                                      "water_flow", "water_ocean", "water_rain"):
        tint = _get("tint_color")
    if tint and not shader_node.inputs.get("Base Color"):
        pass  # gradient / faelights may not have Base Color
    elif tint:
        r = min(float(tint[0]) * 2.0, 1.0)
        g = min(float(tint[1]) * 2.0, 1.0)
        b = min(float(tint[2]) * 2.0, 1.0)
        # If a texture is wired to Base Color, create a tint multiply node
        bc = shader_node.inputs.get("Base Color") or shader_node.inputs.get("Color")
        if bc and bc.links:
            # There's a texture connected — insert tint multiply
            nt = mat.node_tree
            if nt:
                tex_link = bc.links[0]
                from_socket = tex_link.from_socket
                nt.links.remove(tex_link)
                tint_mix = nt.nodes.new("ShaderNodeMix")
                tint_mix.name = "MAPGEO_TINT"
                tint_mix.data_type = 'RGBA'
                tint_mix.blend_type = 'MULTIPLY'
                tint_mix.location = (-50, 200)
                tint_mix.inputs["Factor"].default_value = 1.0
                tint_mix.label = f"Tint ({r:.2f},{g:.2f},{b:.2f})"
                nt.links.new(from_socket, tint_mix.inputs[6])
                tint_mix.inputs[7].default_value = (r, g, b, 1.0)
                nt.links.new(tint_mix.outputs[2], bc)
        elif bc:
            # No texture — just set the color
            bc.default_value = (
                min(float(tint[0]) * 2.0, 1.0),
                min(float(tint[1]) * 2.0, 1.0),
                min(float(tint[2]) * 2.0, 1.0),
                1.0,
            )

    # ── Glass-specific params ──────────────────────────────────────
    if category in ("glass", "glass_diffuse", "glass_blend"):
        glass_col1 = _get("glass_color1")
        glass_col2 = _get("glass_color2") or _get("glass_color")
        nt = mat.node_tree
        if nt:
            cmix = nt.nodes.get("MAPGEO_GLASS_COLOR_MIX")
            if cmix:
                if glass_col1:
                    cmix.inputs[6].default_value = (float(glass_col1[0]), float(glass_col1[1]), float(glass_col1[2]), 1.0)
                if glass_col2:
                    cmix.inputs[7].default_value = (float(glass_col2[0]), float(glass_col2[1]), float(glass_col2[2]), 1.0)

        roughness = _get("glass_roughness")
        if roughness and shader_node.inputs.get("Roughness"):
            shader_node.inputs["Roughness"].default_value = max(0.0, min(1.0, float(roughness[0])))

        alpha_bias = _get("alpha_bias")
        if alpha_bias and shader_node.inputs.get("Alpha"):
            shader_node.inputs["Alpha"].default_value = max(0.0, min(1.0, float(alpha_bias[0])))

        fresnel_inner = _get("fresnel_size_inner")
        if fresnel_inner and nt:
            gf = nt.nodes.get("MAPGEO_GLASS_FRESNEL")
            if gf:
                gf.inputs["IOR"].default_value = 1.0 + float(fresnel_inner[0]) * 0.1

    # ── Hologram params ────────────────────────────────────────────
    if category == "hologram":
        base_col = _get("base_color")
        if base_col:
            ec = shader_node.inputs.get("Emission Color")
            if ec:
                ec.default_value = (float(base_col[0]), float(base_col[1]), float(base_col[2]), 1.0)
        final_alpha = _get("final_alpha")
        if final_alpha and shader_node.inputs.get("Alpha"):
            shader_node.inputs["Alpha"].default_value = max(0.0, min(1.0, float(final_alpha[0])))
        emit_int = _find("emissive_intensity", "emissive_factor")
        if emit_int:
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = max(0.0, float(emit_int[0]))

    # ── Faelights params ───────────────────────────────────────────
    if category == "faelights":
        tint_val = _get("tintcolor")
        if tint_val:
            ec = shader_node.inputs.get("Emission Color")
            if ec:
                ec.default_value = (float(tint_val[0]), float(tint_val[1]), float(tint_val[2]), 1.0)
            if len(tint_val) > 3 and shader_node.inputs.get("Alpha"):
                shader_node.inputs["Alpha"].default_value = max(0.0, min(1.0, float(tint_val[3])))

    # ── Emissive Basic params ──────────────────────────────────────
    if category == "emissive_basic":
        ecolor = _get("emissive_color")
        if ecolor:
            ec = shader_node.inputs.get("Emission Color")
            if ec:
                ec.default_value = (float(ecolor[0]), float(ecolor[1]), float(ecolor[2]), 1.0)
        eint = _get("emissive_intensity") or _find("emissive_factor")
        if eint:
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = max(0.0, float(eint[0]))

    # ── Gradient color params ──────────────────────────────────────
    if category == "gradient_color":
        nt = mat.node_tree
        if nt:
            ramp = nt.nodes.get("MAPGEO_GRAD_RAMP")
            if ramp:
                c_top = _get("colortop")
                c_bot = _get("colorbottom")
                if c_bot and len(ramp.color_ramp.elements) > 0:
                    ramp.color_ramp.elements[0].color = (float(c_bot[0]), float(c_bot[1]), float(c_bot[2]), 1.0)
                if c_top and len(ramp.color_ramp.elements) > 1:
                    ramp.color_ramp.elements[1].color = (float(c_top[0]), float(c_top[1]), float(c_top[2]), 1.0)
            fres = nt.nodes.get("MAPGEO_GRAD_FRESNEL")
            if fres:
                fsize = _find("fresnel_size", "alph_fresnel_size")
                if fsize:
                    fres.inputs["Blend"].default_value = max(0.0, min(1.0, float(fsize[0]) * 0.1))

    # ── Glow / GlowSign / Emissive params ──────────────────────────
    if category in ("glow", "glow_sign", "glow_mask", "glow_decal",
                     "emissive_decal", "scrolling_emissive", "flipbook_emissive"):
        glow_color = _get("glow_color") or _get("emissive_color") or _get("emissioncolor")
        if glow_color:
            ec = shader_node.inputs.get("Emission Color") or shader_node.inputs.get("Emission")
            if ec:
                ec.default_value = (float(glow_color[0]), float(glow_color[1]), float(glow_color[2]), 1.0)

        emit_strength = (_get("emissive_intensity") or _get("bloom_factor") or
                         _get("bloom_intensity") or _find("emissivefactor"))
        if emit_strength:
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = max(0.0, float(emit_strength[0]))

        diffuse_color = _get("diffuse_color")
        if diffuse_color:
            bc = shader_node.inputs.get("Base Color")
            if bc and not bc.links:
                bc.default_value = (float(diffuse_color[0]), float(diffuse_color[1]), float(diffuse_color[2]), 1.0)

    # ── Twist by noise params ──────────────────────────────────────
    if category == "twist_emissive":
        main_color = _get("maincolor")
        if main_color:
            bc = shader_node.inputs.get("Base Color")
            if bc and not bc.links:
                bc.default_value = (float(main_color[0]), float(main_color[1]), float(main_color[2]), 1.0)
        emf = _find("emissivefactor")
        if emf:
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = max(0.0, float(emf[0]))

    # ── Water-specific params ──────────────────────────────────────
    if category in ("water", "water_river", "water_radial", "water_flow",
                     "water_ocean", "water_rain"):
        nt = mat.node_tree if mat else None
        if nt:
            # Water colours
            water_color = (_get("water_color") or _get("color_inside") or
                           _get("color_baseline") or _get("tint_color") or
                           _find("deep_color"))
            if water_color:
                bc = shader_node.inputs.get("Base Color")
                if bc and not bc.links:
                    bc.default_value = (float(water_color[0]), float(water_color[1]), float(water_color[2]), 1.0)

            # Flow speed → UV offset
            flow_speed = _find("flowmap_speed", "flow_speed", "flowspeed")
            if flow_speed:
                mp = nt.nodes.get("MAPGEO_MAPPING")
                if mp and mp.inputs.get("Location"):
                    mp.inputs["Location"].default_value[0] = float(flow_speed[0]) * 0.02

            # Fresnel
            fresnel_val = _find("fresnel")
            fresnel_pow = nt.nodes.get("MAPGEO_WATER_FRESNEL_POW")
            if fresnel_val and fresnel_pow and len(fresnel_pow.inputs) > 1:
                fresnel_pow.inputs[1].default_value = max(0.2, float(fresnel_val[0]))

            # Opacity
            opacity_val = _find("wateropacity", "translucent")
            water_mix = nt.nodes.get("MAPGEO_WATER_MIX")
            if opacity_val and water_mix and water_mix.inputs.get("Fac"):
                base = float(opacity_val[0])
                water_mix.inputs["Fac"].default_value = max(0.0, min(1.0, 1.0 - base))

            # Ocean specular
            if category == "water_ocean":
                spec_color = _get("spec_color")
                if spec_color:
                    bc = shader_node.inputs.get("Base Color")
                    if bc and not bc.links:
                        bc.default_value = (float(spec_color[0]), float(spec_color[1]), float(spec_color[2]), 1.0)
                spec_int = _find("specular_intensity", "specular_min_max")
                if spec_int:
                    si = shader_node.inputs.get("Specular IOR Level") or shader_node.inputs.get("Specular")
                    if si:
                        si.default_value = max(0.0, min(1.0, float(spec_int[0])))

    # ── Alpha test value ───────────────────────────────────────────
    alpha_test = _get("alphatestvalue") or _get("alpha_test_value") or _get("alphaclipvalue")
    if alpha_test:
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = max(0.0, min(1.0, float(alpha_test[0])))

    # ── Planar reflection strength ─────────────────────────────────
    if category == "planar_reflection":
        refl_str = _get("planarreflectionstrength")
        if refl_str and shader_node.inputs.get("Roughness"):
            shader_node.inputs["Roughness"].default_value = max(0.0, 1.0 - float(refl_str[0]))
        # ColorTint for TFT_PlanarReflection → tint ×2
        ctint = _get("colortint")
        if ctint:
            bc = shader_node.inputs.get("Base Color")
            if bc and not bc.links:
                bc.default_value = (
                    min(float(ctint[0]) * 2.0, 1.0),
                    min(float(ctint[1]) * 2.0, 1.0),
                    min(float(ctint[2]) * 2.0, 1.0),
                    1.0,
                )

    # ── Emission color variants (generic) ──────────────────────────
    # Handles: EMISSION_EmissionColor, EmissionColor, FLOW_Color,
    #          Bloom_Color, BloomColor (as emission overlay)
    if category not in ("emissive_basic", "faelights", "hologram",
                         "glow", "glow_sign", "glow_mask", "glow_decal",
                         "emissive_decal", "scrolling_emissive", "flipbook_emissive",
                         "twist_emissive", "gradient_color"):
        # Skip emission override when lightmap owns the emission channel
        _lm_owns_em = bool(mat.get("lightmap_texture"))
        try:
            _mm = json.loads(mat.get("shader_macros", "{}"))
            if "NO_BAKED_LIGHTING" in _mm:
                _lm_owns_em = False
        except Exception:
            pass
        if has_emissive_sampler and not _lm_owns_em:
            emission_color = (_get("emission_emissioncolor") or _get("emissioncolor")
                              or _get("flow_color"))
            if emission_color:
                ec = shader_node.inputs.get("Emission Color")
                if ec:
                    ec.default_value = (float(emission_color[0]), float(emission_color[1]),
                                        float(emission_color[2]), 1.0)
                    es = shader_node.inputs.get("Emission Strength")
                    if es and es.default_value < 0.01:
                        es.default_value = 1.0

            bloom_color = _get("bloom_color") or _get("bloomcolor")
            if bloom_color:
                ec = shader_node.inputs.get("Emission Color")
                if ec and not ec.links:
                    ec.default_value = (float(bloom_color[0]), float(bloom_color[1]),
                                        float(bloom_color[2]), 1.0)
        elif not _lm_owns_em:
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = 0.0

    # ── Color_Multiply (overlay tint, TFT_Skybox etc.) ─────────────
    color_mult = _get("color_multiply")
    if color_mult and shader_node.inputs.get("Base Color"):
        bc = shader_node.inputs["Base Color"]
        if bc.links:
            nt = mat.node_tree
            if nt:
                tex_link = bc.links[0]
                from_socket = tex_link.from_socket
                # Only insert if we haven't inserted tint already
                if not nt.nodes.get("MAPGEO_TINT"):
                    nt.links.remove(tex_link)
                    mult_node = nt.nodes.new("ShaderNodeMix")
                    mult_node.name = "MAPGEO_TINT"
                    mult_node.data_type = 'RGBA'
                    mult_node.blend_type = 'MULTIPLY'
                    mult_node.location = (-50, 200)
                    mult_node.inputs["Factor"].default_value = 1.0
                    mult_node.label = f"Color Multiply"
                    nt.links.new(from_socket, mult_node.inputs[6])
                    mult_node.inputs[7].default_value = (
                        float(color_mult[0]), float(color_mult[1]),
                        float(color_mult[2]), 1.0
                    )
                    nt.links.new(mult_node.outputs[2], bc)

    # ── OverlayColor (DefaultEnv_Flat_ColorMult_Overlay) ───────────
    overlay_color = _get("overlaycolor")
    if overlay_color and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(overlay_color[0]), float(overlay_color[1]),
                                float(overlay_color[2]), 1.0)
            es = shader_node.inputs.get("Emission Strength")
            if es and es.default_value < 0.01:
                es.default_value = 0.3  # subtle overlay as emission hint

    # ── Foliage / TreeCanopy colors ────────────────────────────────
    if category in ("foliage", "standard", "alpha_test", "alpha_test_double"):
        under_color = _get("undercolor") or _get("color_bottom")
        if under_color and shader_node.inputs.get("Base Color"):
            bc = shader_node.inputs["Base Color"]
            if not bc.links:
                bc.default_value = (float(under_color[0]), float(under_color[1]),
                                    float(under_color[2]), 1.0)

    # ── Glass extended colors ──────────────────────────────────────
    if category in ("glass", "glass_diffuse", "glass_blend"):
        nt = mat.node_tree
        # HighColor / LowColor → glass color blend (DefaultEnv_Glass_BlendAndReflection)
        high_color = _get("highcolor")
        low_color = _get("lowcolor")
        if nt:
            cmix = nt.nodes.get("MAPGEO_GLASS_COLOR_MIX")
            if cmix:
                if low_color:
                    cmix.inputs[6].default_value = (float(low_color[0]), float(low_color[1]),
                                                     float(low_color[2]), 1.0)
                if high_color:
                    cmix.inputs[7].default_value = (float(high_color[0]), float(high_color[1]),
                                                     float(high_color[2]), 1.0)

        # ReflectionColor → Emission hint (reflection tint)
        refl_color = _get("reflectioncolor")
        if refl_color and shader_node.inputs.get("Emission Color"):
            ec = shader_node.inputs["Emission Color"]
            if not ec.links:
                ec.default_value = (float(refl_color[0]), float(refl_color[1]),
                                    float(refl_color[2]), 1.0)
                es = shader_node.inputs.get("Emission Strength")
                if es:
                    refl_int = _get("reflectionintensity")
                    es.default_value = float(refl_int[0]) if refl_int else 0.2

        # SpecularColor / SunColor → Specular Tint
        spec_col = _get("specularcolor") or _get("suncolor")
        if spec_col and shader_node.inputs.get("Specular Tint"):
            shader_node.inputs["Specular Tint"].default_value = (
                float(spec_col[0]), float(spec_col[1]), float(spec_col[2]), 1.0
            )

    # ── Water extended colors ──────────────────────────────────────
    if category in ("water", "water_river", "water_radial", "water_flow",
                     "water_ocean", "water_rain"):
        # Color_Outside for Flowmap_River (secondary water color)
        color_out = _get("color_outside")
        if color_out:
            bc = shader_node.inputs.get("Base Color")
            if bc and not bc.links:
                bc.default_value = (float(color_out[0]), float(color_out[1]),
                                    float(color_out[2]), 1.0)

        # Deep_Color (TFT_Water — darker depth color)
        deep_color = _get("deep_color")
        if deep_color and shader_node.inputs.get("Base Color"):
            bc = shader_node.inputs["Base Color"]
            if not bc.links:
                bc.default_value = (float(deep_color[0]), float(deep_color[1]),
                                    float(deep_color[2]), 1.0)

        # Foam_Color → store as emission hint (no foam in Blender)
        foam_color = _get("foam_color")
        if foam_color and shader_node.inputs.get("Emission Color"):
            ec = shader_node.inputs["Emission Color"]
            if not ec.links:
                ec.default_value = (float(foam_color[0]), float(foam_color[1]),
                                    float(foam_color[2]), 1.0)
                foam_amount = _get("foam_amount")
                if foam_amount:
                    es = shader_node.inputs.get("Emission Strength")
                    if es:
                        es.default_value = max(0.0, float(foam_amount[0]))

        # Rim_Color (OD_FlowMap) → Emission
        rim_color = _get("rim_color")
        if rim_color and shader_node.inputs.get("Emission Color"):
            ec = shader_node.inputs["Emission Color"]
            if not ec.links:
                ec.default_value = (float(rim_color[0]), float(rim_color[1]),
                                    float(rim_color[2]), 1.0)
                rim_int = _get("rim_intensity")
                if rim_int:
                    es = shader_node.inputs.get("Emission Strength")
                    if es:
                        es.default_value = max(0.0, float(rim_int[0]))

    # ── ShadowColor (flag/wave shaders) ────────────────────────────
    shadow_color = _get("shadowcolor")
    if shadow_color:
        # Shadow tint approximation — darken Base Color slightly
        bc = shader_node.inputs.get("Base Color")
        if bc and not bc.links:
            # Blend shadow color with existing base
            existing = list(bc.default_value)
            bc.default_value = (
                existing[0] * 0.7 + float(shadow_color[0]) * 0.3,
                existing[1] * 0.7 + float(shadow_color[1]) * 0.3,
                existing[2] * 0.7 + float(shadow_color[2]) * 0.3,
                1.0,
            )

    # ── Starting_Color / Color (transition/scrolling) ──────────────
    starting_color = _get("starting_color") or _get("color")
    if starting_color:
        bc = shader_node.inputs.get("Base Color")
        if bc and not bc.links:
            bc.default_value = (float(starting_color[0]), float(starting_color[1]),
                                float(starting_color[2]), 1.0)

    # ── Color_Blend (TFT_Skybox) ───────────────────────────────────
    color_blend = _get("color_blend")
    if color_blend and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(color_blend[0]), float(color_blend[1]),
                                float(color_blend[2]), 1.0)

    # ── Background_color (TFT_Blink) ──────────────────────────────
    bg_color = _get("background_color")
    if bg_color and shader_node.inputs.get("Base Color"):
        bc = shader_node.inputs["Base Color"]
        if not bc.links:
            bc.default_value = (float(bg_color[0]), float(bg_color[1]),
                                float(bg_color[2]), 1.0)

    # ── FogColor (billboard shaders) ───────────────────────────────
    fog_color = _get("fogcolor")
    if fog_color and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(fog_color[0]), float(fog_color[1]),
                                float(fog_color[2]), 1.0)

    # ── WaveTintColor (SRX Chemtech/Hextech) ───────────────────────
    wave_tint = _get("wavetintcolor")
    if wave_tint and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(wave_tint[0]), float(wave_tint[1]),
                                float(wave_tint[2]), 1.0)
            es = shader_node.inputs.get("Emission Strength")
            if es and es.default_value < 0.01:
                es.default_value = 0.5

    # ── ScrollingTexBTint (ENV_ScrollingDiffuse) ───────────────────
    scroll_tint = _get("scrollingtexbtint")
    if scroll_tint and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(scroll_tint[0]), float(scroll_tint[1]),
                                float(scroll_tint[2]), 1.0)

    # ── RippleColor (TFT_VertexRipple) ─────────────────────────────
    ripple_color = _get("ripplecolor")
    if ripple_color and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(ripple_color[0]), float(ripple_color[1]),
                                float(ripple_color[2]), 1.0)

    # ── Sparkle / Glitter colors (TFT_SparkleParallaxGlow) ─────────
    glitter_a = _get("glittercolora")
    if glitter_a and shader_node.inputs.get("Emission Color"):
        ec = shader_node.inputs["Emission Color"]
        if not ec.links:
            ec.default_value = (float(glitter_a[0]), float(glitter_a[1]),
                                float(glitter_a[2]), 1.0)
            es = shader_node.inputs.get("Emission Strength")
            if es and es.default_value < 0.01:
                es.default_value = 1.0

    # ── Generic remaining params (only if not already handled) ─────

    # Emission (generic fallback)
    if category not in ("emissive_basic", "faelights", "hologram", "glow",
                         "glow_sign", "glow_mask", "glow_decal", "emissive_decal",
                         "scrolling_emissive", "flipbook_emissive", "twist_emissive",
                         "gradient_color"):
        emission_val = _find("emissive_intensity", "bloom_intensity", "emissivefactor")
        if emission_val and has_emissive_sampler and shader_node.type == 'BSDF_PRINCIPLED':
            es = shader_node.inputs.get("Emission Strength")
            if es:
                es.default_value = max(float(emission_val[0]), 0.0)

    # Roughness (generic)
    if category not in ("glass", "glass_diffuse", "glass_blend",
                         "water", "water_river", "water_radial", "water_flow",
                         "water_ocean", "water_rain", "planar_reflection"):
        rough = _get("roughness") or _get("glass_roughness")
        if rough and shader_node.inputs.get("Roughness"):
            shader_node.inputs["Roughness"].default_value = max(0.0, min(1.0, float(rough[0])))

    # Specular (generic)
    spec = _find("specular_intensity", "reflectivity")
    if spec:
        si = shader_node.inputs.get("Specular IOR Level") or shader_node.inputs.get("Specular")
        if si:
            si.default_value = max(0.0, min(1.0, float(spec[0])))

    # Metallic
    metal = _find("metallic", "metalness", "reflectivity")
    if metal and shader_node.inputs.get("Metallic"):
        shader_node.inputs["Metallic"].default_value = max(0.0, min(1.0, float(metal[0])))

    # See-through alpha (VertexDeform)
    if category == "vertex_deform":
        sta = _get("seethroughalpha")
        if sta and shader_node.inputs.get("Alpha"):
            shader_node.inputs["Alpha"].default_value = max(0.0, min(1.0, float(sta[0])))


def _update_parameters_only(mat):
    """Lightweight parameter update — does NOT rebuild the node graph.

    Finds the existing shader node (MAPGEO_SHADER or any Principled BSDF)
    and the existing tint node (MAPGEO_TINT or any Mix node labelled Tint),
    then updates their values from the stored JSON parameters.
    This preserves loaded textures and node connections.
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return

    nt = mat.node_tree
    nodes = nt.nodes

    # Find shader node (editor-created or loader-created)
    shader_node = nodes.get("MAPGEO_SHADER")
    if not shader_node:
        for node in nodes:
            if node.type == 'BSDF_PRINCIPLED':
                shader_node = node
                break
    if not shader_node:
        return

    # Determine category from shader label or techniques
    category = "standard"
    try:
        techniques = json.loads(mat.get("techniques", "[]"))
        if techniques:
            passes = techniques[0].get("passes", [])
            if passes:
                shader_path = passes[0].get("shader", "")
                _, category = _classify_shader(shader_path)
    except Exception:
        pass

    # Parse parameters
    try:
        params = json.loads(mat.get("parameters", "[]"))
    except Exception:
        params = []

    by_name = {}
    for p in params:
        n = (p.get("name") or "").lower()
        v = p.get("value") or [0.0, 0.0, 0.0, 0.0]
        if n:
            by_name[n] = v

    def _get(name_lower):
        return by_name.get(name_lower)

    # ── Update TintColor ──────────────────────────────────────────
    tint = (_get("tintcolor") or _get("basetex_tintcolor") or _get("colortint")
            or _get("tint") or _get("basetint") or _get("diffuse_tint")
            or _get("diffusetint"))
    if not tint and category not in ("water", "water_river", "water_radial",
                                      "water_flow", "water_ocean", "water_rain"):
        tint = _get("tint_color")

    if tint:
        r = min(float(tint[0]) * 2.0, 1.0)
        g = min(float(tint[1]) * 2.0, 1.0)
        b = min(float(tint[2]) * 2.0, 1.0)

        # Find existing tint node
        tint_node = nodes.get("MAPGEO_TINT")
        if not tint_node:
            for node in nodes:
                if node.type == 'MIX' and node.blend_type == 'MULTIPLY' and 'tint' in (node.label or '').lower():
                    tint_node = node
                    break

        if tint_node:
            # Update existing tint node values
            tint_node.inputs[7].default_value = (r, g, b, 1.0)
            tint_node.label = f"Tint ({r:.2f},{g:.2f},{b:.2f})"
        else:
            # No tint node exists — try to insert one between texture and shader
            bc = shader_node.inputs.get("Base Color") or shader_node.inputs.get("Color")
            if bc and bc.links:
                tex_link = bc.links[0]
                from_socket = tex_link.from_socket
                nt.links.remove(tex_link)
                tint_mix = nodes.new("ShaderNodeMix")
                tint_mix.name = "MAPGEO_TINT"
                tint_mix.data_type = 'RGBA'
                tint_mix.blend_type = 'MULTIPLY'
                tint_mix.location = (-50, 200)
                tint_mix.inputs["Factor"].default_value = 1.0
                tint_mix.label = f"Tint ({r:.2f},{g:.2f},{b:.2f})"
                nt.links.new(from_socket, tint_mix.inputs[6])
                tint_mix.inputs[7].default_value = (r, g, b, 1.0)
                nt.links.new(tint_mix.outputs[2], bc)
            elif bc:
                bc.default_value = (r, g, b, 1.0)

    # ── Other simple scalar params (roughness, metallic, etc.) ────
    rough = _get("roughness") or _get("glass_roughness")
    if rough and shader_node.inputs.get("Roughness"):
        shader_node.inputs["Roughness"].default_value = max(0.0, min(1.0, float(rough[0])))

    metal = _get("metallic") or _get("metalness")
    if metal and shader_node.inputs.get("Metallic"):
        shader_node.inputs["Metallic"].default_value = max(0.0, min(1.0, float(metal[0])))

    # Glass color updates
    if category in ("glass", "glass_diffuse", "glass_blend"):
        cmix = nodes.get("MAPGEO_GLASS_COLOR_MIX")
        if cmix:
            gc1 = _get("glass_color1")
            gc2 = _get("glass_color2") or _get("glass_color")
            if gc1:
                cmix.inputs[6].default_value = (float(gc1[0]), float(gc1[1]), float(gc1[2]), 1.0)
            if gc2:
                cmix.inputs[7].default_value = (float(gc2[0]), float(gc2[1]), float(gc2[2]), 1.0)

    # Emission color/strength (only when an emissive sampler is defined in material data)
    # Skip if material has a lightmap (lightmap manages emission)
    has_emissive_sampler_defined = _material_has_emissive_sampler(mat)
    _has_lightmap = bool(mat.get("lightmap_texture"))
    _has_baked_lt = True
    try:
        _m = json.loads(mat.get("shader_macros", "{}"))
        if "NO_BAKED_LIGHTING" in _m:
            _has_baked_lt = False
    except Exception:
        pass
    _lightmap_owns_emission = _has_lightmap and _has_baked_lt

    es = shader_node.inputs.get("Emission Strength") if shader_node.type == 'BSDF_PRINCIPLED' else None
    if not has_emissive_sampler_defined and not _lightmap_owns_emission:
        if es:
            es.default_value = 0.0
    else:
        emission_col = (_get("emission_emissioncolor") or _get("emissioncolor")
                        or _get("flow_color") or _get("bloom_color") or _get("bloomcolor"))
        if emission_col and shader_node.type == 'BSDF_PRINCIPLED':
            ec = shader_node.inputs.get("Emission Color")
            if ec:
                ec.default_value = (float(emission_col[0]), float(emission_col[1]),
                                    float(emission_col[2]), 1.0)

        emission_val = _get("emissive_intensity") or _get("bloom_intensity") or _get("emissivefactor")
        if emission_val and es:
            es.default_value = max(float(emission_val[0]), 0.0)
        elif es and es.default_value < 0.01:
            es.default_value = 1.0


def _sync_material_preview_from_data(mat, technique_index=0, pass_index=0, assets_folder="", custom_assets_folder="", prioritize_custom=False):
    """Sync Blender preview from League techniques/samplers/parameters state.
    
    Args:
        mat: Blender material
        technique_index: Which technique to use
        pass_index: Which pass within technique to use
        assets_folder: Original Riot assets folder path
        custom_assets_folder: Custom assets folder path
        prioritize_custom: If True, check custom folder first
    """
    if not mat:
        return
    try:
        techniques = json.loads(mat.get("techniques", "[]"))
    except Exception:
        techniques = []

    if techniques and 0 <= technique_index < len(techniques):
        passes = techniques[technique_index].get("passes", [])
        if not (0 <= pass_index < len(passes)):
            pass_index = 0
        if not passes:
            return
        p = passes[pass_index]
        _apply_pass_material_settings(mat, p)
        _rebuild_shader_preview_nodes(mat, p.get("shader", ""), assets_folder, custom_assets_folder, prioritize_custom)


def refresh_league_material_preview(mat, technique_index=0, pass_index=0, assets_folder="", custom_assets_folder="", prioritize_custom=False):
    """Public helper: rebuild one material preview from stored League data.

    Returns True if a refresh was performed, False otherwise.
    
    Args:
        mat: Blender material
        technique_index: Which technique to use
        pass_index: Which pass within technique to use
        assets_folder: Original Riot assets folder path
        custom_assets_folder: Custom assets folder path
        prioritize_custom: If True, check custom folder first
    """
    if not mat:
        return False
    if "samplers" not in mat and "parameters" not in mat and "techniques" not in mat:
        return False
    _sync_material_preview_from_data(mat, technique_index, pass_index, assets_folder, custom_assets_folder, prioritize_custom)
    return True


def refresh_league_materials(materials=None, technique_index=0, pass_index=0):
    """Public helper: refresh many League materials from stored JSON data.

    Args:
        materials: Iterable of bpy.types.Material or None for all bpy.data.materials.
        technique_index: Technique index to preview.
        pass_index: Pass index to preview.

    Returns:
        Number of materials refreshed.
    """
    # Get assets folders from scene settings (includes Riot WAD fallback)
    assets_folder, custom_assets_folder, prioritize_custom = _get_assets_folders_from_context()
    
    mats = materials if materials is not None else bpy.data.materials
    refreshed = 0
    for mat in mats:
        try:
            if refresh_league_material_preview(mat, technique_index, pass_index, assets_folder, custom_assets_folder, prioritize_custom):
                refreshed += 1
        except Exception:
            continue
    return refreshed


def _get_riot_wad_assets_fallback():
    """Get Riot WAD cache assets path if project settings allow it.
    
    Returns the riot assets folder path, or empty string.
    Uses the already-extracted WAD cache (fast — no re-extraction).
    """
    try:
        if hasattr(bpy.context, 'scene') and hasattr(bpy.context.scene, 'project_settings'):
            ps = bpy.context.scene.project_settings
            if ps.use_riot_base and ps.project_map_id and ps.league_install:
                from . import project_manager
                league_path = bpy.path.abspath(ps.league_install)
                riot_cache = project_manager._ensure_riot_wad_cache(league_path, ps.project_map_id)
                if riot_cache:
                    riot_assets = os.path.join(riot_cache, "assets")
                    if os.path.isdir(riot_assets):
                        return riot_assets
    except Exception:
        pass
    return ""


def _get_assets_folders_from_context():
    """Get assets folders from scene settings.
    
    If custom_assets_folder is not set, auto-populates from Riot WAD cache
    when project settings are available.
    
    Returns:
        Tuple of (assets_folder, custom_assets_folder, prioritize_custom)
    """
    assets_folder = ""
    custom_assets_folder = ""
    prioritize_custom = False
    
    if hasattr(bpy.context, 'scene') and hasattr(bpy.context.scene, 'mapgeo_settings'):
        settings = bpy.context.scene.mapgeo_settings
        assets_folder = getattr(settings, 'assets_folder', '')
        custom_assets_folder = getattr(settings, 'custom_assets_folder', '')
        prioritize_custom = getattr(settings, 'prioritize_custom_assets', False)
    
    # Auto-populate Riot WAD fallback if custom_assets_folder is not set
    if not custom_assets_folder:
        custom_assets_folder = _get_riot_wad_assets_fallback()
    
    return assets_folder, custom_assets_folder, prioritize_custom


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

        tex_path = (texture_path or "").strip()
        sampler_name = samplers[sampler_index].get('textureName', '')

        # Allow clearing sampler paths (important for keeping UI/data/node state in sync)
        if not tex_path:
            old_path = samplers[sampler_index].get('texturePath', '')
            samplers[sampler_index]["texturePath"] = ""
            mat["samplers"] = json.dumps(samplers)

            message = f"Path: '{old_path}' -> ''"
            if mat.use_nodes and mat.node_tree:
                cleared = False
                sampler_name_l = sampler_name.lower()
                diffuse_aliases = {
                    "diffusetexture", "diffuse_texture", "baked_diffuse_texture", "colortexture", "_maintex"
                }
                for node in mat.node_tree.nodes:
                    if node.type != 'TEX_IMAGE':
                        continue
                    if node.label == sampler_name or (sampler_name_l in diffuse_aliases and node.name == "MAPGEO_DIFFUSE"):
                        node.image = None
                        cleared = True
                if cleared:
                    message += " | viewport cleared"

            return True, message

        if not tex_path.lower().endswith(('.tex', '.dds', '.png')):
            tex_path += '.tex'

        # Resolve the on-disk file ------------------------------------------
        assets_folder, custom_assets_folder, prioritize_custom = _get_assets_folders_from_context()

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
                img = None
                if resolved_path.lower().endswith('.tex'):
                    converter = TexConverter()
                    img = converter.load_tex_as_blender_image(resolved_path)
                elif os.path.exists(resolved_path):
                    img = bpy.data.images.load(resolved_path, check_existing=True)

                if img:
                    if mat.use_nodes and mat.node_tree:
                        # Try to find the correct image node.
                        # First look for a node whose label matches the sampler name.
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
                            target_node.image = img
                            message += f" | viewport updated ({img.name})"
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
    """Import materials from a League .materials.bin file"""
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


def _normalize_shader_key(shader_name: str) -> str:
    return "".join(ch for ch in shader_name.lower() if ch.isalnum())


def _resolve_template_path_for_staticmesh(shader_name: str):
    expected_path = f"Shaders/StaticMesh/{shader_name}"
    if expected_path in _SHADER_TEMPLATES:
        return expected_path

    target_lower = shader_name.lower()
    target_norm = _normalize_shader_key(shader_name)

    for path, tpl in _SHADER_TEMPLATES.items():
        short = tpl.get("short_name", path.rsplit("/", 1)[-1])
        leaf = path.rsplit("/", 1)[-1]

        if short.lower() == target_lower or leaf.lower() == target_lower:
            return path

        if _normalize_shader_key(short) == target_norm or _normalize_shader_key(leaf) == target_norm:
            return path

    return None


def _apply_template_to_material(mat, shader_template: str, threshold: int, use_shader_defaults: bool = True):
    tpl = _SHADER_TEMPLATES.get(shader_template)
    if not tpl:
        return False

    mat["league_material_name"] = mat.name
    mat["league_material_type"] = "StaticMaterialDef"

    default_texture_map = {}
    if use_shader_defaults:
        default_texture_map = _load_shader_default_textures().get(shader_template, {})

    samplers = []
    for s in tpl.get("samplers", []):
        if s.get("frequency", 0) >= threshold:
            sampler_name = s["name"]
            samplers.append({
                "textureName": sampler_name,
                "texturePath": default_texture_map.get(sampler_name.lower(), ""),
                "addressU": s.get("addressU", 1),
                "addressV": s.get("addressV", 1),
                "addressW": s.get("addressW", 1),
            })
    mat["samplers"] = json.dumps(samplers)

    params = []
    for p in tpl.get("parameters", []):
        if p.get("frequency", 0) >= threshold:
            params.append({
                "name": p["name"],
                "value": p.get("value", [0, 0, 0, 0]),
            })
    mat["parameters"] = json.dumps(params)

    switches = []
    for s in tpl.get("switches", []):
        if s.get("frequency", 0) >= threshold:
            switches.append({
                "name": s["name"],
                "on": s.get("on", False),
            })
    mat["switches"] = json.dumps(switches)

    mat["shader_macros"] = json.dumps(tpl.get("macros", {}))

    blend = tpl.get("blend", {})
    technique = {
        "name": "normal",
        "passes": [{
            "shader": shader_template,
            "blendEnable": blend.get("blendEnable", False),
            "srcColorBlendFactor": blend.get("srcColorBlendFactor", 1),
            "dstColorBlendFactor": blend.get("dstColorBlendFactor", 0),
            "srcAlphaBlendFactor": blend.get("srcAlphaBlendFactor", 1),
            "dstAlphaBlendFactor": blend.get("dstAlphaBlendFactor", 0),
        }],
    }
    mat["techniques"] = json.dumps([technique])

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

    _, category = _classify_shader(shader_template)
    mat["shader_name"] = shader_template.rsplit("/", 1)[-1]
    mat["shader_category"] = category
    if use_shader_defaults and _SHADER_DEFAULT_TEXTURES_SOURCE:
        mat["shader_defaults_source"] = _SHADER_DEFAULT_TEXTURES_SOURCE
    return True


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
    use_shader_defaults: BoolProperty(
        name="Use Riot Default Textures",
        default=True,
        description="Auto-fill sampler texture paths from Shaders.wad data/shaders/shaders.py",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "shader_template")
        layout.prop(self, "new_name")
        layout.prop(self, "include_low_freq")
        layout.prop(self, "use_shader_defaults")

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
        short_name = tpl.get("short_name", self.shader_template.rsplit("/", 1)[-1])

        mat = bpy.data.materials.new(name=self.new_name)
        mat.use_nodes = True
        _apply_template_to_material(mat, self.shader_template, threshold, self.use_shader_defaults)
        _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())
        _tag_redraw(context)

        samplers = json.loads(mat.get("samplers", "[]"))
        params = json.loads(mat.get("parameters", "[]"))
        switches = json.loads(mat.get("switches", "[]"))
        self.report(
            {'INFO'},
            f"Created '{mat.name}' from {short_name} template "
            f"({len(samplers)} samplers, {len(params)} params, {len(switches)} switches)",
        )
        return {'FINISHED'}


class MAPGEO_OT_create_staticmesh_shader_previews(Operator):
    """Create preview meshes and assign StaticMesh shader materials"""
    bl_idname = "mapgeo.create_staticmesh_shader_previews"
    bl_label = "Create StaticMesh Shader Previews"
    bl_options = {'REGISTER', 'UNDO'}

    name_prefix: StringProperty(
        name="Name Prefix",
        default="SM_",
        description="Material name prefix for template-generated materials",
    )
    include_low_freq: BoolProperty(
        name="Include Rare Properties",
        default=False,
        description="Also include low-frequency template params/switches",
    )
    rebuild_materials: BoolProperty(
        name="Rebuild Materials",
        default=False,
        description="Re-apply templates to existing preview materials",
    )
    use_shader_defaults: BoolProperty(
        name="Use Riot Default Textures",
        default=True,
        description="Auto-fill sampler texture paths from Shaders.wad data/shaders/shaders.py",
    )
    add_shader_labels: BoolProperty(
        name="Add Shader Labels",
        default=True,
        description="Create a text label for each preview mesh",
    )
    labels_as_mesh: BoolProperty(
        name="Convert Labels to Mesh",
        default=False,
        description="Convert text labels to mesh objects (exportable to mapgeo)",
    )
    label_size: FloatProperty(
        name="Label Size",
        default=0.25,
        min=0.01,
        description="Size of shader name labels",
    )
    label_offset_y: FloatProperty(
        name="Label Y Offset",
        default=1.05,
        min=0.0,
        description="Distance in front of each preview plane",
    )
    label_offset_z: FloatProperty(
        name="Label Z Offset",
        default=0.02,
        min=0.0,
        description="Height offset for labels",
    )
    collection_name: StringProperty(
        name="Collection",
        default="StaticMesh_Shader_Previews",
        description="Collection to store preview meshes",
    )
    grid_columns: IntProperty(
        name="Columns",
        default=8,
        min=1,
        max=64,
        description="Number of columns in the preview grid",
    )
    spacing: FloatProperty(
        name="Spacing",
        default=5.0,
        min=0.1,
        description="Spacing between preview meshes",
    )
    plane_size: FloatProperty(
        name="Plane Size",
        default=1.5,
        min=0.1,
        description="Size of each preview plane",
    )
    rebuild_collection: BoolProperty(
        name="Rebuild Collection",
        default=True,
        description="Delete existing preview collection contents before creating",
    )

    def execute(self, context):
        json_path = os.path.join(os.path.dirname(__file__), "staticmesh_shader_list.json")
        if not os.path.exists(json_path):
            self.report({'ERROR'}, f"Missing shader list: {json_path}")
            return {'CANCELLED'}

        try:
            with open(json_path, "r", encoding="utf-8") as handle:
                shader_names = json.load(handle)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to read shader list: {exc}")
            return {'CANCELLED'}

        behavior_order = {
            "water": 0,
            "water_river": 0,
            "water_radial": 0,
            "water_flow": 0,
            "water_ocean": 0,
            "water_rain": 0,
            "glass": 1,
            "glass_diffuse": 1,
            "glass_blend": 1,
            "planar_reflection": 1,
            "emissive_basic": 2,
            "glow": 2,
            "glow_sign": 2,
            "glow_mask": 2,
            "glow_decal": 2,
            "emissive_decal": 2,
            "hologram": 3,
            "faelights": 3,
            "gradient_color": 3,
            "flipbook_emissive": 3,
            "twist_emissive": 3,
            "terrain_4tex": 4,
            "vertex_deform": 4,
            "foliage": 5,
            "scrolling": 5,
            "scrolling_emissive": 5,
            "transition": 5,
            "parallax": 6,
            "sparkle_parallax": 6,
            "cloth": 6,
            "alpha_test": 7,
            "alpha_test_double": 7,
            "standard": 9,
        }

        shader_entries = []
        for shader_name in shader_names:
            template_path = _resolve_template_path_for_staticmesh(shader_name)
            classify_path = template_path if template_path else f"Shaders/StaticMesh/{shader_name}"
            _, category = _classify_shader(classify_path)
            rank = behavior_order.get(category, 99)
            shader_entries.append((rank, category, shader_name, template_path))

        shader_entries.sort(key=lambda item: (item[0], item[1], item[2].lower()))

        root_collection = context.scene.collection
        preview_collection = bpy.data.collections.get(self.collection_name)
        if preview_collection is None:
            preview_collection = bpy.data.collections.new(self.collection_name)
            root_collection.children.link(preview_collection)
        elif self.rebuild_collection:
            for obj in list(preview_collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)

        created = 0
        labels_created = 0
        skipped = 0

        label_material = None
        if self.add_shader_labels and self.labels_as_mesh:
            label_material = bpy.data.materials.get("SM_ShaderLabel")
            if label_material is None:
                label_material = bpy.data.materials.new(name="SM_ShaderLabel")
                label_material.use_nodes = True
                label_nodes = label_material.node_tree.nodes
                label_links = label_material.node_tree.links
                label_nodes.clear()
                emission = label_nodes.new("ShaderNodeEmission")
                emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
                emission.inputs["Strength"].default_value = 2.0
                out = label_nodes.new("ShaderNodeOutputMaterial")
                label_links.new(emission.outputs["Emission"], out.inputs["Surface"])
        for _, category, shader_name, template_path in shader_entries:
            if not template_path:
                skipped += 1
                continue

            mat_name = f"{self.name_prefix}{shader_name}"
            mat = bpy.data.materials.get(mat_name)
            if mat is None:
                mat = bpy.data.materials.new(name=mat_name)

            if mat is None:
                skipped += 1
                continue

            preview_index = created
            if self.rebuild_materials or "techniques" not in mat:
                threshold = 0 if self.include_low_freq else 10
                _apply_template_to_material(mat, template_path, threshold, self.use_shader_defaults)
                _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())

            col = preview_index % self.grid_columns
            row = preview_index // self.grid_columns
            x = col * self.spacing
            y = -row * self.spacing

            mesh = bpy.data.meshes.new(f"SM_Preview_{shader_name}")
            half = self.plane_size * 0.5
            verts = [
                (-half, -half, 0.0),
                (half, -half, 0.0),
                (half, half, 0.0),
                (-half, half, 0.0),
            ]
            faces = [(0, 1, 2, 3)]
            mesh.from_pydata(verts, [], faces)
            mesh.update()

            obj = bpy.data.objects.new(f"SM_Preview_{shader_name}", mesh)
            obj.location = (x, y, 0.0)
            preview_collection.objects.link(obj)

            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

            obj["preview_shader_name"] = shader_name
            obj["preview_shader_category"] = category

            if self.add_shader_labels:
                curve = bpy.data.curves.new(f"SM_LabelCurve_{shader_name}", type='FONT')
                curve.body = shader_name
                curve.size = self.label_size
                curve.align_x = 'CENTER'
                curve.align_y = 'CENTER'

                label_obj = bpy.data.objects.new(f"SM_Label_{shader_name}", curve)
                label_obj.location = (x, y - self.label_offset_y, self.label_offset_z)
                preview_collection.objects.link(label_obj)

                if self.labels_as_mesh:
                    for scene_obj in context.view_layer.objects:
                        scene_obj.select_set(False)
                    label_obj.select_set(True)
                    context.view_layer.objects.active = label_obj
                    try:
                        bpy.ops.object.convert(target='MESH')
                    except Exception:
                        pass
                    converted_obj = context.view_layer.objects.active
                    if converted_obj and converted_obj.type == 'MESH':
                        converted_obj["preview_shader_name"] = shader_name
                        if label_material:
                            if converted_obj.data.materials:
                                converted_obj.data.materials[0] = label_material
                            else:
                                converted_obj.data.materials.append(label_material)
                        labels_created += 1
                else:
                    labels_created += 1

            created += 1

        _tag_redraw(context)
        self.report({'INFO'}, f"Created {created} preview meshes + {labels_created} labels ({skipped} shaders skipped)")
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
    """Export all League materials to .materials.bin"""
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
    """Export materials merged with an existing .materials.bin file (preserves VFX, containers, etc.)"""
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
        _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())

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
        _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())
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
            _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())
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
        _sync_material_preview_from_data(mat, 0, 0, *_get_assets_folders_from_context())
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
        _sync_material_preview_from_data(mat, len(techniques) - 1, 0, *_get_assets_folders_from_context())
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
    include_low_freq: BoolProperty(
        name="Include Rare Properties",
        default=False,
        description="Also include parameters/switches that appear in <10% of materials using this shader",
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
                box.prop(self, "include_low_freq")
                tpl = _SHADER_TEMPLATES[new_shader]
                threshold = 0 if self.include_low_freq else 10
                samp = len([s for s in tpl.get("samplers", []) if s.get("frequency", 0) >= threshold])
                parm = len([p for p in tpl.get("parameters", []) if p.get("frequency", 0) >= threshold])
                sw = len([s for s in tpl.get("switches", []) if s.get("frequency", 0) >= threshold])
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

        _sync_material_preview_from_data(mat, self.technique_index, self.pass_index, *_get_assets_folders_from_context())

        _tag_redraw(context)
        if shader_changed and self.apply_template and shader in _SHADER_TEMPLATES:
            self.report({'INFO'}, f"Pass updated — shader template applied for {shader.rsplit('/', 1)[-1]}")
        else:
            self.report({'INFO'}, "Pass updated")
        return {'FINISHED'}

    def _apply_shader_template(self, mat, shader_path):
        """Apply shader template data to material, preserving DiffuseTexture path"""
        tpl = _SHADER_TEMPLATES[shader_path]
        threshold = 0 if self.include_low_freq else 10

        # --- Preserve existing sampler paths by sampler name ---
        preserved_paths = {}
        try:
            old_samplers = json.loads(mat.get("samplers", "[]"))
            for s in old_samplers:
                name = (s.get("textureName") or "").strip()
                path = (s.get("texturePath") or "").strip()
                if name and path:
                    preserved_paths[name.lower()] = path
        except Exception:
            pass

        # --- Samplers ---
        samplers = []
        for s in tpl.get("samplers", []):
            if s.get("frequency", 0) >= threshold:
                sampler_name = s["name"]
                sampler = {
                    "textureName": sampler_name,
                    "texturePath": "",
                    "addressU": s.get("addressU"),
                    "addressV": s.get("addressV"),
                    "addressW": s.get("addressW"),
                }
                # Restore existing texture path for matching sampler names
                preserved = preserved_paths.get(sampler_name.lower())
                if preserved:
                    sampler["texturePath"] = preserved
                samplers.append(sampler)
        mat["samplers"] = json.dumps(samplers)

        # --- Parameters ---
        params = []
        for p in tpl.get("parameters", []):
            if p.get("frequency", 0) >= threshold:
                params.append({
                    "name": p["name"],
                    "value": p.get("value", [0, 0, 0, 0]),
                })
        mat["parameters"] = json.dumps(params)

        # --- Switches ---
        switches = []
        for s in tpl.get("switches", []):
            if s.get("frequency", 0) >= threshold:
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
    bl_options = {'DEFAULT_CLOSED'}

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

        # Lightmap info
        lm_tex = mat.get("lightmap_texture", "")
        if lm_tex:
            lm_scale = mat.get("lightmap_color_scale", 1.0)
            col = layout.column(align=True)
            col.label(text="Lightmap:", icon='SHADING_RENDERED')
            col.label(text=f"  {os.path.basename(lm_tex)}")
            if lm_scale != 1.0:
                col.label(text=f"  Scale: {lm_scale:.2f}")


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

        state_box = layout.box()
        state_box.label(text="Current Preview State", icon='MATERIAL')
        blend_mode = getattr(mat, "blend_method",
                             getattr(mat, "surface_render_method", "(n/a)"))
        cull_state = getattr(mat, "use_backface_culling", False)
        state_box.label(text=f"Blend Mode: {blend_mode}")
        state_box.label(text=f"Backface Culling: {'On' if cull_state else 'Off'}")

        # Show detected shader category
        try:
            techniques = json.loads(mat.get("techniques", "[]"))
        except Exception:
            techniques = []
        if techniques:
            first_shader = ""
            passes_t0 = techniques[0].get("passes", [])
            if passes_t0:
                first_shader = passes_t0[0].get("shader", "")
            if first_shader:
                _sn, _cat = _classify_shader(first_shader)
                state_box.label(text=f"Shader Type: {_cat.replace('_', ' ').title()}")
        else:
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
# Shader Validation Panel
# ============================================================================

def _get_shader_from_material(mat):
    """Extract shader path from a Blender material's techniques JSON."""
    try:
        techs = json.loads(mat.get("techniques", "[]"))
        if techs and techs[0].get("passes"):
            return techs[0]["passes"][0].get("shader", "")
    except Exception:
        pass
    return ""


def _get_all_defines_from_material(mat):
    """
    Collect material-level macros and first pass macros from a material.
    Returns (material_macros, pass_macros).
    """
    material_macros = {}
    pass_macros = {}

    try:
        material_macros = json.loads(mat.get("shader_macros", "{}"))
        if not isinstance(material_macros, dict):
            material_macros = {}
    except Exception:
        pass

    try:
        techs = json.loads(mat.get("techniques", "[]"))
        if techs and techs[0].get("passes"):
            pass_macros = techs[0]["passes"][0].get("shaderMacros", {})
            if not isinstance(pass_macros, dict):
                pass_macros = {}
    except Exception:
        pass

    return material_macros, pass_macros


class MAPGEO_OT_validate_shader(Operator):
    """Validate material defines against compiled shader permutations"""
    bl_idname = "mapgeo.validate_shader"
    bl_label = "Validate Shader Defines"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not _HAS_SHADER_VALIDATION:
            self.report({'WARNING'}, "Shader validation unavailable (dx11_shader_parser or xxhash not installed)")
            return {'CANCELLED'}

        mat = context.material
        if not mat or not mat.get("league_material_name"):
            self.report({'WARNING'}, "No League material selected")
            return {'CANCELLED'}

        shader_path = _get_shader_from_material(mat)
        if not shader_path:
            self.report({'WARNING'}, "No shader set on this material")
            return {'CANCELLED'}

        material_macros, pass_macros = _get_all_defines_from_material(mat)

        result = validate_material_defines(
            shader_path=shader_path,
            material_macros=material_macros,
            pass_macros=pass_macros,
        )

        status = result.get("status", "")
        if status == "valid":
            self.report({'INFO'}, "Shader defines are VALID - this material will work in-game")
            return {'FINISHED'}

        if status in ("no_cache", "unknown_shader", "no_xxhash"):
            self.report({'WARNING'}, result.get("message", "Validation unavailable"))
            return {'CANCELLED'}

        # Invalid — do deep analysis
        self.report({'ERROR'}, f"INVALID permutation: {result['message']}")

        # Find nearest valid
        nearest = find_nearest_valid_defines(
            shader_path=shader_path,
            material_macros=material_macros,
            pass_macros=pass_macros,
        )

        # Store results for the panel to display
        mat["_shader_validation"] = json.dumps({
            "status": status,
            "message": result["message"],
            "shader_name": result.get("shader_name", ""),
            "filtered_defines": result.get("filtered_defines", {}),
            "unrecognized_defines": result.get("unrecognized_defines", {}),
            "hash": str(result.get("hash", 0)),
            "multi_value_defines": result.get("multi_value_defines", {}),
            "nearest": [
                {"distance": d, "defines": c, "changes": ch}
                for d, c, ch in (nearest or [])
            ],
        })

        return {'FINISHED'}


class MATERIAL_PT_league_shader_validation(Panel):
    """Shader define validation — checks if material will crash in-game"""
    bl_label = "Shader Validation"
    bl_idname = "MATERIAL_PT_league_shader_validation"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_parent_id = "MATERIAL_PT_league_properties"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        mat = context.material

        if not _HAS_SHADER_VALIDATION:
            layout.label(text="Validation unavailable", icon='ERROR')
            layout.label(text="Install xxhash: pip install xxhash")
            return

        shader_path = _get_shader_from_material(mat)
        if not shader_path:
            layout.label(text="No shader set", icon='INFO')
            return

        short_name = shader_path.rsplit("/", 1)[-1]

        # --- Live quick-check (lightweight: one hash lookup) ---
        material_macros, pass_macros = _get_all_defines_from_material(mat)
        result = validate_material_defines(
            shader_path=shader_path,
            material_macros=material_macros,
            pass_macros=pass_macros,
        )

        status = result.get("status", "")

        # Show what defines were detected
        if material_macros or pass_macros:
            info_box = layout.box()
            info_box.label(text="Defines detected:", icon='INFO')
            if material_macros:
                for k, v in sorted(material_macros.items()):
                    info_box.label(text=f"  Material: {k} = {v}")
            if pass_macros:
                for k, v in sorted(pass_macros.items()):
                    info_box.label(text=f"  Pass: {k} = {v}")

        # Status header
        if status == "valid":
            box = layout.box()
            box.label(text="VALID", icon='CHECKMARK')
            box.label(text=f"{short_name}: exact permutation hash found")
            box.label(text=f"Permutations: {result.get('permutation_count', '?')}  |  "
                       f"Bytecodes: {result.get('bytecode_count', '?')}")
        elif status == "invalid":
            box = layout.box()
            row = box.row()
            row.alert = True
            row.label(text="WILL CRASH", icon='ERROR')

            # Show specific reason
            missing_req = result.get("missing_required", {})
            if missing_req:
                box.label(text=f"{short_name}: missing required shader macro(s)")
                col = box.column(align=True)
                col.alert = True
                col.label(text="Required defines (add these to Shader Macros):")
                for k, v in sorted(missing_req.items()):
                    col.label(text=f"    {k} = {v}", icon='ERROR')
            else:
                box.label(text=f"{short_name}: no compiled permutation for these defines")

            # Show the filtered defines that were used
            filtered = result.get("filtered_defines", {})
            if filtered:
                col = box.column(align=True)
                col.label(text="Active defines (after filtering):")
                for k, v in sorted(filtered.items()):
                    col.label(text=f"    {k} = {v}", icon='DOT')

            # Show unrecognized defines
            unrec = result.get("unrecognized_defines", {})
            if unrec:
                col = box.column(align=True)
                col.label(text="Ignored (not in shader):")
                for k, v in sorted(unrec.items()):
                    col.label(text=f"    {k} = {v}", icon='REMOVE')

            # Show multi-value defines (potential trouble spots)
            multi = result.get("multi_value_defines", {})
            if multi:
                col = box.column(align=True)
                col.label(text="Multi-value defines (check these):")
                for name, vals in sorted(multi.items()):
                    current_val = filtered.get(name, "absent")
                    col.label(text=f"    {name}: current={current_val}, compiled={vals}",
                              icon='QUESTION')
        elif status == "no_cache":
            box = layout.box()
            box.label(text="Shader cache not found", icon='FILE_FOLDER')
            box.label(text=result.get("message", ""))
        elif status == "unknown_shader":
            box = layout.box()
            box.label(text=f"Unknown shader: {short_name}", icon='QUESTION')
        else:
            box = layout.box()
            box.label(text=result.get("message", "Unavailable"), icon='INFO')

        # Deep analysis button
        layout.operator("mapgeo.validate_shader", text="Deep Validate (Find Fixes)",
                        icon='VIEWZOOM')

        # Show stored deep analysis results if available
        try:
            stored = json.loads(mat.get("_shader_validation", "{}"))
        except Exception:
            stored = {}

        if stored and stored.get("status") == "invalid":
            nearest = stored.get("nearest", [])
            if nearest:
                box = layout.box()
                box.label(text="Nearest Valid Permutations:", icon='RECOVER_LAST')
                for i, entry in enumerate(nearest[:3]):
                    dist = entry.get("distance", "?")
                    changes = entry.get("changes", [])
                    sbox = box.box()
                    sbox.label(text=f"Option {i + 1} ({dist} change{'s' if dist != 1 else ''}):")
                    for ch in changes:
                        if ch.startswith("+"):
                            sbox.label(text=f"  Add: {ch[2:]}", icon='ADD')
                        elif ch.startswith("-"):
                            sbox.label(text=f"  Remove: {ch[2:]}", icon='REMOVE')
                        else:
                            sbox.label(text=f"  Change: {ch.strip()}", icon='FILE_REFRESH')


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
        box.operator("mapgeo.export_materials_merge_file", text="Export Merged", icon='FILE_BLEND')

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

        box = layout.box()
        box.label(text="Shader Library", icon='SHADING_RENDERED')
        col = box.column(align=True)
        col.operator(
            "mapgeo.create_staticmesh_shader_previews",
            text="Create Shader Preview Meshes (Templates)", icon='MESH_GRID',
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
# VFX Definitions Manager (Object Properties)
# ============================================================================

class VfxTreeNodeItem(PropertyGroup):
    """A flattened tree node for VFX bin fields display."""
    depth: IntProperty(name="Depth", default=0)
    path_key: StringProperty(name="Path")
    name_hash: StringProperty(name="Hash")
    resolved_name: StringProperty(name="Name")
    type_label: StringProperty(name="Type")
    value_display: StringProperty(name="Value")
    is_leaf: BoolProperty(name="IsLeaf", default=True)
    is_container: BoolProperty(name="IsContainer", default=False)


class MAPGEO_UL_vfx_tree(UIList):
    """UIList for VFX bin fields tree view."""
    bl_idname = "MAPGEO_UL_vfx_tree"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            indent = "    " * item.depth
            if item.is_container:
                prefix = indent + "\u25BC "
            elif not item.is_leaf:
                prefix = indent + "\u25B6 "
            else:
                prefix = indent + "  "
            name_text = item.resolved_name if item.resolved_name else item.name_hash
            row.label(text=f"{prefix}{name_text}")
            sub = row.row()
            sub.scale_x = 0.35
            sub.label(text=item.type_label)
            sub2 = row.row()
            sub2.scale_x = 1.5
            val_text = item.value_display
            if len(val_text) > 50:
                val_text = val_text[:47] + "..."
            sub2.label(text=val_text)


# Module-level cache to avoid writing to Scene during draw
_vfx_tree_cache_obj = ""
_particle_tree_cache_obj = ""


def _populate_vfx_tree(scene, obj):
    """Populate the VFX tree collection — must be called OUTSIDE Panel.draw()."""
    global _vfx_tree_cache_obj
    col = scene.mapgeo_vfx_tree_items
    obj_name = obj.name if obj else ""
    _vfx_tree_cache_obj = obj_name
    col.clear()
    if not obj:
        return
    fields_json = obj.get("vfx_fields_json", "")
    if not fields_json:
        return
    try:
        fields = json.loads(fields_json)
    except Exception:
        return
    try:
        from . import propertybin_parser as pbp
        flat = pbp.flatten_fields(fields)
    except Exception:
        flat = []
    try:
        from . import community_hashes
        _resolve = community_hashes.resolve_field
    except Exception:
        _resolve = None
    for fn in flat:
        item = col.add()
        item.depth = fn["depth"]
        item.path_key = fn["path"]
        item.name_hash = fn["name_hash"]
        nh = fn["name_hash"]
        if _resolve and nh.startswith("0x"):
            try:
                item.resolved_name = _resolve(int(nh, 16)) or nh
            except (ValueError, TypeError):
                item.resolved_name = nh
        else:
            item.resolved_name = nh
        item.type_label = fn["type_name"]
        item.is_leaf = fn["is_leaf"]
        item.is_container = fn["is_container"]
        item.value_display = fn.get("value_display", "")


def _populate_particle_tree(scene, obj):
    """Populate the particle tree collection — must be called OUTSIDE Panel.draw()."""
    global _particle_tree_cache_obj
    col = scene.mapgeo_particle_tree_items
    obj_name = obj.name if obj else ""
    _particle_tree_cache_obj = obj_name
    col.clear()
    if not obj:
        return
    for prop_key, label, editable, is_int in _PARTICLE_PROPS:
        val = obj.get(prop_key)
        if val is None:
            continue
        item = col.add()
        item.prop_key = prop_key
        item.label = label
        item.value_display = str(val)
        item.editable = editable
        item.is_int = is_int


@bpy.app.handlers.persistent
def _sync_trees_on_depsgraph(scene, depsgraph=None):
    """Depsgraph handler: sync VFX/particle tree collections when active object changes."""
    global _vfx_tree_cache_obj, _particle_tree_cache_obj
    try:
        obj = bpy.context.view_layer.objects.active
    except (AttributeError, RuntimeError):
        return
    obj_name = obj.name if obj else ""
    need_vfx = (_vfx_tree_cache_obj != obj_name)
    need_particle = (_particle_tree_cache_obj != obj_name)
    if not need_vfx and not need_particle:
        return
    try:
        sc = bpy.context.scene
    except (AttributeError, RuntimeError):
        return
    if not hasattr(sc, "mapgeo_vfx_tree_items"):
        return
    if need_vfx:
        _populate_vfx_tree(sc, obj)
    if need_particle:
        _populate_particle_tree(sc, obj)


class OBJECT_PT_vfx_definitions(Panel):
    """VFX Definitions Manager — edit VfxSystemDefinitionData properties"""
    bl_label = "VFX Definitions"
    bl_idname = "OBJECT_PT_vfx_definitions"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.object and context.object.get("is_vfx_definition", False)

    def draw(self, context):
        layout = self.layout
        obj = context.object

        col = layout.column(align=True)
        col.label(text=obj.get("vfx_name", "---"), icon='PARTICLES')
        col.label(text=f"Type: {obj.get('vfx_type', '---')}")

        if obj.get("vfx_entry_hash"):
            col.label(text=f"Entry Hash: {obj['vfx_entry_hash']}")
        if obj.get("vfx_entry_type_hash"):
            col.label(text=f"Type Hash: {obj['vfx_entry_type_hash']}")

        col.separator()
        col.label(text=f"Source: {obj.get('particle_source', '---')}", icon='FILE')

        # Editable fields
        box = layout.box()
        box.label(text="Properties", icon='PREFERENCES')
        col = box.column(align=True)

        row = col.row(align=True)
        row.label(text="Name:")
        op = row.operator("mapgeo.edit_vfx_prop", text="", icon='GREASEPENCIL')
        op.prop_name = "vfx_name"
        op.prop_value = obj.get("vfx_name", "")
        col.label(text=f"  {obj.get('vfx_name', '---')}")

        if obj.get("vfx_entry_hash"):
            row = col.row(align=True)
            row.label(text="Entry Hash:")
            op = row.operator("mapgeo.edit_vfx_prop", text="", icon='GREASEPENCIL')
            op.prop_name = "vfx_entry_hash"
            op.prop_value = obj.get("vfx_entry_hash", "")
            col.label(text=f"  {obj.get('vfx_entry_hash', '---')}")

        # VFX fields from bin — tree view
        fields_json = obj.get("vfx_fields_json", "")
        if fields_json:
            box = layout.box()
            box.label(text="Bin Fields", icon='FILE_TEXT')
            scene = context.scene
            items = scene.mapgeo_vfx_tree_items
            if len(items) > 0:
                box.template_list(
                    "MAPGEO_UL_vfx_tree", "",
                    scene, "mapgeo_vfx_tree_items",
                    scene, "mapgeo_vfx_tree_active",
                    rows=min(len(items), 12),
                    maxrows=20,
                )
                # Show full details for selected item
                idx = scene.mapgeo_vfx_tree_active
                if 0 <= idx < len(items):
                    sel = items[idx]
                    detail = box.column(align=True)
                    detail.label(text=f"Name: {sel.resolved_name}")
                    detail.label(text=f"Hash: {sel.name_hash}")
                    detail.label(text=f"Type: {sel.type_label}")
                    val = sel.value_display
                    if len(val) > 80:
                        # Split long values across lines
                        detail.label(text=f"Value: {val[:80]}")
                        detail.label(text=f"       {val[80:160]}")
                    else:
                        detail.label(text=f"Value: {val}")
            else:
                box.label(text="(no fields)", icon='INFO')


class MAPGEO_OT_edit_vfx_prop(Operator):
    """Edit a VFX definition property"""
    bl_idname = "mapgeo.edit_vfx_prop"
    bl_label = "Edit VFX Property"
    bl_options = {'REGISTER', 'UNDO'}

    prop_name: StringProperty(name="Property")
    prop_value: StringProperty(name="Value")

    def execute(self, context):
        obj = context.object
        if not obj or not obj.get("is_vfx_definition"):
            return {'CANCELLED'}
        obj[self.prop_name] = self.prop_value
        # Re-sync tree (operator context allows writes)
        global _vfx_tree_cache_obj
        _vfx_tree_cache_obj = ""
        _populate_vfx_tree(context.scene, obj)
        _tag_redraw(context)
        self.report({'INFO'}, f"Updated {self.prop_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        obj = context.object
        if obj:
            self.prop_value = str(obj.get(self.prop_name, ""))
        return context.window_manager.invoke_props_dialog(self)


# ============================================================================
# MapParticle Manager (Object Properties)
# ============================================================================

# Particle property definitions: (custom_prop_key, display_label, editable, is_int)
_PARTICLE_PROPS = [
    ("particle_entry_hash",   "Entry Hash",    True,  False),
    ("particle_entry_kind",   "Entry Kind",    True,  False),
    ("particle_system",       "System",        True,  False),
    ("particle_name_value",   "Name",          True,  False),
    ("particle_name_kind",    "Name Kind",     True,  False),
    ("particle_container",    "Container",     True,  False),
    ("particle_visibility_flags", "Vis. Flags", True,  True),
    ("particle_visibility_controller", "Vis. Controller", True, False),
    ("baron_hash",            "Baron Hash",    True,  False),
    ("baron_layers_decoded",  "Layers",        False, False),
    ("baron_dragon_layers_decoded", "Dragon Layers", False, False),
    ("particle_source",       "Source",        False, False),
    ("particle_materials_path", "Materials Path", False, False),
]


class ParticleTreeItem(PropertyGroup):
    """An item in the particle properties list."""
    prop_key: StringProperty(name="Key")
    label: StringProperty(name="Label")
    value_display: StringProperty(name="Value")
    editable: BoolProperty(name="Editable", default=False)
    is_int: BoolProperty(name="IsInt", default=False)


class MAPGEO_UL_particle_tree(UIList):
    """UIList for MapParticle properties."""
    bl_idname = "MAPGEO_UL_particle_tree"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.label, icon='DOT')
            sub = row.row()
            sub.scale_x = 2.0
            val_text = item.value_display
            if len(val_text) > 60:
                val_text = val_text[:57] + "..."
            sub.label(text=val_text)
            if item.editable:
                op = row.operator("mapgeo.edit_particle_prop", text="", icon='GREASEPENCIL')
                op.prop_name = item.prop_key
                op.prop_value = item.value_display
                op.is_int = item.is_int


# _sync_particle_tree removed — population handled by _populate_particle_tree
# called from _sync_trees_on_depsgraph handler and operator execute


class OBJECT_PT_map_particle(Panel):
    """MapParticle Manager — edit placed particle properties"""
    bl_label = "MapParticle"
    bl_idname = "OBJECT_PT_map_particle"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.object and context.object.get("is_particle_system", False)

    def draw(self, context):
        layout = self.layout
        obj = context.object

        # Header info
        col = layout.column(align=True)
        system = obj.get("particle_system", "")
        short_sys = system.rsplit('/', 1)[-1] if '/' in system else system
        col.label(text=short_sys or obj.name, icon='PARTICLES')
        col.label(text=f"Type: {obj.get('particle_entry_kind', '---')}")
        col.label(text=f"Container: {obj.get('particle_container_short', obj.get('particle_container', '---'))}")

        # Properties tree view (populated by depsgraph handler)
        scene = context.scene
        items = scene.mapgeo_particle_tree_items
        if len(items) > 0:
            box = layout.box()
            box.label(text="Properties", icon='PREFERENCES')
            box.template_list(
                "MAPGEO_UL_particle_tree", "",
                scene, "mapgeo_particle_tree_items",
                scene, "mapgeo_particle_tree_active",
                rows=min(len(items), 10),
                maxrows=16,
            )
            # Show full value for selected item
            idx = scene.mapgeo_particle_tree_active
            if 0 <= idx < len(items):
                sel = items[idx]
                detail = box.column(align=True)
                detail.label(text=f"{sel.label}: {sel.value_display}")

        # Transform info
        box = layout.box()
        box.label(text="Transform", icon='ORIENTATION_LOCAL')
        col = box.column(align=True)
        loc = obj.location
        col.label(text=f"Location: ({loc.x:.2f}, {loc.y:.2f}, {loc.z:.2f})")
        scl = obj.scale
        col.label(text=f"Scale: ({scl.x:.2f}, {scl.y:.2f}, {scl.z:.2f})")
        rot = obj.rotation_euler
        col.label(text=f"Rotation: ({math.degrees(rot.x):.1f}\u00b0, {math.degrees(rot.y):.1f}\u00b0, {math.degrees(rot.z):.1f}\u00b0)")


class MAPGEO_OT_edit_particle_prop(Operator):
    """Edit a MapParticle property"""
    bl_idname = "mapgeo.edit_particle_prop"
    bl_label = "Edit Particle Property"
    bl_options = {'REGISTER', 'UNDO'}

    prop_name: StringProperty(name="Property")
    prop_value: StringProperty(name="Value")
    is_int: BoolProperty(default=False)

    def execute(self, context):
        obj = context.object
        if not obj or not obj.get("is_particle_system"):
            return {'CANCELLED'}
        if self.is_int:
            try:
                obj[self.prop_name] = int(self.prop_value)
            except ValueError:
                self.report({'ERROR'}, f"Invalid integer: {self.prop_value}")
                return {'CANCELLED'}
        else:
            obj[self.prop_name] = self.prop_value
        # Sync visibility_layer when visibility_flags changes
        if self.prop_name == "particle_visibility_flags":
            obj["visibility_layer"] = obj[self.prop_name]
        # Sync baron_hash when visibility_controller changes
        if self.prop_name == "particle_visibility_controller":
            obj["baron_hash"] = self.prop_value.strip().upper()
        # Re-sync tree (operator context allows writes)
        global _particle_tree_cache_obj
        _particle_tree_cache_obj = ""
        _populate_particle_tree(context.scene, context.object)
        _tag_redraw(context)
        self.report({'INFO'}, f"Updated {self.prop_name}")
        return {'FINISHED'}

    def invoke(self, context, event):
        obj = context.object
        if obj:
            self.prop_value = str(obj.get(self.prop_name, ""))
        return context.window_manager.invoke_props_dialog(self)


# ============================================================================
# Registration
# ============================================================================

def register_material_editor_properties():
    for cls in (MAPGEO_MaterialParameterProperty, MAPGEO_MaterialSwitchProperty, MAPGEO_MaterialEditorProperties,
                VfxTreeNodeItem, ParticleTreeItem):
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
    # VFX tree view properties
    if not hasattr(bpy.types.Scene, "mapgeo_vfx_tree_items"):
        bpy.types.Scene.mapgeo_vfx_tree_items = CollectionProperty(type=VfxTreeNodeItem)
    if not hasattr(bpy.types.Scene, "mapgeo_vfx_tree_active"):
        bpy.types.Scene.mapgeo_vfx_tree_active = IntProperty(name="Active VFX Field", default=0)
    # Particle tree view properties
    if not hasattr(bpy.types.Scene, "mapgeo_particle_tree_items"):
        bpy.types.Scene.mapgeo_particle_tree_items = CollectionProperty(type=ParticleTreeItem)
    if not hasattr(bpy.types.Scene, "mapgeo_particle_tree_active"):
        bpy.types.Scene.mapgeo_particle_tree_active = IntProperty(name="Active Particle Prop", default=0)


def unregister_material_editor_properties():
    for attr in ("mapgeo_material_props", "mat_editor_search", "mat_template_search", "mat_new_name",
                 "mapgeo_vfx_tree_items", "mapgeo_vfx_tree_active",
                 "mapgeo_particle_tree_items", "mapgeo_particle_tree_active"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in (MAPGEO_MaterialEditorProperties, MAPGEO_MaterialSwitchProperty, MAPGEO_MaterialParameterProperty,
                ParticleTreeItem, VfxTreeNodeItem):
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
    MAPGEO_OT_create_staticmesh_shader_previews,
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
    # Shader validation
    MAPGEO_OT_validate_shader,
    # Panels (parent first, then children)
    MATERIAL_PT_league_properties,
    MATERIAL_PT_league_info,
    MATERIAL_PT_league_samplers,
    MATERIAL_PT_league_parameters,
    MATERIAL_PT_league_switches,
    MATERIAL_PT_league_macros,
    MATERIAL_PT_league_techniques,
    MATERIAL_PT_league_shader_validation,
    # 3D viewport sidebar
    VIEW3D_PT_mapgeo_material_editor_panel,
    # Object Properties — VFX / MapParticle
    VfxTreeNodeItem,
    MAPGEO_UL_vfx_tree,
    OBJECT_PT_vfx_definitions,
    MAPGEO_OT_edit_vfx_prop,
    ParticleTreeItem,
    MAPGEO_UL_particle_tree,
    OBJECT_PT_map_particle,
    MAPGEO_OT_edit_particle_prop,
)


def register():
    register_material_editor_properties()
    for cls in material_editor_classes:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    # Register depsgraph handler for tree sync
    if _sync_trees_on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_trees_on_depsgraph)


def unregister():
    # Remove depsgraph handler
    if _sync_trees_on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_trees_on_depsgraph)
    for cls in reversed(material_editor_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    unregister_material_editor_properties()


if __name__ == "__main__":
    register()
