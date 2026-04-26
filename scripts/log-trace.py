#!/usr/bin/env python3
"""Append a berrypicking step to memory/seeking-trace.jsonl.

Bates (1989) の進化するクエリ軌跡を 1 行 1 ステップで記録する。
詳細スキーマ: memory/README.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / "memory" / "seeking-trace.jsonl"

STRATEGIES = {
    "subject",
    "footnote-chasing",
    "citation-searching",
    "author",
    "area-scan",
    "journal-run",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--query", required=True, help="検索クエリ")
    p.add_argument("--hits", default="", help="ヒットしたトピック (comma-separated)")
    p.add_argument("--picked", default="", help="採用したトピック (comma-separated)")
    p.add_argument("--next", dest="next_query", default="", help="進化させた次のクエリ")
    p.add_argument(
        "--strategy",
        default="subject",
        help=f"Bates の戦略 ({', '.join(sorted(STRATEGIES))})",
    )
    p.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""), help="セッション識別子")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.strategy not in STRATEGIES:
        print(f"warn: unknown strategy '{args.strategy}'", file=sys.stderr)

    record = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "session": args.session or "anonymous",
        "query": args.query,
        "hits": [s for s in args.hits.split(",") if s.strip()],
        "picked": [s for s in args.picked.split(",") if s.strip()],
        "next_query": args.next_query,
        "strategy": args.strategy,
    }

    TRACE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"trace: {record['strategy']} q='{record['query'][:40]}' -> {len(record['hits'])} hits", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
