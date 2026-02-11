# Baron Hash Visibility System

## Overview

The Baron Hash system is a **secondary visibility controller system** that **overrides the Dragon Layer System** when a mesh has a baron_hash assigned.

## Two Visibility Systems

### 1. Dragon Layer System (Standard)
Used for elemental rift variations. Controlled by the `visibility_layer` property (bits 0-7):

- **Bit 0 (1)**: Base
- **Bit 1 (2)**: Inferno (Fire)
- **Bit 2 (4)**: Mountain (Earth)
- **Bit 3 (8)**: Ocean
- **Bit 4 (16)**: Cloud
- **Bit 5 (32)**: Hextech
- **Bit 6 (64)**: Chemtech
- **Bit 7 (128)**: Void

Defined in Map11.bin as `VisibilityFlagDefines` (hash: default)

### 2. Baron Hash System (Override)
Used for Baron-specific map variations. Controlled by the `baron_hash` property.

Defined in Map11.bin as hash `0xd31ac6ce` with 4 states:

- **Base** (Bit 0): Default state
- **Cup** (Bit 1): Cup variation
- **Tunnel** (Bit 2): Tunnel variation
- **Upgraded** (Bit 3): Upgraded variation

## How It Works

### Visibility Logic (Corrected in v0.0.6)

1. **When baron_hash is NOT set (00000000)**:
   - Mesh uses the Dragon Layer System
   - Visibility controlled by `visibility_layer` bits
   - Mesh appears in corresponding elemental rift variations
   - Visible on ALL baron pit states (Base, Cup, Tunnel, Upgraded)

2. **When baron_hash IS set BUT has no dragon_layers**:
   - Mesh uses the Dragon Layer System for dragon visibility
   - Visibility controlled by `visibility_layer` bits
   - Baron pit state controlled by `baron_layers_decoded` 
   - Appears only on specified baron pit states

3. **When baron_hash IS set AND has dragon_layers** (OVERRIDE MODE):
   - **Baron hash OVERRIDES the Dragon Layer System**
   - `visibility_layer` is **IGNORED** for dragon visibility
   - Dragon visibility determined by `baron_dragon_layers_decoded`
   - Baron pit state controlled by `baron_layers_decoded`
   - **Example**: If baron hash decodes to dragon_layers=[32] (Hextech), mesh appears ONLY on Hextech, regardless of `visibility_layer` value
   
### Visibility Check Priority
```python
# STEP 1: Dragon visibility
if has_baron_hash and has_baron_dragon_layers:
    # OVERRIDE: Use baron dragon layers
    dragon_visible = (current_dragon in baron_dragon_layers)
else:
    # STANDARD: Use visibility_layer
    dragon_visible = (visibility_layer & current_dragon_flag)

# STEP 2: Baron pit visibility
if has_baron_hash and has_baron_layers:
    baron_visible = (current_baron_state in baron_layers)
else:
    baron_visible = True  # Visible on all baron states

# FINAL
visible = dragon_visible AND baron_visible
```

## Materials.bin Structure

Baron hash controllers are defined in materials.bin with several types:

### Type 1: Direct Layer Controllers ({c406a533})
```json
"{8e6a128e}": {
  "PathHash": "{8e6a128e}",
  "name": "{5086eb70}",
  "DefaultVisible": false,
  "{27639032}": 64,
  "__type": "{c406a533}"
}
```

### Type 2: Child Controllers (ChildMapVisibilityController)
```json
"{5e652742}": {
  "PathHash": "{5e652742}",
  "Parents": [
    "{8e6a128e}",
    "{4f0b2a3e}",
    "{48106271}",
    "{d1a17399}",
    "{2b8dbdee}",
    "{3c5b24f7}"
  ],
  "ParentMode": 3,
  "__type": "ChildMapVisibilityController"
}
```

### Type 3: Named Controllers ({e07edfa4})
```json
"{7dcbc884}": {
  "PathHash": "{7dcbc884}",
  "name": "{34e04176}",
  "__type": "{e07edfa4}"
}
```

### Type 4: Baron State Controllers ({ec733fe2})
```json
"{f4968631}": {
  "PathHash": "{f4968631}",
  "name": "{6204d1e5}",
  "{8bff8cdf}": 1,
  "__type": "{ec733fe2}"
}
```

## ParentMode Values

- **1**: OR mode - visible if ANY parent is active
- **3**: AND mode - visible only if ALL parents are active (common for complex combinations)

## Example: Baron Hash 5E652742

This hash references parents for all 6 dragon layers with ParentMode=3 (AND):
- Requires ALL elemental variations (Inferno, Mountain, Ocean, Cloud, Hextech, Chemtech) to be active
- Used for meshes that appear in all elemental states when Baron system is active

## In Blender Addon

- **Split Filter System**: Separate dropdowns for dragon layer (8 variants) and baron pit state (4 states)
- **Properties Panel**: Shows baron hash status with decoded layers
- **Baron Pit Layers**: Displays which baron pit states the mesh is visible on (Base, Cup, Tunnel, Upgraded)
- **Referenced Dragon Layers**: Shows dragon layers from baron hash (OVERRIDES visibility_layer when present)
- **Parent Mode**: Displays whether visibility uses AND (all) or OR (any) logic
- **Baron Hash Assignment**: Can assign custom baron hash values (8 hex characters)
- **Layer Collections**: Meshes organized into both dragon layer and baron state collections
- **Automatic Decoding**: When materials.bin.json is loaded during import, baron hashes are automatically decoded
- **Override Behavior**: Baron dragon layers take precedence over visibility_layer when present

## Baron Hash Decoding Process

1. **Parse materials.bin.json** - Index all visibility controllers by PathHash (format: `"{5e652742}"`)
2. **Find Controller** - Look up the baron hash in the indexed controllers
3. **Check Type** - Identify if it's a ChildMapVisibilityController via `__type` field
4. **Get Parents** - Extract parent references from the Parents list
5. **Resolve Parents** - For each parent:
   - Check if it's a dragon layer controller (`__type`: `"{c406a533}"` with `"{27639032}"` property)
   - Check if it's a baron layer controller (`__type`: `"{ec733fe2}"` with `"{8bff8cdf}"` property)
   - If it's another child controller, recursively resolve its parents
6. **Apply ParentMode** - Combine parent visibility using AND or OR logic
7. **Store Results** - Save decoded layers and parent mode as custom properties

**Note**: JSON format uses curly braces around hash values: `"{5e652742}"` instead of `0x5e652742`

## visibility_layer`: Standard dragon layer bitfield (0-255) - IGNORED if baron hash has dragon_layers
- `baron_hash`: The raw hash value (e.g., "5E652742")
- `baron_parent_mode`: The parent mode (1=OR, 3=AND)
- `baron_layers_decoded`: List of baron pit layer indices (e.g., "[0, 1, 2, 3]")
- `baron_dragon_layers_decoded`: List of dragon layer bits (e.g., "[2, 4, 8, 16, 32, 64]") - OVERRIDES visibility_layer when present

## Version History

### v0.0.6 (2026-02-11)
- **Fixed**: Baron hash visibility logic corrected
- Baron dragon layers now properly OVERRIDE visibility_layer (not add to it)
- Split visibility check: dragon layers OR'd, baron pit layers filtered independently

### v0.0.5 (2026-02-11)
- Baron state viewport filtering (4 states)
- Baron state collections
- Split dragon/baron filter UI

### v0.0.4 (2026-02-11)
- Initial baron hash decoding implementation
- materials.bin.json parser

## Future Enhancements

✓ **Completed**: Parse materials.bin.json to read ChildMapVisibilityController definitions
✓ **Completed**: Decode parent references and ParentMode
✓ **Completed**: Show which dragon layers the baron hash references
✓ **Completed**: Implement proper baron state filtering in viewport
✓ **Completed**: Add collection organization based on decoded baron layers
✓ **Completed**: Fix baron hash override behavior (v0.0.6)
✓ **Completed**: Implement proper baron state filtering in viewport
✓ **Completed**: Add collection organization based on decoded baron layers
- **TODO**: Export baron hash controllers when creating new .mapgeo files
