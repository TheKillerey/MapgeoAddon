"""
Baron Hash Controller Parser
Parses materials.bin.json to decode ChildMapVisibilityController structures
and determine which baron/dragon layers a mesh is visible on.
"""

import json
import os


class BaronHashController:
    """Represents a decoded baron hash controller with its visibility logic"""
    
    def __init__(self, path_hash, parent_mode=0, parents=None):
        self.path_hash = path_hash
        self.parent_mode = parent_mode  # 1 = OR (any), 3 = AND (all)
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
    
    def __init__(self, materials_json_path):
        self.materials_json_path = materials_json_path
        self.data = {}
        self.controllers = {}  # PathHash -> controller data
        
        if os.path.exists(materials_json_path):
            self.load()
    
    def load(self):
        """Load and parse materials.bin.json"""
        try:
            with open(self.materials_json_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            
            # Index all controllers by their PathHash
            self._index_controllers()
            
            print(f"[BaronHash] Loaded {len(self.controllers)} visibility controllers")
            return True
        except Exception as e:
            print(f"[BaronHash] Error loading materials.bin.json: {e}")
            return False
    
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
            # Get parent mode
            parent_mode = controller_data.get("ParentMode", controller_data.get("parentMode", 0))
            if isinstance(parent_mode, str):
                parent_mode = int(parent_mode.replace("u32 = ", "").strip())
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
                
                # Map bit to baron layer index
                if baron_bit == 1:
                    layer_index = 0  # Base
                elif baron_bit == 2:
                    layer_index = 1  # Cup
                elif baron_bit == 4:
                    layer_index = 2  # Tunnel
                elif baron_bit == 8:
                    layer_index = 3  # Upgraded
                else:
                    layer_index = baron_bit  # Unknown
                
                controller.baron_layers.add(layer_index)
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
            
            # This parent represents a dragon layer
            # ParentMode 3 = AND = visible when this layer is active
            # ParentMode 1 = OR = visible when any parent is active
            if parent_mode == 3:  # AND mode - visible on this layer
                controller.dragon_layers.add(dragon_bit)
            elif parent_mode == 1:  # OR mode - might be visible
                controller.dragon_layers.add(dragon_bit)
        
        # Check for baron layer bit
        baron_bit = parent_data.get(self.PROP_BARON_LAYER_BIT)
        if baron_bit is not None:
            if isinstance(baron_bit, str):
                baron_bit = int(baron_bit.replace("u8 = ", "").strip())
            
            # This parent represents a baron layer
            # Map bit to baron layer index (1=Cup, 2=Tunnel, 4=Upgraded, 8=bit3)
            if baron_bit == 1:
                layer_index = 0  # Base
            elif baron_bit == 2:
                layer_index = 1  # Cup
            elif baron_bit == 4:
                layer_index = 2  # Tunnel
            elif baron_bit == 8:
                layer_index = 3  # Upgraded
            else:
                layer_index = baron_bit  # Unknown
            
            if parent_mode == 3:  # AND mode - visible on this layer
                controller.baron_layers.add(layer_index)
            elif parent_mode == 1:  # OR mode - might be visible
                controller.baron_layers.add(layer_index)
        
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


def get_baron_layer_name(layer_index):
    """Get the name of a baron layer by index"""
    names = {
        0: "Base",
        1: "Cup",
        2: "Tunnel",
        3: "Upgraded"
    }
    return names.get(layer_index, f"Unknown ({layer_index})")


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
