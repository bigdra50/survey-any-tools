"""Minimal frontmatter parser shared across scripts/.

Targets the YAML subset actually used in this repo:
  - Quoted/unquoted scalar values (`title: "..."`, `status: done`)
  - Inline lists (`tags: [a, b]`)
  - Block lists (`sources:\n  - a\n  - b`)
  - Top-level keys only (no nested mappings)

Returns dict[str, str | list[str]]. Anything more elaborate falls back to a
string. The parser is permissive on purpose; loud failures live at use-site.
"""

from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.S)
_QUOTE = re.compile(r'^"(.*)"$|^\'(.*)\'$')


def _strip_quotes(value: str) -> str:
    m = _QUOTE.match(value)
    if not m:
        return value
    return m.group(1) if m.group(1) is not None else m.group(2)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text_or_None, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse the YAML subset used in this repo into a flat dict."""
    fm_text, _ = split_frontmatter(text)
    if fm_text is None:
        return {}

    out: dict[str, str | list[str]] = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blanks / comment lines.
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level keys start at column 0.
        if line.startswith(" ") or line.startswith("\t"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()

        # Inline list: `key: [a, b]`
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1]
            items = [_strip_quotes(s.strip()) for s in inner.split(",") if s.strip()]
            out[key] = items
            i += 1
            continue

        # Block list: subsequent lines starting with `  - `.
        if raw == "" and i + 1 < len(lines) and re.match(r"^\s+-\s+", lines[i + 1]):
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                m = re.match(r"^\s+-\s+(.*)", lines[j])
                if m:
                    items.append(_strip_quotes(m.group(1).strip()))
                j += 1
            out[key] = items
            i = j
            continue

        # Plain scalar.
        out[key] = _strip_quotes(raw)
        i += 1

    return out


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
