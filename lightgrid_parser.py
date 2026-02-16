"""
LightGrid file parser - reads/writes League of Legends light grid data.

Format (from LeagueToolkit):
- uint32: version (must be 3)
- uint32: gridOffset (header size, typically 32 bytes)
- int32: width
- int32: height  
- Vector2: bounds (2 floats)
- float: lightScale
- float: fullbrightIntensity
- [At gridOffset]: lightgrid cell data
  - Each cell: 24 bytes (6 colors * 4 bytes BGRA each)
  - Color format: BGRA with 8 bits per channel

LightGridCell = 6 RGB colors (C1-C6) representing light sampling directions:
  - C1-C4: Directional light samples (typically from 4 directions)
  - C5-C6: Sky/ambient light colors
"""

import struct
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Color:
    """8-bit RGBA color"""
    r: float
    g: float
    b: float
    a: float
    
    @staticmethod
    def from_bgra(bgra: int) -> 'Color':
        """Convert 32-bit BGRA to Color (normalize to 0-1)"""
        b = (bgra >> 0) & 0xFF
        g = (bgra >> 8) & 0xFF
        r = (bgra >> 16) & 0xFF
        a = (bgra >> 24) & 0xFF
        return Color(r/255.0, g/255.0, b/255.0, a/255.0)
    
    def to_bgra(self) -> int:
        """Convert Color to 32-bit BGRA"""
        b = int(max(0, min(255, self.b * 255)))
        g = int(max(0, min(255, self.g * 255)))
        r = int(max(0, min(255, self.r * 255)))
        a = int(max(0, min(255, self.a * 255)))
        return (a << 24) | (r << 16) | (g << 8) | b
    
    def to_tuple(self) -> Tuple[float, float, float, float]:
        """Return as (r, g, b, a)"""
        return (self.r, self.g, self.b, self.a)


@dataclass
class LightGridCell:
    """Single cell in the light grid (6 color samples)"""
    c1: Color  # Direction 1
    c2: Color  # Direction 2
    c3: Color  # Direction 3
    c4: Color  # Direction 4
    c5: Color  # Sky/Ambient
    c6: Color  # Bounce/Environment
    
    def to_bgra_list(self) -> List[int]:
        """Export as list of 6 BGRA values"""
        return [self.c1.to_bgra(), self.c2.to_bgra(), self.c3.to_bgra(),
                self.c4.to_bgra(), self.c5.to_bgra(), self.c6.to_bgra()]


class LightGrid:
    """League of Legends LightGrid - spatial light sampling grid"""
    
    def __init__(self, width: int = 0, height: int = 0, 
                 bounds: Tuple[float, float] = (0.0, 0.0),
                 light_scale: float = 1.0, fullbright_intensity: float = 1.0):
        self.version = 3
        self.width = width
        self.height = height
        self.bounds = bounds
        self.light_scale = light_scale
        self.fullbright_intensity = fullbright_intensity
        self.cells: List[LightGridCell] = []
    
    def read(self, filepath: str):
        """Read LightGrid from file"""
        with open(filepath, 'rb') as f:
            self.read_stream(f)
    
    def read_stream(self, stream):
        """Read LightGrid from binary stream"""
        data = stream.read()
        reader = BinaryReader(data)
        
        # Header
        version = reader.read_uint32()
        if version != 3:
            raise ValueError(f"Invalid LightGrid version: {version}, expected 3")
        
        grid_offset = reader.read_uint32()
        self.width = reader.read_int32()
        self.height = reader.read_int32()
        
        bounds_x = reader.read_float()
        bounds_y = reader.read_float()
        self.bounds = (bounds_x, bounds_y)
        
        self.light_scale = reader.read_float()
        self.fullbright_intensity = reader.read_float()
        
        # Read grid data at offset
        reader.seek(grid_offset)
        self.cells = []
        
        for _ in range(self.width * self.height):
            colors = []
            for _ in range(6):
                bgra = reader.read_uint32()
                colors.append(Color.from_bgra(bgra))
            
            cell = LightGridCell(
                c1=colors[0], c2=colors[1], c3=colors[2],
                c4=colors[3], c5=colors[4], c6=colors[5]
            )
            self.cells.append(cell)
        
        print(f"✓ Loaded LightGrid: {self.width}x{self.height}, "
              f"bounds={self.bounds}, scale={self.light_scale}, fullbright={self.fullbright_intensity}")
    
    def write(self, filepath: str):
        """Write LightGrid to file"""
        with open(filepath, 'wb') as f:
            self.write_stream(f)
    
    def write_stream(self, stream):
        """Write LightGrid to binary stream"""
        writer = BinaryWriter()
        
        # Header (32 bytes typical)
        header_size = 32
        writer.write_uint32(self.version)
        writer.write_uint32(header_size)
        writer.write_int32(self.width)
        writer.write_int32(self.height)
        writer.write_float(self.bounds[0])
        writer.write_float(self.bounds[1])
        writer.write_float(self.light_scale)
        writer.write_float(self.fullbright_intensity)
        
        # Grid data
        for cell in self.cells:
            for bgra in cell.to_bgra_list():
                writer.write_uint32(bgra)
        
        stream.write(writer.data)
        print(f"✓ Wrote LightGrid: {self.width}x{self.height}, {len(self.cells)} cells")


class BinaryReader:
    """Simple binary reader"""
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
    
    def read(self, count: int) -> bytes:
        """Read raw bytes"""
        result = self.data[self.offset:self.offset + count]
        self.offset += count
        return result
    
    def read_uint32(self) -> int:
        result = struct.unpack_from('<I', self.data, self.offset)[0]
        self.offset += 4
        return result
    
    def read_int32(self) -> int:
        result = struct.unpack_from('<i', self.data, self.offset)[0]
        self.offset += 4
        return result
    
    def read_float(self) -> float:
        result = struct.unpack_from('<f', self.data, self.offset)[0]
        self.offset += 4
        return result
    
    def seek(self, offset: int):
        self.offset = offset


class BinaryWriter:
    """Simple binary writer"""
    def __init__(self):
        self.data = bytearray()
    
    def write(self, data: bytes):
        self.data.extend(data)
    
    def write_uint32(self, value: int):
        self.write(struct.pack('<I', value))
    
    def write_int32(self, value: int):
        self.write(struct.pack('<i', value))
    
    def write_float(self, value: float):
        self.write(struct.pack('<f', value))
