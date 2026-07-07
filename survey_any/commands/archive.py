#!/usr/bin/env python3
"""Move a topic to archive/<YYYY>/<topic>/ with redirect: frontmatter.

ALA / Texas State Library CREW manual の closed stack 移管に対応する一人運用版。
物理削除しない。後継 topic があれば redirect: で明示する。

Usage:
  python3 -m survey_any archive <topic-name> [--reason MUSTIE-letter] [--successor topic]

Reason letters: M U S T I E (see CLAUDE.md MUSTIE-PKB).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from survey_any._frontmatter import update_fields
from survey_any._root import content_root

ROOT = content_root()
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("topic", help="Topic name under topics/")
    p.add_argument("--reason", choices=list(REASONS), help="MUSTIE-PKB reason letter")
    p.add_argument("--successor", help="Successor topic name (sets redirect:)")
    p.add_argument("--year", type=int, default=date.today().year, help="Archive year folder")
    p.add_argument("--dry-run", action="store_true", help="Show planned move only")
    return p.parse_args(argv)


def update_frontmatter(readme: Path, *, reason: str | None, successor: str | None) -> None:
    """Stamp archive metadata onto an archived topic's README frontmatter.

    Forces ``status: archived`` and ``archived_at: <today>``. Optional
    ``archive_reason`` / ``redirect`` are written when ``reason`` /
    ``successor`` are provided; pre-existing values for those keys are
    preserved otherwise (matching the legacy line-level behaviour).
    """
    text = readme.read_text(encoding="utf-8")
    if not re.match(r"^---\n", text):
        print(f"warn: no frontmatter in {readme}; appending markers", file=sys.stderr)

    today = date.today().isoformat()
    updates: dict[str, str] = {
        "status": "archived",
        "archived_at": today,
    }
    if reason:
        updates["archive_reason"] = f"{reason} ({REASONS[reason]})"
    if successor:
        updates["redirect"] = successor

    new_text = update_fields(text, updates=updates)
    readme.write_text(new_text, encoding="utf-8")


def append_replaces(successor_readme: Path, archived_topic: str) -> bool:
    """Add ``archived_topic`` to the successor's frontmatter ``replaces:`` list.

    Returns True if the file was modified. Existing inline / block list
    style is preserved; a new ``replaces`` key is appended in block style
    when missing. No-op when the entry is already present.
    """
    text = successor_readme.read_text(encoding="utf-8")
    if not re.match(r"^---\n", text):
        return False

    new_text = update_fields(text, list_appends={"replaces": [archived_topic]})
    if new_text == text:
        return False
    successor_readme.write_text(new_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

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

    # Sync `replaces:` on the successor topic so the back-pointer survives
    # alongside the archived `redirect:`.
    if args.successor:
        succ_readme = (topics_dir / args.successor / "README.md").resolve()
        if succ_readme.is_file() and succ_readme.is_relative_to(topics_dir):
            if append_replaces(succ_readme, args.topic):
                print(f"updated replaces in {succ_readme}")

    # Regenerate citation back-pointers so references no longer link to the
    # archived path. backlinks.py only scans topics/, so any references that
    # used to cite the archived topic will lose their stale link automatically.
    try:
        subprocess.run(
            [sys.executable, "-m", "survey_any", "backlinks"],
            check=True,
            cwd=ROOT,
            env={**os.environ, "SURVEY_ANY_ROOT": str(ROOT)},
        )
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"warn: backlinks regeneration failed: {e}", file=sys.stderr)

    print()
    print("Archived. Run `mise run index` to refresh INDEX.md (it skips archive/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
