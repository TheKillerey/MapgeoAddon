"""
Quick installer script for MapgeoAddon
This script helps you install the addon properly into Blender
"""

import os
import shutil
import sys

def find_blender_addons_path():
    """Find the Blender user addons directory"""
    if sys.platform == "win32":
        base = os.path.expandvars(r"%APPDATA%\Blender Foundation\Blender")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/Blender")
    else:  # Linux
        base = os.path.expanduser("~/.config/blender")
    
    # Look for version folders
    if os.path.exists(base):
        versions = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
        if versions:
            # Sort and get the latest version
            versions.sort(reverse=True)
            latest = versions[0]
            addons_path = os.path.join(base, latest, "scripts", "addons")
            return addons_path
    
    return None

def remove_old_installation(addons_path, addon_name):
    """Remove old installation of the addon"""
    addon_folder = os.path.join(addons_path, addon_name)
    if os.path.exists(addon_folder):
        print(f"Removing old installation at: {addon_folder}")
        try:
            shutil.rmtree(addon_folder)
            print("✓ Old installation removed")
            return True
        except Exception as e:
            print(f"✗ Error removing old installation: {e}")
            return False
    else:
        print("No old installation found")
        return True

def create_symlink(source, target):
    """Create a symbolic link (requires admin on Windows)"""
    try:
        if os.path.exists(target):
            os.remove(target)
        os.symlink(source, target, target_is_directory=True)
        print(f"✓ Created symlink: {target} -> {source}")
        return True
    except OSError as e:
        print(f"✗ Could not create symlink: {e}")
        print("  Note: On Windows, you may need administrator privileges")
        return False

def copy_addon(source, target):
    """Copy addon files to target location"""
    try:
        if os.path.exists(target):
            shutil.rmtree(target)
        
        # Copy the entire directory
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '.git', '.gitignore', '*.md',
            'LeagueTestMap', 'LeagueToolkit', 'install_addon.py'
        ))
        print(f"✓ Copied addon to: {target}")
        return True
    except Exception as e:
        print(f"✗ Error copying addon: {e}")
        return False

def main():
    print("=" * 60)
    print("MapgeoAddon Installer")
    print("=" * 60)
    
    # Get current directory (where this script is)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    addon_name = os.path.basename(current_dir)
    
    print(f"\nAddon source: {current_dir}")
    print(f"Addon name: {addon_name}")
    
    # Find Blender addons directory
    addons_path = find_blender_addons_path()
    
    if not addons_path:
        print("\n✗ Could not find Blender addons directory")
        print("Please ensure Blender is installed")
        return
    
    print(f"Blender addons path: {addons_path}")
    
    # Create addons directory if it doesn't exist
    os.makedirs(addons_path, exist_ok=True)
    
    # Remove old installation
    print("\n" + "-" * 60)
    print("Step 1: Removing old installation")
    print("-" * 60)
    remove_old_installation(addons_path, addon_name)
    
    # Ask user which method to use
    print("\n" + "-" * 60)
    print("Step 2: Choose installation method")
    print("-" * 60)
    print("1. Copy files (recommended, works always)")
    print("2. Create symlink (development mode, requires admin on Windows)")
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    target_path = os.path.join(addons_path, addon_name)
    
    if choice == "2":
        print("\nAttempting to create symlink...")
        success = create_symlink(current_dir, target_path)
        if not success:
            print("\nFalling back to copy method...")
            success = copy_addon(current_dir, target_path)
    else:
        print("\nCopying addon files...")
        success = copy_addon(current_dir, target_path)
    
    # Final instructions
    print("\n" + "=" * 60)
    if success:
        print("✓ Installation completed successfully!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start (or restart) Blender")
        print("2. Go to Edit > Preferences > Add-ons")
        print("3. Search for 'League of Legends Mapgeo Tools'")
        print("4. Enable the addon by checking the checkbox")
        print("\nThe addon will appear in:")
        print("- File > Import > League of Legends Mapgeo (.mapgeo)")
        print("- File > Export > League of Legends Mapgeo (.mapgeo)")
        print("- 3D Viewport > Sidebar (N key) > LoL Mapgeo tab")
    else:
        print("✗ Installation failed")
        print("=" * 60)
        print("\nPlease try running this script as administrator")
    
    print("\n")
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
