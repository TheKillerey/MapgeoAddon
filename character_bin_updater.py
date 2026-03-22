"""Character Bin Updater – apply CDragon patch diffs to project character bins.

Scans {ProjectFolder}/Map*/data/characters/**/*.bin, downloads the same files
from CommunityDragon for old and new patch versions, creates per-file diffs,
and applies them to the local project files (with automatic backups).
"""

from __future__ import annotations

import glob
import os
import shutil
from datetime import datetime
from urllib import request

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import propertybin_parser
from .map_patcher import (
    _CDRAGON_BASE,
    _USER_AGENT,
    _apply_diff_to_entries,
    _create_diff,
    _fetch_cdragon_versions,
    _get_download_dir,
    _load_bin_entries,
    _resolve_channel,
)


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
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.char_bin_updater_settings = bpy.props.PointerProperty(
        type=CharBinUpdaterSettings
    )
    bpy.types.Scene.char_bin_items = bpy.props.CollectionProperty(type=CharBinItem)


def unregister():
    if hasattr(bpy.types.Scene, "char_bin_items"):
        del bpy.types.Scene.char_bin_items
    if hasattr(bpy.types.Scene, "char_bin_updater_settings"):
        del bpy.types.Scene.char_bin_updater_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
