# League of Legends Map Editor for Blender

[![Blender](https://img.shields.io/badge/Blender-5.0+-orange.svg)](https://www.blender.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Status](https://img.shields.io/badge/status-stable-green)

**Edit League of Legends maps in Blender!** Open Summoner's Rift, ARAM, or any League map as a 3D model, make changes, and save them back.

Perfect for:
- 🎨 Creating custom map mods
- 🔍 Studying League's map design
- 🎮 Exploring Summoner's Rift in 3D
- 🛠️ Learning 3D game development

---

## ⚡ Quick Start (3 Steps)

### 1. Install Blender
Download Blender 5.0+ from [blender.org](https://www.blender.org/download/) (it's free!)

### 2. Install This Addon
1. Download this addon (green "Code" button → Download ZIP)
2. In Blender: `Edit` → `Preferences` → `Add-ons` → `Install...`
3. Choose the `__init__.py` file from the addon folder
4. Check the box next to "Import-Export: League of Legends Mapgeo Tools"

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
- Organized by dragon type (Infernal, Ocean, etc.)

### ✏️ Edit Everything
- **Move objects**: Drag trees, rocks, buildings anywhere
- **Delete things**: Remove decorations you don't want
- **Add new models**: Import your own 3D creations
- **Change textures**: Replace with custom images
- **Modify terrain**: Reshape hills, paths, rivers

### 💾 Export Back to Game
- Save your changes as a new `.mapgeo` file
- Everything is preserved: animations, visibility, quality settings
- Works with all League features (dragon states, baron pit, etc.)

---

## 🌟 Key Features Explained

### Dragon Elemental States
League's map changes based on which dragon spawns. Each element has different props:
- **Base** - Default map
- **Infernal** (Red) - Fire and lava themed
- **Mountain** (Gray) - Rocks and stone
- **Ocean** (Blue) - Water and coral
- **Cloud** (White) - Sky and wind
- **Hextech** (Cyan) - Technology themed
- **Chemtech** (Green) - Toxic/industrial themed  
- **Void** (Purple) - Cosmic void themed

**The addon lets you:**
- View each dragon state separately
- Toggle visibility to see specific variants
- Edit props for any dragon state

### Baron Pit Transformations
The baron pit changes appearance when captured:
- **Base** - Normal pit before any baron kills
- **Cup** - After first baron is killed
- **Tunnel** - Underground passage state
- **Upgraded** - Enhanced pit state

**You can:**
- Filter to see each state
- Edit any transformation state
- Control when objects appear/disappear

### Bush Animations
League's bushes sway in the wind - this addon preserves that!
- Import keeps animation data (called TEXCOORD5)
- Export saves it back perfectly
- No setup needed, it just works

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

---

## 📖 How to Use

### Importing a Map

1. **Get the map file**
   - Extract `.mapgeo` files from League using tools like Obsidian
   - Common location: `Map11.mapgeo` (Summoner's Rift)

2. **Open in Blender**
   - `File` → `Import` → `League of Legends Mapgeo (.mapgeo)`
   - Select your `.mapgeo` file

3. **Configure import** (optional)
   - **Assets Folder**: Path to textures (if you want them to load)
   - **Materials File**: `.materials.bin.json` for full materials
   - **Dragon Layer**: Choose which dragon state to view
   - **Baron State**: Choose which baron state to view
   - **Load Materials**: Check this to get textures

4. **Click Import**

The map will load! It might take a minute for large maps like Summoner's Rift (748 objects).

### Editing the Map

After import, you can use normal Blender tools:

**Move objects:**
- Select object → Press `G` → Move mouse → Click to place

**Rotate objects:**
- Select object → Press `R` → Move mouse → Click

**Scale objects:**
- Select object → Press `S` → Move mouse → Click

**Delete objects:**
- Select object → Press `X` → Confirm delete

**Add your own models:**
- `File` → `Import` → Choose format (FBX, OBJ, etc.)

### Viewing Mesh Properties

Select any object and press `N` to open the sidebar:
- **Layer panel** shows which dragon states it appears in
- **Quality** shows which graphics settings use it
- **Bush Flag** shows if it's a wind-animated bush
- **Baron Hash** shows if it's baron-pit controlled

### Exporting Your Changes

When you're ready to test in-game:

1. **Export the map**
   - `File` → `Export` → `League of Legends Mapgeo (.mapgeo)`
   - Choose where to save

2. **Export options**
   - **Export Selected Only**: Check to export only selected objects
   - **Apply Modifiers**: Check if you used Blender modifiers
   - **Triangulate**: Always keep checked (League needs triangles)
   - **Bucket Grid Mode**: Keep as "ORIGINAL"

3. **Click Export**

Your edited map is ready! Replace the original file in League to test.

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
   - **Materials JSON**: Point to `.materials.bin.json` file
   - **Check "Load Materials"**

3. **Import**

Textures will automatically:
- Convert from League's `.tex` format → PNG
- Create Blender materials with proper colors
- Apply to correct objects
- Load lightmaps for realistic lighting

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
- Materials JSON file path is correct
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
**This is normal** - Not al objects need textures:
- Collision geometry (invisible in-game)
- Shadow casters (just for shadows)
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

## 🎯 Example Workflows

### Workflow 1: Remove Decorations
Goal: Make a cleaner version of Summoner's Rift

1. Import `Map11.mapgeo`
2. Set Dragon Layer to "Base"
3. Select decorative objects (flags, crystals, etc.)
4. Delete them (press X)
5. Export as `Map11_clean.mapgeo`
6. Replace original in League folder

### Workflow 2: Add Custom Trees
Goal: Add your own 3D tree models

1. Import `Map11.mapgeo`
2. Import your tree model (File → Import → FBX/OBJ)
3. Scale and position your tree
4. In Properties panel:
   - Set Visibility Layer to 1 (base map)
   - Set Quality to "AllQualities"
5. Select both original map and your tree
6. Export (your tree will be included)

### Workflow 3: Study Dragon Variants
Goal: See all dragon states side-by-side

1. Import map 8 times (once per dragon state)
2. Set each import to a different dragon layer
3. Arrange them in a row in Blender
4. Study the differences
5. Take screenshots or renders

### Workflow 4: Create a Custom Dragon State
Goal: Make a new themed dragon variant

1. Import base map (Layer 1)
2. Import one dragon variant (e.g., Layer 2 Infernal)
3. Duplicate the Infernal props
4. Modify colors/textures  
5. Tag with a different layer (e.g., Layer 6)
6. Export

---

## 💡 Tips and Tricks

### Performance Tips
- **Import only what you need** - Use layer filters
- **Disable materials initially** - Speeds up import
- **Work on smaller sections** - Delete far-away objects
- **Save often** - Large maps can be heavy on RAM

### Modding Tips
- **Always backup originals** - Keep untouched copies
- **Test in Practice Tool** - Safest way to test changes
- **Use collections** - Keep imports organized
- **Name your exports** - Track different versions

### Learning Tips
- **Start with small changes** - Move one object first
- **Study the original** - See how Riot structured things
- **Use layer filters** - Understand what each layer does
- **Experiment!** - You can't break anything permanently

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
- **League modding communities** - Discord servers and forums
- **Blender communities** - For general 3D questions

### What to Include in Bug Reports
1. Blender version (e.g., "5.0.0")
2. What map you're trying to import (e.g., "Map11.mapgeo")
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
- ❌ Creating cheating tools
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
- Love for League and modding ❤️

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
- [ ] Batch export multiple maps
- [ ] Preview render in Blender
- [ ] Automated UV unwrapping for custom models
- [ ] Material template library
- [ ] One-click League folder detection
- [ ] Drag-and-drop import

Suggestions welcome - open an issue!

---

**Happy mapping! 🎮✨**

Found this useful? Star the repo! ⭐
