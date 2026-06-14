"""Map Patcher – sequential patch-to-patch materials.bin updater.

Downloads the same map variant across consecutive CommunityDragon patch
channels (e.g. 16.3 → 16.4 → 16.5 → latest), creates incremental diffs
for each step, and applies them sequentially to a local .materials.bin
with automatic backup.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from urllib import request

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import propertybin_parser

_DIFF_FORMAT = "map_patcher_diff_v1"
_CDRAGON_BASE = "https://raw.communitydragon.org"
_USER_AGENT = {"User-Agent": "BlenderMapgeoAddon/1.0"}
_MATERIAL_TYPE_HASHES = {
    "0xff9d3409",  # StaticMaterialDef
}
_TEXTURE_EXTS = (
    ".tex", ".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".ktx", ".ktx2"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_hash(value) -> str:
    return str(value or "").strip().lower()


def _entry_key(entry: dict) -> str:
    return _normalize_hash(entry.get("path_hash"))


def _entry_fingerprint(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _looks_like_texture_path(value: str) -> bool:
    if not isinstance(value, str):
        return False
    s = value.replace("\\", "/").strip().lower()
    if "assets/" not in s:
        return False
    return s.endswith(_TEXTURE_EXTS)


def _entry_type_hash(entry: dict) -> str:
    th = entry.get("type_hash")
    if th is None:
        th = entry.get("typeHash")
    return _normalize_hash(th)


def _is_material_entry(entry: dict) -> bool:
    """Best-effort material-entry detector for map materials.bin entries."""
    if not isinstance(entry, dict):
        return False
    if _entry_type_hash(entry) in _MATERIAL_TYPE_HASHES:
        return True
    tn = str(entry.get("type_name") or entry.get("typeName") or "").lower()
    return "material" in tn


def _merge_preserve_textures(new_node, old_node):
    """Merge two parsed subtrees while preserving texture-path strings from
    old_node whenever the new value also looks like a texture path."""
    if isinstance(new_node, str) and isinstance(old_node, str):
        if _looks_like_texture_path(new_node) and _looks_like_texture_path(old_node):
            return old_node
        return new_node

    if isinstance(new_node, dict) and isinstance(old_node, dict):
        out = copy.deepcopy(new_node)
        for k in list(out.keys()):
            if k in old_node:
                out[k] = _merge_preserve_textures(out[k], old_node[k])
        return out

    if isinstance(new_node, list) and isinstance(old_node, list):
        out = copy.deepcopy(new_node)
        lim = min(len(out), len(old_node))
        for i in range(lim):
            out[i] = _merge_preserve_textures(out[i], old_node[i])
        return out

    if isinstance(new_node, tuple) and isinstance(old_node, tuple):
        out = list(copy.deepcopy(new_node))
        lim = min(len(out), len(old_node))
        for i in range(lim):
            out[i] = _merge_preserve_textures(out[i], old_node[i])
        return tuple(out)

    return copy.deepcopy(new_node)


def _get_download_dir() -> str:
    """Persistent download directory inside Blender user config."""
    d = os.path.join(
        bpy.utils.resource_path("USER"), "mapgeo_addon", "map_patcher"
    )
    os.makedirs(d, exist_ok=True)
    return d


def _build_cdragon_url(channel: str, map_name: str, variant: str) -> str:
    channel = (channel or "latest").strip().strip("/")
    map_name = (map_name or "map11").strip().lower()
    variant = (variant or "base").strip().lower()
    return (
        f"{_CDRAGON_BASE}/{channel}/game/data/maps/mapgeometry/"
        f"{map_name}/{variant}.materials.bin"
    )


def _version_tuple(v: str):
    """Parse '16.3' → (16, 3) for sorting."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except ValueError:
        return (999999,)


def _fetch_cdragon_versions() -> list[str]:
    """Fetch all numeric patch versions from CommunityDragon, sorted."""
    url = f"{_CDRAGON_BASE}/json/"
    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    versions = []
    for entry in data:
        name = entry.get("name", "")
        # Only numeric versions like "16.3"
        parts = name.split(".")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            versions.append(name)
    versions.sort(key=_version_tuple)
    return versions


def _resolve_channel(channel: str, all_versions: list[str]) -> str:
    """Resolve 'latest' to the highest numeric version, otherwise return as-is."""
    ch = channel.strip().lower()
    if ch == "latest" and all_versions:
        return all_versions[-1]
    return channel.strip()


def _build_patch_chain(old_ch: str, new_ch: str, all_versions: list[str]) -> list[str]:
    """Return the ordered list of versions from old_ch to new_ch (inclusive).

    Example: old='16.3', new='16.5' → ['16.3', '16.4', '16.5']
    """
    old_resolved = _resolve_channel(old_ch, all_versions)
    new_resolved = _resolve_channel(new_ch, all_versions)

    old_t = _version_tuple(old_resolved)
    new_t = _version_tuple(new_resolved)

    chain = [v for v in all_versions if old_t <= _version_tuple(v) <= new_t]
    if not chain:
        # Fallback: just old and new
        chain = [old_resolved, new_resolved]
    return chain


def _download_bin(channel: str, map_name: str, variant: str) -> str:
    """Download a single materials.bin. Returns local path."""
    url = _build_cdragon_url(channel, map_name, variant)
    out_dir = os.path.join(
        _get_download_dir(),
        map_name.strip().lower(),
        variant.strip().lower(),
    )
    os.makedirs(out_dir, exist_ok=True)
    safe_ch = channel.replace("/", "_").replace("\\", "_")
    out_path = os.path.join(out_dir, f"{safe_ch}.materials.bin")

    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _load_bin_entries(path: str) -> list:
    data = propertybin_parser.parse_bin(path)
    return list(data.get("entries", []))


# ---------------------------------------------------------------------------
# Diff creation / apply (in-memory variant for chaining)
# ---------------------------------------------------------------------------

def diff_entries(from_entries: list, to_entries: list, key_fn, equal_fn,
                 deepcopy_results: bool = False,
                 keep_unkeyed_as_added: bool = False) -> dict:
    """Generic entry-level diff — the single shared bin-diff primitive.

    Indexes both entry lists by ``key_fn`` and classifies every ``to`` entry as
    added (key absent in ``from``) or modified (present but ``equal_fn`` is
    False), plus the keys present only in ``from`` as removed.

    Callers supply their own ``key_fn`` / ``equal_fn`` so each preserves its own
    notion of identity and equality (``map_patcher`` keys on a normalized
    path_hash + fingerprint equality; ``map_porter`` keys on the raw path_hash +
    JSON-comparable equality).

    Args:
        deepcopy_results: deep-copy entries placed into added/modified
            (``map_patcher`` needs this; ``map_porter`` keeps live references).
        keep_unkeyed_as_added: when a ``to`` entry has a falsy key, treat it as
            added instead of skipping it (``map_porter`` behavior).
    """
    _c = copy.deepcopy if deepcopy_results else (lambda x: x)

    from_index = {}
    for e in from_entries:
        k = key_fn(e)
        if k:
            from_index[k] = e

    added, modified, removed = [], [], []
    seen_to = set()
    for e in to_entries:
        k = key_fn(e)
        if not k:
            if keep_unkeyed_as_added:
                added.append(_c(e))
            continue
        seen_to.add(k)
        if k not in from_index:
            added.append(_c(e))
        elif not equal_fn(from_index[k], e):
            modified.append(_c(e))

    for k in from_index:
        if k not in seen_to:
            removed.append(k)

    return {"added": added, "modified": modified, "removed": removed}


def _create_diff(from_entries: list, to_entries: list) -> dict:
    """Create an in-memory diff dict from two entry lists."""
    diff = diff_entries(
        from_entries, to_entries,
        key_fn=_entry_key,
        equal_fn=lambda a, b: _entry_fingerprint(a) == _entry_fingerprint(b),
        deepcopy_results=True,
    )
    diff["removed"] = sorted(diff["removed"])
    return diff


def _apply_diff_to_entries(entries: list, diff: dict, options: dict | None = None) -> list:
    """Apply a diff dict to an entry list, returning a new entry list."""
    options = options or {}
    apply_added = bool(options.get("apply_added", True))
    apply_modified = bool(options.get("apply_modified", True))
    apply_removed = bool(options.get("apply_removed", True))
    preserve_textures = bool(options.get("preserve_texture_paths", False))
    skip_material_mods = bool(options.get("skip_material_entry_modifications", False))

    entries = list(entries)

    # Remove
    if apply_removed and diff.get("removed"):
        remove_set = {_normalize_hash(x) for x in diff["removed"]}
        entries = [e for e in entries if not (_entry_key(e) and _entry_key(e) in remove_set)]

    by_key = {_entry_key(e): i for i, e in enumerate(entries) if _entry_key(e)}

    # Modify
    if apply_modified:
        for entry in diff.get("modified", []):
            key = _entry_key(entry)
            if not key:
                continue
            idx = by_key.get(key)
            if skip_material_mods:
                ref_entry = entries[idx] if idx is not None else entry
                if _is_material_entry(ref_entry):
                    continue
            if idx is None:
                entries.append(copy.deepcopy(entry))
                by_key[key] = len(entries) - 1
            else:
                repl = copy.deepcopy(entry)
                if preserve_textures:
                    repl = _merge_preserve_textures(repl, entries[idx])
                entries[idx] = repl

    # Add
    if apply_added:
        for entry in diff.get("added", []):
            key = _entry_key(entry)
            if not key:
                continue
            if key in by_key:
                entries[by_key[key]] = copy.deepcopy(entry)
                continue
            entries.append(copy.deepcopy(entry))
            by_key[key] = len(entries) - 1

    return entries


def create_diff_file(from_path: str, to_path: str, diff_path: str,
                     old_channel: str = "", new_channel: str = "") -> dict:
    """Create a JSON diff file on disk."""
    diff = _create_diff(_load_bin_entries(from_path), _load_bin_entries(to_path))

    diff_data = {
        "format": _DIFF_FORMAT,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "old_channel": old_channel,
        "new_channel": new_channel,
        "from_file": os.path.basename(from_path),
        "to_file": os.path.basename(to_path),
        **diff,
    }

    os.makedirs(os.path.dirname(diff_path) or ".", exist_ok=True)
    with open(diff_path, "w", encoding="utf-8") as f:
        json.dump(diff_data, f, indent=2, ensure_ascii=True)

    return {
        "added": len(diff["added"]),
        "modified": len(diff["modified"]),
        "removed": len(diff["removed"]),
        "path": diff_path,
    }


def _build_map11bin_url(channel: str) -> str:
    ch = (channel or "latest").strip().strip("/")
    return f"{_CDRAGON_BASE}/{ch}/game/data/maps/shipping/map11/map11.bin"


def _download_map11bin(channel: str) -> str:
    """Download map11.bin from CommunityDragon. Returns local path."""
    url = _build_map11bin_url(channel)
    out_dir = os.path.join(_get_download_dir(), "map11", "shipping")
    os.makedirs(out_dir, exist_ok=True)
    safe_ch = channel.replace("/", "_").replace("\\", "_")
    out_path = os.path.join(out_dir, f"{safe_ch}.map11.bin")
    req = request.Request(url, headers=_USER_AGENT)
    with request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def apply_diff_file(diff_path: str, target_bin_path: str, options: dict | None = None) -> dict:
    """Apply a JSON diff file to a materials.bin on disk (with backup)."""
    with open(diff_path, "r", encoding="utf-8") as f:
        diff = json.load(f)

    if diff.get("format") != _DIFF_FORMAT:
        raise ValueError(
            f"Unsupported diff format: {diff.get('format')} (expected {_DIFF_FORMAT})"
        )

    options = options or {}

    data = propertybin_parser.parse_bin(target_bin_path)
    entries = list(data.get("entries", []))
    new_entries = _apply_diff_to_entries(entries, diff, options=options)

    backup_path = (
        target_bin_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    shutil.copy2(target_bin_path, backup_path)

    data["entries"] = new_entries
    data["entry_count"] = len(new_entries)
    propertybin_parser.write_bin(data, target_bin_path)

    added = len(diff.get("added", [])) if options.get("apply_added", True) else 0
    modified = _count_applied_modified_entries(diff, options)
    removed = len(diff.get("removed", [])) if options.get("apply_removed", True) else 0
    return {"backup": backup_path, "added": added, "modified": modified, "removed": removed}


# ---------------------------------------------------------------------------
# PropertyGroup
# ---------------------------------------------------------------------------

class MapPatcherSettings(PropertyGroup):
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

    cdragon_map: StringProperty(
        name="Map",
        description="Map folder name (e.g. map11)",
        default="map11",
    )

    variant: StringProperty(
        name="Variant",
        description="Map variant (e.g. base, bloom, sodapop_srs, base_srx)",
        default="base",
    )

    # Resolved file paths (auto-filled after download)
    old_file: StringProperty(name="Old Patch File", subtype="FILE_PATH", default="")
    new_file: StringProperty(name="New Patch File", subtype="FILE_PATH", default="")
    diff_file: StringProperty(name="Diff File", subtype="FILE_PATH", default="")
    apply_target_file: StringProperty(name="Apply To File", subtype="FILE_PATH", default="")

    # Status line shown in the panel
    status_text: StringProperty(name="Status", default="")

    apply_added: BoolProperty(
        name="Apply Added Entries",
        description="Apply newly added entries from the diff",
        default=True,
    )
    apply_modified: BoolProperty(
        name="Apply Modified Entries",
        description="Apply modified entries from the diff",
        default=True,
    )
    apply_removed: BoolProperty(
        name="Apply Removed Entries",
        description="Remove entries listed as removed in the diff",
        default=True,
    )
    preserve_texture_paths: BoolProperty(
        name="Preserve Custom Textures (Prey)",
        description="When applying modified entries, keep existing texture asset paths from the target file",
        default=False,
    )
    skip_material_entry_modifications: BoolProperty(
        name="Skip Material Entry Modifications",
        description="Ignore modified entries for material types (e.g. StaticMaterialDef)",
        default=False,
    )


def _build_apply_options(settings: MapPatcherSettings) -> dict:
    return {
        "apply_added": bool(settings.apply_added),
        "apply_modified": bool(settings.apply_modified),
        "apply_removed": bool(settings.apply_removed),
        "preserve_texture_paths": bool(settings.preserve_texture_paths),
        "skip_material_entry_modifications": bool(settings.skip_material_entry_modifications),
    }


def _count_applied_modified_entries(diff: dict, options: dict) -> int:
    if not options.get("apply_modified", True):
        return 0
    if not options.get("skip_material_entry_modifications", False):
        return len(diff.get("modified", []))
    n = 0
    for entry in diff.get("modified", []):
        if _is_material_entry(entry):
            continue
        n += 1
    return n


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MAPPATCHER_OT_pick_file(Operator):
    """Select a file path for Map Patcher"""

    bl_idname = "mappatcher.pick_file"
    bl_label = "Pick File"

    target_field: EnumProperty(
        name="Target Field",
        items=[
            ("old_file", "Old Patch File", "Old patch bin"),
            ("new_file", "New Patch File", "New patch bin"),
            ("diff_file", "Diff File", "Diff JSON file"),
            ("apply_target_file", "Apply To", "Target file to patch"),
        ],
    )

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.map_patcher_settings
        setattr(settings, self.target_field, self.filepath)
        return {"FINISHED"}


class MAPPATCHER_OT_download(Operator):
    """Download materials.bin from CommunityDragon for a specific patch"""

    bl_idname = "mappatcher.download"
    bl_label = "Download from CDragon"

    which: EnumProperty(
        name="Which",
        items=[
            ("old", "Old Patch", "Download old patch bin"),
            ("new", "New Patch", "Download new patch bin"),
            ("both", "Both", "Download old and new patch bins"),
        ],
    )

    def execute(self, context):
        settings = context.scene.map_patcher_settings
        targets = []
        if self.which in ("old", "both"):
            targets.append(("old", settings.old_channel))
        if self.which in ("new", "both"):
            targets.append(("new", settings.new_channel))

        for which, channel in targets:
            ch = channel.strip()
            if not ch:
                self.report({"ERROR"}, f"{'Old' if which == 'old' else 'New'} Patch channel is empty")
                return {"CANCELLED"}
            try:
                path = _download_bin(ch, settings.cdragon_map, settings.variant)
            except Exception as e:
                self.report({"ERROR"}, f"Download failed ({ch}): {e}")
                return {"CANCELLED"}

            if which == "old":
                settings.old_file = path
            else:
                settings.new_file = path

        label = "both patches" if self.which == "both" else f"{self.which} patch"
        self.report({"INFO"}, f"Downloaded {label} for {settings.cdragon_map}/{settings.variant}")
        return {"FINISHED"}


class MAPPATCHER_OT_create_diff(Operator):
    """Create a JSON diff between old and new patch bins"""

    bl_idname = "mappatcher.create_diff"
    bl_label = "Create Diff"

    def execute(self, context):
        settings = context.scene.map_patcher_settings
        old_path = bpy.path.abspath(settings.old_file)
        new_path = bpy.path.abspath(settings.new_file)

        if not old_path or not os.path.isfile(old_path):
            self.report({"ERROR"}, "Old Patch file not found")
            return {"CANCELLED"}
        if not new_path or not os.path.isfile(new_path):
            self.report({"ERROR"}, "New Patch file not found")
            return {"CANCELLED"}

        diff_path = bpy.path.abspath(settings.diff_file) if settings.diff_file else ""
        if not diff_path:
            safe_old = settings.old_channel.replace("/", "_").replace("\\", "_")
            safe_new = settings.new_channel.replace("/", "_").replace("\\", "_")
            diff_path = os.path.join(
                os.path.dirname(new_path),
                f"{safe_old}_to_{safe_new}.map_patch.json",
            )
            settings.diff_file = diff_path

        try:
            result = create_diff_file(
                old_path, new_path, diff_path,
                old_channel=settings.old_channel,
                new_channel=settings.new_channel,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Diff creation failed: {e}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Diff created: +{result['added']} ~{result['modified']} -{result['removed']}",
        )
        return {"FINISHED"}


class MAPPATCHER_OT_apply_diff(Operator):
    """Apply a JSON diff to a local materials.bin (backup created automatically)"""

    bl_idname = "mappatcher.apply_diff"
    bl_label = "Apply Diff (Make Backup)"

    def execute(self, context):
        settings = context.scene.map_patcher_settings
        diff_path = bpy.path.abspath(settings.diff_file)
        target_path = bpy.path.abspath(settings.apply_target_file)

        if not diff_path or not os.path.isfile(diff_path):
            self.report({"ERROR"}, "Diff file not found")
            return {"CANCELLED"}
        if not target_path or not os.path.isfile(target_path):
            self.report({"ERROR"}, "Apply To file not found")
            return {"CANCELLED"}

        options = _build_apply_options(settings)

        try:
            result = apply_diff_file(diff_path, target_path, options=options)
        except Exception as e:
            self.report({"ERROR"}, f"Apply failed: {e}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Patched: +{result['added']} ~{result['modified']} -{result['removed']}  (backup saved)",
        )
        return {"FINISHED"}


class MAPPATCHER_OT_patch_all(Operator):
    """Download every intermediate patch, create sequential diffs, and apply them to the target file"""

    bl_idname = "mappatcher.patch_all"
    bl_label = "Patch All Steps"
    bl_description = (
        "Downloads all intermediate patches between Old and New, "
        "then applies each diff step-by-step to the target file"
    )

    def execute(self, context):
        settings = context.scene.map_patcher_settings
        target_path = bpy.path.abspath(settings.apply_target_file)

        if not target_path or not os.path.isfile(target_path):
            self.report({"ERROR"}, "Apply To file not set or not found")
            return {"CANCELLED"}

        old_ch = settings.old_channel.strip()
        new_ch = settings.new_channel.strip()
        if not old_ch or not new_ch:
            self.report({"ERROR"}, "Old Patch and New Patch channels must be set")
            return {"CANCELLED"}

        map_name = settings.cdragon_map.strip().lower()
        variant_name = settings.variant.strip().lower()
        options = _build_apply_options(settings)

        # 1. Fetch available versions ----------------------------------------
        settings.status_text = "Fetching CDragon version list..."
        try:
            all_versions = _fetch_cdragon_versions()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to fetch CDragon versions: {e}")
            settings.status_text = "Error fetching versions"
            return {"CANCELLED"}

        # 2. Build patch chain ------------------------------------------------
        chain = _build_patch_chain(old_ch, new_ch, all_versions)
        if len(chain) < 2:
            self.report({"ERROR"}, f"No patches found between {old_ch} and {new_ch}")
            settings.status_text = ""
            return {"CANCELLED"}

        total_steps = len(chain) - 1
        settings.status_text = f"Patch chain: {' → '.join(chain)} ({total_steps} steps)"
        print(f"[Map Patcher] Patch chain: {' → '.join(chain)}")

        # 3. Download all versions in the chain -------------------------------
        downloaded = {}
        for i, ver in enumerate(chain):
            settings.status_text = f"Downloading {ver} ({i+1}/{len(chain)})..."
            try:
                path = _download_bin(ver, map_name, variant_name)
                downloaded[ver] = path
                print(f"[Map Patcher] Downloaded {ver} → {path}")
            except Exception as e:
                self.report({"ERROR"}, f"Download failed for patch {ver}: {e}")
                settings.status_text = f"Error downloading {ver}"
                return {"CANCELLED"}

        # Update file fields for first/last
        settings.old_file = downloaded[chain[0]]
        settings.new_file = downloaded[chain[-1]]

        # 4. Backup the target file once before patching ----------------------
        backup_path = (
            target_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        shutil.copy2(target_path, backup_path)
        print(f"[Map Patcher] Backup created: {backup_path}")

        # 5. Apply diffs step by step -----------------------------------------
        data = propertybin_parser.parse_bin(target_path)
        entries = list(data.get("entries", []))

        total_added = 0
        total_modified = 0
        total_removed = 0

        diff_dir = os.path.join(
            _get_download_dir(), map_name, variant_name, "diffs"
        )
        os.makedirs(diff_dir, exist_ok=True)

        for step in range(total_steps):
            ver_a = chain[step]
            ver_b = chain[step + 1]
            settings.status_text = f"Diffing {ver_a} → {ver_b} (step {step+1}/{total_steps})..."

            entries_a = _load_bin_entries(downloaded[ver_a])
            entries_b = _load_bin_entries(downloaded[ver_b])
            diff = _create_diff(entries_a, entries_b)

            n_add_raw = len(diff["added"])
            n_mod_raw = len(diff["modified"])
            n_rem_raw = len(diff["removed"])
            n_add = n_add_raw if options.get("apply_added", True) else 0
            n_mod = _count_applied_modified_entries(diff, options)
            n_rem = n_rem_raw if options.get("apply_removed", True) else 0
            print(
                f"[Map Patcher] {ver_a} → {ver_b}: "
                f"raw +{n_add_raw} ~{n_mod_raw} -{n_rem_raw} | "
                f"applied +{n_add} ~{n_mod} -{n_rem}"
            )

            if n_add_raw == 0 and n_mod_raw == 0 and n_rem_raw == 0:
                print(f"[Map Patcher] {ver_a} → {ver_b}: no changes, skipping")
                continue

            # Save individual diff file for reference
            diff_data = {
                "format": _DIFF_FORMAT,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "old_channel": ver_a,
                "new_channel": ver_b,
                **diff,
            }
            diff_file_path = os.path.join(diff_dir, f"{ver_a}_to_{ver_b}.map_patch.json")
            with open(diff_file_path, "w", encoding="utf-8") as f:
                json.dump(diff_data, f, indent=2, ensure_ascii=True)

            # Apply to in-memory entries
            entries = _apply_diff_to_entries(entries, diff, options=options)
            total_added += n_add
            total_modified += n_mod
            total_removed += n_rem

        # 6. Write the final result -------------------------------------------
        data["entries"] = entries
        data["entry_count"] = len(entries)
        propertybin_parser.write_bin(data, target_path)

        # Set diff_file to the last step diff for reference
        settings.diff_file = os.path.join(diff_dir, f"{chain[-2]}_to_{chain[-1]}.map_patch.json")

        summary = (
            f"Done! {total_steps} steps ({chain[0]} → {chain[-1]}): "
            f"+{total_added} ~{total_modified} -{total_removed}"
        )
        settings.status_text = summary
        self.report({"INFO"}, summary)
        print(f"[Map Patcher] {summary}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class VIEW3D_PT_map_patcher(Panel):
    """Map Patcher – compare materials.bin across patches"""

    bl_label = "Map Patcher"
    bl_idname = "VIEW3D_PT_map_patcher"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "League Tools"
    bl_order = 90
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.map_patcher_settings

        # -- CDragon Settings ------------------------------------------------
        box = layout.box()
        box.label(text="CommunityDragon", icon="URL")

        row = box.row(align=True)
        row.prop(settings, "cdragon_map")
        row.prop(settings, "variant")

        row = box.row(align=True)
        split = row.split(factor=0.5, align=True)
        split.prop(settings, "old_channel")
        split.prop(settings, "new_channel")

        # -- Target file (needed for one-click) ------------------------------
        box = layout.box()
        box.label(text="Target File", icon="FILE_BLEND")
        row = box.row(align=True)
        row.prop(settings, "apply_target_file", text="Apply To")
        op = row.operator("mappatcher.pick_file", text="", icon="FILEBROWSER")
        op.target_field = "apply_target_file"

        # -- One-click sequential patch --------------------------------------
        box = layout.box()
        box.label(text="Sequential Patch", icon="MODIFIER")
        box.operator("mappatcher.patch_all", text="Patch All Steps", icon="PLAY")

        if settings.status_text:
            info = box.box()
            info.scale_y = 0.7
            for line in settings.status_text.split("\n"):
                info.label(text=line)

        # -- Manual / Advanced -----------------------------------------------
        box = layout.box()
        box.label(text="Manual (Advanced)", icon="PREFERENCES")

        opts = box.box()
        opts.label(text="Apply Filters", icon="FILTER")
        row = opts.row(align=True)
        row.prop(settings, "apply_added")
        row.prop(settings, "apply_modified")
        row.prop(settings, "apply_removed")
        opts.prop(settings, "skip_material_entry_modifications")
        opts.prop(settings, "preserve_texture_paths")

        row = box.row(align=True)
        op = row.operator("mappatcher.download", text="Download Old", icon="IMPORT")
        op.which = "old"
        op = row.operator("mappatcher.download", text="Download New", icon="IMPORT")
        op.which = "new"
        row = box.row(align=True)
        op = row.operator("mappatcher.download", text="Download Both", icon="IMPORT")
        op.which = "both"

        row = box.row(align=True)
        row.prop(settings, "old_file", text="Old")
        op = row.operator("mappatcher.pick_file", text="", icon="FILEBROWSER")
        op.target_field = "old_file"

        row = box.row(align=True)
        row.prop(settings, "new_file", text="New")
        op = row.operator("mappatcher.pick_file", text="", icon="FILEBROWSER")
        op.target_field = "new_file"

        row = box.row(align=True)
        row.prop(settings, "diff_file", text="Diff")
        op = row.operator("mappatcher.pick_file", text="", icon="FILEBROWSER")
        op.target_field = "diff_file"

        row = box.row(align=True)
        row.operator("mappatcher.create_diff", text="Create Diff", icon="FILE_TICK")
        row.operator("mappatcher.apply_diff", text="Apply Diff", icon="CHECKMARK")


# ---------------------------------------------------------------------------
# Map11.bin Patcher – standalone sequential patcher for map11.bin
# ---------------------------------------------------------------------------

class Map11BinPatcherSettings(PropertyGroup):
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
    apply_target_file: StringProperty(
        name="Apply To",
        description="Local map11.bin to patch",
        subtype="FILE_PATH",
        default="",
    )
    status_text: StringProperty(name="Status", default="")
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


class MAP11BIN_OT_pick_file(Operator):
    """Select the local map11.bin to patch"""

    bl_idname = "map11bin_patcher.pick_file"
    bl_label = "Pick map11.bin"

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.map11bin_patcher_settings.apply_target_file = self.filepath
        return {"FINISHED"}


class MAP11BIN_OT_patch_all(Operator):
    """Download every intermediate map11.bin, diff, and apply sequentially"""

    bl_idname = "map11bin_patcher.patch_all"
    bl_label = "Patch All Steps"
    bl_description = (
        "Downloads all intermediate map11.bin versions between Old and New, "
        "then applies each diff step-by-step to the target file"
    )

    def execute(self, context):
        settings = context.scene.map11bin_patcher_settings
        target_path = bpy.path.abspath(settings.apply_target_file)

        if not target_path or not os.path.isfile(target_path):
            self.report({"ERROR"}, "Apply To file not set or not found")
            return {"CANCELLED"}

        old_ch = settings.old_channel.strip()
        new_ch = settings.new_channel.strip()
        if not old_ch or not new_ch:
            self.report({"ERROR"}, "Old Patch and New Patch channels must be set")
            return {"CANCELLED"}

        options = {
            "apply_added": bool(settings.apply_added),
            "apply_modified": bool(settings.apply_modified),
            "apply_removed": bool(settings.apply_removed),
            "preserve_texture_paths": bool(settings.preserve_texture_paths),
        }

        # 1. Fetch available versions -----------------------------------------
        settings.status_text = "Fetching CDragon version list..."
        try:
            all_versions = _fetch_cdragon_versions()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to fetch CDragon versions: {e}")
            settings.status_text = "Error fetching versions"
            return {"CANCELLED"}

        # 2. Build patch chain ------------------------------------------------
        chain = _build_patch_chain(old_ch, new_ch, all_versions)
        if len(chain) < 2:
            self.report({"ERROR"}, f"No patches found between {old_ch} and {new_ch}")
            settings.status_text = ""
            return {"CANCELLED"}

        total_steps = len(chain) - 1
        settings.status_text = f"Patch chain: {' → '.join(chain)} ({total_steps} steps)"
        print(f"[Map11Bin Patcher] Patch chain: {' → '.join(chain)}")

        # 3. Download all versions in the chain --------------------------------
        downloaded = {}
        for i, ver in enumerate(chain):
            settings.status_text = f"Downloading {ver} ({i+1}/{len(chain)})..."
            try:
                path = _download_map11bin(ver)
                downloaded[ver] = path
                print(f"[Map11Bin Patcher] Downloaded {ver} → {path}")
            except Exception as e:
                self.report({"ERROR"}, f"Download failed for patch {ver}: {e}")
                settings.status_text = f"Error downloading {ver}"
                return {"CANCELLED"}

        # 4. Backup the target file once before patching -----------------------
        backup_path = target_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target_path, backup_path)
        print(f"[Map11Bin Patcher] Backup created: {backup_path}")

        # 5. Apply diffs step by step ------------------------------------------
        data = propertybin_parser.parse_bin(target_path)
        entries = list(data.get("entries", []))

        total_added = 0
        total_modified = 0
        total_removed = 0

        diff_dir = os.path.join(_get_download_dir(), "map11", "shipping", "diffs")
        os.makedirs(diff_dir, exist_ok=True)

        for step in range(total_steps):
            ver_a = chain[step]
            ver_b = chain[step + 1]
            settings.status_text = f"Diffing {ver_a} → {ver_b} (step {step+1}/{total_steps})..."

            entries_a = _load_bin_entries(downloaded[ver_a])
            entries_b = _load_bin_entries(downloaded[ver_b])
            diff = _create_diff(entries_a, entries_b)

            n_add_raw = len(diff["added"])
            n_mod_raw = len(diff["modified"])
            n_rem_raw = len(diff["removed"])
            n_add = n_add_raw if options.get("apply_added") else 0
            n_mod = _count_applied_modified_entries(diff, options)
            n_rem = n_rem_raw if options.get("apply_removed") else 0
            print(
                f"[Map11Bin Patcher] {ver_a} → {ver_b}: "
                f"raw +{n_add_raw} ~{n_mod_raw} -{n_rem_raw} | "
                f"applied +{n_add} ~{n_mod} -{n_rem}"
            )

            if n_add_raw == 0 and n_mod_raw == 0 and n_rem_raw == 0:
                print(f"[Map11Bin Patcher] {ver_a} → {ver_b}: no changes, skipping")
                continue

            # Save diff file for reference
            diff_data = {
                "format": _DIFF_FORMAT,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "old_channel": ver_a,
                "new_channel": ver_b,
                "from_file": f"{ver_a}.map11.bin",
                "to_file": f"{ver_b}.map11.bin",
                **diff,
            }
            diff_file_path = os.path.join(diff_dir, f"{ver_a}_to_{ver_b}.map11_patch.json")
            with open(diff_file_path, "w", encoding="utf-8") as f:
                json.dump(diff_data, f, indent=2, ensure_ascii=True)

            entries = _apply_diff_to_entries(entries, diff, options=options)
            total_added += n_add
            total_modified += n_mod
            total_removed += n_rem

        # 6. Write the final result -------------------------------------------
        data["entries"] = entries
        data["entry_count"] = len(entries)
        propertybin_parser.write_bin(data, target_path)

        summary = (
            f"Done! {total_steps} steps ({chain[0]} → {chain[-1]}): "
            f"+{total_added} ~{total_modified} -{total_removed}"
        )
        settings.status_text = summary
        self.report({"INFO"}, summary)
        print(f"[Map11Bin Patcher] {summary}")
        return {"FINISHED"}


class VIEW3D_PT_map11bin_patcher(Panel):
    """Map11.bin Patcher – sequential patch updater for map11.bin"""

    bl_label = "Map11.bin Patcher"
    bl_idname = "VIEW3D_PT_map11bin_patcher"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "League Tools"
    bl_order = 91
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.map11bin_patcher_settings

        box = layout.box()
        box.label(text="CommunityDragon Channels", icon="URL")
        row = box.row(align=True)
        split = row.split(factor=0.5, align=True)
        split.prop(settings, "old_channel")
        split.prop(settings, "new_channel")

        box = layout.box()
        box.label(text="Target map11.bin", icon="FILE")
        row = box.row(align=True)
        row.prop(settings, "apply_target_file", text="")
        row.operator("map11bin_patcher.pick_file", text="", icon="FILEBROWSER")

        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")
        row = box.row(align=True)
        row.prop(settings, "apply_added")
        row.prop(settings, "apply_modified")
        row.prop(settings, "apply_removed")
        box.prop(settings, "preserve_texture_paths")

        layout.operator("map11bin_patcher.patch_all", text="Patch All Steps", icon="PLAY")

        if settings.status_text:
            info = layout.box()
            info.scale_y = 0.7
            for line in settings.status_text.split("\n"):
                info.label(text=line)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    MapPatcherSettings,
    Map11BinPatcherSettings,
    MAPPATCHER_OT_pick_file,
    MAPPATCHER_OT_download,
    MAPPATCHER_OT_create_diff,
    MAPPATCHER_OT_apply_diff,
    MAPPATCHER_OT_patch_all,
    VIEW3D_PT_map_patcher,
    MAP11BIN_OT_pick_file,
    MAP11BIN_OT_patch_all,
    VIEW3D_PT_map11bin_patcher,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.map_patcher_settings = bpy.props.PointerProperty(type=MapPatcherSettings)
    bpy.types.Scene.map11bin_patcher_settings = bpy.props.PointerProperty(type=Map11BinPatcherSettings)


def unregister():
    if hasattr(bpy.types.Scene, "map11bin_patcher_settings"):
        del bpy.types.Scene.map11bin_patcher_settings
    if hasattr(bpy.types.Scene, "map_patcher_settings"):
        del bpy.types.Scene.map_patcher_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
