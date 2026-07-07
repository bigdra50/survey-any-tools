#!/usr/bin/env python3
"""Suggest `related:` candidates for a topic by fusing three signals.

Read-only: this script never writes to topics/ or memory/. It only reads
existing artifacts and prints a ranked suggestion list.

Signals (each optional; a signal that has no data for a given pair simply
contributes nothing, and if a whole signal is globally unavailable its
weight is redistributed among the remaining ones):

  1. dense   - cosine similarity over the existing embedding index
               (memory/embeddings.npy + embedding-meta.json, built by
               build-embeddings.py). Skipped with a note if the index is
               missing or numpy is not installed.
  2. trace   - co-occurrence in memory/seeking-trace.jsonl: how many trace
               lines mention both the target topic and the candidate in the
               same line's (hits + picked) set.
  3. sources - overlap-coefficient similarity of the two topics' `sources:`
               lists (shared references / size of the smaller list), i.e.
               "how much of the smaller topic's reading list is shared".

For comparison, the existing tag-overlap heuristic (mise run fm-related) is
recomputed locally and diffed against the fused suggestions, so a reader can
see what the new signals surface that plain tag overlap misses (and vice
versa).

Usage:
  python3 -m survey_any suggest-related <topic-name> [--top N] [--json]

Weights (renormalized when a signal is unavailable):
  dense=0.5  trace=0.3  sources=0.2
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from survey_any._embedding import EmbeddingUnavailable, cosine_scores, load_index
from survey_any._frontmatter import get_list, parse_frontmatter
from survey_any._root import content_root

ROOT = content_root()
TOPICS = ROOT / "topics"
MEMORY = ROOT / "memory"
TRACE_PATH = MEMORY / "seeking-trace.jsonl"

WEIGHT_DENSE = 0.5
WEIGHT_TRACE = 0.3
WEIGHT_SOURCES = 0.2


@dataclass(frozen=True)
class TopicRecord:
    name: str
    title: str
    tags: tuple[str, ...]
    sources: tuple[str, ...]
    related: tuple[str, ...]


@dataclass
class Candidate:
    name: str
    title: str
    dense: float | None = None
    trace_count: int = 0
    shared_sources: tuple[str, ...] = ()
    shared_tags: tuple[str, ...] = ()
    composite: float = 0.0
    evidence: list[str] = field(default_factory=list)


def load_topics() -> dict[str, TopicRecord]:
    topics: dict[str, TopicRecord] = {}
    for readme in sorted(TOPICS.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        name = readme.parent.name
        title = fm.get("title", name)
        topics[name] = TopicRecord(
            name=name,
            title=title if isinstance(title, str) else name,
            tags=tuple(get_list(fm, "tags")),
            sources=tuple(get_list(fm, "sources")),
            related=tuple(get_list(fm, "related")),
        )
    return topics


def load_trace() -> list[dict]:
    if not TRACE_PATH.exists():
        return []
    lines = []
    for raw in TRACE_PATH.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return lines


def trace_cooccurrence(target: str, trace_lines: list[dict]) -> dict[str, int]:
    """Count, per candidate topic, how many trace lines mention both.

    A "mention" is membership in a single line's hits+picked set. Multiple
    occurrences within one line count once (line-level co-occurrence, not
    token count).
    """
    counts: dict[str, int] = {}
    for entry in trace_lines:
        mentioned = set(entry.get("hits") or []) | set(entry.get("picked") or [])
        if target not in mentioned:
            continue
        for other in mentioned:
            if other == target:
                continue
            counts[other] = counts.get(other, 0) + 1
    return counts


def source_overlap(target: TopicRecord, candidate: TopicRecord) -> tuple[float, tuple[str, ...]]:
    """Overlap coefficient: shared / min(|A|, |B|). 0 if either list is empty."""
    a, b = set(target.sources), set(candidate.sources)
    if not a or not b:
        return 0.0, ()
    shared = tuple(sorted(a & b))
    if not shared:
        return 0.0, ()
    return len(shared) / min(len(a), len(b)), shared


def tag_overlap(target: TopicRecord, candidate: TopicRecord) -> tuple[int, tuple[str, ...]]:
    """Mirrors mise's fm-related: raw count of shared tags."""
    shared = tuple(sorted(set(target.tags) & set(candidate.tags)))
    return len(shared), shared


def dense_similarities(target_name: str, topics: dict[str, TopicRecord]) -> tuple[dict[str, float], str | None]:
    """Return (candidate -> cosine score, skip_reason_or_None)."""
    index = load_index(MEMORY)
    if isinstance(index, EmbeddingUnavailable):
        return {}, index.reason

    target_id = f"topic:{target_name}"
    if target_id not in index.ids:
        return {}, f"'{target_name}' not present in dense index (rebuild with build-embeddings.py)"

    pos = index.ids.index(target_id)
    query_vec = index.matrix[pos]
    scores = cosine_scores(query_vec, index.matrix)

    out: dict[str, float] = {}
    for doc_id, score in zip(index.ids, scores):
        if not doc_id.startswith("topic:"):
            continue
        name = doc_id[len("topic:") :]
        if name == target_name:
            continue
        if name not in topics:
            continue
        out[name] = float(score)
    return out, None


def normalize_linear(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalize to [0, 1] against the max observed value (0 if empty)."""
    if not values:
        return {}
    max_v = max(values.values())
    if max_v <= 0:
        return {k: 0.0 for k in values}
    return {k: v / max_v for k, v in values.items()}


def build_candidates(
    target_name: str,
    topics: dict[str, TopicRecord],
    trace_lines: list[dict],
) -> tuple[list[Candidate], str | None]:
    target = topics[target_name]

    dense_raw, dense_skip_reason = dense_similarities(target_name, topics)
    trace_raw = trace_cooccurrence(target_name, trace_lines)

    source_raw: dict[str, tuple[float, tuple[str, ...]]] = {}
    for name, rec in topics.items():
        if name == target_name:
            continue
        ratio, shared = source_overlap(target, rec)
        if ratio > 0:
            source_raw[name] = (ratio, shared)

    dense_available = dense_skip_reason is None
    weights = {
        "dense": WEIGHT_DENSE if dense_available else 0.0,
        "trace": WEIGHT_TRACE,
        "sources": WEIGHT_SOURCES,
    }
    weight_sum = sum(weights.values()) or 1.0
    weights = {k: v / weight_sum for k, v in weights.items()}

    trace_norm = normalize_linear({k: float(v) for k, v in trace_raw.items()})
    source_ratio_only = {k: v[0] for k, v in source_raw.items()}
    source_norm = normalize_linear(source_ratio_only)

    candidate_names = set(dense_raw) | set(trace_raw) | set(source_raw)
    candidates: list[Candidate] = []
    for name in candidate_names:
        rec = topics[name]
        dense_score = dense_raw.get(name)
        trace_count = trace_raw.get(name, 0)
        shared_sources = source_raw.get(name, (0.0, ()))[1]
        _, shared_tags = tag_overlap(target, rec)

        composite = 0.0
        evidence: list[str] = []
        if dense_score is not None:
            composite += weights["dense"] * max(dense_score, 0.0)
            evidence.append(f"dense={dense_score:.3f}")
        if name in trace_norm:
            composite += weights["trace"] * trace_norm[name]
            evidence.append(f"trace_cooccur={trace_count}")
        if name in source_norm:
            composite += weights["sources"] * source_norm[name]
            evidence.append(f"shared_sources={len(shared_sources)}")

        candidates.append(
            Candidate(
                name=name,
                title=rec.title,
                dense=dense_score,
                trace_count=trace_count,
                shared_sources=shared_sources,
                shared_tags=shared_tags,
                composite=composite,
                evidence=evidence,
            )
        )

    candidates.sort(key=lambda c: c.composite, reverse=True)
    return candidates, dense_skip_reason


def fm_related_ranking(target_name: str, topics: dict[str, TopicRecord], top: int) -> list[tuple[str, int, tuple[str, ...]]]:
    """Recompute the existing tag-overlap heuristic (mise run fm-related) for the diff view."""
    target = topics[target_name]
    ranked: list[tuple[str, int, tuple[str, ...]]] = []
    for name, rec in topics.items():
        if name == target_name:
            continue
        count, shared = tag_overlap(target, rec)
        if count > 0:
            ranked.append((name, count, shared))
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked[:top]


def render_text(
    target_name: str,
    candidates: list[Candidate],
    top: int,
    dense_skip_reason: str | None,
    fm_related: list[tuple[str, int, tuple[str, ...]]],
    existing_related: tuple[str, ...],
) -> str:
    lines: list[str] = []
    lines.append(f"related suggestions for: {target_name}")
    lines.append(f"existing related: {', '.join(existing_related) if existing_related else '(none)'}")
    if dense_skip_reason:
        lines.append(f"[dense signal skipped] {dense_skip_reason}")
    lines.append("")
    lines.append(f"{'#':<3} {'topic':<45} {'score':<7} evidence")
    for i, c in enumerate(candidates[:top], start=1):
        mark = " *" if c.name in existing_related else ""
        lines.append(f"{i:<3} {c.name:<45} {c.composite:<7.3f} {'; '.join(c.evidence)}{mark}")
    lines.append("")
    lines.append(f"tag-overlap baseline (mise run fm-related), top {top}:")
    fm_names = [name for name, _, _ in fm_related]
    for i, (name, count, shared) in enumerate(fm_related, start=1):
        lines.append(f"{i:<3} {name:<45} tags={count} [{', '.join(shared)}]")
    lines.append("")
    fused_names = [c.name for c in candidates[:top]]
    only_fused = [n for n in fused_names if n not in fm_names]
    only_tags = [n for n in fm_names if n not in fused_names]
    lines.append("diff vs tag-overlap baseline:")
    lines.append(f"  only in fused suggestions: {', '.join(only_fused) if only_fused else '(none)'}")
    lines.append(f"  only in tag-overlap:       {', '.join(only_tags) if only_tags else '(none)'}")
    return "\n".join(lines)


def render_json(
    target_name: str,
    candidates: list[Candidate],
    top: int,
    dense_skip_reason: str | None,
    fm_related: list[tuple[str, int, tuple[str, ...]]],
    existing_related: tuple[str, ...],
) -> str:
    payload = {
        "target": target_name,
        "existing_related": list(existing_related),
        "dense_signal_skipped_reason": dense_skip_reason,
        "suggestions": [
            {
                "topic": c.name,
                "title": c.title,
                "composite_score": round(c.composite, 4),
                "dense_cosine": None if c.dense is None else round(c.dense, 4),
                "trace_cooccurrence": c.trace_count,
                "shared_sources": list(c.shared_sources),
                "shared_tags": list(c.shared_tags),
                "already_related": c.name in existing_related,
            }
            for c in candidates[:top]
        ],
        "tag_overlap_baseline": [
            {"topic": name, "shared_tag_count": count, "shared_tags": list(shared)}
            for name, count, shared in fm_related
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("topic", help="topic directory name under topics/ (bare slug or topics/<slug>[/README.md] path)")
    parser.add_argument("--top", type=int, default=10, help="number of suggestions to show (default: 10)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a text table")
    args = parser.parse_args(argv)

    # slug 以外に topics/<slug> や topics/<slug>/README.md のパス形式も受け付ける
    args.topic = args.topic.rstrip("/")
    if args.topic.endswith("/README.md"):
        args.topic = args.topic[: -len("/README.md")]
    if "/" in args.topic:
        args.topic = args.topic.split("/")[-1]

    topics = load_topics()
    if args.topic not in topics:
        print(f"suggest-related: topic '{args.topic}' not found under topics/", file=sys.stderr)
        return 1

    trace_lines = load_trace()
    candidates, dense_skip_reason = build_candidates(args.topic, topics, trace_lines)
    fm_related = fm_related_ranking(args.topic, topics, args.top)
    existing_related = topics[args.topic].related

    if args.json:
        print(render_json(args.topic, candidates, args.top, dense_skip_reason, fm_related, existing_related))
    else:
        print(render_text(args.topic, candidates, args.top, dense_skip_reason, fm_related, existing_related))
    return 0


if __name__ == "__main__":
    sys.exit(main())
