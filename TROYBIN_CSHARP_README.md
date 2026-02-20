# Troybin Parser for C#

A complete C# implementation for reading and writing League of Legends `.troybin` particle effect files with full unhashing support.

## Features

- ✅ **Read & Write** - Parse and create troybin files
- ✅ **Unhashing** - Automatic property name resolution
- ✅ **Type-Safe** - Strongly typed C# implementation
- ✅ **LINQ Support** - Easy querying and manipulation
- ✅ **Multi-Emitter** - Full support for complex particle systems
- ✅ **Byte-Perfect** - Produces identical output to original files

## Installation

Add the following files to your project:
- `TroybinParser.cs`
- `IniHashDictionary.cs`

Namespace: `LeagueToolkit.IO.TroybinFiles`

## Quick Start

### Read a Troybin File

```csharp
using LeagueToolkit.IO.TroybinFiles;

// Read file
var data = TroybinParser.Read("particle.troybin");

// Resolve property names
TroybinParser.ResolveNames(data);

// Print to console
TroybinParser.Print(data);
```

### Create a New Troybin File

```csharp
var data = new TroybinParser.TroybinData
{
    Version = 2,
    Sets = new()
};

string emitterName = "glow";

// Define emitter in System section
data.Sets["StringList"] = new()
{
    new TroybinParser.PropertyEntry
    {
        Hash = IniHashDictionary.SectionFieldHash("System", "GroupPart0"),
        Value = emitterName
    },
    new TroybinParser.PropertyEntry
    {
        Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-mesh"),
        Value = "particle.scb"
    }
};

// Add properties
data.Sets["Int8List"] = new()
{
    new TroybinParser.PropertyEntry
    {
        Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-life"),
        Value = 2
    }
};

data.Sets["Float32ListVec3"] = new()
{
    new TroybinParser.PropertyEntry
    {
        Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-scale"),
        Value = new[] { 10.0f, 10.0f, 10.0f }
    }
};

// Save
TroybinParser.Write("my_particle.troybin", data);
```

### Modify an Existing File

```csharp
// Read
var data = TroybinParser.Read("particle.troybin");

// Get emitter name
string emitter = data.EmitterNames.FirstOrDefault() ?? "GroupPart0";

// Get and modify properties using convenience methods
var scale = TroybinParser.GetProperty<float[]>(data, emitter, "p-scale");
var newScale = scale.Select(x => x * 2.0f).ToArray();
TroybinParser.SetProperty(data, emitter, "p-scale", newScale, "Float32ListVec3");

// Save
TroybinParser.Write("particle_modified.troybin", data);
```

## API Reference

### TroybinParser Class

#### Static Methods

**Read(string filePath) : TroybinData**
- Reads and parses a troybin file from disk

**Read(byte[] data) : TroybinData**
- Parses a troybin file from byte array

**Write(string filePath, TroybinData data)**
- Writes a troybin file to disk

**Write(TroybinData data) : byte[]**
- Serializes a troybin file to byte array

**ResolveNames(TroybinData data)**
- Resolves all property hashes to human-readable names

**Print(TroybinData data, bool resolveNames = true)**
- Prints troybin contents to console

**GetProperty&lt;T&gt;(TroybinData data, string emitter, string field, T defaultValue = default) : T**
- Gets a property value by emitter and field name

**SetProperty&lt;T&gt;(TroybinData data, string emitter, string field, T value, string setType)**
- Sets a property value by emitter and field name

### TroybinData Class

**Properties:**
- `byte Version` - File format version (always 2)
- `ushort Flags` - Property type flags
- `ushort StringDataLength` - Length of string table
- `Dictionary<string, List<PropertyEntry>> Sets` - Property collections by type
- `List<string> EmitterNames` - Detected emitter names

### PropertyEntry Class

**Properties:**
- `uint Hash` - Property hash value
- `object Value` - Property value (type varies)
- `string ResolvedName` - Human-readable property name (after ResolveNames())

### IniHashDictionary Class

#### Static Methods

**SectionFieldHash(string section, string field) : uint**
- Calculates hash for a section+field combination
- Example: `SectionFieldHash("crown", "p-scale")`

**BuildHashMap(IEnumerable&lt;string&gt; groupNames = null) : Dictionary&lt;uint, string&gt;**
- Builds complete hash→name lookup table

**Resolve(uint hash, IEnumerable&lt;string&gt; groupNames = null) : (string section, string field)**
- Resolves a hash to section and field names

**ParseLabel(string label) : (string section, string field)**
- Parses a "[section] field" label into components

## Property Types

All 13 Inibin v2 property types are supported:

| Type | C# Type | Description |
|------|---------|-------------|
| `Int32List` | `int` | 32-bit integers |
| `Float32List` | `float` | 32-bit floats |
| `FixedPointFloatList` | `float` | Fixed-point floats (0.1 precision) |
| `Int16List` | `short` | 16-bit integers |
| `Int8List` | `byte` | 8-bit integers |
| `BitList` | `bool` | Boolean flags |
| `FixedPointFloatListVec3` | `int[]` | 3D vector (fixed-point) |
| `Float32ListVec3` | `float[]` | 3D vector |
| `FixedPointFloatListVec2` | `int[]` | 2D vector (fixed-point) |
| `Float32ListVec2` | `float[]` | 2D vector |
| `FixedPointFloatListVec4` | `int[]` | 4D vector (fixed-point) |
| `Float32ListVec4` | `float[]` | 4D vector |
| `StringList` | `string` | Null-terminated strings |

## Common Particle Properties

### System Section
- `GroupPart0..49` - Emitter names
- `GroupPart0Type..49Type` - Emitter types
- `MaterialOverride0..4*` - Material settings

### Emitter Properties
- `e-life` - Emitter lifetime (-1 = infinite)
- `e-rate` - Emission rate
- `e-rgba` - Emitter color (Vec4)
- `p-life` - Particle lifetime
- `p-type` - Particle type
- `p-scale` - Particle scale (Vec3)
- `p-offset` - Particle offset (Vec3)
- `p-mesh` - Mesh file (.scb)
- `p-meshtex` - Texture file (.dds)
- `rendermode` - Render mode

## Examples

See `TroybinExamples.cs` for complete examples including:
1. Reading and displaying troybin files
2. Creating new particle effects
3. Modifying existing files
4. Multi-emitter particles
5. Batch processing
6. JSON export
7. Finding texture usage

## Hash Algorithm

The SDBM hash algorithm is used (case-insensitive):

```csharp
// Hash formula: [section] field
section_hash = IHash(section.ToLower())
star_hash = IHash("*", section_hash)
final_hash = IHash(field.ToLower(), star_hash)
```

## Requirements

- .NET 5.0 or higher (for top-level init support)
- OR .NET Framework 4.7.2+ with C# 9.0 language features

For older .NET Framework versions, replace:
- `new()` with explicit types: `new Dictionary<string, List<PropertyEntry>>()`
- Target records may need conversion to classes

## Testing

Tested with multiple real League of Legends particle files:
- ✅ `chaos_inhibit_base_glow.troybin` - 22 properties
- ✅ `dragon_smoke.troybin` - 50 properties
- ✅ `sru_bluebuff_idle.troybin` - 71 properties, 4 emitters

All tests produce byte-identical output.

## License

Based on LeagueToolkit's Inibin parser and TroybinEditor's hash dictionary.

## Credits

- Hash dictionary implementation based on TroybinEditor by Leischii
- Inibin structure from LeagueToolkit
- Property name mappings from League particle system documentation
