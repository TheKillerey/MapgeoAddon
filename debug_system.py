"""
Centralized Debug & Diagnostic System for Mapgeo Addon
Tracks every import step — textures, materials, meshes, lights —
and reports what loaded, what's missing, and what failed.
Results are shown in a dedicated UI panel.
"""

import time
import os
from enum import Enum
from typing import Optional


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class DebugEntry:
    __slots__ = ('severity', 'category', 'message', 'detail', 'timestamp')

    def __init__(self, severity: Severity, category: str, message: str, detail: str = ""):
        self.severity = severity
        self.category = category
        self.message = message
        self.detail = detail
        self.timestamp = time.time()


class ImportStats:
    """Counters for a single import session."""
    __slots__ = (
        'meshes_imported', 'meshes_failed',
        'materials_loaded', 'materials_missing',
        'textures_loaded', 'textures_missing', 'textures_failed',
        'lights_created', 'lights_failed',
        'duration',
    )

    def __init__(self):
        self.meshes_imported = 0
        self.meshes_failed = 0
        self.materials_loaded = 0
        self.materials_missing = 0
        self.textures_loaded = 0
        self.textures_missing = 0
        self.textures_failed = 0
        self.lights_created = 0
        self.lights_failed = 0
        self.duration = 0.0


class DebugLog:
    """
    Singleton-style log that collects entries during an import session.
    Access via ``get_debug_log()``.
    """

    def __init__(self):
        self.entries: list[DebugEntry] = []
        self.stats = ImportStats()
        self._start_time: Optional[float] = None
        self._enabled = True

    # ── session control ──────────────────────────────────────────────

    def begin_session(self):
        """Call at the start of an import to reset everything."""
        self.entries.clear()
        self.stats = ImportStats()
        self._start_time = time.time()

    def end_session(self):
        """Call when an import finishes."""
        if self._start_time is not None:
            self.stats.duration = time.time() - self._start_time
            self._start_time = None

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    # ── logging helpers ──────────────────────────────────────────────

    def _add(self, severity: Severity, category: str, message: str, detail: str = ""):
        entry = DebugEntry(severity, category, message, detail)
        self.entries.append(entry)
        # Also print to console so Blender's System Console still works
        prefix = {Severity.INFO: "  ", Severity.WARNING: "  WARNING: ", Severity.ERROR: "  ERROR: "}[severity]
        tag = f"[{category}]"
        print(f"{prefix}{tag} {message}" + (f" | {detail}" if detail else ""))

    def info(self, category: str, message: str, detail: str = ""):
        if self._enabled:
            self._add(Severity.INFO, category, message, detail)

    def warning(self, category: str, message: str, detail: str = ""):
        self._add(Severity.WARNING, category, message, detail)

    def error(self, category: str, message: str, detail: str = ""):
        self._add(Severity.ERROR, category, message, detail)

    # ── stat helpers (always tracked) ────────────────────────────────

    def mesh_imported(self):
        self.stats.meshes_imported += 1

    def mesh_failed(self, name: str = "", reason: str = ""):
        self.stats.meshes_failed += 1
        self._add(Severity.ERROR, "Mesh", f"Failed to import mesh: {name}", reason)

    def material_loaded(self, name: str = ""):
        self.stats.materials_loaded += 1

    def material_missing(self, name: str = "", detail: str = ""):
        self.stats.materials_missing += 1
        self._add(Severity.WARNING, "Material", f"Material not found: {name}", detail)

    def texture_loaded(self, path: str = ""):
        self.stats.textures_loaded += 1
        if self._enabled:
            self._add(Severity.INFO, "Texture", f"Loaded: {os.path.basename(path)}", path)

    def texture_missing(self, path: str = "", tried: str = ""):
        self.stats.textures_missing += 1
        self._add(Severity.WARNING, "Texture", f"Not found: {os.path.basename(path) if path else '(empty)'}", tried)

    def texture_failed(self, path: str = "", reason: str = ""):
        self.stats.textures_failed += 1
        self._add(Severity.ERROR, "Texture", f"Failed to load: {os.path.basename(path)}", reason)

    def light_created(self):
        self.stats.lights_created += 1

    def light_failed(self, reason: str = ""):
        self.stats.lights_failed += 1
        self._add(Severity.ERROR, "Light", "Failed to create point light", reason)

    # ── query helpers ────────────────────────────────────────────────

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.entries if e.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.entries if e.severity == Severity.WARNING)

    def get_filtered(self, severity: Optional[Severity] = None, category: str = ""):
        """Return entries matching filters."""
        for e in self.entries:
            if severity and e.severity != severity:
                continue
            if category and e.category != category:
                continue
            yield e

    def summary_lines(self) -> list[str]:
        """Return a short human-readable summary."""
        s = self.stats
        lines = []
        lines.append(f"Import completed in {s.duration:.1f}s")
        lines.append(f"Meshes: {s.meshes_imported} loaded, {s.meshes_failed} failed")
        lines.append(f"Materials: {s.materials_loaded} loaded, {s.materials_missing} missing")
        lines.append(f"Textures: {s.textures_loaded} loaded, {s.textures_missing} missing, {s.textures_failed} failed")
        if s.lights_created or s.lights_failed:
            lines.append(f"Lights: {s.lights_created} created, {s.lights_failed} failed")
        lines.append(f"Issues: {self.error_count} errors, {self.warning_count} warnings")
        return lines


# ── module-level singleton ───────────────────────────────────────────

_debug_log: Optional[DebugLog] = None


def get_debug_log() -> DebugLog:
    """Return the global DebugLog instance (created on first call)."""
    global _debug_log
    if _debug_log is None:
        _debug_log = DebugLog()
    return _debug_log
