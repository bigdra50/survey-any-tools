#!/usr/bin/env python3
"""Dispatch for `mise run new <kind> <name>` family.

Replaces the previous flat new-{report,notebook,reference,paper-reference,
course,lesson,inbox} mise tasks. Kind selects the template and destination.

Kinds:
  memo       topics/<name>/README.md (memo template, default for topics)
  report     topics/<name>/README.md (report template)
  notebook   topics/<name>/analysis.ipynb (Jupyter notebook template)
  reference  references/<name>.md (web/book reference template)
  paper      references/<name>.md (paper 6-item survey template)
  course     courses/<name>/README.md (course overview template)
  lesson     courses/<course>/<NN>-<slug>.md (auto-numbered lesson template)
  inbox      inbox/<timestamp>-<slug>.md (external capture, optional source)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontmatter import update_fields  # noqa: E402
from _root import content_root  # noqa: E402

REPO_ROOT = content_root()
TEMPLATES = REPO_ROOT / "templates"

# reference/paper frontmatter fields that --batch entries and single-shot
# flags (--title/--url/--type/--author/--organization) are allowed to set.
REFERENCE_OVERRIDE_FIELDS = ("title", "url", "type", "author", "organization", "date")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def render_template(template_path: Path, replacements: dict[str, str]) -> str:
    text = template_path.read_text()
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def write_new(path: Path, content: str) -> None:
    if path.exists():
        print(f"Error: {path} already exists", file=sys.stderr)
        sys.exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"Created {path.relative_to(REPO_ROOT)}")


def cmd_topic(name: str, template_filename: str) -> None:
    target = REPO_ROOT / "topics" / name / "README.md"
    if target.parent.exists():
        print(f"Error: {target.parent.relative_to(REPO_ROOT)} already exists", file=sys.stderr)
        sys.exit(1)
    content = render_template(TEMPLATES / template_filename, {"YYYY-MM-DD": now_iso()})
    write_new(target, content)


def cmd_notebook(name: str) -> None:
    target = REPO_ROOT / "topics" / name / "analysis.ipynb"
    if target.parent.exists():
        print(f"Error: {target.parent.relative_to(REPO_ROOT)} already exists", file=sys.stderr)
        sys.exit(1)
    content = render_template(TEMPLATES / "notebook.ipynb", {"YYYY-MM-DD": now_iso()})
    write_new(target, content)


def cmd_reference(
    name: str,
    template_filename: str,
    *,
    title: str | None = None,
    url: str | None = None,
    type_: str | None = None,
    author: str | None = None,
    organization: str | None = None,
) -> None:
    target = REPO_ROOT / "references" / f"{name}.md"
    content = render_template(TEMPLATES / template_filename, {"YYYY-MM-DD": now_date()})
    overrides = {
        "title": title,
        "url": url,
        "type": type_,
        "author": author,
        "organization": organization,
    }
    updates = {k: v for k, v in overrides.items() if v is not None}
    if updates:
        content = update_fields(content, updates=updates)
    write_new(target, content)


def cmd_reference_batch(template_filename: str, batch_path: Path) -> None:
    """Create multiple references from a JSON array file.

    Each entry: {name, title, url, type?, author?, organization?, date?, body?}.
    Entries whose target file already exists are skipped with a warning;
    the rest of the batch still runs.
    """
    try:
        raw = json.loads(batch_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: failed to read batch file {batch_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(raw, list):
        print("Error: --batch file must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    created = 0
    skipped = 0
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("name"):
            print(f"Warning: skipping entry without 'name': {entry!r}", file=sys.stderr)
            skipped += 1
            continue

        name = entry["name"]
        target = REPO_ROOT / "references" / f"{name}.md"
        if target.exists():
            print(f"Warning: {target.relative_to(REPO_ROOT)} already exists, skipping", file=sys.stderr)
            skipped += 1
            continue

        content = render_template(TEMPLATES / template_filename, {"YYYY-MM-DD": now_date()})
        updates = {
            field_name: str(entry[field_name])
            for field_name in REFERENCE_OVERRIDE_FIELDS
            if entry.get(field_name) is not None
        }
        if updates:
            content = update_fields(content, updates=updates)

        body = entry.get("body")
        if body:
            content = content.rstrip("\n") + "\n\n" + str(body).rstrip("\n") + "\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        print(f"Created {target.relative_to(REPO_ROOT)}")
        created += 1

    print(f"Batch complete: {created} created, {skipped} skipped", file=sys.stderr)


def cmd_course(name: str) -> None:
    target = REPO_ROOT / "courses" / name / "README.md"
    if target.parent.exists():
        print(f"Error: {target.parent.relative_to(REPO_ROOT)} already exists", file=sys.stderr)
        sys.exit(1)
    content = render_template(TEMPLATES / "course.md", {"YYYY-MM-DD": now_iso()})
    write_new(target, content)


def cmd_lesson(course: str, slug: str) -> None:
    course_dir = REPO_ROOT / "courses" / course
    if not course_dir.is_dir():
        print(
            f"Error: {course_dir.relative_to(REPO_ROOT)} does not exist. "
            f"Run 'mise run new course {course}' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    pattern = re.compile(r"^(\d{2})-.+\.md$")
    existing = [
        int(m.group(1))
        for path in course_dir.iterdir()
        if path.is_file() and (m := pattern.match(path.name))
    ]
    next_order = max(existing, default=0) + 1
    target = course_dir / f"{next_order:02d}-{slug}.md"

    template = (TEMPLATES / "lesson.md").read_text()
    content = template.replace("order: 0", f"order: {next_order}", 1)
    write_new(target, content)


def cmd_inbox(slug: str, source: str | None) -> None:
    inbox_dir = REPO_ROOT / "inbox"
    inbox_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    target = inbox_dir / f"{timestamp}-{slug}.md"
    captured = now_iso()
    source_path = source if source is not None else str(Path.cwd())
    content = render_template(
        TEMPLATES / "inbox.md",
        {"CAPTURED_AT": captured, "SOURCE_PATH": source_path},
    )
    write_new(target, content)


def _dispatch_reference(args: argparse.Namespace, template_filename: str) -> None:
    if args.batch:
        cmd_reference_batch(template_filename, Path(args.batch))
        return
    if not args.name:
        print("Error: 'name' is required unless --batch is given", file=sys.stderr)
        sys.exit(1)
    cmd_reference(
        args.name,
        template_filename,
        title=args.title,
        url=args.url,
        type_=args.type,
        author=args.author,
        organization=args.organization,
    )


KIND_HANDLERS = {
    "memo": lambda args: cmd_topic(args.name, "memo.md"),
    "report": lambda args: cmd_topic(args.name, "report.md"),
    "notebook": lambda args: cmd_notebook(args.name),
    "reference": lambda args: _dispatch_reference(args, "reference.md"),
    "paper": lambda args: _dispatch_reference(args, "paper-reference.md"),
    "course": lambda args: cmd_course(args.name),
    "lesson": lambda args: cmd_lesson(args.course, args.slug),
    "inbox": lambda args: cmd_inbox(args.slug, args.source),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new",
        description="Create a new survey artifact (topic / reference / course / lesson / inbox).",
    )
    sub = parser.add_subparsers(dest="kind", required=True)

    for kind in ("memo", "report", "notebook", "course"):
        p = sub.add_parser(kind, help=f"Create a {kind}")
        p.add_argument("name")

    for kind in ("reference", "paper"):
        p = sub.add_parser(kind, help=f"Create a {kind}")
        p.add_argument("name", nargs="?", default=None, help="Not needed with --batch")
        p.add_argument("--title")
        p.add_argument("--url")
        p.add_argument("--type")
        p.add_argument("--author")
        p.add_argument("--organization")
        p.add_argument(
            "--batch",
            metavar="JSON_FILE",
            help="Create multiple references from a JSON array file "
            "([{name, title, url, type?, author?, organization?, date?, body?}, ...])",
        )

    p_lesson = sub.add_parser("lesson", help="Create a lesson inside a course (auto-numbered)")
    p_lesson.add_argument("course")
    p_lesson.add_argument("slug")

    p_inbox = sub.add_parser("inbox", help="Create an inbox capture")
    p_inbox.add_argument("slug")
    p_inbox.add_argument("source", nargs="?", default=None)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    KIND_HANDLERS[args.kind](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
