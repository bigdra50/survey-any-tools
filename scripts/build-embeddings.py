#!/usr/bin/env python3
"""Build dense sentence-transformer embeddings over topics + references.

Writes:
  memory/embeddings.npy         - float32 matrix shape (N, dim), L2-normalized
  memory/embedding-meta.json    - {model, dim, count, ids}

The embedding stack (numpy + sentence-transformers) is an *optional dependency*.
This script exits cleanly with a hint when either is missing; build-index.py
(BM25) keeps working without them.

Usage:
  python3 scripts/build-embeddings.py [--model MODEL] [--batch-size N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "topics"
REFS = ROOT / "references"
MEMORY = ROOT / "memory"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _embedding import (  # noqa: E402
    DEFAULT_MODEL,
    EmbeddingDoc,
    encode_passages,
    import_numpy,
    import_sentence_transformers,
    save_index,
)
from _frontmatter import parse_frontmatter, split_frontmatter  # noqa: E402


def collect_docs() -> list[EmbeddingDoc]:
    docs: list[EmbeddingDoc] = []
    for readme in sorted(TOPICS.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        _, body = split_frontmatter(text)
        topic = readme.parent.name
        title = fm.get("title", topic)
        docs.append(
            EmbeddingDoc(
                id=f"topic:{topic}",
                kind="topic",
                name=topic,
                title=title if isinstance(title, str) else topic,
                text=body,
            )
        )
    for ref in sorted(REFS.glob("*.md")):
        text = ref.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        _, body = split_frontmatter(text)
        name = ref.stem
        title = fm.get("title", name)
        docs.append(
            EmbeddingDoc(
                id=f"reference:{name}",
                kind="reference",
                name=name,
                title=title if isinstance(title, str) else name,
                text=body,
            )
        )
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL, help="sentence-transformers model id")
    parser.add_argument("--batch-size", type=int, default=16, help="encode batch size")
    args = parser.parse_args()

    np_module, np_err = import_numpy()
    if np_err is not None:
        print(f"build-embeddings: {np_err.reason}", file=sys.stderr)
        return 2
    SentenceTransformer, st_err = import_sentence_transformers()
    if st_err is not None:
        print(f"build-embeddings: {st_err.reason}", file=sys.stderr)
        return 2

    docs = collect_docs()
    if not docs:
        print("build-embeddings: no docs found", file=sys.stderr)
        return 1

    print(
        f"build-embeddings: loading model {args.model!r} (first run downloads ~120MB)...",
        file=sys.stderr,
    )
    load_start = time.perf_counter()
    model = SentenceTransformer(args.model)
    load_seconds = time.perf_counter() - load_start

    encode_start = time.perf_counter()
    matrix = encode_passages(model, docs, batch_size=args.batch_size)
    encode_seconds = time.perf_counter() - encode_start

    ids = [d.id for d in docs]
    npy_path, meta_path = save_index(MEMORY, args.model, ids, matrix)

    rel_npy = npy_path.relative_to(ROOT)
    rel_meta = meta_path.relative_to(ROOT)
    print(
        f"dense index: {matrix.shape[0]} docs, dim={matrix.shape[1]}, "
        f"model_load={load_seconds:.1f}s encode={encode_seconds:.1f}s -> "
        f"{rel_npy}, {rel_meta}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
