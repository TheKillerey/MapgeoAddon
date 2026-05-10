"""
Automated release script for Rey's Mapgeo Blender Addon.

Usage examples:
  python release_addon.py --version 0.4.2 --notes "Bug fixes\nUI improvements"
  python release_addon.py --version 0.4.2 --notes-file release_notes.txt

What it does:
  1) Updates __init__.py version tuple
  2) Updates README version badge
  3) Prepends CHANGELOG release section
  4) Commits changes and creates tag
  5) Pushes main and tag
  6) Builds release zip from the tag
  7) Creates GitHub release and uploads zip
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
INIT_FILE = REPO_ROOT / "__init__.py"
README_FILE = REPO_ROOT / "README.md"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
RELEASES_DIR = REPO_ROOT / "releases"


def run(cmd: list[str]) -> str:
    print("$", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    if proc.stdout:
        print(proc.stdout.strip())
    return proc.stdout.strip()


def parse_version(version: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version.strip())
    if not m:
        raise ValueError("Version must be in format X.Y.Z, e.g. 0.4.2")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def replace_once(path: pathlib.Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Expected exactly 1 match in {path.name} for pattern: {pattern}")
    path.write_text(new_text, encoding="utf-8")


def update_version_files(version: str, version_tuple: tuple[int, int, int], notes_lines: list[str]) -> None:
    replace_once(
        INIT_FILE,
        r'"version":\s*\(\d+,\s*\d+,\s*\d+\)',
        f'"version": ({version_tuple[0]}, {version_tuple[1]}, {version_tuple[2]})',
    )

    replace_once(
        README_FILE,
        r'version-\d+\.\d+\.\d+-blue',
        f'version-{version}-blue',
    )

    changelog_text = CHANGELOG_FILE.read_text(encoding="utf-8")
    marker = "## [Released]\n"
    if marker not in changelog_text:
        raise RuntimeError("CHANGELOG marker '## [Released]' not found")

    today = dt.date.today().isoformat()
    bullet_lines = "\n".join(f"- {line}" for line in notes_lines if line.strip())
    if not bullet_lines:
        bullet_lines = "- Maintenance release"

    new_section = (
        f"\n## [{version}] - {today}\n\n"
        f"### Changes\n"
        f"{bullet_lines}\n"
    )

    updated = changelog_text.replace(marker, marker + new_section, 1)
    CHANGELOG_FILE.write_text(updated, encoding="utf-8")


def ensure_clean_worktree() -> None:
    status = run(["git", "status", "--porcelain"])
    if status.strip():
        raise RuntimeError("Working tree is not clean. Commit/stash changes before running release script.")


def ensure_init_imports_tracked() -> None:
    """Fail fast if any module imported at the top of __init__.py is untracked.

    `git archive` (used to build the release zip) only includes tracked files,
    so an untracked module silently breaks every release with a misleading
    'cannot import name X from partially initialized module' error on install.
    """
    text = INIT_FILE.read_text(encoding="utf-8")
    m = re.search(r"from\s+\.\s+import\s+\(([^)]*)\)", text)
    if not m:
        return
    block = m.group(1)
    modules = [
        line.strip().rstrip(",").strip()
        for line in block.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    modules = [mod for mod in modules if mod and mod.isidentifier()]

    missing = []
    for mod in modules:
        rel = f"{mod}.py"
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(f"{rel} (file does not exist on disk)")
            continue
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            missing.append(f"{rel} (untracked)")

    if missing:
        raise RuntimeError(
            "Refusing to release: the following modules are imported by "
            "__init__.py but are not tracked by git, so they would be "
            "missing from the release zip:\n  - " + "\n  - ".join(missing) +
            "\n\nRun `git add` on these files (or remove the import) and try again."
        )


def build_release_zip(tag: str) -> pathlib.Path:
    """Build a Blender-installable ZIP.

    Blender requires the ZIP to contain a single top-level folder whose name
    matches the addon (i.e. MapgeoAddon/__init__.py must be the entry point).
    ``git archive`` alone produces a flat ZIP, so we use its ``--prefix``
    option to wrap everything inside ``MapgeoAddon/``.
    """
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASES_DIR / f"MapgeoAddon-v{tag.lstrip('v')}.zip"
    run([
        "git", "archive",
        "--format=zip",
        "--prefix=MapgeoAddon/",
        "--output", str(zip_path),
        tag,
    ])
    return zip_path


def create_github_release(tag: str, notes_text: str, zip_path: pathlib.Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(f"Release {tag}\n\n{notes_text}\n")
        notes_path = pathlib.Path(tmp.name)

    try:
        run([
            "gh", "release", "create", tag,
            str(zip_path),
            "--title", tag,
            "--notes-file", str(notes_path)
        ])
    finally:
        try:
            notes_path.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Automate addon release workflow")
    parser.add_argument("--version", required=True, help="Release version in X.Y.Z format")
    parser.add_argument("--notes", default="", help="Release notes text; use \\n for line breaks")
    parser.add_argument("--notes-file", default="", help="Optional path to release notes file")
    args = parser.parse_args()

    version = args.version.strip()
    version_tuple = parse_version(version)
    tag = f"v{version}"

    if args.notes_file:
        notes_text = pathlib.Path(args.notes_file).read_text(encoding="utf-8")
    else:
        notes_text = args.notes.replace("\\n", "\n").strip()

    notes_lines = [line.strip() for line in notes_text.splitlines() if line.strip()]
    if not notes_lines:
        notes_lines = ["Maintenance release"]

    ensure_clean_worktree()
    ensure_init_imports_tracked()
    update_version_files(version, version_tuple, notes_lines)

    run(["git", "add", "__init__.py", "README.md", "CHANGELOG.md"])
    run(["git", "commit", "-m", f"Release {tag}"])
    run(["git", "tag", "-a", tag, "-m", f"Version {version}"])
    run(["git", "push", "origin", "main"])
    run(["git", "push", "origin", tag])

    zip_path = build_release_zip(tag)
    create_github_release(tag, "\n".join(notes_lines), zip_path)

    print("\nRelease completed successfully")
    print(f"Tag: {tag}")
    print(f"Zip: {zip_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Release failed: {exc}")
        raise SystemExit(1)
