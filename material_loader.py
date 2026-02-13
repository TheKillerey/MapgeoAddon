"""
Material Loader for Mapgeo Addon
Loads materials from .materials.bin.json or .materials.py files and creates Blender materials
"""

import json
import math
import os
import re
import bpy
from typing import Dict, Optional
from .texture_utils import TexConverter, resolve_texture_path


class MaterialLoader:
    """Loads and creates Blender materials from League materials JSON or Python format"""
    
    def __init__(self, assets_folder: str = "", levels_folder: str = "",
                 map_py_path: str = "", dragon_layer: str = "LAYER_1"):
        self.assets_folder = assets_folder
        self.levels_folder = levels_folder
        self.map_py_path = map_py_path
        self.dragon_layer = dragon_layer  # e.g. 'LAYER_1' (base), 'LAYER_2' (Inferno), etc.
        self.tex_converter = TexConverter()
        self.materials_cache = {}  # Cache loaded materials
        self._grass_tint_cache = None  # Cache parsed grass tint info
    
    def load_materials(self, file_path: str) -> Dict[str, dict]:
        """
        Load materials from a .materials.bin.json or .materials.py file.
        Auto-detects format based on file extension.
        
        Returns:
            Dictionary of material_name -> material_data
        """
        self._materials_path = file_path  # Store for grass tint chain
        if file_path.endswith('.py'):
            return self._load_materials_py(file_path)
        else:
            return self._load_materials_json(file_path)
    
    def load_materials_from_json(self, json_path: str) -> Dict[str, dict]:
        """Legacy method - calls load_materials for backwards compatibility"""
        return self.load_materials(json_path)
    
    def load_map_settings(self, file_path: str) -> dict:
        """
        Load map-level settings (sun, lightmap, bake properties) from materials file.
        
        Returns:
            Dictionary with keys: sun_color, sun_direction, sky_light_color,
            horizon_color, ground_color, sky_light_scale, lightmap_color_scale,
            fog_color, fog_start_end, lightmap_path, etc.
        """
        if file_path.endswith('.py'):
            return self._load_map_settings_py(file_path)
        else:
            return self._load_map_settings_json(file_path)
    
    def _load_map_settings_json(self, json_path: str) -> dict:
        """Parse map settings from JSON format"""
        settings = {}
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                # Look for mapContainer entries with components
                components = value.get('components', [])
                if not isinstance(components, list):
                    continue
                
                for comp in components:
                    if not isinstance(comp, dict):
                        continue
                    comp_type = comp.get('__type', '')
                    
                    if comp_type == 'MapSunProperties':
                        settings['sun_color'] = comp.get('sunColor', [1, 1, 1, 1])
                        settings['sun_direction'] = comp.get('sunDirection', [0, 1, 0])
                        settings['sky_light_color'] = comp.get('skyLightColor', [1, 1, 1, 1])
                        settings['horizon_color'] = comp.get('horizonColor', [1, 1, 1, 1])
                        settings['ground_color'] = comp.get('groundColor', [1, 1, 1, 1])
                        settings['sky_light_scale'] = comp.get('skyLightScale', 1.0)
                        settings['lightmap_color_scale'] = comp.get('lightMapColorScale', 1.0)
                        settings['fog_enabled'] = comp.get('fogEnabled', True)
                        settings['fog_color'] = comp.get('fogColor', [0, 0, 0, 1])
                        settings['fog_alternate_color'] = comp.get('fogAlternateColor', [0, 0, 0, 1])
                        settings['fog_start_end'] = comp.get('fogStartAndEnd', [0, -10000])
                        
                    elif comp_type == 'MapBakeProperties':
                        settings['light_grid_size'] = comp.get('lightGridSize', 256)
                        settings['light_grid_file'] = comp.get('lightGridFileName', '')
                        settings['rma_light_grid_texture'] = comp.get('RmaStaticLightGridTexturePath', '')
                        settings['rma_light_grid_intensity_scale'] = comp.get('RmaStaticLightGridIntensityScale', 1.0)
                        settings['light_grid_fullbright'] = comp.get('lightGridCharacterFullBrightIntensity', 0.5)
                        
                    elif comp_type == 'MapLightingV2':
                        settings['min_env_color_contribution'] = comp.get('MinimumEnvironmentColorContribution', 0.8)
            
            if settings:
                print(f"[MapSettings] Loaded map settings from {os.path.basename(json_path)}")
                if 'lightmap_color_scale' in settings:
                    print(f"  lightMapColorScale: {settings['lightmap_color_scale']}")
            return settings
        except Exception as e:
            print(f"[MapSettings] Error loading map settings from JSON: {e}")
            return {}
    
    def _load_map_settings_py(self, py_path: str) -> dict:
        """Parse map settings from Python format"""
        settings = {}
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find MapSunProperties block
            sun_match = re.search(r'MapSunProperties\s*\{', content)
            if sun_match:
                start = sun_match.end()
                brace_count = 1
                pos = start
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1
                body = content[start:pos-1]
                
                # Parse vec4 fields
                for field_name, key in [
                    ('sunColor', 'sun_color'),
                    ('skyLightColor', 'sky_light_color'),
                    ('horizonColor', 'horizon_color'),
                    ('groundColor', 'ground_color'),
                    ('fogColor', 'fog_color'),
                    ('fogAlternateColor', 'fog_alternate_color'),
                ]:
                    m = re.search(rf'{field_name}:\s*vec4\s*=\s*\{{\s*([^}}]+)\}}', body)
                    if m:
                        settings[key] = [float(v.strip()) for v in m.group(1).split(',')]
                
                # Parse vec3
                m = re.search(r'sunDirection:\s*vec3\s*=\s*\{\s*([^}]+)\}', body)
                if m:
                    settings['sun_direction'] = [float(v.strip()) for v in m.group(1).split(',')]
                
                # Parse vec2
                m = re.search(r'fogStartAndEnd:\s*vec2\s*=\s*\{\s*([^}]+)\}', body)
                if m:
                    settings['fog_start_end'] = [float(v.strip()) for v in m.group(1).split(',')]
                
                # Parse bool fields
                fog_enabled_match = re.search(r'fogEnabled:\s*bool\s*=\s*(true|false)', body)
                if fog_enabled_match:
                    settings['fog_enabled'] = fog_enabled_match.group(1) == 'true'
                else:
                    settings['fog_enabled'] = True  # Default to enabled
                
                # Parse f32 fields
                for field_name, key in [
                    ('skyLightScale', 'sky_light_scale'),
                    ('lightMapColorScale', 'lightmap_color_scale'),
                ]:
                    m = re.search(rf'{field_name}:\s*f32\s*=\s*([0-9.eE+-]+)', body)
                    if m:
                        settings[key] = float(m.group(1))
            
            # Find MapBakeProperties block
            bake_match = re.search(r'MapBakeProperties\s*\{', content)
            if bake_match:
                start = bake_match.end()
                brace_count = 1
                pos = start
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1
                body = content[start:pos-1]
                
                m = re.search(r'lightGridSize:\s*u32\s*=\s*(\d+)', body)
                if m:
                    settings['light_grid_size'] = int(m.group(1))
                
                m = re.search(r'lightGridFileName:\s*string\s*=\s*"([^"]+)"', body)
                if m:
                    settings['light_grid_file'] = m.group(1)
                
                m = re.search(r'RmaStaticLightGridTexturePath:\s*string\s*=\s*"([^"]+)"', body)
                if m:
                    settings['rma_light_grid_texture'] = m.group(1)
                
                m = re.search(r'RmaStaticLightGridIntensityScale:\s*f32\s*=\s*([0-9.eE+-]+)', body)
                if m:
                    settings['rma_light_grid_intensity_scale'] = float(m.group(1))
                
                m = re.search(r'lightGridCharacterFullBrightIntensity:\s*f32\s*=\s*([0-9.eE+-]+)', body)
                if m:
                    settings['light_grid_fullbright'] = float(m.group(1))
            
            # Find MapLightingV2 block
            lighting_match = re.search(r'MapLightingV2\s*\{', content)
            if lighting_match:
                start = lighting_match.end()
                brace_count = 1
                pos = start
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1
                body = content[start:pos-1]
                
                m = re.search(r'MinimumEnvironmentColorContribution:\s*f32\s*=\s*([0-9.eE+-]+)', body)
                if m:
                    settings['min_env_color_contribution'] = float(m.group(1))
            
            if settings:
                print(f"[MapSettings] Loaded map settings from {os.path.basename(py_path)}")
                if 'lightmap_color_scale' in settings:
                    print(f"  lightMapColorScale: {settings['lightmap_color_scale']}")
            return settings
        except Exception as e:
            print(f"[MapSettings] Error loading map settings from .py: {e}")
            return {}
    
    def _load_materials_json(self, json_path: str) -> Dict[str, dict]:
        """
        Load materials from a .materials.bin.json file
        
        Returns:
            Dictionary of material_name -> material_data (normalized with shader/blend/cull fields)
        """
        materials = {}
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Iterate through all entries and find StaticMaterialDef
            for key, value in data.items():
                if isinstance(value, dict) and value.get("__type") == "StaticMaterialDef":
                    # Normalize: extract shader/blend/cull from techniques into top-level keys
                    techniques = value.get('techniques', [])
                    if techniques and isinstance(techniques, list):
                        passes = techniques[0].get('passes', [])
                        if passes and isinstance(passes, list):
                            first_pass = passes[0]
                            value['shader'] = first_pass.get('shader', '')
                            value['blendEnable'] = first_pass.get('blendEnable', False)
                            value['cullEnable'] = first_pass.get('cullEnable', False)
                    
                    # Ensure defaults exist
                    value.setdefault('shader', '')
                    value.setdefault('blendEnable', False)
                    value.setdefault('cullEnable', False)
                    value.setdefault('switches', {})
                    value.setdefault('shaderMacros', {})
                    
                    # Normalize switches from list to dict if needed
                    switches_raw = value.get('switchValues', value.get('switches', {}))
                    if isinstance(switches_raw, list):
                        switches_dict = {}
                        for sw in switches_raw:
                            if isinstance(sw, dict):
                                sw_name = sw.get('name', '')
                                sw_on = sw.get('on', True)
                                if sw_name:
                                    switches_dict[sw_name] = sw_on
                        value['switches'] = switches_dict
                    
                    materials[key] = value
            
            print(f"Loaded {len(materials)} static materials from {os.path.basename(json_path)}")
            return materials
        
        except Exception as e:
            print(f"Error loading materials JSON: {e}")
            return {}
    
    def _load_materials_py(self, py_path: str) -> Dict[str, dict]:
        """
        Load materials from a .materials.py file.
        
        Parses Python format like:
            "Material/Path/Name" = StaticMaterialDef {
                name: string = "Material/Path/Name"
                samplerValues: list2[embed] = {
                    StaticMaterialShaderSamplerDef {
                        textureName: string = "DiffuseTexture"
                        texturePath: string = "ASSETS/path/to/texture.tex"
                    }
                }
                ...
            }
        
        Returns:
            Dictionary of material_name -> material_data (same format as JSON)
        """
        materials = {}
        
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all StaticMaterialDef blocks
            mat_pattern = re.compile(
                r'"([^"]+)"\s*=\s*StaticMaterialDef\s*\{',
                re.MULTILINE
            )
            
            for match in mat_pattern.finditer(content):
                mat_name = match.group(1)
                start_pos = match.end()
                
                # Find matching closing brace
                brace_count = 1
                pos = start_pos
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1
                
                body = content[start_pos:pos-1]
                
                # Parse into JSON-compatible dict
                mat_data = {
                    '__type': 'StaticMaterialDef',
                    'name': mat_name,
                    'samplerValues': [],
                    'paramValues': [],
                    'shaderMacros': {},
                    'switches': {},
                    'shader': '',
                    'blendEnable': False,
                    'cullEnable': False,
                }
                
                # Parse shader link from techniques
                shader_match = re.search(
                    r'shader:\s*link\s*=\s*"([^"]+)"', body
                )
                if shader_match:
                    mat_data['shader'] = shader_match.group(1)
                
                # Parse blend/cull state from techniques
                blend_enable = re.search(r'blendEnable:\s*bool\s*=\s*(true|false)', body)
                if blend_enable:
                    mat_data['blendEnable'] = blend_enable.group(1) == 'true'
                
                cull_enable = re.search(r'cullEnable:\s*bool\s*=\s*(true|false)', body)
                if cull_enable:
                    mat_data['cullEnable'] = cull_enable.group(1) == 'true'
                
                # Parse samplerValues (texture references)
                sampler_pattern = re.compile(
                    r'StaticMaterialShaderSamplerDef\s*\{([^}]+)\}',
                    re.DOTALL
                )
                for sampler_match in sampler_pattern.finditer(body):
                    sampler_body = sampler_match.group(1)
                    sampler = {}
                    
                    tex_name = re.search(r'textureName:\s*string\s*=\s*"([^"]+)"', sampler_body)
                    if tex_name:
                        sampler['TextureName'] = tex_name.group(1)
                        sampler['textureName'] = tex_name.group(1)
                    
                    tex_path = re.search(r'texturePath:\s*string\s*=\s*"([^"]+)"', sampler_body)
                    if tex_path:
                        sampler['texturePath'] = tex_path.group(1)
                    
                    # Parse address modes (0=Repeat/default, 1=Clamp)
                    addr_u = re.search(r'addressU:\s*u32\s*=\s*(\d+)', sampler_body)
                    if addr_u:
                        sampler['addressU'] = int(addr_u.group(1))
                    addr_v = re.search(r'addressV:\s*u32\s*=\s*(\d+)', sampler_body)
                    if addr_v:
                        sampler['addressV'] = int(addr_v.group(1))
                    
                    if sampler:
                        mat_data['samplerValues'].append(sampler)
                
                # Parse paramValues (shader parameters)
                param_pattern = re.compile(
                    r'StaticMaterialShaderParamDef\s*\{([^}]+)\}',
                    re.DOTALL
                )
                for param_match in param_pattern.finditer(body):
                    param_body = param_match.group(1)
                    param = {}
                    
                    param_name = re.search(r'name:\s*string\s*=\s*"([^"]+)"', param_body)
                    if param_name:
                        param['name'] = param_name.group(1)
                    
                    param_value = re.search(r'value:\s*vec4\s*=\s*\{\s*([^}]+)\}', param_body)
                    if param_value:
                        try:
                            values = [float(v.strip()) for v in param_value.group(1).split(',')]
                            param['value'] = values
                        except:
                            param['value'] = [1.0, 1.0, 1.0, 1.0]
                    
                    if param:
                        mat_data['paramValues'].append(param)
                
                # Parse shaderMacros
                macros_match = re.search(
                    r'shaderMacros:\s*map\[string,string\]\s*=\s*\{([^}]+)\}',
                    body
                )
                if macros_match:
                    macros_body = macros_match.group(1)
                    for macro_match in re.finditer(r'"([^"]+)"\s*=\s*"([^"]+)"', macros_body):
                        mat_data['shaderMacros'][macro_match.group(1)] = macro_match.group(2)
                
                # Parse switches (StaticMaterialSwitchDef)
                switch_pattern = re.compile(
                    r'StaticMaterialSwitchDef\s*\{([^}]+)\}',
                    re.DOTALL
                )
                for sw_match in switch_pattern.finditer(body):
                    sw_body = sw_match.group(1)
                    sw_name_m = re.search(r'name:\s*string\s*=\s*"([^"]+)"', sw_body)
                    if sw_name_m:
                        sw_on = True  # default ON if not specified
                        sw_on_m = re.search(r'on:\s*bool\s*=\s*(true|false)', sw_body)
                        if sw_on_m:
                            sw_on = sw_on_m.group(1) == 'true'
                        mat_data['switches'][sw_name_m.group(1)] = sw_on
                
                materials[mat_name] = mat_data
            
            print(f"Loaded {len(materials)} static materials from {os.path.basename(py_path)}")
            return materials
        
        except Exception as e:
            print(f"Error loading materials .py: {e}")
            return {}
    
    def _get_shader_short_name(self, mat_data: dict) -> str:
        """Extract short shader name from material data (e.g., 'DefaultEnv_Flat')"""
        shader_path = mat_data.get('shader', '')
        if shader_path:
            # "Shaders/StaticMesh/DefaultEnv_Flat" → "DefaultEnv_Flat"
            return shader_path.rsplit('/', 1)[-1]
        return ''
    
    def _get_param(self, mat_data: dict, name: str, default=None):
        """Get a shader parameter value by name"""
        for param in mat_data.get('paramValues', []):
            if param.get('name') == name:
                return param.get('value', default)
        return default
    
    def _get_sampler_path(self, mat_data: dict, name: str) -> str:
        """Get a texture sampler path by name (tries both 'DiffuseTexture' and 'Diffuse_Texture')"""
        for sampler in mat_data.get('samplerValues', []):
            tex_name = sampler.get('TextureName', sampler.get('textureName', ''))
            if tex_name == name:
                return sampler.get('texturePath', '')
        return ''
    
    def _get_sampler_data(self, mat_data: dict, name: str) -> dict:
        """Get full sampler dict by name, including address modes"""
        for sampler in mat_data.get('samplerValues', []):
            tex_name = sampler.get('TextureName', sampler.get('textureName', ''))
            if tex_name == name:
                return sampler
        return {}
    
    def _sampler_needs_clip(self, sampler: dict) -> bool:
        """Check if a sampler has addressU=1 and addressV=1 (Clamp mode)"""
        return sampler.get('addressU', 0) == 1 and sampler.get('addressV', 0) == 1
    
    def _find_grass_tint_texture(self) -> str:
        """
        Find grass tint texture using the map file chain:
        1. Parse mapContainer name from the materials file
        2. Parse map*.py to find MapSkin with matching mMapContainerLink
        3. Select base mGrassTintTexture or per-dragon mGrassTintTextureName
        4. Resolve the path via levels_folder (base) or assets_folder (per-dragon)
        
        Falls back to glob search if map file chain is not available.
        """
        # Use cached result if available
        if self._grass_tint_cache is not None:
            return self._grass_tint_cache
        
        result = self._find_grass_tint_from_map_file()
        if result:
            self._grass_tint_cache = result
            return result
        
        # Fallback: glob search in assets folder
        result = self._find_grass_tint_fallback()
        self._grass_tint_cache = result
        return result
    
    def _extract_map_container_name(self, materials_path: str) -> str:
        """
        Extract the mapContainer key from a materials file.
        
        In .py format: "Maps/MapGeometry/Map11/Sodapop_SRS" = mapContainer {
        In .json format: key with __type == "mapContainer"
        
        Returns the container key string or empty string.
        """
        try:
            if materials_path.endswith('.py'):
                with open(materials_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                m = re.search(r'"([^"]+)"\s*=\s*mapContainer\s*\{', content)
                if m:
                    return m.group(1)
            else:
                with open(materials_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for key, value in data.items():
                    if isinstance(value, dict) and value.get('__type') == 'mapContainer':
                        return key
        except Exception as e:
            print(f"[GrassTint] Error extracting mapContainer: {e}")
        return ''
    
    def _parse_map_file_grass_tints(self, map_file_path: str, container_name: str) -> dict:
        """
        Parse a map*.py file to find the MapSkin whose mMapContainerLink
        matches container_name, then extract grass tint texture paths.
        
        Returns dict:
            {
                'base': 'GrassTint_SRX.something.dds',  # filename only
                'alternates': {
                    'Fire': 'ASSETS/Maps/Info/Map11/GrassTint_SRX_Infernal.tex',
                    'earth': 'ASSETS/Maps/Info/Map11/GrassTint_SRX_Mountain.tex',
                    ...
                }
            }
        """
        result = {'base': '', 'alternates': {}}
        
        try:
            with open(map_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all MapSkin blocks and look for the one matching our container
            skin_pattern = re.compile(
                r'"([^"]+)"\s*=\s*MapSkin\s*\{',
                re.MULTILINE
            )
            
            for skin_match in skin_pattern.finditer(content):
                skin_start = skin_match.end()
                
                # Find matching closing brace for this MapSkin block
                brace_count = 1
                pos = skin_start
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1
                
                skin_body = content[skin_start:pos-1]
                
                # Check if mMapContainerLink matches
                link_match = re.search(r'mMapContainerLink:\s*string\s*=\s*"([^"]+)"', skin_body)
                if not link_match or link_match.group(1) != container_name:
                    continue
                
                skin_name = skin_match.group(1)
                print(f"[GrassTint] Found matching MapSkin: {skin_name}")
                
                # Extract base grass tint texture
                base_match = re.search(r'mGrassTintTexture:\s*string\s*=\s*"([^"]+)"', skin_body)
                if base_match:
                    result['base'] = base_match.group(1)
                    print(f"[GrassTint]   Base: {result['base']}")
                
                # Extract per-dragon alternate assets using brace-counting
                # (MapAlternateAsset blocks have deeply nested braces)
                alt_iter = re.finditer(r'MapAlternateAsset\s*\{', skin_body)
                for alt_start_match in alt_iter:
                    a_start = alt_start_match.end()
                    a_brace = 1
                    a_pos = a_start
                    while a_pos < len(skin_body) and a_brace > 0:
                        if skin_body[a_pos] == '{':
                            a_brace += 1
                        elif skin_body[a_pos] == '}':
                            a_brace -= 1
                        a_pos += 1
                    alt_body = skin_body[a_start:a_pos-1]
                    
                    tint_match = re.search(r'mGrassTintTextureName:\s*string\s*=\s*"([^"]+)"', alt_body)
                    flag_match = re.search(r'mVisibilityFlagName:\s*hash\s*=\s*"([^"]+)"', alt_body)
                    
                    if tint_match and flag_match:
                        flag_name = flag_match.group(1)
                        tint_path = tint_match.group(1)
                        result['alternates'][flag_name] = tint_path
                        print(f"[GrassTint]   {flag_name}: {tint_path}")
                
                # Found our matching skin, no need to continue
                break
        
        except Exception as e:
            print(f"[GrassTint] Error parsing map file: {e}")
        
        return result
    
    # Map dragon layer enum to visibility flag name from map file
    LAYER_TO_FLAG = {
        'LAYER_2': 'Fire',
        'LAYER_3': 'earth',
        'LAYER_4': 'Ocean',
        'LAYER_5': 'CLOUD',
        'LAYER_6': 'Hextech',
        'LAYER_7': 'Chemtech',
    }
    
    def _resolve_grass_tint_path(self, grass_tint_info: dict) -> str:
        """
        Resolve the actual grass tint texture path based on dragon layer selection.
        
        Dragon layer mapping:
            LAYER_1 (Base) -> use base mGrassTintTexture
            LAYER_2 (Inferno) -> Fire
            LAYER_3 (Mountain) -> earth  
            LAYER_4 (Ocean) -> Ocean
            LAYER_5 (Cloud) -> CLOUD
            LAYER_6 (Hextech) -> Hextech
            LAYER_7 (Chemtech) -> Chemtech
            LAYER_8 (Void) -> base fallback
        """
        alternates = grass_tint_info.get('alternates', {})
        base_name = grass_tint_info.get('base', '')
        
        # Check for dragon-specific grass tint
        flag_name = self.LAYER_TO_FLAG.get(self.dragon_layer, '')
        if flag_name and flag_name in alternates:
            alt_path = alternates[flag_name]
            resolved = self._resolve_assets_path(alt_path)
            if resolved:
                print(f"[GrassTint] Using dragon variant ({flag_name}): {os.path.basename(resolved)}")
                return resolved
            print(f"[GrassTint] Dragon variant {flag_name} texture not found: {alt_path}")
        
        # Use base grass tint texture (filename only, lives in levels_folder)
        if base_name:
            resolved = self._resolve_base_grass_tint(base_name)
            if resolved:
                return resolved
        
        return ''
    
    def _resolve_assets_path(self, asset_path: str) -> str:
        """Resolve an ASSETS/ prefixed path to a real file."""
        if not asset_path or not self.assets_folder:
            return ''
        rel_path = asset_path
        if rel_path.upper().startswith('ASSETS/'):
            rel_path = rel_path[7:]
        full_path = os.path.join(self.assets_folder, rel_path.replace('/', os.sep))
        if os.path.exists(full_path):
            return full_path
        found = self._find_file_case_insensitive(self.assets_folder, rel_path)
        return found or ''
    
    def _resolve_base_grass_tint(self, base_name: str) -> str:
        """
        Resolve a base grass tint filename (no path) to a real file.
        Base texture lives in levels_folder (e.g. levels/map11/info/)
        
        Example: "GrassTint_SRX.SRT_2024_Strategy_Differentiation_Preseason.dds"
                 -> "levels/map11/info/GrassTint_SRX.SRT_2024_Strategy_Differentiation_Preseason.dds"
        """
        print(f"[GrassTint] Resolving base: {base_name}")
        print(f"[GrassTint]   levels_folder: {self.levels_folder}")
        
        if not base_name:
            return ''
        
        # Extract stem and extension using proper splitext (handles multi-dot names)
        name_stem, name_ext = os.path.splitext(base_name)
        
        # Build variants: try original, then with .tex/.dds/.png extensions
        variants = [base_name]
        for alt_ext in ['.tex', '.dds', '.png']:
            if alt_ext.lower() != name_ext.lower():
                variants.append(name_stem + alt_ext)
        
        print(f"[GrassTint]   Trying variants: {variants}")
        
        # Search levels_folder first (primary location for base grass tint)
        if self.levels_folder:
            if not os.path.isdir(self.levels_folder):
                print(f"[GrassTint]   ERROR: levels_folder is not a directory!")
                return ''
            
            # Try exact filename match (case-sensitive)
            for variant in variants:
                full_path = os.path.join(self.levels_folder, variant)
                if os.path.exists(full_path):
                    print(f"[GrassTint]   ✓ Found: {variant}")
                    return full_path
            
            # Try case-insensitive match
            try:
                dir_entries = os.listdir(self.levels_folder)
                print(f"[GrassTint]   levels_folder contains {len(dir_entries)} files")
            except OSError as e:
                print(f"[GrassTint]   ERROR: Cannot list levels_folder: {e}")
                return ''
            
            lower_variants = {v.lower() for v in variants}
            for f in dir_entries:
                if f.lower() in lower_variants:
                    found = os.path.join(self.levels_folder, f)
                    print(f"[GrassTint]   ✓ Found (case-insensitive): {f}")
                    return found
            
            # Try partial match on the base name (without extension)
            base_lower = base_name.lower()
            for f in dir_entries:
                if base_lower in f.lower():
                    found = os.path.join(self.levels_folder, f)
                    print(f"[GrassTint]   ✓ Found (partial match): {f}")
                    return found
            
            # Try recursive search in subdirectories (e.g., levels/map11/info/)
            print(f"[GrassTint]   Searching recursively in levels_folder...")
            import glob
            for variant in variants:
                pattern = os.path.join(self.levels_folder, '**', variant)
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    print(f"[GrassTint]   ✓ Found (recursive): {os.path.basename(matches[0])}")
                    print(f"[GrassTint]     Full path: {matches[0]}")
                    return matches[0]
            
            print(f"[GrassTint]   ✗ Not found in levels_folder (even recursively)")
        else:
            print(f"[GrassTint]   WARNING: levels_folder not set!")
        
        # Fallback: search assets folder recursively (slower, shouldn't normally be needed)
        if self.assets_folder:
            print(f"[GrassTint]   Trying assets_folder as fallback...")
            import glob
            for variant in variants:
                matches = glob.glob(os.path.join(self.assets_folder, '**', variant), recursive=True)
                if matches:
                    print(f"[GrassTint]   ✓ Found in assets: {os.path.basename(matches[0])}")
                    return matches[0]
        
        print(f"[GrassTint]   ✗ Base grass tint not found anywhere!")
        return ''
    
    def _find_file_case_insensitive(self, base_dir: str, rel_path: str) -> str:
        """Find a file with case-insensitive path matching."""
        parts = rel_path.replace('/', os.sep).replace('\\', os.sep).split(os.sep)
        current = base_dir
        
        for part in parts:
            if not os.path.isdir(current):
                return ''
            try:
                entries = os.listdir(current)
            except OSError:
                return ''
            
            found = False
            for entry in entries:
                if entry.lower() == part.lower():
                    current = os.path.join(current, entry)
                    found = True
                    break
            
            if not found:
                return ''
        
        return current if os.path.exists(current) else ''
    
    def _find_grass_tint_from_map_file(self) -> str:
        """
        Try to find grass tint texture using the map file chain:
        materials.py -> mapContainer name -> map*.py -> MapSkin -> grass tint
        """
        if not self.map_py_path or not os.path.exists(self.map_py_path):
            return ''
        
        # We need to know the mapContainer name from the materials file
        # The materials path is stored when load_materials was called
        if not hasattr(self, '_materials_path') or not self._materials_path:
            return ''
        
        container_name = self._extract_map_container_name(self._materials_path)
        if not container_name:
            print("[GrassTint] No mapContainer found in materials file")
            return ''
        
        print(f"[GrassTint] mapContainer: {container_name}")
        
        grass_tint_info = self._parse_map_file_grass_tints(self.map_py_path, container_name)
        if not grass_tint_info.get('base') and not grass_tint_info.get('alternates'):
            print("[GrassTint] No grass tint textures found in map file")
            return ''
        
        return self._resolve_grass_tint_path(grass_tint_info)
    
    def _find_grass_tint_fallback(self) -> str:
        """Fallback: search for grass tint texture by globbing the assets folder."""
        if not self.assets_folder:
            return ''
        
        import glob
        
        # Search for grasstint textures in assets folder recursively
        search_patterns = [
            os.path.join(self.assets_folder, '**', 'grasstint*.tex'),
            os.path.join(self.assets_folder, '**', 'GrassTint*.tex'),
        ]
        
        for pattern in search_patterns:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                print(f"  Found grass tint texture (fallback): {os.path.basename(matches[0])}")
                return matches[0]
        
        # Check levels folder
        if self.levels_folder and os.path.isdir(self.levels_folder):
            for f in os.listdir(self.levels_folder):
                if 'grasstint' in f.lower():
                    found = os.path.join(self.levels_folder, f)
                    print(f"  Found grass tint texture (levels): {f}")
                    return found
        
        return ''
    
    @staticmethod
    def update_grass_tint_for_dragon(settings) -> int:
        """
        Update grass tint texture on all materials that have a 'Grass Tint (World UV)' node.
        Called when dragon layer filter changes.
        
        Args:
            settings: MapgeoSettings with assets_folder, levels_folder, map_py_path,
                      materials_json_path, dragon_layer_filter
        
        Returns:
            Number of materials updated
        """
        assets_folder = getattr(settings, 'assets_folder', '')
        levels_folder = getattr(settings, 'levels_folder', '')
        map_py_path = getattr(settings, 'map_py_path', '')
        materials_path = getattr(settings, 'materials_json_path', '')
        dragon_layer = getattr(settings, 'dragon_layer_filter', 'LAYER_1')
        
        if not map_py_path or not materials_path:
            return 0
        
        if not os.path.exists(map_py_path) or not os.path.exists(materials_path):
            return 0
        
        # Create a temporary loader to resolve the grass tint path
        loader = MaterialLoader(
            assets_folder=assets_folder,
            levels_folder=levels_folder,
            map_py_path=map_py_path,
            dragon_layer=dragon_layer
        )
        loader._materials_path = materials_path
        
        # Resolve the grass tint path for the current dragon layer
        container_name = loader._extract_map_container_name(materials_path)
        if not container_name:
            return 0
        
        grass_tint_info = loader._parse_map_file_grass_tints(map_py_path, container_name)
        if not grass_tint_info.get('base') and not grass_tint_info.get('alternates'):
            return 0
        
        new_path = loader._resolve_grass_tint_path(grass_tint_info)
        if not new_path:
            # Try fallback
            new_path = loader._find_grass_tint_fallback()
        
        if not new_path:
            return 0
        
        # Convert to PNG
        png_path = None
        if new_path.lower().endswith('.dds'):
            png_path = loader.tex_converter.convert_dds_to_png(new_path)
        else:
            png_path = loader.tex_converter.convert_tex_to_png(new_path)
        
        if not png_path or not os.path.exists(png_path):
            print(f"[GrassTint] Could not convert grass tint texture: {new_path}")
            return 0
        
        # Load or find the image
        try:
            new_img = bpy.data.images.load(png_path, check_existing=True)
            new_img.colorspace_settings.name = 'sRGB'
        except Exception as e:
            print(f"[GrassTint] Could not load grass tint image: {e}")
            return 0
        
        # Swap the image on all materials that have a grass tint node
        updated = 0
        for mat in bpy.data.materials:
            if not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.label == 'Grass Tint (World UV)':
                    if node.image != new_img:
                        node.image = new_img
                        updated += 1
                    break
        
        if updated > 0:
            dragon_name = {
                'LAYER_1': 'Base', 'LAYER_2': 'Inferno', 'LAYER_3': 'Mountain',
                'LAYER_4': 'Ocean', 'LAYER_5': 'Cloud', 'LAYER_6': 'Hextech',
                'LAYER_7': 'Chemtech', 'LAYER_8': 'Void',
            }.get(dragon_layer, 'Base')
            print(f"[GrassTint] Switched {updated} materials to {dragon_name} grass tint: {os.path.basename(new_path)}")
        
        return updated
    
    def create_blender_material(self, mat_name: str, mat_data: dict, 
                                lightmap_texture: str = None,
                                lightmap_color_scale: float = 1.0,
                                texture_overrides: Dict[str, str] = None,
                                baked_paint_scale: tuple = (1.0, 1.0),
                                baked_paint_bias: tuple = (0.0, 0.0)) -> Optional[bpy.types.Material]:
        """
        Create a Blender material from material data with shader-aware node setup.
        
        Dispatches to shader-specific builders based on the shader type.
        """
        # Apply texture overrides to mat_data if present
        # This replaces sampler texturePath values with per-mesh overrides
        if texture_overrides:
            import copy
            mat_data = copy.deepcopy(mat_data)
            for sampler in mat_data.get('samplerValues', []):
                tex_name = sampler.get('TextureName', sampler.get('textureName', ''))
                if tex_name in texture_overrides:
                    sampler['texturePath'] = texture_overrides[tex_name]
        
        # Build a unique cache key that includes lightmap and texture override info
        cache_key = mat_name
        if lightmap_texture:
            cache_key = f"{mat_name}__lm__{lightmap_texture}"
        if texture_overrides:
            import hashlib
            override_hash = hashlib.md5(str(sorted(texture_overrides.items())).encode()).hexdigest()[:6]
            cache_key = f"{cache_key}__to__{override_hash}"
        
        # Check cache
        if cache_key in self.materials_cache:
            return self.materials_cache[cache_key]
        
        # Create material with unique name if it has a lightmap or texture overrides
        bl_mat_name = mat_name
        if lightmap_texture:
            import hashlib
            lm_hash = hashlib.md5(lightmap_texture.encode()).hexdigest()[:6]
            bl_mat_name = f"{mat_name}_lm{lm_hash}"
        if texture_overrides:
            import hashlib
            to_hash = hashlib.md5(str(sorted(texture_overrides.items())).encode()).hexdigest()[:6]
            bl_mat_name = f"{bl_mat_name}_to{to_hash}"
        
        bl_mat = bpy.data.materials.get(bl_mat_name)
        if bl_mat is None:
            bl_mat = bpy.data.materials.new(name=bl_mat_name)
        
        # Enable nodes
        bl_mat.use_nodes = True
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        nodes.clear()
        
        # Create base nodes (all shaders need these)
        output_node = nodes.new('ShaderNodeOutputMaterial')
        output_node.location = (600, 0)
        
        bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf_node.location = (300, 0)
        bsdf_node.inputs['IOR'].default_value = 1.0
        bsdf_node.inputs['Roughness'].default_value = 1.0
        
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
        
        # Shader macros
        shader_macros = mat_data.get('shaderMacros', {})
        has_baked_lighting = 'NO_BAKED_LIGHTING' not in shader_macros
        
        # Determine shader type
        shader_name = self._get_shader_short_name(mat_data)
        
        # Store shader type as custom property on the material
        bl_mat["league_shader"] = shader_name or "Unknown"
        bl_mat["league_shader_path"] = mat_data.get('shader', '')
        
        # --- Dispatch to shader-specific builder ---
        if shader_name in ('ENV_Glass', 'ENV_Glass_Vertex_Offset', 'ENV_Glass_Diffuse'):
            self._build_glass_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('ENV_GlowSign', 'ENV_GlowSign_Atlas'):
            self._build_glow_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('Emissive_Basic',):
            self._build_emissive_basic(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('Hologram', 'Hologram_Rotate'):
            self._build_hologram_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'Indicator_Faelights':
            self._build_faelights_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'DefaultEnv_Flat_BakedTerrain':
            self._build_baked_terrain(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                     lightmap_texture, lightmap_color_scale, has_baked_lighting,
                                     baked_paint_scale, baked_paint_bias)
        elif shader_name == 'DefaultEnv_Metal':
            self._build_metal_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'DefaultEnv_Flat_PlanarReflection':
            self._build_planar_reflection(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                          lightmap_texture, lightmap_color_scale, has_baked_lighting)
        elif shader_name == '4TextureBlend_WorldProjected':
            self._build_4texture_blend(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        else:
            # Default path: all DefaultEnv_Flat variants and most other shaders
            self._build_default_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                       lightmap_texture, lightmap_color_scale, has_baked_lighting)
        
        # --- Apply blend state / alpha settings ---
        shader_macros = mat_data.get('shaderMacros', {})
        
        # Backface culling based on shader/material settings
        if not mat_data.get('cullEnable', False) or 'DoubleSided' in shader_name:
            bl_mat.use_backface_culling = False
        else:
            bl_mat.use_backface_culling = True
        
        # Per-shader backface culling overrides
        if shader_name == 'Flowmap_River':
            bl_mat.use_backface_culling = True
        
        # Render method: BLENDED if blendEnable, otherwise DITHERED
        # Special cases: PREMULTIPLIED_ALPHA always uses DITHERED, Indicator_Faelights always uses BLENDED
        # addressU=1 + addressV=1 on diffuse sampler forces BLENDED (Clamp mode)
        # Exception: BakedTerrain uses clip for UV clamping but stays DITHERED (opaque terrain)
        diffuse_sampler = (self._get_sampler_data(mat_data, 'DiffuseTexture') or 
                           self._get_sampler_data(mat_data, 'Diffuse_Texture') or
                           self._get_sampler_data(mat_data, 'BAKED_DIFFUSE_TEXTURE'))
        needs_clip_blend = (self._sampler_needs_clip(diffuse_sampler) 
                            and shader_name != 'DefaultEnv_Flat_BakedTerrain')
        
        if needs_clip_blend:
            bl_mat.surface_render_method = 'BLENDED'
        elif shader_macros.get('PREMULTIPLIED_ALPHA') == '1':
            bl_mat.surface_render_method = 'DITHERED'
        elif shader_name == 'Indicator_Faelights':
            bl_mat.surface_render_method = 'BLENDED'
            bl_mat.use_transparency_overlap = True
        elif mat_data.get('blendEnable', False):
            bl_mat.surface_render_method = 'BLENDED'
            bl_mat.show_transparent_back = False
        else:
            bl_mat.surface_render_method = 'DITHERED'
        
        # Store all shader switches as custom properties for reference
        switches = mat_data.get('switches', {})
        if switches:
            bl_mat["league_switches"] = str(switches)
        if shader_macros:
            bl_mat["league_macros"] = str(shader_macros)
        
        # Cache and return
        self.materials_cache[cache_key] = bl_mat
        return bl_mat
    
    # =========================================================================
    # Shader-specific builders
    # =========================================================================
    
    def _build_default_shader(self, bl_mat, nodes, links, bsdf_node, output_node,
                              mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting):
        """
        Default shader builder for DefaultEnv_Flat, DefaultEnv_Flat_AlphaTest,
        DefaultEnv_Flat_AlphaTest_DoubleSided, VertexDeform, SRX_Blend_*, ENV_TreeCanopy,
        ENV_SimpleFoliage, and most other shaders.
        
        Diffuse × TintColor × 2 → (with lightmap: Emission, without: Base Color)
        """
        # Find diffuse texture (try both naming conventions)
        diffuse_path = (self._get_sampler_path(mat_data, 'DiffuseTexture') or 
                        self._get_sampler_path(mat_data, 'Diffuse_Texture') or
                        self._get_sampler_path(mat_data, 'BAKED_DIFFUSE_TEXTURE'))
        
        # Check diffuse sampler address mode for Clip
        diffuse_sampler = (self._get_sampler_data(mat_data, 'DiffuseTexture') or 
                           self._get_sampler_data(mat_data, 'Diffuse_Texture') or
                           self._get_sampler_data(mat_data, 'BAKED_DIFFUSE_TEXTURE'))
        diffuse_extension = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
        
        diffuse_node = None
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap", diffuse_extension)
            if diffuse_node:
                diffuse_node.location = (-700, 200)
        
        # If diffuse sampler uses Clip, force BLENDED render mode
        if diffuse_extension == 'CLIP':
            bl_mat.surface_render_method = 'BLENDED'
        
        # TintColor: League's tint is multiplied × 2 (0.5 = neutral, 1.0 = 2× bright)
        tint_color = self._get_param(mat_data, 'TintColor') or self._get_param(mat_data, 'BaseTex_TintColor')
        
        # Apply tint as multiply node if we have a diffuse texture and tint differs from neutral
        tinted_color_output = None
        tinted_alpha_output = None
        
        if diffuse_node and tint_color and len(tint_color) >= 3:
            # Tint × 2 (League convention: 0.5 = no change)
            tint_r = min(tint_color[0] * 2.0, 1.0)
            tint_g = min(tint_color[1] * 2.0, 1.0)
            tint_b = min(tint_color[2] * 2.0, 1.0)
            
            # Only add tint node if it's not neutral white (i.e., not ~0.5,0.5,0.5)
            is_neutral = (abs(tint_color[0] - 0.5) < 0.01 and 
                         abs(tint_color[1] - 0.5) < 0.01 and 
                         abs(tint_color[2] - 0.5) < 0.01)
            
            if not is_neutral:
                tint_mix = nodes.new('ShaderNodeMix')
                tint_mix.data_type = 'RGBA'
                tint_mix.blend_type = 'MULTIPLY'
                tint_mix.location = (-400, 200)
                tint_mix.inputs['Factor'].default_value = 1.0
                tint_mix.label = f"Tint ({tint_r:.2f}, {tint_g:.2f}, {tint_b:.2f})"
                
                links.new(diffuse_node.outputs['Color'], tint_mix.inputs[6])
                tint_mix.inputs[7].default_value = (tint_r, tint_g, tint_b, 1.0)
                
                tinted_color_output = tint_mix.outputs[2]
                tinted_alpha_output = diffuse_node.outputs['Alpha']
            else:
                tinted_color_output = diffuse_node.outputs['Color']
                tinted_alpha_output = diffuse_node.outputs['Alpha']
        elif diffuse_node:
            tinted_color_output = diffuse_node.outputs['Color']
            tinted_alpha_output = diffuse_node.outputs['Alpha']
        elif tint_color and len(tint_color) >= 3:
            # No texture, just tint color
            bsdf_node.inputs['Base Color'].default_value = (
                min(tint_color[0] * 2.0, 1.0),
                min(tint_color[1] * 2.0, 1.0),
                min(tint_color[2] * 2.0, 1.0),
                1.0
            )
        
        # Grass Tint Map for VertexDeform shader (world-space tint overlay)
        shader_name = self._get_shader_short_name(mat_data)
        switches = mat_data.get('switches', {})
        use_grass_tint = switches.get('USE_GRASS_TINT_MAP', False)
        
        if shader_name == 'VertexDeform' and use_grass_tint and tinted_color_output:
            # Look for grass tint texture (usually maps/textures/grasstint_*.tex)
            grass_tint_path = self._find_grass_tint_texture()
            
            if grass_tint_path:
                # Create world position-based UV mapping
                # Grass tint textures are sampled using XY world coordinates mapped to 0-1
                tex_coord = nodes.new('ShaderNodeTexCoord')
                tex_coord.location = (-1100, -400)
                
                # Separate XYZ to use only X and Y
                separate_xyz = nodes.new('ShaderNodeSeparateXYZ')
                separate_xyz.location = (-900, -400)
                links.new(tex_coord.outputs['Object'], separate_xyz.inputs['Vector'])
                
                # Map world coordinates to UV space (typical map size ~15000 units)
                # This may need adjustment based on actual map bounds
                map_scale = 1.0 / 15000.0  # Adjust this if needed
                
                combine_xy = nodes.new('ShaderNodeCombineXYZ')
                combine_xy.location = (-700, -400)
                
                # Scale and offset to 0-1 range
                scale_x = nodes.new('ShaderNodeMath')
                scale_x.operation = 'MULTIPLY'
                scale_x.location = (-800, -350)
                scale_x.inputs[1].default_value = map_scale
                links.new(separate_xyz.outputs['X'], scale_x.inputs[0])
                
                scale_y = nodes.new('ShaderNodeMath')
                scale_y.operation = 'MULTIPLY'
                scale_y.location = (-800, -450)
                scale_y.inputs[1].default_value = map_scale
                links.new(separate_xyz.outputs['Y'], scale_y.inputs[0])
                
                # Offset to center (0.5, 0.5)
                offset_x = nodes.new('ShaderNodeMath')
                offset_x.operation = 'ADD'
                offset_x.location = (-650, -350)
                offset_x.inputs[1].default_value = 0.5
                links.new(scale_x.outputs[0], offset_x.inputs[0])
                
                offset_y = nodes.new('ShaderNodeMath')
                offset_y.operation = 'ADD'
                offset_y.location = (-650, -450)
                offset_y.inputs[1].default_value = 0.5
                links.new(scale_y.outputs[0], offset_y.inputs[0])
                
                links.new(offset_x.outputs[0], combine_xy.inputs['X'])
                links.new(offset_y.outputs[0], combine_xy.inputs['Y'])
                
                # Load grass tint texture
                grass_tint_node = nodes.new('ShaderNodeTexImage')
                grass_tint_node.location = (-500, -400)
                grass_tint_node.label = "Grass Tint (World UV)"
                links.new(combine_xy.outputs['Vector'], grass_tint_node.inputs['Vector'])
                
                # Load the texture (supports .tex and .dds)
                if grass_tint_path:
                    png_path = None
                    if grass_tint_path.lower().endswith('.dds'):
                        png_path = self.tex_converter.convert_dds_to_png(grass_tint_path)
                    else:
                        png_path = self.tex_converter.convert_tex_to_png(grass_tint_path)
                    if png_path and os.path.exists(png_path):
                        try:
                            img = bpy.data.images.load(png_path, check_existing=True)
                            grass_tint_node.image = img
                            img.colorspace_settings.name = 'sRGB'  # It's a color tint map
                        except Exception as e:
                            print(f"  Warning: Could not load grass tint texture: {e}")
                
                # Multiply grass tint with tinted diffuse
                grass_tint_mix = nodes.new('ShaderNodeMix')
                grass_tint_mix.data_type = 'RGBA'
                grass_tint_mix.blend_type = 'MULTIPLY'
                grass_tint_mix.location = (-250, 0)
                grass_tint_mix.inputs['Factor'].default_value = 1.0
                grass_tint_mix.label = "Diffuse × Grass Tint"
                
                links.new(tinted_color_output, grass_tint_mix.inputs[6])
                links.new(grass_tint_node.outputs['Color'], grass_tint_mix.inputs[7])
                
                # Update output to be after grass tint multiplication
                tinted_color_output = grass_tint_mix.outputs[2]
        
        # Load lightmap texture if available
        lightmap_node = None
        if has_baked_lighting and lightmap_texture and self.assets_folder:
            lightmap_node = self._load_texture_node(bl_mat, nodes, links, lightmap_texture, "LightmapUV")
            if lightmap_node:
                lightmap_node.location = (-700, -200)
                if lightmap_node.image:
                    lightmap_node.image.colorspace_settings.name = 'Non-Color'
        
        # Connect: Diffuse × Lightmap → Emission (or Diffuse → Base Color)
        if tinted_color_output and lightmap_node:
            # Lightmap × Scale
            lm_multiply = nodes.new('ShaderNodeMix')
            lm_multiply.data_type = 'RGBA'
            lm_multiply.blend_type = 'MULTIPLY'
            lm_multiply.location = (-400, -100)
            lm_multiply.inputs['Factor'].default_value = 1.0
            lm_multiply.label = "LM × Scale"
            links.new(lightmap_node.outputs['Color'], lm_multiply.inputs[6])
            lm_multiply.inputs[7].default_value = (
                lightmap_color_scale, lightmap_color_scale, lightmap_color_scale, 1.0
            )
            
            # Diffuse × Lightmap
            final_mix = nodes.new('ShaderNodeMix')
            final_mix.data_type = 'RGBA'
            final_mix.blend_type = 'MULTIPLY'
            final_mix.location = (-100, 100)
            final_mix.inputs['Factor'].default_value = 1.0
            final_mix.label = "Diffuse × Lightmap"
            links.new(tinted_color_output, final_mix.inputs[6])
            links.new(lm_multiply.outputs[2], final_mix.inputs[7])
            
            # → Emission (Combined pass)
            links.new(final_mix.outputs[2], bsdf_node.inputs['Emission Color'])
            bsdf_node.inputs['Emission Strength'].default_value = 1.0
            bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
            
            if tinted_alpha_output:
                links.new(tinted_alpha_output, bsdf_node.inputs['Alpha'])
                
        elif tinted_color_output:
            links.new(tinted_color_output, bsdf_node.inputs['Base Color'])
            if tinted_alpha_output:
                links.new(tinted_alpha_output, bsdf_node.inputs['Alpha'])
        
        # Alpha test handling
        alpha_test = self._get_param(mat_data, 'AlphaTestValue')
        shader_name = self._get_shader_short_name(mat_data)
        if alpha_test and len(alpha_test) > 0:
            bl_mat.alpha_threshold = alpha_test[0]
        elif 'AlphaTest' in shader_name:
            bl_mat.alpha_threshold = 0.5
        
        if not has_baked_lighting:
            if 'Specular IOR Level' in bsdf_node.inputs:
                bsdf_node.inputs['Specular IOR Level'].default_value = 0.5
    
    def _build_glass_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        ENV_Glass / ENV_Glass_Vertex_Offset / ENV_Glass_Diffuse
        
        Fresnel-based glass with two colors blending by view angle.
        """
        color1 = self._get_param(mat_data, 'Glass_Color1', [0.1, 0.2, 0.3, 1])
        color2 = self._get_param(mat_data, 'Glass_Color2', [0.2, 0.4, 0.6, 1])
        fresnel_inner = self._get_param(mat_data, 'Fresnel_Size_Inner', [2.0])
        fresnel_outer = self._get_param(mat_data, 'Fresnel_Size_Outer', [5.0])
        roughness = self._get_param(mat_data, 'Glass_Roughness', [0.1])
        alpha_bias = self._get_param(mat_data, 'Alpha_Bias', [0.3])
        
        # Fresnel node
        fresnel = nodes.new('ShaderNodeFresnel')
        fresnel.location = (-300, 200)
        fresnel.inputs['IOR'].default_value = 1.0 + (fresnel_inner[0] if fresnel_inner else 2.0) * 0.1
        
        # Color mix: Glass_Color1 → Glass_Color2 based on fresnel
        color_mix = nodes.new('ShaderNodeMix')
        color_mix.data_type = 'RGBA'
        color_mix.location = (-100, 200)
        color_mix.label = "Glass Color Blend"
        links.new(fresnel.outputs['Fac'], color_mix.inputs['Factor'])
        color_mix.inputs[6].default_value = (color1[0], color1[1], color1[2], 1.0)
        color_mix.inputs[7].default_value = (color2[0], color2[1], color2[2], 1.0)
        
        # Load diffuse if available (ENV_Glass_Diffuse)
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_sampler = self._get_sampler_data(mat_data, 'Diffuse_Texture')
        diffuse_ext = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap", diffuse_ext)
            if diffuse_node:
                diffuse_node.location = (-500, 400)
                # Mix diffuse with glass color
                diff_mix = nodes.new('ShaderNodeMix')
                diff_mix.data_type = 'RGBA'
                diff_mix.blend_type = 'MULTIPLY'
                diff_mix.location = (50, 300)
                diff_mix.inputs['Factor'].default_value = 1.0
                links.new(diffuse_node.outputs['Color'], diff_mix.inputs[6])
                links.new(color_mix.outputs[2], diff_mix.inputs[7])
                links.new(diff_mix.outputs[2], bsdf_node.inputs['Base Color'])
            else:
                links.new(color_mix.outputs[2], bsdf_node.inputs['Base Color'])
        else:
            links.new(color_mix.outputs[2], bsdf_node.inputs['Base Color'])
        
        # Glass properties
        bsdf_node.inputs['Roughness'].default_value = roughness[0] if roughness else 0.1
        bsdf_node.inputs['Alpha'].default_value = alpha_bias[0] if alpha_bias else 0.3
        bsdf_node.inputs['IOR'].default_value = 1.45
        
        bl_mat.show_transparent_back = True
    
    def _build_glow_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        ENV_GlowSign / ENV_GlowSign_Atlas
        
        Diffuse + Emissive texture with emissive color/intensity control.
        """
        # Load diffuse
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_sampler = self._get_sampler_data(mat_data, 'Diffuse_Texture')
        diffuse_ext = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
        diffuse_node = None
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap", diffuse_ext)
            if diffuse_node:
                diffuse_node.location = (-700, 300)
                links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        
        if diffuse_ext == 'CLIP':
            bl_mat.surface_render_method = 'BLENDED'
        
        # Load emissive texture
        emissive_path = self._get_sampler_path(mat_data, 'Emissive_Texture')
        if emissive_path:
            emissive_node = self._load_texture_node(bl_mat, nodes, links, emissive_path, "UVMap")
            if emissive_node:
                emissive_node.location = (-700, -100)
                if emissive_node.image:
                    emissive_node.image.colorspace_settings.name = 'Non-Color'
                
                # Emissive color and intensity
                emissive_color = self._get_param(mat_data, 'Emissive_Color', [1, 1, 1, 1])
                emissive_intensity = self._get_param(mat_data, 'Emissive_Intensity', [2.0])
                
                # Emissive × Color
                emit_mix = nodes.new('ShaderNodeMix')
                emit_mix.data_type = 'RGBA'
                emit_mix.blend_type = 'MULTIPLY'
                emit_mix.location = (-400, -100)
                emit_mix.inputs['Factor'].default_value = 1.0
                emit_mix.label = "Emissive × Color"
                links.new(emissive_node.outputs['Color'], emit_mix.inputs[6])
                emit_mix.inputs[7].default_value = (
                    emissive_color[0], emissive_color[1], emissive_color[2], 1.0
                )
                
                links.new(emit_mix.outputs[2], bsdf_node.inputs['Emission Color'])
                bsdf_node.inputs['Emission Strength'].default_value = emissive_intensity[0] if emissive_intensity else 2.0
        
        # Alpha offset
        alpha_offset = self._get_param(mat_data, 'Alpha_Offset', [0])
        if alpha_offset and alpha_offset[0] > 0:
            bl_mat.alpha_threshold = alpha_offset[0]
    
    def _build_emissive_basic(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        Emissive_Basic: solid emissive color, no textures.
        """
        emissive_color = self._get_param(mat_data, 'Emissive_Color', [1, 1, 1, 1])
        emissive_intensity = self._get_param(mat_data, 'Emissive_Intensity', [1.0])
        
        bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        bsdf_node.inputs['Emission Color'].default_value = (
            emissive_color[0], emissive_color[1], emissive_color[2], 1.0
        )
        bsdf_node.inputs['Emission Strength'].default_value = emissive_intensity[0] if emissive_intensity else 1.0
    
    def _build_hologram_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        Hologram / Hologram_Rotate
        
        Semi-transparent emissive with base color and distortion effects.
        """
        base_color = self._get_param(mat_data, 'Base_Color', [0, 0.5, 1, 1])
        emissive_intensity = self._get_param(mat_data, 'Emissive_Intensity', [1.5])
        final_alpha = self._get_param(mat_data, 'Final_Alpha', [0.5])
        
        # Load diffuse if available
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_sampler = self._get_sampler_data(mat_data, 'Diffuse_Texture')
        diffuse_ext = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap", diffuse_ext)
            if diffuse_node:
                diffuse_node.location = (-700, 200)
                
                # Mix diffuse with base color
                color_mix = nodes.new('ShaderNodeMix')
                color_mix.data_type = 'RGBA'
                color_mix.blend_type = 'MULTIPLY'
                color_mix.location = (-400, 200)
                color_mix.inputs['Factor'].default_value = 1.0
                links.new(diffuse_node.outputs['Color'], color_mix.inputs[6])
                color_mix.inputs[7].default_value = (base_color[0], base_color[1], base_color[2], 1.0)
                
                links.new(color_mix.outputs[2], bsdf_node.inputs['Emission Color'])
        else:
            bsdf_node.inputs['Emission Color'].default_value = (
                base_color[0], base_color[1], base_color[2], 1.0
            )
        
        bsdf_node.inputs['Emission Strength'].default_value = emissive_intensity[0] if emissive_intensity else 1.5
        bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        bsdf_node.inputs['Alpha'].default_value = final_alpha[0] if final_alpha else 0.5
        
        bl_mat.show_transparent_back = True
    
    def _build_faelights_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        Indicator_Faelights: simple emissive indicator with tint color.
        """
        tint = self._get_param(mat_data, 'TintColor', [0, 1, 1, 0.1])
        
        bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        bsdf_node.inputs['Emission Color'].default_value = (tint[0], tint[1], tint[2], 1.0)
        bsdf_node.inputs['Emission Strength'].default_value = 2.0
        bsdf_node.inputs['Alpha'].default_value = tint[3] if len(tint) > 3 else 0.1
    
    def _build_baked_terrain(self, bl_mat, nodes, links, bsdf_node, output_node, 
                             mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting,
                             baked_paint_scale=(1.0, 1.0), baked_paint_bias=(0.0, 0.0)):
        """
        DefaultEnv_Flat_BakedTerrain: Uses BAKED_DIFFUSE_TEXTURE sampler name.
        Applies BakedPaintScale/Bias UV transform via Mapping node.
        """
        # Check if we need a UV transform for the baked paint texture
        needs_uv_transform = (baked_paint_scale != (1.0, 1.0) or baked_paint_bias != (0.0, 0.0))
        
        if needs_uv_transform:
            # Build the shader manually with a Mapping node for UV transform
            diffuse_path = self._get_sampler_path(mat_data, 'BAKED_DIFFUSE_TEXTURE')
            diffuse_sampler = self._get_sampler_data(mat_data, 'BAKED_DIFFUSE_TEXTURE')
            diffuse_ext = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
            
            if diffuse_path:
                # UV Map node - BakedTerrain uses UV channel 0 (UVMap) with scale/offset for baked paint
                uv_node = nodes.new('ShaderNodeUVMap')
                uv_node.uv_map = 'UVMap'
                uv_node.location = (-1100, 200)
                
                # Mapping node for scale+bias transform: finalUV = rawUV * Scale + Bias
                mapping_node = nodes.new('ShaderNodeMapping')
                mapping_node.vector_type = 'POINT'
                mapping_node.location = (-900, 200)
                # Location = raw bias values from file
                mapping_node.inputs['Location'].default_value = (baked_paint_bias[0], baked_paint_bias[1], 0.0)
                # Scale = raw scale values from file
                mapping_node.inputs['Scale'].default_value = (baked_paint_scale[0], baked_paint_scale[1], 1.0)
                
                links.new(uv_node.outputs['UV'], mapping_node.inputs['Vector'])
                
                # Load texture with custom UV
                tex_node = self._load_texture_from_path(bl_mat, nodes, diffuse_path, diffuse_ext)
                if tex_node:
                    tex_node.location = (-700, 200)
                    links.new(mapping_node.outputs['Vector'], tex_node.inputs['Vector'])
                    
                    # Apply tint color (same as default shader)
                    tint = self._get_param(mat_data, 'Tint', self._get_param(mat_data, 'TintColor', [0.5, 0.5, 0.5, 1]))
                    
                    if has_baked_lighting and lightmap_texture:
                        # With lightmap: emission path
                        lm_node = self._load_texture_node(bl_mat, nodes, links, lightmap_texture, 'LightmapUV')
                        if lm_node:
                            lm_node.location = (-700, -200)
                            
                            # Multiply diffuse × lightmap
                            mix_node = nodes.new('ShaderNodeMix')
                            mix_node.data_type = 'RGBA'
                            mix_node.blend_type = 'MULTIPLY'
                            mix_node.location = (-200, 200)
                            mix_node.inputs['Factor'].default_value = 1.0
                            links.new(tex_node.outputs['Color'], mix_node.inputs[6])
                            links.new(lm_node.outputs['Color'], mix_node.inputs[7])
                            
                            # Apply lightmap color scale
                            if lightmap_color_scale != 1.0:
                                scale_node = nodes.new('ShaderNodeMix')
                                scale_node.data_type = 'RGBA'
                                scale_node.blend_type = 'MULTIPLY'
                                scale_node.location = (0, 200)
                                scale_node.inputs['Factor'].default_value = 1.0
                                scale_node.inputs[7].default_value = (lightmap_color_scale, lightmap_color_scale, lightmap_color_scale, 1.0)
                                links.new(mix_node.outputs[2], scale_node.inputs[6])
                                links.new(scale_node.outputs[2], bsdf_node.inputs['Emission Color'])
                            else:
                                links.new(mix_node.outputs[2], bsdf_node.inputs['Emission Color'])
                            
                            bsdf_node.inputs['Emission Strength'].default_value = 1.0
                            bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 0.0, 1.0)
                        else:
                            links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                    else:
                        links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                    
                    links.new(tex_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
            else:
                # No diffuse texture, fall through to default
                self._build_default_shader(bl_mat, nodes, links, bsdf_node, output_node,
                                           mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting)
        else:
            # No UV transform needed, use default shader path
            self._build_default_shader(bl_mat, nodes, links, bsdf_node, output_node,
                                       mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting)
    
    def _build_metal_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        DefaultEnv_Metal: PBR-like with specular, roughness, environment reflection.
        """
        # Load diffuse
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_sampler = self._get_sampler_data(mat_data, 'Diffuse_Texture')
        diffuse_ext = 'CLIP' if self._sampler_needs_clip(diffuse_sampler) else 'REPEAT'
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap", diffuse_ext)
            if diffuse_node:
                diffuse_node.location = (-700, 200)
                links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        
        if diffuse_ext == 'CLIP':
            bl_mat.surface_render_method = 'BLENDED'
        
        # Load mask texture (R=metallic, G=roughness, B=AO typically)
        mask_path = self._get_sampler_path(mat_data, 'Mask_Texture')
        if mask_path:
            mask_node = self._load_texture_node(bl_mat, nodes, links, mask_path, "UVMap")
            if mask_node:
                mask_node.location = (-700, -100)
                if mask_node.image:
                    mask_node.image.colorspace_settings.name = 'Non-Color'
                
                # Separate RGB
                sep_rgb = nodes.new('ShaderNodeSeparateColor')
                sep_rgb.location = (-400, -100)
                links.new(mask_node.outputs['Color'], sep_rgb.inputs['Color'])
        
        # Metal properties
        roughness = self._get_param(mat_data, 'Roughness', [0.5])
        reflectivity = self._get_param(mat_data, 'Reflectivity', [0.5])
        
        bsdf_node.inputs['Roughness'].default_value = roughness[0] if roughness else 0.5
        bsdf_node.inputs['Metallic'].default_value = reflectivity[0] if reflectivity else 0.5
        bsdf_node.inputs['IOR'].default_value = 1.5
        
        # Tint
        tint = self._get_param(mat_data, 'Tint', [0.5, 0.5, 0.5, 1])
        if tint:
            bl_mat["league_tint"] = list(tint)
    
    def _build_planar_reflection(self, bl_mat, nodes, links, bsdf_node, output_node,
                                 mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting):
        """
        DefaultEnv_Flat_PlanarReflection: Flat diffuse with planar reflection support.
        """
        self._build_default_shader(bl_mat, nodes, links, bsdf_node, output_node,
                                   mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting)
        
        # Reduce roughness for reflective surfaces
        reflection_strength = self._get_param(mat_data, 'PlanarReflectionStrength', [0.5])
        if reflection_strength:
            roughness = max(0.0, 1.0 - reflection_strength[0])
            bsdf_node.inputs['Roughness'].default_value = roughness
    
    def _build_4texture_blend(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        4TextureBlend_WorldProjected: Terrain blending shader with 4 textures and vertex color masks.
        
        Uses:
        - Bottom_Texture (base layer)
        - Middle_Texture (blended via Red channel)
        - Top_Texture (blended via Green channel)
        - Extras_Texture (blended via Blue channel)
        
        Vertex color RGB channels control which texture is visible.
        """
        # Get texture paths
        bottom_path = self._get_sampler_path(mat_data, 'Bottom_Texture')
        middle_path = self._get_sampler_path(mat_data, 'Middle_Texture')
        top_path = self._get_sampler_path(mat_data, 'Top_Texture')
        extras_path = self._get_sampler_path(mat_data, 'Extras_Texture')
        
        # Get tiling parameters
        bottom_tiling = self._get_param(mat_data, 'Bottom_Tiling', [0.1, 0.1])
        mid_tiling = self._get_param(mat_data, 'Mid_Tiling', [0.08, 0.08])
        top_tiling = self._get_param(mat_data, 'Top_Tiling', [0.2, 0.2])
        extra_tiling = self._get_param(mat_data, 'Extra_Tiling', [0.1, 0.1])
        
        # Get blend powers
        red_power = self._get_param(mat_data, 'Red_Blend_Power', [4.0])[0]
        green_power = self._get_param(mat_data, 'Green_Blend_Power', [4.0])[0]
        blue_power = self._get_param(mat_data, 'Blue_Blend_Power', [4.0])[0]
        
        # Get switches
        switches = mat_data.get('switches', {})
        use_top = switches.get('USE_TOP', True)
        use_extras = switches.get('USE_EXTRAS', False)
        
        # World projection: use Texture Coordinate -> Object for world-space UVs
        tex_coord = nodes.new('ShaderNodeTexCoord')
        tex_coord.location = (-1400, 0)
        
        # Vertex color node for masks
        vcol_node = nodes.new('ShaderNodeVertexColor')
        vcol_node.location = (-1400, -400)
        vcol_node.layer_name = ''  # Use default vertex color layer
        
        # Separate RGB channels from vertex colors
        separate_rgb = nodes.new('ShaderNodeSeparateColor')
        separate_rgb.location = (-1200, -400)
        links.new(vcol_node.outputs['Color'], separate_rgb.inputs['Color'])
        
        # Helper function to create tiled texture
        def create_tiled_texture(texture_path, tiling, y_offset):
            if not texture_path:
                return None
            
            # Mapping node for tiling
            mapping = nodes.new('ShaderNodeMapping')
            mapping.location = (-1200, y_offset)
            mapping.vector_type = 'POINT'
            mapping.inputs['Scale'].default_value = (tiling[0], tiling[1], 1.0)
            links.new(tex_coord.outputs['Object'], mapping.inputs['Vector'])
            
            # Load texture
            tex_node = self._load_texture_from_path(bl_mat, nodes, texture_path)
            if tex_node:
                tex_node.location = (-900, y_offset)
                links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])
                return tex_node
            return None
        
        # Create texture nodes with tiling
        bottom_tex = create_tiled_texture(bottom_path, bottom_tiling, 400)
        middle_tex = create_tiled_texture(middle_path, mid_tiling, 100) if middle_path else None
        top_tex = create_tiled_texture(top_path, top_tiling, -200) if use_top and top_path else None
        extras_tex = create_tiled_texture(extras_path, extra_tiling, -500) if use_extras and extras_path else None
        
        # Start with bottom texture
        current_color = bottom_tex.outputs['Color'] if bottom_tex else None
        
        if not current_color:
            # No textures available, use default color
            bsdf_node.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
            return
        
        current_x = -500
        
        # Blend Middle texture using Red channel
        if middle_tex:
            # Apply blend power to red mask
            power_node = nodes.new('ShaderNodeMath')
            power_node.operation = 'POWER'
            power_node.location = (-700, -200)
            power_node.inputs[1].default_value = red_power
            links.new(separate_rgb.outputs['Red'], power_node.inputs[0])
            
            # Mix with red channel mask
            mix_middle = nodes.new('ShaderNodeMix')
            mix_middle.data_type = 'RGBA'
            mix_middle.blend_type = 'MIX'
            mix_middle.location = (current_x, 200)
            mix_middle.label = "Middle (Red)"
            links.new(current_color, mix_middle.inputs[6])  # A
            links.new(middle_tex.outputs['Color'], mix_middle.inputs[7])  # B
            links.new(power_node.outputs[0], mix_middle.inputs['Factor'])
            current_color = mix_middle.outputs[2]
            current_x += 250
        
        # Blend Top texture using Green channel
        if top_tex and use_top:
            # Apply blend power to green mask
            power_node = nodes.new('ShaderNodeMath')
            power_node.operation = 'POWER'
            power_node.location = (-700, -300)
            power_node.inputs[1].default_value = green_power
            links.new(separate_rgb.outputs['Green'], power_node.inputs[0])
            
            # Mix with green channel mask
            mix_top = nodes.new('ShaderNodeMix')
            mix_top.data_type = 'RGBA'
            mix_top.blend_type = 'MIX'
            mix_top.location = (current_x, 200)
            mix_top.label = "Top (Green)"
            links.new(current_color, mix_top.inputs[6])  # A
            links.new(top_tex.outputs['Color'], mix_top.inputs[7])  # B
            links.new(power_node.outputs[0], mix_top.inputs['Factor'])
            current_color = mix_top.outputs[2]
            current_x += 250
        
        # Blend Extras texture using Blue channel
        if extras_tex and use_extras:
            # Apply blend power to blue mask
            power_node = nodes.new('ShaderNodeMath')
            power_node.operation = 'POWER'
            power_node.location = (-700, -400)
            power_node.inputs[1].default_value = blue_power
            links.new(separate_rgb.outputs['Blue'], power_node.inputs[0])
            
            # Mix with blue channel mask
            mix_extras = nodes.new('ShaderNodeMix')
            mix_extras.data_type = 'RGBA'
            mix_extras.blend_type = 'MIX'
            mix_extras.location = (current_x, 200)
            mix_extras.label = "Extras (Blue)"
            links.new(current_color, mix_extras.inputs[6])  # A
            links.new(extras_tex.outputs['Color'], mix_extras.inputs[7])  # B
            links.new(power_node.outputs[0], mix_extras.inputs['Factor'])
            current_color = mix_extras.outputs[2]
        
        # Connect final color to BSDF
        if current_color:
            links.new(current_color, bsdf_node.inputs['Base Color'])
    
    def _load_texture(self, material, nodes, links, texture_path: str, bsdf_node) -> Optional[bpy.types.Node]:
        """Legacy method - load texture and connect to BSDF directly"""
        tex_node = self._load_texture_node(material, nodes, links, texture_path, "UVMap")
        if tex_node:
            links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
            links.new(tex_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        return tex_node
    
    def _load_texture_from_path(self, material, nodes, texture_path: str, 
                                extension: str = 'REPEAT') -> Optional[bpy.types.Node]:
        """
        Load a texture and create an image texture node WITHOUT connecting UV.
        Caller is responsible for connecting the Vector input.
        
        Returns:
            ShaderNodeTexImage node or None
        """
        if not self.assets_folder:
            return None
        
        full_tex_path = resolve_texture_path(texture_path, self.assets_folder)
        if not full_tex_path:
            return None
        
        png_path = None
        file_ext = os.path.splitext(full_tex_path)[1].lower()
        
        if file_ext == '.tex':
            png_path = self.tex_converter.convert_tex_to_png(full_tex_path)
            if not png_path:
                base_path = os.path.splitext(full_tex_path)[0]
                for alt_ext in ['.dds', '.png']:
                    alt_path = base_path + alt_ext
                    if os.path.exists(alt_path):
                        png_path = alt_path
                        break
        elif file_ext == '.dds':
            base_path = os.path.splitext(full_tex_path)[0]
            png_alt = base_path + '.png'
            if os.path.exists(png_alt):
                png_path = png_alt
            else:
                png_path = self.tex_converter.convert_dds_to_png(full_tex_path)
                if not png_path:
                    png_path = full_tex_path
        elif file_ext == '.png':
            png_path = full_tex_path
        else:
            png_path = full_tex_path
        
        if not png_path:
            return None
        
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.extension = extension
        
        try:
            img = bpy.data.images.load(png_path, check_existing=True)
            tex_node.image = img
            return tex_node
        except Exception as e:
            print(f"  Error loading texture {os.path.basename(png_path)}: {e}")
        
        return None
    
    def _load_texture_node(self, material, nodes, links, texture_path: str, 
                            uv_map_name: str = "UVMap", extension: str = 'REPEAT') -> Optional[bpy.types.Node]:
        """
        Load a texture and create an image texture node with UV map selection.
        Does NOT connect to BSDF - caller handles connections.
        
        Args:
            material: Blender material
            nodes: Node tree nodes
            links: Node tree links  
            texture_path: Path to texture (from materials file)
            uv_map_name: Name of the UV map to use for sampling
            extension: Texture extension mode ('REPEAT', 'CLIP', 'EXTEND')
        
        Returns:
            ShaderNodeTexImage node or None
        """
        if not self.assets_folder:
            return None
        
        # Resolve texture path (tries .tex -> .dds -> .png)
        full_tex_path = resolve_texture_path(texture_path, self.assets_folder)
        if not full_tex_path:
            print(f"  Warning: Could not find texture: {texture_path}")
            return None
        
        png_path = None
        file_ext = os.path.splitext(full_tex_path)[1].lower()
        
        # Handle different file types
        if file_ext == '.tex':
            png_path = self.tex_converter.convert_tex_to_png(full_tex_path)
            if not png_path:
                base_path = os.path.splitext(full_tex_path)[0]
                for alt_ext in ['.dds', '.png']:
                    alt_path = base_path + alt_ext
                    if os.path.exists(alt_path):
                        png_path = alt_path
                        break
        elif file_ext == '.dds':
            base_path = os.path.splitext(full_tex_path)[0]
            png_alt = base_path + '.png'
            if os.path.exists(png_alt):
                png_path = png_alt
            else:
                png_path = self.tex_converter.convert_dds_to_png(full_tex_path)
                if not png_path:
                    png_path = full_tex_path
        elif file_ext == '.png':
            png_path = full_tex_path
        else:
            png_path = full_tex_path
        
        if not png_path:
            return None
        
        # Create UV Map node to select the right UV channel
        uv_node = nodes.new('ShaderNodeUVMap')
        uv_node.uv_map = uv_map_name
        
        # Create image texture node
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.extension = extension
        
        # Connect UV to texture
        links.new(uv_node.outputs['UV'], tex_node.inputs['Vector'])
        
        # Load image
        try:
            img = bpy.data.images.load(png_path, check_existing=True)
            tex_node.image = img
            
            # Position UV node next to texture node (will be repositioned by caller)
            uv_node.location = (tex_node.location[0] - 200, tex_node.location[1])
            uv_node.label = uv_map_name
            
            return tex_node
        except Exception as e:
            print(f"  Error loading texture {os.path.basename(png_path)}: {e}")
        
        return None
    
    def get_or_create_material(self, mat_name: str, materials_db: Dict[str, dict],
                               lightmap_texture: str = None,
                               lightmap_color_scale: float = 1.0,
                               texture_overrides: Dict[str, str] = None,
                               baked_paint_scale: tuple = (1.0, 1.0),
                               baked_paint_bias: tuple = (0.0, 0.0)) -> Optional[bpy.types.Material]:
        """
        Get or create a material by name from the materials database
        
        Args:
            mat_name: Material name to look up
            materials_db: Materials database from JSON
            lightmap_texture: Path to lightmap texture for this mesh
            lightmap_color_scale: Global lightmap intensity multiplier
            texture_overrides: Dict of sampler_name -> texture_path overrides from mesh
            baked_paint_scale: Per-mesh UV scale for baked paint texture
            baked_paint_bias: Per-mesh UV offset for baked paint texture
        
        Returns:
            Blender material or None
        """
        # Try exact match first
        if mat_name in materials_db:
            return self.create_blender_material(mat_name, materials_db[mat_name],
                                                lightmap_texture, lightmap_color_scale,
                                                texture_overrides,
                                                baked_paint_scale, baked_paint_bias)
        
        # Try case-insensitive search
        mat_name_lower = mat_name.lower()
        for key, value in materials_db.items():
            if key.lower() == mat_name_lower:
                return self.create_blender_material(key, value,
                                                    lightmap_texture, lightmap_color_scale,
                                                    texture_overrides,
                                                    baked_paint_scale, baked_paint_bias)
        
        # Material not found - create a simple material
        print(f"  Warning: Material not found in database: {mat_name}")
        if mat_name not in self.materials_cache:
            bl_mat = bpy.data.materials.get(mat_name)
            if bl_mat is None:
                bl_mat = bpy.data.materials.new(name=mat_name)
                bl_mat.use_nodes = True
                # Set to a distinct color to indicate missing material
                bsdf = bl_mat.node_tree.nodes.get('Principled BSDF')
                if bsdf:
                    bsdf.inputs['Base Color'].default_value = (1.0, 0.0, 1.0, 1.0)  # Magenta
            self.materials_cache[mat_name] = bl_mat
        
        return self.materials_cache[mat_name]
