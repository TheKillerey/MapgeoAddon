"""
Baron Hash Controller Parser
Parses materials.bin.json OR materials.py to decode ChildMapVisibilityController structures
and determine which baron/dragon layers a mesh is visible on.

Supports both JSON (.json) and Python (.py) material file formats.
"""

import json
import os
import re


class BaronHashController:
    """Represents a decoded baron hash controller with its visibility logic"""
    
    def __init__(self, path_hash, parent_mode=0, parents=None):
        self.path_hash = path_hash
        self.parent_mode = parent_mode  # 1 = Visible, 3 = Not Visible
        self.parents = parents or []
        
        # Decoded visibility
        self.baron_layers = set()  # Which baron layers (1=Cup, 2=Tunnel, 3=Upgraded, 0=Base)
        self.dragon_layers = set()  # Which dragon layers (bits from visibility_layer)


class MaterialsBinParser:
    """Parser for materials.bin.json to extract visibility controller data"""
    
    # Type identifiers (JSON format uses curly braces)
    TYPE_CHILD_CONTROLLER = "ChildMapVisibilityController"
    TYPE_DRAGON_LAYER = "{c406a533}"  # Dragon layer visibility flag
    TYPE_BARON_LAYER = "{ec733fe2}"   # Baron pit layer visibility flag
    TYPE_NAMED_CONTROLLER = "{e07edfa4}"  # Named controller
    
    # Property names (JSON format uses curly braces)
    PROP_DRAGON_LAYER_BIT = "{27639032}"  # Dragon layer bit value
    PROP_BARON_LAYER_BIT = "{8bff8cdf}"   # Baron layer bit value
    
    def __init__(self, materials_path):
        self.materials_path = materials_path
        self.data = {}
        self.controllers = {}  # PathHash -> controller data
        self.file_format = None  # 'json' or 'py'
        
        if os.path.exists(materials_path):
            # Detect format
            if materials_path.endswith('.json'):
                self.file_format = 'json'
            elif materials_path.endswith('.py'):
                self.file_format = 'py'
            else:
                print(f"[BaronHash] Warning: Unknown file extension for {materials_path}")
                self.file_format = 'json'  # Default to JSON
            
            self.load()
    
    def load(self):
        """Load and parse materials file (JSON or Python format)"""
        try:
            if self.file_format == 'py':
                # Parse .py format and convert to dict
                self.data = self._parse_py_file()
            else:
                # Load JSON format
                with open(self.materials_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            
            # Index all controllers by their PathHash
            self._index_controllers()
            
            format_str = "Python .py" if self.file_format == 'py' else "JSON"
            print(f"[BaronHash] Loaded {len(self.controllers)} visibility controllers from {format_str}")
            return True
        except Exception as e:
            print(f"[BaronHash] Error loading materials file: {e}")
            return False
    
    def _parse_py_file(self):
        """Parse .py format and convert to dict format compatible with JSON parser"""
        with open(self.materials_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        controllers_dict = {}
        
        # Pattern to match controller definitions:
        # 0x5e652742 = ChildMapVisibilityController { ... }
        # Need to handle nested braces in Parents list
        # Strategy: Find each controller start, then manually find matching closing brace
        
        # Only process visibility controller types (not particles, placeables, etc.)
        valid_types = {
            'ChildMapVisibilityController',
            '0xc406a533',  # Dragon layer controller
            '0xe07edfa4',  # Named controller
            '0xec733fe2',  # Baron layer controller
            'MutatorMapVisibilityController',
        }
        
        controller_starts = list(re.finditer(r'(0x[0-9a-fA-F]{8})\s*=\s*([^\s{]+)\s*\{', content))
        
        for i, match in enumerate(controller_starts):
            path_hash = match.group(1).upper()  # 0X5E652742
            controller_type = match.group(2)     # ChildMapVisibilityController or 0xc406a533
            
            # Skip non-visibility-controller types (particles, placeables, etc.)
            if controller_type not in valid_types:
                continue
            
            start_pos = match.end()  # Position after opening {
            
            # Find matching closing brace
            brace_count = 1
            pos = start_pos
            while pos < len(content) and brace_count > 0:
                if content[pos] == '{':
                    brace_count += 1
                elif content[pos] == '}':
                    brace_count -= 1
                pos += 1
            
            controller_body = content[start_pos:pos-1]  # Exclude the closing }
            
            # Store with format compatible with JSON: use curly braces without 0x
            hashkey = "{" + path_hash[2:].lower() + "}"  # "{5e652742}"
            
            # Create controller dict compatible with JSON format
            controller_data = {
                'PathHash': hashkey,
                '__type': controller_type  # JSON uses __type field
            }
            
            # Parse Parents list
            parents_match = re.search(r'Parents:\s*list2\[link\]\s*=\s*\{([^}]+)\}', controller_body)
            if parents_match:
                parents_str = parents_match.group(1)
                # Extract all hex values and convert to JSON format
                parents_hex = re.findall(r'0x[0-9a-fA-F]{8}', parents_str)
                controller_data['Parents'] = ["{" + p[2:].lower() + "}" for p in parents_hex]
            
            # Parse ParentMode
            parent_mode_match = re.search(r'ParentMode:\s*u32\s*=\s*(\d+)', controller_body)
            if parent_mode_match:
                controller_data['ParentMode'] = int(parent_mode_match.group(1))
            
            # Parse dragon layer bit (0x27639032)
            dragon_bit_match = re.search(r'0x27639032:\s*u8\s*=\s*(\d+)', controller_body)
            if dragon_bit_match:
                controller_data[self.PROP_DRAGON_LAYER_BIT] = int(dragon_bit_match.group(1))
            
            # Parse baron layer bit (0x8bff8cdf)
            baron_bit_match = re.search(r'0x8bff8cdf:\s*u8\s*=\s*(\d+)', controller_body)
            if baron_bit_match:
                controller_data[self.PROP_BARON_LAYER_BIT] = int(baron_bit_match.group(1))
            
            # Store in dict
            controllers_dict[hashkey] = controller_data
        
        return controllers_dict
    
    def _index_controllers(self):
        """Index all visibility controllers from the materials data"""
        if not self.data:
            return
        
        # Materials.bin.json structure: keys and PathHash values use curly braces like "{5e652742}"
        for key, value in self.data.items():
            if isinstance(value, dict):
                # Check if this is a controller
                if "PathHash" in value:
                    path_hash_str = value["PathHash"]
                    
                    # Extract just the hash value (remove "hash = " prefix if present)
                    if isinstance(path_hash_str, str):
                        path_hash_str = path_hash_str.replace("hash = ", "").strip()
                    
                    # Store with original format (includes curly braces)
                    self.controllers[path_hash_str] = value
                    
                    # Also store without curly braces for easier lookup
                    hash_no_braces = path_hash_str.strip("{}").lower()
                    self.controllers[hash_no_braces] = value
    
    def decode_baron_hash(self, baron_hash):
        """
        Decode a baron hash to determine which baron and dragon layers it's visible on.
        
        Args:
            baron_hash: hex string like "5E652742"
            
        Returns:
            BaronHashController with decoded visibility info
        """
        controller = BaronHashController(baron_hash)
        
        # Find the controller in our data
        # Blender stores hashes in uppercase like "5E652742", JSON uses "{5e652742}"
        # Try various formats
        controller_data = self.controllers.get(baron_hash.lower())
        if not controller_data:
            controller_data = self.controllers.get(f"{{{baron_hash.lower()}}}")
        if not controller_data:
            controller_data = self.controllers.get(baron_hash.upper())
        if not controller_data:
            controller_data = self.controllers.get(f"{{{baron_hash.upper()}}}")
        
        if not controller_data:
            print(f"[BaronHash] Controller {baron_hash} not found in materials.bin.json")
            print(f"[BaronHash] Available controllers: {len(self.controllers)}")
            return controller
        
        # Check if it's a ChildMapVisibilityController
        # JSON format uses "__type": "ChildMapVisibilityController"
        is_child_controller = False
        type_value = controller_data.get("__type", controller_data.get("type", ""))
        if isinstance(type_value, str) and "ChildMapVisibilityController" in type_value:
            is_child_controller = True
        
        if not is_child_controller:
            # Check for Parents key which indicates child controller
            is_child_controller = "Parents" in controller_data or "parents" in controller_data
        
        if is_child_controller:
            # Get parent mode (default to 1 = Visible if not specified)
            parent_mode = controller_data.get("ParentMode", controller_data.get("parentMode", 1))
            if isinstance(parent_mode, str):
                parent_mode = int(parent_mode.replace("u32 = ", "").strip())
            if parent_mode == 0:
                parent_mode = 1  # Treat unset/0 as Visible mode
            controller.parent_mode = parent_mode
            
            # Get parent list
            parents = controller_data.get("Parents", controller_data.get("parents", []))
            
            # Parents might be in different formats
            if isinstance(parents, dict):
                # Format: { "list2[link]": [...] }
                for key, value in parents.items():
                    if "list" in key.lower() and isinstance(value, list):
                        parents = value
                        break
            
            if isinstance(parents, list):
                # Resolve each parent
                for parent_ref in parents:
                    self._resolve_parent(parent_ref, controller, parent_mode)
        else:
            # Not a child controller - might be a direct baron or dragon layer controller
            # Check if it's a direct baron layer controller
            baron_bit = controller_data.get(self.PROP_BARON_LAYER_BIT)
            if baron_bit is not None:
                if isinstance(baron_bit, str):
                    baron_bit = int(baron_bit.replace("u8 = ", "").strip())
                
                # Store the actual bit value (not an index)
                controller.baron_layers.add(baron_bit)
                controller.parent_mode = 1  # Single direct reference
            
            # Check if it's a direct dragon layer controller
            dragon_bit = controller_data.get(self.PROP_DRAGON_LAYER_BIT)
            if dragon_bit is not None:
                if isinstance(dragon_bit, str):
                    dragon_bit = int(dragon_bit.replace("u8 = ", "").strip())
                
                controller.dragon_layers.add(dragon_bit)
                controller.parent_mode = 1  # Single direct reference
        
        return controller
    
    def _resolve_parent(self, parent_ref, controller, parent_mode):
        """Resolve a parent reference to determine layer visibility"""
        # Parent ref might be a hash string with curly braces like "{48106271}"
        if isinstance(parent_ref, str):
            parent_hash = parent_ref.strip()
        else:
            parent_hash = str(parent_ref)
        
        # Find parent in controllers (JSON format uses curly braces)
        parent_data = self.controllers.get(parent_hash)
        if not parent_data:
            # Try without curly braces
            parent_data = self.controllers.get(parent_hash.strip("{}").lower())
        if not parent_data:
            # Try with curly braces
            parent_data = self.controllers.get(f"{{{parent_hash.strip('{}')}}}")
        
        if not parent_data:
            return
        
        # Check what type of controller this parent is
        # Look for dragon layer bit
        dragon_bit = parent_data.get(self.PROP_DRAGON_LAYER_BIT)
        if dragon_bit is not None:
            if isinstance(dragon_bit, str):
                dragon_bit = int(dragon_bit.replace("u8 = ", "").strip())
            
            # This parent represents a dragon layer - always add it
            controller.dragon_layers.add(dragon_bit)
        
        # Check for baron layer bit
        baron_bit = parent_data.get(self.PROP_BARON_LAYER_BIT)
        if baron_bit is not None:
            if isinstance(baron_bit, str):
                baron_bit = int(baron_bit.replace("u8 = ", "").strip())
            
            # This parent represents a baron layer - always add it
            controller.baron_layers.add(baron_bit)
        
        # Check if this parent is itself a child controller (recursive)
        is_child = False
        type_value = parent_data.get("__type", parent_data.get("type", ""))
        if isinstance(type_value, str) and "ChildMapVisibilityController" in type_value:
            is_child = True
        
        if not is_child:
            is_child = "Parents" in parent_data or "parents" in parent_data
        
        if is_child:
            # Recursively resolve this parent's parents
            sub_parents = parent_data.get("Parents", parent_data.get("parents", []))
            if isinstance(sub_parents, dict):
                for key, value in sub_parents.items():
                    if "list" in key.lower() and isinstance(value, list):
                        sub_parents = value
                        break
            
            if isinstance(sub_parents, list):
                sub_parent_mode = parent_data.get("ParentMode", parent_data.get("parentMode", parent_mode))
                if isinstance(sub_parent_mode, str):
                    sub_parent_mode = int(sub_parent_mode.replace("u32 = ", "").strip())
                
                for sub_parent_ref in sub_parents:
                    self._resolve_parent(sub_parent_ref, controller, sub_parent_mode)


def get_baron_layer_name(layer_bit):
    """Get the name of a baron layer by its bit value"""
    names = {
        1: "Base",
        2: "Cup",
        4: "Tunnel",
        8: "Upgraded"
    }
    return names.get(layer_bit, f"Custom ({layer_bit})")


def get_dragon_layer_name(layer_bit):
    """Get the name of a dragon layer by its bit value"""
    names = {
        1: "Base",
        2: "Inferno",
        4: "Mountain",
        8: "Ocean",
        16: "Cloud",
        32: "Hextech",
        64: "Chemtech",
        128: "Void"
    }
    return names.get(layer_bit, f"Unknown ({layer_bit})")
