#!/usr/bin/env python3
"""topics の sources: を逆引きして references に Cited by セクションを挿入する。

冪等: <!-- backlinks:start --> ... <!-- backlinks:end --> マーカーで挟まれた領域だけ更新する。
マーカーがなければファイル末尾に追加する。
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "topics"
REFS = ROOT / "references"

START = "<!-- backlinks:start -->"
END = "<!-- backlinks:end -->"


def parse_frontmatter(text: str) -> dict[str, object]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = m.group(1)
    out: dict[str, object] = {}

    title = re.search(r'^title:\s*"(.*)"', fm, re.M)
    if title:
        out["title"] = title.group(1)

    # sources: list (multi-line "  - name" or inline "[a, b]")
    sources: list[str] = []
    inline = re.search(r"^sources:\s*\[(.*)\]\s*$", fm, re.M)
    if inline:
        sources = [s.strip().strip('"') for s in inline.group(1).split(",") if s.strip()]
    else:
        block = re.search(r"^sources:\s*\n((?:\s+-\s+.*\n)+)", fm, re.M)
        if block:
            for line in block.group(1).splitlines():
                m2 = re.match(r"\s+-\s+(.*)", line)
                if m2:
                    sources.append(m2.group(1).strip().strip('"'))
    out["sources"] = sources
    return out


def collect_backlinks() -> dict[str, list[tuple[str, str]]]:
    """ref-name -> list[(topic-name, topic-title)]"""
    backlinks: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for readme in sorted(TOPICS.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        topic = readme.parent.name
        title = fm.get("title") or topic
        for src in fm.get("sources", []):
            # Strip "url:" or "http..." which aren't reference names
            if src.startswith("http") or ":" in src and not (REFS / f"{src}.md").exists():
                continue
            backlinks[src].append((topic, str(title)))
    return backlinks


def render_block(entries: list[tuple[str, str]]) -> str:
    lines = [START, "", "## Cited by", ""]
    for topic, title in sorted(entries, key=lambda x: x[0]):
        lines.append(f"- [{title}](../topics/{topic}/) (`{topic}`)")
    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def update_reference(ref_path: Path, entries: list[tuple[str, str]]) -> bool:
    text = ref_path.read_text(encoding="utf-8")
    block = render_block(entries)

    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if pat.search(text):
        new_text = pat.sub(block, text)
    else:
        sep = "\n\n" if not text.endswith("\n") else "\n"
        new_text = text.rstrip() + "\n\n" + block + "\n"

    if new_text != text:
        ref_path.write_text(new_text, encoding="utf-8")
        return True
    return False


def remove_block(ref_path: Path) -> bool:
    text = ref_path.read_text(encoding="utf-8")
    pat = re.compile(r"\n*" + re.escape(START) + r".*?" + re.escape(END) + r"\n*", re.S)
    new_text = pat.sub("\n", text).rstrip() + "\n"
    if new_text != text:
        ref_path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    backlinks = collect_backlinks()
    updated, removed = 0, 0
    seen: set[str] = set()

    for ref_name, entries in backlinks.items():
        ref_path = REFS / f"{ref_name}.md"
        if not ref_path.exists():
            print(f"warn: source '{ref_name}' has no matching reference file", file=sys.stderr)
            continue
        seen.add(ref_path.name)
        if update_reference(ref_path, entries):
            updated += 1

    # References not cited by any topic: strip stale backlink blocks if present.
    for ref_path in REFS.glob("*.md"):
        if ref_path.name in seen:
            continue
        if START in ref_path.read_text(encoding="utf-8"):
            if remove_block(ref_path):
                removed += 1

    print(f"backlinks: updated {updated} reference(s), cleaned {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
