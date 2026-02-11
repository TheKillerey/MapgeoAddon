# Installation Guide - League of Legends Mapgeo Addon

This guide will walk you through installing the addon step-by-step. The process takes about 5 minutes.

## 📦 Prerequisites

Before you start, make sure you have:

- ✅ **Blender 5.0 or higher** installed
- ✅ **Internet connection** (for installing Pillow)
- ✅ The **MapgeoAddon folder** (from this repository)

---

## 🚀 Installation Steps

### Step 1: Install the Addon in Blender

#### Option A: Install from Folder (Recommended)

1. **Open Blender 5.0+**

2. **Go to Preferences**:
   - Click `Edit` in the top menu
   - Select `Preferences...`

3. **Navigate to Add-ons**:
   - Click the `Add-ons` tab on the left

4. **Install the addon**:
   - Click the `Install...` button at the top right
   - Navigate to the `MapgeoAddon` folder
   - Select the `__init__.py` file
   - Click `Install Add-on`

5. **Enable the addon**:
   - In the search box, type: `mapgeo`
   - Find **"Import-Export: League of Legends Mapgeo Tools"**
   - Check the checkbox to enable it

#### Option B: Install from ZIP

1. **Create a ZIP file**:
   - Compress the entire `MapgeoAddon` folder to `MapgeoAddon.zip`

2. **Follow the same steps as Option A**, but select the ZIP file instead

### Step 2: Verify the Addon is Loaded

After enabling the addon, you should see:

1. **In the File menu**:
   - `File > Import > League of Legends Mapgeo (.mapgeo)`

2. **In the Edit menu (Preferences)**:
   - The addon settings appear when you expand the addon entry
   - You'll see options for "Assets Folder" and "Materials JSON Path"

✅ If you see these menu items, the addon is successfully installed!

---

## 🎨 Step 3: Install Pillow (Required for Textures)

Pillow is a Python library needed to convert League's `.tex` texture files to `.png` format.

### Quick Install Method (Recommended)

1. **Open Blender** (if not already open)

2. **Go to Scripting workspace**:
   - Click `Scripting` at the top of the window
   - Or go to the top-left dropdown and select `Scripting`

3. **Open the install script**:
   - Click `Open` in the text editor header
   - Navigate to the `MapgeoAddon` folder
   - Select `install_pillow.py`
   - Click `Open Text`

4. **Run the script**:
   - Click the `▶ Run Script` button
   - Or press `Alt + P`

5. **Wait for completion**:
   - You should see output in the console
   - Look for: `✓ SUCCESS! Pillow has been installed successfully.`

6. **Restart Blender**:
   - Close and reopen Blender completely
   - This is **required** for Pillow to be recognized

### Alternative: Command Line Method

If the script method doesn't work, you can install Pillow manually:

**On Windows:**
```bash
python -m pip install --user Pillow
```

**On macOS/Linux:**
```bash
python3 -m pip install --user Pillow
```

Then restart Blender.

### Verify Pillow Installation

1. **Open Blender**
2. **Go to Scripting workspace**
3. **Type this in the console**:
   ```python
   import PIL
   print("Pillow version:", PIL.__version__)
   ```
4. **Press Enter**

✅ If you see a version number (e.g., "Pillow version: 10.2.0"), Pillow is installed correctly!

❌ If you see an error, repeat Step 3 or see Troubleshooting below.

---

## 🎯 Step 4: Configure the Addon

After installation and restarting Blender:

1. **Go to Addon Preferences**:
   - `Edit > Preferences > Add-ons`
   - Search for "mapgeo"
   - Expand the addon by clicking the arrow

2. **Set the Assets Folder** (optional, for texture loading):
   - Click the folder icon
   - Navigate to your extracted League WAD assets folder
   - Example: `C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\assets\`

3. **Set the Materials JSON Path** (optional, for material loading):
   - Click the folder icon
   - Select your `.materials.bin.json` file
   - Example: `C:\LeagueFiles\sodapop_srs.materials.bin.json`

4. **Click "Save Preferences"** at the bottom left

> **Note**: These settings are optional. You can set them later when importing files.

---

## ✅ Verification Checklist

Make sure everything is working:

- [ ] Addon appears in `Edit > Preferences > Add-ons`
- [ ] `File > Import > League of Legends Mapgeo (.mapgeo)` menu item exists
- [ ] Pillow is installed (no import errors when using the addon)
- [ ] (Optional) Assets folder and materials JSON paths are configured

---

## 🐛 Troubleshooting

### Problem: "Pillow (PIL) is not installed"

**Solution 1**: Run the `install_pillow.py` script again
1. Make sure you're running it in **Blender's** Scripting workspace
2. Check the console output for errors
3. Restart Blender after installation

**Solution 2**: Manual installation
```bash
# Windows
python -m pip install --user Pillow

# macOS/Linux
python3 -m pip install --user Pillow
```

**Solution 3**: Check Python path
1. Open Blender console: `Window > Toggle System Console` (Windows) or check terminal (macOS/Linux)
2. In Blender's Python console, type:
   ```python
   import sys
   print(sys.executable)
   ```
3. Use that path to install Pillow:
   ```bash
   "C:\Path\To\Blender\5.0\python\bin\python.exe" -m pip install --user Pillow
   ```

### Problem: Addon doesn't appear in preferences

**Possible causes:**
1. Wrong file selected (make sure you selected `__init__.py`)
2. Blender version too old (requires 5.0+)
3. Files are missing from the folder

**Solution:**
1. Re-download the complete addon folder
2. Make sure all files are present:
   - `__init__.py`
   - `mapgeo_parser.py`
   - `import_mapgeo.py`
   - `export_mapgeo.py`
   - `material_loader.py`
   - `texture_utils.py`
   - `ui_panel.py`
   - `utils.py`

### Problem: Import fails with "module not found"

**Solution:**
1. Check Blender console for the specific module name
2. Make sure all `.py` files are in the same folder
3. Try disabling and re-enabling the addon
4. Restart Blender

### Problem: Textures don't load

**Check these:**
1. ✅ Pillow is installed correctly
2. ✅ Assets folder path is correct and accessible
3. ✅ `.tex` files exist in the assets folder
4. ✅ "Load Materials" option is enabled during import
5. ✅ Materials JSON path is valid

**Debug steps:**
1. Open Blender console: `Window > Toggle System Console`
2. Try importing again and watch for error messages
3. Check if `.tex` files are being found (you'll see conversion messages)

### Problem: Slow import with many meshes

**This is normal!** Large mapgeo files (700+ meshes) with textures take time.

**Speed up import:**
- ✅ Disable "Load Materials" option
- ✅ Use "Layer Visibility" filter to import only specific layers
- ✅ Import materials afterwards for selected meshes only

---

## 🔧 Advanced: Manual Pillow Installation in Blender Python

If all else fails, you can install Pillow directly into Blender's Python:

### Windows:
```batch
"C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\bin\python.exe" -m pip install --user Pillow
```

### macOS:
```bash
/Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 -m pip install --user Pillow
```

### Linux:
```bash
/path/to/blender/5.0/python/bin/python3.11 -m pip install --user Pillow
```

Then restart Blender.

---

## 📚 Next Steps

Once everything is installed:

1. **Read the [README.md](README.md)** for usage instructions
2. **Check [CHANGELOG.md](CHANGELOG.md)** for version history
3. **Try importing a `.mapgeo` file** to test the addon

---

## 💡 Tips

- **Save your preferences** after configuring paths (bottom-left button in Preferences)
- **Keep the addon folder** - you might need `install_pillow.py` again after Blender updates
- **Internet required** only for initial Pillow installation
- **No administrator rights needed** - we use `--user` installation

---

## 🆘 Still Having Issues?

If you're still experiencing problems:

1. **Check the Blender console** for error messages
2. **Try with a fresh Blender installation**
3. **Make sure you're using Blender 5.0 or higher**
4. **Verify Python version** (should be 3.11+):
   ```python
   import sys
   print(sys.version)
   ```

---

**Installation Complete!** 🎉

You're now ready to import League of Legends mapgeo files into Blender.
