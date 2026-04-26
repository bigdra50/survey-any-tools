#!/usr/bin/env python3
"""references/ 内の「次に読むべき論文」セクションに既存 reference へのリンクを挿入する。

照合キー: arXiv ID, DOI
冪等: 既にリンク済みの行はスキップする。
"""

import re
import sys
from pathlib import Path

REFS_DIR = Path("references")
ARXIV_PAT = re.compile(r"(\d{4}\.\d{4,6})")
DOI_PAT = re.compile(r"(10\.\d{4,}/[^\s,\]\)]+)")


def extract_ids_from_frontmatter(text: str) -> dict[str, str]:
    """frontmatter から arXiv ID と DOI を抽出する。"""
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not fm_match:
        return {}
    fm = fm_match.group(1)
    ids = {}

    arxiv = re.search(r"^arxiv_id:\s*\"(\d{4}\.\d{4,6})\"", fm, re.M)
    if arxiv:
        ids[f"arxiv:{arxiv.group(1)}"] = True

    url = re.search(r'^url:\s*"?(https?://\S+?)"?\s*$', fm, re.M)
    if url:
        m = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,6})", url.group(1))
        if m:
            ids[f"arxiv:{m.group(1)}"] = True

    doi = re.search(r'^doi:\s*"(.+?)"', fm, re.M)
    if doi and doi.group(1).strip():
        ids[f"doi:{doi.group(1)}"] = True

    return ids


def build_index() -> dict[str, str]:
    """ID → reference ファイル名 のインデックスを構築する。"""
    index: dict[str, str] = {}
    for f in sorted(REFS_DIR.glob("*.md")):
        text = f.read_text()
        fm_match = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not fm_match or "type: paper" not in fm_match.group(1):
            continue
        for key in extract_ids_from_frontmatter(text):
            index[key] = f.name
    return index


def process_file(filepath: Path, index: dict[str, str], dry_run: bool) -> list[str]:
    """1ファイルの「次に読むべき論文」セクションを処理する。"""
    text = filepath.read_text()
    lines = text.splitlines()
    changes: list[str] = []
    in_section = False
    new_lines: list[str] = []

    for line in lines:
        if "次に読むべき論文" in line:
            in_section = True
            new_lines.append(line)
            continue

        if in_section and line.startswith("#"):
            in_section = False

        if in_section and line.strip().startswith("-"):
            if re.search(r"\[→\]\(.*?\.md\)", line):
                new_lines.append(line)
                continue

            ref_file = None
            for m in ARXIV_PAT.finditer(line):
                key = f"arxiv:{m.group(1)}"
                if key in index and index[key] != filepath.name:
                    ref_file = index[key]
                    break

            if not ref_file:
                for m in DOI_PAT.finditer(line):
                    key = f"doi:{m.group(1)}"
                    if key in index and index[key] != filepath.name:
                        ref_file = index[key]
                        break

            if ref_file:
                link = f" [→]({ref_file})"
                new_line = line.rstrip() + link
                changes.append(f"  {filepath.name}: {ref_file}")
                new_lines.append(new_line)
                continue

        new_lines.append(line)

    if changes and not dry_run:
        filepath.write_text("\n".join(new_lines) + "\n")

    return changes


def collect_unlinked(threshold: int = 2) -> None:
    """未リンクエントリからタイトルを抽出し、言及回数でランク付けして報告する。"""
    from collections import Counter

    title_mentions: Counter[str] = Counter()
    title_sources: dict[str, list[str]] = {}

    for f in sorted(REFS_DIR.glob("*.md")):
        text = f.read_text()
        in_section = False
        for line in text.splitlines():
            if "次に読むべき論文" in line:
                in_section = True
                continue
            if in_section and line.startswith("#"):
                in_section = False
            if in_section and line.strip().startswith("-") and "[→]" not in line:
                title_m = re.search(r'"([^"]{10,})"', line)
                if title_m:
                    key = title_m.group(1).strip()[:80].lower()
                    title_mentions[key] += 1
                    title_sources.setdefault(key, []).append(f.name)

    hot = [(t, c, title_sources[t]) for t, c in title_mentions.most_common() if c >= threshold]
    if not hot:
        return

    print(f"\n=== 未調査だが複数回言及されている論文 ({threshold}回以上) ===")
    for title, count, sources in hot:
        print(f"  {count}x  {title}")
        print(f"       言及元: {', '.join(sorted(set(sources)))}")


def main():
    dry_run = "--dry-run" in sys.argv

    index = build_index()
    print(f"Index: {len(index)} IDs from {len(set(index.values()))} references")

    total_changes: list[str] = []
    for f in sorted(REFS_DIR.glob("*.md")):
        changes = process_file(f, index, dry_run)
        total_changes.extend(changes)

    if total_changes:
        label = "would link" if dry_run else "linked"
        print(f"\n{label} {len(total_changes)} entries:")
        for c in total_changes:
            print(c)
    else:
        print("\nNo linkable entries found.")

    if dry_run and total_changes:
        print(f"\nRun without --dry-run to apply.")

    collect_unlinked()


if __name__ == "__main__":
    main()
