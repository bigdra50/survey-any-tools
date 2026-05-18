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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


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


def cmd_reference(name: str, template_filename: str) -> None:
    target = REPO_ROOT / "references" / f"{name}.md"
    content = render_template(TEMPLATES / template_filename, {"YYYY-MM-DD": now_iso()})
    write_new(target, content)


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


KIND_HANDLERS = {
    "memo": lambda args: cmd_topic(args.name, "memo.md"),
    "report": lambda args: cmd_topic(args.name, "report.md"),
    "notebook": lambda args: cmd_notebook(args.name),
    "reference": lambda args: cmd_reference(args.name, "reference.md"),
    "paper": lambda args: cmd_reference(args.name, "paper-reference.md"),
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

    for kind in ("memo", "report", "notebook", "reference", "paper", "course"):
        p = sub.add_parser(kind, help=f"Create a {kind}")
        p.add_argument("name")

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
