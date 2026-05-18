#!/usr/bin/env python3
"""Course progress sync CLI for survey-any.

Talks to /api/progress on the deployed Pages site, authenticated with a
shared Bearer token (PROGRESS_TOKEN) compared against the Pages secret of
the same name. Used by mise tasks and Claude Code skills so progress
recorded from a phone browser stays visible to the AI butler on the laptop.

Auth resolution order (first match wins):
  1. environment variable PROGRESS_TOKEN
  2. ~/.config/survey-any/.env  (KEY=VALUE per line)

Base URL: $SURVEY_ANY_URL (default: https://survey-any.pages.dev)

Exit codes:
  0  success
  1  user error (bad arguments, missing confirmation, HTTP 4xx other than auth)
  2  authentication error (HTTP 401/403, missing credentials)
  3  network error (DNS, connection refused, malformed JSON)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_URL = "https://survey-any.pages.dev"
CONFIG_PATH = Path.home() / ".config" / "survey-any" / ".env"

EXIT_OK = 0
EXIT_USER = 1
EXIT_AUTH = 2
EXIT_NETWORK = 3


def LoadEnvFile(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def ResolveAuthHeaders() -> dict[str, str]:
    file_env = LoadEnvFile(CONFIG_PATH)
    token = os.environ.get("PROGRESS_TOKEN") or file_env.get("PROGRESS_TOKEN")
    if not token:
        print(
            f"error: PROGRESS_TOKEN not set (env or {CONFIG_PATH})",
            file=sys.stderr,
        )
        sys.exit(EXIT_AUTH)
    return {"Authorization": f"Bearer {token}"}


def ResolveBaseUrl() -> str:
    return os.environ.get("SURVEY_ANY_URL", DEFAULT_URL).rstrip("/")


def CallApi(method: str, path: str, body: Any | None = None) -> Any:
    url = ResolveBaseUrl() + path
    headers = {"accept": "application/json", **ResolveAuthHeaders()}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    req = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(req) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as e:
        message = e.read().decode("utf-8", errors="replace")
        if e.code in (401, 403):
            print(f"auth error: HTTP {e.code} {message}", file=sys.stderr)
            sys.exit(EXIT_AUTH)
        print(f"http error {e.code}: {message}", file=sys.stderr)
        sys.exit(EXIT_USER)
    except error.URLError as e:
        print(f"network error: {e.reason}", file=sys.stderr)
        sys.exit(EXIT_NETWORK)
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        print(f"invalid JSON in response: {e}: {payload!r}", file=sys.stderr)
        sys.exit(EXIT_NETWORK)


def ParseBool(value: str) -> bool:
    lowered = value.lower()
    if lowered in ("true", "1", "yes", "y", "t", "done"):
        return True
    if lowered in ("false", "0", "no", "n", "f", "undone"):
        return False
    raise argparse.ArgumentTypeError(f"expected boolean (true/false), got {value!r}")


def CommandList(args: argparse.Namespace) -> None:
    data = CallApi("GET", "/api/progress")
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    courses = (data or {}).get("courses", {}) or {}
    if not courses:
        print("(no progress recorded)")
        return
    for course_id in sorted(courses):
        lesson_ids = sorted(courses[course_id])
        print(f"{course_id}  ({len(lesson_ids)} lessons completed)")
        for lesson_id in lesson_ids:
            print(f"  - {lesson_id}")


def CommandGet(args: argparse.Namespace) -> None:
    encoded = parse.quote(args.course, safe="")
    data = CallApi("GET", f"/api/progress/{encoded}")
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    lessons = sorted(((data or {}).get("lessons") or {}).keys())
    print(f"{args.course}  ({len(lessons)} lessons completed)")
    for lesson_id in lessons:
        print(f"  - {lesson_id}")


def CommandSet(args: argparse.Namespace) -> None:
    course = parse.quote(args.course, safe="")
    lesson = parse.quote(args.lesson, safe="")
    data = CallApi(
        "PUT",
        f"/api/progress/{course}/{lesson}",
        {"completed": args.completed},
    )
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    state = "completed" if args.completed else "uncompleted"
    print(f"{args.course}/{args.lesson} -> {state}")


def CommandReset(args: argparse.Namespace) -> None:
    if not args.yes:
        print(f"refusing to reset {args.course} without --yes", file=sys.stderr)
        sys.exit(EXIT_USER)
    encoded = parse.quote(args.course, safe="")
    data = CallApi("DELETE", f"/api/progress/{encoded}")
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    deleted = (data or {}).get("deleted", 0)
    print(f"{args.course}: deleted {deleted} lesson rows")


def CommandToken(_args: argparse.Namespace) -> None:
    import secrets

    print(secrets.token_hex(32))


def BuildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync course progress with the survey-any API",
    )
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list completed lessons across all courses")

    get_parser = sub.add_parser("get", help="get progress for one course")
    get_parser.add_argument("course")

    set_parser = sub.add_parser("set", help="mark a lesson completed or uncompleted")
    set_parser.add_argument("course")
    set_parser.add_argument("lesson")
    set_parser.add_argument("completed", type=ParseBool)

    reset_parser = sub.add_parser("reset", help="reset all lessons in a course")
    reset_parser.add_argument("course")
    reset_parser.add_argument("--yes", action="store_true", help="confirm")

    sub.add_parser("token", help="print a fresh random PROGRESS_TOKEN (32 bytes hex)")

    return parser


HANDLERS = {
    "list": CommandList,
    "get": CommandGet,
    "set": CommandSet,
    "reset": CommandReset,
    "token": CommandToken,
}


def main() -> None:
    args = BuildParser().parse_args()
    HANDLERS[args.command](args)


if __name__ == "__main__":
    main()
