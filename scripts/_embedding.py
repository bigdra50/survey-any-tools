"""Shared dense-embedding helpers for build-embeddings.py / search-fulltext.py.

Design choices:
- sentence-transformers and numpy are *optional*. Importing this module never
  fails; helpers report missing deps via the EmbeddingUnavailable result type.
- Default model: paraphrase-multilingual-MiniLM-L12-v2 (384 dim, 50+ languages,
  fits the Japanese-heavy corpus without a CJK-specific pretrain step).
- File I/O lives at the boundary (load_corpus / save_index / load_index); the
  scoring helpers stay pure for easier reasoning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDINGS_FILENAME = "embeddings.npy"
META_FILENAME = "embedding-meta.json"
# Truncate body to keep encode time bounded; multilingual MiniLM caps at 128
# tokens internally, so feeding more than ~4 KB of text just wastes time.
MAX_BODY_CHARS = 4096


@dataclass(frozen=True)
class EmbeddingDoc:
    """One indexed document. Mirrors the BM25 doc shape minus tf/len."""

    id: str
    kind: str
    name: str
    title: str
    text: str


@dataclass(frozen=True)
class EmbeddingIndex:
    """Loaded dense index. matrix is shape (N, dim), L2-normalized."""

    model_name: str
    dim: int
    ids: tuple[str, ...]
    matrix: "np.ndarray"


@dataclass(frozen=True)
class EmbeddingUnavailable:
    """Returned when a hard dep is missing. Carries a human-readable hint."""

    reason: str


def import_numpy() -> "tuple[Any, EmbeddingUnavailable | None]":
    try:
        import numpy as np
    except ImportError as e:
        return None, EmbeddingUnavailable(
            reason=f"numpy is not installed ({e}). Install with `pip install numpy`."
        )
    return np, None


def import_sentence_transformers() -> "tuple[Any, EmbeddingUnavailable | None]":
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        return None, EmbeddingUnavailable(
            reason=(
                f"sentence-transformers is not installed ({e}). "
                "Install with `pip install sentence-transformers` to enable "
                "dense / hybrid search."
            )
        )
    return SentenceTransformer, None


def truncate_body(text: str, limit: int = MAX_BODY_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def encode_passages(
    model: Any, docs: list[EmbeddingDoc], batch_size: int = 16
) -> "np.ndarray":
    """Encode (title + body) into an L2-normalized float32 matrix."""
    passages = [f"{d.title}\n\n{truncate_body(d.text)}" for d in docs]
    matrix = model.encode(
        passages,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return matrix.astype("float32", copy=False)


def encode_query(model: Any, query: str) -> "np.ndarray":
    matrix = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return matrix[0].astype("float32", copy=False)


def cosine_scores(query_vec: "np.ndarray", matrix: "np.ndarray") -> "np.ndarray":
    """Cosine similarity assuming both sides are L2-normalized."""
    return matrix @ query_vec


def save_index(
    out_dir: Path,
    model_name: str,
    ids: list[str],
    matrix: "np.ndarray",
) -> tuple[Path, Path]:
    """Persist embeddings + sidecar metadata. Returns (npy_path, meta_path)."""
    np_module, err = import_numpy()
    if err is not None or np_module is None:
        # Caller should have guarded this; raise loudly to avoid silent corruption.
        raise RuntimeError(err.reason if err else "numpy unavailable")

    out_dir.mkdir(parents=True, exist_ok=True)
    npy_path = out_dir / EMBEDDINGS_FILENAME
    meta_path = out_dir / META_FILENAME

    np_module.save(npy_path, matrix)
    meta = {
        "model": model_name,
        "dim": int(matrix.shape[1]),
        "count": int(matrix.shape[0]),
        "ids": ids,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return npy_path, meta_path


def load_index(memory_dir: Path) -> EmbeddingIndex | EmbeddingUnavailable:
    """Load embeddings + metadata. Returns EmbeddingUnavailable on any failure."""
    np_module, err = import_numpy()
    if err is not None or np_module is None:
        return err or EmbeddingUnavailable(reason="numpy unavailable")

    npy_path = memory_dir / EMBEDDINGS_FILENAME
    meta_path = memory_dir / META_FILENAME
    if not npy_path.exists() or not meta_path.exists():
        return EmbeddingUnavailable(
            reason=(
                f"dense index not found at {npy_path.name} / {meta_path.name}. "
                "Run `python3 scripts/build-embeddings.py` first."
            )
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    matrix = np_module.load(npy_path)
    if matrix.shape[0] != meta["count"] or matrix.shape[1] != meta["dim"]:
        return EmbeddingUnavailable(
            reason=(
                f"dense index shape mismatch: matrix={matrix.shape}, "
                f"meta count={meta['count']} dim={meta['dim']}. Rebuild required."
            )
        )
    return EmbeddingIndex(
        model_name=meta["model"],
        dim=int(meta["dim"]),
        ids=tuple(meta["ids"]),
        matrix=matrix,
    )


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60
) -> dict[str, float]:
    """Reciprocal Rank Fusion (Cormack et al. 2009).

    Each ranking is a list of doc ids in descending relevance order.
    Returns a dict id -> fused score (higher is better).
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores
