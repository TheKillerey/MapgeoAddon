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

try:
    from .particles_materials import update_other_entries_with_particles
except ImportError:
    try:
        from particles_materials import update_other_entries_with_particles
    except ImportError:
        update_other_entries_with_particles = None

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
    
    # Retrieve preserved other_entries and entry_order
    other_entries, entry_order = _retrieve_other_entries()
    if update_other_entries_with_particles:
        other_entries, entry_order = update_other_entries_with_particles(other_entries, entry_order)
    
    # Export to file with preserved entries in original order
    if league_materials:
        MaterialsExporter.export(league_materials, output_filepath, other_entries, entry_order)
        if other_entries:
            print(f"Exported {len(league_materials)} materials + {len(other_entries)} other entries to {output_filepath}")
        else:
            print(f"Exported {len(league_materials)} materials to {output_filepath}")
            print(f"Warning: No other entries found - VFX/MapPlaceableContainer data may be lost")
    
    return len(league_materials)


def export_blender_materials_merge(source_filepath: str, output_filepath: str, 
                                    materials_list: Optional[List[bpy.types.Material]] = None) -> int:
    """
    Export Blender materials merged with an existing .materials.py file.
    
    Reads the source file to get all non-material entries and entry order,
    then replaces only the materials with Blender's versions while preserving
    everything else (VFX, MapPlaceableContainer, etc.) from the source file.
    
    Args:
        source_filepath: Path to existing .materials.py file to merge with
        output_filepath: Path to write the merged output file
        materials_list: List of Blender materials to export (None = all with league_material_name)
    
    Returns:
        Number of materials exported
    """
    from materials_parser import MaterialsParser
    
    if MaterialsExporter is None:
        raise RuntimeError("materials_parser module not available")
    
    # Parse the source file to get other_entries and entry_order
    parser = MaterialsParser(source_filepath)
    parser.parse()
    other_entries = parser.other_entries
    entry_order = parser.entry_order

    if update_other_entries_with_particles:
        other_entries, entry_order = update_other_entries_with_particles(other_entries, entry_order)
    
    print(f"Source file: {len(parser.materials)} materials, {len(other_entries)} other entries")
    
    # Collect Blender materials
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
    
    # Export: use source file's other_entries and entry_order, but with Blender's materials
    if league_materials:
        MaterialsExporter.export(league_materials, output_filepath, other_entries, entry_order)
        print(f"Exported {len(league_materials)} materials + {len(other_entries)} other entries")
        print(f"  (merged with: {source_filepath})")
    
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
                    addressU=s.get("addressU"),
                    addressV=s.get("addressV"),
                    addressW=s.get("addressW")
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
                if "group" in s:
                    switch.group = s["group"]
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
                        cullEnable=p.get("cullEnable"),
                        srcColorBlendFactor=p.get("srcColorBlendFactor", 1),
                        srcAlphaBlendFactor=p.get("srcAlphaBlendFactor", 1),
                        dstColorBlendFactor=p.get("dstColorBlendFactor", 0),
                        dstAlphaBlendFactor=p.get("dstAlphaBlendFactor", 0),
                        writeMask=p.get("writeMask"),
                        shaderMacros=p.get("shaderMacros", {})
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
    
    # Restore dynamicMaterial
    if "dynamic_material" in blender_mat:
        league_mat.dynamicMaterial = blender_mat["dynamic_material"]
    
    return league_mat

def _retrieve_other_entries() -> tuple:
    """Retrieve preserved non-material entries and entry order.

    Supports two storage formats:
      - **filepath** (current): text block contains ``# FORMAT: filepath`` followed
        by the source .materials.py path.  The file is re-parsed on the fly (~0.3 s).
      - **legacy (pickle/base64)**: text block contains ``# DATA:`` followed by a
        base64-encoded pickle blob.  Kept for backwards compatibility with .blend
        files saved before this optimisation.

    Returns:
        Tuple of (other_entries dict, entry_order list) or (None, None) if not found
    """
    text_name = "league_other_entries"

    if text_name not in bpy.data.texts:
        return None, None

    try:
        text_block = bpy.data.texts[text_name]
        lines = text_block.as_string().split('\n')

        # Detect format
        fmt = None
        payload = ""
        for line in lines:
            stripped = line.strip()
            if stripped == "# FORMAT: filepath":
                fmt = "filepath"
                continue
            if stripped == "# DATA:":
                fmt = "legacy"
                continue
            if fmt and not stripped.startswith("#") and stripped:
                payload = stripped
                break

        if not payload:
            print("Warning: No data found in other_entries text block")
            return None, None

        # ── New path-based format ──
        if fmt == "filepath":
            import os
            source_path = payload
            if not os.path.isfile(source_path):
                print(f"Warning: Source materials file not found: {source_path}")
                return None, None
            try:
                from .materials_parser import MaterialsParser
            except ImportError:
                from materials_parser import MaterialsParser
            import time as _t
            _t0 = _t.perf_counter()
            parser = MaterialsParser(source_path)
            parser.parse()
            elapsed = _t.perf_counter() - _t0
            print(f"Re-parsed {len(parser.other_entries)} other entries + {len(parser.entry_order)} order from {os.path.basename(source_path)} in {elapsed:.2f}s")
            return parser.other_entries, parser.entry_order

        # ── Legacy pickle/base64 format ──
        import pickle
        import base64
        store_data = pickle.loads(base64.b64decode(payload))

        if isinstance(store_data, dict) and 'other_entries' in store_data:
            other_entries = store_data['other_entries']
            entry_order = store_data.get('entry_order', None)
            print(f"Retrieved {len(other_entries)} other entries + {len(entry_order) if entry_order else 0} order entries from Blender text block (legacy)")
            return other_entries, entry_order
        else:
            print(f"Retrieved {len(store_data)} other entries (legacy list format) from Blender text block")
            other_entries = {}
            for name, etype, content in store_data:
                other_entries[name] = (etype, content)
            return other_entries, None

    except Exception as e:
        print(f"Warning: Failed to retrieve other_entries: {e}")
        return None, None

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


class MAPGEO_OT_export_materials_merge(bpy.types.Operator):
    """Export materials merged with an existing .materials.py file (preserves VFX, containers, etc.)"""
    bl_idname = "mapgeo.export_materials_merge"
    bl_label = "Export Materials (Merge)"
    bl_options = {'REGISTER'}
    
    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Select the source .materials.py file to merge with",
        subtype='FILE_PATH',
    )
    
    def execute(self, context):
        import os
        try:
            source = self.filepath
            if not os.path.isfile(source):
                self.report({'ERROR'}, f"Source file not found: {source}")
                return {'CANCELLED'}
            
            # Write output next to source with _export suffix
            base, ext = os.path.splitext(source)
            output = f"{base}_export{ext}"
            
            count = export_blender_materials_merge(source, output)
            self.report({'INFO'}, f"Exported {count} materials merged with {os.path.basename(source)}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Merge export failed: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


def register():
    """Register operators"""
    bpy.utils.register_class(MAPGEO_OT_export_materials_to_league)
    bpy.utils.register_class(MAPGEO_OT_export_materials_json)
    bpy.utils.register_class(MAPGEO_OT_export_materials_merge)

def unregister():
    """Unregister operators"""
    bpy.utils.unregister_class(MAPGEO_OT_export_materials_to_league)
    bpy.utils.unregister_class(MAPGEO_OT_export_materials_json)
    bpy.utils.unregister_class(MAPGEO_OT_export_materials_merge)

if __name__ == "__main__":
    register()
