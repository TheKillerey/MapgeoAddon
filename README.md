# League of Legends Map Editor for Blender

[![Blender](https://img.shields.io/badge/Blender-5.0+-orange.svg)](https://www.blender.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Status](https://img.shields.io/badge/status-stable-green)

**Edit League of Legends maps in Blender!** Open Summoner's Rift, ARAM, or any League map as a 3D model, make changes, and save them back.
---

## ⚡ Quick Start (3 Steps)

### 1. Install Blender
Download Blender 5.0+ from [blender.org](https://www.blender.org/download/) (it's free!)

### 2. Install This Addon
1. Download latest version ([Download ZIP](https://github.com/TheKillerey/MapgeoAddon/archive/refs/heads/main.zip))
2. In Blender: `Edit` → `Preferences` → `Add-ons`
3. Drag and Drop the `.zip` file into the window
4. A new sidebar UI will appear

### 3. Install Pillow (for textures)
1. In Blender, go to `Scripting` workspace (top menu)
2. Open the `install_pillow.py` file from the addon folder
3. Click "Run Script" button
4. Restart Blender

**Done!** Now you can import League maps.

---

## 🎮 What Can You Do?

### 📥 Import League Maps
Open `.mapgeo` files from League in Blender:
- All terrain and objects load as editable 3D models
- Textures automatically convert to PNG
- Materials and colors preserved
- Organized by dragon and baron layer's starting with Base (Same how Riot does)

### 💾 Export Back to Game
- Save your changes as a new `.mapgeo` file
- Everything is preserved: layers, visibility, quality settings
- Works with all League features (dragon states, baron pit, etc.)

---

## 🌟 Key Features Explained

### Dragon Elemental States (Summoners Rift only) - TFT Maps have also different states using this layer system
League's map changes based on which dragon spawns. Each element has different props:
- **Base** - Layer 1 - (Starting Layer)
- **Infernal**  - Layer 2
- **Mountain** - Layer 3
- **Ocean** - Layer 4
- **Cloud** - Layer 5
- **Hextech** - Layer 6
- **Chemtech** - Layer 7
- **Void** - Layer 8 (Not used)

**The addon lets you:**
- View each dragon state separately (Exact how Riot does ingame)
- Toggle visibility to see specific variants
- Edit props for any dragon state

### Baron Pit Transformations
The baron pit changes appearance when captured:
- **Base** - Normal pit before any baron spawns
- **Cup** - Cup passage state after baron spawns
- **Tunnel** - Underground passage state after baron spawns
- **Upgraded** - Enhanced pit state after baron spawns

**You can:**
- Filter to see each state
- Edit any transformation state
- Control when objects appear/disappear

### Baron Hash System (Advanced)

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

Defined in Map11.bin as hash `0xd31ac6ce` with bit-based states (stored in `0x8bff8cdf` property):

- **Base** (Bit value 1): Default state
- **Cup** (Bit value 2): Cup variation
- **Tunnel** (Bit value 4): Tunnel variation
- **Upgraded** (Bit value 8): Upgraded variation

**Note**: Custom maps may have different baron states with different bit values. The system supports any combination of baron states defined in the materials file.

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
    # OVERRIDE: Use baron dragon layers with ParentMode
    is_in_list = (current_dragon in baron_dragon_layers) or (base in baron_dragon_layers)
    if parent_mode == 3:  # Not Visible mode
        dragon_visible = not is_in_list  # Visible when NOT in list
    else:  # Visible mode (default)
        dragon_visible = is_in_list  # Visible when in list
else:
    # STANDARD: Use visibility_layer
    # visibility_layer == 0 means no dragon restriction (always visible)
    if visibility_layer == 0 or visibility_layer == 255:
        dragon_visible = True
    else:
        dragon_visible = (visibility_layer & current_dragon_flag)

# STEP 2: Baron pit visibility (ParentMode also applies here)
if has_baron_hash and has_baron_layers:
    is_in_list = (current_baron_state in baron_layers)
    if parent_mode == 3:  # Not Visible mode
        baron_visible = not is_in_list  # Visible when NOT in list
    else:  # Visible mode (default)
        baron_visible = is_in_list  # Visible when in list
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

- **1**: Visible mode - visible on this layer
- **3**: Not Visible mode - not visible on this layer (but visible on any other layers)
- **Not added**: Changes to default value 1 - Visible mode

## Example: Baron Hash 5E652742

This hash references parents for all 6 dragon layers with ParentMode=3 (Not Visible):
- Mesh is NOT visible on these specific dragon layers
- Used for meshes that should be hidden in elemental states (visible on other layers only)

## In Blender Addon

- **Split Filter System**: Separate dropdowns for dragon layer (8 variants) and baron pit state (4 states)
- **Properties Panel**: Shows baron hash status with decoded layers
- **Baron Pit Layers**: Displays which baron pit states the mesh is visible on (Base, Cup, Tunnel, Upgraded)
- **Referenced Dragon Layers**: Shows dragon layers from baron hash (OVERRIDES visibility_layer when present)
- **Parent Mode**: Displays whether mesh is Visible (1) or Not Visible (3) on referenced layers
- **Baron Hash Assignment**: Can assign custom baron hash values (8 hex characters)
- **Layer Collections**: Meshes organized into both dragon layer and baron state collections
- **Automatic Decoding**: When materials.bin.json / materials.py is loaded during import, baron hashes are automatically decoded
- **Override Behavior**: Baron dragon layers take precedence over visibility_layer when present

## Baron Hash Decoding Process

1. **Parse materials.bin.json / .py** - Index all visibility controllers by PathHash (format: `"{5e652742}"`)
2. **Find Controller** - Look up the baron hash in the indexed controllers
3. **Check Type** - Identify if it's a ChildMapVisibilityController via `__type` field
4. **Get Parents** - Extract parent references from the Parents list
5. **Resolve Parents** - For each parent:
   - Check if it's a dragon layer controller (`__type`: `"{c406a533}"` with `"{27639032}"` property)
   - Check if it's a baron layer controller (`__type`: `"{ec733fe2}"` with `"{8bff8cdf}"` property)
   - If it's another child controller, recursively resolve its parents
6. **Apply ParentMode** - Apply visibility mode (1=Visible, 3=Not Visible) for referenced layers
7. **Store Results** - Save decoded layers and parent mode as custom properties

**Note**: JSON format uses curly braces around hash values: `"{5e652742}"` instead of `0x5e652742` in python

## Custom Properties

- `visibility_layer`: Standard dragon layer bitfield (0-255) - IGNORED if baron hash has dragon_layers
- `baron_hash`: The raw hash value (e.g., "5E652742") (You can put any name also in it if you link it also in materials.py / materials.bin.json)
- `baron_parent_mode`: The parent mode (1=Visible, 3=Not Visible)
- `baron_layers_decoded`: List of baron pit layer bit values (e.g., "[1, 2, 4, 8]") - uses actual bit values from 0x8bff8cdf property
- `baron_dragon_layers_decoded`: List of dragon layer bits (e.g., "[2, 4, 8, 16, 32, 64]") - OVERRIDES visibility_layer when present

### Bush Animations
League's bushes sway in the wind - this addon preserves that!
- Import keeps animation data (called TEXCOORD5)
- Export saves it back perfectly
- No setup needed, it just works
- Using the `LEVELS` folder and `map*.py` give the feature to use GRASS Tint. Same how Riot does it ingame
`*` -> This is the map number. For Summoners Rift we use `map11.py`

We can't create it yet but this feature will be planned

### Quality Levels
League has 5 graphics quality settings. The addon handles all of them:
- Very Low
- Low
- Medium
- High  
- Very High

Each mesh has a quality tag. You can:
- See which quality level each object uses
- Filter to show only certain quality levels
- Change quality settings per object

Default Value for a mesh in League is `31`
Why `31`? because of this:
Very Low -> `1`
Low -> `2`
Medium -> `4`
High -> `8`
Very High -> `16`

`1 + 2 + 4 + 8 + 16` = `31`
 `31` just means that we load the mesh on all quality settings

Some meshes have the value `255` - This just means that you have full quality and your mesh is not affected by the quality settings.
Currently using `32` -> `254` will be the same as `31` but the usage for that is currently unknown.

---

## 📖 How to Use

### Importing a Map

1. **Configure import** (optional)
   - **Assets Folder**: Path to textures (if you want them to load)
   - **Materials File**: `.materials.bin.json` / `.materials.py` (recommended) for full materials
   - **Levels Folder**: Path to get grass tint maps (if you want them to load)
   - **Map*.py File**: Check this to get grass tint maps working in viewport

2. **Get the map file**
   - Extract `.mapgeo` files from League using tools like Obsidian
   - Common location: `Map11.wad\data\maps\mapgeometry\map11\base_srx.mapgeo` (Summoner's Rift)

3. **Open in Blender**
   - `File` → `Import` → `League of Legends Mapgeo (.mapgeo)`
   - Select your `.mapgeo` file

4. **Click Import**

The map will load! It might take a minute for large maps like Summoner's Rift (748 objects).


### Exporting Your Changes

When you're ready to test in-game:

1. **Export the map**
   - `File` → `Export` → `League of Legends Mapgeo (.mapgeo)`
   - Choose where to save

2. **Export options**
   - **Export Selected Only**: Check to export only selected objects
   - **Apply Modifiers**: Check if you used Blender modifiers
   - **Triangulate**: Always keep checked (League needs triangles)
   - **Bucket Grid Mode**: Keep as "ORIGINAL" / "CUSTOM" is broken and will not work

3. **Click Export**

Your edited map is ready! Replace the original file in League to test using your favorite Custom Skin manager

⚠️ **Always backup the original file first!**

---

## 🎨 Working With Textures

### Auto-Loading Materials

For textures to load automatically:

1. **Extract game assets**
   - Use Obsidian or similar tool
   - Extract the map's folder (e.g., `Map11.wad/assets/`)

2. **In the import dialog:**
   - **Assets Folder**: Point to extracted `assets/` folder
   - **Materials JSON/PY**: Point to `.materials.bin.json` / `.materials.py` file
   - **Check "Load Materials"**

3. **Import**

Textures will automatically:
- Convert from League's `.tex` format → PNG
- Create Blender materials with proper colors
- Apply to correct objects
- Load lightmaps for realistic lighting same as how Riot does it ingame.

### Manual Material Setup

If auto-loading doesn't work:

1. **Get texture files** (`.tex` files from game)
2. **Convert to PNG** using Obsidian or similar
3. **In Blender:**
   - Select object
   - Go to Shading workspace
   - Add Principled BSDF shader
   - Add Image Texture node
   - Load your PNG file
   - Connect Color → Base Color

---

## 🔧 Troubleshooting

### "Pillow not installed" error
**Solution:** Run the `install_pillow.py` script in Blender's Scripting workspace, then restart Blender.

### Textures don't load
**Check:**
- Assets folder path is correct
- Materials JSON / PY file path is correct
- "Load Materials" checkbox is enabled
- Pillow is installed
- `.tex` files exist in the assets folder

### Import freezes or crashes
**Try:**
- Import without materials first (uncheck "Load Materials")
- Filter to one dragon layer only
- Close other programs to free RAM
- Update to latest Blender version

### Some objects have no textures
**This is normal** - Not all objects need textures:
- Collision geometry (invisible in-game) named Bucketgrid
- Visual effects objects (use particle systems instead)

### Export file is larger than original
**This is expected** - The addon exports slightly larger files because:
- It keeps all vertex data that might be needed
- Original files have optimizations we can't replicate perfectly
- Doesn't affect game performance

### Objects disappear when changing dragon/baron filter
**This is correct behavior** - Objects are tagged to appear only in specific states. Use the layer panel to see which states an object belongs to.

---

## 📚 Understanding the Technical Stuff

### What is a .mapgeo file?
League's 3D map format. Contains:
- 3D geometry (vertices, faces)
- Texture coordinates (UV mapping)
- Vertex colors
- Layer visibility tags
- Quality settings
- Animation data
- Material references

### Coordinate Systems
- **League uses**: X, Y, Z where Y is up
- **Blender uses**: X, Z, Y where Z is up
- **The addon handles this automatically** - you don't need to do anything

### Layers vs Dragon States
- League has 8 "layers" that control visibility
- Each dragon state uses different layers
- Layer 1 = Base map (always visible)
- Layers 2-8 = Different dragon variants
- Objects can be visible in multiple layers simultaneously

### What's preserved on export?
Everything:
- ✅ All geometry
- ✅ All textures and UVs
- ✅ Vertex colors
- ✅ Bush animation data
- ✅ Layer tags
- ✅ Quality settings
- ✅ Baron pit visibility
- ✅ Lightmap data
- ✅ Transform matrices (position/rotation/scale)

---

## 📁 Addon Files Explained

```
MapgeoAddon/
├── __init__.py              # Main addon file (install this)
├── import_mapgeo.py         # Handles importing .mapgeo files
├── export_mapgeo.py         # Handles exporting back to .mapgeo
├── mapgeo_parser.py         # Reads/writes the binary format
├── material_loader.py       # Loads textures and materials
├── texture_utils.py         # Converts .tex files to PNG
├── ui_panel.py              # Creates the sidebar panel
├── install_pillow.py        # Helper to install Pillow
├── utils.py                 # Miscellaneous helper functions
├── README.md                # This file
├── CHANGELOG.md             # Version history
└── LICENSE                  # MIT License
```

---

## 🆘 Getting Help

### Where to Ask Questions
- **Issues tab** on GitHub - Report bugs or ask questions
- **League modding communities** - My Discord Server  [PROJECT: Rey](https://discord.gg/V3UWZbDGqj)
- **Blender communities** - For general 3D questions

### What to Include in Bug Reports
1. Blender version (e.g., "5.0.0")
2. What map you're trying to import (e.g., "base_srx.mapgeo")
3. Error message from Blender console
4. What you were doing when it broke

### Useful Resources
- [Blender Manual](https://docs.blender.org/manual/en/latest/) - Learn Blender basics
- [LeagueToolkit GitHub](https://github.com/LeagueToolkit/LeagueToolkit) - Technical format details
- [CommunityDragon](https://communitydragon.org/) - League file format documentation

---

## 📜 Legal Stuff

**Educational and Modding Use Only**

This tool is for:
- ✅ Learning how League maps work
- ✅ Personal experimentation
- ✅ Creating mods for personal use
- ✅ Educational purposes

This tool is NOT for:
- ❌ Gaining unfair advantages online
- ❌ Distributing modified game files
- ❌ Commercial use

**All rights to League of Legends and its assets belong to Riot Games, Inc.**

Using this tool is at your own risk. Modifying game files may violate Terms of Service.

---

## 🙏 Credits

**Created by:** TheKillerey

**Special Thanks:**
- **Riot Games** - For creating League of Legends
- **Crauzer & LeagueToolkit contributors** - C# format reference
- **tarngaina** - LtMAO Maya plugin reference
- **CommunityDragon** - Format documentation

**Built with:**
- Blender 5.0+
- Python
- Love for League and the custom skin community ❤️

---

## 📝 Version History

### v0.1.0 (February 13, 2026) - Current
- ✨ **Full import and export support** - Complete round-trip editing
- ✨ **All League features working** - Dragons, baron, bushes, lightmaps
- ✨ **Stable release** - Production ready
- 🐛 **All major bugs fixed** - Render regions, animations, transforms
- 📖 **Newbie-friendly docs** - Complete rewrite of README

### v0.0.9 (February 12, 2026)
- Lightmap support
- Materials system improvements

### v0.0.3-0.0.8
- Initial development
- Basic import functionality
- Layer system
- Material loading

---

## 🚀 Future Plans

Potential features for future versions:
- [ ] Automated Bucketgrid creation
- [ ] Material template library
- [ ] Lightmap Baking
- [ ] Full particle support
- [ ] Full project workflow
- [ ] Direct reading of TEX files in blender without converting them
- [ ] Map Object Support
- [ ] Dynamic Light Support
- [ ] Vertex Animations

Suggestions welcome - open an issue!

---

**Happy mapping! 🎮✨**

Found this useful? Star the repo! ⭐