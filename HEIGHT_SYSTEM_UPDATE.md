# Height Range System Update

## New UI Changes

The **Create Custom Bucket Grid** operator now has an improved height system:

### Before
- **Height**: Single value (Z coordinate for flat bounding box)
- Limited to showing the grid at one height level

### After  
- **Min Height (Z)**: Minimum Z value for the bounding box (default: -10000.0)
- **Max Height (Z)**: Maximum Z value for the bounding box (default: 10000.0)
- **Visualization**: 3D wireframe box showing the height range

## Usage

When creating a custom bucket grid:

```
Bucket Size: 500.0           (size of each grid cell)
Height Range (Z):
  Min: -1000.0               (bottom of the box)
  Max: 5000.0                (top of the box)
Include Render Regions: [ ]
```

The bounding box will now display as a complete 3D wireframe box from z_min to z_max, making it easier to visualize the vertical extent of the bucket grid.

## Example Values

### Wide Range (includes all vertical space)
```
Min Height: -10000.0
Max Height: 20000.0
```

### Narrow Range (specific vertical band)
```
Min Height: 2500.0
Max Height: 4000.0
```

### Single Level (old behavior)
```
Min Height: 0.0
Max Height: 0.0
```

---

## Vertex Index Limitation

### ⚠️ Important: 65535 Vertex Limit

Bucket grids are stored using **ushort** (unsigned 16-bit) integers for vertex indices, which means:
- **Maximum vertices per grid**: 65,535
- **When exceeded**: Indices get clamped, causing potential visual/structural issues

### When This Occurs

Large bucket grids with many meshes can exceed this limit, especially:
- **Layer 255 (Baron pit)**: Often includes many meshes → easily exceeds limit
- **Large custom grids**: Using small bucket size or including many objects
- **High-detail areas**: Dense mesh geometry

### Export Warning

When exporting, if vertex count exceeds 65535, you'll see:
```
WARNING: Vertex index 68318 exceeds ushort max (65535)
  → This bucket grid has 68318 total vertices (limit: 65535)
  → Consider reducing bucket size or splitting mesh by visibility_layer
```

### How to Fix

**Option 1: Reduce Bucket Size** (Less Buckets Per Grid)
- Larger bucket size = fewer buckets = fewer potential issues
- Trade-off: Less detailed spatial partitioning
- Example: Use 750.0 instead of 500.0

**Option 2: Split by Visibility Layer** (Multiple Grids)
- Create separate grids for different visibility layers
- Instead of: One large grid with layer 255
- Try: Separate grids for layers 1, 2, 4, 8, 16, 32, 64, and 255
- Each layer individually may be under 65535 vertices

**Option 3: Select Fewer Objects**
- Create grids from subsets of meshes
- Group meshes by area/region
- Create multiple grids covering different areas

**Option 4: Increase Bucket Size Further**
- Use very large bucket sizes (800-1000) for overview-level grids
- Creates fewer, larger buckets
- Reduces vertex count

### Technical Details

The issue occurs because:
1. Custom bucket grid creation collects all triangles from selected meshes
2. Vertices are fuzzy-deduplicated (same x,y,z within tolerance)
3. Large/dense areas naturally have many unique vertices
4. Unified buffer stores all vertices: if >65535, indices can't reference them properly

Riot's actual bucket grids avoid this through:
- Multiple bucket grids per map (for different areas)
- Layer-specific visibility (only meshes for that layer in the grid)
- Optimized vertex deduplication
- Careful object selection per grid

---

## Example Workflow

### Create Multi-Layer Bucket Grids

```
For Map11 with Layer 255 (Baron pit) having too many vertices:

Step 1: Select all layer 255 meshes
→ Create Custom Bucket Grid
  Bucket Size: 500.0
  Min Height: floor_level (e.g., -100)
  Max Height: ceiling_level (e.g., 5000)
  ✓ Works if vertices < 65535

If appears "WARNING: Vertex index exceeds ushort max":

Step 2: Either
  A) Use larger bucket size (700.0 or higher)
  B) Select only baron pit geometry subset
  C) Split into two grids (baron high + baron low areas)
```

### Create Area-Specific Grids

```
Instead of one huge grid, create multiple:

Grid 1: Top lane area
Grid 2: Middle lane area
Grid 3: Bottom lane area
Grid 4: Jungle area
...
```

Each grid will have fewer vertices and stay under the 65535 limit.

---

## Current Status

- ✅ New height min/max UI implemented
- ✅ 3D wireframe box visualization
- ✅ Better export warnings for vertex limits
- ✅ Suggestions for fixing overflow issues

## Recommendations

1. **For production maps**: Stick with created separate grids per area/layer
2. **For testing**: Use larger bucket sizes to avoid vertex limits
3. **For debugging**: Watch export console for "exceeds ushort max" warnings

---

## Next Steps

If you encounter vertex index warnings during export:

1. Check the export console output for exact vertex count
2. Try one of the fix options above (reduce bucket size, split layers, etc.)
3. Re-create the bucket grid with adjusted parameters
4. Re-export and verify no warnings appear

The warnings are advisory - the export will still complete, but exported grids may not render correctly in-game if indices are significantly clamped.
