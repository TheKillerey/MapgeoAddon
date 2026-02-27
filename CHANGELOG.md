# Changelog

All notable changes to Rey's Mapgeo Blender Addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Released]

## [0.2.9] - 2025-07-25

### 🦴 Phase 4 — SKN/SKL Skinned Mesh & Skeleton Import
- **SKN Parser** — Full SimpleSkin binary parser supporting versions 0, 2, and 4
  - Magic `0x00112233` detection, vertex types: Basic (52B), Color (56B), Tangent (72B)
  - Submesh definitions with material names, vertex/index ranges
  - Bounding box parsing for v2+, v4 extended header support
- **SKL Parser** — Auto-detects and parses both skeleton formats
  - Legacy `r3d2sklt` v1/v2 with global transform matrices
  - New format `0x22FD4FC3` v0 with TRS decomposition + inverse bind matrices
  - Full bone hierarchy reconstruction with parent/child relationships
- **Blender Armature Builder** — Creates proper Blender armatures from SKL data
  - Proportional bone sizing based on skeleton bounding box (3% default, 1% min)
  - Child/parent distance heuristics for natural bone lengths
  - Octahedral display mode for clear skeleton visualization
- **Mesh Builder** — Imports SKN meshes with full vertex data
  - Positions, normals, UVs, vertex colors, bone weights (up to 4 influences)
  - Vertex group creation per bone with weight painting
  - Armature modifier automatically applied
  - Unified mesh mode (single mesh) and per-submesh mode
- **Texture & Material Support** — 5-pass fuzzy texture matching system
  - Pass 1: Exact stem match
  - Pass 2: Submesh name found in texture stem
  - Pass 3: Stem + color map keyword (`_TX_CM`, `_diffuse`, `_base_color`)
  - Pass 4: Any color map keyword in texture name
  - Pass 5: Any texture containing the stem
  - Recursive texture folder scanning with extension filtering (.dds, .png, .tex, .tga)
  - Principled BSDF material setup with diffuse texture wiring
- **Blender 5.0+ Compatibility** — Graceful handling of removed `blend_method` attribute
  - Per-material try/except isolation prevents single failure from breaking all materials
- **UI Integration** — New "SKN/SKL Import" section in League Tools sidebar panel
  - Single file import and batch folder import operators
  - Toggle options: load textures, unified mesh, assets folder path
  - Info panel for inspecting imported SKN/SKL meshes
  - File > Import menu integration

### 🧹 Project Cleanup
- Moved development/debug files to Research/ and TestCode/ folders
- Cleaned `__pycache__/` from project root
- Root directory now contains only addon-essential files

---

## [0.2.8] - 2025-07-24

### 🌐 CommunityDragon Hash Integration
- **Community Hashes Module** (`community_hashes.py`) — Download, cache, and parse CommunityDragon hash dictionaries
  - Automatic download from CommunityDragon CDN with local file caching
  - Supports `hashes.binentries.txt`, `hashes.bintypes.txt`, `hashes.binfields.txt`, `hashes.binhashes.txt`
  - Resolves FNV1a hashes to human-readable names for entries, types, fields, and values
  - Statistics display showing total resolved vs unresolved hashes
- **PropertyBin Hash Resolution** — Enhanced PropertyBin editor with hash name display
  - `TYPE_HASH` and `TYPE_LINK` values resolved to `name (0xhash)` format
  - `class_hash` in struct entries resolved to readable type names
  - Entry path hashes resolved in the entry list
  - Field name hashes resolved in the tree view
- **Hash Format Fix** — Correct parsing of CommunityDragon's `hex_hash name` format
  - Uses `split(None, 1)` for robust whitespace handling
  - Strips `0x` prefix from hex hashes for consistent integer key lookups
  - Both CommunityDragon format and binary data produce matching integer keys

---

## [0.2.7] - 2025-07-20

### 📦 Phase 1 — CFGBin / Inibin Editor
- **CFGBin Reader** (`cfgbin_reader.py`) — Full binary parser for League .cfgbin and .inibin files
  - Inibin v2 format with 13 set types (bool, int, float, vector, string, color, etc.)
  - Automatic hash → name resolution via .cfg companion files
  - Read and write support for round-trip editing
- **CFGBin Editor UI** (`cfgbin_editor_ui.py`) — Complete editor panel in League Tools tab
  - Import/export operators with file browser integration
  - Entry list with hash names and value display
  - Inline editing for all value types (int, float, bool, string, vector, color)
  - Color picker for RGBA entries
  - Add/remove entries with hash auto-generation
  - Load .cfg files for additional hash name resolution
  - File > Import/Export menu integration

### 🏗️ Phase 2 — SCO/SCB Static Mesh Import & Export
- **SCO Parser** — Text-based static mesh format (Static Collision Object)
  - Reads material name, vertex positions, UVs, face indices
  - Full write support for exporting back to SCO text format
- **SCB Parser** — Binary static mesh format (Static Collision Binary)
  - Version 1-3 support with magic `r3d2Mesh`
  - Vertex positions, normals, UVs, face indices, material names
  - Central point and bounding box parsing
  - Full write support for binary round-trip
- **Blender Integration** — Import and export operators
  - Creates Blender meshes with proper materials, UVs, and normals
  - Coordinate system conversion (League Y↔Z to Blender)
  - Batch import from folder
  - Export selected meshes as SCO or SCB
  - File > Import/Export menu entries

### 📋 Phase 3 — PropertyBin (.bin) Editor
- **PropertyBin Parser** (`propertybin_parser.py`) — Full PROP binary format parser
  - PROP versions 1-3 and PTCH (patch) wrapper support
  - All 27 value types: bool, int8-64, uint8-64, float, vec2/3/4, matrix4x4, RGBA, string, hash, file, container, struct, embedded, link, optional, map, bitfield
  - Nested struct/container/map/optional traversal
  - Binary writer for round-trip export
- **PropertyBin Editor UI** (`propertybin_editor_ui.py`) — Tree-based editor in League Tools tab
  - Entry list showing all top-level entries with class types
  - Expandable tree view for nested structs, containers, maps
  - Inline editing for all value types
  - Add/remove entries and fields
  - Import/export with file browser
  - File > Import/Export menu integration

---

## [0.2.6] - 2025-02-23

### 🪣 Bucket Grid Export Overhaul
- **Merge-based export pipeline** — CUSTOM bucket grid export now follows a 3-step Load Imported → Load Custom → Merge workflow, preserving original grid ordering and metadata
- **Fixed hash/v18 field placement** — Original file stores identifiers in either `path_hash` or `unknown_v18_float`; export now preserves the correct field assignment for each grid
- **Master grid preservation** — The master grid (hash=0, v18=0, flags=1) containing all scene geometry with per-face visibility flags is kept from the original import
- **Face visibility flags** — Auto-generates `face_visibility_flags` (default 255 = always visible) for custom grids replacing originals that had `flags=1`
- **Extra grid filtering** — Custom grids with no matching imported grid are now skipped to prevent game crashes
- **Shared `_reconstruct_grid_from_json()`** — Refactored both import and custom export paths to use a common JSON→BucketGrid reconstruction method

### 🪣 Bucket Grid Generation Improvements
- **Per-hash-type grouping** — Bucket grids created separately per render region, baron hash, and visibility layer
- **Riot-style per-bucket vertex subsets** — Each bucket owns a contiguous vertex slice with `base_vertex`; local indices always fit in ushort
- **Centroid-based face assignment** — Faces assigned to one bucket based on centroid with stickout tracking
- **Visibility controller layer→hash mapping** — Loads `materials.bin` to extract layer→hash mappings via `BaronHashParser`
- **3D bounding box visualization** — Bucket grid bounding boxes now display as full 3D volumes
- **Height range clamping** and **max grid size cap** to prevent freezes on large maps
- **Bush/fog/sun mesh filtering** — Irrelevant meshes are skipped during bucket grid creation

### 🎨 Material Editor — Shader Preview Rewrite
- **Full shader preview system** with 20+ shader classifications
- **Category-specific node builders** — Water, glass, hologram, pure emissive, fae lights, gradient color
- **Smart diffuse identification** — 3-pass diffuse sampler detection that skips shader template textures
- **Comprehensive texture wiring** — Normal maps, reflection/specular, noise/scrolling, flow maps, thickness/deformation masks, emission masks
- **Full parameter application** — TintColor, glass colors, hologram params, glow/emission, water colors/flow/fresnel/opacity, alpha test, planar reflection, shadow color
- **Blend mode configuration** — Correct Blender blend/render mode per shader type

### 🔧 Material Loader Improvements
- **Hashed material key resolution** — Supports `0x0221ffad = StaticMaterialDef {}` format
- **New shader builders** — `DefaultEnv_Glow`, `GradientColor`, `Water`, `Ocean`, `Twist`
- **Emission color support** — Handles `EMISSION_EmissionColor`, `EmissionColor`, `FLOW_Color`
- **Starting_Color / ShadowColor support** — Color fallback for base color and shadow tint blending

### 🔧 Other Fixes
- **Blender 5.1+ deferred packing fix** — Deferred image packing auto-disabled for Blender 5.1.0+
- **Case-insensitive ASSETS/ prefix** — Custom maps using lowercase `assets/` prefix now handled correctly
- **Shader texture fallback folder** — `LeagueShaderTextures/assets` added as fallback
- **Emission strength default** — Emission Strength on new Principled BSDF explicitly set to 0.0

---

## [0.2.5] - 2025-02-21

### 🔍 Centralized Debug System
- **New Debug Module** (`debug_system.py`) — Unified logging and diagnostics
  - `DebugLog` singleton with categories and severity levels
  - `ImportStats` counters for meshes, materials, textures, lights
  - Session tracking with duration and summary generation

### 🎨 Debug UI Panel
- Shows last import summary: duration, mesh/material/texture/light counts
- Displays warnings and errors with category tags up to 30 recent issues

### ✅ Integrated Debug Logging
- `import_mapgeo.py` — All print statements converted to debug log calls
- `material_loader.py` — Material/texture loading tracked with full diagnostics
- `texture_utils.py` — Texture conversion tracked

### 🧹 UI Cleanup
- Removed unused "Testing Paths" UI buttons and stale operator references

---

## [0.2.4] - 2025-02-20

### 🧹 Repository Cleanup
- Removed C# implementations, standalone docs, research materials, diagnostic tools
- Repository now contains only Blender addon essentials
- Updated .gitignore for development artifacts

---

## [0.2.3] - 2025-02-20

### ✨ League Tools: Troybin Particle Editor
- **Troybin Parser** — Full read/write for .troybin particle files (Inibin v2)
- **New "League Tools" Panel** — Import/export, multi-emitter support, property editor
- **Property Editor** — All types editable: Int, Float, Bool, Vec2/3/4, Color, String
- **14 Property Templates** — Common particle properties (lifetime, rate, color, scale, velocity, etc.)
- **Emitter Management** — Add/remove emitters, custom names and types
- **Create New Particles** — Build particles from scratch with minimal valid structure

---

## [0.2.1] - 2025-02-16

### ✨ LightGrid System
- Full binary parser for lightgrid.dat (version 3)
- UI operators: Create, Import/Export, Bake (with shadow raycasting), Visualize, Clear
- Mesh lightmap settings panel (shadow flags, lightmap texture/scale/bias/channel)

### ✨ Lightmap Export System
- TEXCOORD7 export for lightmap UVs
- Baked light channel export with texture path + scale/bias
- LightGrid export with 256x256 grid, 6 directional color samples per cell

---

## [0.2.0] - 2025-02-15

### ✨ Shader Template System
- 91 shader templates from 9,509 materials with per-shader samplers, parameters, switches, macros
- Dropdown-based Add operators for shader compatibility

### ✨ Point Light System (Custom Feature)
- Add/remove point lights linked to meshes
- Point light management UI and JSON export
- Auto-creation on import, export to JSON companion file
- Note: Custom feature — NOT used in official League maps

### 🛠 Fixes
- GrassTintMap UV offsets corrected
- Baron hash assignment with automatic decode/refresh
- World-space bounding sphere/box for visibility culling

---

## [0.1.1] - 2025-02-14

### 🛠 Fixes
- Quality bitmask correctness (0-31 bitmask instead of single enum)
- Layer visibility refresh on assignment
- Operator registration fixes

### ✨ Setup Wizard
- New dialog for assigning mapgeo fields in one place

---

## [0.1.0] - 2025-02-13

### 🎉 Stable Release — Full Export Support
- Complete export operator for .mapgeo (versions 13-18)
- Sampler definition round-trip, vertex buffer deduplication
- Bush animation (TEXCOORD5), transform matrix, bounding box fixes
- Render region hash (v18), baron hash, all custom properties preserved
- Bucket grid spatial partitioning round-trip

---

## [0.0.9] - 2025-02-12

### ✨ Lightmap Support
- Per-mesh baked lightmap textures with scale+bias UV transform
- Lightmap shader nodes (Diffuse × Lightmap × colorScale)
- Map settings parsing (sun, sky, bake properties)
- Import toggle and custom property storage

---

## [0.0.8] - 2025-02-12

### 🐛 ParentMode Visibility Fix
- Corrected ParentMode 1 (Visible) vs 3 (Not Visible) interpretation
- Updated dragon layer and baron pit state filtering

### ✨ Enhanced Texture Format Support
- Multiple extension fallback: .tex → .dds → .png
- DDS to PNG conversion with caching

---

## [0.0.7] - 2025-02-12

### ✨ Python Materials Format
- `.materials.py` file support alongside `.materials.bin.json`
- Enhanced baron hash parser for both formats

---

## [0.0.6] - 2025-02-11

### 🐛 Baron Hash Visibility Logic
- Baron dragon layers now properly override visibility_layer
- Fixed import error with `update_environment_visibility()`

---

## [0.0.5] - 2025-02-11

### ✨ Baron State Viewport Filtering
- 4 baron state filters (Base, Cup, Tunnel, Upgraded)
- Baron state collections auto-created on import

---

## [0.0.4] - 2025-02-11

### ✨ Baron Hash Decoding
- Automatic decoding from materials.bin.json
- Baron pit layers, referenced dragon layers, parent mode display
- New `baron_hash_parser.py` module

---

## [0.0.3] - 2025-02-11

### ✨ Baron Hash Documentation & Collection Organization
- Multi-layer collection support
- Layer toggle buttons (add/remove instead of replace)

---

## [0.0.2] - 2025-02-11
- Bush/Baron Hash/Render Region assignment panels
- Enhanced environment visibility filters

---

## [1.0.0] - 2025-02-11

### 🎉 Initial Release
- Full .mapgeo import for versions 13-18
- Material & texture system with .tex → PNG conversion
- 8-layer visibility system with filtering
- Bush render flag support
- Complete Blender UI with sidebar panels

---

**Note**: Dates use ISO 8601 format (YYYY-MM-DD)
