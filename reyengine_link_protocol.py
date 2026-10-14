"""ReyEngine live link, protocol 3 - the wire half (no bpy).

ReyEngine listens on 127.0.0.1 (default port 47800); MapgeoAddon connects.  Every
message is one UTF-8 JSON header line ending in a newline, optionally followed by
exactly ``header["bytes"]`` bytes of binary body.  Every connection starts with
``hello``.  The full specification is docs/reyengine-link-protocol.md, kept in
this repository and in ReyEngine's.

The wire is League space: Y up, the numbers the .mapgeo holds.  The Blender side
(reyengine_link.py) owns the conversion to Z up.

ReyEngine is the only writer of the .mapgeo and the .materials.bin: this module
only ever sends EDITS (a transform, a shape, an assignment, a material value),
which ReyEngine applies through its own undoable editors and its normal Save.

Kept free of bpy so it can be exercised by plain Python - ReyEngine's test suite
runs ``encode_meshes`` / ``decode_meshes`` against its own C# codec.
"""

import json
import socket
import struct
import zlib

PROTOCOL = 4
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47800
MAX_HEADER_BYTES = 16 * 1024 * 1024
# mapgeo index buffers are 16-bit
MAX_VERTICES_PER_MESH = 65536


class LinkError(Exception):
    """A refusal or a broken link, with a message meant for the user."""


# ---------------------------------------------------------------- transport

def read_header(sock):
    """Read one newline-terminated JSON header, a byte at a time.

    Byte at a time because a buffered read would swallow part of the binary body
    that follows the newline, and the body is not self-describing enough to
    recover from that.
    """
    line = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise LinkError("ReyEngine closed the connection")
        if b == b"\n":
            return json.loads(line.decode("utf-8"))
        if b != b"\r":
            line += b
        if len(line) > MAX_HEADER_BYTES:
            raise LinkError("header never ended - is that port really ReyEngine?")


def read_exactly(sock, count):
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(min(1 << 20, count - len(chunks)))
        if not chunk:
            raise LinkError("ReyEngine closed the connection mid-payload")
        chunks += chunk
    return bytes(chunks)


class Connection:
    """One connection to ReyEngine: hello on open, then any number of requests.

    Short-lived by design - one per user action.  A socket held open across
    Blender's UI would have to be pumped from its single thread and would need
    reconnect logic that can fail in the middle of an edit; reconnecting costs a
    millisecond on loopback and cannot get stuck.
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, client="MapgeoAddon", timeout=60.0, token=""):
        self.host = host
        self.token = token or ""
        self.port = int(port)
        self.client = client
        self.timeout = timeout
        self.sock = None
        self.info = {}

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def open(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as ex:
            raise LinkError("ReyEngine is not listening on %s:%d (%s). In ReyEngine: open a map, then "
                            "Tools > Blender link (MapgeoAddon)." % (self.host, self.port, ex))
        self.info = self.request({"op": "hello", "protocol": PROTOCOL, "client": self.client,
                                  "token": self.token})[0]
        if self.info.get("protocol") != PROTOCOL:
            raise LinkError("ReyEngine speaks protocol %s, this add-on %s - update the older one"
                            % (self.info.get("protocol"), PROTOCOL))
        return self.info

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def request(self, payload, body=None, want_body=False):
        """Send one request and read its reply.  An ``error`` reply raises LinkError.

        Returns (header, body bytes).  The body is read whenever the reply declares
        one, so the stream stays in step even when the caller does not want it.
        """
        if body:
            payload = dict(payload)
            payload["bytes"] = len(body)
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        if body:
            self.sock.sendall(body)
        header = read_header(self.sock)
        size = int(header.get("bytes", 0) or 0)
        data = read_exactly(self.sock, size) if size > 0 else b""
        if header.get("op") == "error":
            raise LinkError(header.get("message", "refused"))
        return header, (data if want_body else b"")


_TOKEN_RE = None


def looks_like_token(text):
    """True for ReyEngine's session token as it is copied: 'XXXX-XXXX' (letters and digits)."""
    global _TOKEN_RE
    import re
    if _TOKEN_RE is None:
        _TOKEN_RE = re.compile(r'^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$')
    return isinstance(text, str) and bool(_TOKEN_RE.match(text.strip()))


# ---------------------------------------------------------------- mesh block

def _pack_floats(values):
    values = list(values or ())
    return struct.pack("<i", len(values)) + struct.pack("<%df" % len(values), *values)


def _pack_string(text):
    raw = (text or "").encode("utf-8")
    return struct.pack("<i", len(raw)) + raw


def encode_meshes(entries):
    """Pack meshes into the protocol 3 mesh block (what ``push_geometry`` carries).

    Per mesh: name, index, pivot, location, rotation, scale, then positions,
    normals, uvs, lightmap uvs, colours, grass pivots (protocol 4) and indices (each length-prefixed), then
    the submesh table (material, start index, index count).
    """
    out = bytearray()
    out += struct.pack("<i", len(entries))
    for e in entries:
        out += _pack_string(e["name"])
        out += struct.pack("<i", int(e["index"]))
        for key in ("pivot", "location", "rotation", "scale"):
            out += struct.pack("<3f", *e[key])
        out += _pack_floats(e.get("positions"))
        out += _pack_floats(e.get("normals"))
        out += _pack_floats(e.get("uvs"))
        out += _pack_floats(e.get("lightmap_uvs"))
        out += _pack_floats(e.get("colors"))
        out += _pack_floats(e.get("grass_pivots"))
        indices = list(e.get("indices") or ())
        out += struct.pack("<i", len(indices)) + struct.pack("<%dI" % len(indices), *indices)
        submeshes = e.get("submeshes") or ()
        out += struct.pack("<i", len(submeshes))
        for s in submeshes:
            out += _pack_string(s["material"])
            out += struct.pack("<ii", int(s["start"]), int(s["count"]))
    return bytes(out)


def decode_meshes(body):
    """Read the protocol 3 mesh block a ``pull`` sends."""
    at = 0

    def i32():
        nonlocal at
        (value,) = struct.unpack_from("<i", body, at)
        at += 4
        return value

    def floats(n):
        nonlocal at
        values = struct.unpack_from("<%df" % n, body, at)
        at += 4 * n
        return values

    def string():
        nonlocal at
        n = i32()
        if n < 0 or n > 4096:
            raise LinkError("string length %d is not plausible - wrong protocol?" % n)
        text = body[at:at + n].decode("utf-8")
        at += n
        return text

    count = i32()
    meshes = []
    for _ in range(count):
        name = string()
        index = i32()
        pivot = floats(3)
        location = floats(3)
        rotation = floats(3)
        scale = floats(3)
        positions = floats(i32())
        normals = floats(i32())
        uvs = floats(i32())
        lightmap = floats(i32())
        colors = floats(i32())
        grass = floats(i32())
        index_count = i32()
        indices = struct.unpack_from("<%dI" % index_count, body, at)
        at += 4 * index_count
        submeshes = []
        for _s in range(i32()):
            material = string()
            start, length = struct.unpack_from("<ii", body, at)
            at += 8
            submeshes.append({"material": material, "start": start, "count": length})
        meshes.append({
            "name": name, "index": index, "pivot": pivot,
            "location": location, "rotation": rotation, "scale": scale,
            "positions": positions, "normals": normals, "uvs": uvs,
            "lightmap_uvs": lightmap, "colors": colors, "grass_pivots": grass,
            "indices": indices, "submeshes": submeshes,
        })
    if at != len(body):
        raise LinkError("%d byte(s) left over after the mesh block - wrong protocol?" % (len(body) - at))
    return meshes


# ---------------------------------------------------------------- pure geometry helpers

def reverse_winding(indices):
    """Flip every triangle, so a mirrored mesh still faces outward.

    The League -> Blender basis swap negates a face's normal; reversing its
    winding negates it back.
    """
    flipped = list(indices)
    for at in range(0, len(flipped) - 2, 3):
        flipped[at + 1], flipped[at + 2] = flipped[at + 2], flipped[at + 1]
    return flipped


def per_loop(values, indices, width):
    """Expand per-VERTEX values (``width`` floats each) into per-LOOP order.

    from_pydata lays loops out in the order of ``indices``, so this is a gather.
    """
    out = [0.0] * (len(indices) * width)
    for loop_index, vertex_index in enumerate(indices):
        src = vertex_index * width
        dst = loop_index * width
        out[dst:dst + width] = values[src:src + width]
    return out


def flip_v(uvs):
    """(u, v) -> (u, 1 - v) over a flat list: MapgeoAddon's UV convention."""
    out = list(uvs)
    for i in range(1, len(out), 2):
        out[i] = 1.0 - out[i]
    return out


def to_league_axes(flat):
    """Blender (x, y, z) -> League (x, z, y) over a flat xyz buffer, as slices."""
    return flat[0::3], flat[2::3], flat[1::3]


def fingerprint(mesh):
    """A cheap signature of a mesh's shape: its coordinates and its topology.

    Returned as a STRING: crc32 is unsigned 32-bit and a Blender custom property
    is a signed C int.  Duck-typed (vertices/loops with foreach_get) so it runs
    without Blender.
    """
    co = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    loops = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", loops)
    digest = zlib.crc32(struct.pack("<%df" % len(co), *co))
    return "%d" % zlib.crc32(struct.pack("<%dI" % len(loops), *loops), digest)


# ---------------------------------------------------------------- material edits

def _close(a, b, eps=1e-6):
    try:
        a = [float(x) for x in a]
        b = [float(x) for x in b]
    except (TypeError, ValueError):
        return a == b
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= eps * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def _load(text, empty):
    try:
        value = json.loads(text) if text else empty
    except (TypeError, ValueError):
        return empty
    return value if isinstance(value, type(empty)) else empty


def safe_cache_path(cache_root, rel_parts):
    """Join ``rel_parts`` under ``cache_root``, or None when they would land anywhere else.

    The parts come from ReyEngine's answer (a texture path), so they are checked like any outside input:
    no '..', no absolute or drive-qualified component, and the result must stay inside the cache."""
    import os
    clean = []
    for part in rel_parts:
        if not part or part in (".", ".."):
            return None
        if ":" in part or "\\" in part or part.startswith("/") or os.path.isabs(part):
            return None
        clean.append(part)
    if not clean:
        return None
    root = os.path.abspath(cache_root)
    full = os.path.abspath(os.path.join(root, *clean))
    try:
        if os.path.commonpath([root, full]) != root:
            return None
    except ValueError:
        return None
    return full


def material_edits(material_name, before, after):
    """The ``edit_material`` entries that turn ``before`` into ``after``.

    ``before`` and ``after`` hold the JSON strings MapgeoAddon's material editor
    keeps on a material: ``samplers``, ``parameters``, ``switches`` and
    ``shader_macros``.  Returns (edits, notes) - notes describe changes the
    protocol does not carry (a removed parameter, a removed sampler).
    """
    edits, notes = [], []

    p0 = {p.get("name"): p for p in _load(before.get("parameters"), []) if isinstance(p, dict)}
    p1 = {p.get("name"): p for p in _load(after.get("parameters"), []) if isinstance(p, dict)}
    for name, p in p1.items():
        if not name:
            continue
        old = p0.get(name)
        value = p.get("value")
        if old is not None and _close(old.get("value"), value):
            continue
        if isinstance(value, (list, tuple)):
            edits.append({"material": material_name, "kind": "param", "name": name, "value": [float(v) for v in value]})
        elif isinstance(value, (int, float)):
            edits.append({"material": material_name, "kind": "param", "name": name, "value": [float(value)]})
        elif value is not None:
            edits.append({"material": material_name, "kind": "param", "name": name, "value": str(value)})
    for name in p0:
        if name and name not in p1:
            notes.append("%s: removing parameter %s is not sent - remove it in ReyEngine" % (material_name, name))

    def sampler_name(s):
        return s.get("textureName") or s.get("TextureName") or ""

    s0 = {sampler_name(s): s for s in _load(before.get("samplers"), []) if isinstance(s, dict)}
    s1 = {sampler_name(s): s for s in _load(after.get("samplers"), []) if isinstance(s, dict)}
    for name, s in s1.items():
        if not name:
            continue
        old = s0.get(name, {})
        if (s.get("texturePath") or "") != (old.get("texturePath") or "") and s.get("texturePath"):
            edits.append({"material": material_name, "kind": "sampler", "name": name, "path": s["texturePath"]})
        address = {}
        for axis, key in (("u", "addressU"), ("v", "addressV"), ("w", "addressW")):
            if s.get(key) != old.get(key) and (key in s or key in old):
                value = s.get(key)
                address[axis] = int(value) if isinstance(value, (int, float)) else None
        if address:
            entry = {"material": material_name, "kind": "address", "name": name}
            entry.update(address)
            edits.append(entry)
    for name in s0:
        if name and name not in s1:
            notes.append("%s: removing sampler %s is not sent - remove it in ReyEngine" % (material_name, name))

    w0 = {w.get("name"): bool(w.get("on")) for w in _load(before.get("switches"), []) if isinstance(w, dict)}
    w1 = {w.get("name"): bool(w.get("on")) for w in _load(after.get("switches"), []) if isinstance(w, dict)}
    for name, on in w1.items():
        if name and w0.get(name) != on:
            edits.append({"material": material_name, "kind": "switch", "name": name, "on": on})

    m0 = _load(before.get("shader_macros"), {})
    m1 = _load(after.get("shader_macros"), {})
    for name, value in m1.items():
        if str(m0.get(name)) != str(value) or name not in m0:
            edits.append({"material": material_name, "kind": "macro", "name": name, "value": str(value)})
    for name in m0:
        if name not in m1:
            edits.append({"material": material_name, "kind": "macro", "name": name, "value": None})

    return edits, notes
