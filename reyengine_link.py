"""ReyEngine live link - the ReyEngine panel in the LoL Mapgeo tab.

MapgeoAddon is ReyEngine's Blender add-on: it replaced the single-file "ReyEngine
Bridge" (reyengine_bridge.py).  ReyEngine serves the open map over loopback
(Tools > Blender link (MapgeoAddon)); this module

* pulls it - meshes with their submesh ranges and materials, UV0, the lightmap
  channel (LightmapUV + raw_lightmap_uv, exactly as the importer stores them),
  vertex colour and normals, every material of the map's materials.bin, and the
  textures those need, fetched from ReyEngine's own mounts into a temporary cache;
* builds the scene with MapgeoAddon's own conventions (collections per visibility
  layer, materials through material_loader);
* pushes changes back as EDITS: transforms, reshaped geometry, material
  assignments and material values edited in MapgeoAddon's material editor.

ReyEngine is the only writer of the .mapgeo and the .materials.bin.  Nothing here
writes a file into the ReyEngine project: every push becomes a pending, undoable
ReyEngine edit that ReyEngine's normal Save writes.

Coordinates: the wire is League space (Y up).  League (x, y, z) -> Blender (x, z, y)
- the importer's swap - which mirrors, so winding is reversed both ways.  Object
transforms convert as B = C @ L @ C^-1, and each object's origin sits on the
ReyEngine mesh's pivot, so rotation and scale round trip exactly.
"""

import json
import os
import tempfile
import time

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from mathutils import Euler, Matrix, Vector

from . import reyengine_link_protocol as wire
from . import reyengine_link_navgrid as _nav_props     # the navgrid's dropdown callbacks (settings below)
from . import reyengine_link_visibility as _vis_props  # ReyEngine's visibility controls (settings below)

ROOT_PREFIX = "ReyLink"
INDEX_KEY = "rey_index"
PIVOT_KEY = "rey_pivot"
SHAPE_KEY = "rey_shape"
SUBMESH_MATERIALS_KEY = "rey_submesh_materials"
SUBMESH_SLOTS_KEY = "rey_submesh_slots"
MATERIAL_SNAPSHOT_KEY = "rey_link_snapshot"
MATERIAL_PROPS = ("samplers", "parameters", "switches", "shader_macros")
GRASS_ATTR = "TEXCOORD5"
RAW_LIGHTMAP_ATTR = "raw_lightmap_uv"

# Summoner's Rift's dragon layers - what the importer names its layer collections.
DEFAULT_LAYERS = [("Base", 1), ("Inferno", 2), ("Mountain", 4), ("Ocean", 8),
                  ("Cloud", 16), ("Hextech", 32), ("Chemtech", 64), ("Void", 128)]

# League -> Blender basis: swap the ground axes, height stays height.  Its own inverse.
L2B = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))).to_4x4()
B2L = L2B


def _addon_version():
    try:
        from . import bl_info
        return ".".join(str(v) for v in bl_info["version"])
    except Exception:
        try:
            import sys
            pkg = sys.modules.get(__package__)
            return ".".join(str(v) for v in pkg.bl_info["version"])
        except Exception:
            return "?"


def _client_name():
    return "MapgeoAddon %s" % _addon_version()


def _settings(context):
    return context.scene.reyengine_link


def _connection(context, timeout=120.0):
    s = _settings(context)
    return wire.Connection(s.host, s.port, client=_client_name(), timeout=timeout, token=s.token)


def _deg(radians):
    return radians * 57.29577951308232


def _rad(degrees):
    return degrees * 0.017453292519943295


def _log(msg):
    print("[ReyEngine link] " + msg)


# ---------------------------------------------------------------- scene helpers

def _cache_key(info):
    """The texture cache folder of one project's map: two projects with a base_srx must not share one."""
    import hashlib
    ident = "%s|%s" % (info.get("project_root") or info.get("project") or "", info.get("map_path") or info.get("map") or "")
    return "%s_%s" % (_root_name(info.get("map_path") or info.get("map")), hashlib.sha1(ident.lower().encode("utf-8")).hexdigest()[:10])


def _root_name(map_name):
    stem = os.path.splitext(os.path.basename(map_name or "map"))[0] or "map"
    return "%s_%s" % (ROOT_PREFIX, stem)


def linked_objects(scene=None):
    """Every object a pull created (it carries the ReyEngine mesh index)."""
    objs = (scene.objects if scene is not None else bpy.data.objects)
    return [o for o in objs if o.type == "MESH" and INDEX_KEY in o]


def _ensure_collection(name, parent):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if parent is not None and col.name not in parent.children:
        parent.children.link(col)
    return col


def _clear_root(root):
    """Remove what an earlier pull built under ``root`` (objects and their meshes)."""
    def walk(col):
        yield col
        for child in col.children:
            yield from walk(child)
    meshes = set()
    for col in list(walk(root)):
        for obj in list(col.objects):
            if obj.type == "MESH" and obj.data is not None:
                meshes.add(obj.data)
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _widen_clipping(context):
    """A League map is ~15,000 units across and Blender's default view clips at 1,000."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type == "VIEW_3D":
                space.clip_start = max(space.clip_start, 1.0)
                space.clip_end = max(space.clip_end, 200000.0)


# ---------------------------------------------------------------- textures

def _texture_requests(materials, mesh_info):
    """Every texture reference the pulled map can ask for: samplers of every material,
    and each mesh's lightmap, baked paint, stationary light and texture overrides."""
    wanted = []
    seen = set()

    def add(path):
        if not path or not isinstance(path, str):
            return
        key = path.replace("\\", "/").lower()
        if key not in seen:
            seen.add(key)
            wanted.append(path)

    for mat in materials.values():
        for s in mat.get("samplerValues", []):
            add(s.get("texturePath"))
    for info in mesh_info:
        add((info.get("lightmap") or {}).get("texture"))
        add((info.get("baked_paint") or {}).get("texture"))
        add(info.get("stationary_light"))
        for path in (info.get("texture_overrides") or {}).values():
            add(path)
    return wanted


def _cache_file(cache_root, header):
    """Where a fetched texture goes so MapgeoAddon's resolver finds it: under
    ``<cache>/assets/`` by its path, or ``<cache>/raw/<hash>.<ext>`` when unnamed.
    None when the answer names a place outside the cache (a '..' or a drive in the path)."""
    path = (header.get("path") or "").replace("\\", "/")
    ext = (header.get("ext") or os.path.splitext(path)[1] or ".tex").lower()
    if ext not in (".tex", ".dds"):
        return None
    if path and not wire_is_link(path):
        rel = path[7:] if path.lower().startswith("assets/") else path
        return wire.safe_cache_path(cache_root, ["assets"] + rel.split("/"))
    link = (header.get("link") or "").lower()
    link = link[2:] if link.startswith("0x") else link
    if len(link) != 16 or any(c not in "0123456789abcdef" for c in link):
        return None
    return wire.safe_cache_path(cache_root, ["raw", link + ext])


def wire_is_link(text):
    t = (text or "").strip()
    return len(t) == 18 and t[:2].lower() == "0x"


def fetch_textures(conn, paths, cache_root):
    """Fetch every texture over the open connection.  Returns (fetched, missing, bytes)."""
    fetched, missing, total = 0, [], 0
    for path in paths:
        try:
            header, body = conn.request({"op": "texture", "path": path}, want_body=True)
        except wire.LinkError as ex:
            missing.append("%s (%s)" % (path, ex))
            continue
        if not header.get("found") or not body:
            missing.append(path)
            continue
        target = _cache_file(cache_root, header)
        if target is None:
            missing.append("%s (refused: the answer names a place outside the cache)" % path)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(body)
        fetched += 1
        total += len(body)
    try:
        from . import wad_links
        wad_links.clear_index()
    except Exception:
        pass
    return fetched, missing, total


# ---------------------------------------------------------------- building the scene

def _league_matrix(entry):
    return (Matrix.Translation(Vector(entry["location"]))
            @ Euler([_rad(a) for a in entry["rotation"]], "XYZ").to_matrix().to_4x4()
            @ Matrix.Diagonal(Vector(entry["scale"])).to_4x4())


def _material_for(loader, materials_db, name, info, lightmap_scale, cache):
    """A Blender material for one (material, mesh) pair, through material_loader - with the
    importer's cache key, so meshes sharing a lightmap atlas share the material."""
    lm = info.get("lightmap") or {}
    bp = info.get("baked_paint") or {}
    lightmap_texture = lm.get("texture") or None
    overrides = dict(info.get("texture_overrides") or {})
    bp_scale = tuple(bp.get("scale") or (1.0, 1.0))
    bp_bias = tuple(bp.get("bias") or (0.0, 0.0))
    key = (name, lightmap_texture, tuple(sorted(overrides.items())), bp_scale, bp_bias)
    mat = cache.get(key)
    if mat is None:
        if name in materials_db and loader is not None:
            mat = loader.get_or_create_material(
                name, materials_db,
                lightmap_texture=lightmap_texture,
                lightmap_color_scale=lightmap_scale,
                texture_overrides=overrides or None,
                baked_paint_scale=bp_scale,
                baked_paint_bias=bp_bias)
        if mat is None:
            mat = bpy.data.materials.get(name) or bpy.data.materials.new(name or "Default")
            mat["league_material_name"] = name
        # what only ReyEngine knows: a Shader Graph material is drawn here with its BASE shader (the node
        # builders know Riot's shaders, not ReyEngine's graphs), and a linked/read-only one refuses edits
        rey = (materials_db.get(name) or {}).get("rey") or {}
        if rey.get("graph"):
            mat["rey_graph"] = str(rey["graph"])
        if rey.get("read_only_reason"):
            mat["rey_read_only"] = str(rey["read_only_reason"])
        snapshot_material(mat)
        cache[key] = mat
    return mat


def snapshot_material(mat):
    """Remember the material's editable state as pulled; a push diffs against it."""
    mat[MATERIAL_SNAPSHOT_KEY] = json.dumps({k: mat.get(k, "") for k in MATERIAL_PROPS})


def build_object(entry, info, collection, layer_collections, regions_collection,
                 loader, materials_db, lightmap_scale, material_cache):
    positions = entry["positions"]
    vertex_count = len(positions) // 3
    indices = entry["indices"]
    wound = wire.reverse_winding(indices)
    face_count = len(wound) // 3

    mesh = bpy.data.meshes.new(entry["name"] or ("mesh_%d" % entry["index"]))
    mesh.from_pydata([(0.0, 0.0, 0.0)] * vertex_count, [],
                     [wound[i:i + 3] for i in range(0, len(wound), 3)])
    # League (x, y, z) -> Blender (x, z, y), once for the whole buffer
    co = [0.0] * len(positions)
    co[0::3] = positions[0::3]
    co[1::3] = positions[2::3]
    co[2::3] = positions[1::3]
    mesh.vertices.foreach_set("co", co)

    # submesh -> material slot, faces -> material_index
    submeshes = entry.get("submeshes") or []
    slots, slot_of = [], {}
    face_slots = [0] * face_count
    submesh_slots = []
    for s in submeshes:
        name = s["material"]
        mat = _material_for(loader, materials_db, name, info, lightmap_scale, material_cache)
        if mat.name not in slot_of:
            slot_of[mat.name] = len(slots)
            slots.append(mat)
        slot = slot_of[mat.name]
        submesh_slots.append(slot)
        first, last = s["start"] // 3, (s["start"] + s["count"]) // 3
        for f in range(first, min(last, face_count)):
            face_slots[f] = slot
    for mat in slots:
        mesh.materials.append(mat)
    if face_count and slots:
        mesh.polygons.foreach_set("material_index", face_slots)
    if len(submeshes) > 1 and face_count:
        prim = [0] * face_count
        for k, s in enumerate(submeshes):
            for f in range(s["start"] // 3, min((s["start"] + s["count"]) // 3, face_count)):
                prim[f] = k
        attr = mesh.attributes.new(name="mapgeo_prim_idx", type="INT", domain="FACE")
        attr.data.foreach_set("value", prim)

    # UV0, in MapgeoAddon's convention (v flipped)
    uvs = entry.get("uvs") or ()
    if len(uvs) == vertex_count * 2 and face_count:
        layer = mesh.uv_layers.new(name="UVMap")
        layer.data.foreach_set("uv", wire.per_loop(wire.flip_v(uvs), wound, 2))

    # TEXCOORD7: LightmapUV in atlas space (as the importer shows it) + the raw channel
    lightmap = entry.get("lightmap_uvs") or ()
    if len(lightmap) == vertex_count * 2 and face_count:
        lm = info.get("lightmap") or {}
        su, sv = (lm.get("scale") or (1.0, 1.0))
        bu, bv = (lm.get("bias") or (0.0, 0.0))
        atlas = [0.0] * len(lightmap)
        for i in range(0, len(lightmap), 2):
            atlas[i] = lightmap[i] * su + bu
            atlas[i + 1] = 1.0 - (lightmap[i + 1] * sv + bv)
        layer = mesh.uv_layers.new(name="LightmapUV")
        layer.data.foreach_set("uv", wire.per_loop(atlas, wound, 2))
        try:
            from .import_mapgeo import RAW_LIGHTMAP_UV_ATTR
        except Exception:
            RAW_LIGHTMAP_UV_ATTR = "raw_lightmap_uv"
        raw = mesh.attributes.new(name=RAW_LIGHTMAP_UV_ATTR, type="FLOAT2", domain="POINT")
        raw.data.foreach_set("vector", list(lightmap))

    colors = entry.get("colors") or ()
    if len(colors) == vertex_count * 4 and face_count:
        attr = mesh.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
        # color_srgb: the bytes as the file holds them, so a push writes back exactly what was pulled
        attr.data.foreach_set("color_srgb", wire.per_loop(colors, wound, 4))

    # TEXCOORD5, the grass clump pivot of a VertexDeform bush: a position, in the vertices' own space
    grass = entry.get("grass_pivots") or ()
    if len(grass) == vertex_count * 3:
        g = [0.0] * len(grass)
        g[0::3] = grass[0::3]
        g[1::3] = grass[2::3]
        g[2::3] = grass[1::3]
        attr = mesh.attributes.new(name=GRASS_ATTR, type="FLOAT_VECTOR", domain="POINT")
        attr.data.foreach_set("vector", g)

    mesh.update()

    normals = entry.get("normals") or ()
    if len(normals) == vertex_count * 3 and face_count:
        try:
            from .import_mapgeo import _safe_set_vertex_normals
            _safe_set_vertex_normals(mesh, [(normals[i], normals[i + 2], normals[i + 1])
                                            for i in range(0, len(normals), 3)], entry["name"])
        except Exception as ex:
            _log("normals skipped on %s: %s" % (entry["name"], ex))

    obj = bpy.data.objects.new(entry["name"] or ("mesh_%d" % entry["index"]), mesh)
    obj[INDEX_KEY] = int(entry["index"])
    obj[PIVOT_KEY] = [float(v) for v in entry["pivot"]]
    obj[SHAPE_KEY] = shape_fingerprint(mesh)
    obj[SUBMESH_MATERIALS_KEY] = json.dumps([s["material"] for s in submeshes])
    obj[SUBMESH_SLOTS_KEY] = json.dumps(submesh_slots)
    if len(submeshes) > 1:
        obj["mapgeo_prim_materials"] = json.dumps([s["material"] for s in submeshes])

    # the importer's custom properties, so its panels read a linked object like an imported one
    obj["visibility_layer"] = int(info.get("visibility", 0) or 0)
    obj["disable_backface_culling"] = int(bool(info.get("disable_backface_culling")))
    if info.get("render_flags"):
        obj["render_flags_text"] = str(info["render_flags"])
    lm = info.get("lightmap") or {}
    if lm:
        obj["lightmap_texture"] = lm.get("texture", "")
        obj["lightmap_scale"] = list(lm.get("scale") or (1.0, 1.0))
        obj["lightmap_bias"] = list(lm.get("bias") or (0.0, 0.0))
    bp = info.get("baked_paint") or {}
    if bp:
        obj["baked_paint_scale"] = list(bp.get("scale") or (1.0, 1.0))
        obj["baked_paint_bias"] = list(bp.get("bias") or (0.0, 0.0))
    if info.get("controller"):
        obj["baron_hash"] = "%08X" % int(info["controller"])
    if info.get("render_region"):
        obj["render_region_hash"] = "%08X" % int(info["render_region"])

    obj.rotation_mode = "XYZ"
    obj.matrix_world = L2B @ _league_matrix(entry) @ B2L

    collection.objects.link(obj)
    vis = int(info.get("visibility", 0) or 0)
    for mask, col in layer_collections:
        if vis & mask:
            col.objects.link(obj)
    if info.get("render_region") and regions_collection is not None:
        regions_collection.objects.link(obj)
    return obj


def pull_map(context, report=None):
    """Pull the open map from ReyEngine and build it.  Returns a stats dict."""
    s = _settings(context)
    started = time.time()
    with _connection(context, timeout=300.0) as conn:
        info = conn.info
        header, body = conn.request({"op": "pull"}, want_body=True)
        meshes = wire.decode_meshes(body)
        mesh_info = {int(m.get("i", -1)): m for m in header.get("meshes", [])}
        mats_reply, _ = conn.request({"op": "materials"})
        materials_db = mats_reply.get("materials") or {}

        cache_root = os.path.join(tempfile.gettempdir(), "reyengine_link", _cache_key(info))
        paths = _texture_requests(materials_db, mesh_info.values())
        fetched, missing, total_bytes = fetch_textures(conn, paths, cache_root)

        # the navgrid comes along (protocol 4, shown read-only); a map without one says so.  Its variants (every
        # grid and state overlay of the map) fill the dropdowns, which start on what ReyEngine shows right now
        nav_header, nav_body = conn.request({"op": "navgrid"}, want_body=True)
        # optional: a failure here must not abort the pull (an older ReyEngine answers an unknown op with an error)
        try:
            nav_variants, _ = conn.request({"op": "navgrid_variants"})
        except wire.LinkError as ex:
            nav_variants = {}
            _log("navgrid variants unavailable: %s" % ex)

    for note in header.get("notes", []):
        if report:
            report({"WARNING"}, "ReyEngine: %s" % note)

    # material_loader resolves texture paths under its assets folder, exactly as for an import
    loader = None
    try:
        from . import material_loader as mat_loader
        loader = mat_loader.MaterialLoader(assets_folder=os.path.join(cache_root, "assets"))
    except Exception as ex:
        _log("material loader unavailable: %s" % ex)

    root_name = _root_name(info.get("map_path") or info.get("map"))
    root = bpy.data.collections.get(root_name)
    if root is None:
        root = bpy.data.collections.new(root_name)
        context.scene.collection.children.link(root)
    else:
        _clear_root(root)
    meshes_col = _ensure_collection(root_name + "_Meshes", root)
    layers = [(l.get("name"), int(l.get("mask", 0))) for l in header.get("layers", []) if l.get("mask")]
    layer_collections = [(mask, _ensure_collection("%s_%s" % (root_name, name), root))
                         for name, mask in (layers or DEFAULT_LAYERS)]
    regions_col = _ensure_collection(root_name + "_RenderRegions", root)

    lightmap_scale = float(mats_reply.get("lightmap_color_scale", header.get("lightmap_color_scale", 1.0)) or 1.0)
    material_cache = {}
    wm = context.window_manager
    wm.progress_begin(0, max(1, len(meshes)))
    built = 0
    try:
        for at, entry in enumerate(meshes):
            try:
                build_object(entry, mesh_info.get(int(entry["index"]), {}), meshes_col,
                             layer_collections, regions_col, loader, materials_db,
                             lightmap_scale, material_cache)
                built += 1
            except Exception as ex:
                _log("mesh %s (%s) failed: %s" % (entry.get("index"), entry.get("name"), ex))
            if at % 64 == 0:
                wm.progress_update(at)
    finally:
        wm.progress_end()

    # ReyEngine's visibility: its controls and its current selection; the meshes it hides are hidden here
    if header.get("visibility") and header["visibility"].get("found", True):
        from . import reyengine_link_visibility as vis
        try:
            vis.apply_model(s, header["visibility"])
            shown = len(header["visibility"].get("visible") or [])
            s.vis_status = "%d of %d meshes drawn (as ReyEngine draws them)" % (shown, len(meshes))
        except Exception as ex:  # the controls are optional; the pull stands
            s.vis_status = "Visibility controls unavailable: %s" % ex
    else:
        s.vis_status = "ReyEngine sent no visibility model: the controls are unavailable."
    if nav_variants.get("found"):
        from . import reyengine_link_navgrid as nav_vars
        nav_vars.apply_variants(s, nav_variants)

    nav_stats = {}
    if nav_header.get("found"):
        from . import reyengine_link_navgrid as nav
        nav.build_navgrid(context, nav_header, nav_body, root)   # shown as ReyEngine shows it right now
        nav_stats["navgrid"] = "%dx%d cells, %d layer(s) (%s)" % (nav_header["count_x"], nav_header["count_z"],
                                                                  len(nav_header.get("layers") or []),
                                                                  nav_header.get("path", ""))
    else:
        nav_stats["navgrid"] = nav_header.get("message") or "the map has no navgrid"
    s.navgrid_status = nav_stats["navgrid"]

    # every map material exists in Blender, so any can be assigned to a slot
    for name in materials_db:
        _material_for(loader, materials_db, name, {}, lightmap_scale, material_cache)

    images_with_data = sum(1 for img in bpy.data.images if img.has_data or img.size[0] > 0)
    _widen_clipping(context)

    stats = {
        "meshes": built, "meshes_sent": len(meshes),
        "materials": len(materials_db),
        "materials_editable": sum(1 for m in materials_db.values() if (m.get("rey") or {}).get("editable")),
        "blender_materials": len({id(m) for m in material_cache.values()}),
        "textures_requested": len(paths), "textures_received": fetched,
        "textures_missing": len(missing), "texture_bytes": total_bytes,
        "images": images_with_data,
        "seconds": round(time.time() - started, 1),
        "root": root_name, "cache": cache_root,
        "navgrid": nav_stats["navgrid"],
    }
    s.last_pull = json.dumps(stats)
    s.map_name = info.get("map", "")
    s.project = info.get("project", "") or ""
    for m in missing[:10]:
        _log("texture not found: %s" % m)
    _log("pulled %(meshes)d/%(meshes_sent)d mesh(es), %(materials)d material(s), "
         "%(textures_received)d/%(textures_requested)d texture(s) in %(seconds)ss" % stats)
    return stats


# ---------------------------------------------------------------- pushing

def _transform_of(obj):
    # matrix_basis is computed from location/rotation/scale on access; matrix_world is only as current as
    # the last depsgraph evaluation (and not evaluated at all for an object outside the view layer). A linked
    # object has no parent, so the two are the same transform.
    world = obj.matrix_basis if obj.parent is None else obj.matrix_world
    league = B2L @ world @ L2B
    location, rotation, scale = league.decompose()
    euler = rotation.to_euler("XYZ")
    entry = {
        "i": int(obj[INDEX_KEY]),
        "loc": [location.x, location.y, location.z],
        "rot": [_deg(euler.x), _deg(euler.y), _deg(euler.z)],
        "scl": [scale.x, scale.y, scale.z],
    }
    if PIVOT_KEY in obj:
        entry["anc"] = [float(v) for v in obj[PIVOT_KEY]]
    return entry


def _league_name(mat):
    if mat is None:
        return None
    return mat.get("league_material_name") or mat.name


def assignment_changes(obj):
    """(assignments, problems): submeshes whose slot now holds another ReyEngine material."""
    try:
        original = json.loads(obj.get(SUBMESH_MATERIALS_KEY, "[]"))
        slots = json.loads(obj.get(SUBMESH_SLOTS_KEY, "[]"))
    except ValueError:
        return [], []
    out, problems = [], []
    for k, (name, slot) in enumerate(zip(original, slots)):
        if slot >= len(obj.material_slots):
            continue
        mat = obj.material_slots[slot].material
        current = _league_name(mat)
        if current is None or current == name:
            continue
        if mat is not None and "league_material_name" not in mat:
            problems.append("%s: '%s' is not a material of the map (only ReyEngine materials can be assigned)"
                            % (obj.name, mat.name))
            continue
        out.append({"mesh": int(obj[INDEX_KEY]), "submesh": k, "material": current})
    return out, problems


def material_changes(materials, owners=None):
    """(edits, notes) for every pulled material whose editable state changed.

    ``owners``, when given, is filled with edit index -> the Blender materials that produced it (variants of
    one ReyEngine material produce the same edit once)."""
    edits, notes, seen = [], [], {}
    for mat in materials:
        if MATERIAL_SNAPSHOT_KEY not in mat or "league_material_name" not in mat:
            continue
        try:
            before = json.loads(mat[MATERIAL_SNAPSHOT_KEY])
        except ValueError:
            continue
        after = {k: mat.get(k, "") for k in MATERIAL_PROPS}
        if before == after:
            continue
        e, n = wire.material_edits(mat["league_material_name"], before, after)
        for edit in e:
            key = json.dumps(edit, sort_keys=True)
            if key not in seen:
                seen[key] = len(edits)
                edits.append(edit)
            if owners is not None:
                owners.setdefault(seen[key], []).append(mat)
        notes.extend(n)
    return edits, notes


def shape_fingerprint(mesh):
    """Coordinates, topology AND each face's material slot: moving faces from one material to another is a
    change of the mesh (its submeshes), even when no vertex moved."""
    import struct
    import zlib
    mats = [0] * len(mesh.polygons)
    mesh.polygons.foreach_get("material_index", mats)
    return "%s:%d" % (wire.fingerprint(mesh), zlib.crc32(struct.pack("<%di" % len(mats), *mats)))


def has_changed_shape(obj):
    if SHAPE_KEY not in obj:
        return True
    if len(obj.modifiers) > 0:
        return True
    stored = str(obj[SHAPE_KEY])
    if ":" not in stored:
        # a .blend pulled with protocol 3 stored the geometry signature alone: compare just that part,
        # or every mesh of an old file would read as changed (and be pushed as a reshape)
        return wire.fingerprint(obj.data) != stored
    return shape_fingerprint(obj.data) != stored


def mesh_to_league(obj):
    """Evaluated, triangulated geometry in League axes, relative to the object origin (the pivot).
    UVs go back in the file's convention (v unflipped)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertex_count, loop_count, tri_count = len(mesh.vertices), len(mesh.loops), len(mesh.loop_triangles)
        if not vertex_count or not tri_count:
            return None
        co = [0.0] * (vertex_count * 3)
        mesh.vertices.foreach_get("co", co)
        no = [0.0] * (vertex_count * 3)
        mesh.vertices.foreach_get("normal", no)
        loop_vertex = [0] * loop_count
        mesh.loops.foreach_get("vertex_index", loop_vertex)
        tri_loops = [0] * (tri_count * 3)
        mesh.loop_triangles.foreach_get("loops", tri_loops)
        tri_material = [0] * tri_count
        mesh.loop_triangles.foreach_get("material_index", tri_material)
        uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.active
        loop_uv = [0.0] * (loop_count * 2)
        if uv_layer:
            uv_layer.data.foreach_get("uv", loop_uv)

        # the channels a reshape keeps (M842): raw lightmap UV and grass pivot per vertex, colour per corner
        raw_lm = None
        attr = mesh.attributes.get(RAW_LIGHTMAP_ATTR)
        if attr is not None and attr.domain == "POINT" and attr.data_type == "FLOAT2":
            raw_lm = [0.0] * (vertex_count * 2)
            attr.data.foreach_get("vector", raw_lm)
        grass = None
        attr = mesh.attributes.get(GRASS_ATTR)
        if attr is not None and attr.domain == "POINT" and attr.data_type == "FLOAT_VECTOR":
            grass = [0.0] * (vertex_count * 3)
            attr.data.foreach_get("vector", grass)
        loop_col = None
        col_attr = mesh.color_attributes.get("Color")
        if col_attr is not None and col_attr.domain == "CORNER":
            loop_col = [0.0] * (loop_count * 4)
            col_attr.data.foreach_get("color_srgb" if col_attr.data_type == "BYTE_COLOR" else "color", loop_col)

        cx, cy, cz = wire.to_league_axes(co)
        nx, ny, nz = wire.to_league_axes(no)
        if grass is not None:
            gx, gy, gz = wire.to_league_axes(grass)
        unique = {}
        positions, normals, uvs, lightmap, colors, pivots = [], [], [], [], [], []
        by_material = {}
        wound = wire.reverse_winding(tri_loops)
        for t in range(tri_count):
            tri = []
            for loop_index in wound[t * 3:t * 3 + 3]:
                v = loop_vertex[loop_index]
                u, w = loop_uv[loop_index * 2], 1.0 - loop_uv[loop_index * 2 + 1]
                c = tuple(round(x, 4) for x in loop_col[loop_index * 4:loop_index * 4 + 4]) if loop_col else ()
                # a vertex with two UVs (or two corner colours) has to become two vertices
                key = (v, round(u, 6), round(w, 6), c)
                at = unique.get(key)
                if at is None:
                    at = len(positions) // 3
                    unique[key] = at
                    positions += (cx[v], cy[v], cz[v])
                    normals += (nx[v], ny[v], nz[v])
                    uvs += (u, w)
                    if raw_lm is not None:
                        lightmap += (raw_lm[v * 2], raw_lm[v * 2 + 1])
                    if loop_col:
                        colors += c
                    if grass is not None:
                        if gx[v] == 0.0 and gy[v] == 0.0 and gz[v] == 0.0:
                            # a vertex added in Blender has no pivot (the attribute defaults to zero, the
                            # object origin): it becomes its own pivot, as ReyEngine reads a missing one
                            pivots += (cx[v], cy[v], cz[v])
                        else:
                            pivots += (gx[v], gy[v], gz[v])
                tri.append(at)
            by_material.setdefault(tri_material[t], []).extend(tri)

        indices, submeshes = [], []
        for slot in sorted(by_material):
            submeshes.append({"slot": slot, "start": len(indices), "count": len(by_material[slot])})
            indices += by_material[slot]
        return {"positions": positions, "normals": normals, "uvs": uvs, "indices": indices,
                "lightmap_uvs": lightmap if raw_lm is not None else [],
                "colors": colors if loop_col else [],
                "grass_pivots": pivots if grass is not None else [],
                "submeshes": submeshes, "materials": sorted(by_material)}
    finally:
        evaluated.to_mesh_clear()


def push_changes(context, transforms=True, materials=True, geometry=True, selected_only=False):
    """Send every change to ReyEngine.  Returns a stats dict (also stored on the scene)."""
    s = _settings(context)
    # matrix_world is only current after a depsgraph update - a script (or a driver) that just set
    # obj.location would otherwise push the old placement
    context.view_layer.update()
    objs = [o for o in linked_objects(context.scene) if not selected_only or o.select_get()]
    stats = {"transforms": 0, "assignments": 0, "material_edits": 0, "geometry": 0,
             "refused": [], "notes": []}
    with _connection(context, timeout=300.0) as conn:
        if transforms and objs:
            header, _ = conn.request({"op": "push", "transforms": [_transform_of(o) for o in objs]})
            stats["transforms"] = int(header.get("applied", 0))
            stats["transform_detail"] = header.get("detail", "")

        if materials:
            assignments, problems = [], []
            for o in objs:
                a, p = assignment_changes(o)
                assignments += a
                problems += p
            stats["notes"] += problems
            if assignments:
                header, _ = conn.request({"op": "assign_material", "assignments": assignments})
                stats["assignments"] = int(header.get("applied", 0))
                stats["refused"] += ["assign: %s - %s" % (r.get("what"), r.get("reason")) for r in header.get("refused", [])]
                refused_index = {int(r.get("index", -1)) for r in header.get("refused", [])}
                # re-baseline what ReyEngine took
                taken = {(a["mesh"], a["submesh"]): a["material"] for i, a in enumerate(assignments) if i not in refused_index}
                for o in objs:
                    names = json.loads(o.get(SUBMESH_MATERIALS_KEY, "[]"))
                    changed = False
                    for k in range(len(names)):
                        if (int(o[INDEX_KEY]), k) in taken:
                            names[k] = taken[(int(o[INDEX_KEY]), k)]
                            changed = True
                    if changed:
                        o[SUBMESH_MATERIALS_KEY] = json.dumps(names)

            pulled = [m for m in bpy.data.materials if MATERIAL_SNAPSHOT_KEY in m]
            owners = {}
            edits, notes = material_changes(pulled, owners)
            stats["notes"] += notes
            if edits:
                header, _ = conn.request({"op": "edit_material", "edits": edits})
                stats["material_edits"] = int(header.get("applied", 0))
                stats["refused"] += ["edit: %s - %s" % (r.get("what"), r.get("reason")) for r in header.get("refused", [])]
                # Re-baseline only the materials ReyEngine took in full. One with a refused edit keeps its old
                # snapshot, so the next push sends it again (the accepted part then answers as unchanged) and
                # the refusal is reported again rather than forgotten.
                refused_index = {int(r.get("index", -1)) for r in header.get("refused", [])}
                blocked = {id(m) for i in refused_index for m in owners.get(i, [])}
                for m in {id(m): m for ms in owners.values() for m in ms}.values():
                    if id(m) not in blocked:
                        snapshot_material(m)
                stats["material_edits_refused"] = len(refused_index)

        if geometry:
            entries, pushed = [], []
            for o in objs:
                if not has_changed_shape(o):
                    continue
                shape = mesh_to_league(o)
                if shape is None:
                    continue
                # one submesh per material slot the faces use, named by the slot's ReyEngine material
                named, bad = [], None
                for sub in shape["submeshes"]:
                    mat = o.material_slots[sub["slot"]].material if sub["slot"] < len(o.material_slots) else None
                    league = _league_name(mat) if mat is not None and "league_material_name" in mat else None
                    if league is None:
                        bad = "faces use slot %d (%s), which holds no ReyEngine material" % (
                            sub["slot"], mat.name if mat is not None else "empty")
                        break
                    named.append({"material": league, "start": sub["start"], "count": sub["count"]})
                if bad:
                    stats["refused"].append("shape: %s - %s" % (o.name, bad))
                    continue
                if len(shape["positions"]) // 3 > wire.MAX_VERTICES_PER_MESH:
                    stats["refused"].append("shape: %s has %d vertices after splitting seams - the limit is %d (16-bit "
                                            "index buffers); split the mesh" % (o.name, len(shape["positions"]) // 3,
                                                                                 wire.MAX_VERTICES_PER_MESH))
                    continue
                entries.append({"name": o.name, "index": int(o[INDEX_KEY]),
                                "pivot": (0.0, 0.0, 0.0), "location": (0.0, 0.0, 0.0),
                                "rotation": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0),
                                "positions": shape["positions"], "normals": shape["normals"],
                                "uvs": shape["uvs"], "indices": shape["indices"],
                                "lightmap_uvs": shape["lightmap_uvs"], "colors": shape["colors"],
                                "grass_pivots": shape["grass_pivots"], "submeshes": named})
                pushed.append(o)
            if entries:
                body = wire.encode_meshes(entries)
                header, _ = conn.request({"op": "push_geometry"}, body=body)
                refused_index = {int(r.get("index", -1)) for r in header.get("refused", [])}
                stats["geometry"] = len(entries) - len(refused_index)
                stats["geometry_detail"] = header.get("detail", "")
                stats["refused"] += ["shape: %s - %s" % (r.get("what"), r.get("reason")) for r in header.get("refused", [])]
                # only what ReyEngine queued counts as sent; a refused shape stays "changed" and is sent again
                for i, o in enumerate(pushed):
                    if i not in refused_index:
                        o[SHAPE_KEY] = shape_fingerprint(o.data)

    s.last_push = json.dumps(stats)
    s.last_refused = json.dumps(stats["refused"])
    _log("pushed %(transforms)d transform(s), %(assignments)d assignment(s), %(material_edits)d material edit(s), "
         "%(geometry)d shape(s)" % stats)
    for line in stats["refused"] + stats["notes"]:
        _log(line)
    return stats


# ---------------------------------------------------------------- operators

class MAPGEO_OT_rey_link_connect(bpy.types.Operator):
    bl_idname = "mapgeo.rey_link_connect"
    bl_label = "Connect to ReyEngine"
    bl_description = "Say hello to the ReyEngine that is serving a map (Tools > Blender link (MapgeoAddon))"

    def execute(self, context):
        s = _settings(context)
        # The token ReyEngine copies when the link starts: taken from the clipboard when the field is empty, so
        # starting the link in ReyEngine and pressing Connect here is the whole ritual.
        if not s.token.strip():
            clip = (context.window_manager.clipboard or "").strip()
            if wire.looks_like_token(clip):
                s.token = clip
        try:
            with _connection(context, timeout=15.0) as conn:
                info = conn.info
        except (wire.LinkError, OSError, ValueError) as ex:
            s.connected = False
            s.status = str(ex)
            self.report({"ERROR"}, "ReyEngine: %s" % ex)
            return {"CANCELLED"}
        s.connected = True
        s.project = info.get("project", "") or ""
        s.map_name = info.get("map", "") or ""
        s.map_path = info.get("map_path", "") or ""
        s.materials_bin = info.get("materials_bin", "") or ""
        ro = info.get("map_read_only_reason") or info.get("materials_read_only_reason") or ""
        s.status = ("Connected to %s %s" % (info.get("app", "ReyEngine"), info.get("app_version") or "")).strip()
        s.read_only = ro
        self.report({"INFO"}, "ReyEngine: %s - %s" % (s.project or "(no project)", s.map_name or "(no map)"))
        return {"FINISHED"}


class MAPGEO_OT_rey_link_disconnect(bpy.types.Operator):
    bl_idname = "mapgeo.rey_link_disconnect"
    bl_label = "Disconnect"
    bl_description = "Forget the ReyEngine connection (the pulled objects stay)"

    def execute(self, context):
        s = _settings(context)
        s.connected = False
        s.status = "Disconnected."
        return {"FINISHED"}


class MAPGEO_OT_rey_link_pull(bpy.types.Operator):
    bl_idname = "mapgeo.rey_link_pull"
    bl_label = "Pull Map"
    bl_description = ("Build the map ReyEngine has open: meshes, materials (through MapgeoAddon's material "
                      "loader) and their textures, fetched from ReyEngine")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            stats = pull_map(context, self.report)
        except (wire.LinkError, OSError, ValueError) as ex:
            self.report({"ERROR"}, "ReyEngine: %s" % ex)
            return {"CANCELLED"}
        self.report({"INFO"}, "ReyEngine: %d mesh(es), %d material(s), %d/%d texture(s)"
                    % (stats["meshes"], stats["materials"], stats["textures_received"], stats["textures_requested"]))
        return {"FINISHED"}


class MAPGEO_OT_rey_link_push(bpy.types.Operator):
    bl_idname = "mapgeo.rey_link_push"
    bl_label = "Push Changes"
    bl_description = ("Send transforms, material assignments, material edits and changed shapes to ReyEngine. "
                      "They become pending ReyEngine edits; ReyEngine's Save writes them")
    bl_options = {"REGISTER"}

    transforms: BoolProperty(name="Transforms", default=True)
    materials: BoolProperty(name="Materials", default=True)
    geometry: BoolProperty(name="Shapes", default=True)
    selected_only: BoolProperty(name="Selected only", default=False)

    def execute(self, context):
        try:
            stats = push_changes(context, self.transforms, self.materials, self.geometry, self.selected_only)
        except (wire.LinkError, OSError, ValueError) as ex:
            self.report({"ERROR"}, "ReyEngine: %s" % ex)
            return {"CANCELLED"}
        summary = ("ReyEngine: %d transform(s), %d assignment(s), %d material edit(s), %d shape(s)"
                   % (stats["transforms"], stats["assignments"], stats["material_edits"], stats["geometry"]))
        if stats["refused"]:
            # one WARNING with every reason (Blender shows the latest report in the status bar, the full text in
            # the Info editor), and the list stays in the ReyEngine panel until the next push
            self.report({"WARNING"}, "ReyEngine refused %d item(s):\n%s" % (len(stats["refused"]), "\n".join(stats["refused"][:30])))
            self.report({"WARNING"}, "%s - %d REFUSED, see the ReyEngine panel" % (summary, len(stats["refused"])))
        else:
            self.report({"INFO"}, summary)
        return {"FINISHED"}


def _navgrid_show_update(self, context):
    from . import reyengine_link_navgrid as nav
    nav.master_update(self, context)


class ReyEngineLinkSettings(bpy.types.PropertyGroup):
    host: StringProperty(name="Host", default=wire.DEFAULT_HOST)
    port: IntProperty(name="Port", default=wire.DEFAULT_PORT, min=1, max=65535)
    token: StringProperty(name="Token", default="",
                          description="The link token ReyEngine shows (Tools menu) and copies when the link starts. "
                                      "Left empty, Connect takes it from the clipboard")
    connected: BoolProperty(default=False)
    status: StringProperty(default="Not connected.")
    project: StringProperty(default="")
    map_name: StringProperty(default="")
    map_path: StringProperty(default="")
    materials_bin: StringProperty(default="")
    read_only: StringProperty(default="")
    last_pull: StringProperty(default="")
    last_push: StringProperty(default="")
    last_refused: StringProperty(default="")
    navgrid_status: StringProperty(default="")
    # protocol 4: ReyEngine's visibility controls (reyengine_link_visibility) and the navgrid's variant lists
    vis_axes: bpy.props.CollectionProperty(type=_vis_props.ReyVisAxis)
    vis_events: bpy.props.CollectionProperty(type=_vis_props.ReyVisEvent)
    vis_regions: BoolProperty(name="Render regions", default=False, update=_vis_props._changed,
                              description="Show the meshes that belong to a render region (ReyEngine's Render Regions switch)")
    vis_regions_available: BoolProperty(default=False)
    vis_stages_json: StringProperty(default="")
    vis_stage: bpy.props.EnumProperty(name="Board stage", items=_vis_props._stage_items, update=_vis_props._changed,
                                      description="A TFT board's stage (ReyEngine's Board stage picker)")
    vis_status: StringProperty(default="")
    navgrid_variants_json: StringProperty(default="")
    navgrid_grid: bpy.props.EnumProperty(
        name="Grid", items=_nav_props._grid_items, update=_nav_props.variant_changed,
        description="Every navigation grid this map ships; Base is the one the open geometry plays on")
    navgrid_overlay: bpy.props.EnumProperty(
        name="Overlay", items=_nav_props._overlay_items, update=_nav_props.variant_changed,
        description="A state overlay shown on top of the grid; Auto follows the dragon / baron pit state selected "
                    "in Visibility")
    navgrid_show: BoolProperty(
        name="Show NavGrid", default=False,
        update=_navgrid_show_update,
        description="Show the pulled navgrid (ReyEngine's navgrid overlay switch); the layers below choose what")


class MAPGEO_PT_reyengine_link(bpy.types.Panel):
    bl_label = "ReyEngine"
    bl_idname = "MAPGEO_PT_reyengine_link"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "LoL Mapgeo"
    bl_order = 4   # after Project Manager, Mapgeo Tools, Heightmap Baker, Asset Finder

    def draw(self, context):
        layout = self.layout
        s = _settings(context)
        row = layout.row(align=True)
        row.prop(s, "host", text="")
        row.prop(s, "port", text="")
        layout.prop(s, "token")
        row = layout.row(align=True)
        if s.connected:
            row.operator("mapgeo.rey_link_connect", text="Reconnect", icon="FILE_REFRESH")
            row.operator("mapgeo.rey_link_disconnect", text="Disconnect", icon="UNLINKED")
        else:
            row.operator("mapgeo.rey_link_connect", text="Connect", icon="LINKED")

        box = layout.box()
        box.label(text=s.status or "Not connected.", icon="CHECKMARK" if s.connected else "INFO")
        if s.connected:
            box.label(text="Project: %s" % (s.project or "-"))
            box.label(text="Map: %s" % (s.map_name or "-"))
            if s.read_only:
                box.label(text="Read-only: %s" % s.read_only, icon="LOCKED")

        col = layout.column(align=True)
        col.enabled = s.connected
        col.operator("mapgeo.rey_link_pull", icon="IMPORT")
        op = col.operator("mapgeo.rey_link_push", icon="EXPORT")
        op.selected_only = False
        op = col.operator("mapgeo.rey_link_push", text="Push Selected")
        op.selected_only = True

        if s.last_pull:
            try:
                p = json.loads(s.last_pull)
                layout.label(text="%d meshes, %d materials, %d/%d textures"
                             % (p["meshes"], p["materials"], p["textures_received"], p["textures_requested"]))
            except (ValueError, KeyError):
                pass
        try:
            refused = json.loads(s.last_refused) if s.last_refused else []
        except ValueError:
            refused = []
        if refused:
            box = layout.box()
            row = box.row()
            row.alert = True
            row.label(text="%d refused by the last push:" % len(refused), icon="ERROR")
            row.operator("mapgeo.rey_link_clear_refused", text="", icon="X")
            for line in refused[:12]:
                box.label(text=line)
            if len(refused) > 12:
                box.label(text="... and %d more (Info editor)" % (len(refused) - 12))

        from . import reyengine_link_visibility as vis
        vis.draw_panel(layout, context, s)
        from . import reyengine_link_navgrid as nav
        nav.draw_panel(layout, context, s)
        layout.label(text="ReyEngine writes the files; Save there.", icon="INFO")


class MAPGEO_OT_rey_link_clear_refused(bpy.types.Operator):
    bl_idname = "mapgeo.rey_link_clear_refused"
    bl_label = "Clear Refusals"
    bl_description = "Hide the list of what ReyEngine refused in the last push"

    def execute(self, context):
        _settings(context).last_refused = ""
        return {"FINISHED"}


CLASSES = (ReyEngineLinkSettings, MAPGEO_OT_rey_link_connect, MAPGEO_OT_rey_link_disconnect,
           MAPGEO_OT_rey_link_pull, MAPGEO_OT_rey_link_push, MAPGEO_OT_rey_link_clear_refused,
           MAPGEO_PT_reyengine_link)


def register():
    _vis_props.register()     # before the settings that hold its property groups
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    from . import reyengine_link_navgrid as nav
    nav.register()
    bpy.types.Scene.reyengine_link = bpy.props.PointerProperty(type=ReyEngineLinkSettings)


def unregister():
    try:
        from . import reyengine_link_navgrid as nav
        nav.unregister()
    except Exception:
        pass
    try:
        del bpy.types.Scene.reyengine_link
    except AttributeError:
        pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _vis_props.unregister()
