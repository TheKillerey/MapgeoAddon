"""ReyEngine live link - the map's VISIBILITY, mirrored from ReyEngine (protocol 4 ops ``visibility`` and
``visibility_eval``).

ReyEngine decides which mesh is drawn from the Map Visibility layer (dragon state), the Baron Pit state, the
events (MutatorMapVisibilityController), visibility controllers that override the layer bits, render regions and,
on a TFT board, the board stage.  None of that is re-implemented here: this module shows ReyEngine's controls
(the same option lists, labels and defaults, sent by ReyEngine) and ASKS ReyEngine which meshes are drawn for the
selection (``visibility_eval``, ReyEngine's own function), then hides the others with ``hide_viewport`` /
``hide_render``.  So Blender draws exactly the meshes ReyEngine's function says (ReyEngine's per-mesh
eye / disable / delete state is not modelled).  Only the objects of the current pull's root collection are touched,
which OVERRIDES any manual hide the user set on them.

The controls' update callbacks do no socket I/O themselves: they schedule one deferred refresh (bpy.app.timers) so
the UI stays responsive and the callbacks change nothing that undo would record.  ``flush`` runs it at once.

The layer collections of a pull (``<root>_Base``, ``_Infernal`` ...) stay as an outline; they are not what hides
a mesh, because a mesh sits in several of them and a controller can override its bits.  "Sync from ReyEngine"
adopts whatever ReyEngine has selected right now.  Picking a dragon or baron-pit state also picks the matching
navgrid overlay while the navgrid's overlay choice is "Auto" (see reyengine_link_navgrid).
"""

import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

_QUIET = [0]          # > 0 while the add-on itself sets properties, so their update callbacks do nothing
_ITEMS = {}           # json text -> enum items; Blender keeps no copy of dynamic enum strings, so we must


def quiet():
    """Context manager: property writes inside do not trigger a refresh."""
    class _Q:
        def __enter__(self):
            _QUIET[0] += 1

        def __exit__(self, *exc):
            _QUIET[0] -= 1
            return False
    return _Q()


# ---------------------------------------------------------------- the properties

def _axis_items(self, context):
    text = self.options_json
    items = _ITEMS.get(text)
    if items is None:
        try:
            options = json.loads(text) if text else []
        except ValueError:
            options = []
        items = [(str(int(o["bit"])), str(o["label"]), "") for o in options] or [("0", "All", "")]
        _ITEMS[text] = items
    return items


def _stage_items(self, context):
    text = self.vis_stages_json
    items = _ITEMS.get("stage:" + text)
    if items is None:
        try:
            options = json.loads(text) if text else []
        except ValueError:
            options = []
        items = [(str(int(o["index"])), str(o["label"]), "") for o in options] or [("0", "Start", "")]
        _ITEMS["stage:" + text] = items
    return items


_PENDING = set()


def defer(kind):
    """Schedule one refresh ("vis" = visibility + auto navgrid, "nav" = navgrid variant) after the current UI event."""
    if kind in _PENDING:
        return
    _PENDING.add(kind)
    try:
        bpy.app.timers.register(_run_pending, first_interval=0.05)
    except Exception:
        pass


def _run_pending():
    flush(bpy.context)
    return None


def flush(context):
    """Run what ``defer`` scheduled (the timer calls this; background scripts call it directly)."""
    kinds = set(_PENDING)
    _PENDING.clear()
    if "vis" in kinds:
        refresh(context)
    elif "nav" in kinds:
        from . import reyengine_link_navgrid as nav
        nav.reload_now(context)


def _changed(self, context):
    if _QUIET[0]:
        return
    defer("vis")


class ReyVisAxis(bpy.types.PropertyGroup):
    """One Map Visibility axis (Map Visibility, Baron Pit ...) as ReyEngine lists it."""
    axis_id: StringProperty()
    label: StringProperty()
    primary: BoolProperty()
    options_json: StringProperty()
    selected: EnumProperty(name="Layer", items=_axis_items, update=_changed,
                           description="The layer ReyEngine's combo shows for this axis (All = no filter)")


class ReyVisEvent(bpy.types.PropertyGroup):
    """One event (MutatorMapVisibilityController): its content is hidden until it is ticked."""
    name: StringProperty()
    label: StringProperty()
    on: BoolProperty(name="On", default=False, update=_changed)


# The scene-level pieces live on ReyEngineLinkSettings (reyengine_link.py): vis_axes, vis_events, vis_regions,
# vis_regions_available, vis_stages_json, vis_stage, vis_status.


# ---------------------------------------------------------------- the model

def apply_model(settings, model):
    """Adopt a ``visibility`` reply (or the copy a pull carries): option lists and ReyEngine's current selection."""
    with quiet():
        settings.vis_axes.clear()
        for axis in model.get("axes") or []:
            item = settings.vis_axes.add()
            item.axis_id = str(axis.get("id", ""))
            item.label = str(axis.get("name", ""))
            item.primary = bool(axis.get("primary"))
            item.options_json = json.dumps(axis.get("options") or [])
            item.selected = str(int(axis.get("selected", 0) or 0))
        settings.vis_events.clear()
        for ev in model.get("events") or []:
            item = settings.vis_events.add()
            item.name = str(ev.get("name", ""))
            item.label = str(ev.get("label") or ev.get("name", ""))
            item.on = bool(ev.get("on"))
        regions = model.get("render_regions") or {}
        settings.vis_regions_available = bool(regions.get("available"))
        settings.vis_regions = bool(regions.get("enabled"))
        stages = model.get("stages")
        settings.vis_stages_json = json.dumps(stages["options"]) if stages else ""
        settings.vis_stage = str(int(stages.get("selected", 0))) if stages else "0"
    visible = model.get("visible")
    if visible is not None:
        apply_visible(None, visible)


def selection(settings):
    """The selection as ``visibility_eval`` takes it - exactly what the controls show."""
    axes = {}
    for axis in settings.vis_axes:
        axes[axis.axis_id] = int(axis.selected)
    return {
        "axes": axes,
        "events": [e.name for e in settings.vis_events if e.on],
        "render_regions": bool(settings.vis_regions),
        "stage": int(settings.vis_stage) if settings.vis_stages_json else 0,
    }


def _pull_objects():
    """The pulled meshes of the current pull: the objects under its root collection (not every rey_index object
    of the .blend)."""
    from . import reyengine_link as link
    s = link._settings(bpy.context)
    root = bpy.data.collections.get(link._root_name(s.map_path or s.map_name))
    if root is None:
        return link.linked_objects()
    seen, stack, out = set(), [root], []
    while stack:
        col = stack.pop()
        stack.extend(col.children)
        for o in col.objects:
            if o.type == "MESH" and link.INDEX_KEY in o and o.name not in seen:
                seen.add(o.name)
                out.append(o)
    return out


def apply_visible(_scene, visible):
    """Hide every pulled mesh ReyEngine does not draw, show the rest (overrides the user's manual hide)."""
    from . import reyengine_link as link
    shown = set(int(i) for i in visible)
    objs = _pull_objects()
    hidden = 0
    for obj in objs:
        draw = int(obj[link.INDEX_KEY]) in shown
        if obj.hide_viewport == draw:
            obj.hide_viewport = not draw
        if obj.hide_render == draw:
            obj.hide_render = not draw
        hidden += 0 if draw else 1
    return len(objs) - hidden, hidden


# ---------------------------------------------------------------- talking to ReyEngine

def refresh(context):
    """Ask ReyEngine which meshes the current selection draws, apply it, and re-tie the navgrid overlay."""
    from . import reyengine_link as link
    from . import reyengine_link_protocol as wire
    s = link._settings(context)
    if not s.connected:
        s.vis_status = "Connect first: the selection is evaluated by ReyEngine."
        return False
    try:
        with link._connection(context, timeout=20.0) as conn:
            reply, _ = conn.request({"op": "visibility_eval", "selection": selection(s)})
            if not reply.get("found"):
                s.vis_status = reply.get("message") or "ReyEngine could not evaluate the selection"
                return False
            shown, hidden = apply_visible(None, reply.get("visible") or [])
            s.vis_status = "%d meshes drawn, %d hidden (evaluated by ReyEngine)" % (shown, hidden)
            from . import reyengine_link_navgrid as nav
            nav.reload_for_visibility(context, conn)
    except (wire.LinkError, OSError, ValueError) as ex:
        s.vis_status = "ReyEngine: %s" % ex
        return False
    return True


def sync_from_reyengine(context):
    """Adopt ReyEngine's current selection (and which meshes it draws)."""
    from . import reyengine_link as link
    from . import reyengine_link_protocol as wire
    s = link._settings(context)
    with link._connection(context, timeout=60.0) as conn:
        model, _ = conn.request({"op": "visibility"})
        if not model.get("found"):
            raise wire.LinkError(model.get("message") or "ReyEngine has no map open")
        apply_model(s, model)
        s.vis_status = "Synced from ReyEngine: %d meshes drawn" % len(model.get("visible") or [])
        from . import reyengine_link_navgrid as nav
        nav.reload_for_visibility(context, conn)
    return model


class MAPGEO_OT_rey_vis_sync(bpy.types.Operator):
    bl_idname = "mapgeo.rey_vis_sync"
    bl_label = "Sync from ReyEngine"
    bl_description = "Adopt the visibility ReyEngine has selected right now (dragon state, baron pit, events, render regions)"

    def execute(self, context):
        from . import reyengine_link_protocol as wire
        try:
            sync_from_reyengine(context)
        except (wire.LinkError, OSError, ValueError) as ex:
            self.report({"ERROR"}, "ReyEngine: %s" % ex)
            return {"CANCELLED"}
        return {"FINISHED"}


class MAPGEO_OT_rey_vis_apply(bpy.types.Operator):
    bl_idname = "mapgeo.rey_vis_apply"
    bl_label = "Apply Visibility"
    bl_description = "Ask ReyEngine again which meshes the selection draws"

    def execute(self, context):
        return {"FINISHED"} if refresh(context) else {"CANCELLED"}


def draw_panel(layout, context, s):
    box = layout.box()
    box.label(text="Visibility (ReyEngine's)", icon="HIDE_OFF")
    row = box.row(align=True)
    row.enabled = s.connected
    row.operator("mapgeo.rey_vis_sync", icon="FILE_REFRESH")
    row.operator("mapgeo.rey_vis_apply", text="", icon="CHECKMARK")
    if len(s.vis_axes) == 0:
        box.label(text="Pull a map to get ReyEngine's visibility controls.")
        return
    for axis in s.vis_axes:
        box.prop(axis, "selected", text=axis.label)
    if s.vis_stages_json:
        box.prop(s, "vis_stage", text="Board stage")
    if len(s.vis_events) > 0:
        sub = box.box()
        sub.label(text="Events")
        for ev in s.vis_events:
            sub.prop(ev, "on", text=ev.label)
    if s.vis_regions_available:
        box.prop(s, "vis_regions", text="Render regions")
    if s.vis_status:
        box.label(text=s.vis_status)


CLASSES = (ReyVisAxis, ReyVisEvent, MAPGEO_OT_rey_vis_sync, MAPGEO_OT_rey_vis_apply)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
