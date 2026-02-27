import argparse
import struct
from pathlib import Path


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
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read_u8(self):
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_u16(self):
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_u32(self):
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_i16(self):
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_i32(self):
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_f32(self):
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value


def read_cstr(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("ascii", errors="replace")


def read_set(reader: Reader, set_name: str, string_base: int):
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


def sdbm_hash(value: str) -> int:
    hash_value = 0
    for char in value:
        hash_value = (ord(char) + (65599 * hash_value)) & 0xFFFFFFFF
    return hash_value


def sdbm_hash_lower_with_delimiter(section: str, prop: str, delimiter: str = "*") -> int:
    return sdbm_hash((section.lower() + delimiter + prop.lower()))


def parse_ini_sections(path: Path):
    sections = {}
    current_section = None

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            sections.setdefault(current_section, [])
            continue

        if current_section is not None and "=" in line:
            key, value = line.split("=", 1)
            sections[current_section].append((key.strip(), value.strip()))

    return sections


def build_hash_name_map_from_cfg(cfg_path: Path):
    sections = parse_ini_sections(cfg_path)
    hash_to_names = {}
    for section, entries in sections.items():
        for prop, _value in entries:
            hash_value = sdbm_hash_lower_with_delimiter(section, prop, "*")
            hash_to_names.setdefault(hash_value, []).append(f"{section}*{prop}")
    return hash_to_names


def parse_cfgbin(path: Path):
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
        "string_base": string_base,
        "file_size": len(data),
        "sets": parsed_sets,
    }


def write_cfgbin(sets: dict, output_path: Path):
    """Write an inibin v2 binary file from a dict of sets.

    ``sets`` should have the same shape as ``parse_cfgbin()["sets"]``:

        {
            "Int32List": [(hash, value), ...],
            "Float32List": [(hash, value), ...],
            ...
        }

    Only non-empty sets are written.  The order of INIBIN_FLAGS is used for
    the canonical set ordering.
    """
    import io

    # --- Build string table first (needed for StringList offsets) ----------
    string_table = bytearray()
    string_offsets: dict[int, int] = {}  # id(entry) → offset into string_table

    if "StringList" in sets and sets["StringList"]:
        for _hash, value in sets["StringList"]:
            offset = len(string_table)
            string_offsets[id((_hash, value))] = offset
            string_table.extend(value.encode("ascii", errors="replace"))
            string_table.append(0)  # null terminator

    # Because we can't use id() of tuples reliably across rebuild, store
    # offsets by index instead.
    string_offset_by_idx: list[int] = []
    if "StringList" in sets and sets["StringList"]:
        cur = 0
        for _hash, value in sets["StringList"]:
            string_offset_by_idx.append(cur)
            encoded = value.encode("ascii", errors="replace")
            cur += len(encoded) + 1  # +1 for null terminator

    # --- Compute flags and build set body bytes ---------------------------
    flags = 0
    body = bytearray()

    for set_name, set_flag in INIBIN_FLAGS:
        entries = sets.get(set_name, [])
        if not entries:
            continue
        flags |= set_flag
        count = len(entries)
        body.extend(struct.pack("<H", count))
        # Hashes
        for hash_val, _value in entries:
            body.extend(struct.pack("<I", hash_val))
        # Values
        if set_name == "BitList":
            packed = 0
            for i, (_h, v) in enumerate(entries):
                bit = 1 if v else 0
                packed |= (bit << (i % 8))
                if (i % 8) == 7 or i == count - 1:
                    body.extend(struct.pack("<B", packed))
                    packed = 0
        elif set_name == "Int32List":
            for _h, v in entries:
                body.extend(struct.pack("<i", int(v)))
        elif set_name == "Float32List":
            for _h, v in entries:
                body.extend(struct.pack("<f", float(v)))
        elif set_name == "FixedPointFloatList":
            for _h, v in entries:
                body.extend(struct.pack("<B", max(0, min(255, int(round(float(v) / 0.1))))))
        elif set_name == "Int16List":
            for _h, v in entries:
                body.extend(struct.pack("<h", int(v)))
        elif set_name == "Int8List":
            for _h, v in entries:
                body.extend(struct.pack("<B", max(0, min(255, int(v)))))
        elif set_name.startswith("FixedPointFloatListVec"):
            for _h, vec in entries:
                for comp in vec:
                    body.extend(struct.pack("<B", max(0, min(255, int(comp)))))
        elif set_name.startswith("Float32ListVec"):
            for _h, vec in entries:
                for comp in vec:
                    body.extend(struct.pack("<f", float(comp)))
        elif set_name == "StringList":
            for idx, (_h, _v) in enumerate(entries):
                body.extend(struct.pack("<H", string_offset_by_idx[idx]))
        else:
            raise ValueError(f"Unsupported set for writing: {set_name}")

    # --- Assemble file: header + body + string_table ----------------------
    string_data_length = len(string_table)
    header = bytearray()
    header.extend(struct.pack("<B", 2))             # version
    header.extend(struct.pack("<H", string_data_length))
    header.extend(struct.pack("<H", flags))

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(body)
        f.write(string_table)


def main():
    parser = argparse.ArgumentParser(description="Read League cfgbin (Inibin v2) files")
    parser.add_argument("file", help="Path to .cfgbin file")
    parser.add_argument("--cfg", help="Optional path to readable .cfg to dehash keys")
    parser.add_argument("--max-per-set", type=int, default=0, help="Limit rows per set (0 = all)")
    args = parser.parse_args()

    result = parse_cfgbin(Path(args.file))
    hash_name_map = build_hash_name_map_from_cfg(Path(args.cfg)) if args.cfg else {}

    print(f"File: {args.file}")
    print(f"Version: {result['version']}")
    print(f"Size: {result['file_size']} bytes")
    print(f"Flags: 0x{result['flags']:04x}")
    print(f"StringDataLength: {result['string_data_length']}")
    print(f"StringBaseOffset: {result['string_base']}")
    if args.cfg:
        resolved_total = sum(1 for entries in result["sets"].values() for hash_value, _ in entries if hash_value in hash_name_map)
        all_total = sum(len(entries) for entries in result["sets"].values())
        print(f"ResolvedWithCFG: {resolved_total}/{all_total}")
    print()

    for set_name, entries in result["sets"].items():
        print(f"[{set_name}] count={len(entries)}")
        limit = args.max_per_set if args.max_per_set > 0 else len(entries)
        for hash_value, value in entries[:limit]:
            resolved = hash_name_map.get(hash_value)
            if resolved:
                if len(resolved) == 1:
                    print(f"  0x{hash_value:08x} ({resolved[0]}) = {value}")
                else:
                    print(f"  0x{hash_value:08x} ({' | '.join(resolved)}) = {value}")
            else:
                print(f"  0x{hash_value:08x} = {value}")
        if limit < len(entries):
            print(f"  ... ({len(entries) - limit} more)")
        print()


if __name__ == "__main__":
    main()
