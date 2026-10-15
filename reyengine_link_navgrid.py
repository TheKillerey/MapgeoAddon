"""ReyEngine live link - the navgrid, SHOWN the way ReyEngine's overlay shows it (protocol 4 op ``navgrid``).

Read-only: nothing here edits the navgrid or sends anything back.  ReyEngine's reply carries the grid (a height
and a u16 flag word per 50-unit cell) and its overlay layers - one per single-bit flag present, commonest
first, with ReyEngine's own label, colour and default visibility - so nothing about the layers is decided here.

Each layer is one object in a "<map>_NavGrid" collection: the layer's cells as two triangles each (the
diagonal shows, as in ReyEngine), lifted ReyEngine's distance above the cell's ground height, drawn as a thin
wireframe (a Wireframe modifier) in the layer colour at the layer's opacity, in front of the map (ReyEngine
draws the overlay without depth testing).  The objects cannot be selected, so they cannot be edited by
accident.  "Show NavGrid" is ReyEngine's overlay switch: turning it on with no layer chosen shows the
commonest layer, as ReyEngine does.
"""

import json
import struct

import bpy
from bpy.props import BoolProperty

LAYER_KEY = "rey_navgrid_mask"     # object property: the layer's flag mask
ORDER_KEY = "rey_navgrid_order"
LABEL_KEY = "rey_navgrid_label"
CELLS_KEY = "rey_navgrid_cells"
GRID_KEY = "rey_navgrid"           # collection property: the grid's path
LAYER_STEP = 0.5                   # extra lift per layer, so later layers draw over earlier ones
WIRE_WIDTH = 2.0                   # world units; a cell is 50 (ReyEngine draws ~1.5 px lines)


def navgrid_collections():
    return [c for c in bpy.data.collections if GRID_KEY in c]


def layer_objects(collection):
    objs = [o for o in collection.objects if LAYER_KEY in o]
    objs.sort(key=lambda o: int(o.get(ORDER_KEY, 0)))
    return objs


def _layer_material(name, color):
    """The layer colour: diffuse_color for Solid shading, emission at the layer alpha for EEVEE.

    Solid shading gets the colour OPAQUE: its transparency pass blends every translucent surface order-free,
    which washes out the colours and mixes layers that share a cell, where ReyEngine draws the later layer
    over the earlier.  The lines are thin, so ReyEngine's 0.8 alpha is a small loss next to that."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    rgba = tuple(float(c) for c in color)
    mat.diffuse_color = (rgba[0], rgba[1], rgba[2], 1.0)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = rgba
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs[0].default_value = rgba[3]
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(emit.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    for attr, value in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        try:
            setattr(mat, attr, value)
        except (AttributeError, TypeError):
            pass
    return mat


def _remove_collection(col):
    for o in list(col.objects):
        mesh = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(col)


def _layer_mesh(name, cells, nx, mn, cs, heights, lift):
    """Two triangles per cell, the cell's own four corners at its height + lift: League (x, y, z) -> Blender
    (x, z, y)."""
    count = len(cells)
    co = [0.0] * (count * 12)
    for k, c in enumerate(cells):
        ix, iz = c % nx, c // nx
        x0, z0 = mn[0] + ix * cs, mn[2] + iz * cs
        h = heights[c] + lift
        co[k * 12:k * 12 + 12] = (x0, z0, h, x0 + cs, z0, h, x0 + cs, z0 + cs, h, x0, z0 + cs, h)
    loops = []
    for k in range(count):
        v = k * 4
        loops += (v, v + 1, v + 2, v, v + 2, v + 3)
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(count * 4)
    mesh.vertices.foreach_set("co", co)
    mesh.loops.add(count * 6)
    mesh.loops.foreach_set("vertex_index", loops)
    mesh.polygons.add(count * 2)
    mesh.polygons.foreach_set("loop_start", list(range(0, count * 6, 3)))
    mesh.update(calc_edges=True)
    mesh.validate()
    return mesh


def build_navgrid(context, header, body, root, show=None):
    """Build the navgrid layers from a ``navgrid`` reply under ``root``.  ``show`` None mirrors ReyEngine's
    overlay (shown when ReyEngine shows a layer).  Returns the collection."""
    nx, nz = int(header["count_x"]), int(header["count_z"])
    n = nx * nz
    cs = float(header["cell_size"])
    mn = header["min"]
    lift = float(header.get("lift", 12.0))
    heights = struct.unpack_from("<%df" % n, body, 0)
    flags = struct.unpack_from("<%dH" % n, body, n * 4)
    layers = header.get("layers") or []

    name = root.name + "_NavGrid"
    # a rebuild (another variant) keeps which layers the user switched on, by flag mask
    previous = {}
    for old in [c for c in root.children if GRID_KEY in c]:
        for o in layer_objects(old):
            previous[int(o[LAYER_KEY])] = bool(o.rey_navgrid_visible)
        _remove_collection(old)
    col = bpy.data.collections.new(name)
    col[GRID_KEY] = header.get("path", "")
    col["rey_navgrid_variant"] = header.get("variant", "")
    root.children.link(col)

    editor_shows = any(bool(layer.get("visible")) for layer in layers)
    for order, layer in enumerate(layers):
        mask = int(layer["mask"])
        color = tuple(float(c) for c in (layer.get("color") or (1, 1, 1, 1)))
        cells = [c for c in range(n) if flags[c] & mask]
        obj_name = "%s 0x%04x" % (name, mask)
        # ReyEngine draws the layers in order without depth testing, so a later layer covers an earlier one on
        # a shared cell; a hair of extra lift per layer gives the same order here
        mesh = _layer_mesh(obj_name, cells, nx, mn, cs, heights, lift + LAYER_STEP * order)
        mesh.materials.append(_layer_material(obj_name, color))
        obj = bpy.data.objects.new(obj_name, mesh)
        obj[LAYER_KEY] = mask
        obj[ORDER_KEY] = order
        obj[LABEL_KEY] = layer.get("label") or "0x%04x" % mask
        obj[CELLS_KEY] = int(layer.get("cells", len(cells)))
        wire_mod = obj.modifiers.new("NavGrid wire", "WIREFRAME")
        wire_mod.thickness = WIRE_WIDTH
        wire_mod.use_replace = True
        obj.show_in_front = True          # ReyEngine draws the overlay without depth testing
        obj.hide_select = True            # shown, never edited
        obj.color = color
        col.objects.link(obj)
        if mask in previous:
            obj.rey_navgrid_visible = previous[mask]
        else:
            obj.rey_navgrid_visible = bool(layer.get("visible")) if editor_shows else bool(layer.get("default_visible"))

    s = context.scene.reyengine_link
    s.navgrid_show = editor_shows if show is None else bool(show)
    master_update(s, context)
    return col


def pull_navgrid(context, conn, root, stats, show=True, variant=None, selection=None):
    """Pull the navgrid.  ``variant`` is a variant id or ``grid:x+overlay:y`` / ``grid:x+auto``; without one,
    ReyEngine serves the grid and overlays it shows right now.  ``selection`` is what ``auto`` is evaluated for."""
    request = {"op": "navgrid"}
    if variant:
        request["variant"] = variant
    if selection is not None:
        request["selection"] = selection
    header, body = conn.request(request, want_body=True)
    if not header.get("found"):
        stats["navgrid"] = header.get("message") or "the map has no navgrid"
        return None
    col = build_navgrid(context, header, body, root, show=show)
    overlays = header.get("overlays") or []
    stats["navgrid"] = "%dx%d cells, %d layer(s) (%s%s)" % (
        header["count_x"], header["count_z"], len(header.get("layers") or []), header.get("path", ""),
        "".join(" + %s" % o.get("label") for o in overlays))
    return col


# ---------------------------------------------------------------- variants

_ITEMS = {}


def _items_of(settings, kind):
    try:
        variants = json.loads(settings.navgrid_variants_json or "[]")
    except ValueError:
        variants = []
    return [v for v in variants if v.get("kind") == kind]


def _grid_items(self, context):
    key = ("grid", self.navgrid_variants_json)
    items = _ITEMS.get(key)
    if items is None:
        items = [(v["id"], v["label"], v.get("detail", "")) for v in _items_of(self, "grid")] or [("none_available", "(none available)", "")]
        _ITEMS[key] = items
    return items


def _overlay_items(self, context):
    key = ("overlay", self.navgrid_variants_json)
    items = _ITEMS.get(key)
    if items is None:
        items = [("auto", "Auto (follows Visibility)", "The overlay of the dragon / baron pit state selected above"),
                 ("none", "None", "")]
        items += [(v["id"], v["label"], v.get("detail", "")) for v in _items_of(self, "overlay")]
        _ITEMS[key] = items
    return items


def variant_changed(self, context):
    """The dropdowns changed: reload after the UI event (no socket I/O inside the callback)."""
    from . import reyengine_link_visibility as vis
    if vis._QUIET[0]:
        return
    vis.defer("nav")


def reload_now(context):
    from . import reyengine_link as link
    from . import reyengine_link_protocol as wire
    s = link._settings(context)
    if not s.connected:
        return
    try:
        with link._connection(context, timeout=30.0) as conn:
            reload_navgrid(context, conn)
    except (wire.LinkError, OSError, ValueError) as ex:
        s.navgrid_status = "ReyEngine: %s" % ex


def apply_variants(settings, reply):
    """Adopt a ``navgrid_variants`` reply: the lists, and the choice ReyEngine currently shows."""
    from . import reyengine_link_visibility as vis
    with vis.quiet():
        settings.navgrid_variants_json = json.dumps(reply.get("variants") or [])
        grids = [v["id"] for v in _items_of(settings, "grid")]
        current = reply.get("current_grid") or reply.get("default_grid") or ""
        if current in grids:
            settings.navgrid_grid = current
        elif grids:
            settings.navgrid_grid = grids[0]
        overlays = ["auto", "none"] + [v["id"] for v in _items_of(settings, "overlay")]
        choice = reply.get("current_overlay") or "auto"
        settings.navgrid_overlay = choice if choice in overlays else "auto"


def variant_spec(settings):
    """``grid:x+auto`` / ``grid:x+none`` / ``grid:x+overlay:y`` for the dropdowns."""
    grid = settings.navgrid_grid or ""
    if grid == "none_available":
        grid = ""
    overlay = settings.navgrid_overlay or "auto"
    return "+".join(p for p in (grid, overlay) if p)


def reload_navgrid(context, conn):
    """Pull the navgrid for the dropdowns' variant (and the visibility selection ``auto`` needs), in place."""
    from . import reyengine_link as link
    from . import reyengine_link_visibility as vis
    s = link._settings(context)
    root = None
    for col in navgrid_collections():
        for parent in bpy.data.collections:
            if col.name in parent.children:
                root = parent
    if root is None:
        root_name = link._root_name(conn.info.get("map_path") or conn.info.get("map"))
        root = bpy.data.collections.get(root_name)
        if root is None:
            root = bpy.data.collections.new(root_name)
            context.scene.collection.children.link(root)
    stats = {}
    selection = vis.selection(s) if len(s.vis_axes) else None
    col = pull_navgrid(context, conn, root, stats, show=s.navgrid_show, variant=variant_spec(s), selection=selection)
    s.navgrid_status = stats.get("navgrid", "")
    return col


def reload_for_visibility(context, conn):
    """A dragon / baron selection changed: with the overlay on Auto, the matching overlay comes along."""
    from . import reyengine_link as link
    s = link._settings(context)
    if navgrid_collections() and (s.navgrid_overlay or "auto") == "auto":
        reload_navgrid(context, conn)


# ---------------------------------------------------------------- visibility

def layer_update(obj, context):
    obj.hide_viewport = not obj.rey_navgrid_visible
    obj.hide_render = not obj.rey_navgrid_visible


def master_update(settings, context):
    """Show NavGrid: ReyEngine's overlay switch.  On with no layer chosen shows the commonest layer."""
    for col in navgrid_collections():
        col.hide_viewport = not settings.navgrid_show
        col.hide_render = not settings.navgrid_show
        objs = layer_objects(col)
        if settings.navgrid_show and objs and not any(o.rey_navgrid_visible for o in objs):
            objs[0].rey_navgrid_visible = True


class MAPGEO_OT_rey_navgrid_pull(bpy.types.Operator):
    bl_idname = "mapgeo.rey_navgrid_pull"
    bl_label = "Pull NavGrid"
    bl_description = "Show the open map's navgrid as ReyEngine's overlay does (read-only)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import reyengine_link as link
        from . import reyengine_link_protocol as wire
        s = link._settings(context)
        stats = {}
        try:
            with link._connection(context, timeout=120.0) as conn:
                root_name = link._root_name(conn.info.get("map_path") or conn.info.get("map"))
                root = bpy.data.collections.get(root_name)
                if root is None:
                    root = bpy.data.collections.new(root_name)
                    context.scene.collection.children.link(root)
                col = pull_navgrid(context, conn, root, stats, show=True)
                variants, _ = conn.request({"op": "navgrid_variants"})
                if variants.get("found"):
                    apply_variants(s, variants)
        except (wire.LinkError, OSError, ValueError) as ex:
            self.report({"ERROR"}, "ReyEngine: %s" % ex)
            return {"CANCELLED"}
        s.navgrid_status = stats.get("navgrid", "")
        if col is None:
            self.report({"WARNING"}, "ReyEngine: %s" % stats.get("navgrid"))
            return {"CANCELLED"}
        self.report({"INFO"}, "NavGrid: %s" % stats["navgrid"])
        return {"FINISHED"}


def draw_panel(layout, context, s):
    box = layout.box()
    box.label(text="NavGrid (read-only)", icon="MESH_GRID")
    row = box.row(align=True)
    row.enabled = s.connected
    row.operator("mapgeo.rey_navgrid_pull", icon="IMPORT")
    if s.navgrid_status:
        box.label(text=s.navgrid_status)
    cols = navgrid_collections()
    if not cols:
        return
    if s.navgrid_variants_json:
        box.prop(s, "navgrid_grid", text="Grid")
        box.prop(s, "navgrid_overlay", text="Overlay")
    box.prop(s, "navgrid_show", text="Show NavGrid")
    for col in cols:
        sub = box.column(align=True)
        sub.active = s.navgrid_show
        for obj in layer_objects(col):
            r = sub.row(align=True)
            r.prop(obj, "rey_navgrid_visible",
                   text="%s  (%d)" % (obj.get(LABEL_KEY, ""), int(obj.get(CELLS_KEY, 0))))
            mat = obj.data.materials[0] if obj.data is not None and obj.data.materials else None
            if mat is not None:
                swatch = r.row()
                swatch.enabled = False
                swatch.scale_x = 0.3
                swatch.prop(mat, "diffuse_color", text="")


CLASSES = (MAPGEO_OT_rey_navgrid_pull,)


def register():
    bpy.types.Object.rey_navgrid_visible = BoolProperty(
        name="Show layer", default=False, update=layer_update,
        description="Show this navgrid layer (the layer switch of ReyEngine's navgrid overlay)")
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    try:
        del bpy.types.Object.rey_navgrid_visible
    except AttributeError:
        pass
