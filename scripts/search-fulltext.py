#!/usr/bin/env python3
"""BM25 ranked search over memory/bm25-index.json.

Usage:
  python3 scripts/search-fulltext.py "query string" [--top N] [--kind topic|reference]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "memory" / "bm25-index.json"
TOPICS_DIR = ROOT / "topics"
REFS_DIR = ROOT / "references"

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tokenizer import tokenize, BM25_K1 as K1, BM25_B as B  # noqa: E402


def warn_if_stale(index_path: Path) -> None:
    """Print a warning when source content is newer than the index."""
    try:
        index_mtime = index_path.stat().st_mtime
    except OSError:
        return
    newest = 0.0
    for d in (TOPICS_DIR, REFS_DIR):
        for f in d.rglob("*.md"):
            m = f.stat().st_mtime
            if m > newest:
                newest = m
    if newest > index_mtime:
        print(
            "warn: bm25 index is older than source content. "
            "Run `mise run build-index` to refresh.",
            file=sys.stderr,
        )



def score(query_terms: list[str], doc: dict, idf: dict, avgdl: float) -> float:
    s = 0.0
    dl = doc["len"]
    norm = K1 * (1 - B + B * dl / avgdl)
    for t in query_terms:
        if t not in doc["tf"]:
            continue
        idf_t = idf.get(t, 0)
        tf = doc["tf"][t]
        s += idf_t * (tf * (K1 + 1)) / (tf + norm)
    return s


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--kind", choices=["topic", "reference"], help="filter by kind")
    args = p.parse_args()

    if not INDEX_PATH.exists():
        print(f"index not found: {INDEX_PATH}. Run `mise run build-index` first.", file=sys.stderr)
        return 1

    warn_if_stale(INDEX_PATH)
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    qterms = tokenize(args.query)
    if not qterms:
        print("query is empty after tokenization", file=sys.stderr)
        return 1

    ranked: list[tuple[float, dict]] = []
    for doc in index["docs"]:
        if args.kind and doc["kind"] != args.kind:
            continue
        s = score(qterms, doc, index["idf"], index["avgdl"])
        if s > 0:
            ranked.append((s, doc))

    ranked.sort(key=lambda x: -x[0])

    print(f"query: {args.query!r}  ({len(qterms)} tokens after normalization)")
    print(f"results: {len(ranked)} hits, top {min(args.top, len(ranked))}:")
    print()
    for s, doc in ranked[: args.top]:
        marker = "[T]" if doc["kind"] == "topic" else "[R]"
        print(f"  {s:6.2f}  {marker}  {doc['name']:50s}  {doc['title'][:50]}")

    if not ranked:
        print("  (no hits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
