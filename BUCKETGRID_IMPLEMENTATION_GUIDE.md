# Bucket Grid Implementation Guide

## Quick Fix: Adding path_hash Support

### Current Problem
When creating custom bucket grids (ui_panel.py MAPGEO_OT_create_bucket_grid), the addon:
1. ✓ Correctly generates spatial partitioning structure
2. ✗ Sets `path_hash = 0` (loses visibility controller link)
3. ✗ Creates separate grid per visibility layer

### The Fix (3 Steps)

#### Step 1: Load Visibility Controller Mapping
Before generating bucket grids, build a map of layer → hash:

```python
def _get_layer_to_hash_mapping(materials_bin_path):
    """
    Extract ChildMapVisibilityController entries from materials.bin
    Returns: dict[layer_bit] → path_hash
    
    Example result:
    {
        1: 0x12345678,    # Base layer → hash
        2: 0xABCDEF00,    # Inferno layer → hash
        ...
    }
    """
    # For Map11, query materials.bin for ChildMapVisibilityController entries
    # Filter by layer bits (1, 2, 4, 8, 16, 32, 64, 128)
    # Return hash→layer mapping
    pass
```

#### Step 2: Assign path_hash When Creating Each Layer Grid
In ui_panel.py around line 1920:

```python
# CURRENT CODE (line 1920):
grid_obj = bpy.data.objects.new(f"CustomBucketGrid{layer_suffix}_Mesh", grid_mesh)
bg_collection.objects.link(grid_obj)

# CHANGE TO:
grid_obj = bpy.data.objects.new(f"CustomBucketGrid{layer_suffix}_Mesh", grid_mesh)
bg_collection.objects.link(grid_obj)

# ADD: Store path_hash if available
if layer_to_hash and visibility_layer in layer_to_hash:
    path_hash = layer_to_hash[visibility_layer]
    grid_obj["path_hash"] = path_hash  # Store for export
```

#### Step 3: Use path_hash When Exporting
In export_mapgeo.py around line 820:

```python
# CURRENT CODE:
grid.path_hash = 0  # Always zero

# CHANGE TO:
grid.path_hash = obj.get("path_hash", 0)  # Use stored hash, default 0 if not set
```

### Result
- Custom bucket grids with correct path_hash values
- Proper linking to materials.bin visibility controllers
- Game engine can properly interpret visibility rules

---

## Understanding the Layer Mapping

### Dragon Layers (Standard System)
```
Bit  Value  Name        Material Flag
0    1      Base        (default, always visible)
1    2      Inferno     Fire variant
2    4      Mountain    earth variant  
3    8      Ocean       water variant
4    16     Cloud       flying change
5    32     Hextech     tech variant
6    64     Chemtech    toxic variant
7    128    Void        LAYER_8
```

### How Hash Links to Layer
In materials.bin, each ChildMapVisibilityController has:
- A hash key (unique identifier)
- A set of layer bits it applies to
- Visibility rules (which states make it visible)

Example:
```
Hash: 0x12345678
Type: ChildMapVisibilityController
Layers: [1]           # Only applies to Base layer
Visibility: Always    # Always visible on Base

Hash: 0xABCDEF00
Type: ChildMapVisibilityController  
Layers: [2, 4, 8]    # Applies to Inferno + Ocean + Cloud
Visibility: Not Ocean # Visible on Inferno and Cloud, not Ocean

Hash: 0x00000000
Type: Default
Layers: Any
Visibility: As per mesh visibility_layer
```

---

## Alternative Approach: Per-Face Visibility Flags

### What Are face_visibility_flags?

In BucketGrid structure:
```python
face_visibility_flags: List[int]  # One byte per triangle
```

**Option**: Instead of separate grid per layer, use ONE grid with per-face visibility:

```
Bucket Grid (Single)
├─ vertices: all geometry shared
├─ indices: unified index buffer
├─ buckets: spatial organization
└─ face_visibility_flags: [0xFF, 0x01, 0x02, ...]
                           each byte = which layers can see this face
```

**Byte encoding** (example - depends on implementation):
```
Face 0: 0xFF = visible on all layers (binary 11111111)
Face 1: 0x01 = visible on layer 1 only (binary 00000001 = Base)
Face 2: 0x0E = visible on layers 2,3,4 (binary 00001110 = Inferno+Mountain+Ocean)
Face 3: 0x00 = not visible anywhere
```

### Advantages
- Single bucket grid structure (smaller file)
- Proper layer filtering at face level
- Matches game engine design better

### Current Addon Limitation
Currently creates separate bucket grid per layer - which works but is less efficient than per-face flags.

---

## Materials.bin QueryTool Idea

To properly support bucket grid generation, could create helper:

```python
class MaterialsVisibilityIndex:
    """Index visibility controllers from materials.bin for quick lookup"""
    
    def __init__(self, materials_data):
        self.layer_to_hashes = {}  # layer_bit → [hashes]
        self.hash_to_layers = {}   # hash → [layer_bits]
        self.hash_to_rules = {}    # hash → VisibilityRules
        self._build_index(materials_data)
    
    def _build_index(self, materials_data):
        # Parse materials.bin ChildMapVisibilityController entries
        # Build mappings for quick lookup
        pass
    
    def get_hash_for_layer(self, layer_bit):
        """Find primary hash for this layer"""
        return self.layer_to_hashes.get(layer_bit, [0])[0]
    
    def get_layers_for_hash(self, path_hash):
        """Find which layers this hash applies to"""
        return self.hash_to_layers.get(path_hash, [])
    
    def get_visibility_rules(self, path_hash):
        """Get the visibility rules for this hash"""
        return self.hash_to_rules.get(path_hash)
```

---

## Why Current Implementation Works (Despite path_hash=0)

Game engine fallback behavior:
1. If path_hash == 0 → No visibility controller link
2. Game uses mesh's visibility_layer bits directly
3. Bucket grid is treated as "always visible if mesh is visible"
4. Per-face flags are ignored if unavailable

**Result**: Works for visualization and basic export, but loses complex visibility rules.

---

## Testing Verification

To confirm bucket grid structure is correct:

```python
# Check imported bucket grids
for grid in mapgeo.bucket_grids:
    print(f"path_hash: 0x{grid.path_hash:08X}")
    print(f"Grid size: {grid.buckets_per_side}x{grid.buckets_per_side}")
    print(f"Faces: {len(grid.indices)//3}")
    print(f"Vertices: {len(grid.vertices)}")
    if grid.path_hash != 0:
        print(f"  → Has visibility controller link")
    if grid.face_visibility_flags:
        print(f"  → Has per-face visibility ({len(grid.face_visibility_flags)} flags)")
```

---

## Implementation Priority

1. **Essential** (breaks export): Preserve path_hash on export
2. **Important** (better correctness): Set path_hash when creating custom grids
3. **Nice-to-have** (optimization): Support per-face visibility flags
4. **Advanced** (full compatibility): Complex visibility rules from materials.bin

