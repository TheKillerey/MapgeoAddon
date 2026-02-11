"""
Material Loader for Mapgeo Addon
Loads materials from .materials.bin.json files and creates Blender materials
"""

import json
import os
import bpy
from typing import Dict, Optional
from .texture_utils import TexConverter, resolve_texture_path


class MaterialLoader:
    """Loads and creates Blender materials from League materials JSON"""
    
    def __init__(self, assets_folder: str = ""):
        self.assets_folder = assets_folder
        self.tex_converter = TexConverter()
        self.materials_cache = {}  # Cache loaded materials
    
    def load_materials_from_json(self, json_path: str) -> Dict[str, dict]:
        """
        Load materials from a .materials.bin.json file
        
        Returns:
            Dictionary of material_name -> material_data
        """
        materials = {}
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Iterate through all entries and find StaticMaterialDef
            for key, value in data.items():
                if isinstance(value, dict) and value.get("__type") == "StaticMaterialDef":
                    materials[key] = value
            
            print(f"Loaded {len(materials)} static materials from {os.path.basename(json_path)}")
            return materials
        
        except Exception as e:
            print(f"Error loading materials JSON: {e}")
            return {}
    
    def create_blender_material(self, mat_name: str, mat_data: dict) -> Optional[bpy.types.Material]:
        """
        Create a Blender material from material data
        
        Args:
            mat_name: Material name
            mat_data: Material data dictionary from JSON
        
        Returns:
            Created Blender material or None
        """
        # Check cache
        if mat_name in self.materials_cache:
            return self.materials_cache[mat_name]
        
        # Create or get existing material
        bl_mat = bpy.data.materials.get(mat_name)
        if bl_mat is None:
            bl_mat = bpy.data.materials.new(name=mat_name)
        
        # Enable nodes
        bl_mat.use_nodes = True
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        
        # Clear existing nodes
        nodes.clear()
        
        # Create shader nodes
        output_node = nodes.new('ShaderNodeOutputMaterial')
        output_node.location = (300, 0)
        
        bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)
        
        # Link BSDF to output
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
        
        # Get textures from samplerValues
        sampler_values = mat_data.get('samplerValues', [])
        texture_node = None
        
        for sampler in sampler_values:
            texture_name = sampler.get('TextureName', '')
            texture_path = sampler.get('texturePath', '')
            
            # Focus on DiffuseTexture for now
            if texture_name == 'DiffuseTexture' and texture_path:
                texture_node = self._load_texture(
                    bl_mat, nodes, links, texture_path, bsdf_node
                )
                break
        
        # Get shader parameters
        param_values = mat_data.get('paramValues', [])
        for param in param_values:
            param_name = param.get('name', '')
            param_value = param.get('value', [1.0, 1.0, 1.0, 1.0])
            
            if param_name == 'TintColor' and len(param_value) >= 3:
                # Apply tint color as base color multiplier
                bsdf_node.inputs['Base Color'].default_value = (
                    param_value[0],
                    param_value[1],
                    param_value[2],
                    param_value[3] if len(param_value) > 3 else 1.0
                )
            elif param_name == 'AlphaTestValue' and len(param_value) > 0:
                # Enable alpha blend for alpha-tested materials
                bl_mat.blend_method = 'CLIP'
                bl_mat.alpha_threshold = param_value[0]
        
        # Check shader macros for additional settings
        shader_macros = mat_data.get('shaderMacros', {})
        if 'NO_BAKED_LIGHTING' in shader_macros:
            # Adjust material for no baked lighting
            # Note: Specular input name changed in Blender 4.0+
            # Try to set it if it exists, otherwise skip
            if 'Specular' in bsdf_node.inputs:
                bsdf_node.inputs['Specular'].default_value = 0.5
            elif 'Specular IOR Level' in bsdf_node.inputs:
                bsdf_node.inputs['Specular IOR Level'].default_value = 0.5
        
        # Cache and return
        self.materials_cache[mat_name] = bl_mat
        return bl_mat
    
    def _load_texture(self, material, nodes, links, texture_path: str, bsdf_node) -> Optional[bpy.types.Node]:
        """Load a texture and connect it to the material"""
        if not self.assets_folder:
            print(f"  Warning: No assets folder set, cannot load texture")
            return None
        
        # Resolve texture path
        full_tex_path = resolve_texture_path(texture_path, self.assets_folder)
        if not full_tex_path:
            print(f"  Warning: Could not find texture: {texture_path}")
            return None
        
        # Convert TEX to PNG
        png_path = self.tex_converter.convert_tex_to_png(full_tex_path)
        
        # If conversion failed, try to use .dds or original path
        if not png_path:
            # Try .dds alternative
            dds_path = os.path.splitext(full_tex_path)[0] + ".dds"
            if os.path.exists(dds_path):
                png_path = dds_path
            elif os.path.exists(full_tex_path):
                png_path = full_tex_path
            else:
                print(f"  Warning: Could not load texture: {os.path.basename(texture_path)}")
                return None
        
        # Create image texture node
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.location = (-300, 0)
        
        # Load image
        try:
            # Change extension to .png for Blender
            display_path = os.path.splitext(png_path)[0] + ".png"
            
            if os.path.exists(display_path):
                img = bpy.data.images.load(display_path, check_existing=True)
                tex_node.image = img
                
                # Connect to BSDF
                links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
                links.new(tex_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
                
                return tex_node
            else:
                print(f"  Warning: PNG file not found: {display_path}")
        except Exception as e:
            print(f"  Error loading texture {os.path.basename(png_path)}: {e}")
        
        return None
    
    def get_or_create_material(self, mat_name: str, materials_db: Dict[str, dict]) -> Optional[bpy.types.Material]:
        """
        Get or create a material by name from the materials database
        
        Args:
            mat_name: Material name to look up
            materials_db: Materials database from JSON
        
        Returns:
            Blender material or None
        """
        # Try exact match first
        if mat_name in materials_db:
            return self.create_blender_material(mat_name, materials_db[mat_name])
        
        # Try case-insensitive search
        mat_name_lower = mat_name.lower()
        for key, value in materials_db.items():
            if key.lower() == mat_name_lower:
                return self.create_blender_material(key, value)
        
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
