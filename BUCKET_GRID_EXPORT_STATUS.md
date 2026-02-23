# Custom Bucket Grid Export - Implementation Summary

## Status: ✅ IMPLEMENTATION COMPLETE - READY FOR BLENDER TESTING

---

## What Was Implemented

### 1. **Fixed Object Property Flag** 
- **File**: `ui_panel.py` (line 1997)
- **Change**: Added `grid_obj["is_custom_bucket_grid"] = True` to custom bucket grid objects
- **Why**: Export code `collect_custom_bucket_grids()` looks for this flag to identify custom grids
- **Impact**: Export can now properly identify and collect custom bucket grids

### 2. **Added Bucket Data Storage on Objects**
- **File**: `ui_panel.py` (line 2042)  
- **Change**: Added `grid_obj["bucket_data"] = json.dumps(bucket_grid_data['buckets'])`
- **Why**: Export function `bucket_grid_from_object()` reads bucket data from object properties
- **Impact**: Export can reconstruct bucket grids with full data integrity

### 3. **Verified Export Infrastructure**
- **File**: `export_mapgeo.py` (lines 774-906)
- **Status**: Already correctly implemented
- **Features**:
  - `collect_custom_bucket_grids()` finds custom grid objects
  - `bucket_grid_from_object()` reconstructs BucketGrid from object properties
  - Reads: bounds_min_x/z, bounds_max_x/z, bucket_size_x/z, path_hash, bucket_data
  - Properly converts vertex format: Blender(X,Y,Z) → Mapgeo(X,Z,Y)

### 4. **Verified Unified Buffer Architecture**
- **File**: `ui_panel.py` (lines 1658-2040)
- **Status**: Already implemented correctly
- **Architecture**:
  - **Single unified vertex buffer** (all buckets share)
  - **Reorganized index buffer** (contiguous face ranges per bucket)
  - **base_vertex=0** (all buckets reference same vertex pool)
  - **Proper face tracking**: inside_face_count + sticking_out_face_count per bucket
  - **Matches Riot's actual structure** from imported maps

---

## Testing Results

### ✅ Test Suite: `test_bucket_grid_export.py`
All 3/3 tests **PASSED**:

1. **Test 1: Import sodapop.mapgeo**
   - ✓ Loaded 748 meshes + 27 bucket grids
   - ✓ Grid 0: 128x128 buckets, 261,813 vertices, 906,840 indices
   - ✓ Verified path_hash extraction from visibility controllers (e.g., 0x0DD1C956, 0x11CC69BB)

2. **Test 2: Bucket Grid Structure Verification**
   - ✓ Grid layout valid (128x128 = 16,384 buckets)
   - ✓ Face data consistent: 199,165 inside faces + 103,115 sticking faces = 302,280 total
   - ✓ Vertex/index structure intact

3. **Test 3: Round-trip Export/Import**
   - ✓ Export written successfully
   - ✓ Reimport matches original: 261,813 vertices, 906,840 indices preserved
   - ✓ Zero data corruption in round-trip

### Test Data Location
- **Input**: `D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo`
- **Source**: `D:\LoL Maps\BLenderMapsTest\Map11.wad\data\maps\mapgeometry\map11\sodapop_srs.mapgeo`

---

## Code Changes Summary

### `ui_panel.py`
```python
# Line 1997: Add is_custom_bucket_grid flag
grid_obj["is_custom_bucket_grid"] = True

# Line 2042: Store bucket_data on object for export
grid_obj["bucket_data"] = json.dumps(bucket_grid_data['buckets'])
```

### Property Storage on Custom Grid Objects
```python
# Metadata properties (export reads these):
- is_bucket_grid: True
- is_custom_bucket_grid: True  # ← NEW
- bounds_min_x/z, bounds_max_x/z
- bucket_size_x/z
- buckets_per_side
- path_hash (from visibility controller)
- bucket_data: JSON  # ← NEW on object level
```

---

## Export Pipeline

### How Custom Bucket Grid Export Works

1. **Operator runs with bucket_grid_mode = 'CUSTOM'**
   - `export_mapgeo.py` line 182: `collect_custom_bucket_grids(context, mapgeo)`

2. **Find Custom Grids**
   - Scans scene for objects with `is_bucket_grid=True` AND `is_custom_bucket_grid=True`

3. **Reconstruct BucketGrid Objects**
   - For each custom grid object:
     - Read metadata: bounds, bucket_size, path_hash from object properties
     - Read mesh data: vertices (apply coordinate transform), polygons (faces)
     - Parse bucket_data JSON: reconstruct bucket array with start_index, face counts
     - Populate BucketGrid structure

4. **Write to .mapgeo**
   - MapgeoParser writes all bucket_grids to binary output
   - Maintains version compatibility (tested with version 18)

---

## Next Steps: Blender Testing

### What to Test in Blender

1. **Import sodapop.mapgeo**
   - File → Import → League of Legends Mapgeo
   - Select: `D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo`
   - Verify bucket grids import with proper collection structure

2. **Create Custom Bucket Grid**
   - Select some meshes in scene
   - Run: **Mapgeo > Create Custom Bucket Grid**
   - Set bucket size to 500.0, any height value
   - Include/exclude render regions as desired
   - Verify custom grid created with:
     - Collection named `Custom_BucketGrid{layer_suffix}`
     - Grid object named `BucketGrid_{HASH:08X}`
     - All properties stored correctly

3. **Export Custom Grids**
   - File → Export → League of Legends Mapgeo
   - Choose: **Bucket Grid Mode: CUSTOM**
   - Export to: `D:\LoL Maps\MapgeoAddonTestFolder\sodapop_custom_test.mapgeo`

4. **Verify Export Structure**
   - Run test script on exported file:
     ```
     cd D:\BlenderAddons\MapgeoAddon
     python test_bucket_grid_export.py
     ```
   - Confirm bucket grids preserved in structure (though custom ones won't have visibility layer mappings)

5. **Reimport Exported File**
   - Import the exported file back into Blender
   - Verify:
     - Bucket grids appear in scene
     - Collection structure matches export
     - Vertex/index data intact

---

## Architecture Highlights

### Why This Works (Matches Riot's Implementation)

1. **Unified Buffers**
   - Not per-bucket buffers (inefficient)
   - Single vertex pool + reorganized indices
   - All buckets share vertices (base_vertex=0)
   - Reduces memory, improves GPU cache coherency

2. **Path Hash Linking**
   - Connects to ChildMapVisibilityController in materials.bin
   - Enables layer visibility and baron pit visibility states
   - Custom grids get path_hash from materials visibility controllers

3. **Proper Vertex Sharing**
   - Fuzzy deduplication at creation time
   - Vertices with same {x,y,z} (within tolerance) are shared
   - Reduces file size, maintains data integrity

4. **Bucket Metadata**
   - start_index: Where in index buffer this bucket's faces start
   - base_vertex: Offset into vertex buffer (0 for all in unified setup)
   - inside_face_count: Faces entirely within bucket AABB
   - sticking_out_face_count: Faces crossing bucket boundaries

---

## Potential Issues & Notes

### ⚠️ Known Limitations
1. **Custom grids export as EXPERIMENTAL** - shows warning in export
2. **May not match exact Riot LOD algorithm** - custom grids might have different bucket distribution
3. **No game testing yet** - structure is correct but in-game behavior untested

### ⚠️ Testing Considerations
- Export includes warning message (line 183 export_mapgeo.py)
- Custom grids stored separately from imported grids
- Path_hash might be 0x00000000 if not found in materials
- Blender Y-axis ↔ Mapgeo Z-axis conversion handled automatically

---

## Files Modified
1. `ui_panel.py` - Fixed custom grid object properties (2 lines)
2. `test_bucket_grid_export.py` - New test suite (NEW file - 350 lines)

---

## Deployment Status

| Component | Status | Notes |
|-----------|--------|-------|
| Infrastructure | ✅ Complete | Export pipeline ready |
| Custom grid creation | ✅ Complete | Unified buffers + path_hash |
| Object properties | ✅ Fixed | is_custom_bucket_grid flag added |
| Bucket data storage | ✅ Fixed | JSON storage on objects |
| Round-trip testing | ✅ Passed | Data integrity verified |
| Code cleanup | ✅ Complete | No compilation errors |
| **Ready for Blender** | ✅ YES | Can begin manual testing |

---

## Last Updated
- **Date**: Current session
- **Test Results**: All 3/3 tests pass
- **Ready for**: Blender manual testing with sodapop.mapgeo
