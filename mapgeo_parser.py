"""
Mapgeo File Parser
Handles reading and writing .mapgeo files based on LeagueToolkit format
Reference: https://github.com/LeagueToolkit/LeagueToolkit
"""

import struct
import io
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import IntEnum, IntFlag

# Constants
MAPGEO_MAGIC = b'OEGM'
SUPPORTED_VERSIONS = [13, 14, 15, 16, 17, 18]

class VertexElementName(IntEnum):
    """Vertex element semantic names - C# enum values are sequential, StreamIndex comments are just D3D mappings"""
    POSITION = 0
    BLEND_WEIGHT = 1
    NORMAL = 2
    FOG_COORDINATE = 3
    PRIMARY_COLOR = 4
    SECONDARY_COLOR = 5
    BLEND_INDEX = 6
    TEXCOORD0 = 7
    TEXCOORD1 = 8
    TEXCOORD2 = 9
    TEXCOORD3 = 10
    TEXCOORD4 = 11
    TEXCOORD5 = 12
    TEXCOORD6 = 13
    TEXCOORD7 = 14
    TANGENT = 15

class VertexElementFormat(IntEnum):
    """Vertex element data formats"""
    X_FLOAT32 = 0
    XY_FLOAT32 = 1
    XYZ_FLOAT32 = 2
    XYZW_FLOAT32 = 3
    BGRA_PACKED8888 = 4
    ZYXW_PACKED8888 = 5
    RGBA_PACKED8888 = 6
    XY_PACKED1616 = 7
    XYZ_PACKED161616 = 8
    XYZW_PACKED16161616 = 9
    XY_PACKED88 = 10
    XYZ_PACKED888 = 11
    XYZW_PACKED8888 = 12

class EnvironmentVisibility(IntFlag):
    """Environment visibility flags for layers"""
    NONE = 0
    LAYER_1 = 1 << 0
    LAYER_2 = 1 << 1
    LAYER_3 = 1 << 2
    LAYER_4 = 1 << 3
    LAYER_5 = 1 << 4
    LAYER_6 = 1 << 5
    LAYER_7 = 1 << 6
    LAYER_8 = 1 << 7
    ALL_LAYERS = LAYER_1 | LAYER_2 | LAYER_3 | LAYER_4 | LAYER_5 | LAYER_6 | LAYER_7 | LAYER_8

class EnvironmentQuality(IntEnum):
    """Quality levels for environment meshes"""
    VERY_LOW = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4

@dataclass
class VertexElement:
    """Represents a vertex element in the vertex declaration"""
    name: VertexElementName
    format: VertexElementFormat
    offset: int = 0
    
    @staticmethod
    def get_format_size(fmt: int) -> int:
        """Get size in bytes for a given format"""
        sizes = {
            0: 4,   # X_FLOAT32
            1: 8,   # XY_FLOAT32
            2: 12,  # XYZ_FLOAT32
            3: 16,  # XYZW_FLOAT32
            4: 4,   # BGRA_PACKED8888
            5: 4,   # ZYXW_PACKED8888
            6: 4,   # RGBA_PACKED8888
            7: 4,   # XY_PACKED1616
            8: 8,   # XYZ_PACKED161616
            9: 8,   # XYZW_PACKED16161616
            10: 2,  # XY_PACKED88
            11: 3,  # XYZ_PACKED888
            12: 4,  # XYZW_PACKED8888
        }
        return sizes.get(fmt, 0)
    
    def get_size(self) -> int:
        """Get size in bytes of this element"""
        return self.get_format_size(self.format)

@dataclass
class VertexBufferDescription:
    """Describes the format of a vertex buffer"""
    usage: int  # VertexBufferUsage
    elements: List[VertexElement] = field(default_factory=list)
    
    def get_vertex_size(self) -> int:
        """Calculate total vertex size in bytes"""
        return sum(elem.get_size() for elem in self.elements)

@dataclass
class VertexBuffer:
    """Contains vertex buffer data"""
    data: bytes
    description: Optional[VertexBufferDescription] = None  # Set when mesh references it
    vertex_count: int = 0

@dataclass
class IndexBuffer:
    """Contains index buffer data"""
    data: bytes
    format: int  # 0 = U16, 1 = U32
    index_count: int = 0
    visibility: EnvironmentVisibility = EnvironmentVisibility.ALL_LAYERS

@dataclass
class LightChannel:
    """Represents a baked/stationary light channel per mesh"""
    texture: str = ""  # Path to lightmap texture
    scale: Tuple[float, float] = (1.0, 1.0)  # UV scale for lightmap atlas
    bias: Tuple[float, float] = (0.0, 0.0)  # UV offset for lightmap atlas

@dataclass
class MeshPrimitive:
    """Represents a submesh/primitive"""
    material: str
    start_index: int
    index_count: int
    min_vertex: int
    max_vertex: int
    hash: int = 0  # Material hash (usually 0, computed by game)

@dataclass
class BoundingSphere:
    """Bounding sphere for mesh"""
    center: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 0.0

@dataclass
class BoundingBox:
    """Axis-aligned bounding box"""
    min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    max: Tuple[float, float, float] = (0.0, 0.0, 0.0)

@dataclass
class Mesh:
    """Represents a mesh in the mapgeo"""
    name: str = ""
    quality: EnvironmentQuality = EnvironmentQuality.MEDIUM
    visibility: EnvironmentVisibility = EnvironmentVisibility.ALL_LAYERS
    bounding_sphere: BoundingSphere = field(default_factory=BoundingSphere)
    bounding_box: BoundingBox = field(default_factory=BoundingBox)
    
    # Vertex/index buffer references
    vertex_count: int = 0
    vertex_declaration_id: int = 0  # Base index into vertex buffer descriptions
    vertex_declaration_count: int = 0  # Number of vertex buffers used
    vertex_buffer_ids: List[int] = field(default_factory=list)  # IDs of vertex buffers
    index_buffer_id: int = 0
    index_count: int = 0
    
    primitives: List[MeshPrimitive] = field(default_factory=list)
    
    # Visibility layer transition behavior (version 14+)
    layer_transition_behavior: int = 0  # 0=Unaffected, 1=TurnInvisibleDoesNotMatch, 2=TurnVisibleDoesMatch
    render_flags: int = 0  # Version 11+: additional render flags
    disable_backface_culling: bool = False  # Whether backface culling is disabled
    
    # Version 18+ unknown field
    unknown_version18_int: int = 0
    
    # Version 15+ visibility controller
    visibility_controller_path_hash: int = 0
    
    # Transform
    transform_matrix: List[float] = field(default_factory=lambda: [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])
    
    # Lightmap channels
    baked_light: Optional[LightChannel] = None  # BAKED_LIGHT channel
    stationary_light: Optional[LightChannel] = None  # STATIONARY_LIGHT channel
    
    # Texture overrides (version >= 17)
    texture_overrides: List['TextureOverride'] = field(default_factory=list)
    
    # Baked paint UV transform (version >= 17)
    baked_paint_scale: Tuple[float, float] = (1.0, 1.0)
    baked_paint_bias: Tuple[float, float] = (0.0, 0.0)

@dataclass
class TextureOverride:
    """Per-mesh texture override (index maps to sampler_defs)"""
    index: int = 0
    texture: str = ""

@dataclass
class SamplerDef:
    """Shader texture override / sampler definition"""
    index: int = 0
    name: str = ""

@dataclass
class GeometryBucket:
    """A single bucket in the bucket grid"""
    max_stickout_x: float = 0.0
    max_stickout_z: float = 0.0
    start_index: int = 0
    base_vertex: int = 0
    inside_face_count: int = 0
    sticking_out_face_count: int = 0

@dataclass
class BucketGrid:
    """Bucketed geometry scene graph for spatial partitioning"""
    path_hash: int = 0  # VisibilityControllerPathHash (version >= 15)
    unknown_v18_float: float = 0.0  # Unknown float (version >= 18)
    min_x: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_z: float = 0.0
    max_stickout_x: float = 0.0
    max_stickout_z: float = 0.0
    bucket_size_x: float = 0.0
    bucket_size_z: float = 0.0
    buckets_per_side: int = 0
    is_disabled: bool = False
    flags: int = 0  # BucketedGeometryFlags (bit 0 = HasFaceVisibilityFlags)
    
    # Geometry data (empty if disabled)
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    indices: List[int] = field(default_factory=list)
    buckets: List[List[GeometryBucket]] = field(default_factory=list)  # 2D grid [row][col]
    face_visibility_flags: List[int] = field(default_factory=list)  # Per-face visibility

@dataclass
class PlanarReflector:
    """Planar reflector data (version >= 13)"""
    transform: List[float] = field(default_factory=lambda: [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1])
    plane: List[Tuple[float, float, float]] = field(default_factory=list)  # 2 vec3s
    normal: Tuple[float, float, float] = (0.0, 1.0, 0.0)

@dataclass
class MapgeoFile:
    """Main mapgeo file structure"""
    version: int = 18
    vertex_buffer_descriptions: List[VertexBufferDescription] = field(default_factory=list)
    vertex_buffers: List[VertexBuffer] = field(default_factory=list)
    index_buffers: List[IndexBuffer] = field(default_factory=list)
    meshes: List[Mesh] = field(default_factory=list)
    
    # Additional data
    sampler_defs: List[SamplerDef] = field(default_factory=list)
    bucket_grids: List[BucketGrid] = field(default_factory=list)
    planar_reflectors: List[PlanarReflector] = field(default_factory=list)


class MapgeoParser:
    """Parser for .mapgeo files"""
    
    def __init__(self):
        self.data = None
    
    def read(self, filepath: str) -> MapgeoFile:
        """Read a mapgeo file"""
        with open(filepath, 'rb') as f:
            return self.read_from_stream(f)
    
    def read_from_stream(self, stream: io.BufferedReader) -> MapgeoFile:
        """Read mapgeo from a stream"""
        mapgeo = MapgeoFile()
        
        # Read header
        magic = stream.read(4)
        if magic != MAPGEO_MAGIC:
            raise ValueError(f"Invalid mapgeo magic: {magic}. Expected {MAPGEO_MAGIC}")
        
        version = struct.unpack('<I', stream.read(4))[0]
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported mapgeo version: {version}")
        
        mapgeo.version = version
        
        # Read sampler definitions (version >= 17 has new format with index + name)
        if version >= 17:
            sampler_count = struct.unpack('<I', stream.read(4))[0]
            for _ in range(sampler_count):
                sampler_index = struct.unpack('<i', stream.read(4))[0]
                sampler_name_len = struct.unpack('<I', stream.read(4))[0]
                sampler_name = stream.read(sampler_name_len).decode('utf-8', errors='ignore')
                mapgeo.sampler_defs.append(SamplerDef(sampler_index, sampler_name))
        elif version >= 9:
            # Version 9-16: simpler format
            sampler_name_len = struct.unpack('<I', stream.read(4))[0]
            sampler_name = stream.read(sampler_name_len).decode('utf-8', errors='ignore')
            mapgeo.sampler_defs.append(SamplerDef(0, sampler_name))
            
            if version >= 11:
                sampler_name_len = struct.unpack('<I', stream.read(4))[0]
                sampler_name = stream.read(sampler_name_len).decode('utf-8', errors='ignore')
                mapgeo.sampler_defs.append(SamplerDef(1, sampler_name))
        
        # Read vertex buffer descriptions
        vertex_buffer_count = struct.unpack('<I', stream.read(4))[0]
        vertex_buffer_descs = []
        
        for _ in range(vertex_buffer_count):
            usage = struct.unpack('<I', stream.read(4))[0]
            element_count = struct.unpack('<I', stream.read(4))[0]
            
            elements = []
            current_offset = 0
            for _ in range(element_count):
                name = struct.unpack('<I', stream.read(4))[0]
                fmt = struct.unpack('<I', stream.read(4))[0]
                # Offset is calculated, not stored in file
                elements.append(VertexElement(name, fmt, current_offset))
                current_offset += VertexElement.get_format_size(fmt)
            
            # Skip unused elements (8 bytes per element: name + format)
            stream.read(8 * (15 - element_count))
            
            vertex_buffer_descs.append(VertexBufferDescription(usage, elements))
        
        # Store vertex buffer descriptions in mapgeo
        mapgeo.vertex_buffer_descriptions = vertex_buffer_descs
        
        # Read vertex buffers - note there's a separate count, not 1-to-1 with descriptions
        vertex_buffer_count = struct.unpack('<I', stream.read(4))[0]
        
        for _ in range(vertex_buffer_count):
            if version >= 13:
                visibility = struct.unpack('<B', stream.read(1))[0]
            
            buffer_size = struct.unpack('<I', stream.read(4))[0]
            buffer_data = stream.read(buffer_size)
            
            # Vertex buffer doesn't have description yet - meshes will link them
            vb = VertexBuffer(buffer_data)
            mapgeo.vertex_buffers.append(vb)
        
        # Read index buffers
        index_buffer_count = struct.unpack('<I', stream.read(4))[0]
        
        for _ in range(index_buffer_count):
            if version >= 13:
                visibility = struct.unpack('<B', stream.read(1))[0]
            else:
                visibility = EnvironmentVisibility.ALL_LAYERS
            
            buffer_size = struct.unpack('<I', stream.read(4))[0]
            buffer_data = stream.read(buffer_size)
            
            # Determine format (U16 or U32) based on size
            index_count = buffer_size // 2  # Assume U16 first
            index_format = 0  # U16
            
            ib = IndexBuffer(buffer_data, index_format, index_count, visibility)
            mapgeo.index_buffers.append(ib)
        
        # Read meshes
        mesh_count = struct.unpack('<I', stream.read(4))[0]
        
        for i in range(mesh_count):
            mesh = Mesh()
            
            # Name (only if version <= 11)
            if version <= 11:
                name_len = struct.unpack('<I', stream.read(4))[0]
                mesh.name = stream.read(name_len).decode('ascii', errors='ignore')
            
            # Vertex and index count info
            mesh.vertex_count = struct.unpack('<I', stream.read(4))[0]
            mesh.vertex_declaration_count = struct.unpack('<I', stream.read(4))[0]
            mesh.vertex_declaration_id = struct.unpack('<I', stream.read(4))[0]
            
            # Read all vertex buffer IDs
            for j in range(mesh.vertex_declaration_count):
                vb_id = struct.unpack('<I', stream.read(4))[0]
                mesh.vertex_buffer_ids.append(vb_id)
            
            # Index buffer info
            mesh.index_count = struct.unpack('<I', stream.read(4))[0]
            mesh.index_buffer_id = struct.unpack('<I', stream.read(4))[0]
            
            # Visibility flags
            if version >= 13:
                mesh.visibility = struct.unpack('<B', stream.read(1))[0]
            
            # Version 18+ unknown int
            if version >= 18:
                mesh.unknown_version18_int = struct.unpack('<I', stream.read(4))[0]
            
            # Version 15+ visibility controller path hash
            if version >= 15:
                mesh.visibility_controller_path_hash = struct.unpack('<I', stream.read(4))[0]
            
            # Primitives/Submeshes
            primitive_count = struct.unpack('<I', stream.read(4))[0]
            for _ in range(primitive_count):
                # Material hash (usually 0)
                prim_hash = struct.unpack('<I', stream.read(4))[0]
                
                # Material name
                material_len = struct.unpack('<I', stream.read(4))[0]
                material = stream.read(material_len).decode('ascii', errors='ignore')
                
                start_index = struct.unpack('<I', stream.read(4))[0]
                index_count = struct.unpack('<I', stream.read(4))[0]
                min_vertex = struct.unpack('<I', stream.read(4))[0]
                max_vertex = struct.unpack('<I', stream.read(4))[0]
                
                primitive = MeshPrimitive(material, start_index, index_count, min_vertex, max_vertex, prim_hash)
                mesh.primitives.append(primitive)
            
            # Disable backface culling (if version != 5)
            if version != 5:
                mesh.disable_backface_culling = struct.unpack('<?', stream.read(1))[0]
            
            # Bounding box
            bbox_min_x, bbox_min_y, bbox_min_z = struct.unpack('<fff', stream.read(12))
            bbox_max_x, bbox_max_y, bbox_max_z = struct.unpack('<fff', stream.read(12))
            mesh.bounding_box = BoundingBox((bbox_min_x, bbox_min_y, bbox_min_z), 
                                           (bbox_max_x, bbox_max_y, bbox_max_z))
            
            # Transform matrix (16 floats)
            mesh.transform_matrix = list(struct.unpack('<16f', stream.read(64)))
            
            # Quality filter
            mesh.quality = struct.unpack('<B', stream.read(1))[0]
            
            # Additional version-specific fields (version >= 7 && <= 12)
            if version >= 7 and version <= 12:
                mesh.visibility = struct.unpack('<B', stream.read(1))[0]
            
            # Render flags and layer transition behavior
            if version >= 11 and version < 14:
                mesh.render_flags = struct.unpack('<B', stream.read(1))[0]
                # layer_transition_behavior computed from render_flags
            elif version >= 14:
                # Version 14+: layer transition behavior (0=Unaffected, 1=TurnInvisible, 2=TurnVisible)
                mesh.layer_transition_behavior = struct.unpack('<B', stream.read(1))[0]
                if version < 16:
                    mesh.render_flags = struct.unpack('<B', stream.read(1))[0]
                else:
                    mesh.render_flags = struct.unpack('<H', stream.read(2))[0]
            
            # Spherical harmonics and baked light for version < 9
            if version < 9:
                # Skip 9 Vector3s (spherical harmonics)
                stream.read(9 * 12)  # 9 * (3 floats * 4 bytes)
                # Read baked light channel
                mesh.baked_light = self._read_light_channel(stream)
                # Early return for version < 9
                mapgeo.meshes.append(mesh)
                continue
            
            # Version >= 9: Read baked light channel
            mesh.baked_light = self._read_light_channel(stream)
            
            # Version >= 9: Read stationary light channel
            mesh.stationary_light = self._read_light_channel(stream)
            
            # Version >= 12 && < 17: Read baked paint channel
            if version >= 12 and version < 17:
                self._read_light_channel(stream)  # baked paint (not stored)
            
            # Version >= 17: Read texture overrides
            if version >= 17:
                texture_override_count = struct.unpack('<I', stream.read(4))[0]
                for _ in range(texture_override_count):
                    override_index = struct.unpack('<I', stream.read(4))[0]
                    override_tex_len = struct.unpack('<I', stream.read(4))[0]
                    override_tex_name = stream.read(override_tex_len).decode('utf-8', errors='replace')
                    mesh.texture_overrides.append(TextureOverride(override_index, override_tex_name))
                
                # BakedPaintScale and BakedPaintBias
                bp_sx, bp_sy, bp_bx, bp_by = struct.unpack('<4f', stream.read(16))
                mesh.baked_paint_scale = (bp_sx, bp_sy)
                mesh.baked_paint_bias = (bp_bx, bp_by)
            
            # Calculate bounding sphere from box (approximation)
            center_x = (bbox_min_x + bbox_max_x) / 2
            center_y = (bbox_min_y + bbox_max_y) / 2
            center_z = (bbox_min_z + bbox_max_z) / 2
            radius = ((bbox_max_x - bbox_min_x)**2 + (bbox_max_y - bbox_min_y)**2 + (bbox_max_z - bbox_min_z)**2)**0.5 / 2
            mesh.bounding_sphere = BoundingSphere((center_x, center_y, center_z), radius)
            
            mapgeo.meshes.append(mesh)
        
        # Read bucket grids (scene graphs)
        # Check if there's still data to read (some modded files may not have bucket grids)
        remaining = self._remaining_bytes(stream)
        if remaining > 0:
            try:
                mapgeo.bucket_grids = self._read_bucket_grids(stream, version)
            except Exception as e:
                print(f"Warning: Failed to read bucket grids: {e}")
                mapgeo.bucket_grids = []
            
            # Read planar reflectors (version >= 13)
            remaining = self._remaining_bytes(stream)
            if remaining > 0 and version >= 13:
                try:
                    mapgeo.planar_reflectors = self._read_planar_reflectors(stream)
                except Exception as e:
                    print(f"Warning: Failed to read planar reflectors: {e}")
                    mapgeo.planar_reflectors = []
        
        return mapgeo
    
    def _remaining_bytes(self, stream) -> int:
        """Check how many bytes remain in the stream"""
        current = stream.tell()
        stream.seek(0, 2)  # Seek to end
        end = stream.tell()
        stream.seek(current)  # Seek back
        return end - current
    
    def _read_bucket_grids(self, stream, version: int) -> List[BucketGrid]:
        """Read bucket grid scene graphs from stream"""
        grids = []
        
        if version >= 15:
            grid_count = struct.unpack('<I', stream.read(4))[0]
        else:
            grid_count = 1
        
        for _ in range(grid_count):
            grid = BucketGrid()
            
            if version >= 15:
                grid.path_hash = struct.unpack('<I', stream.read(4))[0]
            
            if version >= 18:
                grid.unknown_v18_float = struct.unpack('<f', stream.read(4))[0]
            
            grid.min_x, grid.min_z, grid.max_x, grid.max_z = struct.unpack('<4f', stream.read(16))
            grid.max_stickout_x, grid.max_stickout_z = struct.unpack('<2f', stream.read(8))
            grid.bucket_size_x, grid.bucket_size_z = struct.unpack('<2f', stream.read(8))
            
            grid.buckets_per_side = struct.unpack('<H', stream.read(2))[0]
            grid.is_disabled = struct.unpack('<?', stream.read(1))[0]
            grid.flags = struct.unpack('<B', stream.read(1))[0]
            
            vertex_count, index_count = struct.unpack('<2I', stream.read(8))
            
            if grid.is_disabled:
                grids.append(grid)
                continue
            
            # Read vertices (Vector3)
            for _ in range(vertex_count):
                x, y, z = struct.unpack('<3f', stream.read(12))
                grid.vertices.append((x, y, z))
            
            # Read indices (u16)
            for _ in range(index_count):
                idx = struct.unpack('<H', stream.read(2))[0]
                grid.indices.append(idx)
            
            # Read buckets (buckets_per_side × buckets_per_side)
            for i in range(grid.buckets_per_side):
                row = []
                for j in range(grid.buckets_per_side):
                    bucket = GeometryBucket()
                    bucket.max_stickout_x, bucket.max_stickout_z = struct.unpack('<2f', stream.read(8))
                    bucket.start_index, bucket.base_vertex = struct.unpack('<2I', stream.read(8))
                    bucket.inside_face_count, bucket.sticking_out_face_count = struct.unpack('<2H', stream.read(4))
                    row.append(bucket)
                grid.buckets.append(row)
            
            # Read face visibility flags if present
            if grid.flags & 1:  # HasFaceVisibilityFlags
                face_count = index_count // 3
                for _ in range(face_count):
                    flag = struct.unpack('<B', stream.read(1))[0]
                    grid.face_visibility_flags.append(flag)
            
            grids.append(grid)
        
        return grids
    
    def _read_planar_reflectors(self, stream) -> List[PlanarReflector]:
        """Read planar reflectors from stream"""
        reflectors = []
        count = struct.unpack('<I', stream.read(4))[0]
        
        for _ in range(count):
            pr = PlanarReflector()
            pr.transform = list(struct.unpack('<16f', stream.read(64)))
            # 2 Vector3s for the plane
            v1 = struct.unpack('<3f', stream.read(12))
            v2 = struct.unpack('<3f', stream.read(12))
            pr.plane = [v1, v2]
            pr.normal = struct.unpack('<3f', stream.read(12))
            reflectors.append(pr)
        
        return reflectors
    
    def _read_light_channel(self, stream) -> LightChannel:
        """Read a light channel (texture path + scale + bias) from stream"""
        channel = LightChannel()
        tex_len = struct.unpack('<I', stream.read(4))[0]
        if tex_len > 0:
            channel.texture = stream.read(tex_len).decode('utf-8', errors='replace')
        scale_x, scale_y, bias_x, bias_y = struct.unpack('<4f', stream.read(16))
        channel.scale = (scale_x, scale_y)
        channel.bias = (bias_x, bias_y)
        return channel
    
    def write(self, filepath: str, mapgeo: MapgeoFile):
        """Write a mapgeo file"""
        with open(filepath, 'wb') as f:
            self.write_to_stream(f, mapgeo)
    
    def write_to_stream(self, stream: io.BufferedWriter, mapgeo: MapgeoFile):
        """Write mapgeo to a stream"""
        # Write header
        stream.write(MAPGEO_MAGIC)
        stream.write(struct.pack('<I', mapgeo.version))
        
        # Write sampler definitions
        if mapgeo.version >= 17:
            stream.write(struct.pack('<I', len(mapgeo.sampler_defs)))
            for sampler in mapgeo.sampler_defs:
                stream.write(struct.pack('<i', sampler.index))
                sampler_bytes = sampler.name.encode('utf-8')
                stream.write(struct.pack('<I', len(sampler_bytes)))
                stream.write(sampler_bytes)
        elif mapgeo.version >= 9:
            # Write version 9-16 format
            if len(mapgeo.sampler_defs) > 0:
                sampler_bytes = mapgeo.sampler_defs[0].name.encode('utf-8')
                stream.write(struct.pack('<I', len(sampler_bytes)))
                stream.write(sampler_bytes)
            
            if mapgeo.version >= 11 and len(mapgeo.sampler_defs) > 1:
                sampler_bytes = mapgeo.sampler_defs[1].name.encode('utf-8')
                stream.write(struct.pack('<I', len(sampler_bytes)))
                stream.write(sampler_bytes)
        
        # Write vertex buffer descriptions
        desc_list = mapgeo.vertex_buffer_descriptions
        if not desc_list:
            desc_list = [vb.description for vb in mapgeo.vertex_buffers if vb.description is not None]
        
        stream.write(struct.pack('<I', len(desc_list)))
        
        for desc in desc_list:
            stream.write(struct.pack('<I', desc.usage))
            stream.write(struct.pack('<I', len(desc.elements)))
            
            for elem in desc.elements:
                stream.write(struct.pack('<I', elem.name))
                stream.write(struct.pack('<I', elem.format))
                # Offset is not written, it's calculated on read
            
            # Pad unused elements (8 bytes each: name + format)
            for _ in range(15 - len(desc.elements)):
                stream.write(struct.pack('<II', 0, 0))
        
        # Write vertex buffers
        stream.write(struct.pack('<I', len(mapgeo.vertex_buffers)))
        
        for vb in mapgeo.vertex_buffers:
            if mapgeo.version >= 13:
                stream.write(struct.pack('<B', EnvironmentVisibility.ALL_LAYERS))
            
            stream.write(struct.pack('<I', len(vb.data)))
            stream.write(vb.data)
        
        # Write index buffers
        stream.write(struct.pack('<I', len(mapgeo.index_buffers)))
        
        for ib in mapgeo.index_buffers:
            if mapgeo.version >= 13:
                stream.write(struct.pack('<B', ib.visibility))
            
            stream.write(struct.pack('<I', len(ib.data)))
            stream.write(ib.data)
        
        # Write meshes
        stream.write(struct.pack('<I', len(mapgeo.meshes)))
        
        for mesh in mapgeo.meshes:
            # Name (only if version <= 11)
            if mapgeo.version <= 11:
                name_bytes = mesh.name.encode('ascii')
                stream.write(struct.pack('<I', len(name_bytes)))
                stream.write(name_bytes)
            
            # Vertex count - calculate from vertex buffer if available
            vb_ids = list(mesh.vertex_buffer_ids) if mesh.vertex_buffer_ids else []
            if not vb_ids and hasattr(mesh, "vertex_buffer_id"):
                vb_ids = [mesh.vertex_buffer_id]
            
            decl_count = mesh.vertex_declaration_count if mesh.vertex_declaration_count else (len(vb_ids) if vb_ids else 1)
            decl_id = mesh.vertex_declaration_id if mesh.vertex_declaration_count else (vb_ids[0] if vb_ids else 0)
            if not vb_ids:
                vb_ids = [decl_id]
            
            if len(vb_ids) < decl_count:
                vb_ids += [decl_id] * (decl_count - len(vb_ids))
            elif len(vb_ids) > decl_count:
                vb_ids = vb_ids[:decl_count]
            
            vertex_count = mesh.vertex_count
            if not vertex_count and vb_ids and vb_ids[0] < len(mapgeo.vertex_buffers):
                vertex_count = mapgeo.vertex_buffers[vb_ids[0]].vertex_count
            
            # Write vertex/index buffer info
            stream.write(struct.pack('<I', vertex_count))
            stream.write(struct.pack('<I', decl_count))
            stream.write(struct.pack('<I', decl_id))
            for vb_id in vb_ids:
                stream.write(struct.pack('<I', vb_id))
            
            # Index count
            index_count = mesh.index_count if mesh.index_count else sum(p.index_count for p in mesh.primitives)
            stream.write(struct.pack('<I', index_count))
            stream.write(struct.pack('<I', mesh.index_buffer_id))
            
            # Visibility flags
            if mapgeo.version >= 13:
                stream.write(struct.pack('<B', mesh.visibility))
            
            # Version 18+ unknown int
            if mapgeo.version >= 18:
                stream.write(struct.pack('<I', mesh.unknown_version18_int))
            
            # Version 15+ visibility controller
            if mapgeo.version >= 15:
                stream.write(struct.pack('<I', mesh.visibility_controller_path_hash))
            
            # Primitives
            stream.write(struct.pack('<I', len(mesh.primitives)))
            for prim in mesh.primitives:
                stream.write(struct.pack('<I', prim.hash))
                material_bytes = prim.material.encode('ascii')
                stream.write(struct.pack('<I', len(material_bytes)))
                stream.write(material_bytes)
                
                stream.write(struct.pack('<I', prim.start_index))
                stream.write(struct.pack('<I', prim.index_count))
                stream.write(struct.pack('<I', prim.min_vertex))
                stream.write(struct.pack('<I', prim.max_vertex))
            
            # Disable backface culling
            if mapgeo.version != 5:
                stream.write(struct.pack('<?', mesh.disable_backface_culling))
            
            # Bounding box
            stream.write(struct.pack('<fff', *mesh.bounding_box.min))
            stream.write(struct.pack('<fff', *mesh.bounding_box.max))
            
            # Transform matrix
            stream.write(struct.pack('<16f', *mesh.transform_matrix))
            
            # Quality filter
            stream.write(struct.pack('<B', mesh.quality))
            
            # Version-specific visibility (7-12)
            if mapgeo.version >= 7 and mapgeo.version <= 12:
                stream.write(struct.pack('<B', mesh.visibility))
            
            # Render flags / layer transition behavior
            if mapgeo.version >= 11 and mapgeo.version < 14:
                stream.write(struct.pack('<B', mesh.render_flags))
            elif mapgeo.version >= 14:
                stream.write(struct.pack('<B', mesh.layer_transition_behavior))
                if mapgeo.version < 16:
                    stream.write(struct.pack('<B', mesh.render_flags))
                else:
                    stream.write(struct.pack('<H', mesh.render_flags))
            
            # Light channels
            if mapgeo.version < 9:
                # Spherical harmonics (9 zero vec3s)
                stream.write(b'\x00' * (9 * 12))
                self._write_light_channel(stream, mesh.baked_light)
            else:
                self._write_light_channel(stream, mesh.baked_light)
                self._write_light_channel(stream, mesh.stationary_light)
                
                if mapgeo.version >= 12 and mapgeo.version < 17:
                    # Empty baked paint channel
                    self._write_light_channel(stream, None)
                
                if mapgeo.version >= 17:
                    # Texture overrides
                    stream.write(struct.pack('<I', len(mesh.texture_overrides)))
                    for override in mesh.texture_overrides:
                        stream.write(struct.pack('<I', override.index))
                        tex_bytes = override.texture.encode('utf-8')
                        stream.write(struct.pack('<I', len(tex_bytes)))
                        stream.write(tex_bytes)
                    # BakedPaintScale + BakedPaintBias
                    stream.write(struct.pack('<4f', mesh.baked_paint_scale[0], mesh.baked_paint_scale[1],
                                             mesh.baked_paint_bias[0], mesh.baked_paint_bias[1]))
        
        # Write bucket grids
        self._write_bucket_grids(stream, mapgeo)
        
        # Write planar reflectors (version >= 13)
        if mapgeo.version >= 13:
            self._write_planar_reflectors(stream, mapgeo)
        
        print(f"Wrote mapgeo version {mapgeo.version}")
    
    def _write_bucket_grids(self, stream, mapgeo: MapgeoFile):
        """Write bucket grid scene graphs to stream"""
        if mapgeo.version >= 15:
            stream.write(struct.pack('<I', len(mapgeo.bucket_grids)))
        
        for grid in mapgeo.bucket_grids:
            if mapgeo.version >= 15:
                stream.write(struct.pack('<I', grid.path_hash))
            
            if mapgeo.version >= 18:
                stream.write(struct.pack('<f', grid.unknown_v18_float))
            
            stream.write(struct.pack('<4f', grid.min_x, grid.min_z, grid.max_x, grid.max_z))
            stream.write(struct.pack('<2f', grid.max_stickout_x, grid.max_stickout_z))
            stream.write(struct.pack('<2f', grid.bucket_size_x, grid.bucket_size_z))
            
            stream.write(struct.pack('<H', grid.buckets_per_side))
            stream.write(struct.pack('<?', grid.is_disabled))
            stream.write(struct.pack('<B', grid.flags))
            
            stream.write(struct.pack('<2I', len(grid.vertices), len(grid.indices)))
            
            if grid.is_disabled:
                continue
            
            # Write vertices
            for v in grid.vertices:
                stream.write(struct.pack('<3f', v[0], v[1], v[2]))
            
            # Write indices
            for idx in grid.indices:
                stream.write(struct.pack('<H', idx))
            
            # Write buckets
            for row in grid.buckets:
                for bucket in row:
                    stream.write(struct.pack('<2f', bucket.max_stickout_x, bucket.max_stickout_z))
                    stream.write(struct.pack('<2I', bucket.start_index, bucket.base_vertex))
                    stream.write(struct.pack('<2H', bucket.inside_face_count, bucket.sticking_out_face_count))
            
            # Write face visibility flags
            if grid.flags & 1:
                for flag in grid.face_visibility_flags:
                    stream.write(struct.pack('<B', flag))
    
    def _write_planar_reflectors(self, stream, mapgeo: MapgeoFile):
        """Write planar reflectors to stream"""
        stream.write(struct.pack('<I', len(mapgeo.planar_reflectors)))
        for pr in mapgeo.planar_reflectors:
            stream.write(struct.pack('<16f', *pr.transform))
            for plane_vec in pr.plane:
                stream.write(struct.pack('<3f', *plane_vec))
            stream.write(struct.pack('<3f', *pr.normal))
    
    def _write_light_channel(self, stream, channel: Optional[LightChannel]):
        """Write a light channel to stream"""
        if channel and channel.texture:
            tex_bytes = channel.texture.encode('utf-8')
            stream.write(struct.pack('<I', len(tex_bytes)))
            stream.write(tex_bytes)
            stream.write(struct.pack('<4f', channel.scale[0], channel.scale[1],
                                     channel.bias[0], channel.bias[1]))
        else:
            stream.write(struct.pack('<I', 0))
            # Write actual scale/bias if channel exists, otherwise zeros
            if channel:
                stream.write(struct.pack('<4f', channel.scale[0], channel.scale[1],
                                         channel.bias[0], channel.bias[1]))
            else:
                stream.write(struct.pack('<4f', 0.0, 0.0, 0.0, 0.0))
