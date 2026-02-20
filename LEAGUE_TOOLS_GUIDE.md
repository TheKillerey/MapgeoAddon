# League Tools - Troybin Particle Editor

## Overview
The League Tools panel provides a user-friendly interface in Blender for working with League of Legends `.troybin` particle files. You can import, view, edit, and export particle effects directly within Blender.

## Location
Access the League Tools panel in Blender's 3D Viewport:
- Open the **Sidebar** (press `N` if hidden)
- Look for the **"League Tools"** tab
- Click to open the Troybin Particle Editor

## Features

### 1. Import Troybin Files
**Import Troybin** button - Browse and load any `.troybin` particle file from your League of Legends mod directory or game files.

**What happens on import:**
- File is parsed and validated
- All emitters are detected and listed
- Properties are automatically unhashed (resolved to human-readable names)
- Statistics shown: number of emitters, total properties, resolution percentage

### 2. Export Troybin Files
**Export Troybin** button (visible when a file is loaded) - Save your modified particle data back to a `.troybin` file.

**Features:**
- Preserves binary format compatibility
- Maintains string table ordering for byte-identical output
- Defaults to original filepath or allows choosing new location

### 3. Create New Particles
**New Particle** button (visible when no file is loaded) - Create a fresh particle effect from scratch.

**What you get:**
- Minimal valid troybin structure
- Single emitter with custom name
- Ready to be expanded with properties
- Can be exported immediately

### 4. View File Information
The **File Info** box displays:
- Current filename (or "\<New Particle\>" for new creations)
- Number of emitters in the particle system
- Total property count

### 5. Emitters Panel
Expandable **Emitters** section shows all particle emitters:
- Emitter name (e.g., `core_glow`, `sparkles`, `trail`)
- Property count per emitter
- Select emitters to filter properties (planned feature)

### 6. Properties Panel
Expandable **Properties** section displays all particle properties:

**Display Options:**
- **Show Hashes** - Toggle to show property hashes alongside names

**Property List:**
- Organized by type (Int32List, Float32List, Vec3, Vec4, StringList, etc.)
- Shows property names (unhashed when possible)
- Displays current values
- First 5 properties per type shown (with "...and N more" for larger sets)

**Property Types:**
- **Int Lists** - Integer values (lifetimes, rates, types)
- **Float Lists** - Decimal values (scales, speeds)
- **Vec2/Vec3/Vec4** - Vector values (positions, velocities, rotations, colors)
- **Bit Lists** - Boolean flags (backface rendering, simulation settings)
- **String Lists** - Text values (mesh names, texture paths, emitter names)

### 7. Reload & Clear
- **Reload** - Re-read the current file from disk (useful after external edits)
- **Clear** - Remove all loaded data and reset the editor

## Typical Workflow

### Editing Existing Particles
1. Click **Import Troybin**
2. Browse to your `.troybin` file (e.g., from `DATA/Particles/`)
3. Review the **Emitters** panel to see all effects
4. Expand **Properties** to view current values
5. *(Property editing in development)*
6. Click **Export Troybin** to save changes
7. Test in game!

### Creating New Particles
1. Click **New Particle**
2. Enter emitter name (e.g., `my_awesome_effect`)
3. *(Add properties via UI - in development)*
4. Click **Export Troybin** to save
5. Reference in your mod's particle system

### Analyzing Particles
1. Import any `.troybin` file from the game
2. Check **File Info** for statistics
3. Review **Emitters** to understand the effect structure
4. Examine **Properties** to see how colors, scales, meshes, and behaviors are configured
5. Enable **Show Hashes** to see the binary hash values if needed

## Property Reference

### Common Properties (Unhashed Names)

**System Section:**
- `GroupPart0`, `GroupPart1`, ... - Emitter names
- `GroupPart0Type`, ... - Emitter types (Simple, Complex, etc.)
- `SimulateEveryFrame` - Simulation mode

**Emitter Properties (per emitter):**
- `e-life` - Emitter lifetime (-1 = infinite)
- `e-rate` - Emission rate (particles per second)
- `e-rgba` - Emitter color (RGBA 0-255)
- `p-life` - Particle lifetime
- `p-scale` - Particle scale (Vec3)
- `p-vel` - Particle velocity (Vec3)
- `p-rotvel` - Particle rotation velocity (Vec3)
- `p-offset` - Particle spawn offset (Vec3)
- `p-type` - Particle render type (0=billboard, 3=mesh, etc.)
- `p-mesh` - Mesh filename (e.g., `saucer7.scb`)
- `p-texture` - Texture filename (e.g., `glows.dds`)
- `p-meshtex` - Mesh texture filename
- `p-backfaceon` - Enable backface rendering
- `rendermode` - Render mode setting

### Property Value Ranges
- **Colors** - RGBA values typically 0-255
- **Scales** - Arbitrary units (game scale)
- **Lifetimes** - Seconds (floating point)
- **Velocities** - Units per second
- **Rotation** - Degrees per second

## Technical Details

### Hash Resolution
Properties are stored with SDBM hash keys. The UI automatically resolves hashes to names using:
- System field names
- Group-specific field names (GPART_VARS, COLOR_VARS, RAND_VARS)
- Flex field generation (e0-e49, p0-p49)

Resolution rates vary depending on the particle:
- **100%** - Simple particles with known fields
- **82-95%** - Complex particles with some custom fields
- **Hash display** - Shows `0x12345678` format for unresolved properties

### File Format
- **Version 2** - Current League of Legends troybin format
- **13 Property Types** - Int32List, Float32List, Vec2/3/4, BitList, etc.
- **Binary Compact** - Efficient storage (typical files 200-500 bytes)
- **String Table** - Shared string storage at end of file

## Troubleshooting

**"No file loaded" error**
- Import a troybin file first using the Import button

**"Failed to import" error**
- Check file is a valid `.troybin` (version 2 format)
- Check file path is accessible
- Look for error details in Blender's console

**Missing properties**
- Some properties may show as hashes (`0x...`) if not in the dictionary
- This is normal for custom or unknown fields

**Export doesn't work**
- Make sure a file is loaded (File Info shows filename)
- Check export path is writable
- Check Blender console for detailed error messages

## Future Features (Planned)
- ✅ Import/Export troybin files
- ✅ View emitters and properties
- ✅ Automatic hash resolution
- ⏳ Edit property values directly in UI
- ⏳ Add/remove properties
- ⏳ Add/remove emitters
- ⏳ Visual preview of particle effects
- ⏳ Property templates for common effects
- ⏳ Batch editing multiple particles

## Python API Access
The underlying troybin parser can be used directly:

```python
from pathlib import Path
import bpy

# Access via Blender context
settings = bpy.context.scene.troybin_settings

# Import programmatically
bpy.ops.troybin.import_file(filepath="path/to/particle.troybin")

# Check loaded data
print(f"Loaded: {settings.is_loaded}")
print(f"Emitters: {len(settings.emitters)}")
print(f"Properties: {len(settings.properties)}")

# Export
bpy.ops.troybin.export_file(filepath="path/to/output.troybin")
```

See `troybin_parser.py` and `TROYBIN_README.md` for direct parser usage.

## Support
- Check `TROYBIN_README.md` for parser documentation
- Review `troybin_example.py` for Python usage examples
- Review `create_custom_particle.py` for file creation templates
- Test particles available: `custom_magical_aura.troybin`, `test_simple_glow.troybin`
