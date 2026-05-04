"""
League Tools – Materials.bin Manager (Chunks + Particles)

Provides UI for managing:
  - mapContainer chunks: view, enable/disable, remove, add chunk references
  - MPC embedded items: view item counts per container, remove particles
    by class type or individually

Integrates with the project system (project_settings.loaded_materials_path)
and resolves hashes via community_hashes.
"""

import os
import json

import bpy
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy.props import (
    StringProperty, BoolProperty, IntProperty,
    CollectionProperty, EnumProperty,
)

from . import propertybin_parser
from . import community_hashes

# ============================================================================
# Constants
# ============================================================================

HASH_MAP_CONTAINER = 0xdde8c114
HASH_MPC           = 0xb25c0a3f
HASH_MAP_PARTICLE  = 0x1f1f50f2
HASH_VFX_DEF       = 0x45cd899f

MC_FIELD_CHUNKS   = "0x5e0e1da3"
MC_FIELD_GEO_PATH = "0xcc5e808a"


# ============================================================================
# Hash resolution helpers
# ============================================================================

def _resolve_hash(hash_str: str) -> str:
    """Resolve a hash string via community_hashes. Returns resolved name or ''."""
    if not hash_str or hash_str == "0x00000000":
        return ""
    return community_hashes.resolve(hash_str)


def _resolve_entry_hash(hash_str: str) -> str:
    """Resolve a path/entry hash."""
    if not hash_str:
        return ""
    return community_hashes.resolve_entry(hash_str) or community_hashes.resolve(hash_str)


def _resolve_type_hash(hash_str: str) -> str:
    """Resolve a type/class hash."""
    if not hash_str:
        return ""
    return community_hashes.resolve_type(hash_str) or community_hashes.resolve(hash_str)


def _display(hash_str: str, resolved: str) -> str:
    """Format a display string: 'ResolvedName' or '0x...' if unresolved."""
    if resolved:
        return resolved
    return hash_str


def _display_full(hash_str: str, resolved: str) -> str:
    """Format: 'ResolvedName (0x...)' or just '0x...' if unresolved."""
    if resolved:
        return f"{resolved} ({hash_str})"
    return hash_str


def _class_label(class_hash: str) -> str:
    """Human-readable label for an embedded item class, using hash resolution."""
    resolved = _resolve_type_hash(class_hash)
    if resolved:
        return resolved
    # Fallback to known names
    fallback = {
        "0x00000000": "Null/Link",
        "0x1f1f50f2": "MapParticle",
        "0x9aa5b4bc": "CharacterPlacement",
        "0xad65d8c4": "ObjectPlacement",
        "0x3c995caf": "SpawnPoint",
        "0xba138ae3": "ShopPlacement",
        "0xa844df61": "LightSource",
        "0xda9e5c0c": "AudioEmitter",
        "0x592ef6c3": "Decal",
        "0x091c0b1c": "CameraZone",
        "0xa783cfd5": "TriggerZone",
        "0xd178749c": "Grass",
        "0xeb997689": "WindSource",
        "0xf3726d48": "WaterRegion",
        "0xe64ff723": "RiverStrip",
        "0xd8f395a4": "FogRegion",
        "0x8a533844": "SoundPoint",
        "0x300333fc": "Barrier",
        "0x25e3f5d0": "PathNode",
    }
    return fallback.get(class_hash, class_hash)


def _type_hash_int(entry: dict) -> int:
    th = entry.get("type_hash", "0x0")
    if isinstance(th, str):
        return int(th, 16) if th.startswith("0x") else int(th)
    return int(th)


# ============================================================================
# PropertyGroups
# ============================================================================

class MATBIN_ChunkItem(PropertyGroup):
    """One chunk (key → MPC reference) in the mapContainer."""
    chunk_key: StringProperty(name="Chunk Key")
    chunk_key_name: StringProperty(name="Chunk Name")
    mpc_hash: StringProperty(name="MPC Hash")
    mpc_name: StringProperty(name="MPC Name")
    mpc_items: IntProperty(name="Items", default=0)
    particle_count: IntProperty(name="Particles", default=0)
    enabled: BoolProperty(name="Enabled", default=True)


class MATBIN_MPCItem(PropertyGroup):
    """One MapPlaceableContainer entry summary."""
    path_hash: StringProperty(name="Path Hash")
    path_name: StringProperty(name="Path Name")
    item_count: IntProperty(name="Items", default=0)
    particle_count: IntProperty(name="Particles", default=0)
    class_summary: StringProperty(name="Class Summary")
    chunk_key: StringProperty(name="Chunk Key")


class MATBIN_ParticleItem(PropertyGroup):
    """One embedded item inside an MPC."""
    pair_index: IntProperty(name="Pair Index")
    class_hash: StringProperty(name="Class Hash")
    class_label: StringProperty(name="Class Label")
    key_hash: StringProperty(name="Key Hash")
    key_name: StringProperty(name="Key Name")
    selected: BoolProperty(name="Selected", default=False)
    system_link: StringProperty(name="System Link")
    system_link_name: StringProperty(name="System Link Name")
    transform_x: StringProperty(name="X")
    transform_z: StringProperty(name="Z")


class MATBIN_ManagerSettings(PropertyGroup):
    filepath: StringProperty(
        name="Materials File",
        description="Path to .materials.bin file",
        subtype='FILE_PATH',
    )
    loaded: BoolProperty(default=False)
    raw_data_json: StringProperty(default="", options={'HIDDEN'})

    # Stats
    total_entries: IntProperty(default=0)
    total_chunks: IntProperty(default=0)
    total_mpcs: IntProperty(default=0)

    # Active indices
    active_chunk_index: IntProperty(default=0)
    active_mpc_index: IntProperty(default=0)

    # Collections
    chunks: CollectionProperty(type=MATBIN_ChunkItem)
    mpcs: CollectionProperty(type=MATBIN_MPCItem)
    particles: CollectionProperty(type=MATBIN_ParticleItem)

    # Filter
    particle_filter: EnumProperty(
        name="Show",
        items=[
            ('ALL', "All Items", "Show all embedded items"),
            ('PARTICLE', "Particles Only", "Show only MapParticle items"),
        ],
        default='ALL',
    )

    # Viewing state
    viewing_mpc_hash: StringProperty(default="")


# ============================================================================
# Helpers — populate UI collections from bin data
# ============================================================================

def _get_map_container(bin_data: dict):
    for e in bin_data.get("entries", []):
        if _type_hash_int(e) == HASH_MAP_CONTAINER:
            return e
    return None


def _get_chunks_pairs(mc_entry: dict) -> list:
    for f in mc_entry.get("fields", []):
        if f.get("name_hash") == MC_FIELD_CHUNKS:
            return f.get("pairs", [])
    return []


def _get_chunks_field(mc_entry: dict):
    for f in mc_entry.get("fields", []):
        if f.get("name_hash") == MC_FIELD_CHUNKS:
            return f
    return None


def _build_mpc_index(bin_data: dict) -> dict:
    idx = {}
    for e in bin_data.get("entries", []):
        if _type_hash_int(e) == HASH_MPC:
            idx[e.get("path_hash", "")] = e
    return idx


def _count_mpc_items(mpc_entry: dict) -> tuple:
    """Return (total_items, particle_count, class_summary_str)."""
    total = 0
    particles = 0
    classes = {}
    for f in mpc_entry.get("fields", []):
        if f.get("type") == 134:
            for p in f.get("pairs", []):
                total += 1
                v = p.get("value", {})
                ch = v.get("class_hash", "") if isinstance(v, dict) else ""
                classes[ch] = classes.get(ch, 0) + 1
                if ch == "0x1f1f50f2":
                    particles += 1
    summary_parts = []
    for ch, cnt in sorted(classes.items(), key=lambda x: -x[1]):
        if ch == "0x00000000":
            continue
        name = _class_label(ch)
        summary_parts.append(f"{name}: {cnt}")
    return total, particles, ", ".join(summary_parts)


def _populate_all(settings, bin_data: dict):
    """Populate chunks, MPCs, and stats from bin data."""
    settings.chunks.clear()
    settings.mpcs.clear()
    settings.particles.clear()
    settings.viewing_mpc_hash = ""

    mc = _get_map_container(bin_data)
    mpc_index = _build_mpc_index(bin_data)

    settings.total_entries = len(bin_data.get("entries", []))
    settings.total_mpcs = len(mpc_index)

    if mc:
        pairs = _get_chunks_pairs(mc)
        settings.total_chunks = len(pairs)

        for pair in pairs:
            key = pair.get("key", {})
            val = pair.get("value", {})
            kv = key.get("value", "") if isinstance(key, dict) else str(key)
            vv = val.get("value", "") if isinstance(val, dict) else str(val)

            item = settings.chunks.add()
            item.chunk_key = kv
            item.chunk_key_name = _resolve_hash(kv)
            item.mpc_hash = vv
            item.mpc_name = _resolve_entry_hash(vv)
            item.enabled = True

            mpc = mpc_index.get(vv)
            if mpc:
                total, particle_count, _ = _count_mpc_items(mpc)
                item.mpc_items = total
                item.particle_count = particle_count
            else:
                item.mpc_items = 0
                item.particle_count = 0

    for ph, mpc in mpc_index.items():
        total, particle_count, summary = _count_mpc_items(mpc)
        mi = settings.mpcs.add()
        mi.path_hash = ph
        mi.path_name = _resolve_entry_hash(ph)
        mi.item_count = total
        mi.particle_count = particle_count
        mi.class_summary = summary
        for ci in settings.chunks:
            if ci.mpc_hash == ph:
                mi.chunk_key = ci.chunk_key
                break

    settings.loaded = True


def _populate_particles(settings, bin_data: dict, mpc_hash: str):
    """Populate the particles list for a specific MPC."""
    settings.particles.clear()
    settings.viewing_mpc_hash = mpc_hash
    mpc_index = _build_mpc_index(bin_data)
    mpc = mpc_index.get(mpc_hash)
    if not mpc:
        return

    show_filter = settings.particle_filter
    for f in mpc.get("fields", []):
        if f.get("type") != 134:
            continue
        for i, p in enumerate(f.get("pairs", [])):
            v = p.get("value", {})
            ch = v.get("class_hash", "") if isinstance(v, dict) else ""

            if show_filter == 'PARTICLE' and ch != "0x1f1f50f2":
                continue

            key = p.get("key", {})
            kv = key.get("value", "") if isinstance(key, dict) else str(key)

            pi = settings.particles.add()
            pi.pair_index = i
            pi.class_hash = ch
            pi.class_label = _class_label(ch)
            pi.key_hash = kv
            pi.key_name = _resolve_entry_hash(kv)

            flds = v.get("fields") if isinstance(v, dict) else None
            if flds:
                for sf in flds:
                    nh = sf.get("name_hash", "")
                    if nh == "0x491e0a9c":
                        link_val = str(sf.get("value", ""))
                        pi.system_link = link_val
                        pi.system_link_name = _resolve_entry_hash(link_val)
                    elif nh == "0xe1ad931b":
                        val_list = sf.get("value", [])
                        if isinstance(val_list, list) and len(val_list) >= 16:
                            pi.transform_x = f"{val_list[12]:.1f}"
                            pi.transform_z = f"{val_list[14]:.1f}"


def _load_bin_data(path: str, settings) -> str:
    """Parse a materials.bin and populate the manager. Returns error string or ''."""
    if not path or not os.path.isfile(path):
        return "File not found"
    try:
        bin_data = propertybin_parser.parse_bin(path)
    except Exception as e:
        return f"Parse failed: {e}"

    # Ensure hashes are loaded for resolution
    try:
        community_hashes.load_cached_hashes("bin")
        community_hashes.compute_custom_hashes(bin_data)
    except Exception:
        pass

    settings.filepath = path
    settings.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
    _populate_all(settings, bin_data)
    return ""


# ============================================================================
# UILists
# ============================================================================

class MATBIN_UL_chunk_list(UIList):
    bl_idname = "MATBIN_UL_chunk_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")

            # Chunk key — resolved or raw
            key_text = item.chunk_key_name if item.chunk_key_name else item.chunk_key
            sub = row.row()
            sub.scale_x = 0.8
            sub.label(text=key_text)

            # MPC — resolved or raw
            mpc_text = item.mpc_name if item.mpc_name else item.mpc_hash
            # Truncate long resolved paths to last segment
            if "/" in mpc_text:
                mpc_text = "…/" + mpc_text.rsplit("/", 1)[-1]
            sub2 = row.row()
            sub2.scale_x = 1.4
            sub2.label(text=mpc_text)

            # Item count
            sub3 = row.row()
            sub3.alignment = 'RIGHT'
            sub3.scale_x = 0.4
            count_text = str(item.mpc_items)
            if item.particle_count > 0:
                count_text += f" ({item.particle_count}p)"
            sub3.label(text=count_text)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.chunk_key_name or item.chunk_key)


class MATBIN_UL_particle_list(UIList):
    bl_idname = "MATBIN_UL_particle_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "selected", text="")

            icon_type = 'PARTICLES' if item.class_hash == "0x1f1f50f2" else 'OUTLINER_OB_EMPTY'
            sub = row.row()
            sub.scale_x = 0.6
            sub.label(text=item.class_label, icon=icon_type)

            # Key or system link — prefer resolved names
            detail = ""
            if item.system_link_name:
                detail = item.system_link_name
            elif item.system_link:
                detail = item.system_link
            elif item.key_name:
                detail = item.key_name
            elif item.key_hash:
                detail = item.key_hash
            if detail:
                # Truncate long paths
                if "/" in detail:
                    detail = "…/" + detail.rsplit("/", 1)[-1]
                sub2 = row.row()
                sub2.scale_x = 1.4
                sub2.label(text=detail)

            if item.transform_x:
                sub3 = row.row()
                sub3.alignment = 'RIGHT'
                sub3.scale_x = 0.4
                sub3.label(text=f"({item.transform_x}, {item.transform_z})")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.class_label)


# ============================================================================
# Operators — File I/O
# ============================================================================

class MATBIN_OT_load_from_project(Operator):
    """Load the materials.bin from the currently loaded project"""
    bl_idname = "matbin.load_from_project"
    bl_label = "Load from Project"

    @classmethod
    def poll(cls, context):
        ps = getattr(context.scene, "project_settings", None)
        if not ps:
            return False
        path = ps.loaded_materials_path
        return bool(path) and os.path.isfile(bpy.path.abspath(path))

    def execute(self, context):
        ps = context.scene.project_settings
        path = bpy.path.abspath(ps.loaded_materials_path)
        s = context.scene.matbin_manager

        err = _load_bin_data(path, s)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        name = os.path.basename(path)
        self.report({'INFO'}, f"Loaded {name}: {s.total_entries} entries, {s.total_chunks} chunks, {s.total_mpcs} MPCs")
        return {'FINISHED'}


class MATBIN_OT_load(Operator):
    """Load a materials.bin file for editing"""
    bl_idname = "matbin.load"
    bl_label = "Load Materials.bin"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        s = context.scene.matbin_manager
        err = _load_bin_data(self.filepath, s)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        name = os.path.basename(self.filepath)
        self.report({'INFO'}, f"Loaded {name}: {s.total_entries} entries, {s.total_chunks} chunks, {s.total_mpcs} MPCs")
        return {'FINISHED'}


class MATBIN_OT_reload(Operator):
    """Reload the current file from disk (discards unsaved changes)"""
    bl_idname = "matbin.reload"
    bl_label = "Reload"

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.filepath:
            self.report({'ERROR'}, "No file loaded")
            return {'CANCELLED'}

        path = bpy.path.abspath(s.filepath)
        err = _load_bin_data(path, s)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        self.report({'INFO'}, f"Reloaded {os.path.basename(path)}")
        return {'FINISHED'}


class MATBIN_OT_save(Operator):
    """Save changes back to materials.bin (creates .bak backup)"""
    bl_idname = "matbin.save"
    bl_label = "Save Materials.bin"

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json or not s.filepath:
            self.report({'ERROR'}, "No file loaded")
            return {'CANCELLED'}

        path = bpy.path.abspath(s.filepath)
        bin_data = json.loads(s.raw_data_json)

        # Apply chunk enable/disable state
        mc = _get_map_container(bin_data)
        if mc:
            chunks_field = _get_chunks_field(mc)
            if chunks_field:
                old_pairs = chunks_field.get("pairs", [])
                enabled_keys = {ci.chunk_key for ci in s.chunks if ci.enabled}
                new_pairs = []
                for pair in old_pairs:
                    key = pair.get("key", {})
                    kv = key.get("value", "") if isinstance(key, dict) else str(key)
                    if kv in enabled_keys:
                        new_pairs.append(pair)
                chunks_field["pairs"] = new_pairs

        # Create backup
        if os.path.isfile(path):
            bak = path + ".bak"
            if not os.path.isfile(bak):
                import shutil
                shutil.copy2(path, bak)

        bin_data["entry_count"] = len(bin_data.get("entries", []))
        propertybin_parser.write_bin(bin_data, path)

        # Reload to reflect actual state
        err = _load_bin_data(path, s)
        if err:
            self.report({'WARNING'}, f"Saved but reload failed: {err}")
            return {'FINISHED'}

        self.report({'INFO'}, f"Saved {os.path.basename(path)}")
        return {'FINISHED'}


class MATBIN_OT_save_as(Operator):
    """Save materials.bin to a new file"""
    bl_idname = "matbin.save_as"
    bl_label = "Save As"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.materials.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        s = context.scene.matbin_manager
        if s.filepath:
            self.filepath = bpy.path.abspath(s.filepath)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json:
            self.report({'ERROR'}, "No file loaded")
            return {'CANCELLED'}

        bin_data = json.loads(s.raw_data_json)

        # Apply chunk enable/disable state
        mc = _get_map_container(bin_data)
        if mc:
            chunks_field = _get_chunks_field(mc)
            if chunks_field:
                old_pairs = chunks_field.get("pairs", [])
                enabled_keys = {ci.chunk_key for ci in s.chunks if ci.enabled}
                chunks_field["pairs"] = [
                    p for p in old_pairs
                    if (p.get("key", {}).get("value", "") if isinstance(p.get("key"), dict) else str(p.get("key", ""))) in enabled_keys
                ]

        bin_data["entry_count"] = len(bin_data.get("entries", []))
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        propertybin_parser.write_bin(bin_data, self.filepath)

        self.report({'INFO'}, f"Saved as {os.path.basename(self.filepath)}")
        return {'FINISHED'}


# ============================================================================
# Operators — Chunk Management
# ============================================================================

class MATBIN_OT_view_chunk_mpc(Operator):
    """View the MPC contents for the selected chunk"""
    bl_idname = "matbin.view_chunk_mpc"
    bl_label = "View MPC Contents"

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json:
            return {'CANCELLED'}

        idx = s.active_chunk_index
        if idx < 0 or idx >= len(s.chunks):
            return {'CANCELLED'}

        chunk = s.chunks[idx]
        bin_data = json.loads(s.raw_data_json)
        _populate_particles(s, bin_data, chunk.mpc_hash)

        count = len(s.particles)
        mpc_label = chunk.mpc_name or chunk.mpc_hash
        self.report({'INFO'}, f"{mpc_label}: {count} items loaded")
        return {'FINISHED'}


class MATBIN_OT_remove_chunk(Operator):
    """Remove the selected chunk from mapContainer and its MPC entry"""
    bl_idname = "matbin.remove_chunk"
    bl_label = "Remove Chunk + MPC"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json:
            return {'CANCELLED'}

        idx = s.active_chunk_index
        if idx < 0 or idx >= len(s.chunks):
            return {'CANCELLED'}

        chunk = s.chunks[idx]
        bin_data = json.loads(s.raw_data_json)

        mc = _get_map_container(bin_data)
        if mc:
            chunks_field = _get_chunks_field(mc)
            if chunks_field:
                pairs = chunks_field.get("pairs", [])
                chunks_field["pairs"] = [
                    p for p in pairs
                    if (p.get("key", {}).get("value", "") if isinstance(p.get("key"), dict) else "") != chunk.chunk_key
                ]

        mpc_hash = chunk.mpc_hash
        bin_data["entries"] = [
            e for e in bin_data.get("entries", [])
            if not (e.get("path_hash") == mpc_hash and _type_hash_int(e) == HASH_MPC)
        ]
        bin_data["entry_count"] = len(bin_data["entries"])

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)

        label = chunk.chunk_key_name or chunk.chunk_key
        self.report({'INFO'}, f"Removed chunk {label}")
        return {'FINISHED'}


class MATBIN_OT_enable_all_chunks(Operator):
    """Enable all chunks"""
    bl_idname = "matbin.enable_all_chunks"
    bl_label = "Enable All"

    def execute(self, context):
        for ci in context.scene.matbin_manager.chunks:
            ci.enabled = True
        return {'FINISHED'}


class MATBIN_OT_disable_all_chunks(Operator):
    """Disable all chunks"""
    bl_idname = "matbin.disable_all_chunks"
    bl_label = "Disable All"

    def execute(self, context):
        for ci in context.scene.matbin_manager.chunks:
            ci.enabled = False
        return {'FINISHED'}


class MATBIN_OT_add_chunk(Operator):
    """Add a new chunk pointing to an existing MPC entry"""
    bl_idname = "matbin.add_chunk"
    bl_label = "Add Chunk"
    bl_options = {'REGISTER', 'UNDO'}

    chunk_key: StringProperty(
        name="Chunk Key Hash",
        description="Hash for the new chunk key (e.g. 0xABCD1234)",
    )
    mpc_hash: StringProperty(
        name="MPC Path Hash",
        description="Path hash of the MPC entry to reference",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json:
            return {'CANCELLED'}

        key = self.chunk_key.strip()
        mpc = self.mpc_hash.strip()
        if not key or not mpc:
            self.report({'ERROR'}, "Both chunk key and MPC hash are required")
            return {'CANCELLED'}

        bin_data = json.loads(s.raw_data_json)
        mc = _get_map_container(bin_data)
        if not mc:
            self.report({'ERROR'}, "No mapContainer found")
            return {'CANCELLED'}

        chunks_field = _get_chunks_field(mc)
        if not chunks_field:
            self.report({'ERROR'}, "No chunks field in mapContainer")
            return {'CANCELLED'}

        for pair in chunks_field.get("pairs", []):
            pk = pair.get("key", {})
            kv = pk.get("value", "") if isinstance(pk, dict) else str(pk)
            if kv == key:
                self.report({'ERROR'}, f"Chunk key {key} already exists")
                return {'CANCELLED'}

        new_pair = {
            "key": {"type": 17, "value": key},
            "value": {"type": 17, "value": mpc},
        }
        chunks_field.setdefault("pairs", []).append(new_pair)

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)

        self.report({'INFO'}, f"Added chunk {key} → {mpc}")
        return {'FINISHED'}


# ============================================================================
# Operators — Particle / Item Management
# ============================================================================

class MATBIN_OT_remove_selected_items(Operator):
    """Remove selected items from the current MPC"""
    bl_idname = "matbin.remove_selected_items"
    bl_label = "Remove Selected Items"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json or not s.viewing_mpc_hash:
            return {'CANCELLED'}

        indices_to_remove = {pi.pair_index for pi in s.particles if pi.selected}
        if not indices_to_remove:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}

        mpc_hash = s.viewing_mpc_hash
        bin_data = json.loads(s.raw_data_json)
        mpc_index = _build_mpc_index(bin_data)
        mpc = mpc_index.get(mpc_hash)
        if not mpc:
            self.report({'ERROR'}, "MPC not found")
            return {'CANCELLED'}

        removed = 0
        for f in mpc.get("fields", []):
            if f.get("type") != 134:
                continue
            pairs = f.get("pairs", [])
            new_pairs = [p for i, p in enumerate(pairs) if i not in indices_to_remove]
            removed = len(pairs) - len(new_pairs)
            f["pairs"] = new_pairs

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)
        _populate_particles(s, bin_data, mpc_hash)

        self.report({'INFO'}, f"Removed {removed} items")
        return {'FINISHED'}


class MATBIN_OT_remove_all_particles(Operator):
    """Remove all MapParticle items from the current MPC"""
    bl_idname = "matbin.remove_all_particles"
    bl_label = "Remove All Particles from MPC"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json or not s.viewing_mpc_hash:
            return {'CANCELLED'}

        mpc_hash = s.viewing_mpc_hash
        bin_data = json.loads(s.raw_data_json)
        mpc_index = _build_mpc_index(bin_data)
        mpc = mpc_index.get(mpc_hash)
        if not mpc:
            return {'CANCELLED'}

        removed = 0
        for f in mpc.get("fields", []):
            if f.get("type") != 134:
                continue
            pairs = f.get("pairs", [])
            new_pairs = [
                p for p in pairs
                if not (isinstance(p.get("value"), dict)
                        and p["value"].get("class_hash") == "0x1f1f50f2")
            ]
            removed = len(pairs) - len(new_pairs)
            f["pairs"] = new_pairs

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)
        _populate_particles(s, bin_data, mpc_hash)

        self.report({'INFO'}, f"Removed {removed} particles")
        return {'FINISHED'}


class MATBIN_OT_remove_particles_all_mpcs(Operator):
    """Remove all MapParticle items from ALL MPCs in the file"""
    bl_idname = "matbin.remove_particles_all_mpcs"
    bl_label = "Remove All Particles (All MPCs)"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json:
            return {'CANCELLED'}

        bin_data = json.loads(s.raw_data_json)
        total_removed = 0

        for e in bin_data.get("entries", []):
            if _type_hash_int(e) != HASH_MPC:
                continue
            for f in e.get("fields", []):
                if f.get("type") != 134:
                    continue
                pairs = f.get("pairs", [])
                new_pairs = [
                    p for p in pairs
                    if not (isinstance(p.get("value"), dict)
                            and p["value"].get("class_hash") == "0x1f1f50f2")
                ]
                total_removed += len(pairs) - len(new_pairs)
                f["pairs"] = new_pairs

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)

        self.report({'INFO'}, f"Removed {total_removed} particles from all MPCs")
        return {'FINISHED'}


class MATBIN_OT_select_all_items(Operator):
    """Select all visible items"""
    bl_idname = "matbin.select_all_items"
    bl_label = "Select All"

    def execute(self, context):
        for pi in context.scene.matbin_manager.particles:
            pi.selected = True
        return {'FINISHED'}


class MATBIN_OT_select_none_items(Operator):
    """Deselect all items"""
    bl_idname = "matbin.select_none_items"
    bl_label = "Select None"

    def execute(self, context):
        for pi in context.scene.matbin_manager.particles:
            pi.selected = False
        return {'FINISHED'}


class MATBIN_OT_select_by_class(Operator):
    """Select all items of a specific class type"""
    bl_idname = "matbin.select_by_class"
    bl_label = "Select by Type"

    class_hash: StringProperty(name="Class Hash")

    def execute(self, context):
        count = 0
        for pi in context.scene.matbin_manager.particles:
            if pi.class_hash == self.class_hash:
                pi.selected = True
                count += 1
        label = _class_label(self.class_hash)
        self.report({'INFO'}, f"Selected {count} {label} items")
        return {'FINISHED'}


class MATBIN_OT_remove_by_class(Operator):
    """Remove all items of a specific class type from the current MPC"""
    bl_idname = "matbin.remove_by_class"
    bl_label = "Remove by Type"
    bl_options = {'REGISTER', 'UNDO'}

    class_hash: StringProperty(name="Class Hash")

    def execute(self, context):
        s = context.scene.matbin_manager
        if not s.raw_data_json or not s.viewing_mpc_hash:
            return {'CANCELLED'}

        mpc_hash = s.viewing_mpc_hash
        bin_data = json.loads(s.raw_data_json)
        mpc_index = _build_mpc_index(bin_data)
        mpc = mpc_index.get(mpc_hash)
        if not mpc:
            return {'CANCELLED'}

        target_class = self.class_hash
        removed = 0
        for f in mpc.get("fields", []):
            if f.get("type") != 134:
                continue
            pairs = f.get("pairs", [])
            new_pairs = [
                p for p in pairs
                if not (isinstance(p.get("value"), dict)
                        and p["value"].get("class_hash") == target_class)
            ]
            removed = len(pairs) - len(new_pairs)
            f["pairs"] = new_pairs

        s.raw_data_json = json.dumps(bin_data, ensure_ascii=False, default=str)
        _populate_all(s, bin_data)
        _populate_particles(s, bin_data, mpc_hash)

        label = _class_label(target_class)
        self.report({'INFO'}, f"Removed {removed} {label} items")
        return {'FINISHED'}


# ============================================================================
# Panels
# ============================================================================

class VIEW3D_PT_matbin_manager(Panel):
    """Materials.bin Manager — Chunks & Particles"""
    bl_label = "Materials.bin Manager"
    bl_idname = "VIEW3D_PT_matbin_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_order = 82
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.matbin_manager
        ps = getattr(context.scene, "project_settings", None)

        if s.loaded:
            # ── Loaded state ──
            box = layout.box()
            row = box.row(align=True)
            row.label(text=os.path.basename(bpy.path.abspath(s.filepath)), icon='CHECKMARK')
            row.operator("matbin.reload", text="", icon='FILE_REFRESH')
            row.operator("matbin.load", text="", icon='FILE_FOLDER')

            row = box.row(align=True)
            row.label(text=f"{s.total_entries} entries  |  {s.total_chunks} chunks  |  {s.total_mpcs} MPCs")

            row = box.row(align=True)
            row.operator("matbin.save", text="Save", icon='FILE_TICK')
            row.operator("matbin.save_as", text="Save As", icon='FILE_NEW')
        else:
            # ── Not loaded — show project button if available ──
            box = layout.box()
            box.label(text="Materials.bin File", icon='FILE')

            if ps and ps.loaded_materials_path and os.path.isfile(bpy.path.abspath(ps.loaded_materials_path)):
                name = os.path.basename(bpy.path.abspath(ps.loaded_materials_path))
                box.operator("matbin.load_from_project", text=f"Load from Project ({name})", icon='LINKED')

            box.operator("matbin.load", text="Browse...", icon='FILE_FOLDER')


class VIEW3D_PT_matbin_chunks(Panel):
    """Chunk Manager sub-panel"""
    bl_label = "Chunks"
    bl_idname = "VIEW3D_PT_matbin_chunks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_parent_id = "VIEW3D_PT_matbin_manager"

    @classmethod
    def poll(cls, context):
        return context.scene.matbin_manager.loaded

    def draw(self, context):
        layout = self.layout
        s = context.scene.matbin_manager

        layout.label(text=f"{s.total_chunks} chunks in mapContainer", icon='MESH_GRID')

        layout.template_list(
            "MATBIN_UL_chunk_list", "",
            s, "chunks",
            s, "active_chunk_index",
            rows=6,
        )

        # Actions
        row = layout.row(align=True)
        row.operator("matbin.enable_all_chunks", text="Enable All", icon='CHECKBOX_HLT')
        row.operator("matbin.disable_all_chunks", text="Disable All", icon='CHECKBOX_DEHLT')

        row = layout.row(align=True)
        row.operator("matbin.view_chunk_mpc", text="View Contents", icon='VIEWZOOM')
        row.operator("matbin.remove_chunk", text="Remove", icon='TRASH')

        layout.operator("matbin.add_chunk", text="Add Chunk", icon='ADD')

        # Selected chunk details
        if 0 <= s.active_chunk_index < len(s.chunks):
            chunk = s.chunks[s.active_chunk_index]
            box = layout.box()

            key_label = _display_full(chunk.chunk_key, chunk.chunk_key_name)
            mpc_label = _display_full(chunk.mpc_hash, chunk.mpc_name)

            box.label(text=f"Key: {key_label}", icon='KEY_HLT')
            box.label(text=f"MPC: {mpc_label}")
            box.label(text=f"Items: {chunk.mpc_items}  |  Particles: {chunk.particle_count}")
            state = "Enabled" if chunk.enabled else "Disabled"
            box.label(text=f"State: {state}", icon='CHECKBOX_HLT' if chunk.enabled else 'CHECKBOX_DEHLT')


class VIEW3D_PT_matbin_particles(Panel):
    """Particle / Item Manager sub-panel"""
    bl_label = "MPC Items"
    bl_idname = "VIEW3D_PT_matbin_particles"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "League Tools"
    bl_parent_id = "VIEW3D_PT_matbin_manager"

    @classmethod
    def poll(cls, context):
        return context.scene.matbin_manager.loaded

    def draw(self, context):
        layout = self.layout
        s = context.scene.matbin_manager

        # Filter
        row = layout.row(align=True)
        row.prop(s, "particle_filter", expand=True)

        if not s.particles:
            layout.label(text="Select a chunk and click 'View Contents'", icon='INFO')
            return

        # Current MPC info
        mpc_label = s.viewing_mpc_hash
        resolved_mpc = _resolve_entry_hash(s.viewing_mpc_hash)
        if resolved_mpc:
            mpc_label = resolved_mpc
        layout.label(text=f"{mpc_label} ({len(s.particles)} items)", icon='OUTLINER_OB_GROUP_INSTANCE')

        # Item list
        layout.template_list(
            "MATBIN_UL_particle_list", "",
            s, "particles",
            s, "active_mpc_index",
            rows=8,
        )

        # Selection
        row = layout.row(align=True)
        row.operator("matbin.select_all_items", text="Select All", icon='CHECKBOX_HLT')
        row.operator("matbin.select_none_items", text="Select None", icon='CHECKBOX_DEHLT')

        # Class type breakdown
        class_types = {}
        for pi in s.particles:
            if pi.class_hash and pi.class_hash != "0x00000000":
                class_types[pi.class_hash] = class_types.get(pi.class_hash, 0) + 1

        if class_types:
            box = layout.box()
            box.label(text="Select / Remove by Type:", icon='FILTER')
            for ch, cnt in sorted(class_types.items(), key=lambda x: -x[1]):
                label = _class_label(ch)
                row = box.row(align=True)
                row.label(text=f"{label} ({cnt})")
                op = row.operator("matbin.select_by_class", text="", icon='CHECKBOX_HLT')
                op.class_hash = ch
                op = row.operator("matbin.remove_by_class", text="", icon='TRASH')
                op.class_hash = ch

        # Remove actions
        layout.separator()
        selected_count = sum(1 for pi in s.particles if pi.selected)
        row = layout.row(align=True)
        row.operator("matbin.remove_selected_items", text=f"Remove Selected ({selected_count})", icon='X')

        layout.separator()
        row = layout.row()
        row.alert = True
        row.operator("matbin.remove_all_particles", text="Remove All Particles (Current MPC)", icon='PARTICLES')

        row = layout.row()
        row.alert = True
        row.operator("matbin.remove_particles_all_mpcs", text="Remove ALL Particles (Entire File)", icon='ERROR')


# ============================================================================
# Registration
# ============================================================================

_classes = [
    MATBIN_ChunkItem,
    MATBIN_MPCItem,
    MATBIN_ParticleItem,
    MATBIN_ManagerSettings,
    MATBIN_UL_chunk_list,
    MATBIN_UL_particle_list,
    MATBIN_OT_load_from_project,
    MATBIN_OT_load,
    MATBIN_OT_reload,
    MATBIN_OT_save,
    MATBIN_OT_save_as,
    MATBIN_OT_view_chunk_mpc,
    MATBIN_OT_remove_chunk,
    MATBIN_OT_enable_all_chunks,
    MATBIN_OT_disable_all_chunks,
    MATBIN_OT_add_chunk,
    MATBIN_OT_remove_selected_items,
    MATBIN_OT_remove_all_particles,
    MATBIN_OT_remove_particles_all_mpcs,
    MATBIN_OT_select_all_items,
    MATBIN_OT_select_none_items,
    MATBIN_OT_select_by_class,
    MATBIN_OT_remove_by_class,
    VIEW3D_PT_matbin_manager,
    VIEW3D_PT_matbin_chunks,
    VIEW3D_PT_matbin_particles,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.matbin_manager = bpy.props.PointerProperty(type=MATBIN_ManagerSettings)
    print("[Materials.bin Manager] Registered")


def unregister():
    del bpy.types.Scene.matbin_manager
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    print("[Materials.bin Manager] Unregistered")
