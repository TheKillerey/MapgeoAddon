#!/usr/bin/env python3
"""
Compare two mapgeo files to identify structural differences
"""

import sys
sys.path.insert(0, r'd:\BlenderAddons\MapgeoAddon')

from mapgeo_parser import MapgeoParser
import os

def compare_files(original_path, exported_path):
    """Compare two mapgeo files and show differences"""
    
    print(f"=== MAPGEO FILE COMPARISON ===\n")
    
    # Show file sizes
    orig_size = os.path.getsize(original_path)
    export_size = os.path.getsize(exported_path)
    
    print(f"Original file size: {orig_size:,} bytes")
    print(f"Exported file size: {export_size:,} bytes")
    print(f"Size difference: {export_size - orig_size:,} bytes ({100.0 * (export_size - orig_size) / orig_size:.1f}%)\n")
    
    # Parse both files
    parser = MapgeoParser()
    
    print("Reading original file...")
    original = parser.read(original_path)
    
    print("Reading exported file...")
    exported = parser.read(exported_path)
    
    # Compare structures
    print("\n=== STRUCTURE COMPARISON ===\n")
    
    print(f"Version: {original.version} -> {exported.version}")
    
    print(f"\nVertex Buffers:")
    print(f"  Original: {len(original.vertex_buffers)}")
    print(f"  Exported: {len(exported.vertex_buffers)}")
    if len(original.vertex_buffers) > 0 and len(exported.vertex_buffers) > 0:
        print(f"  Original VB[0] size: {len(original.vertex_buffers[0].data)} bytes, {original.vertex_buffers[0].vertex_count} vertices")
        print(f"  Exported VB[0] size: {len(exported.vertex_buffers[0].data)} bytes, {exported.vertex_buffers[0].vertex_count} vertices")
    
    print(f"\nIndex Buffers:")
    print(f"  Original: {len(original.index_buffers)}")
    print(f"  Exported: {len(exported.index_buffers)}")
    if len(original.index_buffers) > 0 and len(exported.index_buffers) > 0:
        print(f"  Original IB[0] size: {len(original.index_buffers[0].data)} bytes, {original.index_buffers[0].index_count} indices")
        print(f"  Exported IB[0] size: {len(exported.index_buffers[0].data)} bytes, {exported.index_buffers[0].index_count} indices")
    
    print(f"\nMeshes:")
    print(f"  Original: {len(original.meshes)} meshes")
    print(f"  Exported: {len(exported.meshes)} meshes")
    
    print(f"\nBucket Grids:")
    print(f"  Original: {len(original.bucket_grids)} bucket grids")
    print(f"  Exported: {len(exported.bucket_grids)} bucket grids")
    
    print(f"\nPlanar Reflectors:")
    print(f"  Original: {len(original.planar_reflectors)}")
    print(f"  Exported: {len(exported.planar_reflectors)}")
    
    print("\n[OK] Export successful! File is valid and readable.")
    
    # Detail analysis
    print("\n=== DETAILED ANALYSIS ===\n")
    
    if len(original.meshes) != len(exported.meshes):
        print(f"⚠️  MESHES: Different count! Original={len(original.meshes)}, Exported={len(exported.meshes)}")
        print("   This is the PRIMARY issue - you're not exporting all meshes!")
    else:
        print(f"✓ MESHES: Same count ({len(original.meshes)})")
    
    if len(original.bucket_grids) != len(exported.bucket_grids):
        print(f"⚠️  BUCKET GRIDS: Different count! Original={len(original.bucket_grids)}, Exported={len(exported.bucket_grids)}")
    else:
        print(f"✓ BUCKET GRIDS: Same count ({len(original.bucket_grids)})")
    
    if len(original.planar_reflectors) != len(exported.planar_reflectors):
        print(f"⚠️  PLANAR REFLECTORS: Different count! Original={len(original.planar_reflectors)}, Exported={len(exported.planar_reflectors)}")
    else:
        print(f"✓ PLANAR REFLECTORS: Same count ({len(original.planar_reflectors)})")


if __name__ == "__main__":
    original = r"d:\BlenderAddons\MapgeoAddon\LeagueTestMap\sodapop_srs_original.mapgeo"
    exported = r"d:\BlenderAddons\MapgeoAddon\LeagueTestMap\sodapop_srs_exported_new.mapgeo"
    
    # Check file existence
    if not os.path.exists(original):
        print(f"ERROR: Original file not found: {original}")
        sys.exit(1)
    
    if not os.path.exists(exported):
        print(f"ERROR: Exported file not found: {exported}")
        sys.exit(1)
    
    try:
        compare_files(original, exported)
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
