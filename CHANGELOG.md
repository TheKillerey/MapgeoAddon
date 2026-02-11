# Changelog

All notable changes to Rey's Mapgeo Blender Addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.0.6] - 2026-02-11

### 🐛 Critical Fixes

#### Baron Hash Visibility Logic Corrected
- **BREAKING CHANGE**: Fixed visibility logic to properly handle baron hash override behavior
  - **Baron hash dragon layers NOW OVERRIDE visibility_layer** (not add to it)
  - When baron hash has `baron_dragon_layers_decoded`, those layers replace the mesh's `visibility_layer`
  - Baron pit states (`baron_layers_decoded`) filter independently
  - **Example**: Mesh with `baron_dragon_layers=[32]` (Hextech) shows ONLY on Hextech dragon, ignoring original `visibility_layer`
- **Import Error Fixed**: Resolved 'method-wrapper' object error on import
  - Fixed `update_environment_visibility()` function call signature
  - Import now completes without errors and updates visibility correctly

#### Visibility System Behavior
- **For meshes WITH baron hash AND dragon_layers**:
  - Dragon visibility: Uses `baron_dragon_layers_decoded` (OVERRIDE mode)
  - Baron visibility: Uses `baron_layers_decoded` for pit state filtering
  - Final visibility: `(baron dragon layers) AND (baron pit layers)`
- **For meshes WITHOUT baron hash OR without dragon_layers**:
  - Dragon visibility: Uses `visibility_layer` (standard bitwise check)
  - Baron visibility: Always visible (no baron filtering)
  - Final visibility: Just `visibility_layer` check
- **Base layer (bit 1)**: Always visible on all dragon variations (both modes)

### 📝 Notes
- This fix resolves the issue where baron hash meshes weren't showing on their correct dragon layers
- Baron hash system now correctly implements League engine's override behavior
- Test with baron hash meshes to verify correct visibility on Hextech/Chemtech/etc layers

---

## [0.0.5] - 2026-02-11

### ✨ Features Added

#### Baron State Viewport Filtering
- **Baron State Filter Options** - Added 4 new environment visibility filters
  - Baron - Base: Show meshes visible in baron base state (default pit)
  - Baron - Cup: Show meshes visible in baron cup state (bit 1)
  - Baron - Tunnel: Show meshes visible in baron tunnel state (bit 2)
  - Baron - Upgraded: Show meshes visible in baron upgraded state (bit 3)
- **Decoded Baron Layer Filtering** - Filter works based on decoded `baron_layers_decoded` property
  - Automatically shows/hides meshes based on their baron state visibility
  - Integrates seamlessly with existing dragon layer filtering

#### Collection Organization by Baron Layers
- **Baron State Collections** - Import creates 4 baron state collections automatically
  - BaronBase, BaronCup, BaronTunnel, BaronUpgraded
  - Meshes with decoded baron layers are automatically linked to corresponding collections
- **Multi-Collection Linking** - Meshes can appear in multiple baron state collections
  - Reflects complex baron visibility logic (AND/OR parent modes)
  - Complements existing dragon layer collection structure
- **Better Organization** - Easier to identify and manage baron-specific meshes
  - Collections are created even if empty (consistent structure)
  - Meshes remain linked to both dragon layer and baron state collections

### 📝 Documentation
- Updated baron_hash_system.md to mark viewport filtering and collection organization as completed

---

## [0.0.4] - 2026-02-11

### ✨ Features Added

#### Baron Hash Decoding System
- **Automatic Baron Hash Decoding** - When materials.bin.json is loaded, baron hashes are automatically decoded
  - Parses ChildMapVisibilityController structures from materials.bin.json
  - Resolves parent references to determine actual layer visibility
  - Supports recursive parent resolution for complex controllers
- **Baron Pit Layers Display** - Shows which baron pit states (Base, Cup, Tunnel, Upgraded) the mesh is visible on
  - Decoded from 0xec733fe2 type controllers with 0x8bff8cdf property
  - Displayed in properties panel under "Baron Pit Layers"
- **Referenced Dragon Layers Display** - Shows which dragon layers are referenced by the baron hash
  - Decoded from 0xc406a533 type controllers with 0x27639032 property
  - Displayed in properties panel under "Referenced Dragon Layers"
- **Parent Mode Interpretation** - Shows whether visibility uses AND or OR logic
  - ParentMode 3 = AND (visible when ALL parents are active)
  - ParentMode 1 = OR (visible when ANY parent is active)
- **Baron Hash Parser Module** - New `baron_hash_parser.py` module for materials.bin.json parsing
  - MaterialsBinParser class for loading and indexing visibility controllers
  - BaronHashController class for storing decoded visibility data
  - Recursive parent resolution for nested controllers
  - Helper functions for layer name lookups

### 🔄 Changed
- **Import Process** - Now initializes baron hash parser when materials.bin.json is available
- **Console Output** - Shows decoded baron hash information for first 5 meshes
- **Properties Panel** - Enhanced baron hash section with decoded layer information
- **Storage Format** - Baron/dragon layers stored as string-formatted lists in custom properties

### 🐛 Fixed
- **Materials.bin.json Support** - Properly handles different JSON structure formats
- **Hash Format Handling** - Supports multiple hash format variations (with/without 0x prefix)

---

## [0.0.3] - 2026-02-11

### ✨ Features Added

#### Baron Hash Visibility System Documentation
- **Baron Hash System Support** - Added comprehensive support and documentation for Baron Hash visibility system
  - Baron Hash **overrides** Dragon Layer System when set (non-zero)
  - Used for Baron-specific map variations (Base, Cup, Tunnel, Upgraded states)
  - References ChildMapVisibilityController in materials.bin for complex layer combinations
- **Enhanced Properties Panel** - Shows Baron Hash status prominently
  - Warning indicator when Baron Hash overrides Dragon Layers
  - Info box explaining the 4 Baron states
  - Dragon layers shown as "Inactive" when Baron Hash is active
- **Documentation** - Added `baron_hash_system.md` with complete technical documentation
  - Explains the two visibility systems (Dragon Layers vs Baron Hash)
  - Materials.bin controller structure
  - ParentMode behavior (OR vs AND logic)
  - Current limitations and future enhancement plans

#### Collection Structure & Multi-Layer Support
- **Improved Collection Organization** - Meshes are now organized in a clear hierarchy:
  - `MapName_Meshes` - Contains all actual mesh objects
  - 8 Layer collections (Base, Inferno, Mountain, Ocean, Cloud, Hextech, Chemtech, Unused) - Link to meshes based on visibility
- **Multi-Layer Support** - Meshes can now be assigned to multiple layers simultaneously
  - A mesh with layers 1 and 2 will appear in both "Base" and "Inferno" collections
  - Matches in-game behavior where meshes can be visible in multiple elemental rift states
- **Layer Toggle System** - Layer assignment buttons now toggle layers on/off instead of replacing all layers
  - Click "Toggle Layer 1" to add/remove that layer while keeping other layer assignments
  - Objects automatically link/unlink from appropriate layer collections

### 🔄 Changed
- **Layer assignment behavior** - Buttons now toggle layer membership instead of setting exclusive layers
- **Collection structure** - All imports now create layer collections automatically (previously optional)
- **Button labels** - Changed from "Assign Selected to Layer X" to "Toggle Layer X (Name)" for clarity
- **Layer 8 name** - Changed from "Unused" to "Void" to match actual game data
- **Properties Panel Layout** - Baron Hash now shown first with priority indicator when active

---

## [0.0.2] - 2026-02-11
- **Bush Assignment Panel** - New sidebar section for assigning bush flags to selected meshes
  - "Assign Bush to Selected" button
  - "Remove Bush from Selected" button
- **Baron Hash Assignment Panel** - New sidebar section for assigning Baron Hash to selected meshes
  - "Assign Baron Hash to Selected" button with dialog for hex input
  - Hex validation (8 characters, 0-9 and A-F)
- **Render Region Hash Assignment Panel** - New sidebar section for assigning Render Region Hash to selected meshes
  - "Assign Render Region Hash to Selected" button with dialog for hex input
  - Hex validation (8 characters, 0-9 and A-F)
- **Enhanced Environment Visibility** - Filter dropdown now includes:
  - "Only Baron Hash" - Show only meshes with Baron Hash assigned
  - "Only Bush" - Show only bush meshes
  - All 8 layer options (Base, Inferno, Mountain, Ocean, Cloud, Hextech, Chemtech, Unused)
- **Better property labels** - More intuitive naming in the mesh properties panel

### ✨ Features Planned

#### Custom Properties Cleanup
- **Simplified mesh properties** - Removed unnecessary technical properties that are not needed for export
- **Property renames** for better clarity:
  - `mapgeo_is_bush` → `is_bush` (displayed as "Is Bush?")
  - `mapgeo_quality` → `quality` (displayed as "Quality")
  - `mapgeo_render_flags` → `render_flags` (displayed as "Render Flags")
  - `mapgeo_visibility` → `visibility_layer` (displayed as "Visibility Layer")
  - `mapgeo_unknown_v18` → `render_region_hash` (hex format without 0x prefix)
  - `mapgeo_visibility_controller_hash` → `baron_hash` (hex format without 0x prefix)
- **Removed properties**: `mapgeo_bbox_max`, `mapgeo_bbox_min`, `mapgeo_index_count`, `mapgeo_mesh_index`, `mapgeo_primitive_count`, `mapgeo_transform`, `mapgeo_vertex_count`, `mapgeo_vertex_declaration_count`, `mapgeo_vertex_declaration_id`

#### UI Improvements
- **Bush Assignment Panel** - Improved bush flag assignment interface
- **Baron Hash Display** - Added display for Baron visibility controller hash
- **Render Region Hash Display** - Show render region hash for version 18 files
- **Export Version** - Default export version changed to 18 (latest format)
- **Better property labels** - More intuitive naming in the UI

#### Bucket Grid System (Planned)
- **Custom Bucketgrid Creation** - Create custom bucket grids for spatial optimization
- **Copy Bucketgrid from .mapgeo** - Option to copy existing bucket grid structure from imported files
- **Bucketgrid Visualization** - Toggle visualization of bucket grid structure in viewport
- Reference implementation: `LeagueToolkit/Core/SceneGraph` (BucketedGeometry.cs, GeometryBucket.cs)

### 🔄 Changed
- **Addon name** changed from "League of Legends Mapgeo Tools" to "Rey's Mapgeo Blender Addon"
- **Default export version** now 18 instead of 17
- **Property storage** simplified to only essential export data
- **Quality system** updated to support full 0-255 range instead of simplified 0-4 scale
  - Properties panel now displays "Value: X / 255"
  - Quality assignment now uses presets (0, 63, 127, 191, 255) plus custom input dialog

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
