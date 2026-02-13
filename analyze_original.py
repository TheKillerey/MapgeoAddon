#!/usr/bin/env python3
"""
Analyze original mapgeo file structure
"""

import sys
sys.path.insert(0, r'd:\BlenderAddons\MapgeoAddon')

from mapgeo_parser import MapgeoParser
import os

def analyze_file(filepath):
    """Analyze mapgeo file structure"""
    
    print(f"=== MAPGEO FILE ANALYSIS ===\n")
    print(f"File: {filepath}")
    print(f"Size: {os.path.getsize(filepath):,} bytes\n")
    
    parser = MapgeoParser()
    
    print("Reading file...")
    try:
        data = parser.read(filepath)
    except Exception as e:
        print(f"ERROR reading file: {str(e)}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"\n=== STRUCTURE ===\n")
    print(f"Version: {data.version}")
    
    print(f"\n--- Vertex Buffers: {len(data.vertex_buffers)} ---")
    for i, vb in enumerate(data.vertex_buffers):
        print(f"  [{i}] {len(vb.data):,} bytes, {vb.vertex_count} vertices")
    
    print(f"\n--- Index Buffers: {len(data.index_buffers)} ---")
    for i, ib in enumerate(data.index_buffers):
        print(f"  [{i}] {len(ib.data):,} bytes, {ib.index_count} indices, format={ib.format}")
    
    print(f"\n--- Meshes: {len(data.meshes)} ---")
    total_mesh_bytes = 0
    for i, mesh in enumerate(data.meshes):
        print(f"  [{i}] VB={mesh.vertex_buffer_id}, IB={mesh.index_buffer_id}, primitives={len(mesh.primitives)}")
        total_mesh_bytes += len(data.vertex_buffers[mesh.vertex_buffer_id].data) if mesh.vertex_buffer_id < len(data.vertex_buffers) else 0
    print(f"  Total mesh vertex data: {total_mesh_bytes:,} bytes")
    
    print(f"\n--- Bucket Grids: {len(data.bucket_grids)} ---")
    total_grid_bytes = 0
    for i, grid in enumerate(data.bucket_grids):
        verts_bytes = len(grid.vertices) * 12  # 3 floats per vertex
        indices_bytes = len(grid.indices) * 2
        total_grid_bytes += verts_bytes + indices_bytes
        print(f"  [{i}] {len(grid.vertices)} vertices, {len(grid.indices)} indices, "
              f"{grid.buckets_per_side}x{grid.buckets_per_side} buckets, "
              f"disabled={grid.is_disabled}")
    print(f"  Total bucket grid data: {total_grid_bytes:,} bytes")
    
    print(f"\n--- Planar Reflectors: {len(data.planar_reflectors)} ---")
    
    print(f"\n--- Environment Assets: {len(data.environment_assets)} ---")
    
    print(f"\n=== DATA CONTENT BREAKDOWN ===")
    print(f"Mesh vertex data:     {total_mesh_bytes:,} bytes ({100.0 * total_mesh_bytes / os.path.getsize(filepath):.1f}%)")
    print(f"Bucket grid data:     {total_grid_bytes:,} bytes ({100.0 * total_grid_bytes / os.path.getsize(filepath):.1f}%)")
    print(f"Other (headers, etc): {os.path.getsize(filepath) - total_mesh_bytes - total_grid_bytes:,} bytes ({100.0 * (os.path.getsize(filepath) - total_mesh_bytes - total_grid_bytes) / os.path.getsize(filepath):.1f}%)")
    print(f"Total file size:      {os.path.getsize(filepath):,} bytes")

if __name__ == "__main__":
    original = r"D:\Mods\DefaultMap\Map11_test\data\maps\mapgeometry\map11\sodapop_srs_original.mapgeo"
    
    if not os.path.exists(original):
        print(f"ERROR: File not found: {original}")
        sys.exit(1)
    
    analyze_file(original)
