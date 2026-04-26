"""Minimal frontmatter parser shared across scripts/.

Targets the YAML subset actually used in this repo:
  - Quoted/unquoted scalar values (`title: "..."`, `status: done`)
  - Inline lists (`tags: [a, b]`)
  - Block lists (`sources:\n  - a\n  - b`)
  - Top-level keys only (no nested mappings)

Returns dict[str, str | list[str]]. Anything more elaborate falls back to a
string. The parser is permissive on purpose; loud failures live at use-site.

In addition to parsing, this module exposes a dumper symmetric with the
parser and a high-level ``update_fields`` helper used by archive.py to
mutate frontmatter while preserving the original layout (key order and
inline-vs-block list style).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.S)
_QUOTE = re.compile(r'^"(.*)"$|^\'(.*)\'$')

ListStyle = Literal["inline", "block"]


@dataclass(frozen=True)
class FieldStyle:
    """How a single top-level frontmatter field was rendered in the source.

    Captured during parsing so the dumper can round-trip the document
    without flipping list styles or quoting unrelated scalars.
    """

    kind: Literal["scalar", "list"]
    list_style: ListStyle | None = None  # only set when kind == "list"
    indent: str = "  "  # leading whitespace before "- " in block lists
    quoted: bool = False  # whether the scalar was originally quoted


@dataclass(frozen=True)
class ParsedFrontmatter:
    """Parsed frontmatter plus the layout metadata needed to round-trip."""

    fields: dict[str, str | list[str]] = field(default_factory=dict)
    styles: dict[str, FieldStyle] = field(default_factory=dict)


def _strip_quotes(value: str) -> str:
    m = _QUOTE.match(value)
    if not m:
        return value
    return m.group(1) if m.group(1) is not None else m.group(2)


def _is_quoted(value: str) -> bool:
    return _QUOTE.match(value) is not None


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text_or_None, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse the YAML subset used in this repo into a flat dict."""
    return _parse_with_styles(text).fields


def _parse_with_styles(text: str) -> ParsedFrontmatter:
    """Parse frontmatter and capture per-field rendering metadata."""
    fm_text, _ = split_frontmatter(text)
    if fm_text is None:
        return ParsedFrontmatter()

    fields: dict[str, str | list[str]] = {}
    styles: dict[str, FieldStyle] = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()

        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1]
            items = [_strip_quotes(s.strip()) for s in inner.split(",") if s.strip()]
            fields[key] = items
            styles[key] = FieldStyle(kind="list", list_style="inline")
            i += 1
            continue

        if raw == "" and i + 1 < len(lines) and re.match(r"^\s+-\s+", lines[i + 1]):
            block_items: list[str] = []
            j = i + 1
            indent = "  "
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                m = re.match(r"^(\s+)-\s+(.*)", lines[j])
                if m:
                    indent = m.group(1)
                    block_items.append(_strip_quotes(m.group(2).strip()))
                j += 1
            fields[key] = block_items
            styles[key] = FieldStyle(kind="list", list_style="block", indent=indent)
            i = j
            continue

        fields[key] = _strip_quotes(raw)
        styles[key] = FieldStyle(kind="scalar", quoted=_is_quoted(raw))
        i += 1

    return ParsedFrontmatter(fields=fields, styles=styles)


def load_frontmatter(path: Path | str) -> dict[str, str | list[str]]:
    """Read a file and return its parsed frontmatter."""
    return parse_frontmatter(Path(path).read_text(encoding="utf-8"))


def get_list(fm: dict[str, str | list[str]], key: str) -> list[str]:
    """Return fm[key] coerced to list[str], or [] if missing."""
    v = fm.get(key)
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [v]
    return []


# --------------------------------------------------------------------------- #
# Dumper
# --------------------------------------------------------------------------- #


def _render_scalar(value: str, *, quoted: bool) -> str:
    if quoted:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_inline_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _render_block_list(items: list[str], indent: str) -> list[str]:
    return [f"{indent}- {item}" for item in items]


def dump_frontmatter(
    fm: dict[str, str | list[str]],
    styles: dict[str, FieldStyle] | None = None,
) -> str:
    """Render a frontmatter dict back to its YAML-subset string form.

    Symmetric with :func:`parse_frontmatter` for the supported subset. Field
    order matches dict iteration order (Python 3.7+ preserves insertion).

    ``styles`` is optional layout metadata captured by the parser. When a
    key is absent from ``styles``, sensible defaults are used: lists fall
    back to block style, scalars are emitted unquoted.
    """
    styles = styles or {}
    out: list[str] = []
    for key, value in fm.items():
        style = styles.get(key)
        if isinstance(value, list):
            list_style: ListStyle = (
                style.list_style if style and style.list_style else "block"
            )
            indent = style.indent if style else "  "
            if list_style == "inline":
                out.append(f"{key}: {_render_inline_list(value)}")
                continue
            if not value:
                # Empty block lists collapse to inline `key: []` to stay valid.
                out.append(f"{key}: []")
                continue
            out.append(f"{key}:")
            out.extend(_render_block_list(value, indent))
            continue

        quoted = style.quoted if style else False
        out.append(f"{key}: {_render_scalar(value, quoted=quoted)}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Whole-file update helper
# --------------------------------------------------------------------------- #


def update_fields(
    text: str,
    updates: dict[str, str] | None = None,
    list_appends: dict[str, list[str]] | None = None,
) -> str:
    """Return ``text`` with frontmatter updates applied, body untouched.

    Parameters
    ----------
    text:
        Full file content (frontmatter + body). If no frontmatter is present,
        an empty one is inserted before applying updates.
    updates:
        Scalar field overrides. Existing keys are replaced; missing keys are
        appended at the end of the frontmatter.
    list_appends:
        For each key, append the given items to its list (deduplicated, order
        preserved). If the key is missing it is created. Existing inline /
        block style is preserved; new keys default to block style.

    The returned string preserves the original key order; new keys land at
    the end of the frontmatter in the order they appear in ``updates`` /
    ``list_appends``. Body content (everything after the closing ``---``)
    is returned verbatim.
    """
    updates = updates or {}
    list_appends = list_appends or {}

    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        # Insert empty frontmatter so subsequent edits have a target.
        text = "---\n\n---\n" + text
        fm_text, body = split_frontmatter(text)
        if fm_text is None:
            raise RuntimeError("failed to insert frontmatter markers")

    parsed = _parse_with_styles(text)
    fields = dict(parsed.fields)
    styles = dict(parsed.styles)

    for key, value in updates.items():
        fields[key] = value
        if key not in styles:
            styles[key] = FieldStyle(kind="scalar", quoted=False)

    for key, items_to_add in list_appends.items():
        existing = fields.get(key)
        current: list[str] = list(existing) if isinstance(existing, list) else []
        for item in items_to_add:
            if item not in current:
                current.append(item)
        fields[key] = current
        if key not in styles:
            styles[key] = FieldStyle(kind="list", list_style="block")

    new_fm = dump_frontmatter(fields, styles)
    return f"---\n{new_fm}\n---\n{body}"
