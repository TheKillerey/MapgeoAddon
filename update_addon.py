"""
Quick update script for MapgeoAddon
Copies files to Blender and cleans __pycache__ folders
"""

import os
import shutil
import sys

def main():
    source = r"D:\BlenderAddons\MapgeoAddon"
    target = r"C:\Users\theki\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\MapgeoAddon"
    
    print("Updating MapgeoAddon...")
    
    # Files/folders to exclude from copy
    exclude = {
        '__pycache__', '.git', '.gitignore', 
        'LeagueTestMap', 'LeagueToolkit',
        'install_addon.py', 'update_addon.py'
    }
    
    # Ensure target directory exists
    os.makedirs(target, exist_ok=True)
    
    # Copy Python files
    for item in os.listdir(source):
        # Skip excluded items, markdown files, and test/debug scripts (starting with _)
        if item in exclude or item.endswith('.md') or (item.startswith('_') and item != '__init__.py'):
            continue
            
        source_path = os.path.join(source, item)
        target_path = os.path.join(target, item)
        
        if os.path.isfile(source_path):
            shutil.copy2(source_path, target_path)
            print(f"  Copied: {item}")
    
    # Clean all __pycache__ folders
    removed_count = 0
    for root, dirs, files in os.walk(target):
        if '__pycache__' in dirs:
            pycache_path = os.path.join(root, '__pycache__')
            shutil.rmtree(pycache_path)
            removed_count += 1
    
    print(f"\n✓ Update complete!")
    print(f"✓ Cleaned {removed_count} __pycache__ folder(s)")
    print(f"\nTarget: {target}")

if __name__ == "__main__":
    main()
