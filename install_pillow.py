"""
Pillow Installation Script for Blender
=======================================
This script installs the Pillow library required for texture conversion (.tex to .png).

INSTRUCTIONS:
1. Open Blender
2. Go to Scripting workspace
3. Click "Open" and select this file (install_pillow.py)
4. Click "Run Script" button (or press Alt+P)
5. Restart Blender after installation completes

No administrator rights required!
"""
import subprocess
import sys
import site

def install_pillow():
    """Install Pillow to user site-packages (no admin needed)"""
    print("="*70)
    print("PILLOW INSTALLATION FOR LEAGUE OF LEGENDS MAPGEO ADDON")
    print("="*70)
    print(f"\nPython executable: {sys.executable}")
    print(f"User site-packages: {site.USER_SITE}")
    print("\nThis will install Pillow using pip (no admin rights needed)...")
    print("\nStarting installation...\n")
    
    try:
        # Install to user site-packages (no admin needed)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "Pillow"])
        
        print("\n" + "="*70)
        print("✓ SUCCESS! Pillow has been installed successfully.")
        print("="*70)
        print("\nIMPORTANT: Please RESTART Blender now for changes to take effect.")
        print("After restarting, the League Mapgeo addon will be able to load textures.")
        print("="*70)
        
    except subprocess.CalledProcessError as e:
        print("\n" + "="*70)
        print("✗ ERROR: Installation failed!")
        print("="*70)
        print(f"\nError details: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you have internet connection")
        print("2. Try running Blender as administrator")
        print("3. Install Pillow manually: python -m pip install --user Pillow")
        print("="*70)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")

if __name__ == "__main__":
    install_pillow()
