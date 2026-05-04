"""
Prey Collections — Blender collection-based editing for .prey category files.

Each prey category (lighting, visibility, banners, jungle_camps, navgrid, map,
extra) gets a Blender collection.  Entries become empty objects with editable
custom properties.  Materials, VFX, and particles already have dedicated import
paths and are excluded here.

Workflow:
  1. Load prey categories → Blender collections  (load_prey_categories)
  2. Edit entries in Blender (move, rename, change properties, add, remove)
  3. Save collections → prey JSON files          (save_prey_categories)
  4. Rebuild .materials.bin from prey             (prey_to_bin)
"""

import bpy
import json
import os

# Categories managed by this module (materials/vfx/particles have dedicated systems)
MANAGED_CATEGORIES = (
    "lighting", "map", "visibility", "banners", "jungle_camps", "navgrid", "extra",
)

# Human-readable labels
_CAT_LABELS = {
    "lighting":     "Lighting",
    "map":          "Map",
    "visibility":   "Visibility",
    "banners":      "Banners",
    "jungle_camps": "Jungle Camps",
    "navgrid":      "Nav Grid",
    "extra":        "Extra",
}

# Icons per category
_CAT_ICONS = {
    "lighting":     'LIGHT_SUN',
    "map":          'WORLD',
    "visibility":   'HIDE_OFF',
    "banners":      'OUTLINER_OB_IMAGE',
    "jungle_camps": 'FORCE_TEXTURE',
    "navgrid":      'GRID',
    "extra":        'QUESTION',
}

_COLLECTION_PREFIX = "Prey_"


def _prey_col_name(root_name: str, cat: str) -> str:
    return f"{root_name}_{_COLLECTION_PREFIX}{_CAT_LABELS.get(cat, cat)}"


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ============================================================================
# Load prey categories → Blender collections
# ============================================================================

def _entry_display_name(entry: dict) -> str:
    """Derive a display name for a prey entry."""
    tn = entry.get("typeName", "")
    ph = entry.get("pathHash", "")

    # Try to find a 'name' field
    for f in entry.get("fields", []):
        fname = f.get("fieldName", f.get("name_hash", ""))
        if fname in ("name", "0x8d39bde6"):
            val = f.get("value", "")
            if isinstance(val, str) and val:
                return val

    # Use typeName + short pathHash
    short_ph = ph[-6:] if len(ph) > 6 else ph
    return f"{tn}_{short_ph}" if tn else f"Entry_{short_ph}"


def load_prey_categories(prey_dir: str, base_name: str, root_name: str = "Prey") -> dict:
    """Load prey category files into Blender collections.

    Creates a root collection with sub-collections per category.
    Each entry becomes an empty object with custom properties.

    Args:
        prey_dir: Path to the _prey/ directory
        base_name: Base name for prey files (e.g., 'sodapop_srs')
        root_name: Name for the root Blender collection

    Returns:
        Dict with category → number of entries loaded.
    """
    # Create or find root collection
    root_col_name = f"{root_name}_{_COLLECTION_PREFIX}Categories"
    root_col = bpy.data.collections.get(root_col_name)
    if root_col:
        # Clean existing
        _remove_collection_recursive(root_col)
    root_col = bpy.data.collections.new(root_col_name)
    bpy.context.scene.collection.children.link(root_col)

    counts = {}

    for cat in MANAGED_CATEGORIES:
        fpath = os.path.join(prey_dir, f"{base_name}.prey.{cat}")
        if not os.path.isfile(fpath):
            counts[cat] = 0
            continue

        data = _read_json(fpath)
        entries = data.get("entries", [])

        # Create category sub-collection
        cat_col_name = _prey_col_name(root_name, cat)
        cat_col = bpy.data.collections.new(cat_col_name)
        root_col.children.link(cat_col)

        for idx, entry in enumerate(entries):
            display_name = _entry_display_name(entry)
            safe_name = display_name.replace("/", "_").replace("\\", "_")[:60]
            obj_name = f"{_CAT_LABELS.get(cat, cat)}_{safe_name}"

            obj = bpy.data.objects.new(obj_name, None)
            obj.empty_display_type = 'PLAIN_AXES'
            obj.empty_display_size = 0.5
            cat_col.objects.link(obj)

            # Store category and type info
            obj["prey_category"] = cat
            obj["prey_type_hash"] = entry.get("typeHash", "")
            obj["prey_type_name"] = entry.get("typeName", "")
            obj["prey_path_hash"] = entry.get("pathHash", "")
            obj["prey_entry_index"] = idx

            # Store the full fields JSON for round-trip
            obj["prey_fields_json"] = json.dumps(
                entry.get("fields", []), ensure_ascii=False, default=str
            )

            # Extract human-readable properties for quick editing
            _extract_editable_props(obj, entry)

        counts[cat] = len(entries)

    # Store metadata on root collection
    root_col["prey_dir"] = prey_dir
    root_col["prey_base_name"] = base_name

    return counts


def _extract_editable_props(obj, entry: dict):
    """Extract key fields as individual custom properties for editing."""
    fields = entry.get("fields", [])

    for f in fields:
        fname = f.get("fieldName", "")
        nhash = f.get("name_hash", "")
        val = f.get("value")

        # Use human-readable name if available, else hash
        prop_name = fname if fname else nhash
        if not prop_name:
            continue

        # Store scalar values directly, complex ones as JSON
        if isinstance(val, (int, float, bool, str)):
            obj[f"field_{prop_name}"] = val
        elif isinstance(val, list):
            # Vectors/arrays: store as JSON string
            obj[f"field_{prop_name}"] = json.dumps(val, default=str)
        elif val is not None:
            obj[f"field_{prop_name}"] = json.dumps(val, default=str)

    # Embedded sub-entries (values lists in container fields)
    for f in fields:
        if "values" in f and isinstance(f["values"], list):
            fname = f.get("fieldName", f.get("name_hash", ""))
            obj[f"container_{fname}_count"] = len(f["values"])


# ============================================================================
# Save Blender collections → prey JSON files
# ============================================================================

def save_prey_categories(prey_dir: str, base_name: str, root_name: str = "Prey") -> dict:
    """Save Blender prey category collections back to .prey.* JSON files.

    Reads objects from category collections, rebuilds entry data from
    custom properties, and writes updated JSON files.

    Returns:
        Dict with category → number of entries saved.
    """
    root_col_name = f"{root_name}_{_COLLECTION_PREFIX}Categories"
    root_col = bpy.data.collections.get(root_col_name)
    if not root_col:
        return {}

    counts = {}

    for cat in MANAGED_CATEGORIES:
        cat_col_name = _prey_col_name(root_name, cat)
        cat_col = bpy.data.collections.get(cat_col_name)

        fpath = os.path.join(prey_dir, f"{base_name}.prey.{cat}")

        if not cat_col or len(cat_col.objects) == 0:
            # Write empty file if category exists but is empty
            if os.path.isfile(fpath):
                data = _read_json(fpath)
                data["entries"] = []
                data["count"] = 0
                _write_json(fpath, data)
            counts[cat] = 0
            continue

        # Load existing file for format/header preservation
        if os.path.isfile(fpath):
            data = _read_json(fpath)
        else:
            from . import prey_format
            data = {
                "format": f"prey.{cat}",
                "version": prey_format.PREY_FORMAT_VERSION,
                "source": f"{base_name}.materials.bin",
                "count": 0,
                "entries": [],
            }

        # Sort objects by their original index to preserve order
        objs = sorted(cat_col.objects, key=lambda o: o.get("prey_entry_index", 9999))

        entries = []
        for obj in objs:
            entry = _obj_to_prey_entry(obj)
            entries.append(entry)

        data["entries"] = entries
        data["count"] = len(entries)
        _write_json(fpath, data)
        counts[cat] = len(entries)

    return counts


def _obj_to_prey_entry(obj) -> dict:
    """Convert a Blender object back to a prey entry dict."""
    # Start from stored fields JSON (authoritative round-trip data)
    fields_json = obj.get("prey_fields_json", "[]")
    try:
        fields = json.loads(fields_json)
    except (json.JSONDecodeError, TypeError):
        fields = []

    # Apply edits: overwrite field values from field_ custom properties
    _apply_edited_props(obj, fields)

    entry = {
        "pathHash": obj.get("prey_path_hash", ""),
        "typeHash": obj.get("prey_type_hash", ""),
        "typeName": obj.get("prey_type_name", ""),
        "fields": fields,
    }

    # Preserve any extra keys from the original entry (_sourceFormat, fullText, etc.)
    return entry


def _apply_edited_props(obj, fields: list):
    """Apply edited field_ custom properties back to the fields list."""
    # Build field lookup by name or hash
    field_map = {}
    for i, f in enumerate(fields):
        fname = f.get("fieldName", "")
        nhash = f.get("name_hash", "")
        key = fname if fname else nhash
        if key:
            field_map[key] = i

    # Check all field_ properties on the object
    for key in list(obj.keys()):
        if not key.startswith("field_"):
            continue
        prop_name = key[6:]  # strip "field_"
        if prop_name not in field_map:
            continue

        idx = field_map[prop_name]
        bl_val = obj[key]

        # Try to parse JSON values (for vectors/arrays)
        if isinstance(bl_val, str):
            try:
                parsed = json.loads(bl_val)
                if isinstance(parsed, (list, dict)):
                    bl_val = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Convert Blender IDPropertyArray to regular list
        if hasattr(bl_val, 'to_list'):
            bl_val = bl_val.to_list()

        fields[idx]["value"] = bl_val


# ============================================================================
# Helpers
# ============================================================================

def _remove_collection_recursive(col):
    """Remove a collection and all its objects/children."""
    for child in list(col.children):
        _remove_collection_recursive(child)
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(col)


def get_prey_root_collection(root_name: str = "Prey"):
    """Find the prey categories root collection."""
    root_col_name = f"{root_name}_{_COLLECTION_PREFIX}Categories"
    return bpy.data.collections.get(root_col_name)


def get_active_prey_entry():
    """Return the active object if it's a prey entry, else None."""
    obj = bpy.context.active_object
    if obj and obj.get("prey_category"):
        return obj
    return None


# ============================================================================
# Update manifest for new/removed entries
# ============================================================================

def update_manifest_from_categories(prey_dir: str, base_name: str, root_name: str = "Prey"):
    """Update the prey manifest file to reflect current collection state.

    This ensures prey_to_bin will include entries added/removed in collections.
    """
    manifest_path = os.path.join(prey_dir, f"{base_name}.prey.manifest")
    if not os.path.isfile(manifest_path):
        return

    manifest = _read_json(manifest_path)
    entry_order = manifest.get("entryOrder", [])

    root_col_name = f"{root_name}_{_COLLECTION_PREFIX}Categories"
    root_col = bpy.data.collections.get(root_col_name)
    if not root_col:
        return

    # Collect current pathHashes from collections
    current_entries = set()
    for cat in MANAGED_CATEGORIES:
        cat_col_name = _prey_col_name(root_name, cat)
        cat_col = bpy.data.collections.get(cat_col_name)
        if not cat_col:
            continue
        for obj in cat_col.objects:
            ph = obj.get("prey_path_hash", "")
            if ph:
                current_entries.add(ph)

    # Remove deleted entries from manifest order
    new_order = []
    for item in entry_order:
        cat = item.get("category", "extra")
        ph = item.get("pathHash", "")
        if cat in MANAGED_CATEGORIES:
            if ph in current_entries:
                new_order.append(item)
            # else: entry was removed from collection, skip
        else:
            # Categories not managed here (materials, vfx, particles) stay
            new_order.append(item)

    # Add new entries (in collections but not in manifest)
    existing_phs = {item.get("pathHash", "") for item in new_order}
    for cat in MANAGED_CATEGORIES:
        cat_col_name = _prey_col_name(root_name, cat)
        cat_col = bpy.data.collections.get(cat_col_name)
        if not cat_col:
            continue
        for obj in sorted(cat_col.objects, key=lambda o: o.get("prey_entry_index", 9999)):
            ph = obj.get("prey_path_hash", "")
            if ph and ph not in existing_phs:
                new_order.append({
                    "category": cat,
                    "typeHash": obj.get("prey_type_hash", ""),
                    "pathHash": ph,
                })
                existing_phs.add(ph)

    manifest["entryOrder"] = new_order
    manifest["totalEntries"] = len(new_order)
    _write_json(manifest_path, manifest)
