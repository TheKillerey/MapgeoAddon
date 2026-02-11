# Changelog

All notable changes to the League of Legends Mapgeo Addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-02-11

### 🎉 Initial Release

First stable release of the League of Legends Mapgeo Addon for Blender 5.0+.

### ✨ Features Added

#### Core Import System
- **Full .mapgeo file import** for versions 13-18 (primary focus on version 18)
- **Multi-vertex buffer support** with correct vertex description indexing per buffer
- **Multiple vertex buffers per mesh** - each buffer uses `vertex_descriptions[vertex_declaration_id + buffer_index]`
- **Coordinate system conversion** - League (X,Y,Z) → Blender (X,Z,Y) for proper orientation
- **Complete geometry data import**:
  - Positions (XYZ_FLOAT32)
  - Normals (XYZ_FLOAT32)
  - UV coordinates (XY_FLOAT32) - supports multiple UV channels
  - Vertex colors (BGRA_PACKED8888, RGBA formats)
  - Tangents and other custom vertex attributes

#### Material & Texture System
- **Automatic material loading** from `.materials.bin.json` files
- **Texture conversion system** - converts League's `.tex` format to PNG via DDS intermediate
- **Supported texture formats**:
  - BGRA8 (32-bit uncompressed)
  - BC1/DXT1 (compressed, no alpha)
  - BC3/DXT5 (compressed, with alpha)
  - RGBA16 (64-bit uncompressed)
- **CommunityDragon algorithm** for accurate texture decompression
- **Mipmap extraction** - extracts only the largest mipmap for optimal quality
- **Blender Principled BSDF integration**:
  - Diffuse texture (Base Color)
  - Normal map support
  - Emission (self-illumination)
  - Blender 5.0 compatibility (no deprecated 'Specular' input)
- **Material caching** - reuses materials across meshes for efficiency

#### Multi-Material Mesh Support
- **Proper material slot assignment** for meshes with multiple primitives
- **Face-level material mapping** - assigns faces to correct material slots
- **Material database parsing** - reads StaticMaterialDef from JSON

#### 8-Layer Visibility System
- **Environment visibility flags** - full support for League's layer-based map system
- **Layer filtering during import** - filter by Layer 1-8 or ALL
- **Bitwise visibility calculation** - proper AND operations for layer membership
- **Layer collection grouping** - optional organization of meshes into layer-based collections

#### Bush Render Flag System
- **Bush flag parsing** for version 14+ mapgeo files
- **Bush flag storage** as custom property (`mapgeo_is_bush`)
- **Render flags storage** (`mapgeo_render_flags`) for export roundtrip
- **UI panel for bush flag toggling** - checkbox editor in Mesh Properties panel
- **Bulk bush flag operator** - toggle bush flag for multiple selected objects

#### User Interface
- **Mesh Properties Panel** in 3D View (press `N`):
  - 8-button grid showing visibility layers
  - Quality level display (Very Low to Very High)
  - Bush flag checkbox
  - Render flags hex display
- **Import operator** - `File > Import > League of Legends Mapgeo (.mapgeo)`
- **Import options panel**:
  - Assets folder path configuration
  - Materials JSON path configuration
  - Load Materials checkbox
  - Group by Layer checkbox
  - Layer visibility dropdown filter
  - Import UV/Normals/Colors toggles
- **Toggle Bush Flag operator** - bulk edit bush flags for selected meshes

#### Custom Properties
- **mapgeo_visibility** - Layer visibility bitfield (0-255)
- **mapgeo_quality** - Quality level (0 = Very Low, 4 = Very High)
- **mapgeo_is_bush** - Bush render flag (boolean)
- **mapgeo_render_flags** - Additional render flags (int)

All properties stored for potential future export functionality.

#### Dependency Management
- **Automatic Pillow support** - adds user site-packages to sys.path
- **No admin rights required** - uses `--user` installation for Pillow
- **Included install script** - `install_pillow.py` for easy one-click installation

### 🛠️ Technical Improvements

- **Version 18 parsing fixes**:
  - Vertex elements now 8 bytes per element (name + format, no stored offset)
  - Correct offset calculation during parsing
- **Enum value corrections**:
  - VertexElementName values sequential (0-15)
  - Proper StreamIndex mapping to D3D streams
- **Multi-buffer vertex description indexing**:
  - Each buffer uses `vertex_declaration_id + buffer_index` for its description
  - Fixed critical bug where all buffers were using the same description
- **Blender 5.0 shader compatibility**:
  - Removed 'Specular' input connection (doesn't exist in new shader)
  - Conditional input checks for version-safe material creation
- **TEX header parsing**:
  - 12-byte header: magic + width + height + extended + format + type + flags
  - Proper struct packing format for DDS header generation
- **Optimized texture conversion**:
  - Only extracts largest mipmap (level 0)
  - Skips unnecessary mipmap processing
  - Efficient memory usage

### 📚 Documentation

- **Comprehensive README.md** with:
  - Feature overview with badges
  - Complete installation guide
  - Usage instructions with examples
  - Material setup walkthrough
  - Technical details section
  - Troubleshooting guide
  - References to LeagueToolkit and LtMAO
- **Detailed INSTALLATION.md** with:
  - Step-by-step installation instructions
  - Multiple installation methods
  - Pillow installation guide (3 methods)
  - Verification checklist
  - Extensive troubleshooting section
- **CHANGELOG.md** (this file) - Complete version history

### 🔧 Dependencies

- **Blender**: 5.0 or higher
- **Python**: 3.11+ (bundled with Blender)
- **Pillow** (PIL): Required for texture conversion
  - Installed to user site-packages
  - Automatic path injection in addon initialization

### 🧪 Testing

- **Test data included**:
  - LeagueTestMap/ - Sample mapgeo files for development
  - LeagueToolkit/ - Reference C# implementation
- **Validated with**:
  - sodapop_srs_original.mapgeo (version 18, 748 meshes)
  - Multiple texture formats (BC1, BC3, BGRA8, RGBA16)
  - Multi-material meshes
  - All 8 visibility layers
  - Meshes with 1-3 vertex buffers

### 📋 Known Limitations

- **Export functionality** not yet implemented (metadata stored for future use)
- **Normal maps** - secondary textures not yet mapped to Normal input
- **Specular maps** - additional texture channels not yet supported
- **Bucket grid** - spatial partitioning data not parsed
- **Planar reflectors** - not yet supported

### 🎯 Compatibility

- **Mapgeo versions**: 13, 14, 15, 16, 17, 18 (focused on 18)
- **Blender versions**: 5.0+ (tested with 5.0)
- **Operating systems**: Windows, macOS, Linux
- **Python**: 3.11+

### 🙏 Credits

- **LeagueToolkit** - C# reference implementation by Crauzer and contributors
- **LtMAO** - Maya plugin by tarngaina (critical vertex buffer indexing reference)
- **CommunityDragon** - Texture format documentation and conversion algorithms
- **Riot Games** - League of Legends and asset formats

---

## [Unreleased]

### Planned Features
- Export operator for modified mapgeo files
- Normal map support (secondary textures)
- Specular/roughness map support
- Bucket grid visualization
- Planar reflector support
- Batch import multiple mapgeo files
- Material library presets

---

## Version History Summary

- **1.0.0** (2026-02-11) - Initial stable release with full import, materials, textures, and 8-layer system

---

**Note**: Dates use ISO 8601 format (YYYY-MM-DD)
