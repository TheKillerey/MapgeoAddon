using System;
using System.Linq;
using LeagueToolkit.IO.TroybinFiles;

namespace LeagueToolkit.Examples
{
    /// <summary>
    /// Example usage of the Troybin Parser
    /// </summary>
    public static class TroybinExamples
    {
        /// <summary>
        /// Example 1: Read a troybin file and display its contents
        /// </summary>
        public static void ReadExample()
        {
            // Read the file
            var data = TroybinParser.Read("particle.troybin");

            // Resolve property names
            TroybinParser.ResolveNames(data);

            // Print to console
            TroybinParser.Print(data);

            // Or access manually
            foreach (var kvp in data.Sets)
            {
                Console.WriteLine($"{kvp.Key}: {kvp.Value.Count} properties");
                foreach (var entry in kvp.Value)
                {
                    string name = entry.ResolvedName ?? $"0x{entry.Hash:X8}";
                    Console.WriteLine($"  {name} = {entry.Value}");
                }
            }
        }

        /// <summary>
        /// Example 2: Create a new troybin file from scratch
        /// </summary>
        public static void CreateExample()
        {
            var data = new TroybinParser.TroybinData
            {
                Version = 2,
                Sets = new()
            };

            string emitterName = "glow";

            // Define the emitter in System section
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
                },
                new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-meshtex"),
                    Value = "glow.dds"
                }
            };

            // Add numeric properties
            data.Sets["Int8List"] = new()
            {
                new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-life"),
                    Value = 2
                },
                new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitterName, "e-rate"),
                    Value = 10
                }
            };

            // Add vector properties
            data.Sets["Float32ListVec3"] = new()
            {
                new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitterName, "p-scale"),
                    Value = new[] { 10.0f, 10.0f, 10.0f }
                }
            };

            // Save to file
            TroybinParser.Write("my_particle.troybin", data);
            Console.WriteLine("Created my_particle.troybin");
        }

        /// <summary>
        /// Example 3: Modify an existing troybin file
        /// </summary>
        public static void ModifyExample()
        {
            // Read existing file
            var data = TroybinParser.Read("particle.troybin");

            string emitter = data.EmitterNames.FirstOrDefault() ?? "GroupPart0";

            // Get current scale
            var currentScale = TroybinParser.GetProperty<float[]>(data, emitter, "p-scale");
            Console.WriteLine($"Current scale: [{string.Join(", ", currentScale)}]");

            // Double the scale
            var newScale = currentScale.Select(x => x * 2.0f).ToArray();
            TroybinParser.SetProperty(data, emitter, "p-scale", newScale, "Float32ListVec3");

            // Get and modify emission rate
            var rate = TroybinParser.GetProperty<byte>(data, emitter, "e-rate", (byte)1);
            Console.WriteLine($"Current emission rate: {rate}");
            TroybinParser.SetProperty<byte>(data, emitter, "e-rate", (byte)(rate * 2), "Int8List");

            // Save modified file
            TroybinParser.Write("particle_modified.troybin", data);
            Console.WriteLine("Saved modifications");
        }

        /// <summary>
        /// Example 4: Work with multi-emitter particles
        /// </summary>
        public static void MultiEmitterExample()
        {
            var data = new TroybinParser.TroybinData
            {
                Version = 2,
                Sets = new()
            };

            var emitters = new[] { "glow", "sparkle", "trail" };

            // Initialize StringList
            data.Sets["StringList"] = new();
            data.Sets["Float32ListVec3"] = new();

            // Define all emitters in System section
            for (int i = 0; i < emitters.Length; i++)
            {
                data.Sets["StringList"].Add(new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash("System", $"GroupPart{i}"),
                    Value = emitters[i]
                });
            }

            // Add properties for each emitter
            foreach (var emitter in emitters)
            {
                // Mesh
                data.Sets["StringList"].Add(new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitter, "p-mesh"),
                    Value = $"{emitter}.scb"
                });

                // Scale
                data.Sets["Float32ListVec3"].Add(new TroybinParser.PropertyEntry
                {
                    Hash = IniHashDictionary.SectionFieldHash(emitter, "p-scale"),
                    Value = new[] { 10.0f, 10.0f, 10.0f }
                });
            }

            TroybinParser.Write("multi_emitter.troybin", data);
            Console.WriteLine($"Created particle with {emitters.Length} emitters");
        }

        /// <summary>
        /// Example 5: Batch process multiple troybin files
        /// </summary>
        public static void BatchProcessExample(string directory)
        {
            var files = System.IO.Directory.GetFiles(directory, "*.troybin");

            foreach (var file in files)
            {
                try
                {
                    var data = TroybinParser.Read(file);
                    TroybinParser.ResolveNames(data);

                    Console.WriteLine($"\n{System.IO.Path.GetFileName(file)}:");
                    Console.WriteLine($"  Version: {data.Version}");
                    Console.WriteLine($"  Properties: {data.Sets.Values.Sum(s => s.Count)}");
                    Console.WriteLine($"  Emitters: {string.Join(", ", data.EmitterNames)}");

                    // Example: Scale all particles by 1.5x
                    foreach (var emitter in data.EmitterNames)
                    {
                        var scale = TroybinParser.GetProperty<float[]>(data, emitter, "p-scale");
                        if (scale != null)
                        {
                            var newScale = scale.Select(x => x * 1.5f).ToArray();
                            TroybinParser.SetProperty(data, emitter, "p-scale", newScale, "Float32ListVec3");
                        }
                    }

                    // Save to output directory
                    var outputFile = System.IO.Path.Combine(directory, "modified", System.IO.Path.GetFileName(file));
                    TroybinParser.Write(outputFile, data);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Error processing {file}: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Example 6: Convert troybin to JSON for external editing
        /// </summary>
        public static void ToJsonExample()
        {
            var data = TroybinParser.Read("particle.troybin");
            TroybinParser.ResolveNames(data);

            // Create a JSON-serializable structure
            var json = new
            {
                version = data.Version,
                emitters = data.EmitterNames,
                properties = data.Sets.SelectMany(kvp =>
                    kvp.Value.Select(e => new
                    {
                        type = kvp.Key,
                        hash = $"0x{e.Hash:X8}",
                        name = e.ResolvedName,
                        value = e.Value
                    })
                )
            };

            // Serialize to JSON (requires System.Text.Json or Newtonsoft.Json)
            var jsonString = System.Text.Json.JsonSerializer.Serialize(json, new System.Text.Json.JsonSerializerOptions
            {
                WriteIndented = true
            });

            System.IO.File.WriteAllText("particle.json", jsonString);
            Console.WriteLine("Exported to particle.json");
        }

        /// <summary>
        /// Example 7: Find all particles using a specific texture
        /// </summary>
        public static void FindTextureUsage(string directory, string textureName)
        {
            var files = System.IO.Directory.GetFiles(directory, "*.troybin");

            foreach (var file in files)
            {
                try
                {
                    var data = TroybinParser.Read(file);

                    if (data.Sets.ContainsKey("StringList"))
                    {
                        var hasTexture = data.Sets["StringList"]
                            .Any(e => e.Value.ToString().Equals(textureName, StringComparison.OrdinalIgnoreCase));

                        if (hasTexture)
                        {
                            Console.WriteLine($"Found in: {System.IO.Path.GetFileName(file)}");
                            TroybinParser.ResolveNames(data);

                            // Show which emitter uses it
                            foreach (var entry in data.Sets["StringList"])
                            {
                                if (entry.Value.ToString().Equals(textureName, StringComparison.OrdinalIgnoreCase))
                                {
                                    Console.WriteLine($"  {entry.ResolvedName}");
                                }
                            }
                        }
                    }
                }
                catch { }
            }
        }
    }
}
