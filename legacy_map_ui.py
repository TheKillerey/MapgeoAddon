"""Legacy Map import UI and operators.

Adds a dedicated "Legacy Map" panel for older League map layouts
(e.g. Season 3/4 style folders) and bridges them into the current
Mapgeo/material import pipeline.
"""

import math
from pathlib import Path
import bpy


def _safe_rglob(root: Path, pattern: str):
    try:
        return list(root.rglob(pattern))
    except Exception:
        return []


def _find_client_root_from_map_folder(map_folder: Path) -> Path:
    if map_folder.name.lower().startswith("map") and map_folder.parent.name.lower() == "levels":
        return map_folder.parent.parent
    return map_folder


def _pick_best_mapgeo(mapgeo_files, nvr_files=None):
    """Pick the best mapgeo file, skipping .nvr.mapgeo conversions when a real NVR exists."""
    if not mapgeo_files:
        return None

    # Filter out .nvr.mapgeo conversions when we have a real NVR
    has_real_nvr = bool(nvr_files)
    candidates = mapgeo_files
    if has_real_nvr:
        non_nvr_mapgeos = [f for f in mapgeo_files if '.nvr.mapgeo' not in f.name.lower()]
        if non_nvr_mapgeos:
            candidates = non_nvr_mapgeos
        else:
            # All mapgeos are .nvr.mapgeo conversions — skip mapgeo entirely, use NVR
            return None

    preferred_names = [
        "base_srx.mapgeo",
        "base.mapgeo",
        "map1_srx.mapgeo",
        "map1.mapgeo",
    ]

    lower_map = {f.name.lower(): f for f in candidates}
    for name in preferred_names:
        if name in lower_map:
            return lower_map[name]

    return sorted(candidates, key=lambda p: (len(str(p)), p.name.lower()))[0]


def _pick_best_materials(material_files, mapgeo_file):
    if not material_files:
        return None

    if mapgeo_file:
        base = mapgeo_file.stem.lower()
        for f in material_files:
            if f.stem.lower().startswith(base):
                return f

    return sorted(material_files, key=lambda p: (len(str(p)), p.name.lower()))[0]


def _build_legacy_report(map_folder: Path):
    mapgeo_files = _safe_rglob(map_folder, "*.mapgeo")
    material_files = _safe_rglob(map_folder, "*.materials.bin")
    nvr_files = _safe_rglob(map_folder, "*.nvr")
    mat_files = _safe_rglob(map_folder, "*.mat")
    dat_files = _safe_rglob(map_folder, "*.dat")

    report = {
        "mapgeo_files": mapgeo_files,
        "material_files": material_files,
        "nvr_files": nvr_files,
        "mat_files": mat_files,
        "dat_files": dat_files,
    }
    return report


def _write_text_report(name: str, lines):
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text.clear()
    text.write("\n".join(lines))


def _pick_best_nvr(nvr_files):
    if not nvr_files:
        return None

    preferred = ["room.nvr", "map.nvr", "base.nvr"]
    by_name = {f.name.lower(): f for f in nvr_files}
    for name in preferred:
        if name in by_name:
            return by_name[name]

    return sorted(nvr_files, key=lambda p: (len(str(p)), p.name.lower()))[0]


def _pick_best_light_dat(dat_files):
    """Find the best Light.dat / Lights.dat file."""
    if not dat_files:
        return None
    preferred = ["light.dat", "lights.dat", "lightdat.dat", "light_correct.dat"]
    by_name = {f.name.lower(): f for f in dat_files}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return None


def _pick_best_light_env(dat_files):
    """Find the best LightEnvironment / Light_Env .dat file."""
    if not dat_files:
        return None
    preferred = ["light_env.dat", "lightenvironment.dat", "light_env_fixed.dat"]
    by_name = {f.name.lower(): f for f in dat_files}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return None


def _pick_best_lightenv(dat_files):
    """Legacy compat: pick best light file (prefers Light_Env, falls back to Light.dat)."""
    env = _pick_best_light_env(dat_files)
    if env:
        return env
    return _pick_best_light_dat(dat_files)


def _pick_best_particles(dat_files):
    if not dat_files:
        return None
    preferred = ["particles.dat", "mapparticles.dat"]
    by_name = {f.name.lower(): f for f in dat_files}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return None


def _parse_legacy_light_dat(filepath: Path):
    """Parse Light.dat / Lights.dat — 7 fields per line:
    x y z r g b radius
    """
    lights = []
    with filepath.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    if not lines:
        return lights

    start_idx = 0
    if len(lines[0].split()) == 1 and lines[0].isdigit():
        start_idx = 1

    for ln in lines[start_idx:]:
        parts = ln.split()
        if len(parts) < 7:
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            r, g, b = int(parts[3]), int(parts[4]), int(parts[5])
            radius = float(parts[6])
        except Exception:
            continue

        lights.append(
            {
                "position": (x, z, y),
                "position_raw": (x, y, z),
                "color": (max(0, min(255, r)) / 255.0, max(0, min(255, g)) / 255.0, max(0, min(255, b)) / 255.0),
                "color_raw": (r, g, b),
                "radius": max(0.01, radius),
                "source": "Light.dat",
            }
        )
    return lights


def _parse_legacy_light_environment(filepath: Path):
    """Parse Light_Env.dat / LightEnvironment.dat — 13 fields per line:
    x y z  r1 g1 b1  r2 g2 b2  type  radius  flag  opacity

    Fields:
      0-2:  Position (x, y, z)
      3-5:  Primary/diffuse color (0-255)
      6-8:  Secondary/ambient color (0-255)
      9:    Type/flag (0 or 20)
      10:   Radius
      11:   Flag (typically 1)
      12:   Opacity/intensity (float)
    """
    lights = []
    with filepath.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    if not lines:
        return lights

    # First line is version/count if single number
    start_idx = 0
    if len(lines[0].split()) == 1:
        start_idx = 1

    for ln in lines[start_idx:]:
        parts = ln.split()
        if len(parts) < 7:
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            r, g, b = int(parts[3]), int(parts[4]), int(parts[5])

            # Secondary color (fields 6-8)
            r2, g2, b2 = 0, 0, 0
            if len(parts) >= 9:
                r2, g2, b2 = int(parts[6]), int(parts[7]), int(parts[8])

            # Type/flag (field 9)
            light_type = 0
            if len(parts) >= 10:
                light_type = int(parts[9])

            # Radius (field 10)
            radius = 1.0
            if len(parts) >= 11:
                radius = float(parts[10])

            # Flag (field 11)
            flag = 1
            if len(parts) >= 12:
                flag = int(parts[11])

            # Opacity (field 12)
            opacity = 1.0
            if len(parts) >= 13:
                opacity = float(parts[12])
        except Exception:
            continue

        lights.append(
            {
                "position": (x, z, y),
                "position_raw": (x, y, z),
                "color": (max(0, min(255, r)) / 255.0, max(0, min(255, g)) / 255.0, max(0, min(255, b)) / 255.0),
                "color_raw": (r, g, b),
                "color2": (max(0, min(255, r2)) / 255.0, max(0, min(255, g2)) / 255.0, max(0, min(255, b2)) / 255.0),
                "color2_raw": (r2, g2, b2),
                "light_type": light_type,
                "radius": max(0.01, radius),
                "flag": flag,
                "opacity": max(0.0, opacity),
                "source": "Light_Env.dat",
            }
        )
    return lights


def _parse_legacy_particles_dat(filepath: Path):
    particles = []
    with filepath.open("r", encoding="utf-8", errors="ignore") as f:
        for ln in f:
            line = ln.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                name = parts[0]
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                rx, ry, rz = float(parts[5]), float(parts[6]), float(parts[7])
            except Exception:
                continue

            particles.append(
                {
                    "name": name,
                    "position": (x, z, y),
                    "rotation": (rx, rz, ry),
                    "raw": line,
                }
            )
    return particles


# ---------------------------------------------------------------------------
# sun.ini parsing — very old League versions (pre-inibin)
# ---------------------------------------------------------------------------

def _parse_sun_ini(filepath: Path) -> dict | None:
    """Parse a legacy sun.ini file.

    Format (line by line):
      Line 0: <sun_texture> <glow_texture>
      SunColor1 R G B          (sky gradient colour band 1, 0-255)
      SunColor2 R G B
      ...
      SunColor5 R G B
      SkyColor1 R G B
      SkyColor2 R G B
      SunImageColor R G B      (colour of the sun disc sprite)
      GlowColor R G B
      SunSize  <int>
      GlowSize <int>
      Position <azimuth_0_255> <elevation_degrees>
      InitialTime <int>        (optional)
    """
    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"[Sun.ini] Failed to read {filepath}: {e}")
        return None

    props: dict = {"source": str(filepath)}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]

        # Colour keys: Key R G B
        if key.startswith(("SunColor", "SkyColor", "SunImageColor", "GlowColor")) and len(parts) >= 4:
            try:
                props[key] = (int(parts[1]), int(parts[2]), int(parts[3]))
            except ValueError:
                pass
        elif key == "Position" and len(parts) >= 3:
            try:
                props["Position_Azimuth"] = int(parts[1])
                props["Position_Elevation"] = int(parts[2])
            except ValueError:
                pass
        elif key == "SunSize" and len(parts) >= 2:
            try:
                props["SunSize"] = int(parts[1])
            except ValueError:
                pass
        elif key == "GlowSize" and len(parts) >= 2:
            try:
                props["GlowSize"] = int(parts[1])
            except ValueError:
                pass
        elif key == "InitialTime" and len(parts) >= 2:
            try:
                props["InitialTime"] = int(parts[1])
            except ValueError:
                pass

    # First line is texture filenames (if it doesn't match a known key)
    if lines and not lines[0].strip().split()[0].startswith((
            "SunColor", "SkyColor", "GlowColor", "SunImageColor",
            "Position", "SunSize", "GlowSize", "InitialTime")):
        tex_parts = lines[0].strip().split()
        if tex_parts:
            props["SunTexture"] = tex_parts[0]
        if len(tex_parts) >= 2:
            props["GlowTexture"] = tex_parts[1]

    return props if len(props) > 1 else None


def _create_sun_light_from_sun_ini(sun_props: dict, collection=None):
    """Create a Blender SUN light from parsed sun.ini properties."""
    # Use SunColor1 as the primary sun colour (brightest sky band)
    sun_color_raw = sun_props.get("SunColor1", sun_props.get("SunImageColor"))
    sky_color_raw = sun_props.get("SkyColor1")

    if isinstance(sun_color_raw, (list, tuple)) and len(sun_color_raw) >= 3:
        sun_color = (sun_color_raw[0] / 255.0, sun_color_raw[1] / 255.0, sun_color_raw[2] / 255.0)
    else:
        sun_color = (1.0, 1.0, 1.0)

    light_data = bpy.data.lights.new(name="LegacySun", type='SUN')
    light_data.energy = 5.0
    light_data.color = sun_color

    light_obj = bpy.data.objects.new(name="LegacySun", object_data=light_data)

    # Convert Position (azimuth 0-255, elevation degrees) to Blender rotation
    azimuth_raw = sun_props.get("Position_Azimuth", 0)
    elevation_raw = sun_props.get("Position_Elevation", 35)
    # Azimuth: 0-255 maps to 0-2*pi
    azimuth_rad = (azimuth_raw / 255.0) * 2.0 * math.pi
    # Elevation: degrees from horizon
    elevation_rad = math.radians(max(0, min(90, elevation_raw)))
    light_obj.rotation_euler = (elevation_rad, 0.0, azimuth_rad)
    light_obj.location = (0, 0, 500)

    target_collection = collection or bpy.context.collection
    target_collection.objects.link(light_obj)

    # Custom properties
    light_obj["mapgeo_light"] = True
    light_obj["light_category"] = "sun_ini"
    light_obj["terrain_source"] = "sun.ini"

    for k, v in sun_props.items():
        prop_key = f"sunini_{k}"
        if isinstance(v, tuple):
            light_obj[prop_key] = list(v)
        elif isinstance(v, (int, float, bool, str)):
            light_obj[prop_key] = v

    # Set world ambient from SkyColor1 if available
    if isinstance(sky_color_raw, (list, tuple)) and len(sky_color_raw) >= 3:
        world = bpy.context.scene.world
        if world is None:
            world = bpy.data.worlds.new("LegacyWorld")
            bpy.context.scene.world = world
        world.use_nodes = True
        bg_node = world.node_tree.nodes.get("Background")
        if bg_node:
            bg_node.inputs["Color"].default_value = (
                sky_color_raw[0] / 255.0,
                sky_color_raw[1] / 255.0,
                sky_color_raw[2] / 255.0,
                1.0,
            )
            bg_node.inputs["Strength"].default_value = 0.3

    print(f"[Sun.ini] Created SUN light: color={sun_color}, azimuth={azimuth_raw}, elev={elevation_raw}")
    return light_obj


# ---------------------------------------------------------------------------
# Terrain.inibin parsing — Sun / Fog / Ambient
# ---------------------------------------------------------------------------

# Known terrain.inibin SDBM hashes (section*property, lowercased)
_TERRAIN_HASH_MAP = {
    0x89ee8f7f: "Sun_SunDir",              # Vec3 direction
    0x7b9e28db: "Sun_SunlightColor",       # Vec3 or String (0-255 RGB)
    0xcd506187: "Sun_AmbientLightColor",   # Vec3 (0-255 RGB)
    0x44993440: "Sun_SecondaryDir",         # Vec3 direction (unverified label)
    0x90a985da: "Sun_SkyColor",            # Vec3 (0-255 RGB, unverified)
    0x91f25f86: "Sun_ShadowColor",         # Vec3 (0-255 RGB, unverified)
    0x100ec247: "Sun_FogEnd",              # String-encoded float
    0x1016c435: "Sun_FogStart",            # String-encoded float
    0xdb014fe6: "Sun_Unknown_0xdb014fe6",  # String "0"
    0xf4a5de1f: "Fog_Opacity",             # String-encoded float
    0xb55ad83f: "Sun_Enabled",             # Bool
    0x2a124bf1: "Sun_Type",                # Int8
    0xeacfa008: "Sun_Flag",                # Int8 or Bool
}


def _parse_terrain_inibin(filepath: Path) -> dict | None:
    """Parse terrain.inibin and return a dict of sun/fog/ambient properties.

    Returns None if parsing fails.
    """
    try:
        from . import cfgbin_reader
    except ImportError:
        try:
            import cfgbin_reader
        except ImportError:
            print("[Terrain] cfgbin_reader not available")
            return None

    try:
        result = cfgbin_reader.parse_cfgbin(filepath)
    except Exception as e:
        print(f"[Terrain] Failed to parse {filepath.name}: {e}")
        return None

    props = {}
    for set_name, entries in result["sets"].items():
        for hash_val, value in entries:
            name = _TERRAIN_HASH_MAP.get(hash_val, f"Unknown_0x{hash_val:08x}")
            props[name] = value

    # Normalise SunlightColor — may be a stringified "R G B" or a Vec3 list
    sc = props.get("Sun_SunlightColor")
    if isinstance(sc, str):
        try:
            parts = sc.split()
            props["Sun_SunlightColor"] = [float(p) for p in parts[:3]]
        except Exception:
            pass

    return props


def _vec3_to_sun_rotation(direction):
    """Convert a League sun direction vector to a Blender euler rotation.

    League direction (x, y, z) → Blender (x, z, y) (Y-up → Z-up).
    The Blender SUN lamp shines along its local -Z axis.
    """
    dx, dy, dz = direction[0], direction[2], direction[1]  # swap Y/Z
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-6:
        return (0, 0, 0)
    dx /= length
    dy /= length
    dz /= length
    # Elevation (rotation around X) — angle from XY plane
    elevation = math.asin(max(-1.0, min(1.0, -dz)))
    # Azimuth (rotation around Z)
    azimuth = math.atan2(dx, dy)
    return (elevation, 0.0, azimuth)


def _create_sun_light_from_inibin(terrain_props: dict, collection=None):
    """Create a Blender SUN light from parsed terrain.inibin properties."""
    sun_dir = terrain_props.get("Sun_SunDir")
    sun_color_raw = terrain_props.get("Sun_SunlightColor")
    ambient_color_raw = terrain_props.get("Sun_AmbientLightColor")

    # Sun color (0-255 → 0-1)
    if isinstance(sun_color_raw, (list, tuple)) and len(sun_color_raw) >= 3:
        sun_color = (sun_color_raw[0] / 255.0, sun_color_raw[1] / 255.0, sun_color_raw[2] / 255.0)
    else:
        sun_color = (1.0, 1.0, 1.0)

    # Create sun light
    light_data = bpy.data.lights.new(name="LegacySun", type='SUN')
    light_data.energy = 5.0
    light_data.color = sun_color

    light_obj = bpy.data.objects.new(name="LegacySun", object_data=light_data)
    if sun_dir and isinstance(sun_dir, (list, tuple)) and len(sun_dir) >= 3:
        light_obj.rotation_euler = _vec3_to_sun_rotation(sun_dir)
    light_obj.location = (0, 0, 500)  # Place high above

    target_collection = collection or bpy.context.collection
    target_collection.objects.link(light_obj)

    # Custom properties — store everything from terrain.inibin
    light_obj["mapgeo_light"] = True
    light_obj["light_category"] = "terrain_inibin_sun"
    light_obj["terrain_source"] = "terrain.inibin"

    if sun_dir:
        light_obj["sun_dir_raw"] = list(sun_dir)
    if sun_color_raw:
        light_obj["sun_color_raw"] = list(sun_color_raw) if isinstance(sun_color_raw, (list, tuple)) else str(sun_color_raw)
    if ambient_color_raw:
        light_obj["ambient_color_raw"] = list(ambient_color_raw)

    # Store all terrain properties as custom props
    for k, v in terrain_props.items():
        prop_key = f"terrain_{k}"
        if isinstance(v, (list, tuple)):
            light_obj[prop_key] = list(v)
        elif isinstance(v, (int, float, bool, str)):
            light_obj[prop_key] = v

    # Also create an ambient world light hint if we have ambient color
    if isinstance(ambient_color_raw, (list, tuple)) and len(ambient_color_raw) >= 3:
        world = bpy.context.scene.world
        if world is None:
            world = bpy.data.worlds.new("LegacyWorld")
            bpy.context.scene.world = world
        world.use_nodes = True
        bg_node = world.node_tree.nodes.get("Background")
        if bg_node:
            bg_node.inputs["Color"].default_value = (
                ambient_color_raw[0] / 255.0,
                ambient_color_raw[1] / 255.0,
                ambient_color_raw[2] / 255.0,
                1.0,
            )
            bg_node.inputs["Strength"].default_value = 0.3

    # Store fog settings as scene custom properties
    scene = bpy.context.scene
    for key in ("Sun_FogStart", "Sun_FogEnd", "Fog_Opacity"):
        val = terrain_props.get(key)
        if val is not None:
            try:
                scene[f"legacy_{key.lower()}"] = float(val) if isinstance(val, str) else val
            except (ValueError, TypeError):
                scene[f"legacy_{key.lower()}"] = str(val)

    print(f"[Terrain] Created SUN light: color={sun_color}, dir={sun_dir}")
    return light_obj


def _create_legacy_light(light_name: str, position, color, energy: float, radius: float,
                         extra_props: dict | None = None):
    light_data = bpy.data.lights.new(name=light_name, type='POINT')
    light_data.energy = energy
    light_data.color = color
    light_data.shadow_soft_size = radius

    # Exposure for point lights
    if hasattr(light_data, 'exposure'):
        light_data.exposure = 10.0

    # EEVEE custom distance — use League radius as cutoff
    # League/Unity-style range maps directly to EEVEE cutoff_distance
    league_radius = radius
    if extra_props and "radius" in extra_props:
        league_radius = extra_props["radius"]
    if hasattr(light_data, 'use_custom_distance'):
        light_data.use_custom_distance = True
        light_data.cutoff_distance = max(1.0, league_radius)

    light_obj = bpy.data.objects.new(name=light_name, object_data=light_data)
    light_obj.location = position
    bpy.context.collection.objects.link(light_obj)
    light_obj["mapgeo_light"] = True
    light_obj["light_category"] = "legacy_dat"

    # Store all original data as custom properties
    if extra_props:
        for k, v in extra_props.items():
            if isinstance(v, tuple):
                light_obj[k] = list(v)
            else:
                light_obj[k] = v

    return light_obj


class MAPGEO_OT_scan_legacy_map(bpy.types.Operator):
    """Scan legacy map folders for importable sources"""

    bl_idname = "mapgeo.scan_legacy_map"
    bl_label = "Scan Legacy Sources"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        report = _build_legacy_report(map_folder)
        lines = [
            "Legacy Map Scan Report",
            f"Folder: {map_folder}",
            "",
            f".mapgeo: {len(report['mapgeo_files'])}",
            f".materials(.py/.bin): {len(report['material_files'])}",
            f".nvr: {len(report['nvr_files'])}",
            f".mat: {len(report['mat_files'])}",
            f".dat: {len(report['dat_files'])}",
            "",
            "Detected legacy files (first 100):",
        ]

        detected = (
            report['mapgeo_files'] + report['material_files'] +
            report['nvr_files'] + report['mat_files'] + report['dat_files']
        )
        for f in detected[:100]:
            lines.append(str(f))

        _write_text_report("legacy_map_scan_report", lines)
        self.report(
            {'INFO'},
            f"Scan complete: {len(report['mapgeo_files'])} mapgeo, {len(report['material_files'])} materials, {len(report['dat_files'])} dat"
        )
        return {'FINISHED'}


class MAPGEO_OT_import_legacy_map_bundle(bpy.types.Operator):
    """Import a legacy map bundle (map + materials + texture paths)"""

    bl_idname = "mapgeo.import_legacy_map_bundle"
    bl_label = "Import Legacy Map Bundle"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        report = _build_legacy_report(map_folder)
        nvr_file = _pick_best_nvr(report["nvr_files"])
        mapgeo_file = _pick_best_mapgeo(report["mapgeo_files"], report["nvr_files"])
        materials_file = _pick_best_materials(report["material_files"], mapgeo_file)

        client_root = _find_client_root_from_map_folder(map_folder)
        assets_folder = client_root / "DATA" / "FINAL" / "ASSETS"
        if assets_folder.exists() and assets_folder.is_dir():
            settings.assets_folder = str(assets_folder)

        if map_folder.parent.name.lower() == "levels":
            settings.levels_folder = str(map_folder.parent)

        if materials_file:
            settings.materials_file_path = str(materials_file)

        imported_map = False
        imported_materials = 0

        # NVR = legacy map format; always prefer it over mapgeo when present
        if nvr_file:
            try:
                from . import legacy_nvr_import
                nvr_result = legacy_nvr_import.import_nvr(str(nvr_file), collection_name="Legacy_NVR")
                imported_map = nvr_result.get("imported_objects", 0) > 0
                # Set viewport clipping for large maps
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            if space.type == 'VIEW_3D':
                                space.clip_start = 10
                                space.clip_end = 10000000
            except Exception as exc:
                self.report({'WARNING'}, f"Native NVR import failed: {exc}")

        if (not imported_map) and mapgeo_file:
            result = bpy.ops.import_scene.mapgeo(
                'EXEC_DEFAULT',
                filepath=str(mapgeo_file),
                import_materials=settings.import_materials,
                import_vertex_colors=settings.import_vertex_colors,
                import_normals=settings.import_normals,
                import_lightmaps=settings.import_lightmaps,
                import_bucket_grid=settings.import_bucket_grid,
                import_particles=True,
                merge_by_layer=False,
                scale_factor=1.0,
            )
            imported_map = 'FINISHED' in result

        if settings.legacy_import_materials and materials_file:
            try:
                from . import import_materials_blender
                mats = import_materials_blender.import_materials_from_file(
                    str(materials_file),
                    create_textures=settings.legacy_import_textures,
                )
                imported_materials = len(mats)
            except Exception as exc:
                self.report({'WARNING'}, f"Materials import failed: {exc}")

        if settings.legacy_collect_dat_report:
            lines = [
                "Legacy DAT/NVR/MAT report",
                f"Folder: {map_folder}",
                "",
                f"NVR files: {len(report['nvr_files'])}",
                f"MAT files: {len(report['mat_files'])}",
                f"DAT files: {len(report['dat_files'])}",
                "",
                "Note: DAT/NVR/MAT parsing is staged via LeagueToolkit conversion.",
            ]
            for f in (report['nvr_files'] + report['mat_files'] + report['dat_files'])[:200]:
                lines.append(str(f))
            _write_text_report("legacy_map_dat_report", lines)

        if settings.legacy_import_legacy_lights:
            # Import both Light.dat and Light_Env.dat if available
            light_dat_path = _pick_best_light_dat(report["dat_files"])
            light_env_path = _pick_best_light_env(report["dat_files"])

            if light_env_path:
                light_entries = _parse_legacy_light_environment(light_env_path)
                for idx, light in enumerate(light_entries):
                    opacity = light.get("opacity", 1.0)
                    radius = light.get("radius", 1.0)
                    _create_legacy_light(
                        f"LegacyLightEnv_{idx:04d}",
                        light["position"],
                        light["color"],
                        max(10.0, 1200.0 * max(0.0, opacity)),
                        max(0.1, radius * 0.02),
                        extra_props=light,
                    )
            elif light_dat_path:
                light_entries = _parse_legacy_light_dat(light_dat_path)
                for idx, light in enumerate(light_entries):
                    radius = max(0.1, light.get("radius", 1.0))
                    _create_legacy_light(
                        f"LegacyLight_{idx:04d}",
                        light["position"],
                        light["color"],
                        max(10.0, radius * 100.0),
                        max(0.1, radius * 0.02),
                        extra_props=light,
                    )

        # Import terrain.inibin sun/fog/ambient (fallback: sun.ini)
        if settings.legacy_import_terrain_inibin:
            inibin_candidates = []
            for f in _safe_rglob(map_folder, "*.inibin"):
                if f.name.lower() == "terrain.inibin":
                    inibin_candidates.append(f)

            sun_created = False
            if inibin_candidates:
                terrain_props = _parse_terrain_inibin(inibin_candidates[0])
                if terrain_props:
                    _create_sun_light_from_inibin(terrain_props)
                    self.report({'INFO'}, f"Created sun light from {inibin_candidates[0].name}")
                    sun_created = True

            # Fallback: look for sun.ini (very old League versions)
            if not sun_created:
                sun_ini_candidates = []
                for f in _safe_rglob(map_folder, "*.ini"):
                    if f.name.lower() == "sun.ini":
                        sun_ini_candidates.append(f)
                if sun_ini_candidates:
                    sun_props = _parse_sun_ini(sun_ini_candidates[0])
                    if sun_props:
                        _create_sun_light_from_sun_ini(sun_props)
                        self.report({'INFO'}, f"Created sun light from {sun_ini_candidates[0].name}")
                        sun_created = True

        if settings.legacy_import_legacy_particles:
            particles_path = _pick_best_particles(report["dat_files"])
            if particles_path:
                particles = _parse_legacy_particles_dat(particles_path)
                if particles:
                    collection_name = "LegacyParticles_DAT"
                    collection = bpy.data.collections.get(collection_name)
                    if collection is None:
                        collection = bpy.data.collections.new(collection_name)
                        context.scene.collection.children.link(collection)

                    for idx, item in enumerate(particles):
                        name = f"LP_{idx:04d}_{item['name']}"
                        obj = bpy.data.objects.new(name, None)
                        obj.empty_display_type = 'SPHERE'
                        obj.empty_display_size = 0.35
                        obj.location = item["position"]
                        obj.rotation_euler = item["rotation"]
                        obj["is_particle_system"] = True
                        obj["particle_source"] = "legacy_particles_dat"
                        obj["legacy_particle_line"] = item["raw"]
                        collection.objects.link(obj)

        if not imported_map and imported_materials == 0:
            self.report({'WARNING'}, "No mapgeo imported and no materials imported")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Legacy import done: map={'yes' if imported_map else 'no'}, materials={imported_materials}, dat={len(report['dat_files'])}"
        )
        return {'FINISHED'}


class VIEW3D_PT_mapgeo_legacy_panel(bpy.types.Panel):
    """Legacy map import panel"""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Mapgeo'
    bl_label = "Legacy Map"
    bl_parent_id = "VIEW3D_PT_mapgeo_panel"
    bl_order = 11
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.mapgeo_settings

        box = layout.box()
        box.label(text="Legacy Source", icon='FILE_FOLDER')
        col = box.column(align=True)
        col.prop(settings, "legacy_map_folder", text="LEVELS/Map Folder")

        options_box = layout.box()
        options_box.label(text="Import Options", icon='PREFERENCES')
        options_col = options_box.column(align=True)
        options_col.prop(settings, "legacy_import_materials", text="Import Materials")
        options_col.prop(settings, "legacy_import_textures", text="Load Textures")
        options_col.prop(settings, "legacy_collect_dat_report", text="Collect DAT/NVR/MAT Report")
        options_col.prop(settings, "legacy_import_legacy_lights", text="Import Legacy Lights (.dat)")
        options_col.prop(settings, "legacy_import_legacy_particles", text="Import Legacy Particles (.dat)")
        options_col.prop(settings, "legacy_import_terrain_inibin", text="Import terrain.inibin (Sun/Fog)")

        toolkit_box = layout.box()
        toolkit_box.label(text="NVR Native Import", icon='MESH_DATA')
        tk_col = toolkit_box.column(align=True)
        tk_col.label(text="Uses built-in SimpleEnvironment parser", icon='CHECKMARK')
        tk_col.label(text="No external conversion commands", icon='INFO')

        actions = layout.box()
        actions.label(text="Actions", icon='TOOL_SETTINGS')
        action_col = actions.column(align=True)
        action_col.operator("mapgeo.scan_legacy_map", text="Scan Legacy Sources", icon='VIEWZOOM')
        action_col.operator("mapgeo.import_legacy_map_bundle", text="Import Full Legacy Map", icon='IMPORT')
        action_col.operator("mapgeo.import_legacy_nvr", text="Import NVR (Native)", icon='MESH_CUBE')

        dat_actions = layout.box()
        dat_actions.label(text="Legacy DAT Import", icon='LIGHT')
        dat_col = dat_actions.column(align=True)
        dat_col.operator("mapgeo.import_legacy_lightdat", text="Import LightDat/Lights.dat", icon='LIGHT_POINT')
        dat_col.operator("mapgeo.import_legacy_lightenv", text="Import LightEnvironment.dat", icon='LIGHT_SUN')
        dat_col.operator("mapgeo.import_legacy_particles_dat", text="Import Particles.dat", icon='PARTICLES')

        help_box = layout.box()
        help_box.label(text="Supports: mapgeo + materials + textures", icon='INFO')
        help_box.label(text="Also imports legacy: lights/particles DAT")


class MAPGEO_OT_import_legacy_lightdat(bpy.types.Operator):
    """Import legacy LightDat/Lights.dat point lights"""

    bl_idname = "mapgeo.import_legacy_lightdat"
    bl_label = "Import Legacy LightDat"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        dat_files = _safe_rglob(map_folder, "*.dat")
        target = _pick_best_lightenv(dat_files)
        if not target:
            self.report({'WARNING'}, "No LightDat/LightEnvironment .dat found")
            return {'CANCELLED'}

        is_env = target.name.lower() in ("light_env.dat", "lightenvironment.dat", "light_env_fixed.dat")
        if is_env:
            entries = _parse_legacy_light_environment(target)
            created = 0
            for idx, light in enumerate(entries):
                opacity = light.get("opacity", 1.0)
                radius = light.get("radius", 1.0)
                energy = max(10.0, 1200.0 * opacity)
                _create_legacy_light(
                    f"LegacyLightEnv_{idx:04d}",
                    light["position"],
                    light["color"],
                    energy,
                    max(0.1, radius * 0.02),
                    extra_props=light,
                )
                created += 1
        else:
            entries = _parse_legacy_light_dat(target)
            created = 0
            for idx, light in enumerate(entries):
                radius = light.get("radius", 1.0)
                energy = max(10.0, radius * 100.0)
                _create_legacy_light(
                    f"LegacyLight_{idx:04d}",
                    light["position"],
                    light["color"],
                    energy,
                    max(0.1, radius * 0.02),
                    extra_props=light,
                )
                created += 1

        self.report({'INFO'}, f"Imported {created} legacy lights from {target.name}")
        return {'FINISHED'}


class MAPGEO_OT_import_legacy_lightenv(bpy.types.Operator):
    """Import legacy LightEnvironment.dat lights"""

    bl_idname = "mapgeo.import_legacy_lightenv"
    bl_label = "Import Legacy LightEnvironment"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        target = _pick_best_light_env(_safe_rglob(map_folder, "*.dat"))

        if not target:
            self.report({'WARNING'}, "No Light_Env/LightEnvironment .dat found")
            return {'CANCELLED'}

        entries = _parse_legacy_light_environment(target)
        created = 0
        for idx, light in enumerate(entries):
            opacity = light.get("opacity", 1.0)
            radius = light.get("radius", 1.0)
            _create_legacy_light(
                f"LegacyLightEnv_{idx:04d}",
                light["position"],
                light["color"],
                max(10.0, 1200.0 * opacity),
                max(0.1, radius * 0.02),
                extra_props=light,
            )
            created += 1

        self.report({'INFO'}, f"Imported {created} lights from {target.name}")
        return {'FINISHED'}


class MAPGEO_OT_import_legacy_particles_dat(bpy.types.Operator):
    """Import legacy particles.dat as empties"""

    bl_idname = "mapgeo.import_legacy_particles_dat"
    bl_label = "Import Legacy Particles.dat"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        target = None
        for f in _safe_rglob(map_folder, "*.dat"):
            if f.name.lower() in {"particles.dat", "mapparticles.dat"}:
                target = f
                break

        if not target:
            self.report({'WARNING'}, "No particles.dat found")
            return {'CANCELLED'}

        particles = _parse_legacy_particles_dat(target)
        if not particles:
            self.report({'WARNING'}, "No particles parsed from file")
            return {'CANCELLED'}

        collection_name = "LegacyParticles_DAT"
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(collection)

        for idx, item in enumerate(particles):
            name = f"LP_{idx:04d}_{item['name']}"
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_type = 'SPHERE'
            obj.empty_display_size = 0.35
            obj.location = item["position"]
            obj.rotation_euler = item["rotation"]
            obj["is_particle_system"] = True
            obj["particle_source"] = "legacy_particles_dat"
            obj["legacy_particle_line"] = item["raw"]
            collection.objects.link(obj)

        self.report({'INFO'}, f"Imported {len(particles)} particles from {target.name}")
        return {'FINISHED'}


class MAPGEO_OT_import_legacy_nvr(bpy.types.Operator):
    """Import legacy NVR (SimpleEnvironment) directly"""

    bl_idname = "mapgeo.import_legacy_nvr"
    bl_label = "Import Legacy NVR"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.mapgeo_settings
        map_folder = Path(settings.legacy_map_folder).expanduser()
        if not map_folder.exists() or not map_folder.is_dir():
            self.report({'ERROR'}, "Legacy map folder is invalid")
            return {'CANCELLED'}

        nvr_files = _safe_rglob(map_folder, "*.nvr")
        nvr_file = _pick_best_nvr(nvr_files)
        if not nvr_file:
            self.report({'WARNING'}, "No .nvr file found")
            return {'CANCELLED'}

        try:
            from . import legacy_nvr_import
            result = legacy_nvr_import.import_nvr(str(nvr_file), collection_name="Legacy_NVR")
        except Exception as exc:
            self.report({'ERROR'}, f"NVR import failed: {exc}")
            return {'CANCELLED'}

        # Set viewport clipping for large maps
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.clip_start = 10
                        space.clip_end = 10000000

        self.report(
            {'INFO'},
            f"Imported NVR: {result.get('decoded_meshes', 0)} mesh defs → {result.get('imported_objects', 0)} objects, "
            f"materials={result.get('materials', 0)}, skipped={result.get('skipped', 0)}"
        )
        return {'FINISHED'}


classes = (
    MAPGEO_OT_scan_legacy_map,
    MAPGEO_OT_import_legacy_map_bundle,
    MAPGEO_OT_import_legacy_nvr,
    MAPGEO_OT_import_legacy_lightdat,
    MAPGEO_OT_import_legacy_lightenv,
    MAPGEO_OT_import_legacy_particles_dat,
    VIEW3D_PT_mapgeo_legacy_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
