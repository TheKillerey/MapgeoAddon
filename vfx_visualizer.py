"""
VFX Visualizer — Translates Riot's VfxSystemDefinitionData into Blender particle systems.

Architecture
------------
Riot's `.materials.bin` files store particle effects as `VfxSystemDefinitionData`
entries (type hash 0x45cd899f). Each entry contains a list of emitter definitions
(class hash 0x09cde442), each with full simulation parameters embedded inline:
emission rate, lifetime, mesh path, texture, color curves, scale curves, gravity,
velocity, etc. There is no external `.troybin` linkage.

This module decodes those embedded fields into Python dataclasses, then generates
Blender particle systems on proxy emitter objects so the user can preview each
VFX placement in the viewport using Blender's native particle renderer.

Pipeline
--------
1. Import particles via `import_particles_from_materials()` (existing). Each
   `VfxSystemDefinitionData` becomes an empty with a `vfx_fields_json` custom
   property containing the raw bin fields. Each `MapParticle` placement
   becomes an empty with `particle_system` linking to the VFX entry hash.
2. Call `visualize_particles()` on a set of MapParticle empties.
3. For each MapParticle: locate its linked VFX definition empty, decode its
   emitter list, and create one Blender particle system per emitter on the
   MapParticle empty (replacing it with a small icosphere proxy).

Field hashes are documented in `/memories/repo/vfx-system-fields.md`.
"""

import bpy
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Re-use the addon's existing texture resolution + .tex decoder
try:
    from .texture_utils import resolve_texture_path as _resolve_with_assets
    from .texture_utils import TexConverter
    _TEX_CONVERTER = TexConverter()
except Exception:
    _resolve_with_assets = None
    _TEX_CONVERTER = None

# ---------------------------------------------------------------------------
# Bin type constants (mirror propertybin_parser values)
# ---------------------------------------------------------------------------
TYPE_BOOL       = 1
TYPE_U8         = 3
TYPE_S16        = 4
TYPE_U16        = 5
TYPE_F32        = 10
TYPE_VEC2       = 11
TYPE_VEC3       = 12
TYPE_VEC4       = 13
TYPE_STRING     = 16
TYPE_HASH       = 17
TYPE_FILE       = 18
TYPE_CONTAINER  = 128
TYPE_STRUCT     = 130
TYPE_EMBEDDED   = 131
TYPE_LINK       = 132
TYPE_OPTIONAL   = 133
TYPE_MAP        = 134
TYPE_BITBOOL    = 135

# ---------------------------------------------------------------------------
# VFX field hashes
# ---------------------------------------------------------------------------

# Top-level VfxSystemDefinitionData fields
H_EMITTER_LIST          = "0x868eb76a"   # CONTAINER of emitter struct
H_VFX_SIM_DISTANCE      = "0xfd01a9d3"   # F32
H_VFX_SHORT_NAME        = "0xecf1c6bc"   # STRING
H_VFX_FULL_PATH         = "0xe7638138"   # STRING
H_VFX_FLAG              = "0x9c677a2c"   # U16

# Emitter struct (class 0x09cde442) field hashes
H_EM_NAME               = "0x3d25b8ce"   # STRING
H_EM_PROBABILITY        = "0xae839c67"   # struct(0x04300058) -> F32 0xb4b427aa
H_EM_LIFETIME           = "0x2a552694"   # struct(0x04300058) -> F32 (-1=infinite)
H_EM_RATE               = "0xca406316"   # struct(0x04300058) -> F32
H_EM_MESH_OUTER         = "0x007b14f6"   # struct(0x8594e839)
H_EM_MESH_INNER         = "0x0d89732d"   # struct(0x6a88780b) inside outer
H_EM_MESH_PATH          = "0xd467e8c0"   # STRING (path to .scb)
H_EM_BASE_COLOR         = "0x83cdeaa1"   # struct(0x074f91dd) -> VEC4
H_EM_COLOR_OVER_LIFE    = "0x3d7e6258"   # struct with curve
H_EM_TEXTURE_ALPHA      = "0x3c6468f4"   # STRING (.tex/.dds)
H_EM_TEXTURE_DIFFUSE    = "0x2f2e99f2"   # struct(0xb097c1bd) -> STRING (same hash inside!)
H_EM_RENDER_MODE        = "0xfa784eab"   # U8 (0=normal, 1, 2, 4=additive)
H_EM_RENDER_PRIORITY    = "0x7b7a7318"   # S16
H_EM_TYPE               = "0xb9516a6f"   # U8 (Simple=2, etc.)
H_EM_INITIAL_SCALE      = "0x5932ff9c"   # struct -> VEC3
H_EM_BASE_SCALE         = "0x8275da98"   # struct -> VEC3
H_EM_SCALE_OVER_LIFE    = "0xd4e17a53"   # struct with VEC3 curve
H_EM_VELOCITY           = "0xeb9a4e0f"   # struct -> VEC3
H_EM_VELOCITY_2         = "0xfa41ab8d"   # struct -> VEC3
H_EM_PARTICLE_SCALE     = "0xf0eb7084"   # struct -> VEC3
H_EM_VEC3_CURVED        = "0x1d779e6a"   # struct -> VEC3 with curve
H_EM_SPAWN_RADIUS       = "0xbfb0efdd"   # struct(0x1daa3fb0) -> F32 0x1f661402
H_EM_ENABLED            = "0x3c91cebd"   # BOOL
H_EM_FLAG_BIT_1         = "0x27d40903"   # BITBOOL
H_EM_FLAG_BIT_2         = "0x2ae335b2"   # BITBOOL
H_EM_FLAG_BIT_3         = "0x42bd7f6b"   # BITBOOL (single particle?)

# Generic struct field hashes
H_STRUCT_VALUE          = "0xb4b427aa"   # the actual base value inside struct wrappers
H_CURVE_BINDING         = "0xbc037de7"   # optional curve override on a struct

# Curve struct content
H_CURVE_TIME_KEYS       = "0x5d68eeb5"   # CONTAINER F32 (time keys 0..1)
H_CURVE_VALUE_KEYS      = "0x34474c3b"   # CONTAINER (value keys, type matches)
H_CURVE_SUB_CURVES      = "0xa7084719"   # CONTAINER of sub-curve structs

# Sub-curve component (class 0x53a6c97e)
H_SUB_CURVE_TIMES       = "0x40c351da"   # CONTAINER F32
H_SUB_CURVE_VALUES      = "0xe44b7382"   # CONTAINER F32

# Emitter class hash
EMITTER_CLASS_HASH      = "0x09cde442"

# VfxSystemDefinitionData type hash
VFX_DEF_TYPE_HASH       = "0x45cd899f"


# ===========================================================================
# Field accessor helpers
# ===========================================================================

def _get_field(fields, name_hash):
    """Return the field dict whose name_hash matches, or None."""
    if not fields:
        return None
    target = name_hash.lower()
    for f in fields:
        if isinstance(f, dict) and f.get("name_hash", "").lower() == target:
            return f
    return None


def _get_value(fields, name_hash, default=None):
    """Return f['value'] for a named field, or default."""
    f = _get_field(fields, name_hash)
    if f is None:
        return default
    return f.get("value", default)


def _unwrap_struct_value(field_dict, default=None):
    """A common pattern: emitter scalars are wrapped in struct(0x04300058) with
    a single F32 field 0xb4b427aa. This helper returns that inner value.

    Also handles direct scalar fields (returns their value directly).
    """
    if field_dict is None:
        return default
    # Direct scalar
    val = field_dict.get("value")
    if val is not None and "fields" not in field_dict:
        return val
    # Struct wrapper — look for 0xb4b427aa inside
    inner = _get_field(field_dict.get("fields", []), H_STRUCT_VALUE)
    if inner is not None:
        return inner.get("value", default)
    return default


def _unwrap_mesh_path(field_dict):
    """Walk: outer struct → 0x0d89732d → inner struct → 0xd467e8c0 STRING."""
    if field_dict is None:
        return ""
    inner_wrap = _get_field(field_dict.get("fields", []), H_EM_MESH_INNER)
    if inner_wrap is None:
        return ""
    path_field = _get_field(inner_wrap.get("fields", []), H_EM_MESH_PATH)
    if path_field is None:
        return ""
    return path_field.get("value", "") or ""


def _unwrap_texture_struct(field_dict):
    """Diffuse texture struct uses the same hash inside: 0x2f2e99f2."""
    if field_dict is None:
        return ""
    inner = _get_field(field_dict.get("fields", []), H_EM_TEXTURE_DIFFUSE)
    if inner is None:
        return ""
    return inner.get("value", "") or ""


def _unwrap_spawn_radius(field_dict):
    """Spawn radius struct(0x1daa3fb0) holds F32 0x1f661402."""
    if field_dict is None:
        return None
    rf = _get_field(field_dict.get("fields", []), "0x1f661402")
    if rf is not None:
        return rf.get("value")
    return None


# ===========================================================================
# Data model
# ===========================================================================

@dataclass
class EmitterDefinition:
    name: str = ""
    probability: float = 1.0
    lifetime: float = 1.0          # particle lifetime in seconds (-1 = infinite/long)
    rate: float = 10.0             # particles per second
    mesh_path: str = ""            # .scb mesh asset path
    texture_alpha: str = ""        # alpha texture path
    texture_diffuse: str = ""      # diffuse texture path
    base_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    initial_scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    base_scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    spawn_radius: float = 0.0
    render_mode: int = 0           # 0=normal, 4=additive
    render_priority: int = 0
    emitter_type: int = 2          # 2=Simple
    enabled: bool = True


@dataclass
class VfxDefinition:
    name: str = ""
    short_name: str = ""
    full_path: str = ""
    sim_distance: float = 1000.0
    emitters: List[EmitterDefinition] = field(default_factory=list)


# ===========================================================================
# Decoder
# ===========================================================================

def decode_emitter(emitter_struct: dict) -> EmitterDefinition:
    """Decode a single emitter struct into an EmitterDefinition."""
    em = EmitterDefinition()
    fields = emitter_struct.get("fields", []) or []

    em.name = _get_value(fields, H_EM_NAME, "") or ""

    em.probability = float(_unwrap_struct_value(_get_field(fields, H_EM_PROBABILITY), 1.0) or 1.0)
    em.lifetime    = float(_unwrap_struct_value(_get_field(fields, H_EM_LIFETIME), 1.0) or 1.0)
    em.rate        = float(_unwrap_struct_value(_get_field(fields, H_EM_RATE), 10.0) or 10.0)

    color_val = _unwrap_struct_value(_get_field(fields, H_EM_BASE_COLOR), None)
    if isinstance(color_val, (list, tuple)) and len(color_val) >= 4:
        em.base_color = (float(color_val[0]), float(color_val[1]),
                         float(color_val[2]), float(color_val[3]))
    elif isinstance(color_val, (list, tuple)) and len(color_val) == 3:
        em.base_color = (float(color_val[0]), float(color_val[1]),
                         float(color_val[2]), 1.0)

    for hash_key, attr in (
        (H_EM_INITIAL_SCALE, "initial_scale"),
        (H_EM_BASE_SCALE,    "base_scale"),
        (H_EM_PARTICLE_SCALE, "base_scale"),  # fallback
        (H_EM_VELOCITY,      "velocity"),
        (H_EM_VELOCITY_2,    "velocity"),
    ):
        v = _unwrap_struct_value(_get_field(fields, hash_key), None)
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            setattr(em, attr, (float(v[0]), float(v[1]), float(v[2])))

    em.mesh_path        = _unwrap_mesh_path(_get_field(fields, H_EM_MESH_OUTER))
    em.texture_alpha    = _get_value(fields, H_EM_TEXTURE_ALPHA, "") or ""
    em.texture_diffuse  = _unwrap_texture_struct(_get_field(fields, H_EM_TEXTURE_DIFFUSE))

    radius_val = _unwrap_spawn_radius(_get_field(fields, H_EM_SPAWN_RADIUS))
    if radius_val is not None:
        em.spawn_radius = float(radius_val)

    em.render_mode      = int(_get_value(fields, H_EM_RENDER_MODE, 0) or 0)
    em.render_priority  = int(_get_value(fields, H_EM_RENDER_PRIORITY, 0) or 0)
    em.emitter_type     = int(_get_value(fields, H_EM_TYPE, 2) or 2)
    em.enabled          = bool(_get_value(fields, H_EM_ENABLED, True))

    return em


def decode_vfx_definition(vfx_fields: list, vfx_name: str = "") -> VfxDefinition:
    """Decode a top-level VfxSystemDefinitionData fields array."""
    vfx = VfxDefinition()
    vfx.name        = vfx_name
    vfx.short_name  = _get_value(vfx_fields, H_VFX_SHORT_NAME, "") or ""
    vfx.full_path   = _get_value(vfx_fields, H_VFX_FULL_PATH, "") or ""
    vfx.sim_distance = float(_get_value(vfx_fields, H_VFX_SIM_DISTANCE, 1000.0) or 1000.0)

    emitter_field = _get_field(vfx_fields, H_EMITTER_LIST)
    if emitter_field is None:
        return vfx

    for em_struct in emitter_field.get("values", []) or []:
        if not isinstance(em_struct, dict):
            continue
        # Only decode emitter-class structs
        cls = em_struct.get("class_hash", "").lower()
        if cls and cls != EMITTER_CLASS_HASH:
            # Unknown emitter sub-class — skip but record name if present
            continue
        try:
            em = decode_emitter(em_struct)
            vfx.emitters.append(em)
        except Exception as e:
            print(f"[VFX Visualizer] Failed to decode emitter in {vfx_name}: {e}")

    return vfx


def decode_vfx_from_object(vfx_obj: bpy.types.Object) -> Optional[VfxDefinition]:
    """Decode a VfxDefinition empty (created during particle import) using its
    cached `vfx_fields_json` custom property.
    """
    if vfx_obj is None:
        return None
    fields_json = vfx_obj.get("vfx_fields_json", "")
    if not fields_json:
        return None
    try:
        fields = json.loads(fields_json)
    except Exception:
        return None
    name = vfx_obj.get("vfx_name", vfx_obj.name) or vfx_obj.name
    return decode_vfx_definition(fields, name)


# ===========================================================================
# Riot → Blender mapping
# ===========================================================================

# League world units are roughly 1 cm. Keep particle scale in League units;
# the user's scene is already imported at that scale.

# Render mode → Blender material blend
RENDER_MODE_TO_BLEND = {
    0: 'BLEND',     # normal alpha
    1: 'CLIP',
    2: 'BLEND',
    3: 'BLEND',
    4: 'BLEND',     # additive — handled via shader graph
}


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
# League maps are imported in centimetres (1 BU = 1 cm). Riot scale values
# are roughly direct world-unit multipliers; brazier-fire flames are ~1-3 BU,
# small ground glows ~10 BU, large environmental effects ~50 BU.
PARTICLE_SIZE_FUDGE     = 0.5     # base particle size multiplier (Riot scale is in BU already)
VELOCITY_FUDGE          = 1.0     # initial velocity multiplier (Riot units ≈ BU/s)
DEFAULT_SPAWN_RADIUS    = 2.0     # BU, used when spawn_radius == 0
RENDER_PLANE_BASE       = 1.0     # BU, instance plane size (multiplied by particle_size)
# Default soft-rise velocity is now zero — we let the emitter velocity
# field decide. Position-locked fires (brazier) have velocity=(0,0,0) and
# should hold their position, only drifting upward via a small bias.
DEFAULT_RISE_VELOCITY   = 0.0     # BU/s upward when velocity is zero
DEFAULT_NORMAL_VELOCITY = 0.0     # BU/s outward jitter
FIRE_RISE_BIAS          = 25.0    # gentle upward drift for static emitters
FIRE_RISE_RANDOM        = 6.0     # small randomness on the rise


def _build_proxy_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    """Get or create the collection that holds visual particle proxies."""
    name = "_VFX_Visual"
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
        coll.hide_render = True
    return coll


def _ensure_render_collection() -> bpy.types.Collection:
    """Hidden collection that holds the per-emitter render proxy meshes
    (the objects the particle system instances)."""
    cname = "_VFX_RenderObjects"
    coll = bpy.data.collections.get(cname)
    if coll is None:
        coll = bpy.data.collections.new(cname)
        bpy.context.scene.collection.children.link(coll)
        coll.hide_viewport = True
        coll.hide_render = True
    return coll


def _create_billboard_plane_mesh(name: str) -> bpy.types.Mesh:
    """Create a UV sphere for volumetric particle rendering.
    Uses spherical UVs so textures wrap around the surface naturally.
    """
    import math
    mesh = bpy.data.meshes.get(name)
    if mesh is not None:
        return mesh

    r = RENDER_PLANE_BASE * 0.5
    segments = 16   # longitude
    rings = 8       # latitude (excluding poles)

    verts = []
    faces = []

    # Top pole
    verts.append((0.0, 0.0, r))
    # Rings from top to bottom
    for ring in range(1, rings + 1):
        phi = math.pi * ring / (rings + 1)
        sp, cp = math.sin(phi), math.cos(phi)
        for seg in range(segments):
            theta = 2.0 * math.pi * seg / segments
            verts.append((r * sp * math.cos(theta),
                          r * sp * math.sin(theta),
                          r * cp))
    # Bottom pole
    verts.append((0.0, 0.0, -r))

    top_pole = 0
    bot_pole = len(verts) - 1

    # Top cap triangles
    for seg in range(segments):
        s_next = (seg + 1) % segments
        faces.append((top_pole, 1 + seg, 1 + s_next))
    # Middle quad strips → two tris each
    for ring in range(rings - 1):
        base = 1 + ring * segments
        for seg in range(segments):
            s_next = (seg + 1) % segments
            a = base + seg
            b = base + s_next
            c = base + segments + s_next
            d = base + segments + seg
            faces.append((a, b, c))
            faces.append((a, c, d))
    # Bottom cap triangles
    base = 1 + (rings - 1) * segments
    for seg in range(segments):
        s_next = (seg + 1) % segments
        faces.append((base + seg, bot_pole, base + s_next))

    mesh.from_pydata(verts, [], faces)
    mesh.uv_layers.new(name="UVMap")
    uv = mesh.uv_layers.active.data

    # Spherical projection UVs
    loop_idx = 0
    def _sphere_uv(vi):
        x, y, z = verts[vi]
        u = 0.5 + math.atan2(y, x) / (2.0 * math.pi)
        v = 0.5 + math.asin(max(-1.0, min(1.0, z / r))) / math.pi if r > 0 else 0.5
        return (u, v)

    for face in faces:
        for vi in face:
            uv[loop_idx].uv = _sphere_uv(vi)
            loop_idx += 1

    mesh.update()
    return mesh


def _ensure_render_object(emitter: "EmitterDefinition",
                          material: bpy.types.Material) -> bpy.types.Object:
    """Return the per-emitter render-instance object (a billboard plane).

    One render object is shared by all particle systems that use the same
    emitter name + material.
    """
    safe = re.sub(r'[^A-Za-z0-9_]+', '_', emitter.name) or "Emitter"
    obj_name = f"VFX_Render_{safe}"
    existing = bpy.data.objects.get(obj_name)
    if existing is not None:
        # Refresh material in case it was updated
        if existing.data.materials:
            existing.data.materials[0] = material
        else:
            existing.data.materials.append(material)
        return existing

    mesh = _create_billboard_plane_mesh(f"VFX_PlaneMesh_{safe}")
    obj = bpy.data.objects.new(obj_name, mesh)
    obj.data.materials.append(material)
    obj.hide_render = False
    obj.hide_select = True
    # Crucial: instances inherit the source object's display_type. Force
    # textured shading so particle billboards don't draw their wireframe
    # outline in the viewport (which made the cross-plane edges visible
    # as orange squares around each flame).
    obj.display_type = 'TEXTURED'
    obj.show_wire = False
    obj.show_all_edges = False
    obj.show_in_front = False

    coll = _ensure_render_collection()
    coll.objects.link(obj)
    return obj


def _create_emitter_proxy(name: str, location, rotation,
                          spawn_radius: float) -> bpy.types.Object:
    """Create a UV-sphere mesh sized to the emitter's spawn radius. The
    particle system attaches to this object and emits from its volume.
    """
    radius = max(spawn_radius, DEFAULT_SPAWN_RADIUS)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                         radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.rotation_euler = rotation
    obj.display_type = 'WIRE'
    obj.hide_render = True
    obj.show_in_front = False
    return obj


# ---------------------------------------------------------------------------
# Material builder
# ---------------------------------------------------------------------------

def _image_has_alpha(img: bpy.types.Image) -> bool:
    """Return True if the image has a meaningful alpha channel.
    Some particle textures store the shape as bright-on-black RGB with no
    alpha (alpha = 1.0 everywhere).  We sample ~200 evenly-spaced pixels;
    if any alpha value is below 0.99, the alpha channel carries real data.
    """
    if img is None or img.channels < 4:
        return False
    try:
        px = img.pixels[:]          # flat RGBA float list, fast C copy
    except Exception:
        return False
    total = len(px) // 4            # number of pixels
    step = max(1, total // 200)     # sample ~200 pixels
    for i in range(3, len(px), 4 * step):
        if px[i] < 0.99:
            return True
    return False


def _build_particle_material(emitter: EmitterDefinition,
                             assets_folder: str = "",
                             custom_assets_folder: str = "",
                             prioritize_custom: bool = False) -> bpy.types.Material:
    """Build a per-emitter material:

    - Texture (if resolvable) drives Color and Alpha.
    - Color is multiplied by the emitter's base_color (tint).
    - For ADDITIVE render modes, an Emission shader is mixed via Transparent
      BSDF using the alpha so particles glow without occluding.
    - For NORMAL render modes, a Principled BSDF with Alpha is used.
    - Transparent shadows are enabled so EEVEE/Cycles render correctly.
    """
    safe_name = re.sub(r'[^A-Za-z0-9_]+', '_', emitter.name) or "Emitter"
    mat_name = f"VFX_{safe_name}_M"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

    nt = mat.node_tree
    nt.nodes.clear()

    r, g, b, a = emitter.base_color
    # Riot render-mode meanings (best-known mapping):
    #   0 = normal alpha-blend (e.g. ash sprites with proper alpha)
    #   1 = additive (most fire/glow particles)
    #   2 = soft-additive
    #   3 = additive
    #   4 = additive (alternate)
    additive = emitter.render_mode in (1, 2, 3, 4)

    # ---- Load up to TWO textures ----
    # Riot fire emitters typically reference both:
    #   diffuse  (color/multiply)  e.g. "Env_MB_brazierFire_mult.tex"
    #   alpha    (shape mask)      e.g. "SRU_Brazier_Flame_Temp_01.tex"
    # The final color is `diffuse.rgb * alpha.rgb` (or just one if missing).
    img_diffuse = None
    img_alpha = None
    if emitter.texture_diffuse:
        img_diffuse = _load_particle_image(
            emitter.texture_diffuse, assets_folder, custom_assets_folder, prioritize_custom
        )
        if img_diffuse:
            try: img_diffuse.alpha_mode = 'CHANNEL_PACKED'
            except Exception: pass
            print(f"[VFX Visualizer] '{emitter.name}' diffuse: {img_diffuse.name}")
        else:
            print(f"[VFX Visualizer] '{emitter.name}' diffuse missing: {emitter.texture_diffuse}")
    if emitter.texture_alpha:
        img_alpha = _load_particle_image(
            emitter.texture_alpha, assets_folder, custom_assets_folder, prioritize_custom
        )
        if img_alpha:
            try: img_alpha.alpha_mode = 'STRAIGHT'
            except Exception: pass
            print(f"[VFX Visualizer] '{emitter.name}' alpha: {img_alpha.name}")
        else:
            print(f"[VFX Visualizer] '{emitter.name}' alpha missing: {emitter.texture_alpha}")

    n_out = nt.nodes.new("ShaderNodeOutputMaterial");  n_out.location = (900, 0)

    # ---- Texture image nodes ----
    n_diff = None
    n_alph = None
    if img_diffuse is not None:
        n_diff = nt.nodes.new("ShaderNodeTexImage");  n_diff.image = img_diffuse
        n_diff.location = (-900, 200);  n_diff.label = "Diffuse/Color"
    if img_alpha is not None:
        n_alph = nt.nodes.new("ShaderNodeTexImage");  n_alph.image = img_alpha
        n_alph.location = (-900, -200); n_alph.label = "Alpha/Shape"

    # ---- Color pipeline ----
    # Riot fire: diffuse.rgb × alpha.rgb (multiply texture by shape),
    # then tint by base_color.
    if n_diff is not None and n_alph is not None:
        n_combine = nt.nodes.new("ShaderNodeMix")
        n_combine.data_type = 'RGBA'
        n_combine.blend_type = 'MULTIPLY'
        n_combine.location = (-500, 100)
        n_combine.inputs["Factor"].default_value = 1.0
        nt.links.new(n_diff.outputs["Color"], n_combine.inputs[6])
        nt.links.new(n_alph.outputs["Color"], n_combine.inputs[7])
        color_socket = n_combine.outputs[2]
    elif n_diff is not None:
        color_socket = n_diff.outputs["Color"]
    elif n_alph is not None:
        color_socket = n_alph.outputs["Color"]
    else:
        color_socket = None

    # Tint by base_color
    n_tint = nt.nodes.new("ShaderNodeMix")
    n_tint.data_type = 'RGBA'
    n_tint.blend_type = 'MULTIPLY'
    n_tint.location = (-200, 100)
    n_tint.inputs["Factor"].default_value = 1.0
    n_tint.inputs[7].default_value = (r, g, b, 1.0)
    if color_socket is not None:
        nt.links.new(color_socket, n_tint.inputs[6])
    else:
        n_tint.inputs[6].default_value = (1.0, 1.0, 1.0, 1.0)
    final_color_socket = n_tint.outputs[2]

    # ---- Alpha / mask pipeline ----
    # Some textures have a proper alpha channel (feathered mask).
    # Others have NO alpha (all 1.0) with the shape baked into RGB
    # brightness (bright = visible, black = background).
    # We detect this at load time and fall back to RGB luminance.
    diff_has_alpha = _image_has_alpha(img_diffuse)
    alph_has_alpha = _image_has_alpha(img_alpha)

    def _alpha_from_node(tex_node, has_alpha):
        """Return the best alpha socket for a texture node.
        If the image has real alpha data, use the Alpha output directly.
        Otherwise derive alpha from RGB luminance (bright = opaque)."""
        if has_alpha:
            return tex_node.outputs["Alpha"]
        # RGB → luminance as alpha
        n_bw = nt.nodes.new("ShaderNodeRGBToBW")
        n_bw.location = (tex_node.location.x + 300, tex_node.location.y - 150)
        n_bw.label = f"Luminance→Alpha"
        nt.links.new(tex_node.outputs["Color"], n_bw.inputs["Color"])
        print(f"[VFX Visualizer] '{emitter.name}' — no alpha channel in "
              f"{tex_node.image.name}, using RGB luminance as mask")
        return n_bw.outputs["Val"]

    alpha_socket = None
    if n_alph is not None and n_diff is not None:
        a_alph = _alpha_from_node(n_alph, alph_has_alpha)
        a_diff = _alpha_from_node(n_diff, diff_has_alpha)
        n_mul_a = nt.nodes.new("ShaderNodeMath")
        n_mul_a.operation = 'MULTIPLY'
        n_mul_a.location = (-200, -300)
        nt.links.new(a_alph, n_mul_a.inputs[0])
        nt.links.new(a_diff, n_mul_a.inputs[1])
        alpha_socket = n_mul_a.outputs["Value"]
    elif n_alph is not None:
        alpha_socket = _alpha_from_node(n_alph, alph_has_alpha)
    elif n_diff is not None:
        alpha_socket = _alpha_from_node(n_diff, diff_has_alpha)

    # ---- Surface shader ----
    if additive:
        # Additive fire/glow: Transparent BSDF + Emission mixed by alpha.
        # The Transparent BSDF lets background show through; Emission adds
        # light on top.  This is order-independent (A+B = B+A), so no
        # depth-write artefacts with overlapping particles.
        n_emit  = nt.nodes.new("ShaderNodeEmission");       n_emit.location  = (300,  150)
        n_trans = nt.nodes.new("ShaderNodeBsdfTransparent"); n_trans.location = (300, -100)
        n_mix   = nt.nodes.new("ShaderNodeMixShader");      n_mix.location   = (550,   0)

        n_emit.inputs["Strength"].default_value = 2.5
        nt.links.new(final_color_socket, n_emit.inputs["Color"])
        if alpha_socket is not None:
            nt.links.new(alpha_socket, n_mix.inputs["Fac"])
        else:
            n_mix.inputs["Fac"].default_value = a
        nt.links.new(n_trans.outputs["BSDF"],     n_mix.inputs[1])
        nt.links.new(n_emit.outputs["Emission"],  n_mix.inputs[2])
        nt.links.new(n_mix.outputs["Shader"],     n_out.inputs["Surface"])
    else:
        # Normal alpha-blend (smoke, ash, dust).
        n_bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); n_bsdf.location = (300, 0)
        nt.links.new(final_color_socket, n_bsdf.inputs["Base Color"])
        if alpha_socket is not None and "Alpha" in n_bsdf.inputs:
            nt.links.new(alpha_socket, n_bsdf.inputs["Alpha"])
        elif "Alpha" in n_bsdf.inputs:
            n_bsdf.inputs["Alpha"].default_value = a
        # Self-illumination so particles aren't pitch-black in shadows
        if "Emission Color" in n_bsdf.inputs:
            nt.links.new(final_color_socket, n_bsdf.inputs["Emission Color"])
        if "Emission Strength" in n_bsdf.inputs:
            n_bsdf.inputs["Emission Strength"].default_value = 0.5
        if "Specular IOR Level" in n_bsdf.inputs:
            n_bsdf.inputs["Specular IOR Level"].default_value = 0.0
        if "Roughness" in n_bsdf.inputs:
            n_bsdf.inputs["Roughness"].default_value = 1.0
        nt.links.new(n_bsdf.outputs["BSDF"], n_out.inputs["Surface"])

    # ---- Render-engine settings ----
    # Additive (Transparent + Emission) is order-independent, so BLENDED
    # works perfectly — no depth-write artefacts, no dithering noise.
    # Normal alpha-blend (Principled) needs DITHERED so overlapping
    # semi-transparent planes don't depth-reject each other.
    try:
        mat.surface_render_method = 'BLENDED' if additive else 'DITHERED'
    except Exception:
        pass
    try:
        mat.show_transparent_back = True   # both faces of cross-plane visible
    except Exception:
        pass
    try:
        mat.use_backface_culling = False
    except Exception:
        pass
    # No shadows from particle billboards
    try:
        mat.shadow_method = 'NONE'
    except Exception:
        pass
    try:
        mat.use_shadows = False
    except Exception:
        pass

    return mat


def _load_particle_image(asset_path: str, assets_folder: str,
                         custom_assets_folder: str = "",
                         prioritize_custom: bool = False) -> Optional[bpy.types.Image]:
    """Resolve a Riot texture path (e.g. "ASSETS/Maps/Particles/.../foo.dds")
    to an actual file via the addon's `texture_utils.resolve_texture_path`,
    then load it as a `bpy.types.Image`.

    Handles `.tex` files via the `TexConverter` (decodes to DDS in-memory).
    Returns None if the file cannot be located on disk.
    """
    if not asset_path:
        return None
    if _resolve_with_assets is None:
        return None

    resolved = _resolve_with_assets(
        asset_path,
        assets_folder or "",
        custom_assets_folder or "",
        prioritize_custom,
    )
    if not resolved or not os.path.isfile(resolved):
        return None

    # .tex needs decoding to DDS first
    if resolved.lower().endswith(".tex") and _TEX_CONVERTER is not None:
        try:
            return _TEX_CONVERTER.load_tex_as_blender_image(
                resolved,
                image_name=os.path.basename(resolved),
                defer_packing=False,
            )
        except Exception as e:
            print(f"[VFX Visualizer] .tex decode failed for {resolved}: {e}")
            return None

    # .dds / .png / .tga — Blender loads natively
    try:
        return bpy.data.images.load(resolved, check_existing=True)
    except Exception as e:
        print(f"[VFX Visualizer] Image load failed for {resolved}: {e}")
        return None


def _resolve_texture_path(asset_path: str, texture_root: str) -> Optional[str]:
    """Legacy single-folder resolver kept for callers that don't have access
    to the addon settings. Prefer `_load_particle_image` when possible.
    """
    if not asset_path or not texture_root:
        return None
    p = os.path.join(texture_root, asset_path.lstrip("/").lstrip("\\"))
    if os.path.isfile(p):
        return p
    p_low = os.path.join(texture_root, asset_path.lower().lstrip("/").lstrip("\\"))
    if os.path.isfile(p_low):
        return p_low
    base, _ = os.path.splitext(p)
    for ext in (".dds", ".png", ".tga", ".tex"):
        if os.path.isfile(base + ext):
            return base + ext
    return None


# ===========================================================================
# Particle system construction
# ===========================================================================

def _scene_fps(scene: bpy.types.Scene) -> float:
    fps = scene.render.fps / scene.render.fps_base if scene.render.fps_base else scene.render.fps
    if fps <= 0:
        fps = 24.0
    return float(fps)


def _frame_count_for_lifetime(scene: bpy.types.Scene, lifetime_seconds: float) -> int:
    return max(1, int(lifetime_seconds * _scene_fps(scene)))


def _apply_emitter_to_psys(psys: bpy.types.ParticleSystem,
                           emitter: EmitterDefinition,
                           render_obj: bpy.types.Object,
                           scene: bpy.types.Scene):
    """Push decoded VFX values onto a Blender ParticleSettings.

    Continuous-emission strategy:
      - emission spans the entire scene timeline ([frame_start, frame_end])
      - count = rate (per second) * timeline_seconds (capped to 50000)
      - particle lifetime = emitter.lifetime (clamped); -1 → 5 s
      - small lifetime randomisation breaks up uniform appearance
    """
    s = psys.settings
    fps = _scene_fps(scene)

    # ---- Lifetime ----
    life_secs = emitter.lifetime if emitter.lifetime > 0 else 5.0
    life_secs = max(0.25, min(life_secs, 30.0))
    s.lifetime = _frame_count_for_lifetime(scene, life_secs)
    s.lifetime_random = 0.15

    # ---- Emission window — full timeline for continuous loop ----
    s.frame_start = float(scene.frame_start)
    s.frame_end = float(max(scene.frame_start + 1, scene.frame_end))
    timeline_secs = (s.frame_end - s.frame_start) / fps

    # ---- Count: continuous emission ----
    # Empirically, Riot's `0xae839c67` (which we labelled "probability")
    # is actually the per-second emission count for the bulk of static
    # particles (e.g. brazier fire prob=20 → 20/sec). The field
    # `0xca406316` is constant 10.0 for those same emitters — likely a
    # default scalar of some other purpose. Use probability as the
    # effective rate when it's > 1, otherwise fall back to `rate * prob`.
    if emitter.probability > 1.0:
        per_second = emitter.probability
    elif emitter.probability > 0.0:
        per_second = max(0.05, emitter.rate * emitter.probability)
    else:
        per_second = emitter.rate
    per_second = max(0.05, min(per_second, 500.0))
    raw_count = int(per_second * timeline_secs)
    s.count = max(1, min(raw_count, 50000))

    # ---- Emission shape — sphere VOLUME (proxy mesh is a UV sphere) ----
    s.emit_from = 'VOLUME'
    s.distribution = 'RAND'
    s.use_emit_random = True

    # ---- Initial velocity ----
    # CRITICAL coordinate swap: Riot's particle editor is Y-up, Blender is
    # Z-up. The mapgeo importer rotates the world geometry to match Blender,
    # but the raw VFX vectors here are still in Riot space. We swap Y↔Z so
    # that, e.g., the brazier sparks emitter `(0, 250, 0)` (Riot "up")
    # becomes `(0, 0, 250)` (Blender "up").
    rx, ry, rz = emitter.velocity
    vx, vy, vz = rx, rz, ry      # Y-up → Z-up
    speed = math.sqrt(vx * vx + vy * vy + vz * vz)
    if speed > 1e-3:
        # Directional motion straight from the VFX data.
        s.object_align_factor = (vx * VELOCITY_FUDGE,
                                 vy * VELOCITY_FUDGE,
                                 vz * VELOCITY_FUDGE)
        s.normal_factor = 0.0
        s.factor_random = speed * VELOCITY_FUDGE * 0.10
    else:
        # Static emitter (most braziers, glows). Particles get a gentle
        # upward bias and almost zero outward spread so they look like a
        # localised flame instead of an explosion.
        s.object_align_factor = (0.0, 0.0, FIRE_RISE_BIAS)
        s.normal_factor = 0.0
        s.factor_random = FIRE_RISE_RANDOM

    # ---- Particle size ----
    # Take the largest base / initial scale component. If the emitter
    # provides only the default (1,1,1), this still gives a reasonable size.
    sx, sy, sz = emitter.base_scale
    ix, iy, iz = emitter.initial_scale
    base_size = max(abs(sx), abs(sy), abs(sz),
                    abs(ix), abs(iy), abs(iz))
    if base_size <= 1e-6:
        base_size = 1.0
    s.particle_size = base_size * PARTICLE_SIZE_FUDGE
    s.size_random = 0.4    # nice variety for fire/smoke

    # ---- Render: instance the billboard plane ----
    s.render_type = 'OBJECT'
    s.instance_object = render_obj
    s.use_rotation_instance = True
    s.use_scale_instance = True
    s.show_unborn = False
    s.use_dead = False
    # NOTE: `use_render_emitter` moved off ParticleSettings in newer Blender.
    # Hiding the wire-sphere instancer is done at the Object level in
    # `visualize_map_particle()` via `show_instancer_for_*`.

    # ---- Rotation: a small fixed random orientation per particle so the
    #      cross-plane proxies don't all align identically. No spin —
    #      Riot fire/smoke billboards stay still relative to the camera. ----
    try:
        s.use_rotations = True
        s.rotation_mode = 'GLOB_X'
        s.rotation_factor_random = 0.3
        s.use_dynamic_rotation = False
        s.angular_velocity_mode = 'NONE'
        s.angular_velocity_factor = 0.0
    except Exception:
        pass

    # ---- Physics: simple Newtonian, no scene gravity, no drag ----
    s.physics_type = 'NEWTON'
    s.mass = 1.0
    try:
        s.brownian_factor = 0.0
        s.drag_factor = 0.0
        s.damping = 0.0
    except Exception:
        pass
    s.effector_weights.gravity = 0.0    # League VFX don't fall under scene gravity

    # ---- Display ----
    try:
        s.display_method = 'RENDER'
    except Exception:
        pass


def visualize_map_particle(map_particle_obj: bpy.types.Object,
                           vfx_lookup: dict,
                           assets_folder: str = "",
                           custom_assets_folder: str = "",
                           prioritize_custom: bool = False,
                           verbose: bool = False) -> int:
    """Generate Blender particle systems on a single MapParticle empty.

    Args:
        map_particle_obj: The Blender object created by import_particles_from_materials.
        vfx_lookup: Dict mapping vfx_entry_hash (lowercased '0x...') → VfxDefinition empty.
        texture_root: Optional path to project `assets/` folder for texture loading.
        verbose: Print progress to console.

    Returns:
        Number of particle systems created (one per emitter).
    """
    scene = bpy.context.scene
    system_link = (map_particle_obj.get("particle_system", "") or "").lower()
    if not system_link:
        return 0

    vfx_obj = vfx_lookup.get(system_link)
    if vfx_obj is None:
        if verbose:
            print(f"[VFX Visualizer] No VFX def found for system={system_link}")
        return 0

    vfx = decode_vfx_from_object(vfx_obj)
    if vfx is None or not vfx.emitters:
        if verbose:
            print(f"[VFX Visualizer] VFX '{vfx_obj.name}' has no decoded emitters")
        return 0

    # Convert the empty into a UV-sphere proxy mesh sized to the largest
    # spawn_radius across the emitter list. Don't carry over the empty's
    # (50,50,50) display scale — that would balloon the emission volume.
    if map_particle_obj.type == 'EMPTY':
        loc = map_particle_obj.location.copy()
        rot = map_particle_obj.rotation_euler.copy()
        original_props = {k: map_particle_obj[k] for k in map_particle_obj.keys()
                          if not k.startswith('_RNA_UI')}
        target_cols = list(map_particle_obj.users_collection)
        original_name = map_particle_obj.name

        max_radius = max(
            (em.spawn_radius for em in vfx.emitters if em.spawn_radius > 0),
            default=DEFAULT_SPAWN_RADIUS,
        )

        # Unlink and remove the empty FIRST so we can reuse its name
        for c in list(map_particle_obj.users_collection):
            try:
                c.objects.unlink(map_particle_obj)
            except Exception:
                pass
        bpy.data.objects.remove(map_particle_obj, do_unlink=True)

        new_obj = _create_emitter_proxy(original_name, loc, rot, max_radius)

        # Copy custom properties forward
        for k, v in original_props.items():
            try:
                new_obj[k] = v
            except Exception:
                pass

        # Move into the same collection(s) as the original
        scene_default = bpy.context.scene.collection
        if new_obj.name in scene_default.objects:
            try:
                scene_default.objects.unlink(new_obj)
            except Exception:
                pass
        for c in target_cols:
            if new_obj.name not in c.objects:
                c.objects.link(new_obj)
        map_particle_obj = new_obj

    created = 0
    for i, emitter in enumerate(vfx.emitters):
        if not emitter.enabled:
            continue

        em_safe = re.sub(r'[^A-Za-z0-9_]+', '_', emitter.name) or f"Em{i}"
        psys_name = f"VFX_{em_safe}"
        if psys_name in [ps.name for ps in map_particle_obj.particle_systems]:
            continue   # already exists

        # Build material + render proxy plane
        mat = _build_particle_material(
            emitter,
            assets_folder=assets_folder,
            custom_assets_folder=custom_assets_folder,
            prioritize_custom=prioritize_custom,
        )
        render_obj = _ensure_render_object(emitter, mat)

        # Add particle-system modifier with a unique ParticleSettings datablock
        map_particle_obj.modifiers.new(name=psys_name, type='PARTICLE_SYSTEM')
        psys = map_particle_obj.particle_systems[-1]
        psys.name = psys_name
        psys.settings = bpy.data.particles.new(name=f"VFX_{em_safe}_S")

        _apply_emitter_to_psys(psys, emitter, render_obj, scene)
        created += 1

    # Hide the wire-sphere instancer in viewport & render so only the
    # spawned particles are visible (replacement for the removed
    # ParticleSettings.use_render_emitter flag).
    if created:
        for attr in ("show_instancer_for_viewport", "show_instancer_for_render"):
            if hasattr(map_particle_obj, attr):
                try:
                    setattr(map_particle_obj, attr, False)
                except Exception:
                    pass

    if verbose and created:
        print(f"[VFX Visualizer] {map_particle_obj.name}: {created} emitter(s)")

    return created


def build_vfx_lookup() -> dict:
    """Build a dict of vfx_entry_hash → VFX empty for every imported VFX def."""
    lookup = {}
    for obj in bpy.data.objects:
        if not obj.get("is_vfx_definition"):
            continue
        eh = (obj.get("vfx_entry_hash", "") or "").lower()
        if eh:
            lookup[eh] = obj
        # Also index by name for legacy items
        nm = (obj.get("vfx_name", "") or "").lower()
        if nm:
            lookup[nm] = obj
    return lookup


def visualize_particles(particle_objs, assets_folder: str = "",
                        custom_assets_folder: str = "",
                        prioritize_custom: bool = False,
                        verbose: bool = False) -> dict:
    """Visualize a list of MapParticle empties.

    Returns a dict with statistics: 'objects_processed', 'emitters_created',
    'skipped_no_link', 'skipped_no_vfx_data'.
    """
    stats = {
        "objects_processed": 0,
        "emitters_created": 0,
        "skipped_no_link": 0,
        "skipped_no_vfx_data": 0,
    }

    vfx_lookup = build_vfx_lookup()
    if verbose:
        print(f"[VFX Visualizer] {len(vfx_lookup)} VFX definitions in scene")

    # Iterate over a copy because we replace empties with mesh objects
    for obj in list(particle_objs):
        if obj is None or obj.name not in bpy.data.objects:
            continue

        link = (obj.get("particle_system", "") or "").lower()
        if not link:
            stats["skipped_no_link"] += 1
            continue

        vfx_obj = vfx_lookup.get(link)
        if vfx_obj is None or not vfx_obj.get("vfx_fields_json"):
            stats["skipped_no_vfx_data"] += 1
            continue

        # Capture the name up-front because visualize_map_particle may
        # remove the empty (replacing it with a mesh proxy of the same name).
        obj_name = obj.name
        try:
            n = visualize_map_particle(
                obj, vfx_lookup,
                assets_folder=assets_folder,
                custom_assets_folder=custom_assets_folder,
                prioritize_custom=prioritize_custom,
                verbose=verbose,
            )
            stats["objects_processed"] += 1
            stats["emitters_created"] += n
        except Exception as e:
            import traceback
            print(f"[VFX Visualizer] Failed on {obj_name}: {e}")
            traceback.print_exc()

    return stats


def collect_visualizable_particles(only_selected: bool = False) -> list:
    """Return a list of MapParticle objects that could be visualized."""
    out = []
    pool = bpy.context.selected_objects if only_selected else bpy.data.objects
    for obj in pool:
        if obj.get("is_particle_system") and obj.get("particle_system"):
            out.append(obj)
    return out


def clear_particle_systems(particle_objs):
    """Remove all VFX_* particle systems from the given objects."""
    removed = 0
    for obj in particle_objs:
        if obj is None or not hasattr(obj, "particle_systems"):
            continue
        # Remove all VFX_-prefixed particle modifiers
        to_remove = [m for m in obj.modifiers
                     if m.type == 'PARTICLE_SYSTEM' and m.name.startswith("VFX_")]
        for m in to_remove:
            try:
                obj.modifiers.remove(m)
                removed += 1
            except Exception:
                pass
    return removed


# ===========================================================================
# Blender Operators
# ===========================================================================

class MAPGEO_OT_visualize_particles(bpy.types.Operator):
    """Generate Blender particle systems for imported MapParticle placements"""
    bl_idname = "mapgeo.visualize_particles"
    bl_label = "Visualize Particles"
    bl_description = ("Decode imported VfxSystemDefinitionData entries and create "
                      "Blender particle systems on each MapParticle placement so "
                      "the particles are visible in the viewport")
    bl_options = {'REGISTER', 'UNDO'}

    only_selected: bpy.props.BoolProperty(
        name="Selected Only",
        description="Visualize only selected MapParticle objects",
        default=False,
    )

    use_texture_root: bpy.props.BoolProperty(
        name="Load Textures",
        description="Resolve and load particle textures from the addon's "
                    "Original Assets / Custom Assets folders (and Riot WAD "
                    "extraction caches)",
        default=True,
    )

    verbose: bpy.props.BoolProperty(
        name="Verbose Console Log",
        description="Print per-emitter info to the system console",
        default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "only_selected")
        layout.prop(self, "use_texture_root")
        layout.prop(self, "verbose")

        settings = getattr(context.scene, "mapgeo_settings", None)
        if settings is not None:
            box = layout.box()
            box.label(text="Texture sources:", icon='IMAGE_DATA')
            box.label(text=f"Original: {(settings.assets_folder or '(unset)')[:48]}")
            box.label(text=f"Custom:   {(settings.custom_assets_folder or '(unset)')[:48]}")

        n = len(collect_visualizable_particles(only_selected=self.only_selected))
        layout.label(text=f"Will process {n} MapParticle object(s)", icon='INFO')

    def execute(self, context):
        particle_objs = collect_visualizable_particles(only_selected=self.only_selected)
        if not particle_objs:
            self.report({'WARNING'}, "No MapParticle objects found")
            return {'CANCELLED'}

        # Pull the addon's configured asset folders. These are the same
        # folders used by the rest of the addon (mapgeo import, materials, etc).
        assets_folder = ""
        custom_assets_folder = ""
        prioritize_custom = False
        if self.use_texture_root:
            settings = getattr(context.scene, "mapgeo_settings", None)
            if settings is not None:
                assets_folder = bpy.path.abspath(settings.assets_folder or "")
                custom_assets_folder = bpy.path.abspath(settings.custom_assets_folder or "")
                prioritize_custom = bool(getattr(settings, "prioritize_custom_assets", False))

                # Fallback: if no explicit asset folders are set, derive from project_folder
                if not assets_folder and not custom_assets_folder:
                    project_folder = bpy.path.abspath(getattr(settings, "project_folder", "") or "")
                    if project_folder:
                        cand = os.path.join(project_folder, "assets")
                        assets_folder = cand if os.path.isdir(cand) else project_folder

            if not assets_folder and not custom_assets_folder:
                self.report({'WARNING'},
                            "No assets folder configured — set 'Original Assets Folder' "
                            "in the Mapgeo panel for textures to load")

        stats = visualize_particles(
            particle_objs,
            assets_folder=assets_folder,
            custom_assets_folder=custom_assets_folder,
            prioritize_custom=prioritize_custom,
            verbose=self.verbose,
        )

        msg = (f"Visualized {stats['objects_processed']} placement(s) — "
               f"{stats['emitters_created']} emitter(s) created. "
               f"Skipped: {stats['skipped_no_link']} (no link), "
               f"{stats['skipped_no_vfx_data']} (no VFX data)")
        self.report({'INFO'}, msg)
        print(f"[VFX Visualizer] {msg}")
        return {'FINISHED'}


class MAPGEO_OT_clear_particle_visuals(bpy.types.Operator):
    """Remove all generated VFX particle systems from MapParticle objects"""
    bl_idname = "mapgeo.clear_particle_visuals"
    bl_label = "Clear Particle Visuals"
    bl_description = "Remove all VFX_* particle systems from the scene"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected: bpy.props.BoolProperty(
        name="Selected Only",
        default=False,
    )

    def execute(self, context):
        particle_objs = collect_visualizable_particles(only_selected=self.only_selected)
        # Also include any object with VFX_ modifiers
        all_particle_owners = list(particle_objs)
        for obj in bpy.data.objects:
            if any(m.type == 'PARTICLE_SYSTEM' and m.name.startswith("VFX_")
                   for m in obj.modifiers):
                if obj not in all_particle_owners:
                    all_particle_owners.append(obj)

        removed = clear_particle_systems(all_particle_owners)
        self.report({'INFO'}, f"Removed {removed} particle system(s)")
        return {'FINISHED'}


class MAPGEO_OT_inspect_vfx_definition(bpy.types.Operator):
    """Print decoded VFX emitter info for the active VFX definition empty"""
    bl_idname = "mapgeo.inspect_vfx_definition"
    bl_label = "Inspect VFX (console)"
    bl_description = ("Decode the active VFX definition and print its emitter "
                      "list to the system console")

    def execute(self, context):
        obj = context.active_object
        if obj is None or not obj.get("is_vfx_definition"):
            self.report({'WARNING'}, "Select a VFX definition empty first")
            return {'CANCELLED'}

        vfx = decode_vfx_from_object(obj)
        if vfx is None:
            self.report({'WARNING'}, "VFX has no cached fields data")
            return {'CANCELLED'}

        print("=" * 60)
        print(f"VFX: {vfx.name}")
        print(f"  short_name:   {vfx.short_name}")
        print(f"  full_path:    {vfx.full_path}")
        print(f"  sim_distance: {vfx.sim_distance}")
        print(f"  emitters:     {len(vfx.emitters)}")
        for i, em in enumerate(vfx.emitters):
            print(f"  [{i}] {em.name!r}")
            print(f"       lifetime={em.lifetime}  rate={em.rate}  prob={em.probability}")
            print(f"       color={em.base_color}  scale={em.base_scale}")
            print(f"       velocity={em.velocity}  spawn_radius={em.spawn_radius}")
            print(f"       mesh={em.mesh_path or '(none)'}")
            print(f"       tex_diffuse={em.texture_diffuse or '(none)'}")
            print(f"       tex_alpha={em.texture_alpha or '(none)'}")
            print(f"       render_mode={em.render_mode}  type={em.emitter_type}")
        print("=" * 60)

        self.report({'INFO'}, f"VFX '{vfx.name}': {len(vfx.emitters)} emitter(s) — see console")
        return {'FINISHED'}


# ===========================================================================
# Registration
# ===========================================================================

CLASSES = (
    MAPGEO_OT_visualize_particles,
    MAPGEO_OT_clear_particle_visuals,
    MAPGEO_OT_inspect_vfx_definition,
)


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            # already registered
            pass


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
