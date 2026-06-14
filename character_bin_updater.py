"""Character Bin Updater – apply CDragon patch diffs to project character bins.

Scans {ProjectFolder}/Map*/data/characters/**/*.bin, downloads the same files
from CommunityDragon for old and new patch versions, creates per-file diffs,
and applies them to the local project files (with automatic backups).
"""

from __future__ import annotations

import glob
import json as _json
import os
import shutil
from datetime import datetime
from urllib import error as _urllib_error, request

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import propertybin_parser
from . import wad_tool as _wt
from .map_patcher import (
    _CDRAGON_BASE,
    _DIFF_FORMAT,
    _USER_AGENT,
    _apply_diff_to_entries,
    _build_patch_chain,
    _count_applied_modified_entries,
    _create_diff,
    _fetch_cdragon_versions,
    _get_download_dir,
    _load_bin_entries,
    _resolve_channel,
)


# ---------------------------------------------------------------------------
# hashed_bins.json helpers — stores files whose CDragon paths exceed the
# NTFS 255-char filename or 260-char MAX_PATH limits.
# Format: { "a1b2c3d4e5f60718.bin": "data/characters/turret/very_long_name.bin" }
# ---------------------------------------------------------------------------

_NTFS_MAX_FILENAME = 255
_WIN_MAX_PATH = 260


def _hashed_bins_path(map_root: str) -> str:
    return os.path.join(map_root, "hashed_bins.json")


def _load_hashed_bins(map_root: str) -> dict:
    """Load hashed_bins.json from map_root.  Returns {} if missing or invalid."""
    try:
        with open(_hashed_bins_path(map_root), "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save_hashed_bins(map_root: str, data: dict) -> None:
    """Write hashed_bins.json to map_root (pretty-printed, sorted by key)."""
    with open(_hashed_bins_path(map_root), "w", encoding="utf-8") as f:
        _json.dump(dict(sorted(data.items())), f, indent=4)


# ---------------------------------------------------------------------------
# CDragon character bin helpers
# ---------------------------------------------------------------------------

def _build_char_bin_url(channel: str, rel_path: str) -> str:
    """Build a CommunityDragon URL for a character bin.

    rel_path is relative to ``data/characters/``, e.g. ``kindred/kindred.bin``.
    """
    channel = (channel or "latest").strip().strip("/")
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    return f"{_CDRAGON_BASE}/{channel}/game/data/characters/{rel_path}"


def _get_char_download_dir() -> str:
    d = os.path.join(
        bpy.utils.resource_path("USER"), "mapgeo_addon", "char_bin_updater"
    )
    os.makedirs(d, exist_ok=True)
    return d


def _download_char_bin(channel: str, rel_path: str) -> str:
    """Download a character bin from CommunityDragon. Returns local file path."""
    url = _build_char_bin_url(channel, rel_path)
    safe_ch = channel.replace("/", "_").replace("\\", "_")
    out_dir = os.path.join(
        _get_char_download_dir(),
        safe_ch,
        os.path.dirname(rel_path.replace("\\", "/")),
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, os.path.basename(rel_path))

    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _scan_character_bins(project_folder: str) -> list[dict]:
    """Return all .bin files under ``{project_folder}/Map*/data/characters``."""
    results = []
    if not project_folder or not os.path.isdir(project_folder):
        return results

    pattern = os.path.join(project_folder, "Map*", "data", "characters", "**", "*.bin")
    for full_path in glob.glob(pattern, recursive=True):
        norm = full_path.replace("\\", "/")
        marker = "/data/characters/"
        idx = norm.lower().find(marker)
        if idx == -1:
            continue
        rel = norm[idx + len(marker):]  # e.g. "kindred/kindred.bin"
        results.append({
            "full_path": full_path,
            "rel_path": rel,
            "name": os.path.basename(full_path),
        })

    results.sort(key=lambda x: x["rel_path"].lower())
    return results


# ---------------------------------------------------------------------------
# PropertyGroups
# ---------------------------------------------------------------------------

class CharBinItem(PropertyGroup):
    """One character bin file entry in the project."""
    name: StringProperty(name="Name", default="")
    rel_path: StringProperty(name="Relative Path", default="")
    full_path: StringProperty(name="Full Path", default="")
    selected: BoolProperty(name="Update", default=True)
    status: StringProperty(name="Status", default="")


class CharBinUpdaterSettings(PropertyGroup):
    project_folder: StringProperty(
        name="Project Folder",
        description="Root folder of the project (contains Map* subfolders)",
        default="",
        subtype="DIR_PATH",
    )
    old_channel: StringProperty(
        name="Old Patch",
        description="CommunityDragon channel for old patch (e.g. 16.3)",
        default="16.3",
    )
    new_channel: StringProperty(
        name="New Patch",
        description="CommunityDragon channel for new patch (e.g. latest)",
        default="latest",
    )
    status_text: StringProperty(name="Status", default="")
    active_item_index: IntProperty(name="Active Item", default=0)


# ---------------------------------------------------------------------------
# UIList
# ---------------------------------------------------------------------------

class CHARBIN_UL_file_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="")
        sub = row.row()
        sub.label(text=item.rel_path or item.name, icon="FILE_BLANK")
        if item.status:
            row.label(text=item.status)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class CHARBIN_OT_pick_project_folder(Operator):
    """Browse for the project root folder"""
    bl_idname = "charbin.pick_project_folder"
    bl_label = "Pick Project Folder"

    filepath: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.char_bin_updater_settings.project_folder = self.filepath
        return {"FINISHED"}


class CHARBIN_OT_scan(Operator):
    """Scan the project folder for character .bin files"""
    bl_idname = "charbin.scan"
    bl_label = "Scan Project"
    bl_description = (
        "Scan {ProjectFolder}/Map*/data/characters for .bin files "
        "and populate the list below"
    )

    def execute(self, context):
        settings = context.scene.char_bin_updater_settings
        folder = bpy.path.abspath(settings.project_folder)

        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Project folder not set or not found")
            return {"CANCELLED"}

        items = context.scene.char_bin_items
        items.clear()
        settings.status_text = ""

        bins = _scan_character_bins(folder)
        for b in bins:
            item = items.add()
            item.name = b["name"]
            item.rel_path = b["rel_path"]
            item.full_path = b["full_path"]
            item.selected = True
            item.status = ""

        if bins:
            self.report({"INFO"}, f"Found {len(bins)} character bin file(s)")
        else:
            self.report({"WARNING"}, "No character bin files found in Map*/data/characters")
        return {"FINISHED"}


class CHARBIN_OT_select_all(Operator):
    """Select all character bin files"""
    bl_idname = "charbin.select_all"
    bl_label = "Select All"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        for item in context.scene.char_bin_items:
            item.selected = True
        return {"FINISHED"}


class CHARBIN_OT_select_none(Operator):
    """Deselect all character bin files"""
    bl_idname = "charbin.select_none"
    bl_label = "Select None"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        for item in context.scene.char_bin_items:
            item.selected = False
        return {"FINISHED"}


class CHARBIN_OT_update(Operator):
    """Download CDragon bins, diff, and apply to selected project character bins"""
    bl_idname = "charbin.update"
    bl_label = "Update Selected Bins"
    bl_description = (
        "For each selected character bin: download old + new patch versions "
        "from CommunityDragon, create a diff, and apply it to the local project "
        "file (a .bak backup is created automatically)"
    )

    def execute(self, context):
        settings = context.scene.char_bin_updater_settings
        items = context.scene.char_bin_items

        selected = [item for item in items if item.selected]
        if not selected:
            self.report({"ERROR"}, "No character bin files selected")
            return {"CANCELLED"}

        old_ch = settings.old_channel.strip()
        new_ch = settings.new_channel.strip()
        if not old_ch or not new_ch:
            self.report({"ERROR"}, "Old Patch and New Patch must be set")
            return {"CANCELLED"}

        # Resolve patch channels (e.g. "latest" → "16.5")
        settings.status_text = "Fetching CommunityDragon version list..."
        try:
            all_versions = _fetch_cdragon_versions()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to fetch CDragon versions: {e}")
            settings.status_text = f"Error: {e}"
            return {"CANCELLED"}

        old_resolved = _resolve_channel(old_ch, all_versions)
        new_resolved = _resolve_channel(new_ch, all_versions)

        total = len(selected)
        updated = 0
        skipped = 0
        failed = 0

        wm = context.window_manager
        wm.progress_begin(0, total)

        try:
            for i, item in enumerate(selected):
                rel = item.rel_path
                local_path = item.full_path

                settings.status_text = f"[{i+1}/{total}] {item.name}..."
                wm.progress_update(i)

                if not os.path.isfile(local_path):
                    item.status = "Not found"
                    failed += 1
                    print(f"[CharBinUpdater] Local file not found: {local_path}")
                    continue

                # --- Download old version from CDragon ---
                try:
                    old_path = _download_char_bin(old_resolved, rel)
                except Exception as e:
                    item.status = "DL old failed"
                    failed += 1
                    print(f"[CharBinUpdater] Download old failed for {rel}: {e}")
                    continue

                # --- Download new version from CDragon ---
                try:
                    new_path = _download_char_bin(new_resolved, rel)
                except Exception as e:
                    item.status = "DL new failed"
                    failed += 1
                    print(f"[CharBinUpdater] Download new failed for {rel}: {e}")
                    continue

                # --- Build diff between CDragon old → new ---
                try:
                    old_entries = _load_bin_entries(old_path)
                    new_entries = _load_bin_entries(new_path)
                    diff = _create_diff(old_entries, new_entries)
                except Exception as e:
                    item.status = "Diff failed"
                    failed += 1
                    print(f"[CharBinUpdater] Diff failed for {rel}: {e}")
                    continue

                n_add = len(diff["added"])
                n_mod = len(diff["modified"])
                n_rem = len(diff["removed"])

                if n_add == 0 and n_mod == 0 and n_rem == 0:
                    item.status = "No changes"
                    skipped += 1
                    print(f"[CharBinUpdater] {rel}: no changes between patches")
                    continue

                # --- Apply diff to local project bin ---
                try:
                    local_data = propertybin_parser.parse_bin(local_path)
                    local_entries = list(local_data.get("entries", []))
                    new_local_entries = _apply_diff_to_entries(local_entries, diff)

                    backup_path = (
                        local_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                    )
                    shutil.copy2(local_path, backup_path)

                    local_data["entries"] = new_local_entries
                    local_data["entry_count"] = len(new_local_entries)
                    propertybin_parser.write_bin(local_data, local_path)

                    item.status = f"+{n_add} ~{n_mod} -{n_rem}"
                    updated += 1
                    print(f"[CharBinUpdater] {rel}: +{n_add} ~{n_mod} -{n_rem}")

                except Exception as e:
                    item.status = "Apply failed"
                    failed += 1
                    print(f"[CharBinUpdater] Apply failed for {rel}: {e}")

        finally:
            wm.progress_end()

        summary = (
            f"Done: {updated} updated, {skipped} unchanged, {failed} failed "
            f"({old_resolved} \u2192 {new_resolved})"
        )
        settings.status_text = summary
        self.report({"INFO"}, summary)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class VIEW3D_PT_char_bin_updater(Panel):
    """Character Bin Updater — update project character bins from CDragon diffs"""
    bl_label = "Character Bin Updater"
    bl_idname = "VIEW3D_PT_char_bin_updater"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "League Tools"
    bl_order = 95
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.char_bin_updater_settings
        items = context.scene.char_bin_items

        # --- Project Folder ---
        box = layout.box()
        box.label(text="Project Folder", icon="FILE_FOLDER")
        row = box.row(align=True)
        row.prop(settings, "project_folder", text="")
        row.operator("charbin.pick_project_folder", text="", icon="FILEBROWSER")
        info = box.box()
        info.scale_y = 0.7
        info.label(text="Scans: Map*/data/characters/**/*.bin", icon="INFO")
        box.operator("charbin.scan", text="Scan for Character Bins", icon="VIEWZOOM")

        # --- Patch Versions ---
        box = layout.box()
        box.label(text="CommunityDragon Patches", icon="URL")
        row = box.row(align=True)
        split = row.split(factor=0.5, align=True)
        split.prop(settings, "old_channel", text="Old")
        split.prop(settings, "new_channel", text="New")

        # --- File List ---
        box = layout.box()
        if items:
            box.label(
                text=f"Character Bins  ({len(items)} found)",
                icon="FILE_BLANK",
            )
            box.template_list(
                "CHARBIN_UL_file_list", "",
                context.scene, "char_bin_items",
                settings, "active_item_index",
                rows=6,
            )
            row = box.row(align=True)
            row.operator("charbin.select_all", text="All", icon="CHECKBOX_HLT")
            row.operator("charbin.select_none", text="None", icon="CHECKBOX_DEHLT")

            selected_count = sum(1 for item in items if item.selected)
            box.label(text=f"{selected_count} / {len(items)} selected", icon="INFO")
        else:
            info = box.column(align=True)
            info.scale_y = 0.8
            info.label(text="No files scanned yet", icon="INFO")
            info.label(text="Set a project folder and press Scan")

        # --- Update ---
        box = layout.box()
        box.label(text="Update Bins", icon="FILE_REFRESH")
        can_run = bool(items and any(item.selected for item in items))
        row = box.row()
        row.scale_y = 1.4
        row.enabled = can_run
        row.operator("charbin.update", text="Update Selected Bins", icon="PLAY")

        if settings.status_text:
            info = box.box()
            info.scale_y = 0.7
            for line in settings.status_text.split("\n"):
                info.label(text=line)


# ---------------------------------------------------------------------------
# Project-wide sequential bin patcher
# ---------------------------------------------------------------------------

# Subdirectory names that are never real game data (backups, old versions, etc.)
_SKIP_DIR_NAMES = frozenset({"old", "backup", "bak", "temp", "tmp", "archive"})


def _is_valid_project_bin(game_rel: str) -> bool:
    """Return True if this game-relative path looks like a real CDragon bin.

    Filters out:
    - Files inside backup/old subdirectories
    - Double-extension files  (e.g. ``.before-fix.bin``, ``.materials.bin``)
    - Hash-named files        (e.g. ``e00366c8733f0062.bin``)
    - Unreasonably long names (merged/concatenated skin files)
    """
    parts = game_rel.replace("\\", "/").lower().split("/")
    dir_parts = parts[:-1]
    if any(p in _SKIP_DIR_NAMES for p in dir_parts):
        return False
    stem = parts[-1][:-4]  # strip .bin
    if "." in stem:         # double extension
        return False
    if len(stem) == 16 and all(c in "0123456789abcdef" for c in stem):  # hash name
        return False
    if len(parts[-1]) > 120:  # unreasonably long filename
        return False
    return True


def _scan_all_project_bins(project_folder: str) -> list[dict]:
    """Return all .bin files under Map* subfolders of project_folder.

    The ``game_rel_path`` key holds the path relative to the Map* folder root,
    matching the CDragon game/ tree (e.g. ``data/characters/sru_baron/sru_baron.bin``).
    Junk files (backups, double-extension) are excluded.  Hash-named files that
    appear in hashed_bins.json are included under their original CDragon path.
    """
    results = []
    if not project_folder or not os.path.isdir(project_folder):
        return results

    for entry in os.listdir(project_folder):
        if not entry.lower().startswith("map"):
            continue
        map_root = os.path.join(project_folder, entry)
        if not os.path.isdir(map_root):
            continue
        map_root_norm = map_root.replace("\\", "/").rstrip("/") + "/"
        hashed = _load_hashed_bins(map_root)
        pattern = os.path.join(map_root, "**", "*.bin")
        for full_path in glob.glob(pattern, recursive=True):
            norm = full_path.replace("\\", "/")
            if not norm.startswith(map_root_norm):
                continue
            game_rel = norm[len(map_root_norm):]
            if not _is_valid_project_bin(game_rel):
                # Hash-named files at map_root level are stored via hashed_bins.json
                fname = os.path.basename(game_rel)
                stem = fname[:-4] if fname.endswith(".bin") else ""
                if (
                    len(stem) == 16
                    and all(c in "0123456789abcdef" for c in stem)
                    and fname in hashed
                ):
                    real_rel = hashed[fname]
                    results.append({
                        "full_path": full_path,
                        "game_rel_path": real_rel,
                        "name": os.path.basename(real_rel),
                    })
                continue
            results.append({
                "full_path": full_path,
                "game_rel_path": game_rel,
                "name": os.path.basename(full_path),
            })

    results.sort(key=lambda x: x["game_rel_path"].lower())
    return results


def _build_game_bin_url(channel: str, game_rel_path: str) -> str:
    channel = (channel or "latest").strip().strip("/")
    # CDragon paths are always lowercase
    game_rel_path = game_rel_path.replace("\\", "/").lstrip("/").lower()
    return f"{_CDRAGON_BASE}/{channel}/game/{game_rel_path}"


def _download_game_bin(channel: str, game_rel_path: str) -> str:
    """Download a game .bin from CommunityDragon. Returns local file path."""
    url = _build_game_bin_url(channel, game_rel_path)
    safe_ch = channel.replace("/", "_").replace("\\", "_")
    game_rel_path = game_rel_path.replace("\\", "/")
    out_dir = os.path.join(
        _get_char_download_dir(), "game_bins", safe_ch,
        os.path.dirname(game_rel_path),
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, os.path.basename(game_rel_path))

    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _find_file_in_project(map_root: str, lf_ref: str) -> str | None:
    """Locate a CDragon linked_files reference inside a project Map* folder.

    Walks each path component case-insensitively so platform/case differences
    (e.g. ``DATA`` vs ``data``) don't cause mismatches.  If the walk fails at
    any component (e.g. the file was already moved to a hash name), falls back
    to checking hashed_bins.json.
    Returns the absolute path if found, or None.
    """
    parts = lf_ref.replace("\\", "/").split("/")
    current: str | None = map_root
    for part in parts:
        try:
            dir_entries = os.listdir(current)
        except OSError:
            current = None
            break
        match = next((e for e in dir_entries if e.lower() == part.lower()), None)
        if match is None:
            current = None
            break
        current = os.path.join(current, match)
    if current is not None and os.path.isfile(current):
        return current

    # Fallback: check hashed_bins.json for files stored under a hash name
    lf_lower = lf_ref.replace("\\", "/").lower()
    for fname, orig in _load_hashed_bins(map_root).items():
        if orig.lower() == lf_lower:
            fp = os.path.join(map_root, fname)
            if os.path.isfile(fp):
                return fp
    return None


def _map_root_of(abs_path: str, project_folder: str) -> str | None:
    """Return the Map* subdirectory that contains abs_path, or None."""
    rel = os.path.relpath(abs_path, project_folder)
    first = rel.split(os.sep)[0]
    return os.path.join(project_folder, first) if first.lower().startswith("map") else None


# ---------------------------------------------------------------------------
# PropertyGroups – project patcher
# ---------------------------------------------------------------------------

class CharBinProjectItem(PropertyGroup):
    name: StringProperty(name="Name", default="")
    game_rel_path: StringProperty(name="CDragon Game Path", default="")
    full_path: StringProperty(name="Full Path", default="")
    selected: BoolProperty(name="Update", default=True)
    status: StringProperty(name="Status", default="")


class CharBinProjectSettings(PropertyGroup):
    project_folder: StringProperty(
        name="Project Folder",
        description="Root folder of the project (contains Map* subfolders)",
        default="",
        subtype="DIR_PATH",
    )
    old_channel: StringProperty(
        name="Old Patch",
        description="CommunityDragon channel for the old patch (e.g. 16.9)",
        default="16.9",
    )
    new_channel: StringProperty(
        name="New Patch",
        description="CommunityDragon channel for the new patch (e.g. latest)",
        default="latest",
    )
    apply_added: BoolProperty(
        name="Apply Added",
        description="Apply newly added entries from the diff",
        default=True,
    )
    apply_modified: BoolProperty(
        name="Apply Modified",
        description="Apply modified entries from the diff",
        default=True,
    )
    apply_removed: BoolProperty(
        name="Apply Removed",
        description="Remove entries listed as removed in the diff",
        default=True,
    )
    preserve_texture_paths: BoolProperty(
        name="Preserve Custom Textures (Prey)",
        description="Keep existing texture asset paths from the target file when applying modifications",
        default=False,
    )
    status_text: StringProperty(name="Status", default="")
    active_item_index: IntProperty(name="Active Item", default=0)


# ---------------------------------------------------------------------------
# UIList – project patcher
# ---------------------------------------------------------------------------

class CHARPROJ_UL_file_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="")
        sub = row.row()
        sub.label(text=item.game_rel_path or item.name, icon="FILE_BLANK")
        if item.status:
            row.label(text=item.status)


# ---------------------------------------------------------------------------
# Operators – project patcher
# ---------------------------------------------------------------------------

class CHARPROJ_OT_pick_folder(Operator):
    """Browse for the project root folder"""
    bl_idname = "charproj.pick_folder"
    bl_label = "Pick Project Folder"

    filepath: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.char_bin_project_settings.project_folder = self.filepath
        return {"FINISHED"}


class CHARPROJ_OT_scan(Operator):
    """Scan the project for all .bin files"""
    bl_idname = "charproj.scan"
    bl_label = "Scan Project"
    bl_description = "Scan all Map* subfolders for .bin files and populate the list"

    def execute(self, context):
        settings = context.scene.char_bin_project_settings
        folder = bpy.path.abspath(settings.project_folder)

        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Project folder not set or not found")
            return {"CANCELLED"}

        items = context.scene.char_bin_project_items
        items.clear()
        settings.status_text = ""

        bins = _scan_all_project_bins(folder)
        for b in bins:
            item = items.add()
            item.name = b["name"]
            item.game_rel_path = b["game_rel_path"]
            item.full_path = b["full_path"]
            item.selected = True
            item.status = ""

        if bins:
            self.report({"INFO"}, f"Found {len(bins)} .bin file(s)")
        else:
            self.report({"WARNING"}, "No .bin files found in Map* subfolders")
        return {"FINISHED"}


class CHARPROJ_OT_select_all(Operator):
    bl_idname = "charproj.select_all"
    bl_label = "Select All"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        for item in context.scene.char_bin_project_items:
            item.selected = True
        return {"FINISHED"}


class CHARPROJ_OT_select_none(Operator):
    bl_idname = "charproj.select_none"
    bl_label = "Select None"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        for item in context.scene.char_bin_project_items:
            item.selected = False
        return {"FINISHED"}


class CHARPROJ_OT_patch_all(Operator):
    """Download every intermediate CDragon version and apply sequential diffs to each selected bin"""
    bl_idname = "charproj.patch_all"
    bl_label = "Patch All Selected"
    bl_description = (
        "For each selected .bin: downloads all intermediate CDragon versions "
        "between Old and New, then applies each diff step-by-step"
    )

    def execute(self, context):
        import json as _json

        settings = context.scene.char_bin_project_settings
        items = context.scene.char_bin_project_items

        selected = [item for item in items if item.selected]
        if not selected:
            self.report({"ERROR"}, "No files selected")
            return {"CANCELLED"}

        old_ch = settings.old_channel.strip()
        new_ch = settings.new_channel.strip()
        if not old_ch or not new_ch:
            self.report({"ERROR"}, "Old Patch and New Patch must be set")
            return {"CANCELLED"}

        options = {
            "apply_added": bool(settings.apply_added),
            "apply_modified": bool(settings.apply_modified),
            "apply_removed": bool(settings.apply_removed),
            "preserve_texture_paths": bool(settings.preserve_texture_paths),
        }

        # 1. Fetch versions
        settings.status_text = "Fetching CDragon version list..."
        try:
            all_versions = _fetch_cdragon_versions()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to fetch CDragon versions: {e}")
            settings.status_text = f"Error: {e}"
            return {"CANCELLED"}

        # 2. Build patch chain (shared for all files)
        chain = _build_patch_chain(old_ch, new_ch, all_versions)
        if len(chain) < 2:
            self.report({"ERROR"}, f"No patches found between {old_ch} and {new_ch}")
            settings.status_text = ""
            return {"CANCELLED"}

        total_steps = len(chain) - 1
        total_files = len(selected)
        chain_str = " \u2192 ".join(chain)
        print(f"[CharProj] Chain: {chain_str} ({total_steps} steps, {total_files} files)")

        wm = context.window_manager
        wm.progress_begin(0, total_files)
        total_updated = total_skipped = total_failed = 0

        try:
            for file_idx, item in enumerate(selected):
                game_rel = item.game_rel_path.replace("\\", "/")
                local_path = item.full_path
                bin_name = os.path.basename(game_rel)
                # Map* root — used when repathing linked bin files in the project.
                # Hash-named files live directly in map_root, so we can't use the
                # game_rel depth to count up — detect them and use dirname directly.
                _loc_stem = os.path.basename(local_path)
                _loc_stem = _loc_stem[:-4] if _loc_stem.endswith(".bin") else _loc_stem
                if len(_loc_stem) == 16 and all(c in "0123456789abcdef" for c in _loc_stem):
                    map_root = os.path.dirname(local_path)
                else:
                    map_root = local_path
                    for _ in game_rel.split("/"):
                        map_root = os.path.dirname(map_root)

                wm.progress_update(file_idx)
                settings.status_text = f"[{file_idx+1}/{total_files}] {bin_name}..."
                item.status = "Working..."

                if not os.path.isfile(local_path):
                    # A hash-named file that no longer exists has likely been repathed
                    # to a real path during this same run.  Treat as skipped, not failed.
                    _loc_fname = os.path.basename(local_path)
                    _loc_stem2 = _loc_fname[:-4] if _loc_fname.endswith(".bin") else ""
                    if (
                        len(_loc_stem2) == 16
                        and all(c in "0123456789abcdef" for c in _loc_stem2)
                        and _loc_fname not in _load_hashed_bins(map_root)
                    ):
                        item.status = "Repathed"
                        total_skipped += 1
                        print(f"[CharProj] Hash file was repathed elsewhere this run, skipping: {_loc_fname}")
                    else:
                        item.status = "Not found"
                        total_failed += 1
                        print(f"[CharProj] Local file not found: {local_path}")
                    continue

                # Download all versions in the chain for this bin
                downloaded = {}
                dl_failed = False
                not_on_cdragon = False
                for i, ver in enumerate(chain):
                    settings.status_text = (
                        f"[{file_idx+1}/{total_files}] {bin_name}: "
                        f"downloading {ver} ({i+1}/{len(chain)})..."
                    )
                    try:
                        path = _download_game_bin(ver, game_rel)
                        downloaded[ver] = path
                    except _urllib_error.HTTPError as e:
                        if e.code == 404:
                            item.status = "Not on CDragon"
                            total_skipped += 1
                            print(f"[CharProj] Not on CDragon: {game_rel}")
                            not_on_cdragon = True
                        else:
                            item.status = f"HTTP {e.code}"
                            total_failed += 1
                            print(f"[CharProj] HTTP {e.code} for {ver}/{game_rel}: {e}")
                            dl_failed = True
                        break
                    except Exception as e:
                        item.status = f"DL {ver} failed"
                        total_failed += 1
                        print(f"[CharProj] Download failed {ver}/{game_rel}: {e}")
                        dl_failed = True
                        break

                if dl_failed or not_on_cdragon:
                    continue

                # Backup once before patching
                backup_path = local_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(local_path, backup_path)

                # Apply sequential diffs
                data = propertybin_parser.parse_bin(local_path)
                entries = list(data.get("entries", []))
                file_added = file_modified = file_removed = 0

                diff_dir = os.path.join(
                    _get_char_download_dir(), "diffs",
                    os.path.dirname(game_rel),
                )
                os.makedirs(diff_dir, exist_ok=True)

                apply_failed = False
                file_lf_updated = False
                for step in range(total_steps):
                    ver_a = chain[step]
                    ver_b = chain[step + 1]
                    settings.status_text = (
                        f"[{file_idx+1}/{total_files}] {bin_name}: "
                        f"diff {ver_a}\u2192{ver_b} (step {step+1}/{total_steps})"
                    )

                    try:
                        cdr_a = propertybin_parser.parse_bin(downloaded[ver_a])
                        cdr_b = propertybin_parser.parse_bin(downloaded[ver_b])
                        diff = _create_diff(
                            list(cdr_a.get("entries", [])),
                            list(cdr_b.get("entries", [])),
                        )
                        lf_a = cdr_a.get("linked_files", [])
                        lf_b = cdr_b.get("linked_files", [])
                        lf_step_changed = lf_a != lf_b
                    except Exception as e:
                        item.status = "Diff failed"
                        total_failed += 1
                        print(f"[CharProj] Diff failed {game_rel} {ver_a}\u2192{ver_b}: {e}")
                        apply_failed = True
                        break

                    n_add_raw = len(diff["added"])
                    n_mod_raw = len(diff["modified"])
                    n_rem_raw = len(diff["removed"])
                    has_entry_changes = bool(n_add_raw or n_mod_raw or n_rem_raw)

                    if not has_entry_changes and not lf_step_changed:
                        continue

                    n_add = n_add_raw if options.get("apply_added") else 0
                    n_mod = _count_applied_modified_entries(diff, options)
                    n_rem = n_rem_raw if options.get("apply_removed") else 0

                    if has_entry_changes:
                        diff_data = {
                            "format": _DIFF_FORMAT,
                            "created_at": datetime.utcnow().isoformat() + "Z",
                            "old_channel": ver_a,
                            "new_channel": ver_b,
                            "from_file": f"{ver_a}.{bin_name}",
                            "to_file": f"{ver_b}.{bin_name}",
                            **diff,
                        }
                        diff_fp = os.path.join(diff_dir, f"{ver_a}_to_{ver_b}.char_patch.json")
                        with open(diff_fp, "w", encoding="utf-8") as jf:
                            _json.dump(diff_data, jf, indent=2, ensure_ascii=True)

                        entries = _apply_diff_to_entries(entries, diff, options=options)
                        file_added += n_add
                        file_modified += n_mod
                        file_removed += n_rem
                        print(
                            f"[CharProj] {bin_name} {ver_a}\u2192{ver_b}: "
                            f"+{n_add} ~{n_mod} -{n_rem}"
                        )

                    if lf_step_changed:
                        data["linked_files"] = list(lf_b)
                        file_lf_updated = True
                        print(
                            f"[CharProj] {bin_name} {ver_a}\u2192{ver_b}: "
                            f"linked_files {len(lf_a)}\u2192{len(lf_b)}: "
                            + str(lf_b)
                        )
                        # Repath any project files whose CDragon path changed
                        for old_ref, new_ref in zip(lf_a, lf_b):
                            if old_ref.lower() == new_ref.lower():
                                continue
                            old_file = _find_file_in_project(map_root, old_ref)
                            if not old_file:
                                print(f"[CharProj] Repath: not in project, skipping: {old_ref}")
                                continue
                            new_ref_norm = new_ref.replace("\\", "/").lower()
                            new_file = os.path.normpath(
                                os.path.join(map_root, new_ref.replace("/", os.sep))
                            )
                            new_fname = os.path.basename(new_file)
                            if len(new_fname) > _NTFS_MAX_FILENAME or len(new_file) >= _WIN_MAX_PATH:
                                # Path too long for NTFS/MAX_PATH — store as hashed bin
                                hash_fname = f"{_wt.xxhash64_path(new_ref_norm):016x}.bin"
                                hashed_path = os.path.join(map_root, hash_fname)
                                hashed = _load_hashed_bins(map_root)
                                hash_done = hash_fname in hashed
                                hash_exists = os.path.isfile(hashed_path)
                                src_still_exists = old_file != hashed_path and os.path.isfile(old_file)
                                if hash_done and hash_exists:
                                    # Fully done — clean up stale source left by a previous partial run
                                    if src_still_exists:
                                        try:
                                            os.remove(old_file)
                                            print(f"[CharProj] Repath: removed stale source: {old_ref}")
                                        except OSError as _e:
                                            print(f"[CharProj] Repath: could not remove stale source ({_e}): {old_ref}")
                                    else:
                                        print(f"[CharProj] Repath: already hashed as {hash_fname}: {new_ref}")
                                    continue
                                if hash_exists and not hash_done:
                                    # Hash file exists but JSON not updated (crashed after copy, before save)
                                    hashed[hash_fname] = new_ref_norm
                                    _save_hashed_bins(map_root, hashed)
                                    if src_still_exists:
                                        try:
                                            os.remove(old_file)
                                        except OSError:
                                            pass
                                    print(f"[CharProj] Repath (recovered hashed): {old_ref} \u2192 {hash_fname}")
                                    continue
                                # Normal path: move old file to hash name
                                try:
                                    shutil.move(old_file, hashed_path)
                                except Exception as _e:
                                    print(f"[CharProj] Repath move failed {old_ref} \u2192 {hash_fname}: {_e}")
                                    continue
                                # If old_file was itself a hash-named file, remove its stale entry
                                old_fname = os.path.basename(old_file)
                                old_stem = old_fname[:-4] if old_fname.endswith(".bin") else ""
                                if (
                                    len(old_stem) == 16
                                    and all(c in "0123456789abcdef" for c in old_stem)
                                    and old_fname in hashed
                                ):
                                    del hashed[old_fname]
                                hashed[hash_fname] = new_ref_norm
                                _save_hashed_bins(map_root, hashed)
                                print(f"[CharProj] Repath (hashed): {old_ref} \u2192 {hash_fname}")
                            else:
                                if os.path.isfile(new_file):
                                    # Already at the right place — clean up any stale source
                                    if old_file != new_file and os.path.isfile(old_file):
                                        try:
                                            os.remove(old_file)
                                            print(f"[CharProj] Repath: removed stale source: {old_ref}")
                                        except OSError:
                                            pass
                                    else:
                                        print(f"[CharProj] Repath: already at new path: {new_ref}")
                                    continue
                                try:
                                    os.makedirs(os.path.dirname(new_file), exist_ok=True)
                                    shutil.move(old_file, new_file)
                                    # If old_file was a hash-named file, remove its stale JSON entry
                                    old_fname = os.path.basename(old_file)
                                    old_stem = old_fname[:-4] if old_fname.endswith(".bin") else ""
                                    if len(old_stem) == 16 and all(c in "0123456789abcdef" for c in old_stem):
                                        _hb = _load_hashed_bins(map_root)
                                        if old_fname in _hb:
                                            del _hb[old_fname]
                                            _save_hashed_bins(map_root, _hb)
                                    print(f"[CharProj] Repaths: {old_ref} \u2192 {new_ref}")
                                except Exception as _e:
                                    print(f"[CharProj] Repath move failed {old_ref} \u2192 {new_ref}: {_e}")

                if apply_failed:
                    continue

                data["entries"] = entries
                data["entry_count"] = len(entries)
                try:
                    propertybin_parser.write_bin(data, local_path)
                except Exception as e:
                    item.status = "Write failed"
                    total_failed += 1
                    print(f"[CharProj] Write failed for {local_path}: {e}")
                    continue

                no_changes = (
                    file_added == 0
                    and file_modified == 0
                    and file_removed == 0
                    and not file_lf_updated
                )
                if no_changes:
                    item.status = "No changes"
                    total_skipped += 1
                else:
                    lf_suffix = " +lf" if file_lf_updated else ""
                    item.status = f"+{file_added} ~{file_modified} -{file_removed}{lf_suffix}"
                    total_updated += 1

        finally:
            wm.progress_end()

        summary = (
            f"Done: {total_updated} updated, {total_skipped} unchanged, "
            f"{total_failed} failed  ({chain[0]} \u2192 {chain[-1]})"
        )
        settings.status_text = summary
        self.report({"INFO"}, summary)
        print(f"[CharProj] {summary}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel – project patcher
# ---------------------------------------------------------------------------


class CHARPROJ_OT_restore_backups(Operator):
    """Restore project bins from their .bak_ backups and reverse linked-file moves"""
    bl_idname = "charproj.restore_backups"
    bl_label = "Restore Backups"
    bl_description = (
        "Find the most recent .bak_ backup for every patched .bin in the project, "
        "restore it, and reverse any linked-file renames/moves"
    )

    def execute(self, context):
        import re as _re

        settings = context.scene.char_bin_project_settings
        folder = bpy.path.abspath(settings.project_folder)
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Project folder not set or not found")
            return {"CANCELLED"}

        # Walk the project tree and collect .bin.bak_YYYYMMDD_HHMMSS files
        bak_re = _re.compile(r"^(.+\.bin)\.bak_(\d{8}_\d{6})$")
        backup_map: dict[str, list[tuple[str, str]]] = {}  # orig_path -> [(timestamp, bak_path)]
        for dirpath, _dirs, files in os.walk(folder):
            for fname in files:
                m = bak_re.match(fname)
                if not m:
                    continue
                orig_name, ts = m.group(1), m.group(2)
                orig_full = os.path.join(dirpath, orig_name)
                bak_full = os.path.join(dirpath, fname)
                backup_map.setdefault(orig_full, []).append((ts, bak_full))

        if not backup_map:
            self.report({"WARNING"}, "No .bak_ files found in project")
            return {"CANCELLED"}

        restored = 0
        lf_reverted = 0
        failed = 0

        for orig_path, bak_list in backup_map.items():
            # Use the most recent backup (highest timestamp string)
            bak_list.sort(key=lambda x: x[0], reverse=True)
            _, bak_path = bak_list[0]

            map_root = _map_root_of(orig_path, folder)

            try:
                # Read current bin's linked_files BEFORE overwriting it
                current_lf: list[str] = []
                backup_lf: list[str] = []
                if os.path.isfile(orig_path):
                    try:
                        current_lf = propertybin_parser.parse_bin(orig_path).get("linked_files", [])
                    except Exception:
                        pass
                try:
                    backup_lf = propertybin_parser.parse_bin(bak_path).get("linked_files", [])
                except Exception:
                    pass

                # Restore the bin from its backup
                shutil.copy2(bak_path, orig_path)
                restored += 1
                print(f"[CharProj] Restored: {os.path.basename(orig_path)}")

                # Reverse any linked-file moves (new_ref -> old_ref)
                if map_root and current_lf != backup_lf:
                    for new_ref, old_ref in zip(current_lf, backup_lf):
                        if new_ref.lower() == old_ref.lower():
                            continue
                        moved_file = _find_file_in_project(map_root, new_ref)
                        if not moved_file:
                            print(f"[CharProj] Reverse repath: not found in project: {new_ref}")
                            continue
                        old_file = os.path.normpath(
                            os.path.join(map_root, old_ref.replace("/", os.sep))
                        )
                        if os.path.isfile(old_file):
                            print(f"[CharProj] Reverse repath: already at old path: {old_ref}")
                            continue
                        os.makedirs(os.path.dirname(old_file), exist_ok=True)
                        shutil.move(moved_file, old_file)
                        lf_reverted += 1
                        print(f"[CharProj] Reverse repath: {new_ref} \u2192 {old_ref}")

            except Exception as e:
                failed += 1
                print(f"[CharProj] Restore failed for {orig_path}: {e}")

        parts = [f"Restored {restored} bin(s)"]
        if lf_reverted:
            parts.append(f"reverted {lf_reverted} linked file(s)")
        if failed:
            parts.append(f"{failed} failed")
        summary = ", ".join(parts)
        settings.status_text = summary
        self.report({"INFO"}, summary)
        return {"FINISHED"}


class VIEW3D_PT_charbin_project(Panel):
    """Project-wide sequential bin patcher"""
    bl_label = "Character Bin Patcher"
    bl_idname = "VIEW3D_PT_charbin_project"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "League Tools"
    bl_order = 96
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.char_bin_project_settings
        items = context.scene.char_bin_project_items

        # Project folder
        box = layout.box()
        box.label(text="Project Folder", icon="FILE_FOLDER")
        row = box.row(align=True)
        row.prop(settings, "project_folder", text="")
        row.operator("charproj.pick_folder", text="", icon="FILEBROWSER")
        hint = box.box()
        hint.scale_y = 0.7
        hint.label(text="Scans all .bin in Map* subfolders", icon="INFO")
        box.operator("charproj.scan", text="Scan for Bin Files", icon="VIEWZOOM")

        # Channels
        box = layout.box()
        box.label(text="CommunityDragon Channels", icon="URL")
        row = box.row(align=True)
        split = row.split(factor=0.5, align=True)
        split.prop(settings, "old_channel", text="Old")
        split.prop(settings, "new_channel", text="New")

        # File list
        box = layout.box()
        if items:
            box.label(text=f"Bin Files  ({len(items)} found)", icon="FILE_BLANK")
            box.template_list(
                "CHARPROJ_UL_file_list", "",
                context.scene, "char_bin_project_items",
                settings, "active_item_index",
                rows=6,
            )
            row = box.row(align=True)
            row.operator("charproj.select_all", text="All", icon="CHECKBOX_HLT")
            row.operator("charproj.select_none", text="None", icon="CHECKBOX_DEHLT")
            selected_count = sum(1 for item in items if item.selected)
            box.label(text=f"{selected_count} / {len(items)} selected", icon="INFO")
        else:
            col = box.column(align=True)
            col.scale_y = 0.8
            col.label(text="No files scanned yet", icon="INFO")
            col.label(text="Set a project folder and press Scan")

        # Options
        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")
        row = box.row(align=True)
        row.prop(settings, "apply_added")
        row.prop(settings, "apply_modified")
        row.prop(settings, "apply_removed")
        box.prop(settings, "preserve_texture_paths")

        # Action
        box = layout.box()
        box.label(text="Patch", icon="FILE_REFRESH")
        can_run = bool(items and any(item.selected for item in items))
        row = box.row()
        row.scale_y = 1.4
        row.enabled = can_run
        row.operator("charproj.patch_all", text="Patch All Selected", icon="PLAY")

        row = box.row()
        row.scale_y = 1.1
        row.enabled = bool(settings.project_folder)
        row.operator("charproj.restore_backups", text="Restore Backups", icon="LOOP_BACK")

        if settings.status_text:
            info = box.box()
            info.scale_y = 0.7
            for line in settings.status_text.split("\n"):
                info.label(text=line)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    CharBinItem,
    CharBinUpdaterSettings,
    CHARBIN_UL_file_list,
    CHARBIN_OT_pick_project_folder,
    CHARBIN_OT_scan,
    CHARBIN_OT_select_all,
    CHARBIN_OT_select_none,
    CHARBIN_OT_update,
    VIEW3D_PT_char_bin_updater,
    CharBinProjectItem,
    CharBinProjectSettings,
    CHARPROJ_UL_file_list,
    CHARPROJ_OT_pick_folder,
    CHARPROJ_OT_scan,
    CHARPROJ_OT_select_all,
    CHARPROJ_OT_select_none,
    CHARPROJ_OT_patch_all,
    CHARPROJ_OT_restore_backups,
    VIEW3D_PT_charbin_project,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.char_bin_updater_settings = bpy.props.PointerProperty(
        type=CharBinUpdaterSettings
    )
    bpy.types.Scene.char_bin_items = bpy.props.CollectionProperty(type=CharBinItem)
    bpy.types.Scene.char_bin_project_settings = bpy.props.PointerProperty(
        type=CharBinProjectSettings
    )
    bpy.types.Scene.char_bin_project_items = bpy.props.CollectionProperty(
        type=CharBinProjectItem
    )


def unregister():
    if hasattr(bpy.types.Scene, "char_bin_project_items"):
        del bpy.types.Scene.char_bin_project_items
    if hasattr(bpy.types.Scene, "char_bin_project_settings"):
        del bpy.types.Scene.char_bin_project_settings
    if hasattr(bpy.types.Scene, "char_bin_items"):
        del bpy.types.Scene.char_bin_items
    if hasattr(bpy.types.Scene, "char_bin_updater_settings"):
        del bpy.types.Scene.char_bin_updater_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
