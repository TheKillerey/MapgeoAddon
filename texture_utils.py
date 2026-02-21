"""
Texture Utilities for Mapgeo Addon
Handles Riot .tex format — converts to DDS in-memory, writes a temp file,
loads via Blender's native DDS support, packs into .blend, then cleans up.
"""

import struct
import os
import math
import tempfile
from typing import Optional

# Late-import helper to avoid circular dependency at module load time
def _log():
    from debug_system import get_debug_log
    return get_debug_log()


def _is_debug_enabled():
    """Check if debug logging is enabled in mapgeo settings."""
    import bpy
    if hasattr(bpy.context, 'scene') and hasattr(bpy.context.scene, 'mapgeo_settings'):
        return bpy.context.scene.mapgeo_settings.debug_logging
    return False


class TexConverter:
    """Converts Riot .tex files to DDS and loads them via Blender's native loader."""

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def load_tex_as_blender_image(self, tex_path: str, image_name: str = None):
        """
        Convert a .tex file to DDS, load it natively in Blender, pack it,
        then delete the temp DDS file.

        Args:
            tex_path:   Absolute path to the ``.tex`` file.
            image_name: Optional display name; defaults to the file basename.

        Returns:
            ``bpy.types.Image`` on success, ``None`` on failure.
        """
        import bpy

        tex_path = os.path.normpath(os.path.abspath(tex_path))

        if not os.path.exists(tex_path):
            print(f"  [Texture] TEX file not found: {tex_path}")
            return None

        # --- deduplicate — reuse if already loaded ----------------------
        for img in bpy.data.images:
            if img.get('_tex_source_path') == tex_path:
                # Only log reuse in debug mode to avoid spam
                if _is_debug_enabled():
                    print(f"  [Texture] Reusing loaded TEX image: {img.name}")
                return img

        # --- read TEX ---------------------------------------------------
        try:
            with open(tex_path, 'rb') as fh:
                tex_data = fh.read()
        except OSError as exc:
            print(f"  [Texture] Cannot read TEX file: {exc}")
            return None

        if len(tex_data) < 12 or tex_data[:4] != b'TEX\0':
            print(f"  [Texture] Invalid TEX header: {tex_path}")
            return None

        # --- convert to DDS bytes ---------------------------------------
        try:
            dds_data = self._tex_to_dds(tex_data)
        except Exception as exc:
            print(f"  [Texture] TEX→DDS conversion failed for {tex_path}: {exc}")
            return None

        # --- write temp DDS, load, pack, delete -------------------------
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dds', prefix='mapgeo_tex_')
            os.write(tmp_fd, dds_data)
            os.close(tmp_fd)
            tmp_fd = None  # mark closed

            img = bpy.data.images.load(tmp_path, check_existing=False)
            img.pack()  # embed valid DDS data into .blend

            # Give it a nice name
            if image_name is None:
                image_name = os.path.basename(tex_path)
            img.name = image_name

            # Tag for deduplication
            img['_tex_source_path'] = tex_path

            # Only log success in debug mode to reduce console spam
            if _is_debug_enabled():
                print(f"  [Texture] TEX loaded via DDS: {tex_path}")
            return img

        except Exception as exc:
            print(f"  [Texture] Failed to load TEX as DDS: {tex_path}: {exc}")
            return None
        finally:
            # Clean up temp file
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # kept for API compatibility
    def clear_cache(self):
        """No-op kept for API compatibility."""
        pass

    # ------------------------------------------------------------------ #
    #  TEX → DDS conversion                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tex_to_dds(data: bytes) -> bytes:
        """
        Build a valid DDS file from raw TEX data.
        Based on CommunityDragon CDTB implementation.
        """
        _magic, width, height, _ext, tex_fmt, _res, flags = \
            struct.unpack('<4sHHBBBB', data[:12])
        has_mipmaps = bool(flags & 0x01)
        has_dx10 = False

        # Map TEX format → DDS pixel-format struct (32 bytes)
        if tex_fmt == 0x0a:        # DXT1 / BC1
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DXT1')
        elif tex_fmt == 0x0c:      # DXT5 / BC3
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DXT5')
        elif tex_fmt == 0x14:      # BGRA8
            ddspf = struct.pack('<LL4x5L', 32, 0x41,
                                8 * 4, 0x00ff0000, 0x0000ff00,
                                0x000000ff, 0xff000000)
        elif tex_fmt == 0x15:      # RGBA16 → needs DX10 extension
            ddspf = struct.pack('<LL4s20x', 32, 0x4, b'DX10')
            dx10 = struct.pack('<LL4xLL', 13, 3, 1, 1)
            has_dx10 = True
        else:
            raise ValueError(f"Unsupported TEX format: 0x{tex_fmt:02x}")

        # Block / pixel sizes
        if tex_fmt == 0x0a:
            bs, bpb = 4, 8
        elif tex_fmt == 0x0c:
            bs, bpb = 4, 16
        elif tex_fmt == 0x14:
            bs, bpb = 1, 4
        else:
            bs, bpb = 1, 8

        bw = (width + bs - 1) // bs
        bh = (height + bs - 1) // bs
        largest = bw * bh * bpb

        # TEX stores mipmaps smallest→largest; largest is at the end
        if has_mipmaps:
            total = len(data) - 12
            start = 12 + total - largest
            pixels = data[start:]
        else:
            pixels = data[12:12 + largest]

        # Build DDS header (128 bytes)
        hdr = struct.pack('<4s7L',
            b'DDS ', 124,
            0x1 | 0x2 | 0x4 | 0x1000,  # CAPS | HEIGHT | WIDTH | PIXELFORMAT
            height, width,
            0, 0, 0)                    # pitch, depth, mipcount
        hdr += b'\x00' * 44            # reserved1[11]
        hdr += ddspf                   # pixel format (32 bytes)
        hdr += struct.pack('<4L', 0x1000, 0, 0, 0)  # caps
        hdr += b'\x00' * 4             # reserved2

        if has_dx10:
            hdr += dx10

        return hdr + pixels


def resolve_texture_path(texture_path: str, assets_folder: str, custom_assets_folder: str = "", prioritize_custom: bool = False) -> Optional[str]:
    """
    Resolve a texture path from the materials file.
    Tries multiple extensions in order: .tex -> .dds -> .png
    Checks folders based on priority setting.
    
    Args:
        texture_path: Path from materials file (e.g., "ASSETS/Maps/.../texture.tex")
        assets_folder: Original Riot assets folder path
        custom_assets_folder: Custom assets folder path
        prioritize_custom: If True, check custom folder first, then original. If False, check original first.
    
    Returns:
        Full resolved path to texture file, or None if not found
    """
    original_texture_path = texture_path

    # Remove "ASSETS/" prefix if present
    if texture_path.startswith("ASSETS/"):
        texture_path = texture_path[7:]
    elif texture_path.startswith("ASSETS\\"):
        texture_path = texture_path[7:]
    
    # Convert to OS-specific path separators
    texture_path = texture_path.replace('/', os.sep).replace('\\', os.sep)
    
    # Determine folder order based on priority
    folders = []
    if prioritize_custom:
        # Custom first, then original
        if custom_assets_folder:
            folders.append(custom_assets_folder)
        if assets_folder:
            folders.append(assets_folder)
    else:
        # Original first, then custom (default)
        if assets_folder:
            folders.append(assets_folder)
        if custom_assets_folder:
            folders.append(custom_assets_folder)
    
    attempted_paths = []

    # Try each folder in order
    for folder in folders:
        full_path = os.path.join(folder, texture_path)
        attempted_paths.append(full_path)
        
        # Try exact path first
        if os.path.exists(full_path):
            _log().info("Texture", f"Resolved: {original_texture_path}", full_path)
            return full_path
        
        # Try alternative extensions in order: .tex -> .dds -> .png
        base_path = os.path.splitext(full_path)[0]
        extensions = ['.tex', '.dds', '.png']
        
        for ext in extensions:
            test_path = base_path + ext
            attempted_paths.append(test_path)
            if os.path.exists(test_path):
                _log().info("Texture", f"Resolved: {original_texture_path}", test_path)
                return test_path
    
    tried_str = ", ".join(attempted_paths[:4])
    _log().texture_missing(original_texture_path, f"Tried: {tried_str}")

    return None
