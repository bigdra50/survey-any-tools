#!/usr/bin/env python3
"""Move a topic to archive/<YYYY>/<topic>/ with redirect: frontmatter.

ALA / Texas State Library CREW manual の closed stack 移管に対応する一人運用版。
物理削除しない。後継 topic があれば redirect: で明示する。

Usage:
  python3 scripts/archive.py <topic-name> [--reason MUSTIE-letter] [--successor topic]

Reason letters: M U S T I E (see CLAUDE.md MUSTIE-PKB).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ROOT / "topics"
ARCHIVE = ROOT / "archive"

REASONS = {
    "M": "Misleading",
    "U": "Ugly",
    "S": "Superseded",
    "T": "Trivial",
    "I": "Irrelevant",
    "E": "Elsewhere",
}

# Conservative slug for topic / successor names. Matches CLAUDE.md naming rule
# (no Japanese, no spaces, hyphens allowed).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("topic", help="Topic name under topics/")
    p.add_argument("--reason", choices=list(REASONS), help="MUSTIE-PKB reason letter")
    p.add_argument("--successor", help="Successor topic name (sets redirect:)")
    p.add_argument("--year", type=int, default=date.today().year, help="Archive year folder")
    p.add_argument("--dry-run", action="store_true", help="Show planned move only")
    return p.parse_args()


def update_frontmatter(readme: Path, *, reason: str | None, successor: str | None) -> None:
    text = readme.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---)", text, re.S)
    if not m:
        print(f"warn: no frontmatter in {readme}; appending markers", file=sys.stderr)
        text = "---\n\n---\n" + text
        m = re.match(r"^(---\n)(.*?)(\n---)", text, re.S)
        if not m:
            raise RuntimeError(f"failed to insert frontmatter markers into {readme}")

    head, body, tail = m.group(1), m.group(2), m.group(3)
    today = date.today().isoformat()

    # Force status to archived; preserve other fields.
    body_lines = body.splitlines()
    out: list[str] = []
    seen = {"status": False, "archived_at": False, "archive_reason": False, "redirect": False}
    for line in body_lines:
        if line.startswith("status:"):
            out.append(f"status: archived")
            seen["status"] = True
        elif line.startswith("archived_at:"):
            out.append(f"archived_at: {today}")
            seen["archived_at"] = True
        elif line.startswith("archive_reason:"):
            seen["archive_reason"] = True
            if reason:
                out.append(f"archive_reason: {reason} ({REASONS[reason]})")
            else:
                out.append(line)
        elif line.startswith("redirect:"):
            seen["redirect"] = True
            if successor:
                out.append(f"redirect: {successor}")
            else:
                out.append(line)
        else:
            out.append(line)

    if not seen["status"]:
        out.append("status: archived")
    if not seen["archived_at"]:
        out.append(f"archived_at: {today}")
    if reason and not seen["archive_reason"]:
        out.append(f"archive_reason: {reason} ({REASONS[reason]})")
    if successor and not seen["redirect"]:
        out.append(f"redirect: {successor}")

    new_body = "\n".join(out)
    new_text = head + new_body + tail + text[m.end():]
    readme.write_text(new_text, encoding="utf-8")


def main() -> int:
    args = parse_args()

    if not SLUG_RE.match(args.topic):
        print(f"error: invalid topic name: {args.topic!r}", file=sys.stderr)
        return 2
    if args.successor is not None and not SLUG_RE.match(args.successor):
        print(f"error: invalid successor name: {args.successor!r}", file=sys.stderr)
        return 2

    topics_dir = TOPICS.resolve()
    archive_root = ARCHIVE.resolve()

    src = (topics_dir / args.topic).resolve()
    if not src.is_relative_to(topics_dir) or not src.is_dir():
        print(f"error: topic '{args.topic}' not found at {src}", file=sys.stderr)
        return 1

    dest_year = archive_root / str(args.year)
    dest = (dest_year / args.topic).resolve()
    if not dest.is_relative_to(archive_root):
        print(f"error: archive destination escapes archive/: {dest}", file=sys.stderr)
        return 2
    if dest.exists():
        print(f"error: archive destination already exists: {dest}", file=sys.stderr)
        return 1

    if args.successor:
        succ = (topics_dir / args.successor).resolve()
        if not succ.is_relative_to(topics_dir) or not succ.is_dir():
            print(
                f"warn: successor topic '{args.successor}' does not exist (yet)",
                file=sys.stderr,
            )

    print(f"src:  {src}")
    print(f"dest: {dest}")
    if args.reason:
        print(f"reason: {args.reason} ({REASONS[args.reason]})")
    if args.successor:
        print(f"successor: {args.successor}")

    if args.dry_run:
        print("(dry run — no changes)")
        return 0

    dest_year.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    readme = dest / "README.md"
    if readme.exists():
        update_frontmatter(readme, reason=args.reason, successor=args.successor)
        print(f"updated frontmatter: {readme}")
    else:
        print(f"warn: no README.md at {readme}; frontmatter not updated", file=sys.stderr)

    print()
    print(f"Archived. Run `mise run index` to refresh INDEX.md (it skips archive/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
