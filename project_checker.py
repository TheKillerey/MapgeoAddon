"""
Project Integrity Checker for MapgeoAddon

Validates all cross-file references in a loaded mod project:
  - Mapgeo mesh primitives → materials.bin  (material names)
  - materials.bin samplers → texture files   (texture paths)
  - Mapgeo texture overrides                 (v17+ per-mesh textures)
  - Mapgeo visibility controller hashes      (v15+ mesh & bucket-grid links)
  - Custom bucket grid detection             (known issue warning)
  - Linked bin files                         (materials.bin header linked_files)
  - VFX / MapParticle cross-links            (TYPE_LINK integrity)
  - Lightmap & stationary-light textures     (baked_light / stationary_light channels)
  - Audio / soundbank references             (linked .bnk / .wpk paths)

Results are stored in scene.project_checker (ProjectCheckerSettings) and
displayed as a sub-panel under the Project Manager.
"""

import bpy
import os
import shutil
from difflib import SequenceMatcher
from datetime import datetime
from bpy.props import (
    StringProperty, EnumProperty, IntProperty, FloatProperty,
    CollectionProperty, PointerProperty, BoolProperty,
)
from bpy.types import PropertyGroup, Operator, Panel, UIList


# ============================================================================
# Severity icon mapping
# ============================================================================

_SEV_ICONS = {
    'ERROR':   'ERROR',
    'WARNING': 'QUESTION',
    'INFO':    'INFO',
}

_AUDIO_EXTENSIONS = {'.bnk', '.wpk', '.ogg', '.wav', '.mp3'}
_TEXTURE_EXTENSIONS = {'.tex', '.dds', '.png', '.jpg', '.jpeg', '.tga', '.bmp', '.ktx', '.ktx2'}

# Cache for Riot-hash classification of texture asset paths
_riot_known_cache = {}
_riot_hash_bootstrap_done = False


# ============================================================================
# Property Groups
# ============================================================================

class CheckIssue(PropertyGroup):
    severity: EnumProperty(
        name="Severity",
        items=[
            ('ERROR',   'Error',   ''),
            ('WARNING', 'Warning', ''),
            ('INFO',    'Info',    ''),
        ],
        default='INFO',
    )
    category:  StringProperty(name="Category",  default="")
    message:   StringProperty(name="Message",   default="")
    detail:    StringProperty(name="Detail",    default="")
    file_path: StringProperty(name="File",      default="", subtype='FILE_PATH')
    fix_id:    StringProperty(name="Fix ID",    default="")


class ProjectCheckerSettings(PropertyGroup):
    issues:        CollectionProperty(type=CheckIssue)
    active_index:  IntProperty(default=0)
    last_run:      StringProperty(default="")
    error_count:   IntProperty(default=0)
    warning_count: IntProperty(default=0)
    info_count:    IntProperty(default=0)
    filter_mode:   EnumProperty(
        name="Filter",
        items=[
            ('ALL',     'All',      '', 'COLLAPSEMENU', 0),
            ('ERROR',   'Errors',   '', 'ERROR',        1),
            ('WARNING', 'Warnings', '', 'QUESTION',     2),
            ('INFO',    'Info',     '', 'INFO',         3),
        ],
        default='ALL',
    )
    texture_project_mode: EnumProperty(
        name="Texture Project Type",
        description="How missing textures should be validated for this project",
        items=[
            ('MIXED',
             "Mixed (Project OR Riot)",
             "Legacy behavior: a texture is OK if it exists in project or Riot cache"),
            ('REPLACED_RIOT',
             "Replaced Riot Textures",
             "Strict project mode: texture must exist in project folder (ignore Riot cache hit)"),
            ('FULLY_CUSTOM',
             "Fully Custom Names",
             "Use Riot hash knowledge: known Riot paths can resolve from Riot cache, unknown/custom names must exist in project"),
        ],
        default='MIXED',
    )
    ai_fix_min_confidence: FloatProperty(
        name="AI Texture Min Confidence",
        description="Minimum confidence score required for automatic texture aliasing",
        default=0.58,
        min=0.0,
        max=2.0,
    )
    use_chatgpt_api: BoolProperty(
        name="Use ChatGPT API",
        description="Use OpenAI ChatGPT to suggest the best matching project texture for each missing path (requires API key)",
        default=False,
    )
    chatgpt_api_key: StringProperty(
        name="OpenAI API Key",
        description="Your OpenAI API key. Stored in the .blend file — do not share the file if this is set",
        default="",
        subtype='PASSWORD',
    )
    chatgpt_model: StringProperty(
        name="ChatGPT Model",
        description="Model name (e.g. gpt-4o-mini, gpt-4o, gpt-4.1-mini)",
        default="gpt-4o-mini",
    )


# ============================================================================
# Core Checker
# ============================================================================

# FNV-1a 32-bit (same as propertybin_parser)
def _fnv1a_32(s: str) -> int:
    s = s.lower()
    h = 0x811c9dc5
    for c in s:
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# Known type hashes
_HASH_STATIC_MAT   = 0xff9d3409
_HASH_VFX_SYSTEM   = 0x45cd899f
_HASH_MAP_PLACEABLE= 0xb25c0a3f
_HASH_MAP_PARTICLE = 0x24a31b3e
_HASH_SUN          = 0x169a2f9c
_HASH_BAKE         = 0x6a4a3409
_HASH_VIS_CTRL     = 0xe21083b5
_HASH_DRAGON_LAYER = 0xc406a533
_HASH_BARON_LAYER  = 0xec733fe2
_HASH_NAMED_CTRL   = 0xe07edfa4
_HASH_MUTATOR      = 0x4275b121

# Known field hashes
_HASH_NAME          = 0x8d39bde6
_HASH_TEXTURE_PATH  = 0xf0a363e3
_HASH_SAMPLER_VALS  = 0x0a6f0eb5

# Bin field types
_TYPE_STRING    = 16
_TYPE_FILE      = 18
_TYPE_CONTAINER = 0x80
_TYPE_STRUCT    = 0x82
_TYPE_EMBEDDED  = 0x83
_TYPE_LINK      = 0x84
_TYPE_OPTIONAL  = 0x85
_TYPE_MAP       = 0x86


def _walk_fields(fields):
    """Yield every leaf/nested field dict recursively."""
    if not fields:
        return
    for f in fields:
        yield f
        # Nested containers / structs store their children in 'items'
        if f.get('type') in (_TYPE_CONTAINER, 0x81):
            for item in f.get('items', []):
                if isinstance(item, dict):
                    if 'fields' in item:
                        yield from _walk_fields(item['fields'])
                    else:
                        yield item
        # Struct / embedded / optional with inline fields
        if f.get('type') in (_TYPE_STRUCT, _TYPE_EMBEDDED, _TYPE_OPTIONAL):
            inner = f.get('value')
            if isinstance(inner, dict) and 'fields' in inner:
                yield from _walk_fields(inner['fields'])
            elif isinstance(inner, list):
                yield from _walk_fields(inner)
        # Map type: iterate values
        if f.get('type') == _TYPE_MAP:
            for _k, v in f.get('pairs', []):
                if isinstance(v, dict) and 'fields' in v:
                    yield from _walk_fields(v['fields'])


def _stems_are_season_variants(a: str, b: str) -> bool:
    """Two stems match if they're equal or one is a dot-token-extension of the other.

    e.g. 'foo' <-> 'foo.summer'         -> True
         'foo.summer' <-> 'foo.summer.hi' -> True
         'foo.summer' <-> 'foo.winter'  -> False
         'foobar' <-> 'foo'             -> False (must be split on '.')
    """
    a = (a or '').lower()
    b = (b or '').lower()
    if a == b:
        return True
    if a.startswith(b + '.'):
        return True
    if b.startswith(a + '.'):
        return True
    return False


def _find_season_variant(project_root: str, rel_dir: str, base: str):
    """Return rel-path of a season-variant file in project_root/rel_dir for `base`.

    Looks for files in the same directory whose stem is a season variant of
    `base` (under any known texture extension). Returns None if none found.
    """
    if not project_root:
        return None
    abs_dir = os.path.join(project_root, rel_dir.replace('/', os.sep))
    if not os.path.isdir(abs_dir):
        return None
    base_l = base.lower()
    for fn in os.listdir(abs_dir):
        full = os.path.join(abs_dir, fn)
        if not os.path.isfile(full):
            continue
        f_base, f_ext = os.path.splitext(fn)
        if f_ext.lower() not in _TEXTURE_EXTENSIONS:
            continue
        if _stems_are_season_variants(f_base, base_l):
            if f_base.lower() == base_l:
                continue  # exact stem already handled by caller
            rel = os.path.join(rel_dir, fn).replace('\\', '/')
            return rel
    return None


def _tex_exists(tex_path: str, roots: list) -> bool:
    """Check whether a texture path exists under any of the given root dirs.

    Accepts any matching file with the same stem under a known texture
    extension (e.g. materials.bin references foo.dds but the project
    actually contains foo.tex \u2014 still considered present).
    """
    tex_norm = tex_path.replace('\\', '/')
    base, ext = os.path.splitext(tex_norm)
    # Candidate extensions: the requested one first (case-insensitive), then
    # every other known texture extension.
    candidates = [ext]
    for e in _TEXTURE_EXTENSIONS:
        if e.lower() != ext.lower():
            candidates.append(e)

    for root in roots:
        # Fast path: the literal requested path exists.
        if os.path.isfile(os.path.join(root, tex_norm)):
            return True
        # Fallback: same stem with a different texture extension.
        for cand_ext in candidates[1:]:
            alt = base + cand_ext
            if os.path.isfile(os.path.join(root, alt)):
                return True
    return False


def _file_exists(rel_path: str, roots: list) -> bool:
    norm = rel_path.replace('\\', '/')
    for root in roots:
        if os.path.isfile(os.path.join(root, norm)):
            return True
    return False


def _is_known_riot_texture_path(tex_path: str):
    """Return True/False if the texture path is known in Riot hash DB.

    Returns None when hash DB is unavailable.
    """
    global _riot_hash_bootstrap_done
    norm = (tex_path or '').replace('\\', '/').strip().lower()
    if not norm:
        return False
    if norm in _riot_known_cache:
        return _riot_known_cache[norm]

    try:
        from . import wad_tool
    except Exception:
        _riot_known_cache[norm] = None
        return None

    if not _riot_hash_bootstrap_done:
        try:
            wad_tool.load_wad_hashes()
        except Exception:
            pass
        _riot_hash_bootstrap_done = True

    try:
        h = wad_tool.xxhash64_path(norm)
        ok = wad_tool.resolve_wad_hash(h) is not None
    except Exception:
        ok = None
    _riot_known_cache[norm] = ok
    return ok


def _find_first_file_by_ext(root_dir: str, ext: str) -> str:
    """Find the first file ending with `ext` under root_dir (sorted walk)."""
    if not root_dir or not os.path.isdir(root_dir):
        return ""
    for root, dirs, files in os.walk(root_dir):
        dirs.sort(key=str.lower)
        files_sorted = sorted(files, key=str.lower)
        for fn in files_sorted:
            if fn.lower().endswith(ext.lower()):
                return os.path.join(root, fn)
    return ""


def _find_first_mapgeo_and_materials(root_dir: str) -> tuple:
    """Best-effort pair resolver under a project/cache root.

    Prefer a basename pair inside data/maps/mapgeometry (variant.mapgeo +
    variant.materials.bin). Fallback to first mapgeo/materials found anywhere.
    """
    if not root_dir or not os.path.isdir(root_dir):
        return "", ""

    geom_root = os.path.join(root_dir, 'data', 'maps', 'mapgeometry')
    if os.path.isdir(geom_root):
        for walk_root, dirs, files in os.walk(geom_root):
            dirs.sort(key=str.lower)
            files_sorted = sorted(files, key=str.lower)
            mapgeos = [f for f in files_sorted if f.lower().endswith('.mapgeo')]
            mats = [f for f in files_sorted if f.lower().endswith('.materials.bin')]
            if mapgeos and mats:
                mat_by_base = {
                    m[:-len('.materials.bin')].lower(): m for m in mats
                }
                for mg in mapgeos:
                    base = mg[:-len('.mapgeo')].lower()
                    if base in mat_by_base:
                        return (
                            os.path.join(walk_root, mg),
                            os.path.join(walk_root, mat_by_base[base]),
                        )

    # Fallback: first-found files anywhere
    mg = _find_first_file_by_ext(root_dir, '.mapgeo')
    mb = _find_first_file_by_ext(root_dir, '.materials.bin')
    return mg, mb


def _resolve_integrity_paths(settings, wad_cache_dir: str) -> tuple:
    """Resolve mapgeo/materials paths even when no variant was loaded.

    Priority:
      1) loaded_* paths
      2) selected variant from map_variants
      3) any variant from map_variants with existing files
      4) project folder scan
      5) Riot WAD cache scan
    """
    loaded_mapgeo = bpy.path.abspath(settings.loaded_mapgeo_path) if settings.loaded_mapgeo_path else ""
    loaded_materials = bpy.path.abspath(settings.loaded_materials_path) if settings.loaded_materials_path else ""

    mapgeo_path = loaded_mapgeo if (loaded_mapgeo and os.path.isfile(loaded_mapgeo)) else ""
    materials_path = loaded_materials if (loaded_materials and os.path.isfile(loaded_materials)) else ""
    source = "loaded"

    # 2) selected variant
    if (not mapgeo_path or not materials_path) and getattr(settings, 'map_variants', None):
        idx = int(getattr(settings, 'selected_variant_index', 0) or 0)
        if 0 <= idx < len(settings.map_variants):
            v = settings.map_variants[idx]
            if not mapgeo_path and v.mapgeo_path:
                p = bpy.path.abspath(v.mapgeo_path)
                if os.path.isfile(p):
                    mapgeo_path = p
                    source = "selected variant"
            if not materials_path and v.materials_bin_path:
                p = bpy.path.abspath(v.materials_bin_path)
                if os.path.isfile(p):
                    materials_path = p
                    source = "selected variant"

    # 3) any variant
    if (not mapgeo_path or not materials_path) and getattr(settings, 'map_variants', None):
        for v in settings.map_variants:
            if not mapgeo_path and v.mapgeo_path:
                p = bpy.path.abspath(v.mapgeo_path)
                if os.path.isfile(p):
                    mapgeo_path = p
                    source = "variant list"
            if not materials_path and v.materials_bin_path:
                p = bpy.path.abspath(v.materials_bin_path)
                if os.path.isfile(p):
                    materials_path = p
                    source = "variant list"
            if mapgeo_path and materials_path:
                break

    # 4) project folder scan
    project_folder = bpy.path.abspath(settings.project_folder) if settings.project_folder else ""
    if (not mapgeo_path or not materials_path) and project_folder and os.path.isdir(project_folder):
        mg, mb = _find_first_mapgeo_and_materials(project_folder)
        if not mapgeo_path and mg:
            mapgeo_path = mg
            source = "project scan"
        if not materials_path and mb:
            materials_path = mb
            source = "project scan"

    # 5) Riot WAD cache fallback
    if (not mapgeo_path or not materials_path) and wad_cache_dir and os.path.isdir(wad_cache_dir):
        mg, mb = _find_first_mapgeo_and_materials(wad_cache_dir)
        if not mapgeo_path and mg:
            mapgeo_path = mg
            source = "Riot cache scan"
        if not materials_path and mb:
            materials_path = mb
            source = "Riot cache scan"

    return mapgeo_path, materials_path, source


def _norm_rel(path: str) -> str:
    return (path or '').replace('\\', '/').strip().lower()


def _iter_project_texture_files(project_root: str):
    """Yield relative texture file paths under project_root."""
    if not project_root or not os.path.isdir(project_root):
        return
    for root, _dirs, files in os.walk(project_root):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _TEXTURE_EXTENSIONS:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, project_root).replace('\\', '/')
            yield rel


def _score_texture_candidate(expected_rel: str, candidate_rel: str) -> float:
    """Heuristic "AI-like" similarity score for wrong texture path recovery."""
    e = _norm_rel(expected_rel)
    c = _norm_rel(candidate_rel)

    e_dir, e_name = os.path.split(e)
    c_dir, c_name = os.path.split(c)
    e_base, e_ext = os.path.splitext(e_name)
    c_base, c_ext = os.path.splitext(c_name)

    base_ratio = SequenceMatcher(None, e_base, c_base).ratio()
    path_ratio = SequenceMatcher(None, e, c).ratio()
    dir_ratio = SequenceMatcher(None, e_dir, c_dir).ratio()

    score = base_ratio * 0.60 + path_ratio * 0.25 + dir_ratio * 0.15
    if e_base == c_base:
        score += 0.30
    if e_ext == c_ext:
        score += 0.10
    if e_dir and c_dir and (e_dir in c_dir or c_dir in e_dir):
        score += 0.10
    return score


def _best_texture_candidate(expected_rel: str, project_root: str):
    """Return (best_rel_path, score) for expected texture path."""
    expected = _norm_rel(expected_rel)
    if not expected:
        return "", 0.0

    e_name = os.path.basename(expected)
    e_base, e_ext = os.path.splitext(e_name)

    best_rel = ""
    best_score = 0.0

    for rel in _iter_project_texture_files(project_root):
        r = _norm_rel(rel)
        if r == expected:
            return rel, 1.0

        # Fast prefilter for scale: keep candidates with either matching ext
        # or strong basename overlap signal.
        r_name = os.path.basename(r)
        r_base, r_ext = os.path.splitext(r_name)
        if r_ext != e_ext and e_base[:4] not in r_base and r_base[:4] not in e_base:
            continue

        s = _score_texture_candidate(expected, r)
        if s > best_score:
            best_score = s
            best_rel = rel

    return best_rel, best_score


def _chatgpt_audit_one_batch(refs, files, api_key, model, timeout):
    """Single OpenAI call for one batch of references."""
    import json
    import urllib.request
    import urllib.error

    system_msg = (
        "You audit referenced texture paths against an actual project file "
        "listing. For each reference, decide one of:\n"
        "  - 'exact'   : the reference is present in the project files (case-insensitive)\n"
        "  - 'fuzzy'   : not present, but a project file is clearly the renamed/moved equivalent\n"
        "  - 'missing' : no reasonable equivalent exists in the project files\n"
        "Only choose 'fuzzy' when the basename or directory clearly corresponds "
        "(do not invent matches). Respond with ONLY valid JSON of the form:\n"
        "{\"exact\":[...refs...], \"fuzzy\":[{\"ref\":\"...\",\"candidate\":\"...\"}], "
        "\"missing\":[...refs...]}\n"
        "Each candidate MUST be one of the supplied project files verbatim."
    )
    user_msg = json.dumps({"references": refs, "project_files": files}, ensure_ascii=False)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode('utf-8'),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace') if e.fp else ''
        # Surface 429 specifically so the caller's retry-with-backoff can react
        raise RuntimeError(f"OpenAI HTTP {e.code}: {body[:300]}")
    except Exception as e:
        raise RuntimeError(f"OpenAI request failed: {e}")

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
    except Exception as e:
        raise RuntimeError(f"OpenAI response parse failed: {e}")

    out = {'exact': [], 'fuzzy': [], 'missing': []}
    if isinstance(result, dict):
        out['exact']   = [r for r in result.get('exact', []) if isinstance(r, str)]
        out['missing'] = [r for r in result.get('missing', []) if isinstance(r, str)]
        for entry in result.get('fuzzy', []):
            if isinstance(entry, dict) and isinstance(entry.get('ref'), str):
                out['fuzzy'].append({
                    'ref': entry['ref'],
                    'candidate': entry.get('candidate', '') if isinstance(entry.get('candidate'), str) else '',
                })
    return out


def _chatgpt_audit_textures(referenced_paths, project_files, api_key: str,
                            model: str = "gpt-4o-mini", timeout: float = 90.0,
                            batch_size: int = 20, max_files: int = 250,
                            max_retries: int = 3) -> dict:
    """Ask ChatGPT to classify every referenced texture path against the
    actual project file list. Pre-filters exact matches locally, then sends
    only ambiguous refs to the AI in small batches with retry.

    Returns: { 'exact': [...], 'fuzzy': [{'ref','candidate'}, ...], 'missing': [...] }
    Raises RuntimeError if every batch fails.
    """
    import time

    if not api_key or not referenced_paths:
        return {'exact': [], 'fuzzy': [], 'missing': []}

    # Local pre-pass: anything already present (case-insensitive) is 'exact'.
    # Also treat same-stem-different-extension as exact (e.g. project has
    # foo.tex while the bin references foo.dds, or vice versa).
    files_norm_map = {f.replace('\\', '/').lower(): f for f in project_files}
    files_stem_map = {}
    for f in project_files:
        fn = f.replace('\\', '/').lower()
        stem = os.path.splitext(fn)[0]
        files_stem_map.setdefault(stem, fn)
    exact_local = []
    needs_ai = []
    for r in referenced_paths:
        rn = (r or '').replace('\\', '/').lower()
        if rn in files_norm_map:
            exact_local.append(r)
            continue
        stem = os.path.splitext(rn)[0]
        if stem in files_stem_map:
            exact_local.append(r)
            continue
        needs_ai.append(r)

    aggregate = {'exact': list(exact_local), 'fuzzy': [], 'missing': []}

    if not needs_ai:
        return aggregate

    # Trim project files to keep the prompt small. Prefer files whose basename
    # appears in any unresolved ref so candidates remain useful.
    files_list = project_files
    if len(files_list) > max_files:
        ref_basenames = {os.path.basename(r).lower() for r in needs_ai}
        scored = []
        for f in files_list:
            base = os.path.basename(f).lower()
            score = 1 if base in ref_basenames else 0
            # also prefer same first 4 chars
            stem = os.path.splitext(base)[0]
            if any(rb.startswith(stem[:4]) for rb in ref_basenames if stem):
                score += 1
            scored.append((score, f))
        scored.sort(key=lambda x: (-x[0], x[1]))
        files_list = [f for _s, f in scored[:max_files]]

    last_err = None
    n_batches = (len(needs_ai) + batch_size - 1) // batch_size
    succeeded_batches = 0

    for bi in range(n_batches):
        batch = needs_ai[bi * batch_size:(bi + 1) * batch_size]
        attempt = 0
        cur_timeout = timeout
        while True:
            try:
                res = _chatgpt_audit_one_batch(batch, files_list, api_key, model, cur_timeout)
                aggregate['exact'].extend(res.get('exact', []))
                aggregate['fuzzy'].extend(res.get('fuzzy', []))
                aggregate['missing'].extend(res.get('missing', []))
                succeeded_batches += 1
                break
            except Exception as e:
                last_err = str(e)
                attempt += 1
                if attempt > max_retries:
                    print(f"[Project Checker] AI batch {bi+1}/{n_batches} failed permanently: {e}")
                    # Treat batch as inconclusive — leave to local heuristic later
                    break
                # 429 (rate limit) — parse "try again in Xs" if present
                wait_s = 2.0 * attempt
                if '429' in last_err:
                    import re as _re
                    m = _re.search(r'try again in ([\d.]+)s', last_err, _re.IGNORECASE)
                    if m:
                        try:
                            wait_s = max(wait_s, float(m.group(1)) + 1.0)
                        except Exception:
                            pass
                    else:
                        wait_s = max(wait_s, 10.0)
                cur_timeout = min(cur_timeout + 60.0, 360.0)
                print(f"[Project Checker] AI batch {bi+1}/{n_batches} attempt {attempt} retry in {wait_s:.1f}s "
                      f"(timeout {cur_timeout}s): {e}")
                time.sleep(wait_s)

    if succeeded_batches == 0 and last_err:
        raise RuntimeError(last_err)

    # Dedupe
    aggregate['exact'] = sorted(set(aggregate['exact']))
    aggregate['missing'] = sorted(set(aggregate['missing']))
    seen_fuzzy = set()
    deduped_fuzzy = []
    for entry in aggregate['fuzzy']:
        key = (entry.get('ref', ''), entry.get('candidate', ''))
        if key in seen_fuzzy:
            continue
        seen_fuzzy.add(key)
        deduped_fuzzy.append(entry)
    aggregate['fuzzy'] = deduped_fuzzy
    return aggregate


def _chatgpt_match_textures(missing_paths, candidate_paths, api_key: str,
                            model: str = "gpt-4o-mini", timeout: float = 180.0):
    """Ask ChatGPT to map each missing texture path to the best candidate.

    Returns dict { missing_path_lower : candidate_path } (candidate is one of
    the supplied candidate_paths, or "" if the model could not match).
    Raises RuntimeError on transport / API errors so the caller can fall back.
    """
    import json
    import re
    import time
    import urllib.request
    import urllib.error

    if not api_key or not missing_paths or not candidate_paths:
        return {}

    BATCH_SIZE = 20
    MAX_FILES_PER_CALL = 300

    def _trim_candidates_for(batch_misses):
        """Keep candidates whose basename / stem overlaps the batch refs."""
        ref_bases = {os.path.basename(m).lower() for m in batch_misses}
        ref_stems = {os.path.splitext(b)[0][:4] for b in ref_bases if b}
        scored = []
        for c in candidate_paths:
            base = os.path.basename(c).lower()
            stem = os.path.splitext(base)[0]
            score = 0
            if base in ref_bases:
                score += 2
            if stem and any(stem.startswith(s) or s.startswith(stem[:4]) for s in ref_stems):
                score += 1
            scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [c for _s, c in scored[:MAX_FILES_PER_CALL]]

    out = {}
    n = len(missing_paths)
    n_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE

    for bi in range(n_batches):
        miss = missing_paths[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
        cands = _trim_candidates_for(miss)
        if not cands:
            continue

        system_msg = (
            "You map missing texture file paths to the closest matching existing "
            "project texture path. Respond with ONLY valid JSON: an object whose "
            "keys are the missing paths (verbatim) and whose values are the chosen "
            "candidate path from the provided list, or an empty string if none "
            "is a reasonable match. Do not invent paths."
        )
        user_msg = json.dumps({"missing": miss, "candidates": cands}, ensure_ascii=False)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        # Up to 3 attempts with 429-aware backoff
        raw = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode('utf-8', errors='replace')
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', errors='replace') if e.fp else ''
                if e.code == 429:
                    wait_s = 5.0 * (attempt + 1)
                    m = re.search(r'try again in ([\d.]+)s', body, re.IGNORECASE)
                    if m:
                        try:
                            wait_s = max(wait_s, float(m.group(1)) + 1.0)
                        except Exception:
                            pass
                    if attempt < 2:
                        print(f"[Project Checker] OpenAI 429 (batch {bi+1}/{n_batches}), "
                              f"backing off {wait_s:.1f}s\u2026")
                        time.sleep(wait_s)
                        continue
                if attempt == 2:
                    raise RuntimeError(f"OpenAI HTTP {e.code}: {body[:300]}")
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"OpenAI request failed: {e}")
                time.sleep(2.0 * (attempt + 1))

        if not raw:
            continue

        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            mapping = json.loads(content)
            if not isinstance(mapping, dict):
                continue
        except Exception:
            continue

        cand_set = {c.replace('\\', '/').lower(): c for c in cands}
        for k, v in mapping.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            v_norm = v.replace('\\', '/').strip().lower()
            if v_norm and v_norm in cand_set:
                out[k.replace('\\', '/').strip().lower()] = cand_set[v_norm]

    return out


def _convert_texture_file(src_abs: str, dst_abs: str) -> str:
    """Convert between .tex and .dds when extensions differ.

    Returns one of: 'converted_tex_to_dds', 'converted_dds_to_tex'.
    Raises RuntimeError on unsupported conversion or failure.
    """
    src_ext = os.path.splitext(src_abs)[1].lower()
    dst_ext = os.path.splitext(dst_abs)[1].lower()
    os.makedirs(os.path.dirname(dst_abs) or '.', exist_ok=True)

    if src_ext == '.dds' and dst_ext == '.tex':
        from . import texture_utils
        texture_utils.convert_dds_to_tex_file(src_abs, dst_abs)
        return 'converted_dds_to_tex'

    if src_ext == '.tex' and dst_ext == '.dds':
        from . import texture_utils
        with open(src_abs, 'rb') as fh:
            tex_data = fh.read()
        # TexConverter._tex_to_dds is the inverse used internally for previews.
        dds_data = texture_utils.TexConverter._tex_to_dds(tex_data)
        with open(dst_abs, 'wb') as fh:
            fh.write(dds_data)
        return 'converted_tex_to_dds'

    raise RuntimeError(
        f"No converter from {src_ext or '?'} to {dst_ext or '?'}"
    )


def _create_texture_alias(project_root: str, source_rel: str, expected_rel: str):
    """Create expected texture path next to existing project file.

    Strategy:
      1. If destination already exists \u2192 ('exists').
      2. If source extension matches destination \u2192 hardlink (fallback copy).
      3. If extensions differ but both are .tex/.dds \u2192 convert via texture_utils.
      4. Otherwise raise.
    """
    src = os.path.join(project_root, source_rel.replace('/', os.sep))
    dst = os.path.join(project_root, expected_rel.replace('/', os.sep))

    if not os.path.isfile(src):
        raise FileNotFoundError(f"Candidate source not found: {src}")

    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    if os.path.isfile(dst):
        return dst, 'exists'

    src_ext = os.path.splitext(src)[1].lower()
    dst_ext = os.path.splitext(dst)[1].lower()

    if src_ext == dst_ext:
        try:
            os.link(src, dst)
            return dst, 'hardlink'
        except Exception:
            shutil.copy2(src, dst)
            return dst, 'copy'

    # Extensions differ \u2014 try TEX <-> DDS conversion
    if {src_ext, dst_ext} == {'.tex', '.dds'}:
        try:
            mode = _convert_texture_file(src, dst)
            return dst, mode
        except Exception as e:
            # Fallback: just copy the bytes so the file at least exists; note
            # the format will be wrong but it preserves the previous behavior.
            shutil.copy2(src, dst)
            print(f"[Project Checker] TEX/DDS conversion failed ({e}); copied raw bytes instead.")
            return dst, 'copy_fallback'

    # Different image format with no converter \u2014 plain copy
    shutil.copy2(src, dst)
    return dst, 'copy'


def run_checks(project_settings, checker_settings=None) -> list:
    """
    Run all integrity checks against the currently loaded project.
    Returns a list of issue dicts:
      {severity, category, message, detail, file_path}
    """
    from . import mapgeo_parser, propertybin_parser

    # Resolve checker settings (where texture_project_mode lives) — fall back
    # to scene.project_checker when not explicitly passed.
    if checker_settings is None:
        try:
            checker_settings = bpy.context.scene.project_checker
        except Exception:
            checker_settings = None

    issues = []

    def add(severity, category, message, detail="", file_path="", fix_id=""):
        issues.append({
            'severity': severity,
            'category': category,
            'message':  message,
            'detail':   detail,
            'file_path': file_path,
            'fix_id':   fix_id,
        })

    s = project_settings
    project_folder   = bpy.path.abspath(s.project_folder)   if s.project_folder   else ""
    league_install   = bpy.path.abspath(s.league_install)   if s.league_install   else ""
    loaded_mapgeo    = bpy.path.abspath(s.loaded_mapgeo_path)    if s.loaded_mapgeo_path    else ""
    loaded_materials = bpy.path.abspath(s.loaded_materials_path) if s.loaded_materials_path else ""
    map_id           = s.project_map_id or ""

    if not project_folder:
        add('ERROR', 'Setup', 'No project folder is set.')
        return issues, None

    # ── Resolve WAD cache dirs ─────────────────────────────────────────────
    wad_cache_dir    = ""
    levels_cache_dir = ""
    if map_id and league_install and os.path.isdir(league_install):
        try:
            from . import project_manager
            wad_cache_dir = project_manager._ensure_riot_wad_cache(league_install, map_id)
        except Exception as e:
            add('INFO', 'Setup', f'Could not access Riot WAD cache: {e}')
        try:
            from . import project_manager
            levels_cache_dir = project_manager._ensure_riot_levels_wad_cache(league_install, map_id)
        except Exception:
            pass

    # Resolve check targets even when no variant has been loaded into Blender.
    resolved_mapgeo, resolved_materials, resolved_source = _resolve_integrity_paths(s, wad_cache_dir)
    loaded_mapgeo = resolved_mapgeo or loaded_mapgeo
    loaded_materials = resolved_materials or loaded_materials
    if resolved_source != "loaded" and (resolved_mapgeo or resolved_materials):
        add('INFO', 'Setup',
            f'Auto-resolved integrity inputs from {resolved_source}.',
            detail=(f"mapgeo={resolved_mapgeo or '-'} | materials={resolved_materials or '-'}"))

    project_asset_roots = [r for r in [project_folder] if r]
    riot_asset_roots = [r for r in [wad_cache_dir] if r]
    asset_roots    = [r for r in [project_folder, wad_cache_dir] if r]
    lightmap_roots = [r for r in [project_folder, levels_cache_dir, wad_cache_dir] if r]
    texture_mode = getattr(checker_settings, 'texture_project_mode', 'MIXED') or 'MIXED'
    hash_db_info = {'warned': False}

    def _texture_exists_for_project(tex: str) -> bool:
        project_hit = _tex_exists(tex, project_asset_roots)
        riot_hit = _tex_exists(tex, riot_asset_roots)

        if texture_mode == 'REPLACED_RIOT':
            return project_hit
        if texture_mode == 'MIXED':
            return project_hit or riot_hit

        # FULLY_CUSTOM:
        # - known Riot paths may resolve from Riot cache
        # - unknown/custom paths must exist in project
        known_riot = _is_known_riot_texture_path(tex)
        if known_riot is None and not hash_db_info['warned']:
            add('INFO', 'Setup',
                'FULLY_CUSTOM mode: Riot hash DB unavailable, treating unknown paths as custom (project-only).')
            hash_db_info['warned'] = True
        if known_riot is True:
            return project_hit or riot_hit
        return project_hit

    add('INFO', 'Setup', f"Texture project type: {texture_mode}")
    add('INFO', 'Setup',
        f"Texture roots — project: {project_folder or '(none)'} | riot: {wad_cache_dir or '(none)'}")

    # ── Parse mapgeo ──────────────────────────────────────────────────────
    mapgeo_data = None
    if loaded_mapgeo and os.path.isfile(loaded_mapgeo):
        try:
            mapgeo_data = mapgeo_parser.MapgeoParser().read(loaded_mapgeo)
            add('INFO', 'Mapgeo',
                f'Parsed mapgeo v{mapgeo_data.version}: '
                f'{len(mapgeo_data.meshes)} meshes, '
                f'{len(mapgeo_data.bucket_grids)} bucket grid(s).',
                file_path=loaded_mapgeo)
        except Exception as e:
            add('ERROR', 'Mapgeo', f'Failed to parse mapgeo: {e}', file_path=loaded_mapgeo)
    elif loaded_mapgeo:
        add('WARNING', 'Mapgeo', 'Loaded mapgeo path not found on disk.', detail=loaded_mapgeo)
    else:
        add('WARNING', 'Mapgeo', 'No mapgeo loaded — mapgeo checks skipped.')

    # ── Parse materials bin ───────────────────────────────────────────────
    bin_data = None
    if loaded_materials and os.path.isfile(loaded_materials):
        try:
            bin_data = propertybin_parser.parse_bin(loaded_materials)
            add('INFO', 'Materials',
                f'Parsed materials.bin: {len(bin_data.get("entries", []))} entries.',
                file_path=loaded_materials)
        except Exception as e:
            add('ERROR', 'Materials', f'Failed to parse materials.bin: {e}', file_path=loaded_materials)
    elif loaded_materials:
        add('WARNING', 'Materials', 'Loaded materials path not found on disk.', detail=loaded_materials)
    else:
        add('WARNING', 'Materials', 'No materials.bin loaded — materials checks skipped.')

    # ── Build lookup sets from bin ────────────────────────────────────────
    all_path_hashes  = set()   # "0x1a2b3c4d" hex strings
    mat_path_hashes  = set()   # path_hash hex strings for StaticMaterialDef entries
    mat_names_lower  = set()   # lowercased name strings from HASH_NAME fields

    if bin_data:
        for entry in bin_data.get('entries', []):
            ph = entry.get('path_hash', '')
            th = entry.get('type_hash', '')
            all_path_hashes.add(ph)
            th_int = int(th, 16) if (th and th.startswith('0x')) else 0
            if th_int == _HASH_STATIC_MAT:
                mat_path_hashes.add(ph)
                for fld in entry.get('fields', []):
                    ni = fld.get('name_hash_int', 0)
                    if ni == _HASH_NAME and fld.get('type') == _TYPE_STRING:
                        mat_names_lower.add(fld['value'].lower())
                        break

    # ── CHECK 1: Mapgeo → Materials ───────────────────────────────────────
    if mapgeo_data and bin_data:
        missing_mats = set()
        default_count = 0
        for mesh in mapgeo_data.meshes:
            for prim in mesh.primitives:
                name = prim.material
                if not name:
                    continue
                if name == 'Default':
                    default_count += 1
                    continue
                # Look up by FNV-1a hash (robust, doesn't rely on name field)
                ph = f"0x{_fnv1a_32(name):08x}"
                if ph not in all_path_hashes:
                    missing_mats.add(name)

        if missing_mats:
            for name in sorted(missing_mats):
                add('ERROR', 'Materials',
                    'Mapgeo material not found in materials.bin',
                    detail=name, file_path=loaded_mapgeo,
                    fix_id='MISSING_MATERIAL')
        else:
            total = sum(len(m.primitives) for m in mapgeo_data.meshes)
            add('INFO', 'Materials',
                f'All {total - default_count} mesh primitive materials resolve OK.')
        if default_count:
            add('WARNING', 'Materials',
                f'{default_count} mesh primitive(s) use "Default" material '
                f'(VFX placeholder — not expected in mapgeo)',
                file_path=loaded_mapgeo,
                fix_id='MISSING_MATERIAL')

    # ── CHECK 2: Materials → Textures ─────────────────────────────────────
    all_referenced_tex = set()  # union of sampler tex + mapgeo overrides
    riot_tex_set = set()        # known Riot original paths
    custom_tex_set = set()      # not in Riot hash DB (custom/renamed)
    unknown_tex_set = set()     # could not classify (hash DB unavailable)

    if bin_data:
        from . import project_manager as _pm

        sampler_total = 0
        unique_tex = set()
        missing_tex = []
        ok_count = 0
        sampler_field_entries = 0

        for entry in bin_data.get('entries', []):
            mat = _pm.convert_bin_entry_to_material_dict(entry)
            if not mat:
                continue
            samplers = mat.get('samplerValues') or []
            if samplers:
                sampler_field_entries += 1
            for s in samplers:
                tex = (s.get('texturePath') or '').replace('\\', '/').strip()
                if not tex:
                    continue
                sampler_total += 1
                if tex in unique_tex:
                    continue
                unique_tex.add(tex)
                all_referenced_tex.add(tex)

                # Classify Riot vs custom
                cls = _is_known_riot_texture_path(tex)
                if cls is True:
                    riot_tex_set.add(tex)
                elif cls is False:
                    custom_tex_set.add(tex)
                else:
                    unknown_tex_set.add(tex)

                if _texture_exists_for_project(tex):
                    ok_count += 1
                else:
                    missing_tex.append(tex)

        for tex in missing_tex:
            add('WARNING', 'Textures',
                'Texture file not found on disk',
                detail=tex, file_path=loaded_materials,
                fix_id='MISSING_TEXTURE')

        add('INFO', 'Textures',
            f'Sampler textures: {len(unique_tex)} unique '
            f'({sampler_total} total refs across {sampler_field_entries} materials) '
            f'\u2014 OK: {ok_count}, missing: {len(missing_tex)}.')
        add('INFO', 'Textures',
            f'Classification \u2014 Riot original: {len(riot_tex_set)}, '
            f'Custom/renamed: {len(custom_tex_set)}, '
            f'Unclassified: {len(unknown_tex_set)} '
            f'(hash DB {"loaded" if (riot_tex_set or custom_tex_set) else "may be unavailable"}).')

    # ── CHECK 3: Mapgeo texture overrides (v17+) ──────────────────────────
    if mapgeo_data and bin_data:
        sampler_def_names = {sd.index: sd.name for sd in mapgeo_data.sampler_defs}
        override_missing = []
        override_ok = 0
        override_total = 0
        override_unique = set()

        for mesh in mapgeo_data.meshes:
            for ov in mesh.texture_overrides:
                tex = ov.texture.replace('\\', '/')
                if not tex:
                    continue
                override_total += 1
                if tex in override_unique:
                    continue
                override_unique.add(tex)
                all_referenced_tex.add(tex)

                cls = _is_known_riot_texture_path(tex)
                if cls is True:
                    riot_tex_set.add(tex)
                elif cls is False:
                    custom_tex_set.add(tex)
                else:
                    unknown_tex_set.add(tex)

                if _texture_exists_for_project(tex):
                    override_ok += 1
                else:
                    slot_name = sampler_def_names.get(ov.index, f'slot {ov.index}')
                    override_missing.append((tex, slot_name))

        for tex, slot in override_missing:
            add('WARNING', 'Textures',
                f'Texture override not found (sampler: {slot})',
                detail=tex, file_path=loaded_mapgeo,
                fix_id='MISSING_TEXTURE')
        add('INFO', 'Textures',
            f'Mapgeo overrides: {len(override_unique)} unique '
            f'({override_total} total refs) \u2014 OK: {override_ok}, missing: {len(override_missing)}.')

    # ── CHECK 2b: AI texture audit (DEFERRED — runs on background thread) ─
    # Build the AI candidate list according to the chosen validation mode:
    #   MIXED         => audit every referenced texture
    #   REPLACED_RIOT => audit Riot-original references that should now exist in project
    #   FULLY_CUSTOM  => audit custom/unknown references (project must own them)
    ai_payload = None
    if (all_referenced_tex
            and checker_settings is not None
            and getattr(checker_settings, 'use_chatgpt_api', False)
            and (getattr(checker_settings, 'chatgpt_api_key', '') or '').strip()
            and project_folder
            and os.path.isdir(project_folder)):

        if texture_mode == 'REPLACED_RIOT':
            ai_targets = sorted(riot_tex_set | unknown_tex_set)
            ai_scope_label = "Riot+unknown (project must own these)"
        elif texture_mode == 'FULLY_CUSTOM':
            ai_targets = sorted(custom_tex_set | unknown_tex_set)
            ai_scope_label = "custom/unknown (project must own these)"
        else:  # MIXED
            ai_targets = sorted(all_referenced_tex)
            ai_scope_label = "all referenced textures"

        try:
            project_files = list(_iter_project_texture_files(project_folder))
        except Exception as e:
            project_files = []
            add('WARNING', 'AI Audit', f'Failed to scan project files: {e}')

        if ai_targets and project_files:
            add('INFO', 'AI Audit',
                f"ChatGPT scope: {ai_scope_label} \u2014 {len(ai_targets)} refs vs "
                f"{len(project_files)} project file(s). Running in background\u2026")
            ai_payload = {
                'targets': ai_targets,
                'project_files': project_files,
                'api_key': checker_settings.chatgpt_api_key.strip(),
                'model': (checker_settings.chatgpt_model or 'gpt-4o-mini').strip(),
                'materials_path': loaded_materials,
            }
        elif not project_files:
            add('WARNING', 'AI Audit',
                'No texture files found under project folder \u2014 nothing to match against.')

    # ── CHECK 4: Custom bucket grid ───────────────────────────────────────
    if mapgeo_data:
        active_grids = [bg for bg in mapgeo_data.bucket_grids if not bg.is_disabled]
        if active_grids:
            riot_mapgeo = None
            if wad_cache_dir:
                geo_root = os.path.join(wad_cache_dir, 'data', 'maps', 'mapgeometry')
                if os.path.isdir(geo_root):
                    for root, _dirs, files in os.walk(geo_root):
                        for fn in files:
                            if fn.endswith('.mapgeo'):
                                try:
                                    riot_mapgeo = mapgeo_parser.MapgeoParser().read(
                                        os.path.join(root, fn))
                                except Exception:
                                    continue
                                break
                        if riot_mapgeo:
                            break

            if riot_mapgeo:
                riot_hashes  = {bg.path_hash for bg in riot_mapgeo.bucket_grids}
                local_hashes = {bg.path_hash for bg in active_grids}
                is_custom    = local_hashes != riot_hashes
            else:
                is_custom = True   # no basis for comparison → assume custom

            if is_custom:
                add('INFO', 'BucketGrid',
                    f'Custom bucket grid detected ({len(active_grids)} active grid(s)).',
                    detail='This is a custom bucket grid. It will be exported as-is.',
                    file_path=loaded_mapgeo)
            else:
                add('INFO', 'BucketGrid',
                    f'Bucket grid matches Riot base ({len(active_grids)} grid(s)). OK.')
        else:
            add('INFO', 'BucketGrid', 'No active bucket grids found.')

    # ── CHECK 5: Visibility controller path_hashes ────────────────────────
    if mapgeo_data and bin_data:
        bad_vis  = []
        ok_vis   = 0

        # Build set of render_region_hash values used by meshes so we can
        # distinguish genuine VC lookups from render-region identifiers on
        # bucket grids.
        render_region_hashes = set()
        for mesh in mapgeo_data.meshes:
            rr = mesh.unknown_version18_int
            if rr and rr != 0:
                render_region_hashes.add(f"0x{rr:08x}")

        for i, mesh in enumerate(mapgeo_data.meshes):
            h = mesh.visibility_controller_path_hash
            if h and h != 0:
                ph_str = f"0x{h:08x}"
                if ph_str not in all_path_hashes:
                    bad_vis.append(f'Mesh #{i}: {ph_str}')
                else:
                    ok_vis += 1

        bad_bg_vis  = []
        ok_bg_vis   = 0
        rr_bg_count = 0
        for bg in mapgeo_data.bucket_grids:
            h = bg.path_hash
            if h and h != 0:
                ph_str = f"0x{h:08x}"
                if ph_str in all_path_hashes:
                    ok_bg_vis += 1
                elif ph_str in render_region_hashes:
                    # This is a render-region identifier, not a VC lookup
                    rr_bg_count += 1
                else:
                    bad_bg_vis.append(f'BucketGrid: {ph_str}')

        for item in bad_vis:
            add('ERROR', 'Visibility',
                'Visibility controller path_hash not in materials.bin',
                detail=item, file_path=loaded_mapgeo,
                fix_id='MISSING_VISIBILITY')
        for item in bad_bg_vis:
            add('ERROR', 'Visibility',
                'BucketGrid path_hash not in materials.bin',
                detail=item, file_path=loaded_mapgeo,
                fix_id='MISSING_VISIBILITY')
        ok_total = ok_vis + ok_bg_vis
        if ok_total:
            add('INFO', 'Visibility', f'{ok_total} visibility controller(s) resolved OK.')
        if rr_bg_count:
            add('INFO', 'Visibility',
                f'{rr_bg_count} bucket grid(s) use render-region hashes (no VC entry needed).')

    # ── CHECK 6: Linked bin files ─────────────────────────────────────────
    if bin_data:
        for linked in bin_data.get('linked_files', []):
            norm = linked.replace('\\', '/')
            ext  = os.path.splitext(norm)[1].lower()
            cat  = 'Soundbanks' if ext in _AUDIO_EXTENSIONS else 'LinkedFiles'

            if _file_exists(norm, asset_roots):
                add('INFO', cat,
                    f'Linked file found: {os.path.basename(norm)}',
                    detail=norm)
            else:
                add('WARNING', cat,
                    f'Linked file not found: {os.path.basename(norm)}',
                    detail=norm, file_path=loaded_materials)

    # ── CHECK 7: VFX / MapParticle cross-links (bin level) ──────────────
    if bin_data:
        vfx_types = {_HASH_VFX_SYSTEM, _HASH_MAP_PLACEABLE, _HASH_MAP_PARTICLE}
        bad_links  = []
        ok_links   = 0

        for entry in bin_data.get('entries', []):
            th = entry.get('type_hash', '')
            th_int = int(th, 16) if (th and th.startswith('0x')) else 0
            if th_int not in vfx_types:
                continue
            for fld in _walk_fields(entry.get('fields', [])):
                if fld.get('type') == _TYPE_LINK:
                    target = fld.get('value', '')
                    if target and target not in all_path_hashes:
                        bad_links.append(
                            f'Entry {entry.get("path_hash")} → {target}')
                    else:
                        ok_links += 1

        for item in bad_links:
            add('WARNING', 'VFX',
                'VFX/particle link target not found in materials.bin',
                detail=item, file_path=loaded_materials)
        if ok_links:
            add('INFO', 'VFX', f'{ok_links} VFX link(s) resolved OK.')

    # ── CHECK 7b: MapParticle → VFX_Definition (scene level) ─────────────
    # Verify each MapParticle in the scene references a VFX_Definition that
    # actually exists both in the Blender scene and in the materials.bin.
    vfx_defs_by_name = {}   # vfx_name → obj
    particle_systems = []   # (obj, system_name)

    for obj in bpy.context.scene.objects:
        if obj.get('is_vfx_definition'):
            vname = obj.get('vfx_name', '')
            if vname:
                vfx_defs_by_name[vname] = obj
        if obj.get('is_particle_system'):
            sys_name = obj.get('particle_system', '')
            if sys_name:
                particle_systems.append((obj, sys_name))

    if particle_systems:
        # Also build a set of VFX entry path_hashes in the bin
        vfx_bin_hashes = set()
        if bin_data:
            for entry in bin_data.get('entries', []):
                th = entry.get('type_hash', '')
                th_int = int(th, 16) if (th and th.startswith('0x')) else 0
                if th_int == _HASH_VFX_SYSTEM:
                    vfx_bin_hashes.add(entry.get('path_hash', ''))

        missing_scene = []
        missing_bin   = []
        ok_particle   = 0

        for obj, sys_name in particle_systems:
            # Check Blender scene
            has_scene_def = sys_name in vfx_defs_by_name
            # Check materials.bin by hashing the system name
            sys_hash = f"0x{_fnv1a_32(sys_name):08x}"
            has_bin_def = sys_hash in vfx_bin_hashes or sys_hash in all_path_hashes

            if has_scene_def and has_bin_def:
                ok_particle += 1
            elif not has_scene_def and not has_bin_def:
                missing_scene.append(f'{obj.name} → {sys_name} (missing in scene + bin)')
            elif not has_scene_def:
                missing_scene.append(f'{obj.name} → {sys_name} (missing in scene)')
            elif not has_bin_def:
                missing_bin.append(f'{obj.name} → {sys_name} (missing in bin)')

        for item in missing_scene:
            add('WARNING', 'VFX',
                'MapParticle references missing VFX definition',
                detail=item)
        for item in missing_bin:
            add('WARNING', 'VFX',
                'MapParticle VFX system not found in materials.bin',
                detail=item, file_path=loaded_materials)
        if ok_particle:
            add('INFO', 'VFX',
                f'{ok_particle} MapParticle(s) have matching VFX definitions.')
    elif vfx_defs_by_name:
        add('INFO', 'VFX',
            f'{len(vfx_defs_by_name)} VFX definition(s) loaded (no MapParticles to check).')

    # ── CHECK 8: Lightmap / stationary-light textures ─────────────────────
    if mapgeo_data:
        checked_lm = set()
        bad_lm  = []
        ok_lm   = 0

        for mesh in mapgeo_data.meshes:
            for channel, label in [
                (mesh.baked_light,       'BakedLight'),
                (mesh.stationary_light,  'StationaryLight'),
            ]:
                if not (channel and channel.texture):
                    continue
                tex = channel.texture.replace('\\', '/')
                if tex in checked_lm:
                    continue
                checked_lm.add(tex)
                if _tex_exists(tex, lightmap_roots):
                    ok_lm += 1
                else:
                    bad_lm.append((label, tex))

        for label, tex in bad_lm:
            add('WARNING', 'Lightmaps',
                f'{label} texture not found on disk',
                detail=tex, file_path=loaded_mapgeo)
        if ok_lm:
            add('INFO', 'Lightmaps', f'{ok_lm} lightmap texture(s) found OK.')

    # ── CHECK 9: TYPE_FILE WAD references ─────────────────────────────────
    # Only run if wad_tool hash tables are loaded to avoid slow load on every check
    if bin_data:
        try:
            from . import wad_tool
            # Only attempt resolution if hashes are already cached
            if wad_tool._wad_hashes or wad_tool._custom_hashes:
                unresolved_file_refs = []
                seen_hashes = set()

                for entry in bin_data.get('entries', []):
                    for fld in _walk_fields(entry.get('fields', [])):
                        if fld.get('type') == _TYPE_FILE:
                            hval = fld.get('value', '')
                            if hval in seen_hashes:
                                continue
                            seen_hashes.add(hval)
                            try:
                                h_int = int(hval, 16)
                                resolved = wad_tool.resolve_wad_hash(h_int)
                                if not resolved:
                                    unresolved_file_refs.append(hval)
                            except Exception:
                                pass

                if unresolved_file_refs:
                    add('INFO', 'WAD Refs',
                        f'{len(unresolved_file_refs)} WAD file reference(s) could not be resolved '
                        'to a known path (may just be missing from the hash dictionary).',
                        detail=', '.join(unresolved_file_refs[:8]) +
                               (f' … (+{len(unresolved_file_refs)-8} more)'
                                if len(unresolved_file_refs) > 8 else ''))
        except Exception:
            pass

    # ── CHECK 10: MapSkin / map.bin links ─────────────────────────────────
    # If the project has a map11.bin / shippping bin, check it too
    if project_folder and map_id:
        map_id_num = ''.join(c for c in map_id if c.isdigit())
        map_id_lower = f'map{map_id_num}'
        shipping_candidates = [
            os.path.join(project_folder, 'data', 'maps', 'shipping',
                         map_id_lower, f'{map_id_lower}.bin'),
            os.path.join(wad_cache_dir, 'data', 'maps', 'shipping',
                         map_id_lower, f'{map_id_lower}.bin') if wad_cache_dir else '',
        ]
        for spath in shipping_candidates:
            if spath and os.path.isfile(spath):
                try:
                    sbin = propertybin_parser.parse_bin(spath)
                    skins_entry_count = sum(
                        1 for e in sbin.get('entries', [])
                        if e.get('type_hash', '') == f"0x{_HASH_VIS_CTRL:08x}"
                    )
                    add('INFO', 'MapBin',
                        f'Shipping map bin parsed OK: {len(sbin.get("entries", []))} entries',
                        detail=spath)
                    # Check its linked_files too
                    for lf in sbin.get('linked_files', []):
                        norm = lf.replace('\\', '/')
                        if not _file_exists(norm, asset_roots):
                            add('WARNING', 'MapBin',
                                f'map.bin linked file not found: {os.path.basename(norm)}',
                                detail=norm, file_path=spath)
                except Exception as e:
                    add('WARNING', 'MapBin',
                        f'Could not parse shipping bin: {e}', detail=spath)
                break

    return issues, ai_payload


# ============================================================================
# Background AI worker (non-blocking)
# ============================================================================

_ai_worker_state = {
    'thread': None,
    'result': None,   # dict from _chatgpt_audit_textures
    'error': None,    # str
    'payload': None,  # original payload (for materials_path)
    'done': False,
}


def _ai_worker_run(payload):
    import threading

    def _work():
        try:
            # Heavy filesystem scan happens here, OFF the main thread
            project_files = list(_iter_project_texture_files(payload.get('project_folder', '')))
            if not project_files:
                _ai_worker_state['error'] = (
                    'No texture files found under project folder — nothing to match against.'
                )
                return
            res = _chatgpt_audit_textures(
                payload['targets'],
                project_files,
                api_key=payload['api_key'],
                model=payload['model'],
            )
            _ai_worker_state['result'] = res
            _ai_worker_state['scanned_files'] = len(project_files)
        except Exception as e:
            _ai_worker_state['error'] = str(e)
        finally:
            _ai_worker_state['done'] = True

    _ai_worker_state.update({'thread': None, 'result': None, 'error': None,
                             'payload': payload, 'done': False, 'scanned_files': 0})
    t = threading.Thread(target=_work, name='MapgeoAIAudit', daemon=True)
    _ai_worker_state['thread'] = t
    t.start()


def _ai_worker_poll():
    """bpy.app.timers callback: returns interval (s) until next poll, or None to stop."""
    if not _ai_worker_state.get('done'):
        return 0.5

    try:
        scene = bpy.context.scene
        checker = getattr(scene, 'project_checker', None)
        if checker is None:
            return None

        payload = _ai_worker_state.get('payload') or {}
        materials_path = payload.get('materials_path', '')

        def _add(sev, cat, msg, detail='', fix_id=''):
            it = checker.issues.add()
            it.severity = sev
            it.category = cat
            it.message = msg
            it.detail = detail
            it.file_path = materials_path
            it.fix_id = fix_id
            if sev == 'ERROR':
                checker.error_count += 1
            elif sev == 'WARNING':
                checker.warning_count += 1
            else:
                checker.info_count += 1

        err = _ai_worker_state.get('error')
        if err:
            _add('WARNING', 'AI Audit', f'ChatGPT audit failed: {err}')
        else:
            res = _ai_worker_state.get('result') or {}
            _add('INFO', 'AI Audit',
                 f"ChatGPT result: {len(res.get('exact', []))} exact, "
                 f"{len(res.get('fuzzy', []))} fuzzy, "
                 f"{len(res.get('missing', []))} truly missing.")
            for item in res.get('fuzzy', []):
                ref = item.get('ref', '')
                cand = item.get('candidate', '')
                if not ref:
                    continue
                _add('WARNING', 'AI Audit',
                     'AI suggests this texture exists under a different path',
                     detail=f"{ref}  =>  {cand}",
                     fix_id='MISSING_TEXTURE')
            for ref in res.get('missing', []):
                if not ref:
                    continue
                _add('ERROR', 'AI Audit',
                     'AI confirms texture is missing from project',
                     detail=ref,
                     fix_id='MISSING_TEXTURE')

        # Force a UI redraw so the new rows appear
        for area in bpy.context.window.screen.areas:
            area.tag_redraw()
    except Exception as e:
        print(f"[Project Checker] AI poll error: {e}")
    finally:
        _ai_worker_state['payload'] = None
        _ai_worker_state['result'] = None
        _ai_worker_state['error'] = None
        _ai_worker_state['thread'] = None
        _ai_worker_state['done'] = False
    return None


# ============================================================================
# Operator
# ============================================================================

class PROJ_OT_run_integrity_check(Operator):
    bl_idname = "project.run_integrity_check"
    bl_label = "Check Project Integrity"
    bl_description = (
        "Scan all loaded project files for broken references: "
        "materials, textures, VFX links, visibility controllers, "
        "linked bins, lightmaps, and audio banks"
    )

    def execute(self, context):
        checker  = context.scene.project_checker
        settings = context.scene.project_settings

        if not settings.project_folder:
            self.report({'ERROR'}, "No project folder set in Project Manager.")
            return {'CANCELLED'}

        # Clear old results
        checker.issues.clear()

        try:
            issues, ai_payload = run_checks(settings, checker)
        except Exception as e:
            import traceback
            self.report({'ERROR'}, f"Integrity check failed: {e}")
            print(f"[Project Checker] Exception:\n{traceback.format_exc()}")
            return {'CANCELLED'}

        # Populate collection
        errors = warnings = infos = 0
        for issue in issues:
            item              = checker.issues.add()
            item.severity     = issue['severity']
            item.category     = issue['category']
            item.message      = issue['message']
            item.detail       = issue.get('detail', '')
            item.file_path    = issue.get('file_path', '')
            item.fix_id       = issue.get('fix_id', '')
            if issue['severity'] == 'ERROR':
                errors += 1
            elif issue['severity'] == 'WARNING':
                warnings += 1
            else:
                infos += 1

        checker.error_count   = errors
        checker.warning_count = warnings
        checker.info_count    = infos
        checker.last_run      = datetime.now().strftime("%Y-%m-%d %H:%M")
        checker.active_index  = 0

        msg = f"Check complete: {errors} error(s), {warnings} warning(s), {infos} info"
        self.report({'WARNING' if errors else 'INFO'}, msg)

        # Kick off the AI audit on a background thread so Blender stays responsive
        if ai_payload:
            try:
                _ai_worker_run(ai_payload)
                if not bpy.app.timers.is_registered(_ai_worker_poll):
                    bpy.app.timers.register(_ai_worker_poll, first_interval=0.5)
                self.report({'INFO'}, "AI audit running in background… results will appear shortly.")
            except Exception as e:
                self.report({'WARNING'}, f"Could not start AI audit thread: {e}")

        return {'FINISHED'}


class PROJ_OT_clear_check_results(Operator):
    bl_idname = "project.clear_check_results"
    bl_label  = "Clear Results"
    bl_description = "Clear all integrity check results"

    def execute(self, context):
        c = context.scene.project_checker
        c.issues.clear()
        c.error_count = c.warning_count = c.info_count = 0
        c.last_run = ""
        return {'FINISHED'}


class PROJ_OT_open_issue_file(Operator):
    """Open the file associated with the selected issue in the OS file browser."""
    bl_idname  = "project.open_issue_file"
    bl_label   = "Show File"
    bl_description = "Reveal this file in the OS file explorer"
    file_path: StringProperty(default="")

    def execute(self, context):
        path = self.file_path
        if path and os.path.isfile(path):
            import subprocess
            try:
                subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
            except Exception:
                pass
        return {'FINISHED'}


class PROJ_OT_select_issue_meshes(Operator):
    """Select mesh objects affected by the selected issue"""
    bl_idname  = "project.select_issue_meshes"
    bl_label   = "Select Affected Meshes"
    bl_description = "Select all mesh objects affected by this issue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        checker = context.scene.project_checker
        idx = checker.active_index
        if idx < 0 or idx >= len(checker.issues):
            self.report({'ERROR'}, "No issue selected")
            return {'CANCELLED'}

        item = checker.issues[idx]
        fix_id = item.fix_id

        if fix_id == 'MISSING_MATERIAL':
            return self._select_by_material(context, item.detail)
        elif fix_id == 'MISSING_VISIBILITY':
            return self._select_by_visibility(context, item.detail)

        self.report({'WARNING'}, "No mesh selection available for this issue type")
        return {'CANCELLED'}

    def _select_by_material(self, context, mat_name):
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            for mat_slot in obj.material_slots:
                mat = mat_slot.material
                if mat and mat.get('league_material_name') == mat_name:
                    obj.select_set(True)
                    count += 1
                    break

        self.report({'INFO'}, f"Selected {count} mesh(es) using '{mat_name}'")
        return {'FINISHED'}

    def _select_by_visibility(self, context, detail):
        """Select meshes whose visibility_controller_path_hash matches the issue detail."""
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        # detail format: "Mesh #<idx>: 0x<hash>" or "BucketGrid: 0x<hash>"
        hash_str = detail.split(':')[-1].strip() if ':' in detail else ''
        try:
            target_hash = int(hash_str, 16)
        except (ValueError, TypeError):
            self.report({'ERROR'}, f"Could not parse hash from: {detail}")
            return {'CANCELLED'}

        # baron_hash is stored as uppercase hex WITHOUT 0x prefix (e.g. "1A2B3C4D")
        target_baron = f"{target_hash:08X}"

        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            baron = obj.get('baron_hash', '')
            if baron and baron.upper() == target_baron:
                obj.select_set(True)
                count += 1

        self.report({'INFO'}, f"Selected {count} mesh(es) with visibility hash {hash_str}")
        return {'FINISHED'}


class PROJ_OT_fix_issue(Operator):
    """Automatically fix the selected issue"""
    bl_idname  = "project.fix_issue"
    bl_label   = "Fix Issue"
    bl_description = "Automatically fix this issue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        checker = context.scene.project_checker
        idx = checker.active_index
        if idx < 0 or idx >= len(checker.issues):
            self.report({'ERROR'}, "No issue selected")
            return {'CANCELLED'}

        item = checker.issues[idx]
        if item.fix_id == 'MISSING_MATERIAL':
            return self._fix_missing_material(context, item.detail)
        if item.fix_id == 'MISSING_TEXTURE':
            return self._fix_missing_texture(context, item.detail)

        self.report({'WARNING'}, "No auto-fix available for this issue type")
        return {'CANCELLED'}

    def _fix_missing_material(self, context, mat_name):
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        fixed_count = 0
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.data:
                continue
            slots_to_remove = []
            for slot_idx, mat_slot in enumerate(obj.material_slots):
                mat = mat_slot.material
                if mat and mat.get('league_material_name') == mat_name:
                    slots_to_remove.append(slot_idx)

            if not slots_to_remove:
                continue

            context.view_layer.objects.active = obj
            for slot_idx in reversed(slots_to_remove):
                obj.active_material_index = slot_idx
                bpy.ops.object.material_slot_remove()
            fixed_count += 1

        if fixed_count:
            self.report({'INFO'}, f"Removed '{mat_name}' material from {fixed_count} mesh(es)")
        else:
            self.report({'INFO'}, f"No meshes found with '{mat_name}' material")
        return {'FINISHED'}

    def _fix_missing_texture(self, context, missing_tex):
        settings = context.scene.project_settings
        project_root = bpy.path.abspath(settings.project_folder) if settings.project_folder else ""
        if not project_root or not os.path.isdir(project_root):
            self.report({'ERROR'}, "Project Folder is not set or invalid")
            return {'CANCELLED'}

        expected = (missing_tex or '').replace('\\', '/').strip()
        if not expected:
            self.report({'ERROR'}, "No texture path in issue detail")
            return {'CANCELLED'}

        # If another process already resolved it, skip cleanly.
        if os.path.isfile(os.path.join(project_root, expected.replace('/', os.sep))):
            self.report({'INFO'}, f"Texture already exists: {expected}")
            return {'FINISHED'}

        best_rel, score = _best_texture_candidate(expected, project_root)
        if not best_rel:
            self.report({'WARNING'}, f"AI Fix: no candidate found for {expected}")
            return {'CANCELLED'}

        # Safety floor: avoid bad matches.
        if score < 0.58:
            self.report({'WARNING'},
                        f"AI Fix confidence too low ({score:.2f}) for {expected} -> {best_rel}")
            return {'CANCELLED'}

        try:
            _dst, mode = _create_texture_alias(project_root, best_rel, expected)
        except Exception as e:
            self.report({'ERROR'}, f"AI Fix failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"AI Fix ({mode}): {expected} -> source {best_rel} (confidence {score:.2f})")
        return {'FINISHED'}


class PROJ_OT_fix_texture_name_variants(Operator):
    """Resolve missing textures whose file exists in the same directory under a
    season-variant name (e.g. ``foo.summer.tex`` instead of ``foo.tex``).

    For every MISSING_TEXTURE issue, looks in the expected directory for files
    whose stem differs only by extra dot-separated tokens (season tags). If
    found, creates the bin-expected file (rename or copy) so the engine and
    Blender both find it.
    """
    bl_idname = "project.fix_texture_name_variants"
    bl_label = "Fix Texture Name Variants"
    bl_description = (
        "Find missing textures whose file exists under a season-variant "
        "name (foo.summer.tex vs foo.tex) and create the expected name"
    )
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(
        name="Action",
        description="What to do with the season-variant file",
        items=[
            ('COPY', "Copy (keep original)",
             "Copy the season-variant file to the expected name, keep the original"),
            ('RENAME', "Rename (replace original)",
             "Rename the season-variant file to the expected name (only if no other ref needs the original)"),
        ],
        default='COPY',
    )
    dry_run: BoolProperty(
        name="Dry Run",
        description="Only report what would change, do not modify files",
        default=False,
    )

    def execute(self, context):
        import shutil
        checker = context.scene.project_checker
        settings = context.scene.project_settings

        project_root = bpy.path.abspath(settings.project_folder) if settings.project_folder else ""
        if not project_root or not os.path.isdir(project_root):
            self.report({'ERROR'}, "Project Folder is not set or invalid")
            return {'CANCELLED'}

        # Collect unique missing-texture refs from the current issue list
        targets = []
        seen = set()
        for issue in checker.issues:
            if issue.fix_id != 'MISSING_TEXTURE':
                continue
            expected = (issue.detail or '').replace('\\', '/').strip()
            if not expected:
                continue
            key = expected.lower()
            if key in seen:
                continue
            seen.add(key)
            targets.append(expected)

        if not targets:
            self.report({'WARNING'}, "No missing texture issues to scan")
            return {'CANCELLED'}

        fixed = 0
        no_variant = 0
        already = 0
        failed = 0

        lines = ["Texture name-variant fix report",
                 f"Project: {project_root}",
                 f"Action: {self.action}",
                 f"Dry run: {self.dry_run}",
                 f"Targets: {len(targets)}", ""]

        for expected_rel in targets:
            dst_abs = os.path.join(project_root, expected_rel.replace('/', os.sep))
            if os.path.isfile(dst_abs):
                already += 1
                lines.append(f"[ALREADY] {expected_rel}")
                continue

            base_no_ext, _ext = os.path.splitext(expected_rel)
            rel_dir, base_name = os.path.split(base_no_ext)
            variant_rel = _find_season_variant(project_root, rel_dir, base_name)
            if not variant_rel:
                no_variant += 1
                lines.append(f"[NO_VARIANT] {expected_rel}")
                continue

            src_abs = os.path.join(project_root, variant_rel.replace('/', os.sep))

            # If src and dst extensions differ, we need conversion not a plain copy.
            src_ext = os.path.splitext(src_abs)[1].lower()
            dst_ext = os.path.splitext(dst_abs)[1].lower()
            need_convert = (src_ext != dst_ext)

            if self.dry_run:
                tag = "WOULD_CONVERT" if need_convert else f"WOULD_{self.action}"
                lines.append(f"[{tag}] {expected_rel}  <=  {variant_rel}")
                fixed += 1
                continue

            try:
                os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                if need_convert:
                    # Use the existing alias helper which handles TEX<->DDS.
                    _create_texture_alias(project_root, variant_rel, expected_rel)
                    lines.append(f"[CONVERTED] {expected_rel}  <=  {variant_rel}")
                elif self.action == 'RENAME':
                    os.rename(src_abs, dst_abs)
                    lines.append(f"[RENAMED] {expected_rel}  <=  {variant_rel}")
                else:  # COPY
                    shutil.copy2(src_abs, dst_abs)
                    lines.append(f"[COPIED] {expected_rel}  <=  {variant_rel}")
                fixed += 1
            except Exception as e:
                failed += 1
                lines.append(f"[FAIL] {expected_rel}  <=  {variant_rel}: {e}")

        lines.append("")
        lines.append("Summary")
        lines.append(f"  Targets:    {len(targets)}")
        lines.append(f"  Fixed:      {fixed}")
        lines.append(f"  Already:    {already}")
        lines.append(f"  No variant: {no_variant}")
        lines.append(f"  Failed:     {failed}")

        report_text = "\n".join(lines)
        context.window_manager.clipboard = report_text
        print("[Project Checker] " + report_text.replace("\n", "\n[Project Checker] "))

        verb = "would fix" if self.dry_run else "fixed"
        self.report({'INFO'},
                    f"Name variants: {verb} {fixed}, already {already}, "
                    f"no variant {no_variant}, failed {failed} (report copied)")
        return {'FINISHED'}


class PROJ_OT_fix_texture_extensions(Operator):
    """Repair texture files whose extension does not match their actual format.

    Two strategies (selectable):
      - RENAME: just rename the file extension to match the magic bytes
                (lossless, fast, recommended).
      - CONVERT: re-encode the file in-place to match its current extension
                 (use when the extension is the contract you must keep).
    """
    bl_idname = "project.fix_texture_extensions"
    bl_label = "Fix TEX/DDS Extensions"
    bl_description = (
        "Find .tex files that are actually DDS (and .dds files that are "
        "actually TEX) and repair the mismatch by renaming or re-encoding"
    )
    bl_options = {'REGISTER', 'UNDO'}

    strategy: EnumProperty(
        name="Strategy",
        description="How to fix mismatched texture files",
        items=[
            ('RENAME', "Rename to Match Content",
             "Rename the file extension so it matches the real bytes (lossless, recommended)"),
            ('CONVERT', "Convert to Match Extension",
             "Re-encode the file in place so its bytes match the current extension"),
        ],
        default='RENAME',
    )
    dry_run: BoolProperty(
        name="Dry Run",
        description="Only report what would change, do not modify files",
        default=False,
    )

    def execute(self, context):
        settings = context.scene.project_settings
        project_root = bpy.path.abspath(settings.project_folder) if settings.project_folder else ""
        if not project_root or not os.path.isdir(project_root):
            self.report({'ERROR'}, "Project Folder is not set or invalid")
            return {'CANCELLED'}

        from . import texture_utils

        scanned = 0
        already_ok = 0
        repaired = 0
        failed = 0
        skipped = 0

        lines = ["TEX/DDS extension repair report",
                 f"Project: {project_root}",
                 f"Strategy: {self.strategy}",
                 f"Dry run: {self.dry_run}", ""]

        def _unique_dst(path: str) -> str:
            """Return path or path with numeric suffix if it already exists."""
            if not os.path.exists(path):
                return path
            base, ext = os.path.splitext(path)
            i = 1
            while True:
                cand = f"{base}__{i}{ext}"
                if not os.path.exists(cand):
                    return cand
                i += 1

        for root, _dirs, files in os.walk(project_root):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in ('.tex', '.dds'):
                    continue
                full = os.path.join(root, fn)
                try:
                    with open(full, 'rb') as fh:
                        head = fh.read(8)
                except Exception as e:
                    failed += 1
                    lines.append(f"[READ_FAIL] {full}: {e}")
                    continue
                scanned += 1

                if ext == '.tex' and head[:4] == b'TEX\0':
                    already_ok += 1
                    continue
                if ext == '.dds' and head[:4] == b'DDS ':
                    already_ok += 1
                    continue

                rel = os.path.relpath(full, project_root)

                # Determine actual format
                if head[:4] == b'TEX\0':
                    actual = '.tex'
                elif head[:4] == b'DDS ':
                    actual = '.dds'
                else:
                    skipped += 1
                    lines.append(f"[UNKNOWN_FORMAT] {rel} (head={head[:4]!r})")
                    continue

                if self.strategy == 'RENAME':
                    new_full = _unique_dst(os.path.splitext(full)[0] + actual)
                    new_rel = os.path.relpath(new_full, project_root)
                    if self.dry_run:
                        lines.append(f"[WOULD_RENAME {ext}->{actual}] {rel}  ->  {new_rel}")
                        repaired += 1
                        continue
                    try:
                        os.rename(full, new_full)
                        repaired += 1
                        lines.append(f"[RENAMED {ext}->{actual}] {rel}  ->  {new_rel}")
                    except Exception as e:
                        failed += 1
                        lines.append(f"[FAIL_RENAME {ext}->{actual}] {rel}: {e}")
                    continue

                # CONVERT: re-encode bytes in place to match current extension
                if actual == '.tex' and ext == '.dds':
                    if self.dry_run:
                        lines.append(f"[WOULD_CONVERT TEX->DDS] {rel}")
                        repaired += 1
                        continue
                    try:
                        with open(full, 'rb') as fh:
                            tex_data = fh.read()
                        dds_data = texture_utils.TexConverter._tex_to_dds(tex_data)
                        with open(full, 'wb') as fh:
                            fh.write(dds_data)
                        repaired += 1
                        lines.append(f"[CONVERTED TEX->DDS] {rel}")
                    except Exception as e:
                        failed += 1
                        lines.append(f"[FAIL TEX->DDS] {rel}: {e}")
                elif actual == '.dds' and ext == '.tex':
                    if self.dry_run:
                        lines.append(f"[WOULD_CONVERT DDS->TEX] {rel}")
                        repaired += 1
                        continue
                    try:
                        import tempfile
                        with tempfile.NamedTemporaryFile(
                                suffix='.dds', delete=False) as tmp:
                            with open(full, 'rb') as src:
                                tmp.write(src.read())
                            tmp_path = tmp.name
                        try:
                            texture_utils.convert_dds_to_tex_file(tmp_path, full)
                        finally:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass
                        repaired += 1
                        lines.append(f"[CONVERTED DDS->TEX] {rel}")
                    except Exception as e:
                        failed += 1
                        lines.append(f"[FAIL DDS->TEX] {rel}: {e}")

        lines.append("")
        lines.append("Summary")
        lines.append(f"  Scanned:    {scanned}")
        lines.append(f"  Already OK: {already_ok}")
        lines.append(f"  Repaired:   {repaired}")
        lines.append(f"  Failed:     {failed}")
        lines.append(f"  Skipped:    {skipped}")

        report_text = "\n".join(lines)
        context.window_manager.clipboard = report_text
        print("[Project Checker] " + report_text.replace("\n", "\n[Project Checker] "))

        verb = "would repair" if self.dry_run else "repaired"
        self.report({'INFO'},
                    f"TEX/DDS {self.strategy.lower()}: {verb} {repaired}, ok {already_ok}, "
                    f"failed {failed}, skipped {skipped} (report copied)")
        return {'FINISHED'}


class PROJ_OT_fix_all_missing_textures(Operator):
    """Batch AI fix for all missing texture issues in the current checker list."""
    bl_idname = "project.fix_all_missing_textures"
    bl_label = "AI Fix All Missing Textures"
    bl_description = (
        "Try to auto-resolve every missing texture by matching the nearest existing "
        "project texture path and creating aliases"
    )
    bl_options = {'REGISTER', 'UNDO'}

    rerun_check: BoolProperty(
        name="Re-run Integrity Check",
        description="Automatically run integrity check after batch AI fix",
        default=True,
    )

    def execute(self, context):
        checker = context.scene.project_checker
        settings = context.scene.project_settings

        project_root = bpy.path.abspath(settings.project_folder) if settings.project_folder else ""
        if not project_root or not os.path.isdir(project_root):
            self.report({'ERROR'}, "Project Folder is not set or invalid")
            return {'CANCELLED'}

        min_conf = float(getattr(checker, 'ai_fix_min_confidence', 0.58) or 0.58)

        targets = []
        seen = set()
        for issue in checker.issues:
            if issue.fix_id != 'MISSING_TEXTURE':
                continue
            expected = (issue.detail or '').replace('\\', '/').strip()
            if not expected:
                continue
            key = expected.lower()
            if key in seen:
                continue
            seen.add(key)
            targets.append(expected)

        if not targets:
            self.report({'WARNING'}, "No missing texture issues to fix")
            return {'CANCELLED'}

        # Optional: ask ChatGPT for suggested mappings up-front
        gpt_map = {}
        gpt_used = False
        gpt_error = ""
        if getattr(checker, 'use_chatgpt_api', False) and (checker.chatgpt_api_key or "").strip():
            try:
                candidates = list(_iter_project_texture_files(project_root))
                gpt_map = _chatgpt_match_textures(
                    targets, candidates,
                    api_key=checker.chatgpt_api_key.strip(),
                    model=(checker.chatgpt_model or "gpt-4o-mini").strip(),
                )
                gpt_used = True
            except Exception as e:
                gpt_error = str(e)
                print(f"[Project Checker] ChatGPT fallback to local heuristic: {e}")

        fixed = 0
        already = 0
        no_candidate = 0
        low_conf = 0
        failed = 0
        gpt_hits = 0

        lines = []
        lines.append("AI Texture Batch Fix Report")
        lines.append(f"Project: {project_root}")
        lines.append(f"Min confidence: {min_conf:.2f}")
        lines.append(f"Targets: {len(targets)}")
        if gpt_used:
            lines.append(f"ChatGPT model: {checker.chatgpt_model} (mappings: {len(gpt_map)})")
        if gpt_error:
            lines.append(f"ChatGPT error (using local heuristic): {gpt_error}")
        lines.append("")

        for expected in targets:
            dst = os.path.join(project_root, expected.replace('/', os.sep))
            if os.path.isfile(dst):
                already += 1
                lines.append(f"[ALREADY] {expected}")
                continue

            # Prefer ChatGPT suggestion when available
            gpt_choice = gpt_map.get(expected.replace('\\', '/').strip().lower(), "")
            if gpt_choice:
                try:
                    _dst, mode = _create_texture_alias(project_root, gpt_choice, expected)
                    fixed += 1
                    gpt_hits += 1
                    lines.append(
                        f"[FIXED gpt {mode}] {expected}  <=  {gpt_choice}"
                    )
                    continue
                except Exception as e:
                    lines.append(
                        f"[GPT_FAIL] {expected}  <=  {gpt_choice}  ({e}) \u2014 trying local"
                    )

            best_rel, score = _best_texture_candidate(expected, project_root)
            if not best_rel:
                no_candidate += 1
                lines.append(f"[NO_CANDIDATE] {expected}")
                continue

            if score < min_conf:
                low_conf += 1
                lines.append(
                    f"[LOW_CONF {score:.2f}] {expected}  <=  {best_rel}"
                )
                continue

            try:
                _dst, mode = _create_texture_alias(project_root, best_rel, expected)
                fixed += 1
                lines.append(
                    f"[FIXED {score:.2f} {mode}] {expected}  <=  {best_rel}"
                )
            except Exception as e:
                failed += 1
                lines.append(
                    f"[FAILED {score:.2f}] {expected}  <=  {best_rel}  ({e})"
                )

        lines.append("")
        lines.append("Summary")
        lines.append(f"  Fixed: {fixed}  (ChatGPT-driven: {gpt_hits})")
        lines.append(f"  Already present: {already}")
        lines.append(f"  Low confidence: {low_conf}")
        lines.append(f"  No candidate: {no_candidate}")
        lines.append(f"  Failed: {failed}")

        report_text = "\n".join(lines)
        context.window_manager.clipboard = report_text
        print("[Project Checker] " + report_text.replace("\n", "\n[Project Checker] "))

        if self.rerun_check:
            try:
                bpy.ops.project.run_integrity_check()
            except Exception as e:
                self.report({'WARNING'}, f"Batch done, but re-check failed: {e}")

        self.report(
            {'INFO'},
            f"AI batch done: fixed={fixed}, low_conf={low_conf}, no_candidate={no_candidate}, failed={failed} (report copied)")
        return {'FINISHED'}


class PROJ_OT_fix_visibility(Operator):
    """Import missing visibility controller entries from another materials.bin"""
    bl_idname  = "project.fix_visibility"
    bl_label   = "Import Visibility Controller"
    bl_description = (
        "Browse for a materials.bin that contains the missing baron hash "
        "visibility controller, and add it to your project's materials.bin"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import copy
        from . import propertybin_parser

        checker  = context.scene.project_checker
        settings = context.scene.project_settings

        # Gather all missing visibility path hashes from current issues
        missing_hashes = set()
        for issue in checker.issues:
            if issue.fix_id != 'MISSING_VISIBILITY':
                continue
            detail = issue.detail
            hash_str = detail.split(':')[-1].strip() if ':' in detail else ''
            if hash_str:
                missing_hashes.add(hash_str.lower())

        if not missing_hashes:
            self.report({'INFO'}, "No missing visibility controllers to import")
            return {'CANCELLED'}

        # Parse the source bin the user selected
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "Selected file does not exist")
            return {'CANCELLED'}

        try:
            source_data = propertybin_parser.parse_bin(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse source bin: {e}")
            return {'CANCELLED'}

        # Find matching entries in the source
        entries_to_inject = []
        for entry in source_data.get('entries', []):
            ph = entry.get('path_hash', '').lower()
            if ph in missing_hashes:
                entries_to_inject.append(copy.deepcopy(entry))

        if not entries_to_inject:
            self.report({'WARNING'},
                        f"Source bin does not contain any of the {len(missing_hashes)} "
                        f"missing visibility controller(s)")
            return {'CANCELLED'}

        # Load the project's materials.bin
        project_bin_path = bpy.path.abspath(settings.loaded_materials_path) \
            if settings.loaded_materials_path else ''
        if not project_bin_path or not os.path.isfile(project_bin_path):
            self.report({'ERROR'}, "No project materials.bin loaded")
            return {'CANCELLED'}

        try:
            target_data = propertybin_parser.parse_bin(project_bin_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse project bin: {e}")
            return {'CANCELLED'}

        # Check for duplicates and inject
        existing = {e.get('path_hash', '').lower()
                    for e in target_data.get('entries', [])}
        injected = 0
        for entry in entries_to_inject:
            ph = entry.get('path_hash', '').lower()
            if ph not in existing:
                target_data['entries'].append(entry)
                existing.add(ph)
                injected += 1

        if injected == 0:
            self.report({'INFO'}, "All entries already exist in project bin")
            return {'FINISHED'}

        # Write back
        try:
            propertybin_parser.write_bin(target_data, project_bin_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write project bin: {e}")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Imported {injected} visibility controller(s) into "
                    f"{os.path.basename(project_bin_path)}")
        return {'FINISHED'}


# ============================================================================
# UIList
# ============================================================================

class PROJ_UL_check_issues(UIList):
    bl_idname = "PROJ_UL_check_issues"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        checker = data
        filter_mode = checker.filter_mode

        if filter_mode != 'ALL' and item.severity != filter_mode:
            return

        row = layout.row(align=True)

        # Severity badge
        sev_icon = _SEV_ICONS.get(item.severity, 'INFO')
        row.label(text="", icon=sev_icon)

        # Category
        cat_col = row.column()
        cat_col.ui_units_x = 8
        cat_col.label(text=item.category)

        # Message
        row.label(text=item.message)

    def filter_items(self, context, data, property):
        checker = data
        filter_mode = checker.filter_mode
        items = getattr(data, property)

        flt_flags = []
        flt_order = list(range(len(items)))

        if filter_mode == 'ALL':
            flt_flags = [self.bitflag_filter_item] * len(items)
        else:
            for item in items:
                if item.severity == filter_mode:
                    flt_flags.append(self.bitflag_filter_item)
                else:
                    flt_flags.append(0)

        return flt_flags, flt_order


# ============================================================================
# Sub-panel (child of Project Manager)
# ============================================================================

class VIEW3D_PT_project_checker(Panel):
    bl_label   = "Project Integrity"
    bl_idname  = "VIEW3D_PT_project_checker"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'LoL Mapgeo'
    bl_parent_id   = 'VIEW3D_PT_project_manager'
    bl_options     = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        checker = context.scene.project_checker
        layout  = self.layout
        if checker.error_count > 0:
            layout.label(text="", icon='ERROR')
        elif checker.warning_count > 0:
            layout.label(text="", icon='QUESTION')
        elif checker.last_run:
            layout.label(text="", icon='CHECKMARK')

    def draw(self, context):
        layout  = self.layout
        checker = context.scene.project_checker
        settings = context.scene.project_settings

        # ── Run button ────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.3
        op_row = row.row(align=True)
        op_row.enabled = bool(settings.project_folder)
        op_row.operator("project.run_integrity_check",
                        text="Check Project", icon='VIEWZOOM')

        if checker.last_run:
            row.operator("project.clear_check_results", text="", icon='X')

        if checker.last_run:
            layout.label(text=f"Last run: {checker.last_run}", icon='TIME')

        mode_box = layout.box()
        mode_box.label(text="Texture Validation Mode", icon='TEXTURE')
        mode_box.prop(checker, "texture_project_mode", text="")

        # ── Summary ───────────────────────────────────────────────────────
        if checker.last_run:
            sum_row = layout.row(align=True)
            sum_row.alignment = 'CENTER'
            err_col = sum_row.column()
            err_col.alert = checker.error_count > 0
            err_col.label(text=f"{checker.error_count} Error(s)",   icon='ERROR')
            sum_row.label(text=f"{checker.warning_count} Warning(s)", icon='QUESTION')
            sum_row.label(text=f"{checker.info_count} Info",          icon='INFO')

            ai_box = layout.box()
            ai_box.label(text="AI Texture Repair", icon='FILE_REFRESH')
            ai_box.prop(checker, "ai_fix_min_confidence")

            gpt_box = ai_box.box()
            gpt_box.prop(checker, "use_chatgpt_api", text="Use ChatGPT API (optional)")
            sub = gpt_box.column(align=True)
            sub.enabled = checker.use_chatgpt_api
            sub.prop(checker, "chatgpt_api_key", text="API Key")
            sub.prop(checker, "chatgpt_model", text="Model")

            ai_box.operator("project.fix_all_missing_textures",
                            text="AI Fix All Missing Textures", icon='CHECKMARK')

            fmt_box = ai_box.row(align=True)
            fmt_box.operator("project.fix_texture_name_variants",
                             text="Fix Name Variants", icon='SORTALPHA')
            fmt_box.operator("project.fix_texture_extensions",
                             text="Fix TEX/DDS Extensions", icon='FILE_REFRESH')

            # ── Filter bar ────────────────────────────────────────────────
            layout.prop(checker, "filter_mode", expand=True)

        # ── Issue list ────────────────────────────────────────────────────
        if checker.issues:
            # Count visible items for row height
            fm = checker.filter_mode
            visible = sum(
                1 for it in checker.issues
                if fm == 'ALL' or it.severity == fm
            )
            rows = max(3, min(visible, 10))

            layout.template_list(
                "PROJ_UL_check_issues", "",
                checker, "issues",
                checker, "active_index",
                rows=rows,
            )

            # ── Detail box for selected issue ─────────────────────────────
            idx = checker.active_index
            if 0 <= idx < len(checker.issues):
                item = checker.issues[idx]
                detail_box = layout.box()
                detail_box.scale_y = 0.85

                sev_icon = _SEV_ICONS.get(item.severity, 'INFO')
                detail_box.label(
                    text=f"[{item.severity}] {item.category}: {item.message}",
                    icon=sev_icon)

                if item.detail:
                    # Wrap long detail text
                    detail = item.detail
                    chunk = 60
                    while detail:
                        detail_box.label(text=detail[:chunk])
                        detail = detail[chunk:]

                if item.file_path and os.path.isfile(item.file_path):
                    op = detail_box.operator(
                        "project.open_issue_file",
                        text=f"Show: {os.path.basename(item.file_path)}",
                        icon='FILEBROWSER')
                    op.file_path = item.file_path

                if item.fix_id:
                    detail_box.separator()
                    row = detail_box.row(align=True)
                    row.operator("project.select_issue_meshes",
                                 text="Select Affected Meshes",
                                 icon='RESTRICT_SELECT_OFF')
                    if item.fix_id == 'MISSING_MATERIAL':
                        row.operator("project.fix_issue",
                                     text="Fix", icon='CHECKMARK')
                    elif item.fix_id == 'MISSING_TEXTURE':
                        row.operator("project.fix_issue",
                                     text="AI Fix", icon='FILE_REFRESH')
                    elif item.fix_id == 'MISSING_VISIBILITY':
                        row.operator("project.fix_visibility",
                                     text="Fix (Load .bin)", icon='FILEBROWSER')


# ============================================================================
# Registration
# ============================================================================

classes = (
    CheckIssue,
    ProjectCheckerSettings,
    PROJ_OT_run_integrity_check,
    PROJ_OT_clear_check_results,
    PROJ_OT_open_issue_file,
    PROJ_OT_select_issue_meshes,
    PROJ_OT_fix_issue,
    PROJ_OT_fix_all_missing_textures,
    PROJ_OT_fix_texture_name_variants,
    PROJ_OT_fix_texture_extensions,
    PROJ_OT_fix_visibility,
    PROJ_UL_check_issues,
    VIEW3D_PT_project_checker,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.project_checker = PointerProperty(type=ProjectCheckerSettings)
    print("[Project Checker] Registered")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, 'project_checker'):
        del bpy.types.Scene.project_checker
    print("[Project Checker] Unregistered")
