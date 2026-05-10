"""Map Auto Updater - multi-project per-entry materials.bin updater.

Separate from the Project Checker. Lets the user point at a folder that
contains many map mod projects (each with a `Map*` subfolder), diffs every
project's `*.materials.bin` against CommunityDragon `latest`, lets the user
pick exactly which entries to apply per project, backs the project up as a
zip, and writes the updated bin.

Map*.bin patching is intentionally out of scope for v1 (no prey schema yet).

UI: child sub-panel of `VIEW3D_PT_project_manager`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime
from urllib import request
from urllib.error import HTTPError, URLError

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import map_patcher, prey_format, propertybin_parser

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_CDRAGON_BASE = "https://raw.communitydragon.org"
_USER_AGENT = {"User-Agent": "BlenderMapgeoAddon/MapAutoUpdater"}
_MAP_FOLDER_RE = re.compile(r"^map\d+$", re.IGNORECASE)
_BACKUP_DIRNAME = "_backups"

# Background diff worker (single-flight)
_worker_state: dict = {
    "thread": None,
    "running": False,
    "result": None,
    "error": "",
    "progress": "",
}

# Cached cdragon version list (refreshed on demand)
_cdragon_versions_cache: list[str] = []
_cdragon_versions_error: str = ""

# Cached list of (variant, label, description) tuples for the variant
# EnumProperty. Kept at module scope so Blender doesn't GC the strings.
_variant_items_cache: list = [("__all__", "(All variants)", "Diff every variant")]


def _norm(s: str) -> str:
    return (s or "").replace("\\", "/").strip()


def _is_map_folder(name: str) -> bool:
    """Match Map* folders, including 'Map11', 'Map11.wad', 'Map11.wad.client'."""
    n = (name or "").lower()
    if not n.startswith("map"):
        return False
    head = n.split(".", 1)[0]  # 'map11' from 'map11.wad.client'
    return bool(re.match(r"^map\d+$", head))


def _find_mapgeometry_dir(map_dir: str) -> str:
    """Return path to <map_dir>/data/maps/mapgeometry if it exists.

    Tolerates case variants ('DATA', 'Data') by walking the first level.
    """
    if not os.path.isdir(map_dir):
        return ""
    # Fast path
    direct = os.path.join(map_dir, "data", "maps", "mapgeometry")
    if os.path.isdir(direct):
        return direct
    # Case-insensitive walk for the 3 segments
    cur = map_dir
    for seg in ("data", "maps", "mapgeometry"):
        try:
            entries = os.listdir(cur)
        except OSError:
            return ""
        match = next((e for e in entries if e.lower() == seg), None)
        if not match:
            return ""
        cur = os.path.join(cur, match)
        if not os.path.isdir(cur):
            return ""
    return cur


def _list_materials_bins(map_dir: str) -> list[tuple[str, str, str]]:
    """Return list of (abs_path, variant, map_id) for every *.materials.bin
    found under <map_dir>/data/maps/mapgeometry/<mapid>/.

    Falls back to scanning *.materials.bin directly under map_dir for the
    rare flat-layout case.
    """
    out: list[tuple[str, str, str]] = []
    if not os.path.isdir(map_dir):
        return out

    mg_root = _find_mapgeometry_dir(map_dir)
    if mg_root:
        for map_id_name in sorted(os.listdir(mg_root)):
            mid_dir = os.path.join(mg_root, map_id_name)
            if not os.path.isdir(mid_dir):
                continue
            for fn in sorted(os.listdir(mid_dir)):
                full = os.path.join(mid_dir, fn)
                if not os.path.isfile(full):
                    continue
                low = fn.lower()
                if not low.endswith(".materials.bin"):
                    continue
                variant = low[:-len(".materials.bin")]
                out.append((full, variant, map_id_name.lower()))
        if out:
            return out

    # Legacy / flat fallback: project authors who keep bins next to Map*
    folder_name = os.path.basename(map_dir.rstrip("/\\")).lower().split(".", 1)[0]
    for fn in os.listdir(map_dir):
        full = os.path.join(map_dir, fn)
        if not os.path.isfile(full):
            continue
        low = fn.lower()
        if not low.endswith(".materials.bin"):
            continue
        variant = low[:-len(".materials.bin")]
        out.append((full, variant, folder_name))
    return out


def _discover_projects(projects_root: str) -> list[dict]:
    """Walk projects_root and find map mod projects.

    A project is any direct subfolder that contains a `Map*` subfolder whose
    `data/maps/mapgeometry/<mapid>/` directory holds at least one
    `*.materials.bin`. The `Map*` folder itself can be `Map11`, `Map11.wad`,
    or `Map11.wad.client`.
    Returns: [{name, path, map_dir, map_name (mapid), materials: [(path, variant, mapid)]}]
    """
    projects = []
    if not projects_root or not os.path.isdir(projects_root):
        return projects
    for entry in sorted(os.listdir(projects_root)):
        proj_path = os.path.join(projects_root, entry)
        if not os.path.isdir(proj_path):
            continue
        for sub in sorted(os.listdir(proj_path)):
            sub_path = os.path.join(proj_path, sub)
            if not os.path.isdir(sub_path):
                continue
            if not _is_map_folder(sub):
                continue
            mats = _list_materials_bins(sub_path)
            if not mats:
                continue
            # Use the mapid from the first found bin (e.g. 'map11')
            map_id = mats[0][2]
            projects.append({
                "name": entry,
                "path": proj_path,
                "map_dir": sub_path,
                "map_name": map_id,
                "materials": [(p, v, m) for (p, v, m) in mats],
            })
            break  # only first Map* per project
    return projects


def _download_cdragon_materials(map_name: str, variant: str, channel: str = "latest") -> bytes:
    """Download a .materials.bin for map/variant from CommunityDragon."""
    url = (
        f"{_CDRAGON_BASE}/{channel}/game/data/maps/mapgeometry/"
        f"{map_name.lower()}/{variant.lower()}.materials.bin"
    )
    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _refresh_cdragon_versions() -> tuple[list[str], str]:
    """Populate the cdragon version cache. Returns (versions, error_str)."""
    global _cdragon_versions_cache, _cdragon_versions_error
    try:
        versions = map_patcher._fetch_cdragon_versions()
        # Newest first for nicer dropdowns
        _cdragon_versions_cache = list(reversed(versions))
        _cdragon_versions_error = ""
    except Exception as e:
        _cdragon_versions_error = f"{type(e).__name__}: {e}"
    return _cdragon_versions_cache, _cdragon_versions_error


def _channel_enum_items(self, context):
    """EnumProperty items callback: cached cdragon versions + 'latest'/'pbe'."""
    items = [
        ("latest", "latest", "CommunityDragon latest channel"),
        ("pbe", "pbe", "CommunityDragon PBE channel"),
    ]
    for v in _cdragon_versions_cache:
        items.append((v, v, f"Patch {v}"))
    return items


def _fetch_cdragon_variants(channel: str, map_id: str) -> list[str]:
    """List the *.materials.bin variants Riot ships under
    `<channel>/game/data/maps/mapgeometry/<map_id>/`.

    Returns a sorted list of variant names (e.g. ['base', 'odin', 'srx']).
    Raises on network/parse errors so the caller can surface the error.
    """
    ch = (channel or "latest").strip().strip("/").lower()
    mid = (map_id or "map11").strip().lower()
    url = f"{_CDRAGON_BASE}/json/{ch}/game/data/maps/mapgeometry/{mid}/"
    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    variants: list[str] = []
    for entry in data:
        name = (entry.get("name") or "").lower()
        etype = (entry.get("type") or "").lower()
        if etype and etype != "file":
            continue
        if name.endswith(".materials.bin"):
            variants.append(name[: -len(".materials.bin")])
    variants.sort()
    return variants


def _local_map_ids(projects_root: str) -> list[str]:
    """Return the distinct map_ids of local projects (used to scope the
    Riot-side variant lookup). Falls back to ['map11'] if none found."""
    seen: list[str] = []
    if projects_root and os.path.isdir(projects_root):
        try:
            for proj in _discover_projects(projects_root):
                mid = (proj.get("map_name") or "").lower()
                if mid and mid not in seen:
                    seen.append(mid)
        except Exception:
            pass
    return seen or ["map11"]


def _refresh_variant_items(projects_root: str, channel: str = "latest") -> tuple[int, str]:
    """Rebuild `_variant_items_cache` from CommunityDragon for the given channel.

    Variants are looked up per local map_id (so multi-project setups still
    work). Falls back to map11 if no project is configured.
    Returns (count, error_str).
    """
    global _variant_items_cache
    items = [("__all__", "(All variants)", "Diff every variant in every project")]
    map_ids = _local_map_ids(projects_root)
    seen: list[tuple[str, str]] = []  # (variant, source-map_id)
    error = ""
    for mid in map_ids:
        try:
            for v in _fetch_cdragon_variants(channel, mid):
                if not any(v == sv for sv, _ in seen):
                    seen.append((v, mid))
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            print(f"[MapAutoUpdater] variant lookup failed for {mid}@{channel}: {e}")
    for v, mid in seen:
        if len(map_ids) > 1:
            items.append((v, f"{v} ({mid})", f"Riot variant '{v}' under {mid}"))
        else:
            items.append((v, v, f"Riot variant '{v}'"))
    _variant_items_cache = items
    return len(seen), error


def _variant_enum_items(self, context):
    """EnumProperty items: cached '(All)' + every Riot-side variant found."""
    return _variant_items_cache


def _on_projects_root_changed(self, context):
    """Update callback: refresh variant list when projects folder changes."""
    try:
        root = bpy.path.abspath(self.projects_root) if self.projects_root else ""
        _refresh_variant_items(root, self.new_channel or "latest")
    except Exception as e:
        print(f"[MapAutoUpdater] projects_root update failed: {e}")


def _on_new_channel_changed(self, context):
    """Update callback: refresh variant list when target patch changes."""
    try:
        root = bpy.path.abspath(self.projects_root) if self.projects_root else ""
        _refresh_variant_items(root, self.new_channel or "latest")
    except Exception as e:
        print(f"[MapAutoUpdater] new_channel update failed: {e}")


def _detect_lol_game_path() -> str:
    """Auto-detect the League of Legends `Game` directory.

    Reuses project_manager.find_league_install() and appends 'Game'.
    """
    try:
        from . import project_manager as _pm
        install = _pm.find_league_install()
        if install:
            game = os.path.join(install, "Game")
            if os.path.isdir(game):
                return game
    except Exception:
        pass
    return ""


def _entry_label(entry: dict) -> str:
    """Best-effort human label for an entry (the asset path string)."""
    if not isinstance(entry, dict):
        return "<invalid>"
    # propertybin_parser includes path / pathString variants
    for key in ("path", "pathString", "path_string", "name"):
        v = entry.get(key)
        if isinstance(v, str) and v:
            return v
    # Fallback: search fields for first string value
    fields = entry.get("fields") or []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                v = f.get("value")
                if isinstance(v, str) and v and ("/" in v or "_" in v):
                    return v
    return entry.get("path_hash") or "<unknown>"


def _entry_type_label(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    return (
        entry.get("type_name")
        or entry.get("typeName")
        or entry.get("type_hash")
        or ""
    )


def _short_change_summary(diff_entry: dict, old_entry: dict | None) -> str:
    """Produce a short multi-line summary of what changed in a modified entry.

    Uses prey conversion when entry is a material; otherwise diffs top-level
    field names by hash.
    """
    try:
        if old_entry and map_patcher._is_material_entry(diff_entry):
            old_prey = prey_format._bin_material_to_prey(old_entry)
            new_prey = prey_format._bin_material_to_prey(diff_entry)
            keys = sorted(set(old_prey.keys()) | set(new_prey.keys()))
            lines = []
            for k in keys:
                a = old_prey.get(k)
                b = new_prey.get(k)
                if a == b:
                    continue
                lines.append(f"  {k}: {_short_repr(a)} -> {_short_repr(b)}")
            if not lines:
                return "  (no field-level changes detected)"
            return "\n".join(lines[:30])
    except Exception:
        pass

    # Generic field list comparison
    new_fields = {f.get("name_hash"): f for f in (diff_entry.get("fields") or []) if isinstance(f, dict)}
    old_fields = {f.get("name_hash"): f for f in ((old_entry or {}).get("fields") or []) if isinstance(f, dict)}
    changed = []
    for h, fnew in new_fields.items():
        fold = old_fields.get(h)
        if fold is None:
            changed.append(f"  + field {h}")
        elif json.dumps(fnew, sort_keys=True, default=str) != json.dumps(fold, sort_keys=True, default=str):
            changed.append(f"  ~ field {h}")
    for h in old_fields:
        if h not in new_fields:
            changed.append(f"  - field {h}")
    if not changed:
        return "  (no field-level diff)"
    return "\n".join(changed[:30])


def _short_repr(v) -> str:
    s = repr(v)
    return s if len(s) <= 80 else s[:77] + "..."


# ---------------------------------------------------------------------------
# Diff core: per project
# ---------------------------------------------------------------------------

def _diff_one_project(project: dict, old_channel: str, new_channel: str) -> dict:
    """Diff every materials.bin in `project` between two cdragon channels.

    For each variant the project ships, downloads `<old>` and `<new>` from
    CommunityDragon and computes the entry-level diff representing the Riot
    upstream changes between those patches. The user picks which of those
    Riot changes to apply on top of their local mod bin.

    Returns:
      {
        name, path, map_dir, map_name,
        files: [
          {
            local_path, variant, map_id, status, error,
            added: [...new entries...], modified: [...new entries...],
            removed: [keys...],
            old_index: {key: old-channel entry},
            new_index: {key: new-channel entry},
            local_index: {key: local entry},
          },
          ...
        ],
      }
    """
    out = {
        "name": project["name"],
        "path": project["path"],
        "map_dir": project["map_dir"],
        "map_name": project["map_name"],
        "files": [],
    }

    cache_root = os.path.join(
        bpy.utils.resource_path("USER"),
        "mapgeo_addon", "map_auto_updater", "remote_cache",
    )

    def _fetch(map_id: str, variant: str, channel: str) -> str:
        tmp_dir = os.path.join(cache_root, map_id, variant)
        os.makedirs(tmp_dir, exist_ok=True)
        out_path = os.path.join(tmp_dir, f"{channel}.materials.bin")
        if not os.path.isfile(out_path):
            data = _download_cdragon_materials(map_id, variant, channel=channel)
            with open(out_path, "wb") as f:
                f.write(data)
        return out_path

    for local_path, variant, map_id in project["materials"]:
        file_result = {
            "local_path": local_path,
            "variant": variant,
            "map_id": map_id,
            "status": "ok",
            "error": "",
            "added": [],
            "modified": [],
            "removed": [],
            "old_index": {},
            "new_index": {},
            "local_index": {},
        }
        try:
            try:
                old_path = _fetch(map_id, variant, old_channel)
                new_path = _fetch(map_id, variant, new_channel)
            except HTTPError as e:
                file_result["status"] = "missing_remote"
                file_result["error"] = f"HTTP {e.code} for {variant}.materials.bin"
                out["files"].append(file_result)
                continue
            except URLError as e:
                file_result["status"] = "network_error"
                file_result["error"] = str(e)
                out["files"].append(file_result)
                continue

            old_entries = map_patcher._load_bin_entries(old_path)
            new_entries = map_patcher._load_bin_entries(new_path)
            local_entries = map_patcher._load_bin_entries(local_path)

            old_index = {map_patcher._entry_key(e): e for e in old_entries if map_patcher._entry_key(e)}
            new_index = {map_patcher._entry_key(e): e for e in new_entries if map_patcher._entry_key(e)}
            local_index = {map_patcher._entry_key(e): e for e in local_entries if map_patcher._entry_key(e)}

            diff = map_patcher._create_diff(old_entries, new_entries)

            file_result["added"] = diff["added"]
            file_result["modified"] = diff["modified"]
            file_result["removed"] = diff["removed"]
            file_result["old_index"] = old_index
            file_result["new_index"] = new_index
            file_result["local_index"] = local_index
        except Exception as e:
            file_result["status"] = "error"
            file_result["error"] = f"{type(e).__name__}: {e}"
        out["files"].append(file_result)
    return out


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _backup_project(project_path: str, label: str = "pre_update") -> str:
    """Create a zip backup of the project's materials.bin files.

    Backs up only *.materials.bin under any Map* folder (small, fast, safe).
    Returns path to the created zip.
    """
    backup_dir = os.path.join(project_path, _BACKUP_DIRNAME)
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(backup_dir, f"{ts}_{label}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_path):
            # Skip our own backup dir to prevent runaway nesting
            rel_root = os.path.relpath(root, project_path)
            if rel_root.split(os.sep)[0] == _BACKUP_DIRNAME:
                continue
            for fn in files:
                if fn.lower().endswith(".materials.bin"):
                    full = os.path.join(root, fn)
                    arcname = os.path.relpath(full, project_path)
                    zf.write(full, arcname)
    return zip_path


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _apply_selected_to_file(file_result: dict, selected_keys: set, settings) -> dict:
    """Apply the user-selected entries from a diff to the local materials.bin.

    selected_keys: set of normalized hashes that the user has checked in the UI.
    Returns: {added, modified, removed, written}
    """
    local_path = file_result["local_path"]
    data = propertybin_parser.parse_bin(local_path)
    entries = list(data.get("entries", []))

    # Build filtered diff containing only user-selected items
    filtered = {
        "added":    [e for e in file_result["added"]    if map_patcher._entry_key(e) in selected_keys],
        "modified": [e for e in file_result["modified"] if map_patcher._entry_key(e) in selected_keys],
        "removed":  [k for k in file_result["removed"]  if map_patcher._normalize_hash(k) in selected_keys],
    }

    options = {
        "apply_added":    True,
        "apply_modified": True,
        "apply_removed":  True,
        "preserve_texture_paths": bool(getattr(settings, "preserve_textures", True)),
        "skip_material_entry_modifications": False,
    }
    new_entries = map_patcher._apply_diff_to_entries(entries, filtered, options=options)

    data["entries"] = new_entries
    data["entry_count"] = len(new_entries)
    propertybin_parser.write_bin(data, local_path)

    return {
        "added": len(filtered["added"]),
        "modified": len(filtered["modified"]),
        "removed": len(filtered["removed"]),
        "written": local_path,
    }


# ---------------------------------------------------------------------------
# Property groups
# ---------------------------------------------------------------------------

class MapUpdaterEntry(PropertyGroup):
    apply: BoolProperty(default=True, name="Apply")
    project_idx: IntProperty(default=-1)
    file_idx: IntProperty(default=-1)
    change: StringProperty(default="modified")  # 'added' | 'modified' | 'removed'
    entry_key: StringProperty(default="")        # normalized hash
    label: StringProperty(default="")
    type_label: StringProperty(default="")
    preview: StringProperty(default="")          # short multi-line summary
    is_material: BoolProperty(default=False)      # True if this entry is a StaticMaterialDef


class MapUpdaterFile(PropertyGroup):
    local_path: StringProperty()
    variant: StringProperty()
    status: StringProperty(default="ok")
    error: StringProperty()
    added_count: IntProperty(default=0)
    modified_count: IntProperty(default=0)
    removed_count: IntProperty(default=0)
    expanded: BoolProperty(default=False)


class MapUpdaterProject(PropertyGroup):
    name: StringProperty()
    path: StringProperty(subtype="DIR_PATH")
    map_name: StringProperty()
    map_dir: StringProperty(subtype="DIR_PATH")
    selected: BoolProperty(default=True, name="Selected")
    expanded: BoolProperty(default=True)
    status_text: StringProperty()
    files: CollectionProperty(type=MapUpdaterFile)


class MapUpdaterSettings(PropertyGroup):
    game_path: StringProperty(
        name="LoL Game Path",
        description="Path to the League of Legends 'Game' directory (used for offline / local WAD extraction; optional in v1)",
        subtype="DIR_PATH",
        default="",
    )
    projects_root: StringProperty(
        name="Projects Folder",
        description="Folder that contains one or more map mod projects (each with a Map* subfolder)",
        subtype="DIR_PATH",
        default="",
        update=_on_projects_root_changed,
    )
    channel: StringProperty(
        name="Legacy Channel",
        description="(Deprecated) Use Old/New Patch instead",
        default="latest",
    )
    old_channel: EnumProperty(
        name="Old Patch",
        description="CommunityDragon channel to diff FROM (the patch your mod was built on)",
        items=_channel_enum_items,
    )
    new_channel: EnumProperty(
        name="New Patch",
        description="CommunityDragon channel to diff TO (usually 'latest')",
        items=_channel_enum_items,
        update=_on_new_channel_changed,
    )
    versions_status: StringProperty(default="")
    variant_filter: EnumProperty(
        name="Variant",
        description="Limit the diff to a single map variant. '(All)' diffs every variant Riot ships for this map",
        items=_variant_enum_items,
    )
    preserve_textures: BoolProperty(
        name="Preserve Custom Texture Paths",
        description="When applying modified entries, keep your project's texture asset paths instead of overwriting with Riot's",
        default=True,
    )
    show_preview: BoolProperty(
        name="Show Field Diff Preview",
        description="Show per-entry field-level diff text in the panel (slower)",
        default=False,
    )
    last_status: StringProperty(default="")

    projects: CollectionProperty(type=MapUpdaterProject)
    entries: CollectionProperty(type=MapUpdaterEntry)
    active_entry_index: IntProperty(default=0)


# ---------------------------------------------------------------------------
# Background worker (so UI doesn't freeze on cdragon downloads)
# ---------------------------------------------------------------------------

def _worker_run(projects: list[dict], old_channel: str, new_channel: str):
    try:
        results = []
        for i, p in enumerate(projects):
            _worker_state["progress"] = f"[{i+1}/{len(projects)}] {p['name']}"
            results.append(_diff_one_project(p, old_channel, new_channel))
        _worker_state["result"] = results
    except Exception as e:
        _worker_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        _worker_state["running"] = False


def _worker_poll():
    """Timer callback: when the worker finishes, populate UI state."""
    if _worker_state["running"]:
        return 0.5
    # Done — push results into scene properties on main thread
    try:
        results = _worker_state.get("result") or []
        scene = bpy.context.scene
        s = scene.map_updater_settings
        s.projects.clear()
        s.entries.clear()

        total_added = total_mod = total_rem = 0
        for p in results:
            proj = s.projects.add()
            proj.name = p["name"]
            proj.path = p["path"]
            proj.map_name = p["map_name"]
            proj.map_dir = p["map_dir"]
            project_idx = len(s.projects) - 1

            for fi, f in enumerate(p["files"]):
                pf = proj.files.add()
                pf.local_path = f["local_path"]
                pf.variant = f["variant"]
                pf.status = f["status"]
                pf.error = f["error"]
                pf.added_count = len(f["added"])
                pf.modified_count = len(f["modified"])
                pf.removed_count = len(f["removed"])
                total_added += pf.added_count
                total_mod += pf.modified_count
                total_rem += pf.removed_count

                if f["status"] != "ok":
                    continue

                show_preview = s.show_preview
                # Added
                for e in f["added"]:
                    row = s.entries.add()
                    row.project_idx = project_idx
                    row.file_idx = fi
                    row.change = "added"
                    row.entry_key = map_patcher._entry_key(e)
                    row.label = _entry_label(e)
                    row.type_label = _entry_type_label(e)
                    row.is_material = bool(map_patcher._is_material_entry(e))
                    row.preview = "  (new entry)"
                # Modified
                for e in f["modified"]:
                    row = s.entries.add()
                    row.project_idx = project_idx
                    row.file_idx = fi
                    row.change = "modified"
                    row.entry_key = map_patcher._entry_key(e)
                    row.label = _entry_label(e)
                    row.type_label = _entry_type_label(e)
                    row.is_material = bool(map_patcher._is_material_entry(e))
                    row.preview = (
                        _short_change_summary(e, f["old_index"].get(row.entry_key))
                        if show_preview else ""
                    )
                # Removed
                for k in f["removed"]:
                    row = s.entries.add()
                    row.project_idx = project_idx
                    row.file_idx = fi
                    row.change = "removed"
                    row.entry_key = map_patcher._normalize_hash(k)
                    old = f["old_index"].get(row.entry_key)
                    row.label = _entry_label(old) if old else row.entry_key
                    row.type_label = _entry_type_label(old) if old else ""
                    row.is_material = bool(
                        map_patcher._is_material_entry(old) if old else False
                    )
                    row.preview = "  (would be removed)"

        if _worker_state.get("error"):
            s.last_status = f"Diff error: {_worker_state['error']}"
        else:
            s.last_status = (
                f"Diff complete: {len(s.projects)} project(s), "
                f"+{total_added} ~{total_mod} -{total_rem}"
            )
        # Cache the raw results for apply-time access
        _worker_state["last_results"] = results
        # Tag redraw
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as e:
        print(f"[MapAutoUpdater] poll merge failed: {e}")
    return None  # stop timer


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MAPUPD_OT_scan_and_diff(Operator):
    """Scan the projects folder and diff every project's materials.bin
    against CommunityDragon `latest` (background; UI stays responsive)."""
    bl_idname = "map_updater.scan_and_diff"
    bl_label = "Scan & Diff Projects"
    bl_options = {'REGISTER'}

    def execute(self, context):
        s = context.scene.map_updater_settings
        root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
        if not root or not os.path.isdir(root):
            self.report({'ERROR'}, "Set a valid Projects Folder first")
            return {'CANCELLED'}

        if _worker_state["running"]:
            self.report({'WARNING'}, "Diff already in progress")
            return {'CANCELLED'}

        projects = _discover_projects(root)
        if not projects:
            self.report({'WARNING'},
                        "No projects found (need <root>/<project>/Map*/<variant>.materials.bin)")
            return {'CANCELLED'}

        # Refresh the variant cache so the dropdown reflects what we just scanned
        _refresh_variant_items(root, s.new_channel or "latest")

        # Optional variant filter
        vf = (s.variant_filter or "").strip().lower()
        if vf and vf != "__all__":
            for p in projects:
                p["materials"] = [
                    m for m in p["materials"] if m[1].lower() == vf
                ]
            projects = [p for p in projects if p["materials"]]
            if not projects:
                self.report({'WARNING'},
                            f"None of your projects ship the Riot variant '{vf}'. "
                            "Pick a different variant or use '(All variants)'.")
                return {'CANCELLED'}

        # Reset state
        s.projects.clear()
        s.entries.clear()
        s.last_status = (
            f"Diffing {len(projects)} project(s): {s.old_channel} -> {s.new_channel}..."
        )
        _worker_state["result"] = None
        _worker_state["error"] = ""
        _worker_state["progress"] = ""
        _worker_state["running"] = True
        _worker_state["thread"] = threading.Thread(
            target=_worker_run,
            args=(projects, s.old_channel.strip() or "latest",
                  s.new_channel.strip() or "latest"),
            daemon=True,
        )
        _worker_state["thread"].start()
        bpy.app.timers.register(_worker_poll, first_interval=0.5)
        self.report({'INFO'}, f"Diffing {len(projects)} project(s) in background")
        return {'FINISHED'}


class MAPUPD_OT_set_apply_all(Operator):
    """Toggle 'apply' on all listed entries."""
    bl_idname = "map_updater.set_apply_all"
    bl_label = "Set Apply on All"

    value: BoolProperty(default=True)
    only_change: StringProperty(default="")  # '' | 'added' | 'modified' | 'removed'
    only_type: StringProperty(default="")    # '' | 'material' | 'other'

    def execute(self, context):
        s = context.scene.map_updater_settings
        n = 0
        for e in s.entries:
            if self.only_change and e.change != self.only_change:
                continue
            if self.only_type == "material" and not e.is_material:
                continue
            if self.only_type == "other" and e.is_material:
                continue
            e.apply = self.value
            n += 1
        self.report({'INFO'}, f"{n} entry rows updated")
        return {'FINISHED'}


class MAPUPD_OT_apply(Operator):
    """Backup each project as a zip, then apply the user-selected entries
    to every project's materials.bin."""
    bl_idname = "map_updater.apply"
    bl_label = "Backup & Apply Selected"
    bl_options = {'REGISTER'}

    dry_run: BoolProperty(name="Dry Run", default=False)

    def execute(self, context):
        s = context.scene.map_updater_settings
        results = _worker_state.get("last_results") or []
        if not results:
            self.report({'ERROR'}, "Run 'Scan & Diff Projects' first")
            return {'CANCELLED'}

        # Group selected entry keys per (project_idx, file_idx)
        selected: dict = {}
        for e in s.entries:
            if not e.apply:
                continue
            key = (e.project_idx, e.file_idx)
            selected.setdefault(key, set()).add(e.entry_key)

        if not selected:
            self.report({'WARNING'}, "Nothing selected to apply")
            return {'CANCELLED'}

        report_lines = ["Map Auto Updater - Apply Report",
                        f"Diff: {s.old_channel} -> {s.new_channel}",
                        f"Dry run: {self.dry_run}", ""]
        applied_files = 0
        backed_up = 0
        failed = 0

        # Iterate per project so we make exactly one backup per project
        per_project: dict = {}
        for (pi, fi), keys in selected.items():
            per_project.setdefault(pi, []).append((fi, keys))

        for pi, file_groups in per_project.items():
            if pi < 0 or pi >= len(s.projects):
                continue
            proj = s.projects[pi]
            project_path = bpy.path.abspath(proj.path)

            # Backup once per project
            if not self.dry_run:
                try:
                    zip_path = _backup_project(project_path)
                    backed_up += 1
                    report_lines.append(f"[BACKUP] {proj.name} -> {os.path.basename(zip_path)}")
                except Exception as e:
                    report_lines.append(f"[BACKUP_FAIL] {proj.name}: {e}")
                    failed += 1
                    continue
            else:
                report_lines.append(f"[WOULD_BACKUP] {proj.name}")

            for fi, keys in file_groups:
                if pi >= len(results) or fi >= len(results[pi]["files"]):
                    continue
                fr = results[pi]["files"][fi]
                if fr["status"] != "ok":
                    report_lines.append(
                        f"  [SKIP] {proj.name}/{fr['variant']}: status={fr['status']}"
                    )
                    continue
                if self.dry_run:
                    report_lines.append(
                        f"  [WOULD_APPLY] {proj.name}/{fr['variant']}.materials.bin "
                        f"({len(keys)} entries)"
                    )
                    continue
                try:
                    res = _apply_selected_to_file(fr, keys, s)
                    applied_files += 1
                    report_lines.append(
                        f"  [APPLIED] {proj.name}/{fr['variant']}.materials.bin "
                        f"+{res['added']} ~{res['modified']} -{res['removed']}"
                    )
                except Exception as e:
                    failed += 1
                    report_lines.append(
                        f"  [APPLY_FAIL] {proj.name}/{fr['variant']}.materials.bin: {e}"
                    )

        report_lines.append("")
        report_lines.append(
            f"Summary: backed up {backed_up}, applied to {applied_files} file(s), failed {failed}"
        )
        report_text = "\n".join(report_lines)
        context.window_manager.clipboard = report_text
        print("[MapAutoUpdater] " + report_text.replace("\n", "\n[MapAutoUpdater] "))

        s.last_status = (
            f"Apply done: {applied_files} file(s), {backed_up} backup(s), {failed} fail(s)"
        )
        self.report({'INFO'}, s.last_status + " (report copied to clipboard)")
        return {'FINISHED'}


def _list_project_backups(projects_root: str) -> list[tuple[str, str, str]]:
    """Return [(project_name, zip_path, mtime_iso), ...] sorted newest first."""
    out: list[tuple[str, str, str]] = []
    if not projects_root or not os.path.isdir(projects_root):
        return out
    for entry in os.listdir(projects_root):
        proj_path = os.path.join(projects_root, entry)
        bdir = os.path.join(proj_path, _BACKUP_DIRNAME)
        if not os.path.isdir(bdir):
            continue
        for fn in os.listdir(bdir):
            if not fn.lower().endswith(".zip"):
                continue
            full = os.path.join(bdir, fn)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            out.append((entry, full,
                        datetime.fromtimestamp(mtime).isoformat(timespec="seconds")))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def _restore_backup_zip(zip_path: str, project_path: str) -> tuple[int, list[str]]:
    """Extract every file in the zip into project_path (overwriting).

    Returns (count_restored, errors). Refuses unsafe path-traversal arcnames.
    """
    errors: list[str] = []
    count = 0
    project_norm = os.path.normpath(project_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            try:
                target = os.path.normpath(os.path.join(project_path, info.filename))
                if not target.startswith(project_norm + os.sep) and target != project_norm:
                    errors.append(f"unsafe path: {info.filename}")
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info, "r") as src, open(target, "wb") as dst:
                    dst.write(src.read())
                count += 1
            except Exception as e:
                errors.append(f"{info.filename}: {e}")
    return count, errors


class MAPUPD_OT_recover_backup(Operator):
    """Restore a project's materials.bin files from a previous backup zip."""
    bl_idname = "map_updater.recover_backup"
    bl_label = "Recover Backup"
    bl_description = "Restore *.materials.bin files from a previously created _backups/*.zip"
    bl_options = {'REGISTER'}

    def _backup_items(self, context):
        s = context.scene.map_updater_settings
        root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
        items = []
        for proj, zpath, when in _list_project_backups(root):
            label = f"{proj} | {os.path.basename(zpath)} | {when}"
            items.append((zpath, label, f"Restore from {zpath}"))
        if not items:
            items = [("__none__", "(no backups found)", "")]
        return items

    backup: EnumProperty(name="Backup", items=_backup_items)
    confirm: BoolProperty(
        name="I understand this will overwrite current files",
        default=False,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        s = context.scene.map_updater_settings
        root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
        col = layout.column(align=True)
        if not root or not os.path.isdir(root):
            col.alert = True
            col.label(text="Set a valid Projects Folder first.", icon='ERROR')
            return
        backups = _list_project_backups(root)
        if not backups:
            col.label(text="No backups found in any project's _backups/ folder.",
                      icon='INFO')
            return
        col.label(text=f"Found {len(backups)} backup(s):", icon='FILE_BACKUP')
        col.prop(self, "backup", text="")
        col.separator()
        warn = col.row()
        warn.alert = True
        warn.prop(self, "confirm")

    def execute(self, context):
        s = context.scene.map_updater_settings
        root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
        if not root or not os.path.isdir(root):
            self.report({'ERROR'}, "Set a valid Projects Folder first")
            return {'CANCELLED'}
        if self.backup == "__none__" or not self.backup:
            self.report({'WARNING'}, "No backup selected")
            return {'CANCELLED'}
        if not self.confirm:
            self.report({'WARNING'}, "Tick the confirmation checkbox to proceed")
            return {'CANCELLED'}
        if not os.path.isfile(self.backup):
            self.report({'ERROR'}, f"Backup file not found: {self.backup}")
            return {'CANCELLED'}

        # Project path = parent of the _backups directory
        backup_dir = os.path.dirname(self.backup)
        project_path = os.path.dirname(backup_dir)
        if (os.path.basename(backup_dir) != _BACKUP_DIRNAME
                or not os.path.isdir(project_path)):
            self.report({'ERROR'},
                        "Backup zip is not inside a project's _backups/ folder")
            return {'CANCELLED'}

        # Safety: snapshot current state first so a recovery is itself reversible
        try:
            safety_zip = _backup_project(project_path, label="pre_recover")
        except Exception as e:
            self.report({'ERROR'}, f"Pre-recover snapshot failed: {e}")
            return {'CANCELLED'}

        try:
            count, errors = _restore_backup_zip(self.backup, project_path)
        except Exception as e:
            self.report({'ERROR'}, f"Recover failed: {e}")
            return {'CANCELLED'}

        if errors:
            s.last_status = (
                f"Recovered {count} file(s) with {len(errors)} error(s); "
                f"safety snapshot: {os.path.basename(safety_zip)}"
            )
            self.report({'WARNING'}, s.last_status)
            for err in errors[:5]:
                print(f"[MapAutoUpdater][recover] {err}")
        else:
            s.last_status = (
                f"Recovered {count} file(s) from {os.path.basename(self.backup)}; "
                f"safety snapshot: {os.path.basename(safety_zip)}"
            )
            self.report({'INFO'}, s.last_status)
        return {'FINISHED'}


class MAPUPD_OT_detect_game_path(Operator):
    """Auto-detect the League of Legends 'Game' directory."""
    bl_idname = "map_updater.detect_game_path"
    bl_label = "Detect Game Path"
    bl_description = "Search common install locations and the Windows registry for the LoL Game folder"

    def execute(self, context):
        s = context.scene.map_updater_settings
        path = _detect_lol_game_path()
        if not path:
            self.report({'WARNING'},
                        "League of Legends Game folder not found. Set it manually.")
            return {'CANCELLED'}
        s.game_path = path
        self.report({'INFO'}, f"Detected: {path}")
        return {'FINISHED'}


class MAPUPD_OT_refresh_versions(Operator):
    """Fetch the list of CommunityDragon patch versions for the dropdowns."""
    bl_idname = "map_updater.refresh_versions"
    bl_label = "Refresh Patches"
    bl_description = "Download the list of available CommunityDragon patch channels"

    def execute(self, context):
        s = context.scene.map_updater_settings
        versions, err = _refresh_cdragon_versions()
        if err:
            s.versions_status = err
            self.report({'ERROR'}, f"Refresh failed: {err}")
            return {'CANCELLED'}
        s.versions_status = f"{len(versions)} patches loaded"
        self.report({'INFO'}, s.versions_status)
        return {'FINISHED'}


class MAPUPD_OT_refresh_variants(Operator):
    """Rescan the projects folder for map variants and refresh the dropdown."""
    bl_idname = "map_updater.refresh_variants"
    bl_label = "Refresh Variants"
    bl_description = "Rescan the projects folder for available map variants"

    def execute(self, context):
        s = context.scene.map_updater_settings
        root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
        if not root or not os.path.isdir(root):
            self.report({'WARNING'}, "Set a valid Projects Folder first")
            return {'CANCELLED'}
        n, err = _refresh_variant_items(root, s.new_channel or "latest")
        if err and n == 0:
            self.report({'ERROR'}, f"Variant lookup failed: {err}")
            return {'CANCELLED'}
        if err:
            self.report({'WARNING'}, f"Found {n} variant(s) ({err})")
        else:
            self.report({'INFO'}, f"Found {n} variant(s) on '{s.new_channel}'")
        return {'FINISHED'}


class MAPUPD_OT_clear(Operator):
    """Clear the diff results."""
    bl_idname = "map_updater.clear"
    bl_label = "Clear"

    def execute(self, context):
        s = context.scene.map_updater_settings
        s.projects.clear()
        s.entries.clear()
        s.last_status = ""
        _worker_state["result"] = None
        _worker_state["last_results"] = None
        return {'FINISHED'}


class MAPUPD_OT_open_path(Operator):
    """Reveal a project or backup path in the OS file browser."""
    bl_idname = "map_updater.open_path"
    bl_label = "Open Folder"

    path: StringProperty()

    def execute(self, context):
        target = bpy.path.abspath(self.path) if self.path else ""
        if not target or not os.path.exists(target):
            self.report({'ERROR'}, f"Not found: {target}")
            return {'CANCELLED'}
        try:
            if os.name == 'nt':
                os.startfile(target)  # noqa
            elif os.uname().sysname == 'Darwin':
                import subprocess
                subprocess.Popen(['open', target])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', target])
        except Exception as e:
            self.report({'ERROR'}, f"Open failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI list for entries
# ---------------------------------------------------------------------------

class MAPUPD_UL_entries(UIList):
    bl_idname = "MAPUPD_UL_entries"

    filter_change: EnumProperty(
        name="Change",
        items=[
            ('ALL', "All", "Show all"),
            ('added', "Added", "Show only added"),
            ('modified', "Modified", "Show only modified"),
            ('removed', "Removed", "Show only removed"),
        ],
        default='ALL',
    )
    filter_type: EnumProperty(
        name="Type",
        items=[
            ('ALL', "All", "Show every entry type"),
            ('material', "Materials", "Show only StaticMaterialDef entries"),
            ('other', "Other", "Show only non-material entries"),
        ],
        default='ALL',
    )

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        s = context.scene.map_updater_settings
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "apply", text="")
            icon_map = {'added': 'ADD', 'modified': 'FILE_REFRESH', 'removed': 'X'}
            row.label(text=item.change, icon=icon_map.get(item.change, 'DOT'))

            # Show project / file context
            if 0 <= item.project_idx < len(s.projects):
                proj = s.projects[item.project_idx]
                if 0 <= item.file_idx < len(proj.files):
                    pf = proj.files[item.file_idx]
                    row.label(text=f"{proj.name}/{pf.variant}", icon='OUTLINER_OB_GROUP_INSTANCE')
            row.label(text=item.label or "(unnamed)")
            if item.type_label:
                row.label(text=item.type_label)

    def draw_filter(self, context, layout):
        col = layout.column(align=True)
        col.prop(self, "filter_change", expand=True)
        col.prop(self, "filter_type", expand=True)

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_neworder = []
        flt_flags = [self.bitflag_filter_item] * len(items)
        for i, it in enumerate(items):
            if self.filter_change != 'ALL' and it.change != self.filter_change:
                flt_flags[i] = 0
                continue
            if self.filter_type == 'material' and not it.is_material:
                flt_flags[i] = 0
                continue
            if self.filter_type == 'other' and it.is_material:
                flt_flags[i] = 0
                continue
        return flt_flags, flt_neworder


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class VIEW3D_PT_map_auto_updater(Panel):
    bl_label = "Map Auto Updater"
    bl_idname = "VIEW3D_PT_map_auto_updater"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_parent_id = 'VIEW3D_PT_project_manager'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.map_updater_settings

        # ── Paths ────────────────────────────────────────────────
        paths_box = layout.box()
        paths_box.label(text="Paths", icon='FILE_FOLDER')
        gp_row = paths_box.row(align=True)
        gp_row.prop(s, "game_path")
        gp_row.operator("map_updater.detect_game_path", text="", icon='VIEWZOOM')
        paths_box.prop(s, "projects_root")

        # ── Patch channels ───────────────────────────────────────
        ch_box = layout.box()
        ch_box.label(text="Patch Diff", icon='RECOVER_LAST')
        if not _cdragon_versions_cache:
            warn = ch_box.row()
            warn.alert = True
            warn.label(text="Click 'Refresh Patches' to load version list",
                       icon='ERROR')
        crow = ch_box.row(align=True)
        crow.prop(s, "old_channel", text="From")
        crow.label(text="", icon='FORWARD')
        crow.prop(s, "new_channel", text="To")
        rrow = ch_box.row(align=True)
        rrow.operator("map_updater.refresh_versions", icon='FILE_REFRESH')
        if s.versions_status:
            rrow.label(text=s.versions_status)

        # Variant filter
        vrow = ch_box.row(align=True)
        vrow.prop(s, "variant_filter")
        vrow.operator("map_updater.refresh_variants", text="", icon='FILE_REFRESH')

        # ── Options ───────────────────────────────────────────────
        opt = layout.row(align=True)
        opt.prop(s, "preserve_textures", toggle=True)
        opt.prop(s, "show_preview", toggle=True)

        run_row = layout.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("map_updater.scan_and_diff", icon='ZOOM_ALL')
        run_row.operator("map_updater.clear", text="", icon='X')

        # ── Backup recovery ──────────────────────────────────────
        rec = layout.row(align=True)
        rec.operator("map_updater.recover_backup", icon='LOOP_BACK')

        if _worker_state.get("running"):
            box = layout.box()
            box.label(text=f"Working... {_worker_state.get('progress', '')}",
                      icon='SORTTIME')
        elif s.last_status:
            box = layout.box()
            box.label(text=s.last_status, icon='INFO')

        if not s.projects:
            return

        # Per-project summary
        proj_box = layout.box()
        proj_box.label(text="Projects", icon='OUTLINER_COLLECTION')
        for pi, p in enumerate(s.projects):
            row = proj_box.row(align=True)
            row.label(text=f"{p.name}  ({p.map_name})", icon='FILE_FOLDER')
            tot_a = sum(f.added_count for f in p.files)
            tot_m = sum(f.modified_count for f in p.files)
            tot_r = sum(f.removed_count for f in p.files)
            row.label(text=f"+{tot_a} ~{tot_m} -{tot_r}")
            op = row.operator("map_updater.open_path", text="", icon='FILE_FOLDER')
            op.path = p.path
            for f in p.files:
                if f.status != "ok":
                    sub = proj_box.row()
                    sub.label(text=f"  {f.variant}: {f.status} {f.error}",
                              icon='ERROR')

        # Bulk actions
        bulk = layout.box()
        bulk.label(text="Selection", icon='CHECKBOX_HLT')
        r1 = bulk.row(align=True)
        op = r1.operator("map_updater.set_apply_all", text="All ON")
        op.value = True; op.only_change = ""; op.only_type = ""
        op = r1.operator("map_updater.set_apply_all", text="All OFF")
        op.value = False; op.only_change = ""; op.only_type = ""
        r2 = bulk.row(align=True)
        op = r2.operator("map_updater.set_apply_all", text="Added ON")
        op.value = True; op.only_change = "added"; op.only_type = ""
        op = r2.operator("map_updater.set_apply_all", text="Modified ON")
        op.value = True; op.only_change = "modified"; op.only_type = ""
        op = r2.operator("map_updater.set_apply_all", text="Removed OFF")
        op.value = False; op.only_change = "removed"; op.only_type = ""

        # Type-based bulk toggles
        r3 = bulk.row(align=True)
        r3.label(text="By type:")
        op = r3.operator("map_updater.set_apply_all", text="Materials ON")
        op.value = True; op.only_change = ""; op.only_type = "material"
        op = r3.operator("map_updater.set_apply_all", text="Materials OFF")
        op.value = False; op.only_change = ""; op.only_type = "material"
        r4 = bulk.row(align=True)
        op = r4.operator("map_updater.set_apply_all", text="Other ON")
        op.value = True; op.only_change = ""; op.only_type = "other"
        op = r4.operator("map_updater.set_apply_all", text="Other OFF")
        op.value = False; op.only_change = ""; op.only_type = "other"

        # Entries list
        layout.label(text=f"Changes ({len(s.entries)})", icon='PRESET')
        layout.template_list(
            "MAPUPD_UL_entries", "",
            s, "entries",
            s, "active_entry_index",
            rows=10,
        )

        # Optional preview text for currently-selected row
        if s.show_preview and s.entries:
            # Show preview of first applied entry as a hint
            for e in s.entries:
                if e.apply and e.preview:
                    pv = layout.box()
                    pv.label(text=f"Preview: {e.label}", icon='ZOOM_IN')
                    for line in e.preview.splitlines()[:8]:
                        pv.label(text=line)
                    break

        apply_row = layout.row(align=True)
        apply_row.scale_y = 1.4
        op = apply_row.operator("map_updater.apply",
                                text="Backup & Apply Selected",
                                icon='CHECKMARK')
        op.dry_run = False
        op = apply_row.operator("map_updater.apply",
                                text="Dry Run",
                                icon='HIDE_OFF')
        op.dry_run = True


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    MapUpdaterEntry,
    MapUpdaterFile,
    MapUpdaterProject,
    MapUpdaterSettings,
    MAPUPD_OT_scan_and_diff,
    MAPUPD_OT_set_apply_all,
    MAPUPD_OT_apply,
    MAPUPD_OT_detect_game_path,
    MAPUPD_OT_refresh_versions,
    MAPUPD_OT_refresh_variants,
    MAPUPD_OT_recover_backup,
    MAPUPD_OT_clear,
    MAPUPD_OT_open_path,
    MAPUPD_UL_entries,
    VIEW3D_PT_map_auto_updater,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.map_updater_settings = PointerProperty(type=MapUpdaterSettings)

    # Best-effort: prefill the LoL Game path on first scene access
    def _autofill():
        try:
            scene = bpy.context.scene
            if scene and hasattr(scene, "map_updater_settings"):
                s = scene.map_updater_settings
                if not s.game_path:
                    detected = _detect_lol_game_path()
                    if detected:
                        s.game_path = detected
                # If projects_root was loaded from a saved blend, populate
                # the variant dropdown right away.
                root = bpy.path.abspath(s.projects_root) if s.projects_root else ""
                if root and os.path.isdir(root):
                    _refresh_variant_items(root, s.new_channel or "latest")
        except Exception:
            pass
        return None
    try:
        bpy.app.timers.register(_autofill, first_interval=1.0)
    except Exception:
        pass

    # Best-effort: warm the cdragon version cache in the background so the
    # 'From' / 'To' dropdowns aren't empty on first open.
    def _warm_versions():
        try:
            versions, err = _refresh_cdragon_versions()
            if not err:
                print(f"[MapAutoUpdater] Loaded {len(versions)} cdragon patches")
            else:
                print(f"[MapAutoUpdater] Could not pre-load patches: {err}")
        except Exception as e:
            print(f"[MapAutoUpdater] Patch warm-up failed: {e}")
    try:
        threading.Thread(target=_warm_versions, daemon=True).start()
    except Exception:
        pass

    print("[MapAutoUpdater] Registered")


def unregister():
    if hasattr(bpy.types.Scene, "map_updater_settings"):
        del bpy.types.Scene.map_updater_settings
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    print("[MapAutoUpdater] Unregistered")
