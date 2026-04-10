"""Native legacy NVR (SimpleEnvironment) importer.

Implements direct parsing for old NVR maps (pre-mapgeo) and creates Blender
meshes/material placeholders without requiring external conversion tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
import os
import bpy


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NvrChannel:
    color: tuple[float, float, float, float]
    texture: str


@dataclass
class NvrMaterial:
    name: str
    mat_type: int
    flags: int
    channels: list[NvrChannel]


@dataclass
class NvrPrimitive:
    vertex_buffer_id: int
    start_vertex: int
    vertex_count: int
    index_buffer_id: int
    start_index: int
    index_count: int


@dataclass
class NvrMesh:
    quality: int
    flags: int
    material_id: int
    primitives: list[NvrPrimitive]


# Material type constants
MAT_DEFAULT = 0
MAT_DECAL = 1
MAT_WALL_OF_GRASS = 2
MAT_FOUR_BLEND = 3
MAT_ANTI_BRUSH = 4


@dataclass
class HeightBlendConfig:
    """Parameters from terrain.inibin HeightBlending section."""
    enable: bool = False
    layer0_scale: float = 1.0
    layer1_scale: float = 1.0
    layer2_scale: float = 1.0
    layer3_scale: float = 1.0
    heightscale_path: Path | None = None

# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------

def _read_padded_string(f, length: int) -> str:
    raw = f.read(length)
    if not raw:
        return ""
    nul = raw.find(b"\x00")
    if nul >= 0:
        raw = raw[:nul]
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _read_i32(f) -> int:
    return struct.unpack("<i", f.read(4))[0]


def _read_u32(f) -> int:
    return struct.unpack("<I", f.read(4))[0]


def _read_f32x4(f):
    return struct.unpack("<4f", f.read(16))


def _read_material_new(f) -> NvrMaterial:
    name = _read_padded_string(f, 260)
    mat_type = _read_i32(f)
    flags = _read_u32(f)

    channels: list[NvrChannel] = []
    for _ in range(8):
        color = _read_f32x4(f)
        texture = _read_padded_string(f, 260)
        _ = f.read(64)  # Matrix4x4 row-major
        channels.append(NvrChannel(color=color, texture=texture))

    return NvrMaterial(name=name, mat_type=mat_type, flags=flags, channels=channels)


def _read_material_old(f) -> NvrMaterial:
    name = _read_padded_string(f, 260)
    mat_type = _read_i32(f)
    diffuse_color = _read_f32x4(f)
    diffuse_texture = _read_padded_string(f, 260)
    emissive_color = _read_f32x4(f)
    emissive_texture = _read_padded_string(f, 260)
    channels = [
        NvrChannel(color=diffuse_color, texture=diffuse_texture),
        NvrChannel(color=emissive_color, texture=emissive_texture),
    ] + [NvrChannel(color=(0.0, 0.0, 0.0, 0.0), texture="") for _ in range(6)]
    return NvrMaterial(name=name, mat_type=mat_type, flags=0, channels=channels)


def _read_primitive(f) -> NvrPrimitive:
    return NvrPrimitive(
        vertex_buffer_id=_read_i32(f),
        start_vertex=_read_i32(f),
        vertex_count=_read_i32(f),
        index_buffer_id=_read_i32(f),
        start_index=_read_i32(f),
        index_count=_read_i32(f),
    )


def _decode_indices(buffer: bytes, index_format: int):
    if index_format == 0x65:
        count = len(buffer) // 2
        return struct.unpack(f"<{count}H", buffer) if count else ()
    count = len(buffer) // 4
    return struct.unpack(f"<{count}I", buffer) if count else ()


# ---------------------------------------------------------------------------
# Vertex layout
# ---------------------------------------------------------------------------

def _vertex_stride_for_material(mat: NvrMaterial) -> int:
    """Matches LeagueToolkit SimpleEnvironmentMaterial.GetVertexDeclaration():
      - Default (0): DualVertexColor flag -> 40, else -> 36
      - Decal (1): always DEFAULT -> 36
      - WallOfGrass (2): always DEFAULT -> 36
      - FourBlend (3): always FOUR_BLEND -> 44
      - AntiBrush (4): always DEFAULT -> 36
    """
    if mat.mat_type == MAT_FOUR_BLEND:
        return 44
    if mat.mat_type == MAT_DEFAULT and (mat.flags & (1 << 4)):
        return 40
    return 36


def _candidate_strides_for_material(mat: NvrMaterial):
    primary = _vertex_stride_for_material(mat)
    order = [primary, 36, 40, 44]
    seen = set()
    result = []
    for s in order:
        if s not in seen:
            result.append(s)
            seen.add(s)
    return result


def _decode_vertices(raw: bytes, stride: int, has_second_uv: bool = False):
    """Decode vertices from raw buffer.

    Vertex layouts (all start with Position + Normal + UV0):
      DEFAULT (36):    pos(3f) normal(3f) uv0(2f) color(4B)
      FOUR_BLEND(44):  pos(3f) normal(3f) uv0(2f) uv1(2f) color(4B)
      DUAL_VTXCOL(40): pos(3f) normal(3f) uv0(2f) color(4B) color2(4B)

    Returns: (vertices, uvs0, uvs1, colors)
      uvs1 is empty list if not present.
      colors is list of (r,g,b,a) floats 0-1.
    """
    vertices = []
    uvs0 = []
    uvs1 = []
    colors = []

    if stride < 32:
        return vertices, uvs0, uvs1, colors

    count = len(raw) // stride
    for i in range(count):
        off = i * stride
        x, y, z = struct.unpack_from("<3f", raw, off)
        u0, v0 = struct.unpack_from("<2f", raw, off + 24)

        # League -> Blender axis conversion (swap Y/Z)
        vertices.append((x, z, y))
        uvs0.append((u0, 1.0 - v0))

        if has_second_uv and stride >= 44:
            # FourBlend: uv1 at offset 32, color at offset 40
            u1, v1 = struct.unpack_from("<2f", raw, off + 32)
            uvs1.append((u1, 1.0 - v1))
            r, g, b, a = struct.unpack_from("<4B", raw, off + 40)
        else:
            # Default / DualVertexColor: color at offset 32
            r, g, b, a = struct.unpack_from("<4B", raw, off + 32)

        colors.append((r / 255.0, g / 255.0, b / 255.0, a / 255.0))

    return vertices, uvs0, uvs1, colors


# ---------------------------------------------------------------------------
# Texture finder
# ---------------------------------------------------------------------------

def _build_texture_lookup(nvr_path: Path) -> dict[str, Path]:
    """Build a case-insensitive filename->path lookup from the Textures folder."""
    lookup: dict[str, Path] = {}
    for folder_name in ("Textures", "textures", "TEXTURES"):
        tex_dir = nvr_path.parent / folder_name
        if tex_dir.is_dir():
            for entry in os.scandir(str(tex_dir)):
                if entry.is_file():
                    lookup[entry.name.lower()] = Path(entry.path)
            # Also scan subdirectories (e.g. Textures/hq/)
            for sub in tex_dir.iterdir():
                if sub.is_dir():
                    for entry in os.scandir(str(sub)):
                        if entry.is_file():
                            lookup[entry.name.lower()] = Path(entry.path)
            break
    return lookup


def _find_texture(lookup: dict[str, Path], tex_name: str) -> Path | None:
    """Find a texture by name (case-insensitive), trying .dds/.png fallbacks."""
    if not tex_name:
        return None
    key = tex_name.lower()
    if key in lookup:
        return lookup[key]
    # Try stripping path components
    base = Path(tex_name).name.lower()
    if base in lookup:
        return lookup[base]
    # Try alternative extensions
    stem = Path(base).stem
    for ext in (".dds", ".png", ".tga", ".bmp"):
        candidate = stem + ext
        if candidate in lookup:
            return lookup[candidate]
    return None


def _load_image(filepath: Path) -> bpy.types.Image | None:
    """Load image into Blender, reusing existing."""
    str_path = str(filepath)
    for img in bpy.data.images:
        if img.filepath and os.path.normpath(img.filepath) == os.path.normpath(str_path):
            return img
    try:
        return bpy.data.images.load(str_path, check_existing=True)
    except Exception as e:
        print(f"[NVR] Failed to load image {filepath.name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Material creation
# ---------------------------------------------------------------------------

def _ensure_material(nvr_mat: NvrMaterial, tex_lookup: dict[str, Path],
                     hb_config: HeightBlendConfig | None = None) -> bpy.types.Material:
    base_name = nvr_mat.name.strip() or f"NVRMaterial_{nvr_mat.mat_type}"
    mat_name = f"NVR_{base_name}"
    existing = bpy.data.materials.get(mat_name)
    if existing:
        return existing

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    # Store metadata
    mat["legacy_nvr"] = True
    mat["legacy_nvr_name"] = base_name
    mat["legacy_nvr_type"] = nvr_mat.mat_type
    mat["legacy_nvr_type_name"] = {0: "Default", 1: "Decal", 2: "WallOfGrass", 3: "FourBlend", 4: "AntiBrush"}.get(nvr_mat.mat_type, f"Unknown({nvr_mat.mat_type})")
    mat["legacy_nvr_flags"] = int(nvr_mat.flags)
    mat["legacy_nvr_has_dual_vertex_color"] = bool(nvr_mat.flags & 0x10)
    mat["legacy_nvr_needs_alpha"] = _needs_alpha(nvr_mat)
    # Store channel info
    for ci, ch in enumerate(nvr_mat.channels):
        if ch.texture:
            mat[f"legacy_nvr_ch{ci}_texture"] = ch.texture
        mat[f"legacy_nvr_ch{ci}_color"] = str(list(ch.color))

    if nvr_mat.mat_type == MAT_FOUR_BLEND:
        _setup_four_blend_material(mat, nvr_mat, tex_lookup, hb_config)
    elif nvr_mat.mat_type == MAT_DECAL:
        _setup_decal_material(mat, nvr_mat, tex_lookup)
    else:
        _setup_default_material(mat, nvr_mat, tex_lookup)

    return mat


def _add_tex_node(nodes, links, tex_lookup, tex_name, label, location,
                  extension='REPEAT'):
    """Create a texture image node if the texture file exists. Returns node or None."""
    tex_path = _find_texture(tex_lookup, tex_name)
    if not tex_path:
        return None
    img = _load_image(tex_path)
    if not img:
        return None
    tex_node = nodes.new(type='ShaderNodeTexImage')
    tex_node.location = location
    tex_node.label = label
    tex_node.image = img
    tex_node.extension = extension
    tex_node.interpolation = 'Closest'
    return tex_node


def _is_null_texture(tex_name: str) -> bool:
    """Check if a texture name refers to a null/black placeholder."""
    if not tex_name:
        return True
    lower = tex_name.lower()
    return 'null_black' in lower or 'null' == Path(lower).stem


def _needs_alpha(nvr_mat: NvrMaterial) -> bool:
    """Detect if this material should use alpha transparency.

    Heuristic: flag bit 0x04 set, or material name contains 'alpha',
    or material type is WallOfGrass or Decal.
    """
    if nvr_mat.mat_type in (MAT_DECAL, MAT_WALL_OF_GRASS):
        return True
    if nvr_mat.flags & 0x04:
        return True
    if 'alpha' in nvr_mat.name.lower():
        return True
    return False


def _setup_default_material(mat, nvr_mat, tex_lookup):
    """Default/WallOfGrass/AntiBrush: single diffuse texture."""
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (400, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (100, 0)
    if bsdf.inputs.get('Specular IOR Level'):
        bsdf.inputs['Specular IOR Level'].default_value = 0.0
    elif bsdf.inputs.get('Specular'):
        bsdf.inputs['Specular'].default_value = 0.0
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    use_alpha = _needs_alpha(nvr_mat)
    if use_alpha:
        if hasattr(mat, 'blend_method'):
            mat.blend_method = 'BLEND'
        if hasattr(mat, 'shadow_method'):
            mat.shadow_method = 'CLIP'
        # WallOfGrass with blend: disable transparency overlap
        if nvr_mat.mat_type == MAT_WALL_OF_GRASS:
            if hasattr(mat, 'use_transparency_overlap'):
                mat.use_transparency_overlap = False

    ch0 = nvr_mat.channels[0] if nvr_mat.channels else None
    if ch0 and ch0.texture:
        tex_node = _add_tex_node(nodes, links, tex_lookup, ch0.texture,
                                 "Diffuse", (-300, 0))
        if tex_node:
            links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
            # Always connect alpha channel for proper transparency
            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])


def _setup_decal_material(mat, nvr_mat, tex_lookup):
    """Decal: single texture with alpha blending."""
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Enable alpha blending
    if hasattr(mat, 'blend_method'):
        mat.blend_method = 'BLEND'
    if hasattr(mat, 'shadow_method'):
        mat.shadow_method = 'CLIP'

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (400, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (100, 0)
    if bsdf.inputs.get('Specular IOR Level'):
        bsdf.inputs['Specular IOR Level'].default_value = 0.0
    elif bsdf.inputs.get('Specular'):
        bsdf.inputs['Specular'].default_value = 0.0
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    ch0 = nvr_mat.channels[0] if nvr_mat.channels else None
    if ch0 and ch0.texture:
        tex_node = _add_tex_node(nodes, links, tex_lookup, ch0.texture,
                                 "Decal", (-300, 0), extension='CLIP')
        if tex_node:
            links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])


def _setup_four_blend_material(mat, nvr_mat, tex_lookup,
                               hb_config: HeightBlendConfig | None = None):
    """FourBlend terrain shader: 4 tileable textures blended via a blend map
    or height-based blending (for maps like Twisted Treeline).

    NVR channels:
      Ch[0] = Base layer texture (tiled via UV0)
      Ch[1] = RGB blend map (sampled via UV1) - R=layer2, G=layer3, B=layer4
      Ch[2] = Layer 2 texture (tiled via UV0)
      Ch[4] = Layer 3 texture (tiled via UV0)
      Ch[6] = Layer 4 texture (tiled via UV0)

    When Ch[1] is null/black (e.g. TT) and a terrainHeightScale.dds exists,
    height-based blending is used per HeightBlending.hls: the heightscale
    texture RGBA channels (sampled via UV1) provide per-layer scale values
    that determine which layer is visible at each point.
    """
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (1200, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (900, 0)
    if bsdf.inputs.get('Specular IOR Level'):
        bsdf.inputs['Specular IOR Level'].default_value = 0.0
    elif bsdf.inputs.get('Specular'):
        bsdf.inputs['Specular'].default_value = 0.0
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    # UV nodes
    uv0_node = nodes.new(type='ShaderNodeUVMap')
    uv0_node.uv_map = "UVMap"
    uv0_node.location = (-1400, 200)
    uv0_node.label = "UV0 (Tile)"

    # Determine blend source: texture blend map vs height blending
    ch = nvr_mat.channels
    blend_tex_name = ch[1].texture if len(ch) > 1 else ""
    use_height_blend = _is_null_texture(blend_tex_name)

    # Texture nodes
    base_tex = _add_tex_node(nodes, links, tex_lookup,
                             ch[0].texture if len(ch) > 0 else "",
                             "Base Layer", (-1000, 500))
    blend_tex = None
    if not use_height_blend:
        blend_tex = _add_tex_node(nodes, links, tex_lookup,
                                  blend_tex_name,
                                  "Blend Map", (-1000, -400))
    layer2_tex = _add_tex_node(nodes, links, tex_lookup,
                               ch[2].texture if len(ch) > 2 else "",
                               "Layer 2", (-1000, 300))
    layer3_tex = _add_tex_node(nodes, links, tex_lookup,
                               ch[4].texture if len(ch) > 4 else "",
                               "Layer 3", (-1000, 100))
    layer4_tex = _add_tex_node(nodes, links, tex_lookup,
                               ch[6].texture if len(ch) > 6 else "",
                               "Layer 4", (-1000, -100))

    # Connect UVs to tile textures
    for tex in (base_tex, layer2_tex, layer3_tex, layer4_tex):
        if tex:
            links.new(uv0_node.outputs['UV'], tex.inputs['Vector'])

    if use_height_blend:
        _build_height_blend_nodes(nodes, links, bsdf,
                                  base_tex, layer2_tex, layer3_tex, layer4_tex,
                                  hb_config)
    else:
        _build_blendmap_blend_nodes(nodes, links, bsdf, tex_lookup,
                                    uv0_node, blend_tex, blend_tex_name,
                                    base_tex, layer2_tex, layer3_tex, layer4_tex)


def _build_height_blend_nodes(nodes, links, bsdf,
                              base_tex, layer2_tex, layer3_tex, layer4_tex,
                              hb_config: HeightBlendConfig | None = None):
    """Build height-based blending nodes per HeightBlending.hls.

    Uses terrainHeightScale.dds (sampled via UV1) whose RGBA channels encode
    per-layer height scale values:
      R = base layer scale,  G = layer 2 scale,
      B = layer 3 scale,     A = layer 4 scale

    Additionally applies inibin layer scale constants from HeightBlendConfig
    (from terrain.inibin HeightBlending section) as multipliers.

    Algorithm (from HeightBlending.hls):
      height_i  = texAlpha_i * heightScaleTex_i * inibinScale_i
      maxHeight = max(heights)
      weight_i  = saturate(height_i - maxHeight + half_blend_area)
                * saturate(height_i * 32)
      weights  /= sum(weights)
      color     = sum(layer_i * weight_i)
    """
    if hb_config is None:
        hb_config = HeightBlendConfig()
    heightscale_path = hb_config.heightscale_path

    half_blend = 0.15   # Controls transition softness (0..1)
    inibin_scales = [hb_config.layer0_scale, hb_config.layer1_scale,
                     hb_config.layer2_scale, hb_config.layer3_scale]
    layer_texes = [base_tex, layer2_tex, layer3_tex, layer4_tex]
    layer_labels = ["Base", "Layer2", "Layer3", "Layer4"]

    # --- Load heightscale texture and sample via UV1 ----------------------
    hs_tex_node = None
    if heightscale_path and heightscale_path.exists():
        img = _load_image(heightscale_path)
        if img:
            hs_tex_node = nodes.new(type='ShaderNodeTexImage')
            hs_tex_node.location = (-1000, -600)
            hs_tex_node.label = "terrainHeightScale"
            hs_tex_node.image = img
            hs_tex_node.interpolation = 'Linear'
            hs_tex_node.extension = 'CLIP'
            # Mark non-color so Blender doesn't gamma-correct the data
            img.colorspace_settings.name = 'Non-Color'

            uv1_node = nodes.new(type='ShaderNodeUVMap')
            uv1_node.uv_map = "UV1_Blend"
            uv1_node.location = (-1400, -600)
            uv1_node.label = "UV1 (HeightScale)"
            links.new(uv1_node.outputs['UV'], hs_tex_node.inputs['Vector'])

    if not hs_tex_node:
        # No heightscale texture – fall back to equal-weight blend so all 4
        # layers are visible instead of showing only the base layer.
        print("[NVR] WARNING: terrainHeightScale.dds not found – "
              "using equal-weight fallback for height blending.")
        _build_equal_blend_fallback(nodes, links, bsdf,
                                   base_tex, layer2_tex, layer3_tex, layer4_tex)
        return

    # --- Separate heightscale RGBA into per-layer heights -----------------
    sep_hs = nodes.new(type='ShaderNodeSeparateColor')
    sep_hs.location = (-700, -600)
    sep_hs.label = "HeightScale RGBA"
    links.new(hs_tex_node.outputs['Color'], sep_hs.inputs['Color'])
    # R, G, B from Color output; A from Alpha output
    raw_heights = [
        sep_hs.outputs['Red'],     # base
        sep_hs.outputs['Green'],   # layer 2
        sep_hs.outputs['Blue'],    # layer 3
        hs_tex_node.outputs['Alpha'],  # layer 4
    ]

    # --- Apply inibin layer scale multipliers -----------------------------
    # height_i = heightScaleTex_i * layer_i_scale  (from terrain.inibin)
    heights = []
    for i, (raw_h, scale) in enumerate(zip(raw_heights, inibin_scales)):
        if abs(scale - 1.0) < 1e-6:
            heights.append(raw_h)  # No multiply needed
        else:
            mul = nodes.new(type='ShaderNodeMath')
            mul.operation = 'MULTIPLY'
            mul.location = (-600, -400 - i * 100)
            mul.label = f"h{i}*{scale:.2f}"
            links.new(raw_h, mul.inputs[0])
            mul.inputs[1].default_value = scale
            heights.append(mul.outputs['Value'])
    print(f"[NVR] HeightBlend inibin scales: {inibin_scales}")

    # --- Multiply by tile texture alpha (HeightBlending.hls) --------------
    # The HLSL shader computes: height_i = texel_color_i.alpha * heightScale_i
    # DXT5 textures store per-pixel height data in their alpha channel,
    # which modulates the heightscale value to create detailed transitions.
    for i in range(4):
        tex = layer_texes[i]
        if tex is not None:
            tex_alpha_mul = nodes.new(type='ShaderNodeMath')
            tex_alpha_mul.operation = 'MULTIPLY'
            tex_alpha_mul.location = (-450, -400 - i * 100)
            tex_alpha_mul.label = f"h{i}*texA"
            links.new(heights[i], tex_alpha_mul.inputs[0])
            links.new(tex.outputs['Alpha'], tex_alpha_mul.inputs[1])
            heights[i] = tex_alpha_mul.outputs['Value']

    # --- maxHeight = max(h0, h1, h2, h3) ----------------------------------
    max01 = nodes.new(type='ShaderNodeMath')
    max01.operation = 'MAXIMUM'
    max01.location = (-500, -400)
    max01.label = "Max(h0,h1)"
    links.new(heights[0], max01.inputs[0])
    links.new(heights[1], max01.inputs[1])

    max23 = nodes.new(type='ShaderNodeMath')
    max23.operation = 'MAXIMUM'
    max23.location = (-500, -550)
    max23.label = "Max(h2,h3)"
    links.new(heights[2], max23.inputs[0])
    links.new(heights[3], max23.inputs[1])

    max_all = nodes.new(type='ShaderNodeMath')
    max_all.operation = 'MAXIMUM'
    max_all.location = (-300, -475)
    max_all.label = "maxHeight"
    links.new(max01.outputs['Value'], max_all.inputs[0])
    links.new(max23.outputs['Value'], max_all.inputs[1])

    # --- Per-layer weight: saturate(h - maxH + half_blend) ----------------
    weights = []
    for i in range(4):
        y = 500 - i * 200

        sub = nodes.new(type='ShaderNodeMath')
        sub.operation = 'SUBTRACT'
        sub.location = (-100, y)
        sub.label = f"h{i}-max"
        links.new(heights[i], sub.inputs[0])
        links.new(max_all.outputs['Value'], sub.inputs[1])

        add = nodes.new(type='ShaderNodeMath')
        add.operation = 'ADD'
        add.location = (50, y)
        add.label = "+blend_area"
        links.new(sub.outputs['Value'], add.inputs[0])
        add.inputs[1].default_value = half_blend

        clamp = nodes.new(type='ShaderNodeClamp')
        clamp.location = (200, y)
        clamp.label = f"w{i}_raw"
        links.new(add.outputs['Value'], clamp.inputs['Value'])
        clamp.inputs['Min'].default_value = 0.0
        clamp.inputs['Max'].default_value = 1.0

        # Gate: saturate(height * 32) — kills truly-zero layers
        gate = nodes.new(type='ShaderNodeMath')
        gate.operation = 'MULTIPLY'
        gate.location = (200, y - 50)
        gate.label = f"h{i}*32"
        links.new(heights[i], gate.inputs[0])
        gate.inputs[1].default_value = 32.0

        gate_clamp = nodes.new(type='ShaderNodeClamp')
        gate_clamp.location = (350, y - 50)
        gate_clamp.label = f"gate{i}"
        links.new(gate.outputs['Value'], gate_clamp.inputs['Value'])
        gate_clamp.inputs['Min'].default_value = 0.0
        gate_clamp.inputs['Max'].default_value = 1.0

        # weight = raw_weight * gate
        w_mul = nodes.new(type='ShaderNodeMath')
        w_mul.operation = 'MULTIPLY'
        w_mul.location = (400, y)
        w_mul.label = f"w{i}"
        links.new(clamp.outputs['Result'], w_mul.inputs[0])
        links.new(gate_clamp.outputs['Result'], w_mul.inputs[1])

        weights.append(w_mul.outputs['Value'])

    # --- Sum weights for normalization ------------------------------------
    sum01 = nodes.new(type='ShaderNodeMath')
    sum01.operation = 'ADD'
    sum01.location = (550, 400)
    sum01.label = "w0+w1"
    links.new(weights[0], sum01.inputs[0])
    links.new(weights[1], sum01.inputs[1])

    sum23 = nodes.new(type='ShaderNodeMath')
    sum23.operation = 'ADD'
    sum23.location = (550, 200)
    sum23.label = "w2+w3"
    links.new(weights[2], sum23.inputs[0])
    links.new(weights[3], sum23.inputs[1])

    sum_all = nodes.new(type='ShaderNodeMath')
    sum_all.operation = 'ADD'
    sum_all.location = (700, 300)
    sum_all.label = "sumWeights"
    links.new(sum01.outputs['Value'], sum_all.inputs[0])
    links.new(sum23.outputs['Value'], sum_all.inputs[1])

    # --- Weighted colour per layer and accumulate -------------------------
    # Build: result = base*w0n + layer2*w1n + layer3*w2n + layer4*w3n
    # Using sequential MixRGB(MIX) with normalized weight as Fac:
    #   result = mix(previous, layer_i, w_i_normalized)
    # This is equivalent to a weighted sum when done from layer 0 upwards,
    # because mix(a, b, f) = a*(1-f) + b*f.  With properly normalized
    # weights the sequential mix chain produces the correct result only if we
    # accumulate in the right order.  A more robust approach: compute each
    # layer's colour * normalised weight and then ADD them.

    weighted_colors = []
    for i, (tex, lbl) in enumerate(zip(layer_texes, layer_labels)):
        y = 500 - i * 200

        # norm_w = w_i / sum_all
        div = nodes.new(type='ShaderNodeMath')
        div.operation = 'DIVIDE'
        div.location = (850, y)
        div.label = f"norm_w{i}"
        div.use_clamp = True
        links.new(weights[i], div.inputs[0])
        links.new(sum_all.outputs['Value'], div.inputs[1])

        # colour * norm_w  →  MixRGB(MIX) from black to layer colour
        # mix(black, color, fac) = color * fac
        mul = nodes.new(type='ShaderNodeMixRGB')
        mul.location = (1000, y)
        mul.label = f"{lbl}*w"
        mul.blend_type = 'MIX'
        mul.inputs['Color1'].default_value = (0, 0, 0, 1)
        if tex:
            links.new(tex.outputs['Color'], mul.inputs['Color2'])
        else:
            mul.inputs['Color2'].default_value = (0, 0, 0, 1)
        links.new(div.outputs['Value'], mul.inputs['Fac'])

        weighted_colors.append(mul.outputs['Color'])

    # --- Sum weighted colours: add(add(c0,c1), add(c2,c3)) ---------------
    add01 = nodes.new(type='ShaderNodeMixRGB')
    add01.location = (1150, 400)
    add01.label = "Sum 0+1"
    add01.blend_type = 'ADD'
    add01.inputs['Fac'].default_value = 1.0
    links.new(weighted_colors[0], add01.inputs['Color1'])
    links.new(weighted_colors[1], add01.inputs['Color2'])

    add23 = nodes.new(type='ShaderNodeMixRGB')
    add23.location = (1150, 200)
    add23.label = "Sum 2+3"
    add23.blend_type = 'ADD'
    add23.inputs['Fac'].default_value = 1.0
    links.new(weighted_colors[2], add23.inputs['Color1'])
    links.new(weighted_colors[3], add23.inputs['Color2'])

    add_final = nodes.new(type='ShaderNodeMixRGB')
    add_final.location = (1300, 300)
    add_final.label = "Final Blend"
    add_final.blend_type = 'ADD'
    add_final.inputs['Fac'].default_value = 1.0
    links.new(add01.outputs['Color'], add_final.inputs['Color1'])
    links.new(add23.outputs['Color'], add_final.inputs['Color2'])

    links.new(add_final.outputs['Color'], bsdf.inputs['Base Color'])


def _build_equal_blend_fallback(nodes, links, bsdf,
                                base_tex, layer2_tex, layer3_tex, layer4_tex):
    """Simple equal-weight blend of all available layers (fallback when no
    heightscale texture is available)."""
    available = [(tex, lbl) for tex, lbl in
                 zip([base_tex, layer2_tex, layer3_tex, layer4_tex],
                     ["Base", "Layer2", "Layer3", "Layer4"])
                 if tex is not None]
    if not available:
        return
    if len(available) == 1:
        links.new(available[0][0].outputs['Color'], bsdf.inputs['Base Color'])
        return

    # Sequential mix with equal weight per layer
    fac = 1.0 / len(available)
    prev = available[0][0].outputs['Color']
    for i, (tex, lbl) in enumerate(available[1:], 1):
        mix = nodes.new(type='ShaderNodeMixRGB')
        mix.location = (200 + i * 200, 300)
        mix.label = f"+{lbl}"
        mix.blend_type = 'MIX'
        mix.inputs['Fac'].default_value = fac * i  # Progressive blend
        links.new(prev, mix.inputs['Color1'])
        links.new(tex.outputs['Color'], mix.inputs['Color2'])
        prev = mix.outputs['Color']
    links.new(prev, bsdf.inputs['Base Color'])


def _build_blendmap_blend_nodes(nodes, links, bsdf, tex_lookup,
                                uv0_node, blend_tex, blend_tex_name,
                                base_tex, layer2_tex, layer3_tex, layer4_tex):
    """Standard blend-map blending (e.g. Summoner's Rift).

    Blend map RGB channels control layer mixing:
      R = blend factor for layer 2 over base
      G = blend factor for layer 3 over previous
      B = blend factor for layer 4 over previous
    """
    # UV1 for blend map sampling
    uv1_node = nodes.new(type='ShaderNodeUVMap')
    uv1_node.uv_map = "UV1_Blend"
    uv1_node.location = (-1400, -400)
    uv1_node.label = "UV1 (Blend)"
    if blend_tex:
        links.new(uv1_node.outputs['UV'], blend_tex.inputs['Vector'])
        blend_tex.interpolation = 'Closest'

    blend_color_output = blend_tex.outputs['Color'] if blend_tex else None

    if blend_color_output:
        sep = nodes.new(type='ShaderNodeSeparateColor')
        sep.location = (-600, -400)
        sep.label = "Blend Channels"
        links.new(blend_color_output, sep.inputs['Color'])

        # Mix: base <-(R)-> layer2
        mix1 = nodes.new(type='ShaderNodeMixRGB')
        mix1.location = (-50, 300)
        mix1.label = "Base + Layer2"
        mix1.blend_type = 'MIX'
        if base_tex:
            links.new(base_tex.outputs['Color'], mix1.inputs['Color1'])
        if layer2_tex:
            links.new(layer2_tex.outputs['Color'], mix1.inputs['Color2'])
        links.new(sep.outputs['Red'], mix1.inputs['Fac'])

        # Mix: result <-(G)-> layer3
        mix2 = nodes.new(type='ShaderNodeMixRGB')
        mix2.location = (100, 200)
        mix2.label = "+ Layer3"
        mix2.blend_type = 'MIX'
        links.new(mix1.outputs['Color'], mix2.inputs['Color1'])
        if layer3_tex:
            links.new(layer3_tex.outputs['Color'], mix2.inputs['Color2'])
        links.new(sep.outputs['Green'], mix2.inputs['Fac'])

        # Mix: result <-(B)-> layer4
        mix3 = nodes.new(type='ShaderNodeMixRGB')
        mix3.location = (250, 100)
        mix3.label = "+ Layer4"
        mix3.blend_type = 'MIX'
        links.new(mix2.outputs['Color'], mix3.inputs['Color1'])
        if layer4_tex:
            links.new(layer4_tex.outputs['Color'], mix3.inputs['Color2'])
        links.new(sep.outputs['Blue'], mix3.inputs['Fac'])

        links.new(mix3.outputs['Color'], bsdf.inputs['Base Color'])
    elif base_tex:
        links.new(base_tex.outputs['Color'], bsdf.inputs['Base Color'])


# ---------------------------------------------------------------------------
# terrain.inibin HeightBlending parser
# ---------------------------------------------------------------------------

# SDBM hashes for HeightBlending section properties
_HB_HASH_ENABLE       = 0x1db39e15  # HeightBlending*enable
_HB_HASH_LAYER0_SCALE = 0x18da747c  # HeightBlending*layer0_scale
_HB_HASH_LAYER1_SCALE = 0xef0562fd  # HeightBlending*layer1_scale (StringList)
_HB_HASH_LAYER2_SCALE = 0xc530517e  # HeightBlending*layer2_scale
_HB_HASH_LAYER3_SCALE = 0x9b5b3fff  # HeightBlending*layer3_scale


def _parse_height_blend_config(nvr_path: Path) -> HeightBlendConfig:
    """Build HeightBlendConfig from terrainHeightScale.dds and terrain.inibin.

    Searches for:
      - terrainHeightScale.dds (one level above scene/ and in scene/)
      - terrain.inibin (in scene/) for HeightBlending layer_scale constants
    """
    config = HeightBlendConfig()

    # --- Find terrainHeightScale.dds --------------------------------------
    for candidate in [
        nvr_path.parent.parent / "terrainHeightScale.dds",
        nvr_path.parent / "terrainHeightScale.dds",
    ]:
        if candidate.exists():
            config.heightscale_path = candidate
            print(f"[NVR] Found terrainHeightScale: {candidate}")
            break
    if not config.heightscale_path:
        print("[NVR] No terrainHeightScale.dds found (height blending unavailable)")

    # --- Parse terrain.inibin for HeightBlending scales -------------------
    inibin_path = nvr_path.parent / "terrain.inibin"
    if not inibin_path.exists():
        inibin_path = nvr_path.parent.parent / "terrain.inibin"
    if not inibin_path.exists():
        inibin_path = nvr_path.parent / "terrain.cfgbin"

    if inibin_path.exists():
        try:
            from . import cfgbin_reader
        except ImportError:
            try:
                import cfgbin_reader
            except ImportError:
                cfgbin_reader = None

        if cfgbin_reader:
            try:
                result = cfgbin_reader.parse_cfgbin(inibin_path)
                for _set_name, entries in result["sets"].items():
                    for hash_val, value in entries:
                        if hash_val == _HB_HASH_ENABLE:
                            config.enable = bool(value)
                        elif hash_val == _HB_HASH_LAYER0_SCALE:
                            config.layer0_scale = float(value)
                        elif hash_val == _HB_HASH_LAYER1_SCALE:
                            config.layer1_scale = float(value)
                        elif hash_val == _HB_HASH_LAYER2_SCALE:
                            config.layer2_scale = float(value)
                        elif hash_val == _HB_HASH_LAYER3_SCALE:
                            config.layer3_scale = float(value)

                print(f"[NVR] HeightBlending from {inibin_path.name}: "
                      f"enable={config.enable}, "
                      f"scales=[{config.layer0_scale:.4f}, {config.layer1_scale:.4f}, "
                      f"{config.layer2_scale:.4f}, {config.layer3_scale:.4f}]")
            except Exception as e:
                print(f"[NVR] Failed to parse {inibin_path.name}: {e}")
        else:
            print("[NVR] cfgbin_reader not available — cannot parse terrain.inibin")
    else:
        print("[NVR] No terrain.inibin found (using default layer scales)")

    return config


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

def import_nvr(filepath: str, collection_name: str = "Legacy_NVR") -> dict:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"NVR not found: {filepath}")

    tex_lookup = _build_texture_lookup(path)
    print(f"[NVR] Found {len(tex_lookup)} textures in Textures folder")

    # --- Build HeightBlendConfig from terrain assets ----------------------
    hb_config = _parse_height_blend_config(path)

    with path.open("rb") as f:
        magic = f.read(4)
        if magic != b"NVR\x00":
            raise ValueError("Invalid NVR magic")

        major, minor = struct.unpack("<HH", f.read(4))
        materials_count = _read_i32(f)
        vertex_buffer_count = _read_i32(f)
        index_buffer_count = _read_i32(f)
        mesh_count = _read_i32(f)
        _nodes_count = _read_i32(f)

        is_old = (major, minor) == (8, 1)

        print(f"[NVR] Version {major}.{minor} ({'old' if is_old else 'new'}) — "
              f"{materials_count} materials, {vertex_buffer_count} VBs, "
              f"{index_buffer_count} IBs, {mesh_count} meshes, {_nodes_count} nodes")

        materials = [
            _read_material_old(f) if is_old else _read_material_new(f)
            for _ in range(materials_count)
        ]

        vertex_buffers: list[bytes] = []
        for _ in range(vertex_buffer_count):
            size = _read_i32(f)
            vertex_buffers.append(f.read(size))

        index_buffers: list[tuple[int, bytes]] = []
        for _ in range(index_buffer_count):
            size = _read_i32(f)
            index_format = _read_i32(f)
            index_buffers.append((index_format, f.read(size)))

        meshes: list[NvrMesh] = []
        for _ in range(mesh_count):
            quality = _read_u32(f)
            flags = 0 if is_old else _read_u32(f)
            _ = f.read(16)  # sphere
            _ = f.read(24)  # box
            material_id = _read_i32(f)
            p0 = _read_primitive(f)
            p1 = _read_primitive(f)
            meshes.append(NvrMesh(quality=quality, flags=flags, material_id=material_id, primitives=[p0, p1]))

    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)

    # ------------------------------------------------------------------
    # Pass 1: decode all mesh primitives, group geometry by material_id
    # ------------------------------------------------------------------
    mat_buckets: dict[int, dict] = {}

    skipped = 0
    errors = 0
    decoded = 0
    skip_detail = {"mat_id": 0, "empty_prim": 0, "vb_id": 0, "ib_id": 0,
                    "vb_bounds": 0, "ib_bounds": 0, "no_faces": 0, "empty_idx": 0,
                    "blender_err": 0}

    for mesh_id, mesh in enumerate(meshes):
        if mesh.material_id < 0 or mesh.material_id >= len(materials):
            skipped += 1
            skip_detail["mat_id"] += 1
            continue
        nvr_mat = materials[mesh.material_id]
        has_uv1 = nvr_mat.mat_type == MAT_FOUR_BLEND

        primitive = mesh.primitives[0]
        if primitive.index_count <= 0 or primitive.vertex_count <= 0:
            skipped += 1
            skip_detail["empty_prim"] += 1
            continue

        if primitive.vertex_buffer_id < 0 or primitive.vertex_buffer_id >= len(vertex_buffers):
            skipped += 1
            skip_detail["vb_id"] += 1
            continue
        if primitive.index_buffer_id < 0 or primitive.index_buffer_id >= len(index_buffers):
            skipped += 1
            skip_detail["ib_id"] += 1
            continue

        vb = vertex_buffers[primitive.vertex_buffer_id]

        selected_verts = None
        selected_uvs0 = None
        selected_uvs1 = None
        selected_colors = None
        for stride in _candidate_strides_for_material(nvr_mat):
            start = primitive.start_vertex * stride
            end = start + primitive.vertex_count * stride
            if start < 0 or end > len(vb):
                continue
            verts_raw = vb[start:end]
            verts, u0, u1, cols = _decode_vertices(verts_raw, stride, has_uv1)
            if not verts:
                continue
            selected_verts = verts
            selected_uvs0 = u0
            selected_uvs1 = u1
            selected_colors = cols
            break

        if selected_verts is None:
            skipped += 1
            skip_detail["vb_bounds"] += 1
            continue

        idx_format, ib = index_buffers[primitive.index_buffer_id]
        all_indices = _decode_indices(ib, idx_format)
        i0 = primitive.start_index
        i1 = i0 + primitive.index_count
        if i0 < 0 or i1 > len(all_indices):
            skipped += 1
            skip_detail["ib_bounds"] += 1
            continue

        subset = list(all_indices[i0:i1])
        if not subset:
            skipped += 1
            skip_detail["empty_idx"] += 1
            continue

        min_idx = min(subset)
        subset = [int(i - min_idx) for i in subset]

        faces = []
        for i in range(0, len(subset) - 2, 3):
            a, b, c = subset[i], subset[i + 1], subset[i + 2]
            if a < len(selected_verts) and b < len(selected_verts) and c < len(selected_verts):
                # Reverse winding order: Y/Z swap changes handedness
                faces.append((a, c, b))

        if not faces:
            skipped += 1
            skip_detail["no_faces"] += 1
            continue

        if mesh.material_id not in mat_buckets:
            mat_buckets[mesh.material_id] = {
                "verts": [], "uvs0": [], "uvs1": [], "colors": [], "faces": []
            }

        bucket = mat_buckets[mesh.material_id]
        base_vert = len(bucket["verts"])
        bucket["verts"].extend(selected_verts)
        bucket["uvs0"].extend(selected_uvs0)
        bucket["uvs1"].extend(selected_uvs1)
        bucket["colors"].extend(selected_colors)
        bucket["faces"].extend((a + base_vert, b + base_vert, c + base_vert) for a, b, c in faces)
        decoded += 1

    # ------------------------------------------------------------------
    # Pass 2: create one Blender object per material bucket
    # ------------------------------------------------------------------
    imported = 0
    for mat_id, bucket in mat_buckets.items():
        nvr_mat = materials[mat_id]
        all_verts = bucket["verts"]
        all_uvs0 = bucket["uvs0"]
        all_uvs1 = bucket["uvs1"]
        all_colors = bucket["colors"]
        all_faces = bucket["faces"]

        if not all_faces:
            continue

        try:
            base_name = nvr_mat.name.strip() or f"Material_{mat_id}"
            me = bpy.data.meshes.new(f"NVR_{base_name}")
            me.from_pydata(all_verts, [], all_faces)
            me.update()

            # Pre-fetch loop→vertex mapping for bulk UV/color writes
            n_loops = len(me.loops)
            loop_vi = [0] * n_loops
            me.loops.foreach_get("vertex_index", loop_vi)
            uv0_count = len(all_uvs0)

            # UV0 — primary tile/diffuse UVs (bulk foreach_set)
            uv0_layer = me.uv_layers.new(name="UVMap")
            uv0_flat = [0.0] * (n_loops * 2)
            for i, vi in enumerate(loop_vi):
                if vi < uv0_count:
                    uv0_flat[i * 2] = all_uvs0[vi][0]
                    uv0_flat[i * 2 + 1] = all_uvs0[vi][1]
            uv0_layer.data.foreach_set("uv", uv0_flat)

            # UV1 — blend map UVs (FourBlend only)
            if all_uvs1:
                uv1_layer = me.uv_layers.new(name="UV1_Blend")
                uv1_count = len(all_uvs1)
                uv1_flat = [0.0] * (n_loops * 2)
                for i, vi in enumerate(loop_vi):
                    if vi < uv1_count:
                        uv1_flat[i * 2] = all_uvs1[vi][0]
                        uv1_flat[i * 2 + 1] = all_uvs1[vi][1]
                uv1_layer.data.foreach_set("uv", uv1_flat)

            # Vertex colors (bulk foreach_set)
            if all_colors:
                vcol = me.color_attributes.new(name="Color", type='BYTE_COLOR', domain='CORNER')
                color_count = len(all_colors)
                color_flat = [0.0] * (n_loops * 4)
                for i, vi in enumerate(loop_vi):
                    if vi < color_count:
                        c = all_colors[vi]
                        base = i * 4
                        color_flat[base] = c[0]
                        color_flat[base + 1] = c[1]
                        color_flat[base + 2] = c[2]
                        color_flat[base + 3] = c[3] if len(c) > 3 else 1.0
                vcol.data.foreach_set("color", color_flat)

            obj = bpy.data.objects.new(me.name, me)
            collection.objects.link(obj)

            bl_mat = _ensure_material(nvr_mat, tex_lookup, hb_config)
            if bl_mat:
                if not me.materials:
                    me.materials.append(bl_mat)
                else:
                    me.materials[0] = bl_mat

            obj["legacy_nvr"] = True
            obj["legacy_nvr_material_id"] = int(mat_id)
            obj["legacy_nvr_material_name"] = nvr_mat.name.strip()
            obj["legacy_nvr_material_type"] = nvr_mat.mat_type
            obj["legacy_nvr_material_type_name"] = {0: "Default", 1: "Decal", 2: "WallOfGrass", 3: "FourBlend", 4: "AntiBrush"}.get(nvr_mat.mat_type, f"Unknown({nvr_mat.mat_type})")
            obj["legacy_nvr_vertex_count"] = len(all_verts)
            obj["legacy_nvr_face_count"] = len(all_faces)
            obj["legacy_nvr_has_uv1"] = bool(all_uvs1)
            obj["legacy_nvr_has_vertex_colors"] = bool(all_colors)

            imported += 1
        except Exception as exc:
            errors += 1
            skip_detail["blender_err"] += 1
            if errors <= 5:
                print(f"[NVR] Material {mat_id} ({nvr_mat.name}) Blender error: {exc}")

    print(f"[NVR] Import complete: {decoded} mesh defs -> {imported} objects "
          f"({len(mat_buckets)} materials), {skipped} skipped, {errors} errors")
    print(f"[NVR] Skip detail: {skip_detail}")

    return {
        "materials": len(materials),
        "meshes": len(meshes),
        "decoded_meshes": decoded,
        "imported_objects": imported,
        "skipped": skipped,
        "errors": errors,
        "skip_detail": skip_detail,
    }
