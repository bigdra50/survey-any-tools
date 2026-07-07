#!/usr/bin/env python3
"""Validate frontmatter tags against vocab/tags.yml controlled vocabulary.

Reports three classes of issues:
  - rename: tag matches a `use_for` entry; should be replaced by the preferred name
  - unknown: tag isn't preferred and doesn't match any `use_for`
  - ok: tag is a registered preferred form

Exit code 0 always (this is advisory). Use --strict to exit 1 on rename hits.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict

from survey_any._root import content_root

ROOT = content_root()
VOCAB = ROOT / "vocab" / "tags.yml"


def parse_yaml_minimal(text: str) -> dict[str, dict[str, list[str] | None]]:
    """Tiny YAML parser sized for our flat tag dict + list-valued attributes.

    Skips lines starting with '#'. Top-level keys end with ':'. Inline
    list values are written as `[a, b]`. Multi-line lists aren't used here.
    """
    out: dict[str, dict[str, list[str] | None]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            # top-level "name:"
            key = line.split(":", 1)[0].strip()
            current = key
            out[current] = {}
        else:
            if current is None:
                continue
            inner = line.strip()
            if ":" not in inner:
                continue
            k, v = inner.split(":", 1)
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                items = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                out[current][k.strip()] = items
            elif not v:
                out[current][k.strip()] = []
            else:
                out[current][k.strip()] = v
    return out


def load_vocab() -> tuple[set[str], dict[str, str]]:
    """Return (preferred_set, alias->preferred map)."""
    if not VOCAB.exists():
        print(f"vocab file not found: {VOCAB}", file=sys.stderr)
        return set(), {}
    text = VOCAB.read_text(encoding="utf-8")
    vocab = parse_yaml_minimal(text)
    preferred = set(vocab.keys())
    alias: dict[str, str] = {}
    for pref, attrs in vocab.items():
        for syn in attrs.get("use_for") or []:
            alias[syn] = pref
    return preferred, alias


def fm_dump() -> list[dict]:
    out = subprocess.check_output(["mise", "run", "fm"], text=True, stderr=subprocess.DEVNULL)
    return json.loads(out)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    strict = "--strict" in args

    preferred, alias = load_vocab()
    if not preferred:
        return 1

    rename: dict[str, list[str]] = defaultdict(list)  # alias -> [topic, ...]
    unknown: Counter[str] = Counter()
    ok: Counter[str] = Counter()

    data = fm_dump()
    for entry in data:
        topic = entry.get("topic", "?")
        for tag in entry.get("tags", []):
            t = tag.strip().strip('"')
            if not t:
                continue
            if t in alias:
                rename[t].append(topic)
            elif t in preferred:
                ok[t] += 1
            else:
                unknown[t] += 1

    print(f"# Tag validation against vocab/tags.yml ({len(preferred)} preferred terms)")
    print()
    print(f"  ok:      {sum(ok.values())} usages across {len(ok)} preferred tags")
    print(f"  rename:  {sum(len(v) for v in rename.values())} usages of {len(rename)} aliases")
    print(f"  unknown: {sum(unknown.values())} usages of {len(unknown)} unregistered tags")
    print()

    if rename:
        print("## Aliases that should be renamed to preferred form")
        print()
        for src, topics in sorted(rename.items(), key=lambda x: -len(x[1])):
            dst = alias[src]
            preview = ", ".join(topics[:3]) + (" ..." if len(topics) > 3 else "")
            print(f"  {src:30s}  ->  {dst:25s}  ({len(topics)} topics: {preview})")
        print()

    if unknown:
        print("## Unregistered tags (top 30 by frequency)")
        print()
        for tag, n in unknown.most_common(30):
            print(f"  {n:4d}  {tag}")
        print()
        print(f"  Run `mise run tags-suggest` to identify merge/promote candidates.")

    if strict and rename:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
