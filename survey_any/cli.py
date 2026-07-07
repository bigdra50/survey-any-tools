"""survey-any CLI: dispatch ``survey-any <command> [args...]`` to command modules.

Each subcommand maps to a module under ``survey_any.commands`` (module name is the
subcommand name with hyphens replaced by underscores). Every command module exposes
``def main(argv: list[str] | None = None) -> int | None`` and is imported lazily so
that optional dependencies (e.g. the ``dense`` embedding extras) do not block
unrelated subcommands from starting.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Final

COMMANDS: Final[tuple[str, ...]] = (
    "doctor",
    "new",
    "backlinks",
    "archive",
    "trace",
    "recall",
    "review-due",
    "link-papers",
    "tags-suggest",
    "tags-validate",
    "build-index",
    "search-fulltext",
    "build-embeddings",
    "suggest-related",
    "check-schema",
    "check-tokenizer-drift",
    "progress",
    "sync-content",
    "trace-footer",
    "fix-currency",
)


def _print_help(stream=sys.stdout) -> None:
    print("usage: survey-any <command> [args...]\n\ncommands:", file=stream)
    for name in sorted(COMMANDS):
        print(f"  {name}", file=stream)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return 0
    name, rest = args[0], args[1:]
    if name not in COMMANDS:
        print(f"survey-any: unknown command {name!r}", file=sys.stderr)
        _print_help(sys.stderr)
        return 2
    module = import_module(f"survey_any.commands.{name.replace('-', '_')}")
    rc = module.main(rest)
    return 0 if rc is None else rc


if __name__ == "__main__":
    sys.exit(main())
