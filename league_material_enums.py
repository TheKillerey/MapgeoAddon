"""
League of Legends Materials System - Complete Enum Data
=======================================================
Extracted from research across 9,509 materials in 195 files (282.95 MB).
Source: MATERIALS_RESEARCH.md, _research_materials.py, MATERIALS_GUIDE.md,
        and 26 .materials.py files from LoL map data.

All lists are formatted as Blender EnumProperty items: (identifier, name, description)
"""

# =============================================================================
# MATERIAL SWITCHES (178 unique)
# Boolean feature toggles on materials (StaticMaterialSwitchDef)
# =============================================================================

MATERIAL_SWITCHES = [
    # --- Alpha & Blending (10) ---
    ("ALPHA", "ALPHA", "Alpha channel enable (1 file)"),
    ("ALPHACLIP", "ALPHACLIP", "Alpha clipping/cutout mode (21 files)"),
    ("DISABLE_ALPHA", "DISABLE_ALPHA", "Disable alpha channel (3 files)"),
    ("DISABLE_BASE_ALPHA", "DISABLE_BASE_ALPHA", "Disable base texture alpha (3 files)"),
    ("MULTIPLY_ALPHA", "MULTIPLY_ALPHA", "Multiply alpha blending mode (79 files)"),
    ("ON_ALPHA", "ON_ALPHA", "Alpha rendering toggle (1 file)"),
    ("PREMULTIPLIED_ALPHA", "PREMULTIPLIED_ALPHA", "Premultiplied alpha blending (listed in guide)"),
    ("USE_ALPHA", "USE_ALPHA", "Use alpha channel (1 file)"),
    ("USE_ALPHA_FADE", "USE_ALPHA_FADE", "Use alpha fade effect (1 file)"),
    ("USE_ALPHA_PULSE", "USE_ALPHA_PULSE", "Use pulsing alpha effect (1 file)"),

    # --- Debug (17) ---
    ("DEBUG_MASK", "DEBUG_MASK", "Debug mask visualization (1 file)"),
    ("DEBUG_MASTER_VIEW_OFFSET", "DEBUG_MASTER_VIEW_OFFSET", "Debug master view offset (16 files)"),
    ("DEBUG_MODE", "DEBUG_MODE", "Debug mode toggle (19 files)"),
    ("DEBUG_REMOVE_ALPHA", "DEBUG_REMOVE_ALPHA", "Debug: remove alpha (5 files)"),
    ("DEBUG_VIEW_GLOW", "DEBUG_VIEW_GLOW", "Debug: view glow (10 files)"),
    ("DEBUG_VIEW_GRADIENT", "DEBUG_VIEW_GRADIENT", "Debug: view gradient (2 files)"),
    ("DEBUG_VIEW_LS_MASK", "DEBUG_VIEW_LS_MASK", "Debug: view local-space mask (16 files)"),
    ("DEBUG_VIEW_MASK", "DEBUG_VIEW_MASK", "Debug: view mask visualization (25 files)"),
    ("DEBUG_VIEW_RANDOM_FLOAT", "DEBUG_VIEW_RANDOM_FLOAT", "Debug: view random float (16 files)"),
    ("DEBUG_VIEW_SIN", "DEBUG_VIEW_SIN", "Debug: view sinusoidal wave (19 files)"),
    ("DEBUG_VIEW_UV_MASK_X_AXIS", "DEBUG_VIEW_UV_MASK_X_AXIS", "Debug: view UV mask X axis (5 files)"),
    ("DEBUG_VIEW_UV_MASK_Y_AXIS", "DEBUG_VIEW_UV_MASK_Y_AXIS", "Debug: view UV mask Y axis (5 files)"),
    ("DEBUG_VIEW_UV_MASK_Z_AXIS", "DEBUG_VIEW_UV_MASK_Z_AXIS", "Debug: view UV mask Z axis (5 files)"),
    ("DEBUG_VIEW_VERTEXCOLORS", "DEBUG_VIEW_VERTEXCOLORS", "Debug: view vertex colors (2 files)"),
    ("DEBUG_VIEW_WS_SIN", "DEBUG_VIEW_WS_SIN", "Debug: view world-space sinusoidal (16 files)"),
    ("DEBUG_VIEW_X_OFFSET", "DEBUG_VIEW_X_OFFSET", "Debug: view X offset (18 files)"),
    ("DEBUG_VIEW_Y_OFFSET", "DEBUG_VIEW_Y_OFFSET", "Debug: view Y offset (18 files)"),
    ("DEBUG_VIEW_Z_OFFSET", "DEBUG_VIEW_Z_OFFSET", "Debug: view Z offset (18 files)"),
    ("DEBUG_VISUALIZE_ANIM_GRADIENT", "DEBUG_VISUALIZE_ANIM_GRADIENT", "Debug: visualize animation gradient (1 file)"),
    ("SHINEDEBUG", "SHINEDEBUG", "Debug: shine effect (1 file)"),

    # --- Disable Features (10) ---
    ("DISABLE_CLOUD_FX", "DISABLE_CLOUD_FX", "Disable cloud effects (1 file)"),
    ("DISABLE_DIFFUSE_BLEND", "DISABLE_DIFFUSE_BLEND", "Disable diffuse blend (3 files)"),
    ("DISABLE_FIRE_FX", "DISABLE_FIRE_FX", "Disable fire effects (23 files)"),
    ("DISABLE_GLITCH", "DISABLE_GLITCH", "Disable glitch effect (3 files)"),
    ("DISABLE_GROUND_TINT", "DISABLE_GROUND_TINT", "Disable ground tinting (5 files)"),
    ("DISABLE_PIXELATE", "DISABLE_PIXELATE", "Disable pixelation effect (3 files)"),
    ("DISABLE_SHADOWS", "DISABLE_SHADOWS", "Disable shadow rendering (listed in guide)"),
    ("DISABLE_UV_DISTORTION", "DISABLE_UV_DISTORTION", "Disable UV distortion (3 files)"),
    ("DISABLE_UV_DISTORTION_ALPHA", "DISABLE_UV_DISTORTION_ALPHA", "Disable UV distortion alpha (3 files)"),
    ("DISTORT_BASE_ONLY", "DISTORT_BASE_ONLY", "Distort base texture only (3 files)"),

    # --- Enable Features (18) ---
    ("ENABLE_BILLBOARD", "ENABLE_BILLBOARD", "Enable billboard rendering (31 files)"),
    ("ENABLE_BPMCONTROL", "ENABLE_BPMCONTROL", "Enable BPM-based animation control (3 files)"),
    ("ENABLE_DEPTHFOG", "ENABLE_DEPTHFOG", "Enable depth fog (6 files)"),
    ("ENABLE_DISSOLVE", "ENABLE_DISSOLVE", "Enable dissolve effect (3 files)"),
    ("ENABLE_FLIPBOOK", "ENABLE_FLIPBOOK", "Enable flipbook animation (3 files)"),
    ("ENABLE_GLITCH", "ENABLE_GLITCH", "Enable glitch effect (3 files)"),
    ("ENABLE_GROUND_DECAL", "ENABLE_GROUND_DECAL", "Enable ground decal mode (5 files)"),
    ("ENABLE_LOW_QUALITY_ALPHA", "ENABLE_LOW_QUALITY_ALPHA", "Enable low quality alpha (10 files)"),
    ("ENABLE_MESH_PIVOT", "ENABLE_MESH_PIVOT", "Enable mesh pivot point (31 files)"),
    ("ENABLE_PIXELATE", "ENABLE_PIXELATE", "Enable pixelation effect (3 files)"),
    ("ENABLE_SCANLINES", "ENABLE_SCANLINES", "Enable scanline effect (3 files)"),
    ("ENABLE_SHINE", "ENABLE_SHINE", "Enable shine effect (1 file)"),
    ("ENABLE_TEXTURE", "ENABLE_TEXTURE", "Enable texture sampling (2 files)"),
    ("ENABLE_TRANSITION", "ENABLE_TRANSITION", "Enable transition effect (2 files)"),
    ("ENABLE_TRANSITION_FADE", "ENABLE_TRANSITION_FADE", "Enable transition fade (20 files)"),
    ("ENABLE_VERTEX_DEFORM", "ENABLE_VERTEX_DEFORM", "Enable vertex deformation (3 files)"),
    ("ENABLE_WS_ALPHACLIP", "ENABLE_WS_ALPHACLIP", "Enable world-space alpha clip (2 files)"),

    # --- Environment & Transition (6) ---
    ("ENV_TRANSITION", "ENV_TRANSITION", "Environment transition effect (40 files)"),
    ("USE_ENV_TRANSITION", "USE_ENV_TRANSITION", "Use environment transition (9 files)"),
    ("TRANSITION_END", "TRANSITION_END", "Transition end state (5 files)"),
    ("TRANSITION_OUT", "TRANSITION_OUT", "Transition out state (19 files)"),
    ("MASK_FX_IN_MAP_CENTER", "MASK_FX_IN_MAP_CENTER", "Mask FX at map center (24 files)"),
    ("BASE_ON_MAP", "BASE_ON_MAP", "Base positioned on map (19 files)"),

    # --- Emission & Glow (7) ---
    ("EMISSION_ROTATE_ON", "EMISSION_ROTATE_ON", "Enable emission rotation (18 files)"),
    ("EMISSION_SINGLE_DIRECTION_ON", "EMISSION_SINGLE_DIRECTION_ON", "Emission single direction (18 files)"),
    ("EMISSIVE_GRADIENT_MASK", "EMISSIVE_GRADIENT_MASK", "Emissive gradient mask (2 files)"),
    ("EMISSIVE_IS_TEXTURE", "EMISSIVE_IS_TEXTURE", "Emissive from texture (2 files)"),
    ("TOGGLE_EMISSION_TEXTURE_MASK", "TOGGLE_EMISSION_TEXTURE_MASK", "Toggle emission texture mask (2 files)"),
    ("TOGGLE_EMMISSIVE_MASTER", "TOGGLE_EMMISSIVE_MASTER", "Toggle emissive master switch (2 files)"),
    ("USE_ANIMATED_EMISSION", "USE_ANIMATED_EMISSION", "Use animated emission (2 files)"),

    # --- Animation & Deformation (15) ---
    ("CHECK_NOMASK_ON", "CHECK_NOMASK_ON", "Check no-mask on (18 files)"),
    ("DEFORM_ON", "DEFORM_ON", "Enable deformation (11 files)"),
    ("FLAG_ANIMATION_ON", "FLAG_ANIMATION_ON", "Enable flag wave animation (18 files)"),
    ("FLOW_FAN_ON", "FLOW_FAN_ON", "Enable flow fan effect (18 files)"),
    ("FLOW_RIPPLE_ON", "FLOW_RIPPLE_ON", "Enable flow ripple effect (18 files)"),
    ("FOLIAGEWIND_ANIMATION_CLIP_ON", "FOLIAGEWIND_ANIMATION_CLIP_ON", "Foliage wind animation with clip (18 files)"),
    ("FOLIAGEWIND_ANIMATION_ON", "FOLIAGEWIND_ANIMATION_ON", "Enable foliage wind animation (18 files)"),
    ("TRANSPARENT_ANIMATION_ON", "TRANSPARENT_ANIMATION_ON", "Enable transparent animation (18 files)"),
    ("TWO_D_DEFORM_ON", "TWO_D_DEFORM_ON", "Enable 2D deformation (25 files)"),
    ("VERTEX_ANIMATION_ON", "VERTEX_ANIMATION_ON", "Enable vertex animation (18 files)"),
    ("USE_SINUSOIDAL_MOVEMENT", "USE_SINUSOIDAL_MOVEMENT", "Use sinusoidal movement (18 files)"),
    ("USE_VERTEX_ANIMATION", "USE_VERTEX_ANIMATION", "Use vertex animation (5 files)"),
    ("USE_VERTEX_OFFSET", "USE_VERTEX_OFFSET", "Use vertex offset (1 file)"),
    ("USE_ROTATION", "USE_ROTATION", "Use rotation (18 files)"),
    ("USE_TRANSLATION", "USE_TRANSLATION", "Use translation (18 files)"),

    # --- Mask & Channel (16) ---
    ("INVERSE", "INVERSE", "Invert mask/effect (19 files)"),
    ("MASK_USING_LAYER_ONE_UV", "MASK_USING_LAYER_ONE_UV", "Use layer one UVs for mask (3 files)"),
    ("ROTATE_MASK_CHANNEL_B", "ROTATE_MASK_CHANNEL_B", "Rotate mask blue channel (1 file)"),
    ("ROTATE_MASK_CHANNEL_G", "ROTATE_MASK_CHANNEL_G", "Rotate mask green channel (1 file)"),
    ("ROTATE_MASK_CHANNEL_R", "ROTATE_MASK_CHANNEL_R", "Rotate mask red channel (1 file)"),
    ("SHOW_BLUE_MASK", "SHOW_BLUE_MASK", "Show blue mask channel (1 file)"),
    ("SHOW_GREEN_MASK", "SHOW_GREEN_MASK", "Show green mask channel (1 file)"),
    ("SHOW_PAINTED_A", "SHOW_PAINTED_A", "Show painted alpha (1 file)"),
    ("SHOW_RED_MASK", "SHOW_RED_MASK", "Show red mask channel (1 file)"),
    ("SS_MASK", "SS_MASK", "Screen-space mask (11 files)"),
    ("TOGGLE_MASK", "TOGGLE_MASK", "Toggle mask (56 files)"),
    ("USE_BLUE_CHANNEL_MASK", "USE_BLUE_CHANNEL_MASK", "Use blue channel as mask (8 files)"),
    ("USE_GREEN_CHANNEL_MASK", "USE_GREEN_CHANNEL_MASK", "Use green channel as mask (8 files)"),
    ("USE_RED_CHANNEL_MASK", "USE_RED_CHANNEL_MASK", "Use red channel as mask (8 files)"),
    ("USE_ANIMATEDMASK", "USE_ANIMATEDMASK", "Use animated mask (1 file)"),

    # --- UV & Scroll (16) ---
    ("TOGGLE_UV_DIRECTION", "TOGGLE_UV_DIRECTION", "Toggle UV scroll direction (10 files)"),
    ("TOGGLE_UV_ROTATE_SCROLL", "TOGGLE_UV_ROTATE_SCROLL", "Toggle UV rotate/scroll mode (56 files)"),
    ("RADIAL_UV_LOCALSPACE_TOGGLE", "RADIAL_UV_LOCALSPACE_TOGGLE", "Toggle radial UV local space (10 files)"),
    ("USE_EMISSIVE_SCROLL", "USE_EMISSIVE_SCROLL", "Use emissive scrolling (2 files)"),
    ("USE_FLOW", "USE_FLOW", "Use flow effect (2 files)"),
    ("USE_FLOW_ALPHA_SCROLL", "USE_FLOW_ALPHA_SCROLL", "Use flow alpha scrolling (2 files)"),
    ("USE_FLOW_MAP", "USE_FLOW_MAP", "Use flow map (11 files)"),
    ("USE_UV_ALPHA_SCROLL", "USE_UV_ALPHA_SCROLL", "Use UV alpha scrolling (2 files)"),
    ("USE_UV_SCROLL", "USE_UV_SCROLL", "Use UV scrolling (2 files)"),
    ("USE_UV_SCROLL_GLOW", "USE_UV_SCROLL_GLOW", "Use UV scroll glow (10 files)"),
    ("USE_WORLDSCROLLING_FORDODGEMASK", "USE_WORLDSCROLLING_FORDODGEMASK", "World scrolling for dodge mask (4 files)"),
    ("USE_SS_UVS", "USE_SS_UVS", "Use screen-space UVs (3 files)"),
    ("USE_SS_UVS_FX", "USE_SS_UVS_FX", "Use screen-space UVs for FX (3 files)"),
    ("USE_SS_UVS_GLITCH", "USE_SS_UVS_GLITCH", "Use screen-space UVs for glitch (3 files)"),
    ("USE_SS_UVS_PIXELATE", "USE_SS_UVS_PIXELATE", "Use screen-space UVs for pixelation (3 files)"),

    # --- Color & Lighting (13) ---
    ("ADD_OR_MULTIPLY_COLORS", "ADD_OR_MULTIPLY_COLORS", "Add or multiply color blend mode (2 files)"),
    ("IS_ADDITIVE_MTL", "IS_ADDITIVE_MTL", "Additive material blending (1 file)"),
    ("MULT_REFLECTION_OPACITY", "MULT_REFLECTION_OPACITY", "Multiply reflection opacity (3 files)"),
    ("UNLIT_MODE", "UNLIT_MODE", "Unlit rendering mode (3 files)"),
    ("USE_COLOR", "USE_COLOR", "Use color parameter (7 files)"),
    ("USE_COLOR_BLEND", "USE_COLOR_BLEND", "Use color blending (56 files)"),
    ("USE_COLOR_SWITCH", "USE_COLOR_SWITCH", "Use color switching (5 files)"),
    ("USE_COLOROVERLAY", "USE_COLOROVERLAY", "Use color overlay (1 file)"),
    ("USE_DIFFUSE_COLOR", "USE_DIFFUSE_COLOR", "Use diffuse color (10 files)"),
    ("USE_DIFFUSE_TEXTURE", "USE_DIFFUSE_TEXTURE", "Use diffuse texture (11 files)"),
    ("USE_GLOW_AS_ALPHA", "USE_GLOW_AS_ALPHA", "Use glow as alpha channel (10 files)"),
    ("USE_GLOW_MASK", "USE_GLOW_MASK", "Use glow mask (10 files)"),
    ("USE_RADIAL_GLOW", "USE_RADIAL_GLOW", "Use radial glow (10 files)"),
    ("USING_BLOOM", "USING_BLOOM", "Using bloom effect (3 files)"),

    # --- World Position & Offset (16) ---
    ("USE_GRASS_TINT_MAP", "USE_GRASS_TINT_MAP", "Use grass tint map (33 files)"),
    ("USE_OBJECT_GRADIENT", "USE_OBJECT_GRADIENT", "Use object gradient (14 files)"),
    ("USE_WORLD_OFFSET", "USE_WORLD_OFFSET", "Use world position offset (18 files)"),
    ("USE_WS_MASK", "USE_WS_MASK", "Use world-space mask (7 files)"),
    ("USE_WS_X_OFFSET", "USE_WS_X_OFFSET", "Use world-space X offset (16 files)"),
    ("USE_X_AXIS_UV_MASK", "USE_X_AXIS_UV_MASK", "Use X axis UV mask (5 files)"),
    ("USE_X_OFFSET", "USE_X_OFFSET", "Use X offset (18 files)"),
    ("USE_Y_AXIS_UV_MASK", "USE_Y_AXIS_UV_MASK", "Use Y axis UV mask (5 files)"),
    ("USE_Y_OFFSET", "USE_Y_OFFSET", "Use Y offset (18 files)"),
    ("USE_Z_AXIS_UV_MASK", "USE_Z_AXIS_UV_MASK", "Use Z axis UV mask (5 files)"),
    ("USE_Z_OFFSET", "USE_Z_OFFSET", "Use Z offset (18 files)"),
    ("X_AXIS_UV_MASK_DIRECTION_INVERT", "X_AXIS_UV_MASK_DIRECTION_INVERT", "Invert X axis UV mask direction (5 files)"),
    ("X_AXIS_UV_MASK_DIRECTION_TOGGLE", "X_AXIS_UV_MASK_DIRECTION_TOGGLE", "Toggle X axis UV mask direction (5 files)"),
    ("Y_AXIS_UV_MASK_DIRECTION_INVERT", "Y_AXIS_UV_MASK_DIRECTION_INVERT", "Invert Y axis UV mask direction (5 files)"),
    ("Y_AXIS_UV_MASK_DIRECTION_TOGGLE", "Y_AXIS_UV_MASK_DIRECTION_TOGGLE", "Toggle Y axis UV mask direction (5 files)"),
    ("Z_AXIS_UV_MASK_DIRECTION_INVERT", "Z_AXIS_UV_MASK_DIRECTION_INVERT", "Invert Z axis UV mask direction (5 files)"),
    ("Z_AXIS_UV_MASK_DIRECTION_TOGGLE", "Z_AXIS_UV_MASK_DIRECTION_TOGGLE", "Toggle Z axis UV mask direction (5 files)"),

    # --- Miscellaneous (19) ---
    ("ON_BILLBOARD", "ON_BILLBOARD", "Billboard rendering (1 file)"),
    ("ON_CRYSTAL_GLITTER", "ON_CRYSTAL_GLITTER", "Crystal glitter effect (1 file)"),
    ("ON_DEFUSE", "ON_DEFUSE", "Diffuse enable (1 file)"),
    ("ON_GLITTER_GLASS_ROTATE", "ON_GLITTER_GLASS_ROTATE", "Glitter glass rotation (1 file)"),
    ("ON_PARALLAX", "ON_PARALLAX", "Parallax mapping (1 file)"),
    ("ON_PARALLAX_ROTATE", "ON_PARALLAX_ROTATE", "Parallax rotation (1 file)"),
    ("THIRD_GLITTER_LAYER_C", "THIRD_GLITTER_LAYER_C", "Third glitter layer C (1 file)"),
    ("USE_A_AS_OVERLAY", "USE_A_AS_OVERLAY", "Use alpha as overlay (1 file)"),
    ("USE_BACKGROUND_TEX", "USE_BACKGROUND_TEX", "Use background texture (1 file)"),
    ("USE_BLINK", "USE_BLINK", "Use blink effect (1 file)"),
    ("USE_CUSTOM_OBJECT_NORMAL", "USE_CUSTOM_OBJECT_NORMAL", "Use custom object normals (3 files)"),
    ("USE_EXTRAS", "USE_EXTRAS", "Use extras (1 file)"),
    ("USE_FADE_OUT", "USE_FADE_OUT", "Use fade out effect (1 file)"),
    ("USE_FLAT_PARALLAX", "USE_FLAT_PARALLAX", "Use flat parallax (1 file)"),
    ("USE_FLICKER", "USE_FLICKER", "Use flicker effect (8 files)"),
    ("USE_FLIPBOOK_OFFSET", "USE_FLIPBOOK_OFFSET", "Use flipbook offset (1 file)"),
    ("USE_FLIPBOOK_ROTATION", "USE_FLIPBOOK_ROTATION", "Use flipbook rotation (1 file)"),
    ("USE_GAMEPLAY_CONSTANTS", "USE_GAMEPLAY_CONSTANTS", "Use gameplay constants (1 file)"),
    ("USE_HORIZONTAL_GRADIENT", "USE_HORIZONTAL_GRADIENT", "Use horizontal gradient (1 file)"),
    ("USE_OVERLAY", "USE_OVERLAY", "Use overlay blend (1 file)"),
    ("USE_RADIAL_BLUR", "USE_RADIAL_BLUR", "Use radial blur (1 file)"),
    ("USE_RANDOM_SECONDARY_MOTION", "USE_RANDOM_SECONDARY_MOTION", "Use random secondary motion (13 files)"),
    ("USE_RIM_LIGHT", "USE_RIM_LIGHT", "Use rim lighting (2 files)"),
    ("USE_SCANLINES", "USE_SCANLINES", "Use scanline effect (1 file)"),
    ("USE_SPEC", "USE_SPEC", "Use specular highlight (1 file)"),
    ("USE_TOP", "USE_TOP", "Use top texture (1 file)"),
    ("USE_VERTEX_COLORS", "USE_VERTEX_COLORS", "Use vertex colors (2 files)"),
    ("USING_CUSTOM_MOVEMENT_DIRECTION", "USING_CUSTOM_MOVEMENT_DIRECTION", "Using custom movement direction (3 files)"),
    ("USING_LAYER_THREE", "USING_LAYER_THREE", "Using layer three (3 files)"),
    ("USING_LAYER_TWO", "USING_LAYER_TWO", "Using layer two (3 files)"),
    ("USING_NOISE_ONE", "USING_NOISE_ONE", "Using noise layer one (3 files)"),
    ("USING_NOISE_THREE", "USING_NOISE_THREE", "Using noise layer three (3 files)"),
    ("USING_NOISE_TWO", "USING_NOISE_TWO", "Using noise layer two (3 files)"),
    ("USING_VERTEX_COLOR", "USING_VERTEX_COLOR", "Using vertex color (3 files)"),
]


# =============================================================================
# SHADER MACROS (14 unique)
# Compile-time shader constants (shaderMacros map[string,string])
# =============================================================================

SHADER_MACROS = [
    ("BLEND", "BLEND", "Blend mode enable (value: '1')"),
    ("BLOOM", "BLOOM", "Bloom post-process effect (value: '0')"),
    ("DEATH_EFFECT", "DEATH_EFFECT", "Death/destruction effect (value: '1')"),
    ("DEBUG_FULLBRIGHT", "DEBUG_FULLBRIGHT", "Debug fullbright mode (value: '1')"),
    ("DISABLE_DEPTH_FOG", "DISABLE_DEPTH_FOG", "Disable depth-based fog (values: '0', '1')"),
    ("DISABLE_FOW", "DISABLE_FOW", "Disable fog of war (value: '1')"),
    ("DISABLE_SHADOWS", "DISABLE_SHADOWS", "Disable shadow rendering (value: '1')"),
    ("ENV_TRANSITION", "ENV_TRANSITION", "Environment transition enable (value: '1')"),
    ("FEATURE_MASKED", "FEATURE_MASKED", "Feature masking enable (value: '1')"),
    ("NO_BAKED_LIGHTING", "NO_BAKED_LIGHTING", "Disable baked lighting - most common macro (value: '1')"),
    ("NUM_BLEND_WEIGHTS", "NUM_BLEND_WEIGHTS", "Number of blend weights (value: '4')"),
    ("PREMULTIPLIED_ALPHA", "PREMULTIPLIED_ALPHA", "Premultiplied alpha blending (value: '1')"),
    ("TRANSITION", "TRANSITION", "Transition mode enable (value: '1')"),
    ("VFX02_LNY", "VFX02_LNY", "VFX path reference for Lunar New Year (value: path string)"),
]

# Shader macro known values for validation/dropdowns
SHADER_MACRO_VALUES = {
    "BLEND": ["1"],
    "BLOOM": ["0"],
    "DEATH_EFFECT": ["1"],
    "DEBUG_FULLBRIGHT": ["1"],
    "DISABLE_DEPTH_FOG": ["0", "1"],
    "DISABLE_FOW": ["1"],
    "DISABLE_SHADOWS": ["1"],
    "ENV_TRANSITION": ["1"],
    "FEATURE_MASKED": ["1"],
    "NO_BAKED_LIGHTING": ["1"],
    "NUM_BLEND_WEIGHTS": ["4"],
    "PREMULTIPLIED_ALPHA": ["1"],
    "TRANSITION": ["1"],
    "VFX02_LNY": [],  # Path string, varies
}


# =============================================================================
# TECHNIQUES (from 26 .materials.py files, 5688 technique instances)
# =============================================================================

TECHNIQUE_NAMES = [
    ("normal", "normal", "Standard rendering technique (5688 instances across all materials)"),
]

CHILD_TECHNIQUE_NAMES = [
    ("env_transition", "env_transition", "Environment transition child technique, parent='normal' (1340 instances)"),
]

# Combined for a single dropdown
TECHNIQUE_ALL = [
    ("normal", "normal", "Standard rendering technique (parent)"),
    ("env_transition", "env_transition", "Environment transition (child of 'normal')"),
]


# =============================================================================
# SAMPLER TEXTURE NAMES (71 unique)
# Texture slot identifiers used in StaticMaterialShaderSamplerDef
# =============================================================================

SAMPLER_TEXTURE_NAMES = [
    # --- Primary Diffuse ---
    ("DiffuseTexture", "DiffuseTexture", "Main diffuse/color texture (186 files)"),
    ("Diffuse_Texture", "Diffuse_Texture", "Alt diffuse texture naming (147 files)"),
    ("ColorTexture", "ColorTexture", "Color-based diffuse texture (21 files)"),
    ("BAKED_DIFFUSE_TEXTURE", "BAKED_DIFFUSE_TEXTURE", "Baked diffuse texture (2 files)"),
    ("Glass_Diffuse_Texture", "Glass_Diffuse_Texture", "Glass diffuse texture (1 file)"),

    # --- Masks ---
    ("Mask_Texture", "Mask_Texture", "Primary mask texture (97 files)"),
    ("MaskTexture", "MaskTexture", "Alt mask texture (6 files)"),
    ("Mask_Tex", "Mask_Tex", "Mask texture short name (18 files)"),
    ("Mask", "Mask", "Generic mask (1 file)"),
    ("_Mask", "_Mask", "Underscore-prefixed mask (1 file)"),
    ("_MaskTex", "_MaskTex", "Underscore-prefixed mask tex (3 files)"),
    ("FlagMask_Texture", "FlagMask_Texture", "Flag mask texture (18 files)"),
    ("ShineMask_Texture", "ShineMask_Texture", "Shine mask texture (1 file)"),
    ("Effects_Mask", "Effects_Mask", "Effects mask texture (3 files)"),
    ("RGB_Mask_Main", "RGB_Mask_Main", "RGB mask main (1 file)"),
    ("Blink_Mask", "Blink_Mask", "Blink mask (1 file)"),

    # --- Noise ---
    ("Noise_Texture", "Noise_Texture", "Noise texture (42 files)"),
    ("NoiseTexture", "NoiseTexture", "Alt noise texture (20 files)"),
    ("Noise", "Noise", "Generic noise (4 files)"),
    ("Noise_Gradient_Texture", "Noise_Gradient_Texture", "Noise gradient texture (3 files)"),
    ("Noise_Mask_Texture", "Noise_Mask_Texture", "Noise mask texture (3 files)"),
    ("NoiseGlitter", "NoiseGlitter", "Noise for glitter effect (1 file)"),
    ("_NoiseTex01", "_NoiseTex01", "Noise texture layer 01 (3 files)"),
    ("_NoiseTex02", "_NoiseTex02", "Noise texture layer 02 (3 files)"),
    ("_NoiseTex03", "_NoiseTex03", "Noise texture layer 03 (3 files)"),

    # --- Emission ---
    ("EmissionMaskTex", "EmissionMaskTex", "Emission mask texture (16 files)"),
    ("EmissionTex", "EmissionTex", "Emission texture (16 files)"),
    ("Emission_Tex", "Emission_Tex", "Alt emission texture (18 files)"),
    ("Emission_X_Noise_Mask", "Emission_X_Noise_Mask", "Emission noise mask (2 files)"),
    ("Emissive_Texture", "Emissive_Texture", "Emissive texture (8 files)"),

    # --- Distortion ---
    ("Distortion_Texture", "Distortion_Texture", "UV distortion texture (12 files)"),
    ("DistortionA_Texture", "DistortionA_Texture", "Distortion A texture (3 files)"),
    ("DistortionB_Texture", "DistortionB_Texture", "Distortion B texture (3 files)"),

    # --- Scrolling ---
    ("Scrolling_Texture", "Scrolling_Texture", "Scrolling texture (4 files)"),
    ("Scrolling_Texture2", "Scrolling_Texture2", "Scrolling texture 2 (4 files)"),
    ("ScrollingA_Texture", "ScrollingA_Texture", "Scrolling A texture (3 files)"),
    ("ScrollingB_Texture", "ScrollingB_Texture", "Scrolling B texture (1 file)"),
    ("Alpha_Scroll_Texture", "Alpha_Scroll_Texture", "Alpha scrolling texture (3 files)"),

    # --- Flow ---
    ("FlowMap", "FlowMap", "Flow/water direction map (2 files)"),
    ("Flow_Map", "Flow_Map", "Alt flow map (11 files)"),
    ("Flowing_Normal_Map", "Flowing_Normal_Map", "Flowing normal map (11 files)"),

    # --- Deformation ---
    ("VertexDeformationMask", "VertexDeformationMask", "Vertex deformation/WPO mask (11 files)"),
    ("_DeformTex", "_DeformTex", "Deform texture (3 files)"),
    ("WPO_Texture", "WPO_Texture", "World position offset texture (1 file)"),

    # --- Decal & Strength ---
    ("Decal_Texture", "Decal_Texture", "Decal overlay texture (5 files)"),
    ("Strength_Texture", "Strength_Texture", "Strength/intensity texture (9 files)"),

    # --- Reflection ---
    ("Reflection_Texture", "Reflection_Texture", "Reflection/cubemap texture (5 files)"),

    # --- Layer System ---
    ("_LayerTex01", "_LayerTex01", "Layer texture 01 (3 files)"),
    ("_LayerTex02", "_LayerTex02", "Layer texture 02 (3 files)"),
    ("_LayerTex03", "_LayerTex03", "Layer texture 03 (3 files)"),

    # --- Special / Misc ---
    ("Background_Texture", "Background_Texture", "Background texture (1 file)"),
    ("Blink_Texture", "Blink_Texture", "Blink/pulse effect texture (1 file)"),
    ("Bottom_Texture", "Bottom_Texture", "Bottom layer texture (2 files)"),
    ("Top_Texture", "Top_Texture", "Top layer texture (2 files)"),
    ("Middle_Texture", "Middle_Texture", "Middle layer texture (1 file)"),
    ("ColorGradingTexture", "ColorGradingTexture", "LUT/color grading texture (1 file)"),
    ("Crystal_Texture", "Crystal_Texture", "Crystal effect texture (1 file)"),
    ("Extras_Texture", "Extras_Texture", "Extras/overlay texture (1 file)"),
    ("FlipBook_Texture", "FlipBook_Texture", "Flipbook animation texture (1 file)"),
    ("GlitterBlendingTexture", "GlitterBlendingTexture", "Glitter blending texture (1 file)"),
    ("Gradient_Texture", "Gradient_Texture", "Gradient lookup texture (2 files)"),
    ("MatCap_Tex", "MatCap_Tex", "MatCap texture (1 file)"),
    ("Mod_Texture", "Mod_Texture", "Modifier texture (2 files)"),
    ("Normal_Rain_Texture", "Normal_Rain_Texture", "Rain normal map (2 files)"),
    ("Sigil_Texture", "Sigil_Texture", "Sigil decoration texture (1 file)"),
    ("Sparkle_Texture", "Sparkle_Texture", "Sparkle effect texture (2 files)"),
    ("Thickness_Texture", "Thickness_Texture", "Thickness/subsurface texture (2 files)"),
    ("TintTexture", "TintTexture", "Tint color texture (1 file)"),
    ("_MainTex", "_MainTex", "Main texture (Unity-style naming) (1 file)"),
    ("_Specular", "_Specular", "Specular texture (1 file)"),
    ("iridescentTex", "iridescentTex", "Iridescent effect texture (1 file)"),
]


# =============================================================================
# SHADER LINKS (91 unique)
# Shader program references
# =============================================================================

SHADER_LINKS = [
    ("Shaders/PostProcess/TFT_RadialBlur", "TFT_RadialBlur", "Post-process radial blur"),
    ("Shaders/SkinnedMesh/HKG_MatCap_Only", "HKG_MatCap_Only", "MatCap-only skinned mesh"),
    ("Shaders/SkinnedMesh/TFT_FixedUVSpace_Bloom", "TFT_FixedUVSpace_Bloom", "Fixed UV bloom skinned mesh"),
    ("Shaders/SkinnedMesh/TFT_Flag_Wave", "TFT_Flag_Wave", "Flag wave animation skinned"),
    ("Shaders/SkinnedMesh/TFT_TwistByNoise", "TFT_TwistByNoise", "Noise-based twist skinned"),
    ("Shaders/SkinnedMesh/TFT_Water", "TFT_Water", "Water shader skinned mesh"),
    ("Shaders/StaticMesh/4TextureBlend_WorldProjected", "4TextureBlend_WorldProjected", "4-texture world projection blend"),
    ("Shaders/StaticMesh/Cloth_Base_StaticMesh", "Cloth_Base_StaticMesh", "Cloth base material"),
    ("Shaders/StaticMesh/DefaultEnv_Colorblend", "DefaultEnv_Colorblend", "Default env color blend"),
    ("Shaders/StaticMesh/DefaultEnv_Colorgrading", "DefaultEnv_Colorgrading", "Default env color grading"),
    ("Shaders/StaticMesh/DefaultEnv_Flag_Wave", "DefaultEnv_Flag_Wave", "Default env flag wave"),
    ("Shaders/StaticMesh/DefaultEnv_Flat", "DefaultEnv_Flat", "Default env flat (most basic)"),
    ("Shaders/StaticMesh/DefaultEnv_Flat_AlphaTest", "DefaultEnv_Flat_AlphaTest", "Flat with alpha testing"),
    ("Shaders/StaticMesh/DefaultEnv_Flat_AlphaTest_DoubleSided", "DefaultEnv_Flat_AlphaTest_DoubleSided", "Flat alpha-test double-sided"),
    ("Shaders/StaticMesh/DefaultEnv_Flat_BakedTerrain", "DefaultEnv_Flat_BakedTerrain", "Flat baked terrain"),
    ("Shaders/StaticMesh/DefaultEnv_Flat_ColorMult_Overlay", "DefaultEnv_Flat_ColorMult_Overlay", "Flat color multiply overlay"),
    ("Shaders/StaticMesh/DefaultEnv_Flat_PlanarReflection", "DefaultEnv_Flat_PlanarReflection", "Flat with planar reflection"),
    ("Shaders/StaticMesh/DefaultEnv_Glass_BlendAndReflection", "DefaultEnv_Glass_BlendAndReflection", "Glass blend and reflection"),
    ("Shaders/StaticMesh/DefaultEnv_Glow", "DefaultEnv_Glow", "Default env glow effect"),
    ("Shaders/StaticMesh/DefaultEnv_Rotate", "DefaultEnv_Rotate", "Default env rotation"),
    ("Shaders/StaticMesh/DefaultEnv_Transition", "DefaultEnv_Transition", "Default env transition"),
    ("Shaders/StaticMesh/ENV_ColorShift_Overlay", "ENV_ColorShift_Overlay", "Color shift overlay"),
    ("Shaders/StaticMesh/ENV_DIffuse_Pulse", "ENV_DIffuse_Pulse", "Diffuse pulse effect"),
    ("Shaders/StaticMesh/ENV_DarkstarBase", "ENV_DarkstarBase", "Darkstar base material"),
    ("Shaders/StaticMesh/ENV_Diffuse_Vertex_Expand", "ENV_Diffuse_Vertex_Expand", "Diffuse with vertex expansion"),
    ("Shaders/StaticMesh/ENV_FloatingObjects", "ENV_FloatingObjects", "Floating objects animation"),
    ("Shaders/StaticMesh/ENV_FloatingObjects_VertexColors", "ENV_FloatingObjects_VertexColors", "Floating objects with vertex colors"),
    ("Shaders/StaticMesh/ENV_Glass", "ENV_Glass", "Glass material"),
    ("Shaders/StaticMesh/ENV_Glass_Diffuse", "ENV_Glass_Diffuse", "Glass with diffuse texture"),
    ("Shaders/StaticMesh/ENV_Glass_Vertex_Offset", "ENV_Glass_Vertex_Offset", "Glass with vertex offset"),
    ("Shaders/StaticMesh/ENV_GlowSign", "ENV_GlowSign", "Glowing sign effect"),
    ("Shaders/StaticMesh/ENV_GlowSign_Atlas", "ENV_GlowSign_Atlas", "Glowing sign with atlas"),
    ("Shaders/StaticMesh/ENV_Lantern", "ENV_Lantern", "Lantern light effect"),
    ("Shaders/StaticMesh/ENV_Light_Sequence", "ENV_Light_Sequence", "Light sequence animation"),
    ("Shaders/StaticMesh/ENV_ScrollingColor", "ENV_ScrollingColor", "Scrolling color effect"),
    ("Shaders/StaticMesh/ENV_ScrollingDiffuse", "ENV_ScrollingDiffuse", "Scrolling diffuse texture"),
    ("Shaders/StaticMesh/ENV_SimpleFoliage", "ENV_SimpleFoliage", "Simple foliage/vegetation"),
    ("Shaders/StaticMesh/ENV_SimpleRotate", "ENV_SimpleRotate", "Simple rotation animation"),
    ("Shaders/StaticMesh/ENV_TileableDiffuse", "ENV_TileableDiffuse", "Tileable diffuse"),
    ("Shaders/StaticMesh/ENV_TreeCanopy", "ENV_TreeCanopy", "Tree canopy shader"),
    ("Shaders/StaticMesh/ENV_TreeCanopy_VertexColors", "ENV_TreeCanopy_VertexColors", "Tree canopy with vertex colors"),
    ("Shaders/StaticMesh/ENV_UVGradientColorMapping", "ENV_UVGradientColorMapping", "UV gradient color mapping"),
    ("Shaders/StaticMesh/ENV_Vertex_TranslateAndRotate", "ENV_Vertex_TranslateAndRotate", "Vertex translate and rotate"),
    ("Shaders/StaticMesh/Emissive_Basic", "Emissive_Basic", "Basic emissive shader"),
    ("Shaders/StaticMesh/Env_Diffuse_VertexColor_Multiply", "Env_Diffuse_VertexColor_Multiply", "Diffuse vertex color multiply"),
    ("Shaders/StaticMesh/Env_TwistByNoise", "Env_TwistByNoise", "Noise-based twist"),
    ("Shaders/StaticMesh/FlickerAlpha_FlipBook", "FlickerAlpha_FlipBook", "Flickering alpha flipbook"),
    ("Shaders/StaticMesh/FlowMap_Radial", "FlowMap_Radial", "Radial flow map"),
    ("Shaders/StaticMesh/Flowmap_River", "Flowmap_River", "River flow map"),
    ("Shaders/StaticMesh/Hologram", "Hologram", "Hologram effect"),
    ("Shaders/StaticMesh/Hologram_Rotate", "Hologram_Rotate", "Rotating hologram"),
    ("Shaders/StaticMesh/Indicator_Faelights", "Indicator_Faelights", "Faelight indicator"),
    ("Shaders/StaticMesh/OD_FlowMap", "OD_FlowMap", "OD flow map shader"),
    ("Shaders/StaticMesh/SRX_Blend_Chemtech_Decal", "SRX_Blend_Chemtech_Decal", "SRX chemtech decal blend"),
    ("Shaders/StaticMesh/SRX_Blend_Chemtech_Ground", "SRX_Blend_Chemtech_Ground", "SRX chemtech ground blend"),
    ("Shaders/StaticMesh/SRX_Blend_Cloud_Ground", "SRX_Blend_Cloud_Ground", "SRX cloud ground blend"),
    ("Shaders/StaticMesh/SRX_Blend_Cloud_WindZone", "SRX_Blend_Cloud_WindZone", "SRX cloud wind zone blend"),
    ("Shaders/StaticMesh/SRX_Blend_Decal_Cloud", "SRX_Blend_Decal_Cloud", "SRX decal cloud blend"),
    ("Shaders/StaticMesh/SRX_Blend_Earth_Ground", "SRX_Blend_Earth_Ground", "SRX earth ground blend"),
    ("Shaders/StaticMesh/SRX_Blend_Earth_Island", "SRX_Blend_Earth_Island", "SRX earth island blend"),
    ("Shaders/StaticMesh/SRX_Blend_Earth_Rocks", "SRX_Blend_Earth_Rocks", "SRX earth rocks blend"),
    ("Shaders/StaticMesh/SRX_Blend_Generic_Island", "SRX_Blend_Generic_Island", "SRX generic island blend"),
    ("Shaders/StaticMesh/SRX_Blend_Hextech_Dragon", "SRX_Blend_Hextech_Dragon", "SRX hextech dragon blend"),
    ("Shaders/StaticMesh/SRX_Blend_Hextech_Ground", "SRX_Blend_Hextech_Ground", "SRX hextech ground blend"),
    ("Shaders/StaticMesh/SRX_Blend_Infernal_Dragon", "SRX_Blend_Infernal_Dragon", "SRX infernal dragon blend"),
    ("Shaders/StaticMesh/SRX_Blend_Infernal_Ground", "SRX_Blend_Infernal_Ground", "SRX infernal ground blend"),
    ("Shaders/StaticMesh/SRX_Blend_Infernal_Island", "SRX_Blend_Infernal_Island", "SRX infernal island blend"),
    ("Shaders/StaticMesh/SRX_Blend_Master", "SRX_Blend_Master", "SRX master blend shader"),
    ("Shaders/StaticMesh/SRX_Blend_Ocean", "SRX_Blend_Ocean", "SRX ocean blend shader"),
    ("Shaders/StaticMesh/SRX_DynamicEffect", "SRX_DynamicEffect", "SRX dynamic effect"),
    ("Shaders/StaticMesh/TFT_Blink", "TFT_Blink", "TFT blink effect"),
    ("Shaders/StaticMesh/TFT_Env_Flat_Billboard", "TFT_Env_Flat_Billboard", "TFT flat billboard"),
    ("Shaders/StaticMesh/TFT_Env_Parallax", "TFT_Env_Parallax", "TFT parallax environment"),
    ("Shaders/StaticMesh/TFT_Env_Rain", "TFT_Env_Rain", "TFT rain effect"),
    ("Shaders/StaticMesh/TFT_Env_Shine_Billboard", "TFT_Env_Shine_Billboard", "TFT shiny billboard"),
    ("Shaders/StaticMesh/TFT_Gradient_Lookup", "TFT_Gradient_Lookup", "TFT gradient lookup"),
    ("Shaders/StaticMesh/TFT_PlanarReflection", "TFT_PlanarReflection", "TFT planar reflection"),
    ("Shaders/StaticMesh/TFT_RotatingMask", "TFT_RotatingMask", "TFT rotating mask"),
    ("Shaders/StaticMesh/TFT_Screenspace_Glitch_Static", "TFT_Screenspace_Glitch_Static", "TFT screen-space glitch"),
    ("Shaders/StaticMesh/TFT_ScrollingDiffuse_Distortion", "TFT_ScrollingDiffuse_Distortion", "TFT scrolling diffuse distortion"),
    ("Shaders/StaticMesh/TFT_Scrolling_Delay_Static", "TFT_Scrolling_Delay_Static", "TFT scrolling delay static"),
    ("Shaders/StaticMesh/TFT_Skybox", "TFT_Skybox", "TFT skybox shader"),
    ("Shaders/StaticMesh/TFT_SparkleParallaxGlow", "TFT_SparkleParallaxGlow", "TFT sparkle parallax glow"),
    ("Shaders/StaticMesh/TFT_Transition_Ground", "TFT_Transition_Ground", "TFT transition ground"),
    ("Shaders/StaticMesh/TFT_VertexBend", "TFT_VertexBend", "TFT vertex bend"),
    ("Shaders/StaticMesh/TFT_VertexOffset", "TFT_VertexOffset", "TFT vertex offset"),
    ("Shaders/StaticMesh/TFT_VertexRipple", "TFT_VertexRipple", "TFT vertex ripple"),
    ("Shaders/StaticMesh/TFT_VertexScroll", "TFT_VertexScroll", "TFT vertex scroll"),
    ("Shaders/StaticMesh/TFT_VertexWave", "TFT_VertexWave", "TFT vertex wave"),
    ("Shaders/StaticMesh/TFT_Wind_Simple", "TFT_Wind_Simple", "TFT simple wind animation"),
    ("Shaders/StaticMesh/VertexDeform", "VertexDeform", "Vertex deformation shader"),
]


# =============================================================================
# MATERIAL PARAMETERS (627 unique, grouped by category)
# All parameters are vec4 (4 float values)
# Listed with frequency: (files_used_in)
# =============================================================================

# --- TOP 100 MOST USED PARAMETERS (by file count) ---
PARAM_TOP_USED = [
    # Color & Tint (appearing in many files)
    ("TintColor", "TintColor", "Main tint color RGBA (184 files)"),
    ("AlphaTestValue", "AlphaTestValue", "Alpha test threshold (98 files)"),
    ("Color_Blend", "Color_Blend", "Color blend factor (56 files)"),
    ("Color_Multiply", "Color_Multiply", "Color multiply factor (56 files)"),
    ("Rotation_Speed", "Rotation_Speed", "UV/object rotation speed (58 files)"),
    ("Scroll_Speed", "Scroll_Speed", "UV scroll speed (56 files)"),
    ("DistControlFactor", "DistControlFactor", "Distance control factor (33 files)"),
    ("MinDistance", "MinDistance", "Minimum distance threshold (33 files)"),
    ("PitchFactor", "PitchFactor", "Pitch factor for billboards (32 files)"),
    ("ScaleInFactor", "ScaleInFactor", "Scale-in animation factor (33 files)"),
    ("ScaleOutFactor", "ScaleOutFactor", "Scale-out animation factor (33 files)"),
    ("SeeThroughAlphaMax", "SeeThroughAlphaMax", "See-through alpha maximum (33 files)"),
    ("SeeThroughAlphaMin", "SeeThroughAlphaMin", "See-through alpha minimum (33 files)"),
    ("SeeThroughRangeScale", "SeeThroughRangeScale", "See-through range scale (33 files)"),
    ("SpreadStrength", "SpreadStrength", "Spread strength (33 files)"),
    ("VelocityStrength", "VelocityStrength", "Velocity strength (33 files)"),
    ("WaveAmplitude", "WaveAmplitude", "Wave amplitude (33 files)"),
    ("WaveFrequency", "WaveFrequency", "Wave frequency (33 files)"),
    ("WaveOffset", "WaveOffset", "Wave offset (33 files)"),
    ("UV_Rotation", "UV_Rotation", "UV rotation angle (31 files)"),
    ("DeformWaveController", "DeformWaveController", "Deform wave controller (25 files)"),
    ("DeformWaveStrength", "DeformWaveStrength", "Deform wave strength (25 files)"),
    ("DeformMaskStrength", "DeformMaskStrength", "Deform mask strength (25 files)"),
    ("Color", "Color", "Generic color RGBA (24 files)"),
    ("Tint_Color", "Tint_Color", "Alt tint color (24 files)"),
    ("Transition_Speed_Factor", "Transition_Speed_Factor", "Transition animation speed (24 files)"),
    ("AlphaClipValue", "AlphaClipValue", "Alpha clip threshold (21 files)"),
    ("ColorTexTilling", "ColorTexTilling", "Color texture tiling (21 files)"),
    ("EdgeRange", "EdgeRange", "Edge range for effects (21 files)"),
    ("EdgeRangeOuter", "EdgeRangeOuter", "Outer edge range (21 files)"),
    ("NoiseTexTilling", "NoiseTexTilling", "Noise texture tiling (21 files)"),
    ("ParamStage1", "ParamStage1", "Parameter stage 1 (21 files)"),
    ("Specular_Intensity", "Specular_Intensity", "Specular intensity (21 files)"),
    ("Starting_Color", "Starting_Color", "Starting color for transitions (21 files)"),
    ("Starting_Geo_Offset", "Starting_Geo_Offset", "Starting geometry offset (21 files)"),
    ("UV_Rotation_Center", "UV_Rotation_Center", "UV rotation center point (21 files)"),
    ("Bloom_Intensity", "Bloom_Intensity", "Bloom/glow intensity (20 files)"),
    ("Spec_Color", "Spec_Color", "Specular highlight color (20 files)"),
    ("Specular_Mask_Distance", "Specular_Mask_Distance", "Specular mask distance (20 files)"),
    ("Specular_Min_Max", "Specular_Min_Max", "Specular min/max range (20 files)"),
    ("Transition_Opacity", "Transition_Opacity", "Transition opacity (20 files)"),
    ("Bend_Mask_Bounds", "Bend_Mask_Bounds", "Bend mask bounds (19 files)"),
    ("Bend_Mask_Vector", "Bend_Mask_Vector", "Bend mask vector direction (19 files)"),
    ("Bend_Time", "Bend_Time", "Bend animation time (19 files)"),
    ("Bend_XYZ_Offset", "Bend_XYZ_Offset", "Bend XYZ offset (19 files)"),
    ("Distance", "Distance", "Distance parameter (19 files)"),
    ("EdgeNoiseIntensity", "EdgeNoiseIntensity", "Edge noise intensity (19 files)"),
    ("EmissiveFactor", "EmissiveFactor", "Emissive factor (19 files)"),
    ("LS_Offset_Global", "LS_Offset_Global", "Local-space global offset (19 files)"),
    ("LS_Sin_Bounds", "LS_Sin_Bounds", "Local-space sine bounds (19 files)"),
    ("LS_Sin_Frequency", "LS_Sin_Frequency", "Local-space sine frequency (19 files)"),
    ("LS_Sin_Time", "LS_Sin_Time", "Local-space sine time (19 files)"),
    ("LS_Sin_Vector", "LS_Sin_Vector", "Local-space sine vector (19 files)"),
    ("LS_XYZ_Offset", "LS_XYZ_Offset", "Local-space XYZ offset (19 files)"),
    ("MaxTransitionFactor", "MaxTransitionFactor", "Max transition factor (19 files)"),
    ("MinTransitionFactor", "MinTransitionFactor", "Min transition factor (19 files)"),
    ("Opacity_Clip", "Opacity_Clip", "Opacity clip threshold (19 files)"),
    ("ProgressScope", "ProgressScope", "Progress scope for transitions (19 files)"),
    ("WS_Offset_Global", "WS_Offset_Global", "World-space global offset (19 files)"),
    ("centeroffset", "centeroffset", "Center offset (19 files)"),
    ("ratio", "ratio", "Ratio parameter (19 files)"),
    ("AdditionalWPO", "AdditionalWPO", "Additional world position offset (18 files)"),
    ("BaseTex_TintColor", "BaseTex_TintColor", "Base texture tint color (18 files)"),
    ("EMISSION_AnimationSpeed", "EMISSION_AnimationSpeed", "Emission animation speed (18 files)"),
    ("EMISSION_EmissionColor", "EMISSION_EmissionColor", "Emission color (18 files)"),
    ("EMISSION_ROTATE_RotationCenter", "EMISSION_ROTATE_RotationCenter", "Emission rotation center (18 files)"),
    ("EMISSION_ROTATE_TexUVScale", "EMISSION_ROTATE_TexUVScale", "Emission rotation UV scale (18 files)"),
    ("FLOW_Center", "FLOW_Center", "Flow effect center (18 files)"),
    ("FLOW_Color", "FLOW_Color", "Flow effect color (18 files)"),
    ("FLOW_FAN_Count", "FLOW_FAN_Count", "Flow fan count (18 files)"),
    ("FLOW_RIPPLE_Bright", "FLOW_RIPPLE_Bright", "Flow ripple bright (18 files)"),
    ("FLOW_RIPPLE_Dark", "FLOW_RIPPLE_Dark", "Flow ripple dark (18 files)"),
    ("FLOW_RIPPLE_Frequence", "FLOW_RIPPLE_Frequence", "Flow ripple frequency (18 files)"),
    ("FLOW_RIPPLE_ShapeSmoothness", "FLOW_RIPPLE_ShapeSmoothness", "Flow ripple shape smoothness (18 files)"),
    ("FLOW_RIPPLE_Width", "FLOW_RIPPLE_Width", "Flow ripple width (18 files)"),
    ("RotateVector", "RotateVector", "Rotation vector (18 files)"),
    ("RotationDistance", "RotationDistance", "Rotation distance (18 files)"),
    ("RotationMult", "RotationMult", "Rotation multiplier (18 files)"),
    ("RotationSpeed", "RotationSpeed", "Rotation speed (18 files)"),
    ("RotationTimingOffset", "RotationTimingOffset", "Rotation timing offset (18 files)"),
    ("Strength", "Strength", "Generic strength parameter (18 files)"),
    ("TranslationDistance", "TranslationDistance", "Translation distance (18 files)"),
    ("TranslationSpeed", "TranslationSpeed", "Translation speed (18 files)"),
    ("TranslationTimingOffset", "TranslationTimingOffset", "Translation timing offset (18 files)"),
    ("TranslationVector", "TranslationVector", "Translation vector (18 files)"),
    ("TransparentOutSpeed", "TransparentOutSpeed", "Transparent out speed (18 files)"),
    ("TransparentSpeed", "TransparentSpeed", "Transparent animation speed (18 files)"),
    ("WS_RotatePivotPoint", "WS_RotatePivotPoint", "World-space rotation pivot (18 files)"),
    ("WaveTintColor", "WaveTintColor", "Wave tint color (18 files)"),
    ("WindIntensity", "WindIntensity", "Wind intensity (18 files)"),
    ("WindScale", "WindScale", "Wind scale (18 files)"),
    ("WindSpeed", "WindSpeed", "Wind speed (18 files)"),
]


# --- ALL 627 PARAMETERS GROUPED BY CATEGORY ---

PARAMS_ALPHA = [
    ("Alph_Fresnel_Size", "Alph_Fresnel_Size", "Alpha fresnel size (1 file)"),
    ("Alpha", "Alpha", "Alpha value (10 files)"),
    ("AlphaBias", "AlphaBias", "Alpha bias (3 files)"),
    ("AlphaClip", "AlphaClip", "Alpha clip (2 files)"),
    ("AlphaClipValue", "AlphaClipValue", "Alpha clip threshold (21 files)"),
    ("AlphaControl", "AlphaControl", "Alpha control (3 files)"),
    ("AlphaOverride", "AlphaOverride", "Alpha override (1 file)"),
    ("AlphaPower", "AlphaPower", "Alpha power/exponent (16 files)"),
    ("AlphaStepMax", "AlphaStepMax", "Alpha step max (1 file)"),
    ("AlphaStepMin", "AlphaStepMin", "Alpha step min (1 file)"),
    ("AlphaStrength", "AlphaStrength", "Alpha strength (1 file)"),
    ("AlphaTestValue", "AlphaTestValue", "Alpha test threshold (98 files)"),
    ("AlphaTwist", "AlphaTwist", "Alpha twist (9 files)"),
    ("Alpha_Bias", "Alpha_Bias", "Alpha bias (7 files)"),
    ("Alpha_Contrast", "Alpha_Contrast", "Alpha contrast (3 files)"),
    ("Alpha_DistortionUV_Strength", "Alpha_DistortionUV_Strength", "Alpha distortion UV strength (3 files)"),
    ("Alpha_Distortion_Strength", "Alpha_Distortion_Strength", "Alpha distortion strength (3 files)"),
    ("Alpha_Fade_Min_Max", "Alpha_Fade_Min_Max", "Alpha fade min/max (1 file)"),
    ("Alpha_Fade_Randomizer", "Alpha_Fade_Randomizer", "Alpha fade randomizer (1 file)"),
    ("Alpha_Fade_Time", "Alpha_Fade_Time", "Alpha fade time (1 file)"),
    ("Alpha_Intensity", "Alpha_Intensity", "Alpha intensity (1 file)"),
    ("Alpha_Mask_Strength", "Alpha_Mask_Strength", "Alpha mask strength (2 files)"),
    ("Alpha_Multiply", "Alpha_Multiply", "Alpha multiply factor (1 file)"),
    ("Alpha_Offset", "Alpha_Offset", "Alpha offset (8 files)"),
    ("Alpha_Remap_Param_U", "Alpha_Remap_Param_U", "Alpha remap U (3 files)"),
    ("Alpha_Remap_Param_V", "Alpha_Remap_Param_V", "Alpha remap V (3 files)"),
    ("Alpha_Scroll_Tiling", "Alpha_Scroll_Tiling", "Alpha scroll tiling (3 files)"),
    ("Alpha_Strength", "Alpha_Strength", "Alpha strength (2 files)"),
    ("Alpha_Test_Value", "Alpha_Test_Value", "Alpha test value (16 files)"),
    ("DiffuseAlphaStrength", "DiffuseAlphaStrength", "Diffuse alpha strength (6 files)"),
    ("EdgeAlpha", "EdgeAlpha", "Edge alpha (2 files)"),
    ("Final_Alpha", "Final_Alpha", "Final alpha output (4 files)"),
    ("Opacity_Clip", "Opacity_Clip", "Opacity clip threshold (19 files)"),
    ("OpacityControl", "OpacityControl", "Opacity control (2 files)"),
]

PARAMS_COLOR = [
    ("Background_color", "Background_color", "Background color (1 file)"),
    ("BaseTex_TintColor", "BaseTex_TintColor", "Base texture tint (18 files)"),
    ("BaseTint", "BaseTint", "Base tint (3 files)"),
    ("Base_Color", "Base_Color", "Base color (4 files)"),
    ("Color", "Color", "Generic RGBA color (24 files)"),
    ("ColorBottom", "ColorBottom", "Bottom color (1 file)"),
    ("ColorTint", "ColorTint", "Color tint (3 files)"),
    ("ColorTop", "ColorTop", "Top color (1 file)"),
    ("Color_A", "Color_A", "Color A (2 files)"),
    ("Color_B", "Color_B", "Color B (2 files)"),
    ("Color_Baseline", "Color_Baseline", "Color baseline (11 files)"),
    ("Color_Blend", "Color_Blend", "Color blend (56 files)"),
    ("Color_Bottom", "Color_Bottom", "Color bottom (14 files)"),
    ("Color_Highlight_Contrast", "Color_Highlight_Contrast", "Color highlight contrast (11 files)"),
    ("Color_Inside", "Color_Inside", "Color inside (11 files)"),
    ("Color_Multiply", "Color_Multiply", "Color multiply (56 files)"),
    ("Color_Outside", "Color_Outside", "Color outside (11 files)"),
    ("ColorDodge_Amount", "ColorDodge_Amount", "Color dodge amount (2 files)"),
    ("Deep_Color", "Deep_Color", "Deep color (2 files)"),
    ("Diffuse_Color", "Diffuse_Color", "Diffuse color (10 files)"),
    ("Diffuse_Tint", "Diffuse_Tint", "Diffuse tint (1 file)"),
    ("DiffuseTint", "DiffuseTint", "Diffuse tint alt (1 file)"),
    ("Glass_Color", "Glass_Color", "Glass color (2 files)"),
    ("Glass_Color1", "Glass_Color1", "Glass color 1 (5 files)"),
    ("Glass_Color2", "Glass_Color2", "Glass color 2 (5 files)"),
    ("HighColor", "HighColor", "High color (1 file)"),
    ("LowColor", "LowColor", "Low color (1 file)"),
    ("MainColor", "MainColor", "Main color (16 files)"),
    ("OverlayColor", "OverlayColor", "Overlay color (5 files)"),
    ("Prismatic_Color", "Prismatic_Color", "Prismatic color (1 file)"),
    ("ReflectionColor", "ReflectionColor", "Reflection color (4 files)"),
    ("ReflectionHighColor", "ReflectionHighColor", "Reflection high color (1 file)"),
    ("ReflectionLowColor", "ReflectionLowColor", "Reflection low color (1 file)"),
    ("RippleColor", "RippleColor", "Ripple color (2 files)"),
    ("ShadowColor", "ShadowColor", "Shadow color (10 files)"),
    ("SpecularColor", "SpecularColor", "Specular color (1 file)"),
    ("Specular_Color", "Specular_Color", "Specular color alt (2 files)"),
    ("Starting_Color", "Starting_Color", "Starting color (21 files)"),
    ("SunColor", "SunColor", "Sun light color (5 files)"),
    ("Switch_Color", "Switch_Color", "Switch state color (5 files)"),
    ("Tint", "Tint", "Tint (2 files)"),
    ("TintColor", "TintColor", "Tint color RGBA (184 files)"),
    ("TintColor_B", "TintColor_B", "Tint color blue (6 files)"),
    ("TintColor_G", "TintColor_G", "Tint color green (6 files)"),
    ("TintColor_R", "TintColor_R", "Tint color red (6 files)"),
    ("Tint_Color", "Tint_Color", "Tint color alt (24 files)"),
    ("UnderColor", "UnderColor", "Under color (1 file)"),
    ("Water_Color", "Water_Color", "Water color (2 files)"),
    ("WaveTintColor", "WaveTintColor", "Wave tint color (18 files)"),
]

PARAMS_BLOOM_GLOW = [
    ("BloomColor", "BloomColor", "Bloom color (3 files)"),
    ("BloomIntensity", "BloomIntensity", "Bloom intensity (8 files)"),
    ("BloomStrength", "BloomStrength", "Bloom strength (2 files)"),
    ("BloomThreshold", "BloomThreshold", "Bloom threshold (3 files)"),
    ("BloomWeight", "BloomWeight", "Bloom weight (3 files)"),
    ("Bloom_Color", "Bloom_Color", "Bloom color alt (5 files)"),
    ("Bloom_Factor", "Bloom_Factor", "Bloom factor (10 files)"),
    ("Bloom_Intensity", "Bloom_Intensity", "Bloom intensity alt (20 files)"),
    ("Bloom_Intensity_Adjust", "Bloom_Intensity_Adjust", "Bloom intensity adjust (1 file)"),
    ("Glow_Color", "Glow_Color", "Glow color (26 files)"),
    ("Glow_Frequency", "Glow_Frequency", "Glow frequency (16 files)"),
    ("Glow_Intensity", "Glow_Intensity", "Glow intensity (1 file)"),
    ("Glow_Intensity_Min_Max", "Glow_Intensity_Min_Max", "Glow intensity min/max (10 files)"),
    ("Glow_Min_Max", "Glow_Min_Max", "Glow min/max (16 files)"),
    ("Glow_SmoothStep", "Glow_SmoothStep", "Glow smooth step (10 files)"),
    ("Glow_Speed", "Glow_Speed", "Glow speed (16 files)"),
    ("Radial_Bounds", "Radial_Bounds", "Radial bounds (10 files)"),
    ("Radial_Frequency", "Radial_Frequency", "Radial frequency (10 files)"),
    ("Radial_Glow_Opacity", "Radial_Glow_Opacity", "Radial glow opacity (10 files)"),
    ("Radial_Speed", "Radial_Speed", "Radial speed (10 files)"),
]

PARAMS_EMISSION = [
    ("EMISSION_AnimationSpeed", "EMISSION_AnimationSpeed", "Emission anim speed (18 files)"),
    ("EMISSION_EmissionColor", "EMISSION_EmissionColor", "Emission color (18 files)"),
    ("EMISSION_ROTATE_RotationCenter", "EMISSION_ROTATE_RotationCenter", "Emission rotation center (18 files)"),
    ("EMISSION_ROTATE_TexUVScale", "EMISSION_ROTATE_TexUVScale", "Emission rotation UV scale (18 files)"),
    ("EMMISSIVE_WorldSpace_GradientBounds_MIN_MAX", "EMMISSIVE_WorldSpace_GradientBounds_MIN_MAX", "Emissive WS gradient bounds (2 files)"),
    ("EmiRotationSpeed", "EmiRotationSpeed", "Emission rotation speed (16 files)"),
    ("EmissionColor", "EmissionColor", "Emission color alt (16 files)"),
    ("EmissionTexUV", "EmissionTexUV", "Emission texture UV (16 files)"),
    ("Emission_Anim_Amplitude", "Emission_Anim_Amplitude", "Emission anim amplitude (2 files)"),
    ("Emission_Anim_Frequency", "Emission_Anim_Frequency", "Emission anim frequency (2 files)"),
    ("Emission_Anim_Offset", "Emission_Anim_Offset", "Emission anim offset (2 files)"),
    ("EmissiveFactor", "EmissiveFactor", "Emissive factor (19 files)"),
    ("EmissiveStrength", "EmissiveStrength", "Emissive strength (3 files)"),
    ("Emissive_Color", "Emissive_Color", "Emissive color (14 files)"),
    ("Emissive_Dims", "Emissive_Dims", "Emissive dimensions (4 files)"),
    ("Emissive_Intensity", "Emissive_Intensity", "Emissive intensity (16 files)"),
    ("Emissive_Intensity_Adjust", "Emissive_Intensity_Adjust", "Emissive intensity adjust (1 file)"),
    ("Emissive_Selector", "Emissive_Selector", "Emissive selector (4 files)"),
    ("Emmissive_Intensity", "Emmissive_Intensity", "Emissive intensity (typo variant) (2 files)"),
]

PARAMS_DIFFUSE_TEXTURE = [
    ("Base_Diffuse_Tiling", "Base_Diffuse_Tiling", "Base diffuse tiling (3 files)"),
    ("ColorTexTilling", "ColorTexTilling", "Color texture tiling (21 files)"),
    ("DiffuseMultiply", "DiffuseMultiply", "Diffuse multiply (5 files)"),
    ("DiffuseScale", "DiffuseScale", "Diffuse scale (1 file)"),
    ("DiffuseScrollSpeed", "DiffuseScrollSpeed", "Diffuse scroll speed (1 file)"),
    ("DiffuseStrength", "DiffuseStrength", "Diffuse strength (3 files)"),
    ("DiffuseTexOffset", "DiffuseTexOffset", "Diffuse tex offset (2 files)"),
    ("DiffuseTexParams", "DiffuseTexParams", "Diffuse tex params (3 files)"),
    ("DiffuseTexTiling", "DiffuseTexTiling", "Diffuse tex tiling (2 files)"),
    ("DiffuseTextureTiling", "DiffuseTextureTiling", "Diffuse texture tiling (6 files)"),
    ("DiffuseUVScroll", "DiffuseUVScroll", "Diffuse UV scroll (6 files)"),
    ("Diffuse_Brightness", "Diffuse_Brightness", "Diffuse brightness (1 file)"),
    ("Diffuse_Contrast", "Diffuse_Contrast", "Diffuse contrast (1 file)"),
    ("Diffuse_Dims", "Diffuse_Dims", "Diffuse dimensions (4 files)"),
    ("Diffuse_Offset", "Diffuse_Offset", "Diffuse offset (10 files)"),
    ("Diffuse_Rotation_Speed", "Diffuse_Rotation_Speed", "Diffuse rotation speed (1 file)"),
    ("Diffuse_Scale", "Diffuse_Scale", "Diffuse scale (1 file)"),
    ("Diffuse_Selector", "Diffuse_Selector", "Diffuse selector (4 files)"),
    ("Diffuse_UV_Offset", "Diffuse_UV_Offset", "Diffuse UV offset (1 file)"),
    ("Diffuse_UV_PivotPoint", "Diffuse_UV_PivotPoint", "Diffuse UV pivot point (1 file)"),
    ("Diffuse_UV_Tiling", "Diffuse_UV_Tiling", "Diffuse UV tiling (2 files)"),
    ("DesaturationValue", "DesaturationValue", "Desaturation value (16 files)"),
    ("NoiseTexTilling", "NoiseTexTilling", "Noise texture tiling (21 files)"),
    ("Normal_Tiling", "Normal_Tiling", "Normal map tiling (10 files)"),
]

PARAMS_SCROLL_ROTATE = [
    ("Rotation_Speed", "Rotation_Speed", "Rotation speed (58 files)"),
    ("Scroll_Speed", "Scroll_Speed", "Scroll speed (56 files)"),
    ("UV_Rotation", "UV_Rotation", "UV rotation angle (31 files)"),
    ("UV_Rotation_Center", "UV_Rotation_Center", "UV rotation center (21 files)"),
    ("UV_Scroll_Speed", "UV_Scroll_Speed", "UV scroll speed (12 files)"),
    ("ScrollDirectionSpeed", "ScrollDirectionSpeed", "Scroll direction speed (11 files)"),
    ("RotateVector", "RotateVector", "Rotate vector (18 files)"),
    ("RotationDistance", "RotationDistance", "Rotation distance (18 files)"),
    ("RotationMult", "RotationMult", "Rotation multiplier (18 files)"),
    ("RotationSpeed", "RotationSpeed", "Rotation speed (18 files)"),
    ("RotationTimingOffset", "RotationTimingOffset", "Rotation timing offset (18 files)"),
    ("RotationAngle_Primary", "RotationAngle_Primary", "Primary rotation angle (13 files)"),
    ("RotationAngle_Secondary", "RotationAngle_Secondary", "Secondary rotation angle (13 files)"),
    ("RotationalAxis_Primary", "RotationalAxis_Primary", "Primary rotational axis (13 files)"),
    ("RotationalAxis_Secondary", "RotationalAxis_Secondary", "Secondary rotational axis (13 files)"),
    ("Secondary_Rotation_Rate", "Secondary_Rotation_Rate", "Secondary rotation rate (13 files)"),
    ("ScrollTexAOffset", "ScrollTexAOffset", "Scroll tex A offset (2 files)"),
    ("ScrollTexASpeed", "ScrollTexASpeed", "Scroll tex A speed (2 files)"),
    ("ScrollTexATiling", "ScrollTexATiling", "Scroll tex A tiling (2 files)"),
    ("ScrollTexIntensity", "ScrollTexIntensity", "Scroll tex intensity (2 files)"),
    ("ScrollingTexture2Rate", "ScrollingTexture2Rate", "Scrolling texture 2 rate (4 files)"),
    ("ScrollingTexture2Scale", "ScrollingTexture2Scale", "Scrolling texture 2 scale (4 files)"),
    ("ScrollingTextureRate", "ScrollingTextureRate", "Scrolling texture rate (4 files)"),
    ("ScrollingTextureScale", "ScrollingTextureScale", "Scrolling texture scale (4 files)"),
    ("ScrollingMask_Bias", "ScrollingMask_Bias", "Scrolling mask bias (3 files)"),
    ("ScrollingMask_Sharpness", "ScrollingMask_Sharpness", "Scrolling mask sharpness (3 files)"),
    ("Rotation_Axis", "Rotation_Axis", "Rotation axis (1 file)"),
    ("Rotation_Center", "Rotation_Center", "Rotation center (1 file)"),
    ("RotationSpeedCrystalGlass", "RotationSpeedCrystalGlass", "Crystal glass rotation speed (1 file)"),
    ("UV_Offset", "UV_Offset", "UV offset (5 files)"),
    ("UV_Translate", "UV_Translate", "UV translate (5 files)"),
    ("UV_TileAmount", "UV_TileAmount", "UV tile amount (6 files)"),
    ("UV_Scroll_Offset", "UV_Scroll_Offset", "UV scroll offset (2 files)"),
    ("UV_Scroll_Scale", "UV_Scroll_Scale", "UV scroll scale (2 files)"),
]

PARAMS_DEFORM_WAVE = [
    ("DeformColor01", "DeformColor01", "Deform color 01 (3 files)"),
    ("DeformColor02", "DeformColor02", "Deform color 02 (3 files)"),
    ("DeformInfo", "DeformInfo", "Deform info (3 files)"),
    ("DeformMaskStrength", "DeformMaskStrength", "Deform mask strength (25 files)"),
    ("DeformWaveController", "DeformWaveController", "Deform wave controller (25 files)"),
    ("DeformWaveStrength", "DeformWaveStrength", "Deform wave strength (25 files)"),
    ("LargeWaveInfo", "LargeWaveInfo", "Large wave info (10 files)"),
    ("SmallWaveInfo", "SmallWaveInfo", "Small wave info (10 files)"),
    ("WaveAmplitude", "WaveAmplitude", "Wave amplitude (33 files)"),
    ("WaveContrast", "WaveContrast", "Wave contrast (2 files)"),
    ("WaveController", "WaveController", "Wave controller (13 files)"),
    ("WaveFrequency", "WaveFrequency", "Wave frequency (33 files)"),
    ("WaveMaskStrength", "WaveMaskStrength", "Wave mask strength (11 files)"),
    ("WaveOffset", "WaveOffset", "Wave offset (33 files)"),
    ("WaveStrength", "WaveStrength", "Wave strength (11 files)"),
    ("Wave_Speed", "Wave_Speed", "Wave speed (2 files)"),
]

PARAMS_BEND_FOLIAGE = [
    ("Bend_Mask_Bounds", "Bend_Mask_Bounds", "Bend mask bounds (19 files)"),
    ("Bend_Mask_Vector", "Bend_Mask_Vector", "Bend mask vector (19 files)"),
    ("Bend_Time", "Bend_Time", "Bend time (19 files)"),
    ("Bend_XYZ_Offset", "Bend_XYZ_Offset", "Bend XYZ offset (19 files)"),
    ("Bobbing_Rate", "Bobbing_Rate", "Bobbing rate (13 files)"),
    ("WindIntensity", "WindIntensity", "Wind intensity (18 files)"),
    ("WindScale", "WindScale", "Wind scale (18 files)"),
    ("WindSpeed", "WindSpeed", "Wind speed (18 files)"),
    ("Wind_Bend_Intensity", "Wind_Bend_Intensity", "Wind bend intensity (16 files)"),
    ("Wind_Global_Intensity", "Wind_Global_Intensity", "Wind global intensity (5 files)"),
    ("Wind_Shake_Intensity", "Wind_Shake_Intensity", "Wind shake intensity (16 files)"),
]

PARAMS_DISTANCE_SEETHROUGH = [
    ("DistControlFactor", "DistControlFactor", "Distance control factor (33 files)"),
    ("Distance", "Distance", "Distance (19 files)"),
    ("DistanceBias", "DistanceBias", "Distance bias (6 files)"),
    ("DistanceOffset", "DistanceOffset", "Distance offset (2 files)"),
    ("MinDistance", "MinDistance", "Minimum distance (33 files)"),
    ("ScaleInFactor", "ScaleInFactor", "Scale-in factor (33 files)"),
    ("ScaleOutFactor", "ScaleOutFactor", "Scale-out factor (33 files)"),
    ("SeeThroughAlphaMax", "SeeThroughAlphaMax", "See-through alpha max (33 files)"),
    ("SeeThroughAlphaMin", "SeeThroughAlphaMin", "See-through alpha min (33 files)"),
    ("SeeThroughRangeScale", "SeeThroughRangeScale", "See-through range scale (33 files)"),
    ("SpreadStrength", "SpreadStrength", "Spread strength (33 files)"),
    ("VelocityStrength", "VelocityStrength", "Velocity strength (33 files)"),
    ("PitchFactor", "PitchFactor", "Pitch factor (32 files)"),
]

PARAMS_TRANSITION = [
    ("Decal_Transition_Factor", "Decal_Transition_Factor", "Decal transition factor (5 files)"),
    ("EdgeRange", "EdgeRange", "Edge range (21 files)"),
    ("EdgeRangeOuter", "EdgeRangeOuter", "Edge range outer (21 files)"),
    ("EdgeNoiseIntensity", "EdgeNoiseIntensity", "Edge noise intensity (19 files)"),
    ("MaxTransitionFactor", "MaxTransitionFactor", "Max transition factor (19 files)"),
    ("MinTransitionFactor", "MinTransitionFactor", "Min transition factor (19 files)"),
    ("ProgressScope", "ProgressScope", "Progress scope (19 files)"),
    ("Transition_Opacity", "Transition_Opacity", "Transition opacity (20 files)"),
    ("Transition_Speed_Factor", "Transition_Speed_Factor", "Transition speed factor (24 files)"),
    ("Transition_Start_End", "Transition_Start_End", "Transition start/end (7 files)"),
    ("ParamStage1", "ParamStage1", "Param stage 1 (21 files)"),
    ("Starting_Geo_Offset", "Starting_Geo_Offset", "Starting geo offset (21 files)"),
]

PARAMS_SPECULAR = [
    ("Glass_Roughness", "Glass_Roughness", "Glass roughness (5 files)"),
    ("Glass_Transparency", "Glass_Transparency", "Glass transparency (1 file)"),
    ("PlanarReflectionStrength", "PlanarReflectionStrength", "Planar reflection strength (12 files)"),
    ("ReflectionIntensity", "ReflectionIntensity", "Reflection intensity (3 files)"),
    ("ReflectionParams", "ReflectionParams", "Reflection params (3 files)"),
    ("ReflectionSize", "ReflectionSize", "Reflection size (1 file)"),
    ("Reflection_Intensity", "Reflection_Intensity", "Reflection intensity alt (2 files)"),
    ("Refraction_Brightness", "Refraction_Brightness", "Refraction brightness (2 files)"),
    ("Refraction_Strength", "Refraction_Strength", "Refraction strength (2 files)"),
    ("Refraction_Tiling", "Refraction_Tiling", "Refraction tiling (2 files)"),
    ("Rim_Color", "Rim_Color", "Rim light color (2 files)"),
    ("Rim_Intensity", "Rim_Intensity", "Rim light intensity (2 files)"),
    ("Rim_Power", "Rim_Power", "Rim light power (2 files)"),
    ("Spec_Color", "Spec_Color", "Specular color (20 files)"),
    ("Specular_Highlight_Size", "Specular_Highlight_Size", "Specular highlight size (1 file)"),
    ("Specular_Intensity", "Specular_Intensity", "Specular intensity (21 files)"),
    ("Specular_Mask_Distance", "Specular_Mask_Distance", "Specular mask distance (20 files)"),
    ("Specular_Min_Max", "Specular_Min_Max", "Specular min/max (20 files)"),
    ("SpecularSensitity", "SpecularSensitity", "Specular sensitivity (4 files)"),
]

PARAMS_FLOW_WATER = [
    ("FlowDirection", "FlowDirection", "Flow direction (2 files)"),
    ("FlowMap_Speed", "FlowMap_Speed", "Flow map speed (11 files)"),
    ("FlowNormal_Tile", "FlowNormal_Tile", "Flow normal tile (11 files)"),
    ("FlowSpeed", "FlowSpeed", "Flow speed (2 files)"),
    ("FlowTiling", "FlowTiling", "Flow tiling (2 files)"),
    ("Flow_Direction", "Flow_Direction", "Flow direction alt (12 files)"),
    ("Flow_Distance", "Flow_Distance", "Flow distance (2 files)"),
    ("Flow_Speed", "Flow_Speed", "Flow speed alt (14 files)"),
    ("Flow_Strength", "Flow_Strength", "Flow strength (12 files)"),
    ("Flowmap_Strength", "Flowmap_Strength", "Flowmap strength (11 files)"),
    ("MaxFlowStrength", "MaxFlowStrength", "Max flow strength (2 files)"),
    ("Foam_Amount", "Foam_Amount", "Foam amount (2 files)"),
    ("Foam_Color", "Foam_Color", "Foam color (2 files)"),
    ("Foam_Cutoff", "Foam_Cutoff", "Foam cutoff (2 files)"),
    ("Foam_Lines", "Foam_Lines", "Foam lines (2 files)"),
    ("Foam_Thickness", "Foam_Thickness", "Foam thickness (2 files)"),
    ("FLOW_Center", "FLOW_Center", "Flow center (18 files)"),
    ("FLOW_Color", "FLOW_Color", "Flow color (18 files)"),
    ("FLOW_FAN_Count", "FLOW_FAN_Count", "Flow fan count (18 files)"),
    ("FLOW_RIPPLE_Bright", "FLOW_RIPPLE_Bright", "Flow ripple bright (18 files)"),
    ("FLOW_RIPPLE_Dark", "FLOW_RIPPLE_Dark", "Flow ripple dark (18 files)"),
    ("FLOW_RIPPLE_Frequence", "FLOW_RIPPLE_Frequence", "Flow ripple frequency (18 files)"),
    ("FLOW_RIPPLE_ShapeSmoothness", "FLOW_RIPPLE_ShapeSmoothness", "Flow ripple smoothness (18 files)"),
    ("FLOW_RIPPLE_Width", "FLOW_RIPPLE_Width", "Flow ripple width (18 files)"),
]

PARAMS_DISTORTION = [
    ("Distortion_Amount", "Distortion_Amount", "Distortion amount (4 files)"),
    ("Distortion_Highlight_Contrast", "Distortion_Highlight_Contrast", "Distortion highlight contrast (11 files)"),
    ("Distortion_ScrollSpeed", "Distortion_ScrollSpeed", "Distortion scroll speed (4 files)"),
    ("Distortion_TimeSpeed", "Distortion_TimeSpeed", "Distortion time speed (4 files)"),
    ("DistortionA_Strength", "DistortionA_Strength", "Distortion A strength (3 files)"),
    ("DistortionA_Tiling", "DistortionA_Tiling", "Distortion A tiling (3 files)"),
    ("DistortionA_UV_Strength", "DistortionA_UV_Strength", "Distortion A UV strength (3 files)"),
    ("DistortionAmountU", "DistortionAmountU", "Distortion amount U (1 file)"),
    ("DistortionAmountV", "DistortionAmountV", "Distortion amount V (1 file)"),
    ("DistortionB_Strength", "DistortionB_Strength", "Distortion B strength (3 files)"),
    ("DistortionB_Tiling", "DistortionB_Tiling", "Distortion B tiling (3 files)"),
    ("DistortionB_UV_Strength", "DistortionB_UV_Strength", "Distortion B UV strength (3 files)"),
]

PARAMS_MASK = [
    ("MaskContrast", "MaskContrast", "Mask contrast (2 files)"),
    ("MaskIntensity", "MaskIntensity", "Mask intensity (2 files)"),
    ("MaskScale", "MaskScale", "Mask scale (1 file)"),
    ("MaskScrollSpeed", "MaskScrollSpeed", "Mask scroll speed (1 file)"),
    ("MaskSmoothStep", "MaskSmoothStep", "Mask smooth step (3 files)"),
    ("MaskSpotlight_Offset", "MaskSpotlight_Offset", "Mask spotlight offset (1 file)"),
    ("MaskUVScroll", "MaskUVScroll", "Mask UV scroll (3 files)"),
    ("MaskUVTile", "MaskUVTile", "Mask UV tile (3 files)"),
    ("Mask_A_LS_Bounds", "Mask_A_LS_Bounds", "Mask A local-space bounds (16 files)"),
    ("Mask_A_LS_Vector", "Mask_A_LS_Vector", "Mask A local-space vector (16 files)"),
    ("Mask_B_Rotation_Speed", "Mask_B_Rotation_Speed", "Mask B rotation speed (1 file)"),
    ("Mask_B_Scale", "Mask_B_Scale", "Mask B scale (1 file)"),
    ("Mask_B_UV_PivotPoint", "Mask_B_UV_PivotPoint", "Mask B UV pivot point (1 file)"),
    ("Mask_G_Rotation_Speed", "Mask_G_Rotation_Speed", "Mask G rotation speed (1 file)"),
    ("Mask_G_Scale", "Mask_G_Scale", "Mask G scale (1 file)"),
    ("Mask_G_UV_PivotPoint", "Mask_G_UV_PivotPoint", "Mask G UV pivot point (1 file)"),
    ("Mask_R_Rotation_Speed", "Mask_R_Rotation_Speed", "Mask R rotation speed (1 file)"),
    ("Mask_R_Scale", "Mask_R_Scale", "Mask R scale (1 file)"),
    ("Mask_R_UV_PivotPoint", "Mask_R_UV_PivotPoint", "Mask R UV pivot point (1 file)"),
    ("Effects_Mask_Tiling", "Effects_Mask_Tiling", "Effects mask tiling (3 files)"),
]

PARAMS_GRADIENT = [
    ("GradientTexOffset", "GradientTexOffset", "Gradient tex offset (2 files)"),
    ("GradientTexSpeed", "GradientTexSpeed", "Gradient tex speed (2 files)"),
    ("GradientTexTiling", "GradientTexTiling", "Gradient tex tiling (2 files)"),
    ("Gradient_Hardness", "Gradient_Hardness", "Gradient hardness (2 files)"),
    ("Gradient_Offset", "Gradient_Offset", "Gradient offset (15 files)"),
    ("Gradient_Opacity", "Gradient_Opacity", "Gradient opacity (2 files)"),
    ("Gradient_Scroll_Speed", "Gradient_Scroll_Speed", "Gradient scroll speed (3 files)"),
    ("Gradient_Shift", "Gradient_Shift", "Gradient shift (3 files)"),
    ("Gradient_Size", "Gradient_Size", "Gradient size (2 files)"),
    ("Gradient_Softness", "Gradient_Softness", "Gradient softness (14 files)"),
    ("Remap_Gradient", "Remap_Gradient", "Remap gradient (1 file)"),
]

PARAMS_NOISE = [
    ("NoiseContrast", "NoiseContrast", "Noise contrast (2 files)"),
    ("NoiseControl", "NoiseControl", "Noise control (5 files)"),
    ("NoiseOffset", "NoiseOffset", "Noise offset (2 files)"),
    ("NoiseScale", "NoiseScale", "Noise scale (12 files)"),
    ("NoiseScrollSpeed", "NoiseScrollSpeed", "Noise scroll speed (2 files)"),
    ("NoiseTiling", "NoiseTiling", "Noise tiling (2 files)"),
    ("NoiseUVInfo", "NoiseUVInfo", "Noise UV info (16 files)"),
    ("Noise_Amp", "Noise_Amp", "Noise amplitude (1 file)"),
    ("Noise_Control", "Noise_Control", "Noise control alt (1 file)"),
    ("Noise_Intensity", "Noise_Intensity", "Noise intensity (1 file)"),
    ("Noise_Mask_Strength", "Noise_Mask_Strength", "Noise mask strength (3 files)"),
    ("Noise_Mask_Tiling", "Noise_Mask_Tiling", "Noise mask tiling (3 files)"),
    ("Noise_MinMax", "Noise_MinMax", "Noise min/max (8 files)"),
    ("Noise_Offset", "Noise_Offset", "Noise offset alt (1 file)"),
    ("Noise_Scale", "Noise_Scale", "Noise scale alt (4 files)"),
    ("Noise_Strength", "Noise_Strength", "Noise strength (2 files)"),
    ("Noise_Tiling", "Noise_Tiling", "Noise tiling alt (2 files)"),
    ("Noise_UVScale", "Noise_UVScale", "Noise UV scale (2 files)"),
]

PARAMS_WORLD_OFFSET = [
    ("AdditionalWPO", "AdditionalWPO", "Additional world position offset (18 files)"),
    ("LS_Offset_Global", "LS_Offset_Global", "Local-space offset global (19 files)"),
    ("LS_Sin_Bounds", "LS_Sin_Bounds", "LS sine bounds (19 files)"),
    ("LS_Sin_Frequency", "LS_Sin_Frequency", "LS sine frequency (19 files)"),
    ("LS_Sin_Time", "LS_Sin_Time", "LS sine time (19 files)"),
    ("LS_Sin_Vector", "LS_Sin_Vector", "LS sine vector (19 files)"),
    ("LS_XYZ_Offset", "LS_XYZ_Offset", "LS XYZ offset (19 files)"),
    ("WS_Mask_Location", "WS_Mask_Location", "WS mask location (7 files)"),
    ("WS_Mask_SmoothStep", "WS_Mask_SmoothStep", "WS mask smooth step (7 files)"),
    ("WS_Multiplier", "WS_Multiplier", "WS multiplier (1 file)"),
    ("WS_Offset_Global", "WS_Offset_Global", "WS offset global (19 files)"),
    ("WS_RotatePivotPoint", "WS_RotatePivotPoint", "WS rotation pivot (18 files)"),
    ("WS_Sin_Bounds", "WS_Sin_Bounds", "WS sine bounds (16 files)"),
    ("WS_Sin_Frequency", "WS_Sin_Frequency", "WS sine frequency (16 files)"),
    ("WS_Sin_Speed", "WS_Sin_Speed", "WS sine speed (16 files)"),
    ("WS_Sin_Vector", "WS_Sin_Vector", "WS sine vector (16 files)"),
    ("WPO_Adjustment", "WPO_Adjustment", "WPO adjustment (1 file)"),
    ("WPO_Scale", "WPO_Scale", "WPO scale (1 file)"),
    ("WPO_speed", "WPO_speed", "WPO speed (1 file)"),
    ("Vertex_Offset_Global", "Vertex_Offset_Global", "Vertex offset global (1 file)"),
]

PARAMS_TRANSLATION_MOVEMENT = [
    ("TranslationDistance", "TranslationDistance", "Translation distance (18 files)"),
    ("TranslationSpeed", "TranslationSpeed", "Translation speed (18 files)"),
    ("TranslationTimingOffset", "TranslationTimingOffset", "Translation timing offset (18 files)"),
    ("TranslationVector", "TranslationVector", "Translation vector (18 files)"),
    ("TranslucentControl", "TranslucentControl", "Translucent control (11 files)"),
    ("TransparentOutSpeed", "TransparentOutSpeed", "Transparent out speed (18 files)"),
    ("TransparentSpeed", "TransparentSpeed", "Transparent speed (18 files)"),
    ("Translate_Axis", "Translate_Axis", "Translate axis (13 files)"),
    ("Translate_Range", "Translate_Range", "Translate range (13 files)"),
    ("Movement_Direction", "Movement_Direction", "Movement direction (9 files)"),
    ("Movement_Interpolator", "Movement_Interpolator", "Movement interpolator (9 files)"),
    ("Movement_Offset_Multiplier", "Movement_Offset_Multiplier", "Movement offset multiplier (9 files)"),
]

PARAMS_FRESNEL = [
    ("FrenelRange", "FrenelRange", "Fresnel range (typo variant) (1 file)"),
    ("FresnelSize", "FresnelSize", "Fresnel size (4 files)"),
    ("Fresnel_Size", "Fresnel_Size", "Fresnel size alt (4 files)"),
    ("Fresnel_Size_Inner", "Fresnel_Size_Inner", "Fresnel size inner (7 files)"),
    ("Fresnel_Size_Outer", "Fresnel_Size_Outer", "Fresnel size outer (7 files)"),
]

PARAMS_FOG = [
    ("FogClipDistance", "FogClipDistance", "Fog clip distance (6 files)"),
    ("FogColor", "FogColor", "Fog color (6 files)"),
    ("FogMinMax", "FogMinMax", "Fog min/max (6 files)"),
    ("FogSize", "FogSize", "Fog size (6 files)"),
]

PARAMS_FLIPBOOK = [
    ("AtlasSize", "AtlasSize", "Atlas size (3 files)"),
    ("FlipBook_Dims", "FlipBook_Dims", "Flipbook dimensions (1 file)"),
    ("FlipBook_FPS", "FlipBook_FPS", "Flipbook FPS (1 file)"),
    ("FlipbookSize", "FlipbookSize", "Flipbook size (3 files)"),
    ("FlipbookSpeed", "FlipbookSpeed", "Flipbook speed (3 files)"),
    ("Flipbook_Dims", "Flipbook_Dims", "Flipbook dims alt (1 file)"),
    ("Flipbook_FPS", "Flipbook_FPS", "Flipbook FPS alt (1 file)"),
    ("Flipbook_Offset", "Flipbook_Offset", "Flipbook offset (1 file)"),
    ("Flipbook_RotationSpeed", "Flipbook_RotationSpeed", "Flipbook rotation speed (1 file)"),
    ("Flipbook_Tiling", "Flipbook_Tiling", "Flipbook tiling (1 file)"),
    ("FrameSpeed", "FrameSpeed", "Frame speed (2 files)"),
]

PARAMS_SCANLINE_GLITCH = [
    ("GlitchSpeed", "GlitchSpeed", "Glitch speed (3 files)"),
    ("GlitchStrength", "GlitchStrength", "Glitch strength (3 files)"),
    ("Glitch_Speed", "Glitch_Speed", "Glitch speed alt (3 files)"),
    ("Glitch_Strength", "Glitch_Strength", "Glitch strength alt (3 files)"),
    ("ScanLine_ScrollSpeed", "ScanLine_ScrollSpeed", "Scanline scroll speed (4 files)"),
    ("ScanLine_amount", "ScanLine_amount", "Scanline amount (1 file)"),
    ("ScanLine_minmax", "ScanLine_minmax", "Scanline min/max (1 file)"),
    ("ScanLine_rate", "ScanLine_rate", "Scanline rate (1 file)"),
    ("ScanLines1", "ScanLines1", "Scanlines 1 (4 files)"),
    ("ScanlineAmount", "ScanlineAmount", "Scanline amount alt (3 files)"),
    ("ScanlineMinMax", "ScanlineMinMax", "Scanline min/max alt (3 files)"),
    ("ScanlineRate", "ScanlineRate", "Scanline rate alt (3 files)"),
    ("Scanline_Size", "Scanline_Size", "Scanline size (3 files)"),
    ("PixelateFrequency", "PixelateFrequency", "Pixelate frequency (3 files)"),
    ("PixelateStrength", "PixelateStrength", "Pixelate strength (3 files)"),
    ("Pixelate_Frequency", "Pixelate_Frequency", "Pixelate frequency alt (3 files)"),
    ("Pixelate_Strength", "Pixelate_Strength", "Pixelate strength alt (3 files)"),
    ("PixelationSize", "PixelationSize", "Pixelation size (3 files)"),
    ("Pixelation_Size", "Pixelation_Size", "Pixelation size alt (3 files)"),
]

PARAMS_XYZ_OFFSET = [
    ("X_Offset_Value", "X_Offset_Value", "X offset value (16 files)"),
    ("X_Time_Multiplier", "X_Time_Multiplier", "X time multiplier (16 files)"),
    ("X_Time_Offset", "X_Time_Offset", "X time offset (16 files)"),
    ("X_WS_Offset", "X_WS_Offset", "X world-space offset (16 files)"),
    ("Y_Offset_Value", "Y_Offset_Value", "Y offset value (16 files)"),
    ("Y_Time_Multiplier", "Y_Time_Multiplier", "Y time multiplier (16 files)"),
    ("Y_Time_Offset", "Y_Time_Offset", "Y time offset (16 files)"),
    ("Y_WS_Offset", "Y_WS_Offset", "Y world-space offset (16 files)"),
    ("Z_Offset_Value", "Z_Offset_Value", "Z offset value (16 files)"),
    ("Z_Time_Multiplier", "Z_Time_Multiplier", "Z time multiplier (16 files)"),
    ("Z_Time_Offset", "Z_Time_Offset", "Z time offset (16 files)"),
    ("Z_WS_Offset", "Z_WS_Offset", "Z world-space offset (16 files)"),
    ("X_Offset", "X_Offset", "X offset (1 file)"),
    ("Y_Offset", "Y_Offset", "Y offset (1 file)"),
    ("Z_Offset", "Z_Offset", "Z offset (1 file)"),
    ("Y_AXIS_OFFSET_VALUE", "Y_AXIS_OFFSET_VALUE", "Y axis offset value (5 files)"),
]

PARAMS_UV_AXIS_MASK = [
    ("X_Axis_Offset_UV_Wave", "X_Axis_Offset_UV_Wave", "X axis offset UV wave (5 files)"),
    ("X_Axis_UV_Mask_High", "X_Axis_UV_Mask_High", "X axis UV mask high (5 files)"),
    ("X_Axis_UV_Mask_Low", "X_Axis_UV_Mask_Low", "X axis UV mask low (5 files)"),
    ("X_Axis_UV_Offset_Frequency", "X_Axis_UV_Offset_Frequency", "X axis UV offset freq (5 files)"),
    ("X_Axis_UV_Offset_High", "X_Axis_UV_Offset_High", "X axis UV offset high (5 files)"),
    ("X_Axis_UV_Offset_Low", "X_Axis_UV_Offset_Low", "X axis UV offset low (5 files)"),
    ("X_Axis_UV_Rotation", "X_Axis_UV_Rotation", "X axis UV rotation (5 files)"),
    ("X_Axis_Vertex_Displacement", "X_Axis_Vertex_Displacement", "X axis vertex displacement (5 files)"),
    ("X_UV_Mask_Distance_Offset", "X_UV_Mask_Distance_Offset", "X UV mask distance offset (5 files)"),
    ("Y_Axis_Offset_UV_Wave", "Y_Axis_Offset_UV_Wave", "Y axis offset UV wave (5 files)"),
    ("Y_Axis_UV_Mask_High", "Y_Axis_UV_Mask_High", "Y axis UV mask high (5 files)"),
    ("Y_Axis_UV_Mask_Low", "Y_Axis_UV_Mask_Low", "Y axis UV mask low (5 files)"),
    ("Y_Axis_UV_Offset_Frequency", "Y_Axis_UV_Offset_Frequency", "Y axis UV offset freq (5 files)"),
    ("Y_Axis_UV_Offset_High", "Y_Axis_UV_Offset_High", "Y axis UV offset high (5 files)"),
    ("Y_Axis_UV_Offset_Low", "Y_Axis_UV_Offset_Low", "Y axis UV offset low (5 files)"),
    ("Y_Axis_UV_Rotation", "Y_Axis_UV_Rotation", "Y axis UV rotation (5 files)"),
    ("Y_Axis_Vertex_Displacement", "Y_Axis_Vertex_Displacement", "Y axis vertex displacement (5 files)"),
    ("Y_UV_Mask_Distance_Offset", "Y_UV_Mask_Distance_Offset", "Y UV mask distance offset (5 files)"),
    ("Z_Axis_Offset_UV_Wave", "Z_Axis_Offset_UV_Wave", "Z axis offset UV wave (5 files)"),
    ("Z_Axis_UV_Mask_High", "Z_Axis_UV_Mask_High", "Z axis UV mask high (5 files)"),
    ("Z_Axis_UV_Mask_Low", "Z_Axis_UV_Mask_Low", "Z axis UV mask low (5 files)"),
    ("Z_Axis_UV_Offset_Frequency", "Z_Axis_UV_Offset_Frequency", "Z axis UV offset freq (5 files)"),
    ("Z_Axis_UV_Offset_High", "Z_Axis_UV_Offset_High", "Z axis UV offset high (5 files)"),
    ("Z_Axis_UV_Offset_Low", "Z_Axis_UV_Offset_Low", "Z axis UV offset low (5 files)"),
    ("Z_Axis_UV_Rotation", "Z_Axis_UV_Rotation", "Z axis UV rotation (5 files)"),
    ("Z_Axis_Vertex_Displacement", "Z_Axis_Vertex_Displacement", "Z axis vertex displacement (5 files)"),
    ("Z_UV_Mask_Distance_Offset", "Z_UV_Mask_Distance_Offset", "Z UV mask distance offset (5 files)"),
    ("Time_Multiplier_X_Axis", "Time_Multiplier_X_Axis", "Time multiplier X axis (5 files)"),
    ("Time_Multiplier_Y_Axis", "Time_Multiplier_Y_Axis", "Time multiplier Y axis (5 files)"),
    ("Time_Multiplier_Z_Axis", "Time_Multiplier_Z_Axis", "Time multiplier Z axis (5 files)"),
]

PARAMS_LAYER_SYSTEM = [
    ("LayerBlendMode01", "LayerBlendMode01", "Layer blend mode 01 (3 files)"),
    ("LayerBlendMode02", "LayerBlendMode02", "Layer blend mode 02 (3 files)"),
    ("LayerBlendMode03", "LayerBlendMode03", "Layer blend mode 03 (3 files)"),
    ("LayerMultiFactor02", "LayerMultiFactor02", "Layer multi factor 02 (3 files)"),
    ("LayerMultiFactor03", "LayerMultiFactor03", "Layer multi factor 03 (3 files)"),
    ("LayerTint01", "LayerTint01", "Layer tint 01 (3 files)"),
    ("LayerTint02", "LayerTint02", "Layer tint 02 (3 files)"),
    ("LayerTint03", "LayerTint03", "Layer tint 03 (3 files)"),
    ("LayerUVFactor01", "LayerUVFactor01", "Layer UV factor 01 (3 files)"),
    ("LayerUVFactor02", "LayerUVFactor02", "Layer UV factor 02 (3 files)"),
    ("LayerUVFactor03", "LayerUVFactor03", "Layer UV factor 03 (3 files)"),
    ("LayerUVInfo01", "LayerUVInfo01", "Layer UV info 01 (3 files)"),
    ("LayerUVInfo02", "LayerUVInfo02", "Layer UV info 02 (3 files)"),
    ("LayerUVInfo03", "LayerUVInfo03", "Layer UV info 03 (3 files)"),
    ("LayerUVType01", "LayerUVType01", "Layer UV type 01 (3 files)"),
    ("LayerUVType02", "LayerUVType02", "Layer UV type 02 (3 files)"),
    ("LayerUVType03", "LayerUVType03", "Layer UV type 03 (3 files)"),
    ("NoiseUVInfo01", "NoiseUVInfo01", "Noise UV info 01 (3 files)"),
    ("NoiseUVInfo02", "NoiseUVInfo02", "Noise UV info 02 (3 files)"),
    ("NoiseUVInfo03", "NoiseUVInfo03", "Noise UV info 03 (3 files)"),
    ("NoiseUVType01", "NoiseUVType01", "Noise UV type 01 (3 files)"),
    ("NoiseUVType02", "NoiseUVType02", "Noise UV type 02 (3 files)"),
    ("NoiseUVType03", "NoiseUVType03", "Noise UV type 03 (3 files)"),
]

PARAMS_MISCELLANEOUS = [
    ("Axis", "Axis", "Axis parameter (3 files)"),
    ("BPM", "BPM", "Beats per minute (3 files)"),
    ("BPMIntensity", "BPMIntensity", "BPM intensity (3 files)"),
    ("BPMMeasurement", "BPMMeasurement", "BPM measurement (3 files)"),
    ("BPMStep", "BPMStep", "BPM step (3 files)"),
    ("Bias", "Bias", "Bias value (2 files)"),
    ("Blend_BaseAndScrolling", "Blend_BaseAndScrolling", "Blend base and scrolling (4 files)"),
    ("Blink_ControlAll", "Blink_ControlAll", "Blink control all (1 file)"),
    ("Blink_speed", "Blink_speed", "Blink speed (1 file)"),
    ("BlurCenter", "BlurCenter", "Blur center (1 file)"),
    ("Blue_Blend_Power", "Blue_Blend_Power", "Blue blend power (1 file)"),
    ("BoneInfo", "BoneInfo", "Bone info (3 files)"),
    ("BottomTexParams", "BottomTexParams", "Bottom tex params (1 file)"),
    ("Bottom_Tiling", "Bottom_Tiling", "Bottom tiling (1 file)"),
    ("CrystalA_Depth", "CrystalA_Depth", "Crystal A depth (1 file)"),
    ("CrystalA_Tiling", "CrystalA_Tiling", "Crystal A tiling (1 file)"),
    ("CrystalB_Depth", "CrystalB_Depth", "Crystal B depth (1 file)"),
    ("CrystalGlass_Strength", "CrystalGlass_Strength", "Crystal glass strength (1 file)"),
    ("Crystal_brightness", "Crystal_brightness", "Crystal brightness (1 file)"),
    ("CustomObjectNormal", "CustomObjectNormal", "Custom object normal (3 files)"),
    ("Decal_UV_Tile", "Decal_UV_Tile", "Decal UV tile (5 files)"),
    ("DelayTime", "DelayTime", "Delay time (3 files)"),
    ("DepthPullPush", "DepthPullPush", "Depth pull/push (3 files)"),
    ("Direction", "Direction", "Direction vector (2 files)"),
    ("DissolveInfo", "DissolveInfo", "Dissolve info (3 files)"),
    ("Dodge_MaxValue", "Dodge_MaxValue", "Dodge max value (4 files)"),
    ("Dodge_MinValue", "Dodge_MinValue", "Dodge min value (4 files)"),
    ("DustGlowMaskPower", "DustGlowMaskPower", "Dust glow mask power (1 file)"),
    ("End_Delay", "End_Delay", "End delay (1 file)"),
    ("Extra_Tiling", "Extra_Tiling", "Extra tiling (1 file)"),
    ("Fade_Time", "Fade_Time", "Fade time (1 file)"),
    ("FlickerProperties", "FlickerProperties", "Flicker properties (3 files)"),
    ("Flicker_Rate", "Flicker_Rate", "Flicker rate (4 files)"),
    ("Flicker_Speed", "Flicker_Speed", "Flicker speed (1 file)"),
    ("Frequency", "Frequency", "Frequency (10 files)"),
    ("FrequencyMulti", "FrequencyMulti", "Frequency multiplier (3 files)"),
    ("FrequencyOffsetByWorldPos", "FrequencyOffsetByWorldPos", "Frequency offset by world pos (10 files)"),
    ("From01", "From01", "From value 01 (1 file)"),
    ("From02", "From02", "From value 02 (1 file)"),
    ("From03", "From03", "From value 03 (1 file)"),
    ("GlitterColorA", "GlitterColorA", "Glitter color A (1 file)"),
    ("GlitterColorB", "GlitterColorB", "Glitter color B (1 file)"),
    ("GlitterColorC", "GlitterColorC", "Glitter color C (1 file)"),
    ("GlitterColorP", "GlitterColorP", "Glitter color P (1 file)"),
    ("GlitterNoiseScaleA", "GlitterNoiseScaleA", "Glitter noise scale A (1 file)"),
    ("GlitterNoiseScaleB", "GlitterNoiseScaleB", "Glitter noise scale B (1 file)"),
    ("GlitterNoiseScaleC", "GlitterNoiseScaleC", "Glitter noise scale C (1 file)"),
    ("GlitterOffsetA", "GlitterOffsetA", "Glitter offset A (1 file)"),
    ("GlitterOffsetB", "GlitterOffsetB", "Glitter offset B (1 file)"),
    ("GlitterOffsetC", "GlitterOffsetC", "Glitter offset C (1 file)"),
    ("GlitterOffsetP", "GlitterOffsetP", "Glitter offset P (1 file)"),
    ("GlitterPStrength", "GlitterPStrength", "Glitter P strength (1 file)"),
    ("GlitterP_Tiling", "GlitterP_Tiling", "Glitter P tiling (1 file)"),
    ("GlitterPower", "GlitterPower", "Glitter power (1 file)"),
    ("Green_Blend_Power", "Green_Blend_Power", "Green blend power (1 file)"),
    ("HeightScale_Bot", "HeightScale_Bot", "Height scale bottom (1 file)"),
    ("HeightScale_Top", "HeightScale_Top", "Height scale top (1 file)"),
    ("Height_Start_End", "Height_Start_End", "Height start/end (8 files)"),
    ("Iridescence", "Iridescence", "Iridescence effect (1 file)"),
    ("Iridescence_Strength", "Iridescence_Strength", "Iridescence strength (1 file)"),
    ("Length", "Length", "Length (1 file)"),
    ("LineUVInfo", "LineUVInfo", "Line UV info (1 file)"),
    ("Loop_Reset_Duration", "Loop_Reset_Duration", "Loop reset duration (1 file)"),
    ("Lower_Limit", "Lower_Limit", "Lower limit (10 files)"),
    ("Magnitude", "Magnitude", "Magnitude (10 files)"),
    ("MatcapNormalScale", "MatcapNormalScale", "Matcap normal scale (3 files)"),
    ("MatcapType", "MatcapType", "Matcap type (3 files)"),
    ("Mid_Tiling", "Mid_Tiling", "Mid tiling (1 file)"),
    ("ModOverlay_Amount", "ModOverlay_Amount", "Mod overlay amount (2 files)"),
    ("NoiseRotationSpeedA", "NoiseRotationSpeedA", "Noise rotation speed A (1 file)"),
    ("NoiseRotationSpeedB", "NoiseRotationSpeedB", "Noise rotation speed B (1 file)"),
    ("NoiseRotationSpeedC", "NoiseRotationSpeedC", "Noise rotation speed C (1 file)"),
    ("NoiseRotationSpeedP", "NoiseRotationSpeedP", "Noise rotation speed P (1 file)"),
    ("Object_Height", "Object_Height", "Object height (1 file)"),
    ("OV_High", "OV_High", "OV high value (1 file)"),
    ("OV_Low", "OV_Low", "OV low value (1 file)"),
    ("OverallOffsetX", "OverallOffsetX", "Overall offset X (1 file)"),
    ("OverallOffsetY", "OverallOffsetY", "Overall offset Y (1 file)"),
    ("OverallScaleX", "OverallScaleX", "Overall scale X (1 file)"),
    ("OverallScaleY", "OverallScaleY", "Overall scale Y (1 file)"),
    ("OverlayStrength", "OverlayStrength", "Overlay strength (1 file)"),
    ("Overlay_Boost", "Overlay_Boost", "Overlay boost (4 files)"),
    ("Overlay_Range", "Overlay_Range", "Overlay range (5 files)"),
    ("ParallaxOffset_Bot", "ParallaxOffset_Bot", "Parallax offset bottom (1 file)"),
    ("ParallaxOffset_Top", "ParallaxOffset_Top", "Parallax offset top (1 file)"),
    ("ParallaxVector", "ParallaxVector", "Parallax vector (1 file)"),
    ("Pivot", "Pivot", "Pivot point (3 files)"),
    ("PrismaticB_Tiling", "PrismaticB_Tiling", "Prismatic B tiling (1 file)"),
    ("PuddleContrast", "PuddleContrast", "Puddle contrast (2 files)"),
    ("Pulse_Rate", "Pulse_Rate", "Pulse rate (1 file)"),
    ("RGB_Difffuse_Add", "RGB_Difffuse_Add", "RGB diffuse add (2 files)"),
    ("RainContrast", "RainContrast", "Rain contrast (2 files)"),
    ("RainOffset", "RainOffset", "Rain offset (2 files)"),
    ("RainTiling", "RainTiling", "Rain tiling (2 files)"),
    ("RandThreshold", "RandThreshold", "Random threshold (3 files)"),
    ("Red_Blend_Power", "Red_Blend_Power", "Red blend power (1 file)"),
    ("RepeatLength", "RepeatLength", "Repeat length (1 file)"),
    ("Ring_Offset_Size", "Ring_Offset_Size", "Ring offset size (1 file)"),
    ("RippleIntensity", "RippleIntensity", "Ripple intensity (2 files)"),
    ("RowCount", "RowCount", "Row count (1 file)"),
    ("RowIndex", "RowIndex", "Row index (1 file)"),
    ("SPEED_RANDOMIZER_VALUE", "SPEED_RANDOMIZER_VALUE", "Speed randomizer value (5 files)"),
    ("ScrollingTexAParams", "ScrollingTexAParams", "Scrolling tex A params (1 file)"),
    ("ScrollingTexBParams", "ScrollingTexBParams", "Scrolling tex B params (1 file)"),
    ("ScrollingTexBTint", "ScrollingTexBTint", "Scrolling tex B tint (1 file)"),
    ("ShadowInfo", "ShadowInfo", "Shadow info (10 files)"),
    ("ShineContrast", "ShineContrast", "Shine contrast (1 file)"),
    ("ShineDuration", "ShineDuration", "Shine duration (1 file)"),
    ("ShineFrequency", "ShineFrequency", "Shine frequency (1 file)"),
    ("ShineIntensity", "ShineIntensity", "Shine intensity (1 file)"),
    ("ShineThickness", "ShineThickness", "Shine thickness (1 file)"),
    ("SigilAlpha", "SigilAlpha", "Sigil alpha (1 file)"),
    ("SigilBrightness", "SigilBrightness", "Sigil brightness (1 file)"),
    ("SigilOffsetX", "SigilOffsetX", "Sigil offset X (1 file)"),
    ("SigilOffsetY", "SigilOffsetY", "Sigil offset Y (1 file)"),
    ("SigilTilingX", "SigilTilingX", "Sigil tiling X (1 file)"),
    ("SigilTilingY", "SigilTilingY", "Sigil tiling Y (1 file)"),
    ("Skin_Mask", "Skin_Mask", "Skin mask (1 file)"),
    ("Skin_Mask_Contrast", "Skin_Mask_Contrast", "Skin mask contrast (1 file)"),
    ("SparkleScale", "SparkleScale", "Sparkle scale (1 file)"),
    ("SparkleSpeed", "SparkleSpeed", "Sparkle speed (1 file)"),
    ("Sparkle_Strength", "Sparkle_Strength", "Sparkle strength (1 file)"),
    ("Sparkle_Tiling", "Sparkle_Tiling", "Sparkle tiling (1 file)"),
    ("SparklesIntensity", "SparklesIntensity", "Sparkles intensity (1 file)"),
    ("Speed", "Speed", "Speed (3 files)"),
    ("SpeedMulti", "SpeedMulti", "Speed multiplier (3 files)"),
    ("SpeedParralaxGlitterP", "SpeedParralaxGlitterP", "Parallax glitter speed (1 file)"),
    ("Start_Delay", "Start_Delay", "Start delay (1 file)"),
    ("Steps", "Steps", "Steps (1 file)"),
    ("Strength", "Strength", "Strength (18 files)"),
    ("StrengthMulti", "StrengthMulti", "Strength multiplier (3 files)"),
    ("Switch_MinMax", "Switch_MinMax", "Switch min/max (5 files)"),
    ("Switch_Time_Speed", "Switch_Time_Speed", "Switch time speed (5 files)"),
    ("TimeOffset", "TimeOffset", "Time offset (1 file)"),
    ("Time_Offset_Modifier", "Time_Offset_Modifier", "Time offset modifier (1 file)"),
    ("Time_Speed", "Time_Speed", "Time speed (8 files)"),
    ("To01", "To01", "To value 01 (1 file)"),
    ("To02", "To02", "To value 02 (1 file)"),
    ("To03", "To03", "To value 03 (1 file)"),
    ("TopTexParams", "TopTexParams", "Top tex params (1 file)"),
    ("Top_Tiling", "Top_Tiling", "Top tiling (1 file)"),
    ("TrackAController", "TrackAController", "Track A controller (2 files)"),
    ("TrackBController", "TrackBController", "Track B controller (2 files)"),
    ("Transform", "Transform", "Transform (5 files)"),
    ("UV_Frequency", "UV_Frequency", "UV frequency (10 files)"),
    ("UV_Glow_Opacity", "UV_Glow_Opacity", "UV glow opacity (10 files)"),
    ("Upper_Limit", "Upper_Limit", "Upper limit (10 files)"),
    ("Vertex_Color_Opacity", "Vertex_Color_Opacity", "Vertex color opacity (2 files)"),
    ("WorldPosInfluenceFactor", "WorldPosInfluenceFactor", "World pos influence factor (3 files)"),
    ("centeroffset", "centeroffset", "Center offset (19 files)"),
    ("ratio", "ratio", "Ratio (19 files)"),
]


# =============================================================================
# BLEND FACTORS (D3D11 blend factor enum)
# =============================================================================

BLEND_FACTORS = [
    ("0", "ZERO", "Zero / transparent"),
    ("1", "ONE", "One / opaque"),
    ("2", "SRC_COLOR", "Source color"),
    ("3", "ONE_MINUS_SRC_COLOR", "One minus source color"),
    ("4", "SRC_ALPHA", "Source alpha"),
    ("5", "ONE_MINUS_SRC_ALPHA", "One minus source alpha"),
    ("6", "DST_ALPHA", "Destination alpha"),
    ("7", "ONE_MINUS_DST_ALPHA", "One minus destination alpha"),
    ("8", "DST_COLOR", "Destination color"),
    ("9", "ONE_MINUS_DST_COLOR", "One minus destination color"),
    ("10", "SRC_ALPHA_SATURATE", "Source alpha saturate"),
]


# =============================================================================
# CONVENIENCE: ALL PARAMETERS COMBINED
# =============================================================================

PARAMS_ALL = (
    PARAMS_ALPHA +
    PARAMS_COLOR +
    PARAMS_BLOOM_GLOW +
    PARAMS_EMISSION +
    PARAMS_DIFFUSE_TEXTURE +
    PARAMS_SCROLL_ROTATE +
    PARAMS_DEFORM_WAVE +
    PARAMS_BEND_FOLIAGE +
    PARAMS_DISTANCE_SEETHROUGH +
    PARAMS_TRANSITION +
    PARAMS_SPECULAR +
    PARAMS_FLOW_WATER +
    PARAMS_DISTORTION +
    PARAMS_MASK +
    PARAMS_GRADIENT +
    PARAMS_NOISE +
    PARAMS_WORLD_OFFSET +
    PARAMS_TRANSLATION_MOVEMENT +
    PARAMS_FRESNEL +
    PARAMS_FOG +
    PARAMS_FLIPBOOK +
    PARAMS_SCANLINE_GLITCH +
    PARAMS_XYZ_OFFSET +
    PARAMS_UV_AXIS_MASK +
    PARAMS_LAYER_SYSTEM +
    PARAMS_MISCELLANEOUS
)

# Quick parameter name lookup set
PARAM_NAMES_SET = {item[0] for item in PARAMS_ALL}

# Quick switch name lookup set
SWITCH_NAMES_SET = {item[0] for item in MATERIAL_SWITCHES}

# Quick macro name lookup set
MACRO_NAMES_SET = {item[0] for item in SHADER_MACROS}


# =============================================================================
# SUMMARY
# =============================================================================
if __name__ == "__main__":
    print(f"Material Switches:     {len(MATERIAL_SWITCHES)}")
    print(f"Shader Macros:         {len(SHADER_MACROS)}")
    print(f"Sampler Textures:      {len(SAMPLER_TEXTURE_NAMES)}")
    print(f"Shader Links:          {len(SHADER_LINKS)}")
    print(f"Technique Names:       {len(TECHNIQUE_NAMES)}")
    print(f"Child Technique Names: {len(CHILD_TECHNIQUE_NAMES)}")
    print(f"Blend Factors:         {len(BLEND_FACTORS)}")
    print(f"Parameters (grouped):  {len(PARAMS_ALL)}")
    print(f"  - Alpha:             {len(PARAMS_ALPHA)}")
    print(f"  - Color:             {len(PARAMS_COLOR)}")
    print(f"  - Bloom/Glow:        {len(PARAMS_BLOOM_GLOW)}")
    print(f"  - Emission:          {len(PARAMS_EMISSION)}")
    print(f"  - Diffuse/Texture:   {len(PARAMS_DIFFUSE_TEXTURE)}")
    print(f"  - Scroll/Rotate:     {len(PARAMS_SCROLL_ROTATE)}")
    print(f"  - Deform/Wave:       {len(PARAMS_DEFORM_WAVE)}")
    print(f"  - Bend/Foliage:      {len(PARAMS_BEND_FOLIAGE)}")
    print(f"  - Distance:          {len(PARAMS_DISTANCE_SEETHROUGH)}")
    print(f"  - Transition:        {len(PARAMS_TRANSITION)}")
    print(f"  - Specular:          {len(PARAMS_SPECULAR)}")
    print(f"  - Flow/Water:        {len(PARAMS_FLOW_WATER)}")
    print(f"  - Distortion:        {len(PARAMS_DISTORTION)}")
    print(f"  - Mask:              {len(PARAMS_MASK)}")
    print(f"  - Gradient:          {len(PARAMS_GRADIENT)}")
    print(f"  - Noise:             {len(PARAMS_NOISE)}")
    print(f"  - World Offset:      {len(PARAMS_WORLD_OFFSET)}")
    print(f"  - Translation:       {len(PARAMS_TRANSLATION_MOVEMENT)}")
    print(f"  - Fresnel:           {len(PARAMS_FRESNEL)}")
    print(f"  - Fog:               {len(PARAMS_FOG)}")
    print(f"  - Flipbook:          {len(PARAMS_FLIPBOOK)}")
    print(f"  - Scanline/Glitch:   {len(PARAMS_SCANLINE_GLITCH)}")
    print(f"  - XYZ Offset:        {len(PARAMS_XYZ_OFFSET)}")
    print(f"  - UV Axis Mask:      {len(PARAMS_UV_AXIS_MASK)}")
    print(f"  - Layer System:      {len(PARAMS_LAYER_SYSTEM)}")
    print(f"  - Miscellaneous:     {len(PARAMS_MISCELLANEOUS)}")
