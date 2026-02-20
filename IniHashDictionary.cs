using System;
using System.Collections.Generic;
using System.Linq;

namespace LeagueToolkit.IO.TroybinFiles
{
    /// <summary>
    /// Builds the hash→name lookup table for Troybin files.
    /// Based on the SDBM hashing algorithm used by League of Legends particle system.
    /// </summary>
    public static class IniHashDictionary
    {
        // Constants matching dictionary.jsx
        private const int FIELD_VARS = 10;
        private const int GPART_VARS = 50;
        private const int MAT_VARS = 5;
        private const int RAND_VARS = 10;
        private const int COLOR_VARS = 25;
        private const int ROT_VARS = 10;

        /// <summary>
        /// Calculate SDBM hash for a string (case-insensitive)
        /// </summary>
        private static uint IHash(string value, uint ret = 0)
        {
            foreach (char c in value)
                ret = (uint)(char.ToLowerInvariant(c) + 65599u * ret);
            return ret;
        }

        /// <summary>
        /// Calculate section+field hash (standard format)
        /// </summary>
        public static uint SectionFieldHash(string section, string field)
        {
            uint sh = IHash("*", IHash(section));
            return IHash(field, sh);
        }

        /// <summary>
        /// Calculate section+field hash for commented fields
        /// </summary>
        private static uint SectionFieldHashComment(string section, string field)
        {
            uint sh = IHash("*", IHash(section));
            return IHash("'" + field, sh);
        }

        /// <summary>
        /// Build a complete hash→"[section] field" map for a Troybin file.
        /// </summary>
        /// <param name="groupNames">Actual emitter names from System[GroupPart0..N] values</param>
        public static Dictionary<uint, string> BuildHashMap(IEnumerable<string> groupNames = null)
        {
            var map = new Dictionary<uint, string>();

            void Add(string section, IEnumerable<string> fieldNames)
            {
                foreach (var field in fieldNames)
                {
                    uint h1 = SectionFieldHash(section, field);
                    uint h2 = SectionFieldHashComment(section, field);
                    string label = $"[{section}] {field}";
                    map.TryAdd(h1, label);
                    map.TryAdd(h2, label);
                }
            }

            // Always add System section
            Add("System", GetSystemFieldNames());

            // GroupPartN section keys (fallback)
            var gpFields = GetGroupFieldNames().ToList();
            for (int i = 0; i < GPART_VARS; i++)
                Add($"GroupPart{i}", gpFields);

            // If we have actual group names, build hashes using those as sections
            if (groupNames != null)
            {
                foreach (var gn in groupNames.Where(n => !string.IsNullOrEmpty(n)))
                    Add(gn, gpFields);
            }

            return map;
        }

        /// <summary>
        /// Parse a label string "[section] field" into its two parts
        /// </summary>
        public static (string section, string field) ParseLabel(string label)
        {
            int start = label.IndexOf('[') + 1;
            int end = label.IndexOf(']');
            if (start > 0 && end > start)
                return (label.Substring(start, end - start), label.Substring(end + 2));
            return ("Unknown", label);
        }

        /// <summary>
        /// Resolve a hash to (section, fieldName) pair
        /// </summary>
        public static (string section, string field) Resolve(uint hash, IEnumerable<string> groupNames = null)
        {
            var map = BuildHashMap(groupNames);
            if (!map.TryGetValue(hash, out var label))
                return (null, null);
            return ParseLabel(label);
        }

        // ═══════════════════════════════════════════════════════════════════
        // System Section Field Names
        // ═══════════════════════════════════════════════════════════════════

        private static IEnumerable<string> GetSystemFieldNames()
        {
            var fields = new List<string>();

            // GroupPartN, GroupPartNType, GroupPartNImportance
            for (int i = 0; i < GPART_VARS; i++)
            {
                fields.Add($"GroupPart{i}");
                fields.Add($"GroupPart{i}Type");
                fields.Add($"GroupPart{i}Importance");
                fields.Add($"Override-Offset{i}");
                fields.Add($"Override-Rotation{i}");
                fields.Add($"Override-Scale{i}");
            }

            fields.AddRange(new[]
            {
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
            });

            for (int i = 0; i < MAT_VARS; i++)
            {
                fields.Add($"MaterialOverride{i}BlendMode");
                fields.Add($"MaterialOverride{i}Texture");
                fields.Add($"MaterialOverride{i}SubMesh");
            }

            return fields;
        }

        // ═══════════════════════════════════════════════════════════════════
        // Group/Emitter Field Names
        // ═══════════════════════════════════════════════════════════════════

        private static IEnumerable<string> GetGroupFieldNames()
        {
            var fields = new List<string>();

            // Base group names
            var groupNames = new[]
            {
                "ExcludeAttachmentType","KeywordsExcluded","KeywordsIncluded","KeywordsRequired",
                "Particle-ScaleAlongMovementVector","SoundOnCreate","SoundPersistent",
                "VoiceOverOnCreate","VoiceOverPersistent","dont-scroll-alpha-UV",
                "e-active","e-alpharef","e-beam-segments","e-censor-policy","e-disabled",
                "e-life","e-life-scale","e-linger","e-local-orient","e-period",
                "e-shape-name","e-shape-scale","e-shape-use-normal-for-birth",
                "e-soft-in-depth","e-soft-out-depth","e-soft-in-depth-delta","e-soft-out-depth-delta",
                "e-timeoffset","e-trail-cutoff","e-trail-smoothing","e-uvscroll","e-uvscroll-mult",
                "flag-brighter-in-fow","flag-disable-z","flag-disable-y","flag-groundlayer",
                "flag-ground-layer","flag-force-animated-mesh-z-write","flag-projected",
                "p-alphaslicerange","p-animation","p-backfaceon","p-beammode","p-bindtoemitter",
                "p-coloroffset","p-colorscale","p-colortype","p-distortion-mode","p-distortion-power",
                "p-falloff-texture","p-fixedorbit","p-fixedorbittype","p-flexoffset","p-flexscale",
                "p-followterrain","p-frameRate","p-frameRate-mult","p-fresnel","p-life-scale",
                "p-life-scale-offset","p-life-scale-symX","p-life-scale-symY","p-life-scale-symZ",
                "p-linger","p-local-orient","p-lockedtoemitter","p-mesh","p-meshtex",
                "p-meshtex-mult","p-normal-map","p-numframes","p-numframes-mult",
                "p-offsetbyheight","p-offsetbyradius","p-orientation","p-projection-fading",
                "p-projection-y-range","p-randomstartframe","p-randomstartframe-mult",
                "p-reflection-fresnel","p-reflection-map","p-reflection-opacity-direct",
                "p-reflection-opacity-glancing","p-rgba","p-scalebias","p-scalebyheight",
                "p-scalebyradius","p-scaleupfromorigin","p-shadow","p-simpleorient",
                "p-skeleton","p-skin","p-startframe","p-startframe-mult","p-texdiv",
                "p-texdiv-mult","p-texture","p-texture-mode","p-texture-mult",
                "p-texture-mult-mode","p-texture-pixelate","p-trailmode","p-type","p-uvmode",
                "p-uvparallax-scale","p-uvscroll-alpha-mult","p-uvscroll-no-alpha","p-uvscroll-rgb",
                "p-uvscroll-rgb-clamp","p-uvscroll-rgb-clamp-mult","p-vec-velocity-minscale",
                "p-vec-velocity-scale","p-vecalign","p-xquadrot-on","pass","rendermode",
                "single-particle","submesh-list","teamcolor-correction","uniformscale",
                "ChildParticleName","ChildSpawnAtBone","ChildEmitOnDeath","p-childProb",
            };
            fields.AddRange(groupNames);

            // ChildParticleNameN etc.
            for (int i = 0; i < GPART_VARS; i++)
            {
                fields.Add($"ChildParticleName{i}");
                fields.Add($"ChildSpawnAtBone{i}");
                fields.Add($"ChildEmitOnDeath{i}");
            }

            // MaterialOverrideN*
            for (int i = 0; i < MAT_VARS; i++)
            {
                fields.Add($"MaterialOverride{i}BlendMode");
                fields.Add($"MaterialOverride{i}GlossTexture");
                fields.Add($"MaterialOverride{i}EmissiveTexture");
                fields.Add($"MaterialOverride{i}FixedAlphaScrolling");
                fields.Add($"MaterialOverride{i}Priority");
                fields.Add($"MaterialOverride{i}RenderingMode");
                fields.Add($"MaterialOverride{i}SubMesh");
                fields.Add($"MaterialOverride{i}Texture");
                fields.Add($"MaterialOverride{i}UVScroll");
            }

            // e-rgba / p-rgba / p-xrgba color variants
            foreach (var b in new[] { "e-rgba", "p-rgba", "p-xrgba" })
            {
                fields.Add(b);
                for (int i = 0; i < COLOR_VARS; i++)
                    fields.Add($"{b}{i}");
                foreach (var mod in new[] { "R", "G", "B", "A" })
                {
                    fields.Add($"{b}{mod}P");
                    for (int i = 0; i < COLOR_VARS; i++)
                        fields.Add($"{b}{mod}P{i}");
                }
            }

            // flexFloat: p-scale, p-scaleEmitOffset
            foreach (var b in new[] { "p-scale", "p-scaleEmitOffset" })
            {
                fields.Add(b);
                fields.Add($"{b}_flex");
                for (int j = 0; j < 4; j++)
                    fields.Add($"{b}_flex{j}");
            }

            // flexRandFloat: e-rate, p-life, p-rotvel
            fields.AddRange(FlexRandFloat(new[] { "e-rate", "p-life", "p-rotvel" }));

            // flexRandVec2: e-uvoffset
            fields.AddRange(FlexRandVec2(new[] { "e-uvoffset" }));

            // flexRandVec3: p-offset, p-postoffset, p-vel
            fields.AddRange(FlexRandVec3(new[] { "p-offset", "p-postoffset", "p-vel" }));

            // randFloat: many fields
            fields.AddRange(RandFloat(new[]
            {
                "e-color-modulate","e-framerate","p-bindtoemitter","p-life","p-quadrot",
                "p-rotvel","p-scale","p-xquadrot","p-xscale","e-rate"
            }));

            // randVec2
            fields.AddRange(RandVec2(new[]
            {
                "e-ratebyvel","e-uvoffset","e-uvoffset-mult","p-uvscroll-rgb","p-uvscroll-rgb-mult"
            }));

            // randVec3: many fields
            fields.AddRange(RandVec3(new[]
            {
                "Emitter-BirthRotationalAcceleration","Particle-Acceleration","Particle-Drag",
                "Particle-Velocity","e-tilesize","p-accel","p-drag","p-offset","p-orbitvel",
                "p-postoffset","p-quadrot","p-rotvel","p-scale","p-vel","p-worldaccel",
                "p-xquadrot","p-xrgba-beam-bind-distance","p-xscale"
            }));

            // e-rotationN rand + axis
            for (int i = 0; i < ROT_VARS; i++)
            {
                fields.AddRange(RandFloat(new[] { $"e-rotation{i}" }));
                fields.Add($"e-rotation{i}-axis");
            }

            // field-accel-N .. field-orbit-N
            for (int i = 1; i < FIELD_VARS; i++)
            {
                fields.Add($"field-accel-{i}");
                fields.Add($"field-attract-{i}");
                fields.Add($"field-drag-{i}");
                fields.Add($"field-noise-{i}");
                fields.Add($"field-orbit-{i}");
            }

            fields.Add("fluid-params");

            return fields;
        }

        // ═══════════════════════════════════════════════════════════════════
        // Rand/Flex Expansion Helpers
        // ═══════════════════════════════════════════════════════════════════

        private static IEnumerable<string> RandFloat(IEnumerable<string> bases)
        {
            var fields = new List<string>();
            foreach (var b in bases)
            {
                fields.Add(b);
                for (int j = 0; j < RAND_VARS; j++)
                    fields.Add($"{b}{j}");
                fields.Add($"{b}XP");
                for (int j = 0; j < RAND_VARS; j++)
                    fields.Add($"{b}XP{j}");
                fields.Add($"{b}P");
                for (int j = 0; j < RAND_VARS; j++)
                    fields.Add($"{b}P{j}");
            }
            return fields;
        }

        private static IEnumerable<string> RandVec2(IEnumerable<string> bases)
        {
            var fields = new List<string>();
            foreach (var b in bases)
            {
                fields.Add(b);
                for (int j = 0; j < RAND_VARS; j++)
                    fields.Add($"{b}{j}");
                foreach (var ax in new[] { "X", "Y" })
                {
                    fields.Add($"{b}{ax}P");
                    for (int j = 0; j < RAND_VARS; j++)
                        fields.Add($"{b}{ax}P{j}");
                }
            }
            return fields;
        }

        private static IEnumerable<string> RandVec3(IEnumerable<string> bases)
        {
            var fields = new List<string>();
            foreach (var b in bases)
            {
                fields.Add(b);
                for (int j = 0; j < RAND_VARS; j++)
                    fields.Add($"{b}{j}");
                foreach (var ax in new[] { "X", "Y", "Z" })
                {
                    fields.Add($"{b}{ax}P");
                    for (int j = 0; j < RAND_VARS; j++)
                        fields.Add($"{b}{ax}P{j}");
                }
            }
            return fields;
        }

        private static IEnumerable<string> Flex(IEnumerable<string> bases)
        {
            var fields = new List<string>();
            foreach (var b in bases)
            {
                fields.Add(b);
                fields.Add($"{b}_flex");
                for (int j = 0; j < 4; j++)
                    fields.Add($"{b}_flex{j}");
            }
            return fields;
        }

        private static IEnumerable<string> FlexRandFloat(IEnumerable<string> bases) => RandFloat(Flex(bases));
        private static IEnumerable<string> FlexRandVec2(IEnumerable<string> bases) => RandVec2(Flex(bases));
        private static IEnumerable<string> FlexRandVec3(IEnumerable<string> bases) => RandVec3(Flex(bases));
    }
}
