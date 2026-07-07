#!/usr/bin/env python3
"""Escape bare currency ``$`` signs that remark-math (singleDollarTextMath) misreads.

viewer's remarkMath runs with singleDollarTextMath enabled (needed for legitimate
single-dollar inline math in some references). A side effect: any two unescaped
``$100`` .. ``$176`` style currency figures in the same paragraph get parsed as a
math span, swallowing everything between them (see
topics/ar-tabletop-tracking-display-stack/README.md:131 for a real example).

This script escapes ``$`` immediately followed by a digit (``$100`` -> ``\\$100``)
in the body of topics/*/README.md and references/*.md, skipping:
  - frontmatter (parsed via _frontmatter.split_frontmatter, left untouched)
  - fenced code blocks (``` or ~~~)
  - inline code spans (`...`)
  - ``$`` that is already escaped (``\\$100``)

Usage:
  python3 scripts/fix-currency.py --dry-run
  python3 scripts/fix-currency.py --apply

Idempotent: running --apply twice in a row must report 0 changes on the
second run (already-escaped ``\\$`` is excluded by the lookbehind).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontmatter import split_frontmatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ("topics", "references")

_FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)")
_CODE_SPAN_RE = re.compile(r"(`[^`\n]*`)")
_CURRENCY_RE = re.compile(r"(?<!\\)\$(?=\d)")


@dataclass(frozen=True)
class FileResult:
    """Outcome of processing a single file."""

    path: Path
    count: int
    new_text: str | None  # None when count == 0 (no change needed)


def _escape_non_code_segment(segment: str) -> tuple[str, int]:
    """Escape bare currency ``$`` in a segment known to contain no code spans."""
    return _CURRENCY_RE.subn(r"\\$", segment)


def _process_line(line: str) -> tuple[str, int]:
    """Escape currency ``$`` in a single line, skipping inline code spans."""
    parts = _CODE_SPAN_RE.split(line)
    total = 0
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Odd indices are the code spans captured by the split group; keep as-is.
            out.append(part)
            continue
        escaped, n = _escape_non_code_segment(part)
        out.append(escaped)
        total += n
    return "".join(out), total


def process_body(body: str) -> tuple[str, int]:
    """Escape bare currency ``$`` in a markdown body, skipping fenced code blocks."""
    lines = body.splitlines(keepends=True)
    in_fence = False
    fence_char = None
    total = 0
    out_lines: list[str] = []

    for line in lines:
        m = _FENCE_RE.match(line)
        if m:
            marker_char = m.group(2)[0]
            if not in_fence:
                in_fence = True
                fence_char = marker_char
            elif marker_char == fence_char:
                in_fence = False
                fence_char = None
            out_lines.append(line)
            continue

        if in_fence:
            out_lines.append(line)
            continue

        new_line, n = _process_line(line)
        out_lines.append(new_line)
        total += n

    return "".join(out_lines), total


def process_file(path: Path) -> FileResult:
    """Compute the fixed content for a single file without writing it."""
    text = path.read_text(encoding="utf-8")
    fm_text, body = split_frontmatter(text)
    new_body, count = process_body(body)
    if count == 0:
        return FileResult(path=path, count=0, new_text=None)

    if fm_text is None:
        new_text = new_body
    else:
        new_text = f"---\n{fm_text}\n---\n{new_body}"
    return FileResult(path=path, count=count, new_text=new_text)


def iter_target_files() -> list[Path]:
    """List candidate markdown files under topics/ and references/."""
    files: list[Path] = []
    for d in TARGET_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.md")))
    return files


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="List files/counts without writing")
    mode.add_argument("--apply", action="store_true", help="Write escaped content back to files")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    results = [r for r in (process_file(f) for f in iter_target_files()) if r.count > 0]

    if not results:
        print("no bare currency $ found")
        return 0

    total_replacements = sum(r.count for r in results)

    if args.dry_run:
        for r in results:
            print(f"{r.path.relative_to(ROOT)}: {r.count} replacement(s)")
        print(f"--- {len(results)} file(s), {total_replacements} replacement(s) (dry-run, no changes written) ---")
        return 0

    for r in results:
        assert r.new_text is not None
        r.path.write_text(r.new_text, encoding="utf-8")
        print(f"{r.path.relative_to(ROOT)}: {r.count} replacement(s)")
    print(f"--- {len(results)} file(s), {total_replacements} replacement(s) applied ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
