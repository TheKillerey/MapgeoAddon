"""
Example usage of the troybin parser with unhashing support
"""

from pathlib import Path
from troybin_parser import (
    parse_troybin, write_troybin, 
    section_field_hash_proper, 
    build_hash_map, extract_group_names
)


def example_read():
    """Example: Read a troybin file with unhashed names"""
    path = Path("your_file.troybin")
    
    # Parse the file
    data = parse_troybin(path)
    
    # Extract emitter names and build hash map for unhashing
    group_names = extract_group_names(data)
    hash_map = build_hash_map(group_names)
    
    print(f"Version: {data['version']}")
    print(f"Emitters: {', '.join(group_names)}")
    print()
    
    # Access properties by set type with unhashed names
    for set_name, entries in data['sets'].items():
        print(f"{set_name}: {len(entries)} properties")
        for hash_value, value in entries:
            label = hash_map.get(hash_value, f"0x{hash_value:08X}")
            print(f"  {label} = {value}")


def example_write_with_names():
    """Example: Create a troybin using human-readable field names"""
    # Define your emitter
    emitter_name = "my_particle"
    
    data = {
        "version": 2,
        "sets": {
            # System section - define the emitter
            "StringList": [
                # GroupPart0 defines the first emitter name
                (section_field_hash_proper("System", "GroupPart0"), emitter_name),
                # Now add properties for the emitter
                (section_field_hash_proper(emitter_name, "p-mesh"), "particle.scb"),
                (section_field_hash_proper(emitter_name, "p-meshtex"), "particle.dds"),
                (section_field_hash_proper(emitter_name, "rendermode"), "0"),
            ],
            "Int8List": [
                (section_field_hash_proper(emitter_name, "p-life"), 2),
                (section_field_hash_proper(emitter_name, "e-rate"), 5),
                (section_field_hash_proper(emitter_name, "p-type"), 0),
            ],
            "Int16List": [
                (section_field_hash_proper(emitter_name, "e-life"), -1),
            ],
            "Float32ListVec3": [
                (section_field_hash_proper(emitter_name, "p-scale"), [10.0, 10.0, 10.0]),
            ],
            "Float32ListVec4": [
                (section_field_hash_proper(emitter_name, "e-rgba"), [255.0, 255.0, 255.0, 255.0]),
            ],
        }
    }
    
    write_troybin(Path("my_particle.troybin"), data)
    print(f"Created particle effect: {emitter_name}")


def example_modify():
    """Example: Read, modify, and write back with unhashed names"""
    path = Path("your_file.troybin")
    
    # Read existing file
    data = parse_troybin(path)
    
    # Get emitter names for unhashing
    group_names = extract_group_names(data)
    hash_map = build_hash_map(group_names)
    
    # Find and modify a specific property by name
    emitter = group_names[0] if group_names else "GroupPart0"
    target_hash = section_field_hash_proper(emitter, "p-scale")
    
    if "Float32ListVec3" in data['sets']:
        for i, (hash_value, value) in enumerate(data['sets']['Float32ListVec3']):
            if hash_value == target_hash:
                # Double the scale
                new_value = [v * 2.0 for v in value]
                data['sets']['Float32ListVec3'][i] = (hash_value, new_value)
                print(f"Changed [{emitter}] p-scale from {value} to {new_value}")
                break
    
    # Write back
    write_troybin(Path("modified.troybin"), data)
    print("Modified file saved!")


def example_create_multi_emitter():
    """Example: Create a troybin with multiple emitters"""
    emitters = ["glow", "sparkle", "trail"]
    
    data = {
        "version": 2,
        "sets": {
            "StringList": [],
            "Int8List": [],
            "Float32ListVec3": [],
        }
    }
    
    # Define all emitters in System section
    for i, emitter_name in enumerate(emitters):
        hash_val = section_field_hash_proper("System", f"GroupPart{i}")
        data["sets"]["StringList"].append((hash_val, emitter_name))
    
    # Add properties for each emitter
    for emitter_name in emitters:
        # Mesh and texture
        data["sets"]["StringList"].extend([
            (section_field_hash_proper(emitter_name, "p-mesh"), f"{emitter_name}.scb"),
            (section_field_hash_proper(emitter_name, "p-meshtex"), f"{emitter_name}.dds"),
        ])
        
        # Particle lifetime
        data["sets"]["Int8List"].append(
            (section_field_hash_proper(emitter_name, "p-life"), 2)
        )
        
        # Scale
        data["sets"]["Float32ListVec3"].append(
            (section_field_hash_proper(emitter_name, "p-scale"), [10.0, 10.0, 10.0])
        )
    
    write_troybin(Path("multi_emitter.troybin"), data)
    print(f"Created particle effect with {len(emitters)} emitters: {', '.join(emitters)}")


def example_json_editing():
    """Example: Edit troybin via JSON (human-readable)"""
    # Convert to JSON
    data = parse_troybin(Path("particle.troybin"))
    
    # The JSON will now have "section" and "field" for each property
    # You can edit it manually and convert back
    
    # Example of programmatic JSON editing:
    from troybin_parser import troybin_to_dict, dict_to_troybin
    import json
    
    json_data = troybin_to_dict(data)
    
    # Find properties by name
    for key, prop in json_data["properties"].items():
        if prop.get("field") == "p-scale":
            # Double all scale values
            prop["value"] = [v * 2.0 for v in prop["value"]]
            print(f"Modified {prop.get('name')} to {prop['value']}")
    
    # Convert back and save
    modified_data = dict_to_troybin(json_data)
    write_troybin(Path("particle_modified.troybin"), modified_data)
    print("Saved modified particle")


if __name__ == "__main__":
    print("Troybin Parser Examples (with Unhashing)")
    print("=" * 60)
    print()
    print("Available examples:")
    print("  1. example_read() - Read with unhashed names")
    print("  2. example_write_with_names() - Write using field names")
    print("  3. example_modify() - Modify by field name")
    print("  4. example_create_multi_emitter() - Multiple emitters")
    print("  5. example_json_editing() - Edit via JSON")
    print()
    print("Uncomment to run:")
    print()
    
    # Uncomment to run:
    # example_read()
    # example_write_with_names()
    # example_modify()
    # example_create_multi_emitter()
    # example_json_editing()

