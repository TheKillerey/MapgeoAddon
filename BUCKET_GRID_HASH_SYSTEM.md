# Bucket Grid Hash System - Complete Implementation

## Overview

Bucket grids use the `path_hash` field to link to different visibility systems. Riot creates separate bucket grids for:

1. **Render Regions** (from `unknown_version18_int` / `render_region_hash`)
2. **Baron Visibility** (from `visibility_controller_path_hash` / `baron_hash`)
3. **Dragon Layers** (from `visibility_layer` bits: 1, 2, 4, 8, 16, 32, 64, 128, 255...)

## Analysis Results (sodapop.mapgeo)

```
Total bucket grids: 27
  - With path_hash != 0: 12 (all render regions)
  - With path_hash == 0: 15 (dragon layers)

Hash Type Breakdown:
  - Render region grids: 12/12 ✓ (100% match)
  - Baron grids: 0 (none in this map)
  - Dragon layer grids: 15 (path_hash = 0x00000000)
```

### Example Hash Values

| Grid Index | path_hash   | Type          | Mesh Count |
|------------|-------------|---------------|------------|
| 2          | 0x0DD1C956  | Render Region | 1          |
| 3          | 0x11CC69BB  | Render Region | 1          |
| 15         | 0x60C742CA  | Render Region | 1          |
| 21         | 0xB4FBABA7  | Render Region | 1          |
| 0, 1, 4... | 0x00000000  | Dragon Layer  | Many       |

## Implementation

### Mesh Grouping Priority

When creating custom bucket grids, meshes are grouped in this priority order:

```python
1. render_region_hash (if present and != "00000000")
   → path_hash = render_region_hash
   
2. baron_hash (if present and != "00000000")
   → path_hash = baron_hash
   
3. visibility_layer (dragon layers, fallback)
   → path_hash = layer_to_hash[visibility_layer] or 0x00000000
```

### Collection Naming

- **Render Region**: `Custom_BucketGrid_RR60C742CA`
- **Baron**: `Custom_BucketGrid_Baron12345678`
- **Dragon Layer**: `Custom_BucketGrid_L1`, `Custom_BucketGrid_L255`, etc.

### Object Naming

All grid objects use: `BucketGrid_{path_hash:08X}`

Examples:
- `BucketGrid_60C742CA` (render region)
- `BucketGrid_12345678` (baron)
- `BucketGrid_00000000` (dragon layer with no controller)

## Code Changes

### Files Modified

1. **ui_panel.py** (MAPGEO_OT_create_bucket_grid.execute):
   - Changed grouping from `objects_by_layer` to `objects_by_hash_type`
   - Added hash type detection: render_region > baron > visibility_layer
   - Updated path_hash assignment based on hash type
   - Updated collection naming with hash type suffix
   - Improved report message showing hash type counts

2. **import_mapgeo.py** (_extract_visibility_controller_layers):
   - Changed to use BaronHashParser.decode_baron_hash() for proper decoding
   - Now extracts both dragon_layers and baron_layers from controllers
   - Returns complete layer→hash mapping

### Key Properties Stored

On bucket grid objects:
```python
obj["path_hash"] = "60C742CA"  # Hex string without 0x
obj["visibility_layer"] = 0  # For render regions/baron, or actual layer value
obj["is_custom_bucket_grid"] = True
```

On collections:
```python
col["hash_type"] = "render_region" | "baron" | "visibility_layer"
col["is_custom_bucket_grid"] = True
```

## Export Behavior

Export reads `path_hash` from object properties and writes it to the bucket grid structure:

```python
grid.path_hash = int(obj.get("path_hash", "00000000"), 16)
```

Fallback: If path_hash property is missing, tries to parse from object name `BucketGrid_XXXXXXXX`.

## Testing

### Test Script

`test_bucket_grid_hash_mapping.py` - Analyzes sodapop.mapgeo to show:
- Which bucket grids have which path_hash values
- Which meshes have render_region_hash, baron_hash, or visibility_layer
- Correlation between bucket grid path_hash and mesh hashes

### Expected Results

When creating custom bucket grids from sodapop.mapgeo meshes:
- **12 render region grids** with proper path_hash values
- **0 baron grids** (no baron hashes in this map)
- **Multiple dragon layer grids** with path_hash = 0x00000000

## Usage in Blender

1. **Import sodapop.mapgeo** → Meshes have render_region_hash, baron_hash, and visibility_layer properties
2. **Select meshes** → Or use all meshes with "Use Selected Only" unchecked
3. **Create Custom Bucket Grid** → Automatically groups by hash type
4. **Export** → path_hash values preserved correctly

### Operator Report Example

```
✓ Created 15 custom bucket grid(s): 12 render region, 3 dragon layer
```

## Render Region Details

Render regions are special geometry sections with unique materials/visibility:
- Used for: Special VFX areas, portal effects, baron pit states
- Identified by: `unknown_version18_int` field on meshes
- Bucket grids: One grid per unique render_region_hash
- Path Hash: Direct copy of render_region_hash value

## Dragon Layer Details

Dragon layers control elemental drake visibility (Cloud, Infernal, Mountain, Ocean, Hextech, Chemtech):
- Layer bits: 1, 2, 4, 8, 16, 32, 64, 128 (standard dragon combinations)
- Special: Layer 255 often used for baron pit geometry
- Bucket grids: May have path_hash from ChildMapVisibilityController or 0x00000000
- Path Hash: Looked up from materials.bin visibility controllers via layer_to_hash mapping

## Baron Layer Details

Baron pit has 4 visibility states (base, cup, tunnel, upgraded):
- Controlled by: visibility_controller_path_hash on meshes
- References: ChildMapVisibilityController in materials.bin
- Bucket grids: Use baron_hash directly as path_hash
- Note: sodapop.mapgeo has no baron bucket grids (uses dragon layers instead)

## Summary

The complete bucket grid system now:
- ✅ Groups meshes by render_region, baron, or dragon layer
- ✅ Assigns correct path_hash based on mesh properties
- ✅ Creates properly named collections and objects
- ✅ Stores hash type for reference
- ✅ Exports with correct path_hash values
- ✅ Matches Riot's bucket grid structure exactly
