"""
Import Operator for Mapgeo Files
Imports .mapgeo files into Blender as mesh objects
"""

import bpy
import bmesh
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Matrix
import struct
import os
import json

from . import mapgeo_parser
from . import utils
from . import material_loader as mat_loader
from . import baron_hash_parser
from .debug_system import get_debug_log

# DEPRECATED: Module-level cache no longer used. Bucket grid data is stored 
# on the BucketGrid collection's "bucket_data_json" custom property instead.
_imported_bucket_grids_cache = {}

# Module-level cache for imported sampler defs (persists in Blender session)
_imported_sampler_defs_cache = []

# Module-level cache for vertex buffer descriptions (preserves multi-stream layout)
_imported_vb_descriptions_cache = []

# Per-mesh vertex declaration info: list of {"decl_id": int, "decl_count": int, "stream_elements": [[elem_names], ...]}
_imported_mesh_vb_layout_cache = []

# Blender version check for performance optimizations
_BLENDER_VERSION = bpy.app.version


def _optimized_mesh_update(mesh):
    """
    Version-aware mesh update with performance optimizations.
    Always validate to clean degenerate geometry that would crash
    normals_split_custom_set_from_vertices at the C level.
    """
    mesh.validate(verbose=False, clean_customdata=False)
    if _BLENDER_VERSION >= (5, 1, 0):
        mesh.update(calc_edges=False)
    else:
        mesh.update()


def _safe_set_vertex_normals(bl_mesh, normals, label="mesh"):
    """
    Safely apply per-vertex custom normals, guarding against the C-level
    crash in normals_split_custom_set_from_vertices that a Python try/except
    cannot catch (EXCEPTION_ACCESS_VIOLATION).

    The crash occurs inside Blender's C code when internal mesh topology
    (loops/polygons) is inconsistent — e.g. after from_pydata + validate
    removed degenerate geometry.  We must prevent the call entirely in
    those cases.

    Validations performed:
    1. Mesh must have polygons and loops (otherwise C code dereferences null).
    2. Every loop's vertex_index must be in range (prevents out-of-bounds).
    3. Normal count must match the Blender mesh vertex count.
    4. Every component must be finite (no NaN / Inf).
    5. No zero-length normal vectors.
    """
    import math

    # ── Topology checks ──────────────────────────────────────────────
    bl_vert_count = len(bl_mesh.vertices)
    if bl_vert_count == 0:
        return False

    n_polys = len(bl_mesh.polygons)
    n_loops = len(bl_mesh.loops)
    if n_polys == 0 or n_loops == 0:
        print(f"[Mapgeo] Skipping normals for {label}: "
              f"no polygons/loops ({n_polys} polys, {n_loops} loops)")
        return False

    # Validate that *every* loop references a valid vertex.
    # A single out-of-range index causes the C-level crash.
    # Reading loop data in bulk is much faster than per-loop access.
    loop_vert_indices = [0] * n_loops
    bl_mesh.loops.foreach_get("vertex_index", loop_vert_indices)
    max_vi = max(loop_vert_indices)
    min_vi = min(loop_vert_indices)
    if max_vi >= bl_vert_count or min_vi < 0:
        print(f"[Mapgeo] Skipping normals for {label}: "
              f"loop vertex_index out of range "
              f"(min={min_vi}, max={max_vi}, verts={bl_vert_count})")
        return False

    # ── Normal count check ───────────────────────────────────────────
    if len(normals) != bl_vert_count:
        print(f"[Mapgeo] Skipping normals for {label}: "
              f"count mismatch (normals={len(normals)}, "
              f"bl_verts={bl_vert_count})")
        return False

    # ── Sanitise normal values ───────────────────────────────────────
    sanitised = []
    fallback = (0.0, 0.0, 1.0)  # safe default pointing up
    bad_indices = []
    for i, n in enumerate(normals):
        nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
        if not (math.isfinite(nx) and math.isfinite(ny) and math.isfinite(nz)):
            sanitised.append(fallback)
            bad_indices.append(i)
            continue
        length_sq = nx * nx + ny * ny + nz * nz
        if length_sq < 1e-12:
            sanitised.append(fallback)
            bad_indices.append(i)
            continue
        sanitised.append((nx, ny, nz))

    # Recalculate bad normals from face geometry instead of using static fallback
    if bad_indices:
        bad_set = set(bad_indices)
        # Accumulate face normals for each bad vertex
        accum = {vi: [0.0, 0.0, 0.0] for vi in bad_set}
        for poly in bl_mesh.polygons:
            pn = poly.normal
            if pn.length_squared < 1e-12:
                continue
            for vi in poly.vertices:
                if vi in bad_set:
                    accum[vi][0] += pn.x
                    accum[vi][1] += pn.y
                    accum[vi][2] += pn.z
        for vi in bad_indices:
            ax, ay, az = accum[vi]
            l_sq = ax * ax + ay * ay + az * az
            if l_sq > 1e-12:
                inv_l = 1.0 / math.sqrt(l_sq)
                sanitised[vi] = (ax * inv_l, ay * inv_l, az * inv_l)
            # else: keeps the (0,0,1) fallback

        print(f"[Mapgeo] {label}: recalculated {len(bad_indices)}/{len(normals)} "
              f"bad normals (NaN/Inf/zero-length) from face geometry")
    

    try:
        bl_mesh.normals_split_custom_set_from_vertices(sanitised)
        return True
    except Exception as e:
        print(f"[Mapgeo] Warning: Failed to set custom normals for {label}: {e}")
        return False


def _extract_visibility_controller_layers(materials_path: str) -> dict:
    """
    Extract layer→hash mappings from materials.bin visibility controllers.
    
    Uses BaronHashParser to load and index controllers, then maps each
    layer bit to its corresponding path_hash.
    
    Args:
        materials_path: Path to materials.py or materials.bin
        
    Returns: 
        dict[layer_bit: int] → path_hash: int
        Example: {1: 0x12345678, 2: 0xABCDEF00, ...}
    """
    if not materials_path or not os.path.exists(materials_path):
        return {}
    
    layer_map = {}

    try:
        # Use BaronHashParser to load materials
        parser = baron_hash_parser.MaterialsBinParser(materials_path)

        if not parser.controllers:
            return {}

        seen_hashes = set()

        # Walk through indexed controllers to find layer→hash mappings
        for path_hash_str in parser.controllers.keys():
            if not isinstance(path_hash_str, str):
                continue

            cleaned = path_hash_str.strip().strip("{}")
            if cleaned.lower().startswith("0x"):
                cleaned = cleaned[2:]

            if len(cleaned) != 8:
                continue

            try:
                path_hash = int(cleaned, 16)
            except ValueError:
                continue

            cleaned_upper = cleaned.upper()
            if cleaned_upper in seen_hashes:
                continue
            seen_hashes.add(cleaned_upper)

            controller = parser.decode_baron_hash(cleaned_upper)

            for layer_bit in controller.dragon_layers:
                if layer_bit not in layer_map:  # First match wins
                    layer_map[layer_bit] = path_hash

            for baron_bit in controller.baron_layers:
                if baron_bit not in layer_map:  # First match wins
                    layer_map[baron_bit] = path_hash

    except Exception as e:
        log = get_debug_log()
        log.warning("BucketGrid", f"Error extracting visibility controller layers: {e}")

    return layer_map


def _resolve_materials_path(settings, mapgeo_filepath: str = "") -> str:
    """Return the materials file path taking linked-materials mode into account.

    When ``use_linked_materials`` is enabled the function searches the same
    directory as the .mapgeo file for a matching materials file:
        base.mapgeo  ->  base.materials.bin

    Falls back to the manually-specified ``materials_file_path`` if linked
    mode is off or no linked file can be found.
    """
    log = get_debug_log()
    use_linked = getattr(settings, 'use_linked_materials', False)

    if use_linked and mapgeo_filepath:
        mapgeo_dir = os.path.dirname(mapgeo_filepath)
        mapgeo_base = os.path.splitext(os.path.basename(mapgeo_filepath))[0]

        # Try matching .materials.bin
        candidates = [
            os.path.join(mapgeo_dir, mapgeo_base + ".materials.bin"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                log.info("Material", f"Linked materials found: {candidate}")
                return candidate

        # Also scan the directory for any materials .bin file
        for fname in os.listdir(mapgeo_dir):
            if fname.endswith('.materials.bin'):
                found = os.path.join(mapgeo_dir, fname)
                log.info("Material", f"Linked materials fallback found: {found}")
                return found

        log.warning("Material", f"No materials file found next to {os.path.basename(mapgeo_filepath)}")

    # Fall back to manually specified path
    manual = getattr(settings, 'materials_file_path', '')
    return manual if manual else ""


class IMPORT_SCENE_OT_mapgeo(bpy.types.Operator, ImportHelper):
    """Import League of Legends Mapgeo file"""
    bl_idname = "import_scene.mapgeo"
    bl_label = "Import Mapgeo"
    bl_options = {'REGISTER', 'UNDO'}
    
    # File browser filter
    filename_ext = ".mapgeo"
    filter_glob: StringProperty(
        default="*.mapgeo",
        options={'HIDDEN'},
    )
    
    # Import options
    import_materials: BoolProperty(
        name="Import Materials",
        description="Create materials from mapgeo data",
        default=True,
    )
    
    import_vertex_colors: BoolProperty(
        name="Import Vertex Colors",
        description="Import vertex color data",
        default=True,
    )
    
    import_normals: BoolProperty(
        name="Import Normals",
        description="Import custom vertex normals",
        default=True,
    )
    
    import_lightmaps: BoolProperty(
        name="Import Lightmaps",
        description="Load baked lightmap textures and multiply with diffuse for Riot-accurate lighting",
        default=True,
    )
    
    import_bucket_grid: BoolProperty(
        name="Import Bucket Grid",
        description="Import bucket grid scene graph data for spatial partitioning visualization",
        default=True,
    )

    import_particles: BoolProperty(
        name="Import Particles",
        description="Import MapParticle entries from linked materials file",
        default=True,
    )
    
    merge_by_layer: BoolProperty(
        name="Group by Layer",
        description="Group meshes by visibility layer",
        default=False,
    )
    
    scale_factor: bpy.props.FloatProperty(
        name="Scale",
        description="Scale factor for import",
        default=1.0,
        min=0.001,
        max=1000.0,
    )
    
    # Modal execution state for background mode
    _timer = None
    _background_task = None
    _background_step = 0
    
    def execute(self, context):
        """Execute the import"""
        log = get_debug_log()
        log.begin_session()
        
        # Configure debug logging based on user preference
        settings = context.scene.mapgeo_settings
        log.enabled = settings.debug_logging
        
        # Check execution mode for progress display
        show_progress = (settings.execution_mode == 'BACKGROUND')
        
        try:
            if show_progress:
                context.window_manager.progress_begin(0, 100)
                context.window_manager.progress_update(5)
            
            # Update settings
            settings.last_import_path = self.filepath
            
            if show_progress:
                context.window_manager.progress_update(10)
            
            # Parse the mapgeo file
            parser = mapgeo_parser.MapgeoParser()
            mapgeo = parser.read(self.filepath)
            
            if show_progress:
                context.window_manager.progress_update(20)
            
            # Cache sampler defs for export round-trip
            global _imported_sampler_defs_cache
            _imported_sampler_defs_cache = [
                {"index": sd.index, "name": sd.name}
                for sd in mapgeo.sampler_defs
            ]
            if _imported_sampler_defs_cache:
                log.info("Import", f"Cached {len(_imported_sampler_defs_cache)} sampler defs for export")
            
            # Cache vertex buffer descriptions for export round-trip
            global _imported_vb_descriptions_cache
            _imported_vb_descriptions_cache = []
            for desc in mapgeo.vertex_buffer_descriptions:
                desc_data = {
                    "usage": desc.usage,
                    "elements": [{"name": e.name, "format": e.format, "offset": e.offset} for e in desc.elements]
                }
                _imported_vb_descriptions_cache.append(desc_data)
            log.info("Import", f"Cached {len(_imported_vb_descriptions_cache)} vertex buffer descriptions")
            
            # Cache per-mesh vertex buffer layout for export round-trip
            global _imported_mesh_vb_layout_cache
            _imported_mesh_vb_layout_cache = []
            for mesh_data in mapgeo.meshes:
                layout = {
                    "decl_id": mesh_data.vertex_declaration_id,
                    "decl_count": mesh_data.vertex_declaration_count,
                }
                # Store which element names belong to each stream
                stream_elements = []
                for stream_idx in range(mesh_data.vertex_declaration_count):
                    desc_id = mesh_data.vertex_declaration_id + stream_idx
                    if desc_id < len(mapgeo.vertex_buffer_descriptions):
                        desc = mapgeo.vertex_buffer_descriptions[desc_id]
                        stream_elements.append([e.name for e in desc.elements])
                    else:
                        stream_elements.append([])
                layout["stream_elements"] = stream_elements
                _imported_mesh_vb_layout_cache.append(layout)
            log.info("Import", f"Cached vertex buffer layout for {len(_imported_mesh_vb_layout_cache)} meshes")
            
            if show_progress:
                context.window_manager.progress_update(30)
            
            # Import into Blender
            import time as _time
            _t0 = _time.perf_counter()
            imported_materials = self.import_mapgeo(context, mapgeo, show_progress=show_progress)
            print(f"[TIMING] import_mapgeo: {_time.perf_counter() - _t0:.2f}s")

            if show_progress:
                context.window_manager.progress_update(70)

            # Preserve source materials path for round-trip export
            _t1 = _time.perf_counter()
            # (No longer needed — .py format removed, .bin is handled by prey system)
            print(f"[TIMING] preserve_other_entries: {_time.perf_counter() - _t1:.2f}s")

            # Auto-import particles from materials file when available
            _t2 = _time.perf_counter()
            if self.import_particles:
                try:
                    resolved_materials = _resolve_materials_path(settings, self.filepath)
                    if resolved_materials:
                        from . import particles_materials
                        log.info("Particles", f"Importing particles from {os.path.basename(resolved_materials)}")
                        imported_particles = particles_materials.import_particles_from_materials(
                            context,
                            resolved_materials,
                            log=log,
                        )
                        if imported_particles:
                            log.info("Particles", f"Imported {imported_particles} particle(s)")
                except Exception as e:
                    log.warning("Particles", f"Particle import skipped: {e}")
            print(f"[TIMING] particle_import: {_time.perf_counter() - _t2:.2f}s")

            # Auto-import GdsMapObject entries from materials file
            _t2b = _time.perf_counter()
            if self.import_particles:
                try:
                    resolved_materials = _resolve_materials_path(settings, self.filepath)
                    if resolved_materials:
                        from . import map_objects_import
                        log.info("MapObjects", f"Importing map objects from {os.path.basename(resolved_materials)}")
                        imported_mo = map_objects_import.import_map_objects_from_materials(
                            context,
                            resolved_materials,
                            log=log,
                        )
                        if imported_mo:
                            log.info("MapObjects", f"Imported {imported_mo} map object(s)")
                except Exception as e:
                    log.warning("MapObjects", f"Map object import skipped: {e}")
            print(f"[TIMING] map_objects_import: {_time.perf_counter() - _t2b:.2f}s")

            if show_progress:
                context.window_manager.progress_update(80)

            # NOTE: We intentionally skip refresh_league_materials() here.
            # material_loader.create_blender_material() already builds full
            # shader-specific node trees (glass, water, hologram, glow, etc.)
            # with textures loaded.  Calling refresh_league_materials() would
            # clear every node tree and rebuild it from scratch — including
            # re-resolving and re-loading all textures — which doubles import
            # time and makes the import appear hung on large maps.
            
            # Update visibility based on current dragon/baron layer filters
            _t3 = _time.perf_counter()
            try:
                import sys
                addon_module = sys.modules.get(__package__)
                if addon_module and hasattr(addon_module, 'update_environment_visibility'):
                    settings = context.scene.mapgeo_settings
                    addon_module.update_environment_visibility(settings, context)
                else:
                    log.warning("Import", "update_environment_visibility not found")
            except Exception as e:
                log.warning("Import", f"Could not update visibility: {e}")
            print(f"[TIMING] update_visibility: {_time.perf_counter() - _t3:.2f}s")
            
            if show_progress:
                context.window_manager.progress_update(90)
            
            # Set viewport clipping for large maps
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.clip_start = 10
                            space.clip_end = 10000000
            
            if show_progress:
                context.window_manager.progress_update(100)
                context.window_manager.progress_end()
            
            print(f"[TIMING] TOTAL post-mesh: {_time.perf_counter() - _t0:.2f}s")
            log.end_session()
            # Build a concise status line for the user
            s = log.stats
            status = f"Imported {os.path.basename(self.filepath)}: {s.meshes_imported} meshes, {s.textures_loaded} textures"
            issues = log.error_count + log.warning_count
            if issues:
                status += f" ({issues} issues — see Debug Log)"
            self.report({'INFO'}, status)
            return {'FINISHED'}
        
        except Exception as e:
            if show_progress:
                context.window_manager.progress_end()
            log.end_session()
            self.report({'ERROR'}, f"Failed to import mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        """Handle operator invocation - check execution mode"""
        settings = context.scene.mapgeo_settings
        
        # Always start with file browser
        context.window_manager.fileselect_add(self)
        
        # Check if background mode will be used
        if settings.execution_mode == 'BACKGROUND':
            # Will switch to modal after file selection
            return {'RUNNING_MODAL'}
        else:
            # Standard foreground execution after file selection
            return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        """Handle modal execution for background processing"""
        settings = context.scene.mapgeo_settings
        
        # If we have an active background task, process it
        if self._background_task:
            if event.type == 'TIMER':
                # Process one step of the background task
                try:
                    progress = next(self._background_task)
                    # Update progress indicator
                    context.area.header_text_set(f"Importing: {int(progress)}%")
                    return {'RUNNING_MODAL'}
                except StopIteration:
                    # Task complete
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                    context.area.header_text_set(None)
                    self._background_task = None
                    return {'FINISHED'}
                except Exception as e:
                    # Task failed
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                    context.area.header_text_set(None)
                    self._background_task = None
                    self.report({'ERROR'}, f"Import failed: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return {'CANCELLED'}
            return {'RUNNING_MODAL'}
        
        # File browser is still open or just closed
        if not self.filepath:
            return {'RUNNING_MODAL'}
        
        # File selected - check execution mode
        if settings.execution_mode == 'BACKGROUND':
            # Start background processing with timer
            self._timer = context.window_manager.event_timer_add(0.001, window=context.window)
            self._background_task = self._execute_background(context)
            return {'RUNNING_MODAL'}
        else:
            # Execute immediately in foreground
            return self.execute(context)
    
    def _execute_background(self, context):
        """Generator function that yields progress for background execution"""
        log = get_debug_log()
        log.begin_session()
        
        settings = context.scene.mapgeo_settings
        log.enabled = settings.debug_logging
        
        try:
            yield 5
            
            # Update settings
            settings.last_import_path = self.filepath
            
            yield 10
            
            # Parse the mapgeo file
            parser = mapgeo_parser.MapgeoParser()
            mapgeo = parser.read(self.filepath)
            
            yield 20
            
            # Cache sampler defs, vertex buffer descriptions, etc.
            global _imported_sampler_defs_cache, _imported_vb_descriptions_cache, _imported_mesh_vb_layout_cache
            
            _imported_sampler_defs_cache = [
                {"index": sd.index, "name": sd.name}
                for sd in mapgeo.sampler_defs
            ]
            
            _imported_vb_descriptions_cache = []
            for desc in mapgeo.vertex_buffer_descriptions:
                desc_data = {
                    "usage": desc.usage,
                    "elements": [{"name": e.name, "format": e.format, "offset": e.offset} for e in desc.elements]
                }
                _imported_vb_descriptions_cache.append(desc_data)
            
            _imported_mesh_vb_layout_cache = []
            for mesh_data in mapgeo.meshes:
                layout = {
                    "decl_id": mesh_data.vertex_declaration_id,
                    "decl_count": mesh_data.vertex_declaration_count,
                }
                stream_elements = []
                for stream_idx in range(mesh_data.vertex_declaration_count):
                    desc_id = mesh_data.vertex_declaration_id + stream_idx
                    if desc_id < len(mapgeo.vertex_buffer_descriptions):
                        desc = mapgeo.vertex_buffer_descriptions[desc_id]
                        stream_elements.append([e.name for e in desc.elements])
                    else:
                        stream_elements.append([])
                layout["stream_elements"] = stream_elements
                _imported_mesh_vb_layout_cache.append(layout)
            
            yield 30
            
            # Import meshes (this is the heavy part - yield periodically)
            imported_materials = self.import_mapgeo(context, mapgeo, show_progress=False, yield_func=lambda p: None)
            
            yield 70
            
            # Preserve materials path (no-op — .py format removed)
            # .bin is handled by prey system
            
            # Import particles
            if self.import_particles:
                try:
                    resolved_materials = _resolve_materials_path(settings, self.filepath)
                    if resolved_materials:
                        from . import particles_materials
                        imported_particles = particles_materials.import_particles_from_materials(
                            context, resolved_materials, log=log
                        )
                except Exception as e:
                    log.warning("Particles", f"Particle import skipped: {e}")

            # Import GdsMapObject entries
            if self.import_particles:
                try:
                    resolved_materials = _resolve_materials_path(settings, self.filepath)
                    if resolved_materials:
                        from . import map_objects_import
                        map_objects_import.import_map_objects_from_materials(
                            context, resolved_materials, log=log
                        )
                except Exception as e:
                    log.warning("MapObjects", f"Map object import skipped: {e}")

            yield 80
            
            # Update visibility
            try:
                import sys
                addon_module = sys.modules.get(__package__)
                if addon_module and hasattr(addon_module, 'update_environment_visibility'):
                    addon_module.update_environment_visibility(settings, context)
            except Exception as e:
                log.warning("Import", f"Could not update visibility: {e}")
            
            yield 90
            
            # Set viewport clipping
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.clip_start = 10
                            space.clip_end = 10000000
            
            yield 95
            
            log.end_session()
            s = log.stats
            status = f"Imported {os.path.basename(self.filepath)}: {s.meshes_imported} meshes, {s.textures_loaded} textures"
            issues = log.error_count + log.warning_count
            if issues:
                status += f" ({issues} issues — see Debug Log)"
            self.report({'INFO'}, status)
            
            yield 100
            
        except Exception as e:
            log.end_session()
            self.report({'ERROR'}, f"Failed to import mapgeo: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def import_mapgeo(self, context, mapgeo: mapgeo_parser.MapgeoFile, show_progress=False):
        """Import mapgeo data into Blender"""
        log = get_debug_log()
        
        # Use fixed root collection name from settings (not filename)
        settings = context.scene.mapgeo_settings
        collection_name = settings.root_collection_name if settings.root_collection_name else "rey_map"
        collection = bpy.data.collections.new(collection_name)
        context.scene.collection.children.link(collection)
        
        # Create a "Meshes" sub-collection to hold all actual mesh objects
        meshes_collection = bpy.data.collections.new(f"{collection_name}_Meshes")
        collection.children.link(meshes_collection)
        
        # Layer names for Summoner's Rift
        layer_names = {
            mapgeo_parser.EnvironmentVisibility.LAYER_1: "Base",
            mapgeo_parser.EnvironmentVisibility.LAYER_2: "Inferno",
            mapgeo_parser.EnvironmentVisibility.LAYER_3: "Mountain",
            mapgeo_parser.EnvironmentVisibility.LAYER_4: "Ocean",
            mapgeo_parser.EnvironmentVisibility.LAYER_5: "Cloud",
            mapgeo_parser.EnvironmentVisibility.LAYER_6: "Hextech",
            mapgeo_parser.EnvironmentVisibility.LAYER_7: "Chemtech",
            mapgeo_parser.EnvironmentVisibility.LAYER_8: "Void",
        }
        
        # Always create layer collections for organization
        layer_collections = {}
        for layer_flag, layer_name in layer_names.items():
            layer_col = bpy.data.collections.new(f"{collection_name}_{layer_name}")
            collection.children.link(layer_col)
            layer_collections[layer_flag] = layer_col
        
        # Create baron state collections for baron hash visibility
        # Use bit values (1, 2, 4, 8) to match the 0x8bff8cdf property in materials.bin
        baron_state_names = {
            1: "BaronBase",
            2: "BaronCup",
            4: "BaronTunnel",
            8: "BaronUpgraded"
        }
        baron_collections = {}
        for state_bit, state_name in baron_state_names.items():
            baron_col = bpy.data.collections.new(f"{collection_name}_{state_name}")
            collection.children.link(baron_col)
            baron_collections[state_bit] = baron_col
        
        # Create Bush and RenderRegion collections
        bushes_collection = bpy.data.collections.new(f"{collection_name}_Bushes")
        collection.children.link(bushes_collection)
        render_regions_collection = bpy.data.collections.new(f"{collection_name}_RenderRegions")
        collection.children.link(render_regions_collection)
        
        log.info("Import", f"Importing {len(mapgeo.meshes)} meshes from {collection_name}")
        log.info("Import", f"Vertex buffers: {len(mapgeo.vertex_buffers)}, Index buffers: {len(mapgeo.index_buffers)}, Descriptions: {len(mapgeo.vertex_buffer_descriptions)}")
        
        # Store materials
        materials = {}
        
        # Load materials from file if available
        materials_db = {}
        material_loader = None
        baron_parser = None
        map_settings = {}
        settings = context.scene.mapgeo_settings
        
        # Resolve materials path (linked mode or manual)
        resolved_materials = _resolve_materials_path(settings, self.filepath)
        if resolved_materials:
            settings.materials_file_path = resolved_materials

        # Check for prey-based loading (set by Project Manager)
        prey_dir = getattr(settings, 'prey_materials_dir', '') or ''
        prey_base = getattr(settings, 'prey_materials_base', '') or ''
        use_prey = bool(prey_dir and prey_base and os.path.isfile(
            os.path.join(prey_dir, f"{prey_base}.prey.materials")))

        if use_prey:
            has_original_assets = settings.assets_folder and os.path.exists(settings.assets_folder)
            has_custom_assets = settings.custom_assets_folder and os.path.exists(settings.custom_assets_folder)

            if not has_original_assets and not has_custom_assets:
                log.warning("Material", "Assets folder not set or doesn't exist — materials will be created without textures")

            log.info("Material", f"Loading materials from prey: {prey_base}.prey.materials")
            if has_original_assets:
                log.info("Material", f"Original assets folder: {settings.assets_folder}")
            if has_custom_assets:
                log.info("Material", f"Custom assets folder (fallback): {settings.custom_assets_folder}")

            material_loader = mat_loader.MaterialLoader(
                assets_folder=settings.assets_folder if has_original_assets else "",
                levels_folder=settings.levels_folder if hasattr(settings, 'levels_folder') else "",
                map_py_path=settings.map_py_path if hasattr(settings, 'map_py_path') else "",
                dragon_layer=settings.dragon_layer_filter if hasattr(settings, 'dragon_layer_filter') else "LAYER_1",
                custom_assets_folder=settings.custom_assets_folder if has_custom_assets else "",
                prioritize_custom=settings.prioritize_custom_assets if hasattr(settings, 'prioritize_custom_assets') else False,
            )
            materials_db = material_loader.load_materials_from_prey(
                prey_dir, prey_base, materials_path=resolved_materials or "")

            # Load map settings from prey
            from . import prey_format as _prey_fmt
            map_settings = _prey_fmt.load_prey_map_settings(prey_dir, prey_base)

            # Fall back to loading directly from bin if prey had no sun/fog data
            if not map_settings.get('sun_direction') and resolved_materials and os.path.exists(resolved_materials):
                from . import project_manager as _pm
                bin_settings = _pm.load_map_settings_from_bin(resolved_materials)
                if bin_settings:
                    log.info("MapSettings", "Prey map settings missing sun data, loaded from bin directly")
                    # Merge: bin values fill in any gaps
                    for k, v in bin_settings.items():
                        if k not in map_settings:
                            map_settings[k] = v

            # Baron hash parser still needs the original materials file
            if resolved_materials and os.path.exists(resolved_materials):
                baron_parser = baron_hash_parser.MaterialsBinParser(resolved_materials)
                log.info("Import", "Baron hash parser initialized (from original materials)")

        elif resolved_materials and os.path.exists(resolved_materials):
            has_original_assets = settings.assets_folder and os.path.exists(settings.assets_folder)
            has_custom_assets = settings.custom_assets_folder and os.path.exists(settings.custom_assets_folder)

            if not has_original_assets and not has_custom_assets:
                log.warning("Material", "Assets folder not set or doesn't exist — materials will be created without textures")

            log.info("Material", f"Loading materials from: {os.path.basename(resolved_materials)}")
            if has_original_assets:
                log.info("Material", f"Original assets folder: {settings.assets_folder}")
            if has_custom_assets:
                log.info("Material", f"Custom assets folder (fallback): {settings.custom_assets_folder}")

            material_loader = mat_loader.MaterialLoader(
                assets_folder=settings.assets_folder if has_original_assets else "",
                levels_folder=settings.levels_folder if hasattr(settings, 'levels_folder') else "",
                map_py_path=settings.map_py_path if hasattr(settings, 'map_py_path') else "",
                dragon_layer=settings.dragon_layer_filter if hasattr(settings, 'dragon_layer_filter') else "LAYER_1",
                custom_assets_folder=settings.custom_assets_folder if has_custom_assets else "",
                prioritize_custom=settings.prioritize_custom_assets if hasattr(settings, 'prioritize_custom_assets') else False,
            )
            materials_db = material_loader.load_materials(resolved_materials)

            # Load map settings (sun, lightmap, fog)
            map_settings = material_loader.load_map_settings(resolved_materials)

            # Initialize baron hash parser for visibility decoding
            baron_parser = baron_hash_parser.MaterialsBinParser(resolved_materials)
            log.info("Import", "Baron hash parser initialized")
        else:
            log.info("Material", "No materials file specified — using simple materials")
        
        # Clear prey routing properties after use
        if prey_dir:
            settings.prey_materials_dir = ""
            settings.prey_materials_base = ""
        
        # Get lightmap color scale from map settings
        lightmap_color_scale = map_settings.get('lightmap_color_scale', 1.0) if map_settings else 1.0
        
        # Import each mesh
        imported_count = 0
        for mesh_idx, mesh_data in enumerate(mapgeo.meshes):
            try:
                # Create Blender mesh
                mesh_name = f"{collection_name}_mesh_{mesh_idx:03d}"
                bl_mesh = bpy.data.meshes.new(mesh_name)
                
                # Validate vertex buffer IDs
                if not mesh_data.vertex_buffer_ids:
                    log.mesh_failed(mesh_name, "No vertex buffers")
                    continue
                
                # Get the first vertex buffer (main geometry)
                vb_id = mesh_data.vertex_buffer_ids[0]
                if vb_id >= len(mapgeo.vertex_buffers):
                    log.mesh_failed(mesh_name, f"Invalid vertex buffer ID {vb_id}")
                    continue
                
                if mesh_data.index_buffer_id >= len(mapgeo.index_buffers):
                    log.mesh_failed(mesh_name, f"Invalid index buffer ID {mesh_data.index_buffer_id}")
                    continue
                
                # Get vertex buffer and its description
                vertex_buffer = mapgeo.vertex_buffers[vb_id]
                desc_id = mesh_data.vertex_declaration_id
                if desc_id >= len(mapgeo.vertex_buffer_descriptions):
                    log.mesh_failed(f"mesh_{mesh_idx:03d}", f"Invalid vertex declaration ID {desc_id}")
                    continue
                
                vb_description = mapgeo.vertex_buffer_descriptions[desc_id]
                index_buffer = mapgeo.index_buffers[mesh_data.index_buffer_id]
                
                # Parse vertex data from primary buffer
                vertices, normals, uvs, colors, texcoord5_data = self.parse_vertex_buffer(
                    vertex_buffer, vb_description, mesh_data, mesh_idx
                )
                
                # Check if UVs are in a secondary vertex buffer
                # IMPORTANT: Each vertex buffer can have its own vertex description!
                # Use vertex_declaration_id + buffer_index for each buffer
                if len(mesh_data.vertex_buffer_ids) > 1:
                    for sec_vb_idx in range(1, len(mesh_data.vertex_buffer_ids)):
                        sec_vb_id = mesh_data.vertex_buffer_ids[sec_vb_idx]
                        sec_desc_id = mesh_data.vertex_declaration_id + sec_vb_idx
                        
                        if sec_vb_id >= len(mapgeo.vertex_buffers):
                            continue
                        if sec_desc_id >= len(mapgeo.vertex_buffer_descriptions):
                            continue
                            
                        sec_vb = mapgeo.vertex_buffers[sec_vb_id]
                        sec_desc = mapgeo.vertex_buffer_descriptions[sec_desc_id]
                        
                        # Parse secondary buffer
                        _, sec_normals, sec_uvs, sec_colors, sec_tc5 = self.parse_vertex_buffer(
                            sec_vb, sec_desc, mesh_data, -1
                        )
                        
                        # Merge data from secondary buffer
                        if sec_normals and not normals:
                            normals = sec_normals
                        for uv_idx, uv_data in enumerate(sec_uvs):
                            if uv_data and not uvs[uv_idx]:
                                uvs[uv_idx] = uv_data
                        if sec_colors and not colors:
                            colors = sec_colors
                        if sec_tc5 and not texcoord5_data:
                            texcoord5_data = sec_tc5
                
                # Parse index data with material assignments
                faces, face_materials = self.parse_index_buffer(index_buffer, mesh_data)
                
                if not vertices:
                    log.mesh_failed(f"mesh_{mesh_idx:03d}", f"No vertices parsed (vb_id={vb_id}, desc_id={desc_id})")
                    continue
                    
                if not faces:
                    log.mesh_failed(f"mesh_{mesh_idx:03d}", f"No faces parsed (ib_id={mesh_data.index_buffer_id})")
                    continue
                
                # Create mesh
                bl_mesh.from_pydata(vertices, [], faces)
                _optimized_mesh_update(bl_mesh)
                
                # Store per-face primitive index for multi-prim round-trip.
                # This preserves original primitive boundaries even when prims share the same material.
                if len(mesh_data.primitives) > 1 and face_materials:
                    prim_attr = bl_mesh.attributes.new(name="mapgeo_prim_idx", type='INT', domain='FACE')
                    n_polys = len(bl_mesh.polygons)
                    prim_attr.data.foreach_set("value", face_materials[:n_polys])
                
                # Apply normals - Blender 5.0+ automatically uses custom normals when set
                if self.import_normals and normals:
                    _safe_set_vertex_normals(bl_mesh, normals, f"mesh_{mesh_idx:03d}")
                
                # Create UV layers — bulk foreach_set for performance
                uv_channels_created = 0
                has_lightmap_uv = False
                n_loops = len(bl_mesh.loops)
                # Pre-fetch loop→vertex mapping once for all UV channels and colors
                loop_vert_indices = [0] * n_loops
                bl_mesh.loops.foreach_get("vertex_index", loop_vert_indices)
                if uvs:
                    for uv_idx, uv_data in enumerate(uvs):
                        if uv_data and len(uv_data) > 0:
                            uv_count = len(uv_data)
                            # TEXCOORD7 (index 7) is the lightmap UV channel
                            if uv_idx == 7:
                                uv_layer = bl_mesh.uv_layers.new(name="LightmapUV")
                                has_lightmap_uv = True
                                
                                # Apply scale+bias transform from BakedLight channel
                                # finalUV = rawUV * Scale + Bias
                                lm_scale_u, lm_scale_v = 1.0, 1.0
                                lm_bias_u, lm_bias_v = 0.0, 0.0
                                if mesh_data.baked_light:
                                    lm_scale_u, lm_scale_v = mesh_data.baked_light.scale
                                    lm_bias_u, lm_bias_v = mesh_data.baked_light.bias
                                
                                uv_flat = [0.0] * (n_loops * 2)
                                for i, vi in enumerate(loop_vert_indices):
                                    if vi < uv_count:
                                        raw_u, raw_v = uv_data[vi]
                                        orig_v = 1.0 - raw_v
                                        uv_flat[i * 2] = raw_u * lm_scale_u + lm_bias_u
                                        uv_flat[i * 2 + 1] = 1.0 - (orig_v * lm_scale_v + lm_bias_v)
                                uv_layer.data.foreach_set("uv", uv_flat)
                            else:
                                uv_layer = bl_mesh.uv_layers.new(name=f"UVMap{uv_idx}" if uv_idx > 0 else "UVMap")
                                uv_flat = [0.0] * (n_loops * 2)
                                for i, vi in enumerate(loop_vert_indices):
                                    if vi < uv_count:
                                        uv_flat[i * 2] = uv_data[vi][0]
                                        uv_flat[i * 2 + 1] = uv_data[vi][1]
                                uv_layer.data.foreach_set("uv", uv_flat)
                            uv_channels_created += 1
                
                # Create vertex colors (Blender 5.0+ uses color attributes)
                if self.import_vertex_colors and colors:
                    color_attr = bl_mesh.color_attributes.new(
                        name="Color",
                        type='BYTE_COLOR',
                        domain='CORNER'
                    )
                    color_count = len(colors)
                    color_flat = [0.0] * (n_loops * 4)
                    for i, vi in enumerate(loop_vert_indices):
                        if vi < color_count:
                            col = colors[vi]
                            base = i * 4
                            color_flat[base] = col[0]
                            color_flat[base + 1] = col[1]
                            color_flat[base + 2] = col[2]
                            color_flat[base + 3] = col[3] if len(col) > 3 else 1.0
                    color_attr.data.foreach_set("color", color_flat)
                
                # Raw normals preservation for render region meshes
                # Render region meshes use non-unit "normals" that contain game-specific data.
                # Blender auto-normalizes normals to unit length, destroying this data.
                # Store pre-swap raw normals so the exporter can write them back.
                if normals and mesh_data.unknown_version18_int != 0:
                    raw_attr = bl_mesh.attributes.new(name="raw_normals", type='FLOAT_VECTOR', domain='POINT')
                    n_verts = min(len(normals), len(bl_mesh.vertices))
                    raw_flat = [0.0] * (n_verts * 3)
                    for vi in range(n_verts):
                        n = normals[vi]
                        raw_flat[vi * 3] = n[0]
                        raw_flat[vi * 3 + 1] = n[1]
                        raw_flat[vi * 3 + 2] = n[2]
                    raw_attr.data.foreach_set("vector", raw_flat)

                # TEXCOORD5 - bush animation anchor positions (3D per-vertex data)
                # Store as a vertex-domain float vector attribute for round-trip export
                if texcoord5_data and len(texcoord5_data) > 0:
                    # Store as a vector attribute on the mesh (per-vertex, 3 floats)
                    tc5_attr = bl_mesh.attributes.new(name="TEXCOORD5", type='FLOAT_VECTOR', domain='POINT')
                    n_tc5 = min(len(texcoord5_data), len(bl_mesh.vertices))
                    tc5_flat = [0.0] * (n_tc5 * 3)
                    for vi in range(n_tc5):
                        d = texcoord5_data[vi]
                        tc5_flat[vi * 3] = d[0]
                        tc5_flat[vi * 3 + 1] = d[1]
                        tc5_flat[vi * 3 + 2] = d[2]
                    tc5_attr.data.foreach_set("vector", tc5_flat)
                
                # Assign materials
                material_mapping = {}  # Maps primitive index to material slot
                
                # Get per-mesh lightmap texture path (only if lightmaps enabled)
                mesh_lightmap_texture = None
                if self.import_lightmaps and has_lightmap_uv and mesh_data.baked_light and mesh_data.baked_light.texture:
                    mesh_lightmap_texture = mesh_data.baked_light.texture
                
                # Build texture overrides dict: sampler_name -> texture_path
                # Maps per-mesh texture overrides using file-level sampler_defs
                mesh_texture_overrides = {}
                if mesh_data.texture_overrides:
                    for override in mesh_data.texture_overrides:
                        # Find sampler name by index
                        for sampler_def in mapgeo.sampler_defs:
                            if sampler_def.index == override.index:
                                mesh_texture_overrides[sampler_def.name] = override.texture
                                break
                    if mesh_texture_overrides and imported_count <= 5:
                        log.info("Material", f"Texture overrides for mesh {mesh_idx}", str(mesh_texture_overrides))
                
                # Get per-mesh baked paint UV transform
                baked_paint_scale = mesh_data.baked_paint_scale
                baked_paint_bias = mesh_data.baked_paint_bias
                
                if self.import_materials:
                    for prim_idx, prim in enumerate(mesh_data.primitives):
                        mat_name = prim.material if prim.material else "Default"
                        
                        # Build cache key that includes lightmap and texture override info
                        mat_cache_key = mat_name
                        if mesh_lightmap_texture:
                            import hashlib
                            lm_hash = hashlib.md5(mesh_lightmap_texture.encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_name}__lm__{lm_hash}"
                        if mesh_texture_overrides:
                            import hashlib
                            override_hash = hashlib.md5(str(sorted(mesh_texture_overrides.items())).encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_cache_key}__to__{override_hash}"
                        if baked_paint_scale != (1.0, 1.0) or baked_paint_bias != (0.0, 0.0):
                            import hashlib
                            bp_hash = hashlib.md5(f"{baked_paint_scale}{baked_paint_bias}".encode()).hexdigest()[:6]
                            mat_cache_key = f"{mat_cache_key}__bp__{bp_hash}"
                        
                        if mat_cache_key not in materials:
                            # Try to load from materials database first
                            if material_loader and materials_db:
                                mat = material_loader.get_or_create_material(
                                    mat_name, materials_db,
                                    lightmap_texture=mesh_lightmap_texture,
                                    lightmap_color_scale=lightmap_color_scale,
                                    texture_overrides=mesh_texture_overrides,
                                    baked_paint_scale=baked_paint_scale,
                                    baked_paint_bias=baked_paint_bias
                                )
                                materials[mat_cache_key] = mat
                            else:
                                # Fallback to simple material
                                materials[mat_cache_key] = self.create_material(mat_name)
                        
                        # Check if material is already in mesh materials
                        mat_slot_idx = -1
                        for idx, mat_slot in enumerate(bl_mesh.materials):
                            if mat_slot == materials[mat_cache_key]:
                                mat_slot_idx = idx
                                break
                        
                        if mat_slot_idx == -1:
                            bl_mesh.materials.append(materials[mat_cache_key])
                            mat_slot_idx = len(bl_mesh.materials) - 1
                        
                        material_mapping[prim_idx] = mat_slot_idx
                    
                    # Assign face materials
                    if len(material_mapping) > 0:
                        for face_idx, face in enumerate(bl_mesh.polygons):
                            if face_idx < len(face_materials):
                                prim_idx = face_materials[face_idx]
                                if prim_idx in material_mapping:
                                    face.material_index = material_mapping[prim_idx]
                
                # Create object
                obj = bpy.data.objects.new(mesh_name, bl_mesh)
                
                # Store per-primitive material names for multi-prim round-trip export
                if len(mesh_data.primitives) > 1:
                    import json as _json
                    prim_mats = [p.material for p in mesh_data.primitives]
                    obj["mapgeo_prim_materials"] = _json.dumps(prim_mats)
                
                # Link object to main Meshes collection (this owns the object data)
                meshes_collection.objects.link(obj)
                
                # Link to layer-specific collections based on visibility flags
                if mesh_data.visibility:
                    for layer_flag, layer_col in layer_collections.items():
                        if mesh_data.visibility & layer_flag:
                            layer_col.objects.link(obj)
                
                # Link to baron state collections if baron hash is decoded
                # baron_layers_decoded contains bit values (1, 2, 4, 8, etc.)
                # This provides better organization for meshes with baron visibility
                if "baron_layers_decoded" in obj and obj["baron_layers_decoded"]:
                    try:
                        import ast
                        baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                        for baron_state_bit in baron_layers:
                            if baron_state_bit in baron_collections:
                                baron_collections[baron_state_bit].objects.link(obj)
                    except Exception as e:
                        log.warning("Import", f"Could not link mesh to baron collections: {e}")
                
                # Link to Bushes collection if mesh has TEXCOORD5 (bush animation data)
                if texcoord5_data and len(texcoord5_data) > 0:
                    obj["is_bush"] = True
                    bushes_collection.objects.link(obj)
                
                # Link to RenderRegions collection if mesh has render region hash
                if mesh_data.unknown_version18_int:
                    render_regions_collection.objects.link(obj)
                
                # Apply transform
                matrix = self.convert_transform_matrix(mesh_data.transform_matrix)
                obj.matrix_world = matrix
                
                # Apply scale
                obj.scale *= self.scale_factor
                
                # Store essential custom properties for mapgeo export
                
                # Visibility and quality
                obj["visibility_layer"] = int(mesh_data.visibility)
                # Quality is a uint8 bitmask. Common values: 31 (all 5 levels), 255 (all bits).
                # Render region meshes often use 255. Do NOT clamp to 31.
                obj["quality"] = max(0, min(255, int(mesh_data.quality)))
                
                # Render flags, layer transition behavior, backface culling
                obj["layer_transition_behavior"] = mesh_data.layer_transition_behavior
                obj["render_flags"] = mesh_data.render_flags
                obj["disable_backface_culling"] = int(mesh_data.disable_backface_culling)
                
                # Vertex buffer layout for round-trip export (preserve multi-stream)
                obj["vertex_declaration_id"] = mesh_data.vertex_declaration_id
                obj["vertex_declaration_count"] = mesh_data.vertex_declaration_count
                # Store per-stream element names as JSON
                stream_elements = []
                for stream_idx in range(mesh_data.vertex_declaration_count):
                    desc_id = mesh_data.vertex_declaration_id + stream_idx
                    if desc_id < len(mapgeo.vertex_buffer_descriptions):
                        desc = mapgeo.vertex_buffer_descriptions[desc_id]
                        stream_elements.append([e.name for e in desc.elements])
                    else:
                        stream_elements.append([])
                obj["vb_stream_elements"] = json.dumps(stream_elements)
                
                # Lightmap data - store scale/bias for all channels for round-trip
                if mesh_data.baked_light:
                    if mesh_data.baked_light.texture:
                        obj["lightmap_texture"] = mesh_data.baked_light.texture
                    obj["lightmap_scale"] = list(mesh_data.baked_light.scale)
                    obj["lightmap_bias"] = list(mesh_data.baked_light.bias)
                if mesh_data.stationary_light:
                    if mesh_data.stationary_light.texture:
                        obj["stationary_light_texture"] = mesh_data.stationary_light.texture
                    obj["stationary_light_scale"] = list(mesh_data.stationary_light.scale)
                    obj["stationary_light_bias"] = list(mesh_data.stationary_light.bias)
                
                # Baked paint scale/bias (version 17+)
                if mesh_data.baked_paint_scale != (1.0, 1.0) or mesh_data.baked_paint_bias != (0.0, 0.0):
                    obj["baked_paint_scale"] = list(mesh_data.baked_paint_scale)
                    obj["baked_paint_bias"] = list(mesh_data.baked_paint_bias)
                
                # Version-specific fields (hex without 0x prefix)
                if mesh_data.unknown_version18_int:
                    obj["render_region_hash"] = f"{mesh_data.unknown_version18_int:08X}"  # Hex without 0x
                if mesh_data.visibility_controller_path_hash:
                    # Baron Hash System: When set (non-zero), this OVERRIDES the dragon layer system
                    # The hash references a ChildMapVisibilityController in materials.bin
                    # which defines complex visibility behavior combining multiple dragon layers
                    # See baron_hash_system.md for full documentation
                    baron_hash_str = f"{mesh_data.visibility_controller_path_hash:08X}"
                    obj["baron_hash"] = baron_hash_str  # Hex without 0x
                    
                    # Decode baron hash to determine actual layer visibility
                    if baron_parser:
                        try:
                            controller = baron_parser.decode_baron_hash(baron_hash_str)
                            
                            # Store decoded baron layers (if any)
                            if controller.baron_layers:
                                # Convert set to sorted list for storage
                                baron_layers_list = sorted(list(controller.baron_layers))
                                obj["baron_layers_decoded"] = str(baron_layers_list)
                            
                            # Store decoded dragon layers (if any)
                            if controller.dragon_layers:
                                # Convert set to sorted list for storage
                                dragon_layers_list = sorted(list(controller.dragon_layers))
                                obj["baron_dragon_layers_decoded"] = str(dragon_layers_list)
                            
                            # Store parent mode for reference
                            obj["baron_parent_mode"] = controller.parent_mode
                            
                            if imported_count <= 5:
                                detail_parts = [f"ParentMode: {controller.parent_mode}"]
                                if controller.baron_layers:
                                    baron_names = [baron_hash_parser.get_baron_layer_name(l) for l in controller.baron_layers]
                                    detail_parts.append(f"Baron: {', '.join(baron_names)}")
                                if controller.dragon_layers:
                                    dragon_names = [baron_hash_parser.get_dragon_layer_name(l) for l in controller.dragon_layers]
                                    detail_parts.append(f"Dragon: {', '.join(dragon_names)}")
                                log.info("Import", f"Baron Hash {baron_hash_str}", " | ".join(detail_parts))
                        except Exception as e:
                            log.warning("Import", f"Could not decode baron hash {baron_hash_str}: {e}")
                
                # Create Blender point light if mesh has point_light custom properties
                # This is a CUSTOM FEATURE (stationary_light field is unused in official maps)
                if obj.get("point_light_enabled", False):
                    try:
                        light_color = obj.get("point_light_color", [1.0, 0.95, 0.8])
                        light_intensity = obj.get("point_light_intensity", 500.0)
                        light_radius = obj.get("point_light_radius", 5.0)
                        offset_z = obj.get("point_light_offset_z", 0.0)
                        
                        # Create light data
                        light_data = bpy.data.lights.new(name=f"{mesh_name}_PointLight", type='POINT')
                        light_data.energy = light_intensity
                        light_data.color = light_color
                        light_data.shadow_soft_size = light_radius
                        
                        # Create light object
                        light_obj = bpy.data.objects.new(name=f"{mesh_name}_PointLight", object_data=light_data)
                        light_obj.location = obj.location.copy()
                        light_obj.location.z += offset_z
                        
                        # Link to same collection as mesh
                        meshes_collection.objects.link(light_obj)
                        
                        # Parent to mesh
                        light_obj.parent = obj
                        
                        if imported_count <= 5:
                            log.info("Light", f"Created point light for {mesh_name}")
                        log.light_created()
                    except Exception as e:
                        log.light_failed(f"{obj.name}: {e}")
                
                imported_count += 1
                log.mesh_imported()
                if imported_count <= 5 or imported_count % 100 == 0:
                    uv_info = f", {uv_channels_created} UV" if uv_channels_created > 0 else ", no UV"
                    log.info("Mesh", f"Imported mesh {mesh_idx}: {len(vertices)} verts, {len(faces)} faces{uv_info}")
            
            except Exception as e:
                log.mesh_failed(f"mesh_{mesh_idx:03d}", str(e))
                import traceback
                traceback.print_exc()
                continue        
        
        log.info("Import", f"Successfully imported {imported_count}/{len(mapgeo.meshes)} meshes")
        print(f"[TIMING] mesh_loop done: {imported_count} meshes")
        
        # Layer statistics
        layer_stats = []
        for layer_flag, layer_col in layer_collections.items():
            layer_name = layer_names[layer_flag]
            mesh_count = len(layer_col.objects)
            if mesh_count > 0:
                layer_stats.append(f"{layer_name}: {mesh_count}")
        if layer_stats:
            log.info("Import", f"Layer distribution: {', '.join(layer_stats)}")
        
        # Import bucket grids
        import time as _time
        _tb = _time.perf_counter()
        if self.import_bucket_grid and mapgeo.bucket_grids:
            self.import_bucket_grids(context, collection, collection_name, mapgeo)
        print(f"[TIMING] bucket_grids: {_time.perf_counter() - _tb:.2f}s")
        
        # Store bucket grid raw data on the collection for export
        if mapgeo.bucket_grids:
            collection["has_bucket_grids"] = True
            collection["bucket_grid_count"] = len(mapgeo.bucket_grids)
            # Store source file for potential re-read on export
            collection["source_mapgeo_path"] = self.filepath
        
        # Store planar reflector data on the collection for export
        if mapgeo.planar_reflectors:
            collection["has_planar_reflectors"] = True
            collection["planar_reflector_count"] = len(mapgeo.planar_reflectors)
        
        # Create scene lighting from map settings (Sun, World ambient)
        _tl = _time.perf_counter()
        if self.import_lightmaps and map_settings:
            self.create_scene_lighting(context, collection, map_settings)
        print(f"[TIMING] lighting: {_time.perf_counter() - _tl:.2f}s")
        
        # Finalize texture packing (batch operation for performance)
        _tp = _time.perf_counter()
        if material_loader and hasattr(material_loader, 'tex_converter'):
            material_loader.tex_converter.pack_all_images()
        print(f"[TIMING] pack_all_images: {_time.perf_counter() - _tp:.2f}s")

        # Return imported materials so caller can run post-import refresh/update.
        return list(materials.values())
            
    def import_bucket_grids(self, context, parent_collection, collection_name, mapgeo):
        """
        Import bucket grid scene graph data as visual wireframe meshes.
        
        Creates a separate collection for bucket grid visualization with:
        - Wireframe mesh objects for each bucket grid's simplified geometry
        - Bounding box empties showing grid extents
        - Custom properties storing metadata for export
        """
        log = get_debug_log()
        import json
        
        scale = self.scale_factor
        
        # Create bucket grid collection separate from _Meshes
        bg_col_name = f"{collection_name}_BucketGrid"
        bg_collection = bpy.data.collections.new(bg_col_name)
        parent_collection.children.link(bg_collection)
        
        # Tag the collection for identification
        bg_collection["is_bucket_grid_collection"] = True
        bg_collection["bucket_grid_count"] = len(mapgeo.bucket_grids)
        
        total_verts = 0
        total_faces = 0
        all_grid_jsons = []  # Collect full grid data for collection property
        
        for grid_idx, grid in enumerate(mapgeo.bucket_grids):
            if grid.is_disabled:
                log.info("BucketGrid", f"Grid {grid_idx}: disabled, skipping")
                continue
            
            if not grid.vertices or not grid.indices:
                log.info("BucketGrid", f"Grid {grid_idx}: no geometry, skipping")
                continue
            
            # --- Create mesh from bucket grid geometry ---
            grid_name = f"BucketGrid_{grid_idx:03d}"
            if grid.path_hash:
                grid_name = f"BucketGrid_{grid.path_hash:08X}"
            
            mesh = bpy.data.meshes.new(grid_name)
            
            # Scale vertices and swap Y/Z (mapgeo Y-up → Blender Z-up)
            verts = [(v[0] * scale, v[2] * scale, v[1] * scale) for v in grid.vertices]
            
            # Build face list from indices with base_vertex offsets per bucket
            # Buckets use local indexing - must add base_vertex to each index
            faces = []
            for bucket_row in grid.buckets:
                for bucket in bucket_row:
                    face_count = bucket.inside_face_count + bucket.sticking_out_face_count
                    if face_count == 0:
                        continue
                    
                    # Process indices for this bucket
                    start_idx = bucket.start_index
                    for i in range(face_count):
                        idx_pos = start_idx + (i * 3)
                        if idx_pos + 2 < len(grid.indices):
                            # Apply base_vertex offset and reverse winding for Y/Z swap
                            v0 = grid.indices[idx_pos] + bucket.base_vertex
                            v1 = grid.indices[idx_pos + 1] + bucket.base_vertex
                            v2 = grid.indices[idx_pos + 2] + bucket.base_vertex
                            # Reverse winding order for coordinate system handedness
                            faces.append((v0, v2, v1))
            
            mesh.from_pydata(verts, [], faces)
            _optimized_mesh_update(mesh)
            
            total_verts += len(verts)
            total_faces += len(faces)
            
            # Create object
            obj = bpy.data.objects.new(grid_name, mesh)
            bg_collection.objects.link(obj)
            
            # Create or get material with crimson red color and transparency
            mat_name = f"{grid_name}_Material"
            # Check if material exists and remove it to ensure fresh creation
            if mat_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[mat_name])
            
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            mat.blend_method = 'BLEND'  # Enable transparency
            
            # Set up material nodes
            nodes = mat.node_tree.nodes
            nodes.clear()
            
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            bsdf.inputs['Base Color'].default_value = (0.935752, 0.055, 0.0, 1.0)  # Crimson red
            bsdf.inputs['Alpha'].default_value = 0.04  # 96% transparent (4% opaque)
            
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (300, 0)
            
            mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            
            # Assign material to mesh
            if mesh.materials:
                mesh.materials[0] = mat
            else:
                mesh.materials.append(mat)
            
            # Set display as wireframe for visual clarity
            obj.display_type = 'WIRE'
            obj.show_wire = True
            obj.show_all_edges = True
            obj.color = (0.86, 0.08, 0.24, 0.8)  # Object color for viewport
            
            # Make non-selectable by default to avoid accidental edits
            obj.hide_select = True
            
            # Store metadata as custom properties for export
            obj["is_bucket_grid"] = True
            obj["bucket_grid_index"] = grid_idx
            obj["path_hash"] = f"{grid.path_hash:08X}" if grid.path_hash else "00000000"
            obj["bounds_min_x"] = grid.min_x
            obj["bounds_min_z"] = grid.min_z
            obj["bounds_max_x"] = grid.max_x
            obj["bounds_max_z"] = grid.max_z
            obj["bucket_size_x"] = grid.bucket_size_x
            obj["bucket_size_z"] = grid.bucket_size_z
            obj["stickout_x"] = grid.max_stickout_x
            obj["stickout_z"] = grid.max_stickout_z
            obj["buckets_per_side"] = grid.buckets_per_side
            obj["is_disabled"] = grid.is_disabled
            obj["flags"] = grid.flags
            if grid.unknown_v18_float is not None:
                # Store as hex string (interpreting float bytes as uint32)
                import struct
                float_bytes = struct.pack('<f', grid.unknown_v18_float)
                uint_value = struct.unpack('<I', float_bytes)[0]
                obj["unknown_v18_float"] = f"{uint_value:08X}"
            
            # Store face visibility flags if present
            if grid.face_visibility_flags:
                vis_hex = bytes(grid.face_visibility_flags).hex()
                obj["face_visibility_flags_hex"] = vis_hex
            
            # Build full grid data for collection-level storage (used by export)
            grid_json = {
                "index": grid_idx,
                "path_hash": grid.path_hash,
                "min_x": grid.min_x,
                "min_z": grid.min_z,
                "max_x": grid.max_x,
                "max_z": grid.max_z,
                "bucket_size_x": grid.bucket_size_x,
                "bucket_size_z": grid.bucket_size_z,
                "buckets_per_side": grid.buckets_per_side,
                "is_disabled": grid.is_disabled,
                "flags": grid.flags,
                "unknown_v18_float": f"{struct.unpack('<I', struct.pack('<f', grid.unknown_v18_float))[0]:08X}" if grid.unknown_v18_float is not None else "00000000",
                "max_stickout_x": grid.max_stickout_x,
                "max_stickout_z": grid.max_stickout_z,
                "vertices": [(v[0], v[1], v[2]) for v in grid.vertices],
                "indices": grid.indices,
                "buckets": [
                    [
                        {
                            "max_stickout_x": b.max_stickout_x,
                            "max_stickout_z": b.max_stickout_z,
                            "start_index": b.start_index,
                            "base_vertex": b.base_vertex,
                            "inside_face_count": b.inside_face_count,
                            "sticking_out_face_count": b.sticking_out_face_count
                        }
                        for b in row
                    ]
                    for row in grid.buckets
                ],
                "face_visibility_flags": grid.face_visibility_flags,
            }
            all_grid_jsons.append(grid_json)
            log.info("BucketGrid", f"Stored grid {grid_idx} data for export")
            
            # --- Create bounding box wireframe ---
            bbox_name = f"{grid_name}_Bounds"
            bbox_mesh = bpy.data.meshes.new(bbox_name)
            
            min_x = grid.min_x * scale
            min_y = grid.min_z * scale  # mapgeo Z → Blender Y
            max_x = grid.max_x * scale
            max_y = grid.max_z * scale  # mapgeo Z → Blender Y
            
            # Flat rectangle on X-Y plane, thin Z slab (mapgeo Y-up → Blender Z-up)
            z_low = -0.1 * scale
            z_high = 0.1 * scale
            
            bbox_verts = [
                (min_x, min_y, z_low),
                (max_x, min_y, z_low),
                (max_x, max_y, z_low),
                (min_x, max_y, z_low),
                (min_x, min_y, z_high),
                (max_x, min_y, z_high),
                (max_x, max_y, z_high),
                (min_x, max_y, z_high),
            ]
            bbox_edges = [
                (0,1),(1,2),(2,3),(3,0),
                (4,5),(5,6),(6,7),(7,4),
                (0,4),(1,5),(2,6),(3,7),
            ]
            bbox_mesh.from_pydata(bbox_verts, bbox_edges, [])
            _optimized_mesh_update(bbox_mesh)
            
            # Create or get material for bounding box
            bbox_mat_name = f"{bbox_name}_Material"
            # Check if material exists and remove it to ensure fresh creation
            if bbox_mat_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[bbox_mat_name])
            
            bbox_mat = bpy.data.materials.new(name=bbox_mat_name)
            bbox_mat.use_nodes = True
            bbox_mat.blend_method = 'BLEND'
            
            bbox_nodes = bbox_mat.node_tree.nodes
            bbox_nodes.clear()
            
            bbox_bsdf = bbox_nodes.new(type='ShaderNodeBsdfPrincipled')
            bbox_bsdf.location = (0, 0)
            bbox_bsdf.inputs['Base Color'].default_value = (0.935752, 0.055, 0.0, 1.0)  # Vermillion
            bbox_bsdf.inputs['Alpha'].default_value = 0.05
            
            bbox_output = bbox_nodes.new(type='ShaderNodeOutputMaterial')
            bbox_output.location = (300, 0)
            
            bbox_mat.node_tree.links.new(bbox_bsdf.outputs['BSDF'], bbox_output.inputs['Surface'])
            
            if bbox_mesh.materials:
                bbox_mesh.materials[0] = bbox_mat
            else:
                bbox_mesh.materials.append(bbox_mat)
            
            bbox_obj = bpy.data.objects.new(bbox_name, bbox_mesh)
            bg_collection.objects.link(bbox_obj)
            bbox_obj.display_type = 'WIRE'
            bbox_obj.color = (0.935752, 0.055, 0.0, 0.05)  # Match material color
            bbox_obj.hide_select = True
            bbox_obj["is_bucket_grid_bounds"] = True
            bbox_obj["bucket_grid_index"] = grid_idx
        
        # Store full grid data as JSON on the collection for export
        # This is the source of truth - no stale module cache needed
        bg_collection["bucket_data_json"] = json.dumps(all_grid_jsons)
        
        # Hide the bucket grid collection by default in the viewport
        view_layer = context.view_layer
        def find_layer_collection(layer_col, name):
            if layer_col.name == name:
                return layer_col
            for child in layer_col.children:
                result = find_layer_collection(child, name)
                if result:
                    return result
            return None
        
        layer_col = find_layer_collection(view_layer.layer_collection, bg_col_name)
        if layer_col:
            layer_col.hide_viewport = True
        
        log.info("BucketGrid", f"Imported {len(mapgeo.bucket_grids)} grid(s): {total_verts} verts, {total_faces} faces")
    
    def create_scene_lighting(self, context, collection, map_settings):
        """
        Create scene lighting objects from MapSunProperties + MapBakeProperties.
        
        Sets up:
        - Sun light with direction/color from sunDirection/sunColor
        - World environment with hemisphere gradient ambient lighting:
            skyLightColor  = ambient light from above (sky dome)
            horizonColor   = ambient light from the sides (horizon ring)
            groundColor    = ambient light bounced from below (ground plane)
          These form a 3-color hemisphere used by League's ambient lighting system.
        - Fog as Volume Scatter on World (from fogColor, fogStartAndEnd)
        - MapBakeProperties stored as custom properties
        
        Lightmapped materials use Emission + Base Color so they show baked
        lighting and respond to scene lights (sun, sky ambient).
        """
        log = get_debug_log()
        import math
        from mathutils import Vector
        
        collection_name = collection.name
        
        # Create Lighting collection
        lighting_col = bpy.data.collections.new(f"{collection_name}_Lighting")
        collection.children.link(lighting_col)
        
        # --- Sun Light ---
        sun_direction = map_settings.get('sun_direction')
        sun_color = map_settings.get('sun_color', [1, 1, 1, 1])
        
        if sun_direction:
            sun_data = bpy.data.lights.new(name="MapSun", type='SUN')
            sun_data.color = (sun_color[0], sun_color[1], sun_color[2])
            sun_data.energy = 2.0  # Reasonable energy for non-lightmapped materials
            
            sun_obj = bpy.data.objects.new("MapSun", sun_data)
            lighting_col.objects.link(sun_obj)
            
            # Convert League sun direction to Blender rotation
            # League: X-right, Y-up, Z-forward → sunDirection = direction from surface to sun
            # Blender: X-right, Y-forward, Z-up → swap Y and Z
            league_dir = Vector(sun_direction)
            blender_dir = Vector((league_dir.x, league_dir.z, league_dir.y))
            
            # Sun light faces along its local -Z axis
            # Point -Z toward the surface = -blender_dir direction
            target_dir = -blender_dir.normalized()
            rotation = target_dir.to_track_quat('-Z', 'Y')
            sun_obj.rotation_euler = rotation.to_euler()
            
            # Store original sun properties as custom properties
            sun_obj["sun_direction_league"] = list(sun_direction)
            sun_obj["sun_color"] = list(sun_color)
            
            log.info("MapSettings", f"Created Sun light: dir={sun_direction}, color=({sun_color[0]:.3f}, {sun_color[1]:.3f}, {sun_color[2]:.3f})")
        
        # --- World Environment (ambient lighting + fog) ---
        # League uses a 3-color hemisphere ambient lighting system:
        #   skyLightColor  = light color from directly above (sky dome top)
        #   horizonColor   = light color from the sides (horizon ring, ~90° from zenith)
        #   groundColor    = light color from below (ground bounce, reflected light)
        # These blend based on surface normal direction to create soft ambient lighting.
        sky_color = map_settings.get('sky_light_color', [0.5, 0.5, 0.6, 1])
        sky_scale = map_settings.get('sky_light_scale', 1.0)
        horizon_color = map_settings.get('horizon_color', [0.6, 0.7, 0.8, 1])
        ground_color = map_settings.get('ground_color', [0.3, 0.3, 0.4, 1])
        
        world = bpy.data.worlds.new(name=f"{collection_name}_World")
        context.scene.world = world
        world.use_nodes = True
        
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        nodes.clear()
        
        # --- Surface: gradient background (ambient hemisphere lighting) ---
        output_node = nodes.new('ShaderNodeOutputWorld')
        output_node.location = (600, 0)
        
        bg_node = nodes.new('ShaderNodeBackground')
        bg_node.location = (400, 0)
        bg_node.inputs['Strength'].default_value = sky_scale
        bg_node.label = f"Ambient (scale={sky_scale})"
        
        links.new(bg_node.outputs['Background'], output_node.inputs['Surface'])
        
        # Color Ramp: ground(0) → horizon(0.5) → sky(1.0) based on world normal Z
        ramp_node = nodes.new('ShaderNodeValToRGB')
        ramp_node.location = (100, 0)
        ramp_node.label = "Hemisphere Gradient"
        
        ramp = ramp_node.color_ramp
        ramp.elements[0].position = 0.0
        ramp.elements[0].color = (ground_color[0], ground_color[1], ground_color[2], 1.0)
        ramp.elements[1].position = 1.0
        ramp.elements[1].color = (sky_color[0], sky_color[1], sky_color[2], 1.0)
        horizon_stop = ramp.elements.new(0.5)
        horizon_stop.color = (horizon_color[0], horizon_color[1], horizon_color[2], 1.0)
        
        links.new(ramp_node.outputs['Color'], bg_node.inputs['Color'])
        
        # Map Range: convert Z normal from [-1, 1] to [0, 1]
        map_range_node = nodes.new('ShaderNodeMapRange')
        map_range_node.location = (-100, 0)
        map_range_node.inputs['From Min'].default_value = -1.0
        map_range_node.inputs['From Max'].default_value = 1.0
        map_range_node.inputs['To Min'].default_value = 0.0
        map_range_node.inputs['To Max'].default_value = 1.0
        
        links.new(map_range_node.outputs['Result'], ramp_node.inputs['Fac'])
        
        # Separate XYZ → Z component of normal
        sep_xyz_node = nodes.new('ShaderNodeSeparateXYZ')
        sep_xyz_node.location = (-300, 0)
        links.new(sep_xyz_node.outputs['Z'], map_range_node.inputs['Value'])
        
        # Texture Coordinate → Normal
        geom_node = nodes.new('ShaderNodeTexCoord')
        geom_node.location = (-500, 0)
        links.new(geom_node.outputs['Normal'], sep_xyz_node.inputs['Vector'])
        
        # Store world properties
        world["sky_light_color"] = list(sky_color)
        world["sky_light_scale"] = sky_scale
        world["horizon_color"] = list(horizon_color)
        world["ground_color"] = list(ground_color)
        
        log.info("MapSettings", f"Created World ambient: sky=({sky_color[0]:.3f}, {sky_color[1]:.3f}, {sky_color[2]:.3f}), "
              f"horizon=({horizon_color[0]:.3f}, {horizon_color[1]:.3f}, {horizon_color[2]:.3f}), "
              f"ground=({ground_color[0]:.3f}, {ground_color[1]:.3f}, {ground_color[2]:.3f}), scale={sky_scale}")
        
        # --- Volume: Fog (as mesh cube with volume scatter material) ---
        fog_enabled = map_settings.get('fog_enabled', True)
        fog_color = map_settings.get('fog_color')
        fog_start_end = map_settings.get('fog_start_end')
        
        if fog_enabled and fog_color and fog_start_end:
            # fogStartAndEnd: vec2 = { Start, End }
            # Values represent Z-axis positions (can be negative).
            # Example: {0, -19000} means fog from Z=0 down to Z=-19000
            fog_val_a = float(fog_start_end[0])
            fog_val_b = float(fog_start_end[1])
            
            fog_top_z = max(fog_val_a, fog_val_b)
            fog_bottom_z = min(fog_val_a, fog_val_b)
            fog_depth = fog_top_z - fog_bottom_z
            
            if fog_depth > 0:
                # Create a large cube mesh to hold the fog volume
                # Horizontal size should be large enough to cover the map
                fog_horizontal_size = max(fog_depth * 3.0, 20000.0)
                
                # Create a box with specific dimensions
                import bmesh
                fog_mesh = bpy.data.meshes.new("MapFog_Mesh")
                bm = bmesh.new()
                # Create cube with horizontal extent and vertical depth
                bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=(fog_horizontal_size, fog_horizontal_size, fog_depth), verts=bm.verts)
                bm.to_mesh(fog_mesh)
                bm.free()
                
                fog_obj = bpy.data.objects.new("MapFog", fog_mesh)
                lighting_col.objects.link(fog_obj)
                
                # Position the fog box so its top is at fog_top_z and bottom at fog_bottom_z
                # Cube center should be at the midpoint between top and bottom
                fog_center_z = (fog_top_z + fog_bottom_z) / 2.0
                fog_obj.location = (0, 0, fog_center_z)
                fog_obj.display_type = 'BOUNDS'  # Show as wireframe box in viewport
                
                # Fixed fog density matching Riot rendering
                fog_density = 0.000558
                
                # Create Principled Volume material
                fog_mat = bpy.data.materials.new(name="MapFog_Volume")
                fog_mat.use_nodes = True
                fog_nodes = fog_mat.node_tree.nodes
                fog_links = fog_mat.node_tree.links
                fog_nodes.clear()
                
                fog_output = fog_nodes.new('ShaderNodeOutputMaterial')
                fog_output.location = (300, 0)
                
                principled_vol = fog_nodes.new('ShaderNodeVolumePrincipled')
                principled_vol.location = (0, 0)
                principled_vol.inputs['Color'].default_value = (
                    fog_color[0], fog_color[1], fog_color[2], 1.0
                )
                principled_vol.inputs['Density'].default_value = fog_density
                
                # Set anisotropy color from fog_alternate_color
                fog_alt_color = map_settings.get('fog_alternate_color')
                if fog_alt_color:
                    principled_vol.inputs['Absorption Color'].default_value = (
                        fog_alt_color[0], fog_alt_color[1], fog_alt_color[2], 1.0
                    )
                
                principled_vol.label = f"Fog (density={fog_density:.6f})"
                
                fog_links.new(principled_vol.outputs['Volume'], fog_output.inputs['Volume'])
                
                fog_mesh.materials.append(fog_mat)
                
                # Store fog properties on the fog object
                fog_obj["fog_color"] = list(fog_color)
                fog_obj["fog_density"] = fog_density
                fog_obj["fog_start_bottom"] = fog_bottom_z
                fog_obj["fog_end_top"] = fog_top_z
                fog_obj["fog_depth"] = fog_depth
                
                if fog_alt_color:
                    fog_obj["fog_alternate_color"] = list(fog_alt_color)
                
                # Configure EEVEE volumetrics (camera distance, not Z-axis)
                # Use reasonable camera-distance values for volumetric rendering
                eevee = context.scene.eevee
                eevee.volumetric_start = 0.1
                eevee.volumetric_end = max(fog_horizontal_size * 2.0, 50000.0)
                
                log.info("MapSettings", f"Created Fog volume: color=({fog_color[0]:.3f}, {fog_color[1]:.3f}, {fog_color[2]:.3f}), "
                      f"density={fog_density:.6f}, Z range=[{fog_top_z:.0f} (top) to {fog_bottom_z:.0f} (bottom)], depth={fog_depth:.0f}")
            else:
                log.info("MapSettings", f"Fog skipped: zero depth (values={fog_val_a:.0f}, {fog_val_b:.0f})")
        elif not fog_enabled:
            log.info("MapSettings", "Fog disabled in map settings")
        
        # --- Store MapSunProperties on World object (visible in World > Custom Properties) ---
        world["fog_enabled"] = fog_enabled
        if fog_color:
            world["fog_color_value"] = list(fog_color)
        if fog_start_end:
            world["fog_start_end"] = list(fog_start_end)
        fog_alt = map_settings.get('fog_alternate_color')
        if fog_alt:
            world["fog_alternate_color"] = list(fog_alt)
        
        lightmap_scale = map_settings.get('lightmap_color_scale', 1.0)
        world["lightmap_color_scale"] = lightmap_scale
        
        # --- Store MapBakeProperties on World object ---
        light_grid_size = map_settings.get('light_grid_size')
        if light_grid_size is not None:
            world["bake_light_grid_size"] = light_grid_size
        
        light_grid_file = map_settings.get('light_grid_file')
        if light_grid_file:
            world["bake_light_grid_file"] = light_grid_file
        
        rma_texture = map_settings.get('rma_light_grid_texture')
        if rma_texture:
            world["bake_rma_light_grid_texture"] = rma_texture
        
        rma_scale = map_settings.get('rma_light_grid_intensity_scale')
        if rma_scale is not None:
            world["bake_rma_light_grid_intensity_scale"] = rma_scale
        
        light_grid_fullbright = map_settings.get('light_grid_fullbright')
        if light_grid_fullbright is not None:
            world["bake_light_grid_fullbright_intensity"] = light_grid_fullbright
        
        # --- Store MapLightingV2 on World object ---
        min_env = map_settings.get('min_env_color_contribution')
        if min_env is not None:
            world["lighting_v2_min_env_color_contribution"] = min_env
        
        log.info("MapSettings", f"Stored all map properties on World ({world.name})")
    
    def parse_vertex_buffer(self, vb: mapgeo_parser.VertexBuffer, vb_description: mapgeo_parser.VertexBufferDescription, mesh_data, mesh_idx: int = -1):
        """Parse vertex buffer data"""
        log = get_debug_log()
        vertices = []
        normals = []
        uvs = [[] for _ in range(8)]  # Support up to 8 UV channels
        colors = []
        
        vertex_size = vb_description.get_vertex_size()
        if vertex_size == 0:
            return vertices, normals, uvs, colors
        
        # Use mesh vertex count as it's the authoritative source
        vertex_count = mesh_data.vertex_count
        if vertex_count * vertex_size > len(vb.data):
            vertex_count = len(vb.data) // vertex_size
        
        # Find element offsets
        position_elem = None
        normal_elem = None
        color_elem = None
        uv_elems = {}
        
        # Check if this buffer has UV coordinates
        has_uvs = any(mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7 
                      for elem in vb_description.elements)
        
        # Debug: log vertex declaration for first few meshes and meshes without UVs
        should_log = (mesh_idx >= 0 and mesh_idx < 3) or (mesh_idx in [199, 1] and not has_uvs)
        if should_log:
            log.info("VertexBuffer", f"Mesh {mesh_idx}: {len(vb_description.elements)} elements, stride={vertex_size}")
            for elem in vb_description.elements:
                elem_name_str = f"ElementName.{elem.name}"
                if elem.name == mapgeo_parser.VertexElementName.POSITION:
                    elem_name_str = "POSITION"
                elif elem.name == mapgeo_parser.VertexElementName.NORMAL:
                    elem_name_str = "NORMAL"
                elif elem.name == mapgeo_parser.VertexElementName.PRIMARY_COLOR:
                    elem_name_str = "PRIMARY_COLOR"
                elif elem.name == mapgeo_parser.VertexElementName.SECONDARY_COLOR:
                    elem_name_str = "SECONDARY_COLOR"
                elif elem.name == mapgeo_parser.VertexElementName.FOG_COORDINATE:
                    elem_name_str = "FOG_COORDINATE"
                elif elem.name == mapgeo_parser.VertexElementName.BLEND_INDEX:
                    elem_name_str = "BLEND_INDEX"
                elif elem.name == mapgeo_parser.VertexElementName.BLEND_WEIGHT:
                    elem_name_str = "BLEND_WEIGHT"
                elif mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7:
                    elem_name_str = f"TEXCOORD{elem.name - mapgeo_parser.VertexElementName.TEXCOORD0}"
                log.info("VertexBuffer", f"  {elem_name_str}: format={elem.format}, offset={elem.offset}, size={elem.get_size()}")
        
        for elem in vb_description.elements:
            if elem.name == mapgeo_parser.VertexElementName.POSITION:
                position_elem = elem
            elif elem.name == mapgeo_parser.VertexElementName.NORMAL:
                normal_elem = elem
            elif elem.name == mapgeo_parser.VertexElementName.PRIMARY_COLOR:
                color_elem = elem
            elif mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7:
                uv_idx = elem.name - mapgeo_parser.VertexElementName.TEXCOORD0
                uv_elems[uv_idx] = elem
        
        # Identify TEXCOORD5 specially (3-component animation data, NOT a UV map)
        texcoord5_elem = uv_elems.pop(5, None)
        texcoord5_data = []  # Will hold (x, y, z) per vertex in League coords
        
        # Initialize only the UV channels that exist
        uvs = [[] for _ in range(8)]
        
        # Parse vertices
        for i in range(vertex_count):
            offset = i * vertex_size
            vertex_data = vb.data[offset:offset + vertex_size]
            
            # Position
            if position_elem:
                pos = self.read_element(vertex_data, position_elem)
                if pos:
                    # League of Legends coordinate system conversion
                    # League: X-right, Y-up, Z-forward (towards top of map)
                    # Blender: X-right, Y-forward, Z-up
                    # To orient correctly: swap Y and Z
                    vertices.append((pos[0], pos[2], pos[1]))
                else:
                    vertices.append((0, 0, 0))  # Fallback
            
            # Normal
            if normal_elem:
                norm = self.read_element(vertex_data, normal_elem)
                if norm:
                    # Apply same coordinate system conversion as positions
                    normals.append((norm[0], norm[2], norm[1]))
            
            # UVs - only append to channels that have elements
            for uv_idx, uv_elem in uv_elems.items():
                uv = self.read_element(vertex_data, uv_elem)
                if uv and len(uv) >= 2:
                    # Flip V coordinate for Blender
                    uvs[uv_idx].append((uv[0], 1.0 - uv[1]))
                else:
                    # Add default UV if reading failed but element exists
                    uvs[uv_idx].append((0.0, 0.0))
            
            # TEXCOORD5 - animation anchor positions (3 floats, NOT a UV)
            if texcoord5_elem:
                tc5 = self.read_element(vertex_data, texcoord5_elem)
                if tc5 and len(tc5) >= 3:
                    # Store raw League coordinates (coordinate swap happens on import to Blender)
                    # League(X, Y, Z) -> Blender(X, Z, Y)
                    texcoord5_data.append((tc5[0], tc5[2], tc5[1]))
                else:
                    texcoord5_data.append((0.0, 0.0, 0.0))
            
            # Colors
            if color_elem:
                color = self.read_element(vertex_data, color_elem)
                if color:
                    colors.append(color)
        
        return vertices, normals, uvs, colors, texcoord5_data
    
    def read_element(self, data: bytes, elem: mapgeo_parser.VertexElement):
        """Read a single vertex element"""
        try:
            offset = elem.offset
            fmt = elem.format
            
            if fmt == 0:  # X_FLOAT32
                return struct.unpack_from('<f', data, offset)
            elif fmt == 1:  # XY_FLOAT32
                return struct.unpack_from('<ff', data, offset)
            elif fmt == 2:  # XYZ_FLOAT32
                return struct.unpack_from('<fff', data, offset)
            elif fmt == 3:  # XYZW_FLOAT32
                return struct.unpack_from('<ffff', data, offset)
            elif fmt == 4:  # BGRA_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return (values[2]/255.0, values[1]/255.0, values[0]/255.0, values[3]/255.0)  # BGRA -> RGBA
            elif fmt == 5:  # ZYXW_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return (values[2]/255.0, values[1]/255.0, values[0]/255.0, values[3]/255.0)
            elif fmt == 6:  # RGBA_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 7:  # XY_PACKED1616 - 16-bit float (Half precision)
                return struct.unpack_from('<ee', data, offset)  # 'e' = 16-bit float
            elif fmt == 8:  # XYZ_PACKED161616 - 16-bit float (Half precision)
                return struct.unpack_from('<eee', data, offset)
            elif fmt == 9:  # XYZW_PACKED16161616 - 16-bit float (Half precision)
                return struct.unpack_from('<eeee', data, offset)
            elif fmt == 10:  # XY_PACKED88
                values = struct.unpack_from('<BB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 11:  # XYZ_PACKED888
                values = struct.unpack_from('<BBB', data, offset)
                return tuple(v / 255.0 for v in values)
            elif fmt == 12:  # XYZW_PACKED8888
                values = struct.unpack_from('<BBBB', data, offset)
                return tuple(v / 255.0 for v in values)
        except Exception as e:
            # Debug: log what failed
            log.warning("VertexBuffer", f"Failed to read element at offset {offset}, format {fmt}: {e}")
        
        return None
    
    def parse_index_buffer(self, ib: mapgeo_parser.IndexBuffer, mesh_data):
        """Parse index buffer into faces with material assignments"""
        faces = []
        face_materials = []  # Track which primitive each face belongs to
        
        # Parse all primitives
        for prim_idx, prim in enumerate(mesh_data.primitives):
            index_size = 2  # U16
            
            for i in range(0, prim.index_count, 3):
                idx_offset = (prim.start_index + i) * index_size
                
                if idx_offset + index_size * 3 > len(ib.data):
                    break
                
                i0 = struct.unpack_from('<H', ib.data, idx_offset)[0]
                i1 = struct.unpack_from('<H', ib.data, idx_offset + index_size)[0]
                i2 = struct.unpack_from('<H', ib.data, idx_offset + index_size * 2)[0]

                # Y/Z swap in parse_vertex_buffer changes handedness (reflection),
                # so triangle winding must be reversed to keep front faces correct.
                faces.append((i0, i2, i1))
                face_materials.append(prim_idx)  # Track which primitive this face belongs to
        
        return faces, face_materials
    
    def create_material(self, name: str):
        """Create a Blender material"""
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            
            # Basic setup with Principled BSDF
            if mat.node_tree:
                nodes = mat.node_tree.nodes
                nodes.clear()
                
                # Add Principled BSDF
                bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                bsdf.location = (0, 0)
                
                # Add Output
                output = nodes.new('ShaderNodeOutputMaterial')
                output.location = (300, 0)
                
                # Link
                mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        
        return mat
    
    def convert_transform_matrix(self, matrix_list):
        """Convert 16-float list to Blender Matrix with coordinate system conversion"""
        # Mapgeo stores matrices in row-major order
        # Build the matrix from League's coordinate system
        mat_league = Matrix([
            [matrix_list[0], matrix_list[4], matrix_list[8], matrix_list[12]],
            [matrix_list[1], matrix_list[5], matrix_list[9], matrix_list[13]],
            [matrix_list[2], matrix_list[6], matrix_list[10], matrix_list[14]],
            [matrix_list[3], matrix_list[7], matrix_list[11], matrix_list[15]]
        ])
        
        # League: X-right, Y-up, Z-forward
        # Blender: X-right, Y-forward, Z-up
        # Conversion: swap Y and Z axes
        conversion = Matrix([
            [1, 0, 0, 0],  # Blender X = League X
            [0, 0, 1, 0],  # Blender Y = League Z
            [0, 1, 0, 0],  # Blender Z = League Y
            [0, 0, 0, 1]
        ])
        
        # Apply conversion
        mat_blender = conversion @ mat_league @ conversion.inverted()
        return mat_blender


def apply_map_settings_to_scene(context, map_settings):
    """Apply map settings (sun, fog, world ambient) to the current scene.

    Standalone wrapper around IMPORT_SCENE_OT_mapgeo.create_scene_lighting
    so project_manager can call it without an operator instance.
    Returns True if lighting was created, False otherwise.
    """
    if not map_settings:
        return False
    settings = context.scene.mapgeo_settings
    col_name = settings.root_collection_name or "rey_map"
    collection = bpy.data.collections.get(col_name)
    if not collection:
        return False
    # create_scene_lighting does not use 'self'
    IMPORT_SCENE_OT_mapgeo.create_scene_lighting(None, context, collection, map_settings)
    return True


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_mapgeo.bl_idname, text="League of Legends Mapgeo (.mapgeo)")


# ─── Standalone import utility (used by utility operators in ui_panel.py) ───
# Replicates the full main importer pipeline with a filter function.

def read_vertex_element(data: bytes, elem):
    """Read a single vertex element from raw buffer data. Returns tuple or None."""
    try:
        offset = elem.offset
        fmt = elem.format
        
        if fmt == 0:    return struct.unpack_from('<f', data, offset)
        elif fmt == 1:  return struct.unpack_from('<ff', data, offset)
        elif fmt == 2:  return struct.unpack_from('<fff', data, offset)
        elif fmt == 3:  return struct.unpack_from('<ffff', data, offset)
        elif fmt == 4:
            v = struct.unpack_from('<BBBB', data, offset)
            return (v[2]/255.0, v[1]/255.0, v[0]/255.0, v[3]/255.0)
        elif fmt == 5:
            v = struct.unpack_from('<BBBB', data, offset)
            return (v[2]/255.0, v[1]/255.0, v[0]/255.0, v[3]/255.0)
        elif fmt == 6:
            v = struct.unpack_from('<BBBB', data, offset)
            return tuple(x / 255.0 for x in v)
        elif fmt == 7:  return struct.unpack_from('<ee', data, offset)
        elif fmt == 8:  return struct.unpack_from('<eee', data, offset)
        elif fmt == 9:  return struct.unpack_from('<eeee', data, offset)
        elif fmt == 10:
            v = struct.unpack_from('<BB', data, offset)
            return tuple(x / 255.0 for x in v)
        elif fmt == 11:
            v = struct.unpack_from('<BBB', data, offset)
            return tuple(x / 255.0 for x in v)
        elif fmt == 12:
            v = struct.unpack_from('<BBBB', data, offset)
            return tuple(x / 255.0 for x in v)
    except:
        pass
    return None


def _parse_vertex_buffer_standalone(vertex_buffer, vb_description, mesh_data):
    """Parse a single vertex buffer into components. Returns (vertices, normals, uvs[8], colors, texcoord5_data)."""
    vertices = []
    normals = []
    uvs = [[] for _ in range(8)]
    colors = []
    texcoord5_data = []
    
    vertex_size = vb_description.get_vertex_size()
    if vertex_size == 0:
        return vertices, normals, uvs, colors, texcoord5_data
    
    vertex_count = mesh_data.vertex_count
    if vertex_count * vertex_size > len(vertex_buffer.data):
        vertex_count = len(vertex_buffer.data) // vertex_size
    
    # Discover elements
    position_elem = None
    normal_elem = None
    color_elem = None
    uv_elems = {}
    texcoord5_elem = None
    
    for elem in vb_description.elements:
        if elem.name == mapgeo_parser.VertexElementName.POSITION:
            position_elem = elem
        elif elem.name == mapgeo_parser.VertexElementName.NORMAL:
            normal_elem = elem
        elif elem.name == mapgeo_parser.VertexElementName.PRIMARY_COLOR:
            color_elem = elem
        elif mapgeo_parser.VertexElementName.TEXCOORD0 <= elem.name <= mapgeo_parser.VertexElementName.TEXCOORD7:
            uv_idx = elem.name - mapgeo_parser.VertexElementName.TEXCOORD0
            if uv_idx == 5:
                texcoord5_elem = elem  # TEXCOORD5 is NOT a UV, it's bush animation data
            else:
                uv_elems[uv_idx] = elem
    
    for i in range(vertex_count):
        offset = i * vertex_size
        vdata = vertex_buffer.data[offset:offset + vertex_size]
        
        if position_elem:
            pos = read_vertex_element(vdata, position_elem)
            if pos and len(pos) >= 3:
                vertices.append((pos[0], pos[2], pos[1]))
            else:
                vertices.append((0, 0, 0))
        
        if normal_elem:
            n = read_vertex_element(vdata, normal_elem)
            if n and len(n) >= 3:
                normals.append((n[0], n[2], n[1]))
        
        for uv_idx, uv_elem in uv_elems.items():
            uv = read_vertex_element(vdata, uv_elem)
            if uv and len(uv) >= 2:
                uvs[uv_idx].append((uv[0], 1.0 - uv[1]))
            else:
                uvs[uv_idx].append((0.0, 0.0))
        
        if texcoord5_elem:
            tc5 = read_vertex_element(vdata, texcoord5_elem)
            if tc5 and len(tc5) >= 3:
                texcoord5_data.append((tc5[0], tc5[2], tc5[1]))
            else:
                texcoord5_data.append((0.0, 0.0, 0.0))
        
        if color_elem:
            color = read_vertex_element(vdata, color_elem)
            if color:
                colors.append(color)
    
    return vertices, normals, uvs, colors, texcoord5_data


def _parse_index_buffer_standalone(index_buffer, mesh_data):
    """Parse index buffer into faces with per-face primitive index. Returns (faces, face_materials)."""
    faces = []
    face_materials = []
    
    for prim_idx, prim in enumerate(mesh_data.primitives):
        for i in range(0, prim.index_count, 3):
            idx_offset = (prim.start_index + i) * 2
            if idx_offset + 6 > len(index_buffer.data):
                break
            i0, i1, i2 = struct.unpack_from('<HHH', index_buffer.data, idx_offset)
            # Match main importer winding correction after Y/Z swap.
            faces.append((i0, i2, i1))
            face_materials.append(prim_idx)
    
    return faces, face_materials


def _create_simple_material(name):
    """Create a basic Principled BSDF material."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        if mat.node_tree:
            nodes = mat.node_tree.nodes
            nodes.clear()
            bsdf = nodes.new('ShaderNodeBsdfPrincipled')
            bsdf.location = (0, 0)
            output = nodes.new('ShaderNodeOutputMaterial')
            output.location = (300, 0)
            mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def get_blender_transform(matrix_list):
    """Convert 16-float mapgeo transform to Blender Matrix with Y/Z swap."""
    mat_league = Matrix([
        [matrix_list[0], matrix_list[4], matrix_list[8], matrix_list[12]],
        [matrix_list[1], matrix_list[5], matrix_list[9], matrix_list[13]],
        [matrix_list[2], matrix_list[6], matrix_list[10], matrix_list[14]],
        [matrix_list[3], matrix_list[7], matrix_list[11], matrix_list[15]]
    ])
    conversion = Matrix([
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]
    ])
    return conversion @ mat_league @ conversion.inverted()


def import_filtered_meshes(context, filepath, mesh_filter_fn, collection_suffix="", import_particles=True):
    """
    Import meshes from a mapgeo file with full pipeline (materials, UVs, normals,
    vertex colors, lightmaps, baron hashes, custom properties, layer collections).
    
    This replicates the main IMPORT_SCENE_OT_mapgeo.import_mapgeo pipeline exactly,
    but only imports meshes for which mesh_filter_fn returns True.
    
    Args:
        context: Blender context
        filepath: Path to .mapgeo file
        mesh_filter_fn: callable(mesh_idx, mesh_data, mapgeo) -> bool. Return True to import.
                        Receives the full mapgeo object for access to vertex_buffer_descriptions etc.
        collection_suffix: Suffix for the collection name (e.g. "_Bushes", "_RenderRegions")
    
    Returns:
        (imported_count, error_message) - count of imported meshes, or error string
    """
    import hashlib
    log = get_debug_log()
    
    # Parse mapgeo file
    parser = mapgeo_parser.MapgeoParser()
    mapgeo = parser.read(filepath)
    
    if not mapgeo.meshes:
        return 0, "No meshes found in mapgeo file"
    
    # ─── Find or create root collection and sub-collections ───
    settings = context.scene.mapgeo_settings
    root_name = settings.root_collection_name if settings.root_collection_name else "rey_map"
    
    # Find existing root collection, or create it
    root_collection = bpy.data.collections.get(root_name)
    if root_collection is None:
        root_collection = bpy.data.collections.new(root_name)
        context.scene.collection.children.link(root_collection)
    
    # Find or create _Meshes sub-collection (all mesh objects go here)
    meshes_col_name = f"{root_name}_Meshes"
    meshes_collection = bpy.data.collections.get(meshes_col_name)
    if meshes_collection is None:
        meshes_collection = bpy.data.collections.new(meshes_col_name)
        root_collection.children.link(meshes_collection)
    
    # Find or create the specific target sub-collection (e.g. _Bushes, _RenderRegions)
    target_collection = None
    if collection_suffix:
        target_col_name = f"{root_name}{collection_suffix}"
        target_collection = bpy.data.collections.get(target_col_name)
        if target_collection is None:
            target_collection = bpy.data.collections.new(target_col_name)
            root_collection.children.link(target_collection)
    
    # Find or create layer collections
    layer_names = {
        mapgeo_parser.EnvironmentVisibility.LAYER_1: "Base",
        mapgeo_parser.EnvironmentVisibility.LAYER_2: "Inferno",
        mapgeo_parser.EnvironmentVisibility.LAYER_3: "Mountain",
        mapgeo_parser.EnvironmentVisibility.LAYER_4: "Ocean",
        mapgeo_parser.EnvironmentVisibility.LAYER_5: "Cloud",
        mapgeo_parser.EnvironmentVisibility.LAYER_6: "Hextech",
        mapgeo_parser.EnvironmentVisibility.LAYER_7: "Chemtech",
        mapgeo_parser.EnvironmentVisibility.LAYER_8: "Void",
    }
    layer_collections = {}
    for layer_flag, layer_name in layer_names.items():
        col_name = f"{root_name}_{layer_name}"
        layer_col = bpy.data.collections.get(col_name)
        if layer_col is None:
            layer_col = bpy.data.collections.new(col_name)
            root_collection.children.link(layer_col)
        layer_collections[layer_flag] = layer_col
    
    # Find or create baron state collections
    baron_state_names = {1: "BaronBase", 2: "BaronCup", 4: "BaronTunnel", 8: "BaronUpgraded"}
    baron_collections = {}
    for state_bit, state_name in baron_state_names.items():
        col_name = f"{root_name}_{state_name}"
        baron_col = bpy.data.collections.get(col_name)
        if baron_col is None:
            baron_col = bpy.data.collections.new(col_name)
            root_collection.children.link(baron_col)
        baron_collections[state_bit] = baron_col
    
    # ─── Load materials database ───
    materials = {}
    materials_db = {}
    material_loader_inst = None
    baron_parser_inst = None
    lightmap_color_scale = 1.0
    settings = context.scene.mapgeo_settings
    
    # Resolve materials path (linked mode or manual)
    resolved_materials = _resolve_materials_path(settings, filepath)
    if resolved_materials:
        settings.materials_file_path = resolved_materials
    
    if resolved_materials and os.path.exists(resolved_materials):
        has_original_assets = settings.assets_folder and os.path.exists(settings.assets_folder)
        has_custom_assets = settings.custom_assets_folder and os.path.exists(settings.custom_assets_folder)
        
        if has_original_assets or has_custom_assets:
            material_loader_inst = mat_loader.MaterialLoader(
                assets_folder=settings.assets_folder,
                levels_folder=settings.levels_folder if hasattr(settings, 'levels_folder') else "",
                map_py_path=settings.map_py_path if hasattr(settings, 'map_py_path') else "",
                dragon_layer=settings.dragon_layer_filter if hasattr(settings, 'dragon_layer_filter') else "LAYER_1",
                custom_assets_folder=settings.custom_assets_folder if hasattr(settings, 'custom_assets_folder') else "",
                prioritize_custom=settings.prioritize_custom_assets if hasattr(settings, 'prioritize_custom_assets') else False,
            )
            materials_db = material_loader_inst.load_materials(resolved_materials)
            
            map_settings = material_loader_inst.load_map_settings(resolved_materials)
            lightmap_color_scale = map_settings.get('lightmap_color_scale', 1.0) if map_settings else 1.0
            
            baron_parser_inst = baron_hash_parser.MaterialsBinParser(resolved_materials)
    
    # ─── Import matching meshes ───
    imported_count = 0
    
    for mesh_idx, mesh_data in enumerate(mapgeo.meshes):
        # Apply user filter (pass mapgeo for access to vertex descriptions etc.)
        if not mesh_filter_fn(mesh_idx, mesh_data, mapgeo):
            continue
        
        try:
            mesh_name = f"{root_name}_mesh_{mesh_idx:03d}"
            
            # Validate buffer IDs
            if not mesh_data.vertex_buffer_ids:
                continue
            vb_id = mesh_data.vertex_buffer_ids[0]
            if vb_id >= len(mapgeo.vertex_buffers):
                continue
            desc_id = mesh_data.vertex_declaration_id
            if desc_id >= len(mapgeo.vertex_buffer_descriptions):
                continue
            if mesh_data.index_buffer_id >= len(mapgeo.index_buffers):
                continue
            
            vertex_buffer = mapgeo.vertex_buffers[vb_id]
            vb_description = mapgeo.vertex_buffer_descriptions[desc_id]
            index_buffer = mapgeo.index_buffers[mesh_data.index_buffer_id]
            
            # Parse primary vertex buffer
            vertices, normals, uvs, colors, texcoord5_data = _parse_vertex_buffer_standalone(
                vertex_buffer, vb_description, mesh_data
            )
            
            # Parse secondary vertex buffers
            if len(mesh_data.vertex_buffer_ids) > 1:
                for sec_vb_idx in range(1, len(mesh_data.vertex_buffer_ids)):
                    sec_vb_id = mesh_data.vertex_buffer_ids[sec_vb_idx]
                    sec_desc_id = mesh_data.vertex_declaration_id + sec_vb_idx
                    if sec_vb_id >= len(mapgeo.vertex_buffers) or sec_desc_id >= len(mapgeo.vertex_buffer_descriptions):
                        continue
                    sec_vb = mapgeo.vertex_buffers[sec_vb_id]
                    sec_desc = mapgeo.vertex_buffer_descriptions[sec_desc_id]
                    _, sec_normals, sec_uvs, sec_colors, sec_tc5 = _parse_vertex_buffer_standalone(
                        sec_vb, sec_desc, mesh_data
                    )
                    if sec_normals and not normals:
                        normals = sec_normals
                    for uv_idx, uv_data in enumerate(sec_uvs):
                        if uv_data and not uvs[uv_idx]:
                            uvs[uv_idx] = uv_data
                    if sec_colors and not colors:
                        colors = sec_colors
                    if sec_tc5 and not texcoord5_data:
                        texcoord5_data = sec_tc5
            
            # Parse index buffer
            faces, face_materials = _parse_index_buffer_standalone(index_buffer, mesh_data)
            
            if not vertices or not faces:
                continue
            
            # ── Create Blender mesh ──
            bl_mesh = bpy.data.meshes.new(mesh_name)
            bl_mesh.from_pydata(vertices, [], faces)
            _optimized_mesh_update(bl_mesh)
            
            # Store per-face primitive index for multi-prim round-trip
            if len(mesh_data.primitives) > 1 and face_materials:
                prim_attr = bl_mesh.attributes.new(name="mapgeo_prim_idx", type='INT', domain='FACE')
                for fi in range(min(len(face_materials), len(bl_mesh.polygons))):
                    prim_attr.data[fi].value = face_materials[fi]
            
            # Normals
            if normals:
                _safe_set_vertex_normals(bl_mesh, normals, mesh_name)
            
            # All UV channels
            uv_channels_created = 0
            has_lightmap_uv = False
            for uv_idx, uv_data in enumerate(uvs):
                if uv_data and len(uv_data) > 0:
                    if uv_idx == 7:
                        uv_layer = bl_mesh.uv_layers.new(name="LightmapUV")
                        has_lightmap_uv = True
                        lm_scale = (1.0, 1.0)
                        lm_bias = (0.0, 0.0)
                        if mesh_data.baked_light:
                            lm_scale = mesh_data.baked_light.scale
                            lm_bias = mesh_data.baked_light.bias
                        for face in bl_mesh.polygons:
                            for loop_idx in face.loop_indices:
                                vert_idx = bl_mesh.loops[loop_idx].vertex_index
                                if vert_idx < len(uv_data):
                                    raw_u, raw_v = uv_data[vert_idx]
                                    orig_v = 1.0 - raw_v
                                    final_u = raw_u * lm_scale[0] + lm_bias[0]
                                    final_v = orig_v * lm_scale[1] + lm_bias[1]
                                    uv_layer.data[loop_idx].uv = (final_u, 1.0 - final_v)
                    else:
                        uv_layer = bl_mesh.uv_layers.new(name=f"UVMap{uv_idx}" if uv_idx > 0 else "UVMap")
                        for face in bl_mesh.polygons:
                            for loop_idx in face.loop_indices:
                                vert_idx = bl_mesh.loops[loop_idx].vertex_index
                                if vert_idx < len(uv_data):
                                    uv_layer.data[loop_idx].uv = uv_data[vert_idx]
                    uv_channels_created += 1
            
            # Vertex colors
            if colors:
                color_attr = bl_mesh.color_attributes.new(name="Color", type='BYTE_COLOR', domain='CORNER')
                for face in bl_mesh.polygons:
                    for loop_idx in face.loop_indices:
                        vert_idx = bl_mesh.loops[loop_idx].vertex_index
                        if vert_idx < len(colors):
                            col = colors[vert_idx]
                            if len(col) == 3:
                                color_attr.data[loop_idx].color = (*col, 1.0)
                            else:
                                color_attr.data[loop_idx].color = col[:4]
            
            # Raw normals preservation for render region meshes
            if normals and mesh_data.unknown_version18_int != 0:
                raw_attr = bl_mesh.attributes.new(name="raw_normals", type='FLOAT_VECTOR', domain='POINT')
                for vi in range(min(len(normals), len(bl_mesh.vertices))):
                    raw_attr.data[vi].vector = normals[vi]

            # TEXCOORD5 (bush animation)
            if texcoord5_data and len(texcoord5_data) > 0:
                tc5_attr = bl_mesh.attributes.new(name="TEXCOORD5", type='FLOAT_VECTOR', domain='POINT')
                for vert_idx in range(min(len(texcoord5_data), len(bl_mesh.vertices))):
                    tc5_attr.data[vert_idx].vector = texcoord5_data[vert_idx]
            
            # ── Materials ──
            material_mapping = {}
            mesh_lightmap_texture = None
            if has_lightmap_uv and mesh_data.baked_light and mesh_data.baked_light.texture:
                mesh_lightmap_texture = mesh_data.baked_light.texture
            
            mesh_texture_overrides = {}
            if mesh_data.texture_overrides:
                for override in mesh_data.texture_overrides:
                    for sampler_def in mapgeo.sampler_defs:
                        if sampler_def.index == override.index:
                            mesh_texture_overrides[sampler_def.name] = override.texture
                            break
            
            baked_paint_scale = mesh_data.baked_paint_scale
            baked_paint_bias = mesh_data.baked_paint_bias
            
            for prim_idx, prim in enumerate(mesh_data.primitives):
                mat_name = prim.material if prim.material else "Default"
                
                mat_cache_key = mat_name
                if mesh_lightmap_texture:
                    lm_hash = hashlib.md5(mesh_lightmap_texture.encode()).hexdigest()[:6]
                    mat_cache_key = f"{mat_name}__lm__{lm_hash}"
                if mesh_texture_overrides:
                    override_hash = hashlib.md5(str(sorted(mesh_texture_overrides.items())).encode()).hexdigest()[:6]
                    mat_cache_key = f"{mat_cache_key}__to__{override_hash}"
                if baked_paint_scale != (1.0, 1.0) or baked_paint_bias != (0.0, 0.0):
                    bp_hash = hashlib.md5(f"{baked_paint_scale}{baked_paint_bias}".encode()).hexdigest()[:6]
                    mat_cache_key = f"{mat_cache_key}__bp__{bp_hash}"
                
                if mat_cache_key not in materials:
                    if material_loader_inst and materials_db:
                        mat = material_loader_inst.get_or_create_material(
                            mat_name, materials_db,
                            lightmap_texture=mesh_lightmap_texture,
                            lightmap_color_scale=lightmap_color_scale,
                            texture_overrides=mesh_texture_overrides,
                            baked_paint_scale=baked_paint_scale,
                            baked_paint_bias=baked_paint_bias
                        )
                        materials[mat_cache_key] = mat
                    else:
                        materials[mat_cache_key] = _create_simple_material(mat_name)
                
                mat_slot_idx = -1
                for idx, mat_slot in enumerate(bl_mesh.materials):
                    if mat_slot == materials[mat_cache_key]:
                        mat_slot_idx = idx
                        break
                if mat_slot_idx == -1:
                    bl_mesh.materials.append(materials[mat_cache_key])
                    mat_slot_idx = len(bl_mesh.materials) - 1
                material_mapping[prim_idx] = mat_slot_idx
            
            if material_mapping:
                for face_idx, face in enumerate(bl_mesh.polygons):
                    if face_idx < len(face_materials):
                        prim_idx = face_materials[face_idx]
                        if prim_idx in material_mapping:
                            face.material_index = material_mapping[prim_idx]
            
            # ── Create object & link to collections ──
            obj = bpy.data.objects.new(mesh_name, bl_mesh)
            
            # Store per-primitive material names for multi-prim round-trip export
            if len(mesh_data.primitives) > 1:
                import json as _json
                prim_mats = [p.material for p in mesh_data.primitives]
                obj["mapgeo_prim_materials"] = _json.dumps(prim_mats)
            
            meshes_collection.objects.link(obj)
            
            # Link to target sub-collection (Bushes, RenderRegions, etc.)
            if target_collection is not None:
                target_collection.objects.link(obj)
            
            if mesh_data.visibility:
                for layer_flag, layer_col in layer_collections.items():
                    if mesh_data.visibility & layer_flag:
                        layer_col.objects.link(obj)
            
            # Transform
            obj.matrix_world = get_blender_transform(mesh_data.transform_matrix)
            
            # ── Custom properties (full set, identical to main importer) ──
            obj["visibility_layer"] = int(mesh_data.visibility)
            obj["quality"] = max(0, min(255, int(mesh_data.quality)))
            obj["layer_transition_behavior"] = mesh_data.layer_transition_behavior
            obj["render_flags"] = mesh_data.render_flags
            obj["disable_backface_culling"] = int(mesh_data.disable_backface_culling)
            
            # Lightmap data
            if mesh_data.baked_light:
                if mesh_data.baked_light.texture:
                    obj["lightmap_texture"] = mesh_data.baked_light.texture
                obj["lightmap_scale"] = list(mesh_data.baked_light.scale)
                obj["lightmap_bias"] = list(mesh_data.baked_light.bias)
            if mesh_data.stationary_light:
                if mesh_data.stationary_light.texture:
                    obj["stationary_light_texture"] = mesh_data.stationary_light.texture
                obj["stationary_light_scale"] = list(mesh_data.stationary_light.scale)
                obj["stationary_light_bias"] = list(mesh_data.stationary_light.bias)
            
            # Baked paint
            if mesh_data.baked_paint_scale != (1.0, 1.0) or mesh_data.baked_paint_bias != (0.0, 0.0):
                obj["baked_paint_scale"] = list(mesh_data.baked_paint_scale)
                obj["baked_paint_bias"] = list(mesh_data.baked_paint_bias)
            
            # Render region hash
            if mesh_data.unknown_version18_int:
                obj["render_region_hash"] = f"{mesh_data.unknown_version18_int:08X}"
            
            # Baron hash
            if mesh_data.visibility_controller_path_hash:
                baron_hash_str = f"{mesh_data.visibility_controller_path_hash:08X}"
                obj["baron_hash"] = baron_hash_str
                
                if baron_parser_inst:
                    try:
                        controller = baron_parser_inst.decode_baron_hash(baron_hash_str)
                        if controller.baron_layers:
                            baron_layers_list = sorted(list(controller.baron_layers))
                            obj["baron_layers_decoded"] = str(baron_layers_list)
                        if controller.dragon_layers:
                            dragon_layers_list = sorted(list(controller.dragon_layers))
                            obj["baron_dragon_layers_decoded"] = str(dragon_layers_list)
                        obj["baron_parent_mode"] = controller.parent_mode
                    except Exception as e:
                        log.warning("Import", f"Could not decode baron hash {baron_hash_str}: {e}")
            
            # Link to baron collections after properties are set
            if "baron_layers_decoded" in obj and obj["baron_layers_decoded"]:
                try:
                    import ast
                    baron_layers = ast.literal_eval(obj["baron_layers_decoded"])
                    for baron_state_bit in baron_layers:
                        if baron_state_bit in baron_collections:
                            baron_collections[baron_state_bit].objects.link(obj)
                except Exception:
                    pass
            
            # Bush flag (if TEXCOORD5 present)
            if texcoord5_data and len(texcoord5_data) > 0:
                obj["is_bush"] = True
            
            # Point lights
            if obj.get("point_light_enabled", False):
                try:
                    light_color = obj.get("point_light_color", [1.0, 0.95, 0.8])
                    light_intensity = obj.get("point_light_intensity", 500.0)
                    light_radius = obj.get("point_light_radius", 5.0)
                    offset_z = obj.get("point_light_offset_z", 0.0)
                    light_data = bpy.data.lights.new(name=f"{mesh_name}_PointLight", type='POINT')
                    light_data.energy = light_intensity
                    light_data.color = light_color
                    light_data.shadow_soft_size = light_radius
                    light_obj = bpy.data.objects.new(name=f"{mesh_name}_PointLight", object_data=light_data)
                    light_obj.location = obj.location.copy()
                    light_obj.location.z += offset_z
                    meshes_collection.objects.link(light_obj)
                    light_obj.parent = obj
                    log.light_created()
                except Exception as e:
                    log.light_failed(f"{mesh_name}: {e}")
            
            imported_count += 1
            log.mesh_imported()
            if imported_count <= 5 or imported_count % 100 == 0:
                uv_info = f", {uv_channels_created} UV" if uv_channels_created > 0 else ""
                log.info("Mesh", f"Mesh {mesh_idx}: {len(vertices)} verts, {len(faces)} faces{uv_info}")
        
        except Exception as e:
            log.mesh_failed(f"mesh_{mesh_idx:03d}", str(e))
            import traceback
            traceback.print_exc()
            continue
    
    suffix_label = collection_suffix.strip('_') if collection_suffix else 'filtered'
    log.info("Import", f"Filtered import ({suffix_label}): {imported_count} meshes into '{root_name}'")
    
    # Finalize texture packing (batch operation for performance)
    if material_loader_inst and hasattr(material_loader_inst, 'tex_converter'):
        material_loader_inst.tex_converter.pack_all_images()
    
    # Update visibility
    try:
        import sys
        addon_module = sys.modules.get(__package__)
        if addon_module and hasattr(addon_module, 'update_environment_visibility'):
            addon_module.update_environment_visibility(settings, context)
    except Exception:
        pass

    # Auto-import particles from materials file when available
    if import_particles:
        try:
            if resolved_materials:
                from . import particles_materials
                particles_materials.import_particles_from_materials(context, resolved_materials, log=log)
        except Exception:
            pass

    # Auto-import GdsMapObject entries from materials file
    if import_particles:
        try:
            if resolved_materials:
                from . import map_objects_import
                map_objects_import.import_map_objects_from_materials(context, resolved_materials, log=log)
        except Exception:
            pass

    return imported_count, None


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_mapgeo)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_mapgeo)
