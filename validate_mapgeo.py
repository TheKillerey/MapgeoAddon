"""
Mapgeo File Validation Script
Thoroughly validates a mapgeo file to identify issues that could cause game crashes
"""

import struct
import sys
from typing import List, Dict, Tuple
from dataclasses import dataclass

@dataclass
class ValidationIssue:
    """Represents a validation issue found in the file"""
    severity: str  # "ERROR", "WARNING", "INFO"
    category: str  # "VERTEX_BUFFER", "INDEX_BUFFER", "MESH", "BOUNDING_BOX", etc.
    mesh_index: int = -1
    message: str = ""
    offset: int = -1
    expected: str = ""
    actual: str = ""

class MapgeoValidator:
    """Validates mapgeo file structure and data integrity"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.issues: List[ValidationIssue] = []
        self.file_data: bytes = b''
        self.version: int = 0
        
    def validate(self) -> List[ValidationIssue]:
        """Run full validation suite"""
        print(f"=== Validating: {self.filepath} ===\n")
        
        # Read file
        try:
            with open(self.filepath, 'rb') as f:
                self.file_data = f.read()
        except Exception as e:
            self.add_error("FILE", f"Failed to read file: {e}")
            return self.issues
        
        print(f"File size: {len(self.file_data)} bytes\n")
        
        # Parse and validate
        try:
            self._validate_header()
            self._parse_and_validate_structure()
        except Exception as e:
            self.add_error("PARSING", f"Critical parsing error: {e}")
            import traceback
            traceback.print_exc()
        
        return self.issues
    
    def add_error(self, category: str, message: str, **kwargs):
        """Add an error issue"""
        issue = ValidationIssue("ERROR", category, message=message, **kwargs)
        self.issues.append(issue)
        
    def add_warning(self, category: str, message: str, **kwargs):
        """Add a warning issue"""
        issue = ValidationIssue("WARNING", category, message=message, **kwargs)
        self.issues.append(issue)
        
    def add_info(self, category: str, message: str, **kwargs):
        """Add an info issue"""
        issue = ValidationIssue("INFO", category, message=message, **kwargs)
        self.issues.append(issue)
    
    def _validate_header(self):
        """Validate file header"""
        if len(self.file_data) < 8:
            self.add_error("HEADER", "File too small to contain valid header")
            return
        
        magic = self.file_data[0:4]
        if magic != b'OEGM':
            self.add_error("HEADER", f"Invalid magic bytes", expected="OEGM", actual=magic.hex())
        
        self.version = struct.unpack('<I', self.file_data[4:8])[0]
        if self.version not in [13, 14, 15, 16, 17, 18]:
            self.add_warning("HEADER", f"Unsupported version", actual=str(self.version))
        else:
            self.add_info("HEADER", f"Mapgeo version {self.version}")
    
    def _parse_and_validate_structure(self):
        """Parse and validate the entire structure"""
        offset = 8  # After header
        
        # Parse sampler defs
        offset = self._parse_sampler_defs(offset)
        
        # Parse vertex buffer descriptions
        offset, vb_descs = self._parse_vertex_buffer_descriptions(offset)
        
        # Parse vertex buffers
        offset, vertex_buffers = self._parse_vertex_buffers(offset, vb_descs)
        
        # Parse index buffers
        offset, index_buffers = self._parse_index_buffers(offset)
        
        # Parse and validate meshes
        offset = self._parse_and_validate_meshes(offset, vb_descs, vertex_buffers, index_buffers)
        
        # Parse bucket grids
        if offset < len(self.file_data):
            offset = self._parse_bucket_grids(offset, vertex_buffers, index_buffers)
        
        # Check if there's unexpected data at the end
        if offset < len(self.file_data):
            remaining = len(self.file_data) - offset
            if remaining > 100:  # More than 100 bytes is suspicious
                self.add_warning("FILE", f"Unexpected {remaining} bytes remaining at end of file", offset=offset)
    
    def _parse_sampler_defs(self, offset: int) -> int:
        """Parse sampler definitions"""
        if self.version >= 17:
            sampler_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            self.add_info("SAMPLERS", f"Sampler count: {sampler_count}")
            
            for i in range(sampler_count):
                sampler_index = struct.unpack('<i', self.file_data[offset:offset+4])[0]
                offset += 4
                name_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                sampler_name = self.file_data[offset:offset+name_len].decode('utf-8', errors='ignore')
                offset += name_len
                
                if name_len > 1000:
                    self.add_warning("SAMPLERS", f"Sampler {i} has unusually long name: {name_len} bytes")
        elif self.version >= 9:
            # Version 9-16 format
            name_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4 + name_len
            
            if self.version >= 11:
                name_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4 + name_len
        
        return offset
    
    def _parse_vertex_buffer_descriptions(self, offset: int) -> Tuple[int, List]:
        """Parse vertex buffer descriptions"""
        vb_desc_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
        offset += 4
        
        self.add_info("VERTEX_BUFFER_DESC", f"Vertex buffer description count: {vb_desc_count}")
        
        if vb_desc_count > 100:
            self.add_error("VERTEX_BUFFER_DESC", f"Unreasonable vertex buffer description count: {vb_desc_count}")
        
        vb_descs = []
        for i in range(vb_desc_count):
            usage = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            element_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            if element_count > 15:
                self.add_error("VERTEX_BUFFER_DESC", f"VB desc {i}: Invalid element count {element_count} (max 15)")
            
            elements = []
            current_elem_offset = 0
            for j in range(element_count):
                name = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                fmt = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                
                # Validate element name
                if name > 15:
                    self.add_error("VERTEX_BUFFER_DESC", f"VB desc {i}, element {j}: Invalid name {name} (max 15)")
                
                # Validate format
                if fmt > 12:
                    self.add_error("VERTEX_BUFFER_DESC", f"VB desc {i}, element {j}: Invalid format {fmt} (max 12)")
                
                # Calculate size
                elem_size = self._get_format_size(fmt)
                elements.append((name, fmt, current_elem_offset, elem_size))
                current_elem_offset += elem_size
            
            # Skip padding (unused elements)
            offset += 8 * (15 - element_count)
            
            vertex_stride = current_elem_offset
            vb_descs.append({
                'usage': usage,
                'elements': elements,
                'stride': vertex_stride
            })
            
            self.add_info("VERTEX_BUFFER_DESC", f"VB desc {i}: {element_count} elements, stride={vertex_stride} bytes")
        
        return offset, vb_descs
    
    def _get_format_size(self, fmt: int) -> int:
        """Get size in bytes for a vertex format"""
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
    
    def _parse_vertex_buffers(self, offset: int, vb_descs: List) -> Tuple[int, List]:
        """Parse vertex buffers"""
        vb_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
        offset += 4
        
        self.add_info("VERTEX_BUFFER", f"Vertex buffer count: {vb_count}")
        
        if vb_count > 100:
            self.add_error("VERTEX_BUFFER", f"Unreasonable vertex buffer count: {vb_count}")
        
        vertex_buffers = []
        for i in range(vb_count):
            if self.version >= 13:
                visibility = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
            
            buffer_size = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            if buffer_size > len(self.file_data):
                self.add_error("VERTEX_BUFFER", f"VB {i}: Buffer size {buffer_size} exceeds file size")
                break
            
            buffer_data = self.file_data[offset:offset+buffer_size]
            offset += buffer_size
            
            # Calculate vertex count if we have a description
            vertex_count = 0
            if i < len(vb_descs):
                stride = vb_descs[i]['stride']
                if stride > 0:
                    vertex_count = buffer_size // stride
                    expected_size = vertex_count * stride
                    if buffer_size != expected_size:
                        self.add_warning("VERTEX_BUFFER", 
                                       f"VB {i}: Buffer size {buffer_size} doesn't align with stride {stride} "
                                       f"(expected {expected_size}, {buffer_size - expected_size} bytes extra)")
            
            vertex_buffers.append({
                'index': i,
                'size': buffer_size,
                'data': buffer_data,
                'vertex_count': vertex_count,
                'stride': vb_descs[i]['stride'] if i < len(vb_descs) else 0
            })
            
            self.add_info("VERTEX_BUFFER", f"VB {i}: {buffer_size} bytes, {vertex_count} vertices")
        
        return offset, vertex_buffers
    
    def _parse_index_buffers(self, offset: int) -> Tuple[int, List]:
        """Parse index buffers"""
        ib_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
        offset += 4
        
        self.add_info("INDEX_BUFFER", f"Index buffer count: {ib_count}")
        
        if ib_count > 100:
            self.add_error("INDEX_BUFFER", f"Unreasonable index buffer count: {ib_count}")
        
        index_buffers = []
        for i in range(ib_count):
            if self.version >= 13:
                visibility = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
            
            buffer_size = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            if buffer_size > len(self.file_data):
                self.add_error("INDEX_BUFFER", f"IB {i}: Buffer size {buffer_size} exceeds file size")
                break
            
            buffer_data = self.file_data[offset:offset+buffer_size]
            offset += buffer_size
            
            # Determine format (U16 or U32)
            index_count_u16 = buffer_size // 2
            index_count_u32 = buffer_size // 4
            
            # Check for alignment
            is_u16_aligned = (buffer_size % 2 == 0)
            is_u32_aligned = (buffer_size % 4 == 0)
            
            if not is_u16_aligned:
                self.add_error("INDEX_BUFFER", f"IB {i}: Buffer size {buffer_size} not aligned to U16 or U32")
            
            # Default to U16 (most common)
            index_buffers.append({
                'index': i,
                'size': buffer_size,
                'data': buffer_data,
                'index_count_u16': index_count_u16,
                'index_count_u32': index_count_u32,
                'is_u16_aligned': is_u16_aligned,
                'is_u32_aligned': is_u32_aligned
            })
            
            self.add_info("INDEX_BUFFER", f"IB {i}: {buffer_size} bytes ({index_count_u16} U16 indices)")
        
        return offset, index_buffers
    
    def _parse_and_validate_meshes(self, offset: int, vb_descs: List, vertex_buffers: List, index_buffers: List) -> int:
        """Parse and validate meshes"""
        mesh_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
        offset += 4
        
        self.add_info("MESH", f"Mesh count: {mesh_count}")
        
        if mesh_count > 10000:
            self.add_error("MESH", f"Unreasonable mesh count: {mesh_count}")
        
        for mesh_idx in range(mesh_count):
            print(f"\n--- Validating Mesh {mesh_idx} ---")
            
            # Name (version <= 11)
            if self.version <= 11:
                name_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                mesh_name = self.file_data[offset:offset+name_len].decode('ascii', errors='ignore')
                offset += name_len
            else:
                mesh_name = f"Mesh_{mesh_idx}"
            
            # Vertex info
            vertex_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            vertex_decl_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            vertex_decl_id = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            self.add_info("MESH", f"Mesh {mesh_idx} ({mesh_name}): {vertex_count} vertices, {vertex_decl_count} vertex buffers", mesh_index=mesh_idx)
            
            # Validate vertex declaration
            if vertex_decl_id >= len(vb_descs):
                self.add_error("MESH", f"Mesh {mesh_idx}: Invalid vertex_decl_id {vertex_decl_id} (max {len(vb_descs)-1})", mesh_index=mesh_idx)
            
            if vertex_decl_count > 8:
                self.add_error("MESH", f"Mesh {mesh_idx}: Unreasonable vertex_decl_count {vertex_decl_count}", mesh_index=mesh_idx)
            
            # Read vertex buffer IDs
            vb_ids = []
            for j in range(vertex_decl_count):
                vb_id = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                vb_ids.append(vb_id)
                
                # Validate VB ID
                if vb_id >= len(vertex_buffers):
                    self.add_error("MESH", f"Mesh {mesh_idx}: Invalid vertex_buffer_id {vb_id} (max {len(vertex_buffers)-1})", mesh_index=mesh_idx)
                else:
                    # Check if vertex count matches
                    vb = vertex_buffers[vb_id]
                    if vb['vertex_count'] != vertex_count and vb['vertex_count'] > 0:
                        self.add_error("MESH", 
                                     f"Mesh {mesh_idx}: Vertex count mismatch - mesh claims {vertex_count} but VB {vb_id} has {vb['vertex_count']}",
                                     mesh_index=mesh_idx,
                                     expected=str(vertex_count),
                                     actual=str(vb['vertex_count']))
            
            # Index info
            index_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            index_buffer_id = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            self.add_info("MESH", f"Mesh {mesh_idx}: {index_count} indices, using IB {index_buffer_id}", mesh_index=mesh_idx)
            
            # Validate index buffer
            if index_buffer_id >= len(index_buffers):
                self.add_error("MESH", f"Mesh {mesh_idx}: Invalid index_buffer_id {index_buffer_id} (max {len(index_buffers)-1})", mesh_index=mesh_idx)
            else:
                ib = index_buffers[index_buffer_id]
                # Check if index count is reasonable
                if index_count > ib['index_count_u16']:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}: Index count {index_count} exceeds IB {index_buffer_id} capacity "
                                 f"({ib['index_count_u16']} U16 indices)",
                                 mesh_index=mesh_idx)
                
                # Validate indices are within vertex buffer bounds
                if index_count > 0 and vb_ids:
                    self._validate_indices(mesh_idx, ib['data'], index_count, vertex_count)
            
            # Visibility
            if self.version >= 13:
                visibility = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
            
            # Version 18+ unknown
            if self.version >= 18:
                unknown_v18 = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
            
            # Version 15+ visibility controller
            if self.version >= 15:
                visibility_controller = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
            
            # Primitives
            primitive_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
            offset += 4
            
            if primitive_count > 1000:
                self.add_warning("MESH", f"Mesh {mesh_idx}: Unusually high primitive count: {primitive_count}", mesh_index=mesh_idx)
            
            total_prim_indices = 0
            for prim_idx in range(primitive_count):
                prim_hash = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                
                material_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                material = self.file_data[offset:offset+material_len].decode('ascii', errors='ignore')
                offset += material_len
                
                start_index = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                prim_index_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                min_vertex = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                max_vertex = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
                
                total_prim_indices += prim_index_count
                
                # Validate primitive
                if start_index + prim_index_count > index_count:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}, Prim {prim_idx}: start_index ({start_index}) + index_count ({prim_index_count}) "
                                 f"= {start_index + prim_index_count} exceeds mesh index_count {index_count}",
                                 mesh_index=mesh_idx)
                
                if min_vertex >= vertex_count:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}, Prim {prim_idx}: min_vertex {min_vertex} >= vertex_count {vertex_count}",
                                 mesh_index=mesh_idx)
                
                if max_vertex >= vertex_count:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}, Prim {prim_idx}: max_vertex {max_vertex} >= vertex_count {vertex_count}",
                                 mesh_index=mesh_idx)
                
                if min_vertex > max_vertex:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}, Prim {prim_idx}: min_vertex {min_vertex} > max_vertex {max_vertex}",
                                 mesh_index=mesh_idx)
            
            # Check if total primitive indices match mesh index count
            if total_prim_indices != index_count:
                self.add_warning("MESH", 
                               f"Mesh {mesh_idx}: Total primitive indices ({total_prim_indices}) != mesh index_count ({index_count})",
                               mesh_index=mesh_idx)
            
            # Backface culling
            if self.version != 5:
                disable_backface = struct.unpack('<?', self.file_data[offset:offset+1])[0]
                offset += 1
            
            # Bounding box
            bbox_min = struct.unpack('<3f', self.file_data[offset:offset+12])
            offset += 12
            bbox_max = struct.unpack('<3f', self.file_data[offset:offset+12])
            offset += 12
            
            # Validate bounding box
            for axis_idx, axis_name in enumerate(['X', 'Y', 'Z']):
                if bbox_min[axis_idx] > bbox_max[axis_idx]:
                    self.add_error("MESH", 
                                 f"Mesh {mesh_idx}: Bounding box invalid - min_{axis_name} ({bbox_min[axis_idx]:.6f}) > "
                                 f"max_{axis_name} ({bbox_max[axis_idx]:.6f})",
                                 mesh_index=mesh_idx)
                
                # Check for extreme values
                for val, label in [(bbox_min[axis_idx], f"min_{axis_name}"), (bbox_max[axis_idx], f"max_{axis_name}")]:
                    if abs(val) > 1000000:
                        self.add_warning("MESH", 
                                       f"Mesh {mesh_idx}: Bounding box {label} has extreme value: {val:.6f}",
                                       mesh_index=mesh_idx)
                    
                    # Check for NaN or Inf
                    if val != val:  # NaN check
                        self.add_error("MESH", f"Mesh {mesh_idx}: Bounding box {label} is NaN", mesh_index=mesh_idx)
                    elif abs(val) == float('inf'):
                        self.add_error("MESH", f"Mesh {mesh_idx}: Bounding box {label} is Inf", mesh_index=mesh_idx)
            
            # Transform matrix
            transform = struct.unpack('<16f', self.file_data[offset:offset+64])
            offset += 64
            
            # Validate transform (check for NaN/Inf)
            for i, val in enumerate(transform):
                if val != val:  # NaN
                    self.add_error("MESH", f"Mesh {mesh_idx}: Transform matrix element {i} is NaN", mesh_index=mesh_idx)
                elif abs(val) == float('inf'):
                    self.add_error("MESH", f"Mesh {mesh_idx}: Transform matrix element {i} is Inf", mesh_index=mesh_idx)
            
            # Quality
            quality = struct.unpack('<B', self.file_data[offset:offset+1])[0]
            offset += 1
            
            if quality > 4:
                self.add_error("MESH", f"Mesh {mesh_idx}: Invalid quality value {quality} (max 4)", mesh_index=mesh_idx)
            
            # Version-specific fields
            if self.version >= 7 and self.version <= 12:
                visibility = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
            
            if self.version >= 11 and self.version < 14:
                render_flags = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
            elif self.version >= 14:
                layer_transition = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
                if self.version < 16:
                    render_flags = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                    offset += 1
                else:
                    render_flags = struct.unpack('<H', self.file_data[offset:offset+2])[0]
                    offset += 2
            
            # Light channels
            if self.version < 9:
                offset += 9 * 12  # Skip spherical harmonics
                offset = self._skip_light_channel(offset)
            else:
                offset = self._skip_light_channel(offset)  # Baked light
                offset = self._skip_light_channel(offset)  # Stationary light
                
                if self.version >= 12 and self.version < 17:
                    offset = self._skip_light_channel(offset)  # Baked paint
                
                if self.version >= 17:
                    # Texture overrides
                    override_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                    offset += 4
                    for _ in range(override_count):
                        override_index = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                        offset += 4
                        override_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                        offset += 4
                        offset += override_len
                    
                    # Baked paint scale and bias
                    offset += 16
        
        return offset
    
    def _validate_indices(self, mesh_idx: int, index_data: bytes, index_count: int, vertex_count: int):
        """Validate that all indices are within vertex buffer bounds"""
        # Assume U16 format (most common)
        for i in range(index_count):
            if i * 2 + 2 > len(index_data):
                break
            
            idx = struct.unpack('<H', index_data[i*2:i*2+2])[0]
            if idx >= vertex_count:
                self.add_error("MESH", 
                             f"Mesh {mesh_idx}: Index [{i}] = {idx} is out of bounds (vertex_count = {vertex_count})",
                             mesh_index=mesh_idx)
                # Only report first few out-of-bounds indices to avoid spam
                if i > 10:
                    self.add_warning("MESH", f"Mesh {mesh_idx}: Additional out-of-bounds indices not shown...", mesh_index=mesh_idx)
                    break
    
    def _skip_light_channel(self, offset: int) -> int:
        """Skip a light channel in the file"""
        tex_len = struct.unpack('<I', self.file_data[offset:offset+4])[0]
        offset += 4
        offset += tex_len
        offset += 16  # scale + bias (4 floats)
        return offset
    
    def _parse_bucket_grids(self, offset: int, vertex_buffers: List, index_buffers: List) -> int:
        """Parse bucket grids"""
        try:
            if self.version >= 15:
                grid_count = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                offset += 4
            else:
                grid_count = 1
            
            self.add_info("BUCKET_GRID", f"Bucket grid count: {grid_count}")
            
            for grid_idx in range(grid_count):
                if self.version >= 15:
                    path_hash = struct.unpack('<I', self.file_data[offset:offset+4])[0]
                    offset += 4
                
                if self.version >= 18:
                    unknown_float = struct.unpack('<f', self.file_data[offset:offset+4])[0]
                    offset += 4
                
                min_x, min_z, max_x, max_z = struct.unpack('<4f', self.file_data[offset:offset+16])
                offset += 16
                max_stickout_x, max_stickout_z = struct.unpack('<2f', self.file_data[offset:offset+8])
                offset += 8
                bucket_size_x, bucket_size_z = struct.unpack('<2f', self.file_data[offset:offset+8])
                offset += 8
                
                buckets_per_side = struct.unpack('<H', self.file_data[offset:offset+2])[0]
                offset += 2
                is_disabled = struct.unpack('<?', self.file_data[offset:offset+1])[0]
                offset += 1
                flags = struct.unpack('<B', self.file_data[offset:offset+1])[0]
                offset += 1
                
                vertex_count, index_count = struct.unpack('<2I', self.file_data[offset:offset+8])
                offset += 8
                
                self.add_info("BUCKET_GRID", 
                            f"Grid {grid_idx}: {buckets_per_side}x{buckets_per_side} buckets, "
                            f"{vertex_count} vertices, {index_count} indices, disabled={is_disabled}")
                
                if is_disabled:
                    continue
                
                # Validate bounds
                if min_x > max_x:
                    self.add_error("BUCKET_GRID", f"Grid {grid_idx}: min_x ({min_x}) > max_x ({max_x})")
                if min_z > max_z:
                    self.add_error("BUCKET_GRID", f"Grid {grid_idx}: min_z ({min_z}) > max_z ({max_z})")
                
                # Skip vertices
                offset += vertex_count * 12
                
                # Skip indices
                offset += index_count * 2
                
                # Skip buckets
                bucket_count = buckets_per_side * buckets_per_side
                offset += bucket_count * 20  # Each bucket is 20 bytes
                
                # Skip face visibility flags
                if flags & 1:
                    face_count = index_count // 3
                    offset += face_count
        
        except Exception as e:
            self.add_warning("BUCKET_GRID", f"Failed to parse bucket grids: {e}")
        
        return offset
    
    def print_report(self):
        """Print validation report"""
        print("\n" + "="*80)
        print("VALIDATION REPORT")
        print("="*80 + "\n")
        
        error_count = sum(1 for issue in self.issues if issue.severity == "ERROR")
        warning_count = sum(1 for issue in self.issues if issue.severity == "WARNING")
        info_count = sum(1 for issue in self.issues if issue.severity == "INFO")
        
        print(f"Total Issues: {len(self.issues)}")
        print(f"  Errors: {error_count}")
        print(f"  Warnings: {warning_count}")
        print(f"  Info: {info_count}\n")
        
        # Group by severity
        for severity in ["ERROR", "WARNING", "INFO"]:
            severity_issues = [i for i in self.issues if i.severity == severity]
            if not severity_issues:
                continue
            
            print(f"\n{severity}S ({len(severity_issues)}):")
            print("-" * 80)
            
            for issue in severity_issues:
                prefix = f"[{issue.category}]"
                if issue.mesh_index >= 0:
                    prefix += f" Mesh {issue.mesh_index}:"
                
                print(f"{prefix} {issue.message}")
                
                if issue.expected:
                    print(f"  Expected: {issue.expected}")
                if issue.actual:
                    print(f"  Actual: {issue.actual}")
                if issue.offset >= 0:
                    print(f"  Offset: 0x{issue.offset:08X}")
        
        print("\n" + "="*80)
        if error_count > 0:
            print("RESULT: VALIDATION FAILED - File has critical errors that likely cause crashes")
        elif warning_count > 0:
            print("RESULT: VALIDATION PASSED WITH WARNINGS - File may have issues")
        else:
            print("RESULT: VALIDATION PASSED - No issues detected")
        print("="*80 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_mapgeo.py <path_to_mapgeo_file>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    validator = MapgeoValidator(filepath)
    validator.validate()
    validator.print_report()
