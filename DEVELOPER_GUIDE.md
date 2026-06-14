# Developer Guide: Import/Export Mapgeo Files

This guide covers how to programmatically import and export League of Legends `.mapgeo` files using the Rey's Mapgeo Blender Addon.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Mapgeo Format Basics](#mapgeo-format-basics)
3. [Import Workflow](#import-workflow)
4. [Export Workflow](#export-workflow)
5. [Custom Bucket Grids](#custom-bucket-grids)
6. [API Reference](#api-reference)
7. [Debugging](#debugging)
8. [Common Patterns](#common-patterns)

---

## Architecture Overview

The mapgeo import/export pipeline consists of several core modules:

### Core Modules

- **`mapgeo_parser.py`** — Binary format reading/writing, struct packing/unpacking
- **`import_mapgeo.py`** — Collection management, material assignment, Blender object creation
- **`export_mapgeo.py`** — Scene validation, mapgeo serialization, custom bucket grid handling
- **`material_loader.py`** — Materials.bin parsing, texture path resolution
- **`mapgeo_debug.py`** — CLI tool for exporting mapgeo as human-readable JSON

### Data Flow

```
.mapgeo File
    ↓
mapgeo_parser.read_mapgeo()
    ↓
Parsed Binary Data (vertices, indices, materials, bucket grids)
    ↓
import_mapgeo.import_mapgeo()
    ↓
Blender Scene (meshes, materials, collections)
    ↓
[User edits in Blender]
    ↓
export_mapgeo.export_mapgeo()
    ↓
mapgeo_parser.write_mapgeo()
    ↓
.mapgeo File
```

---

## Mapgeo Format Basics

### File Structure

A `.mapgeo` file contains:

1. **Header** — Magic number, version, chunk offsets
2. **Mesh Data** — Vertices, indices, material assignments per primitive
3. **Materials** — References to materials.bin entries
4. **Bucket Grids** — Spatial partitioning for collision/rendering optimization
5. **Lightmaps** — Optional baked light texture data

### Bucket Grid Structure

Bucket grids subdivide map geometry for efficient spatial queries:

```
BucketGrid {
    path_hash: uint32              # Baron/visibility_controller hash (or 0 for render regions)
    render_region_hash: int       # Render region hash (or 0 for baron/VC grids)
    flags: uint32                  # Bit 1 = has face_visibility_flags
    buckets: 2D array              # Per-bucket vertex/index subsets
    face_visibility_flags: bytes   # Per-face visibility bitmask
}
```

### Hash Field Placement Rules

The placement of hashes in `path_hash` vs `render_region_hash` depends on grid type:

| Grid Type | path_hash | render_region_hash | flags |
|-----------|-----------|------------------|-------|
| Render Region | 0 | Region hash | Variable |
| Baron/VC | Baron or VC hash | 0 | Variable |
| Master | 0 | 0 | 1 (always has faces) |

**Important:** The master grid must:
- Cover the entire map (largest bounds)
- Have path_hash = 0 and render_region_hash = 0
- Have flags = 1 (face_visibility_flags present)
- Contain all map faces via face visibility bitmask

---

## Import Workflow

### Basic Import

```python
import bpy
from import_mapgeo import import_mapgeo

# Import a mapgeo file
mapgeo_path = r"D:\path\to\map.mapgeo"
import_mapgeo(
    bpy.context,
    mapgeo_path,
    materials_path=r"D:\path\to\map.materials",
    import_bucket_grids=True,
    import_lightmap=True
)
```

### Import Steps

1. **Parse Binary** — `mapgeo_parser.read_mapgeo()` loads vertices, indices, materials
2. **Create Collections** — Organize by mesh primitive
3. **Create Materials** — Link to materials.bin, load textures
4. **Assign Vertex Groups** — For bone skinning (if applicable)
5. **Create Bucket Grids** — Reconstruct spatial partitioning from binary data
6. **Store Metadata** — Hash values, visibility flags, countson collections and objects

### Inspecting Imported Data

Imported bucket grids store metadata on Blender objects:

```python
import bpy

# Get imported bucket grid
bucket_grid_obj = bpy.data.objects["MapGeo.BucketGrid.0"]

# Access metadata
bucket_count = bucket_grid_obj.get("bucket_count")  # int
path_hash = bucket_grid_obj.get("path_hash")        # hex string "0xDEADBEEF"
render_region_hash = bucket_grid_obj.get("render_region_hash")  # hex string or float
flags = bucket_grid_obj.get("flags")                # uint32
buckets_per_side = bucket_grid_obj.get("buckets_per_side")  # int
```

---

## Export Workflow

### Basic Export

```python
import bpy
from export_mapgeo import export_mapgeo

# Export modified scene back to mapgeo
export_mapgeo(
    bpy.context,
    output_path=r"D:\path\to\map_modified.mapgeo",
    validate=True
)
```

### Export Steps

1. **Validate Scene** — Check for intact mesh structure
2. **Serialize Mesh Data** — Pack vertices and indices into binary format
3. **Handle Custom Bucket Grids** — If custom grids exist in "Bucket Grids" collection
4. **Apply Normalization** — Correct any hash field inversions by collection `hash_type` metadata
5. **Verify Master Grid** — Ensure largest zero-zero grid selected as master
6. **Write Binary** — `mapgeo_parser.write_mapgeo()` serializes to disk

### Export Configuration

Set collection metadata to control bucketgrid export:

```python
import bpy

# Get or create bucket grids collection
custom_grids = bpy.data.collections.get("Bucket Grids")
if not custom_grids:
    custom_grids = bpy.data.collections.new("Bucket Grids")
    bpy.context.scene.collection.children.link(custom_grids)

# Set hash type for the collection
custom_grids["hash_type"] = "render_region"  # or "baron", "master"
```

Supported `hash_type` values:
- `"render_region"` — render_region_hash contains region hash, path_hash = 0
- `"baron"` — path_hash contains baron/VC hash, render_region_hash = 0
- `"master"` — Both hashes 0, flags = 1, covers full map

---

## Custom Bucket Grids

### Creating Custom Bucket Grids

Use the UI operator or programmatically via the addon:

#### Via UI (Blender)

1. LoL Mapgeo panel → Create Custom Bucket Grid
2. Select meshes to subdivide
3. Choose hash types (render_region, baron, master)
4. Configure bucket grid (click operator)

#### Programmatically

```python
import bpy

# Prepare your scene with map meshes
# Then invoke the operator
bpy.ops.mapgeo.create_custom_bucket_grid(
    # Optional parameters (use UI defaults if omitted)
)
```

### Understanding Bucket Data Structure

Bucket grids organize faces into a 2D array:

```python
bucket_data = []
for row_idx in range(buckets_per_side):
    row = []
    for col_idx in range(buckets_per_side):
        bucket = {
            "base_vertex": int,           # Offset into global vertex buffer
            "vertex_count": int,          # Vertices in this bucket
            "indices": [int, int, ...],   # Triangle indices (local to bucket)
            "inside_faces": int,          # Faces fully contained in bucket
            "sticking_faces": int         # Faces crossing bucket boundary
        }
        row.append(bucket)
    bucket_data.append(row)
```

### Hash Type Organization

When creating custom grids, meshes are grouped by hash type:

| Group | Path Hash | V18 Float | Purpose |
|-------|-----------|-----------|---------|
| **render_region** | 0 | Region hash | Render culling by region |
| **baron/visibility_controller** | Hash value | 0 | Visibility system control |
| **base/master** | 0 | 0 | Coverage grid (all faces) |

**Important:** Each group must have exactly one grid. The master grid must cover the entire map.

### Metadata on Custom Grid Objects

Custom bucket grid objects store:

```python
custom_grid = bpy.data.objects["Custom.BucketGrid"]

# Numeric metadata
custom_grid["bucket_count"] = 16            # Total buckets
custom_grid["buckets_per_side"] = 4         # 4x4 grid
custom_grid["flags"] = 1                    # Face visibility flags present

# Hash metadata (stored as hex strings for precision)
custom_grid["path_hash"] = "0x0DD1C956"
custom_grid["render_region_hash"] = "0x8E6A128E"

# Visibility (stored as hex)
custom_grid["face_visibility_flags_hex"] = "FF..."  # Per-face bitmask
```

---

## API Reference

### mapgeo_parser.py

#### `read_mapgeo(filepath: str) -> dict`

Reads a `.mapgeo` file and returns parsed data.

```python
from mapgeo_parser import read_mapgeo

data = read_mapgeo("map.mapgeo")
# data = {
#   "vertices": [...],
#   "indices": [...],
#   "materials": [...],
#   "bucket_grids": [...],
#   "lightmap": {...}
# }
```

#### `write_mapgeo(filepath: str, data: dict) -> None`

Writes parsed data back to `.mapgeo` file.

```python
from mapgeo_parser import write_mapgeo

write_mapgeo("map_modified.mapgeo", data)
```

### import_mapgeo.py

#### `import_mapgeo(context, filepath: str, **options) -> dict`

Imports mapgeo file into Blender scene.

**Options:**
- `materials_path` (str) — Path to `.materials` file
- `import_bucket_grids` (bool) — Import spatial grids (default: True)
- `import_lightmap` (bool) — Import lightmap texture (default: True)

```python
from import_mapgeo import import_mapgeo
import bpy

result = import_mapgeo(
    bpy.context,
    "map.mapgeo",
    materials_path="map.materials",
    import_bucket_grids=True
)
# result = {
#   "collection": Collection,
#   "materials_count": int,
#   "bucket_grid_count": int
# }
```

### export_mapgeo.py

#### `export_mapgeo(context, output_path: str, **options) -> bool`

Exports Blender scene to `.mapgeo` file.

**Options:**
- `validate` (bool) — Run integrity checks (default: True)
- `include_custom_bucket_grids` (bool) — Export custom grids (default: True)

```python
from export_mapgeo import export_mapgeo
import bpy

success = export_mapgeo(
    bpy.context,
    "map_modified.mapgeo",
    validate=True
)
```

---

## Debugging

### Export as JSON

Convert `.mapgeo` files to human-readable JSON for debugging:

#### CLI Usage

```bash
python mapgeo_debug.py original.mapgeo exported.mapgeo
```

This generates `original.mapgeo.json` and `exported.mapgeo.json` with full serialization of:
- All vertices and indices
- Bucket grid structure
- Hash values (hex and decimal)
- Face visibility flags
- Material assignments

#### Python API

```python
from mapgeo_debug import export_mapgeo_as_json

export_mapgeo_as_json("map.mapgeo", "map.mapgeo.json")
```

### Common Issues & Solutions

#### Issue: Hash fields appear "inverted"

**Symptom:** Binary export has hashes in wrong fields.

**Solution:** Ensure collection `hash_type` metadata is set correctly:

```python
collection["hash_type"] = "render_region"  # Not "baron"
```

The export pipeline automatically normalizes field placement based on hash_type.

#### Issue: Master grid not selected

**Symptom:** Custom grids export but game crashes or grids won't load.

**Solution:** Verify master grid:
1. Must have path_hash = 0 and v18 = 0
2. Must have largest bounds covering entire map
3. Must have flags = 1

Check via JSON export:

```bash
python mapgeo_debug.py custom.mapgeo custom.mapgeo.json
```

Look for grid with "path_hash": 0 and "render_region_hash": 0.

#### Issue: Missing face visibility flags

**Symptom:** Game reports face visibility errors.

**Solution:** Ensure `face_visibility_flags_hex` is populated on bucket grid objects:

```python
import bpy

grid = bpy.data.objects["Custom.BucketGrid"]
if "face_visibility_flags_hex" not in grid:
    print("ERROR: Missing face_visibility_flags_hex")
```

The create operator should populate this automatically on v15+ maps.

---

## Common Patterns

### Workflow 1: Import, Modify, Export

```python
import bpy
from import_mapgeo import import_mapgeo
from export_mapgeo import export_mapgeo

# Import
import_mapgeo(bpy.context, "map.mapgeo", materials_path="map.materials")

# [User modifies scene in Blender UI]

# Export
export_mapgeo(bpy.context, "map_modified.mapgeo")
```

### Workflow 2: Create Custom Bucket Grids

```python
import bpy
from export_mapgeo import export_mapgeo

# Import original map
from import_mapgeo import import_mapgeo
import_mapgeo(bpy.context, "map.mapgeo")

# [User creates custom geometry and uses "Create Custom Bucket Grid" operator]

# Export with custom grids
export_mapgeo(bpy.context, "map_custom.mapgeo", include_custom_bucket_grids=True)
```

### Workflow 3: Batch Processing Maps

```python
import bpy
from pathlib import Path
from import_mapgeo import import_mapgeo
from export_mapgeo import export_mapgeo

map_folder = Path(r"D:\maps")

for mapgeo_file in map_folder.glob("*.mapgeo"):
    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Import
    print(f"Importing {mapgeo_file.name}...")
    import_mapgeo(bpy.context, str(mapgeo_file))
    
    # Modify (example: scale all objects)
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            obj.scale *= 1.1
    
    # Export
    out_path = map_folder / f"{mapgeo_file.stem}_scaled.mapgeo"
    print(f"Exporting to {out_path}...")
    export_mapgeo(bpy.context, str(out_path))
```

### Workflow 4: Inspect Bucket Grid Data

```python
import bpy

# Get bucket grid collection
grids_collection = bpy.data.collections.get("MapGeo.BucketGrids")

for grid_obj in grids_collection.objects:
    if grid_obj.name.startswith("MapGeo.BucketGrid"):
        path_hash = grid_obj.get("path_hash")
        v18 = grid_obj.get("render_region_hash")
        bucket_count = grid_obj.get("bucket_count")
        
        print(f"{grid_obj.name}:")
        print(f"  path_hash: {path_hash}")
        print(f"  v18: {v18}")
        print(f"  bucket_count: {bucket_count}")
```

---

## Additional Resources

- **Blender Addon API** — https://docs.blender.org/api/current/
- **League File Formats** — https://github.com/LeagueToolkit
- **Community Documentation** — https://communitydragon.org/
- **Issue Tracking** — https://github.com/TheKillerey/MapgeoAddon/issues

---

## Version Information

This guide is for **Rey's Mapgeo Blender Addon v0.4.0+**

Updated: 2026-03-23
