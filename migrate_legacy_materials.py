#!/usr/bin/env python3
"""
Migrate legacy materials.py files to new field names.

Changes:
  samplerName -> textureName
  textureName -> texturePath
"""

import sys
from pathlib import Path

def migrate_materials_file(filepath):
    """Update legacy materials.py file with new field names."""
    filepath = Path(filepath)
    
    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}")
        return False
    
    print(f"Migrating: {filepath}")
    
    # Read the file
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_size = len(content)
    original_lines = len(content.splitlines())
    
    # Count occurrences
    sampler_count = content.count('samplerName')
    texture_name_count = content.count('textureName')
    
    print(f"  Original size: {original_size} bytes, {original_lines} lines")
    print(f"  Found samplerName: {sampler_count} times")
    print(f"  Found textureName: {texture_name_count} times")
    
    # Apply replacements carefully:
    # 1. samplerName -> __TEMP_NEWNAME1__
    # 2. textureName -> texturePath
    # 3. __TEMP_NEWNAME1__ -> textureName
    
    updated = content.replace('samplerName', '__TEMP_NEWNAME1__')
    updated = updated.replace('textureName', 'texturePath')
    updated = updated.replace('__TEMP_NEWNAME1__', 'textureName')
    
    # Verify counts
    texture_path_count = updated.count('texturePath')
    texture_name_new_count = updated.count('textureName')
    sampler_remaining = updated.count('samplerName')
    
    print(f"  After migration:")
    print(f"    samplerName remaining: {sampler_remaining} (should be 0)")
    print(f"    textureName: {texture_name_new_count} (should be {sampler_count})")
    print(f"    texturePath: {texture_path_count} (should be {texture_name_count})")
    
    updated_size = len(updated)
    updated_lines = len(updated.splitlines())
    print(f"  New size: {updated_size} bytes, {updated_lines} lines")
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(updated)
    
    print(f"✓ Successfully updated: {filepath}")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python migrate_legacy_materials.py <path_to_materials_file>")
        print()
        print("Example:")
        print("  python migrate_legacy_materials.py")
        print("    D:\\Mods\\ProjectRift2025\\Map11.wad\\data\\maps\\mapgeometry\\map11\\base_srx.materials.py")
        sys.exit(1)
    
    filepath = sys.argv[1]
    success = migrate_materials_file(filepath)
    sys.exit(0 if success else 1)
