# Bucket Grid System Research Report

**Date**: 2024-02-22  
**Map**: Map11 (sodapop_srs)  
**Files**: sodapop_srs.mapgeo, sodapop_srs.materials.py

---

## Executive Summary

The **bucket grid system is a spatial partitioning structure** that organizes all terrain/geometry in a map into a 2D grid of "buckets" (cells). Each bucket contains:
- A portion of the unified geometry (shared vertex/index buffers)
- Metadata about which faces touch it and how many stick out
- Per-face visibility flags (which layers can see each face)

**KEY INSIGHT**: Bucket grids are **NOT primarily about dragon layers**. Dragon layers use a different system (visibility_layer bit flags on meshes). Bucket grids are about **spatial partitioning for rendering optimization**.

---

## Bucket Grid Data Structure

Located in `.mapgeo` file, read in `mapgeo_parser.py` lines 548-610:

```python
class BucketGrid:
    path_hash: int = 0              # VisibilityControllerPathHash (v15+) - LINKS to materials.bin
    unknown_v18_float: float = 0.0  # Unknown float (v18+)
    
    # Grid extent and sizing
    min_x, min_z: float             # Grid bounds (mapgeo XZ horizontal plane)
    max_x, max_z: float
    max_stickout_x, max_stickout_z: float  # Max geometry extension beyond grid
    
    bucket_size_x, bucket_size_z: float    # Size of each cell
    buckets_per_side: int                  # Grid is NxN cells
    
    # Geometry data
    vertices: List[Tuple[float, float, float]]  # Unified vertex buffer (mapgeo format: X, Y=height, Z)
    indices: List[int]                         # Unified index buffer (u16)
    
    # 2D bucket grid (NxN)
    buckets: List[List[GeometryBucket]]
    
    # Per-polygon flags (if present)
    face_visibility_flags: List[int]           # One byte per triangle
```

### GeometryBucket Structure

```python
class GeometryBucket:
    max_stickout_x, max_stickout_z: float  # How far geometry extends outside bucket
    
    # Index/vertex buffer pointers
    start_index: int                       # Where this bucket's indices start in unified buffer
    base_vertex: int                       # Vertex offset for this bucket
    
    # Face counts
    inside_face_count: int                 # Faces contained entirely within bucket
    sticking_out_face_count: int           # Faces that extend beyond bucket boundary
```

---

## Layer Visibility System (Separate from Bucket Grids)

**IMPORTANT**: The bucket grid and dragon layer systems are ORTHOGONAL:

### 1. Dragon Layer System (8 Layers)
- **Controlled by**: `mesh.visibility_layer` (8-bit flag)
- **Location**: Set on meshes during import (import_mapgeo.py:620)
- **Values**:
  - Bit 0 (1): LAYER_1 (Base)
  - Bit 1 (2): LAYER_2 (Inferno/Fire)
  - Bit 2 (4): LAYER_3 (Mountain/Earth)
  - Bit 3 (8): LAYER_4 (Ocean)
  - Bit 4 (16): LAYER_5 (Cloud)
  - Bit 5 (32): LAYER_6 (Hextech)
  - Bit 6 (64): LAYER_7 (Chemtech)
  - Bit 7 (128): LAYER_8 (Void)
- **Purpose**: Filter mesh visibility based on elemental rift variant selected

### 2. Baron Hash System (Override)
- **Controlled by**: `mesh.baron_hash` and decoded layers
- **Location**: import_mapgeo.py:651-670
- **Defined in**: materials.bin (`ChildMapVisibilityController` entries)
- **Purpose**: Override dragon layers for Baron pit-specific variations
- **States**: Base, Cup, Tunnel, Upgraded (or custom per map)

---

## Bucket Grid Hash System (path_hash)

### What is path_hash?

- **Field**: `BucketGrid.path_hash` (stored in .mapgeo v15+)
- **Type**: 32-bit unsigned integer (hash)
- **Purpose**: **Links bucket grid to a visibility controller in materials.bin**
- **Lookup**: Materials file contains `ChildMapVisibilityController` entries keyed by this hash

### Current Problem in Addon

Current generation (ui_panel.py line 1858+):
- Creates bucket grids based on mesh objects in Blender
- **Generates a NAIVE buckets_per_side** (calculated from geometry bounds)
- **Does NOT link to materials.bin visibility controller**
- **Does NOT set path_hash correctly**
- **Result**: Bucket grids imported into Blender work for visualization, but create with path_hash=0

### Expected Behavior

When a bucket grid with path_hash != 0 exists:
1. Game looks up the path_hash in materials.bin
2. Finds the corresponding ChildMapVisibilityController
3. Uses visibility rules to determine which faces in the grid should render

---

## How Bucket Grids Relate to Visibility Layers

### The CORRECT Model

```
MESH
├─ visibility_layer (8-bit dragon flags) ─────────► Dragon Visibility
│
└─ baron_hash (if set) ─────┐
                             └─► Baron-specific Visibility (overrides dragon if configured)

BUCKET GRID
├─ path_hash ──────► Lookup in materials.bin ChildMapVisibilityController
│                    │
│                    └─► More complex visibility rules (per-face, per-state)
│
└─ face_visibility_flags ───► Per-face layer filtering (one byte per triangle)
```

### Layered Approach

1. **Mesh-level filtering**: visibility_layer or baron_hash determines if entire mesh is visible
2. **Bucket-level organization**: If mesh is visible, bucket grid organizes its geometry spatially
3. **Face-level filtering**: face_visibility_flags allow per-polygon visibility refinement

### Current Addon Limitation

Current addon treats each visibility layer as a separate bucket grid:
- Creates a bucket grid per layer (line 1708+)
- But doesn't capture the actual path_hash → materials relationship
- Result: Custom bucket grids have path_hash=0 and don't reflect game's actual visibility rules

---

## How to Properly Reproduce Bucket Grids

### Method 1: Copy from Original (Simplest)

```
1. Import .mapgeo file normally
   - Bucket grids are imported with correct path_hash
   - Stored in "BucketGrid" collection
2. Export .mapgeo
   - Bucket grids are exported as-is with preserved path_hash
3. Bucket grids are used without modification
```

**Advantage**: 100% accurate to original  
**Limitation**: Can't modify bucket grid generation

### Method 2: Generate from Scratch (Current Approach)

```
1. Set all mesh visibility_layer flags correctly
2. Create bucket grids per layer (ui_panel.py MAPGEO_OT_create_bucket_grid)
3. IMPORTANT: Determine path_hash for each layer
   - If per-layer, use materials.bin ChildMapVisibilityController lookups
   - Need to find hash for each layer's visibility rules
4. Store path_hash in bucket grid when exporting
```

**Challenge**: Finding correct path_hash for each layer

### Method 3: Hybrid (Recommended for proper support)

```
1. If exported bucket grid exists → use its path_hash mappings
2. If generating new → 
   a. For single-layer grids (path_hash=0) → works fine
   b. For multi-layer grids → need to look up in materials.bin first
```

---

## Materials.bin ChildMapVisibilityController

Location: materials.py (parsed binary)  
Structure: Hash-keyed entries of type `ChildMapVisibilityController`

### Controller Types

Based on baron_hash_system.md:

**Type 1: Direct Layer Controllers** ({c406a533})
- Simple layer inclusion/exclusion
- Example: Dragon layer 32 (Hextech) only

**Type 2: Complex Controllers**
- Multiple layers with logic (AND/OR/NOT)
- Baron states integration
- ParentMode affects visibility (Visible vs NotVisible)

**Type 3: Baron State Controllers**
- Controls baron pit variations
- States: Base (1), Cup (2), Tunnel (4), Upgraded (8)

### How to Link

```
1. Get hash string (8 hex digits without 0x prefix)
2. Search materials.bin for matching ChildMapVisibilityController key
3. Parse the controller data
4. Match layer bits to generated bucket grid layer
5. Store hash in BucketGrid.path_hash
```

---

## Current Implementation Status

### What Works
✓ Bucket grid visualization (imported grids render correctly)  
✓ Bucket grid export (with path_hash preserved)  
✓ Basic custom bucket grid generation (per-layer)  
✓ Mesh visibility_layer assignment  
✓ Baron hash decoding (for meshes)

### What Doesn't Work
✗ Generating bucket grid path_hash during custom creation  
✗ Linking custom bucket grids to materials.bin visibility controllers  
✗ Multi-layer bucket grid coordination (if needed)  
✗ Proper layer integration between baron system and bucket grids

### Issues from Current Approach

1. **path_hash = 0**: Custom grids don't reference visibility rules
   - Effect: Grids render but game would need to know to use basic logic
   
2. **Per-layer generation**: Creates separate grid per layer
   - Expected: Single grid with per-face visibility flags might be better
   - Current approach works but may not match game structure exactly

---

## Practical Implications

### For Map Import/Export
- ✓ Works perfectly (preserves original path_hash)
- ✓ Custom layers added via Blender work if manually linked

### For Custom Maps
- ⚠ Can create bucket grids but path_hash won't match materials.bin
- ⚠ Game engine would need fallback (often it does - treats 0x00 as visible-all)
- ✓ For visualization in Blender, works fine

### For Tools/Analysis
- ✓ Can visualize spatial partitioning
- ✓ Can see bucket boundaries and face distribution
- ✗ Can't automatically determine correct path_hash without materials.bin lookup

---

## Recommendations

### Short-term (Current addon state)
Keep current implementation - it works for:
- Preserving original bucket grids on import/export
- Creating visualizations for layer-based spatial partitions
- Basic bucket grid generation from mesh objects

### Medium-term (Proper support)
Implement path_hash lookup:
1. Parse ChildMapVisibilityController from loaded materials.bin
2. Match controller layer bits to each generated bucket grid layer
3. Store matching path_hash in BucketGrid before export
4. Add optional per-face visibility flags if materials indicate

### Long-term (Full compatibility)
Complete baron/dragon layer system integration:
1. Recognize when bucket grid should represent baron or dragon state
2. Properly set visibility flags based on controller rules
3. Handle complex visibility logic (ParentMode, multi-state conditions)
4. Export with all metadata for game engine interpretation

---

## Test Case: Map11 sodapop_srs

Current state:
- **Bucket grids in .mapgeo**: Has bucket grids with non-zero path_hash values
- **Materials file**: Contains ChildMapVisibilityController entries
- **Addon behavior**: 
  - Imports bucket grids → stores with original path_hash ✓
  - Creates custom grids → path_hash = 0
  - Exports → preserves original OR uses 0 for custom

To verify proper linking:
1. Extract path_hash values from imported bucket grids
2. Search materials.bin for matching ChildMapVisibilityController entries
3. Compare decoded layer bits with mesh visibility_layer values
4. Confirm correlation

---

## File References

- **mapgeo_parser.py**: BucketGrid/GeometryBucket definitions (lines 232-290)
- **mapgeo_parser.py**: _read_bucket_grids() (lines 548-610)
- **import_mapgeo.py**: import_bucket_grids() (lines 773-...)
- **import_mapgeo.py**: Mesh visibility_layer assignment (line 620)
- **import_mapgeo.py**: Baron hash handling (lines 651-670)
- **ui_panel.py**: MAPGEO_OT_create_bucket_grid (lines 1618-2037)
- **export_mapgeo.py**: bucket_grid_from_object() (lines 806-860)
- **baron_hash_system.md**: Full baron visibility documentation
- **league_material_enums.py**: Visibility flag definitions

