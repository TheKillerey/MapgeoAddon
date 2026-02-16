"""
Blender Material Exporter for League of Legends
Exports Blender materials with League properties back to .materials.py format
"""

import bpy
import json
from pathlib import Path
from typing import Dict, List, Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from materials_parser import (
        Material, MaterialSampler, MaterialParam, MaterialSwitch,
        MaterialPass, MaterialTechnique, MaterialChildTechnique,
        MaterialsExporter
    )
except ImportError:
    Material = None
    MaterialsExporter = None

def export_blender_materials_to_league(output_filepath: str, materials_list: Optional[List[bpy.types.Material]] = None) -> int:
    """
    Export Blender materials back to League .materials.py format
    
    Args:
        output_filepath: Path to write .materials.py file
        materials_list: List of Blender materials to export (None = all with league_material_name)
    
    Returns:
        Number of materials exported
    """
    
    if MaterialsExporter is None:
        raise RuntimeError("materials_parser module not available")
    
    # Collect materials to export
    if materials_list is None:
        materials_list = [m for m in bpy.data.materials if m.get("league_material_name")]
    
    # Convert Blender materials to League materials
    league_materials = {}
    
    for blender_mat in materials_list:
        try:
            league_mat = _convert_blender_to_league(blender_mat)
            league_materials[league_mat.name] = league_mat
        except Exception as e:
            print(f"Warning: Failed to export material {blender_mat.name}: {e}")
    
    # Export to file
    if league_materials:
        MaterialsExporter.export(league_materials, output_filepath)
        print(f"Exported {len(league_materials)} materials to {output_filepath}")
    
    return len(league_materials)

def _convert_blender_to_league(blender_mat: bpy.types.Material) -> Material:
    """Convert a Blender material to a League Material object"""
    
    league_mat = Material(
        name=blender_mat.get("league_material_name", blender_mat.name),
        type=blender_mat.get("league_material_type", 0)
    )
    
    # Restore samplers
    if "samplers" in blender_mat:
        try:
            samplers_data = json.loads(blender_mat["samplers"])
            for s in samplers_data:
                sampler = MaterialSampler(
                    textureName=s.get("textureName", ""),
                    texturePath=s.get("texturePath", ""),
                    addressU=s.get("addressU", 1),
                    addressV=s.get("addressV", 1),
                    addressW=s.get("addressW", 1)
                )
                league_mat.samplerValues.append(sampler)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse samplers JSON for {blender_mat.name}")
    
    # Restore parameters
    if "parameters" in blender_mat:
        try:
            params_data = json.loads(blender_mat["parameters"])
            for p in params_data:
                param = MaterialParam(
                    name=p.get("name", ""),
                    value=None if p.get("value") is None else tuple(p.get("value", [0, 0, 0, 0])[:4])
                )
                league_mat.paramValues.append(param)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse parameters JSON for {blender_mat.name}")
    
    # Restore switches
    if "switches" in blender_mat:
        try:
            switches_data = json.loads(blender_mat["switches"])
            for s in switches_data:
                switch = MaterialSwitch(
                    name=s.get("name", ""),
                    on=s.get("on", False)
                )
                league_mat.switches.append(switch)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse switches JSON for {blender_mat.name}")
    
    # Restore shader macros
    if "shader_macros" in blender_mat:
        try:
            league_mat.shaderMacros = json.loads(blender_mat["shader_macros"])
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse shader_macros JSON for {blender_mat.name}")
    
    # Restore techniques
    if "techniques" in blender_mat:
        try:
            techniques_data = json.loads(blender_mat["techniques"])
            for t in techniques_data:
                technique = MaterialTechnique(name=t.get("name", ""))
                for p in t.get("passes", []):
                    pass_obj = MaterialPass(
                        shader=p.get("shader", ""),
                        blendEnable=p.get("blendEnable", False),
                        srcColorBlendFactor=p.get("srcColorBlendFactor", 1),
                        srcAlphaBlendFactor=p.get("srcAlphaBlendFactor", 1),
                        dstColorBlendFactor=p.get("dstColorBlendFactor", 0),
                        dstAlphaBlendFactor=p.get("dstAlphaBlendFactor", 0)
                    )
                    technique.passes.append(pass_obj)
                league_mat.techniques.append(technique)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse techniques JSON for {blender_mat.name}")
    
    # Restore child techniques
    if "child_techniques" in blender_mat:
        try:
            child_techs_data = json.loads(blender_mat["child_techniques"])
            for ct in child_techs_data:
                child_tech = MaterialChildTechnique(
                    name=ct.get("name", ""),
                    parentName=ct.get("parentName", ""),
                    shaderMacros=ct.get("shaderMacros", {})
                )
                league_mat.childTechniques.append(child_tech)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse child_techniques JSON for {blender_mat.name}")
    
    return league_mat

def export_selected_materials_json(output_filepath: str) -> int:
    """Export selected object's materials to JSON for editing"""
    
    obj = bpy.context.active_object
    if not obj or not obj.data.materials:
        print("No object with materials selected")
        return 0
    
    materials_data = []
    for mat in obj.data.materials:
        if mat is None:
            continue
        
        mat_data = {
            'name': mat.name,
            'league_name': mat.get("league_material_name", mat.name),
            'type': mat.get("league_material_type", 0),
            'samplers': [],
            'parameters': [],
            'switches': [],
            'shaderMacros': {},
            'techniques': [],
            'childTechniques': []
        }
        
        # Extract League properties
        if "samplers" in mat:
            try:
                mat_data['samplers'] = json.loads(mat["samplers"])
            except:
                pass
        
        if "parameters" in mat:
            try:
                mat_data['parameters'] = json.loads(mat["parameters"])
            except:
                pass
        
        if "switches" in mat:
            try:
                mat_data['switches'] = json.loads(mat["switches"])
            except:
                pass
        
        if "shader_macros" in mat:
            try:
                mat_data['shaderMacros'] = json.loads(mat["shader_macros"])
            except:
                pass
        
        if "techniques" in mat:
            try:
                mat_data['techniques'] = json.loads(mat["techniques"])
            except:
                pass
        
        if "child_techniques" in mat:
            try:
                mat_data['childTechniques'] = json.loads(mat["child_techniques"])
            except:
                pass
        
        materials_data.append(mat_data)
    
    # Write to file
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(materials_data, f, indent=2, ensure_ascii=False)
    
    print(f"Exported {len(materials_data)} materials to {output_filepath}")
    return len(materials_data)

# ============================================================================
# Blender Addon Operators
# ============================================================================

class MAPGEO_OT_export_materials_to_league(bpy.types.Operator):
    """Export materials back to League .materials.py format"""
    bl_idname = "mapgeo.export_materials_to_league"
    bl_label = "Export Materials to League"
    bl_options = {'REGISTER'}
    
    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Output .materials.py file path",
        subtype='FILE_PATH',
        default="materials.py"
    )
    
    def execute(self, context):
        try:
            count = export_blender_materials_to_league(self.filepath)
            self.report({'INFO'}, f"Exported {count} materials")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class MAPGEO_OT_export_materials_json(bpy.types.Operator):
    """Export selected object's materials to JSON for editing"""
    bl_idname = "mapgeo.export_materials_json"
    bl_label = "Export Materials to JSON"
    bl_options = {'REGISTER'}
    
    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Output JSON file path",
        subtype='FILE_PATH',
        default="materials_export.json"
    )
    
    def execute(self, context):
        try:
            count = export_selected_materials_json(self.filepath)
            self.report({'INFO'}, f"Exported {count} materials to JSON")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

def register():
    """Register operators"""
    bpy.utils.register_class(MAPGEO_OT_export_materials_to_league)
    bpy.utils.register_class(MAPGEO_OT_export_materials_json)

def unregister():
    """Unregister operators"""
    bpy.utils.unregister_class(MAPGEO_OT_export_materials_to_league)
    bpy.utils.unregister_class(MAPGEO_OT_export_materials_json)

if __name__ == "__main__":
    register()
