#!/usr/bin/env python3
"""Analyze test mapgeo file to understand baron hash usage"""

from mapgeo_parser import MapgeoParser

# Parse the test map
parser = MapgeoParser()
mapgeo = parser.read('LeagueTestMap/sodapop_srs_original.mapgeo')

print(f"Total meshes: {len(mapgeo.meshes)}")
print()

# Analyze visibility layers
vis_layers = {}
for mesh in mapgeo.meshes:
    vis = mesh.visibility
    if vis not in vis_layers:
        vis_layers[vis] = 0
    vis_layers[vis] += 1

print("Visibility Layer Distribution:")
for vis, count in sorted(vis_layers.items()):
    print(f"  {vis:3d} (0x{vis:02X}): {count:3d} meshes")
print()

# Analyze baron hashes
baron_hashes = {}
for mesh in mapgeo.meshes:
    if mesh.visibility_controller_path_hash and mesh.visibility_controller_path_hash != 0:
        hash_str = f"{mesh.visibility_controller_path_hash:08X}"
        if hash_str not in baron_hashes:
            baron_hashes[hash_str] = {'count': 0, 'vis_layers': set()}
        baron_hashes[hash_str]['count'] += 1
        baron_hashes[hash_str]['vis_layers'].add(mesh.visibility)

if baron_hashes:
    print(f"Baron Hashes Found ({len(baron_hashes)} unique):")
    for hash_str, info in sorted(baron_hashes.items()):
        vis_list = sorted(info['vis_layers'])
        print(f"  {hash_str}: {info['count']} meshes, vis_layers={vis_list}")
else:
    print("No baron hashes found in this map")
print()

# Show first 5 meshes with their properties
print("First 5 meshes:")
for i, mesh in enumerate(mapgeo.meshes[:5]):
    print(f"  Mesh {i}:")
    print(f"    visibility_layer: {mesh.visibility} (0x{mesh.visibility:02X})")
    if mesh.visibility_controller_path_hash:
        print(f"    baron_hash: {mesh.visibility_controller_path_hash:08X}")
    print(f"    quality: {mesh.quality}")
    print(f"    is_bush: {mesh.is_bush}")
