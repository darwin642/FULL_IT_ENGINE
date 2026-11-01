#!/usr/bin/env python3
"""Cartman global version footer migration.

Run from the Cartman project root. Replaces branded page-footer markup in
active static HTML/JS files with one right-aligned version label and adds a
global footer style. Backups are created before any source file is changed.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import sys

VERSION_TEXT = "Cartman v0.2.3d pre-alpha-0111260212"
MARKER = "CARTMAN_GLOBAL_VERSION_FOOTER_V1"
BRAND = "Cartman Infrastructure Management"

ROOT = Path.cwd()
STATIC = ROOT / "app" / "static"
STYLE = STATIC / "style.css"

if not STATIC.is_dir():
    raise SystemExit(
        "ABORT: run this script from the Cartman project root "
        "(the folder containing app/static)."
    )
if not STYLE.is_file():
    raise SystemExit(f"ABORT: shared stylesheet not found: {STYLE}")

# Only page-level footer elements carrying the old Cartman footer branding are
# replaced. Informational notes inside page content are intentionally untouched.
footer_re = re.compile(r"<footer\b[^>]*>.*?</footer\s*>", re.IGNORECASE | re.DOTALL)
new_footer = (
    '<footer class="app-footer cartman-version-footer">'
    f'<span>{VERSION_TEXT}</span>'
    '</footer>'
)

excluded_dirs = {".backups", "node_modules", ".git", "__pycache__"}
excluded_suffixes = (".bak", ".backup", ".orig", ".pyc")

planned: dict[Path, str] = {}
counts: dict[str, int] = {}

for path in sorted(STATIC.rglob("*")):
    if not path.is_file() or path.suffix.lower() not in {".html", ".js"}:
        continue
    if any(part in excluded_dirs for part in path.parts):
        continue
    if path.name.lower().endswith(excluded_suffixes):
        continue

    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue

    if MARKER in source:
        # Idempotency: do not reprocess a file already migrated.
        continue

    replaced = 0

    def replace_footer(match: re.Match[str]) -> str:
        nonlocal_dummy = None
        nonlocal_count[0] += 1
        return new_footer

    nonlocal_count = [0]
    updated = footer_re.sub(
        lambda match: (
            new_footer
            if BRAND.lower() in match.group(0).lower()
            else match.group(0)
        ),
        source,
    )
    replaced = sum(
        1
        for match in footer_re.finditer(source)
        if BRAND.lower() in match.group(0).lower()
    )

    if replaced:
        planned[path] = updated
        counts[str(path.relative_to(ROOT))] = replaced

style_source = STYLE.read_text(encoding="utf-8")
if MARKER not in style_source:
    style_updated = style_source.rstrip() + "\n\n" + f'''/* {MARKER} */
footer.cartman-version-footer {{
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
    width: 100% !important;
    box-sizing: border-box !important;
    gap: 0 !important;
    text-align: right !important;
}}

footer.cartman-version-footer > span {{
    display: block !important;
    margin: 0 0 0 auto !important;
    text-align: right !important;
    white-space: nowrap;
}}
/* END {MARKER} */
'''
    planned[STYLE] = style_updated
else:
    style_updated = style_source

if not counts:
    # CSS could already be installed; report if no footers remain to migrate.
    print("No old branded footer markup found. It may already be migrated.")
    if MARKER in style_source:
        print("Global footer CSS is already installed.")
    raise SystemExit(0)

# Preflight: ensure every target footer was actually replaced and all new
# markup carries the expected version string. No file is written before this.
for path, updated in planned.items():
    if path == STYLE:
        continue
    if BRAND.lower() in updated.lower():
        # Brand may legitimately exist in page body/help text; verify only that
        # no old page-footer carrying the brand remains.
        remaining = [
            m.group(0) for m in footer_re.finditer(updated)
            if BRAND.lower() in m.group(0).lower()
        ]
        if remaining:
            raise SystemExit(
                f"ABORT: old branded footer remains in {path}: {len(remaining)}"
            )
    if VERSION_TEXT not in updated:
        raise SystemExit(f"ABORT: version label missing from updated file: {path}")

if MARKER not in planned.get(STYLE, style_source):
    raise SystemExit("ABORT: global footer CSS marker missing")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_root = ROOT / ".backups" / f"global-footer-v1-{stamp}"
backup_root.mkdir(parents=True, exist_ok=False)

changed_paths = list(planned)
for path in changed_paths:
    rel = path.relative_to(ROOT)
    backup = backup_root / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)

written: list[Path] = []
try:
    for path, content in planned.items():
        temp = path.with_name(path.name + ".footer-tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, path)
        written.append(path)
except Exception:
    for path in reversed(written):
        backup = backup_root / path.relative_to(ROOT)
        shutil.copy2(backup, path)
    raise

print("\n==============================================")
print("CARTMAN GLOBAL VERSION FOOTER: APPLIED")
print("==============================================")
print("Version:", VERSION_TEXT)
print("Backups:", backup_root)
print("Updated page/script files:", len(counts))
for filename, count in counts.items():
    print(f"  {filename}: {count} footer(s)")
print("Updated stylesheet:", STYLE.relative_to(ROOT))
print("\nOld branded page footers have been replaced.")
print("Footer text is right-aligned; page content and informational notes remain unchanged.")
