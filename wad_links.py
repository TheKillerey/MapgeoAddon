"""
WAD chunk links (PropertyBin type 18, "file" / WadChunkLink).

Since League patch 16.17 Riot stores asset references in .bin files (for
example ``StaticMaterialShaderSamplerDef.texturePath``) as a 64-bit WAD chunk
link instead of a String.  The value is ``xxh64(lowercased path)`` - exactly the
hash the WAD table of contents uses for that file - so it identifies the chunk
even when no hash dictionary can name it.

The add-on's material code works with human-readable paths.  This module is the
single place that converts between the two forms:

* ``link_to_text(value)``  - type-18 value -> path (or "0x%016x" when unknown)
* ``text_to_link(text)``   - path or "0x%016x" -> type-18 value ("0x%016x")
* ``find_file_for_link()`` - locate the file on disk for a link, by indexing the
  asset folders (``assets/...`` relative paths and ``raw/<hash>.<ext>``)

Conventions:
* An unresolvable hash stays ``0x`` + 16 hex digits and round-trips unchanged.
* The WIRE TYPE of an existing field is never changed: a type-18 field is
  written back as type 18 (hash of the lowercased path), a String stays String.

Pure Python (no bpy) so the format parsers can import it outside Blender.
"""

import os
import re
import struct
import time

# ============================================================================
# XXHash64 (pure Python; Blender's bundled Python has no xxhash package)
# ============================================================================

_XXHASH64_PRIME1 = 0x9E3779B185EBCA87
_XXHASH64_PRIME2 = 0xC2B2AE3D27D4EB4F
_XXHASH64_PRIME3 = 0x165667B19E3779F9
_XXHASH64_PRIME4 = 0x85EBCA77C2B2AE63
_XXHASH64_PRIME5 = 0x27D4EB2F165667C5
_U64 = 0xFFFFFFFFFFFFFFFF


def _rotl64(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _U64


def _round64(acc: int, inp: int) -> int:
    acc = (acc + inp * _XXHASH64_PRIME2) & _U64
    acc = _rotl64(acc, 31)
    acc = (acc * _XXHASH64_PRIME1) & _U64
    return acc


def _merge_round64(acc: int, val: int) -> int:
    val = _round64(0, val)
    acc = (acc ^ val) & _U64
    acc = (acc * _XXHASH64_PRIME1 + _XXHASH64_PRIME4) & _U64
    return acc


def xxhash64(data: bytes, seed: int = 0) -> int:
    """Compute XXHash64 of bytes with optional seed. Returns u64."""
    length = len(data)
    idx = 0

    if length >= 32:
        v1 = (seed + _XXHASH64_PRIME1 + _XXHASH64_PRIME2) & _U64
        v2 = (seed + _XXHASH64_PRIME2) & _U64
        v3 = seed & _U64
        v4 = (seed - _XXHASH64_PRIME1) & _U64

        while idx <= length - 32:
            k1, k2, k3, k4 = struct.unpack_from('<4Q', data, idx)
            v1 = _round64(v1, k1)
            v2 = _round64(v2, k2)
            v3 = _round64(v3, k3)
            v4 = _round64(v4, k4)
            idx += 32

        h64 = (_rotl64(v1, 1) + _rotl64(v2, 7) + _rotl64(v3, 12) + _rotl64(v4, 18)) & _U64
        h64 = _merge_round64(h64, v1)
        h64 = _merge_round64(h64, v2)
        h64 = _merge_round64(h64, v3)
        h64 = _merge_round64(h64, v4)
    else:
        h64 = (seed + _XXHASH64_PRIME5) & _U64

    h64 = (h64 + length) & _U64

    while idx <= length - 8:
        k1 = struct.unpack_from('<Q', data, idx)[0]
        k1 = (k1 * _XXHASH64_PRIME2) & _U64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * _XXHASH64_PRIME1) & _U64
        h64 = (h64 ^ k1) & _U64
        h64 = (_rotl64(h64, 27) * _XXHASH64_PRIME1 + _XXHASH64_PRIME4) & _U64
        idx += 8

    if idx <= length - 4:
        k1 = struct.unpack_from('<I', data, idx)[0]
        h64 = (h64 ^ (k1 * _XXHASH64_PRIME1)) & _U64
        h64 = (_rotl64(h64, 23) * _XXHASH64_PRIME2 + _XXHASH64_PRIME3) & _U64
        idx += 4

    while idx < length:
        h64 = (h64 ^ (data[idx] * _XXHASH64_PRIME5)) & _U64
        h64 = (_rotl64(h64, 11) * _XXHASH64_PRIME1) & _U64
        idx += 1

    h64 = (h64 ^ (h64 >> 33)) & _U64
    h64 = (h64 * _XXHASH64_PRIME2) & _U64
    h64 = (h64 ^ (h64 >> 29)) & _U64
    h64 = (h64 * _XXHASH64_PRIME3) & _U64
    h64 = (h64 ^ (h64 >> 32)) & _U64
    return h64


def xxhash64_path(path: str) -> int:
    """XXHash64 of a League file path (lowercased, forward slashes) = WAD chunk hash."""
    return xxhash64(path.lower().replace('\\', '/').encode('utf-8'))


# ============================================================================
# Link value helpers
# ============================================================================

TYPE_FILE = 18      # PropertyBin WadChunkLink
TYPE_STRING = 16

# Wire type for a texturePath field the add-on CREATES (no original to copy the
# type from).  Since 16.17 StaticMaterialShaderSamplerDef.texturePath is a link,
# and the client skips a property whose wire type disagrees with its schema.
NEW_TEXTURE_PATH_TYPE = TYPE_FILE

_LINK_HEX_RE = re.compile(r'^0x[0-9a-fA-F]{16}$')


def is_link_hex(text) -> bool:
    """True for the textual form of an unresolved link: '0x' + 16 hex digits.

    A bare 16-digit token without '0x' is treated as a PATH (hash-named mod
    files look exactly like that)."""
    return isinstance(text, str) and bool(_LINK_HEX_RE.match(text.strip()))


def link_hex(h: int) -> str:
    return f"0x{h & _U64:016x}"


def text_to_link(text) -> str:
    """Path or '0x%016x' -> type-18 value string ('0x%016x').

    Empty text gives the zero link (Riot writes no field in that case; callers
    keep whatever they had)."""
    if text is None:
        return link_hex(0)
    if isinstance(text, int):
        return link_hex(text)
    text = str(text).strip()
    if not text:
        return link_hex(0)
    if is_link_hex(text):
        return text.lower()
    return link_hex(xxhash64_path(text))


def link_to_int(value) -> int:
    if isinstance(value, int):
        return value & _U64
    try:
        return int(str(value), 16) & _U64
    except (TypeError, ValueError):
        return 0


# ============================================================================
# Hash -> path resolution
# ============================================================================

# Registered resolvers: callables taking an int hash and returning a path or None.
# wad_tool registers its CommunityDragon/hashlist/custom table lookup here.
_resolvers = []

# Asset folders that may hold the linked files (registered by texture lookup).
_search_roots = []          # absolute folder paths, in registration order
_root_index = {}            # normcase(root) -> (built_at, {hash: full_path})
_REINDEX_AFTER_S = 10.0     # rebuild a root's index on a miss when older than this

_TEXTURE_EXTS = ('.tex', '.dds', '.png')


def register_resolver(fn):
    if fn not in _resolvers:
        _resolvers.append(fn)


def unregister_resolver(fn):
    if fn in _resolvers:
        _resolvers.remove(fn)


def add_search_root(folder: str):
    """Register an asset folder (e.g. <cache>/assets or <project>/assets)."""
    if not folder:
        return
    try:
        root = os.path.abspath(folder)
    except (TypeError, ValueError):
        return
    if os.path.isdir(root) and os.path.normcase(root) not in {
            os.path.normcase(r) for r in _search_roots}:
        _search_roots.append(root)


def clear_index():
    """Forget every built folder index (e.g. after files were added)."""
    _root_index.clear()


def _build_index(root: str) -> dict:
    """Index files below ``root`` by the WAD hash of their game path.

    ``root`` is an asset folder such as ``.../assets``; a file at
    ``root/maps/x.tex`` has the game path ``assets/maps/x.tex``.  Texture files
    are also indexed under their sibling extensions (.tex/.dds/.png) at lower
    priority so a converted .dds still answers a link to the .tex.  A sibling
    ``raw`` folder (WAD extraction of unnamed chunks: raw/<hash>.<ext>) is
    indexed by its hash file names.
    """
    index = {}
    alt = {}
    prefix = os.path.basename(root.rstrip('\\/')).lower()
    for dirpath, _dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = '' if rel_dir == '.' else rel_dir.replace('\\', '/') + '/'
        for name in files:
            game_path = f"{prefix}/{rel_dir}{name}"
            full = os.path.join(dirpath, name)
            index.setdefault(xxhash64_path(game_path), full)
            base, ext = os.path.splitext(game_path)
            if ext.lower() in _TEXTURE_EXTS:
                for other in _TEXTURE_EXTS:
                    if other != ext.lower():
                        alt.setdefault(xxhash64_path(base + other), full)
    raw_dir = os.path.join(os.path.dirname(root.rstrip('\\/')), 'raw')
    if os.path.isdir(raw_dir):
        for name in os.listdir(raw_dir):
            stem = os.path.splitext(name)[0]
            if len(stem) == 16:
                try:
                    alt.setdefault(int(stem, 16), os.path.join(raw_dir, name))
                except ValueError:
                    pass
    for h, p in alt.items():
        index.setdefault(h, p)
    return index


def _index_for(root: str, force: bool = False) -> dict:
    key = os.path.normcase(root)
    entry = _root_index.get(key)
    if entry is None or force:
        entry = (time.time(), _build_index(root))
        _root_index[key] = entry
    return entry[1]


def find_file_for_link(value, folders=None):
    """Return the on-disk file for a link (int or '0x...'), or None.

    Searches ``folders`` (in order) when given, else every registered root."""
    h = link_to_int(value)
    if not h:
        return None
    roots = []
    for f in (folders if folders is not None else _search_roots):
        if not f:
            continue
        root = os.path.abspath(f)
        if os.path.isdir(root) and os.path.normcase(root) not in {
                os.path.normcase(r) for r in roots}:
            roots.append(root)
    for root in roots:
        hit = _index_for(root).get(h)
        if hit and os.path.exists(hit):
            return hit
    # Miss: refresh stale indexes once (new files may have been copied in)
    now = time.time()
    for root in roots:
        built = _root_index.get(os.path.normcase(root), (now, None))[0]
        if now - built > _REINDEX_AFTER_S:
            hit = _index_for(root, force=True).get(h)
            if hit and os.path.exists(hit):
                return hit
    return None


def _path_from_index(h: int):
    for root in list(_search_roots):
        full = _index_for(root).get(h)
        if not full:
            continue
        prefix = os.path.basename(root.rstrip('\\/')).lower()
        try:
            rel = os.path.relpath(full, root).replace('\\', '/')
        except ValueError:
            continue
        if rel.startswith('..'):
            continue  # raw/<hash> entry - no name known
        game_path = f"{prefix}/{rel}"
        if xxhash64_path(game_path) == h:
            return game_path
    return None


def resolve_link(value):
    """Link (int or '0x...') -> path string, or None when no source names it.

    Every candidate is verified by re-hashing, so a returned path always
    hashes back to the same link."""
    h = link_to_int(value)
    if not h:
        return None
    for fn in list(_resolvers):
        try:
            p = fn(h)
        except Exception:
            p = None
        if p and xxhash64_path(p) == h:
            return p
    return _path_from_index(h)


def link_to_text(value) -> str:
    """Type-18 value -> readable path when known, else the '0x%016x' form."""
    h = link_to_int(value)
    if not h:
        return ""
    return resolve_link(h) or link_hex(h)


# ============================================================================
# Ritobin text form ("texturePath: string = "..."" / "texturePath: file = ...")
# ============================================================================

def parse_text_path_field(body: str, name: str):
    """Find ``name: string|file = "..."|0x...`` in ritobin text.

    Returns (text, type_id) or None.  A bare 0x value is kept in '0x%016x' form."""
    m = re.search(name + r'\s*:\s*(string|file)\s*=\s*(?:"([^"]*)"|(0x[0-9a-fA-F]+))', body)
    if not m:
        return None
    type_id = TYPE_FILE if m.group(1) == 'file' else TYPE_STRING
    if m.group(2) is not None:
        return m.group(2), type_id
    return link_hex(int(m.group(3), 16)), type_id


def format_text_path_field(name: str, text, type_id) -> str:
    """Ritobin text line body for a path field, keeping its type."""
    text = "" if text is None else str(text)
    if type_id == TYPE_FILE:
        if is_link_hex(text):
            return f'{name}: file = {text.lower()}'
        return f'{name}: file = "{text}"'
    return f'{name}: string = "{text}"'


# ============================================================================
# Bin field helpers (propertybin_parser field dicts)
# ============================================================================

def field_text(field) -> str:
    """Readable text of a String or type-18 field ('' for None)."""
    if not field:
        return ""
    if field.get('type') == TYPE_FILE:
        return link_to_text(field.get('value'))
    v = field.get('value')
    return "" if v is None else str(v)


def text_to_field_value(type_id: int, text) -> str:
    """Wire value for ``text`` in a field of ``type_id`` (keeps the type)."""
    if type_id == TYPE_FILE:
        return text_to_link(text)
    return "" if text is None else str(text)


def set_field_text(field, text) -> bool:
    """Set a String or type-18 field from text WITHOUT changing its type.

    Returns True when the stored value changed."""
    new_val = text_to_field_value(field.get('type', TYPE_STRING), text)
    old_val = field.get('value')
    if field.get('type') == TYPE_FILE:
        if link_to_int(old_val) == link_to_int(new_val):
            return False
    elif old_val == new_val:
        return False
    field['value'] = new_val
    return True
