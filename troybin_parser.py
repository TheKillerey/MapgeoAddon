"""
Troybin Parser - Read and Write League of Legends .troybin files
Based on Inibin v2 structure (same as .cfgbin files)
"""

import argparse
import struct
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Union


INIBIN_FLAGS = [
    ("Int32List", 1 << 0),
    ("Float32List", 1 << 1),
    ("FixedPointFloatList", 1 << 2),
    ("Int16List", 1 << 3),
    ("Int8List", 1 << 4),
    ("BitList", 1 << 5),
    ("FixedPointFloatListVec3", 1 << 6),
    ("Float32ListVec3", 1 << 7),
    ("FixedPointFloatListVec2", 1 << 8),
    ("Float32ListVec2", 1 << 9),
    ("FixedPointFloatListVec4", 1 << 10),
    ("Float32ListVec4", 1 << 11),
    ("StringList", 1 << 12),
]


class Reader:
    """Binary reader with little-endian support"""
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read_u8(self) -> int:
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_u16(self) -> int:
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_u32(self) -> int:
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_i16(self) -> int:
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_i32(self) -> int:
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_f32(self) -> float:
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value


class Writer:
    """Binary writer with little-endian support"""
    def __init__(self):
        self.data = bytearray()

    def write_u8(self, value: int):
        self.data.append(value & 0xFF)

    def write_u16(self, value: int):
        self.data.extend(struct.pack("<H", value))

    def write_u32(self, value: int):
        self.data.extend(struct.pack("<I", value))

    def write_i16(self, value: int):
        self.data.extend(struct.pack("<h", value))

    def write_i32(self, value: int):
        self.data.extend(struct.pack("<i", value))

    def write_f32(self, value: float):
        self.data.extend(struct.pack("<f", value))

    def get_bytes(self) -> bytes:
        return bytes(self.data)


def read_cstr(data: bytes, offset: int) -> str:
    """Read null-terminated string from data"""
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("ascii", errors="replace")


def read_set(reader: Reader, set_name: str, string_base: int) -> List[Tuple[int, Any]]:
    """Read a property set from the troybin file"""
    count = reader.read_u16()
    hashes = [reader.read_u32() for _ in range(count)]
    values = []

    if set_name == "BitList":
        for index in range(count):
            if (index % 8) == 0:
                packed = reader.read_u8()
            else:
                packed >>= 1
            values.append(bool(packed & 0x1))
    elif set_name == "Int32List":
        values = [reader.read_i32() for _ in range(count)]
    elif set_name == "Float32List":
        values = [reader.read_f32() for _ in range(count)]
    elif set_name == "FixedPointFloatList":
        values = [reader.read_u8() * 0.1 for _ in range(count)]
    elif set_name == "Int16List":
        values = [reader.read_i16() for _ in range(count)]
    elif set_name == "Int8List":
        values = [reader.read_u8() for _ in range(count)]
    elif set_name == "FixedPointFloatListVec3":
        values = [[reader.read_u8(), reader.read_u8(), reader.read_u8()] for _ in range(count)]
    elif set_name == "Float32ListVec3":
        values = [[reader.read_f32(), reader.read_f32(), reader.read_f32()] for _ in range(count)]
    elif set_name == "FixedPointFloatListVec2":
        values = [[reader.read_u8(), reader.read_u8()] for _ in range(count)]
    elif set_name == "Float32ListVec2":
        values = [[reader.read_f32(), reader.read_f32()] for _ in range(count)]
    elif set_name == "FixedPointFloatListVec4":
        values = [[reader.read_u8(), reader.read_u8(), reader.read_u8(), reader.read_u8()] for _ in range(count)]
    elif set_name == "Float32ListVec4":
        values = [[reader.read_f32(), reader.read_f32(), reader.read_f32(), reader.read_f32()] for _ in range(count)]
    elif set_name == "StringList":
        offsets = [reader.read_u16() for _ in range(count)]
        values = [read_cstr(reader.data, string_base + offset) for offset in offsets]
    else:
        raise ValueError(f"Unsupported set type: {set_name}")

    return list(zip(hashes, values))


def write_set(writer: Writer, set_name: str, entries: List[Tuple[int, Any]], string_offsets: Dict[str, int] = None) -> None:
    """Write a property set to the troybin file"""
    count = len(entries)
    writer.write_u16(count)
    
    # Write hashes
    for hash_value, _ in entries:
        writer.write_u32(hash_value)
    
    # Write values
    if set_name == "BitList":
        packed = 0
        bit_pos = 0
        for _, value in entries:
            if value:
                packed |= (1 << bit_pos)
            bit_pos += 1
            if bit_pos == 8:
                writer.write_u8(packed)
                packed = 0
                bit_pos = 0
        if bit_pos > 0:
            writer.write_u8(packed)
    elif set_name == "Int32List":
        for _, value in entries:
            writer.write_i32(int(value))
    elif set_name == "Float32List":
        for _, value in entries:
            writer.write_f32(float(value))
    elif set_name == "FixedPointFloatList":
        for _, value in entries:
            writer.write_u8(int(value / 0.1))
    elif set_name == "Int16List":
        for _, value in entries:
            writer.write_i16(int(value))
    elif set_name == "Int8List":
        for _, value in entries:
            writer.write_u8(int(value))
    elif set_name == "FixedPointFloatListVec3":
        for _, vec in entries:
            for component in vec:
                writer.write_u8(int(component))
    elif set_name == "Float32ListVec3":
        for _, vec in entries:
            for component in vec:
                writer.write_f32(float(component))
    elif set_name == "FixedPointFloatListVec2":
        for _, vec in entries:
            for component in vec:
                writer.write_u8(int(component))
    elif set_name == "Float32ListVec2":
        for _, vec in entries:
            for component in vec:
                writer.write_f32(float(component))
    elif set_name == "FixedPointFloatListVec4":
        for _, vec in entries:
            for component in vec:
                writer.write_u8(int(component))
    elif set_name == "Float32ListVec4":
        for _, vec in entries:
            for component in vec:
                writer.write_f32(float(component))
    elif set_name == "StringList":
        for _, string in entries:
            offset = string_offsets.get(string, 0)
            writer.write_u16(offset)
    else:
        raise ValueError(f"Unsupported set type: {set_name}")


def parse_troybin(path: Path) -> Dict[str, Any]:
    """Read and parse a troybin file"""
    data = path.read_bytes()
    reader = Reader(data)

    version = reader.read_u8()
    if version != 2:
        raise ValueError(f"Unsupported Inibin version: {version}. This tool currently supports version 2.")

    string_data_length = reader.read_u16()
    flags = reader.read_u16()
    string_base = len(data) - string_data_length

    parsed_sets = {}
    for set_name, set_flag in INIBIN_FLAGS:
        if flags & set_flag:
            parsed_sets[set_name] = read_set(reader, set_name, string_base)

    return {
        "version": version,
        "flags": flags,
        "string_data_length": string_data_length,
        "sets": parsed_sets,
    }


def write_troybin(path: Path, data: Dict[str, Any]) -> None:
    """Write a troybin file from parsed data"""
    writer = Writer()
    
    # Version
    version = data.get("version", 2)
    writer.write_u8(version)
    
    # Calculate flags
    flags = 0
    for set_name, set_flag in INIBIN_FLAGS:
        if set_name in data.get("sets", {}) and len(data["sets"][set_name]) > 0:
            flags |= set_flag
    
    # Collect all strings and build string table
    string_table = bytearray()
    string_offsets = {}
    
    if "StringList" in data.get("sets", {}):
        # Preserve order of first appearance
        seen_strings = []
        for _, string in data["sets"]["StringList"]:
            if string not in string_offsets:
                seen_strings.append(string)
        
        for string in seen_strings:
            string_offsets[string] = len(string_table)
            string_table.extend(string.encode("ascii", errors="replace"))
            string_table.append(0)  # Null terminator
    
    string_data_length = len(string_table)
    
    # Write header
    writer.write_u16(string_data_length)
    writer.write_u16(flags)
    
    # Write all sets
    for set_name, set_flag in INIBIN_FLAGS:
        if flags & set_flag:
            entries = data["sets"].get(set_name, [])
            write_set(writer, set_name, entries, string_offsets)
    
    # Append string table
    writer.data.extend(string_table)
    
    # Write to file
    path.write_bytes(writer.get_bytes())


def troybin_to_dict(troybin_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert troybin data to a JSON-serializable dictionary"""
    # Build hash map for unhashing
    group_names = extract_group_names(troybin_data)
    hash_map = build_hash_map(group_names)
    
    result = {
        "version": troybin_data["version"],
        "emitters": group_names,
        "properties": {}
    }
    
    for set_name, entries in troybin_data["sets"].items():
        for hash_value, value in entries:
            key = f"0x{hash_value:08X}"
            label = resolve_hash(hash_value, hash_map)
            
            prop_data = {
                "hash": hash_value,
                "type": set_name,
                "value": value
            }
            
            if label:
                section, field = parse_label(label)
                prop_data["section"] = section
                prop_data["field"] = field
                prop_data["name"] = label
            
            result["properties"][key] = prop_data
    
    return result


def dict_to_troybin(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a JSON dictionary back to troybin data structure"""
    sets = {}
    
    for key, prop in json_data.get("properties", {}).items():
        set_name = prop["type"]
        hash_value = prop["hash"]
        value = prop["value"]
        
        if set_name not in sets:
            sets[set_name] = []
        
        sets[set_name].append((hash_value, value))
    
    return {
        "version": json_data.get("version", 2),
        "sets": sets
    }


def sdbm_hash(value: str) -> int:
    """Calculate SDBM hash for a string (i_hash)"""
    hash_value = 0
    for char in value.lower():
        hash_value = (ord(char) + (65599 * hash_value)) & 0xFFFFFFFF
    return hash_value


def section_field_hash(section: str, field: str) -> int:
    """Calculate section+field hash (Troybin format)"""
    sh = sdbm_hash("*" + section.lower())
    return sdbm_hash(field.lower() + str(sh)) if isinstance(sh, int) else 0


def section_field_hash_proper(section: str, field: str) -> int:
    """Calculate section+field hash using proper Troybin algorithm"""
    # First hash the section
    section_hash = sdbm_hash(section.lower())
    # Then hash "*" with that as seed
    star_hash = 0
    for char in "*":
        star_hash = (ord(char) + (65599 * section_hash)) & 0xFFFFFFFF
    # Finally hash the field with star_hash as seed
    field_hash = star_hash
    for char in field.lower():
        field_hash = (ord(char) + (65599 * field_hash)) & 0xFFFFFFFF
    return field_hash


def section_field_hash_comment(section: str, field: str) -> int:
    """Calculate section+field hash for commented field"""
    section_hash = sdbm_hash(section.lower())
    star_hash = 0
    for char in "*":
        star_hash = (ord(char) + (65599 * section_hash)) & 0xFFFFFFFF
    field_hash = star_hash
    for char in ("'" + field.lower()):
        field_hash = (ord(char) + (65599 * field_hash)) & 0xFFFFFFFF
    return field_hash


# ── Hash Dictionary Builder (for unhashing Troybin properties) ─────────────

FIELD_VARS = 10
GPART_VARS = 50
MAT_VARS = 5
RAND_VARS = 10
COLOR_VARS = 25
ROT_VARS = 10


def get_system_field_names():
    """Get all System section field names"""
    fields = []
    
    # GroupPartN, GroupPartNType, GroupPartNImportance
    for i in range(GPART_VARS):
        fields.extend([
            f"GroupPart{i}",
            f"GroupPart{i}Type",
            f"GroupPart{i}Importance",
            f"Override-Offset{i}",
            f"Override-Rotation{i}",
            f"Override-Scale{i}",
        ])
    
    fields.extend([
        "AudioFlexValueParameterName",
        "AudioParameterFlexID",
        "build-up-time",
        "group-vis",
        "group-scale-cap",
        "KeepOrientationAfterSpellCast",
        "PersistThruDeath",
        "PersistThruRevive",
        "SelfIllumination",
        "SimulateEveryFrame",
        "SimulateOncePerFrame",
        "SimulateWhileOffScreen",
        "SoundEndsOnEmitterEnd",
        "SoundOnCreate",
        "SoundPersistent",
        "SoundsPlayWhileOffScreen",
        "VoiceOverOnCreate",
        "VoiceOverPersistent",
    ])
    
    for i in range(MAT_VARS):
        fields.extend([
            f"MaterialOverride{i}BlendMode",
            f"MaterialOverride{i}Texture",
            f"MaterialOverride{i}SubMesh",
        ])
    
    return fields


def rand_float(bases):
    """Expand rand float field names"""
    fields = []
    for b in bases:
        fields.append(b)
        for j in range(RAND_VARS):
            fields.append(f"{b}{j}")
        fields.append(f"{b}XP")
        for j in range(RAND_VARS):
            fields.append(f"{b}XP{j}")
        fields.append(f"{b}P")
        for j in range(RAND_VARS):
            fields.append(f"{b}P{j}")
    return fields


def rand_vec2(bases):
    """Expand rand vec2 field names"""
    fields = []
    for b in bases:
        fields.append(b)
        for j in range(RAND_VARS):
            fields.append(f"{b}{j}")
        for ax in ["X", "Y"]:
            fields.append(f"{b}{ax}P")
            for j in range(RAND_VARS):
                fields.append(f"{b}{ax}P{j}")
    return fields


def rand_vec3(bases):
    """Expand rand vec3 field names"""
    fields = []
    for b in bases:
        fields.append(b)
        for j in range(RAND_VARS):
            fields.append(f"{b}{j}")
        for ax in ["X", "Y", "Z"]:
            fields.append(f"{b}{ax}P")
            for j in range(RAND_VARS):
                fields.append(f"{b}{ax}P{j}")
    return fields


def flex(bases):
    """Expand flex field names"""
    fields = []
    for b in bases:
        fields.append(b)
        fields.append(f"{b}_flex")
        for j in range(4):
            fields.append(f"{b}_flex{j}")
    return fields


def flex_rand_float(bases):
    return rand_float(flex(bases))


def flex_rand_vec2(bases):
    return rand_vec2(flex(bases))


def flex_rand_vec3(bases):
    return rand_vec3(flex(bases))


def get_group_field_names():
    """Get all group/emitter field names"""
    fields = []
    
    # Base group names
    group_names = [
        "ExcludeAttachmentType", "KeywordsExcluded", "KeywordsIncluded", "KeywordsRequired",
        "Particle-ScaleAlongMovementVector", "SoundOnCreate", "SoundPersistent",
        "VoiceOverOnCreate", "VoiceOverPersistent", "dont-scroll-alpha-UV",
        "e-active", "e-alpharef", "e-beam-segments", "e-censor-policy", "e-disabled",
        "e-life", "e-life-scale", "e-linger", "e-local-orient", "e-period",
        "e-shape-name", "e-shape-scale", "e-shape-use-normal-for-birth",
        "e-soft-in-depth", "e-soft-out-depth", "e-soft-in-depth-delta", "e-soft-out-depth-delta",
        "e-timeoffset", "e-trail-cutoff", "e-trail-smoothing", "e-uvscroll", "e-uvscroll-mult",
        "flag-brighter-in-fow", "flag-disable-z", "flag-disable-y", "flag-groundlayer",
        "flag-ground-layer", "flag-force-animated-mesh-z-write", "flag-projected",
        "p-alphaslicerange", "p-animation", "p-backfaceon", "p-beammode", "p-bindtoemitter",
        "p-coloroffset", "p-colorscale", "p-colortype", "p-distortion-mode", "p-distortion-power",
        "p-falloff-texture", "p-fixedorbit", "p-fixedorbittype", "p-flexoffset", "p-flexscale",
        "p-followterrain", "p-frameRate", "p-frameRate-mult", "p-fresnel", "p-life-scale",
        "p-life-scale-offset", "p-life-scale-symX", "p-life-scale-symY", "p-life-scale-symZ",
        "p-linger", "p-local-orient", "p-lockedtoemitter", "p-mesh", "p-meshtex",
        "p-meshtex-mult", "p-normal-map", "p-numframes", "p-numframes-mult",
        "p-offsetbyheight", "p-offsetbyradius", "p-orientation", "p-projection-fading",
        "p-projection-y-range", "p-randomstartframe", "p-randomstartframe-mult",
        "p-reflection-fresnel", "p-reflection-map", "p-reflection-opacity-direct",
        "p-reflection-opacity-glancing", "p-rgba", "p-scalebias", "p-scalebyheight",
        "p-scalebyradius", "p-scaleupfromorigin", "p-shadow", "p-simpleorient",
        "p-skeleton", "p-skin", "p-startframe", "p-startframe-mult", "p-texdiv",
        "p-texdiv-mult", "p-texture", "p-texture-mode", "p-texture-mult",
        "p-texture-mult-mode", "p-texture-pixelate", "p-trailmode", "p-type", "p-uvmode",
        "p-uvparallax-scale", "p-uvscroll-alpha-mult", "p-uvscroll-no-alpha", "p-uvscroll-rgb",
        "p-uvscroll-rgb-clamp", "p-uvscroll-rgb-clamp-mult", "p-vec-velocity-minscale",
        "p-vec-velocity-scale", "p-vecalign", "p-xquadrot-on", "pass", "rendermode",
        "single-particle", "submesh-list", "teamcolor-correction", "uniformscale",
        "ChildParticleName", "ChildSpawnAtBone", "ChildEmitOnDeath", "p-childProb",
    ]
    fields.extend(group_names)
    
    # ChildParticleNameN etc.
    for i in range(GPART_VARS):
        fields.extend([
            f"ChildParticleName{i}",
            f"ChildSpawnAtBone{i}",
            f"ChildEmitOnDeath{i}",
        ])
    
    # MaterialOverrideN*
    for i in range(MAT_VARS):
        fields.extend([
            f"MaterialOverride{i}BlendMode",
            f"MaterialOverride{i}GlossTexture",
            f"MaterialOverride{i}EmissiveTexture",
            f"MaterialOverride{i}FixedAlphaScrolling",
            f"MaterialOverride{i}Priority",
            f"MaterialOverride{i}RenderingMode",
            f"MaterialOverride{i}SubMesh",
            f"MaterialOverride{i}Texture",
            f"MaterialOverride{i}UVScroll",
        ])
    
    # e-rgba / p-rgba / p-xrgba color variants
    for b in ["e-rgba", "p-rgba", "p-xrgba"]:
        fields.append(b)
        for i in range(COLOR_VARS):
            fields.append(f"{b}{i}")
        for mod in ["R", "G", "B", "A"]:
            fields.append(f"{b}{mod}P")
            for i in range(COLOR_VARS):
                fields.append(f"{b}{mod}P{i}")
    
    # flexFloat: p-scale, p-scaleEmitOffset
    for b in ["p-scale", "p-scaleEmitOffset"]:
        fields.append(b)
        fields.append(f"{b}_flex")
        for j in range(4):
            fields.append(f"{b}_flex{j}")
    
    # flexRandFloat: e-rate, p-life, p-rotvel
    fields.extend(flex_rand_float(["e-rate", "p-life", "p-rotvel"]))
    
    # flexRandVec2: e-uvoffset
    fields.extend(flex_rand_vec2(["e-uvoffset"]))
    
    # flexRandVec3: p-offset, p-postoffset, p-vel
    fields.extend(flex_rand_vec3(["p-offset", "p-postoffset", "p-vel"]))
    
    # randFloat: many fields
    fields.extend(rand_float([
        "e-color-modulate", "e-framerate", "p-bindtoemitter", "p-life", "p-quadrot",
        "p-rotvel", "p-scale", "p-xquadrot", "p-xscale", "e-rate"
    ]))
    
    # randVec2
    fields.extend(rand_vec2([
        "e-ratebyvel", "e-uvoffset", "e-uvoffset-mult", "p-uvscroll-rgb", "p-uvscroll-rgb-mult"
    ]))
    
    # randVec3: many fields
    fields.extend(rand_vec3([
        "Emitter-BirthRotationalAcceleration", "Particle-Acceleration", "Particle-Drag",
        "Particle-Velocity", "e-tilesize", "p-accel", "p-drag", "p-offset", "p-orbitvel",
        "p-postoffset", "p-quadrot", "p-rotvel", "p-scale", "p-vel", "p-worldaccel",
        "p-xquadrot", "p-xrgba-beam-bind-distance", "p-xscale"
    ]))
    
    # e-rotationN rand + axis
    for i in range(ROT_VARS):
        fields.extend(rand_float([f"e-rotation{i}"]))
        fields.append(f"e-rotation{i}-axis")
    
    # field-accel-N .. field-orbit-N
    for i in range(1, FIELD_VARS):
        fields.extend([
            f"field-accel-{i}",
            f"field-attract-{i}",
            f"field-drag-{i}",
            f"field-noise-{i}",
            f"field-orbit-{i}",
        ])
    
    fields.append("fluid-params")
    
    return fields


def build_hash_map(group_names: List[str] = None) -> Dict[int, str]:
    """
    Build a hash→"[section] field" map for a Troybin file.
    group_names = actual emitter names from System[GroupPart0..N] values
    """
    hash_map = {}
    
    def add_fields(section: str, field_names: List[str]):
        for field in field_names:
            h1 = section_field_hash_proper(section, field)
            h2 = section_field_hash_comment(section, field)
            label = f"[{section}] {field}"
            if h1 not in hash_map:
                hash_map[h1] = label
            if h2 not in hash_map:
                hash_map[h2] = label
    
    # Always add System section
    add_fields("System", get_system_field_names())
    
    # GroupPartN section keys (fallback)
    gp_fields = get_group_field_names()
    for i in range(GPART_VARS):
        add_fields(f"GroupPart{i}", gp_fields)
    
    # If we have actual group names, build hashes using those as sections
    if group_names:
        for gn in group_names:
            if gn and gn.strip():
                add_fields(gn, gp_fields)
    
    return hash_map


def extract_group_names(troybin_data: Dict[str, Any]) -> List[str]:
    """Extract emitter names from System GroupPartN fields"""
    group_names = []
    
    if "StringList" in troybin_data.get("sets", {}):
        for hash_value, value in troybin_data["sets"]["StringList"]:
            # Check if this is a GroupPartN field
            for i in range(GPART_VARS):
                expected_hash = section_field_hash_proper("System", f"GroupPart{i}")
                if hash_value == expected_hash:
                    group_names.append(value)
                    break
    
    return group_names


def resolve_hash(hash_value: int, hash_map: Dict[int, str]) -> Union[str, None]:
    """Resolve a hash to its field name"""
    return hash_map.get(hash_value)


def parse_label(label: str) -> Tuple[str, str]:
    """Parse a label string '[section] field' into its two parts"""
    start = label.find('[')
    end = label.find(']')
    if start >= 0 and end > start:
        section = label[start + 1:end]
        field = label[end + 2:] if end + 2 < len(label) else ""
        return (section, field)
    return ("Unknown", label)


def main():
    parser = argparse.ArgumentParser(description="Read and write League of Legends .troybin files")
    parser.add_argument("file", help="Path to .troybin file")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--to-json", metavar="OUTPUT", help="Convert troybin to JSON file")
    group.add_argument("--from-json", metavar="INPUT", help="Convert JSON file to troybin")
    group.add_argument("--dump", action="store_true", help="Dump troybin contents to console (default)")
    
    parser.add_argument("--max-per-set", type=int, default=0, help="Limit rows per set when dumping (0 = all)")
    
    args = parser.parse_args()
    
    troybin_path = Path(args.file)
    
    # Convert from JSON
    if args.from_json:
        json_path = Path(args.from_json)
        print(f"Converting {json_path} to {troybin_path}...")
        
        with open(json_path, 'r') as f:
            json_data = json.load(f)
        
        troybin_data = dict_to_troybin(json_data)
        write_troybin(troybin_path, troybin_data)
        print(f"✓ Troybin file written successfully")
        return
    
    # Read troybin
    if not troybin_path.exists():
        print(f"Error: File not found: {troybin_path}")
        return
    
    print(f"Reading {troybin_path}...")
    troybin_data = parse_troybin(troybin_path)
    
    # Convert to JSON
    if args.to_json:
        output_path = Path(args.to_json)
        print(f"Converting to {output_path}...")
        
        json_data = troybin_to_dict(troybin_data)
        
        with open(output_path, 'w') as f:
            json.dump(json_data, f, indent=2)
        
        print(f"✓ JSON file written successfully")
        return
    
    # Dump to console (default)
    # Build hash map for unhashing
    group_names = extract_group_names(troybin_data)
    hash_map = build_hash_map(group_names)
    
    print(f"\n{'='*60}")
    print(f"File: {troybin_path.name}")
    print(f"Version: {troybin_data['version']}")
    print(f"Flags: 0x{troybin_data['flags']:04X}")
    print(f"String Data Length: {troybin_data['string_data_length']}")
    
    total_properties = sum(len(entries) for entries in troybin_data["sets"].values())
    resolved_count = sum(1 for entries in troybin_data["sets"].values() 
                        for hash_value, _ in entries if hash_value in hash_map)
    print(f"Total Properties: {total_properties}")
    print(f"Resolved: {resolved_count}/{total_properties}")
    if group_names:
        print(f"Emitters: {', '.join(group_names)}")
    print(f"{'='*60}\n")
    
    for set_name, entries in troybin_data["sets"].items():
        print(f"[{set_name}] count={len(entries)}")
        limit = args.max_per_set if args.max_per_set > 0 else len(entries)
        
        for hash_value, value in entries[:limit]:
            label = resolve_hash(hash_value, hash_map)
            if label:
                print(f"  0x{hash_value:08X} {label} = {value}")
            else:
                print(f"  0x{hash_value:08X} = {value}")
        
        if limit < len(entries):
            print(f"  ... ({len(entries) - limit} more)")
        print()


if __name__ == "__main__":
    main()
