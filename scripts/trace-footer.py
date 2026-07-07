#!/usr/bin/env python3
"""seeking-trace.jsonl から topic ごとの「探索経路」footer を生成・更新する。

認知的徒弟制（Collins, Brown & Newman 1989）の articulation:
結論だけでなく「どう探し、何を採用し、何を棄却したか」を読者（と /ask エージェント）に開示する。

冪等: <!-- seeking-trace:start --> ... <!-- seeking-trace:end --> マーカーで挟まれた
領域だけを更新する（backlinks.py と同じ方式）。マーカーがなければ末尾に追加する。

このスクリプトは topics/*/README.md の frontmatter を変更しない（本文末尾のみ）。

Usage:
    python3 scripts/trace-footer.py --dry-run   # 変更予定を表示するだけ（既定・安全）
    python3 scripts/trace-footer.py --apply     # 実際にファイルへ書き込む
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "topics"
TRACE_FILE = ROOT / "memory" / "seeking-trace.jsonl"

START = "<!-- seeking-trace:start -->"
END = "<!-- seeking-trace:end -->"


@dataclass(frozen=True)
class TraceEntry:
    """seeking-trace.jsonl の1行を表す不変データ。"""

    timestamp: str
    strategy: str
    query: str
    hits: tuple[str, ...]


def collect_by_topic(trace_file: Path, known_topics: set[str]) -> dict[str, list[TraceEntry]]:
    """topic 名 -> その topic が picked された TraceEntry のリスト（時系列昇順）。"""
    by_topic: dict[str, list[TraceEntry]] = defaultdict(list)
    if not trace_file.is_file():
        return by_topic
    for line in trace_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        picked = row.get("picked") or []
        if not isinstance(picked, list):
            continue
        entry = TraceEntry(
            timestamp=str(row.get("timestamp", "")),
            strategy=str(row.get("strategy", "")),
            query=str(row.get("query", "")),
            hits=tuple(str(h) for h in (row.get("hits") or [])),
        )
        for topic in picked:
            topic = str(topic)
            if topic in known_topics:
                by_topic[topic].append(entry)
    for entries in by_topic.values():
        entries.sort(key=lambda e: e.timestamp)
    return by_topic


def _format_date(timestamp: str) -> str:
    """ISO8601 timestamp から YYYY-MM-DD 部分だけ取り出す。壊れていれば原文を返す。"""
    return timestamp.split("T", 1)[0] if "T" in timestamp else timestamp


def render_block(entries: list[TraceEntry]) -> str:
    """探索経路セクションを Markdown へレンダリングする。"""
    lines = [START, "", "## 探索経路", ""]
    for e in entries:
        date = _format_date(e.timestamp)
        hits = "、".join(e.hits) if e.hits else "(なし)"
        lines.append(f"- {date} ({e.strategy}) 「{e.query}」→ 参照: {hits}")
    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def compute_update(readme_path: Path, entries: list[TraceEntry]) -> tuple[str, str] | None:
    """更新後テキストを計算する。変更が無ければ None を返す。"""
    text = readme_path.read_text(encoding="utf-8")
    block = render_block(entries)

    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if pat.search(text):
        new_text = pat.sub(lambda _m: block, text)
    else:
        new_text = text.rstrip() + "\n\n" + block + "\n"

    if new_text == text:
        return None
    return text, new_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="変更予定を表示するだけで書き込まない")
    mode.add_argument("--apply", action="store_true", help="実際に README.md へ書き込む")
    parser.add_argument(
        "--trace-file",
        type=Path,
        default=TRACE_FILE,
        help="seeking-trace.jsonl のパス（既定: memory/seeking-trace.jsonl）",
    )
    args = parser.parse_args()

    topics_dir = TOPICS.resolve()
    known_topics = {p.parent.name for p in topics_dir.glob("*/README.md")}

    by_topic = collect_by_topic(args.trace_file, known_topics)

    if not by_topic:
        print("trace-footer: no picked entries found for existing topics")
        return 0

    updated = 0
    for topic, entries in sorted(by_topic.items()):
        readme_path = topics_dir / topic / "README.md"
        result = compute_update(readme_path, entries)
        if result is None:
            continue
        old_text, new_text = result
        updated += 1
        if args.dry_run:
            print(f"[dry-run] would update: topics/{topic}/README.md ({len(entries)} entries)")
        else:
            readme_path.write_text(new_text, encoding="utf-8")
            print(f"updated: topics/{topic}/README.md ({len(entries)} entries)")

    verb = "would update" if args.dry_run else "updated"
    print(f"trace-footer: {verb} {updated} topic README(s) out of {len(by_topic)} with trace entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
