#!/usr/bin/env python3
"""List topics/courses due for CREW/MUSTIE-style review.

Replaces the bash + jq + sed/awk pipeline in mise.toml. Reads frontmatter
through scripts/_frontmatter.py so the parsing rules stay in sync with
the rest of the toolchain.

References hold immutable bibliographic records (date = publication date),
so they aren't subject to weeding by age. Topics/courses encode our own
work and are weed-eligible.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontmatter import load_frontmatter  # noqa: E402
from _root import content_root  # noqa: E402

ROOT = content_root()

DEFAULT_THRESHOLDS = {
    "memo": 30,
    "in-progress": 90,
    "done": 365,
}
# Treat unknown statuses as if they were in-progress.
FALLBACK_THRESHOLD_KEY = "in-progress"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    # Accept "YYYY-MM-DD" or any ISO-8601 prefix.
    try:
        return datetime.fromisoformat(value.split("T")[0]).date()
    except ValueError:
        return None


def scan(directory: Path, kind: str) -> list[Path]:
    """Return readme paths under topics/<x>/README.md or courses/<x>/README.md."""
    return sorted(directory.glob("*/README.md"))


def evaluate(
    readme: Path,
    *,
    kind: str,
    today: date,
    thresholds: dict[str, int],
) -> dict | None:
    fm = load_frontmatter(readme)
    name = readme.parent.name
    title = fm.get("title") or name
    status_raw = fm.get("status") or "unknown"
    status = status_raw if isinstance(status_raw, str) else str(status_raw)

    updated = parse_date(_as_str(fm.get("updated")))
    created = parse_date(_as_str(fm.get("created")))
    review_at = parse_date(_as_str(fm.get("review_at")))

    base_date = updated or created
    age_days = (today - base_date).days if base_date else -1

    # `review_at` overrides the age-based check.
    reason: str | None = None
    if review_at is not None and review_at <= today:
        reason = "review_at past"
    else:
        threshold = thresholds.get(status, thresholds.get(FALLBACK_THRESHOLD_KEY, 90))
        if age_days >= 0 and age_days >= threshold:
            reason = f"stale {status} ({age_days}d >= {threshold}d)"

    if reason is None:
        return None

    return {
        "kind": kind,
        "name": name,
        "title": title if isinstance(title, str) else str(title),
        "status": status,
        "updated": _as_str(fm.get("updated")) or _as_str(fm.get("created")) or "",
        "age_days": age_days,
        "reason": reason,
        "path": str(readme.relative_to(ROOT)),
    }


def _as_str(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return v[0] if v else None
    return str(v)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--memo", type=int, default=DEFAULT_THRESHOLDS["memo"])
    p.add_argument("--inprog", type=int, default=DEFAULT_THRESHOLDS["in-progress"])
    p.add_argument("--done", type=int, default=DEFAULT_THRESHOLDS["done"])
    p.add_argument("--json", action="store_true", dest="emit_json")
    args = p.parse_args()

    thresholds = {
        "memo": args.memo,
        "in-progress": args.inprog,
        "done": args.done,
    }

    today = date.today()
    results: list[dict] = []
    for kind, sub in (("topic", ROOT / "topics"), ("course", ROOT / "courses")):
        for readme in scan(sub, kind):
            entry = evaluate(readme, kind=kind, today=today, thresholds=thresholds)
            if entry:
                results.append(entry)

    results.sort(key=lambda e: -e["age_days"])

    if args.emit_json:
        print(json.dumps(results, ensure_ascii=False))
        return 0

    print(f"Review-due entries: {len(results)}")
    print()
    print(f"{'KIND':<10} {'AGE':<6} {'STATUS':<12} {'NAME':<50} REASON")
    for e in results:
        kind_u = e["kind"].upper()
        age = f"{e['age_days']}d" if e["age_days"] >= 0 else "?"
        print(f"{kind_u:<10} {age:<6} {e['status']:<12} {e['name']:<50} {e['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
