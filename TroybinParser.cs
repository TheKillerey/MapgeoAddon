using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace LeagueToolkit.IO.TroybinFiles
{
    /// <summary>
    /// Parser for League of Legends .troybin particle effect files
    /// Based on Inibin v2 structure with full unhashing support
    /// </summary>
    public class TroybinParser
    {
        // Property type flags
        private static readonly (string Name, ushort Flag)[] InibinFlags = new[]
        {
            ("Int32List", (ushort)(1 << 0)),
            ("Float32List", (ushort)(1 << 1)),
            ("FixedPointFloatList", (ushort)(1 << 2)),
            ("Int16List", (ushort)(1 << 3)),
            ("Int8List", (ushort)(1 << 4)),
            ("BitList", (ushort)(1 << 5)),
            ("FixedPointFloatListVec3", (ushort)(1 << 6)),
            ("Float32ListVec3", (ushort)(1 << 7)),
            ("FixedPointFloatListVec2", (ushort)(1 << 8)),
            ("Float32ListVec2", (ushort)(1 << 9)),
            ("FixedPointFloatListVec4", (ushort)(1 << 10)),
            ("Float32ListVec4", (ushort)(1 << 11)),
            ("StringList", (ushort)(1 << 12)),
        };

        public class TroybinData
        {
            public byte Version { get; set; } = 2;
            public ushort Flags { get; set; }
            public ushort StringDataLength { get; set; }
            public Dictionary<string, List<PropertyEntry>> Sets { get; set; } = new();
            public List<string> EmitterNames { get; set; } = new();
        }

        public class PropertyEntry
        {
            public uint Hash { get; set; }
            public object Value { get; set; }
            public string ResolvedName { get; set; }
        }

        /// <summary>
        /// Read a troybin file from disk
        /// </summary>
        public static TroybinData Read(string filePath)
        {
            return Read(File.ReadAllBytes(filePath));
        }

        /// <summary>
        /// Read a troybin file from bytes
        /// </summary>
        public static TroybinData Read(byte[] data)
        {
            using var ms = new MemoryStream(data);
            using var reader = new BinaryReader(ms);

            var result = new TroybinData();

            // Read header
            result.Version = reader.ReadByte();
            if (result.Version != 2)
                throw new InvalidDataException($"Unsupported Inibin version: {result.Version}. Only version 2 is supported.");

            result.StringDataLength = reader.ReadUInt16();
            result.Flags = reader.ReadUInt16();

            int stringBase = data.Length - result.StringDataLength;

            // Read all property sets
            result.Sets = new Dictionary<string, List<PropertyEntry>>();
            foreach (var (setName, setFlag) in InibinFlags)
            {
                if ((result.Flags & setFlag) != 0)
                {
                    result.Sets[setName] = ReadSet(reader, setName, data, stringBase);
                }
            }

            // Extract emitter names
            result.EmitterNames = ExtractGroupNames(result);

            return result;
        }

        /// <summary>
        /// Write a troybin file to disk
        /// </summary>
        public static void Write(string filePath, TroybinData data)
        {
            File.WriteAllBytes(filePath, Write(data));
        }

        /// <summary>
        /// Write a troybin file to bytes
        /// </summary>
        public static byte[] Write(TroybinData data)
        {
            using var ms = new MemoryStream();
            using var writer = new BinaryWriter(ms);

            // Calculate flags
            ushort flags = 0;
            foreach (var (setName, setFlag) in InibinFlags)
            {
                if (data.Sets.ContainsKey(setName) && data.Sets[setName].Count > 0)
                    flags |= setFlag;
            }

            // Build string table
            var stringTable = new MemoryStream();
            var stringOffsets = new Dictionary<string, ushort>();

            if (data.Sets.ContainsKey("StringList"))
            {
                var seenStrings = new List<string>();
                foreach (var entry in data.Sets["StringList"])
                {
                    var str = entry.Value.ToString();
                    if (!stringOffsets.ContainsKey(str))
                        seenStrings.Add(str);
                }

                foreach (var str in seenStrings)
                {
                    stringOffsets[str] = (ushort)stringTable.Position;
                    var bytes = Encoding.ASCII.GetBytes(str);
                    stringTable.Write(bytes, 0, bytes.Length);
                    stringTable.WriteByte(0); // Null terminator
                }
            }

            ushort stringDataLength = (ushort)stringTable.Length;

            // Write header
            writer.Write(data.Version);
            writer.Write(stringDataLength);
            writer.Write(flags);

            // Write all sets
            foreach (var (setName, setFlag) in InibinFlags)
            {
                if ((flags & setFlag) != 0)
                {
                    WriteSet(writer, setName, data.Sets[setName], stringOffsets);
                }
            }

            // Append string table
            stringTable.Position = 0;
            stringTable.CopyTo(ms);

            return ms.ToArray();
        }

        /// <summary>
        /// Resolve property names using hash dictionary
        /// </summary>
        public static void ResolveNames(TroybinData data)
        {
            var hashMap = IniHashDictionary.BuildHashMap(data.EmitterNames);

            foreach (var kvp in data.Sets)
            {
                foreach (var entry in kvp.Value)
                {
                    if (hashMap.TryGetValue(entry.Hash, out var label))
                        entry.ResolvedName = label;
                }
            }
        }

        // ═══════════════════════════════════════════════════════════════════
        // Private Helper Methods
        // ═══════════════════════════════════════════════════════════════════

        private static List<PropertyEntry> ReadSet(BinaryReader reader, string setName, byte[] data, int stringBase)
        {
            ushort count = reader.ReadUInt16();
            var hashes = new uint[count];
            for (int i = 0; i < count; i++)
                hashes[i] = reader.ReadUInt32();

            var entries = new List<PropertyEntry>();

            for (int i = 0; i < count; i++)
            {
                object value = setName switch
                {
                    "BitList" => ReadBit(reader, i),
                    "Int32List" => reader.ReadInt32(),
                    "Float32List" => reader.ReadSingle(),
                    "FixedPointFloatList" => reader.ReadByte() * 0.1f,
                    "Int16List" => reader.ReadInt16(),
                    "Int8List" => reader.ReadByte(),
                    "FixedPointFloatListVec3" => new[] { reader.ReadByte(), reader.ReadByte(), reader.ReadByte() },
                    "Float32ListVec3" => new[] { reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle() },
                    "FixedPointFloatListVec2" => new[] { reader.ReadByte(), reader.ReadByte() },
                    "Float32ListVec2" => new[] { reader.ReadSingle(), reader.ReadSingle() },
                    "FixedPointFloatListVec4" => new[] { reader.ReadByte(), reader.ReadByte(), reader.ReadByte(), reader.ReadByte() },
                    "Float32ListVec4" => new[] { reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle() },
                    "StringList" => null, // Read separately
                    _ => throw new InvalidDataException($"Unsupported set type: {setName}")
                };

                entries.Add(new PropertyEntry { Hash = hashes[i], Value = value });
            }

            // Read strings separately
            if (setName == "StringList")
            {
                var offsets = new ushort[count];
                for (int i = 0; i < count; i++)
                    offsets[i] = reader.ReadUInt16();

                for (int i = 0; i < count; i++)
                    entries[i].Value = ReadCString(data, stringBase + offsets[i]);
            }

            return entries;
        }

        private static bool ReadBit(BinaryReader reader, int index)
        {
            if ((index % 8) == 0)
                reader.BaseStream.Position--; // Rewind to read same byte
            
            var packed = reader.ReadByte();
            return ((packed >> (index % 8)) & 0x1) != 0;
        }

        private static string ReadCString(byte[] data, int offset)
        {
            int end = offset;
            while (end < data.Length && data[end] != 0)
                end++;
            return Encoding.ASCII.GetString(data, offset, end - offset);
        }

        private static void WriteSet(BinaryWriter writer, string setName, List<PropertyEntry> entries, Dictionary<string, ushort> stringOffsets)
        {
            ushort count = (ushort)entries.Count;
            writer.Write(count);

            // Write hashes
            foreach (var entry in entries)
                writer.Write(entry.Hash);

            // Write values
            switch (setName)
            {
                case "BitList":
                    WriteBits(writer, entries);
                    break;
                case "Int32List":
                    foreach (var e in entries) writer.Write(Convert.ToInt32(e.Value));
                    break;
                case "Float32List":
                    foreach (var e in entries) writer.Write(Convert.ToSingle(e.Value));
                    break;
                case "FixedPointFloatList":
                    foreach (var e in entries) writer.Write((byte)(Convert.ToSingle(e.Value) / 0.1f));
                    break;
                case "Int16List":
                    foreach (var e in entries) writer.Write(Convert.ToInt16(e.Value));
                    break;
                case "Int8List":
                    foreach (var e in entries) writer.Write(Convert.ToByte(e.Value));
                    break;
                case "FixedPointFloatListVec3":
                    foreach (var e in entries)
                    {
                        var arr = (int[])e.Value;
                        writer.Write((byte)arr[0]);
                        writer.Write((byte)arr[1]);
                        writer.Write((byte)arr[2]);
                    }
                    break;
                case "Float32ListVec3":
                    foreach (var e in entries)
                    {
                        var arr = (float[])e.Value;
                        writer.Write(arr[0]);
                        writer.Write(arr[1]);
                        writer.Write(arr[2]);
                    }
                    break;
                case "FixedPointFloatListVec2":
                    foreach (var e in entries)
                    {
                        var arr = (int[])e.Value;
                        writer.Write((byte)arr[0]);
                        writer.Write((byte)arr[1]);
                    }
                    break;
                case "Float32ListVec2":
                    foreach (var e in entries)
                    {
                        var arr = (float[])e.Value;
                        writer.Write(arr[0]);
                        writer.Write(arr[1]);
                    }
                    break;
                case "FixedPointFloatListVec4":
                    foreach (var e in entries)
                    {
                        var arr = (int[])e.Value;
                        writer.Write((byte)arr[0]);
                        writer.Write((byte)arr[1]);
                        writer.Write((byte)arr[2]);
                        writer.Write((byte)arr[3]);
                    }
                    break;
                case "Float32ListVec4":
                    foreach (var e in entries)
                    {
                        var arr = (float[])e.Value;
                        writer.Write(arr[0]);
                        writer.Write(arr[1]);
                        writer.Write(arr[2]);
                        writer.Write(arr[3]);
                    }
                    break;
                case "StringList":
                    foreach (var e in entries)
                    {
                        var str = e.Value.ToString();
                        var offset = stringOffsets[str];
                        writer.Write(offset);
                    }
                    break;
            }
        }

        private static void WriteBits(BinaryWriter writer, List<PropertyEntry> entries)
        {
            byte packed = 0;
            int bitPos = 0;

            for (int i = 0; i < entries.Count; i++)
            {
                if (Convert.ToBoolean(entries[i].Value))
                    packed |= (byte)(1 << bitPos);

                bitPos++;
                if (bitPos == 8)
                {
                    writer.Write(packed);
                    packed = 0;
                    bitPos = 0;
                }
            }

            if (bitPos > 0)
                writer.Write(packed);
        }

        private static List<string> ExtractGroupNames(TroybinData data)
        {
            var groupNames = new List<string>();

            if (data.Sets.ContainsKey("StringList"))
            {
                for (int i = 0; i < 50; i++)
                {
                    uint expectedHash = IniHashDictionary.SectionFieldHash("System", $"GroupPart{i}");
                    var entry = data.Sets["StringList"].FirstOrDefault(e => e.Hash == expectedHash);
                    if (entry != null && !string.IsNullOrEmpty(entry.Value?.ToString()))
                        groupNames.Add(entry.Value.ToString());
                }
            }

            return groupNames;
        }

        // ═══════════════════════════════════════════════════════════════════
        // Convenience Methods
        // ═══════════════════════════════════════════════════════════════════

        /// <summary>
        /// Get a property value by emitter and field name
        /// </summary>
        public static T GetProperty<T>(TroybinData data, string emitter, string field, T defaultValue = default)
        {
            uint hash = IniHashDictionary.SectionFieldHash(emitter, field);
            
            foreach (var kvp in data.Sets)
            {
                var entry = kvp.Value.FirstOrDefault(e => e.Hash == hash);
                if (entry != null)
                {
                    if (entry.Value is T typedValue)
                        return typedValue;
                    return (T)Convert.ChangeType(entry.Value, typeof(T));
                }
            }

            return defaultValue;
        }

        /// <summary>
        /// Set a property value by emitter and field name
        /// </summary>
        public static void SetProperty<T>(TroybinData data, string emitter, string field, T value, string setType)
        {
            uint hash = IniHashDictionary.SectionFieldHash(emitter, field);

            if (!data.Sets.ContainsKey(setType))
                data.Sets[setType] = new List<PropertyEntry>();

            var entry = data.Sets[setType].FirstOrDefault(e => e.Hash == hash);
            if (entry != null)
            {
                entry.Value = value;
            }
            else
            {
                data.Sets[setType].Add(new PropertyEntry
                {
                    Hash = hash,
                    Value = value
                });
            }
        }

        /// <summary>
        /// Print troybin contents to console (for debugging)
        /// </summary>
        public static void Print(TroybinData data, bool resolveNames = true)
        {
            if (resolveNames)
                ResolveNames(data);

            Console.WriteLine($"Version: {data.Version}");
            Console.WriteLine($"Flags: 0x{data.Flags:X4}");
            Console.WriteLine($"String Data Length: {data.StringDataLength}");
            Console.WriteLine($"Emitters: {string.Join(", ", data.EmitterNames)}");
            Console.WriteLine();

            foreach (var kvp in data.Sets)
            {
                Console.WriteLine($"[{kvp.Key}] count={kvp.Value.Count}");
                foreach (var entry in kvp.Value)
                {
                    string label = entry.ResolvedName ?? $"0x{entry.Hash:X8}";
                    string valueStr = FormatValue(entry.Value);
                    Console.WriteLine($"  {label} = {valueStr}");
                }
                Console.WriteLine();
            }
        }

        private static string FormatValue(object value)
        {
            if (value is Array arr)
            {
                var items = arr.Cast<object>().Select(v => v.ToString());
                return $"[{string.Join(", ", items)}]";
            }
            return value?.ToString() ?? "null";
        }
    }
}
