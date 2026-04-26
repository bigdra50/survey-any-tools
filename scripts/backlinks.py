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

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontmatter import parse_frontmatter, get_list  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "topics"
REFS = ROOT / "references"

START = "<!-- backlinks:start -->"
END = "<!-- backlinks:end -->"




def collect_backlinks(known_refs: set[str]) -> dict[str, list[tuple[str, str]]]:
    """ref-name -> list[(topic-name, topic-title)]

    Only `sources:` entries that exactly match an existing reference stem are
    accepted. Anything else (URLs, free-form citations, '../foo' attempts) is
    silently dropped. This prevents path-traversal-style abuse where a topic
    could otherwise cause writes outside references/ via auto-running pre-commit.
    """
    backlinks: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for readme in sorted(TOPICS.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        topic = readme.parent.name
        title = fm.get("title") or topic
        for src in get_list(fm, "sources"):
            if src not in known_refs:
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
    refs_dir = REFS.resolve()
    known_refs = {p.stem for p in refs_dir.glob("*.md")}
    backlinks = collect_backlinks(known_refs)
    updated, removed = 0, 0
    seen: set[str] = set()

    for ref_name, entries in backlinks.items():
        ref_path = (refs_dir / f"{ref_name}.md").resolve()
        # Refuse anything that escapes references/ even if known_refs filter
        # is bypassed by symlinks or future refactors.
        if not ref_path.is_relative_to(refs_dir) or not ref_path.is_file():
            print(f"warn: skipping suspicious ref path: {ref_name}", file=sys.stderr)
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
