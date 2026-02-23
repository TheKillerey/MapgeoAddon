# Quick Start: Custom Bucket Grid Export Testing

## Pre-Test Checklist ✓
- ✅ sodapop.mapgeo available in `D:\LoL Maps\MapgeoAddonTestFolder\`
- ✅ All code changes deployed
- ✅ Test infrastructure validated (3/3 tests pass)
- ✅ Export pipeline ready

---

## Quick Test Workflow (5-10 minutes)

### Step 1: Open Blender
```
Create new Blender 5.x project
```

### Step 2: Import sodapop.mapgeo
```
File → Import → League of Legends Mapgeo (.mapgeo)
Select: D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo
Click: Import
⏱ Wait: ~30-60 seconds for import to complete
```

### Step 3: Create Custom Bucket Grid
```
Open Scene Properties → Mapgeo panel
1. Select a few mesh objects from scene (select 5-10 objects)
2. Click: "Mapgeo > Create Custom Bucket Grid"
   OR: Right-click on object → Mapgeo > Create Custom Bucket Grid

3. Dialog appears:
   - Bucket Size: 500.0 (keep default)
   - Height: 0.0 (keep default)
   - Include Render Regions: False (keep default)
   - Click: OK
   
⏱ Wait: ~10-30 seconds for grid generation
```

### Step 4: Verify Custom Grid Created
```
Outliner (top right):
✓ Look for collection: "Custom_BucketGrid0" (or similar)
✓ Inside: Grid object named "BucketGrid_XXXXXXXX" (hash name)

View (3D):
✓ A semi-transparent red mesh should appear (bucket grid visualization)

Properties:
✓ Click grid object in outliner
✓ Custom Properties (scroll down in properties)
  - is_bucket_grid: True
  - is_custom_bucket_grid: True ← NEW
  - path_hash: (hex value or 00000000)
  - bounds_min_x, bounds_min_z, etc.
```

### Step 5: Export Custom Grids
```
File → Export → League of Legends Mapgeo (.mapgeo)
Path: D:\LoL Maps\MapgeoAddonTestFolder\sodapop_custom_test.mapgeo
Options:
  - Bucket Grid Mode: CUSTOM ← CRITICAL!
  - Click: Export Mapgeo

Console Output (should show):
  "Found N custom bucket grid mesh(es)"
  "Exported custom bucket grid: BucketGrid_XXXXXXXX"
```

### Step 6: Verify Export
```
Command line:
cd D:\BlenderAddons\MapgeoAddon
python test_bucket_grid_export.py

Then check exported file:
python -c "
import sys
sys.path.insert(0, '.')
from mapgeo_parser import MapgeoParser
parser = MapgeoParser()
mapgeo = parser.read('D:\\LoL Maps\\MapgeoAddonTestFolder\\sodapop_custom_test.mapgeo')
print(f'Bucket grids in exported file: {len(mapgeo.bucket_grids)}')
if mapgeo.bucket_grids:
    g = mapgeo.bucket_grids[-1]  # Check the custom grid (should be last)
    print(f'Last grid: {len(g.vertices)} vertices, {len(g.indices)} indices')
"
```

---

## Expected Results

### ✓ If Everything Works:
1. Custom grid appears in scene as red transparent mesh
2. Grid object has `is_custom_bucket_grid: True` property
3. Export completes without errors
4. Test script verifies data structure is valid
5. Round-trip test shows data preserved

### ✗ If Problems Occur:

**"Create Custom Bucket Grid button does nothing"**
- Check Scene properties panel
- Verify meshes are selected
- Look at System Console for error messages

**"Export button grayed out"**
- File a proper name with .mapgeo extension
- Make sure you selected "Bucket Grid Mode: CUSTOM"

**"Export completes but finds 0 custom grids"**
- Verify collection is named "Custom_BucketGrid*"
- Verify grid object has `is_custom_bucket_grid` property
- Check System Console for warnings

**"Data seems wrong in verification"**
- Run: `python test_bucket_grid_export.py` on exported file
- Compare bucket counts, vertex counts, etc.

---

## What to Check in System Console

### Successful Export should show:
```
mpAddon (Line X, in import_bucket_grids
Bucket Grid Collection: Collection.002 (is_bucket_grid_collection=True)
...
Found N custom bucket grid mesh(es)
Exported custom bucket grid: BucketGrid_XXXXXXXX
...
Successfully exported to sodapop_custom_test.mapgeo
```

### If You See These - It's Working:
- ✅ "Found N custom bucket grid mesh(es)"
- ✅ "Exported custom bucket grid:"
- ✅ No "ERROR" messages
- ✅ "Successfully exported to"

---

## Quick Dataset Summary

| Property | Value |
|----------|-------|
| Test Map | sodapop (Runeterra/Infernal Showdown) |
| Original Grids | 27 bucket grids |
| Meshes | 748 |
| Largest Grid | 128x128 buckets |
| File Size | ~15 MB |

---

## Troubleshooting Checklist

- [ ] Blender version 5.0+?
- [ ] Addon properly installed in Blender?
- [ ] Materials data path configured correctly?
- [ ] sodapop.mapgeo exists in test folder?
- [ ] Python test script runs successfully?
- [ ] Custom grid object has required properties?
- [ ] Export mode set to "CUSTOM"?
- [ ] Export file path ends with .mapgeo?

---

## Next: After Successful Export

If export succeeds:

1. **Keep sodapop_custom_test.mapgeo** for later game testing
2. **Document any visual differences** compared to original grid
3. **Try different bucket sizes** (200, 350, 500, 750)
4. **Create grids from different layer objects** (different visibility_layer values)
5. **Compare path_hash values** with materials visibility controllers

---

## Contact/Debug

If tests fail after export:
1. Check System Console output
2. Run: `python test_bucket_grid_export.py` on exported file
3. Look for specific error messages in console
4. Verify all properties are present on custom grid object
