# Troybin Parser

A complete reader and writer for League of Legends `.troybin` particle effect files with full unhashing support.

## Features

- ✅ **Read & Write** - Parse and create troybin files
- ✅ **Unhashing** - Automatic property name resolution (e.g., `0x9A8D971A` → `[crown] p-scale`)
- ✅ **JSON Export** - Convert to human-readable JSON with property names
- ✅ **Field Name Support** - Create files using readable field names instead of hashes
- ✅ **Multi-Emitter** - Full support for particle effects with multiple emitters
- ✅ **Byte-Perfect** - Verified to produce identical output to original files

## Quick Start

### Command Line Usage

```bash
# View troybin contents with unhashed property names
python troybin_parser.py particle.troybin --dump

# Convert to JSON for easy editing
python troybin_parser.py particle.troybin --to-json particle.json

# Convert back from JSON
python troybin_parser.py new_particle.troybin --from-json particle.json
```

### Python API

#### Read a troybin file

```python
from troybin_parser import parse_troybin, extract_group_names, build_hash_map

# Parse file
data = parse_troybin(Path("particle.troybin"))

# Get emitter names and build hash map for unhashing
group_names = extract_group_names(data)
hash_map = build_hash_map(group_names)

# Access properties with names
for set_name, entries in data['sets'].items():
    for hash_value, value in entries:
        label = hash_map.get(hash_value, f"0x{hash_value:08X}")
        print(f"{label} = {value}")
```

#### Create a troybin using field names

```python
from troybin_parser import write_troybin, section_field_hash_proper

emitter_name = "glow"

data = {
    "version": 2,
    "sets": {
        "StringList": [
            # Define the emitter in System section
            (section_field_hash_proper("System", "GroupPart0"), emitter_name),
            
            # Add emitter properties
            (section_field_hash_proper(emitter_name, "p-mesh"), "particle.scb"),
            (section_field_hash_proper(emitter_name, "p-meshtex"), "glow.dds"),
        ],
        "Int8List": [
            (section_field_hash_proper(emitter_name, "p-life"), 2),
            (section_field_hash_proper(emitter_name, "e-rate"), 10),
        ],
        "Float32ListVec3": [
            (section_field_hash_proper(emitter_name, "p-scale"), [10.0, 10.0, 10.0]),
        ],
    }
}

write_troybin(Path("output.troybin"), data)
```

## Property Types

The parser supports all 13 Inibin v2 property types:

- `Int32List` - 32-bit integers
- `Float32List` - 32-bit floats
- `FixedPointFloatList` - Fixed-point floats (0.1 precision)
- `Int16List` - 16-bit integers
- `Int8List` - 8-bit integers
- `BitList` - Boolean flags
- `FixedPointFloatListVec3` - Fixed-point 3D vectors
- `Float32ListVec3` - Float 3D vectors
- `FixedPointFloatListVec2` - Fixed-point 2D vectors
- `Float32ListVec2` - Float 2D vectors
- `FixedPointFloatListVec4` - Fixed-point 4D vectors
- `Float32ListVec4` - Float 4D vectors
- `StringList` - Null-terminated strings

## Common Particle Properties

### System Section
- `GroupPart0..49` - Emitter names
- `GroupPart0Type..49Type` - Emitter types ("Simple", "Complex")
- `MaterialOverride0..4*` - Material overrides

### Emitter Properties
- `e-life` (Int16) - Emitter lifetime (-1 = infinite)
- `e-rate` (Int8) - Emission rate
- `e-rgba` (Vec4) - Emitter color
- `p-life` (Int8) - Particle lifetime
- `p-type` (Int8) - Particle type
- `p-scale` (Vec3) - Particle scale
- `p-offset` (Vec3) - Particle offset
- `p-mesh` (String) - Mesh file (.scb)
- `p-meshtex` (String) - Texture file (.dds)
- `rendermode` (String) - Render mode

See [troybin_example.py](troybin_example.py) for more examples.

## JSON Format

Exported JSON includes unhashed property names:

```json
{
  "version": 2,
  "emitters": ["crown"],
  "properties": {
    "0x9A8D971A": {
      "hash": 2592970522,
      "type": "FixedPointFloatListVec3",
      "value": [30, 30, 30],
      "section": "crown",
      "field": "p-scale",
      "name": "[crown] p-scale"
    }
  }
}
```

## Hash Algorithm

Troybin uses a modified SDBM hash algorithm:

```python
# Hash formula for property: [section] field
section_hash = sdbm_hash(section.lower())
star_hash = sdbm_hash("*", section_hash)
final_hash = sdbm_hash(field.lower(), star_hash)
```

Use `section_field_hash_proper(section, field)` to calculate hashes.

## Examples

See the example files for detailed usage:
- [troybin_example.py](troybin_example.py) - API usage examples
- [test_troybin_unhashed.py](test_troybin_unhashed.py) - Create particles from scratch

## Testing

Tested with the sample file `chaos_inhibit_base_glow.troybin`:
- ✅ Read: All 22 properties parsed correctly
- ✅ Unhash: 22/22 properties resolved
- ✅ Write: Byte-identical output (266 bytes)
- ✅ Round-trip: JSON → Troybin → JSON preserves all data

## Technical Details

Based on LeagueToolkit's Inibin v2 structure:
- Version byte: `0x02`
- String table at end of file
- Little-endian byte order
- Property hash-based indexing

Hash dictionary implementation based on TroybinEditor's IniHashDictionary.
