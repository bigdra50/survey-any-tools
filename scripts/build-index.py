#!/usr/bin/env python3
"""Build a BM25 index over topics + references and persist to memory/bm25-index.json.

Standard library only (no rank_bm25 dependency). Tokenization is intentionally simple:
  - lowercase
  - split on non-word boundaries (handles English + ASCII tokens)
  - 2-char unigrams for CJK (Japanese) so 図書館 -> ["図書", "書館"]

For Japanese-heavy content this is a "good enough" baseline that fits one file.
A real upgrade path: switch tokenizer to fugashi/sudachi when needed.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tokenizer import tokenize  # noqa: E402
from _frontmatter import parse_frontmatter, split_frontmatter  # noqa: E402
from _root import content_root  # noqa: E402

ROOT = content_root()
TOPICS = ROOT / "topics"
REFS = ROOT / "references"
OUT = ROOT / "memory" / "bm25-index.json"





def collect_docs() -> list[dict]:
    docs: list[dict] = []
    for readme in sorted(TOPICS.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        _, body = split_frontmatter(text)
        topic = readme.parent.name
        docs.append(
            {
                "id": f"topic:{topic}",
                "kind": "topic",
                "name": topic,
                "title": fm.get("title", topic),
                "tokens": tokenize(fm.get("title", "") + "\n" + body),
            }
        )
    for ref in sorted(REFS.glob("*.md")):
        text = ref.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        _, body = split_frontmatter(text)
        name = ref.stem
        docs.append(
            {
                "id": f"reference:{name}",
                "kind": "reference",
                "name": name,
                "title": fm.get("title", name),
                "tokens": tokenize(fm.get("title", "") + "\n" + body),
            }
        )
    return docs


def build_bm25(docs: list[dict]) -> dict:
    N = len(docs)
    avgdl = sum(len(d["tokens"]) for d in docs) / max(N, 1)

    # df per term
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d["tokens"]):
            df[t] = df.get(t, 0) + 1

    # idf
    idf = {t: math.log((N - n + 0.5) / (n + 0.5) + 1) for t, n in df.items()}

    # tf per doc
    doc_records: list[dict] = []
    for d in docs:
        tf: dict[str, int] = {}
        for t in d["tokens"]:
            tf[t] = tf.get(t, 0) + 1
        doc_records.append(
            {
                "id": d["id"],
                "kind": d["kind"],
                "name": d["name"],
                "title": d["title"],
                "len": len(d["tokens"]),
                "tf": tf,
            }
        )

    return {"N": N, "avgdl": avgdl, "idf": idf, "docs": doc_records}


def main() -> int:
    docs = collect_docs()
    if not docs:
        print("no docs found", file=sys.stderr)
        return 1
    index = build_bm25(docs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(
        f"bm25 index: {index['N']} docs, avgdl={index['avgdl']:.1f}, "
        f"{len(index['idf'])} terms -> {OUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
