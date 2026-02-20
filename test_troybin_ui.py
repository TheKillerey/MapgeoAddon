"""
Test script for League Tools Troybin UI
Run this in Blender's scripting console to test the UI
"""

import bpy
import os

def test_troybin_ui():
    """Test the League Tools Troybin UI"""
    print("\n" + "="*60)
    print("Testing League Tools - Troybin UI")
    print("="*60)
    
    # Check if addon is registered
    print("\n1. Checking addon registration...")
    try:
        settings = bpy.context.scene.troybin_settings
        print("   ✓ Troybin settings found")
    except AttributeError:
        print("   ✗ Troybin settings NOT found - addon may not be registered")
        return False
    
    # Check operators are available
    print("\n2. Checking operators...")
    operators = [
        'troybin.import_file',
        'troybin.export_file',
        'troybin.reload_file',
        'troybin.clear_data',
        'troybin.create_new'
    ]
    
    for op in operators:
        if hasattr(bpy.ops.troybin, op.split('.')[1]):
            print(f"   ✓ {op}")
        else:
            print(f"   ✗ {op} NOT found")
    
    # Test import with custom particle
    print("\n3. Testing import...")
    addon_path = os.path.dirname(__file__)
    test_file = os.path.join(addon_path, "test_simple_glow.troybin")
    
    if os.path.exists(test_file):
        print(f"   Found test file: {os.path.basename(test_file)}")
        try:
            bpy.ops.troybin.import_file(filepath=test_file)
            print(f"   ✓ Import successful")
            print(f"   - Emitters: {len(settings.emitters)}")
            print(f"   - Properties: {len(settings.properties)}")
            
            # List emitters
            if settings.emitters:
                print("\n   Emitters:")
                for i, emitter in enumerate(settings.emitters):
                    print(f"     {i+1}. {emitter.name} ({emitter.property_count} props)")
            
            # Show some properties
            if settings.properties:
                print("\n   Sample Properties:")
                for i, prop in enumerate(settings.properties[:10]):
                    value = ""
                    if prop.prop_type in ['Int32List', 'Int16List', 'Int8List']:
                        value = str(prop.value_int)
                    elif prop.prop_type == 'BitList':
                        value = str(prop.value_bool)
                    elif prop.prop_type == 'StringList':
                        value = prop.value_string
                    elif prop.prop_type in ['Float32List', 'FixedPointFloatList']:
                        value = f"{prop.value_float:.2f}"
                    
                    print(f"     {prop.prop_name} = {value}")
            
        except Exception as e:
            print(f"   ✗ Import failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"   ⚠ Test file not found: {test_file}")
    
    # Test create new
    print("\n4. Testing create new particle...")
    try:
        bpy.ops.troybin.create_new(emitter_name="test_emitter")
        print(f"   ✓ Created new particle")
        print(f"   - Emitters: {len(settings.emitters)}")
    except Exception as e:
        print(f"   ✗ Create new failed: {e}")
    
    # Test export
    print("\n5. Testing export...")
    try:
        import tempfile
        test_export = os.path.join(tempfile.gettempdir(), "test_export.troybin")
        bpy.ops.troybin.export_file(filepath=test_export)
        
        if os.path.exists(test_export):
            file_size = os.path.getsize(test_export)
            print(f"   ✓ Export successful: {file_size} bytes")
            os.remove(test_export)
        else:
            print(f"   ✗ Export file not created")
    except Exception as e:
        print(f"   ✗ Export failed: {e}")
    
    # Test clear
    print("\n6. Testing clear...")
    try:
        bpy.ops.troybin.clear_data()
        print(f"   ✓ Data cleared")
        print(f"   - Loaded: {settings.is_loaded}")
    except Exception as e:
        print(f"   ✗ Clear failed: {e}")
    
    print("\n" + "="*60)
    print("Test complete!")
    print("="*60)
    print("\nTo access the UI:")
    print("1. Open 3D Viewport")
    print("2. Press 'N' to show sidebar")
    print("3. Look for 'League Tools' tab")
    print("="*60 + "\n")
    
    return True

if __name__ == "__main__":
    test_troybin_ui()
