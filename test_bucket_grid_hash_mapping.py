#!/usr/bin/env python3
"""
Test which meshes should be grouped into which bucket grids based on their hash properties
"""

import os
import sys
from collections import defaultdict

# Add addon path
addon_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, addon_path)

from mapgeo_parser import MapgeoParser

def analyze_bucket_grid_mesh_relationship():
    """Analyze how bucket grids relate to meshes via hashes"""
    
    mapgeo_path = r"D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo"
    
    parser = MapgeoParser()
    mapgeo = parser.read(mapgeo_path)
    
    print("=" * 80)
    print("BUCKET GRID HASH ANALYSIS")
    print("=" * 80)
    
    # Collect bucket grid path_hashes
    grid_hashes = {}
    for i, grid in enumerate(mapgeo.bucket_grids):
        if grid.path_hash != 0:
            grid_hashes[grid.path_hash] = i
    
    print(f"\nBucket grids with non-zero path_hash: {len(grid_hashes)}")
    
    # Group meshes by their hash properties
    meshes_by_render_region = defaultdict(list)
    meshes_by_baron_hash = defaultdict(list)
    meshes_by_visibility_layer = defaultdict(list)
    
    for mesh in mapgeo.meshes:
        # Render region hash
        if mesh.unknown_version18_int != 0:
            meshes_by_render_region[mesh.unknown_version18_int].append(mesh.name)
        
        # Baron hash
        if mesh.visibility_controller_path_hash != 0:
            meshes_by_baron_hash[mesh.visibility_controller_path_hash].append(mesh.name)
        
        # Visibility layer (dragon layers)
        if mesh.visibility != 0:
            meshes_by_visibility_layer[mesh.visibility].append(mesh.name)
    
    print(f"\n--- RENDER REGION HASHES ---")
    print(f"Unique render region hashes: {len(meshes_by_render_region)}")
    
    # Check which render region hashes match bucket grid path_hashes
    matching_render_regions = 0
    for rr_hash in meshes_by_render_region.keys():
        if rr_hash in grid_hashes:
            matching_render_regions += 1
            grid_idx = grid_hashes[rr_hash]
            mesh_count = len(meshes_by_render_region[rr_hash])
            print(f"  0x{rr_hash:08X} → Grid {grid_idx:2d} ({mesh_count} meshes)")
    
    print(f"\n--- BARON HASHES ---")
    print(f"Unique baron hashes: {len(meshes_by_baron_hash)}")
    
    # Check which baron hashes match bucket grid path_hashes
    matching_baron = 0
    for baron_hash in meshes_by_baron_hash.keys():
        if baron_hash in grid_hashes:
            matching_baron += 1
            grid_idx = grid_hashes[baron_hash]
            mesh_count = len(meshes_by_baron_hash[baron_hash])
            print(f"  0x{baron_hash:08X} → Grid {grid_idx:2d} ({mesh_count} meshes)")
    
    print(f"\n--- VISIBILITY LAYERS (Dragon) ---")
    print(f"Unique visibility layers: {len(meshes_by_visibility_layer)}")
    for vis_layer in sorted(meshes_by_visibility_layer.keys()):
        mesh_count = len(meshes_by_visibility_layer[vis_layer])
        print(f"  Layer {vis_layer:3d} ({mesh_count} meshes)")
    
    print(f"\n--- BUCKET GRIDS WITH path_hash=0 ---")
    zero_hash_grids = [i for i, g in enumerate(mapgeo.bucket_grids) if g.path_hash == 0]
    print(f"Count: {len(zero_hash_grids)}")
    print(f"Indices: {zero_hash_grids[:15]}")
    
    print(f"\n--- SUMMARY ---")
    print(f"Total bucket grids: {len(mapgeo.bucket_grids)}")
    print(f"  - With path_hash != 0: {len(grid_hashes)}")
    print(f"  - With path_hash == 0: {len(zero_hash_grids)}")
    print(f"\nHash matching:")
    print(f"  - Render region hashes matching grids: {matching_render_regions}/{len(meshes_by_render_region)}")
    print(f"  - Baron hashes matching grids: {matching_baron}/{len(meshes_by_baron_hash)}")
    
    print("\n" + "=" * 80)
    
    # Recommendation
    print("\nRECOMMENDATION:")
    print("Bucket grids should use path_hash from:")
    print("  1. render_region_hash (if mesh has it)")
    print("  2. baron_hash (if mesh has it)") 
    print("  3. 00000000 for general dragon layer visibility")
    
    return True

if __name__ == "__main__":
    analyze_bucket_grid_mesh_relationship()
