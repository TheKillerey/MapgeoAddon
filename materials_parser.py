"""
League of Legends Materials System Parser
Handles parsing, importing, and exporting of .materials.py files
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, asdict, field

# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class MaterialSampler:
    """Represents a texture sampler in a material"""
    textureName: str
    texturePath: str
    addressU: Optional[int] = None  # None = not present in original
    addressV: Optional[int] = None
    addressW: Optional[int] = None
    
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class MaterialParam:
    """Represents a shader parameter (vec4)"""
    name: str
    value: Optional[Tuple[float, float, float, float]]
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'value': list(self.value) if self.value is not None else None
        }

@dataclass
class MaterialSwitch:
    """Represents a shader switch (boolean)"""
    name: str
    on: Optional[bool] = None  # None = not present in original, only write when explicitly set
    group: Optional[str] = None  # Group category for the switch
    
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class MaterialPass:
    """Represents a rendering pass"""
    shader: str
    blendEnable: bool = False
    cullEnable: Optional[bool] = None  # None = not present in original
    srcColorBlendFactor: int = 1
    srcAlphaBlendFactor: int = 1
    dstColorBlendFactor: int = 0
    dstAlphaBlendFactor: int = 0
    writeMask: Optional[int] = None  # None = not present in original
    shaderMacros: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class MaterialTechnique:
    """Represents a rendering technique"""
    name: str
    passes: List[MaterialPass] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'passes': [p.to_dict() for p in self.passes]
        }

@dataclass
class MaterialChildTechnique:
    """Represents a child technique (variation)"""
    name: str
    parentName: str
    shaderMacros: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class Material:
    """Complete material definition"""
    name: str
    type: int = 0
    samplerValues: List[MaterialSampler] = field(default_factory=list)
    paramValues: List[MaterialParam] = field(default_factory=list)
    switches: List[MaterialSwitch] = field(default_factory=list)
    shaderMacros: Dict[str, str] = field(default_factory=dict)
    techniques: List[MaterialTechnique] = field(default_factory=list)
    childTechniques: List[MaterialChildTechnique] = field(default_factory=list)
    dynamicMaterial: Optional[str] = None  # Raw text of DynamicMaterialDef block (preserved as-is)
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'type': self.type,
            'samplerValues': [s.to_dict() for s in self.samplerValues],
            'paramValues': [p.to_dict() for p in self.paramValues],
            'switches': [s.to_dict() for s in self.switches],
            'shaderMacros': self.shaderMacros,
            'techniques': [t.to_dict() for t in self.techniques],
            'childTechniques': [ct.to_dict() for ct in self.childTechniques],
            'dynamicMaterial': self.dynamicMaterial,
        }

# ============================================================================
# Parser
# ============================================================================

class MaterialsParser:
    """Parses League .materials.py files"""
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.content = self._read_file()
        self.materials: Dict[str, Material] = {}
        self.other_entries: Dict[str, Tuple[str, str]] = {}  # name -> (type, raw_content)
        self.entry_order: List[Tuple[str, str]] = []  # Ordered list of (name, type) preserving original file order
    
    def _read_file(self) -> str:
        """Read materials file"""
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    def parse(self) -> Dict[str, Material]:
        """Parse all materials from file"""
        # Extract ALL entries from file (in original file order)
        # Returns (name, type, inner_content, full_text) tuples
        all_entries = self._extract_all_entries()
        
        # Separate materials from other entries, preserving order
        for entry_name, entry_type, entry_content, full_text in all_entries:
            self.entry_order.append((entry_name, entry_type))
            
            if entry_type == "StaticMaterialDef":
                # Parse materials (these are editable)
                try:
                    material = self._parse_material(entry_name, entry_content)
                    self.materials[entry_name] = material
                except Exception as e:
                    print(f"Warning: Failed to parse material {entry_name}: {e}")
            else:
                # Store all other entries as-is (VFX, MapPlaceableContainer, etc.)
                # full_text is captured in the first pass — no re-scan needed
                self.other_entries[entry_name] = (entry_type, full_text)
        
        return self.materials

    def _extract_all_entries(self) -> List[Tuple[str, str, str, str]]:
        """Extract all entries from the file.

        Returns list of (name, type, inner_content, full_text) tuples.
        full_text includes the header line + braces — captured here in a
        single pass so callers never need to re-scan the file.
        """
        entries = []
        # Match any top-level entry (4-space indent) with quoted name or unquoted hex hash
        # Quoted:   "name" = TypeName {
        # Unquoted: 0xABCDEF = TypeName {
        pattern = re.compile(r'^    (?:"([^"]+)"|(0x[0-9a-fA-F]+))\s*=\s*(\w+)\s*\{', re.MULTILINE)

        for match in pattern.finditer(self.content):
            entry_name = match.group(1) if match.group(1) else match.group(2)
            entry_type = match.group(3)
            brace_start = match.end() - 1  # position of the opening '{'
            brace_depth = 0
            end_idx = None

            for idx in range(brace_start, len(self.content)):
                char = self.content[idx]
                if char == '{':
                    brace_depth += 1
                elif char == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        end_idx = idx
                        break

            if end_idx is None:
                print(f"Warning: Unclosed entry block for {entry_name} ({entry_type})")
                continue

            # Inner content (without outer braces) — used for material parsing
            entry_content = self.content[brace_start + 1:end_idx]
            # Full text (header + braces) — used for round-trip preservation
            full_text = self.content[match.start():end_idx + 1]
            entries.append((entry_name, entry_type, entry_content, full_text))

        return entries
    
    def _get_full_entry_text(self, entry_name: str, entry_type: str) -> str:
        """Get the complete entry text including name and braces (for preservation)"""
        # Match this specific entry - handle both quoted and unquoted names
        if entry_name.startswith('0x'):
            # Unquoted hex hash
            pattern = re.compile(rf'({re.escape(entry_name)})\s*=\s*{re.escape(entry_type)}\s*\{{')
        else:
            # Quoted name
            pattern = re.compile(rf'"({re.escape(entry_name)})"\s*=\s*{re.escape(entry_type)}\s*\{{')
        match = pattern.search(self.content)
        
        if not match:
            return ""
        
        start_idx = match.start()
        brace_start = match.end() - 1
        brace_depth = 0
        end_idx = None

        for idx in range(brace_start, len(self.content)):
            char = self.content[idx]
            if char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    end_idx = idx + 1
                    break

        if end_idx is None:
            return ""
        
        return self.content[start_idx:end_idx]
    
    def _iter_material_blocks(self) -> List[Tuple[str, str]]:
        """Yield material name and full block content using brace matching"""
        blocks = []
        pattern = re.compile(r'"([^"]+)"\s*=\s*StaticMaterialDef\s*\{')

        for match in pattern.finditer(self.content):
            material_name = match.group(1)
            start_idx = match.end() - 1  # position of the opening '{'
            brace_depth = 0
            end_idx = None

            for idx in range(start_idx, len(self.content)):
                char = self.content[idx]
                if char == '{':
                    brace_depth += 1
                elif char == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        end_idx = idx
                        break

            if end_idx is None:
                print(f"Warning: Unclosed material block for {material_name}")
                continue

            material_content = self.content[start_idx + 1:end_idx]
            blocks.append((material_name, material_content))

        return blocks

    def _iter_blocks(self, content: str, block_type: str) -> List[str]:
        """Yield block contents using brace matching"""
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
    
    def _parse_material(self, name: str, content: str) -> Material:
        """Parse individual material"""
        material = Material(name=name)
        
        # Parse type
        type_match = re.search(r'type:\s*u32\s*=\s*(\d+)', content)
        if type_match:
            material.type = int(type_match.group(1))
        
        # Parse samplers
        material.samplerValues = self._parse_samplers(content)
        
        # Parse parameters
        material.paramValues = self._parse_params(content)
        
        # Parse switches
        material.switches = self._parse_switches(content)
        
        # Parse shader macros
        material.shaderMacros = self._parse_shader_macros(content)
        
        # Parse techniques
        material.techniques = self._parse_techniques(content)
        
        # Parse child techniques
        material.childTechniques = self._parse_child_techniques(content)
        
        # Parse dynamicMaterial (preserve as raw text)
        material.dynamicMaterial = self._parse_dynamic_material(content)
        
        return material
    
    def _parse_samplers(self, content: str) -> List[MaterialSampler]:
        """Parse sampler values"""
        samplers = []

        for sampler_content in self._iter_blocks(content, "StaticMaterialShaderSamplerDef"):
            
            tex_name_match = re.search(r'textureName:\s*string\s*=\s*"([^"]*)"', sampler_content)
            tex_path_match = re.search(r'texturePath:\s*string\s*=\s*"([^"]*)"', sampler_content)
            
            if tex_name_match:
                sampler = MaterialSampler(
                    textureName=tex_name_match.group(1),
                    texturePath=tex_path_match.group(1) if tex_path_match else ""
                )
                
                # Parse address modes
                for addr in ['U', 'V', 'W']:
                    addr_match = re.search(rf'address{addr}:\s*u32\s*=\s*(\d+)', sampler_content)
                    if addr_match:
                        setattr(sampler, f'address{addr}', int(addr_match.group(1)))
                
                samplers.append(sampler)
        
        return samplers
    
    def _parse_params(self, content: str) -> List[MaterialParam]:
        """Parse material parameters"""
        params = []

        for param_content in self._iter_blocks(content, "StaticMaterialShaderParamDef"):
            
            name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', param_content)
            value_match = re.search(r'value:\s*vec4\s*=\s*\{\s*([\d.\-, ]+?)\s*\}', param_content)
            
            if name_match:
                value = None
                if value_match:
                    values = [float(v.strip()) for v in value_match.group(1).split(',')]
                    while len(values) < 4:
                        values.append(0.0)
                    value = tuple(values[:4])
                
                params.append(MaterialParam(name=name_match.group(1), value=value))
        
        return params
    
    def _parse_switches(self, content: str) -> List[MaterialSwitch]:
        """Parse material switches"""
        switches = []

        for switch_content in self._iter_blocks(content, "StaticMaterialSwitchDef"):
            
            name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', switch_content)
            on_match = re.search(r'on:\s*bool\s*=\s*(true|false)', switch_content)
            
            if name_match:
                switch = MaterialSwitch(
                    name=name_match.group(1),
                    on=on_match.group(1).lower() == 'true' if on_match else None
                )
                # Parse optional Group field
                group_match = re.search(r'Group:\s*string\s*=\s*"([^"]*)"', switch_content)
                if group_match:
                    switch.group = group_match.group(1)
                
                switches.append(switch)
        
        return switches
    
    def _parse_shader_macros(self, content: str) -> Dict[str, str]:
        """Parse shader macros at material level only (8-space indent)"""
        macros = {}
        # Only match shaderMacros at material level (8 spaces), not inside passes (24 spaces)
        pattern = r'^        shaderMacros:\s*map\[string,string\]\s*=\s*\{(.*?)\}'
        
        match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
        if match:
            macros_content = match.group(1)
            for line in re.finditer(r'"([^"]+)"\s*=\s*"([^"]*)"', macros_content):
                macros[line.group(1)] = line.group(2)
        
        return macros
    
    def _parse_dynamic_material(self, content: str) -> Optional[str]:
        """Parse dynamicMaterial block and preserve as raw text"""
        pattern = r'^        dynamicMaterial:\s*pointer\s*=\s*DynamicMaterialDef\s*\{'
        match = re.search(pattern, content, re.MULTILINE)
        if not match:
            return None
        
        # Find the opening brace of DynamicMaterialDef
        brace_start = match.end() - 1
        brace_depth = 0
        end_idx = None
        
        for idx in range(brace_start, len(content)):
            char = content[idx]
            if char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    end_idx = idx + 1
                    break
        
        if end_idx is None:
            return None
        
        # Return the full line from 'dynamicMaterial:' through closing '}'
        return content[match.start():end_idx].strip()
    
    def _parse_techniques(self, content: str) -> List[MaterialTechnique]:
        """Parse rendering techniques"""
        techniques = []

        for technique_content in self._iter_blocks(content, "StaticMaterialTechniqueDef"):
            
            name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', technique_content)
            
            if name_match:
                technique = MaterialTechnique(name=name_match.group(1))
                
                # Parse passes
                for pass_content in self._iter_blocks(technique_content, "StaticMaterialPassDef"):
                    
                    shader_match = re.search(r'shader:\s*link\s*=\s*"([^"]*)"', pass_content)
                    blend_match = re.search(r'blendEnable:\s*bool\s*=\s*(true|false)', pass_content)
                    
                    pass_obj = MaterialPass(
                        shader=shader_match.group(1) if shader_match else ""
                    )
                    
                    if blend_match:
                        pass_obj.blendEnable = blend_match.group(1).lower() == 'true'
                    
                    # Parse cullEnable
                    cull_match = re.search(r'cullEnable:\s*bool\s*=\s*(true|false)', pass_content)
                    if cull_match:
                        pass_obj.cullEnable = cull_match.group(1).lower() == 'true'
                    
                    # Parse writeMask
                    write_mask_match = re.search(r'writeMask:\s*u32\s*=\s*(\d+)', pass_content)
                    if write_mask_match:
                        pass_obj.writeMask = int(write_mask_match.group(1))
                    
                    # Parse pass-level shaderMacros
                    macros_match = re.search(r'shaderMacros:\s*map\[string,string\]\s*=\s*\{(.*?)\}', pass_content, re.DOTALL)
                    if macros_match:
                        for line in re.finditer(r'"([^"]+)"\s*=\s*"([^"]*)"', macros_match.group(1)):
                            pass_obj.shaderMacros[line.group(1)] = line.group(2)
                    
                    # Parse blend factors
                    for factor in ['srcColorBlendFactor', 'srcAlphaBlendFactor', 
                                   'dstColorBlendFactor', 'dstAlphaBlendFactor']:
                        factor_match = re.search(rf'{factor}:\s*u32\s*=\s*(\d+)', pass_content)
                        if factor_match:
                            setattr(pass_obj, factor, int(factor_match.group(1)))
                    
                    technique.passes.append(pass_obj)
                
                techniques.append(technique)
        
        return techniques
    
    def _parse_child_techniques(self, content: str) -> List[MaterialChildTechnique]:
        """Parse child techniques"""
        child_techniques = []

        for child_content in self._iter_blocks(content, "StaticMaterialChildTechniqueDef"):
            
            name_match = re.search(r'name:\s*string\s*=\s*"([^"]*)"', child_content)
            parent_match = re.search(r'parentName:\s*string\s*=\s*"([^"]*)"', child_content)
            
            if name_match and parent_match:
                child = MaterialChildTechnique(
                    name=name_match.group(1),
                    parentName=parent_match.group(1)
                )
                
                # Parse shader macros
                macros_match = re.search(r'shaderMacros:\s*map\[string,string\]\s*=\s*\{(.*?)\}', child_content, re.DOTALL)
                if macros_match:
                    for line in re.finditer(r'"([^"]+)"\s*=\s*"([^"]*)"', macros_match.group(1)):
                        child.shaderMacros[line.group(1)] = line.group(2)
                
                child_techniques.append(child)
        
        return child_techniques
    
    def export_json(self, output_path: str) -> None:
        """Export parsed materials to JSON"""
        output = {
            'version': 1,
            'source_file': str(self.file_path),
            'material_count': len(self.materials),
            'materials': {name: mat.to_dict() for name, mat in self.materials.items()}
        }
        
        with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

# ============================================================================
# Exporter
# ============================================================================

class MaterialsExporter:
    """Exports materials back to League format"""
    
    @staticmethod
    def _format_float(value: float) -> str:
        """Format float values to match original file format.
        Whole numbers are written as integers (e.g., 0 not 0.0, 1 not 1.0)"""
        if value == int(value):
            return str(int(value))
        return str(value)
    
    @staticmethod
    def export(materials: Dict[str, Material], output_path: str, 
               other_entries: Dict[str, Tuple[str, str]] = None,
               entry_order: List[Tuple[str, str]] = None) -> None:
        """Export materials to .materials.py format
        
        Args:
            materials: Dictionary of Material objects to export
            output_path: Path to write the output file
            other_entries: Optional dict of name -> (type, raw_content) for non-material entries
            entry_order: Optional list of (name, type) tuples preserving original file order
        """
        lines = [
            "#PROP_text",
            'type: string = "PROP"',
            "version: u32 = 3",
            "linked: list[string] = {}",
            "entries: map[hash,embed] = {"
        ]
        
        if entry_order:
            # Write entries in original file order (interleaved)
            written_materials = set()
            written_others = set()
            
            for entry_name, entry_type in entry_order:
                if entry_type == "StaticMaterialDef":
                    if entry_name in materials:
                        MaterialsExporter._write_material(lines, entry_name, materials[entry_name])
                        written_materials.add(entry_name)
                else:
                    if other_entries and entry_name in other_entries:
                        MaterialsExporter._write_preserved_entry(lines, other_entries[entry_name][1])
                        written_others.add(entry_name)
            
            # Append any new materials not in original order (added in Blender)
            for mat_name, material in materials.items():
                if mat_name not in written_materials:
                    MaterialsExporter._write_material(lines, mat_name, material)
        else:
            # Fallback: write other_entries first, then materials (legacy behavior)
            if other_entries:
                for entry_name, (entry_type, entry_content) in other_entries.items():
                    MaterialsExporter._write_preserved_entry(lines, entry_content)
            
            for mat_name, material in materials.items():
                MaterialsExporter._write_material(lines, mat_name, material)
        
        lines.append("}")
        
        with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write("\n".join(lines))
            f.write("\n")  # Trailing newline to match original format
    
    @staticmethod
    def _write_preserved_entry(lines: list, entry_content: str) -> None:
        """Write a preserved (non-material) entry with correct indentation"""
        entry_lines = entry_content.split('\n')
        for i, entry_line in enumerate(entry_lines):
            if entry_line.strip():
                if i == 0:
                    # First line needs 4-space indent (entry declaration)
                    lines.append(f"    {entry_line}")
                else:
                    # Inner lines already have correct indentation from original file
                    lines.append(entry_line)
            else:
                lines.append("")
    
    @staticmethod
    def _write_material(lines: list, mat_name: str, material: 'Material') -> None:
        """Write a single material entry"""
        lines.append(f'    "{mat_name}" = StaticMaterialDef {{')
        lines.append(f'        name: string = "{material.name}"')
        lines.append(f'        type: u32 = {material.type}')
        
        # Export samplers
        if material.samplerValues:
            lines.append("        samplerValues: list2[embed] = {")
            for sampler in material.samplerValues:
                lines.append("            StaticMaterialShaderSamplerDef {")
                lines.append(f'                textureName: string = "{sampler.textureName}"')
                lines.append(f'                texturePath: string = "{sampler.texturePath}"')
                if sampler.addressU is not None:
                    lines.append(f"                addressU: u32 = {sampler.addressU}")
                if sampler.addressV is not None:
                    lines.append(f"                addressV: u32 = {sampler.addressV}")
                # addressW is only written when explicitly present in original
                if sampler.addressW is not None:
                    lines.append(f"                addressW: u32 = {sampler.addressW}")
                lines.append("            }")
            lines.append("        }")
        
        # Export parameters
        if material.paramValues:
            lines.append("        paramValues: list2[embed] = {")
            for param in material.paramValues:
                lines.append("            StaticMaterialShaderParamDef {")
                lines.append(f'                name: string = "{param.name}"')
                if param.value is not None:
                    values = ", ".join(MaterialsExporter._format_float(v) for v in param.value)
                    lines.append(f"                value: vec4 = {{ {values} }}")
                lines.append("            }")
            lines.append("        }")
        
        # Export switches
        if material.switches:
            lines.append("        switches: list2[embed] = {")
            for switch in material.switches:
                lines.append("            StaticMaterialSwitchDef {")
                lines.append(f'                name: string = "{switch.name}"')
                # Only write on: bool when explicitly set (matches original format)
                if switch.on is not None:
                    lines.append(f'                on: bool = {"true" if switch.on else "false"}')
                # Write Group if present
                if switch.group is not None:
                    lines.append(f'                Group: string = "{switch.group}"')
                lines.append("            }")
            lines.append("        }")
        
        # Export shader macros
        if material.shaderMacros:
            lines.append("        shaderMacros: map[string,string] = {")
            for macro_name, macro_value in material.shaderMacros.items():
                lines.append(f'            "{macro_name}" = "{macro_value}"')
            lines.append("        }")
        
        # Export techniques
        if material.techniques:
            lines.append("        techniques: list[embed] = {")
            for technique in material.techniques:
                lines.append("            StaticMaterialTechniqueDef {")
                lines.append(f'                name: string = "{technique.name}"')
                lines.append("                passes: list[embed] = {")
                for pass_obj in technique.passes:
                    lines.append("                    StaticMaterialPassDef {")
                    if pass_obj.shader:
                        lines.append(f'                        shader: link = "{pass_obj.shader}"')
                    # Write pass-level shaderMacros if present
                    if pass_obj.shaderMacros:
                        lines.append("                        shaderMacros: map[string,string] = {")
                        for macro_name, macro_value in pass_obj.shaderMacros.items():
                            lines.append(f'                            "{macro_name}" = "{macro_value}"')
                        lines.append("                        }")
                    if pass_obj.blendEnable:
                        lines.append('                        blendEnable: bool = true')
                    # Write cullEnable if explicitly set
                    if pass_obj.cullEnable is not None:
                        lines.append(f'                        cullEnable: bool = {"true" if pass_obj.cullEnable else "false"}')
                    # Write blend factors that differ from defaults
                    # src defaults = 1, dst defaults = 0
                    if pass_obj.srcColorBlendFactor != 1:
                        lines.append(f'                        srcColorBlendFactor: u32 = {pass_obj.srcColorBlendFactor}')
                    if pass_obj.srcAlphaBlendFactor != 1:
                        lines.append(f'                        srcAlphaBlendFactor: u32 = {pass_obj.srcAlphaBlendFactor}')
                    if pass_obj.dstColorBlendFactor != 0:
                        lines.append(f'                        dstColorBlendFactor: u32 = {pass_obj.dstColorBlendFactor}')
                    if pass_obj.dstAlphaBlendFactor != 0:
                        lines.append(f'                        dstAlphaBlendFactor: u32 = {pass_obj.dstAlphaBlendFactor}')
                    if pass_obj.writeMask is not None:
                        lines.append(f'                        writeMask: u32 = {pass_obj.writeMask}')
                    lines.append("                    }")
                lines.append("                }")
                lines.append("            }")
            lines.append("        }")
        
        # Export child techniques
        if material.childTechniques:
            lines.append("        childTechniques: list[embed] = {")
            for child_tech in material.childTechniques:
                lines.append("            StaticMaterialChildTechniqueDef {")
                lines.append(f'                name: string = "{child_tech.name}"')
                lines.append(f'                parentName: string = "{child_tech.parentName}"')
                if child_tech.shaderMacros:
                    lines.append("                shaderMacros: map[string,string] = {")
                    for macro_name, macro_value in child_tech.shaderMacros.items():
                        lines.append(f'                    "{macro_name}" = "{macro_value}"')
                    lines.append("                }")
                lines.append("            }")
            lines.append("        }")
        
        # Export dynamicMaterial (preserved raw text)
        if material.dynamicMaterial:
            lines.append(f"        {material.dynamicMaterial}")
        
        lines.append("    }")
    
    @staticmethod
    def export_with_preserved_entries(materials: Dict[str, Material], 
                                       other_entries: Dict[str, Tuple[str, str]], 
                                       entry_order: List[Tuple[str, str]],
                                       output_path: str) -> None:
        """Convenience method to export with preserved non-material entries"""
        MaterialsExporter.export(materials, output_path, other_entries, entry_order)

if __name__ == "__main__":
    # Example usage
    parser = MaterialsParser(r"C:\Riot Games\League of Legends\Game\DATA\FINAL\Maps\Shipping\Map11.wad\data\maps\mapgeometry\map11\base.materials.py")
    materials = parser.parse()
    print(f"Parsed {len(materials)} materials")
    
    # Export as JSON for analysis
    parser.export_json("materials_sample.json")
    print("Exported to materials_sample.json")
