"""
PropertyBin (.bin) Parser and Writer for League of Legends

Parses the modern PROP binary format used by League for materials.bin,
character configs, gameplay data, and more.

Supports PROP versions 1-3 and PTCH (patch) wrappers.
All 27 value types are handled including nested structs, containers,
maps, optionals, and embedded objects.
"""

import struct
from pathlib import Path
import re


# ============================================================================
# FNV-1a Hash
# ============================================================================

def fnv1a_32(s: str) -> int:
    """Compute FNV-1a 32-bit hash (lowercase input)."""
    s = s.lower()
    h = 0x811c9dc5
    for c in s:
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# ============================================================================
# Type Constants
# ============================================================================

TYPE_NONE       = 0
TYPE_BOOL       = 1
TYPE_S8         = 2
TYPE_U8         = 3
TYPE_S16        = 4
TYPE_U16        = 5
TYPE_S32        = 6
TYPE_U32        = 7
TYPE_S64        = 8
TYPE_U64        = 9
TYPE_F32        = 10
TYPE_VEC2       = 11
TYPE_VEC3       = 12
TYPE_VEC4       = 13
TYPE_MTX44      = 14
TYPE_RGBA       = 15
TYPE_STRING     = 16
TYPE_HASH       = 17
TYPE_FILE       = 18       # WAD entry link (XXHash64 u64)
TYPE_CONTAINER  = 0x80     # 128 — list/container of typed elements
TYPE_CONTAINER2 = 0x81     # 129 — unordered container (same binary layout)
TYPE_STRUCT     = 0x82     # 130 — struct (nullable)
TYPE_EMBEDDED   = 0x83     # 131 — embedded struct (non-nullable)
TYPE_LINK       = 0x84     # 132 — link/pointer to another entry
TYPE_OPTIONAL   = 0x85     # 133 — optional<T>
TYPE_MAP        = 0x86     # 134 — map<K, V>
TYPE_BITBOOL    = 0x87     # 135 — flag/bit boolean

TYPE_NAMES = {
    TYPE_NONE:       "none",
    TYPE_BOOL:       "bool",
    TYPE_S8:         "s8",
    TYPE_U8:         "u8",
    TYPE_S16:        "s16",
    TYPE_U16:        "u16",
    TYPE_S32:        "s32",
    TYPE_U32:        "u32",
    TYPE_S64:        "s64",
    TYPE_U64:        "u64",
    TYPE_F32:        "f32",
    TYPE_VEC2:       "vec2",
    TYPE_VEC3:       "vec3",
    TYPE_VEC4:       "vec4",
    TYPE_MTX44:      "mtx44",
    TYPE_RGBA:       "rgba",
    TYPE_STRING:     "string",
    TYPE_HASH:       "hash",
    TYPE_FILE:       "file",
    TYPE_CONTAINER:  "list",
    TYPE_CONTAINER2: "list2",
    TYPE_STRUCT:     "struct",
    TYPE_EMBEDDED:   "embedded",
    TYPE_LINK:       "link",
    TYPE_OPTIONAL:   "optional",
    TYPE_MAP:        "map",
    TYPE_BITBOOL:    "flag",
}

TYPE_NAME_TO_ID = {v: k for k, v in TYPE_NAMES.items()}

# StaticMaterialDef type hash used by old v2 map materials bins.
_TYPE_HASH_STATIC_MATERIAL_DEF = 0xFF9D3409


class _LegacyTypeRetry(Exception):
    """Internal signal to retry entry parsing with legacy type decoding enabled."""


def _unpack_type(type_id: int, use_legacy_type: bool = False) -> int:
    """Match LeagueToolkit legacy type remapping for old PROP2 bins."""
    if not use_legacy_type:
        return type_id

    # Old bins did not have TYPE_FILE (WadChunkLink) at primitive index 18.
    # Values 18..127 are shifted into complex/container range.
    if TYPE_FILE <= type_id < TYPE_CONTAINER:
        type_id = (type_id - TYPE_FILE) | TYPE_CONTAINER

    # Complex type ids after unordered container are shifted by +1 in legacy bins.
    if type_id >= TYPE_CONTAINER2:
        type_id += 1

    return type_id & 0xFF


# ============================================================================
# Binary Reader
# ============================================================================

class BinReader:
    """Low-level binary reader with position tracking."""

    __slots__ = ('data', 'pos', 'size')

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.size = len(data)

    def remaining(self) -> int:
        return self.size - self.pos

    def read_bytes(self, n: int) -> bytes:
        end = self.pos + n
        if end > self.size:
            raise ValueError(f"Read past end: pos={self.pos}, need={n}, size={self.size}")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def read_u8(self) -> int:
        return struct.unpack_from('<B', self.data, self._advance(1))[0]

    def read_s8(self) -> int:
        return struct.unpack_from('<b', self.data, self._advance(1))[0]

    def read_u16(self) -> int:
        return struct.unpack_from('<H', self.data, self._advance(2))[0]

    def read_s16(self) -> int:
        return struct.unpack_from('<h', self.data, self._advance(2))[0]

    def read_u32(self) -> int:
        return struct.unpack_from('<I', self.data, self._advance(4))[0]

    def read_s32(self) -> int:
        return struct.unpack_from('<i', self.data, self._advance(4))[0]

    def read_u64(self) -> int:
        return struct.unpack_from('<Q', self.data, self._advance(8))[0]

    def read_s64(self) -> int:
        return struct.unpack_from('<q', self.data, self._advance(8))[0]

    def read_f32(self) -> float:
        return struct.unpack_from('<f', self.data, self._advance(4))[0]

    def read_string(self) -> str:
        length = self.read_u16()
        raw = self.read_bytes(length)
        return raw.decode('utf-8', errors='replace')

    def _advance(self, n: int) -> int:
        pos = self.pos
        self.pos += n
        if self.pos > self.size:
            raise ValueError(f"Read past end: pos={pos}, need={n}, size={self.size}")
        return pos


# ============================================================================
# Binary Writer
# ============================================================================

class BinWriter:
    """Low-level binary writer."""

    __slots__ = ('parts',)

    def __init__(self):
        self.parts: list[bytes] = []

    def write_bytes(self, data: bytes):
        self.parts.append(data)

    def write_u8(self, v: int):
        self.parts.append(struct.pack('<B', v & 0xFF))

    def write_s8(self, v: int):
        self.parts.append(struct.pack('<b', v))

    def write_u16(self, v: int):
        self.parts.append(struct.pack('<H', v & 0xFFFF))

    def write_s16(self, v: int):
        self.parts.append(struct.pack('<h', v))

    def write_u32(self, v: int):
        self.parts.append(struct.pack('<I', v & 0xFFFFFFFF))

    def write_s32(self, v: int):
        self.parts.append(struct.pack('<i', v))

    def write_u64(self, v: int):
        self.parts.append(struct.pack('<Q', v & 0xFFFFFFFFFFFFFFFF))

    def write_s64(self, v: int):
        self.parts.append(struct.pack('<q', v))

    def write_f32(self, v: float):
        self.parts.append(struct.pack('<f', v))

    def write_string(self, s: str):
        encoded = s.encode('utf-8')
        self.write_u16(len(encoded))
        self.write_bytes(encoded)

    def get_bytes(self) -> bytes:
        return b''.join(self.parts)

    def get_size(self) -> int:
        return sum(len(p) for p in self.parts)


# ============================================================================
# Value Reader
# ============================================================================

def _read_value(reader: BinReader, type_id: int, use_legacy_type: bool = False):
    """Read a typed value from the stream. Returns a Python dict describing the value."""

    if type_id == TYPE_NONE:
        return {"type": type_id, "value": None}

    elif type_id == TYPE_BOOL:
        return {"type": type_id, "value": bool(reader.read_u8())}

    elif type_id == TYPE_S8:
        return {"type": type_id, "value": reader.read_s8()}

    elif type_id == TYPE_U8:
        return {"type": type_id, "value": reader.read_u8()}

    elif type_id == TYPE_S16:
        return {"type": type_id, "value": reader.read_s16()}

    elif type_id == TYPE_U16:
        return {"type": type_id, "value": reader.read_u16()}

    elif type_id == TYPE_S32:
        return {"type": type_id, "value": reader.read_s32()}

    elif type_id == TYPE_U32:
        return {"type": type_id, "value": reader.read_u32()}

    elif type_id == TYPE_S64:
        return {"type": type_id, "value": reader.read_s64()}

    elif type_id == TYPE_U64:
        return {"type": type_id, "value": reader.read_u64()}

    elif type_id == TYPE_F32:
        return {"type": type_id, "value": reader.read_f32()}

    elif type_id == TYPE_VEC2:
        return {"type": type_id, "value": [reader.read_f32() for _ in range(2)]}

    elif type_id == TYPE_VEC3:
        return {"type": type_id, "value": [reader.read_f32() for _ in range(3)]}

    elif type_id == TYPE_VEC4:
        return {"type": type_id, "value": [reader.read_f32() for _ in range(4)]}

    elif type_id == TYPE_MTX44:
        return {"type": type_id, "value": [reader.read_f32() for _ in range(16)]}

    elif type_id == TYPE_RGBA:
        r, g, b, a = reader.read_u8(), reader.read_u8(), reader.read_u8(), reader.read_u8()
        return {"type": type_id, "value": [r, g, b, a]}

    elif type_id == TYPE_STRING:
        return {"type": type_id, "value": reader.read_string()}

    elif type_id == TYPE_HASH:
        h = reader.read_u32()
        return {"type": type_id, "value": f"0x{h:08x}"}

    elif type_id == TYPE_FILE:
        h = reader.read_u64()
        return {"type": type_id, "value": f"0x{h:016x}"}

    elif type_id in (TYPE_CONTAINER, TYPE_CONTAINER2):
        return _read_container(reader, type_id, use_legacy_type)

    elif type_id == TYPE_STRUCT:
        return _read_struct(reader, nullable=True, use_legacy_type=use_legacy_type)

    elif type_id == TYPE_EMBEDDED:
        return _read_struct(reader, nullable=False, use_legacy_type=use_legacy_type)

    elif type_id == TYPE_LINK:
        h = reader.read_u32()
        return {"type": type_id, "value": f"0x{h:08x}"}

    elif type_id == TYPE_OPTIONAL:
        return _read_optional(reader, use_legacy_type)

    elif type_id == TYPE_MAP:
        return _read_map(reader, use_legacy_type)

    elif type_id == TYPE_BITBOOL:
        return {"type": type_id, "value": bool(reader.read_u8())}

    else:
        raise ValueError(f"Unknown type ID: {type_id} (0x{type_id:02x}) at pos {reader.pos}")


def _read_container(reader: BinReader, container_type: int, use_legacy_type: bool = False) -> dict:
    """Read a Container / List."""
    elem_type = _unpack_type(reader.read_u8(), use_legacy_type)
    data_size = reader.read_u32()
    count = reader.read_u32()

    elements = []
    for _ in range(count):
        elem = _read_value(reader, elem_type, use_legacy_type)
        elements.append(elem)

    return {
        "type": container_type,
        "value_type": elem_type,
        "values": elements,
    }


def _read_struct(reader: BinReader, nullable: bool, use_legacy_type: bool = False) -> dict:
    """Read a Struct or Embedded object."""
    class_hash = reader.read_u32()
    type_id = TYPE_STRUCT if nullable else TYPE_EMBEDDED

    if nullable and class_hash == 0:
        return {"type": type_id, "class_hash": "0x00000000", "fields": None}

    data_size = reader.read_u32()
    field_count = reader.read_u16()
    fields = []
    for _ in range(field_count):
        field = _read_field(reader, use_legacy_type)
        fields.append(field)

    return {
        "type": type_id,
        "class_hash": f"0x{class_hash:08x}",
        "fields": fields,
    }


def _read_optional(reader: BinReader, use_legacy_type: bool = False) -> dict:
    """Read an Optional<T>."""
    elem_type = _unpack_type(reader.read_u8(), use_legacy_type)
    has_value = reader.read_u8()

    if has_value:
        val = _read_value(reader, elem_type, use_legacy_type)
    else:
        val = None

    return {
        "type": TYPE_OPTIONAL,
        "value_type": elem_type,
        "value": val,
    }


def _read_map(reader: BinReader, use_legacy_type: bool = False) -> dict:
    """Read a Map<K, V>."""
    key_type = _unpack_type(reader.read_u8(), use_legacy_type)
    value_type = _unpack_type(reader.read_u8(), use_legacy_type)
    data_size = reader.read_u32()
    count = reader.read_u32()

    pairs = []
    for _ in range(count):
        k = _read_value(reader, key_type, use_legacy_type)
        v = _read_value(reader, value_type, use_legacy_type)
        pairs.append({"key": k, "value": v})

    return {
        "type": TYPE_MAP,
        "key_type": key_type,
        "value_type": value_type,
        "pairs": pairs,
    }


def _read_field(reader: BinReader, use_legacy_type: bool = False) -> dict:
    """Read a single field (name_hash + type + value)."""
    name_hash = reader.read_u32()
    type_id = _unpack_type(reader.read_u8(), use_legacy_type)

    value_data = _read_value(reader, type_id, use_legacy_type)

    return {
        "name_hash": f"0x{name_hash:08x}",
        "name_hash_int": name_hash,
        **value_data,
    }


# ============================================================================
# Value Writer
# ============================================================================

def _write_value(writer: BinWriter, node: dict):
    """Write a typed value to the stream."""
    type_id = node["type"]

    if type_id == TYPE_NONE:
        pass

    elif type_id == TYPE_BOOL:
        writer.write_u8(1 if node["value"] else 0)

    elif type_id == TYPE_S8:
        writer.write_s8(int(node["value"]))

    elif type_id == TYPE_U8:
        writer.write_u8(int(node["value"]))

    elif type_id == TYPE_S16:
        writer.write_s16(int(node["value"]))

    elif type_id == TYPE_U16:
        writer.write_u16(int(node["value"]))

    elif type_id == TYPE_S32:
        writer.write_s32(int(node["value"]))

    elif type_id == TYPE_U32:
        writer.write_u32(int(node["value"]))

    elif type_id == TYPE_S64:
        writer.write_s64(int(node["value"]))

    elif type_id == TYPE_U64:
        writer.write_u64(int(node["value"]))

    elif type_id == TYPE_F32:
        writer.write_f32(float(node["value"]))

    elif type_id == TYPE_VEC2:
        for v in node["value"][:2]:
            writer.write_f32(float(v))

    elif type_id == TYPE_VEC3:
        for v in node["value"][:3]:
            writer.write_f32(float(v))

    elif type_id == TYPE_VEC4:
        for v in node["value"][:4]:
            writer.write_f32(float(v))

    elif type_id == TYPE_MTX44:
        for v in node["value"][:16]:
            writer.write_f32(float(v))

    elif type_id == TYPE_RGBA:
        for v in node["value"][:4]:
            writer.write_u8(int(v) & 0xFF)

    elif type_id == TYPE_STRING:
        writer.write_string(str(node["value"]))

    elif type_id == TYPE_HASH:
        writer.write_u32(_parse_hex(node["value"]))

    elif type_id == TYPE_FILE:
        writer.write_u64(_parse_hex(node["value"]))

    elif type_id in (TYPE_CONTAINER, TYPE_CONTAINER2):
        _write_container(writer, node)

    elif type_id == TYPE_STRUCT:
        _write_struct(writer, node, nullable=True)

    elif type_id == TYPE_EMBEDDED:
        _write_struct(writer, node, nullable=False)

    elif type_id == TYPE_LINK:
        writer.write_u32(_parse_hex(node["value"]))

    elif type_id == TYPE_OPTIONAL:
        _write_optional(writer, node)

    elif type_id == TYPE_MAP:
        _write_map(writer, node)

    elif type_id == TYPE_BITBOOL:
        writer.write_u8(1 if node["value"] else 0)

    else:
        raise ValueError(f"Unknown type for writing: {type_id}")


def _write_container(writer: BinWriter, node: dict):
    """Write a Container/List."""
    elem_type = node["value_type"]
    elements = node.get("values", [])

    writer.write_u8(elem_type)

    # Compute data size (count + element data)
    inner = BinWriter()
    inner.write_u32(len(elements))
    for elem in elements:
        _write_value(inner, elem)
    inner_bytes = inner.get_bytes()

    writer.write_u32(len(inner_bytes))
    writer.write_bytes(inner_bytes)


def _write_struct(writer: BinWriter, node: dict, nullable: bool):
    """Write a Struct or Embedded."""
    class_hash = _parse_hex(node.get("class_hash", "0x00000000"))

    if nullable and node.get("fields") is None:
        writer.write_u32(0)
        return

    writer.write_u32(class_hash)

    # Build inner data
    inner = BinWriter()
    fields = node.get("fields", [])
    inner.write_u16(len(fields))
    for field in fields:
        _write_field(inner, field)
    inner_bytes = inner.get_bytes()

    writer.write_u32(len(inner_bytes))
    writer.write_bytes(inner_bytes)


def _write_optional(writer: BinWriter, node: dict):
    """Write an Optional<T>."""
    elem_type = node["value_type"]
    writer.write_u8(elem_type)
    has_value = node.get("value") is not None
    writer.write_u8(1 if has_value else 0)
    if has_value:
        _write_value(writer, node["value"])


def _write_map(writer: BinWriter, node: dict):
    """Write a Map<K, V>."""
    key_type = node["key_type"]
    value_type = node["value_type"]
    pairs = node.get("pairs", [])

    writer.write_u8(key_type)
    writer.write_u8(value_type)

    inner = BinWriter()
    inner.write_u32(len(pairs))
    for pair in pairs:
        _write_value(inner, pair["key"])
        _write_value(inner, pair["value"])
    inner_bytes = inner.get_bytes()

    writer.write_u32(len(inner_bytes))
    writer.write_bytes(inner_bytes)


def _write_field(writer: BinWriter, field: dict):
    """Write a single field (name_hash + type + value)."""
    name_hash = _parse_hex(field["name_hash"])
    type_id = field["type"]

    writer.write_u32(name_hash)
    writer.write_u8(type_id)
    _write_value(writer, field)


def _parse_hex(s) -> int:
    """Parse a hex string like '0x1234abcd' to int. Also accepts plain ints."""
    if isinstance(s, int):
        return s
    s = str(s).strip()
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    return int(s)


# ============================================================================
# Top-Level Parser
# ============================================================================

def parse_bin(filepath: str) -> dict:
    """
    Parse a PropertyBin (.bin) file.

    Returns a dict with:
        magic: str ("PROP" or "PTCH")
        version: int
        linked_files: list[str]
        entries: list[dict]  — each entry has path_hash, type_hash, fields
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    reader = BinReader(data)

    # Magic
    magic = reader.read_bytes(4)
    is_patch = False

    if magic == b'PTCH':
        is_patch = True
        _patch_unknown = reader.read_u32()  # typically 1
        magic = reader.read_bytes(4)

    if magic != b'PROP':
        raise ValueError(f"Invalid PropertyBin magic: {magic!r} (expected b'PROP')")

    version = reader.read_u32()

    # Linked files (version 2+)
    linked_files = []
    if version >= 2:
        linked_count = reader.read_u32()
        for _ in range(linked_count):
            linked_files.append(reader.read_string())

    # Entry count + type hashes
    entry_count = reader.read_u32()
    entry_types = [reader.read_u32() for _ in range(entry_count)]

    # Read entries
    entries_offset = reader.pos

    def _read_entries(use_legacy_type: bool) -> list[dict]:
        reader.pos = entries_offset
        parsed_entries = []
        for i in range(entry_count):
            try:
                entry = _read_entry(reader, entry_types[i], version, use_legacy_type=use_legacy_type)
                parsed_entries.append(entry)
            except _LegacyTypeRetry:
                # Trigger one full retry with LeagueToolkit-style legacy type decode.
                raise
            except Exception as e:
                print(f"[PropertyBin] Error reading entry {i}: {e}")
                parsed_entries.append({
                    "path_hash": f"0x{0:08x}",
                    "type_hash": f"0x{entry_types[i]:08x}",
                    "fields": [],
                    "_error": str(e),
                })
                # Continue; _read_entry consumes full entry chunk before parsing.
        return parsed_entries

    try:
        entries = _read_entries(use_legacy_type=False)
    except _LegacyTypeRetry:
        entries = _read_entries(use_legacy_type=True)

    # Version 3 patch sections (if any trailing data)
    patch_entries = []
    if is_patch and reader.remaining() > 0:
        try:
            patch_count = reader.read_u32()
            for _ in range(patch_count):
                path_hash = reader.read_u32()
                data_size = reader.read_u32()
                raw_patch = reader.read_bytes(data_size)
                patch_entries.append({
                    "path_hash": f"0x{path_hash:08x}",
                    "raw_data": raw_patch.hex(),
                })
        except Exception:
            pass  # Patch section is optional

    result = {
        "magic": "PTCH" if is_patch else "PROP",
        "version": version,
        "linked_files": linked_files,
        "entries": entries,
        "entry_count": len(entries),
    }

    if patch_entries:
        result["patch_entries"] = patch_entries

    return result


def _read_entry(reader: BinReader, type_hash: int, version: int, use_legacy_type: bool = False) -> dict:
    """Read a single entry from the stream.

    Parsing is done from an isolated entry chunk so parse errors don't
    desync the outer stream.
    """
    content_length = reader.read_u32()
    content = reader.read_bytes(content_length)

    entry_reader = BinReader(content)
    path_hash = entry_reader.read_u32()
    field_count = entry_reader.read_u16()

    fields = []
    preserve_raw = False
    try:
        for _ in range(field_count):
            fields.append(_read_field(entry_reader, use_legacy_type))
    except Exception:
        if not use_legacy_type:
            # Match LeagueToolkit behavior: retry whole object table using legacy type mapping.
            raise _LegacyTypeRetry()
        # Legacy v2 StaticMaterialDef payloads in some older map bins are not
        # encoded with the standard typed-field layout. Fall back to a minimal
        # parser so these files remain loadable.
        if type_hash == _TYPE_HASH_STATIC_MATERIAL_DEF:
            fields = _read_legacy_v2_static_material_fields(content)
            preserve_raw = True
        else:
            fields = _read_legacy_v2_entry_fields(content)
            preserve_raw = True

    result = {
        "path_hash": f"0x{path_hash:08x}",
        "type_hash": f"0x{type_hash:08x}",
        "fields": fields,
    }
    if preserve_raw:
        # Keep original payload bytes for lossless round-trip writing.
        result["_preserve_raw"] = True
        result["_raw_entry_data"] = content.hex()
    return result


def _extract_legacy_strings(data: bytes) -> list[str]:
    """Extract short UTF-8-ish strings prefixed by u16 length."""
    out = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        slen = int.from_bytes(data[i:i + 2], 'little')
        if 0 < slen <= 512 and i + 2 + slen <= n:
            raw = data[i + 2:i + 2 + slen]
            try:
                s = raw.decode('utf-8')
            except Exception:
                i += 1
                continue
            # Keep mostly-printable strings only.
            if s and sum(1 for ch in s if 32 <= ord(ch) < 127) >= max(1, int(len(s) * 0.8)):
                out.append(s)
        i += 1
    return out


def _read_legacy_v2_static_material_fields(content: bytes) -> list[dict]:
    """Best-effort decoder for legacy v2 StaticMaterialDef entries.

    It reconstructs essential fields (name, type, diffuse sampler) so old
    version-2 map materials bins can be loaded without hard failure.
    """
    r = BinReader(content)
    _path_hash = r.read_u32()
    field_count = r.read_u16()

    name = ""
    mat_type = 0

    # The first fields are usually still standard typed fields.
    for idx in range(min(field_count, 3)):
        pos = r.pos
        try:
            fld = _read_field(r)
        except Exception:
            r.pos = pos
            break
        if idx == 0 and fld.get('type') == TYPE_STRING:
            name = str(fld.get('value') or '')
        elif idx == 1 and fld.get('type') == TYPE_U32:
            mat_type = int(fld.get('value') or 0)

    # Extract texture-like strings from the remainder.
    strings = _extract_legacy_strings(content)
    texture_path = ""
    for s in strings:
        low = s.lower()
        if ('assets/' in low or 'maps/' in low) and (low.endswith('.dds') or low.endswith('.tex')):
            texture_path = s.replace('\\', '/')
            break

    # Normalize old .dds references to .tex naming when possible.
    if texture_path.lower().endswith('.dds'):
        texture_path = re.sub(r'(?i)\.dds$', '.tex', texture_path)
        texture_path = re.sub(r'(?i)\.srt[^./\\]*(?=\.[^./\\]+$)', '', texture_path)

    fields = [
        {
            'name_hash': '0x8d39bde6',
            'name_hash_int': 0x8D39BDE6,
            'type': TYPE_STRING,
            'value': name,
        },
        {
            'name_hash': '0x5127f14d',
            'name_hash_int': 0x5127F14D,
            'type': TYPE_U32,
            'value': mat_type,
        },
    ]

    if texture_path:
        fields.append({
            'name_hash': '0x0a6f0eb5',
            'name_hash_int': 0x0A6F0EB5,
            'type': TYPE_CONTAINER,
            'value_type': TYPE_EMBEDDED,
            'values': [
                {
                    'type': TYPE_EMBEDDED,
                    'class_hash': '0x663d7491',
                    'fields': [
                        {
                            'name_hash': '0xb311d4ef',
                            'name_hash_int': 0xB311D4EF,
                            'type': TYPE_STRING,
                            'value': 'DiffuseTexture',
                        },
                        {
                            'name_hash': '0xf0a363e3',
                            'name_hash_int': 0xF0A363E3,
                            'type': TYPE_STRING,
                            'value': texture_path,
                        },
                    ],
                }
            ],
        })

    return fields


def _read_legacy_v2_entry_fields(content: bytes) -> list[dict]:
    """Best-effort parser for malformed legacy v2 entry payloads.

    It decodes fields until the first structural mismatch and returns what was
    parsed so callers can still inspect the entry instead of dropping it.
    """
    r = BinReader(content)
    _path_hash = r.read_u32()
    field_count = r.read_u16()

    fields = []
    for _ in range(field_count):
        pos = r.pos
        try:
            fields.append(_read_field(r))
        except Exception:
            r.pos = pos
            break
    return fields


# ============================================================================
# Top-Level Writer
# ============================================================================

def write_bin(bin_data: dict, filepath: str):
    """
    Write a PropertyBin (.bin) file from parsed data.

    bin_data should have the same structure returned by parse_bin().
    """
    writer = BinWriter()

    is_patch = bin_data.get("magic") == "PTCH"
    version = bin_data.get("version", 2)
    linked_files = bin_data.get("linked_files", [])
    entries = bin_data.get("entries", [])

    # PTCH wrapper
    if is_patch:
        writer.write_bytes(b'PTCH')
        writer.write_u32(1)

    # PROP header
    writer.write_bytes(b'PROP')
    writer.write_u32(version)

    # Linked files (v2+)
    if version >= 2:
        writer.write_u32(len(linked_files))
        for lf in linked_files:
            writer.write_string(lf)

    # Entry count + type hashes
    writer.write_u32(len(entries))
    for entry in entries:
        writer.write_u32(_parse_hex(entry["type_hash"]))

    # Entry data
    for entry in entries:
        _write_entry(writer, entry)

    # Patch entries (if any)
    if is_patch and "patch_entries" in bin_data:
        patches = bin_data["patch_entries"]
        writer.write_u32(len(patches))
        for patch in patches:
            writer.write_u32(_parse_hex(patch["path_hash"]))
            raw = bytes.fromhex(patch["raw_data"])
            writer.write_u32(len(raw))
            writer.write_bytes(raw)

    with open(filepath, 'wb') as f:
        f.write(writer.get_bytes())


def _write_entry(writer: BinWriter, entry: dict):
    """Write a single entry to the stream."""
    if entry.get("_preserve_raw") and entry.get("_raw_entry_data"):
        raw = bytes.fromhex(entry["_raw_entry_data"])
        writer.write_u32(len(raw))
        writer.write_bytes(raw)
        return

    # Build entry content first to compute size
    inner = BinWriter()
    inner.write_u32(_parse_hex(entry["path_hash"]))

    fields = entry.get("fields") or []
    inner.write_u16(len(fields))
    for field in fields:
        _write_field(inner, field)

    content = inner.get_bytes()

    # Write content length + content
    writer.write_u32(len(content))
    writer.write_bytes(content)


# ============================================================================
# Utility Functions
# ============================================================================

def get_type_name(type_id: int) -> str:
    """Get readable name for a type ID."""
    return TYPE_NAMES.get(type_id, f"unknown({type_id})")


def count_fields_recursive(fields: list) -> int:
    """Count total number of fields in a tree (including nested)."""
    count = 0
    if not fields:
        return 0
    for field in fields:
        count += 1
        # Count nested struct/embedded fields
        if field.get("fields"):
            count += count_fields_recursive(field["fields"])
        # Count container elements
        if field.get("values"):
            for elem in field["values"]:
                if elem.get("fields"):
                    count += count_fields_recursive(elem["fields"])
        # Count map pairs
        if field.get("pairs"):
            for pair in field["pairs"]:
                for sub in (pair.get("key", {}), pair.get("value", {})):
                    if sub.get("fields"):
                        count += count_fields_recursive(sub["fields"])
    return count


def flatten_fields(fields: list, depth: int = 0, path: str = "") -> list:
    """
    Flatten a field tree into a list of display nodes for UI rendering.

    Each node is a dict with:
        depth: int (nesting level)
        path: str (dot-separated key path)
        name_hash: str
        type: int
        type_name: str
        value_display: str (formatted leaf value or summary)
        is_leaf: bool
        is_container: bool
        node_ref: dict (reference to original node for editing)
    """
    result = []
    if not fields:
        return result

    for field in fields:
        type_id = field["type"]
        name_hash = field.get("name_hash", "")
        field_path = f"{path}.{name_hash}" if path else name_hash

        node = {
            "depth": depth,
            "path": field_path,
            "name_hash": name_hash,
            "type": type_id,
            "type_name": get_type_name(type_id),
            "is_leaf": True,
            "is_container": False,
            "node_ref": field,
        }

        # Format value display
        if type_id in (TYPE_STRUCT, TYPE_EMBEDDED):
            sub_fields = field.get("fields")
            class_hash = field.get("class_hash", "0x00000000")
            if sub_fields is None:
                node["value_display"] = f"null [{class_hash}]"
            else:
                node["value_display"] = f"[{class_hash}] ({len(sub_fields)} fields)"
                node["is_leaf"] = False
                node["is_container"] = True
            result.append(node)
            if sub_fields:
                result.extend(flatten_fields(sub_fields, depth + 1, field_path))

        elif type_id in (TYPE_CONTAINER, TYPE_CONTAINER2):
            elems = field.get("values", [])
            vt_name = get_type_name(field.get("value_type", 0))
            node["value_display"] = f"list<{vt_name}> ({len(elems)} items)"
            node["is_leaf"] = False
            node["is_container"] = True
            result.append(node)
            for idx, elem in enumerate(elems):
                elem_path = f"{field_path}[{idx}]"
                if elem.get("fields"):
                    elem_node = {
                        "depth": depth + 1,
                        "path": elem_path,
                        "name_hash": f"[{idx}]",
                        "type": elem["type"],
                        "type_name": get_type_name(elem["type"]),
                        "value_display": f"[{elem.get('class_hash', '')}] ({len(elem.get('fields', []))} fields)",
                        "is_leaf": False,
                        "is_container": True,
                        "node_ref": elem,
                    }
                    result.append(elem_node)
                    result.extend(flatten_fields(elem.get("fields", []), depth + 2, elem_path))
                else:
                    elem_node = {
                        "depth": depth + 1,
                        "path": elem_path,
                        "name_hash": f"[{idx}]",
                        "type": elem["type"],
                        "type_name": get_type_name(elem["type"]),
                        "value_display": _format_leaf_value(elem),
                        "is_leaf": True,
                        "is_container": False,
                        "node_ref": elem,
                    }
                    result.append(elem_node)

        elif type_id == TYPE_MAP:
            pairs = field.get("pairs", [])
            kt = get_type_name(field.get("key_type", 0))
            vt = get_type_name(field.get("value_type", 0))
            node["value_display"] = f"map<{kt}, {vt}> ({len(pairs)} pairs)"
            node["is_leaf"] = False
            node["is_container"] = True
            result.append(node)
            for idx, pair in enumerate(pairs):
                pair_path = f"{field_path}[{idx}]"
                key_disp = _format_leaf_value(pair["key"])
                val_node = pair["value"]
                if val_node.get("fields"):
                    pair_node = {
                        "depth": depth + 1,
                        "path": pair_path,
                        "name_hash": f"{key_disp}",
                        "type": val_node["type"],
                        "type_name": get_type_name(val_node["type"]),
                        "value_display": f"[{val_node.get('class_hash', '')}]",
                        "is_leaf": False,
                        "is_container": True,
                        "node_ref": val_node,
                    }
                    result.append(pair_node)
                    result.extend(flatten_fields(val_node.get("fields", []), depth + 2, pair_path))
                else:
                    pair_node = {
                        "depth": depth + 1,
                        "path": pair_path,
                        "name_hash": f"{key_disp}",
                        "type": val_node["type"],
                        "type_name": get_type_name(val_node["type"]),
                        "value_display": _format_leaf_value(val_node),
                        "is_leaf": True,
                        "is_container": False,
                        "node_ref": val_node,
                    }
                    result.append(pair_node)

        elif type_id == TYPE_OPTIONAL:
            vt = get_type_name(field.get("value_type", 0))
            inner_val = field.get("value")
            if inner_val is None:
                node["value_display"] = f"optional<{vt}> = None"
            else:
                node["value_display"] = f"optional<{vt}> = {_format_leaf_value(inner_val)}"
            node["is_leaf"] = inner_val is None or not inner_val.get("fields")
            result.append(node)
            if inner_val and inner_val.get("fields"):
                result.extend(flatten_fields(inner_val.get("fields", []), depth + 1, field_path))

        else:
            # Leaf value
            node["value_display"] = _format_leaf_value(field)
            result.append(node)

    return result


def _format_leaf_value(node: dict) -> str:
    """Format a leaf value node for display."""
    type_id = node.get("type", 0)
    val = node.get("value")

    if val is None:
        return "null"

    if type_id in (TYPE_BOOL, TYPE_BITBOOL):
        return "true" if val else "false"

    if type_id in (TYPE_VEC2, TYPE_VEC3, TYPE_VEC4):
        return ", ".join(f"{v:.4f}" for v in val)

    if type_id == TYPE_MTX44:
        return f"[{len(val)} floats]"

    if type_id == TYPE_RGBA:
        return f"({val[0]}, {val[1]}, {val[2]}, {val[3]})"

    if type_id == TYPE_F32:
        return f"{val:.6g}"

    if isinstance(val, str):
        return val

    return str(val)


def parse_leaf_value(type_id: int, text: str):
    """Parse a user-entered string into a value for the given type."""
    text = text.strip()

    if type_id in (TYPE_BOOL, TYPE_BITBOOL):
        return text.lower() in ("true", "1", "yes")

    if type_id == TYPE_S8:
        return max(-128, min(127, int(text)))
    if type_id == TYPE_U8:
        return max(0, min(255, int(text)))
    if type_id == TYPE_S16:
        return max(-32768, min(32767, int(text)))
    if type_id == TYPE_U16:
        return max(0, min(65535, int(text)))
    if type_id == TYPE_S32:
        return int(text)
    if type_id == TYPE_U32:
        if text.startswith('0x'):
            return int(text, 16)
        return int(text)
    if type_id == TYPE_S64:
        return int(text)
    if type_id == TYPE_U64:
        if text.startswith('0x'):
            return int(text, 16)
        return int(text)

    if type_id == TYPE_F32:
        return float(text)

    if type_id in (TYPE_VEC2, TYPE_VEC3, TYPE_VEC4):
        parts = [float(p.strip()) for p in text.replace(",", " ").split() if p.strip()]
        return parts

    if type_id == TYPE_MTX44:
        parts = [float(p.strip()) for p in text.replace(",", " ").split() if p.strip()]
        return parts

    if type_id == TYPE_RGBA:
        # Accept "(r, g, b, a)" or "r g b a" or "r, g, b, a"
        text = text.strip("()")
        parts = [int(p.strip()) for p in text.replace(",", " ").split() if p.strip()]
        return parts[:4]

    if type_id == TYPE_STRING:
        return text

    if type_id in (TYPE_HASH, TYPE_LINK):
        if not text.startswith('0x'):
            # Assume it's a name to hash
            return f"0x{fnv1a_32(text):08x}"
        return text

    if type_id == TYPE_FILE:
        return text  # Keep as hex string

    return text


# ============================================================================
# Convenience: summary / stats
# ============================================================================

def bin_summary(bin_data: dict) -> str:
    """Return a human-readable summary of a parsed .bin file."""
    lines = []
    lines.append(f"PropertyBin {bin_data.get('magic', '?')} v{bin_data.get('version', '?')}")
    lines.append(f"Linked files: {len(bin_data.get('linked_files', []))}")
    entries = bin_data.get("entries", [])
    lines.append(f"Entries: {len(entries)}")

    total_fields = 0
    for entry in entries:
        fields = entry.get("fields", [])
        total_fields += count_fields_recursive(fields)
    lines.append(f"Total fields (recursive): {total_fields}")

    # Type distribution
    type_counts = {}
    for entry in entries:
        th = entry.get("type_hash", "?")
        type_counts[th] = type_counts.get(th, 0) + 1
    lines.append(f"Unique types: {len(type_counts)}")

    return "\n".join(lines)


# ============================================================================
# CLI
# ============================================================================

def main():
    """Command-line parse and display."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: propertybin_parser.py <file.bin>")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Parsing: {filepath}")

    data = parse_bin(filepath)
    print(bin_summary(data))
    print()

    for i, entry in enumerate(data["entries"][:20]):  # Show first 20
        print(f"Entry {i}: path={entry['path_hash']} type={entry['type_hash']} "
              f"fields={len(entry.get('fields', []))}")
        for field in entry.get("fields", [])[:10]:
            tn = get_type_name(field["type"])
            val = field.get("value_display", field.get("value", ""))
            if not val and field.get("fields") is not None:
                val = f"({len(field['fields'])} fields)"
            print(f"  {field['name_hash']} [{tn}] = {val}")

    if len(data["entries"]) > 20:
        print(f"  ... and {len(data['entries']) - 20} more entries")


if __name__ == "__main__":
    main()
