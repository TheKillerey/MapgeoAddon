# League of Legends Mapgeo Addon for Blender 5.0

[![Blender](https://img.shields.io/badge/Blender-5.0+-orange.svg)](https://www.blender.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A comprehensive Blender addon for importing and working with League of Legends `.mapgeo` files (Riot Games' map environment format).

![Version](https://img.shields.io/badge/version-0.0.6-blue)
![Status](https://img.shields.io/badge/status-beta-yellow)

## ✨ Features

### 🎨 Complete Import System
- **Full mapgeo support**: Versions 13-18 (focus on v18)
- **Automatic texture loading**: Converts `.tex` files to PNG (BC1/DXT1, BC3/DXT5, BGRA8, RGBA16)
- **Material system**: Loads materials from `.materials.bin.json` with full shader support
- **Multi-vertex buffer support**: Handles meshes with multiple vertex buffers and attributes
- **8-layer visibility system**: Full support for League's environment layers with bitwise filtering
- **Geometry data preservation**:
  - Positions, normals, UVs, vertex colors
  - Multiple UV channels
  - Custom vertex attributes
  - Bush render flags
  - Quality levels

### 🎯 Advanced Features
- **Environment visibility filtering**: Filter meshes by layer with dropdown selection
- **Layer-based grouping**: Organize imported meshes into layer collections
- **Material auto-loading**: Automatically finds and converts textures from game files
- **Multi-material meshes**: Proper material slot assignment for complex meshes
- **Custom properties**: Stores all metadata for potential export functionality
- **Bush flag support**: Toggle and edit bush render flags via UI panel

### 🎮 Baron Hash Visibility System
- **Baron pit state filtering**: Filter by baron pit states (Base, Cup, Tunnel, Upgraded)
- **Dragon layer override**: Baron hash meshes use decoded dragon layers instead of visibility_layer
- **Automatic decoding**: Parses materials.bin.json to decode ChildMapVisibilityController structures
- **Complex visibility logic**: Supports AND/OR parent modes for multi-layer visibility
- **Test paths button**: Quick setup for Map11 assets and materials paths

### 🖥️ User Interface
- **3D View Properties Panel**: View and edit mesh properties (visibility, quality, bush flag, baron hash)
- **Import operator**: Located in `File > Import > League of Legends Mapgeo (.mapgeo)`
- **Split layer filters**: Separate dragon layer and baron pit state dropdowns
- **Material settings**: Configure assets folder and materials database path

## 📋 Requirements

- **Blender**: Version 5.0 or higher
- **Python**: 3.11+ (included with Blender)
- **Pillow**: Required for texture conversion (`.tex` to `.png`)

## 🚀 Installation

### Step 1: Download the Addon

1. Download or clone this repository:
   ```bash
   git clone https://github.com/yourusername/MapgeoAddon.git
   ```
   Or download as ZIP and extract it.

### Step 2: Install in Blender

1. Open Blender 5.0+
2. Go to `Edit > Preferences > Add-ons`
3. Click `Install...`
4. Navigate to the addon directory and select `__init__.py`
5. Enable the addon by checking: **"Import-Export: League of Legends Mapgeo Tools"**

### Step 3: Install Pillow (Required for Textures)

The addon requires Pillow to convert `.tex` files to PNG format. **Choose ONE method:**

#### Method A: Automatic (Recommended)
The addon automatically uses your user Python packages. Simply install Pillow once:

1. Open Blender
2. Go to `Scripting` workspace
3. Open the provided `install_pillow.py` script
4. Click `Run Script` (or press `Alt+P`)
5. Restart Blender

#### Method B: Manual Command Line
```bash
python -m pip install --user Pillow
```

Then restart Blender.

## 📖 Usage Guide

### Importing Mapgeo Files

1. **Open import dialog**:
   - Go to `File > Import > League of Legends Mapgeo (.mapgeo)`

2. **Select your `.mapgeo` file**

3. **Configure import options**:

   | Option | Description |
   |--------|-------------|
   | **Assets Folder** | Path to game assets (e.g., `Map11.wad/assets/`) |
   | **Materials JSON** | Path to `.materials.bin.json` file |
   | **Load Materials** | Enable automatic material and texture loading |
   | **Group by Layer** | Organize meshes into layer collections |
   | **Layer Visibility** | Filter meshes by environment layer (1-8 or ALL) |
   | **Import UVs** | Import UV coordinates |
   | **Import Normals** | Import custom normals |
   | **Import Vertex Colors** | Import vertex color data |

4. **Click "Import Mapgeo"**

### Material and Texture Setup

For automatic material loading:

1. Set **Assets Folder** to your extracted WAD assets directory:
   ```
   C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\assets\
   ```

2. Set **Materials JSON** to your materials database:
   ```
   C:\Path\To\sodapop_srs.materials.bin.json
   ```

3. Enable **"Load Materials"** checkbox

The addon will automatically:
- Parse material definitions from JSON
- Find referenced `.tex` files in assets folder
- Convert `.tex` → `.dds` → `.png`
- Create Blender materials with proper shader nodes
- Assign materials to meshes

### Layer Visibility System

League of Legends uses 8 environment layers for dynamic map changes:

- **Layer 1-8**: Individual layers
- **ALL**: Show all meshes regardless of layer

Use the **Environment Visibility** dropdown during import to filter meshes.

### Viewing Mesh Properties

After import, select any mesh and check the **Properties Panel** (`N` key) under **Mesh Properties**:

- **Visibility Layers**: 8-button grid showing which layers this mesh belongs to
- **Quality Level**: Mesh quality setting (Very Low to Very High)
- **Bush Flag**: Checkbox showing if mesh is marked as a bush (for render flags)
- **Render Flags**: Hex display of additional render flags

### Toggle Bush Flag

Select one or more meshes and click **"Toggle Bush Flag"** to enable/disable bush rendering.

## 🗂️ Project Structure

```
MapgeoAddon/
├── __init__.py              # Addon registration and settings
├── mapgeo_parser.py         # Binary format parser (versions 13-18)
├── import_mapgeo.py         # Import operator with multi-buffer support
├── material_loader.py       # Material JSON parser and Blender material creator
├── texture_utils.py         # TEX → DDS → PNG converter
├── ui_panel.py              # Properties panel and operators
├── utils.py                 # Utility functions
├── install_pillow.py        # Pillow installation helper script
├── INSTALLATION.md          # Detailed installation guide
├── CHANGELOG.md             # Version history
├── README.md                # This file
├── LeagueToolkit/           # Reference C# implementation
└── LeagueTestMap/           # Test data for development
```

## 🛠️ Technical Details

### Supported Mapgeo Versions
- **Version 13-18**: Full support
- **Version 18**: Primary target (current as of 2026)

### Coordinate System
- **League**: Right-handed (X, Y, Z)
- **Blender**: Right-handed (X, Z, Y)
- **Conversion**: Automatic during import `(X, Y, Z) → (X, Z, Y)`

### Texture Formats Supported
- **BGRA8**: 32-bit uncompressed
- **BC1 (DXT1)**: Compressed, no alpha
- **BC3 (DXT5)**: Compressed, with alpha
- **RGBA16**: 64-bit uncompressed

### Vertex Buffer Features
- **Multiple vertex buffers per mesh**: Each buffer has its own vertex description
- **Vertex description indexing**: `vertex_descriptions[vertex_declaration_id + buffer_index]`
- **Support for secondary attributes**: UVs, normals, colors can be split across buffers

### Custom Properties Stored
- `mapgeo_visibility`: Layer visibility bitfield (0-255)
- `mapgeo_quality`: Quality level (0-4)
- `mapgeo_is_bush`: Bush render flag (boolean)
- `mapgeo_render_flags`: Additional render flags (int)

## 🐛 Troubleshooting

### Pillow Not Found
**Error**: "Pillow (PIL) is not installed..."

**Solution**:
1. Run `install_pillow.py` in Blender's Scripting workspace
2. Restart Blender
3. Re-enable the addon

### Textures Not Loading
**Problem**: Materials created but no textures appear

**Check**:
- Assets folder path is correct and accessible
- `.tex` files exist in the specified location
- Pillow is installed correctly
- Check Blender console for error messages (`Window > Toggle System Console`)

### Some Meshes Have No UVs
**Note**: This is normal. Some meshes in mapgeo files are:
- Collision geometry (no UVs needed)
- Shadow casters (no UVs needed)
- Placeholder objects

Only renderable meshes will have UV coordinates.

### Import Takes Long Time
**Reason**: Large mapgeo files (748+ meshes) with texture conversion

**Tips**:
- Disable "Load Materials" for faster import
- Use layer filtering to import only specific layers
- Textures are cached after first load

## 📚 References

Based on and compatible with:
- [LeagueToolkit](https://github.com/LeagueToolkit/LeagueToolkit) by Crauzer and contributors
- [LtMAO Maya Plugin](https://github.com/tarngaina/LtMAO) by tarngaina
- [CommunityDragon](https://github.com/CommunityDragon) texture format documentation

## 📝 Changelog

### Version 0.0.6 (2026-02-11) - Current
- 🐛 Fixed baron hash visibility logic (override behavior)
- 🐛 Fixed import error with update_environment_visibility
- ✅ Baron hash dragon layers now properly override visibility_layer
- ✅ Split dragon/baron filter system working correctly

### Version 0.0.5 (2026-02-11)
- ✅ Baron state viewport filtering (4 states)
- ✅ Baron state collections
- ✅ Split dragon/baron layer filters UI

### Version 0.0.4 (2026-02-11)
- ✅ Baron hash decoding system
- ✅ materials.bin.json parser
- ✅ Automatic visibility controller resolution

### Version 0.0.3 (2026-02-11)
- ✅ Full mapgeo import for versions 13-18 (focused on v18)
- ✅ Multi-vertex buffer support with correct description indexing
- ✅ Complete material loading system with JSON parsing
- ✅ TEX to PNG conversion (BC1/BC3/BGRA8/RGBA16)
- ✅ 8-layer visibility system with filtering
- ✅ Layer-based collection grouping
- ✅ Multi-material mesh support
- ✅ Bush render flag with UI controls
- ✅ Custom properties for all metadata
- ✅ Blender 5.0 compatibility
- ✅ User-friendly Pillow installation

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

This tool is for **educational and modding purposes only**. All rights to League of Legends and its assets belong to **Riot Games, Inc.**

## 👤 Author

**TheKillerey**

## 🙏 Acknowledgments

- **Crauzer** and **LeagueToolkit contributors** for the C# reference implementation
- **tarngaina** for the LtMAO Maya plugin reference
- **CommunityDragon** project for texture format documentation
- **Riot Games** for League of Legends

---

**Found a bug?** Open an issue with:
- Blender version
- Mapgeo version being imported
- Error message from console
- Steps to reproduce

**Want to contribute?** Pull requests are welcome!
