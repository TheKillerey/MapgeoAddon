"""
Mapgeo Debug Tool — Export .mapgeo files to JSON for side-by-side comparison.

Usage from command line (outside Blender):
    python mapgeo_debug.py  original.mapgeo  exported.mapgeo

Produces:
    original.mapgeo.json
    exported.mapgeo.json

The JSON is deterministic (sorted keys, formatted) so you can diff them with
any diff tool (VS Code, Beyond Compare, WinMerge, etc.) to pinpoint the
exact bytes that differ — bucket grids, mesh fields, vertex counts, etc.

Also registers a Blender operator (if imported as an addon module):
    mapgeo.export_debug_json  — file-browser to pick a .mapgeo and dump JSON
"""

import json
import struct
import os
import sys

# ── Standalone helper: reuse mapgeo_parser when available ─────────────────

def _mapgeo_to_dict(filepath: str) -> dict:
    """Parse a .mapgeo file and return a JSON-serialisable dict."""
    # Prefer the addon parser (handles all versions + edge cases)
    try:
        from . import mapgeo_parser
    except ImportError:
        # Standalone usage: import from same directory
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mapgeo_parser",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapgeo_parser.py"))
        mapgeo_parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mapgeo_parser)

    mgeo = mapgeo_parser.MapgeoParser().read(filepath)

    def _vbd(vbd):
        return {
            "usage": vbd.usage,
            "elements": [
                {"name": int(e.name), "format": int(e.format), "offset": e.offset}
                for e in vbd.elements
            ],
        }

    def _vb(vb):
        return {"byte_count": len(vb.data)}

    def _ib(ib):
        import struct
        fmt_char = 'H' if ib.format == 0 else 'I'
        fmt_size = 2 if ib.format == 0 else 4
        count = len(ib.data) // fmt_size
        indices = list(struct.unpack(f'<{count}{fmt_char}', ib.data[:count * fmt_size]))
        return {"index_count": count, "first_10": indices[:10]}

    def _mesh(m):
        d = {
            "name":       m.name,
            "quality":    m.quality,
            "visibility": m.visibility,
            "primitives": [
                {
                    "material":    p.material,
                    "start_index": p.start_index,
                    "index_count": p.index_count,
                    "min_vertex":  p.min_vertex,
                    "max_vertex":  p.max_vertex,
                    "hash":        hex(p.hash) if p.hash else "0x0",
                }
                for p in m.primitives
            ],
            "vertex_buffer_ids":  m.vertex_buffer_ids,
            "index_buffer_id":    m.index_buffer_id,
            "render_flags":       m.render_flags,
            "visibility_controller_path_hash": hex(m.visibility_controller_path_hash),
            "render_region_hash": hex(m.render_region_hash),
            "layer_transition_behavior": m.layer_transition_behavior,
            "transform_matrix":  m.transform_matrix,
        }
        if m.baked_light:
            d["baked_light"] = {
                "texture": m.baked_light.texture,
                "scale":   list(m.baked_light.scale),
                "bias":    list(m.baked_light.bias),
            }
        if m.stationary_light:
            d["stationary_light"] = {
                "texture": m.stationary_light.texture,
                "scale":   list(m.stationary_light.scale),
                "bias":    list(m.stationary_light.bias),
            }
        if m.texture_overrides:
            d["texture_overrides"] = [
                {"index": o.index, "texture": o.texture}
                for o in m.texture_overrides
            ]
        d["baked_paint_scale"] = list(m.baked_paint_scale)
        d["baked_paint_bias"]  = list(m.baked_paint_bias)
        return d

    def _sampler_def(sd):
        return {"index": sd.index, "name": sd.name}

    def _bucket(b):
        return {
            "max_stickout_x":          b.max_stickout_x,
            "max_stickout_z":          b.max_stickout_z,
            "start_index":             b.start_index,
            "base_vertex":             b.base_vertex,
            "inside_face_count":       b.inside_face_count,
            "sticking_out_face_count": b.sticking_out_face_count,
        }

    def _bucket_grid(bg):
        return {
            "path_hash":          hex(bg.path_hash),
            "render_region_hash": hex(bg.render_region_hash),
            "min_x":              bg.min_x,
            "min_z":              bg.min_z,
            "max_x":              bg.max_x,
            "max_z":              bg.max_z,
            "max_stickout_x":     bg.max_stickout_x,
            "max_stickout_z":     bg.max_stickout_z,
            "bucket_size_x":      bg.bucket_size_x,
            "bucket_size_z":      bg.bucket_size_z,
            "buckets_per_side":   bg.buckets_per_side,
            "is_disabled":        bg.is_disabled,
            "flags":              bg.flags,
            "vertex_count":       len(bg.vertices),
            "index_count":        len(bg.indices),
            "face_visibility_flag_count": len(bg.face_visibility_flags),
            "vertices":           [list(v) for v in bg.vertices],
            "indices":            bg.indices,
            "buckets":            [[_bucket(b) for b in row] for row in bg.buckets],
            "face_visibility_flags": bg.face_visibility_flags,
        }

    def _planar_reflector(pr):
        return {
            "transform": pr.transform,
            "plane":     [list(p) for p in pr.plane],
            "normal":    list(pr.normal),
        }

    return {
        "source_file":  os.path.basename(filepath),
        "version":      mgeo.version,
        "vertex_buffer_descriptions": [_vbd(v) for v in mgeo.vertex_buffer_descriptions],
        "vertex_buffer_count":        len(mgeo.vertex_buffers),
        "vertex_buffers":             [_vb(v) for v in mgeo.vertex_buffers],
        "index_buffer_count":         len(mgeo.index_buffers),
        "index_buffers":              [_ib(i) for i in mgeo.index_buffers],
        "mesh_count":                 len(mgeo.meshes),
        "meshes":                     [_mesh(m) for m in mgeo.meshes],
        "sampler_defs":               [_sampler_def(s) for s in mgeo.sampler_defs],
        "bucket_grid_count":          len(mgeo.bucket_grids),
        "bucket_grids":               [_bucket_grid(bg) for bg in mgeo.bucket_grids],
        "planar_reflectors":          [_planar_reflector(pr) for pr in mgeo.planar_reflectors],
        "use_separate_point_lights":  mgeo.use_separate_point_lights,
    }


def mapgeo_to_json_file(mapgeo_path: str, output_path: str = ""):
    """Convert a .mapgeo to a JSON file. Returns the output path."""
    if not output_path:
        output_path = mapgeo_path + ".json"
    data = _mapgeo_to_dict(mapgeo_path)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_path


# ============================================================================
# Blender Operator (only when imported inside Blender)
# ============================================================================

try:
    import bpy
    from bpy.props import StringProperty
    from bpy.types import Operator

    class MAPGEO_OT_export_debug_json(Operator):
        """Export a .mapgeo file to JSON for debugging / diff comparison"""
        bl_idname  = "mapgeo.export_debug_json"
        bl_label   = "Export Mapgeo as JSON"
        bl_options = {'REGISTER'}

        filepath: StringProperty(subtype='FILE_PATH')
        filter_glob: StringProperty(default="*.mapgeo", options={'HIDDEN'})

        def invoke(self, context, event):
            # If no filepath set yet, try to pre-fill from loaded project
            if not self.filepath:
                settings = getattr(context.scene, 'project_settings', None)
                if settings and settings.loaded_mapgeo_path:
                    self.filepath = bpy.path.abspath(settings.loaded_mapgeo_path)
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        def execute(self, context):
            path = self.filepath
            # Fallback: use the loaded mapgeo from project settings
            if not path or not os.path.isfile(path):
                settings = getattr(context.scene, 'project_settings', None)
                if settings and settings.loaded_mapgeo_path:
                    path = bpy.path.abspath(settings.loaded_mapgeo_path)
            if not path or not os.path.isfile(path):
                self.report({'ERROR'}, "No valid .mapgeo file selected.")
                return {'CANCELLED'}
            try:
                out = mapgeo_to_json_file(path)
                self.report({'INFO'}, f"JSON written: {out}")
            except Exception as e:
                self.report({'ERROR'}, f"Failed: {e}")
                return {'CANCELLED'}
            return {'FINISHED'}

    _HAS_BLENDER = True
except ImportError:
    _HAS_BLENDER = False


# ============================================================================
# Registration
# ============================================================================

def register():
    if _HAS_BLENDER:
        bpy.utils.register_class(MAPGEO_OT_export_debug_json)
        print("[Mapgeo Debug] Registered")


def unregister():
    if _HAS_BLENDER:
        bpy.utils.unregister_class(MAPGEO_OT_export_debug_json)
        print("[Mapgeo Debug] Unregistered")


# ============================================================================
# Standalone CLI
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mapgeo_debug.py <file1.mapgeo> [file2.mapgeo ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        if not os.path.isfile(path):
            print(f"File not found: {path}")
            continue
        out = mapgeo_to_json_file(path)
        print(f"  {path}  →  {out}")
