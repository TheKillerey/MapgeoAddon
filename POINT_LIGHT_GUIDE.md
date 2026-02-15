# Point Light System - Usage Guide

## ⚠️ IMPORTANT: Custom Feature Warning

**Point lights are NOT used in official League of Legends maps!**

- The `stationary_light` field exists in .mapgeo format but is **completely unused**
- Research of 195 official mapgeo files found **ZERO meshes** using this field
- This feature is for **custom/modded maps only**
- Requires a modded game client or custom rendering pipeline

See `STATIONARY_LIGHT_RESEARCH.md` for complete research findings.

---

## Feature Overview

This addon includes a point light system that:
- ✅ Creates Blender Point Light objects in the viewport
- ✅ Stores light data as custom properties on meshes
- ✅ Imports/exports light data for round-trip workflow
- ✅ Exports to JSON for custom rendering pipelines
- ❌ Does NOT work in official League client

---

## How to Use

### 1. Adding Point Lights

**Method A: Via Panel (Recommended)**

1. Select mesh object(s) in the viewport
2. Open sidebar (`N` key) → `LoL Mapgeo` tab
3. Scroll to "Point Lights (Custom Feature)" section
4. Click **"Add Point Light to Selected"**
5. Configure light parameters in dialog:
   - **Color**: RGB color of the light
   - **Intensity**: Light power in Watts (default: 500)
   - **Radius**: Influence radius (default: 5)
   - **Z Offset**: Height above mesh origin (default: 2)
6. Click OK

**Result**: A Blender Point Light object is created and parented to the mesh.

### 2. Viewing Point Lights

Point lights appear as:
- 🔆 Light icon objects in the viewport
- 📊 Listed in Outliner as `[MeshName]_PointLight`
- 🔗 Parented to the mesh (moves with it)

The mesh gains custom properties:
- `point_light_enabled` = True
- `point_light_color` = [R, G, B]
- `point_light_intensity` = Watts
- `point_light_radius` = Influence radius
- `point_light_offset_z` = Z offset

### 3. Editing Point Lights

**Edit Light Properties**:
1. Select the light object in viewport or Outliner
2. Go to Properties Panel → Light Properties
3. Modify: Color, Power, Radius, etc.
4. Changes are visual-only (not saved to custom properties automatically)

**Edit Custom Properties** (for export):
1. Select the mesh object (not the light object)
2. Properties Panel → Object Properties → Custom Properties
3. Edit `point_light_*` values directly

### 4. Removing Point Lights

1. Select mesh object(s) with point lights
2. Open sidebar → `LoL Mapgeo` tab
3. Click **"Remove from Selected"**

**Result**: 
- Light object deleted from scene
- Custom properties removed from mesh

### 5. Exporting Point Lights

**Export to JSON** (for custom renderers):

1. Open sidebar → `LoL Mapgeo` tab
2. Click **"Export Lights to JSON"**
3. Choose save location
4. JSON file created with all point light data

**JSON Format**:
```json
{
  "version": 1,
  "note": "Custom point light data - not used in official League maps",
  "lights": [
    {
      "mesh_name": "Terrain_Mesh_001",
      "type": "point",
      "position": [123.45, 678.90, 100.0],
      "color": [1.0, 0.95, 0.8],
      "intensity": 500.0,
      "radius": 5.0,
      "offset_z": 2.0
    }
  ]
}
```

### 6. Importing Maps with Point Lights

If you import a .mapgeo that has point light custom properties:
- Light objects are **automatically created** in Blender
- Lights are parented to meshes
- All properties restored from custom properties

---

## Use Cases

### ✅ Recommended Uses

1. **Custom Map Visualization** - Preview lighting in Blender viewport
2. **Render Prep** - Create point lights for Cycles/Eevee rendering
3. **Modded Maps** - Design lighting for custom game clients
4. **JSON Export** - Export light data for custom rendering pipelines
5. **Documentation** - Mark important locations with lights

### ❌ NOT Recommended

1. **Official League Client** - Point lights will be ignored
2. **Competitive Maps** - Not compatible with tournament clients
3. **Public Custom Games** - Most clients don't support custom lighting

---

## Technical Details

### Storage Format

Point light data is stored in **two ways**:

1. **Blender Light Object** (visual only):
   - Type: POINT
   - Color: Light Properties → Color
   - Power: Light Properties → Energy (Watts)
   - Radius: Light Properties → Shadow Soft Size

2. **Mesh Custom Properties** (for export):
   - `point_light_enabled`: Boolean
   - `point_light_color`: [R, G, B] float array
   - `point_light_intensity`: Float (Watts)
   - `point_light_radius`: Float
   - `point_light_offset_z`: Float

### Why Separate Storage?

- Blender light properties are **not saved in .mapgeo files**
- Custom properties ensure data survives import/export cycles
- JSON export uses custom properties, not Blender light settings

### Coordinate System

Point lights use Blender's coordinate system:
- **Position**: Blender world coordinates (X, Z, Y in League terms)
- **Offset**: Z-axis offset from mesh origin
- JSON export includes mesh world position

---

## FAQ

**Q: Will these lights work in League of Legends?**  
A: No. The stationary_light field is unused in all official maps. This feature is for custom/modded projects only.

**Q: What file format stores the lights?**  
A: Lights are stored as custom properties on meshes. Export to JSON for external use.

**Q: Can I import lights from JSON?**  
A: Not yet. Currently only export is supported. You can manually add point_light custom properties to meshes.

**Q: Why did you add this if it doesn't work?**  
A: For custom map projects, Blender rendering, and because the field exists in the .mapgeo format (even if unused). Users requested light placement tools.

**Q: What about baked lightmaps?**  
A: Baked lightmaps (baked_light channel) ARE used in official maps. This addon fully supports importing/exporting them. Point lights are a separate, custom feature.

**Q: Can I use these for Blender rendering?**  
A: Yes! Point lights work perfectly for Cycles/Eevee rendering. Enable Eevee shadows for best results.

---

## Troubleshooting

**Issue**: Light objects don't appear in viewport  
**Fix**: Check Object Types Visibility in top-right (Light icon should be enabled)

**Issue**: Light doesn't move with mesh  
**Fix**: Re-apply: Select light object → Alt+P → Clear Parent, then re-parent properly

**Issue**: Custom properties lost after export/import  
**Fix**: Point light properties should persist. Check if you're selecting mesh (not light) when checking properties.

**Issue**: JSON export has wrong positions  
**Fix**: Apply all transforms before export: Object → Apply → All Transforms

**Issue**: Too many lights causing performance issues  
**Fix**: Reduce light count, disable shadows in Eevee settings, or use Cycles rendering

---

## Related Documentation

- `STATIONARY_LIGHT_RESEARCH.md` - Full research findings
- `CHANGELOG.md` - Version history and feature list
- `README.md` - General addon documentation

---

**Remember**: This is a custom feature for modded/custom projects. Lights will NOT work in the official League of Legends client.
