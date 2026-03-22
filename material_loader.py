"""
Material Loader for Mapgeo Addon
Loads materials from .materials.bin or .materials.py files and creates Blender materials
"""

import json
import math
import os
import re
import bpy
from typing import Dict, Optional
from .texture_utils import TexConverter, resolve_texture_path


def _log():
    """Lazy accessor for the debug log singleton."""
    from .debug_system import get_debug_log
    return get_debug_log()


def _fnv1a_32(s: str) -> int:
    """Compute FNV-1a 32-bit hash (lowercase). Used by League .bin files for path hashing."""
    s = s.lower()
    h = 0x811c9dc5
    for c in s:
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _is_hash_key(key: str) -> bool:
    """Check if a dictionary key is a hash (e.g. '0x0221ffad' or '{c406a533}')."""
    if not key:
        return False
    if key.startswith('0x') and len(key) == 10:
        try:
            int(key, 16)
            return True
        except ValueError:
            return False
    if key.startswith('{') and key.endswith('}') and len(key) == 10:
        return True
    return False


class MaterialLoader:
    """Loads and creates Blender materials from League .materials.bin files"""
    
    def __init__(self, assets_folder: str = "", levels_folder: str = "",
                 map_py_path: str = "", dragon_layer: str = "LAYER_1", custom_assets_folder: str = "", prioritize_custom: bool = False):
        self.assets_folder = assets_folder
        self.custom_assets_folder = custom_assets_folder
        self.prioritize_custom = prioritize_custom
        self.levels_folder = levels_folder
        self.map_py_path = map_py_path
        self.dragon_layer = dragon_layer  # e.g. 'LAYER_1' (base), 'LAYER_2' (Inferno), etc.
        self.tex_converter = TexConverter()
        self.materials_cache = {}  # Cache loaded materials
        self._grass_tint_cache = None  # Cache parsed grass tint info
    
    def load_materials(self, file_path: str) -> Dict[str, dict]:
        """
        Load materials from a .materials.bin file.
        
        Returns:
            Dictionary of material_name -> material_data
        """
        self._materials_path = file_path  # Store for grass tint chain
        return self._load_materials_bin(file_path)

    def load_materials_from_prey(self, prey_dir: str, base_name: str,
                                  materials_path: str = "") -> Dict[str, dict]:
        """Load materials from .prey.materials file.

        Args:
            prey_dir: Directory containing .prey.* files
            base_name: Base name for prey files
            materials_path: Original materials path (stored for grass tint chain)

        Returns:
            Dictionary of material_name -> material_data
        """
        if materials_path:
            self._materials_path = materials_path
        try:
            from . import prey_format
            materials = prey_format.load_materials_db_from_prey(prey_dir, base_name)
            _log().info("Material", f"Loaded {len(materials)} materials from prey ({base_name}.prey.materials)")
            return materials
        except Exception as e:
            _log().error("Material", f"Error loading materials from prey: {e}")
            return {}
    
    def _load_materials_bin(self, bin_path: str) -> Dict[str, dict]:
        """
        Load materials directly from a binary .materials.bin file.
        Parses with propertybin_parser and converts to normalized material dicts.
        """
        try:
            from . import project_manager
            materials = project_manager.load_materials_from_bin(bin_path)
            _log().info("Material", f"Loaded {len(materials)} materials from binary {os.path.basename(bin_path)}")
            return materials
        except Exception as e:
            _log().error("Material", f"Error loading materials.bin: {e}")
            return {}
    
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
            return self._load_map_settings_bin(file_path)
    
    def _load_map_settings_bin(self, bin_path: str) -> dict:
        """Parse map settings from a binary .materials.bin (or any .bin) file.
        
        Looks for MapSunProperties, MapBakeProperties, and MapLightingV2
        entries in the propertybin data.
        """
        settings = {}
        try:
            from . import project_manager
            data = project_manager.load_map_settings_from_bin(bin_path)
            if data:
                settings.update(data)
                _log().info("MapSettings", f"Loaded map settings from {os.path.basename(bin_path)}")
                if 'lightmap_color_scale' in settings:
                    _log().info("MapSettings", f"lightMapColorScale: {settings['lightmap_color_scale']}")
            return settings
        except Exception as e:
            _log().error("MapSettings", f"Error loading map settings from bin: {e}")
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
                _log().info("MapSettings", f"Loaded map settings from {os.path.basename(py_path)}")
                if 'lightmap_color_scale' in settings:
                    _log().info("MapSettings", f"lightMapColorScale: {settings['lightmap_color_scale']}")
            return settings
        except Exception as e:
            _log().error("MapSettings", f"Error loading map settings from .py: {e}")
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
            Dictionary of material_name -> material_data
        """
        materials = {}
        
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            def _iter_blocks(content: str, block_type: str):
                blocks = []
                pattern = re.compile(rf'{re.escape(block_type)}\s*\{{')

                for match in pattern.finditer(content):
                    start_idx = match.end() - 1
                    brace_depth = 0
                    end_idx = None

                    for idx in range(start_idx, len(content)):
                        char = content[idx]
                        if char == '{':
                            brace_depth += 1
                        elif char == '}':
                            brace_depth -= 1
                            if brace_depth == 0:
                                end_idx = idx
                                break

                    if end_idx is None:
                        continue

                    blocks.append(content[start_idx + 1:end_idx])

                return blocks

            # Find all StaticMaterialDef blocks
            # Match both quoted names: "Material/Path" = StaticMaterialDef {
            # AND hashed keys:        0x0221ffad = StaticMaterialDef {
            mat_pattern = re.compile(
                r'(?:"([^"]+)"|((0x[0-9a-fA-F]{8})))\s*=\s*StaticMaterialDef\s*\{',
                re.MULTILINE
            )
            
            hash_resolved = 0
            for match in mat_pattern.finditer(content):
                mat_name = match.group(1)  # Quoted name
                hash_key = match.group(2)  # Hex hash key (e.g. 0x0221ffad)
                is_hashed = mat_name is None
                if is_hashed:
                    mat_name = hash_key  # Temporary — will extract real name from body
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
                
                # Build normalized material dict
                mat_data = {
                    '__type': 'StaticMaterialDef',
                    'name': mat_name,
                    'samplerValues': [],
                    'paramValues': [],
                    'shaderMacros': {},
                    'switches': {},
                    'techniques': [],
                    'childTechniques': [],
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
                # Use _iter_blocks for proper nested brace handling
                # (vec4 = { ... } is nested inside the param block)
                for param_body in _iter_blocks(body, "StaticMaterialShaderParamDef"):
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

                # Parse techniques
                for technique_content in _iter_blocks(body, "StaticMaterialTechniqueDef"):
                    name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', technique_content)
                    if not name_match:
                        continue
                    technique = {
                        "name": name_match.group(1),
                        "passes": []
                    }

                    for pass_content in _iter_blocks(technique_content, "StaticMaterialPassDef"):
                        pass_dict = {
                            "shader": "",
                            "blendEnable": False,
                            "cullEnable": False,
                            "srcColorBlendFactor": 1,
                            "srcAlphaBlendFactor": 1,
                            "dstColorBlendFactor": 0,
                            "dstAlphaBlendFactor": 0,
                        }

                        shader_match = re.search(r'shader:\s*link\s*=\s*"([^"]*)"', pass_content)
                        if shader_match:
                            pass_dict["shader"] = shader_match.group(1)

                        blend_match = re.search(r'blendEnable:\s*bool\s*=\s*(true|false)', pass_content)
                        if blend_match:
                            pass_dict["blendEnable"] = blend_match.group(1) == 'true'

                        cull_match = re.search(r'cullEnable:\s*bool\s*=\s*(true|false)', pass_content)
                        if cull_match:
                            pass_dict["cullEnable"] = cull_match.group(1) == 'true'

                        write_mask_match = re.search(r'writeMask:\s*u32\s*=\s*(\d+)', pass_content)
                        if write_mask_match:
                            pass_dict["writeMask"] = int(write_mask_match.group(1))

                        for factor in ['srcColorBlendFactor', 'srcAlphaBlendFactor',
                                       'dstColorBlendFactor', 'dstAlphaBlendFactor']:
                            factor_match = re.search(rf'{factor}:\s*u32\s*=\s*(\d+)', pass_content)
                            if factor_match:
                                pass_dict[factor] = int(factor_match.group(1))

                        # Per-pass shader macros
                        pass_macros_match = re.search(
                            r'shaderMacros:\s*map\[string,string\]\s*=\s*\{([^}]+)\}',
                            pass_content
                        )
                        if pass_macros_match:
                            pass_macros = {}
                            for pm in re.finditer(r'"([^"]+)"\s*=\s*"([^"]*)"', pass_macros_match.group(1)):
                                pass_macros[pm.group(1)] = pm.group(2)
                            if pass_macros:
                                pass_dict["shaderMacros"] = pass_macros

                        technique["passes"].append(pass_dict)

                    mat_data['techniques'].append(technique)

                # Parse child techniques
                for child_content in _iter_blocks(body, "StaticMaterialChildTechniqueDef"):
                    name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', child_content)
                    parent_match = re.search(r'parentName:\s*string\s*=\s*"([^"]*)"', child_content)
                    if not name_match or not parent_match:
                        continue

                    child = {
                        "name": name_match.group(1),
                        "parentName": parent_match.group(1),
                        "shaderMacros": {}
                    }

                    macros_match = re.search(r'shaderMacros:\s*map\[string,string\]\s*=\s*\{(.*?)\}', child_content, re.DOTALL)
                    if macros_match:
                        for line in re.finditer(r'"([^"]+)"\s*=\s*"([^"]*)"', macros_match.group(1)):
                            child["shaderMacros"][line.group(1)] = line.group(2)

                    mat_data['childTechniques'].append(child)
                
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
                
                # For hashed keys, extract the real name from the body
                if is_hashed:
                    name_in_body = re.search(r'name:\s*string\s*=\s*"([^"]+)"', body)
                    if name_in_body:
                        real_name = name_in_body.group(1)
                        mat_data['name'] = real_name
                        # Store under both hash key (fallback) and real name (primary)
                        materials[hash_key] = mat_data
                        mat_name = real_name
                        hash_resolved += 1
                
                materials[mat_name] = mat_data
            
            if hash_resolved:
                _log().info("Material", f"Resolved {hash_resolved} hashed material name(s) from .py")
            _log().info("Material", f"Loaded {len(materials)} static materials from {os.path.basename(py_path)}")
            return materials
        
        except Exception as e:
            _log().error("Material", f"Error loading materials .py: {e}")
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

    def _is_placeholder_texture_path(self, tex_path: str) -> bool:
        """Return True for engine placeholder/default textures that should count as unassigned."""
        if not tex_path:
            return True
        p = tex_path.replace('\\', '/').lower().strip()
        if not p:
            return True

        placeholder_tokens = (
            'bc_testtexture',
            'atlast_test',
            '/shared/materials/white',
            '/shared/materials/black',
            '/shared/materials/default',
            '/shared/materials/blank',
            '/shared/materials/null',
        )
        return any(tok in p for tok in placeholder_tokens)
    
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

    def _get_primary_pass_blend_state(self, mat_data: dict) -> dict:
        """Return blend state/factors from the primary pass.

        Prefers top-level normalized fields; falls back to techniques[0].passes[0].
        """
        state = {
            'blendEnable': bool(mat_data.get('blendEnable', False)),
            'srcColorBlendFactor': mat_data.get('srcColorBlendFactor', 1),
            'dstColorBlendFactor': mat_data.get('dstColorBlendFactor', 0),
            'srcAlphaBlendFactor': mat_data.get('srcAlphaBlendFactor', 1),
            'dstAlphaBlendFactor': mat_data.get('dstAlphaBlendFactor', 0),
        }

        techniques = mat_data.get('techniques', [])
        if techniques and isinstance(techniques, list):
            passes = techniques[0].get('passes', [])
            if passes and isinstance(passes, list):
                p0 = passes[0]
                state['blendEnable'] = bool(p0.get('blendEnable', state['blendEnable']))
                state['srcColorBlendFactor'] = int(p0.get('srcColorBlendFactor', state['srcColorBlendFactor']))
                state['dstColorBlendFactor'] = int(p0.get('dstColorBlendFactor', state['dstColorBlendFactor']))
                state['srcAlphaBlendFactor'] = int(p0.get('srcAlphaBlendFactor', state['srcAlphaBlendFactor']))
                state['dstAlphaBlendFactor'] = int(p0.get('dstAlphaBlendFactor', state['dstAlphaBlendFactor']))

        return state
    
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
        In .bin format: entry with type_hash 0xdde8c114 (mapContainer)
        
        Returns the container key string or empty string.
        """
        try:
            if materials_path.endswith('.py'):
                with open(materials_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                m = re.search(r'"([^"]+)"\s*=\s*mapContainer\s*\{', content)
                if m:
                    return m.group(1)
            elif materials_path.endswith('.bin'):
                from . import propertybin_parser
                data = propertybin_parser.parse_bin(materials_path)
                for entry in data.get('entries', []):
                    if entry.get('type_hash') == '0xdde8c114':  # mapContainer
                        fields = entry.get('fields', [])
                        for f in fields:
                            h = f.get('name_hash_int', 0)
                            # 0xcc5e808a is the link field containing the
                            # container path (e.g. Maps/MapGeometry/Map11/...)
                            if h == 0xcc5e808a and f.get('type') == 16:
                                val = f.get('value', '')
                                if val:
                                    return str(val)
                            # 0x8d39bde6 is the name field (fallback)
                            if h == 0x8d39bde6:
                                val = f.get('value', '')
                                if val:
                                    return str(val)
                        return entry.get('path_hash', '')
        except Exception as e:
            _log().error("GrassTint", f"Error extracting mapContainer: {e}")
        return ''
    
    # Grass tint hash constants (FNV-1a 32-bit)
    _HASH_MAP_SKIN             = 0xcd19ef3c  # MapSkin
    _HASH_MAP_CONTAINER_LINK   = 0x960efd81  # mMapContainerLink
    _HASH_GRASS_TINT_TEXTURE   = 0xbac3a0fa  # mGrassTintTexture
    _HASH_ALTERNATE_ASSETS     = 0xc7c088eb  # mAlternateAssets
    _HASH_MAP_ALTERNATE_ASSET  = 0xe54c014f  # MapAlternateAsset
    _HASH_GRASS_TINT_TEX_NAME  = 0xdcabad81  # mGrassTintTextureName
    _HASH_VISIBILITY_FLAG_NAME = 0x97472c4d  # mVisibilityFlagName

    def _parse_map_file_grass_tints(self, map_file_path: str, container_name: str) -> dict:
        """
        Parse a map*.py or map*.bin file to find the MapSkin whose mMapContainerLink
        matches container_name, then extract grass tint texture paths.
        
        Returns dict:
            {
                'base': 'GrassTint_SRX.something.dds',
                'alternates': {
                    'Fire': 'ASSETS/Maps/Info/Map11/GrassTint_SRX_Infernal.tex',
                    'earth': 'ASSETS/Maps/Info/Map11/GrassTint_SRX_Mountain.tex',
                    ...
                }
            }
        """
        result = {'base': '', 'alternates': {}}

        if map_file_path.lower().endswith('.bin'):
            return self._parse_map_bin_grass_tints(map_file_path, container_name)
        
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
                _log().info("GrassTint", f"Found matching MapSkin: {skin_name}")
                
                # Extract base grass tint texture
                base_match = re.search(r'mGrassTintTexture:\s*string\s*=\s*"([^"]+)"', skin_body)
                if base_match:
                    result['base'] = base_match.group(1)
                    _log().info("GrassTint", f"Base: {result['base']}")
                
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
                        _log().info("GrassTint", f"{flag_name}: {tint_path}")
                
                # Found our matching skin, no need to continue
                break
        
        except Exception as e:
            _log().error("GrassTint", f"Error parsing map file: {e}")
        
        return result

    def _parse_map_bin_grass_tints(self, bin_path: str, container_name: str) -> dict:
        """Parse a map*.bin file for grass tint textures (binary propertybin format)."""
        result = {'base': '', 'alternates': {}}

        try:
            from . import propertybin_parser
            data = propertybin_parser.parse_bin(bin_path)
        except Exception as e:
            _log().error("GrassTint", f"Error parsing bin file: {e}")
            return result

        def _get_field(fields, hash_int):
            if not fields:
                return None
            for f in fields:
                if f.get('name_hash_int') == hash_int:
                    return f
            return None

        for entry in data.get('entries', []):
            type_hash_str = entry.get('type_hash', '')
            try:
                type_hash_int = int(type_hash_str, 16) if type_hash_str.startswith('0x') else 0
            except ValueError:
                continue

            if type_hash_int != self._HASH_MAP_SKIN:
                continue

            fields = entry.get('fields', [])

            # Check mMapContainerLink
            link_f = _get_field(fields, self._HASH_MAP_CONTAINER_LINK)
            if not link_f:
                continue
            link_val = str(link_f.get('value', ''))
            if link_val != container_name:
                continue

            skin_name = entry.get('path_hash', '')
            _log().info("GrassTint", f"Found matching MapSkin (bin): {skin_name}")

            # Base grass tint texture
            base_f = _get_field(fields, self._HASH_GRASS_TINT_TEXTURE)
            if base_f:
                result['base'] = str(base_f.get('value', ''))
                _log().info("GrassTint", f"Base: {result['base']}")

            # Alternate assets (dragon grass tints)
            alt_f = _get_field(fields, self._HASH_ALTERNATE_ASSETS)
            if alt_f:
                for alt_item in alt_f.get('values', []):
                    alt_fields = alt_item.get('fields', [])
                    if not alt_fields:
                        continue
                    tint_f = _get_field(alt_fields, self._HASH_GRASS_TINT_TEX_NAME)
                    flag_f = _get_field(alt_fields, self._HASH_VISIBILITY_FLAG_NAME)
                    if tint_f and flag_f:
                        flag_name = str(flag_f.get('value', ''))
                        tint_path = str(tint_f.get('value', ''))
                        if flag_name and tint_path:
                            result['alternates'][flag_name] = tint_path
                            _log().info("GrassTint", f"{flag_name}: {tint_path}")

            break  # Found our matching skin

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
                _log().info("GrassTint", f"Using dragon variant ({flag_name}): {os.path.basename(resolved)}")
                return resolved
            _log().warning("GrassTint", f"Dragon variant {flag_name} texture not found", detail=alt_path)
        
        # Modern Riot bins often store the base tint as an ASSETS path, while
        # older files stored only a filename that lives under levels/.../info.
        if base_name:
            if str(base_name).upper().startswith('ASSETS/'):
                resolved = self._resolve_assets_path(base_name)
                if resolved:
                    _log().info("GrassTint", f"Using base ASSETS path: {os.path.basename(resolved)}")
                    return resolved
            resolved = self._resolve_base_grass_tint(base_name)
            if resolved:
                return resolved
        
        return ''
    
    def _resolve_assets_path(self, asset_path: str) -> str:
        """Resolve an ASSETS/ prefixed path to a real file."""
        if not asset_path:
            return ''
        rel_path = str(asset_path).replace('\\', '/')
        if rel_path.upper().startswith('ASSETS/'):
            rel_path = rel_path[7:]

        search_roots = []
        if self.prioritize_custom:
            search_roots.extend([self.custom_assets_folder, self.assets_folder])
        else:
            search_roots.extend([self.assets_folder, self.custom_assets_folder])

        for root in search_roots:
            if not root:
                continue
            full_path = os.path.join(root, rel_path.replace('/', os.sep))
            if os.path.exists(full_path):
                return full_path
            found = self._find_file_case_insensitive(root, rel_path)
            if found:
                return found
        return ''
    
    def _resolve_base_grass_tint(self, base_name: str) -> str:
        """
        Resolve a base grass tint filename (no path) to a real file.
        Base texture lives in levels_folder (e.g. levels/map11/info/)
        
        Example legacy value:
            "GrassTint_SRX.SRT_2024_Strategy_Differentiation_Preseason.dds"
            -> "levels/map11/info/GrassTint_SRX.SRT_2024_Strategy_Differentiation_Preseason.dds"
        """
        _log().info("GrassTint", f"Resolving base: {base_name}")
        _log().info("GrassTint", f"levels_folder: {self.levels_folder}")
        
        if not base_name:
            return ''

        if str(base_name).upper().startswith('ASSETS/'):
            return self._resolve_assets_path(base_name)
        
        # Extract stem and extension using proper splitext (handles multi-dot names)
        name_stem, name_ext = os.path.splitext(base_name)
        
        # Build variants: try original, then with .tex/.dds/.png extensions
        variants = [base_name]
        for alt_ext in ['.tex', '.dds', '.png']:
            if alt_ext.lower() != name_ext.lower():
                variants.append(name_stem + alt_ext)
        
        _log().info("GrassTint", f"Trying variants: {variants}")
        
        # Search levels_folder first (primary location for base grass tint)
        if self.levels_folder:
            if not os.path.isdir(self.levels_folder):
                _log().error("GrassTint", "levels_folder is not a directory!")
                return ''
            
            # Try exact filename match (case-sensitive)
            for variant in variants:
                full_path = os.path.join(self.levels_folder, variant)
                if os.path.exists(full_path):
                    _log().info("GrassTint", f"Found: {variant}")
                    return full_path
            
            # Try case-insensitive match
            try:
                dir_entries = os.listdir(self.levels_folder)
                _log().info("GrassTint", f"levels_folder contains {len(dir_entries)} files")
            except OSError as e:
                _log().error("GrassTint", f"Cannot list levels_folder: {e}")
                return ''
            
            lower_variants = {v.lower() for v in variants}
            for f in dir_entries:
                if f.lower() in lower_variants:
                    found = os.path.join(self.levels_folder, f)
                    _log().info("GrassTint", f"Found (case-insensitive): {f}")
                    return found
            
            # Try partial match on the base name (without extension)
            base_lower = base_name.lower()
            for f in dir_entries:
                if base_lower in f.lower():
                    found = os.path.join(self.levels_folder, f)
                    _log().info("GrassTint", f"Found (partial match): {f}")
                    return found
            
            # Try recursive search in subdirectories (e.g., levels/map11/info/)
            _log().info("GrassTint", "Searching recursively in levels_folder...")
            import glob
            for variant in variants:
                pattern = os.path.join(self.levels_folder, '**', variant)
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    _log().info("GrassTint", f"Found (recursive): {os.path.basename(matches[0])}")
                    _log().info("GrassTint", f"Full path: {matches[0]}")
                    return matches[0]
            
            _log().warning("GrassTint", "Not found in levels_folder (even recursively)")
        else:
            _log().warning("GrassTint", "levels_folder not set!")
        
        # Fallback: search assets folder recursively (slower, shouldn't normally be needed)
        if self.assets_folder:
            _log().info("GrassTint", "Trying assets_folder as fallback...")
            import glob
            for variant in variants:
                matches = glob.glob(os.path.join(self.assets_folder, '**', variant), recursive=True)
                if matches:
                    _log().info("GrassTint", f"Found in assets: {os.path.basename(matches[0])}")
                    return matches[0]
        
        _log().warning("GrassTint", "Base grass tint not found anywhere!")
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
        materials -> mapContainer name -> map*.py/bin -> MapSkin -> grass tint
        
        Falls back to Riot WAD cache if map file is not in the project folder.
        """
        map_path = self.map_py_path
        
        # If no map file set, try to auto-discover it from project settings
        if (not map_path or not os.path.exists(map_path)):
            map_path = self._find_map_file_from_riot_wad()
        
        if not map_path or not os.path.exists(map_path):
            return ''
        
        # We need to know the mapContainer name from the materials file
        # The materials path is stored when load_materials was called
        if not hasattr(self, '_materials_path') or not self._materials_path:
            return ''
        
        container_name = self._extract_map_container_name(self._materials_path)
        if not container_name:
            _log().warning("GrassTint", "No mapContainer found in materials file")
            return ''
        
        _log().info("GrassTint", f"mapContainer: {container_name}")
        
        grass_tint_info = self._parse_map_file_grass_tints(map_path, container_name)
        if not grass_tint_info.get('base') and not grass_tint_info.get('alternates'):
            _log().warning("GrassTint", "No grass tint textures found in map file")
            return ''
        
        return self._resolve_grass_tint_path(grass_tint_info)

    def _find_map_file_from_riot_wad(self) -> str:
        """Try to find a map*.bin file from Riot WAD cache via project settings."""
        try:
            import bpy
            if not hasattr(bpy.context, 'scene') or not hasattr(bpy.context.scene, 'project_settings'):
                return ''
            ps = bpy.context.scene.project_settings
            if not ps.use_riot_base or not ps.project_map_id or not ps.league_install:
                return ''
            
            from . import project_manager
            league_path = bpy.path.abspath(ps.league_install)
            map_id_lower = ps.project_map_id.lower()
            
            riot_cache = project_manager._ensure_riot_wad_cache(league_path, ps.project_map_id)
            if not riot_cache:
                return ''
            
            for sub_path in [
                os.path.join("data", "maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
                os.path.join("maps", "shipping", map_id_lower, f"{map_id_lower}.bin"),
            ]:
                candidate = os.path.join(riot_cache, sub_path)
                if os.path.isfile(candidate):
                    _log().info("GrassTint", f"Found map file from Riot WAD: {candidate}")
                    return candidate
        except Exception:
            pass
        return ''
    
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
                _log().info("GrassTint", f"Found grass tint texture (fallback): {os.path.basename(matches[0])}")
                return matches[0]
        
        # Check levels folder
        if self.levels_folder and os.path.isdir(self.levels_folder):
            for f in os.listdir(self.levels_folder):
                if 'grasstint' in f.lower():
                    found = os.path.join(self.levels_folder, f)
                    _log().info("GrassTint", f"Found grass tint texture (levels): {f}")
                    return found
        
        return ''
    
    @staticmethod
    def update_grass_tint_for_dragon(settings) -> int:
        """
        Update grass tint texture on all materials that have a 'Grass Tint (World UV)' node.
        Called when dragon layer filter changes.
        
        Args:
            settings: MapgeoSettings with assets_folder, levels_folder, map_py_path,
                      materials_file_path, dragon_layer_filter
        
        Returns:
            Number of materials updated
        """
        assets_folder = getattr(settings, 'assets_folder', '')
        levels_folder = getattr(settings, 'levels_folder', '')
        map_py_path = getattr(settings, 'map_py_path', '')
        materials_path = getattr(settings, 'materials_file_path', '')
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
            dragon_layer=dragon_layer,
            custom_assets_folder=getattr(settings, 'custom_assets_folder', ''),
            prioritize_custom=getattr(settings, 'prioritize_custom_assets', False)
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
        
        # Load the image
        try:
            if new_path.lower().endswith('.tex'):
                new_img = loader.tex_converter.load_tex_as_blender_image(new_path)
            else:
                new_img = bpy.data.images.load(new_path, check_existing=True)
            if new_img:
                new_img.colorspace_settings.name = 'sRGB'
        except Exception as e:
            new_img = None
            _log().error("GrassTint", f"Could not load grass tint image: {e}")
        
        if not new_img:
            _log().error("GrassTint", f"Failed to load grass tint texture", detail=new_path)
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
            _log().info("GrassTint", f"Switched {updated} materials to {dragon_name} grass tint: {os.path.basename(new_path)}")
        
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
        bsdf_node.inputs['Emission Strength'].default_value = 0.0
        
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
        
        # Shader macros
        shader_macros = mat_data.get('shaderMacros', {})
        has_baked_lighting = 'NO_BAKED_LIGHTING' not in shader_macros
        
        # Determine shader type
        shader_name = self._get_shader_short_name(mat_data)
        
        # Store League material data for editor compatibility
        bl_mat["league_material_name"] = mat_name
        bl_mat["league_material_type"] = mat_data.get('type', 0)

        samplers_json = []
        for sampler in mat_data.get('samplerValues', []):
            tex_name = sampler.get('textureName', sampler.get('TextureName', ''))
            tex_path = sampler.get('texturePath', '')
            if not tex_name and not tex_path:
                continue
            samplers_json.append({
                "textureName": tex_name,
                "texturePath": tex_path,
                "addressU": sampler.get('addressU', 1),
                "addressV": sampler.get('addressV', 1),
                "addressW": sampler.get('addressW', 1),
            })
        bl_mat["samplers"] = json.dumps(samplers_json)

        params_json = []
        for param in mat_data.get('paramValues', []):
            if 'name' not in param:
                continue
            param_entry = {"name": param.get('name', '')}
            if 'value' in param:
                param_entry["value"] = param.get('value')
            params_json.append(param_entry)
        bl_mat["parameters"] = json.dumps(params_json)

        switches_raw = mat_data.get('switches', {})
        switches_json = []
        if isinstance(switches_raw, dict):
            for name, enabled in switches_raw.items():
                switches_json.append({"name": name, "on": bool(enabled)})
        elif isinstance(switches_raw, list):
            for sw in switches_raw:
                if isinstance(sw, dict) and "name" in sw:
                    switches_json.append({"name": sw.get("name", ""), "on": bool(sw.get("on", False))})
        bl_mat["switches"] = json.dumps(switches_json)

        shader_macros = mat_data.get('shaderMacros', {})
        if shader_macros:
            bl_mat["shader_macros"] = json.dumps(shader_macros)

        techniques = mat_data.get('techniques', [])
        if techniques:
            bl_mat["techniques"] = json.dumps(techniques)

        child_techniques = mat_data.get('childTechniques', mat_data.get('child_techniques', []))
        if child_techniques:
            bl_mat["child_techniques"] = json.dumps(child_techniques)

        # Snapshot for dirty-tracking: store the exact property strings at load
        # time so save_prey_materials can detect what actually changed.
        bl_mat["_material_snapshot"] = json.dumps({
            "samplers": bl_mat.get("samplers", "[]"),
            "parameters": bl_mat.get("parameters", "[]"),
            "switches": bl_mat.get("switches", "[]"),
            "shader_macros": bl_mat.get("shader_macros", "{}"),
            "techniques": bl_mat.get("techniques", "[]"),
            "child_techniques": bl_mat.get("child_techniques", "[]"),
            "type": mat_data.get('type', 0),
        })

        # Store lightmap metadata for editor rebuild support
        if lightmap_texture:
            bl_mat["lightmap_texture"] = lightmap_texture
        if lightmap_color_scale != 1.0:
            bl_mat["lightmap_color_scale"] = lightmap_color_scale
        
        # --- Dispatch to shader-specific builder ---
        if shader_name in ('ENV_Glass', 'ENV_Glass_Vertex_Offset', 'ENV_Glass_Diffuse',
                           'DefaultEnv_Glass_BlendAndReflection'):
            self._build_glass_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('ENV_GlowSign', 'ENV_GlowSign_Atlas'):
            self._build_glow_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('DefaultEnv_Glow',):
            self._build_defaultenv_glow(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('Emissive_Basic',):
            self._build_emissive_basic(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('Hologram', 'Hologram_Rotate'):
            self._build_hologram_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'Indicator_Faelights':
            self._build_faelights_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'ENV_UVGradientColorMapping':
            self._build_gradient_color(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('Flowmap_River', 'FlowMap_Radial', 'OD_FlowMap',
                              'TFT_Water', 'TFT_Env_Rain'):
            self._build_water_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                      lightmap_texture, lightmap_color_scale, has_baked_lighting)
        elif shader_name == 'SRX_Blend_Ocean':
            self._build_ocean_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                      lightmap_texture, lightmap_color_scale, has_baked_lighting)
        elif shader_name in ('Env_TwistByNoise', 'TFT_TwistByNoise'):
            self._build_twist_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name == 'DefaultEnv_Flat_BakedTerrain':
            self._build_baked_terrain(bl_mat, nodes, links, bsdf_node, output_node, mat_data,
                                     lightmap_texture, lightmap_color_scale, has_baked_lighting,
                                     baked_paint_scale, baked_paint_bias)
        elif shader_name == 'DefaultEnv_Metal':
            self._build_metal_shader(bl_mat, nodes, links, bsdf_node, output_node, mat_data)
        elif shader_name in ('DefaultEnv_Flat_PlanarReflection', 'TFT_PlanarReflection'):
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
        
        # Render method based on blend factors:
        #   blendEnable + src=1(ONE), dst=7(INV_DST_ALPHA)  → DITHERED
        #   blendEnable + src=6(DST_ALPHA), dst=7(INV_DST_ALPHA) → BLENDED (Indicator_Faelights) or DITHERED
        #   blendEnable (other combos) → BLENDED
        #   no blend → DITHERED (opaque)
        # addressU=1 + addressV=1 on diffuse sampler forces BLENDED (Clamp mode)
        # Exception: BakedTerrain uses clip for UV clamping but stays DITHERED (opaque terrain)
        diffuse_sampler = (self._get_sampler_data(mat_data, 'DiffuseTexture') or 
                           self._get_sampler_data(mat_data, 'Diffuse_Texture') or
                           self._get_sampler_data(mat_data, 'BAKED_DIFFUSE_TEXTURE'))
        needs_clip_blend = (self._sampler_needs_clip(diffuse_sampler) 
                            and shader_name != 'DefaultEnv_Flat_BakedTerrain')
        
        blend_state = self._get_primary_pass_blend_state(mat_data)
        blend_on = blend_state['blendEnable']
        src_c = blend_state['srcColorBlendFactor']
        dst_c = blend_state['dstColorBlendFactor']
        src_a = blend_state['srcAlphaBlendFactor']
        dst_a = blend_state['dstAlphaBlendFactor']

        if not blend_on:
            # No blending → always Dithered (opaque)
            bl_mat.surface_render_method = 'DITHERED'
        elif needs_clip_blend:
            bl_mat.surface_render_method = 'BLENDED'
        elif src_c == 1 and dst_c == 7:
            # ONE / INV_DST_ALPHA → Dithered
            bl_mat.surface_render_method = 'DITHERED'
        elif src_c == 6 and dst_c == 7 and shader_name == 'Indicator_Faelights':
            # DST_ALPHA / INV_DST_ALPHA on Faelights → Blended + overlap
            bl_mat.surface_render_method = 'BLENDED'
        else:
            bl_mat.surface_render_method = 'BLENDED'
            bl_mat.show_transparent_back = False

        # Transparency Overlap: only for Indicator_Faelights with
        # src=6(DST_ALPHA), dst=7(INV_DST_ALPHA) blend factors.
        if hasattr(bl_mat, 'use_transparency_overlap'):
            overlap_on = (
                blend_on and
                src_c == 6 and dst_c == 7 and
                src_a == 6 and dst_a == 7 and
                shader_name == 'Indicator_Faelights'
            )
            bl_mat.use_transparency_overlap = overlap_on

        # EEVEE: disable material shadow casting globally
        try:
            if hasattr(bl_mat, 'shadow_method'):
                bl_mat.shadow_method = 'NONE'
        except Exception:
            pass
        if hasattr(bl_mat, 'use_shadows'):
            bl_mat.use_shadows = False
        if hasattr(bl_mat, 'use_cast_shadows'):
            bl_mat.use_cast_shadows = False
        
        # Cache and return
        self.materials_cache[cache_key] = bl_mat
        _log().material_loaded(mat_name)
        return bl_mat
    
    # =========================================================================
    # Shader-specific builders
    # =========================================================================
    
    def _build_defaultenv_glow(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        DefaultEnv_Glow: Diffuse + Mask → animated glow overlay.
        
        Samplers: Diffuse_Texture, Mask_Texture
        Key params: Glow_Color, Bloom_Factor, Diffuse_Color, UV_Glow_Opacity
        The mask texture alpha drives glow intensity, colored by Glow_Color.
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
        
        if diffuse_ext == 'CLIP':
            bl_mat.surface_render_method = 'BLENDED'
        
        # Diffuse_Color multiplier (default white = no change)
        diffuse_color = self._get_param(mat_data, 'Diffuse_Color', [1.0, 1.0, 1.0, 1.0])
        
        if diffuse_node:
            is_white = all(abs(c - 1.0) < 0.01 for c in diffuse_color[:3])
            if not is_white:
                # Multiply diffuse by Diffuse_Color
                diff_tint = nodes.new('ShaderNodeMix')
                diff_tint.data_type = 'RGBA'
                diff_tint.blend_type = 'MULTIPLY'
                diff_tint.location = (-400, 300)
                diff_tint.inputs['Factor'].default_value = 1.0
                diff_tint.label = "Diffuse × Color"
                links.new(diffuse_node.outputs['Color'], diff_tint.inputs[6])
                diff_tint.inputs[7].default_value = (diffuse_color[0], diffuse_color[1], diffuse_color[2], 1.0)
                links.new(diff_tint.outputs[2], bsdf_node.inputs['Base Color'])
            else:
                links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Base Color'])
            links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        
        # Load mask texture (glow mask)
        mask_path = self._get_sampler_path(mat_data, 'Mask_Texture')
        if mask_path:
            mask_node = self._load_texture_node(bl_mat, nodes, links, mask_path, "UVMap")
            if mask_node:
                mask_node.location = (-700, -100)
                if mask_node.image:
                    mask_node.image.colorspace_settings.name = 'Non-Color'
                
                # Glow parameters
                glow_color = self._get_param(mat_data, 'Glow_Color', [0.451, 0.526, 0.741, 1.0])
                bloom_factor = self._get_param(mat_data, 'Bloom_Factor', [1.0])
                uv_glow_opacity = self._get_param(mat_data, 'UV_Glow_Opacity', [1.0])
                
                # Mask × Glow_Color → Emission
                glow_mix = nodes.new('ShaderNodeMix')
                glow_mix.data_type = 'RGBA'
                glow_mix.blend_type = 'MULTIPLY'
                glow_mix.location = (-400, -100)
                glow_mix.inputs['Factor'].default_value = 1.0
                glow_mix.label = "Mask × Glow Color"
                links.new(mask_node.outputs['Color'], glow_mix.inputs[6])
                glow_mix.inputs[7].default_value = (glow_color[0], glow_color[1], glow_color[2], 1.0)
                
                links.new(glow_mix.outputs[2], bsdf_node.inputs['Emission Color'])
                
                # Emission strength = Bloom_Factor × UV_Glow_Opacity
                strength = (bloom_factor[0] if bloom_factor else 1.0) * (uv_glow_opacity[0] if uv_glow_opacity else 1.0)
                bsdf_node.inputs['Emission Strength'].default_value = min(strength, 10.0)
        else:
            # No mask → use Glow_Color as flat emission
            glow_color = self._get_param(mat_data, 'Glow_Color', [0.451, 0.526, 0.741, 1.0])
            bloom_factor = self._get_param(mat_data, 'Bloom_Factor', [1.0])
            bsdf_node.inputs['Emission Color'].default_value = (glow_color[0], glow_color[1], glow_color[2], 1.0)
            bsdf_node.inputs['Emission Strength'].default_value = bloom_factor[0] if bloom_factor else 1.0
    
    def _build_gradient_color(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        ENV_UVGradientColorMapping: No textures, UV-based gradient between two colors.
        
        Uses UV.y (or UV.x with USE_HORIZONTAL_GRADIENT) to blend ColorTop → ColorBottom.
        Fresnel-based alpha with Alpha_Bias + Alpha_Intensity.
        Optional specular highlight.
        """
        color_top = self._get_param(mat_data, 'ColorTop', [0.702, 0.682, 0.769, 1.0])
        color_bottom = self._get_param(mat_data, 'ColorBottom', [0.298, 0.314, 0.529, 1.0])
        remap = self._get_param(mat_data, 'Remap_Gradient', [0.0, 1.0])
        alpha_fresnel = self._get_param(mat_data, 'Alph_Fresnel_Size', [4.0])
        alpha_bias = self._get_param(mat_data, 'Alpha_Bias', [0.9])
        alpha_intensity = self._get_param(mat_data, 'Alpha_Intensity', [1.0])
        spec_size = self._get_param(mat_data, 'Specular_Highlight_Size', [48.0])
        spec_intensity = self._get_param(mat_data, 'Specular_Intensity', [0.16])
        
        switches = mat_data.get('switches', {})
        use_horizontal = switches.get('USE_HORIZONTAL_GRADIENT', False)
        use_alpha = switches.get('USE_ALPHA', False)
        use_spec = switches.get('USE_SPEC', False)
        
        # TexCoord → Separate XYZ → use Y (or X) as gradient factor
        tex_coord = nodes.new('ShaderNodeTexCoord')
        tex_coord.location = (-900, 200)
        
        sep_xyz = nodes.new('ShaderNodeSeparateXYZ')
        sep_xyz.location = (-700, 200)
        links.new(tex_coord.outputs['UV'], sep_xyz.inputs['Vector'])
        
        # Use X for horizontal, Y for vertical gradient
        gradient_axis = sep_xyz.outputs['X'] if use_horizontal else sep_xyz.outputs['Y']
        
        # Map Range to apply Remap_Gradient (min, max)
        remap_min = remap[0] if remap and len(remap) > 0 else 0.0
        remap_max = remap[1] if remap and len(remap) > 1 else 1.0
        
        if abs(remap_min) > 0.001 or abs(remap_max - 1.0) > 0.001:
            map_range = nodes.new('ShaderNodeMapRange')
            map_range.location = (-500, 200)
            map_range.inputs['From Min'].default_value = remap_min
            map_range.inputs['From Max'].default_value = remap_max
            map_range.inputs['To Min'].default_value = 0.0
            map_range.inputs['To Max'].default_value = 1.0
            map_range.clamp = True
            links.new(gradient_axis, map_range.inputs['Value'])
            gradient_factor = map_range.outputs['Result']
        else:
            gradient_factor = gradient_axis
        
        # ColorRamp: Bottom color at 0, Top color at 1
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.location = (-300, 200)
        ramp.color_ramp.elements[0].color = (color_bottom[0], color_bottom[1], color_bottom[2], 1.0)
        ramp.color_ramp.elements[1].color = (color_top[0], color_top[1], color_top[2], 1.0)
        links.new(gradient_factor, ramp.inputs['Fac'])
        
        links.new(ramp.outputs['Color'], bsdf_node.inputs['Base Color'])
        
        # Alpha via Fresnel (if USE_ALPHA)
        if use_alpha:
            fresnel = nodes.new('ShaderNodeFresnel')
            fresnel.location = (-300, -100)
            fresnel_ior = 1.0 + (alpha_fresnel[0] if alpha_fresnel else 4.0) * 0.1
            fresnel.inputs['IOR'].default_value = min(fresnel_ior, 3.0)
            
            # Fresnel × Alpha_Intensity + Alpha_Bias → Alpha
            multiply = nodes.new('ShaderNodeMath')
            multiply.operation = 'MULTIPLY'
            multiply.location = (-100, -100)
            multiply.inputs[1].default_value = alpha_intensity[0] if alpha_intensity else 1.0
            links.new(fresnel.outputs['Fac'], multiply.inputs[0])
            
            add_bias = nodes.new('ShaderNodeMath')
            add_bias.operation = 'ADD'
            add_bias.location = (50, -100)
            add_bias.inputs[1].default_value = alpha_bias[0] if alpha_bias else 0.9
            add_bias.use_clamp = True
            links.new(multiply.outputs[0], add_bias.inputs[0])
            
            links.new(add_bias.outputs[0], bsdf_node.inputs['Alpha'])
            bl_mat.surface_render_method = 'BLENDED'
            bl_mat.show_transparent_back = True
        
        # Specular (if USE_SPEC)
        if use_spec:
            roughness = 1.0 - min((spec_size[0] if spec_size else 48.0) / 128.0, 1.0)
            bsdf_node.inputs['Roughness'].default_value = max(roughness, 0.05)
            if 'Specular IOR Level' in bsdf_node.inputs:
                bsdf_node.inputs['Specular IOR Level'].default_value = spec_intensity[0] if spec_intensity else 0.16
    
    def _build_water_shader(self, bl_mat, nodes, links, bsdf_node, output_node,
                            mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting):
        """
        Water shaders: Flowmap_River, FlowMap_Radial, OD_FlowMap, TFT_Water, TFT_Env_Rain.
        
        Creates a water-like Principled BSDF with:
        - Low roughness, high IOR (1.333)
        - Water color from params (Color_Outside/Water_Color or diffuse tint)
        - Diffuse texture if available
        - Normal map from Flowing_Normal_Map or Normal_Rain_Texture
        - Alpha for translucency
        - Transparent mix via Fresnel for realism
        """
        shader_name = self._get_shader_short_name(mat_data)
        
        # Determine water colors based on shader variant
        if shader_name == 'Flowmap_River':
            color_outside = self._get_param(mat_data, 'Color_Outside', [0.15, 0.56, 0.7, 1.0])
            color_inside = self._get_param(mat_data, 'Color_Inside', [0.44, 0.87, 0.92, 1.0])
            translucent = self._get_param(mat_data, 'TranslucentControl', [0.74])
            water_color = color_outside  # Use outside color as base
            water_alpha = translucent[0] if translucent else 0.74
        elif shader_name == 'TFT_Water':
            water_color_param = self._get_param(mat_data, 'Water_Color', [0.02, 0.2, 0.02, 0.54])
            water_color = water_color_param
            water_alpha = water_color_param[3] if len(water_color_param) > 3 else 0.54
        elif shader_name == 'TFT_Env_Rain':
            tint = self._get_param(mat_data, 'Tint', [0.91, 0.91, 0.91, 1.0])
            water_color = tint
            water_alpha = 0.85
        elif shader_name == 'OD_FlowMap':
            emissive_color = self._get_param(mat_data, 'Emissive_Color', [0.34, 0.53, 0.65, 1.0])
            water_color = emissive_color
            alpha_strength = self._get_param(mat_data, 'Alpha_Strength', [0.6])
            water_alpha = alpha_strength[0] if alpha_strength else 0.6
        else:  # FlowMap_Radial
            alpha_param = self._get_param(mat_data, 'Alpha', [0.445])
            water_color = [0.2, 0.5, 0.7, 1.0]  # Default blue-ish
            water_alpha = alpha_param[0] if alpha_param else 0.445
        
        # Remove default BSDF, build custom water graph
        nodes.remove(bsdf_node)
        
        # New Principled BSDF for water surface
        water_bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        water_bsdf.location = (200, 300)
        water_bsdf.inputs['Base Color'].default_value = (water_color[0], water_color[1], water_color[2], 1.0)
        water_bsdf.inputs['Roughness'].default_value = 0.05
        water_bsdf.inputs['IOR'].default_value = 1.333
        water_bsdf.inputs['Metallic'].default_value = 0.0
        if 'Specular IOR Level' in water_bsdf.inputs:
            water_bsdf.inputs['Specular IOR Level'].default_value = 0.8
        
        # Transparent BSDF for see-through
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        transparent.location = (200, 0)
        transparent.inputs['Color'].default_value = (water_color[0], water_color[1], water_color[2], 1.0)
        
        # Fresnel for water surface blending
        fresnel = nodes.new('ShaderNodeFresnel')
        fresnel.location = (0, 150)
        fresnel.inputs['IOR'].default_value = 1.333
        
        # Power node to control fresnel falloff
        power = nodes.new('ShaderNodeMath')
        power.operation = 'POWER'
        power.location = (200, 150)
        power.inputs[1].default_value = 0.5
        links.new(fresnel.outputs['Fac'], power.inputs[0])
        
        # Mix Shader: Transparent ↔ Water BSDF based on Fresnel
        mix_shader = nodes.new('ShaderNodeMixShader')
        mix_shader.location = (500, 200)
        links.new(power.outputs[0], mix_shader.inputs['Fac'])
        links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
        links.new(water_bsdf.outputs['BSDF'], mix_shader.inputs[2])
        
        links.new(mix_shader.outputs['Shader'], output_node.inputs['Surface'])
        
        # Load diffuse texture (Flowmap_River, FlowMap_Radial, OD_FlowMap, TFT_Env_Rain)
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap")
            if diffuse_node:
                diffuse_node.location = (-700, 400)
                # Mix diffuse color with water base color
                diff_mix = nodes.new('ShaderNodeMix')
                diff_mix.data_type = 'RGBA'
                diff_mix.blend_type = 'MULTIPLY'
                diff_mix.location = (-100, 400)
                diff_mix.inputs['Factor'].default_value = 1.0
                diff_mix.label = "Diffuse × Water Color"
                links.new(diffuse_node.outputs['Color'], diff_mix.inputs[6])
                diff_mix.inputs[7].default_value = (water_color[0], water_color[1], water_color[2], 1.0)
                links.new(diff_mix.outputs[2], water_bsdf.inputs['Base Color'])
        
        # Load normal map (Flowing_Normal_Map or Normal_Rain_Texture)
        normal_path = (self._get_sampler_path(mat_data, 'Flowing_Normal_Map') or
                       self._get_sampler_path(mat_data, 'Normal_Rain_Texture'))
        if normal_path:
            normal_tex = self._load_texture_node(bl_mat, nodes, links, normal_path, "UVMap")
            if normal_tex:
                normal_tex.location = (-700, -200)
                if normal_tex.image:
                    normal_tex.image.colorspace_settings.name = 'Non-Color'
                
                normal_map = nodes.new('ShaderNodeNormalMap')
                normal_map.location = (-300, -200)
                # Flow normal tiling
                flow_tile = self._get_param(mat_data, 'FlowNormal_Tile', [4.0, 3.0])
                normal_map.inputs['Strength'].default_value = min(flow_tile[0] if flow_tile else 4.0, 2.0) * 0.25
                links.new(normal_tex.outputs['Color'], normal_map.inputs['Color'])
                links.new(normal_map.outputs['Normal'], water_bsdf.inputs['Normal'])
        
        # Load flow map — channels: R=flowX, G=flowY (0.5=neutral), B=flow mask/intensity
        # Blender can't animate the flow, but we use the B channel as a water mask
        # and RG as a static normal-like distortion hint
        flow_path = (self._get_sampler_path(mat_data, 'Flow_Map') or
                     self._get_sampler_path(mat_data, 'FlowMap'))
        if flow_path:
            flow_tex = self._load_texture_node(bl_mat, nodes, links, flow_path, "UVMap")
            if flow_tex:
                flow_tex.location = (-700, -500)
                flow_tex.label = "Flow Map (R=dirX, G=dirY, B=mask)"
                if flow_tex.image:
                    flow_tex.image.colorspace_settings.name = 'Non-Color'
                
                # Separate channels: R=flow dir X, G=flow dir Y, B=flow mask
                sep_flow = nodes.new('ShaderNodeSeparateColor')
                sep_flow.location = (-400, -500)
                sep_flow.label = "Flow Channels"
                links.new(flow_tex.outputs['Color'], sep_flow.inputs['Color'])
                
                # Use RG as a subtle normal map (flow direction → surface distortion)
                # Combine: R→X, G→Y, constant 1.0→Z (like a normal map)
                combine_flow = nodes.new('ShaderNodeCombineColor')
                combine_flow.location = (-200, -550)
                combine_flow.label = "Flow → Normal"
                links.new(sep_flow.outputs['Red'], combine_flow.inputs['Red'])
                links.new(sep_flow.outputs['Green'], combine_flow.inputs['Green'])
                combine_flow.inputs['Blue'].default_value = 1.0  # Z = up
                
                # Only apply flow-as-normal if no dedicated normal map was loaded
                if not normal_path:
                    flow_normal = nodes.new('ShaderNodeNormalMap')
                    flow_normal.location = (-50, -550)
                    flow_normal.label = "Flow Direction Normal"
                    flowmap_strength = self._get_param(mat_data, 'Flowmap_Strength', [1.0, 1.0])
                    flow_normal.inputs['Strength'].default_value = min(
                        (flowmap_strength[0] if flowmap_strength else 1.0) * 0.3, 1.0
                    )
                    links.new(combine_flow.outputs['Color'], flow_normal.inputs['Color'])
                    links.new(flow_normal.outputs['Normal'], water_bsdf.inputs['Normal'])
                
                # B channel = flow mask → modulate water opacity
                # Where B=1 (white) water flows strongly, B=0 (black) no water
                flow_mask_multiply = nodes.new('ShaderNodeMath')
                flow_mask_multiply.operation = 'MULTIPLY'
                flow_mask_multiply.location = (-200, -650)
                flow_mask_multiply.label = "Flow Mask × Alpha"
                links.new(sep_flow.outputs['Blue'], flow_mask_multiply.inputs[0])
                flow_mask_multiply.inputs[1].default_value = water_alpha
                
                # Feed flow mask into the fresnel mix factor (blend with existing fresnel)
                flow_alpha_mix = nodes.new('ShaderNodeMath')
                flow_alpha_mix.operation = 'MULTIPLY'
                flow_alpha_mix.location = (350, 150)
                flow_alpha_mix.label = "Fresnel × Flow Mask"
                links.new(power.outputs[0], flow_alpha_mix.inputs[0])
                links.new(flow_mask_multiply.outputs[0], flow_alpha_mix.inputs[1])
                
                # Reconnect mix shader to use flow-modulated factor
                links.new(flow_alpha_mix.outputs[0], mix_shader.inputs['Fac'])
        
        # Load distortion texture (FlowMap_Radial, TFT_Water)
        distortion_path = self._get_sampler_path(mat_data, 'Distortion_Texture')
        if distortion_path:
            dist_tex = self._load_texture_node(bl_mat, nodes, links, distortion_path, "UVMap")
            if dist_tex:
                dist_tex.location = (-700, -350)
                dist_tex.label = "Distortion (Reference)"
                if dist_tex.image:
                    dist_tex.image.colorspace_settings.name = 'Non-Color'
        
        # Load reflection texture (TFT_Water, TFT_Env_Rain)
        reflection_path = self._get_sampler_path(mat_data, 'Reflection_Texture')
        if reflection_path:
            refl_tex = self._load_texture_node(bl_mat, nodes, links, reflection_path, "UVMap")
            if refl_tex:
                refl_tex.location = (-700, -650)
                refl_tex.label = "Reflection (Reference)"
        
        # Emissive for OD_FlowMap
        if shader_name == 'OD_FlowMap':
            emissive_color = self._get_param(mat_data, 'Emissive_Color', [0.34, 0.53, 0.65, 1.0])
            emissive_intensity = self._get_param(mat_data, 'Emmissive_Intensity', [1.15, 1.0])
            water_bsdf.inputs['Emission Color'].default_value = (
                emissive_color[0], emissive_color[1], emissive_color[2], 1.0
            )
            water_bsdf.inputs['Emission Strength'].default_value = emissive_intensity[0] if emissive_intensity else 1.15
        
        # Flowmap_River: color blend for inside/outside
        if shader_name == 'Flowmap_River':
            color_inside = self._get_param(mat_data, 'Color_Inside', [0.44, 0.87, 0.92, 1.0])
            # Store as custom property for reference
            bl_mat["water_color_inside"] = list(color_inside)
            bl_mat["water_color_outside"] = list(water_color)
        
        bl_mat.surface_render_method = 'BLENDED'
        bl_mat.show_transparent_back = True
        bl_mat.use_backface_culling = True
    
    def _build_ocean_shader(self, bl_mat, nodes, links, bsdf_node, output_node,
                            mat_data, lightmap_texture, lightmap_color_scale, has_baked_lighting):
        """
        SRX_Blend_Ocean: Diffuse + Noise texture, specular highlights, tint color.
        
        Samplers: Diffuse_Texture, Noise_Texture
        Key params: Tint_Color, Spec_Color, Specular_Intensity, Specular_Min_Max, Transition_Opacity
        """
        # Load diffuse
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_node = None
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap")
            if diffuse_node:
                diffuse_node.location = (-700, 300)
        
        # Load noise texture (used as detail/variation overlay)
        noise_path = self._get_sampler_path(mat_data, 'Noise_Texture')
        noise_node = None
        if noise_path:
            noise_node = self._load_texture_node(bl_mat, nodes, links, noise_path, "UVMap")
            if noise_node:
                noise_node.location = (-700, -100)
                noise_node.label = "Noise (Detail)"
        
        # Tint_Color (additive offset, can be negative — unusual)
        tint_color = self._get_param(mat_data, 'Tint_Color', [-0.075, -0.04, -0.03, 0.0])
        
        # Combine diffuse + noise + tint
        if diffuse_node and noise_node:
            # Overlay noise on diffuse (Screen blend for subtle detail)
            overlay_mix = nodes.new('ShaderNodeMix')
            overlay_mix.data_type = 'RGBA'
            overlay_mix.blend_type = 'SCREEN'
            overlay_mix.location = (-400, 200)
            overlay_mix.inputs['Factor'].default_value = 0.3  # Subtle noise overlay
            overlay_mix.label = "Diffuse + Noise"
            links.new(diffuse_node.outputs['Color'], overlay_mix.inputs[6])
            links.new(noise_node.outputs['Color'], overlay_mix.inputs[7])
            
            # Apply tint as additive offset
            if any(abs(c) > 0.01 for c in tint_color[:3]):
                tint_add = nodes.new('ShaderNodeMix')
                tint_add.data_type = 'RGBA'
                tint_add.blend_type = 'ADD'
                tint_add.location = (-200, 200)
                tint_add.inputs['Factor'].default_value = 1.0
                tint_add.label = "Tint Offset"
                links.new(overlay_mix.outputs[2], tint_add.inputs[6])
                tint_add.inputs[7].default_value = (
                    max(tint_color[0], 0), max(tint_color[1], 0), max(tint_color[2], 0), 1.0
                )
                links.new(tint_add.outputs[2], bsdf_node.inputs['Base Color'])
            else:
                links.new(overlay_mix.outputs[2], bsdf_node.inputs['Base Color'])
            
            if diffuse_node:
                links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        elif diffuse_node:
            links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Base Color'])
            links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        
        # Specular properties
        spec_color = self._get_param(mat_data, 'Spec_Color', [0.651, 0.839, 1.0, 1.0])
        spec_intensity = self._get_param(mat_data, 'Specular_Intensity', [0.35])
        spec_min_max = self._get_param(mat_data, 'Specular_Min_Max', [0.1, 0.65])
        
        # Low roughness for ocean specular highlights
        roughness = 1.0 - (spec_min_max[1] if spec_min_max and len(spec_min_max) > 1 else 0.65)
        bsdf_node.inputs['Roughness'].default_value = max(roughness, 0.1)
        
        if 'Specular IOR Level' in bsdf_node.inputs:
            bsdf_node.inputs['Specular IOR Level'].default_value = spec_intensity[0] if spec_intensity else 0.35
        
        # Slight specular tint via Spec_Color as emission hint
        # Store spec color for reference
        bl_mat["ocean_spec_color"] = list(spec_color[:3])
        
        # Transition opacity for blend transitions
        transition_opacity = self._get_param(mat_data, 'Transition_Opacity', [0.6])
        switches = mat_data.get('switches', {})
        if switches.get('ENV_TRANSITION', False) or switches.get('ENABLE_TRANSITION_FADE', False):
            bsdf_node.inputs['Alpha'].default_value = transition_opacity[0] if transition_opacity else 0.6
            bl_mat.surface_render_method = 'BLENDED'
        
        # Lightmap support (same as default)
        if has_baked_lighting and lightmap_texture and self.assets_folder:
            lightmap_node = self._load_texture_node(bl_mat, nodes, links, lightmap_texture, "LightmapUV")
            if lightmap_node:
                lightmap_node.location = (-700, -400)
                if lightmap_node.image:
                    lightmap_node.image.colorspace_settings.name = 'Non-Color'
    
    def _build_twist_shader(self, bl_mat, nodes, links, bsdf_node, output_node, mat_data):
        """
        Env_TwistByNoise / TFT_TwistByNoise: Diffuse + Noise with UV distortion effect.
        
        Samplers: Diffuse_Texture, Noise_Texture, (TFT: Strength_Texture)
        Key params: MainColor, EmissiveFactor, AlphaTestValue, Strength, NoiseUVInfo
        
        The noise texture drives UV distortion (twist) on the diffuse.
        MainColor is used as an emissive tint when EmissiveFactor > 0.
        """
        shader_name = self._get_shader_short_name(mat_data)
        
        # Load diffuse
        diffuse_path = self._get_sampler_path(mat_data, 'Diffuse_Texture')
        diffuse_node = None
        if diffuse_path:
            diffuse_node = self._load_texture_node(bl_mat, nodes, links, diffuse_path, "UVMap")
            if diffuse_node:
                diffuse_node.location = (-700, 300)
        
        # Load noise texture (drives UV distortion)
        noise_path = self._get_sampler_path(mat_data, 'Noise_Texture')
        noise_node = None
        if noise_path:
            noise_node = self._load_texture_node(bl_mat, nodes, links, noise_path, "UVMap")
            if noise_node:
                noise_node.location = (-700, -100)
                noise_node.label = "Noise (Twist Driver)"
                if noise_node.image:
                    noise_node.image.colorspace_settings.name = 'Non-Color'
        
        # Load strength texture (TFT variant only)
        if shader_name == 'TFT_TwistByNoise':
            strength_path = self._get_sampler_path(mat_data, 'Strength_Texture')
            if strength_path:
                strength_node = self._load_texture_node(bl_mat, nodes, links, strength_path, "UVMap")
                if strength_node:
                    strength_node.location = (-700, -400)
                    strength_node.label = "Strength Mask"
                    if strength_node.image:
                        strength_node.image.colorspace_settings.name = 'Non-Color'
        
        # MainColor tint
        main_color = self._get_param(mat_data, 'MainColor', [1.0, 1.0, 1.0, 1.0])
        emissive_factor = self._get_param(mat_data, 'EmissiveFactor', [1.0])
        alpha_test = self._get_param(mat_data, 'AlphaTestValue', [0.5])
        
        if diffuse_node:
            is_white = all(abs(c - 1.0) < 0.01 for c in main_color[:3])
            if not is_white:
                # Multiply diffuse by MainColor
                tint_mix = nodes.new('ShaderNodeMix')
                tint_mix.data_type = 'RGBA'
                tint_mix.blend_type = 'MULTIPLY'
                tint_mix.location = (-400, 300)
                tint_mix.inputs['Factor'].default_value = 1.0
                tint_mix.label = "Diffuse × MainColor"
                links.new(diffuse_node.outputs['Color'], tint_mix.inputs[6])
                tint_mix.inputs[7].default_value = (main_color[0], main_color[1], main_color[2], 1.0)
                
                links.new(tint_mix.outputs[2], bsdf_node.inputs['Base Color'])
                # Also use as emission if factor > 0
                if emissive_factor and emissive_factor[0] > 0.01:
                    links.new(tint_mix.outputs[2], bsdf_node.inputs['Emission Color'])
                    bsdf_node.inputs['Emission Strength'].default_value = emissive_factor[0]
            else:
                links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                if emissive_factor and emissive_factor[0] > 0.01:
                    links.new(diffuse_node.outputs['Color'], bsdf_node.inputs['Emission Color'])
                    bsdf_node.inputs['Emission Strength'].default_value = emissive_factor[0]
            
            links.new(diffuse_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
        else:
            # No diffuse — use MainColor directly
            bsdf_node.inputs['Base Color'].default_value = (main_color[0], main_color[1], main_color[2], 1.0)
            if emissive_factor and emissive_factor[0] > 0.01:
                bsdf_node.inputs['Emission Color'].default_value = (main_color[0], main_color[1], main_color[2], 1.0)
                bsdf_node.inputs['Emission Strength'].default_value = emissive_factor[0]
        
        # Alpha test
        if alpha_test and len(alpha_test) > 0:
            bl_mat.alpha_threshold = alpha_test[0]
        
        # Store twist params for reference (can't animate UV distortion in Blender)
        strength = self._get_param(mat_data, 'Strength', [0.01, 0.01])
        noise_uv = self._get_param(mat_data, 'NoiseUVInfo', [0.1, 0.0, 0.25, 0.25])
        bl_mat["twist_strength"] = list(strength) if strength else [0.01, 0.01]
        bl_mat["twist_noise_uv"] = list(noise_uv) if noise_uv else [0.1, 0.0, 0.25, 0.25]
    
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
        # Also checks: Tint, BaseTint, Diffuse_Tint, DiffuseTint, Tint_Color, ColorTint
        tint_color = (self._get_param(mat_data, 'TintColor') or
                      self._get_param(mat_data, 'BaseTex_TintColor') or
                      self._get_param(mat_data, 'Tint') or
                      self._get_param(mat_data, 'BaseTint') or
                      self._get_param(mat_data, 'Diffuse_Tint') or
                      self._get_param(mat_data, 'DiffuseTint') or
                      self._get_param(mat_data, 'Tint_Color') or
                      self._get_param(mat_data, 'ColorTint'))
        
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
                
                # Offset to center (1.0, 1.0)
                offset_x = nodes.new('ShaderNodeMath')
                offset_x.operation = 'ADD'
                offset_x.location = (-650, -350)
                offset_x.inputs[1].default_value = 1.0
                links.new(scale_x.outputs[0], offset_x.inputs[0])
                
                offset_y = nodes.new('ShaderNodeMath')
                offset_y.operation = 'ADD'
                offset_y.location = (-650, -450)
                offset_y.inputs[1].default_value = 1.0
                links.new(scale_y.outputs[0], offset_y.inputs[0])
                
                links.new(offset_x.outputs[0], combine_xy.inputs['X'])
                links.new(offset_y.outputs[0], combine_xy.inputs['Y'])
                
                # Load grass tint texture
                grass_tint_node = nodes.new('ShaderNodeTexImage')
                grass_tint_node.location = (-500, -400)
                grass_tint_node.label = "Grass Tint (World UV)"
                links.new(combine_xy.outputs['Vector'], grass_tint_node.inputs['Vector'])
                
                # Load the texture (supports .tex, .dds, .png)
                if grass_tint_path:
                    try:
                        if grass_tint_path.lower().endswith('.tex'):
                            img = self.tex_converter.load_tex_as_blender_image(grass_tint_path)
                        else:
                            img = bpy.data.images.load(grass_tint_path, check_existing=True)
                        if img:
                            grass_tint_node.image = img
                            img.colorspace_settings.name = 'sRGB'
                    except Exception as e:
                        _log().error("GrassTint", f"Could not load grass tint texture: {e}")
                
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
        if tinted_color_output and lightmap_node and lightmap_node.image:
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
            
            # → Emission (baked lighting from lightmap)
            links.new(final_mix.outputs[2], bsdf_node.inputs['Emission Color'])
            bsdf_node.inputs['Emission Strength'].default_value = 1.0
            # Route diffuse to Base Color so material also responds to scene
            # lights (sun, sky, ambient). Without this, lightmapped materials
            # are pure self-lit and ignore all scene lighting.
            links.new(tinted_color_output, bsdf_node.inputs['Base Color'])
            # Reduce specular for lightmapped surfaces — League env shaders
            # are diffuse-only; specular highlights would be incorrect.
            if 'Specular IOR Level' in bsdf_node.inputs:
                bsdf_node.inputs['Specular IOR Level'].default_value = 0.0
            bsdf_node.inputs['Roughness'].default_value = 1.0
            
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
        
        # Emission color support (EMISSION_EmissionColor, EmissionColor, FLOW_Color, etc.)
        # Only apply if an emissive texture sampler is actually present — the game
        # ignores EmissionColor when there is no emission texture assigned.
        emission_paths = [
            self._get_sampler_path(mat_data, 'Emissive_Texture'),
            self._get_sampler_path(mat_data, 'EmissionTex'),
            self._get_sampler_path(mat_data, 'Emission_Tex'),
            self._get_sampler_path(mat_data, 'EmissiveTexture'),
            self._get_sampler_path(mat_data, 'EmissionMaskTex'),
        ]

        has_emission_tex = any((p and not self._is_placeholder_texture_path(p)) for p in emission_paths)

        has_primary_emission_tex = any(
            (p and not self._is_placeholder_texture_path(p))
            for p in emission_paths[:4]
        )

        # SRX_DynamicEffect / DefaultEnv_Flat: when Emission_Tex is not assigned,
        # keep emission disabled instead of defaulting to 1.0.
        force_zero_emission_without_tex = (
            shader_name in ('SRX_DynamicEffect', 'DefaultEnv_Flat') and
            not has_primary_emission_tex
        )

        if force_zero_emission_without_tex:
            bsdf_node.inputs['Emission Strength'].default_value = 0.0

        if has_emission_tex:
            emission_color = (self._get_param(mat_data, 'EMISSION_EmissionColor') or
                              self._get_param(mat_data, 'EmissionColor') or
                              self._get_param(mat_data, 'FLOW_Color'))
            if emission_color and len(emission_color) >= 3:
                ec_r, ec_g, ec_b = float(emission_color[0]), float(emission_color[1]), float(emission_color[2])
                is_nonblack = (ec_r > 0.01 or ec_g > 0.01 or ec_b > 0.01)
                if is_nonblack:
                    bsdf_node.inputs['Emission Color'].default_value = (ec_r, ec_g, ec_b, 1.0)
                    em_intensity = self._get_param(mat_data, 'Emissive_Intensity')
                    if em_intensity:
                        bsdf_node.inputs['Emission Strength'].default_value = max(0.0, float(em_intensity[0]))
                    elif not force_zero_emission_without_tex:
                        bsdf_node.inputs['Emission Strength'].default_value = 1.0
        
        # Starting_Color / Color fallback for base color (when no texture)
        if not diffuse_path and not tint_color:
            starting_color = (self._get_param(mat_data, 'Starting_Color') or
                              self._get_param(mat_data, 'Color') or
                              self._get_param(mat_data, 'UnderColor') or
                              self._get_param(mat_data, 'Color_Bottom'))
            if starting_color and len(starting_color) >= 3:
                bsdf_node.inputs['Base Color'].default_value = (
                    float(starting_color[0]), float(starting_color[1]),
                    float(starting_color[2]), 1.0
                )
        
        # ShadowColor hint (blend into base color slightly)
        shadow_color = self._get_param(mat_data, 'ShadowColor')
        if shadow_color and len(shadow_color) >= 3:
            bl_mat["shadow_color"] = list(shadow_color[:3])
    
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
        if not self.assets_folder and not self.custom_assets_folder:
            return None
        
        full_tex_path = resolve_texture_path(texture_path, self.assets_folder, self.custom_assets_folder, self.prioritize_custom)
        if not full_tex_path:
            _log().texture_missing(texture_path, "Could not resolve path")
            return None
        _log().info("Texture", f"Resolved sampler: {texture_path} -> {full_tex_path}")
        
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.extension = extension
        
        try:
            if full_tex_path.lower().endswith('.tex'):
                img = self.tex_converter.load_tex_as_blender_image(full_tex_path)
            else:
                img = bpy.data.images.load(full_tex_path, check_existing=True)
            if img:
                tex_node.image = img
                _log().texture_loaded(full_tex_path)
                return tex_node
        except Exception as e:
            _log().texture_failed(full_tex_path, str(e))
        
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
        if not self.assets_folder and not self.custom_assets_folder:
            return None
        
        # Resolve texture path (tries .tex -> .dds -> .png)
        full_tex_path = resolve_texture_path(texture_path, self.assets_folder, self.custom_assets_folder, self.prioritize_custom)
        if not full_tex_path:
            _log().texture_missing(texture_path, "Could not resolve path")
            return None
        _log().info("Texture", f"Resolved sampler: {texture_path} -> {full_tex_path}")
        
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
            if full_tex_path.lower().endswith('.tex'):
                img = self.tex_converter.load_tex_as_blender_image(full_tex_path)
            else:
                img = bpy.data.images.load(full_tex_path, check_existing=True)
            if img:
                tex_node.image = img
                uv_node.location = (tex_node.location[0] - 200, tex_node.location[1])
                uv_node.label = uv_map_name
                return tex_node
        except Exception as e:
            _log().texture_failed(full_tex_path, str(e))
        
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
        
        # Try FNV-1a hash lookup: material name → hash → check if hash is a key
        mat_hash = f"0x{_fnv1a_32(mat_name):08x}"
        if mat_hash in materials_db:
            _log().info("Material", f"Resolved '{mat_name}' via FNV-1a hash {mat_hash}")
            return self.create_blender_material(mat_name, materials_db[mat_hash],
                                                lightmap_texture, lightmap_color_scale,
                                                texture_overrides,
                                                baked_paint_scale, baked_paint_bias)
        
        # Try matching by 'name' field inside material data (for hashed entries)
        for key, value in materials_db.items():
            if isinstance(value, dict):
                inner_name = value.get('name', '')
                if inner_name and inner_name.lower() == mat_name_lower:
                    _log().info("Material", f"Resolved '{mat_name}' via inner name in {key}")
                    return self.create_blender_material(mat_name, value,
                                                        lightmap_texture, lightmap_color_scale,
                                                        texture_overrides,
                                                        baked_paint_scale, baked_paint_bias)
        
        # Material not found - create a simple material
        _log().material_missing(mat_name, "Not found in database")
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
