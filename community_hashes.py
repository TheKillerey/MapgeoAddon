"""
CommunityDragon Hash Database Integration

Downloads, caches, and provides lookup for community-maintained hash dictionaries
from https://github.com/CommunityDragon/Data/tree/master/hashes/lol

These hash files map FNV-1a 32-bit hashes to their original names, enabling
the PropertyBin editor (and other tools) to display readable names instead of
raw hex hashes.

Supported hash files:
- hashes.binentries.txt  - Entry path hashes (e.g. Characters/Annie/...)
- hashes.binfields.txt   - Field/property name hashes (e.g. mName, mPath, ...)
- hashes.binhashes.txt   - General string hashes used in bin values
- hashes.bintypes.txt    - Class/type hashes (e.g. StaticMaterialDef, ...)
- hashes.game.txt        - Game string hashes (split into .0 and .1)
"""

import os
import threading
import time
from pathlib import Path

# Base URL for raw hash files
_RAW_BASE = "https://raw.githubusercontent.com/CommunityDragon/Data/master/hashes/lol/"

# Files relevant for PropertyBin (.bin) editing
BIN_HASH_FILES = {
    "binentries": "hashes.binentries.txt",
    "binfields":  "hashes.binfields.txt",
    "binhashes":  "hashes.binhashes.txt",
    "bintypes":   "hashes.bintypes.txt",
}

# Additional game string hashes (split into two files due to size)
GAME_HASH_FILES = {
    "game0": "hashes.game.txt.0",
    "game1": "hashes.game.txt.1",
}

# All downloadable hash files
ALL_HASH_FILES = {**BIN_HASH_FILES, **GAME_HASH_FILES}

# ============================================================================
# Global hash dictionaries
# ============================================================================

# Separate dictionaries for different hash categories
bin_entries: dict[int, str] = {}   # path hashes → entry paths
bin_fields: dict[int, str] = {}    # field name hashes → field names
bin_hashes: dict[int, str] = {}    # general string hashes → strings
bin_types: dict[int, str] = {}     # type/class hashes → type names
game_hashes: dict[int, str] = {}   # game string hashes

# Unified lookup (all merged)
_all_hashes: dict[int, str] = {}

# Status tracking
_loaded_files: set[str] = set()
_download_status: str = ""
_download_progress: float = 0.0
_is_downloading: bool = False


def get_cache_dir() -> Path:
    """Get the local cache directory for downloaded hash files."""
    addon_dir = Path(__file__).parent
    cache_dir = addon_dir / "hashes"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def _parse_hash_file(filepath: str | Path) -> dict[int, str]:
    """
    Parse a CommunityDragon hash file.
    
    Format: one entry per line, each line is:
        hex_hash name
    
    Where hex_hash is an 8-character lowercase hex string (no 0x prefix)
    and name is the resolved string, separated by a space.
    
    Also handles:
    - Tab-separated entries
    - Optional 0x prefix on the hash
    - Lines with only a hash and no name (skipped)
    """
    result = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Split on first whitespace (space or tab)
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                hex_part = parts[0]
                name_part = parts[1]
                # Strip optional 0x prefix
                if hex_part.startswith('0x') or hex_part.startswith('0X'):
                    hex_part = hex_part[2:]
                try:
                    h = int(hex_part, 16)
                    result[h] = name_part
                except ValueError:
                    continue
    except (IOError, OSError) as e:
        print(f"[CommunityHashes] Failed to read {filepath}: {e}")
    return result


def _download_file(url: str, dest: Path) -> bool:
    """Download a file from URL to local path. Returns True on success."""
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'BlenderMapgeoAddon/1.0'}
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(data)
        
        return True
    except Exception as e:
        print(f"[CommunityHashes] Download failed for {url}: {e}")
        return False


def load_cached_hashes(categories: str = "bin") -> int:
    """
    Load hash files from the local cache directory.
    
    Args:
        categories: Which hash files to load:
            "bin"  - Only bin-related files (binentries, binfields, binhashes, bintypes)
            "game" - Only game string hashes
            "all"  - Everything
    
    Returns:
        Total number of hash entries loaded.
    """
    global _all_hashes
    cache_dir = get_cache_dir()
    total = 0

    if categories in ("bin", "all"):
        for key, filename in BIN_HASH_FILES.items():
            filepath = cache_dir / filename
            if filepath.exists() and key not in _loaded_files:
                parsed = _parse_hash_file(filepath)
                if key == "binentries":
                    bin_entries.update(parsed)
                elif key == "binfields":
                    bin_fields.update(parsed)
                elif key == "binhashes":
                    bin_hashes.update(parsed)
                elif key == "bintypes":
                    bin_types.update(parsed)
                
                _all_hashes.update(parsed)
                _loaded_files.add(key)
                total += len(parsed)
                print(f"[CommunityHashes] Loaded {len(parsed)} entries from {filename}")

    if categories in ("game", "all"):
        for key, filename in GAME_HASH_FILES.items():
            filepath = cache_dir / filename
            if filepath.exists() and key not in _loaded_files:
                parsed = _parse_hash_file(filepath)
                game_hashes.update(parsed)
                _all_hashes.update(parsed)
                _loaded_files.add(key)
                total += len(parsed)
                print(f"[CommunityHashes] Loaded {len(parsed)} entries from {filename}")

    return total


def download_hashes(categories: str = "bin", callback=None) -> int:
    """
    Download hash files from CommunityDragon GitHub.
    
    Args:
        categories: Which files to download ("bin", "game", "all")
        callback: Optional callable(status_str, progress_float) for progress updates
    
    Returns:
        Number of files successfully downloaded.
    """
    global _download_status, _download_progress, _is_downloading
    
    _is_downloading = True
    cache_dir = get_cache_dir()
    
    files_to_download = {}
    if categories in ("bin", "all"):
        files_to_download.update(BIN_HASH_FILES)
    if categories in ("game", "all"):
        files_to_download.update(GAME_HASH_FILES)
    
    downloaded = 0
    total_files = len(files_to_download)
    
    for i, (key, filename) in enumerate(files_to_download.items()):
        progress = (i / total_files) if total_files > 0 else 0
        _download_progress = progress
        _download_status = f"Downloading {filename}..."
        
        if callback:
            callback(_download_status, progress)
        
        url = _RAW_BASE + filename
        dest = cache_dir / filename
        
        if _download_file(url, dest):
            downloaded += 1
            print(f"[CommunityHashes] Downloaded {filename}")
        else:
            print(f"[CommunityHashes] FAILED to download {filename}")
    
    _download_progress = 1.0
    _download_status = f"Done - {downloaded}/{total_files} files"
    _is_downloading = False
    
    if callback:
        callback(_download_status, 1.0)
    
    # Reload the newly downloaded files
    _loaded_files.clear()  # Force reload
    load_cached_hashes(categories)
    
    return downloaded


def download_hashes_async(categories: str = "bin", on_complete=None):
    """
    Download hash files in a background thread.
    
    Args:
        categories: Which files to download ("bin", "game", "all")
        on_complete: Optional callable(num_downloaded) called when done
    """
    def _worker():
        count = download_hashes(categories)
        if on_complete:
            on_complete(count)
    
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def resolve(hash_val: int | str) -> str:
    """
    Look up a hash in the unified dictionary.
    
    Args:
        hash_val: Either an int hash or a hex string like '0x12345678'
    
    Returns:
        The resolved name, or empty string if not found.
    """
    if isinstance(hash_val, str):
        try:
            hash_val = int(hash_val, 16)
        except (ValueError, TypeError):
            return ""
    
    return _all_hashes.get(hash_val, "")


def resolve_entry(hash_val: int | str) -> str:
    """Look up a hash specifically in binentries."""
    if isinstance(hash_val, str):
        try:
            hash_val = int(hash_val, 16)
        except (ValueError, TypeError):
            return ""
    return bin_entries.get(hash_val, "")


def resolve_field(hash_val: int | str) -> str:
    """Look up a hash specifically in binfields."""
    if isinstance(hash_val, str):
        try:
            hash_val = int(hash_val, 16)
        except (ValueError, TypeError):
            return ""
    return bin_fields.get(hash_val, "")


def resolve_type(hash_val: int | str) -> str:
    """Look up a hash specifically in bintypes."""
    if isinstance(hash_val, str):
        try:
            hash_val = int(hash_val, 16)
        except (ValueError, TypeError):
            return ""
    return bin_types.get(hash_val, "")


def resolve_binhash(hash_val: int | str) -> str:
    """Look up a hash specifically in binhashes."""
    if isinstance(hash_val, str):
        try:
            hash_val = int(hash_val, 16)
        except (ValueError, TypeError):
            return ""
    return bin_hashes.get(hash_val, "")


def get_stats() -> dict:
    """Get statistics about loaded hashes."""
    return {
        "binentries": len(bin_entries),
        "binfields": len(bin_fields),
        "binhashes": len(bin_hashes),
        "bintypes": len(bin_types),
        "game": len(game_hashes),
        "total": len(_all_hashes),
        "loaded_files": list(_loaded_files),
        "is_downloading": _is_downloading,
        "download_status": _download_status,
        "download_progress": _download_progress,
    }


def has_cached_hashes() -> bool:
    """Check if any hash files are cached locally."""
    cache_dir = get_cache_dir()
    for filename in BIN_HASH_FILES.values():
        if (cache_dir / filename).exists():
            return True
    return False


def get_cache_age() -> float | None:
    """
    Get the age of the oldest cached hash file in hours.
    Returns None if no files are cached.
    """
    cache_dir = get_cache_dir()
    oldest = None
    for filename in BIN_HASH_FILES.values():
        fp = cache_dir / filename
        if fp.exists():
            age = (time.time() - fp.stat().st_mtime) / 3600.0
            if oldest is None or age > oldest:
                oldest = age
    return oldest


# ============================================================================
# Auto-load cached hashes on import
# ============================================================================

def _auto_load():
    """Attempt to load cached hashes on module import."""
    if has_cached_hashes():
        count = load_cached_hashes("all")
        if count > 0:
            print(f"[CommunityHashes] Auto-loaded {count} hashes from cache")


_auto_load()
