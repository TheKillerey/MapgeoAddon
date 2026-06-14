"""
heightmap_ui.py
===============
Blender panel for baking top-down map images from the League of Legends
scene currently loaded by the MapgeoAddon.

The panel lives in:  Properties ▸ Scene  (or  N-panel ▸ Mapgeo ▸ Heightmap)

Two bakers
----------
1. NavGrid baker (exact) — parses the game's .aimesh_ngrid navigation grid
   and writes pixel-exact walkability + height maps plus a meta JSON.
   This is the game's own pathing data, so walkable/wall/brush is exact.
2. Legacy render baker — renders the loaded meshes with classification
   heuristics. Useful when no navgrid file is available.

Colour coding (both bakers, "combined" output)
----------------------------------------------
  White → Black  : walkable ground by elevation  (black = low, white = high)
  Green           : bushes / grass
  Red             : walls / non-walkable

Layer filtering
---------------
Meshes are included / excluded based on their baron/dragon layer custom
properties, using the same logic as the main visibility system.
Objects with  obj["render_region_hash"]  are always excluded.
"""

import ast
import os
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       IntProperty, StringProperty)
from mathutils import Vector

from . import navgrid


# ─── Layer name → flags (matches __init__.py visibility logic exactly) ──────
DRAGON_LAYER_FLAGS = {
    "LAYER_1": 1 << 0,   # Base
    "LAYER_2": 1 << 1,   # Inferno
    "LAYER_3": 1 << 2,   # Mountain
    "LAYER_4": 1 << 3,   # Ocean
    "LAYER_5": 1 << 4,   # Cloud
    "LAYER_6": 1 << 5,   # Hextech
    "LAYER_7": 1 << 6,   # Chemtech
    "LAYER_8": 1 << 7,   # Void
}

BARON_LAYER_BITS = {
    "BARON_BASE":     1,
    "BARON_CUP":      2,
    "BARON_TUNNEL":   4,
    "BARON_UPGRADED": 8,
}

HM_DRAGON_LAYER_ITEMS = [
    ("CURRENT", "Use Scene Filter", "Use scene.mapgeo_settings.dragon_layer_filter", 0),
    ("ALL", "All", "Disable dragon-layer filtering", 1),
    ("LAYER_1", "Base", "Base map", 2),
    ("LAYER_2", "Inferno", "Inferno drake variation", 3),
    ("LAYER_3", "Mountain", "Mountain drake variation", 4),
    ("LAYER_4", "Ocean", "Ocean drake variation", 5),
    ("LAYER_5", "Cloud", "Cloud drake variation", 6),
    ("LAYER_6", "Hextech", "Hextech drake variation", 7),
    ("LAYER_7", "Chemtech", "Chemtech drake variation", 8),
    ("LAYER_8", "Void", "Void drake variation", 9),
]

HM_BARON_LAYER_ITEMS = [
    ("CURRENT", "Use Scene Filter", "Use scene.mapgeo_settings.baron_layer_filter", 0),
    ("ALL", "All", "Disable baron-state filtering", 1),
    ("BARON_BASE", "Base", "Default baron pit", 2),
    ("BARON_CUP", "Cup", "Baron cup variation", 3),
    ("BARON_TUNNEL", "Tunnel", "Baron tunnel variation", 4),
    ("BARON_UPGRADED", "Upgraded", "Baron upgraded variation", 5),
]


# ─── Classification heuristics ───────────────────────────────────────────────

# Shader names that we consider "wall-like" (non-walkable vertical geometry).
_WALL_SHADER_KEYWORDS = (
    "wall", "cliff", "rock", "stone", "barrier", "fence",
    "pillar", "column", "tower", "building", "structure",
    "arch", "bridge_side", "railing",
)

# Shader names strongly associated with flat walkable terrain.
_TERRAIN_SHADER_KEYWORDS = (
    "terrain", "ground", "floor", "path", "road", "dirt",
    "baked_terrain", "flat", "pavement", "cobble",
)


def _is_render_region_object(obj):
    """Return True if this object is a render-region helper mesh."""
    if "render_region_hash" in obj:
        return True

    # Fallback for older scenes or hand-edited data where only collection/name
    # hints exist and the custom property may be missing.
    name_l = obj.name.lower()
    if "renderregion" in name_l or "render_region" in name_l:
        return True

    for col in obj.users_collection:
        col_l = col.name.lower()
        if "renderregion" in col_l or "render_region" in col_l:
            return True
    return False


def _is_bucket_grid_object(obj):
    """Return True if object belongs to imported/custom bucket grid data."""
    # Explicit flags set by bucket-grid import/creation tools.
    if obj.get("is_bucket_grid") or obj.get("is_bucket_grid_bounds"):
        return True

    # Collection-level markers used in the addon.
    for col in obj.users_collection:
        if col.get("is_bucket_grid_collection"):
            return True
        col_l = col.name.lower()
        if "bucket_grid" in col_l or "bucketgrid" in col_l:
            return True

    # Name fallback for safety.
    name_l = obj.name.lower()
    if "bucket_grid" in name_l or "bucketgrid" in name_l:
        return True

    return False


def _material_tokens(obj):
    """Collect lowercase tokens from all material slots for robust matching."""
    tokens = []
    if not obj.data:
        return tokens

    for slot in obj.material_slots:
        mat = slot.material
        if not mat:
            continue
        # league_material_name is usually the source material entry name.
        lm_name = str(mat.get("league_material_name", "") or "").lower()
        if lm_name:
            tokens.append(lm_name)
        # Blender material name can still hold useful hints.
        tokens.append(mat.name.lower())
        # Include shader path if present from preview/builder workflows.
        shader_path = str(mat.get("lol_shader_path", "") or "").lower()
        if shader_path:
            tokens.append(shader_path)
    return tokens

def _classify(obj):
    """
    Return one of:  'bush' | 'wall' | 'ground'

        Priority:
            1. is_bush custom property     → 'bush'
            2. ground material-name match  → 'ground'
            3. wall keyword / slope hints  → 'wall'
            4. fallback                    → 'wall' (safer for exports)
    """
    if obj.get("is_bush"):
        return "bush"

    tokens = _material_tokens(obj)

    # Ground-first: if any material looks like terrain/walkable, mark ground.
    for t in tokens:
        for kw in _TERRAIN_SHADER_KEYWORDS:
            if kw in t:
                return "ground"

    # If it wasn't recognized as ground, then wall-like names should force wall.
    for t in tokens:
        for kw in _WALL_SHADER_KEYWORDS:
            if kw in t:
                return "wall"

    # Geometry normal heuristic: if most face normals point sideways → wall
    try:
        mesh = obj.data
        mw   = obj.matrix_world.to_3x3().normalized()
        total = len(mesh.polygons)
        if total > 0:
            sideways = sum(
                1 for p in mesh.polygons
                if abs((mw @ p.normal).z) < 0.4
            )
            if sideways / total > 0.6:
                return "wall"
    except Exception:
        pass

    return "wall"


def _resolve_active_filters(settings, context):
    """Resolve requested dragon+baron filters (CURRENT/ALL/specific)."""
    dragon_key = settings.hm_dragon_layer_filter
    baron_key = settings.hm_baron_layer_filter

    if hasattr(context.scene, "mapgeo_settings"):
        mapgeo_settings = context.scene.mapgeo_settings
        if dragon_key == "CURRENT":
            dragon_key = getattr(mapgeo_settings, "dragon_layer_filter", "LAYER_1")
        if baron_key == "CURRENT":
            baron_key = getattr(mapgeo_settings, "baron_layer_filter", "BARON_BASE")

    return dragon_key, baron_key


def _obj_visible_for_layers(obj, dragon_key: str, baron_key: str) -> bool:
    """
    Same Baron+Dragon logic as update_environment_visibility() in __init__.py.
    If dragon_key == 'ALL', dragon filtering is disabled.
    If baron_key == 'ALL', baron filtering is disabled.
    """
    has_baron_hash = "baron_hash" in obj and obj.get("baron_hash", "00000000") != "00000000"
    visibility_layer = obj.get("visibility_layer", 0)

    # STEP 1: dragon visibility
    if dragon_key == "ALL":
        dragon_visible = True
    else:
        current_dragon_flag = DRAGON_LAYER_FLAGS.get(dragon_key, 1)
        dragon_visible = False

        if has_baron_hash and "baron_dragon_layers_decoded" in obj:
            try:
                dragon_layers = ast.literal_eval(obj["baron_dragon_layers_decoded"])
                parent_mode = obj.get("baron_parent_mode", 1)

                if len(dragon_layers) > 0:
                    is_in_list = (1 in dragon_layers) or (current_dragon_flag in dragon_layers)
                    dragon_visible = (not is_in_list) if parent_mode == 3 else is_in_list
                else:
                    dragon_visible = False
            except Exception:
                if visibility_layer == 0 or visibility_layer == 255:
                    dragon_visible = True
                elif visibility_layer & 1:
                    dragon_visible = True
                elif visibility_layer & current_dragon_flag:
                    dragon_visible = True
        else:
            if visibility_layer == 0 or visibility_layer == 255:
                dragon_visible = True
            elif visibility_layer & 1:
                dragon_visible = True
            elif visibility_layer & current_dragon_flag:
                dragon_visible = True

    # STEP 2: baron visibility
    if baron_key == "ALL":
        baron_visible = True
    else:
        current_baron_bit = BARON_LAYER_BITS.get(baron_key, 1)
        baron_visible = True

        if has_baron_hash and "baron_layers_decoded" in obj:
            try:
                baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                parent_mode = obj.get("baron_parent_mode", 1)
                is_in_list = (current_baron_bit in baron_layers)
                baron_visible = (not is_in_list) if parent_mode == 3 else is_in_list
            except Exception:
                baron_visible = True

    return dragon_visible and baron_visible


def _iter_objects(settings):
    """
    Yield (obj, classification) for every mesh that should be included in
    the bake, applying layer and render-region filters.
    """
    context = bpy.context
    dragon_key, baron_key = _resolve_active_filters(settings, context)

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if not obj.visible_get():
            continue
        # Always exclude bucket-grid helper/partition meshes.
        if _is_bucket_grid_object(obj):
            continue
        # Always exclude render-region meshes (unknown int / hash helpers)
        if _is_render_region_object(obj):
            continue
        # Baron+Dragon filter (same as addon visibility system)
        if not _obj_visible_for_layers(obj, dragon_key, baron_key):
            continue

        cls = _classify(obj)

        # Honour per-type include toggles
        if cls == "bush"   and not settings.hm_include_bush:
            continue
        if cls == "wall"   and not settings.hm_include_walls:
            continue
        if cls == "ground" and not settings.hm_include_ground:
            continue

        yield obj, cls


# ─── Bounds + Z sampling ─────────────────────────────────────────────────────

def _get_bounds_and_z(settings):
    """
    Compute scene XY extents and Z normalisation range.
    Returns (mins, maxs, z_lo, z_hi, obj_list_with_cls).
    """
    INF = float("inf")
    mins = [ INF,  INF,  INF]
    maxs = [-INF, -INF, -INF]

    obj_list = list(_iter_objects(settings))
    if not obj_list:
        raise RuntimeError("No mesh objects passed the current filters.")

    for obj, _cls in obj_list:
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            for i in range(3):
                if wc[i] < mins[i]: mins[i] = wc[i]
                if wc[i] > maxs[i]: maxs[i] = wc[i]

    # Z range
    if settings.hm_use_z_override:
        z_lo = settings.hm_z_min_override
        z_hi = settings.hm_z_max_override
        print(f"[Heightmap] Manual Z range: {z_lo:.2f} → {z_hi:.2f}")
        return mins, maxs, z_lo, z_hi, obj_list

    # Vertex sampling
    budget   = 200_000
    n_objs   = len(obj_list)
    per_obj  = max(1, budget // n_objs)
    z_vals   = []
    dg       = bpy.context.evaluated_depsgraph_get()

    for obj, _cls in obj_list:
        try:
            ev   = obj.evaluated_get(dg)
            mesh = ev.to_mesh()
            step = max(1, len(mesh.vertices) // per_obj)
            mw   = obj.matrix_world
            for i in range(0, len(mesh.vertices), step):
                z_vals.append((mw @ mesh.vertices[i].co).z)
            ev.to_mesh_clear()
        except Exception:
            pass

    if not z_vals:
        return mins, maxs, mins[2], maxs[2], obj_list

    z_vals.sort()
    n   = len(z_vals)
    clip = settings.hm_z_percentile_clip / 100.0
    lo_i = max(0,     int(n * clip))
    hi_i = min(n - 1, int(n * (1.0 - clip)))
    z_lo = z_vals[lo_i]
    z_hi = z_vals[hi_i]

    print(f"[Heightmap] Z distribution ({n} samples):")
    for p in (0, 1, 5, 25, 50, 75, 95, 99, 100):
        idx = min(n - 1, int(n * p / 100))
        print(f"  {p:>3}%  →  {z_vals[idx]:>10.2f}")
    print(f"[Heightmap] Normalisation: {z_lo:.2f} (black) → {z_hi:.2f} (white)")
    return mins, maxs, z_lo, z_hi, obj_list


# ─── Temp material builders ───────────────────────────────────────────────────

def _height_material(z_min, z_max, color_rgb=(1, 1, 1)):
    """Emissive material encoding world-Z as the given RGB colour × normalised height."""
    mat = bpy.data.materials.new("_HM_TMP_height")
    mat.use_nodes = True
    nt = mat.node_tree
    ns, lk = nt.nodes, nt.links
    ns.clear()

    out  = ns.new("ShaderNodeOutputMaterial"); out.location  = (800, 0)
    emit = ns.new("ShaderNodeEmission");       emit.location = (600, 0)
    emit.inputs["Strength"].default_value = 1.0

    geo  = ns.new("ShaderNodeNewGeometry"); geo.location  = (-600, 0)
    sep  = ns.new("ShaderNodeSeparateXYZ"); sep.location  = (-400, 0)
    lk.new(geo.outputs["Position"], sep.inputs["Vector"])

    z_range = max(z_max - z_min, 1e-6)
    sub  = ns.new("ShaderNodeMath"); sub.operation = "SUBTRACT"; sub.location = (-200, 0)
    sub.inputs[1].default_value = z_min
    lk.new(sep.outputs["Z"], sub.inputs[0])

    div  = ns.new("ShaderNodeMath"); div.operation = "DIVIDE"; div.location = (0, 0)
    div.inputs[1].default_value = z_range
    lk.new(sub.outputs["Value"], div.inputs[0])

    clmp = ns.new("ShaderNodeClamp"); clmp.location = (200, 0)
    lk.new(div.outputs["Value"], clmp.inputs["Value"])

    # Multiply scalar by target colour (so walls are red, bushes are green, etc.)
    col_node = ns.new("ShaderNodeRGB"); col_node.location = (200, -200)
    col_node.outputs[0].default_value = (*color_rgb, 1.0)

    mul  = ns.new("ShaderNodeMix"); mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"; mul.location = (400, 0)
    mul.inputs["Factor"].default_value = 1.0
    lk.new(clmp.outputs["Result"], mul.inputs[6])   # A = greyscale value (0..1 in all channels)
    # We need to replicate scalar into a full white first
    white = ns.new("ShaderNodeRGB"); white.location = (200, 150)
    white.outputs[0].default_value = (1, 1, 1, 1)
    # scalar → grey via CombineXYZ
    comb = ns.new("ShaderNodeCombineXYZ"); comb.location = (200, 50)
    lk.new(clmp.outputs["Result"], comb.inputs["X"])
    lk.new(clmp.outputs["Result"], comb.inputs["Y"])
    lk.new(clmp.outputs["Result"], comb.inputs["Z"])
    lk.new(comb.outputs["Vector"], mul.inputs[6])   # A = grey
    lk.new(col_node.outputs["Color"], mul.inputs[7])  # B = tint colour
    lk.new(mul.outputs[2], emit.inputs["Color"])
    lk.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def _flat_material(color_rgb):
    """Flat emissive material at a fixed colour (walls, bushes at full brightness)."""
    mat = bpy.data.materials.new("_HM_TMP_flat")
    mat.use_nodes = True
    nt = mat.node_tree
    ns, lk = nt.nodes, nt.links
    ns.clear()
    out  = ns.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    emit = ns.new("ShaderNodeEmission");       emit.location = (200, 0)
    emit.inputs["Color"].default_value   = (*color_rgb, 1.0)
    emit.inputs["Strength"].default_value = 1.0
    lk.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def _make_camera(mins, maxs, res_x, res_y, padding):
    cx = (mins[0] + maxs[0]) / 2.0
    cy = (mins[1] + maxs[1]) / 2.0
    cz = maxs[2] + 1000.0
    aspect      = res_x / res_y
    x_range     = maxs[0] - mins[0]
    y_range     = maxs[1] - mins[1]
    ortho_scale = max(y_range, x_range / aspect) * (1.0 + padding / 100.0)
    cam_data = bpy.data.cameras.new("_HM_TMP_cam")
    cam_data.type        = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start  = 0.1
    cam_data.clip_end    = (cz - mins[2]) + 2000.0
    cam_obj = bpy.data.objects.new("_HM_TMP_cam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location       = (cx, cy, cz)
    cam_obj.rotation_euler = (0.0, 0.0, 0.0)
    return cam_obj, cam_data


# ─── Core bake routine ───────────────────────────────────────────────────────

def _bake(settings, context):
    scene = context.scene
    vl    = scene.view_layers[0]

    mins, maxs, z_lo, z_hi, obj_list = _get_bounds_and_z(settings)
    if not obj_list:
        return {"CANCELLED"}, "No objects matched the filters."

    out_path = bpy.path.abspath(settings.hm_output_path)
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)

    # Build per-class materials
    mat_ground = _height_material(z_lo, z_hi, (1.0, 1.0, 1.0))  # white→black gradient
    mat_bush   = _flat_material((0.0, 0.8, 0.0))                  # green
    mat_wall   = _flat_material((1.0, 0.0, 0.0))                  # red

    cam_obj, cam_data = _make_camera(mins, maxs, settings.hm_res_x, settings.hm_res_y, settings.hm_padding)

    # Snapshot render / view settings
    orig = {
        "camera":           scene.camera,
        "engine":           scene.render.engine,
        "res_x":            scene.render.resolution_x,
        "res_y":            scene.render.resolution_y,
        "res_pct":          scene.render.resolution_percentage,
        "filepath":         scene.render.filepath,
        "file_fmt":         scene.render.image_settings.file_format,
        "color_mode":       scene.render.image_settings.color_mode,
        "color_depth":      scene.render.image_settings.color_depth,
        "transparent":      scene.render.film_transparent,
        "mat_override":     vl.material_override,
        "world":            scene.world,
        "view_transform":   scene.view_settings.view_transform,
        "exposure":         scene.view_settings.exposure,
        "gamma":            scene.view_settings.gamma,
        "look":             scene.view_settings.look,
    }
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        orig["eevee_samples"] = scene.eevee.taa_render_samples

    # Stash each object's original material slots and override with class mat
    hidden_objs = []     # initialized up-front: the finally block always runs
    orig_materials = {}  # obj → list of original materials
    for obj, cls in obj_list:
        slots = [s.material for s in obj.material_slots]
        orig_materials[obj.name] = (obj, slots)
        target_mat = {"ground": mat_ground, "bush": mat_bush, "wall": mat_wall}[cls]
        for slot in obj.material_slots:
            slot.material = target_mat
        if not obj.material_slots:
            obj.data.materials.append(target_mat)

    try:
        scene.camera = cam_obj
        for eid in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = eid; break
            except Exception:
                pass

        scene.render.resolution_x                = settings.hm_res_x
        scene.render.resolution_y                = settings.hm_res_y
        scene.render.resolution_percentage       = 100
        scene.render.filepath                    = out_path
        scene.render.image_settings.file_format  = "PNG"
        scene.render.image_settings.color_mode   = "RGB"   # RGB so colours are preserved
        scene.render.image_settings.color_depth  = "8"
        scene.render.film_transparent            = False
        vl.material_override                     = None    # NOT overriding — we set per-obj

        if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = 1

        # Disable tone mapping
        for vt in ("Standard", "Raw", "None"):
            try:
                scene.view_settings.view_transform = vt; break
            except TypeError:
                pass
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma    = 1.0
        scene.view_settings.look     = "None"

        # Black world
        tmp_world = bpy.data.worlds.new("_HM_TMP_world")
        tmp_world.use_nodes = False
        tmp_world.color = (0.0, 0.0, 0.0)
        scene.world = tmp_world

        # Hide objects NOT in our list
        our_names = {obj.name for obj, _ in obj_list}
        for obj in scene.objects:
            if obj.type == "MESH" and obj.name not in our_names and obj.visible_get():
                obj.hide_render = True
                hidden_objs.append(obj)

        bpy.ops.render.render(write_still=True)
        print(f"[Heightmap] Saved → {out_path}")

    finally:
        # Restore object materials
        for obj_name, (obj, slots) in orig_materials.items():
            for i, mat in enumerate(slots):
                if i < len(obj.material_slots):
                    obj.material_slots[i].material = mat

        # Unhide
        for obj in hidden_objs:
            obj.hide_render = False

        # Restore render settings
        scene.camera                             = orig["camera"]
        scene.render.engine                      = orig["engine"]
        scene.render.resolution_x                = orig["res_x"]
        scene.render.resolution_y                = orig["res_y"]
        scene.render.resolution_percentage       = orig["res_pct"]
        scene.render.filepath                    = orig["filepath"]
        scene.render.image_settings.file_format  = orig["file_fmt"]
        scene.render.image_settings.color_mode   = orig["color_mode"]
        scene.render.image_settings.color_depth  = orig["color_depth"]
        scene.render.film_transparent            = orig["transparent"]
        vl.material_override                     = orig["mat_override"]
        scene.world                              = orig["world"]
        scene.view_settings.view_transform       = orig["view_transform"]
        scene.view_settings.exposure             = orig["exposure"]
        scene.view_settings.gamma                = orig["gamma"]
        scene.view_settings.look                 = orig["look"]
        if "eevee_samples" in orig and hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "taa_render_samples"):
                scene.eevee.taa_render_samples = orig["eevee_samples"]

        bpy.data.objects.remove(cam_obj,     do_unlink=True)
        bpy.data.cameras.remove(cam_data,    do_unlink=True)
        bpy.data.materials.remove(mat_ground, do_unlink=True)
        bpy.data.materials.remove(mat_bush,   do_unlink=True)
        bpy.data.materials.remove(mat_wall,   do_unlink=True)
        if "_HM_TMP_world" in bpy.data.worlds:
            bpy.data.worlds.remove(bpy.data.worlds["_HM_TMP_world"], do_unlink=True)

    # Load image back
    img_name = "LoL_Heightmap"
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    img = bpy.data.images.load(out_path, check_existing=False)
    img.name = img_name
    img.colorspace_settings.name = "Non-Color"
    return {"FINISHED"}, f"Baked → {out_path}"


# ─── NavGrid file discovery ──────────────────────────────────────────────────

def _riot_cache_dir(context):
    """Riot WAD cache dir for the project's map, extracting it if a League
    install is configured, otherwise falling back to an existing cache."""
    ps = getattr(context.scene, "project_settings", None)
    if ps is None:
        return ""
    map_id = getattr(ps, "project_map_id", "")
    if not map_id:
        return ""
    try:
        from . import project_manager
    except Exception:
        return ""
    league = bpy.path.abspath(getattr(ps, "league_install", "") or "")
    if league:
        try:
            cache = project_manager._ensure_riot_wad_cache(league, map_id)
            if cache and os.path.isdir(cache):
                return cache
        except Exception:
            pass
    # No league path set — use an already-extracted cache if present.
    try:
        cand = os.path.join(project_manager._get_wad_cache_root(), map_id)
        if os.path.isdir(cand):
            return cand
    except Exception:
        pass
    return ""


def _navgrid_candidates(context):
    """Collect .aimesh_ngrid candidate files from the project folder and the
    Riot WAD cache. Returns list of absolute paths (no duplicates)."""
    roots = []
    ps = getattr(context.scene, "project_settings", None)
    if ps is not None:
        proj = bpy.path.abspath(getattr(ps, "project_folder", "") or "")
        if proj and os.path.isdir(proj):
            roots.append(proj)
    cache = _riot_cache_dir(context)
    if cache:
        roots.append(cache)

    found = []
    seen = set()
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".aimesh_ngrid"):
                    p = os.path.join(dirpath, fn)
                    key = os.path.normcase(p)
                    if key not in seen:
                        seen.add(key)
                        found.append(p)
    return found


def _navgrid_from_map_bin(context, candidates):
    """Try to pick the navgrid that belongs to the currently loaded map
    variant by reading the MapSkin entries of the map .bin. Returns a path
    from *candidates* or ''. """
    ps = getattr(context.scene, "project_settings", None)
    if ps is None:
        return ""

    # Name of the loaded variant, e.g. "base_srx"
    variant = ""
    try:
        idx = ps.selected_variant_index
        if 0 <= idx < len(ps.map_variants):
            variant = ps.map_variants[idx].name.lower()
    except Exception:
        pass

    # Locate the map bin in the riot cache
    map_bin = ""
    cache = _riot_cache_dir(context)
    map_id = getattr(ps, "project_map_id", "")
    if cache and map_id:
        mid = map_id.lower()
        for sub in (os.path.join("data", "maps", "shipping", mid, f"{mid}.bin"),
                    os.path.join("maps", "shipping", mid, f"{mid}.bin")):
            cand = os.path.join(cache, sub)
            if os.path.isfile(cand):
                map_bin = cand
                break
    if not map_bin:
        return ""

    try:
        from . import propertybin_parser, map11_editor
        data = propertybin_parser.parse_bin(map_bin)
    except Exception as e:
        print(f"[NavGrid] Could not parse map bin {map_bin}: {e}")
        return ""

    skins = []  # (skin_name, geo_basename, navgrid_path)
    for entry in data.get("entries", []):
        if entry.get("type_hash") != map11_editor.HASH_MAP_SKIN:
            continue
        name = map11_editor._get_field_value(entry, map11_editor.FIELD_NAME)
        geo = map11_editor._get_field_value(entry, map11_editor.FIELD_GEO_PATH)
        ng = map11_editor._get_field_value(entry, map11_editor.FIELD_NAVGRID)
        if ng:
            geo_base = geo.replace("\\", "/").rsplit("/", 1)[-1].lower()
            skins.append((name, geo_base, ng))

    if not skins:
        return ""

    chosen = ""
    if variant:
        for _name, geo_base, ng in skins:
            if geo_base == variant:
                chosen = ng
                break
    if not chosen:
        chosen = skins[0][2]
        print(f"[NavGrid] Variant '{variant}' not matched in map bin; "
              f"using first MapSkin navgrid: {chosen}")
    else:
        print(f"[NavGrid] Map bin says variant '{variant}' uses: {chosen}")

    # Resolve the bin path (e.g. "MAPS/NavGrid/Map11/AIPath_SRX.aimesh_ngrid")
    # against the candidate files by case-insensitive filename match.
    want = chosen.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for c in candidates:
        if os.path.basename(c).lower() == want:
            return c
    return ""


class MAPGEO_OT_detect_navgrid(bpy.types.Operator):
    bl_idname = "mapgeo.detect_navgrid"
    bl_label = "Auto-Detect NavGrid"
    bl_description = (
        "Find the .aimesh_ngrid file for the loaded map.\n"
        "Reads the map .bin to pick the right one for the current variant; "
        "all candidates are listed in the console")
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.hm_settings
        candidates = _navgrid_candidates(context)
        if not candidates:
            self.report({"ERROR"},
                        "No .aimesh_ngrid files found (project folder / WAD cache). "
                        "Set the path manually.")
            return {"CANCELLED"}

        print(f"[NavGrid] {len(candidates)} candidate file(s):")
        for c in candidates:
            print(f"  - {c}")

        chosen = _navgrid_from_map_bin(context, candidates)
        if not chosen:
            # Fallback: largest file is almost always the real gameplay grid
            chosen = max(candidates, key=os.path.getsize)
            print(f"[NavGrid] Falling back to largest candidate: {chosen}")

        settings.ng_path = chosen
        self.report({"INFO"}, f"NavGrid: {os.path.basename(chosen)}")
        return {"FINISHED"}


class MAPGEO_OT_bake_navgrid_maps(bpy.types.Operator):
    bl_idname = "mapgeo.bake_navgrid_maps"
    bl_label = "Bake NavGrid Maps"
    bl_description = (
        "Parse the navgrid and write:\n"
        "  <name>_height.png    16-bit grayscale heightmap\n"
        "  <name>_walkable.png  white = walkable, red = wall, green = brush\n"
        "  <name>_combined.png  height gradient + walls/brush overlay\n"
        "  <name>_meta.json     world bounds + height scale for generators")
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.hm_settings
        path = bpy.path.abspath(settings.ng_path)
        if not path or not os.path.isfile(path):
            self.report({"ERROR"}, "NavGrid file not set or missing — "
                                   "use Auto-Detect or pick it manually.")
            return {"CANCELLED"}

        out_base = bpy.path.abspath(settings.ng_output_path)
        out_dir = os.path.dirname(out_base)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            grid = navgrid.parse(path)
        except Exception as e:
            self.report({"ERROR"}, f"NavGrid parse failed: {e}")
            return {"CANCELLED"}

        print(f"[NavGrid] {os.path.basename(path)}: v{grid.major}.{grid.minor}, "
              f"{grid.count_x}x{grid.count_z} cells @ {grid.cell_size}, "
              f"{grid.walkable_fraction():.1%} walkable")

        try:
            meta = navgrid.bake_all(
                grid, out_base,
                scale=settings.ng_scale,
                smooth=settings.ng_smooth_height,
                mark_brush=settings.ng_mark_brush,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"Bake failed: {e}")
            return {"CANCELLED"}

        # Load results into Blender for quick inspection
        base, ext = os.path.splitext(out_base)
        if ext.lower() != ".png":
            base = out_base
        for suffix, img_name, non_color in (
                ("_height.png",   "LoL_NavGrid_Height",   True),
                ("_walkable.png", "LoL_NavGrid_Walkable", False),
                ("_combined.png", "LoL_NavGrid_Combined", False)):
            p = base + suffix
            if not os.path.isfile(p):
                continue
            if img_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[img_name])
            img = bpy.data.images.load(p, check_existing=False)
            img.name = img_name
            if non_color:
                img.colorspace_settings.name = "Non-Color"

        enc = meta["height_encoding"]
        self.report({"INFO"},
                    f"Baked {meta['image_width']}x{meta['image_height']} px | "
                    f"height {enc['z_black']:.1f}…{enc['z_white']:.1f} | "
                    f"{meta['walkable_fraction']:.0%} walkable")
        return {"FINISHED"}


# ─── Properties ──────────────────────────────────────────────────────────────

class HeightmapSettings(bpy.types.PropertyGroup):
    # NavGrid baker
    ng_path: StringProperty(
        name="NavGrid File",
        description="Path to the .aimesh_ngrid file (use Auto-Detect)",
        subtype="FILE_PATH",
        default="",
    )
    ng_output_path: StringProperty(
        name="Output Base",
        description="Base path for the baked maps; _height/_walkable/"
                    "_combined.png and _meta.json are appended",
        subtype="FILE_PATH",
        default=r"C:\Users\theki\Desktop\lol_navgrid.png",
    )
    ng_scale: IntProperty(
        name="Pixels per Cell",
        description="Upscale factor: image size = cells × this "
                    "(SR grid is 295×296 cells of 50 game units)",
        default=4, min=1, max=16,
    )
    ng_smooth_height: BoolProperty(
        name="Smooth Height",
        description="Bilinear interpolation between cell heights "
                    "(off = blocky nearest-cell values)",
        default=True,
    )
    ng_mark_brush: BoolProperty(
        name="Mark Brush (Green)",
        description="Colour brush cells green instead of treating them "
                    "as plain walkable",
        default=True,
    )
    hm_output_path: StringProperty(
        name="Output Path",
        description="Where to save the heightmap PNG",
        subtype="FILE_PATH",
        default=r"C:\Users\theki\Desktop\lol_heightmap.png",
    )
    hm_res_x: IntProperty(name="Width",  default=4096, min=64, max=16384)
    hm_res_y: IntProperty(name="Height", default=4096, min=64, max=16384)
    hm_padding: FloatProperty(
        name="Border Padding %",
        description="Extra space around the map edge (percent of map size)",
        default=2.0, min=0.0, max=50.0, subtype="PERCENTAGE",
    )
    hm_dragon_layer_filter: EnumProperty(
        name="Dragon Layer",
        description="Dragon filter for bake (can follow current scene filter)",
        items=HM_DRAGON_LAYER_ITEMS,
        default="CURRENT",
    )
    hm_baron_layer_filter: EnumProperty(
        name="Baron Layer",
        description="Baron filter for bake (can follow current scene filter)",
        items=HM_BARON_LAYER_ITEMS,
        default="CURRENT",
    )
    hm_include_ground: BoolProperty(name="Ground (White→Black)", default=True,
        description="Include walkable terrain; height encoded as White (high) → Black (low)")
    hm_include_bush:   BoolProperty(name="Bushes (Green)",        default=True,
        description="Include bush/grass objects, shown in solid green")
    hm_include_walls:  BoolProperty(name="Walls (Red)",           default=True,
        description="Include wall/cliff objects detected by shader name or face normals, shown in red")

    hm_use_z_override: BoolProperty(
        name="Manual Z Range",
        description="Pin black/white points instead of auto-detecting from vertex distribution",
        default=False,
    )
    hm_z_min_override: FloatProperty(name="Z Min (Black)", default=-50.0,
        description="World-space Z that maps to pure black")
    hm_z_max_override: FloatProperty(name="Z Max (White)", default=200.0,
        description="World-space Z that maps to pure white")
    hm_z_percentile_clip: FloatProperty(
        name="Outlier Clip %",
        description="Percent of extreme Z vertices discarded from each end when auto-detecting range",
        default=5.0, min=0.0, max=49.0, subtype="PERCENTAGE",
    )


# ─── Operator ────────────────────────────────────────────────────────────────

class MAPGEO_OT_bake_heightmap(bpy.types.Operator):
    bl_idname  = "mapgeo.bake_heightmap"
    bl_label   = "Bake Heightmap"
    bl_description = (
        "Render a top-down heightmap of the current scene.\n"
        "White→Black = walkable height  |  Green = bushes  |  Red = walls"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.hm_settings
        try:
            result, msg = _bake(settings, context)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return result


# ─── Panel ───────────────────────────────────────────────────────────────────

class MAPGEO_PT_heightmap(bpy.types.Panel):
    bl_label       = "Heightmap Baker"
    bl_idname      = "MAPGEO_PT_heightmap"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "scene"
    bl_category    = "Mapgeo"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.hm_settings

        # ── NavGrid baker (exact game data) ──────────────────────────────
        box = layout.box()
        box.label(text="NavGrid Maps (exact)", icon="GRID")
        row = box.row(align=True)
        row.prop(settings, "ng_path", text="")
        row.operator("mapgeo.detect_navgrid", text="", icon="VIEWZOOM")
        box.prop(settings, "ng_output_path", text="Output")
        row = box.row(align=True)
        row.prop(settings, "ng_scale")
        row = box.row(align=True)
        row.prop(settings, "ng_smooth_height", toggle=True)
        row.prop(settings, "ng_mark_brush", toggle=True)
        box.operator("mapgeo.bake_navgrid_maps",
                     text="Bake NavGrid Maps", icon="RENDER_STILL")
        box.label(text="Writes _height, _walkable, _combined + _meta.json",
                  icon="INFO")

        layout.separator()
        layout.label(text="Legacy Render Baker", icon="RESTRICT_RENDER_OFF")

        # ── Output ────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Output", icon="IMAGE_DATA")
        box.prop(settings, "hm_output_path", text="Path")
        row = box.row(align=True)
        row.prop(settings, "hm_res_x", text="W")
        row.prop(settings, "hm_res_y", text="H")
        box.prop(settings, "hm_padding", text="Border Padding %")

        # ── Layer filter ──────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Layer Filter", icon="RENDERLAYERS")
        box.prop(settings, "hm_dragon_layer_filter", text="Dragon")
        box.prop(settings, "hm_baron_layer_filter", text="Baron")
        box.label(text="Render-region meshes are always excluded.", icon="INFO")

        # ── Colour coding ─────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Colour Coding", icon="COLOR")
        col = box.column(align=True)

        row = col.row()
        row.prop(settings, "hm_include_ground", toggle=True)
        row = col.row()
        row.prop(settings, "hm_include_bush",   toggle=True)
        row = col.row()
        row.prop(settings, "hm_include_walls",  toggle=True)

        box.separator()
        box.label(text="Wall detection: shader name or steep face normals.")
        box.label(text="Bush detection: is_bush custom property.")

        # ── Z range ───────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Height Range (Z)", icon="SORT_ASC")
        box.prop(settings, "hm_use_z_override", toggle=True)
        if settings.hm_use_z_override:
            row = box.row(align=True)
            row.prop(settings, "hm_z_min_override", text="Min (Black)")
            row.prop(settings, "hm_z_max_override", text="Max (White)")
        else:
            box.prop(settings, "hm_z_percentile_clip", text="Outlier Clip %")
            box.label(text="Auto-detects range from vertex Z distribution.")

        # ── Bake ──────────────────────────────────────────────────────────
        layout.separator()
        layout.operator("mapgeo.bake_heightmap", text="Bake Heightmap", icon="RENDER_STILL")


# N-panel mirror (for quick access while in 3D Viewport)
class MAPGEO_PT_heightmap_N(bpy.types.Panel):
    bl_label       = "Heightmap Baker"
    bl_idname      = "MAPGEO_PT_heightmap_N"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "LoL Mapgeo"
    bl_order       = 2
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        MAPGEO_PT_heightmap.draw(self, context)


# ─── Registration ─────────────────────────────────────────────────────────────

classes = (
    HeightmapSettings,
    MAPGEO_OT_detect_navgrid,
    MAPGEO_OT_bake_navgrid_maps,
    MAPGEO_OT_bake_heightmap,
    MAPGEO_PT_heightmap,
    MAPGEO_PT_heightmap_N,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hm_settings = bpy.props.PointerProperty(type=HeightmapSettings)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.hm_settings
