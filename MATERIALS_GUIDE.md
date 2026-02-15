# League of Legends Materials System - Complete Guide

## Overview

This guide covers the complete materials system for the Mapgeo Addon. The addon provides full Python-based import/export for League's `.materials.py` files, including material editing capabilities in Blender.

**Key Statistics:**
- **9,509 total materials** across all League maps
- **195 material files** in the installation
- **282.95 MB** of material data
- **627 unique parameters** documented
- **71 unique texture samplers** identified
- **Multiple shader systems** with blend factor support

---

## Materials Format Overview

League materials are stored in Python-based `.materials.py` files with a custom structure:

```
type: string = "PROP"
version: u32 = 3
entries: map[hash, embed] = {
    "Materials/Path/To/Material_MAT" = StaticMaterialDef { ... }
}
```

### Material Structure

Each `StaticMaterialDef` contains:

1. **name**: Full material identifier (e.g., `"Maps/KitPieces/SRX/Materials/Default/Earth_River_DM"`)
2. **type**: Material type (u32, typically 0)
3. **samplerValues**: List of texture samplers (diffuse, masks, noise, etc.)
4. **paramValues**: Shader parameters (vec4 values for colors, speeds, etc.)
5. **switches**: Boolean features (ENV_TRANSITION, DEBUG_VIEW_MASK, etc.)
6. **shaderMacros**: Compile-time shader constants
7. **techniques**: Rendering techniques with pass definitions
8. **childTechniques**: Technique variations

---

## Texture Samplers (71 Types)

### Primary Diffuse Textures
- `DiffuseTexture` - Main color texture (most common)
- `Diffuse_Texture` - Alternative naming variant
- `ColorTexture` - Color-based diffuse

### Secondary Textures
- `Mask_Texture` - Mask/alpha channel (97 files)
- `Noise_Texture` - Procedural noise (42 files)
- `Emission_Tex` - Emissive/glow maps (16-18 files)
- `Normal_Map` - Implicit normal mapping
- `Distortion_Texture` - UV distortion effects

### Special Effects
- `FlowMap` - Flow/water direction maps
- `Gradient_Texture` - Color gradients
- `Blink_Texture` - Blinking/pulsing effects
- `GlitterBlendingTexture` - Sparkle effects
- `VertexDeformationMask` - WPO/vertex animation masks

### Texture Address Modes
```
addressU: u32 = 1  # 0=Clamp, 1=Wrap, etc.
addressV: u32 = 1
addressW: u32 = 1
```

---

## Material Parameters (Selected Examples)

Parameters stored as `vec4` (4 float values):

### Color Parameters
- `Color`: RGBA color specification
- `Color_Blend`: Blend between two colors  
- `Color_Multiply`: Multiplicative color
- `Tint_Color`: Color tinting
- `BloomColor`: Bloom/glow color

### Animation Parameters
- `Transition_Speed_Factor`: Animation speed
- `BPM`: Beats per minute for rhythm-based animation
- `Bobbing_Rate`: Oscillation speed
- `Alpha_Scroll_Tiling`: Scrolling texture tiling

### Deformation Parameters
- `DeformWaveController`: Wave animation controller
- `DeformWaveStrength`: Wave intensity
- `DeformMaskStrength`: Deformation mask strength
- `Bend_Time`: Bending animation time
- `Bend_XYZ_Offset`: XYZ bending offset

### Quality Parameters
- `AlphaTestValue`: Alpha threshold (0.0-1.0)
- `Alpha_Test_Value`: Alternative naming
- `AlphaClipValue`: Alpha clipping threshold

---

## Material Switches (Boolean Features)

Commonly used switches across materials:

- `ENV_TRANSITION`: Environment transition effect
- `DEBUG_VIEW_MASK`: Debug visualization
- `USE_WS_MASK`: World-space masking
- `DISABLE_FIRE_FX`: Disable fire effects
- `DISABLE_SHADOWS`: Shadow rendering toggle
- `PREMULTIPLIED_ALPHA`: Alpha blending mode

---

## Shader Macros

Compile-time shader constants affecting rendering:

- `NO_BAKED_LIGHTING`: Disable baked lighting (1,142 uses)
- `DISABLE_DEPTH_FOG`: Disable depth-based fog
- `PREMULTIPLIED_ALPHA`: Use premultiplied alpha blending
- `DISABLE_SHADOWS`: Skip shadow rendering
- `ENV_TRANSITION`: Enable environment transition
- Custom values range from "0" to "1"

---

## Shader Links

Materials reference shader programs:

**Common Shader Paths:**
- `Shaders/StaticMesh/SRX_Blend_*` - Seasonal (SRX) shaders
- `Shaders/StaticMesh/Infernal_*` - Infernal theme shaders
- `Shaders/StaticMesh/Default_*` - Default terrain shaders
- `Shaders/StaticMesh/Water_*` - Water-specific shaders

Shaders are referenced via `link` type (not full paths):
```
shader: link = "Shaders/StaticMesh/SRX_Blend_Earth_Rocks"
```

---

## Blend Factors

Controlling transparency and color blending:

```
blendEnable: bool = true
srcColorBlendFactor: u32 = 6   # Source blend factor
dstColorBlendFactor: u32 = 7   # Destination blend factor
srcAlphaBlendFactor: u32 = 6   # Source alpha blend
dstAlphaBlendFactor: u32 = 7   # Dest alpha blend
```

**Blend Factor Values:**
- `0` - ZERO (transparent)
- `1` - ONE (opaque)
- `2` - SRC_COLOR
- `3` - ONE_MINUS_SRC_COLOR
- `4` - SRC_ALPHA
- `5` - ONE_MINUS_SRC_ALPHA
- `6` - DST_ALPHA
- `7` - ONE_MINUS_DST_ALPHA
- `8` - DST_COLOR
- `9` - ONE_MINUS_DST_COLOR

Most common: `(6, 7)` = Standard transparency blending

---

## Using the Addon

### Importing Materials

1. In Blender, go to **View 3D > League Mapgeo > Material Import**
2. Click **Import from File**
3. Navigate to a `.materials.py` file (example: `base.materials.py`)
4. Select and confirm

**Result:**
- All materials imported into Blender
- League properties stored as custom properties (JSON format)
- Material nodes created for visualization

### Exporting Materials

1. Ensure materials are imported or have League custom properties
2. Go to **Material Export** section
3. Click **Export to .materials.py**
4. Select output location

**What Gets Exported:**
- Material names exactly as imported
- All samplers with texture paths
- All parameters with exact values
- All switches and shader macros
- Technique and pass information

### Creating Custom Materials

1. Create a new material in Blender
2. Use a League material as template (Material > Create from Template)
3. Edit material properties through UI or JSON
4. Assign to mesh

**Manual Property Setup:**
To create a material without importing, manually set custom properties:

```json
{
  "league_material_name": "Custom/Path/To/Material_MAT",
  "league_material_type": 0,
  "samplers": [
    {
      "textureName": "DiffuseTexture",
      "texturePath": "ASSETS/Maps/Custom/texture.tex",
      "addressU": 1, "addressV": 1, "addressW": 1
    }
  ],
  "parameters": [
    {
      "name": "Color_Blend",
      "value": [0.5, 0.5, 0.5, 1.0]
    }
  ]
}
```

---

## Material Data Organization

### By Map

| Map | Materials Count |
|-----|-----------------|
| map11 (Summoner's Rift) | 5,116 |
| map12 (Howling Abyss) | 564 |
| map22 (Twisted Treeline) | 2,522 |
| map33 (Butcher's Bridge) | 349 |
| map21 (Proving Grounds) | 141 |
| map30 (Convergence) | 190 |
| map35 (Cherry Blossom) | 55 |

### Most Common Parameters

1. `DiffuseTexture` - 186 files
2. `AlphaTestValue` - 98 files
3. `Mask_Texture` - 97 files
4. `Color_Blend` - 56 files
5. `Color_Multiply` - 56 files

### Technical Classes

The addon uses these Python classes for materials:

- **MaterialsParser**: Parse .materials.py files
- **Material**: Complete material definition
- **MaterialSampler**: Texture reference
- **MaterialParam**: Shader parameter (vec4)
- **MaterialSwitch**: Boolean feature
- **MaterialPass**: Rendering pass
- **MaterialTechnique**: Rendering technique
- **MaterialChildTechnique**: Technique variation
- **MaterialsExporter**: Export to League format

---

## Advanced: JSON Format

All complex properties are stored as JSON in material custom properties:

### Samplers JSON
```json
[
  {
    "textureName": "DiffuseTexture",
    "texturePath": "ASSETS/Maps/path/texture.tex",
    "addressU": 1, "addressV": 1, "addressW": 1
  }
]
```

### Parameters JSON
```json
[
  {
    "name": "Color_Blend",
    "value": [0.1, 0.15, 0.1, 0.0]
  }
]
```

### Switches JSON
```json
[
  {
    "name": "ENV_TRANSITION",
    "on": false
  }
]
```

### Techniques JSON
```json
[
  {
    "name": "normal",
    "passes": [
      {
        "shader": "Shaders/StaticMesh/SRX_Blend_Earth_Rocks",
        "blendEnable": true,
        "srcColorBlendFactor": 6,
        "dstColorBlendFactor": 7
      }
    ]
  }
]
```

---

## Workflow Examples

### Example 1: Import and Modify Material

```python
# Python Console in Blender
import bpy
from material_editor_ui import *

# Import materials
bpy.ops.mapgeo.import_materials_file(filepath="C:/path/to/base.materials.py")

# Get a material
mat = bpy.data.materials["Maps/KitPieces/SRX/Materials/Default/Earth_River_MAT"]

# View properties
bpy.ops.mapgeo.view_material_properties()

# Export back
bpy.ops.mapgeo.export_materials_to_file(filepath="C:/output/materials_modified.py")
```

### Example 2: Create Material from Template

1. Select a mesh object
2. In Material Editor: find "Earth_River_MAT" in template dropdown
3. Enter new name "Custom_River_MAT"
4. Click Create from Template
5. Assign to mesh
6. Export

### Example 3: Batch Export Materials

```python
# Python Script
from materials_parser import MaterialsParser
from pathlib import Path

# Parse original
parser = MaterialsParser("original.materials.py")
materials = parser.parse()

# Modify materials...
# ... your edits here ...

# Export
from materials_parser import MaterialsExporter
MaterialsExporter.export(materials, "modified.materials.py")
```

---

## Research Data Summary

### Statistics from 195 files analyzed:
- Total materials: **9,509**
- Total file size: **282.95 MB**
- Total lines: **7,134,360**
- Average file size: **1.45 MB**
- Average materials per file: **48.7**

### Largest files:
- `base.materials.py`: 3,814 KB (200 materials)
- Various map12/22/30 files: 1,000-2,000 KB range

### Parameter Formula Distribution
Most parameters follow these patterns:
- **Color blends**: 4 values RGBA/XYZW
- **Speeds**: Single or dual values
- **Positions**: XYZ coordinates + padding
- **Ranges**: Min/Max + 2 padding values

---

## Limitations and Notes

- ⚠️ Texture files (`.tex`) are not directly editable in Blender but paths are preserved
- ⚠️ Shader binaries are not modified - only references and macros change
- ⚠️ Some proprietary material types may require manual handling
- ℹ️ Material names should follow League naming conventions
- ℹ️ Blend factors must be valid D3D11 values (0-10)

---

## Troubleshooting

### Import fails with "module not available"
- Ensure `materials_parser.py` is in the same directory as Blender addon
- Check Python path in Blender console

### Materials appear black
- Textures may not be found (normal, textures are inside WAD files)
- Check texture paths in material properties
- Use "View Props" to see loaded paths

### Export produces empty file
- Ensure materials have `league_material_name` property
- Check that custom property JSON is valid
- Use Python console to debug

### Shader compilation errors
- Verify shader paths exist in League installation
- Check shader macro values are valid strings
- Ensure blend factors are in valid range (0-10)

---

## File References

### Addon Files
- `materials_parser.py` - Parser and exporter core
- `import_materials_blender.py` - Blender import operators
- `export_materials_blender.py` - Blender export operators
- `material_editor_ui.py` - UI panels and editing tools

### Research Files
- `MATERIALS_RESEARCH.md` - Detailed research findings
- `_research_materials.py` - Research script

### League Installation Paths
- Materials: `Game/DATA/FINAL/Maps/Shipping/Map*/data/maps/mapgeometry/map*/*.materials.py`
- Total: 195 files across 7 directories

---

## API Reference

### MaterialsParser

```python
from materials_parser import MaterialsParser

parser = MaterialsParser("path/to/file.materials.py")
materials = parser.parse()  # Returns Dict[str, Material]

# Export to JSON
parser.export_json("output.json")
```

### Material Object

```python
Material(
    name: str,
    type: int = 0,
    samplerValues: List[MaterialSampler],
    paramValues: List[MaterialParam],
    switches: List[MaterialSwitch],
    shaderMacros: Dict[str, str],
    techniques: List[MaterialTechnique],
    childTechniques: List[MaterialChildTechnique]
)

# Convert to dict
mat.to_dict()  # Returns serializable dictionary
```

### Blender Operators

```python
# Import
bpy.ops.mapgeo.import_materials_file(filepath="path/to/file")

# Assign
bpy.ops.mapgeo.assign_material_to_mesh(material_name="Material")

# Create from template
bpy.ops.mapgeo.create_material_from_template(
    template_material="Template",
    new_name="NewMaterial"
)

# Export
bpy.ops.mapgeo.export_materials_to_file(filepath="output.py")

# View properties
bpy.ops.mapgeo.view_material_properties()
```

---

## Version History

### v0.2.0 (Current)
- ✅ Materials import/export system
- ✅ Full parser for .materials.py format
- ✅ Material editor UI in Blender
- ✅ JSON intermediate format support
- ✅ Complete research on all 9,509 materials
- ✅ Comprehensive documentation

### v0.1.1
- Point light system (experimental)
- Basic mapgeo import/export

### v0.1.0
- Initial Blender addon release
