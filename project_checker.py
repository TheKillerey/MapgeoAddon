"""
Project Integrity Checker for MapgeoAddon

Validates all cross-file references in a loaded mod project:
  - Mapgeo mesh primitives → materials.bin  (material names)
  - materials.bin samplers → texture files   (texture paths)
  - Mapgeo texture overrides                 (v17+ per-mesh textures)
  - Mapgeo visibility controller hashes      (v15+ mesh & bucket-grid links)
  - Custom bucket grid detection             (known issue warning)
  - Linked bin files                         (materials.bin header linked_files)
  - VFX / MapParticle cross-links            (TYPE_LINK integrity)
  - Lightmap & stationary-light textures     (baked_light / stationary_light channels)
  - Audio / soundbank references             (linked .bnk / .wpk paths)

Results are stored in scene.project_checker (ProjectCheckerSettings) and
displayed as a sub-panel under the Project Manager.
"""

import bpy
import os
from datetime import datetime
from bpy.props import (
    StringProperty, EnumProperty, IntProperty,
    CollectionProperty, PointerProperty, BoolProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList


# ============================================================================
# Severity icon mapping
# ============================================================================

_SEV_ICONS = {
    'ERROR':   'ERROR',
    'WARNING': 'QUESTION',
    'INFO':    'INFO',
}

_AUDIO_EXTENSIONS = {'.bnk', '.wpk', '.ogg', '.wav', '.mp3'}


# ============================================================================
# Property Groups
# ============================================================================

class CheckIssue(PropertyGroup):
    severity: EnumProperty(
        name="Severity",
        items=[
            ('ERROR',   'Error',   ''),
            ('WARNING', 'Warning', ''),
            ('INFO',    'Info',    ''),
        ],
        default='INFO',
    )
    category:  StringProperty(name="Category",  default="")
    message:   StringProperty(name="Message",   default="")
    detail:    StringProperty(name="Detail",    default="")
    file_path: StringProperty(name="File",      default="", subtype='FILE_PATH')


class ProjectCheckerSettings(PropertyGroup):
    issues:        CollectionProperty(type=CheckIssue)
    active_index:  IntProperty(default=0)
    last_run:      StringProperty(default="")
    error_count:   IntProperty(default=0)
    warning_count: IntProperty(default=0)
    info_count:    IntProperty(default=0)
    filter_mode:   EnumProperty(
        name="Filter",
        items=[
            ('ALL',     'All',      '', 'COLLAPSEMENU', 0),
            ('ERROR',   'Errors',   '', 'ERROR',        1),
            ('WARNING', 'Warnings', '', 'QUESTION',     2),
            ('INFO',    'Info',     '', 'INFO',         3),
        ],
        default='ALL',
    )


# ============================================================================
# Core Checker
# ============================================================================

# FNV-1a 32-bit (same as propertybin_parser)
def _fnv1a_32(s: str) -> int:
    s = s.lower()
    h = 0x811c9dc5
    for c in s:
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# Known type hashes
_HASH_STATIC_MAT   = 0xff9d3409
_HASH_VFX_SYSTEM   = 0x45cd899f
_HASH_MAP_PLACEABLE= 0xb25c0a3f
_HASH_MAP_PARTICLE = 0x24a31b3e
_HASH_SUN          = 0x169a2f9c
_HASH_BAKE         = 0x6a4a3409
_HASH_VIS_CTRL     = 0xe21083b5
_HASH_DRAGON_LAYER = 0xc406a533
_HASH_BARON_LAYER  = 0xec733fe2
_HASH_NAMED_CTRL   = 0xe07edfa4
_HASH_MUTATOR      = 0x4275b121

# Known field hashes
_HASH_NAME          = 0x8d39bde6
_HASH_TEXTURE_PATH  = 0xf0a363e3
_HASH_SAMPLER_VALS  = 0x0a6f0eb5

# Bin field types
_TYPE_STRING    = 16
_TYPE_FILE      = 18
_TYPE_CONTAINER = 0x80
_TYPE_STRUCT    = 0x82
_TYPE_EMBEDDED  = 0x83
_TYPE_LINK      = 0x84
_TYPE_OPTIONAL  = 0x85
_TYPE_MAP       = 0x86


def _walk_fields(fields):
    """Yield every leaf/nested field dict recursively."""
    if not fields:
        return
    for f in fields:
        yield f
        # Nested containers / structs store their children in 'items'
        if f.get('type') in (_TYPE_CONTAINER, 0x81):
            for item in f.get('items', []):
                if isinstance(item, dict):
                    if 'fields' in item:
                        yield from _walk_fields(item['fields'])
                    else:
                        yield item
        # Struct / embedded / optional with inline fields
        if f.get('type') in (_TYPE_STRUCT, _TYPE_EMBEDDED, _TYPE_OPTIONAL):
            inner = f.get('value')
            if isinstance(inner, dict) and 'fields' in inner:
                yield from _walk_fields(inner['fields'])
            elif isinstance(inner, list):
                yield from _walk_fields(inner)
        # Map type: iterate values
        if f.get('type') == _TYPE_MAP:
            for _k, v in f.get('pairs', []):
                if isinstance(v, dict) and 'fields' in v:
                    yield from _walk_fields(v['fields'])


def _tex_exists(tex_path: str, roots: list) -> bool:
    """Check whether a texture path exists under any of the given root dirs."""
    tex_norm = tex_path.replace('\\', '/')
    for root in roots:
        if os.path.isfile(os.path.join(root, tex_norm)):
            return True
    return False


def _file_exists(rel_path: str, roots: list) -> bool:
    norm = rel_path.replace('\\', '/')
    for root in roots:
        if os.path.isfile(os.path.join(root, norm)):
            return True
    return False


def run_checks(project_settings) -> list:
    """
    Run all integrity checks against the currently loaded project.
    Returns a list of issue dicts:
      {severity, category, message, detail, file_path}
    """
    from . import mapgeo_parser, propertybin_parser

    issues = []

    def add(severity, category, message, detail="", file_path=""):
        issues.append({
            'severity': severity,
            'category': category,
            'message':  message,
            'detail':   detail,
            'file_path': file_path,
        })

    s = project_settings
    project_folder   = bpy.path.abspath(s.project_folder)   if s.project_folder   else ""
    league_install   = bpy.path.abspath(s.league_install)   if s.league_install   else ""
    loaded_mapgeo    = bpy.path.abspath(s.loaded_mapgeo_path)    if s.loaded_mapgeo_path    else ""
    loaded_materials = bpy.path.abspath(s.loaded_materials_path) if s.loaded_materials_path else ""
    map_id           = s.project_map_id or ""

    if not project_folder:
        add('ERROR', 'Setup', 'No project folder is set.')
        return issues

    # ── Resolve WAD cache dirs ─────────────────────────────────────────────
    wad_cache_dir    = ""
    levels_cache_dir = ""
    if map_id and league_install and os.path.isdir(league_install):
        try:
            from . import project_manager
            wad_cache_dir = project_manager._ensure_riot_wad_cache(league_install, map_id)
        except Exception as e:
            add('INFO', 'Setup', f'Could not access Riot WAD cache: {e}')
        try:
            from . import project_manager
            levels_cache_dir = project_manager._ensure_riot_levels_wad_cache(league_install, map_id)
        except Exception:
            pass

    asset_roots    = [r for r in [project_folder, wad_cache_dir] if r]
    lightmap_roots = [r for r in [project_folder, levels_cache_dir, wad_cache_dir] if r]

    # ── Parse mapgeo ──────────────────────────────────────────────────────
    mapgeo_data = None
    if loaded_mapgeo and os.path.isfile(loaded_mapgeo):
        try:
            mapgeo_data = mapgeo_parser.MapgeoParser().read(loaded_mapgeo)
            add('INFO', 'Mapgeo',
                f'Parsed mapgeo v{mapgeo_data.version}: '
                f'{len(mapgeo_data.meshes)} meshes, '
                f'{len(mapgeo_data.bucket_grids)} bucket grid(s).',
                file_path=loaded_mapgeo)
        except Exception as e:
            add('ERROR', 'Mapgeo', f'Failed to parse mapgeo: {e}', file_path=loaded_mapgeo)
    elif loaded_mapgeo:
        add('WARNING', 'Mapgeo', 'Loaded mapgeo path not found on disk.', detail=loaded_mapgeo)
    else:
        add('WARNING', 'Mapgeo', 'No mapgeo loaded — mapgeo checks skipped.')

    # ── Parse materials bin ───────────────────────────────────────────────
    bin_data = None
    if loaded_materials and os.path.isfile(loaded_materials):
        try:
            bin_data = propertybin_parser.parse_bin(loaded_materials)
            add('INFO', 'Materials',
                f'Parsed materials.bin: {len(bin_data.get("entries", []))} entries.',
                file_path=loaded_materials)
        except Exception as e:
            add('ERROR', 'Materials', f'Failed to parse materials.bin: {e}', file_path=loaded_materials)
    elif loaded_materials:
        add('WARNING', 'Materials', 'Loaded materials path not found on disk.', detail=loaded_materials)
    else:
        add('WARNING', 'Materials', 'No materials.bin loaded — materials checks skipped.')

    # ── Build lookup sets from bin ────────────────────────────────────────
    all_path_hashes  = set()   # "0x1a2b3c4d" hex strings
    mat_path_hashes  = set()   # path_hash hex strings for StaticMaterialDef entries
    mat_names_lower  = set()   # lowercased name strings from HASH_NAME fields

    if bin_data:
        for entry in bin_data.get('entries', []):
            ph = entry.get('path_hash', '')
            th = entry.get('type_hash', '')
            all_path_hashes.add(ph)
            th_int = int(th, 16) if (th and th.startswith('0x')) else 0
            if th_int == _HASH_STATIC_MAT:
                mat_path_hashes.add(ph)
                for fld in entry.get('fields', []):
                    ni = fld.get('name_hash_int', 0)
                    if ni == _HASH_NAME and fld.get('type') == _TYPE_STRING:
                        mat_names_lower.add(fld['value'].lower())
                        break

    # ── CHECK 1: Mapgeo → Materials ───────────────────────────────────────
    if mapgeo_data and bin_data:
        missing_mats = set()
        for mesh in mapgeo_data.meshes:
            for prim in mesh.primitives:
                name = prim.material
                if not name:
                    continue
                # Look up by FNV-1a hash (robust, doesn't rely on name field)
                ph = hex(_fnv1a_32(name))
                if ph not in all_path_hashes:
                    missing_mats.add(name)

        if missing_mats:
            for name in sorted(missing_mats):
                add('ERROR', 'Materials',
                    'Mapgeo material not found in materials.bin',
                    detail=name, file_path=loaded_mapgeo)
        else:
            total = sum(len(m.primitives) for m in mapgeo_data.meshes)
            add('INFO', 'Materials',
                f'All {total} mesh primitive materials resolve OK.')

    # ── CHECK 2: Materials → Textures ─────────────────────────────────────
    if bin_data:
        checked_tex  = set()
        missing_tex  = []
        ok_count     = 0

        for entry in bin_data.get('entries', []):
            for fld in entry.get('fields', []):
                if fld.get('name_hash_int') != _HASH_SAMPLER_VALS:
                    continue
                for sampler in fld.get('items', []):
                    if not isinstance(sampler, dict):
                        continue
                    for sf in sampler.get('fields', []):
                        if sf.get('name_hash_int') == _HASH_TEXTURE_PATH \
                                and sf.get('type') == _TYPE_STRING:
                            tex = sf.get('value', '').replace('\\', '/')
                            if not tex or tex in checked_tex:
                                continue
                            checked_tex.add(tex)
                            if _tex_exists(tex, asset_roots):
                                ok_count += 1
                            else:
                                missing_tex.append(tex)

        for tex in missing_tex:
            add('WARNING', 'Textures',
                'Texture file not found on disk',
                detail=tex, file_path=loaded_materials)
        if ok_count:
            add('INFO', 'Textures',
                f'{ok_count} unique texture(s) found OK, {len(missing_tex)} missing.')

    # ── CHECK 3: Mapgeo texture overrides (v17+) ──────────────────────────
    if mapgeo_data and bin_data:
        sampler_def_names = {sd.index: sd.name for sd in mapgeo_data.sampler_defs}
        override_missing = []
        override_ok = 0

        for mesh in mapgeo_data.meshes:
            for ov in mesh.texture_overrides:
                tex = ov.texture.replace('\\', '/')
                if not tex:
                    continue
                if _tex_exists(tex, asset_roots):
                    override_ok += 1
                else:
                    slot_name = sampler_def_names.get(ov.index, f'slot {ov.index}')
                    override_missing.append((tex, slot_name))

        for tex, slot in override_missing:
            add('WARNING', 'Textures',
                f'Texture override not found (sampler: {slot})',
                detail=tex, file_path=loaded_mapgeo)
        if override_ok:
            add('INFO', 'Textures',
                f'{override_ok} texture override(s) found OK.')

    # ── CHECK 4: Custom bucket grid ───────────────────────────────────────
    if mapgeo_data:
        active_grids = [bg for bg in mapgeo_data.bucket_grids if not bg.is_disabled]
        if active_grids:
            riot_mapgeo = None
            if wad_cache_dir:
                geo_root = os.path.join(wad_cache_dir, 'data', 'maps', 'mapgeometry')
                if os.path.isdir(geo_root):
                    for root, _dirs, files in os.walk(geo_root):
                        for fn in files:
                            if fn.endswith('.mapgeo'):
                                try:
                                    riot_mapgeo = mapgeo_parser.MapgeoParser().read(
                                        os.path.join(root, fn))
                                except Exception:
                                    continue
                                break
                        if riot_mapgeo:
                            break

            if riot_mapgeo:
                riot_hashes  = {bg.path_hash for bg in riot_mapgeo.bucket_grids}
                local_hashes = {bg.path_hash for bg in active_grids}
                is_custom    = local_hashes != riot_hashes
            else:
                is_custom = True   # no basis for comparison → assume custom

            if is_custom:
                add('WARNING', 'BucketGrid',
                    f'Custom bucket grid detected ({len(active_grids)} active grid(s)).',
                    detail='Custom bucket grids cause issues until the bucket grid feature '
                           'is fully implemented. They will be handled automatically later.',
                    file_path=loaded_mapgeo)
            else:
                add('INFO', 'BucketGrid',
                    f'Bucket grid matches Riot base ({len(active_grids)} grid(s)). OK.')
        else:
            add('INFO', 'BucketGrid', 'No active bucket grids found.')

    # ── CHECK 5: Visibility controller path_hashes ────────────────────────
    if mapgeo_data and bin_data:
        bad_vis  = []
        ok_vis   = 0

        for i, mesh in enumerate(mapgeo_data.meshes):
            h = mesh.visibility_controller_path_hash
            if h and h != 0:
                ph_str = hex(h)
                if ph_str not in all_path_hashes:
                    bad_vis.append(f'Mesh #{i}: {ph_str}')
                else:
                    ok_vis += 1

        for bg in mapgeo_data.bucket_grids:
            h = bg.path_hash
            if h and h != 0:
                ph_str = hex(h)
                if ph_str not in all_path_hashes:
                    bad_vis.append(f'BucketGrid: {ph_str}')
                else:
                    ok_vis += 1

        for item in bad_vis:
            add('ERROR', 'Visibility',
                'Visibility controller path_hash not in materials.bin',
                detail=item, file_path=loaded_mapgeo)
        if ok_vis:
            add('INFO', 'Visibility', f'{ok_vis} visibility controller(s) resolved OK.')

    # ── CHECK 6: Linked bin files ─────────────────────────────────────────
    if bin_data:
        for linked in bin_data.get('linked_files', []):
            norm = linked.replace('\\', '/')
            ext  = os.path.splitext(norm)[1].lower()
            cat  = 'Soundbanks' if ext in _AUDIO_EXTENSIONS else 'LinkedFiles'

            if _file_exists(norm, asset_roots):
                add('INFO', cat,
                    f'Linked file found: {os.path.basename(norm)}',
                    detail=norm)
            else:
                add('WARNING', cat,
                    f'Linked file not found: {os.path.basename(norm)}',
                    detail=norm, file_path=loaded_materials)

    # ── CHECK 7: VFX / MapParticle cross-links ────────────────────────────
    if bin_data:
        vfx_types = {_HASH_VFX_SYSTEM, _HASH_MAP_PLACEABLE, _HASH_MAP_PARTICLE}
        bad_links  = []
        ok_links   = 0

        for entry in bin_data.get('entries', []):
            th = entry.get('type_hash', '')
            th_int = int(th, 16) if (th and th.startswith('0x')) else 0
            if th_int not in vfx_types:
                continue
            for fld in _walk_fields(entry.get('fields', [])):
                if fld.get('type') == _TYPE_LINK:
                    target = fld.get('value', '')
                    if target and target not in all_path_hashes:
                        bad_links.append(
                            f'Entry {entry.get("path_hash")} → {target}')
                    else:
                        ok_links += 1

        for item in bad_links:
            add('WARNING', 'VFX',
                'VFX/particle link target not found in materials.bin',
                detail=item, file_path=loaded_materials)
        if ok_links:
            add('INFO', 'VFX', f'{ok_links} VFX link(s) resolved OK.')

    # ── CHECK 8: Lightmap / stationary-light textures ─────────────────────
    if mapgeo_data:
        checked_lm = set()
        bad_lm  = []
        ok_lm   = 0

        for mesh in mapgeo_data.meshes:
            for channel, label in [
                (mesh.baked_light,       'BakedLight'),
                (mesh.stationary_light,  'StationaryLight'),
            ]:
                if not (channel and channel.texture):
                    continue
                tex = channel.texture.replace('\\', '/')
                if tex in checked_lm:
                    continue
                checked_lm.add(tex)
                if _tex_exists(tex, lightmap_roots):
                    ok_lm += 1
                else:
                    bad_lm.append((label, tex))

        for label, tex in bad_lm:
            add('WARNING', 'Lightmaps',
                f'{label} texture not found on disk',
                detail=tex, file_path=loaded_mapgeo)
        if ok_lm:
            add('INFO', 'Lightmaps', f'{ok_lm} lightmap texture(s) found OK.')

    # ── CHECK 9: TYPE_FILE WAD references ─────────────────────────────────
    # Only run if wad_tool hash tables are loaded to avoid slow load on every check
    if bin_data:
        try:
            from . import wad_tool
            # Only attempt resolution if hashes are already cached
            if wad_tool._wad_hashes or wad_tool._custom_hashes:
                unresolved_file_refs = []
                seen_hashes = set()

                for entry in bin_data.get('entries', []):
                    for fld in _walk_fields(entry.get('fields', [])):
                        if fld.get('type') == _TYPE_FILE:
                            hval = fld.get('value', '')
                            if hval in seen_hashes:
                                continue
                            seen_hashes.add(hval)
                            try:
                                h_int = int(hval, 16)
                                resolved = wad_tool.resolve_wad_hash(h_int)
                                if not resolved:
                                    unresolved_file_refs.append(hval)
                            except Exception:
                                pass

                if unresolved_file_refs:
                    add('INFO', 'WAD Refs',
                        f'{len(unresolved_file_refs)} WAD file reference(s) could not be resolved '
                        'to a known path (may just be missing from the hash dictionary).',
                        detail=', '.join(unresolved_file_refs[:8]) +
                               (f' … (+{len(unresolved_file_refs)-8} more)'
                                if len(unresolved_file_refs) > 8 else ''))
        except Exception:
            pass

    # ── CHECK 10: MapSkin / map.bin links ─────────────────────────────────
    # If the project has a map11.bin / shippping bin, check it too
    if project_folder and map_id:
        map_id_num = ''.join(c for c in map_id if c.isdigit())
        map_id_lower = f'map{map_id_num}'
        shipping_candidates = [
            os.path.join(project_folder, 'data', 'maps', 'shipping',
                         map_id_lower, f'{map_id_lower}.bin'),
            os.path.join(wad_cache_dir, 'data', 'maps', 'shipping',
                         map_id_lower, f'{map_id_lower}.bin') if wad_cache_dir else '',
        ]
        for spath in shipping_candidates:
            if spath and os.path.isfile(spath):
                try:
                    sbin = propertybin_parser.parse_bin(spath)
                    skins_entry_count = sum(
                        1 for e in sbin.get('entries', [])
                        if e.get('type_hash', '') == hex(_HASH_VIS_CTRL)
                    )
                    add('INFO', 'MapBin',
                        f'Shipping map bin parsed OK: {len(sbin.get("entries", []))} entries',
                        detail=spath)
                    # Check its linked_files too
                    for lf in sbin.get('linked_files', []):
                        norm = lf.replace('\\', '/')
                        if not _file_exists(norm, asset_roots):
                            add('WARNING', 'MapBin',
                                f'map.bin linked file not found: {os.path.basename(norm)}',
                                detail=norm, file_path=spath)
                except Exception as e:
                    add('WARNING', 'MapBin',
                        f'Could not parse shipping bin: {e}', detail=spath)
                break

    return issues


# ============================================================================
# Operator
# ============================================================================

class PROJ_OT_run_integrity_check(Operator):
    bl_idname = "project.run_integrity_check"
    bl_label = "Check Project Integrity"
    bl_description = (
        "Scan all loaded project files for broken references: "
        "materials, textures, VFX links, visibility controllers, "
        "linked bins, lightmaps, and audio banks"
    )

    def execute(self, context):
        checker  = context.scene.project_checker
        settings = context.scene.project_settings

        if not settings.project_folder:
            self.report({'ERROR'}, "No project folder set in Project Manager.")
            return {'CANCELLED'}

        # Clear old results
        checker.issues.clear()

        try:
            issues = run_checks(settings)
        except Exception as e:
            import traceback
            self.report({'ERROR'}, f"Integrity check failed: {e}")
            print(f"[Project Checker] Exception:\n{traceback.format_exc()}")
            return {'CANCELLED'}

        # Populate collection
        errors = warnings = infos = 0
        for issue in issues:
            item              = checker.issues.add()
            item.severity     = issue['severity']
            item.category     = issue['category']
            item.message      = issue['message']
            item.detail       = issue.get('detail', '')
            item.file_path    = issue.get('file_path', '')
            if issue['severity'] == 'ERROR':
                errors += 1
            elif issue['severity'] == 'WARNING':
                warnings += 1
            else:
                infos += 1

        checker.error_count   = errors
        checker.warning_count = warnings
        checker.info_count    = infos
        checker.last_run      = datetime.now().strftime("%Y-%m-%d %H:%M")
        checker.active_index  = 0

        msg = f"Check complete: {errors} error(s), {warnings} warning(s), {infos} info"
        self.report({'WARNING' if errors else 'INFO'}, msg)
        return {'FINISHED'}


class PROJ_OT_clear_check_results(Operator):
    bl_idname = "project.clear_check_results"
    bl_label  = "Clear Results"
    bl_description = "Clear all integrity check results"

    def execute(self, context):
        c = context.scene.project_checker
        c.issues.clear()
        c.error_count = c.warning_count = c.info_count = 0
        c.last_run = ""
        return {'FINISHED'}


class PROJ_OT_open_issue_file(Operator):
    """Open the file associated with the selected issue in the OS file browser."""
    bl_idname  = "project.open_issue_file"
    bl_label   = "Show File"
    bl_description = "Reveal this file in the OS file explorer"
    file_path: StringProperty(default="")

    def execute(self, context):
        path = self.file_path
        if path and os.path.isfile(path):
            import subprocess
            try:
                subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
            except Exception:
                pass
        return {'FINISHED'}


# ============================================================================
# UIList
# ============================================================================

class PROJ_UL_check_issues(UIList):
    bl_idname = "PROJ_UL_check_issues"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        checker = data
        filter_mode = checker.filter_mode

        if filter_mode != 'ALL' and item.severity != filter_mode:
            return

        row = layout.row(align=True)

        # Severity badge
        sev_icon = _SEV_ICONS.get(item.severity, 'INFO')
        row.label(text="", icon=sev_icon)

        # Category
        cat_col = row.column()
        cat_col.ui_units_x = 8
        cat_col.label(text=item.category)

        # Message
        row.label(text=item.message)

    def filter_items(self, context, data, property):
        checker = data
        filter_mode = checker.filter_mode
        items = getattr(data, property)

        flt_flags = []
        flt_order = list(range(len(items)))

        if filter_mode == 'ALL':
            flt_flags = [self.bitflag_filter_item] * len(items)
        else:
            for item in items:
                if item.severity == filter_mode:
                    flt_flags.append(self.bitflag_filter_item)
                else:
                    flt_flags.append(0)

        return flt_flags, flt_order


# ============================================================================
# Sub-panel (child of Project Manager)
# ============================================================================

class VIEW3D_PT_project_checker(Panel):
    bl_label   = "Project Integrity"
    bl_idname  = "VIEW3D_PT_project_checker"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'LoL Mapgeo'
    bl_parent_id   = 'VIEW3D_PT_project_manager'
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        checker = context.scene.project_checker
        layout  = self.layout
        if checker.error_count > 0:
            layout.label(text="", icon='ERROR')
        elif checker.warning_count > 0:
            layout.label(text="", icon='QUESTION')
        elif checker.last_run:
            layout.label(text="", icon='CHECKMARK')

    def draw(self, context):
        layout  = self.layout
        checker = context.scene.project_checker
        settings = context.scene.project_settings

        # ── Run button ────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.3
        op_row = row.row(align=True)
        op_row.enabled = bool(settings.project_folder)
        op_row.operator("project.run_integrity_check",
                        text="Check Project", icon='VIEWZOOM')

        if checker.last_run:
            row.operator("project.clear_check_results", text="", icon='X')

        if checker.last_run:
            layout.label(text=f"Last run: {checker.last_run}", icon='TIME')

        # ── Summary ───────────────────────────────────────────────────────
        if checker.last_run:
            sum_row = layout.row(align=True)
            sum_row.alignment = 'CENTER'
            err_col = sum_row.column()
            err_col.alert = checker.error_count > 0
            err_col.label(text=f"{checker.error_count} Error(s)",   icon='ERROR')
            sum_row.label(text=f"{checker.warning_count} Warning(s)", icon='QUESTION')
            sum_row.label(text=f"{checker.info_count} Info",          icon='INFO')

            # ── Filter bar ────────────────────────────────────────────────
            layout.prop(checker, "filter_mode", expand=True)

        # ── Issue list ────────────────────────────────────────────────────
        if checker.issues:
            # Count visible items for row height
            fm = checker.filter_mode
            visible = sum(
                1 for it in checker.issues
                if fm == 'ALL' or it.severity == fm
            )
            rows = max(3, min(visible, 10))

            layout.template_list(
                "PROJ_UL_check_issues", "",
                checker, "issues",
                checker, "active_index",
                rows=rows,
            )

            # ── Detail box for selected issue ─────────────────────────────
            idx = checker.active_index
            if 0 <= idx < len(checker.issues):
                item = checker.issues[idx]
                detail_box = layout.box()
                detail_box.scale_y = 0.85

                sev_icon = _SEV_ICONS.get(item.severity, 'INFO')
                detail_box.label(
                    text=f"[{item.severity}] {item.category}: {item.message}",
                    icon=sev_icon)

                if item.detail:
                    # Wrap long detail text
                    detail = item.detail
                    chunk = 60
                    while detail:
                        detail_box.label(text=detail[:chunk])
                        detail = detail[chunk:]

                if item.file_path and os.path.isfile(item.file_path):
                    op = detail_box.operator(
                        "project.open_issue_file",
                        text=f"Show: {os.path.basename(item.file_path)}",
                        icon='FILEBROWSER')
                    op.file_path = item.file_path


# ============================================================================
# Registration
# ============================================================================

classes = (
    CheckIssue,
    ProjectCheckerSettings,
    PROJ_OT_run_integrity_check,
    PROJ_OT_clear_check_results,
    PROJ_OT_open_issue_file,
    PROJ_UL_check_issues,
    VIEW3D_PT_project_checker,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.project_checker = PointerProperty(type=ProjectCheckerSettings)
    print("[Project Checker] Registered")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, 'project_checker'):
        del bpy.types.Scene.project_checker
    print("[Project Checker] Unregistered")
