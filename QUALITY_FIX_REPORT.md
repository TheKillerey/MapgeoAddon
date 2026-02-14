# Quality Field Investigation Report
## Date: February 13, 2026

---

## Executive Summary

**ROOT CAUSE IDENTIFIED**: Quality field is a **BITMASK**, not a single enum value. Our code treats it as an enum (0-4), causing all meshes to be visible only at specific quality settings instead of all settings.

---

## Findings

### 1. Quality Values Comparison

**Original File** (`Map11.wad\...\sodapop_srs.mapgeo`):
- All 748 meshes have quality = **31** (0x1F = 0b00011111)
- Quality 31 = ALL bits set (bits 0-4) = visible at ALL quality levels

**Exported File** (`Map11_test\...\sodapop_srs.mapgeo`):
- All 748 meshes have quality = **4** (0x04 = 0b00000100)
- Quality 4 = Only bit 2 set = visible ONLY at MEDIUM quality

### 2. Quality Field Structure

Quality is a **5-bit bitmask** (valid range: 0-31):

| Bit | Value | Quality Level | Description |
|-----|-------|---------------|-------------|
| 0   | 1     | VERY_LOW      | Bit 0: Visible at Very Low quality |
| 1   | 2     | LOW           | Bit 1: Visible at Low quality |
| 2   | 4     | MEDIUM        | Bit 2: Visible at Medium quality |
| 3   | 8     | HIGH          | Bit 3: Visible at High quality |
| 4   | 16    | VERY_HIGH     | Bit 4: Visible at Very High quality |

**Common Values:**
- `31` (0b11111) = All quality levels enabled (standard/default)
- `4` (0b00100) = Only MEDIUM quality (current bug!)
- `8` (0b01000) = Only HIGH quality
- `24` (0b11000) = HIGH + VERY_HIGH
- `15` (0b01111) = All except VERY_HIGH

### 3. How the Bug Occurs

**Import Process** [import_mapgeo.py:503-506]:
```python
quality_value = int(mesh_data.quality)  # Reads 31 from original
if quality_value < 0 or quality_value > 4:  # 31 fails this check!
    print(f"WARNING: ... clamping to Medium (2)")
    quality_value = 2  # ❌ WRONG: Destroys bitmask, sets to MEDIUM-only
obj["quality"] = quality_value  # Stores 2 in Blender object
```

**Export Process** [export_mapgeo.py:78-87, 481-483]:
```python
# Default quality is set to '4' (enum VERY_HIGH)
default_quality: EnumProperty(
    ...
    default='4',  # ❌ WRONG: Should be '31' (all levels)
)

# Later during export:
raw_quality = obj.get("quality", int(self.default_quality))  # Gets 2 or 4
mesh_entry.quality = max(0, min(4, int(raw_quality)))  # Clamps to 0-4
# ❌ WRONG: Should allow 0-31
```

**Result**: 
- Original: quality=31 → Import clamps to 2 → Export with default 4 → File has quality=4
- Mesh only visible when game quality setting is MEDIUM (bit 2)
- User reports: "only Medium quality shows terrain" ✓ MATCHES!

---

## Byte Offset Verification

Quality field offset is **CORRECT** in parser:
- [mapgeo_parser.py:441] Read: `mesh.quality = struct.unpack('<B', stream.read(1))[0]`
- [mapgeo_parser.py:772] Write: `stream.write(struct.pack('<B', mesh.quality))`

Field order for version 18 is correct - no offset calculation errors found.

---

## Specific Fix Recommendations

### Fix 1: Remove Import Clamping
**File**: [import_mapgeo.py](import_mapgeo.py#L502-L506)

**Current code** (WRONG):
```python
# Clamp quality to valid range (0-4) to prevent crashes from corrupted data
quality_value = int(mesh_data.quality)
if quality_value < 0 or quality_value > 4:
    print(f"WARNING: Mesh {mesh_data.name} has invalid quality {quality_value}, clamping to Medium (2)")
    quality_value = 2  # Default to Medium quality
obj["quality"] = quality_value
```

**Fixed code**:
```python
# Quality is a bitmask (0-31) where each bit enables a quality level
# Bit 0=VeryLow, Bit 1=Low, Bit 2=Medium, Bit 3=High, Bit 4=VeryHigh
# Value 31 (0b11111) = all quality levels enabled (standard default)
quality_value = int(mesh_data.quality)
if quality_value < 0 or quality_value > 31:
    print(f"WARNING: Mesh {mesh_data.name} has invalid quality {quality_value}, using default (31=all levels)")
    quality_value = 31  # Default to all quality levels
obj["quality"] = quality_value
```

### Fix 2: Change Export Default Quality
**File**: [export_mapgeo.py](export_mapgeo.py#L78-L87)

**Current code** (WRONG):
```python
default_quality: EnumProperty(
    name="Default Quality",
    description="Default quality level for meshes",
    items=[
        ('0', "Very Low", "Very Low Quality"),
        ('1', "Low", "Low Quality"),
        ('2', "Medium", "Medium Quality"),
        ('3', "High", "High Quality"),
        ('4', "Very High", "Very High Quality"),
    ],
    default='4'
)
```

**Fixed code** (Option A - Simple Fix):
```python
default_quality: EnumProperty(
    name="Default Quality",
    description="Default quality level bitmask for meshes (31 = all levels)",
    items=[
        ('0', "None", "No quality levels (invisible)"),
        ('1', "Very Low Only", "Very Low Quality Only"),
        ('2', "Low Only", "Low Quality Only"),
        ('4', "Medium Only", "Medium Quality Only"),
        ('8', "High Only", "High Quality Only"),
        ('16', "Very High Only", "Very High Quality Only"),
        ('31', "All Levels (Standard)", "All quality levels - meshes visible at any quality setting"),
    ],
    default='31'  # Changed from '4' to '31'
)
```

**Fixed code** (Option B - Better UX with multiple selection):
```python
default_quality_very_low: BoolProperty(
    name="Very Low", default=True, description="Visible at Very Low quality")
default_quality_low: BoolProperty(
    name="Low", default=True, description="Visible at Low quality")
default_quality_medium: BoolProperty(
    name="Medium", default=True, description="Visible at Medium quality")
default_quality_high: BoolProperty(
    name="High", default=True, description="Visible at High quality")
default_quality_very_high: BoolProperty(
    name="Very High", default=True, description="Visible at Very High quality")

def get_quality_bitmask(self):
    """Calculate quality bitmask from individual flags"""
    bitmask = 0
    if self.default_quality_very_low: bitmask |= 1
    if self.default_quality_low: bitmask |= 2
    if self.default_quality_medium: bitmask |= 4
    if self.default_quality_high: bitmask |= 8
    if self.default_quality_very_high: bitmask |= 16
    return bitmask if bitmask > 0 else 31  # Default to all if none selected
```

### Fix 3: Remove Export Clamping
**File**: [export_mapgeo.py](export_mapgeo.py#L481-L485)

**Current code** (WRONG):
```python
raw_quality = obj.get("quality", obj.get("mapgeo_quality", int(self.default_quality)))
# Clamp to valid range (0-4) to prevent game crashes
mesh_entry.quality = max(0, min(4, int(raw_quality)))
if raw_quality != mesh_entry.quality:
    print(f"WARNING: Object {obj.name} had invalid quality {raw_quality}, clamped to {mesh_entry.quality}")
```

**Fixed code**:
```python
# Option A: If using simple enum with default='31'
raw_quality = obj.get("quality", obj.get("mapgeo_quality", int(self.default_quality)))

# Option B: If using multiple bool properties
raw_quality = obj.get("quality", obj.get("mapgeo_quality", self.get_quality_bitmask()))

# Clamp to valid bitmask range (0-31)
mesh_entry.quality = max(0, min(31, int(raw_quality)))
if raw_quality != mesh_entry.quality:
    print(f"WARNING: Object {obj.name} had invalid quality {raw_quality}, clamped to {mesh_entry.quality}")
```

### Fix 4: Remove Validation Error
**File**: [validate_mapgeo.py](validate_mapgeo.py#L518-L522)

**Current code** (WRONG):
```python
# Quality
quality = struct.unpack('<B', self.file_data[offset:offset+1])[0]
offset += 1

if quality > 4:
    self.add_error("MESH", f"Mesh {mesh_idx}: Invalid quality value {quality} (max 4)", mesh_index=mesh_idx)
```

**Fixed code**:
```python
# Quality (bitmask: 0-31)
quality = struct.unpack('<B', self.file_data[offset:offset+1])[0]
offset += 1

if quality > 31:
    self.add_error("MESH", f"Mesh {mesh_idx}: Invalid quality bitmask {quality} (max 31)", mesh_index=mesh_idx)
elif quality == 0:
    self.add_warning("MESH", f"Mesh {mesh_idx}: Quality is 0 (mesh may be invisible)", mesh_index=mesh_idx)
```

### Fix 5: Update Documentation
**File**: [mapgeo_parser.py](mapgeo_parser.py#L65-L70)

**Current code**:
```python
class EnvironmentQuality(IntEnum):
    """Quality levels for environment meshes"""
    VERY_LOW = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4
```

**Add documentation**:
```python
class EnvironmentQuality(IntEnum):
    """Quality levels for environment meshes
    
    NOTE: In mapgeo files, quality is stored as a BITMASK, not a single enum value!
    Each bit represents whether the mesh is visible at that quality level.
    
    Bit 0 (value 1):  VERY_LOW quality enabled
    Bit 1 (value 2):  LOW quality enabled
    Bit 2 (value 4):  MEDIUM quality enabled
    Bit 3 (value 8):  HIGH quality enabled
    Bit 4 (value 16): VERY_HIGH quality enabled
    
    Common values:
    - 31 (0b11111): All quality levels (standard default)
    - 24 (0b11000): HIGH + VERY_HIGH only
    - 4 (0b00100):  MEDIUM only
    
    The enum values below are used as bit positions, not direct quality values.
    """
    VERY_LOW = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4
```

---

## Pattern Analysis

### Original File
- Quality distribution: All 748 meshes = 31 (all quality levels)
- Pattern: **Uniform** - All meshes visible at all quality settings
- Game behavior: ✓ Works at any quality setting

### Exported File  
- Quality distribution: All 748 meshes = 4 (MEDIUM only)
- Pattern: **Uniform but wrong** - All meshes only visible at MEDIUM
- Game behavior: ✗ Terrain only visible at Medium quality setting

### Differences
- **Total mismatches**: 748 out of 748 meshes (100%)
- **Root cause**: Quality 31 → clamped to 2 → exported as 4
- **Impact**: Game functional but content only visible at specific quality setting

---

## Testing Recommendations

After implementing fixes, test with these quality values:

1. **Quality = 31** (all levels): Should see terrain at any quality setting
2. **Quality = 4** (medium only): Should only see terrain at Medium setting
3. **Quality = 24** (high+very high): Should only see terrain at High/Very High
4. **Quality = 0** (none): Should not see terrain at any setting

Expected outcome: Terrain visible at all quality settings (quality=31).

---

## Summary

| Issue | Location | Current Behavior | Fixed Behavior |
|-------|----------|------------------|----------------|
| Import clamps quality to 0-4 | import_mapgeo.py:503-506 | Value 31 → clamped to 2 | Value 31 → preserved as 31 |
| Export default = 4 | export_mapgeo.py:87 | Missing quality uses VERY_HIGH(4) | Missing quality uses All Levels(31) |
| Export clamps quality to 0-4 | export_mapgeo.py:483 | Value 31 → clamped to 4 | Value 31 → preserved as 31 |
| Validation rejects > 4 | validate_mapgeo.py:521 | Quality 31 = error | Quality 31 = valid |

**Recommended Action**: Implement all 5 fixes above. Priority: Fixes 1-3 are critical, Fixes 4-5 are nice-to-have.

