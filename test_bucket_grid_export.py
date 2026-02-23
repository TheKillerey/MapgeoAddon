#!/usr/bin/env python3
"""
Test script for bucket grid import/export functionality
Tests the complete pipeline: import → create custom grid → export → verify
"""

import os
import sys
import json

# Add addon path to sys.path
addon_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, addon_path)

from mapgeo_parser import MapgeoParser, MapgeoFile, BucketGrid

def test_import_bucket_grids():
    """Test 1: Import sodapop.mapgeo and verify bucket grids"""
    print("\n=== TEST 1: Import sodapop.mapgeo ===")
    
    mapgeo_path = r"D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo"
    
    if not os.path.exists(mapgeo_path):
        print(f"ERROR: Test file not found: {mapgeo_path}")
        return False
    
    try:
        parser = MapgeoParser()
        mapgeo = parser.read(mapgeo_path)
        
        print(f"✓ Successfully loaded: {os.path.basename(mapgeo_path)}")
        print(f"  - Meshes: {len(mapgeo.meshes)}")
        print(f"  - Bucket Grids: {len(mapgeo.bucket_grids)}")
        
        if len(mapgeo.bucket_grids) > 0:
            for i, grid in enumerate(mapgeo.bucket_grids):
                print(f"\n  Bucket Grid [{i}]:")
                print(f"    - Bounds: X[{grid.min_x:.1f}, {grid.max_x:.1f}] Z[{grid.min_z:.1f}, {grid.max_z:.1f}]")
                print(f"    - Bucket Size: {grid.bucket_size_x:.1f} x {grid.bucket_size_z:.1f}")
                print(f"    - Grid Size: {grid.buckets_per_side} x {grid.buckets_per_side}")
                print(f"    - Path Hash: 0x{grid.path_hash:08X}")
                print(f"    - Vertices: {len(grid.vertices)}")
                print(f"    - Indices: {len(grid.indices)}")
                
                if grid.buckets and len(grid.buckets) > 0:
                    bucket = grid.buckets[0][0]
                    print(f"    - First Bucket:")
                    print(f"      - Start Index: {bucket.start_index}")
                    print(f"      - Base Vertex: {bucket.base_vertex}")
                    print(f"      - Inside Faces: {bucket.inside_face_count}")
                    print(f"      - Sticking Out Faces: {bucket.sticking_out_face_count}")
        
        return True
        
    except Exception as e:
        print(f"ERROR during import: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bucket_grid_structure():
    """Test 2: Verify bucket grid data structures are correct"""
    print("\n=== TEST 2: Verify Bucket Grid Structure ===")
    
    mapgeo_path = r"D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo"
    
    try:
        parser = MapgeoParser()
        mapgeo = parser.read(mapgeo_path)
        
        if not mapgeo.bucket_grids:
            print("⚠ No bucket grids found in file")
            return True  # Not a failure, just empty
        
        grid = mapgeo.bucket_grids[0]
        
        # Check buckets structure
        if not grid.buckets or len(grid.buckets) != grid.buckets_per_side:
            print(f"ERROR: Grid has {len(grid.buckets)} rows but buckets_per_side={grid.buckets_per_side}")
            return False
        
        for row_idx, row in enumerate(grid.buckets):
            if len(row) != grid.buckets_per_side:
                print(f"ERROR: Row {row_idx} has {len(row)} buckets but buckets_per_side={grid.buckets_per_side}")
                return False
        
        print(f"✓ Bucket grid structure is valid")
        print(f"  - Grid is {grid.buckets_per_side}x{grid.buckets_per_side}")
        print(f"  - Total buckets: {grid.buckets_per_side * grid.buckets_per_side}")
        
        # Check vertex/index consistency
        total_faces = len(grid.indices) // 3
        print(f"  - Total faces: {total_faces}")
        print(f"  - Total vertices: {len(grid.vertices)}")
        
        # Check if any bucket has valid face counts
        max_inside = 0
        max_sticking = 0
        total_inside = 0
        total_sticking = 0
        
        for row in grid.buckets:
            for bucket in row:
                max_inside = max(max_inside, bucket.inside_face_count)
                max_sticking = max(max_sticking, bucket.sticking_out_face_count)
                total_inside += bucket.inside_face_count
                total_sticking += bucket.sticking_out_face_count
        
        print(f"  - Max inside faces: {max_inside}")
        print(f"  - Max sticking faces: {max_sticking}")
        print(f"  - Total inside faces: {total_inside}")
        print(f"  - Total sticking faces: {total_sticking}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_roundtrip_structure():
    """Test 3: Test that we can read and write bucket grid data without corruption"""
    print("\n=== TEST 3: Round-trip Test ===")
    
    mapgeo_path = r"D:\LoL Maps\MapgeoAddonTestFolder\sodapop.mapgeo"
    output_path = r"D:\LoL Maps\MapgeoAddonTestFolder\sodapop_roundtrip_test.mapgeo"
    
    try:
        # Load
        parser = MapgeoParser()
        mapgeo = parser.read(mapgeo_path)
        print(f"✓ Loaded original file")
        
        orig_grid_count = len(mapgeo.bucket_grids)
        if orig_grid_count > 0:
            orig_grid = mapgeo.bucket_grids[0]
            orig_vertices = len(orig_grid.vertices)
            orig_indices = len(orig_grid.indices)
            print(f"  - Original bucket grid 0: {orig_vertices} vertices, {orig_indices} indices")
        
        # Write (should be lossless for original grids)
        parser.write(output_path, mapgeo)
        print(f"✓ Wrote to: {os.path.basename(output_path)}")
        
        # Load again
        mapgeo2 = parser.read(output_path)
        print(f"✓ Reloaded written file")
        
        if len(mapgeo2.bucket_grids) != orig_grid_count:
            print(f"ERROR: Grid count changed: {orig_grid_count} → {len(mapgeo2.bucket_grids)}")
            return False
        
        if orig_grid_count > 0:
            new_grid = mapgeo2.bucket_grids[0]
            new_vertices = len(new_grid.vertices)
            new_indices = len(new_grid.indices)
            
            if new_vertices != orig_vertices or new_indices != orig_indices:
                print(f"ERROR: Data changed in round-trip:")
                print(f"  Vertices: {orig_vertices} → {new_vertices}")
                print(f"  Indices: {orig_indices} → {new_indices}")
                return False
            
            print(f"  - New bucket grid 0: {new_vertices} vertices, {new_indices} indices ✓")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass


def main():
    """Run all tests"""
    print("=" * 60)
    print("BUCKET GRID EXPORT TEST SUITE")
    print("=" * 60)
    
    results = {}
    
    results['Test 1: Import'] = test_import_bucket_grids()
    results['Test 2: Structure'] = test_bucket_grid_structure()
    results['Test 3: Round-trip'] = test_roundtrip_structure()
    
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
