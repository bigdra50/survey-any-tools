#!/usr/bin/env python3
"""Tag merge candidate detector for vocab/tags.yml authoring.

Reads all topic frontmatter via mise's fm-dump task and groups tags by:
  1. exact lowercased equality (cases of "AI" vs "ai")
  2. plural / singular collapse (agents <-> agent)
  3. hyphen variants (ai-agent <-> aiagent <-> ai_agent)
  4. Levenshtein distance <= 2 between candidates of length >= 4

Output: ordered groups so the human can decide preferred form for vocab/tags.yml.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize(tag: str) -> str:
    t = tag.lower().strip().strip('"').strip("'")
    t = re.sub(r"[\s_/]+", "-", t)
    return t


def collapse_key(tag: str) -> str:
    """Aggressive normalization for grouping candidates."""
    t = normalize(tag)
    t = re.sub(r"-+", "", t)
    if t.endswith("s") and len(t) > 4:
        t = t[:-1]
    return t


def fm_dump() -> list[dict]:
    out = subprocess.check_output(["mise", "run", "fm-dump"], text=True, stderr=subprocess.DEVNULL)
    return json.loads(out)


def main() -> int:
    data = fm_dump()
    counter: Counter[str] = Counter()
    occurrences: dict[str, list[str]] = defaultdict(list)

    for entry in data:
        topic = entry.get("topic", "?")
        for raw in entry.get("tags", []):
            t = normalize(raw)
            if not t:
                continue
            counter[t] += 1
            occurrences[t].append(topic)

    print(f"# Tag analysis ({len(counter)} unique tags across {sum(counter.values())} usages)")
    print()
    print("## Top 30 tags by frequency")
    print()
    for tag, n in counter.most_common(30):
        print(f"  {n:4d}  {tag}")
    print()

    # 1. Group by collapse_key (catches plurals and hyphen variants).
    groups: dict[str, list[str]] = defaultdict(list)
    for tag in counter:
        groups[collapse_key(tag)].append(tag)

    merge_candidates = [grp for grp in groups.values() if len(grp) > 1]

    # 2. Levenshtein-based fuzzy clusters (length >= 4).
    #
    # O(N^2) is wasteful when N grows past a few hundred tags. Cut down candidate
    # pairs by:
    #   - dropping single-occurrence tags (typos, proper nouns rarely worth merging)
    #   - bucketing by (length, first 2 chars) — Levenshtein <= 2 forces both to
    #     match within ±1 length and at most 1 differing prefix char, so we only
    #     need to compare each tag against its own bucket and adjacent buckets.
    longish = [t for t, n in counter.items() if len(t) >= 4 and n >= 2]
    buckets: dict[tuple[int, str], list[str]] = defaultdict(list)
    for t in longish:
        buckets[(len(t), t[:2])].append(t)

    seen: set[str] = set()
    fuzzy_groups: list[list[str]] = []
    for t in longish:
        if t in seen:
            continue
        cluster = [t]
        # Compare against same-length / ±1 / ±2 buckets, scanning all
        # 2-char prefixes that share at least one character with t[:2].
        # In practice prefix mismatch by >=2 chars implies LD >= 2 already.
        candidates: list[str] = []
        for dl in (-2, -1, 0, 1, 2):
            target_len = len(t) + dl
            if target_len < 4:
                continue
            for prefix, bucket in buckets.items():
                if prefix[0] != target_len:
                    continue
                # Allow up to 1 differing prefix char.
                p = prefix[1]
                diff = (p[0] != t[0]) + (p[1] != t[1])
                if diff <= 1:
                    candidates.extend(bucket)
        for b in candidates:
            if b == t or b in seen:
                continue
            if abs(len(t) - len(b)) <= 2 and levenshtein(t, b) <= 2:
                cluster.append(b)
        if len(cluster) > 1:
            for c in cluster:
                seen.add(c)
            fuzzy_groups.append(cluster)

    print("## Likely duplicates (plural/hyphen variants)")
    print()
    if not merge_candidates:
        print("  (none)")
    for grp in sorted(merge_candidates, key=lambda g: -sum(counter[t] for t in g)):
        ranked = sorted(grp, key=lambda t: -counter[t])
        head = ranked[0]
        rest = ranked[1:]
        print(f"  preferred? {head:30s}  use_for: {rest}")
    print()

    print("## Fuzzy-similar tags (Levenshtein <= 2, length >= 4)")
    print()
    if not fuzzy_groups:
        print("  (none)")
    for grp in sorted(fuzzy_groups, key=lambda g: -sum(counter[t] for t in g)):
        ranked = sorted(grp, key=lambda t: -counter[t])
        head = ranked[0]
        rest = ranked[1:]
        # Skip groups already covered by exact-key collapse.
        if collapse_key(head) == collapse_key(rest[0]) and len(set(collapse_key(t) for t in grp)) == 1:
            continue
        print(f"  review:    {head:30s}  similar: {rest}")
    print()

    print("## Suggested vocab/tags.yml seed (top 50)")
    print()
    print("# Auto-suggested. Hand-edit to set broader/narrower/related and merge use_for.")
    print()
    for tag, n in counter.most_common(50):
        print(f"{tag}:")
        print(f"  count: {n}")
        # Auto-suggest use_for from collapse-key duplicates.
        siblings = [t for t in groups[collapse_key(tag)] if t != tag]
        if siblings:
            print(f"  use_for: {siblings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
