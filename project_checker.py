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
    fix_id:    StringProperty(name="Fix ID",    default="")


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

    def add(severity, category, message, detail="", file_path="", fix_id=""):
        issues.append({
            'severity': severity,
            'category': category,
            'message':  message,
            'detail':   detail,
            'file_path': file_path,
            'fix_id':   fix_id,
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
        default_count = 0
        for mesh in mapgeo_data.meshes:
            for prim in mesh.primitives:
                name = prim.material
                if not name:
                    continue
                if name == 'Default':
                    default_count += 1
                    continue
                # Look up by FNV-1a hash (robust, doesn't rely on name field)
                ph = f"0x{_fnv1a_32(name):08x}"
                if ph not in all_path_hashes:
                    missing_mats.add(name)

        if missing_mats:
            for name in sorted(missing_mats):
                add('ERROR', 'Materials',
                    'Mapgeo material not found in materials.bin',
                    detail=name, file_path=loaded_mapgeo,
                    fix_id='MISSING_MATERIAL')
        else:
            total = sum(len(m.primitives) for m in mapgeo_data.meshes)
            add('INFO', 'Materials',
                f'All {total - default_count} mesh primitive materials resolve OK.')
        if default_count:
            add('WARNING', 'Materials',
                f'{default_count} mesh primitive(s) use "Default" material '
                f'(VFX placeholder — not expected in mapgeo)',
                file_path=loaded_mapgeo,
                fix_id='MISSING_MATERIAL')

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
                add('INFO', 'BucketGrid',
                    f'Custom bucket grid detected ({len(active_grids)} active grid(s)).',
                    detail='This is a custom bucket grid. It will be exported as-is.',
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

        # Build set of render_region_hash values used by meshes so we can
        # distinguish genuine VC lookups from render-region identifiers on
        # bucket grids.
        render_region_hashes = set()
        for mesh in mapgeo_data.meshes:
            rr = mesh.unknown_version18_int
            if rr and rr != 0:
                render_region_hashes.add(f"0x{rr:08x}")

        for i, mesh in enumerate(mapgeo_data.meshes):
            h = mesh.visibility_controller_path_hash
            if h and h != 0:
                ph_str = f"0x{h:08x}"
                if ph_str not in all_path_hashes:
                    bad_vis.append(f'Mesh #{i}: {ph_str}')
                else:
                    ok_vis += 1

        bad_bg_vis  = []
        ok_bg_vis   = 0
        rr_bg_count = 0
        for bg in mapgeo_data.bucket_grids:
            h = bg.path_hash
            if h and h != 0:
                ph_str = f"0x{h:08x}"
                if ph_str in all_path_hashes:
                    ok_bg_vis += 1
                elif ph_str in render_region_hashes:
                    # This is a render-region identifier, not a VC lookup
                    rr_bg_count += 1
                else:
                    bad_bg_vis.append(f'BucketGrid: {ph_str}')

        for item in bad_vis:
            add('ERROR', 'Visibility',
                'Visibility controller path_hash not in materials.bin',
                detail=item, file_path=loaded_mapgeo,
                fix_id='MISSING_VISIBILITY')
        for item in bad_bg_vis:
            add('ERROR', 'Visibility',
                'BucketGrid path_hash not in materials.bin',
                detail=item, file_path=loaded_mapgeo,
                fix_id='MISSING_VISIBILITY')
        ok_total = ok_vis + ok_bg_vis
        if ok_total:
            add('INFO', 'Visibility', f'{ok_total} visibility controller(s) resolved OK.')
        if rr_bg_count:
            add('INFO', 'Visibility',
                f'{rr_bg_count} bucket grid(s) use render-region hashes (no VC entry needed).')

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

    # ── CHECK 7: VFX / MapParticle cross-links (bin level) ──────────────
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

    # ── CHECK 7b: MapParticle → VFX_Definition (scene level) ─────────────
    # Verify each MapParticle in the scene references a VFX_Definition that
    # actually exists both in the Blender scene and in the materials.bin.
    vfx_defs_by_name = {}   # vfx_name → obj
    particle_systems = []   # (obj, system_name)

    for obj in bpy.context.scene.objects:
        if obj.get('is_vfx_definition'):
            vname = obj.get('vfx_name', '')
            if vname:
                vfx_defs_by_name[vname] = obj
        if obj.get('is_particle_system'):
            sys_name = obj.get('particle_system', '')
            if sys_name:
                particle_systems.append((obj, sys_name))

    if particle_systems:
        # Also build a set of VFX entry path_hashes in the bin
        vfx_bin_hashes = set()
        if bin_data:
            for entry in bin_data.get('entries', []):
                th = entry.get('type_hash', '')
                th_int = int(th, 16) if (th and th.startswith('0x')) else 0
                if th_int == _HASH_VFX_SYSTEM:
                    vfx_bin_hashes.add(entry.get('path_hash', ''))

        missing_scene = []
        missing_bin   = []
        ok_particle   = 0

        for obj, sys_name in particle_systems:
            # Check Blender scene
            has_scene_def = sys_name in vfx_defs_by_name
            # Check materials.bin by hashing the system name
            sys_hash = f"0x{_fnv1a_32(sys_name):08x}"
            has_bin_def = sys_hash in vfx_bin_hashes or sys_hash in all_path_hashes

            if has_scene_def and has_bin_def:
                ok_particle += 1
            elif not has_scene_def and not has_bin_def:
                missing_scene.append(f'{obj.name} → {sys_name} (missing in scene + bin)')
            elif not has_scene_def:
                missing_scene.append(f'{obj.name} → {sys_name} (missing in scene)')
            elif not has_bin_def:
                missing_bin.append(f'{obj.name} → {sys_name} (missing in bin)')

        for item in missing_scene:
            add('WARNING', 'VFX',
                'MapParticle references missing VFX definition',
                detail=item)
        for item in missing_bin:
            add('WARNING', 'VFX',
                'MapParticle VFX system not found in materials.bin',
                detail=item, file_path=loaded_materials)
        if ok_particle:
            add('INFO', 'VFX',
                f'{ok_particle} MapParticle(s) have matching VFX definitions.')
    elif vfx_defs_by_name:
        add('INFO', 'VFX',
            f'{len(vfx_defs_by_name)} VFX definition(s) loaded (no MapParticles to check).')

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
                        if e.get('type_hash', '') == f"0x{_HASH_VIS_CTRL:08x}"
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
            item.fix_id       = issue.get('fix_id', '')
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


class PROJ_OT_select_issue_meshes(Operator):
    """Select mesh objects affected by the selected issue"""
    bl_idname  = "project.select_issue_meshes"
    bl_label   = "Select Affected Meshes"
    bl_description = "Select all mesh objects affected by this issue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        checker = context.scene.project_checker
        idx = checker.active_index
        if idx < 0 or idx >= len(checker.issues):
            self.report({'ERROR'}, "No issue selected")
            return {'CANCELLED'}

        item = checker.issues[idx]
        fix_id = item.fix_id

        if fix_id == 'MISSING_MATERIAL':
            return self._select_by_material(context, item.detail)
        elif fix_id == 'MISSING_VISIBILITY':
            return self._select_by_visibility(context, item.detail)

        self.report({'WARNING'}, "No mesh selection available for this issue type")
        return {'CANCELLED'}

    def _select_by_material(self, context, mat_name):
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            for mat_slot in obj.material_slots:
                mat = mat_slot.material
                if mat and mat.get('league_material_name') == mat_name:
                    obj.select_set(True)
                    count += 1
                    break

        self.report({'INFO'}, f"Selected {count} mesh(es) using '{mat_name}'")
        return {'FINISHED'}

    def _select_by_visibility(self, context, detail):
        """Select meshes whose visibility_controller_path_hash matches the issue detail."""
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        # detail format: "Mesh #<idx>: 0x<hash>" or "BucketGrid: 0x<hash>"
        hash_str = detail.split(':')[-1].strip() if ':' in detail else ''
        try:
            target_hash = int(hash_str, 16)
        except (ValueError, TypeError):
            self.report({'ERROR'}, f"Could not parse hash from: {detail}")
            return {'CANCELLED'}

        # baron_hash is stored as uppercase hex WITHOUT 0x prefix (e.g. "1A2B3C4D")
        target_baron = f"{target_hash:08X}"

        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            baron = obj.get('baron_hash', '')
            if baron and baron.upper() == target_baron:
                obj.select_set(True)
                count += 1

        self.report({'INFO'}, f"Selected {count} mesh(es) with visibility hash {hash_str}")
        return {'FINISHED'}


class PROJ_OT_fix_issue(Operator):
    """Automatically fix the selected issue"""
    bl_idname  = "project.fix_issue"
    bl_label   = "Fix Issue"
    bl_description = "Automatically fix this issue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        checker = context.scene.project_checker
        idx = checker.active_index
        if idx < 0 or idx >= len(checker.issues):
            self.report({'ERROR'}, "No issue selected")
            return {'CANCELLED'}

        item = checker.issues[idx]
        if item.fix_id == 'MISSING_MATERIAL':
            return self._fix_missing_material(context, item.detail)

        self.report({'WARNING'}, "No auto-fix available for this issue type")
        return {'CANCELLED'}

    def _fix_missing_material(self, context, mat_name):
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        fixed_count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            slots_to_remove = []
            for slot_idx, mat_slot in enumerate(obj.material_slots):
                mat = mat_slot.material
                if mat and mat.get('league_material_name') == mat_name:
                    slots_to_remove.append(slot_idx)

            if not slots_to_remove:
                continue

            context.view_layer.objects.active = obj
            for slot_idx in reversed(slots_to_remove):
                obj.active_material_index = slot_idx
                bpy.ops.object.material_slot_remove()
            fixed_count += 1

        if fixed_count:
            self.report({'INFO'}, f"Removed '{mat_name}' material from {fixed_count} mesh(es)")
        else:
            self.report({'INFO'}, f"No meshes found with '{mat_name}' material")
        return {'FINISHED'}


class PROJ_OT_fix_visibility(Operator):
    """Import missing visibility controller entries from another materials.bin"""
    bl_idname  = "project.fix_visibility"
    bl_label   = "Import Visibility Controller"
    bl_description = (
        "Browse for a materials.bin that contains the missing baron hash "
        "visibility controller, and add it to your project's materials.bin"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import copy
        from . import propertybin_parser

        checker  = context.scene.project_checker
        settings = context.scene.project_settings

        # Gather all missing visibility path hashes from current issues
        missing_hashes = set()
        for issue in checker.issues:
            if issue.fix_id != 'MISSING_VISIBILITY':
                continue
            detail = issue.detail
            hash_str = detail.split(':')[-1].strip() if ':' in detail else ''
            if hash_str:
                missing_hashes.add(hash_str.lower())

        if not missing_hashes:
            self.report({'INFO'}, "No missing visibility controllers to import")
            return {'CANCELLED'}

        # Parse the source bin the user selected
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "Selected file does not exist")
            return {'CANCELLED'}

        try:
            source_data = propertybin_parser.parse_bin(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse source bin: {e}")
            return {'CANCELLED'}

        # Find matching entries in the source
        entries_to_inject = []
        for entry in source_data.get('entries', []):
            ph = entry.get('path_hash', '').lower()
            if ph in missing_hashes:
                entries_to_inject.append(copy.deepcopy(entry))

        if not entries_to_inject:
            self.report({'WARNING'},
                        f"Source bin does not contain any of the {len(missing_hashes)} "
                        f"missing visibility controller(s)")
            return {'CANCELLED'}

        # Load the project's materials.bin
        project_bin_path = bpy.path.abspath(settings.loaded_materials_path) \
            if settings.loaded_materials_path else ''
        if not project_bin_path or not os.path.isfile(project_bin_path):
            self.report({'ERROR'}, "No project materials.bin loaded")
            return {'CANCELLED'}

        try:
            target_data = propertybin_parser.parse_bin(project_bin_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse project bin: {e}")
            return {'CANCELLED'}

        # Check for duplicates and inject
        existing = {e.get('path_hash', '').lower()
                    for e in target_data.get('entries', [])}
        injected = 0
        for entry in entries_to_inject:
            ph = entry.get('path_hash', '').lower()
            if ph not in existing:
                target_data['entries'].append(entry)
                existing.add(ph)
                injected += 1

        if injected == 0:
            self.report({'INFO'}, "All entries already exist in project bin")
            return {'FINISHED'}

        # Write back
        try:
            propertybin_parser.write_bin(target_data, project_bin_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write project bin: {e}")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Imported {injected} visibility controller(s) into "
                    f"{os.path.basename(project_bin_path)}")
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

                if item.fix_id:
                    detail_box.separator()
                    row = detail_box.row(align=True)
                    row.operator("project.select_issue_meshes",
                                 text="Select Affected Meshes",
                                 icon='RESTRICT_SELECT_OFF')
                    if item.fix_id == 'MISSING_MATERIAL':
                        row.operator("project.fix_issue",
                                     text="Fix", icon='CHECKMARK')
                    elif item.fix_id == 'MISSING_VISIBILITY':
                        row.operator("project.fix_visibility",
                                     text="Fix (Load .bin)", icon='FILEBROWSER')


# ============================================================================
# Registration
# ============================================================================

classes = (
    CheckIssue,
    ProjectCheckerSettings,
    PROJ_OT_run_integrity_check,
    PROJ_OT_clear_check_results,
    PROJ_OT_open_issue_file,
    PROJ_OT_select_issue_meshes,
    PROJ_OT_fix_issue,
    PROJ_OT_fix_visibility,
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
