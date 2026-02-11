#!/usr/bin/env python3
"""Understand baron hash behavior with actual test data"""

from mapgeo_parser import MapgeoParser

parser = MapgeoParser()
mapgeo = parser.read('LeagueTestMap/sodapop_srs_original.mapgeo')

print("=== KEY INSIGHT ===")
print("Meshes can have BOTH visibility_layer AND baron_hash")
print("Baron hash adds baron pit state control ON TOP OF dragon layer visibility")
print()

print("=== EXAMPLE ANALYSIS ===")
print()

# Example 1: Baron hash 8E6A128E with visibility 64 (Chemtech)
print("Example 1: Baron Hash 8E6A128E")
print("  - 219 meshes with visibility_layer=64 (Chemtech only)")
print("  - These meshes should be visible:")
print("    * On Chemtech dragon map (because visibility_layer=64)")
print("    * On whatever baron pit state the hash decodes to")
print("  - They should NOT be visible on Base/Inferno/Mountain/etc dragon maps")
print()

# Example 2: Baron hash C11C84E8 with visibility 255
print("Example 2: Baron Hash C11C84E8 (user's question)")
print("  - 3 meshes with visibility_layer=255 (AllLayers)")
print("  - These meshes should be visible:")
print("    * On ALL dragon variations (because visibility_layer=255)")
print("    * On Cup baron pit state (hash decodes to bit 2)")
print()

# Example 3: Baron hash 3C5B24F7 with mixed visibility
print("Example 3: Baron Hash 3C5B24F7")
print("  - 138 meshes with visibility_layer=8, 127, or 255")  
print("  - vis_layer 8 = Ocean only")
print("  - vis_layer 127 = Most dragon layers (bits 0-6)")
print("  - vis_layer 255 = All dragon layers")
print("  - The baron hash adds baron pit state control")
print()

# Example 4: No baron hash
print("Example 4: Meshes WITHOUT baron hash")
count_no_baron = sum(1 for m in mapgeo.meshes if not m.visibility_controller_path_hash or m.visibility_controller_path_hash == 0)
print(f"  - {count_no_baron} meshes have no baron hash")
print("  - These use ONLY visibility_layer for dragon variations")
print("  - They appear on ALL baron pit states (no baron-specific control)")
print()

print("=== CORRECT VISIBILITY LOGIC ===")
print()
print("For a mesh to be visible:")
print("1. Check visibility_layer against current dragon layer")
print("   - If bit 0 (Base=1): Always visible on all dragon maps")
print("   - If visibility_layer=255: Always visible")
print("   - Otherwise: Check if dragon layer bit is set")
print()
print("2. IF mesh has baron_hash:")
print("   - Decode baron_layers_decoded from materials.bin")
print("   - Check if current baron pit state is in baron_layers_decoded")
print("   - If baron_dragon_layers_decoded exists:")
print("     * Check if current dragon layer is referenced")
print("     * This might be additional filtering")
print()
print("3. Final visibility = (dragon check) AND (baron check if hash exists)")
