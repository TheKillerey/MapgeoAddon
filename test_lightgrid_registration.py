"""
Test script to check LightGrid panel registration
Run this in Blender's Text Editor to diagnose issues
"""

import bpy

# Check if operators are registered
operators_to_check = [
    "mapgeo.import_lightgrid",
    "mapgeo.export_lightgrid",
    "mapgeo.clear_lightgrid",
]

print("\n=== Checking LightGrid Operators ===")
for op_id in operators_to_check:
    try:
        op = eval(f"bpy.ops.{op_id}")
        print(f"✓ {op_id} is registered")
    except AttributeError:
        print(f"✗ {op_id} NOT registered")

# Check if panel is registered
print("\n=== Checking LightGrid Panel ===")
panel_name = "VIEW3D_PT_mapgeo_lightgrid_panel"
if panel_name in dir(bpy.types):
    print(f"✓ {panel_name} is registered")
    panel_class = getattr(bpy.types, panel_name)
    print(f"  Category: {panel_class.bl_category}")
    print(f"  Label: {panel_class.bl_label}")
    print(f"  Parent: {panel_class.bl_parent_id}")
else:
    print(f"✗ {panel_name} NOT registered")

# Check parent panel
print("\n=== Checking Parent Panel ===")
parent_name = "VIEW3D_PT_mapgeo_panel"
if parent_name in dir(bpy.types):
    print(f"✓ {parent_name} is registered")
else:
    print(f"✗ {parent_name} NOT registered - THIS IS THE PROBLEM!")

# Try to manually check lightgrid_parser import
print("\n=== Checking lightgrid_parser Module ===")
try:
    import sys
    import os
    addon_path = os.path.dirname(os.path.realpath(__file__))
    if addon_path not in sys.path:
        sys.path.append(addon_path)
    
    # Try direct import
    from MapgeoAddon import lightgrid_parser
    print(f"✓ lightgrid_parser imported successfully")
    print(f"  Has LightGrid class: {hasattr(lightgrid_parser, 'LightGrid')}")
except Exception as e:
    print(f"✗ lightgrid_parser import failed: {e}")

print("\n=== Addon Info ===")
addon = bpy.context.preferences.addons.get("MapgeoAddon")
if addon:
    print(f"✓ MapgeoAddon is enabled")
else:
    print(f"✗ MapgeoAddon is NOT enabled")

print("\nDone!")
