"""
Project Reys Format (.prey) — Blender-friendly split of League materials data.

Converts .materials.bin / .materials.py → sorted, categorised .prey.* JSON files:
    <name>.prey.materials   — StaticMaterialDef entries
    <name>.prey.vfx         — VfxSystemDefinitionData + MapPlaceableContainer + particles
    <name>.prey.map         — MapSunProperties, MapBakeProperties, MapLightingV2, MapContainer
    <name>.prey.visibility  — Visibility controllers (Dragon/Baron/Named/Child/Mutator layers)
    <name>.prey.extra       — Everything else (MapSkin, music, unknown types)

Round-trip: bin → prey → bin preserves all data.
"""

import json
import os
from typing import Optional

# ============================================================================
# Version
# ============================================================================

PREY_FORMAT_VERSION = 1

# ============================================================================
# Type Hash Registry
# ============================================================================

# Known type hashes → (human name, category)
TYPE_REGISTRY = {
    0xff9d3409: ("StaticMaterialDef",                "materials"),
    0x45cd899f: ("VfxSystemDefinitionData",          "vfx"),
    0xb25c0a3f: ("MapPlaceableContainer",            "vfx"),
    0x24a31b3e: ("MapParticle",                      "vfx"),
    0x1f1f50f2: ("MapParticle_Alt",                  "vfx"),
    0x169a2f9c: ("MapSunProperties",                 "map"),
    0x6a4a3409: ("MapBakeProperties",                "map"),
    0xdca35419: ("MapLightingV2",                    "map"),
    0xdde8c114: ("MapContainer",                     "map"),
    0xe21083b5: ("ChildMapVisibilityController",     "visibility"),
    0xc406a533: ("DragonLayerController",            "visibility"),
    0xec733fe2: ("BaronLayerController",             "visibility"),
    0xe07edfa4: ("NamedController",                  "visibility"),
    0x4275b121: ("MutatorVisibilityController",      "visibility"),
}

# ============================================================================
# Field Hash Registry — human-readable field names for known hashes
# ============================================================================

FIELD_NAMES = {
    # StaticMaterialDef
    0x8d39bde6: "name",
    0x5127f14d: "materialType",
    0x0a6f0eb5: "samplerValues",
    0xd0ab46b8: "paramValues",
    0xdd7ddb9d: "switchValues",
    0xe6d67ded: "shaderMacros",
    0x844f384e: "techniques",
    0x9330e6b6: "childTechniques",
    # Sampler fields
    0xb311d4ef: "textureName",
    0xf0a363e3: "texturePath",
    0x111ec6d2: "addressU",
    0x101ec53f: "addressV",
    0x0f1ec3ac: "addressW",
    # Param fields
    0x425ed3ca: "value",
    # Switch fields
    0x61342fd0: "on",
    0x5fb91e8c: "group",
    # Technique/Pass fields (bin-level hashes inside StaticMaterialPassDef)
    0x623cd25c: "passes",
    0xc5ac22aa: "shader",
    0x23b75597: "blendEnable",
    0x4b0f55ce: "cullEnable",
    0x22c0c7d0: "srcColorBlendFactor",
    0xa0958d01: "srcAlphaBlendFactor",
    0xbe0abbf5: "dstColorBlendFactor",
    0x7385e534: "dstAlphaBlendFactor",
    0x917e428e: "writeMask",
    # DefaultTechnique
    0x28da4278: "defaultTechnique",
    # Child technique
    0xb696a5fe: "parentName",
    # MapSunProperties
    0x664a1f44: "sunColor",
    0xe1907cf6: "sunDirection",
    0x0a65794d: "skyLightColor",
    0xfd3d43af: "horizonColor",
    0x583befe1: "groundColor",
    0xb39b0430: "skyLightScale",
    0x986a4d5c: "lightMapColorScale",
    0x00849744: "fogEnabled",
    0x023b1fce: "fogColor",
    0x4896f2da: "fogAlternateColor",
    0x72a72173: "fogStartAndEnd",
    # MapBakeProperties
    0x469be1a2: "lightGridSize",
    0x7561b09e: "lightGridFileName",
    0x9cf064e5: "RmaStaticLightGridTexturePath",
    0x7ab8b646: "RmaStaticLightGridIntensityScale",
    0x5c6a0e0c: "lightGridCharacterFullBrightIntensity",
    # MapLightingV2
    0xee91017d: "MinimumEnvironmentColorContribution",
    # MPC / Particle
    0x3a79338f: "items",
    0x491e0a9c: "system",
    0xe1ad931b: "transform",
    0xccf79327: "visibilityFlags",
    0x5150a6a1: "VisibilityController",
    # Visibility controllers
    0x3044938a: "parents",
    0xc9d3f06a: "parentMode",
    0x27639032: "dragonLayerBit",
    0x8bff8cdf: "baronLayerBit",
    0x4a66b8d0: "enabled",
    0xdca93a3a: "controller",
}

# Reverse lookup: name → hash
FIELD_HASHES = {v: k for k, v in FIELD_NAMES.items()}

# Reverse lookup: type name → hash string
TYPE_NAME_TO_HASH = {name: f"0x{h:08x}" for h, (name, _) in TYPE_REGISTRY.items()}

# Type names for bin type IDs
TYPE_NAMES = {
    0: "none", 1: "bool", 2: "s8", 3: "u8", 4: "s16", 5: "u16",
    6: "s32", 7: "u32", 8: "s64", 9: "u64", 10: "f32",
    11: "vec2", 12: "vec3", 13: "vec4", 14: "mtx44", 15: "rgba",
    16: "string", 17: "hash", 18: "file",
    0x80: "list", 0x81: "list2", 0x82: "struct", 0x83: "embedded",
    0x84: "link", 0x85: "optional", 0x86: "map", 0x87: "flag",
}

# ============================================================================
# Material-specific conversion (bin entry ↔ clean material dict)
# ============================================================================

def _bin_material_to_prey(entry: dict) -> dict:
    """Convert a StaticMaterialDef bin entry to clean prey material dict.

    Preserves unknown fields and container types for perfect round-trip.
    """
    fields = entry.get('fields', [])

    # Known material field hashes we decode
    KNOWN_FIELD_HASHES = {
        0x8d39bde6, 0x5127f14d, 0x0a6f0eb5, 0xd0ab46b8,
        0xdd7ddb9d, 0xe6d67ded, 0x844f384e, 0x9330e6b6,
        0x28da4278,  # defaultTechnique
    }

    def _fld(hash_val):
        for f in fields:
            if f.get('name_hash_int', 0) == hash_val or f.get('name_hash') == f"0x{hash_val:08x}":
                return f
        return None

    def _field_hash(f):
        h = f.get('name_hash_int', 0)
        if h == 0:
            try:
                h = int(f.get('name_hash', '0x0'), 16)
            except ValueError:
                pass
        return h

    def _efld(flds, hash_val):
        for f in flds:
            if f.get('name_hash_int', 0) == hash_val or f.get('name_hash') == f"0x{hash_val:08x}":
                return f.get('value')
        return None

    name_f = _fld(0x8d39bde6)
    mat_name = name_f['value'] if name_f else entry.get('path_hash', '?')

    type_f = _fld(0x5127f14d)
    mat_type = type_f['value'] if type_f else 0
    has_type_field = type_f is not None

    # Samplers
    samplers = []
    sf = _fld(0x0a6f0eb5)
    sampler_container_type = sf.get('type', 0x81) if sf else 0x81
    if sf:
        for item in sf.get('values', []):
            flds = item.get('fields', [])
            sampler = {"textureName": "", "texturePath": ""}
            tn = _efld(flds, 0xb311d4ef)
            if tn is not None:
                sampler["textureName"] = tn
            tp = _efld(flds, 0xf0a363e3)
            if tp is not None:
                sampler["texturePath"] = tp
            au = _efld(flds, 0x111ec6d2)
            if au is not None:
                sampler["addressU"] = au
            av = _efld(flds, 0x101ec53f)
            if av is not None:
                sampler["addressV"] = av
            aw = _efld(flds, 0x0f1ec3ac)
            if aw is not None:
                sampler["addressW"] = aw
            samplers.append(sampler)

    # Params
    params = []
    pf = _fld(0xd0ab46b8)
    param_container_type = pf.get('type', 0x81) if pf else 0x81
    if pf:
        for item in pf.get('values', []):
            flds = item.get('fields', [])
            pname = _efld(flds, 0x8d39bde6) or ""
            pval = _efld(flds, 0x425ed3ca)
            if isinstance(pval, list):
                pval = list(pval)
            params.append({"name": pname, "value": pval})

    # Switches
    switches = []
    swf = _fld(0xdd7ddb9d)
    switch_container_type = swf.get('type', 0x81) if swf else 0x81
    if swf:
        for item in swf.get('values', []):
            flds = item.get('fields', [])
            sw = {}
            sname = _efld(flds, 0x8d39bde6)
            if sname is not None:
                sw["name"] = sname
            son = _efld(flds, 0x61342fd0)
            if son is not None:
                sw["on"] = son
            sgroup = _efld(flds, 0x5fb91e8c)
            if sgroup is not None:
                sw["group"] = sgroup
            switches.append(sw)

    # Shader macros
    shader_macros = {}
    smf = _fld(0xe6d67ded)
    if smf:
        if 'pairs' in smf:
            for pair in smf['pairs']:
                k = pair.get('key', {}).get('value', '')
                v = pair.get('value', {}).get('value', '')
                shader_macros[str(k)] = str(v)
        elif 'values' in smf:
            shader_macros = smf['values']

    # Techniques — passthrough as raw bin data (complex shader pipeline)
    tf = _fld(0x844f384e)
    raw_techniques = None
    if tf:
        raw_techniques = tf

    # Child techniques — passthrough as raw bin data
    ctf = _fld(0x9330e6b6)
    raw_child_techniques = None
    if ctf:
        raw_child_techniques = ctf

    # Collect unknown fields (any field hash not in KNOWN_FIELD_HASHES)
    raw_extra_fields = []
    for f in fields:
        if _field_hash(f) not in KNOWN_FIELD_HASHES:
            raw_extra_fields.append(f)

    # Track which container fields were present (even if empty) and their types
    _present_fields = []
    _container_types = {}
    for f in fields:
        h = _field_hash(f)
        _present_fields.append(f"0x{h:08x}")
        t = f.get('type')
        if t in (0x80, 0x81):  # container
            _container_types[f"0x{h:08x}"] = t

    result = {
        "name": mat_name,
        "type": mat_type,
        "samplers": samplers,
        "params": params,
        "switches": switches,
    }
    # defaultTechnique
    default_tech_f = _fld(0x28da4278)
    default_technique = default_tech_f['value'] if default_tech_f else None

    if shader_macros:
        result["shaderMacros"] = shader_macros
    if default_technique is not None:
        result["defaultTechnique"] = default_technique
    if raw_techniques:
        result["_rawTechniques"] = raw_techniques
        # Also store parsed techniques for editable round-trip
        result["techniques"] = _extract_techniques_from_raw(raw_techniques)
    if raw_child_techniques:
        result["_rawChildTechniques"] = raw_child_techniques
        result["childTechniques"] = _extract_child_techniques_from_raw(raw_child_techniques)

    # Round-trip metadata
    result["_pathHash"] = entry.get('path_hash', '')
    result["_presentFields"] = _present_fields
    result["_containerTypes"] = _container_types
    if raw_extra_fields:
        result["_extraFields"] = raw_extra_fields

    return result


def _prey_material_to_bin(mat: dict) -> dict:
    """Convert a clean prey material dict back to a bin entry."""

    def _mkfield(hash_val, type_id, value):
        return {"name_hash": f"0x{hash_val:08x}", "type": type_id, "value": value}

    def _mkembed(class_hash, fields):
        return {"type": 0x83, "class_hash": class_hash, "fields": fields}

    # Recover original container types from metadata
    ct = mat.get("_containerTypes", {})
    present = set(mat.get("_presentFields", []))

    def _container_type(field_hash_str, default=0x80):
        return ct.get(field_hash_str, default)

    fields = []

    # name (string)
    fields.append(_mkfield(0x8d39bde6, 16, mat["name"]))

    # materialType (u32) — always write if it was present in original
    if f"0x{0x5127f14d:08x}" in present or mat.get("type", 0) != 0:
        fields.append(_mkfield(0x5127f14d, 7, mat.get("type", 0)))

    # defaultTechnique (string) — write before samplers/techniques to match original field order
    dt_hash = f"0x{0x28da4278:08x}"
    if mat.get("defaultTechnique") is not None or dt_hash in present:
        fields.append(_mkfield(0x28da4278, 16, mat.get("defaultTechnique", "normal")))

    # samplerValues (list of embedded)
    sampler_hash = f"0x{0x0a6f0eb5:08x}"
    if mat.get("samplers") or sampler_hash in present:
        sampler_items = []
        for s in mat.get("samplers", []):
            sflds = []
            sflds.append(_mkfield(0xb311d4ef, 16, s.get("textureName", "")))
            sflds.append(_mkfield(0xf0a363e3, 16, s.get("texturePath", "")))
            if "addressU" in s:
                sflds.append(_mkfield(0x111ec6d2, 7, s["addressU"]))
            if "addressV" in s:
                sflds.append(_mkfield(0x101ec53f, 7, s["addressV"]))
            if "addressW" in s:
                sflds.append(_mkfield(0x0f1ec3ac, 7, s["addressW"]))
            sampler_items.append(_mkembed("0x0904b150", sflds))
        fields.append({
            "name_hash": sampler_hash,
            "type": _container_type(sampler_hash, 0x81), "value_type": 0x83,
            "values": sampler_items,
        })

    # paramValues (list of embedded)
    param_hash = f"0x{0xd0ab46b8:08x}"
    if mat.get("params") or param_hash in present:
        param_items = []
        for p in mat.get("params", []):
            pflds = []
            pflds.append(_mkfield(0x8d39bde6, 16, p.get("name", "")))
            val = p.get("value")
            if val is not None:
                pflds.append(_mkfield(0x425ed3ca, 13, list(val)))
            param_items.append(_mkembed("0xde480eef", pflds))
        fields.append({
            "name_hash": param_hash,
            "type": _container_type(param_hash, 0x81), "value_type": 0x83,
            "values": param_items,
        })

    # switchValues (list of embedded)
    switch_hash = f"0x{0xdd7ddb9d:08x}"
    if mat.get("switches") or switch_hash in present:
        switch_items = []
        for sw in mat.get("switches", []):
            sflds = []
            if "name" in sw:
                sflds.append(_mkfield(0x8d39bde6, 16, sw["name"]))
            if sw.get("on") is not None:
                sflds.append(_mkfield(0x61342fd0, 1, sw["on"]))
            if sw.get("group") is not None:
                sflds.append(_mkfield(0x5fb91e8c, 16, sw["group"]))
            switch_items.append(_mkembed("0x0e2212a1", sflds))
        fields.append({
            "name_hash": switch_hash,
            "type": _container_type(switch_hash, 0x81), "value_type": 0x83,
            "values": switch_items,
        })

    # shaderMacros (map<string, string>)
    macro_hash = f"0x{0xe6d67ded:08x}"
    if mat.get("shaderMacros"):
        pairs = []
        for k, v in mat["shaderMacros"].items():
            pairs.append({
                "key": {"type": 16, "value": str(k)},
                "value": {"type": 16, "value": str(v)},
            })
        fields.append({
            "name_hash": macro_hash,
            "type": 0x86, "key_type": 16, "value_type": 16,
            "pairs": pairs,
        })

    # techniques — prefer parsed 'techniques' (Blender-editable) over raw passthrough
    if mat.get("techniques"):
        # Build technique bin fields from parsed technique data
        tech_values = []
        for tech in mat["techniques"]:
            pass_structs = []
            for p in tech.get("passes", []):
                pf = []
                shader_path = p.get("shader", "")
                if shader_path:
                    shader_hash = "0x%08x" % _fnv1a_32(shader_path)
                    pf.append(_mkfield(_HASH_SHADER_LINK, 132, shader_hash))
                if p.get("blendEnable"):
                    pf.append(_mkfield(_BIN_PASS_BLEND, 1, True))
                    pf.append(_mkfield(_BIN_PASS_CULL, 1, bool(p.get("cullEnable", False))))
                    pf.append(_mkfield(_BIN_PASS_SRC_COLOR, 7, p.get("srcColorBlendFactor", 1)))
                    pf.append(_mkfield(_BIN_PASS_SRC_ALPHA, 7, p.get("srcAlphaBlendFactor", 1)))
                    pf.append(_mkfield(_BIN_PASS_DST_COLOR, 7, p.get("dstColorBlendFactor", 0)))
                    pf.append(_mkfield(_BIN_PASS_DST_ALPHA, 7, p.get("dstAlphaBlendFactor", 0)))
                elif "cullEnable" in p:
                    pf.append(_mkfield(_BIN_PASS_CULL, 1, bool(p["cullEnable"])))
                if p.get("writeMask") is not None:
                    pf.append(_mkfield(_BIN_PASS_WRITE_MASK, 7, p["writeMask"]))
                if p.get("shaderMacros"):
                    macro_pairs = []
                    for mk, mv in p["shaderMacros"].items():
                        macro_pairs.append({
                            "key": {"type": 16, "value": str(mk)},
                            "value": {"type": 16, "value": str(mv)},
                        })
                    pf.append({
                        "name_hash": "0x%08x" % _HASH_SHADER_MACROS,
                        "type": 0x86, "key_type": 16, "value_type": 16,
                        "pairs": macro_pairs,
                    })
                pass_structs.append(_mkembed("0x8537d0c2", pf))

            tech_fields_list = [
                _mkfield(_HASH_NAME, 16, tech.get("name", "normal")),
                {
                    "name_hash": "0x%08x" % _HASH_PASSES,
                    "type": 0x80, "value_type": 0x83,
                    "values": pass_structs,
                },
            ]
            tech_values.append(_mkembed("0x060a4413", tech_fields_list))

        fields.append({
            "name_hash": "0x%08x" % _HASH_TECHNIQUES,
            "type": 0x80, "value_type": 0x83,
            "values": tech_values,
        })
    elif mat.get("_rawTechniques"):
        fields.append(mat["_rawTechniques"])

    # childTechniques — prefer parsed over raw passthrough
    if mat.get("childTechniques"):
        child_values = []
        for ct in mat["childTechniques"]:
            cf = [
                _mkfield(_HASH_NAME, 16, ct.get("name", "")),
                _mkfield(_HASH_PARENT_NAME, 16, ct.get("parentName", "normal")),
            ]
            if ct.get("shaderMacros"):
                macro_pairs = []
                for mk, mv in ct["shaderMacros"].items():
                    macro_pairs.append({
                        "key": {"type": 16, "value": str(mk)},
                        "value": {"type": 16, "value": str(mv)},
                    })
                cf.append({
                    "name_hash": "0x%08x" % _HASH_SHADER_MACROS,
                    "type": 0x86, "key_type": 16, "value_type": 16,
                    "pairs": macro_pairs,
                })
            child_values.append(_mkembed("0x735b4c95", cf))
        fields.append({
            "name_hash": "0x%08x" % _HASH_CHILD_TECHNIQUES,
            "type": 0x80, "value_type": 0x83,
            "values": child_values,
        })
    elif mat.get("_rawChildTechniques"):
        fields.append(mat["_rawChildTechniques"])

    # Re-emit any unknown fields preserved during decode
    for ef in mat.get("_extraFields", []):
        fields.append(ef)

    return {
        "path_hash": mat.get("_pathHash", f"0x{0:08x}"),
        "type_hash": f"0x{0xff9d3409:08x}",
        "fields": fields,
    }


# ============================================================================
# Generic entry ↔ prey field decoding (for non-material types)
# ============================================================================

def _decode_field_name(name_hash_str: str) -> str:
    """Resolve a field hash to a human name, or keep the hash string."""
    try:
        h = int(name_hash_str, 16)
        return FIELD_NAMES.get(h, name_hash_str)
    except (ValueError, TypeError):
        return name_hash_str


def _decode_type_name(type_hash_str: str) -> str:
    """Resolve a type hash to a human name."""
    try:
        h = int(type_hash_str, 16)
        name, _ = TYPE_REGISTRY.get(h, (type_hash_str, "extra"))
        return name
    except (ValueError, TypeError):
        return type_hash_str


def _decode_fields_recursive(fields: list) -> list:
    """Decode field hashes to readable names recursively through nested structures."""
    if not fields:
        return fields
    decoded = []
    for f in fields:
        df = dict(f)
        # Decode field name
        nh = df.get('name_hash', '')
        readable = _decode_field_name(nh)
        if readable != nh:
            df['_name'] = readable

        # Recurse into nested structures
        if isinstance(df.get('fields'), list):
            df['fields'] = _decode_fields_recursive(df['fields'])
        if isinstance(df.get('values'), list):
            new_vals = []
            for v in df['values']:
                if isinstance(v, dict) and 'fields' in v:
                    nv = dict(v)
                    nv['fields'] = _decode_fields_recursive(nv['fields'])
                    new_vals.append(nv)
                else:
                    new_vals.append(v)
            df['values'] = new_vals
        if 'pairs' in df and isinstance(df['pairs'], list):
            new_pairs = []
            for p in df['pairs']:
                np = dict(p)
                for side in ('key', 'value'):
                    if isinstance(np.get(side), dict) and 'fields' in np[side]:
                        ns = dict(np[side])
                        ns['fields'] = _decode_fields_recursive(ns['fields'])
                        np[side] = ns
                new_pairs.append(np)
            df['pairs'] = new_pairs
        decoded.append(df)
    return decoded


def _encode_field_name(field: dict) -> dict:
    """Remove the _name annotation — bin writer uses name_hash."""
    ef = dict(field)
    ef.pop('_name', None)
    # Recurse (guard against None fields from nullable structs)
    if isinstance(ef.get('fields'), list):
        ef['fields'] = [_encode_field_name(f) for f in ef['fields']]
    if isinstance(ef.get('values'), list):
        new_vals = []
        for v in ef['values']:
            if isinstance(v, dict):
                nv = dict(v)
                if isinstance(nv.get('fields'), list):
                    nv['fields'] = [_encode_field_name(f) for f in nv['fields']]
                new_vals.append(nv)
            else:
                new_vals.append(v)
        ef['values'] = new_vals
    if isinstance(ef.get('pairs'), list):
        new_pairs = []
        for p in ef['pairs']:
            np = dict(p)
            for side in ('key', 'value'):
                if isinstance(np.get(side), dict) and isinstance(np[side].get('fields'), list):
                    ns = dict(np[side])
                    ns['fields'] = [_encode_field_name(f) for f in ns['fields']]
                    np[side] = ns
            new_pairs.append(np)
        ef['pairs'] = new_pairs
    return ef


def _generic_entry_to_prey(entry: dict) -> dict:
    """Convert any bin entry to a prey-friendly dict with decoded field names."""
    result = {
        "pathHash": entry.get('path_hash', ''),
        "typeHash": entry.get('type_hash', ''),
        "typeName": _decode_type_name(entry.get('type_hash', '')),
        "fields": _decode_fields_recursive(entry.get('fields', [])),
    }
    return result


def _prey_generic_to_bin(prey_entry: dict) -> dict:
    """Convert a prey-friendly dict back to bin entry format."""
    fields = [_encode_field_name(f) for f in prey_entry.get('fields', [])]
    return {
        "path_hash": prey_entry.get('pathHash', ''),
        "type_hash": prey_entry.get('typeHash', ''),
        "fields": fields,
    }


# ============================================================================
# Map settings conversion (decoded to/from clean dict)
# ============================================================================

# (field_hash, prey_key, bin_type)
_SUN_FIELDS = [
    (0x664a1f44, "sunColor",            13),
    (0xe1907cf6, "sunDirection",        12),
    (0x0a65794d, "skyLightColor",       13),
    (0xfd3d43af, "horizonColor",        13),
    (0x583befe1, "groundColor",         13),
    (0xb39b0430, "skyLightScale",       10),
    (0x986a4d5c, "lightMapColorScale",  10),
    (0x00849744, "fogEnabled",           1),
    (0x023b1fce, "fogColor",            13),
    (0x4896f2da, "fogAlternateColor",   13),
    (0x72a72173, "fogStartAndEnd",      11),
]

_BAKE_FIELDS = [
    (0x469be1a2, "lightGridSize",                          7),
    (0x7561b09e, "lightGridFileName",                     16),
    (0x9cf064e5, "RmaStaticLightGridTexturePath",         16),
    (0x7ab8b646, "RmaStaticLightGridIntensityScale",      10),
    (0x5c6a0e0c, "lightGridCharacterFullBrightIntensity", 10),
]

_LIGHTING_FIELDS = [
    (0xee91017d, "MinimumEnvironmentColorContribution", 10),
]


def _bin_map_entry_to_prey(entry: dict) -> dict:
    """Convert a MapSun/Bake/Lighting bin entry to clean prey dict."""
    th = entry.get('type_hash', '')
    try:
        th_int = int(th, 16)
    except ValueError:
        th_int = 0

    fields = entry.get('fields', [])
    result = {"pathHash": entry.get('path_hash', ''), "typeHash": th}

    if th_int == 0x169a2f9c:
        result["typeName"] = "MapSunProperties"
        field_defs = _SUN_FIELDS
    elif th_int == 0x6a4a3409:
        result["typeName"] = "MapBakeProperties"
        field_defs = _BAKE_FIELDS
    elif th_int == 0xdca35419:
        result["typeName"] = "MapLightingV2"
        field_defs = _LIGHTING_FIELDS
    elif th_int == 0xdde8c114:
        # MapContainer — extract embedded sun/bake/lighting items
        return _bin_map_container_to_prey(entry)
    else:
        # Unknown — use generic
        return _generic_entry_to_prey(entry)

    lookup = {}
    for f in fields:
        h = f.get('name_hash_int', 0)
        if h == 0:
            try:
                h = int(f.get('name_hash', '0x0'), 16)
            except ValueError:
                pass
        lookup[h] = f.get('value')

    props = {}
    for fhash, key, _ in field_defs:
        if fhash in lookup:
            val = lookup[fhash]
            if hasattr(val, '__iter__') and not isinstance(val, str):
                val = list(val)
            props[key] = val

    result["properties"] = props
    return result


# Known field hashes used to identify embedded item types in MapContainer
_SUN_FIELD_HASHES = {h for h, _, _ in _SUN_FIELDS}
_BAKE_FIELD_HASHES = {h for h, _, _ in _BAKE_FIELDS}
_LIGHTING_FIELD_HASHES = {h for h, _, _ in _LIGHTING_FIELDS}

_CONTAINER_ITEMS_HASH = 0x1bf51169  # MapContainer embedded items list field


def _bin_map_container_to_prey(entry: dict) -> dict:
    """Convert a MapContainer bin entry, extracting embedded sun/bake/lighting.

    Returns a dict with 'typeName': 'MapContainer' and nested sub-entries
    for any recognised embedded items (sun properties, bake properties, etc.).
    Raw fields are preserved via 'fields' key for lossless round-trip.
    """
    th = entry.get('type_hash', '')
    result = {
        "pathHash": entry.get('path_hash', ''),
        "typeHash": th,
        "typeName": "MapContainer",
        "fields": _decode_fields_recursive(entry.get('fields', [])),
        "properties": {},
        "embedded": [],
    }

    fields = entry.get('fields', [])
    for f in fields:
        h = f.get('name_hash_int', 0)
        if h == 0:
            try:
                h = int(f.get('name_hash', '0x0'), 16)
            except ValueError:
                pass
        if h != _CONTAINER_ITEMS_HASH:
            continue
        items = f.get('values', [])
        for item in items:
            item_fields = item.get('fields', [])
            if not item_fields:
                continue
            item_hashes = set()
            for sf in item_fields:
                sh = sf.get('name_hash_int', 0)
                if sh == 0:
                    try:
                        sh = int(sf.get('name_hash', '0x0'), 16)
                    except ValueError:
                        pass
                item_hashes.add(sh)

            if item_hashes & _SUN_FIELD_HASHES:
                sub = _extract_fields_to_prey(item_fields, _SUN_FIELDS, "MapSunProperties")
                result["embedded"].append(sub)
                # Also copy sun props directly so the prey loader finds them
                result["properties"].update(sub.get("properties", {}))
            elif item_hashes & _BAKE_FIELD_HASHES:
                sub = _extract_fields_to_prey(item_fields, _BAKE_FIELDS, "MapBakeProperties")
                result["embedded"].append(sub)
                result["properties"].update(sub.get("properties", {}))
            elif item_hashes & _LIGHTING_FIELD_HASHES:
                sub = _extract_fields_to_prey(item_fields, _LIGHTING_FIELDS, "MapLightingV2")
                result["embedded"].append(sub)
                result["properties"].update(sub.get("properties", {}))
        break

    return result


def _extract_fields_to_prey(fields: list, field_defs: list, type_name: str) -> dict:
    """Extract known fields from a field list using field_defs, return prey dict."""
    lookup = {}
    for f in fields:
        h = f.get('name_hash_int', 0)
        if h == 0:
            try:
                h = int(f.get('name_hash', '0x0'), 16)
            except ValueError:
                pass
        lookup[h] = f.get('value')

    props = {}
    for fhash, key, _ in field_defs:
        if fhash in lookup:
            val = lookup[fhash]
            if hasattr(val, '__iter__') and not isinstance(val, str):
                val = list(val)
            props[key] = val

    return {"typeName": type_name, "properties": props}


def _prey_map_entry_to_bin(prey_entry: dict) -> dict:
    """Convert a prey map settings dict back to bin entry."""
    tn = prey_entry.get('typeName', '')
    th = prey_entry.get('typeHash', '')

    if tn == "MapSunProperties":
        field_defs = _SUN_FIELDS
    elif tn == "MapBakeProperties":
        field_defs = _BAKE_FIELDS
    elif tn == "MapLightingV2":
        field_defs = _LIGHTING_FIELDS
    elif tn == "MapContainer":
        # MapContainer: use raw fields if present (lossless round-trip),
        # otherwise fall back to generic (legacy prey files without fields).
        if prey_entry.get('fields'):
            return _prey_generic_to_bin(prey_entry)
        # Legacy prey files with only properties/embedded — reconstruct
        return _prey_map_container_to_bin(prey_entry)
    else:
        return _prey_generic_to_bin(prey_entry)

    props = prey_entry.get('properties', {})
    fields = []
    for fhash, key, type_id in field_defs:
        if key in props:
            fields.append({
                "name_hash": f"0x{fhash:08x}",
                "type": type_id,
                "value": props[key],
            })

    return {
        "path_hash": prey_entry.get('pathHash', ''),
        "type_hash": th,
        "fields": fields,
    }


def _prey_map_container_to_bin(prey_entry: dict) -> dict:
    """Reconstruct a MapContainer bin entry from legacy prey data (properties/embedded only).

    This handles old prey files that were created before raw fields were preserved.
    It rebuilds the embedded items list from the extracted properties.
    """
    th = prey_entry.get('typeHash', '')
    props = prey_entry.get('properties', {})
    embedded = prey_entry.get('embedded', [])

    # Reconstruct embedded items from the extracted sub-entries
    items = []
    for sub in embedded:
        sub_tn = sub.get('typeName', '')
        sub_props = sub.get('properties', {})
        if sub_tn == "MapSunProperties":
            field_defs = _SUN_FIELDS
            class_hash = "0x169a2f9c"
        elif sub_tn == "MapBakeProperties":
            field_defs = _BAKE_FIELDS
            class_hash = "0x6a4a3409"
        elif sub_tn == "MapLightingV2":
            field_defs = _LIGHTING_FIELDS
            class_hash = "0xdca35419"
        else:
            continue
        sub_fields = []
        for fhash, key, type_id in field_defs:
            if key in sub_props:
                sub_fields.append({
                    "name_hash": f"0x{fhash:08x}",
                    "type": type_id,
                    "value": sub_props[key],
                })
        items.append({
            "type": 130,
            "class_hash": class_hash,
            "fields": sub_fields,
        })

    fields = []
    if items:
        fields.append({
            "name_hash": f"0x{_CONTAINER_ITEMS_HASH:08x}",
            "type": 128,
            "value_type": 130,
            "values": items,
        })

    return {
        "path_hash": prey_entry.get('pathHash', ''),
        "type_hash": th,
        "fields": fields,
    }


# ============================================================================
# Core: bin ↔ prey split/merge
# ============================================================================

def _categorise_entry(entry: dict) -> str:
    """Return category string for an entry based on its type hash."""
    th = entry.get('type_hash', '')
    try:
        th_int = int(th, 16)
    except ValueError:
        return "extra"
    _, category = TYPE_REGISTRY.get(th_int, (th, "extra"))
    return category


def bin_to_prey(bin_path: str, output_dir: str, base_name: Optional[str] = None) -> dict:
    """Convert a .materials.bin to split .prey.* files.

    Args:
        bin_path: Path to .materials.bin file
        output_dir: Directory to write .prey.* files
        base_name: Base name for output files (default: derived from bin_path)

    Returns:
        Dict with category → filepath for each created file.
    """
    from . import propertybin_parser

    if base_name is None:
        fname = os.path.basename(bin_path)
        base_name = fname.replace('.materials.bin', '')

    data = propertybin_parser.parse_bin(bin_path)
    entries = data.get('entries', [])

    # Track bin header info for perfect round-trip
    header = {
        "magic": data.get('magic', 'PROP'),
        "version": data.get('version', 2),
        "linked_files": data.get('linked_files', []),
    }

    # Categorise entries
    buckets = {
        "materials": [],
        "vfx": [],
        "map": [],
        "visibility": [],
        "extra": [],
    }
    # Preserve original order for round-trip
    entry_order = []

    for idx, entry in enumerate(entries):
        cat = _categorise_entry(entry)
        buckets[cat].append(entry)
        order_item = {
            "index": idx,
            "category": cat,
            "typeHash": entry.get('type_hash', ''),
            "pathHash": entry.get('path_hash', ''),
        }
        # For materials, include the name for disambiguation (pathHash can collide)
        if cat == "materials":
            for f in entry.get('fields', []):
                if f.get('name_hash') == '0x8d39bde6':
                    order_item["name"] = f.get('value', '')
                    break
        entry_order.append(order_item)

    os.makedirs(output_dir, exist_ok=True)
    created = {}

    # ── Materials ──
    mat_list = []
    for entry in buckets["materials"]:
        prey_mat = _bin_material_to_prey(entry)
        mat_list.append(prey_mat)
    mat_list.sort(key=lambda m: m.get("name", ""))

    mat_data = {
        "format": "prey.materials",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "count": len(mat_list),
        "materials": mat_list,
    }
    mat_path = os.path.join(output_dir, f"{base_name}.prey.materials")
    _write_json(mat_path, mat_data)
    created["materials"] = mat_path

    # ── VFX ──
    vfx_entries = []
    for entry in buckets["vfx"]:
        vfx_entries.append(_generic_entry_to_prey(entry))

    vfx_data = {
        "format": "prey.vfx",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "count": len(vfx_entries),
        "entries": vfx_entries,
    }
    vfx_path = os.path.join(output_dir, f"{base_name}.prey.vfx")
    _write_json(vfx_path, vfx_data)
    created["vfx"] = vfx_path

    # ── Map ──
    map_entries = []
    for entry in buckets["map"]:
        map_entries.append(_bin_map_entry_to_prey(entry))

    map_data = {
        "format": "prey.map",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "count": len(map_entries),
        "entries": map_entries,
    }
    map_path = os.path.join(output_dir, f"{base_name}.prey.map")
    _write_json(map_path, map_data)
    created["map"] = map_path

    # ── Visibility ──
    vis_entries = []
    for entry in buckets["visibility"]:
        vis_entries.append(_generic_entry_to_prey(entry))

    vis_data = {
        "format": "prey.visibility",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "count": len(vis_entries),
        "entries": vis_entries,
    }
    vis_path = os.path.join(output_dir, f"{base_name}.prey.visibility")
    _write_json(vis_path, vis_data)
    created["visibility"] = vis_path

    # ── Extra ──
    extra_entries = []
    for entry in buckets["extra"]:
        extra_entries.append(_generic_entry_to_prey(entry))

    extra_data = {
        "format": "prey.extra",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "count": len(extra_entries),
        "entries": extra_entries,
    }
    extra_path = os.path.join(output_dir, f"{base_name}.prey.extra")
    _write_json(extra_path, extra_data)
    created["extra"] = extra_path

    # ── Manifest (for round-trip) ──
    manifest = {
        "format": "prey.manifest",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(bin_path),
        "header": header,
        "entryOrder": entry_order,
        "totalEntries": len(entries),
        "files": {k: os.path.basename(v) for k, v in created.items()},
    }
    manifest_path = os.path.join(output_dir, f"{base_name}.prey.manifest")
    _write_json(manifest_path, manifest)
    created["manifest"] = manifest_path

    summary = {cat: len(buckets[cat]) for cat in buckets}
    print(f"[PREY] Converted {os.path.basename(bin_path)} → {sum(summary.values())} entries")
    for cat, count in summary.items():
        if count:
            print(f"  {cat}: {count}")

    return created


def prey_to_bin(prey_dir: str, base_name: str, output_path: str):
    """Merge .prey.* files back into a .materials.bin.

    Reads the manifest for original entry order, then rebuilds all entries
    and writes via propertybin_parser.write_bin().
    """
    from . import propertybin_parser

    # Load manifest
    manifest_path = os.path.join(prey_dir, f"{base_name}.prey.manifest")
    manifest = _read_json(manifest_path)
    header = manifest.get("header", {"magic": "PROP", "version": 2, "linked_files": []})
    entry_order = manifest.get("entryOrder", [])

    # Load all prey files
    prey_data = {}
    for cat in ("materials", "vfx", "map", "visibility", "extra"):
        fpath = os.path.join(prey_dir, f"{base_name}.prey.{cat}")
        if os.path.exists(fpath):
            prey_data[cat] = _read_json(fpath)

    # Build lookup tables keyed by name (materials) or pathHash (others)
    mat_lookup = {}  # name → prey material dict
    for mat in prey_data.get("materials", {}).get("materials", []):
        mat_lookup[mat.get("name", "")] = mat

    generic_lookups = {}  # cat → {pathHash → prey entry}
    for cat in ("vfx", "visibility", "extra"):
        lookup = {}
        for e in prey_data.get(cat, {}).get("entries", []):
            ph = e.get("pathHash", "")
            lookup[ph] = e
        generic_lookups[cat] = lookup

    map_lookup = {}
    for e in prey_data.get("map", {}).get("entries", []):
        ph = e.get("pathHash", "")
        map_lookup[ph] = e

    # Reconstruct entries in original order using pathHash for exact matching
    entries = []
    consumed = set()  # track consumed pathHashes to avoid duplicates

    for order_item in entry_order:
        cat = order_item.get("category", "extra")
        ph = order_item.get("pathHash", "")

        if cat == "materials":
            mat_name = order_item.get("name", "")
            if mat_name in mat_lookup:
                entries.append(_prey_material_to_bin(mat_lookup[mat_name]))
                consumed.add(("materials", mat_name))
        elif cat == "map" and ph in map_lookup:
            entries.append(_prey_map_entry_to_bin(map_lookup[ph]))
            consumed.add(("map", ph))
        elif cat in generic_lookups and ph in generic_lookups.get(cat, {}):
            entries.append(_prey_generic_to_bin(generic_lookups[cat][ph]))
            consumed.add((cat, ph))

    # Append new entries not in original order (added in prey)
    for name, mat in mat_lookup.items():
        if ("materials", name) not in consumed:
            entries.append(_prey_material_to_bin(mat))
    for ph, me in map_lookup.items():
        if ("map", ph) not in consumed:
            entries.append(_prey_map_entry_to_bin(me))
    for cat in ("vfx", "visibility", "extra"):
        for ph, ge in generic_lookups.get(cat, {}).items():
            if (cat, ph) not in consumed:
                entries.append(_prey_generic_to_bin(ge))

    bin_data = {
        "magic": header.get("magic", "PROP"),
        "version": header.get("version", 2),
        "linked_files": header.get("linked_files", []),
        "entries": entries,
    }

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    propertybin_parser.write_bin(bin_data, output_path)
    print(f"[PREY] Merged {len(entries)} entries → {os.path.basename(output_path)}")


# ============================================================================
# .materials.py → prey conversion
# ============================================================================

def py_to_prey(py_path: str, output_dir: str, base_name: Optional[str] = None) -> dict:
    """Convert a .materials.py to split .prey.* files.

    Uses the materials_parser to extract StaticMaterialDef entries in clean format,
    and preserves other entries (VFX, MPC, sun, etc.) via generic conversion.
    """
    from .materials_parser import MaterialsParser

    if base_name is None:
        fname = os.path.basename(py_path)
        base_name = fname.replace('.materials.py', '')

    parser = MaterialsParser(py_path)
    materials = parser.parse()  # dict of name → Material
    # other_entries: Dict[str, Tuple[str, str]] → name → (type_name, full_text)
    other_entries = parser.other_entries
    entry_order = parser.entry_order  # list of (name, entry_type_name)

    os.makedirs(output_dir, exist_ok=True)
    created = {}

    # ── Materials ──
    mat_list = []
    for mat_name, mat_obj in sorted(materials.items()):
        prey_mat = {
            "name": mat_obj.name,
            "type": mat_obj.type,
            "samplers": [s.to_dict() for s in mat_obj.samplerValues],
            "params": [p.to_dict() for p in mat_obj.paramValues],
            "switches": [s.to_dict() for s in mat_obj.switches],
        }
        if mat_obj.shaderMacros:
            prey_mat["shaderMacros"] = mat_obj.shaderMacros
        if mat_obj.techniques:
            prey_mat["techniques"] = [t.to_dict() for t in mat_obj.techniques]
        if mat_obj.childTechniques:
            prey_mat["childTechniques"] = [ct.to_dict() for ct in mat_obj.childTechniques]
        if mat_obj.dynamicMaterial:
            prey_mat["dynamicMaterial"] = mat_obj.dynamicMaterial
        prey_mat["_pathHash"] = ""  # .py doesn't have path hashes
        mat_list.append(prey_mat)

    mat_data = {
        "format": "prey.materials",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(py_path),
        "count": len(mat_list),
        "materials": mat_list,
    }
    mat_path = os.path.join(output_dir, f"{base_name}.prey.materials")
    _write_json(mat_path, mat_data)
    created["materials"] = mat_path

    # ── Categorise other entries ──
    # other_entries: name → (type_name_str, full_text_str)
    buckets = {"vfx": [], "map": [], "visibility": [], "extra": []}

    for entry_name, (type_name, full_text) in other_entries.items():
        # Resolve type name to hash if known
        th = TYPE_NAME_TO_HASH.get(type_name, "")
        try:
            th_int = int(th, 16) if th.startswith('0x') else 0
        except ValueError:
            th_int = 0

        _, cat = TYPE_REGISTRY.get(th_int, (type_name, "extra"))

        prey_entry = {
            "pathHash": "",
            "typeHash": th,
            "typeName": type_name,
            "entryName": entry_name,
            "fullText": full_text,
            "_sourceFormat": "py",
        }
        buckets[cat].append(prey_entry)

    for cat in ("vfx", "map", "visibility", "extra"):
        file_data = {
            "format": f"prey.{cat}",
            "version": PREY_FORMAT_VERSION,
            "source": os.path.basename(py_path),
            "count": len(buckets[cat]),
            "entries": buckets[cat],
        }
        fpath = os.path.join(output_dir, f"{base_name}.prey.{cat}")
        _write_json(fpath, file_data)
        created[cat] = fpath

    # ── Manifest ──
    py_order = [{"name": n, "type": t} for n, t in entry_order]
    manifest = {
        "format": "prey.manifest",
        "version": PREY_FORMAT_VERSION,
        "source": os.path.basename(py_path),
        "sourceFormat": "py",
        "entryOrder": py_order,
        "totalEntries": len(entry_order),
        "files": {k: os.path.basename(v) for k, v in created.items()},
    }
    manifest_path = os.path.join(output_dir, f"{base_name}.prey.manifest")
    _write_json(manifest_path, manifest)
    created["manifest"] = manifest_path

    counts = {"materials": len(mat_list)}
    for cat in ("vfx", "map", "visibility", "extra"):
        counts[cat] = len(buckets[cat])
    total = sum(counts.values())
    print(f"[PREY] Converted {os.path.basename(py_path)} → {total} entries")
    for cat, count in counts.items():
        if count:
            print(f"  {cat}: {count}")

    return created


# ============================================================================
# Utility: JSON I/O
# ============================================================================

def _write_json(path: str, data: dict):
    """Write a dict as formatted JSON."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=_json_default)


def _read_json(path: str) -> dict:
    """Read a JSON file to dict."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _json_default(obj):
    """Handle non-serializable types."""
    if hasattr(obj, '__iter__'):
        return list(obj)
    return str(obj)


# ============================================================================
# Supplement prey from .py (add missing map entries like sun/bake/lighting)
# ============================================================================

def supplement_prey_from_py(prey_dir: str, base_name: str, py_path: str) -> int:
    """Add missing map/vfx/extra entries from a .materials.py into existing prey files.

    Checks the prey.map file for MapSunProperties/MapBakeProperties/MapLightingV2.
    If missing, parses the .py and appends them.

    Returns the number of entries added.
    """
    from .materials_parser import MaterialsParser

    map_path = os.path.join(prey_dir, f"{base_name}.prey.map")
    if not os.path.isfile(map_path):
        return 0
    if not os.path.isfile(py_path):
        return 0

    map_data = _read_json(map_path)
    existing_types = set()
    for e in map_data.get("entries", []):
        tn = e.get("typeName", "")
        if tn:
            existing_types.add(tn)

    # Determine which map types are missing
    needed_types = {"MapSunProperties", "MapBakeProperties", "MapLightingV2"} - existing_types
    if not needed_types:
        return 0

    # Parse the .py to find those entries
    parser = MaterialsParser(py_path)
    parser.parse()
    other_entries = parser.other_entries  # name → (type_name, full_text)

    added = 0
    for entry_name, (type_name, full_text) in other_entries.items():
        if type_name not in needed_types:
            continue

        th = TYPE_NAME_TO_HASH.get(type_name, "")
        prey_entry = {
            "pathHash": "",
            "typeHash": th,
            "typeName": type_name,
            "entryName": entry_name,
            "fullText": full_text,
            "_sourceFormat": "py",
        }
        map_data["entries"].append(prey_entry)
        map_data["count"] = len(map_data["entries"])
        added += 1
        print(f"[PREY] Supplemented {type_name} from .materials.py")

    if added:
        _write_json(map_path, map_data)

    return added


def find_py_sibling(prey_dir: str) -> str:
    """Find a .materials.py or .materials_old.py file next to the prey directory."""
    import glob
    parent = os.path.dirname(prey_dir)
    for pattern in ('*.materials.py', '*.materials_old.py', '*.materials_old_*.py',
                    '*.materials_new.py'):
        matches = glob.glob(os.path.join(parent, pattern))
        if matches:
            return matches[0]
    return ""


def _load_prey_map_settings_core(prey_dir: str, base_name: str) -> dict:
    """Core loader: parse map settings from the prey.map file without auto-supplement."""
    import re as _re

    map_path = os.path.join(prey_dir, f"{base_name}.prey.map")
    if not os.path.isfile(map_path):
        return {}

    map_data = _read_json(map_path)
    settings = {}

    for entry in map_data.get("entries", []):
        tn = entry.get("typeName", "")

        if entry.get("_sourceFormat") == "py" and entry.get("fullText"):
            # Parse from .py raw text
            body = entry["fullText"]

            if tn == "MapSunProperties":
                _parse_py_sun_properties(body, settings, _re)
            elif tn == "MapBakeProperties":
                _parse_py_bake_properties(body, settings, _re)
            elif tn == "MapLightingV2":
                _parse_py_lighting_v2(body, settings, _re)

        elif "properties" in entry:
            # Parse from bin-decoded properties
            props = entry["properties"]

            if tn == "MapSunProperties":
                _PROP_MAP_SUN = {
                    "sunColor": "sun_color",
                    "sunDirection": "sun_direction",
                    "skyLightColor": "sky_light_color",
                    "horizonColor": "horizon_color",
                    "groundColor": "ground_color",
                    "skyLightScale": "sky_light_scale",
                    "lightMapColorScale": "lightmap_color_scale",
                    "fogEnabled": "fog_enabled",
                    "fogColor": "fog_color",
                    "fogAlternateColor": "fog_alternate_color",
                    "fogStartAndEnd": "fog_start_end",
                }
                for prey_key, scene_key in _PROP_MAP_SUN.items():
                    if prey_key in props:
                        settings[scene_key] = props[prey_key]

            elif tn == "MapBakeProperties":
                _PROP_MAP_BAKE = {
                    "lightGridSize": "light_grid_size",
                    "lightGridFileName": "light_grid_file",
                    "RmaStaticLightGridTexturePath": "rma_light_grid_texture",
                    "RmaStaticLightGridIntensityScale": "rma_light_grid_intensity_scale",
                    "lightGridCharacterFullBrightIntensity": "light_grid_fullbright",
                }
                for prey_key, scene_key in _PROP_MAP_BAKE.items():
                    if prey_key in props:
                        settings[scene_key] = props[prey_key]

            elif tn == "MapLightingV2":
                if "MinimumEnvironmentColorContribution" in props:
                    settings["min_env_color_contribution"] = props["MinimumEnvironmentColorContribution"]

            elif tn == "MapContainer":
                # MapContainer merges all sun/bake/lighting props into one dict
                _PROP_MAP_ALL = {
                    "sunColor": "sun_color",
                    "sunDirection": "sun_direction",
                    "skyLightColor": "sky_light_color",
                    "horizonColor": "horizon_color",
                    "groundColor": "ground_color",
                    "skyLightScale": "sky_light_scale",
                    "lightMapColorScale": "lightmap_color_scale",
                    "fogEnabled": "fog_enabled",
                    "fogColor": "fog_color",
                    "fogAlternateColor": "fog_alternate_color",
                    "fogStartAndEnd": "fog_start_end",
                    "lightGridSize": "light_grid_size",
                    "lightGridFileName": "light_grid_file",
                    "RmaStaticLightGridTexturePath": "rma_light_grid_texture",
                    "RmaStaticLightGridIntensityScale": "rma_light_grid_intensity_scale",
                    "lightGridCharacterFullBrightIntensity": "light_grid_fullbright",
                    "MinimumEnvironmentColorContribution": "min_env_color_contribution",
                }
                for prey_key, scene_key in _PROP_MAP_ALL.items():
                    if prey_key in props:
                        settings[scene_key] = props[prey_key]

    return settings


def load_prey_map_settings(prey_dir: str, base_name: str) -> dict:
    """Load map settings (sun, fog, bake, lighting) from .prey.map file.

    Returns a dict compatible with import_mapgeo's create_scene_lighting():
        sun_color, sun_direction, sky_light_color, horizon_color, ground_color,
        sky_light_scale, lightmap_color_scale, fog_enabled, fog_color,
        fog_alternate_color, fog_start_end, light_grid_size, etc.

    If the prey.map has no MapSunProperties, automatically supplements from a
    sibling .materials.py file (handles legacy bins with type_hash=0).
    """
    settings = _load_prey_map_settings_core(prey_dir, base_name)

    # Auto-supplement: if no sun properties found, try to pull from sibling .py
    if 'sun_direction' not in settings:
        py_path = find_py_sibling(prey_dir)
        if py_path:
            added = supplement_prey_from_py(prey_dir, base_name, py_path)
            if added:
                settings = _load_prey_map_settings_core(prey_dir, base_name)

    return settings

# Store unwrapped version to avoid infinite recursion on re-read
load_prey_map_settings.__wrapped__ = lambda prey_dir, base_name: _load_prey_map_settings_inner(prey_dir, base_name)


def _parse_py_sun_properties(body: str, settings: dict, _re):
    """Parse MapSunProperties from .py full text into settings dict."""
    # vec4 fields
    for field_name, key in [
        ('sunColor', 'sun_color'),
        ('skyLightColor', 'sky_light_color'),
        ('horizonColor', 'horizon_color'),
        ('groundColor', 'ground_color'),
        ('fogColor', 'fog_color'),
        ('fogAlternateColor', 'fog_alternate_color'),
    ]:
        m = _re.search(rf'{field_name}:\s*vec4\s*=\s*\{{\s*([^}}]+)\}}', body)
        if m:
            settings[key] = [float(v.strip()) for v in m.group(1).split(',')]

    # vec3
    m = _re.search(r'sunDirection:\s*vec3\s*=\s*\{\s*([^}]+)\}', body)
    if m:
        settings['sun_direction'] = [float(v.strip()) for v in m.group(1).split(',')]

    # vec2
    m = _re.search(r'fogStartAndEnd:\s*vec2\s*=\s*\{\s*([^}]+)\}', body)
    if m:
        settings['fog_start_end'] = [float(v.strip()) for v in m.group(1).split(',')]

    # f32
    m = _re.search(r'skyLightScale:\s*f32\s*=\s*([\d.eE+-]+)', body)
    if m:
        settings['sky_light_scale'] = float(m.group(1))

    m = _re.search(r'lightMapColorScale:\s*f32\s*=\s*([\d.eE+-]+)', body)
    if m:
        settings['lightmap_color_scale'] = float(m.group(1))

    # bool
    m = _re.search(r'fogEnabled:\s*bool\s*=\s*(\w+)', body)
    if m:
        settings['fog_enabled'] = m.group(1).lower() == 'true'


def _parse_py_bake_properties(body: str, settings: dict, _re):
    """Parse MapBakeProperties from .py full text into settings dict."""
    m = _re.search(r'lightGridSize:\s*u32\s*=\s*(\d+)', body)
    if m:
        settings['light_grid_size'] = int(m.group(1))

    m = _re.search(r'lightGridFileName:\s*string\s*=\s*"([^"]*)"', body)
    if m:
        settings['light_grid_file'] = m.group(1)

    m = _re.search(r'RmaStaticLightGridTexturePath:\s*string\s*=\s*"([^"]*)"', body)
    if m:
        settings['rma_light_grid_texture'] = m.group(1)

    m = _re.search(r'RmaStaticLightGridIntensityScale:\s*f32\s*=\s*([\d.eE+-]+)', body)
    if m:
        settings['rma_light_grid_intensity_scale'] = float(m.group(1))

    m = _re.search(r'lightGridCharacterFullBrightIntensity:\s*f32\s*=\s*([\d.eE+-]+)', body)
    if m:
        settings['light_grid_fullbright'] = float(m.group(1))


def _parse_py_lighting_v2(body: str, settings: dict, _re):
    """Parse MapLightingV2 from .py full text into settings dict."""
    m = _re.search(r'MinimumEnvironmentColorContribution:\s*f32\s*=\s*([\d.eE+-]+)', body)
    if m:
        settings['min_env_color_contribution'] = float(m.group(1))


def save_prey_map_settings(prey_dir: str, base_name: str, settings: dict) -> bool:
    """Write scene map settings back into prey.map entries.

    Updates existing MapSunProperties / MapBakeProperties / MapLightingV2
    entries in prey.map.  Creates new entries if necessary.

    Returns True if prey.map was modified.
    """
    map_path = os.path.join(prey_dir, f"{base_name}.prey.map")
    if not os.path.isfile(map_path):
        return False

    map_data = _read_json(map_path)
    entries = map_data.get("entries", [])
    modified = False

    # Build index of existing type entries
    sun_idx = bake_idx = light_idx = None
    has_map_container = False
    for i, e in enumerate(entries):
        tn = e.get("typeName", "")
        if tn == "MapSunProperties":
            sun_idx = i
        elif tn == "MapBakeProperties":
            bake_idx = i
        elif tn == "MapLightingV2":
            light_idx = i
        elif tn == "MapContainer":
            has_map_container = True
            # Check embedded sub-entries for sun/bake/lighting
            for sub in e.get("embedded", []):
                stn = sub.get("typeName", "")
                if stn == "MapSunProperties" and sun_idx is None:
                    sun_idx = -1  # sentinel: exists inside MapContainer
                elif stn == "MapBakeProperties" and bake_idx is None:
                    bake_idx = -1
                elif stn == "MapLightingV2" and light_idx is None:
                    light_idx = -1
            # Also check properties dict (older prey files)
            props = e.get("properties", {})
            if props and sun_idx is None:
                if any(k in props for k in ("sunColor", "sunDirection", "skyLightColor")):
                    sun_idx = -1
            if props and bake_idx is None:
                if any(k in props for k in ("lightGridSize", "lightGridFileName")):
                    bake_idx = -1
            # Check raw fields for embedded items (new prey files)
            if e.get("fields") and sun_idx is None:
                for f in e.get("fields", []):
                    if f.get("values"):
                        for v in f["values"]:
                            ch = v.get("class_hash", "")
                            if ch == "0x169a2f9c" and sun_idx is None:
                                sun_idx = -1
                            elif ch == "0x6a4a3409" and bake_idx is None:
                                bake_idx = -1
                            elif ch == "0xdca35419" and light_idx is None:
                                light_idx = -1

    # ── MapSunProperties ──
    sun_keys = {
        "sun_color": ("sunColor", "vec4"),
        "sun_direction": ("sunDirection", "vec3"),
        "sky_light_color": ("skyLightColor", "vec4"),
        "horizon_color": ("horizonColor", "vec4"),
        "ground_color": ("groundColor", "vec4"),
        "sky_light_scale": ("skyLightScale", "f32"),
        "lightmap_color_scale": ("lightMapColorScale", "f32"),
        "fog_enabled": ("fogEnabled", "bool"),
        "fog_color": ("fogColor", "vec4"),
        "fog_alternate_color": ("fogAlternateColor", "vec4"),
        "fog_start_end": ("fogStartAndEnd", "vec2"),
    }
    sun_present = any(k in settings for k in sun_keys)
    if sun_present:
        if sun_idx is not None and sun_idx >= 0:
            entry = entries[sun_idx]
        elif sun_idx == -1:
            # Sun properties live inside MapContainer — don't create standalone
            entry = None
        else:
            entry = {
                "pathHash": "",
                "typeHash": TYPE_NAME_TO_HASH.get("MapSunProperties", ""),
                "typeName": "MapSunProperties",
                "entryName": "MapSunProperties",
                "_sourceFormat": "py",
            }
            entries.append(entry)
            sun_idx = len(entries) - 1

        if entry is not None:
            # Build py-style text from settings
            lines = []
            for scene_key, (field_name, field_type) in sun_keys.items():
                val = settings.get(scene_key)
                if val is None:
                    continue
                if field_type in ("vec4", "vec3", "vec2"):
                    val_str = ", ".join(f"{v:g}" for v in val)
                    lines.append(f"    {field_name}: {field_type} = {{ {val_str} }}")
                elif field_type == "f32":
                    lines.append(f"    {field_name}: f32 = {val:g}")
                elif field_type == "bool":
                    lines.append(f"    {field_name}: bool = {'true' if val else 'false'}")

            entry["fullText"] = "\n".join(lines)
            entry["_sourceFormat"] = "py"
            # Remove bin-decoded properties — py text is now authoritative
            entry.pop("properties", None)
            modified = True

    # ── MapBakeProperties ──
    bake_keys = {
        "light_grid_size": ("lightGridSize", "u32"),
        "light_grid_file": ("lightGridFileName", "string"),
        "rma_light_grid_texture": ("RmaStaticLightGridTexturePath", "string"),
        "rma_light_grid_intensity_scale": ("RmaStaticLightGridIntensityScale", "f32"),
        "light_grid_fullbright": ("lightGridCharacterFullBrightIntensity", "f32"),
    }
    bake_present = any(k in settings for k in bake_keys)
    if bake_present:
        if bake_idx is not None and bake_idx >= 0:
            entry = entries[bake_idx]
        elif bake_idx == -1:
            # Bake properties live inside MapContainer — don't create standalone
            entry = None
        else:
            entry = {
                "pathHash": "",
                "typeHash": TYPE_NAME_TO_HASH.get("MapBakeProperties", ""),
                "typeName": "MapBakeProperties",
                "entryName": "MapBakeProperties",
                "_sourceFormat": "py",
            }
            entries.append(entry)
            bake_idx = len(entries) - 1

        if entry is not None:
            lines = []
            for scene_key, (field_name, field_type) in bake_keys.items():
                val = settings.get(scene_key)
                if val is None:
                    continue
                if field_type == "u32":
                    lines.append(f"    {field_name}: u32 = {int(val)}")
                elif field_type == "f32":
                    lines.append(f"    {field_name}: f32 = {val:g}")
                elif field_type == "string":
                    lines.append(f'    {field_name}: string = "{val}"')

            entry["fullText"] = "\n".join(lines)
            entry["_sourceFormat"] = "py"
            entry.pop("properties", None)
            modified = True

    # ── MapLightingV2 ──
    if "min_env_color_contribution" in settings:
        if light_idx is not None and light_idx >= 0:
            entry = entries[light_idx]
        elif light_idx == -1:
            # Lighting properties live inside MapContainer — don't create standalone
            entry = None
        else:
            entry = {
                "pathHash": "",
                "typeHash": TYPE_NAME_TO_HASH.get("MapLightingV2", ""),
                "typeName": "MapLightingV2",
                "entryName": "MapLightingV2",
                "_sourceFormat": "py",
            }
            entries.append(entry)
            light_idx = len(entries) - 1

        if entry is not None:
            val = settings["min_env_color_contribution"]
            entry["fullText"] = f"    MinimumEnvironmentColorContribution: f32 = {val:g}"
            entry["_sourceFormat"] = "py"
            entry.pop("properties", None)
            modified = True

    if modified:
        map_data["count"] = len(entries)
        _write_json(map_path, map_data)

    return modified


# ============================================================================
# Save Blender materials → prey.materials
# ============================================================================

def save_prey_materials(prey_dir: str, base_name: str) -> int:
    """Write Blender material edits back into prey.materials.

    For each Blender material that has a ``league_material_name`` custom
    property, find the corresponding entry in the .prey.materials JSON and
    update samplers, params, switches, and shaderMacros from the Blender
    custom-property JSON strings.  Round-trip metadata (_rawTechniques,
    _pathHash, etc.) is preserved untouched.

    Returns the number of prey entries updated.
    """
    import bpy

    mat_path = os.path.join(prey_dir, f"{base_name}.prey.materials")
    if not os.path.isfile(mat_path):
        return 0

    data = _read_json(mat_path)
    # prey.materials stores material rows under "materials".
    # Keep backward compatibility with older experimental "entries" layout.
    entries = data.get("materials", data.get("entries", []))
    if not entries:
        return 0

    # Build lookup: material name → index in entries list
    name_to_idx = {}
    name_to_idx_lower = {}
    for i, e in enumerate(entries):
        n = e.get("name")
        if n:
            s = str(n)
            name_to_idx[s] = i
            name_to_idx_lower[s.lower()] = i

    def _parse_json_prop(mat, key: str, default):
        """Parse a Blender custom property that may be JSON text or native data.

        Returns (found, value). If parsing fails, found=False.
        """
        if key not in mat.keys():
            return False, None
        raw = mat.get(key)
        if raw is None:
            return True, default
        if isinstance(raw, (dict, list, int, float, bool)):
            return True, raw
        if isinstance(raw, str):
            txt = raw.strip()
            if not txt:
                return True, default
            try:
                return True, json.loads(txt)
            except (json.JSONDecodeError, TypeError):
                return False, None
        return False, None

    updated = 0
    matched_entries = set()

    for bl_mat in bpy.data.materials:
        league_name = str(bl_mat.get("league_material_name", "") or "").strip()
        candidates = []
        if league_name:
            candidates.append(league_name)
        if bl_mat.name:
            candidates.append(str(bl_mat.name))

        idx = None
        for cand in candidates:
            idx = name_to_idx.get(cand)
            if idx is None:
                idx = name_to_idx_lower.get(cand.lower())
            if idx is not None:
                break
        if idx is None or idx in matched_entries:
            continue
        matched_entries.add(idx)
        prey_entry = entries[idx]

        # ── Dirty check: compare current props against load-time snapshot ──
        snapshot_str = bl_mat.get("_material_snapshot", "")
        if snapshot_str:
            try:
                snapshot = json.loads(snapshot_str)
                current = {
                    "samplers": bl_mat.get("samplers", "[]"),
                    "parameters": bl_mat.get("parameters", "[]"),
                    "switches": bl_mat.get("switches", "[]"),
                    "shader_macros": bl_mat.get("shader_macros", "{}"),
                    "techniques": bl_mat.get("techniques", "[]"),
                    "child_techniques": bl_mat.get("child_techniques", "[]"),
                    "type": bl_mat.get("league_material_type", 0),
                }
                if current == snapshot:
                    continue  # Material unchanged since load — skip
            except (json.JSONDecodeError, TypeError):
                pass  # Corrupt snapshot — treat as modified

        changed = False

        # --- Samplers ---
        ok, samplers = _parse_json_prop(bl_mat, "samplers", [])
        if ok and samplers != prey_entry.get("samplers"):
            prey_entry["samplers"] = samplers
            changed = True

        # --- Params ---
        ok, params = _parse_json_prop(bl_mat, "parameters", [])
        if ok and params != prey_entry.get("params"):
            prey_entry["params"] = params
            changed = True

        # --- Switches ---
        ok, switches = _parse_json_prop(bl_mat, "switches", [])
        if ok and switches != prey_entry.get("switches"):
            prey_entry["switches"] = switches
            changed = True

        # --- Shader macros ---
        ok, macros = _parse_json_prop(bl_mat, "shader_macros", {})
        if ok and macros != prey_entry.get("shaderMacros"):
            prey_entry["shaderMacros"] = macros
            changed = True

        # --- Techniques (py-sourced, decoded) ---
        ok, tech = _parse_json_prop(bl_mat, "techniques", [])
        if ok and tech != prey_entry.get("techniques"):
            prey_entry["techniques"] = tech
            changed = True

        ok, ct = _parse_json_prop(bl_mat, "child_techniques", [])
        if ok and ct != prey_entry.get("childTechniques"):
            prey_entry["childTechniques"] = ct
            changed = True

        # --- Material type ---
        if "league_material_type" in bl_mat.keys() and bl_mat.get("league_material_type") != prey_entry.get("type"):
            bl_type = bl_mat.get("league_material_type")
            prey_entry["type"] = bl_type
            changed = True

        if changed:
            updated += 1

    if updated:
        # Preserve the canonical key in case older layouts are encountered.
        if "materials" in data:
            data["materials"] = entries
            data["count"] = len(entries)
        elif "entries" in data:
            data["entries"] = entries
            data["count"] = len(entries)
        _write_json(mat_path, data)

    return updated


# ============================================================================
# Save Blender VFX transforms → prey.vfx
# ============================================================================

def _transforms_differ(a: list, b: list, eps: float = 1e-4) -> bool:
    """Return True if two 16-float transform matrices differ beyond epsilon."""
    if a is None or b is None:
        return a is not b
    if len(a) != len(b):
        return True
    return any(abs(float(x) - float(y)) > eps for x, y in zip(a, b))


def save_prey_vfx_transforms(prey_dir: str, base_name: str) -> int:
    """Write Blender particle position/rotation/scale back into prey.vfx.

    Matches particles using (container_name, system, name_value) and
    updates the transform field in each MapPlaceableContainer item.
    Also syncs visibilityFlags changes.

    Returns the number of particle items updated.
    """
    import bpy
    from collections import defaultdict

    vfx_path = os.path.join(prey_dir, f"{base_name}.prey.vfx")
    if not os.path.isfile(vfx_path):
        return 0

    data = _read_json(vfx_path)
    entries = data.get("entries", [])
    if not entries:
        return 0

    # Collect Blender particle objects
    scene = bpy.context.scene if bpy.context else None
    source_objs = scene.objects if scene is not None else bpy.data.objects
    particle_objs = [o for o in source_objs if o.get("is_particle_system", False)]
    if not particle_objs:
        return 0

    # Build lookup: entry_hash -> list, and (container, system, name) -> list
    lookup = defaultdict(list)
    by_entry_hash = defaultdict(list)
    for obj in sorted(particle_objs, key=lambda o: o.name):
        cname = obj.get("particle_container", "")
        chash = str(obj.get("particle_container_hash", "") or "").lower()
        system = obj.get("particle_system", "")
        name_val = obj.get("particle_name_value", "")
        lookup[(cname, system, name_val)].append(obj)
        if chash:
            lookup[(chash, system, name_val)].append(obj)
        ehash = str(obj.get("particle_entry_hash", "") or "").lower()
        if ehash:
            by_entry_hash[ehash].append(obj)

    updated = 0
    modified = False

    def _field_hash_int(field: dict) -> int:
        h = field.get("name_hash_int")
        if isinstance(h, int):
            return h
        hs = str(field.get("name_hash", "") or "")
        if hs.startswith("0x"):
            try:
                return int(hs, 16)
            except ValueError:
                return 0
        return 0

    def _is_field(field: dict, friendly_name: str, hash_int: int) -> bool:
        if field.get("_name") == friendly_name:
            return True
        return _field_hash_int(field) == hash_int

    def _extract_container_name(mpc_entry: dict) -> str:
        """Resolve MPC container name from entryName or the embedded name field."""
        entry_name = mpc_entry.get("entryName")
        if entry_name:
            return str(entry_name)

        for f in mpc_entry.get("fields") or []:
            if _is_field(f, "name", 0x8d39bde6):
                v = f.get("value")
                if v:
                    return str(v)

        return ""

    for entry in entries:
        if entry.get("typeName") != "MapPlaceableContainer":
            continue

        container_name = _extract_container_name(entry)
        container_path_hash = str(entry.get("pathHash", "") or "").lower()
        fields = entry.get("fields") or []

        # Find the items field (type=134, map/pairs)
        items_field = None
        for f in fields:
            if f.get("type") == 134 and "pairs" in f:
                items_field = f
                break
        if items_field is None:
            continue

        for pair in items_field.get("pairs") or []:
            pair_key_hash = ""
            key_node = pair.get("key") or {}
            if isinstance(key_node, dict):
                kv = key_node.get("value", "")
                if kv:
                    pair_key_hash = str(kv).lower()

            val = pair.get("value") or {}
            val_fields = val.get("fields") or []

            # Extract system and name for matching
            system_link = ""
            name_val = ""
            transform_field = None
            vis_field = None

            for vf in val_fields:
                if _is_field(vf, "system", 0x491e0a9c):
                    sv = vf.get("value", "")
                    system_link = str(sv) if sv else ""
                elif _is_field(vf, "name", 0x8d39bde6):
                    nv = vf.get("value", "")
                    name_val = str(nv) if nv else ""
                elif _is_field(vf, "transform", 0xe1ad931b):
                    transform_field = vf
                elif _is_field(vf, "visibilityFlags", 0xccf79327):
                    vis_field = vf

            # Match to Blender object
            candidates = []

            # 1) Exact by stable item key hash (best match)
            if pair_key_hash:
                candidates = by_entry_hash.get(pair_key_hash) or []

            # 2) Fallback tuple matching
            if not candidates:
                key = (container_name, system_link, name_val)
                candidates = lookup.get(key)
            if not candidates:
                key = (container_name, system_link, "")
                candidates = lookup.get(key)
            if not candidates and container_path_hash:
                key = (container_path_hash, system_link, name_val)
                candidates = lookup.get(key)
            if not candidates and container_path_hash:
                key = (container_path_hash, system_link, "")
                candidates = lookup.get(key)
            if not candidates:
                continue

            obj = candidates.pop(0)

            # ── Dirty check: compare against original transform stored at load ──
            transform_changed = False
            if transform_field is not None:
                orig_str = obj.get("_original_transform", "")
                if orig_str:
                    # Compare current Blender transform against original from bin
                    new_mtx = _blender_to_transform(obj)
                    try:
                        orig_mtx = json.loads(orig_str)
                        if _transforms_differ(new_mtx, orig_mtx):
                            transform_field["value"] = new_mtx
                            transform_changed = True
                    except (json.JSONDecodeError, TypeError):
                        # Corrupt snapshot — fall back to direct comparison
                        if new_mtx != transform_field.get("value"):
                            transform_field["value"] = new_mtx
                            transform_changed = True
                else:
                    # No snapshot — fall back to direct comparison
                    new_mtx = _blender_to_transform(obj)
                    if new_mtx != transform_field.get("value"):
                        transform_field["value"] = new_mtx
                        transform_changed = True

                if transform_changed:
                    modified = True
                    updated += 1

            # Update visibility flags
            vis_changed = False
            bl_vis = obj.get("particle_visibility_flags")
            if bl_vis is not None and vis_field is not None:
                if int(bl_vis) != vis_field.get("value"):
                    vis_field["value"] = int(bl_vis)
                    vis_changed = True
                    modified = True

    if modified:
        _write_json(vfx_path, data)

    return updated


def save_prey_gds_transforms(prey_dir: str, base_name: str) -> int:
    """Write Blender GdsMapObject position/rotation/scale back into prey.vfx.

    Matches map objects using item_key and updates the transform field
    in each MapPlaceableContainer item with class_hash 0xda9e5c0c.

    Returns the number of map object items updated.
    """
    import bpy

    vfx_path = os.path.join(prey_dir, f"{base_name}.prey.vfx")
    if not os.path.isfile(vfx_path):
        return 0

    data = _read_json(vfx_path)
    entries = data.get("entries", [])
    if not entries:
        return 0

    # Collect Blender map object empties
    scene = bpy.context.scene if bpy.context else None
    source_objs = scene.objects if scene is not None else bpy.data.objects
    mo_objs = [o for o in source_objs if o.get("is_map_object", False)]
    if not mo_objs:
        return 0

    # Build lookup: item_key → object
    by_item_key = {}
    for obj in mo_objs:
        ik = str(obj.get("map_object_item_key", "") or "").lower()
        if ik:
            by_item_key[ik] = obj

    updated = 0
    modified = False

    CLASS_GDS = "0xda9e5c0c"

    def _field_hash_int(field: dict) -> int:
        h = field.get("name_hash_int")
        if isinstance(h, int):
            return h
        hs = str(field.get("name_hash", "") or "")
        if hs.startswith("0x"):
            try:
                return int(hs, 16)
            except ValueError:
                return 0
        return 0

    def _is_field(field: dict, friendly_name: str, hash_int: int) -> bool:
        if field.get("_name") == friendly_name:
            return True
        return _field_hash_int(field) == hash_int

    for entry in entries:
        if entry.get("typeName") != "MapPlaceableContainer":
            continue

        fields = entry.get("fields") or []

        # Find the items field (type=134, map/pairs)
        items_field = None
        for f in fields:
            if f.get("type") == 134 and "pairs" in f:
                items_field = f
                break
        if items_field is None:
            continue

        for pair in items_field.get("pairs") or []:
            val = pair.get("value") or {}

            # Check class_hash for GdsMapObject
            class_hash = str(val.get("class_hash", "") or val.get("className", "") or "").lower()
            if class_hash != CLASS_GDS:
                # Also check typeName for prey decoded entries
                if str(val.get("typeName", "")).lower() != "gdsmapobject":
                    continue

            # Get item key for matching
            pair_key_hash = ""
            key_node = pair.get("key") or {}
            if isinstance(key_node, dict):
                kv = key_node.get("value", "")
                if kv:
                    pair_key_hash = str(kv).lower()

            obj = by_item_key.get(pair_key_hash)
            if not obj:
                continue

            val_fields = val.get("fields") or []

            # Find transform field
            transform_field = None
            name_field = None
            type_field = None
            for vf in val_fields:
                if _is_field(vf, "transform", 0xe1ad931b):
                    transform_field = vf
                elif _is_field(vf, "name", 0x8d39bde6):
                    name_field = vf
                elif _is_field(vf, "type", 0x5127f14d):
                    type_field = vf

            # Dirty check: compare against original transform
            if transform_field is not None:
                orig_str = obj.get("_original_transform", "")
                new_mtx = _blender_to_transform(obj)
                transform_changed = False
                if orig_str:
                    try:
                        orig_mtx = json.loads(orig_str)
                        if _transforms_differ(new_mtx, orig_mtx):
                            transform_field["value"] = new_mtx
                            transform_changed = True
                    except (json.JSONDecodeError, TypeError):
                        if new_mtx != transform_field.get("value"):
                            transform_field["value"] = new_mtx
                            transform_changed = True
                else:
                    if new_mtx != transform_field.get("value"):
                        transform_field["value"] = new_mtx
                        transform_changed = True

                if transform_changed:
                    modified = True
                    updated += 1

            # Sync name changes
            new_name = obj.get("map_object_name", "")
            if new_name and name_field is not None:
                if name_field.get("value") != new_name:
                    name_field["value"] = new_name
                    modified = True

            # Sync type changes
            new_type = obj.get("map_object_type")
            if new_type is not None and type_field is not None:
                try:
                    new_val = int(new_type)
                    if type_field.get("value") != new_val:
                        type_field["value"] = new_val
                        modified = True
                except (ValueError, TypeError):
                    pass

    if modified:
        _write_json(vfx_path, data)

    return updated


def save_prey_vfx_definitions(prey_dir: str, base_name: str) -> int:
    """Write Blender VFX definition edits back into prey.vfx.

    Supports both py-style entries (fullText) and bin-decoded entries (fields).
    Matching prefers vfx_entry_hash, then vfx_name.
    """
    import bpy

    vfx_path = os.path.join(prey_dir, f"{base_name}.prey.vfx")
    if not os.path.isfile(vfx_path):
        return 0

    data = _read_json(vfx_path)
    entries = data.get("entries", [])
    if not entries:
        return 0

    vfx_objs = [o for o in bpy.data.objects if o.get("is_vfx_definition", False)]
    if not vfx_objs:
        return 0

    by_hash = {}
    by_name = {}
    for obj in vfx_objs:
        h = str(obj.get("vfx_entry_hash", "") or "").lower()
        n = str(obj.get("vfx_name", "") or "")
        if h:
            by_hash[h] = obj
        if n:
            by_name[n] = obj

    def _entry_name(entry: dict) -> str:
        n = entry.get("entryName")
        if n:
            return str(n)
        for f in entry.get("fields") or []:
            h = f.get("name_hash_int")
            if h == 0x8d39bde6 or str(f.get("name_hash", "")).lower() == "0x8d39bde6":
                v = f.get("value", "")
                if v:
                    return str(v)
        return ""

    updated = 0
    modified = False

    for entry in entries:
        if entry.get("typeName") != "VfxSystemDefinitionData":
            continue

        obj = None
        ph = str(entry.get("pathHash", "") or "").lower()
        if ph and ph in by_hash:
            obj = by_hash[ph]
        if obj is None:
            ename = _entry_name(entry)
            if ename and ename in by_name:
                obj = by_name[ename]
        if obj is None:
            continue

        changed = False

        # Name update if available
        new_name = str(obj.get("vfx_name", "") or "")
        if new_name:
            if entry.get("entryName") and entry.get("entryName") != new_name:
                entry["entryName"] = new_name
                changed = True

        # Bin-style field update — check against snapshot to detect real edits
        fields_json = obj.get("vfx_fields_json")
        if fields_json:
            snapshot = obj.get("_vfx_fields_snapshot", "")
            if fields_json != snapshot:
                try:
                    new_fields = json.loads(fields_json)
                    if isinstance(new_fields, list):
                        entry["fields"] = new_fields
                        changed = True
                except (json.JSONDecodeError, TypeError):
                    pass

        # Py-style fullText update
        block_text = obj.get("vfx_block_text")
        if block_text and entry.get("fullText") is not None and entry.get("fullText") != block_text:
            entry["fullText"] = str(block_text)
            changed = True

        if changed:
            modified = True
            updated += 1

    if modified:
        _write_json(vfx_path, data)

    return updated


def _blender_to_transform(obj) -> list:
    """Build a 16-float mtx44 (column-major) from Blender object transform.

    Uses the same conversion matrix approach as mapgeo export:
    mat_league = conversion @ mat_blender @ conversion
    where conversion swaps Y↔Z axes (self-inverse).
    Particle objects use identity scale (display scale is visual-only).
    """
    from mathutils import Matrix, Euler

    loc = obj.location
    rot = obj.rotation_euler

    # Particle objects have an artificial display scale — use identity
    is_particle = obj.get("is_particle_system", False)
    if is_particle:
        sx, sy, sz = 1.0, 1.0, 1.0
    else:
        sx, sy, sz = obj.scale.x, obj.scale.y, obj.scale.z

    # Build full Blender 4x4 matrix
    mat_rot = Euler((rot.x, rot.y, rot.z), 'XYZ').to_matrix().to_4x4()
    mat_loc = Matrix.Translation(loc)
    mat_scale = Matrix.Diagonal((sx, sy, sz, 1.0))
    mat_blender = mat_loc @ mat_rot @ mat_scale

    # Y↔Z coordinate conversion (self-inverse)
    conversion = Matrix((
        (1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 1, 0, 0),
        (0, 0, 0, 1)
    ))
    mat_league = conversion @ mat_blender @ conversion

    # Flatten to column-major
    return [
        mat_league[0][0], mat_league[1][0], mat_league[2][0], mat_league[3][0],
        mat_league[0][1], mat_league[1][1], mat_league[2][1], mat_league[3][1],
        mat_league[0][2], mat_league[1][2], mat_league[2][2], mat_league[3][2],
        mat_league[0][3], mat_league[1][3], mat_league[2][3], mat_league[3][3],
    ]


# ============================================================================
# Load materials_db from prey (for Blender material creation)
# ============================================================================

# Shader hash → path lookup table.  Bin technique passes store shader
# references as FNV-1a-32 hashes of the full path; py passes store the
# string directly.  This table lets us resolve bin hashes back to paths
# so MaterialLoader's shader dispatch works identically for both sources.
_SHADER_HASH_TO_PATH = {
    0x30e333b5: 'Shaders/StaticMesh/4TextureBlend_WorldProjected',
    0xb965c5a4: 'Shaders/StaticMesh/DefaultEnv_Flat',
    0xeff08973: 'Shaders/StaticMesh/DefaultEnv_Flat_AlphaTest',
    0x0d73b842: 'Shaders/StaticMesh/DefaultEnv_Flat_AlphaTest_DoubleSided',
    0xaf1021c1: 'Shaders/StaticMesh/DefaultEnv_Flat_BakedTerrain',
    0x0c54779c: 'Shaders/StaticMesh/DefaultEnv_Flat_PlanarReflection',
    0xed25f813: 'Shaders/StaticMesh/DefaultEnv_Glass_BlendAndReflection',
    0x01c2231e: 'Shaders/StaticMesh/DefaultEnv_Glow',
    0x95dd2056: 'Shaders/StaticMesh/DefaultEnv_Metal',
    0x197ea776: 'Shaders/StaticMesh/ENV_Glass',
    0x07d0da6b: 'Shaders/StaticMesh/ENV_Glass_Diffuse',
    0x176ea5f1: 'Shaders/StaticMesh/ENV_Glass_Vertex_Offset',
    0x0ebaac0a: 'Shaders/StaticMesh/ENV_GlowSign',
    0x42adf27e: 'Shaders/StaticMesh/ENV_GlowSign_Atlas',
    0x56947b82: 'Shaders/StaticMesh/ENV_UVGradientColorMapping',
    0xe4eebf78: 'Shaders/StaticMesh/Emissive_Basic',
    0xfe12dbf6: 'Shaders/StaticMesh/Env_TwistByNoise',
    0x43893bb2: 'Shaders/StaticMesh/FlowMap_Radial',
    0xc8c7890d: 'Shaders/StaticMesh/Flowmap_River',
    0x220d268d: 'Shaders/StaticMesh/Hologram',
    0x4dd02d45: 'Shaders/StaticMesh/Hologram_Rotate',
    0xef20e7c5: 'Shaders/StaticMesh/Indicator_Faelights',
    0x8bf09e3c: 'Shaders/StaticMesh/OD_FlowMap',
    0x6f53b055: 'Shaders/StaticMesh/SRX_Blend_Chemtech_Decal',
    0x98732205: 'Shaders/StaticMesh/SRX_Blend_Decal_Cloud',
    0x0b09b0dc: 'Shaders/StaticMesh/SRX_Blend_Ocean',
    0x8b183f26: 'Shaders/StaticMesh/SRX_DynamicEffect',
    0xdc91fc13: 'Shaders/StaticMesh/TFT_Env_Rain',
    0x33766fa4: 'Shaders/StaticMesh/TFT_PlanarReflection',
    0x84d04b5d: 'Shaders/StaticMesh/TFT_TwistByNoise',
    0x5d11ef24: 'Shaders/StaticMesh/TFT_Water',
    0x908a4f95: 'Shaders/StaticMesh/VertexDeform',
}

# Also build a reverse lookup (hex-string → path) for hash refs like '0xeff08973'
_SHADER_HEXSTR_TO_PATH = {f'0x{h:08x}': p for h, p in _SHADER_HASH_TO_PATH.items()}


def _resolve_shader_hash(value) -> str:
    """Resolve a shader hash reference to its full path string.

    Accepts integer hashes, hex-string hashes ('0xeff08973'), or
    already-resolved path strings.  Returns the resolved path or
    the original value as a string if unresolvable.
    """
    if isinstance(value, int):
        return _SHADER_HASH_TO_PATH.get(value, f'0x{value:08x}')
    s = str(value)
    if s.startswith('0x'):
        return _SHADER_HEXSTR_TO_PATH.get(s.lower(), s)
    return s


# Actual bin-level field hashes for technique pass fields
# (These differ from the top-level FIELD_NAMES hashes)
_BIN_PASS_SHADER    = 0x355d5568
_BIN_PASS_BLEND     = 0x23b75597
_BIN_PASS_CULL      = 0x4b0f55ce
_BIN_PASS_SRC_COLOR = 0x22c0c7d0
_BIN_PASS_SRC_ALPHA = 0xa0958d01
_BIN_PASS_DST_COLOR = 0xbe0abbf5
_BIN_PASS_DST_ALPHA = 0x7385e534
_BIN_PASS_WRITE_MASK = 0x917e428e
_BIN_TECH_PASSES    = 0x623cd25c
_BIN_TECH_NAME      = 0x8d39bde6


def _extract_techniques_from_raw(raw_techniques: dict) -> list:
    """Extract parsed technique dicts from raw bin technique data.

    Returns list of technique dicts in the same format as py-sourced
    techniques (name, passes with shader/blendEnable/cullEnable etc.).
    """
    techniques = []
    for tech_entry in raw_techniques.get('values', []):
        tech_fields = tech_entry.get('fields', [])
        tech_name = ''
        passes = []

        for f in tech_fields:
            h = f.get('name_hash_int', 0)
            if h == _BIN_TECH_NAME:
                tech_name = f.get('value', '')
            elif h == _BIN_TECH_PASSES:
                for pass_entry in f.get('values', []):
                    pass_fields = pass_entry.get('fields', [])
                    pass_data = {
                        'shader': '',
                        'blendEnable': False,
                        'srcColorBlendFactor': 1,
                        'srcAlphaBlendFactor': 1,
                        'dstColorBlendFactor': 0,
                        'dstAlphaBlendFactor': 0,
                    }
                    for pf in pass_fields:
                        ph = pf.get('name_hash_int', 0)
                        pv = pf.get('value')
                        if ph in (_BIN_PASS_SHADER, _HASH_SHADER_LINK):
                            pass_data['shader'] = _resolve_shader_hash(pv) if pv else ''
                        elif ph in (_BIN_PASS_BLEND, _HASH_BLEND_ENABLE):
                            pass_data['blendEnable'] = bool(pv)
                        elif ph in (_BIN_PASS_CULL, _HASH_CULL_ENABLE):
                            pass_data['cullEnable'] = bool(pv) if pv is not None else False
                        elif ph in (_BIN_PASS_SRC_COLOR, _HASH_SRC_COLOR_BLEND):
                            pass_data['srcColorBlendFactor'] = pv if pv is not None else 1
                        elif ph in (_BIN_PASS_SRC_ALPHA, _HASH_SRC_ALPHA_BLEND):
                            pass_data['srcAlphaBlendFactor'] = pv if pv is not None else 1
                        elif ph in (_BIN_PASS_DST_COLOR, _HASH_DST_COLOR_BLEND):
                            pass_data['dstColorBlendFactor'] = pv if pv is not None else 0
                        elif ph in (_BIN_PASS_DST_ALPHA, _HASH_DST_ALPHA_BLEND):
                            pass_data['dstAlphaBlendFactor'] = pv if pv is not None else 0
                        elif ph in (_BIN_PASS_WRITE_MASK, _HASH_WRITE_MASK):
                            pass_data['writeMask'] = pv
                    passes.append(pass_data)

        techniques.append({'name': tech_name, 'passes': passes})
    return techniques


def _extract_child_techniques_from_raw(raw_child_techniques: dict) -> list:
    """Extract parsed child technique dicts from raw bin data."""
    children = []
    for child_entry in raw_child_techniques.get('values', []):
        child_fields = child_entry.get('fields', [])
        child = {'name': '', 'parentName': '', 'shaderMacros': {}}
        for f in child_fields:
            h = f.get('name_hash_int', 0)
            if h == 0x8d39bde6:  # name
                child['name'] = f.get('value', '')
            elif h == 0xb696a5fe:  # parentName
                child['parentName'] = f.get('value', '')
            elif h == 0xe6d67ded:  # shaderMacros
                if 'pairs' in f:
                    for pair in f['pairs']:
                        k = pair.get('key', {}).get('value', '')
                        v = pair.get('value', {}).get('value', '')
                        child['shaderMacros'][str(k)] = str(v)
        children.append(child)
    return children


def _prey_material_to_db(prey_mat: dict) -> dict:
    """Convert a single prey material entry to the materials_db dict format
    used by MaterialLoader.get_or_create_material().
    """
    # Build switches as both list (switchValues) and dict (switches)
    switch_values = []
    switches_dict = {}
    for sw in prey_mat.get('switches', []):
        on_val = sw.get('on')
        if on_val is None:
            on_val = True
        sw_entry = {'name': sw.get('name', ''), 'on': on_val}
        if 'group' in sw and sw['group'] is not None:
            sw_entry['group'] = sw['group']
        switch_values.append(sw_entry)
        if sw.get('name'):
            switches_dict[sw['name']] = on_val

    # Build sampler values — prey uses 'textureName', db also needs 'TextureName'
    sampler_values = []
    for s in prey_mat.get('samplers', []):
        sampler = {
            'textureName': s.get('textureName', ''),
            'TextureName': s.get('textureName', s.get('TextureName', '')),
            'texturePath': s.get('texturePath', ''),
        }
        if 'addressU' in s:
            sampler['addressU'] = s['addressU']
        if 'addressV' in s:
            sampler['addressV'] = s['addressV']
        if 'addressW' in s:
            sampler['addressW'] = s['addressW']
        sampler_values.append(sampler)

    # Handle techniques — py-sourced has 'techniques', bin-sourced has '_rawTechniques'
    techniques = []
    if 'techniques' in prey_mat and prey_mat['techniques']:
        techniques = prey_mat['techniques']
        # Normalize None → False for blend/cull in py-sourced pass data
        for tech in techniques:
            for p in tech.get('passes', []):
                if p.get('blendEnable') is None:
                    p['blendEnable'] = False
                if p.get('cullEnable') is None:
                    p['cullEnable'] = False
    elif '_rawTechniques' in prey_mat and prey_mat['_rawTechniques']:
        techniques = _extract_techniques_from_raw(prey_mat['_rawTechniques'])

    child_techniques = []
    if 'childTechniques' in prey_mat and prey_mat['childTechniques']:
        child_techniques = prey_mat['childTechniques']
    elif '_rawChildTechniques' in prey_mat and prey_mat['_rawChildTechniques']:
        child_techniques = _extract_child_techniques_from_raw(prey_mat['_rawChildTechniques'])

    # Extract top-level shader/blend/cull from first technique pass
    shader = ''
    blend_enable = False
    cull_enable = False
    if techniques:
        for tech in techniques:
            for p in tech.get('passes', []):
                if p.get('shader'):
                    shader = p['shader']
                    blend_enable = p.get('blendEnable', False)
                    cull_enable = p.get('cullEnable', False)
                    break
            if shader:
                break

    return {
        '__type': 'StaticMaterialDef',
        'name': prey_mat.get('name', ''),
        'type': prey_mat.get('type', 0),
        'samplerValues': sampler_values,
        'paramValues': prey_mat.get('params', []),
        'switchValues': switch_values,
        'switches': switches_dict,
        'shaderMacros': prey_mat.get('shaderMacros', {}),
        'techniques': techniques,
        'childTechniques': child_techniques,
        'shader': shader,
        'blendEnable': blend_enable,
        'cullEnable': cull_enable,
    }


def load_materials_db_from_prey(prey_dir: str, base_name: str) -> dict:
    """Load materials from .prey.materials and return a materials_db dict.

    This is the prey-based equivalent of MaterialLoader.load_materials().

    Args:
        prey_dir: Directory containing .prey.* files
        base_name: Base name for the prey files

    Returns:
        Dict of material_name -> material_data (same format as
        MaterialLoader._load_materials_bin / _load_materials_py)
    """
    mat_path = os.path.join(prey_dir, f"{base_name}.prey.materials")
    if not os.path.isfile(mat_path):
        return {}

    data = _read_json(mat_path)
    materials_db = {}

    for prey_mat in data.get('materials', []):
        mat = _prey_material_to_db(prey_mat)
        name = mat['name']
        if name:
            materials_db[name] = mat

    return materials_db


# ============================================================================
# Standalone CLI
# ============================================================================

def convert(input_path: str, output_dir: Optional[str] = None, base_name: Optional[str] = None) -> dict:
    """Convert a .materials.bin to .prey files.

    Args:
        input_path: Path to .materials.bin
        output_dir: Output directory (default: same directory as input)
        base_name: Base name for files (default: derived from input)

    Returns:
        Dict of category → file path
    """
    if output_dir is None:
        output_dir = os.path.dirname(input_path)

    return bin_to_prey(input_path, output_dir, base_name)


# ============================================================================
# Template-Based Material Migration
# ============================================================================

# Shader link field hash inside technique passes (ObjectLink type 132)
_HASH_SHADER_LINK = 0x355d5568
# Legacy samplerName field hash
_HASH_SAMPLER_NAME_LEGACY = 0x02e7fb4c
# Modern field hashes
_HASH_TEXTURE_NAME = 0xb311d4ef
_HASH_TEXTURE_PATH = 0xf0a363e3
_HASH_NAME = 0x8d39bde6
_HASH_TECHNIQUES = 0x844f384e
_HASH_PASSES = 0x623cd25c
_HASH_SHADER = 0xc5ac22aa
_HASH_SAMPLER_VALUES = 0x0a6f0eb5
_HASH_PARAM_VALUES = 0xd0ab46b8
_HASH_SWITCH_VALUES = 0xdd7ddb9d
_HASH_SHADER_MACROS = 0xe6d67ded
_HASH_MATERIAL_TYPE = 0x5127f14d
_HASH_VALUE = 0x425ed3ca
_HASH_ON = 0x61342fd0
_HASH_GROUP = 0x5fb91e8c
_HASH_ADDRESS_U = 0x111ec6d2
_HASH_ADDRESS_V = 0x101ec53f
_HASH_ADDRESS_W = 0x0f1ec3ac
_HASH_CHILD_TECHNIQUES = 0x9330e6b6
_HASH_BLEND_ENABLE = 0x23b75597   # bin-level: blendEnable
_HASH_CULL_ENABLE = 0x4b0f55ce    # bin-level: cullEnable
_HASH_SRC_COLOR_BLEND = 0x22c0c7d0  # bin-level: srcColorBlendFactor
_HASH_SRC_ALPHA_BLEND = 0xa0958d01  # bin-level: srcAlphaBlendFactor
_HASH_DST_COLOR_BLEND = 0xbe0abbf5  # bin-level: dstColorBlendFactor
_HASH_DST_ALPHA_BLEND = 0x7385e534  # bin-level: dstAlphaBlendFactor
_HASH_WRITE_MASK = 0x917e428e       # bin-level: writeMask
_HASH_PARENT_NAME = 0xb696a5fe

# Old shader prefix → new prefix
_SHADER_PREFIX_REMAP = {
    "Shaders/Environment/": "Shaders/StaticMesh/",
}

_DEFAULT_FALLBACK_SHADER = "Shaders/StaticMesh/DefaultEnv_Flat"


def _load_shader_templates():
    """Load shader_templates_data.json from the addon directory."""
    tpl_path = os.path.join(os.path.dirname(__file__), "shader_templates_data.json")
    if not os.path.isfile(tpl_path):
        return {}
    with open(tpl_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fnv1a_32(s: str) -> int:
    """FNV-1a 32-bit hash (same as propertybin_parser.fnv1a_32)."""
    h = 0x811c9dc5
    for ch in s.encode('utf-8'):
        h = ((h ^ ch) * 0x01000193) & 0xFFFFFFFF
    return h


def _build_shader_hash_table(templates: dict) -> dict:
    """Build a lookup: shader_link_hash_str → (template_path, resolved_shader_path).

    Hashes every template path directly AND with old 'Environment' prefix,
    in both original case and lowercase, so we can resolve old shader link hashes.
    """
    table = {}

    def _add(hash_str, tpl_path, source_path):
        if hash_str not in table:
            table[hash_str] = (tpl_path, source_path)

    for tpl_path in templates:
        short = tpl_path.rsplit("/", 1)[-1]

        # All prefix variants to try
        prefixes = ["Shaders/StaticMesh/", "Shaders/Environment/", "Shaders/"]

        for prefix in prefixes:
            variant = prefix + short
            # Original case
            _add("0x%08x" % _fnv1a_32(variant), tpl_path, variant)
            # Lowercase
            _add("0x%08x" % _fnv1a_32(variant.lower()), tpl_path, variant.lower())

        # Also hash full template path as-is
        _add("0x%08x" % _fnv1a_32(tpl_path), tpl_path, tpl_path)
        _add("0x%08x" % _fnv1a_32(tpl_path.lower()), tpl_path, tpl_path.lower())

    return table


# Manual shader hash overrides for shaders whose names changed between
# old Environment and new StaticMesh versions (name != simple prefix swap).
_SHADER_HASH_OVERRIDES = {
    # Shaders/Environment/DefaultEnv → Shaders/StaticMesh/DefaultEnv_Flat
    "0x2af09534": "Shaders/StaticMesh/DefaultEnv_Flat",
    # shaders/staticmesh/env_glow (no exact template) → DefaultEnv_Glow
    "0x820e2bef": "Shaders/StaticMesh/DefaultEnv_Glow",
    # Hologram_Layered (no template) → closest is Hologram
    "0xcb5aa63a": "Shaders/StaticMesh/Hologram",
}


def _build_shader_hash_table_with_overrides(templates: dict) -> dict:
    """Build shader hash table plus manual overrides for renamed shaders."""
    table = _build_shader_hash_table(templates)
    for h, tpl_path in _SHADER_HASH_OVERRIDES.items():
        if tpl_path in templates:
            table[h] = (tpl_path, f"override:{h}")
    return table


def _get_field(fields: list, hash_val: int):
    """Find a field dict by name_hash integer."""
    h_str = "0x%08x" % hash_val
    for f in fields:
        if f.get('name_hash_int') == hash_val or f.get('name_hash') == h_str:
            return f
    return None


def _get_field_value(fields: list, hash_val: int, default=None):
    """Get a field's value by hash."""
    f = _get_field(fields, hash_val)
    return f.get('value', default) if f else default


def _extract_shader_link_hash(entry: dict) -> Optional[str]:
    """Extract the shader ObjectLink hash from a material's technique passes."""
    tech_f = _get_field(entry.get('fields', []), _HASH_TECHNIQUES)
    if not tech_f:
        return None
    for tech_item in tech_f.get('values', []):
        passes_f = _get_field(tech_item.get('fields', []), _HASH_PASSES)
        if not passes_f:
            continue
        for pass_item in passes_f.get('values', []):
            link_f = _get_field(pass_item.get('fields', []), _HASH_SHADER_LINK)
            if link_f:
                return link_f.get('value')
    return None


def _extract_old_samplers(entry: dict) -> list:
    """Extract sampler data from an old bin entry.

    Handles both old format (samplerName + textureName-as-path) and
    modern format (textureName + texturePath).
    """
    samplers = []
    sf = _get_field(entry.get('fields', []), _HASH_SAMPLER_VALUES)
    if not sf:
        return samplers
    for item in sf.get('values', []):
        flds = item.get('fields', [])
        sampler = {}

        # Old format: samplerName (0x02e7fb4c) has the semantic name,
        #             textureName (0xb311d4ef) has the path
        legacy_name = _get_field_value(flds, _HASH_SAMPLER_NAME_LEGACY)
        texture_name = _get_field_value(flds, _HASH_TEXTURE_NAME)
        texture_path = _get_field_value(flds, _HASH_TEXTURE_PATH)

        if legacy_name is not None:
            # Old format: samplerName = semantic, textureName = path
            sampler["textureName"] = legacy_name
            sampler["texturePath"] = texture_name or ""
        elif texture_path is not None:
            # Modern format already
            sampler["textureName"] = texture_name or ""
            sampler["texturePath"] = texture_path
        else:
            # Ambiguous: textureName might be a path or a semantic name
            val = texture_name or ""
            if "/" in val or "\\" in val or val.endswith(".dds") or val.endswith(".tex"):
                # Looks like a path — use DiffuseTexture as fallback name
                sampler["textureName"] = ""
                sampler["texturePath"] = val
            else:
                sampler["textureName"] = val
                sampler["texturePath"] = ""

        sampler["addressU"] = _get_field_value(flds, _HASH_ADDRESS_U, 1)
        sampler["addressV"] = _get_field_value(flds, _HASH_ADDRESS_V, 1)
        sampler["addressW"] = _get_field_value(flds, _HASH_ADDRESS_W, 1)
        samplers.append(sampler)
    return samplers


def _extract_old_params(entry: dict) -> list:
    """Extract parameter values from an old bin entry."""
    params = []
    pf = _get_field(entry.get('fields', []), _HASH_PARAM_VALUES)
    if not pf:
        return params
    for item in pf.get('values', []):
        flds = item.get('fields', [])
        name = _get_field_value(flds, _HASH_NAME, "")
        value = _get_field_value(flds, _HASH_VALUE)
        if isinstance(value, list):
            value = list(value)
        params.append({"name": name, "value": value})
    return params


def _extract_old_switches(entry: dict) -> list:
    """Extract switch values from an old bin entry."""
    switches = []
    swf = _get_field(entry.get('fields', []), _HASH_SWITCH_VALUES)
    if not swf:
        return switches
    for item in swf.get('values', []):
        flds = item.get('fields', [])
        sw = {}
        sname = _get_field_value(flds, _HASH_NAME)
        if sname is not None:
            sw["name"] = sname
        son = _get_field_value(flds, _HASH_ON)
        if son is not None:
            sw["on"] = son
        sgroup = _get_field_value(flds, _HASH_GROUP)
        if sgroup is not None:
            sw["group"] = sgroup
        switches.append(sw)
    return switches


def _mkfield(hash_val: int, type_id: int, value):
    """Create a bin field dict."""
    return {"name_hash": "0x%08x" % hash_val, "type": type_id, "value": value}


def _mkembed(class_hash: str, fields: list):
    """Create an embedded struct."""
    return {"type": 0x83, "class_hash": class_hash, "fields": fields}


def _build_technique_bin(shader_path: str, blend: dict) -> dict:
    """Build a technique field with the shader path as a proper ObjectLink."""
    shader_hash = "0x%08x" % _fnv1a_32(shader_path)

    pass_fields = [
        _mkfield(_HASH_SHADER_LINK, 132, shader_hash),  # ObjectLink
    ]
    if blend.get("blendEnable"):
        pass_fields.append(_mkfield(_HASH_BLEND_ENABLE, 1, True))
        pass_fields.append(_mkfield(_HASH_CULL_ENABLE, 1, bool(blend.get("cullEnable", False))))
        pass_fields.append(_mkfield(_HASH_SRC_COLOR_BLEND, 7, blend.get("srcColorBlendFactor", 1)))
        pass_fields.append(_mkfield(_HASH_DST_COLOR_BLEND, 7, blend.get("dstColorBlendFactor", 0)))
        pass_fields.append(_mkfield(_HASH_SRC_ALPHA_BLEND, 7, blend.get("srcAlphaBlendFactor", 1)))
        pass_fields.append(_mkfield(_HASH_DST_ALPHA_BLEND, 7, blend.get("dstAlphaBlendFactor", 0)))
    elif "cullEnable" in blend:
        pass_fields.append(_mkfield(_HASH_CULL_ENABLE, 1, bool(blend["cullEnable"])))

    pass_struct = _mkembed("0x8537d0c2", pass_fields)
    technique = _mkembed("0x060a4413", [
        _mkfield(_HASH_NAME, 16, "normal"),
        {
            "name_hash": "0x%08x" % _HASH_PASSES,
            "type": 0x80, "value_type": 0x83,
            "values": [pass_struct],
        },
    ])
    return {
        "name_hash": "0x%08x" % _HASH_TECHNIQUES,
        "type": 0x80, "value_type": 0x83,
        "values": [technique],
    }


def _build_child_techniques_bin(child_names: list) -> dict:
    """Build child techniques field from a list of technique names."""
    children = []
    for cn in child_names:
        child_fields = [
            _mkfield(_HASH_NAME, 16, cn),
            _mkfield(_HASH_PARENT_NAME, 16, "normal"),
        ]
        children.append(_mkembed("0x735b4c95", child_fields))
    return {
        "name_hash": "0x%08x" % _HASH_CHILD_TECHNIQUES,
        "type": 0x80, "value_type": 0x83,
        "values": children,
    }


def migrate_material_entry(entry: dict, templates: dict = None,
                           shader_table: dict = None,
                           fallback_shader: str = None) -> dict:
    """Migrate an old StaticMaterialDef bin entry using shader templates.

    Steps:
        1. Extract shader ObjectLink hash from technique passes
        2. Resolve hash → shader template path (trying old Environment prefix)
        3. Load template defaults (samplers, params, switches, macros, blend)
        4. Override template with old material's actual values:
            - Material name preserved
            - Old samplers override template samplers by textureName slot
            - Old params override template params by name
            - Old switches override template switches by name
        5. Rebuild technique with correct modern shader path + blend

    Returns a new fully-formed bin entry dict.
    """
    if templates is None:
        templates = _load_shader_templates()
    if shader_table is None:
        shader_table = _build_shader_hash_table_with_overrides(templates)
    if fallback_shader is None:
        fallback_shader = _DEFAULT_FALLBACK_SHADER

    old_fields = entry.get('fields', [])
    mat_name = _get_field_value(old_fields, _HASH_NAME, entry.get('path_hash', ''))
    mat_type = _get_field_value(old_fields, _HASH_MATERIAL_TYPE, 0)

    # Step 1: Resolve shader
    shader_link = _extract_shader_link_hash(entry)
    template_path = fallback_shader
    resolved_from = "fallback"

    if shader_link and shader_link in shader_table:
        template_path, original_path = shader_table[shader_link]
        resolved_from = original_path
    elif shader_link:
        resolved_from = f"unresolved:{shader_link}"

    tpl = templates.get(template_path, {})

    # Step 2: Read old material values
    old_samplers = _extract_old_samplers(entry)
    old_params = _extract_old_params(entry)
    old_switches = _extract_old_switches(entry)

    # Step 3: Build from template, override with old values

    # --- Samplers: match by textureName slot, keeping template defaults ---
    tpl_samplers = []
    for ts in tpl.get("samplers", []):
        tpl_samplers.append({
            "textureName": ts["name"],
            "texturePath": "",
            "addressU": ts.get("addressU", 1),
            "addressV": ts.get("addressV", 1),
            "addressW": ts.get("addressW", 1),
        })

    # Build lookup of old samplers by their semantic name
    old_sampler_by_name = {}
    for os_ in old_samplers:
        sn = os_.get("textureName", "")
        if sn:
            old_sampler_by_name[sn] = os_

    # Override template samplers with old values where names match
    merged_samplers = []
    used_old_names = set()
    for ts in tpl_samplers:
        slot_name = ts["textureName"]
        old_s = old_sampler_by_name.get(slot_name)
        if old_s:
            # Override: keep template's textureName, apply old texturePath + addresses
            merged = {
                "textureName": slot_name,
                "texturePath": old_s.get("texturePath", ts.get("texturePath", "")),
                "addressU": old_s.get("addressU", ts.get("addressU", 1)),
                "addressV": old_s.get("addressV", ts.get("addressV", 1)),
                "addressW": old_s.get("addressW", ts.get("addressW", 1)),
            }
            merged_samplers.append(merged)
            used_old_names.add(slot_name)
        else:
            # Keep template default (no old override)
            merged_samplers.append(ts)

    # Append any old samplers with names not in the template
    for os_ in old_samplers:
        sn = os_.get("textureName", "")
        if sn and sn not in used_old_names:
            merged_samplers.append(os_)

    # --- Params: match by name, override value ---
    tpl_params = []
    for tp in tpl.get("parameters", []):
        tpl_params.append({
            "name": tp["name"],
            "value": tp.get("value", [0, 0, 0, 0]),
        })

    old_param_by_name = {p["name"]: p for p in old_params if p.get("name")}
    merged_params = []
    used_param_names = set()
    for tp in tpl_params:
        pn = tp["name"]
        old_p = old_param_by_name.get(pn)
        if old_p and old_p.get("value") is not None:
            merged_params.append({"name": pn, "value": old_p["value"]})
            used_param_names.add(pn)
        else:
            merged_params.append(tp)

    for op in old_params:
        pn = op.get("name", "")
        if pn and pn not in used_param_names:
            merged_params.append(op)

    # --- Switches: match by name, override on/off ---
    tpl_switches = []
    for ts in tpl.get("switches", []):
        tpl_switches.append({
            "name": ts["name"],
            "on": ts.get("on", False),
        })

    old_switch_by_name = {s["name"]: s for s in old_switches if s.get("name")}
    merged_switches = []
    used_switch_names = set()
    for ts in tpl_switches:
        sn = ts["name"]
        old_sw = old_switch_by_name.get(sn)
        if old_sw:
            merged_switches.append({
                "name": sn,
                "on": old_sw.get("on", ts.get("on", False)),
            })
            used_switch_names.add(sn)
        else:
            merged_switches.append(ts)

    for osw in old_switches:
        sn = osw.get("name", "")
        if sn and sn not in used_switch_names:
            merged_switches.append(osw)

    # --- Shader macros: template defaults (old bins rarely have these) ---
    old_macros_f = _get_field(old_fields, _HASH_SHADER_MACROS)
    tpl_macros = tpl.get("macros", {})
    if old_macros_f and old_macros_f.get('pairs'):
        # Merge: template macros as base, old macros override
        merged_macros = dict(tpl_macros)
        for pair in old_macros_f.get('pairs', []):
            k = pair.get('key', {}).get('value', '')
            v = pair.get('value', {}).get('value', '')
            if k:
                merged_macros[str(k)] = str(v)
    else:
        merged_macros = tpl_macros

    # Step 4: Build output bin entry
    new_fields = []

    # name
    new_fields.append(_mkfield(_HASH_NAME, 16, mat_name))

    # materialType
    new_fields.append(_mkfield(_HASH_MATERIAL_TYPE, 7, mat_type))

    # samplerValues
    if merged_samplers:
        sampler_items = []
        for s in merged_samplers:
            sflds = [
                _mkfield(_HASH_TEXTURE_NAME, 16, s.get("textureName", "")),
                _mkfield(_HASH_TEXTURE_PATH, 16, s.get("texturePath", "")),
            ]
            if s.get("addressU") is not None and s["addressU"] != 1:
                sflds.append(_mkfield(_HASH_ADDRESS_U, 7, s["addressU"]))
            if s.get("addressV") is not None and s["addressV"] != 1:
                sflds.append(_mkfield(_HASH_ADDRESS_V, 7, s["addressV"]))
            if s.get("addressW") is not None and s["addressW"] != 1:
                sflds.append(_mkfield(_HASH_ADDRESS_W, 7, s["addressW"]))
            sampler_items.append(_mkembed("0x0904b150", sflds))
        new_fields.append({
            "name_hash": "0x%08x" % _HASH_SAMPLER_VALUES,
            "type": 0x80, "value_type": 0x83,
            "values": sampler_items,
        })

    # paramValues
    if merged_params:
        param_items = []
        for p in merged_params:
            pflds = [
                _mkfield(_HASH_NAME, 16, p.get("name", "")),
            ]
            val = p.get("value")
            if val is not None:
                pflds.append(_mkfield(_HASH_VALUE, 13, list(val) if hasattr(val, '__iter__') else val))
            param_items.append(_mkembed("0xde480eef", pflds))
        new_fields.append({
            "name_hash": "0x%08x" % _HASH_PARAM_VALUES,
            "type": 0x80, "value_type": 0x83,
            "values": param_items,
        })

    # switchValues
    if merged_switches:
        switch_items = []
        for sw in merged_switches:
            sflds = []
            if sw.get("name") is not None:
                sflds.append(_mkfield(_HASH_NAME, 16, sw["name"]))
            if sw.get("on") is not None:
                sflds.append(_mkfield(_HASH_ON, 1, sw["on"]))
            if sw.get("group") is not None:
                sflds.append(_mkfield(_HASH_GROUP, 16, sw["group"]))
            switch_items.append(_mkembed("0x0e2212a1", sflds))
        new_fields.append({
            "name_hash": "0x%08x" % _HASH_SWITCH_VALUES,
            "type": 0x80, "value_type": 0x83,
            "values": switch_items,
        })

    # shaderMacros
    if merged_macros:
        pairs = []
        for k, v in merged_macros.items():
            pairs.append({
                "key": {"type": 16, "value": str(k)},
                "value": {"type": 16, "value": str(v)},
            })
        new_fields.append({
            "name_hash": "0x%08x" % _HASH_SHADER_MACROS,
            "type": 0x86, "key_type": 16, "value_type": 16,
            "pairs": pairs,
        })

    # techniques — rebuilt from template blend + new shader path
    blend = tpl.get("blend", {})
    new_fields.append(_build_technique_bin(template_path, blend))

    # childTechniques
    child_names = tpl.get("child_techniques", [])
    if child_names:
        new_fields.append(_build_child_techniques_bin(child_names))

    return {
        "path_hash": entry.get('path_hash', ''),
        "type_hash": entry.get('type_hash', '0xff9d3409'),
        "fields": new_fields,
        "_migration": {
            "shader_resolved": template_path,
            "shader_source": resolved_from,
            "shader_link": shader_link,
        },
    }


# ── VFX migration constants ──────────────────────────────────────────────
_VFX_OLD_TEXTURE_HASH = "0x38344d14"      # Old emitter texture field (gone in modern)
_VFX_NEW_TEXTURE_HASH = "0x3c6468f4"      # Modern emitter texture field
_VFX_TEXTURE_FIELDS = {                   # All field hashes that carry texture paths
    "0x38344d14", "0x3c6468f4", "0x2f2e99f2", "0x5da05f9b",
    "0x99a7180f", "0xb56e8811", "0xe672d557", "0xffa711fb",
}


def migrate_vfx_entry(entry: dict) -> dict:
    """Migrate a single VfxSystemDefinitionData entry to modern format.

    1. Rename field 0x38344d14 → 0x3c6468f4  (old texture → modern texture)
    2. Rewrite .dds → .tex on all texture path strings
    """
    import copy

    entry = copy.deepcopy(entry)
    stats = {"fields_renamed": 0, "ext_fixed": 0}

    def _walk(node):
        if not isinstance(node, dict):
            return
        nh = node.get("name_hash", "")

        # 1) Field hash rename
        if nh == _VFX_OLD_TEXTURE_HASH:
            node["name_hash"] = _VFX_NEW_TEXTURE_HASH
            if "name_hash_int" in node:
                node["name_hash_int"] = int(_VFX_NEW_TEXTURE_HASH, 16)
            stats["fields_renamed"] += 1

        # 2) .dds → .tex on texture string fields
        cur_hash = node.get("name_hash", "")
        if cur_hash in _VFX_TEXTURE_FIELDS:
            v = node.get("value", "")
            if isinstance(v, str) and v.lower().endswith(".dds"):
                node["value"] = v[:-4] + ".tex"
                stats["ext_fixed"] += 1

        # Recurse
        for f in node.get("fields") or []:
            _walk(f)
        for v in node.get("values") or []:
            _walk(v)
        for p in node.get("pairs") or []:
            _walk(p.get("key", {}))
            _walk(p.get("value", {}))
        if isinstance(node.get("value"), dict):
            _walk(node["value"])

    for f in entry.get("fields", []):
        _walk(f)

    entry["_vfx_migration"] = stats
    return entry


def migrate_materials_bin(input_path: str, output_path: str,
                          fallback_shader: str = None) -> dict:
    """Migrate all StaticMaterialDef and VfxSystemDefinitionData entries in a
    .materials.bin file.

    - Materials: template-based shader/sampler migration
    - VFX: field hash rename + .dds→.tex extension fix
    Non-material/VFX entries are passed through untouched.

    Args:
        input_path: Path to the source .materials.bin
        output_path: Path to write the migrated .materials.bin
        fallback_shader: Shader template path to use when link can't be resolved

    Returns:
        Summary dict with migration statistics.
    """
    from . import propertybin_parser

    templates = _load_shader_templates()
    shader_table = _build_shader_hash_table(templates)

    data = propertybin_parser.parse_bin(input_path)
    entries = data.get('entries', [])

    new_entries = []
    stats = {
        "total": len(entries),
        "materials": 0,
        "migrated": 0,
        "fallback": 0,
        "unresolved_shaders": {},
        "resolved_shaders": {},
        "vfx_total": 0,
        "vfx_fields_renamed": 0,
        "vfx_ext_fixed": 0,
        "passthrough": 0,
    }

    for entry in entries:
        th = entry.get('type_hash', '')
        if th == '0xff9d3409':
            stats["materials"] += 1
            migrated = migrate_material_entry(
                entry, templates, shader_table, fallback_shader
            )
            info = migrated.pop("_migration", {})
            new_entries.append(migrated)
            stats["migrated"] += 1

            shader = info.get("shader_resolved", "")
            source = info.get("shader_source", "")
            if "unresolved" in source:
                link = info.get("shader_link", "?")
                stats["unresolved_shaders"][link] = stats["unresolved_shaders"].get(link, 0) + 1
                stats["fallback"] += 1
            else:
                stats["resolved_shaders"][shader] = stats["resolved_shaders"].get(shader, 0) + 1
        elif th == '0x45cd899f':
            migrated = migrate_vfx_entry(entry)
            vinfo = migrated.pop("_vfx_migration", {})
            new_entries.append(migrated)
            stats["vfx_total"] += 1
            stats["vfx_fields_renamed"] += vinfo.get("fields_renamed", 0)
            stats["vfx_ext_fixed"] += vinfo.get("ext_fixed", 0)
        else:
            new_entries.append(entry)
            stats["passthrough"] += 1

    out_data = {
        "magic": data.get("magic", "PROP"),
        "version": data.get("version", 3),
        "linked_files": data.get("linked_files", []),
        "entries": new_entries,
    }

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    propertybin_parser.write_bin(out_data, output_path)

    print(f"[PREY] Migrated {stats['migrated']}/{stats['materials']} materials → {os.path.basename(output_path)}")
    if stats["resolved_shaders"]:
        print("  Resolved shaders:")
        for s, c in sorted(stats["resolved_shaders"].items(), key=lambda x: -x[1]):
            print(f"    {s}: {c}")
    if stats["unresolved_shaders"]:
        print(f"  Unresolved (using fallback '{fallback_shader or _DEFAULT_FALLBACK_SHADER}'):")
        for s, c in sorted(stats["unresolved_shaders"].items(), key=lambda x: -x[1]):
            print(f"    {s}: {c}")
    if stats["vfx_total"]:
        print(f"  VFX entries: {stats['vfx_total']} "
              f"(fields renamed: {stats['vfx_fields_renamed']}, "
              f"ext .dds→.tex: {stats['vfx_ext_fixed']})")

    return stats


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python prey_format.py <input.materials.bin> [output_dir]")
        sys.exit(1)

    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = convert(inp, out)
    print(f"\nCreated {len(result)} files:")
    for cat, path in result.items():
        print(f"  {cat}: {path}")
