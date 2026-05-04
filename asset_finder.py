"""
Asset Finder & Patch Locator for MapgeoAddon

Scans a project's `.materials.bin` files, extracts every `ASSETS/` path
referenced (textures, meshes, soundbanks, prop files, etc.), then verifies
each path exists either inside the project folder or inside the extracted
Riot WAD cache. Anything missing is reported.

For each missing path, an optional second pass walks CommunityDragon patch
versions from `latest` down to `16.1` (configurable) using HTTP HEAD
requests to find the most recent patch where the asset was still shipped.
The user can then download that patch's WAD via the Map Patcher tool.

Result list groups missing assets by the patch number where they were
last seen, so the user knows which legacy WAD(s) to retrieve.

Settings reused from `project_settings`:
  - project_folder
  - league_install
  - project_map_id
"""

from __future__ import annotations

import bpy
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request, error

from bpy.props import (
    StringProperty, EnumProperty, IntProperty, BoolProperty,
    CollectionProperty, PointerProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList

from . import propertybin_parser


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENT = {"User-Agent": "BlenderMapgeoAddon/1.0 AssetFinder"}
_CDRAGON_BASE = "https://raw.communitydragon.org"
_ASSETS_RE = re.compile(r"ASSETS/[^\s\"'<>|]+", re.IGNORECASE)
_DEFAULT_OLDEST = "16.1"

# Field-type IDs that may carry strings or contain children.
_TYPE_STRING    = 16
_TYPE_FILE      = 18
_TYPE_CONTAINER_IDS = (0x80, 0x81, 128, 129)
_TYPE_STRUCT_IDS    = (0x82, 0x83, 0x85, 130, 131, 133)


# ---------------------------------------------------------------------------
# Module-level scan state (so a long find-patches run can post results back
# from worker threads without crashing Blender's main thread).
# ---------------------------------------------------------------------------

_scan_lock = threading.Lock()
_scan_state = {
    "running": False,
    "cancel": False,
    "done": 0,
    "total": 0,
    "results": {},   # missing_path -> patch_str or "" if not found
    "message": "",
}


# ---------------------------------------------------------------------------
# Property groups
# ---------------------------------------------------------------------------

class MissingAssetItem(PropertyGroup):
    asset_path: StringProperty(name="Asset Path", default="")
    referenced_by: StringProperty(name="Referenced By", default="")
    found_in_patch: StringProperty(
        name="Found In Patch",
        default="",
        description="Most recent CommunityDragon patch where this asset was still shipped (empty = not yet probed or not found)",
    )
    match_kind: EnumProperty(
        name="Match Kind",
        items=[
            ('NONE',   'None',   ''),
            ('EXACT',  'Exact',  'CDragon listed this file by name in the patch'),
            ('DIR',    'Dir',    'CDragon directory exists at this patch but extension is not served (.scb/.skl/etc.) — WAD probably still contains it'),
            ('BINREF', 'BinRef', "That patch's materials.bin still references this asset path — WAD almost certainly contains it"),
        ],
        default='NONE',
    )
    probe_status: EnumProperty(
        name="Probe Status",
        items=[
            ('UNKNOWN',   'Unknown',   '', 'QUESTION', 0),
            ('FOUND',     'Found',     '', 'CHECKMARK', 1),
            ('NOT_FOUND', 'Not Found', '', 'X', 2),
            ('PROBING',   'Probing',   '', 'TIME', 3),
        ],
        default='UNKNOWN',
    )


class AssetFinderSettings(PropertyGroup):
    missing_assets: CollectionProperty(type=MissingAssetItem)
    active_index: IntProperty(default=0)

    last_scan_summary: StringProperty(default="")
    lowest_patch: StringProperty(default="", description="Lowest patch number among all resolved missing assets")
    is_probing: BoolProperty(default=False)
    probe_progress: StringProperty(default="")

    oldest_patch: StringProperty(
        name="Oldest Patch",
        description="Stop scanning patches at this version (e.g. 16.1)",
        default=_DEFAULT_OLDEST,
    )
    probe_workers: IntProperty(
        name="Probe Workers",
        description="Number of parallel HTTP requests for patch detection",
        default=8, min=1, max=32,
    )
    filter_text: StringProperty(
        name="Filter",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )


# ---------------------------------------------------------------------------
# Bin walking + asset string collection
# ---------------------------------------------------------------------------

def _walk_strings(node, out_set: set):
    """Recursively walk any parsed-bin sub-tree and collect every string
    value that looks like an asset path (case-insensitive 'ASSETS/' prefix).
    Walks all dict values + list/tuple items, so it works regardless of the
    container key name (entries, fields, values, value, pairs, …)."""
    if isinstance(node, str):
        for m in _ASSETS_RE.findall(node):
            out_set.add(m.replace("\\", "/"))
        return
    if isinstance(node, dict):
        for v in node.values():
            _walk_strings(v, out_set)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk_strings(item, out_set)


def _scan_bin_for_assets(bin_path: str) -> set:
    """Parse a single .materials.bin and return its set of ASSETS/ paths."""
    found = set()
    try:
        data = propertybin_parser.parse_bin(bin_path)
    except Exception as e:
        print(f"[Asset Finder] Failed to parse {bin_path}: {e}")
        return found
    _walk_strings(data, found)
    return found


def _find_materials_bins(project_folder: str) -> list:
    """Return a list of .materials.bin paths recursively under project_folder."""
    out = []
    for root, _dirs, files in os.walk(project_folder):
        for fn in files:
            if fn.lower().endswith(".materials.bin"):
                out.append(os.path.join(root, fn))
    return out


def _asset_exists(rel_path: str, roots: list) -> bool:
    """Case-insensitive existence check. Tries exact case first, then a
    lowercase walk only if needed (Riot's WAD extraction can be case-mixed)."""
    norm = rel_path.replace("\\", "/")
    for root in roots:
        cand = os.path.join(root, norm)
        if os.path.isfile(cand):
            return True
    # Case-insensitive fallback (slower) — only check when exact-case missed
    norm_lower = norm.lower()
    for root in roots:
        cand_lower = os.path.join(root, norm_lower)
        if os.path.isfile(cand_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# CommunityDragon patch probing
# ---------------------------------------------------------------------------

def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except ValueError:
        return (0,)


def _list_patch_versions(oldest: str) -> list:
    """Return ['latest', '16.x', '16.x-1', ..., oldest] in newest-first order."""
    try:
        from . import map_patcher
        all_versions = map_patcher._fetch_cdragon_versions()
    except Exception as e:
        print(f"[Asset Finder] Could not fetch CDragon versions: {e}")
        return ["latest"]
    oldest_t = _version_tuple(oldest)
    numeric = [v for v in all_versions if _version_tuple(v) >= oldest_t]
    numeric.sort(key=_version_tuple, reverse=True)
    # 'latest' first, then numeric versions newest → oldest
    return ["latest"] + numeric


def _cdragon_dir_listing_url(channel: str, dir_path: str) -> str:
    """CommunityDragon JSON directory listing endpoint."""
    p = dir_path.replace("\\", "/").strip("/").lower()
    return f"{_CDRAGON_BASE}/json/{channel}/game/{p}/"


# Per-process cache for directory listings, keyed by (channel, dir_lower).
# Stores set[str] of lowercase basenames (without extension). None = listing
# does not exist (404). Empty set = listing exists but has no files.
_dir_listing_cache: dict = {}
_dir_listing_lock = threading.Lock()


def _fetch_dir_listing(channel: str, dir_path: str, timeout: float = 10.0):
    """Return a set of lowercase basenames-without-extension for the given
    directory at the given channel, or None if the directory does not exist
    on CommunityDragon. Cached for the lifetime of the process."""
    key = (channel, dir_path.replace("\\", "/").strip("/").lower())
    with _dir_listing_lock:
        if key in _dir_listing_cache:
            return _dir_listing_cache[key]

    url = _cdragon_dir_listing_url(channel, dir_path)
    try:
        req = request.Request(url, headers=_USER_AGENT)
        with request.urlopen(req, timeout=timeout) as resp:
            import json as _json
            data = _json.loads(resp.read().decode("utf-8", errors="replace"))
        bases = set()
        for entry in data:
            if entry.get("type") != "file":
                continue
            name = entry.get("name", "")
            base, _ext = os.path.splitext(name)
            bases.add(base.lower())
        result = bases
    except error.HTTPError as e:
        result = None if e.code == 404 else set()
    except (error.URLError, TimeoutError, OSError, ValueError):
        result = set()  # treat transient errors as "unknown" (won't match)

    with _dir_listing_lock:
        _dir_listing_cache[key] = result
    return result


def _probe_asset_in_patch(channel: str, asset_path: str, timeout: float = 10.0) -> bool:
    """Returns True iff CommunityDragon serves any file with the same base
    name (extension-agnostic) as `asset_path` under the given patch channel.

    Uses a JSON directory listing rather than per-extension HEAD probes
    because CDragon converts .tex/.dds→.png on the fly and omits some
    extensions entirely (.scb, .skl). One request per directory, cached."""
    norm = asset_path.replace("\\", "/")
    dir_part, file_part = os.path.split(norm)
    base, _ext = os.path.splitext(file_part)
    bases = _fetch_dir_listing(channel, dir_part, timeout=timeout)
    if bases is None:
        return False
    return base.lower() in bases


# Extensions that CommunityDragon does NOT serve directly (it only hosts a
# converted form, or strips them entirely). For these we cannot get a clean
# yes/no per file — but if the directory listing exists at the patch, the
# WAD for that patch most likely still contains the original.
_NON_PROBABLE_EXTS = {".scb", ".skl", ".anm", ".aimesh_ngrid",
                      ".ngrid_overlay", ".rg_overlay", ".dds"}


def _probe_asset_with_dir_fallback(channel: str, asset_path: str,
                                   timeout: float = 10.0) -> str:
    """Like _probe_asset_in_patch but returns one of:
      'EXACT' — base name found in directory listing
      'DIR'   — directory exists at this patch but base name not listed
                (likely because CDragon strips this file type — the WAD
                from this patch should still contain it)
      ''      — directory does not exist at this patch
    """
    norm = asset_path.replace("\\", "/")
    dir_part, file_part = os.path.split(norm)
    base, ext = os.path.splitext(file_part)
    bases = _fetch_dir_listing(channel, dir_part, timeout=timeout)
    if bases is None:
        return ""
    if base.lower() in bases:
        return "EXACT"
    if ext.lower() in _NON_PROBABLE_EXTS and bases:
        return "DIR"
    return ""


def _find_patch_for_asset(asset_path: str, channels: list) -> tuple:
    """Walk channels newest-first; return (patch, kind) where kind is
    'EXACT' (CDragon listed the file by name) or 'DIR' (only the directory
    was confirmed to exist at this patch — the WAD likely still contains
    the file but CDragon strips that extension). Returns ('', '') if not
    found in any channel."""
    for ch in channels:
        if _scan_state.get("cancel"):
            return ("", "")
        kind = _probe_asset_with_dir_fallback(ch, asset_path)
        if kind:
            return (ch, kind)
    return ("", "")


# ---------------------------------------------------------------------------
# Deep probe: download per-patch map materials.bin and check whether the
# missing asset path is referenced in it. This is the strongest signal we
# can get for extensions CDragon does not serve directly (.scb/.skl/…).
# ---------------------------------------------------------------------------

# Cache: (channel, map_name, variant) -> set[str] (lowercased ASSETS/ paths)
# or None if the bin could not be downloaded for that patch.
_remote_bin_assets_cache: dict = {}
_remote_bin_lock = threading.Lock()


def _fetch_remote_bin_assets(channel: str, map_name: str, variant: str):
    """Download a map variant's materials.bin from CDragon for the given
    patch channel, parse it, and return the lowercased set of ASSETS/
    paths it references. Returns None on download/parse failure (treated
    as 'unknown' so the search continues to older patches)."""
    key = (channel, map_name.lower(), variant.lower())
    with _remote_bin_lock:
        if key in _remote_bin_assets_cache:
            return _remote_bin_assets_cache[key]
    try:
        from . import map_patcher
        path = map_patcher._download_bin(channel, map_name, variant)
        data = propertybin_parser.parse_bin(path)
        s: set = set()
        _walk_strings(data, s)
        result = {p.lower() for p in s}
    except error.HTTPError as e:
        result = None if e.code == 404 else None
    except Exception as e:
        print(f"[Asset Finder] Deep-probe fetch failed {channel}/{map_name}/{variant}: {e}")
        result = None
    with _remote_bin_lock:
        _remote_bin_assets_cache[key] = result
    return result


def _deep_find_patch_for_asset(asset_path: str, channels: list,
                               map_name: str, variants: list) -> tuple:
    """Walk channels newest-first; for each, fetch every variant's
    materials.bin and check whether `asset_path` appears. Returns
    (patch, 'BINREF') on hit, else ('', '')."""
    needle = asset_path.lower()
    for ch in channels:
        if _scan_state.get("cancel"):
            return ("", "")
        for v in variants:
            if _scan_state.get("cancel"):
                return ("", "")
            assets = _fetch_remote_bin_assets(ch, map_name, v)
            if assets and needle in assets:
                return (ch, "BINREF")
    return ("", "")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class ASSETFINDER_OT_scan_project(Operator):
    """Scan the project's materials.bin files and list any ASSETS/ paths
    that are missing from both the project folder and the Riot WAD cache."""
    bl_idname = "assetfinder.scan_project"
    bl_label = "Scan Project for Missing Assets"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scn = context.scene
        ps = getattr(scn, "project_settings", None)
        finder = scn.asset_finder
        if ps is None:
            self.report({'ERROR'}, "Project settings unavailable")
            return {'CANCELLED'}

        project_folder = bpy.path.abspath(ps.project_folder) if ps.project_folder else ""
        league_install = bpy.path.abspath(ps.league_install) if ps.league_install else ""
        map_id = ps.project_map_id or ""

        if not project_folder or not os.path.isdir(project_folder):
            self.report({'ERROR'}, "Set the Project Folder in Project Manager first")
            return {'CANCELLED'}

        # Build search roots
        roots = [project_folder]
        if map_id and league_install and os.path.isdir(league_install):
            try:
                from . import project_manager
                wad_cache = project_manager._ensure_riot_wad_cache(league_install, map_id)
                if wad_cache:
                    roots.append(wad_cache)
                lvl_cache = project_manager._ensure_riot_levels_wad_cache(league_install, map_id)
                if lvl_cache:
                    roots.append(lvl_cache)
            except Exception as e:
                print(f"[Asset Finder] WAD cache lookup failed: {e}")

        bins = _find_materials_bins(project_folder)
        if not bins:
            self.report({'WARNING'}, f"No .materials.bin files found under {project_folder}")
            finder.missing_assets.clear()
            finder.last_scan_summary = "No .materials.bin files in project."
            return {'CANCELLED'}

        # Build inverted index: asset_path -> first bin that referenced it
        all_assets: dict[str, str] = {}
        for bin_path in bins:
            paths = _scan_bin_for_assets(bin_path)
            for p in paths:
                all_assets.setdefault(p, os.path.relpath(bin_path, project_folder))

        # Filter to those missing from disk
        missing = []
        for path, ref in sorted(all_assets.items(), key=lambda kv: kv[0].lower()):
            if not _asset_exists(path, roots):
                missing.append((path, ref))

        # Populate UI list
        finder.missing_assets.clear()
        for path, ref in missing:
            it = finder.missing_assets.add()
            it.asset_path = path
            it.referenced_by = ref
            it.found_in_patch = ""
            it.probe_status = 'UNKNOWN'

        finder.active_index = 0
        finder.last_scan_summary = (
            f"Scanned {len(bins)} bin(s) → {len(all_assets)} unique ASSETS/ paths, "
            f"{len(missing)} missing"
        )
        self.report({'INFO'}, finder.last_scan_summary)
        return {'FINISHED'}


class ASSETFINDER_OT_find_patches(Operator):
    """For every missing asset, probe CommunityDragon patches (newest-first
    down to 'Oldest Patch') to find the most recent patch that still ships
    the file. Runs in background threads."""
    bl_idname = "assetfinder.find_patches"
    bl_label = "Find Patches for Missing Assets"
    bl_options = {'REGISTER'}

    _timer = None
    _thread = None

    def execute(self, context):
        finder = context.scene.asset_finder
        if not finder.missing_assets:
            self.report({'WARNING'}, "Nothing missing — run the scan first")
            return {'CANCELLED'}

        with _scan_lock:
            if _scan_state["running"]:
                self.report({'WARNING'}, "A patch probe is already running")
                return {'CANCELLED'}
            _scan_state.update({
                "running": True,
                "cancel": False,
                "done": 0,
                "total": len(finder.missing_assets),
                "results": {},
                "message": "Fetching patch list…",
            })

        oldest = finder.oldest_patch.strip() or _DEFAULT_OLDEST
        workers = max(1, finder.probe_workers)
        targets = [it.asset_path for it in finder.missing_assets]

        def _bg():
            try:
                channels = _list_patch_versions(oldest)
                with _scan_lock:
                    _scan_state["message"] = (
                        f"Probing {len(targets)} asset(s) across {len(channels)} channel(s)…"
                    )
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    fut_map = {
                        pool.submit(_find_patch_for_asset, p, channels): p
                        for p in targets
                    }
                    for fut in as_completed(fut_map):
                        if _scan_state.get("cancel"):
                            break
                        path = fut_map[fut]
                        try:
                            patch, kind = fut.result()
                        except Exception:
                            patch, kind = "", ""
                        with _scan_lock:
                            _scan_state["results"][path] = (patch, kind)
                            _scan_state["done"] += 1
            finally:
                with _scan_lock:
                    _scan_state["running"] = False
                    _scan_state["message"] = "Done."

        self._thread = threading.Thread(target=_bg, daemon=True)
        self._thread.start()

        finder.is_probing = True
        finder.probe_progress = "Starting…"

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        finder = context.scene.asset_finder
        if event.type == 'TIMER':
            with _scan_lock:
                done = _scan_state["done"]
                total = _scan_state["total"]
                running = _scan_state["running"]
                msg = _scan_state["message"]
                # Drain results into the property collection
                results = dict(_scan_state["results"])

            # Apply results that haven't been written yet
            for it in finder.missing_assets:
                if it.asset_path in results and it.probe_status in ('UNKNOWN', 'PROBING'):
                    patch, kind = results[it.asset_path]
                    it.found_in_patch = patch
                    it.match_kind = kind or 'NONE'
                    it.probe_status = 'FOUND' if patch else 'NOT_FOUND'

            finder.probe_progress = f"{msg}  {done}/{total}"

            if not running and done >= total:
                self._cleanup(context)
                self.report({'INFO'}, f"Patch probe complete ({done}/{total})")
                return {'FINISHED'}

        elif event.type == 'ESC':
            with _scan_lock:
                _scan_state["cancel"] = True
            self._cleanup(context)
            self.report({'WARNING'}, "Patch probe cancelled")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def _cleanup(self, context):
        finder = context.scene.asset_finder
        finder.is_probing = False
        _recompute_lowest_patch(finder)
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None


def _recompute_lowest_patch(finder) -> None:
    """Find the oldest (lowest) patch among all resolved missing assets and
    store it on the finder for the UI to display."""
    lowest_t = None
    lowest_str = ""
    for it in finder.missing_assets:
        if not it.found_in_patch or it.found_in_patch == "latest":
            continue
        t = _version_tuple(it.found_in_patch)
        if lowest_t is None or t < lowest_t:
            lowest_t = t
            lowest_str = it.found_in_patch
    finder.lowest_patch = lowest_str


def _infer_map_and_variants(project_folder: str, map_id: str) -> tuple:
    """Return (map_name, [variants]) inferred from the project's bins.
    Falls back to ('map<id>', ['base']) if nothing is detected."""
    map_name = f"map{map_id}".lower() if map_id else ""
    variants: list = []
    if not project_folder:
        return (map_name or "map11", ["base"])
    geom_dir = os.path.join(project_folder, "data", "maps", "mapgeometry")
    if os.path.isdir(geom_dir):
        # If user only set a map_id like "11", we may still discover real
        # folder name (e.g. mapXX) here.
        if not map_name:
            for d in sorted(os.listdir(geom_dir)):
                if os.path.isdir(os.path.join(geom_dir, d)) and d.startswith("map"):
                    map_name = d.lower()
                    break
        candidate = os.path.join(geom_dir, map_name) if map_name else ""
        if candidate and os.path.isdir(candidate):
            for fn in sorted(os.listdir(candidate)):
                low = fn.lower()
                if low.endswith(".materials.bin"):
                    variants.append(low[:-len(".materials.bin")])
    if not variants:
        variants = ["base"]
    return (map_name or "map11", variants)


class ASSETFINDER_OT_deep_probe(Operator):
    """For every still-unresolved or DIR-only asset, download each patch's
    map materials.bin and check whether the asset path is referenced. This
    is slow but resolves .scb / .skl / .anm files that CDragon doesn't list
    directly — if the patch's materials.bin still references the path, that
    patch's WAD almost certainly contains the file."""
    bl_idname = "assetfinder.deep_probe"
    bl_label = "Deep Probe (Materials.bin)"
    bl_description = (
        "Slow second pass: downloads each patch's map materials.bin and "
        "searches it for unresolved asset paths. Resolves .scb/.skl files."
    )
    bl_options = {'REGISTER'}

    _timer = None
    _thread = None

    def execute(self, context):
        scn = context.scene
        finder = scn.asset_finder
        ps = getattr(scn, "project_settings", None)
        if ps is None:
            self.report({'ERROR'}, "Project settings unavailable")
            return {'CANCELLED'}

        # Pick assets to deep-probe: anything not yet exact-matched.
        targets = [it.asset_path for it in finder.missing_assets
                   if it.match_kind != 'EXACT' and it.match_kind != 'BINREF']
        if not targets:
            self.report({'INFO'}, "No DIR-only or unresolved items to deep-probe")
            return {'CANCELLED'}

        with _scan_lock:
            if _scan_state["running"]:
                self.report({'WARNING'}, "A patch probe is already running")
                return {'CANCELLED'}
            _scan_state.update({
                "running": True,
                "cancel": False,
                "done": 0,
                "total": len(targets),
                "results": {},
                "message": "Fetching patch list…",
            })

        oldest = finder.oldest_patch.strip() or _DEFAULT_OLDEST
        # Deep probe is heavy per-patch (one bin download per patch), so
        # don't fan out too many simultaneous downloads.
        workers = max(1, min(4, finder.probe_workers))
        project_folder = bpy.path.abspath(ps.project_folder) if ps.project_folder else ""
        map_name, variants = _infer_map_and_variants(project_folder, ps.project_map_id or "")

        def _bg():
            try:
                channels = _list_patch_versions(oldest)
                with _scan_lock:
                    _scan_state["message"] = (
                        f"Deep-probing {len(targets)} asset(s) across "
                        f"{len(channels)} channel(s) × {len(variants)} variant(s)…"
                    )
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    fut_map = {
                        pool.submit(_deep_find_patch_for_asset, p, channels,
                                    map_name, variants): p
                        for p in targets
                    }
                    for fut in as_completed(fut_map):
                        if _scan_state.get("cancel"):
                            break
                        path = fut_map[fut]
                        try:
                            patch, kind = fut.result()
                        except Exception:
                            patch, kind = "", ""
                        with _scan_lock:
                            _scan_state["results"][path] = (patch, kind)
                            _scan_state["done"] += 1
            finally:
                with _scan_lock:
                    _scan_state["running"] = False
                    _scan_state["message"] = "Deep probe done."

        self._thread = threading.Thread(target=_bg, daemon=True)
        self._thread.start()

        finder.is_probing = True
        finder.probe_progress = "Starting deep probe…"

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        finder = context.scene.asset_finder
        if event.type == 'TIMER':
            with _scan_lock:
                done = _scan_state["done"]
                total = _scan_state["total"]
                running = _scan_state["running"]
                msg = _scan_state["message"]
                results = dict(_scan_state["results"])

            # Apply only stronger results: BINREF upgrades DIR/NONE; do not
            # downgrade existing matches.
            for it in finder.missing_assets:
                if it.asset_path not in results:
                    continue
                patch, kind = results[it.asset_path]
                if not kind:
                    if it.match_kind == 'NONE':
                        it.probe_status = 'NOT_FOUND'
                    continue
                # BINREF is the strongest signal
                if kind == 'BINREF' and it.match_kind != 'EXACT':
                    it.found_in_patch = patch
                    it.match_kind = 'BINREF'
                    it.probe_status = 'FOUND'

            finder.probe_progress = f"{msg}  {done}/{total}"

            if not running and done >= total:
                self._cleanup(context)
                self.report({'INFO'}, f"Deep probe complete ({done}/{total})")
                return {'FINISHED'}

        elif event.type == 'ESC':
            with _scan_lock:
                _scan_state["cancel"] = True
            self._cleanup(context)
            self.report({'WARNING'}, "Deep probe cancelled")
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def _cleanup(self, context):
        finder = context.scene.asset_finder
        finder.is_probing = False
        _recompute_lowest_patch(finder)
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None


class ASSETFINDER_OT_cancel_probe(Operator):
    bl_idname = "assetfinder.cancel_probe"
    bl_label = "Cancel Patch Probe"
    bl_options = {'REGISTER'}

    def execute(self, context):
        with _scan_lock:
            _scan_state["cancel"] = True
        self.report({'INFO'}, "Cancellation requested")
        return {'FINISHED'}


class ASSETFINDER_OT_clear(Operator):
    bl_idname = "assetfinder.clear"
    bl_label = "Clear Results"
    bl_options = {'REGISTER'}

    def execute(self, context):
        finder = context.scene.asset_finder
        finder.missing_assets.clear()
        finder.last_scan_summary = ""
        finder.probe_progress = ""
        return {'FINISHED'}


class ASSETFINDER_OT_copy_to_clipboard(Operator):
    """Copy the missing-asset report (grouped by patch) to the clipboard."""
    bl_idname = "assetfinder.copy_report"
    bl_label = "Copy Report to Clipboard"
    bl_options = {'REGISTER'}

    def execute(self, context):
        finder = context.scene.asset_finder
        if not finder.missing_assets:
            self.report({'WARNING'}, "Nothing to copy")
            return {'CANCELLED'}

        groups: dict[str, list] = {}
        for it in finder.missing_assets:
            if it.found_in_patch:
                if it.match_kind == 'DIR':
                    suffix = "~"
                elif it.match_kind == 'BINREF':
                    suffix = "*"
                else:
                    suffix = ""
                key = it.found_in_patch + suffix
            else:
                key = "(not found / not probed)"
            groups.setdefault(key, []).append(it.asset_path)

        lowest = finder.lowest_patch or "(unknown)"
        lines = [
            f"Missing asset report — {finder.last_scan_summary}",
            f"Lowest patch needed (across all resolved assets): {lowest}",
            "Patches with '~' suffix: directory exists but file extension is "
            "not served by CDragon (likely .scb/.skl) — patch's WAD probably "
            "still contains the file.",
            "Patches with '*' suffix: confirmed via that patch's materials.bin "
            "(deep probe).",
            "",
        ]
        # Sort patches with 'latest' first, then numeric desc, then unknown
        def _sort_key(k):
            if k == "latest":
                return (0, ())
            if k.startswith("("):
                return (2, ())
            return (1, tuple(-x for x in _version_tuple(k)))
        for patch in sorted(groups.keys(), key=_sort_key):
            lines.append(f"=== Patch: {patch}  ({len(groups[patch])} file(s)) ===")
            for p in sorted(groups[patch], key=str.lower):
                lines.append(f"  {p}")
            lines.append("")

        bpy.context.window_manager.clipboard = "\n".join(lines)
        self.report({'INFO'}, "Copied report to clipboard")
        return {'FINISHED'}


class ASSETFINDER_OT_open_in_map_patcher(Operator):
    """Pre-fill the Map Patcher with the patch number of the active missing
    asset so the user can quickly download that channel's bin."""
    bl_idname = "assetfinder.open_in_map_patcher"
    bl_label = "Use This Patch in Map Patcher"
    bl_options = {'REGISTER'}

    def execute(self, context):
        finder = context.scene.asset_finder
        if not (0 <= finder.active_index < len(finder.missing_assets)):
            return {'CANCELLED'}
        it = finder.missing_assets[finder.active_index]
        if not it.found_in_patch:
            self.report({'WARNING'}, "This asset has no detected patch yet")
            return {'CANCELLED'}
        mp = getattr(context.scene, "map_patcher_settings", None)
        if mp is None:
            self.report({'ERROR'}, "Map Patcher not registered")
            return {'CANCELLED'}
        # Set Old=found patch, New=latest so user can grab the older bin
        try:
            mp.old_channel = it.found_in_patch
            mp.new_channel = "latest"
            self.report({'INFO'},
                        f"Map Patcher set: old={it.found_in_patch} → new=latest")
        except Exception as e:
            self.report({'ERROR'}, f"Could not prefill Map Patcher: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class ASSETFINDER_UL_missing(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        finder = context.scene.asset_finder
        f = (finder.filter_text or "").lower()
        if f and f not in item.asset_path.lower() and f not in (item.found_in_patch or "").lower():
            return
        row = layout.row(align=True)
        # Status icon
        ic = {
            'UNKNOWN':   'QUESTION',
            'FOUND':     'CHECKMARK',
            'NOT_FOUND': 'X',
            'PROBING':   'TIME',
        }.get(item.probe_status, 'QUESTION')
        row.label(text="", icon=ic)
        # Patch label (fixed width). Append '~' for DIR-only matches,
        # '*' for deep-probe (BINREF) matches.
        if item.found_in_patch:
            mk = item.match_kind
            sfx = "~" if mk == 'DIR' else ("*" if mk == 'BINREF' else "")
            patch_lbl = item.found_in_patch + sfx
        else:
            patch_lbl = "—"
        row.label(text=f"[{patch_lbl}]")
        row.label(text=item.asset_path)


class VIEW3D_PT_asset_finder(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Mapgeo'
    bl_label = "Asset Finder"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        finder = scn.asset_finder
        ps = getattr(scn, "project_settings", None)

        col = layout.column(align=True)
        if ps is not None:
            col.prop(ps, "project_folder", text="Project")
            col.prop(ps, "league_install", text="Riot Install")
            col.prop(ps, "project_map_id", text="Map ID")
        else:
            col.label(text="Project settings unavailable", icon='ERROR')
            return

        col.separator()
        row = col.row(align=True)
        row.operator("assetfinder.scan_project", icon='VIEWZOOM')
        row.operator("assetfinder.clear", text="", icon='TRASH')

        if finder.last_scan_summary:
            col.label(text=finder.last_scan_summary, icon='INFO')

        if finder.missing_assets:
            col.separator()
            row = col.row(align=True)
            row.prop(finder, "oldest_patch", text="Oldest")
            row.prop(finder, "probe_workers", text="Workers")
            row = col.row(align=True)
            if finder.is_probing:
                row.operator("assetfinder.cancel_probe", icon='CANCEL')
                col.label(text=finder.probe_progress, icon='TIME')
            else:
                row.operator("assetfinder.find_patches", icon='URL')
                row.operator("assetfinder.deep_probe", icon='ZOOM_ALL')
            col.operator("assetfinder.copy_report", icon='COPYDOWN')

            if finder.lowest_patch:
                col.label(text=f"Lowest patch needed: {finder.lowest_patch}",
                          icon='SORT_DESC')

            col.separator()
            col.prop(finder, "filter_text", text="", icon='VIEWZOOM')
            col.template_list(
                "ASSETFINDER_UL_missing", "",
                finder, "missing_assets",
                finder, "active_index",
                rows=10,
            )
            if 0 <= finder.active_index < len(finder.missing_assets):
                it = finder.missing_assets[finder.active_index]
                box = col.box()
                box.label(text=it.asset_path, icon='FILE')
                if it.referenced_by:
                    box.label(text=f"in {it.referenced_by}", icon='OUTLINER_DATA_FONT')
                if it.found_in_patch:
                    if it.match_kind == 'DIR':
                        suffix = "  (dir-only — extension not served by CDragon, WAD likely has it)"
                    elif it.match_kind == 'BINREF':
                        suffix = "  (confirmed via patch materials.bin)"
                    else:
                        suffix = ""
                    box.label(text=f"Last seen in patch {it.found_in_patch}{suffix}", icon='RECOVER_LAST')
                    box.operator("assetfinder.open_in_map_patcher", icon='IMPORT')
                elif it.probe_status == 'NOT_FOUND':
                    box.label(text="Not found in any probed patch", icon='ERROR')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    MissingAssetItem,
    AssetFinderSettings,
    ASSETFINDER_OT_scan_project,
    ASSETFINDER_OT_find_patches,
    ASSETFINDER_OT_deep_probe,
    ASSETFINDER_OT_cancel_probe,
    ASSETFINDER_OT_clear,
    ASSETFINDER_OT_copy_to_clipboard,
    ASSETFINDER_OT_open_in_map_patcher,
    ASSETFINDER_UL_missing,
    VIEW3D_PT_asset_finder,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.asset_finder = PointerProperty(type=AssetFinderSettings)


def unregister():
    if hasattr(bpy.types.Scene, "asset_finder"):
        del bpy.types.Scene.asset_finder
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
