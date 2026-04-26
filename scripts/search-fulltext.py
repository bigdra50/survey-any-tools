#!/usr/bin/env python3
"""Ranked full-text search over memory/bm25-index.json (+ optional dense index).

Modes:
  default  - BM25 only (unchanged from the original implementation)
  --dense  - sentence-transformer cosine similarity only
  --hybrid - Reciprocal Rank Fusion of BM25 and dense rankings (k=60)

Dense / hybrid require numpy + sentence-transformers and a prebuilt index at
memory/embeddings.npy + memory/embedding-meta.json. They fall back to BM25
with a warning when either is missing.

Usage:
  python3 scripts/search-fulltext.py "query" [--top N] [--kind topic|reference]
                                              [--hybrid | --dense] [--rrf-k 60]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "memory" / "bm25-index.json"
MEMORY = ROOT / "memory"
TOPICS_DIR = ROOT / "topics"
REFS_DIR = ROOT / "references"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tokenizer import BM25_B as B  # noqa: E402
from _tokenizer import BM25_K1 as K1  # noqa: E402
from _tokenizer import tokenize  # noqa: E402
from _embedding import (  # noqa: E402
    EmbeddingIndex,
    EmbeddingUnavailable,
    cosine_scores,
    encode_query,
    import_sentence_transformers,
    load_index,
    reciprocal_rank_fusion,
)


@dataclass(frozen=True)
class ScoredDoc:
    score: float
    id: str
    kind: str
    name: str
    title: str


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


def score_bm25(query_terms: list[str], doc: dict, idf: dict, avgdl: float) -> float:
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


def rank_bm25(
    query_terms: list[str], index: dict, kind_filter: str | None
) -> list[ScoredDoc]:
    ranked: list[ScoredDoc] = []
    for doc in index["docs"]:
        if kind_filter and doc["kind"] != kind_filter:
            continue
        s = score_bm25(query_terms, doc, index["idf"], index["avgdl"])
        if s > 0:
            ranked.append(
                ScoredDoc(
                    score=s,
                    id=doc["id"],
                    kind=doc["kind"],
                    name=doc["name"],
                    title=doc["title"],
                )
            )
    ranked.sort(key=lambda x: -x.score)
    return ranked


def rank_dense(
    query: str, dense_index: EmbeddingIndex, doc_meta: dict[str, dict], kind_filter: str | None
) -> list[ScoredDoc]:
    SentenceTransformer, st_err = import_sentence_transformers()
    if st_err is not None or SentenceTransformer is None:
        # Caller should have already validated; treat as empty ranking.
        return []
    model = SentenceTransformer(dense_index.model_name)
    query_vec = encode_query(model, query)
    scores = cosine_scores(query_vec, dense_index.matrix)

    pairs: list[tuple[float, str]] = []
    for idx, doc_id in enumerate(dense_index.ids):
        meta = doc_meta.get(doc_id)
        if meta is None:
            continue
        if kind_filter and meta["kind"] != kind_filter:
            continue
        pairs.append((float(scores[idx]), doc_id))
    pairs.sort(key=lambda x: -x[0])

    ranked: list[ScoredDoc] = []
    for s, doc_id in pairs:
        meta = doc_meta[doc_id]
        ranked.append(
            ScoredDoc(
                score=s,
                id=doc_id,
                kind=meta["kind"],
                name=meta["name"],
                title=meta["title"],
            )
        )
    return ranked


def fuse_rrf(
    bm25_ranking: list[ScoredDoc],
    dense_ranking: list[ScoredDoc],
    doc_meta: dict[str, dict],
    k: int,
) -> list[ScoredDoc]:
    fused = reciprocal_rank_fusion(
        [[d.id for d in bm25_ranking], [d.id for d in dense_ranking]],
        k=k,
    )
    items = sorted(fused.items(), key=lambda x: -x[1])
    out: list[ScoredDoc] = []
    for doc_id, score in items:
        meta = doc_meta.get(doc_id)
        if meta is None:
            continue
        out.append(
            ScoredDoc(
                score=score,
                id=doc_id,
                kind=meta["kind"],
                name=meta["name"],
                title=meta["title"],
            )
        )
    return out


def build_doc_meta(index: dict) -> dict[str, dict]:
    return {
        d["id"]: {"kind": d["kind"], "name": d["name"], "title": d["title"]}
        for d in index["docs"]
    }


def print_ranking_bm25(query: str, qterms: list[str], ranked: list[ScoredDoc], top: int) -> None:
    """Original BM25 output format. Kept byte-compatible to avoid regressions."""
    print(f"query: {query!r}  ({len(qterms)} tokens after normalization)")
    print(f"results: {len(ranked)} hits, top {min(top, len(ranked))}:")
    print()
    for r in ranked[:top]:
        marker = "[T]" if r.kind == "topic" else "[R]"
        print(f"  {r.score:6.2f}  {marker}  {r.name:50s}  {r.title[:50]}")
    if not ranked:
        print("  (no hits)")


def print_ranking_scored(query: str, mode: str, ranked: list[ScoredDoc], top: int) -> None:
    """Output for dense / hybrid modes (tighter score precision)."""
    print(f"query: {query!r}  (mode={mode})")
    print(f"results: {len(ranked)} hits, top {min(top, len(ranked))}:")
    print()
    for r in ranked[:top]:
        marker = "[T]" if r.kind == "topic" else "[R]"
        print(f"  {r.score:7.4f}  {marker}  {r.name:50s}  {r.title[:50]}")
    if not ranked:
        print("  (no hits)")


def resolve_dense(
    args: argparse.Namespace,
) -> tuple[EmbeddingIndex | None, str | None]:
    """Return (dense_index, fallback_reason). Fallback reason is None on success."""
    loaded = load_index(MEMORY)
    if isinstance(loaded, EmbeddingUnavailable):
        return None, loaded.reason
    _, st_err = import_sentence_transformers()
    if st_err is not None:
        return None, st_err.reason
    return loaded, None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("query")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--kind", choices=["topic", "reference"], help="filter by kind")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--hybrid", action="store_true", help="BM25 + dense via RRF")
    mode.add_argument("--dense", action="store_true", help="dense embeddings only")
    p.add_argument("--rrf-k", type=int, default=60, help="RRF constant (default 60)")
    p.add_argument(
        "--candidate-pool",
        type=int,
        default=100,
        help="cap each ranking to this size before RRF fusion (default 100)",
    )
    args = p.parse_args()

    if not INDEX_PATH.exists():
        print(
            f"index not found: {INDEX_PATH}. Run `mise run build-index` first.",
            file=sys.stderr,
        )
        return 1

    warn_if_stale(INDEX_PATH)
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    doc_meta = build_doc_meta(index)
    qterms = tokenize(args.query)

    want_dense = args.hybrid or args.dense
    dense_index: EmbeddingIndex | None = None
    if want_dense:
        dense_index, fallback_reason = resolve_dense(args)
        if dense_index is None:
            print(
                f"warn: dense search disabled -> falling back to BM25. {fallback_reason}",
                file=sys.stderr,
            )
            want_dense = False

    # Pure BM25 path (default + fallback) keeps the original output format.
    if not want_dense:
        if not qterms:
            print("query is empty after tokenization", file=sys.stderr)
            return 1
        ranked = rank_bm25(qterms, index, args.kind)
        print_ranking_bm25(args.query, qterms, ranked, args.top)
        return 0

    assert dense_index is not None  # for type narrowing
    dense_ranking = rank_dense(args.query, dense_index, doc_meta, args.kind)

    if args.dense:
        print_ranking_scored(
            args.query, f"dense ({dense_index.model_name})", dense_ranking, args.top
        )
        return 0

    # hybrid: need BM25 even if qterms is empty (just yields no BM25 hits).
    bm25_ranking = rank_bm25(qterms, index, args.kind) if qterms else []
    pool = max(args.candidate_pool, args.top)
    fused = fuse_rrf(bm25_ranking[:pool], dense_ranking[:pool], doc_meta, args.rrf_k)
    print_ranking_scored(
        args.query,
        f"hybrid (rrf k={args.rrf_k}, pool={pool})",
        fused,
        args.top,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
