"""
Create a custom test particle effect using the troybin parser
This creates a glowing magical aura effect with multiple emitters
"""

from pathlib import Path
from troybin_parser import (
    write_troybin,
    section_field_hash_proper
)


def create_custom_particle():
    """Create a custom magical aura particle effect"""
    
    # Define our emitters
    emitters = {
        "core_glow": {
            "description": "Central glowing core",
            "mesh": "saucer7.scb",
            "texture": "ball03.dds",
            "scale": [40.0, 40.0, 40.0],
            "color": [255.0, 180.0, 255.0, 200.0],  # Purple glow
            "lifetime": 2,
            "rate": 1,
            "type": 3,
        },
        "sparkles": {
            "description": "Sparkling particles",
            "mesh": "saucer7.scb",
            "texture": "glows.dds",
            "scale": [5.0, 5.0, 5.0],
            "color": [255.0, 255.0, 255.0, 255.0],  # White sparkles
            "lifetime": 1,
            "rate": 20,
            "type": 0,
        },
        "trail": {
            "description": "Trailing effect",
            "mesh": "saucer7.scb", 
            "texture": "fistoffury01.dds",
            "scale": [15.0, 15.0, 15.0],
            "color": [200.0, 150.0, 255.0, 150.0],  # Light purple
            "lifetime": 3,
            "rate": 10,
            "type": 1,
        }
    }
    
    data = {
        "version": 2,
        "sets": {
            "StringList": [],
            "Int16List": [],
            "Int8List": [],
            "Float32ListVec3": [],
            "Float32ListVec4": [],
            "BitList": [],
            "FixedPointFloatListVec2": [],
        }
    }
    
    # Register all emitters in System section
    emitter_names = list(emitters.keys())
    for i, emitter_name in enumerate(emitter_names):
        # GroupPartN = emitter name
        data["sets"]["StringList"].append((
            section_field_hash_proper("System", f"GroupPart{i}"),
            emitter_name
        ))
        
        # GroupPartNType = Simple/Complex
        data["sets"]["StringList"].append((
            section_field_hash_proper("System", f"GroupPart{i}Type"),
            "Simple"
        ))
    
    # Add SimulateEveryFrame for smooth animation
    data["sets"]["BitList"].append((
        section_field_hash_proper("System", "SimulateEveryFrame"),
        True
    ))
    
    # Configure each emitter
    for emitter_name, config in emitters.items():
        print(f"Configuring emitter: {emitter_name}")
        print(f"  Description: {config['description']}")
        
        # ═══ String Properties ═══
        # Mesh
        data["sets"]["StringList"].append((
            section_field_hash_proper(emitter_name, "p-mesh"),
            config["mesh"]
        ))
        
        # Texture
        data["sets"]["StringList"].append((
            section_field_hash_proper(emitter_name, "p-meshtex"),
            config["texture"]
        ))
        
        # Render mode
        data["sets"]["StringList"].append((
            section_field_hash_proper(emitter_name, "rendermode"),
            "1"
        ))
        
        # ═══ Emitter Properties ═══
        # Emitter lifetime (-1 = infinite)
        data["sets"]["Int16List"].append((
            section_field_hash_proper(emitter_name, "e-life"),
            -1
        ))
        
        # Emission rate
        data["sets"]["Int8List"].append((
            section_field_hash_proper(emitter_name, "e-rate"),
            config["rate"]
        ))
        
        # ═══ Particle Properties ═══
        # Particle lifetime
        data["sets"]["Int8List"].append((
            section_field_hash_proper(emitter_name, "p-life"),
            config["lifetime"]
        ))
        
        # Particle type (0=normal, 1=beam, 3=mesh)
        data["sets"]["Int8List"].append((
            section_field_hash_proper(emitter_name, "p-type"),
            config["type"]
        ))
        
        # ═══ Visual Properties ═══
        # Scale
        data["sets"]["Float32ListVec3"].append((
            section_field_hash_proper(emitter_name, "p-scale"),
            config["scale"]
        ))
        
        # Color (RGBA)
        data["sets"]["Float32ListVec4"].append((
            section_field_hash_proper(emitter_name, "e-rgba"),
            config["color"]
        ))
        
        # Rotation velocity for spin effect
        if emitter_name == "sparkles":
            data["sets"]["Float32ListVec3"].append((
                section_field_hash_proper(emitter_name, "p-rotvel"),
                [0.0, 60.0, 0.0]  # Rotate around Y axis
            ))
        
        # Offset for positioning
        if emitter_name == "trail":
            data["sets"]["Float32ListVec3"].append((
                section_field_hash_proper(emitter_name, "p-offset"),
                [0.0, 0.0, 50.0]  # Behind the source
            ))
        
        # Bind to emitter for some lifetime
        data["sets"]["FixedPointFloatListVec2"].append((
            section_field_hash_proper(emitter_name, "p-bindtoemitter"),
            [5, 0]  # Stay attached for 0.5 seconds
        ))
        
        # Enable backface rendering for visibility
        data["sets"]["BitList"].append((
            section_field_hash_proper(emitter_name, "p-backfaceon"),
            True
        ))
    
    # Save the particle file
    output_path = Path("custom_magical_aura.troybin")
    write_troybin(output_path, data)
    
    print(f"\n{'='*60}")
    print(f"✓ Created custom particle: {output_path}")
    print(f"{'='*60}")
    print(f"\nEmitters created:")
    for name, config in emitters.items():
        print(f"  • {name}: {config['description']}")
    
    print(f"\nFile properties:")
    print(f"  Total emitters: {len(emitters)}")
    total_props = sum(len(v) for v in data["sets"].values())
    print(f"  Total properties: {total_props}")
    print(f"  File size: {output_path.stat().st_size} bytes")
    
    print(f"\nUsage:")
    print(f"  1. Copy 'custom_magical_aura.troybin' to your League particle folder")
    print(f"  2. Reference it in your mod (e.g., replace an existing particle)")
    print(f"  3. Make sure these textures exist in the same folder:")
    for emitter in emitters.values():
        print(f"     - {emitter['texture']}")
        if emitter['mesh']:
            print(f"     - {emitter['mesh']}")
    
    return output_path


def create_simple_test_particle():
    """Create a simpler single-emitter test particle"""
    
    print("Creating simple test particle...")
    
    emitter_name = "test_glow"
    
    data = {
        "version": 2,
        "sets": {
            "StringList": [
                # System: Define emitter
                (section_field_hash_proper("System", "GroupPart0"), emitter_name),
                (section_field_hash_proper("System", "GroupPart0Type"), "Simple"),
                
                # Emitter properties
                (section_field_hash_proper(emitter_name, "p-mesh"), "saucer7.scb"),
                (section_field_hash_proper(emitter_name, "p-meshtex"), "ball03.dds"),
                (section_field_hash_proper(emitter_name, "rendermode"), "1"),
                (section_field_hash_proper(emitter_name, "p-texture"), "glows.dds"),
            ],
            "Int16List": [
                # Infinite emitter
                (section_field_hash_proper(emitter_name, "e-life"), -1),
            ],
            "Int8List": [
                # Particle lifetime (2 seconds)
                (section_field_hash_proper(emitter_name, "p-life"), 2),
                # Emission rate (5 particles per second)
                (section_field_hash_proper(emitter_name, "e-rate"), 5),
                # Particle type (mesh)
                (section_field_hash_proper(emitter_name, "p-type"), 3),
            ],
            "Float32ListVec3": [
                # Scale (medium size)
                (section_field_hash_proper(emitter_name, "p-scale"), [25.0, 25.0, 25.0]),
                # Slight upward velocity
                (section_field_hash_proper(emitter_name, "p-vel"), [0.0, 50.0, 0.0]),
                # Rotation
                (section_field_hash_proper(emitter_name, "p-rotvel"), [0.0, 30.0, 0.0]),
            ],
            "Float32ListVec4": [
                # Bright cyan glow
                (section_field_hash_proper(emitter_name, "e-rgba"), [0.0, 200.0, 255.0, 255.0]),
            ],
            "BitList": [
                # Enable backface rendering
                (section_field_hash_proper(emitter_name, "p-backfaceon"), True),
                # Simulate every frame
                (section_field_hash_proper("System", "SimulateEveryFrame"), True),
            ],
        }
    }
    
    output_path = Path("test_simple_glow.troybin")
    write_troybin(output_path, data)
    
    print(f"✓ Created: {output_path}")
    print(f"  Properties: {sum(len(v) for v in data['sets'].values())}")
    print(f"  Size: {output_path.stat().st_size} bytes")
    
    return output_path


if __name__ == "__main__":
    print("Custom Particle Creator")
    print("="*60)
    print()
    
    # Create both particles
    print("[1] Creating complex multi-emitter particle...")
    print()
    complex_particle = create_custom_particle()
    
    print()
    print()
    
    print("[2] Creating simple test particle...")
    print()
    simple_particle = create_simple_test_particle()
    
    print()
    print("="*60)
    print("All particles created successfully!")
    print("="*60)
