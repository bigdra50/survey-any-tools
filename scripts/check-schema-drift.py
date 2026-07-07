#!/usr/bin/env python3
"""Detect drift between Python `_schema.py` and viewer/src/content.config.ts (zod).

Source of Truth: viewer/src/content.config.ts. Python dataclasses must mirror
the zod field set 1:1. This script reads the .ts file as text, slices each
`defineCollection({ ... })` block, walks the `schema: z.object({ ... })` body,
and extracts the top-level field names. It then compares against the
dataclass field set in scripts/_schema.py.

Exit codes:
  0 — no drift
  1 — drift detected (printed as a unified-diff-like summary)
  2 — input error (file missing / parse failed)

The regex parser is intentionally simple. It tolerates braces inside
`z.object({...})` declarations by counting depth, which is enough for the
shapes used in this repo. If the schema grows complex enough that this
breaks, swap to a proper TS parser.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _schema import (  # noqa: E402  — sys.path mutation above
    course_field_names,
    lesson_field_names,
    reference_field_names,
    topic_field_names,
)
from _root import content_root  # noqa: E402

ROOT = content_root()
ZOD_FILE = ROOT / "viewer" / "src" / "content.config.ts"

_COLLECTION_RE = re.compile(
    r"const\s+(?P<name>\w+)\s*=\s*defineCollection\s*\(\s*\{",
)
_SCHEMA_RE = re.compile(r"schema\s*:\s*z\.object\s*\(\s*\{")
_FIELD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _slice_balanced(text: str, start: int, opener: str = "{", closer: str = "}") -> tuple[int, str]:
    """Return (end_index_after_closer, content_inside_outer_braces).

    `start` must point at the opener char.
    """
    if text[start] != opener:
        raise ValueError(f"_slice_balanced: expected {opener!r} at index {start}")
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i + 1, text[start + 1 : i]
        i += 1
    raise ValueError("_slice_balanced: unbalanced braces")


def extract_zod_fields(source: str) -> dict[str, frozenset[str]]:
    """Return {collection_name: {field, ...}} from the zod source."""
    out: dict[str, frozenset[str]] = {}
    for match in _COLLECTION_RE.finditer(source):
        name = match.group("name")
        # Find the `schema: z.object({ ... })` inside this collection block.
        # First, extract the collection body so we don't accidentally pick a
        # later collection's schema.
        coll_body_start = source.find("{", match.end() - 1)
        if coll_body_start < 0:
            continue
        coll_end, coll_body = _slice_balanced(source, coll_body_start)
        schema_match = _SCHEMA_RE.search(coll_body)
        if not schema_match:
            continue
        # The opener `{` of z.object — relative to coll_body.
        obj_brace_idx = coll_body.find("{", schema_match.end() - 1)
        if obj_brace_idx < 0:
            continue
        _, obj_body = _slice_balanced(coll_body, obj_brace_idx)
        out[name] = _extract_top_level_fields(obj_body)
    return out


def _extract_top_level_fields(obj_body: str) -> frozenset[str]:
    """Walk an object body, returning identifiers at depth 0 followed by `:`.

    Skips identifiers that appear inside nested braces / parens (e.g. enum
    arrays, default-value objects). Skips identifiers inside string literals.
    """
    fields: set[str] = set()
    depth_brace = 0
    depth_paren = 0
    depth_bracket = 0
    in_string: str | None = None
    line_buf = ""

    i = 0
    while i < len(obj_body):
        ch = obj_body[i]

        # Track string literals.
        if in_string is not None:
            if ch == "\\" and i + 1 < len(obj_body):
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ('"', "'", "`"):
            in_string = ch
            i += 1
            continue

        # Skip line comments — irrelevant for our content but cheap to handle.
        if ch == "/" and i + 1 < len(obj_body) and obj_body[i + 1] == "/":
            nl = obj_body.find("\n", i)
            i = len(obj_body) if nl < 0 else nl + 1
            line_buf = ""
            continue
        if ch == "/" and i + 1 < len(obj_body) and obj_body[i + 1] == "*":
            end = obj_body.find("*/", i + 2)
            i = len(obj_body) if end < 0 else end + 2
            continue

        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
        elif ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1

        if ch == "\n":
            line_buf = ""
            i += 1
            continue

        # Only consider identifiers when we're at top level of the schema body.
        if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
            line_buf += ch
            # Match `<ident>:` greedily at top level. Reset on `,`.
            m = _FIELD_RE.match(line_buf)
            if m and ch == ":":
                fields.add(m.group(1))
                line_buf = ""
            elif ch == ",":
                line_buf = ""
        i += 1

    return frozenset(fields)


_PYTHON_FIELDS: dict[str, frozenset[str]] = {
    "topics": topic_field_names(),
    "references": reference_field_names(),
    "courses": course_field_names(),
    "lessons": lesson_field_names(),
}


def main() -> int:
    if not ZOD_FILE.is_file():
        print(f"error: {ZOD_FILE} not found", file=sys.stderr)
        return 2
    source = ZOD_FILE.read_text(encoding="utf-8")

    try:
        zod_fields = extract_zod_fields(source)
    except ValueError as exc:
        print(f"error: failed to parse zod file: {exc}", file=sys.stderr)
        return 2

    drift_found = False
    for name in ("topics", "references", "courses", "lessons"):
        zod_set = zod_fields.get(name)
        py_set = _PYTHON_FIELDS[name]
        if zod_set is None:
            print(f"[{name}] missing in zod source")
            drift_found = True
            continue

        only_zod = zod_set - py_set
        only_py = py_set - zod_set
        if not only_zod and not only_py:
            print(f"[{name}] OK ({len(zod_set)} fields)")
            continue

        drift_found = True
        print(f"[{name}] DRIFT")
        for f in sorted(only_zod):
            print(f"  + zod-only:    {f}")
        for f in sorted(only_py):
            print(f"  - python-only: {f}")

    if drift_found:
        print()
        print(
            "drift: update scripts/_schema.py dataclasses to match "
            "viewer/src/content.config.ts (Source of Truth).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
