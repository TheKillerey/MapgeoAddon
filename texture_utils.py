"""
Texture Utilities for Mapgeo Addon
Handles TEX format loading and conversion to PNG
Based on CommunityDragon CDTB implementation
"""

import struct
import os
import sys
import site
import math
from io import BytesIO
from typing import Optional

# Ensure user site-packages is in sys.path for PIL/Pillow
if site.USER_SITE not in sys.path:
    sys.path.append(site.USER_SITE)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("PIL/Pillow not available - texture conversion will be disabled")
    print(f"  Searched in: {sys.path}")


class TexConverter:
    """Converts Riot .tex files to PNG format via DDS intermediate format"""
    
    def __init__(self):
        self.cache = {}  # Cache converted textures
    
    def convert_tex_to_png(self, tex_path: str, output_path: str = None) -> Optional[str]:
        """
        Convert a .tex file to .png
        
        Args:
            tex_path: Path to .tex file
            output_path: Optional output path for .png (defaults to same location)
        
        Returns:
            Path to converted .png file, or None if conversion failed
        """
        if not PIL_AVAILABLE:
            print("  Warning: PIL not available, skipping texture conversion")
            return None
        
        if not os.path.exists(tex_path):
            print(f"  Warning: Texture file not found: {tex_path}")
            return None
        
        # Use cache if already converted
        if tex_path in self.cache:
            return self.cache[tex_path]
        
        # Determine output path
        if output_path is None:
            output_path = os.path.splitext(tex_path)[0] + ".png"
        
        # Skip if already converted
        if os.path.exists(output_path):
            self.cache[tex_path] = output_path
            return output_path
        
        try:
            with open(tex_path, 'rb') as f:
                tex_data = f.read()
            
            # Convert TEX to DDS in memory
            dds_data = self.tex_to_dds(tex_data)
            
            # Convert DDS to PNG using PIL
            fdds = BytesIO(dds_data)
            img = Image.open(fdds)
            
            # Create output directory if needed
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save as PNG
            img.save(output_path, 'PNG')
            self.cache[tex_path] = output_path
            return output_path
        
        except Exception as e:
            print(f"  Error converting {os.path.basename(tex_path)}: {e}")
            return None
    
    @staticmethod
    def tex_to_dds(data: bytes) -> bytes:
        """
        Convert TEX format to DDS format
        Based on CommunityDragon CDTB implementation
        """
        # Parse TEX header (12 bytes total)
        if len(data) < 12 or data[:4] != b'TEX\0':
            raise ValueError("Invalid TEX file")
        
        # Unpack all 12 bytes of header
        magic, width, height, is_extended, tex_format, resource_type, flags = struct.unpack('<4sHHBBBB', data[:12])
        
        has_mipmaps = bool(flags & 0x01)
        has_dx10 = False
        
        # Map TEX format to DDS pixel format
        if tex_format == 0x0a:  # DXT1 (BC1)
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DXT1')
        elif tex_format == 0x0c:  # DXT5 (BC3)
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DXT5')
        elif tex_format == 0x14:  # BGRA8
            ddspf = struct.pack('<LL4x5L', 32, 0x41, 8*4, 0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
        elif tex_format == 0x15:  # RGBA16
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DX10')
            dx10 = struct.pack('<LL4xLL', 13, 3, 1, 1)
            has_dx10 = True
        else:
            raise ValueError(f"Unsupported TEX format: {tex_format:x}")
        
        # Calculate pixel data size for the largest mipmap only
        if tex_format == 0x0a:  # DXT1
            block_size = 4
            bytes_per_block = 8
        elif tex_format == 0x0c:  # DXT5
            block_size = 4
            bytes_per_block = 16
        elif tex_format == 0x14:  # BGRA8
            block_size = 1
            bytes_per_block = 4
        else:
            # RGBA16 format
            block_size = 1
            bytes_per_block = 8
        
        # Calculate size of largest mipmap
        block_width = (width + block_size - 1) // block_size
        block_height = (height + block_size - 1) // block_size
        largest_mip_size = block_width * block_height * bytes_per_block
        
        # Extract only the largest mipmap
        # TEX stores mipmaps in reverse order (smallest to largest)
        # The largest mipmap is at the end of the file
        if has_mipmaps:
            # Calculate total size of all mipmaps
            mip_count = int(math.floor(math.log2(max(height, width))) + 1)
            
            # Skip to the largest mipmap by calculating offset from end
            total_data_size = len(data) - 12
            pixels = data[total_data_size - largest_mip_size + 12:]
        else:
            # No mipmaps, just get all pixel data
            pixels = data[12:12 + largest_mip_size]
        
        # Build DDS header
        # DDS file structure: magic + DDS_HEADER (124 bytes)
        dds_header = struct.pack('<4s7L', 
            b'DDS ',  # magic (4 bytes)
            124,      # dwSize - header size (4 bytes)
            0x1 | 0x2 | 0x4 | 0x1000,  # dwFlags: CAPS, HEIGHT, WIDTH, PIXELFORMAT
            height,   # dwHeight
            width,    # dwWidth
            0,        # dwPitchOrLinearSize
            0,        # dwDepth
            0         # dwMipMapCount
        )
        
        # Reserved space (11 DWORDs = 44 bytes)
        dds_header += b'\x00' * 44
        
        # DDS_PIXELFORMAT (32 bytes)
        dds_header += ddspf
        
        # DDS_CAPS (16 bytes: 4 DWORDs)
        dds_header += struct.pack('<4L', 0x1000, 0, 0, 0)
        
        # Reserved (4 bytes)
        dds_header += b'\x00' * 4
        
        # Add DX10 header if needed
        if has_dx10:
            dds_header += dx10
        
        return dds_header + pixels


def resolve_texture_path(texture_path: str, assets_folder: str) -> Optional[str]:
    """
    Resolve a texture path from the materials file
    
    Args:
        texture_path: Path from materials file (e.g., "ASSETS/Maps/.../texture.tex")
        assets_folder: Base assets folder path selected by user
    
    Returns:
        Full resolved path to texture file, or None if not found
    """
    # Remove "ASSETS/" prefix if present
    if texture_path.startswith("ASSETS/"):
        texture_path = texture_path[7:]
    elif texture_path.startswith("ASSETS\\"):
        texture_path = texture_path[7:]
    
    # Convert to OS-specific path separators
    texture_path = texture_path.replace('/', os.sep).replace('\\', os.sep)
    
    # Join with assets folder
    full_path = os.path.join(assets_folder, texture_path)
    
    if os.path.exists(full_path):
        return full_path
    
    return None
