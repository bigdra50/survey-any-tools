#!/usr/bin/env python3
"""Cross-cutting consistency checker for the survey-any knowledge base.

Aggregates the static rules that were previously hand-checked (or buried in
skill prose) into one `mise run doctor` gate. Checks:

  sources    topics `sources:` entries resolve to references/*.md   [ERROR]
  related    `related:` bidirectionality + missing targets          [WARN]
  relations  typed `relations:` targets exist, type in vocab        [ERROR]
  links      relative .md links in bodies resolve                   [ERROR]
  dates      references `date:`/`retrieved:` are YYYY-MM-DD         [WARN]
  synthesis  status: done without scent / low maturity (R5)         [WARN/INFO]
  strength   references without `strength:` (legacy backlog)        [INFO]
  lessons    lesson objectives / 理解度チェック section present      [WARN]
  currency   unescaped `$<digit>` outside code (KaTeX misparse)     [WARN]
  skills     skill/agent prose references defined mise tasks        [ERROR]
  tokenizer  _tokenizer.py and tokenizer.ts tokenize identically    [ERROR]
  external   run tags-validate.py --strict + check-schema-drift.py

Usage:
  python3 -m survey_any doctor                 # all checks, human-readable
  python3 -m survey_any doctor --json          # machine-readable output
  python3 -m survey_any doctor --only links,dates
  python3 -m survey_any doctor --list          # list check ids

Exit codes:
  0 — no ERROR findings (WARN/INFO allowed)
  1 — at least one ERROR finding (CI gate)
  2 — usage / internal error
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final

from survey_any._frontmatter import get_list, parse_frontmatter, split_frontmatter
from survey_any._schema import REFERENCE_STRENGTHS, TOPIC_MATURITIES, TOPIC_RELATION_TYPES
from survey_any._root import content_root

ROOT: Final[Path] = content_root()
TOPICS_DIR: Final[Path] = ROOT / "topics"
REFS_DIR: Final[Path] = ROOT / "references"
COURSES_DIR: Final[Path] = ROOT / "courses"
ARCHIVE_DIR: Final[Path] = ROOT / "archive"
RELATION_VOCAB: Final[Path] = ROOT / "vocab" / "relation-types.yml"

SEVERITIES: Final[tuple[str, ...]] = ("ERROR", "WARN", "INFO")
DISPLAY_CAP: Final[int] = 15

_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MD_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)(```+|~~~+)")
_CODE_SPAN_RE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]*`")
_CURRENCY_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\\)\$(?=\d)")
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s")
_CHECK_SECTION_RE: Final[re.Pattern[str]] = re.compile(r"^#{2,3}\s*理解度チェック")
_YMD_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PARTIAL_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}(-\d{2})?$")
_MISE_RUN_RE: Final[re.Pattern[str]] = re.compile(r"mise\s+(?:-C\s+\S+\s+)?run\s+([a-z][a-z0-9-]*)")
_DOCTOR_IGNORE_MARK: Final[str] = "doctor: ignore-next-line"

# Prompt files whose prose invokes mise tasks; both pre- and post-apm layouts
# are listed so the check survives the skills/ -> .apm/skills/ migration.
SKILL_PROSE_GLOBS: Final[tuple[str, ...]] = (
    "skills/*/SKILL.md",
    ".apm/skills/*/SKILL.md",
    ".claude/skills/*/SKILL.md",
    ".claude/agents/*.md",
)


@dataclass(frozen=True)
class Finding:
    """One doctor finding, anchored to a repo-relative path."""

    check: str
    severity: str  # ERROR | WARN | INFO
    path: str
    message: str
    line: int | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class Document:
    """A markdown document split into frontmatter and body."""

    path: Path
    fm: dict[str, str | list[str]]
    fm_text: str | None
    body: str

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(ROOT))

    def body_line_offset(self) -> int:
        """1-based file line number of the first body line, minus one."""
        if self.fm_text is None:
            return 0
        return self.fm_text.count("\n") + 3  # `---` + fm lines + `---`


@dataclass(frozen=True)
class Repo:
    """Loaded repository contents shared across checks (read once)."""

    topics: dict[str, Document]  # topic dir name -> doc
    references: dict[str, Document]  # reference stem -> doc
    lessons: list[Document]
    archived_topics: frozenset[str]


def _load_document(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    fm_text, body = split_frontmatter(text)
    return Document(path=path, fm=parse_frontmatter(text), fm_text=fm_text, body=body)


def load_repo() -> Repo:
    """Read all topics / references / lessons once. Side effect: file IO."""
    topics = {p.parent.name: _load_document(p) for p in sorted(TOPICS_DIR.glob("*/README.md"))}
    references = {p.stem: _load_document(p) for p in sorted(REFS_DIR.glob("*.md"))}
    lessons = [_load_document(p) for p in sorted(COURSES_DIR.glob("*/[0-9][0-9]-*.md"))]
    archived = frozenset(p.parent.name for p in ARCHIVE_DIR.glob("*/*/README.md"))
    return Repo(topics=topics, references=references, lessons=lessons, archived_topics=archived)


# --------------------------------------------------------------------------- #
# Shared helpers (pure functions)
# --------------------------------------------------------------------------- #


def iter_body_lines_outside_fences(body: str) -> list[tuple[int, str]]:
    """Return (0-based body line index, line) pairs outside fenced code blocks."""
    out: list[tuple[int, str]] = []
    in_fence = False
    fence_char: str | None = None
    for i, line in enumerate(body.splitlines()):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(2)[0]
            if not in_fence:
                in_fence, fence_char = True, marker
            elif marker == fence_char:
                in_fence, fence_char = False, None
            continue
        if not in_fence:
            out.append((i, line))
    return out


def load_relation_vocab() -> frozenset[str]:
    """Top-level keys of vocab/relation-types.yml; fall back to _schema constants."""
    if not RELATION_VOCAB.exists():
        return TOPIC_RELATION_TYPES
    types: set[str] = set()
    for raw in RELATION_VOCAB.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            continue
        if line.endswith(":"):
            types.add(line[:-1].strip())
    return frozenset(types) if types else TOPIC_RELATION_TYPES


def parse_relations_block(fm_text: str | None) -> tuple[list[dict[str, str]], list[str]]:
    """Parse the nested `relations:` block that _frontmatter's flat parser flattens.

    Args:
        fm_text: Raw frontmatter text (between the `---` markers), or None.

    Returns:
        (items, problems) where items are {to, type, note?} dicts and problems
        are human-readable structural complaints (e.g. item without `to:`).
    """
    if fm_text is None:
        return [], []
    lines = fm_text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^relations:\s*(\[\s*\])?\s*$", line):
            start = i
            break
    if start is None:
        return [], []

    items: list[dict[str, str]] = []
    problems: list[str] = []
    current: dict[str, str] | None = None
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break  # next top-level key
        if not line.strip():
            continue
        m_item = re.match(r"^\s+-\s+(.*)$", line)
        m_attr = re.match(r"^\s+([A-Za-z_]+):\s*(.*)$", line)
        if m_item:
            current = {}
            items.append(current)
            rest = m_item.group(1).strip()
            if ":" in rest:
                k, _, v = rest.partition(":")
                current[k.strip()] = v.strip().strip("\"'")
            elif rest:
                problems.append(f"relations item is a bare scalar {rest!r} (expected `- to: <topic>` mapping)")
        elif m_attr and current is not None:
            current[m_attr.group(1)] = m_attr.group(2).strip().strip("\"'")
        else:
            problems.append(f"unparsable relations line: {line.strip()!r}")
    return items, problems


# --------------------------------------------------------------------------- #
# Checks — each returns list[Finding]
# --------------------------------------------------------------------------- #


def check_sources(repo: Repo) -> list[Finding]:
    """topics `sources:` entries must resolve to references/*.md stems (or be URLs)."""
    findings: list[Finding] = []
    for doc in repo.topics.values():
        for src in get_list(doc.fm, "sources"):
            if src.startswith(("http://", "https://")) or src in repo.references:
                continue
            if src.endswith(".md") and src[:-3] in repo.references:
                findings.append(
                    Finding(
                        check="sources",
                        severity="ERROR",
                        path=doc.rel,
                        message=f"sources entry '{src}' has a .md extension (backlinks/viewer expect the stem)",
                        suggestion=f"rename entry to '{src[:-3]}'",
                    )
                )
            elif _SLUG_RE.match(src):
                findings.append(
                    Finding(
                        check="sources",
                        severity="ERROR",
                        path=doc.rel,
                        message=f"sources entry '{src}' does not exist in references/",
                        suggestion="create the reference (`mise run new reference <name>`) or fix the name",
                    )
                )
            else:
                findings.append(
                    Finding(
                        check="sources",
                        severity="WARN",
                        path=doc.rel,
                        message=f"free-form sources entry '{src}' (ignored by backlinks/viewer)",
                        suggestion="promote to a references/*.md entry or move the citation into the body",
                    )
                )
    return findings


def check_related(repo: Repo) -> list[Finding]:
    """`related:` targets must exist; symmetric entries are suggested when one-way."""
    findings: list[Finding] = []
    for name, doc in repo.topics.items():
        for target in get_list(doc.fm, "related"):
            if target not in repo.topics:
                if target in repo.archived_topics:
                    findings.append(
                        Finding(
                            check="related",
                            severity="INFO",
                            path=doc.rel,
                            message=f"related target '{target}' is archived",
                            suggestion="drop the entry or point to its redirect target",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            check="related",
                            severity="WARN",
                            path=doc.rel,
                            message=f"related target '{target}' does not exist in topics/",
                        )
                    )
                continue
            if name not in get_list(repo.topics[target].fm, "related"):
                findings.append(
                    Finding(
                        check="related",
                        severity="WARN",
                        path=doc.rel,
                        message=f"related '{target}' is one-way",
                        suggestion=f"add '{name}' to related: in topics/{target}/README.md",
                    )
                )
    return findings


def check_relations(repo: Repo) -> list[Finding]:
    """Typed `relations:` items: `to` must exist, `type` must be in the vocab."""
    vocab = load_relation_vocab()
    findings: list[Finding] = []
    for doc in repo.topics.values():
        if "relations" not in doc.fm:
            continue
        items, problems = parse_relations_block(doc.fm_text)
        for problem in problems:
            findings.append(Finding(check="relations", severity="ERROR", path=doc.rel, message=problem))
        for i, item in enumerate(items):
            to = item.get("to", "")
            rel_type = item.get("type", "")
            if not to:
                findings.append(
                    Finding(check="relations", severity="ERROR", path=doc.rel, message=f"relations[{i}]: missing to:")
                )
            elif to not in repo.topics:
                if to in repo.archived_topics:
                    findings.append(
                        Finding(
                            check="relations",
                            severity="INFO",
                            path=doc.rel,
                            message=f"relations[{i}].to '{to}' is archived",
                            suggestion="drop the entry or point to its redirect target",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            check="relations",
                            severity="ERROR",
                            path=doc.rel,
                            message=f"relations[{i}].to '{to}' does not exist in topics/",
                        )
                    )
            if not rel_type:
                findings.append(
                    Finding(check="relations", severity="ERROR", path=doc.rel, message=f"relations[{i}]: missing type:")
                )
            elif rel_type not in vocab:
                findings.append(
                    Finding(
                        check="relations",
                        severity="ERROR",
                        path=doc.rel,
                        message=f"relations[{i}].type '{rel_type}' not in vocab/relation-types.yml {sorted(vocab)}",
                    )
                )
            if rel_type == "contrasts" and not item.get("note"):
                findings.append(
                    Finding(
                        check="relations",
                        severity="WARN",
                        path=doc.rel,
                        message=f"relations[{i}] (contrasts -> '{to}') has no note:",
                        suggestion="contrasts requires a note recording the contextual difference",
                    )
                )
    return findings


def check_links(repo: Repo) -> list[Finding]:
    """Relative .md links in topic / reference bodies must resolve on disk."""
    findings: list[Finding] = []
    docs = list(repo.topics.values()) + list(repo.references.values())
    for doc in docs:
        offset = doc.body_line_offset()
        for i, line in iter_body_lines_outside_fences(doc.body):
            for target in _MD_LINK_RE.findall(_CODE_SPAN_RE.sub("", line)):
                clean = target.split("#")[0]
                if not clean or clean.startswith(("http://", "https://", "mailto:", "/")):
                    continue
                if not clean.endswith(".md"):
                    continue
                if not (doc.path.parent / clean).exists():
                    findings.append(
                        Finding(
                            check="links",
                            severity="ERROR",
                            path=doc.rel,
                            line=offset + i + 1,
                            message=f"broken relative link '{target}'",
                        )
                    )
    return findings


def _date_finding(doc: Document, key: str, value: str) -> Finding | None:
    """Classify one raw date scalar; return a Finding or None when acceptable."""
    if not value or value.lower() == "null":
        return None
    if _YMD_RE.match(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return None
        except ValueError:
            return Finding(
                check="dates", severity="WARN", path=doc.rel, message=f"{key}: '{value}' is not a valid calendar date"
            )
    if _PARTIAL_DATE_RE.match(value):
        return None  # YYYY / YYYY-MM partial publication dates are accepted by the schema
    if "T" in value:
        suggestion = None
        try:
            suggestion = f"normalize to {key}: {value[:10]}" if _YMD_RE.match(value[:10]) else None
        except ValueError:
            suggestion = None
        return Finding(
            check="dates",
            severity="WARN",
            path=doc.rel,
            message=f"{key}: '{value}' is an ISO datetime (repo convention is YYYY-MM-DD)",
            suggestion=suggestion,
        )
    return Finding(check="dates", severity="WARN", path=doc.rel, message=f"{key}: unrecognized date format '{value}'")


def check_dates(repo: Repo) -> list[Finding]:
    """references `date:` / `retrieved:` should be YYYY-MM-DD (YYYY / YYYY-MM tolerated)."""
    findings: list[Finding] = []
    for doc in repo.references.values():
        for key in ("date", "retrieved"):
            value = doc.fm.get(key)
            if isinstance(value, str):
                finding = _date_finding(doc, key, value.strip())
                if finding:
                    findings.append(finding)
    return findings


def check_synthesis(repo: Repo) -> list[Finding]:
    """R5 signals: `status: done` without scent [WARN] / with low maturity [INFO]."""
    findings: list[Finding] = []
    for doc in repo.topics.values():
        maturity = doc.fm.get("maturity")
        if isinstance(maturity, str) and maturity and maturity not in TOPIC_MATURITIES:
            findings.append(
                Finding(
                    check="synthesis",
                    severity="ERROR",
                    path=doc.rel,
                    message=f"maturity '{maturity}' not in {sorted(TOPIC_MATURITIES)}",
                )
            )
            continue
        if doc.fm.get("status") != "done":
            continue
        if "scent" not in doc.fm:
            findings.append(
                Finding(
                    check="synthesis",
                    severity="WARN",
                    path=doc.rel,
                    message="status: done but scent: is missing",
                    suggestion="add scent: (one_line / key_terms) so readers can judge cost/value before opening",
                )
            )
        if not maturity or maturity == "collected":
            label = maturity or "missing"
            findings.append(
                Finding(
                    check="synthesis",
                    severity="INFO",
                    path=doc.rel,
                    message=f"status: done but maturity is {label} (synthesis may be incomplete, SOLO/R5)",
                    suggestion="if findings are compared/integrated, set maturity: connected|integrated|generalized",
                )
            )
    return findings


def check_strength(repo: Repo) -> list[Finding]:
    """references without `strength:` — aggregated INFO (566+ legacy files expected)."""
    findings: list[Finding] = []
    missing: list[str] = []
    for stem, doc in repo.references.items():
        value = doc.fm.get("strength")
        if isinstance(value, str) and value:
            if value not in REFERENCE_STRENGTHS:
                findings.append(
                    Finding(
                        check="strength",
                        severity="ERROR",
                        path=doc.rel,
                        message=f"strength '{value}' not in {sorted(REFERENCE_STRENGTHS)}",
                    )
                )
        else:
            missing.append(stem)
    if missing:
        preview = ", ".join(missing[:5])
        findings.append(
            Finding(
                check="strength",
                severity="INFO",
                path="references/",
                message=f"{len(missing)} reference(s) lack strength: (e.g. {preview})",
                suggestion="add strength: (vocab/strength-levels.yml) progressively when touching a reference",
            )
        )
    return findings


def _check_section_empty(body: str) -> tuple[bool, bool]:
    """Return (section_missing, section_empty) for the 理解度チェック heading."""
    lines = body.splitlines()
    idx = next((i for i, line in enumerate(lines) if _CHECK_SECTION_RE.match(line)), None)
    if idx is None:
        return True, False
    for line in lines[idx + 1 :]:
        if _HEADING_RE.match(line):
            break
        if line.strip():
            return False, False
    return False, True


def check_lessons(repo: Repo) -> list[Finding]:
    """R7 lite: lessons need non-empty objectives and a non-empty 理解度チェック section."""
    findings: list[Finding] = []
    for doc in repo.lessons:
        if not get_list(doc.fm, "objectives"):
            findings.append(
                Finding(
                    check="lessons",
                    severity="WARN",
                    path=doc.rel,
                    message="objectives: is empty",
                    suggestion="state observable objectives (revised-Bloom verbs) aligned with 理解度チェック",
                )
            )
        missing, empty = _check_section_empty(doc.body)
        if missing:
            findings.append(
                Finding(check="lessons", severity="WARN", path=doc.rel, message="理解度チェック section is missing")
            )
        elif empty:
            findings.append(
                Finding(check="lessons", severity="WARN", path=doc.rel, message="理解度チェック section is empty")
            )
    return findings


def check_currency(repo: Repo) -> list[Finding]:
    """Unescaped `$<digit>` outside code — remark-math (singleDollarTextMath) misparses pairs."""
    findings: list[Finding] = []
    docs = list(repo.topics.values()) + list(repo.references.values())
    for doc in docs:
        offset = doc.body_line_offset()
        for i, line in iter_body_lines_outside_fences(doc.body):
            n = len(_CURRENCY_RE.findall(_CODE_SPAN_RE.sub("", line)))
            if n:
                findings.append(
                    Finding(
                        check="currency",
                        severity="WARN",
                        path=doc.rel,
                        line=offset + i + 1,
                        message=f"{n} unescaped currency $ before a digit",
                        suggestion="run `python3 -m survey_any fix-currency --apply`",
                    )
                )
    return findings


def _load_mise_task_names() -> frozenset[str]:
    """Task ids defined in mise.toml (subcommand-style tasks count as their first word)."""
    data = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))
    return frozenset(data.get("tasks", {}))


def check_skills(repo: Repo) -> list[Finding]:
    """`mise run <task>` references in skill/agent prose must name a defined task."""
    del repo  # skills prose lives outside the content tree
    tasks = _load_mise_task_names()
    findings: list[Finding] = []
    for pattern in SKILL_PROSE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if i > 0 and _DOCTOR_IGNORE_MARK in lines[i - 1]:
                    continue
                for name in _MISE_RUN_RE.findall(line):
                    if name in tasks:
                        continue
                    findings.append(
                        Finding(
                            check="skills",
                            severity="ERROR",
                            path=str(path.relative_to(ROOT)),
                            line=i + 1,
                            message=f"references undefined mise task '{name}'",
                            suggestion="fix the task name or add `<!-- doctor: ignore-next-line -->` above",
                        )
                    )
    return findings


def _head(output: str) -> str:
    """First three nonempty output lines joined by '; '."""
    return "; ".join(line.strip() for line in output.strip().splitlines()[:3] if line.strip())


def _run_subcommand(name: str, argv: list[str]) -> tuple[int | None, str]:
    """Run a survey-any subcommand IN-PROCESS, same (rc, head) contract as a subprocess.

    Imports ``survey_any.commands.<name with '-'→'_'>`` and calls its
    ``main(argv)`` while capturing stdout+stderr. This avoids the fragile
    ``sys.executable -m survey_any`` re-exec that traceback's under uvx (where
    ``sys.executable`` is the ephemeral tool venv, not an importable module).

    Returns ``(rc, head)`` where ``rc`` is ``int | None`` (``None`` maps to 0)
    and ``head`` is the first three nonempty output lines joined by "; ". A
    raised exception is reported as ``(1, str(exc))``.
    """
    os.environ["SURVEY_ANY_ROOT"] = str(ROOT)
    module_name = f"survey_any.commands.{name.replace('-', '_')}"
    buf = io.StringIO()
    try:
        module = importlib.import_module(module_name)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = module.main(argv)
    except SystemExit as exc:  # a sub-command that calls sys.exit() instead of returning
        code = exc.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
    except Exception as exc:  # noqa: BLE001 — surface any failure as rc=1, mirroring a nonzero exit
        return 1, str(exc)[:500]
    return (0 if rc is None else rc), _head(buf.getvalue())


def check_tokenizer(repo: Repo) -> list[Finding]:
    """Python/TS tokenizer parity (rc 3 = bun missing -> INFO, rc 1 = drift -> ERROR)."""
    del repo  # compares implementations, not content
    rc, head = _run_subcommand("check-tokenizer-drift", [])
    if rc == 0:
        return []
    if rc == 3:
        return [
            Finding(
                check="tokenizer",
                severity="INFO",
                path="survey_any/commands/check_tokenizer_drift.py",
                message="skipped: bun is not installed",
            )
        ]
    return [
        Finding(
            check="tokenizer",
            severity="ERROR",
            path="viewer/functions/lib/tokenizer.ts",
            message=f"tokenizer drift vs survey_any/_tokenizer.py (rc={rc}): {head}",
            suggestion="run `python3 -m survey_any check-tokenizer-drift` and re-sync the port",
        )
    ]


def check_external(repo: Repo) -> list[Finding]:
    """Aggregate the existing linters: tags-validate.py --strict and check-schema-drift.py."""
    del repo  # signature parity with other checks
    findings: list[Finding] = []

    rc, head = _run_subcommand("tags-validate", ["--strict"])
    if rc is None:
        findings.append(
            Finding(
                check="external",
                severity="WARN",
                path="survey_any/commands/tags_validate.py",
                message=f"failed to run: {head}",
            )
        )
    elif rc != 0:
        findings.append(
            Finding(
                check="external",
                severity="WARN",
                path="vocab/tags.yml",
                message=f"tags-validate --strict failed (rc={rc}): {head}",
                suggestion="run `mise run tags-validate` for the alias/unknown breakdown",
            )
        )

    rc, head = _run_subcommand("check-schema", [])
    if rc is None:
        findings.append(
            Finding(
                check="external", severity="WARN", path="survey_any/commands/check_schema.py", message=f"failed to run: {head}"
            )
        )
    elif rc != 0:
        findings.append(
            Finding(
                check="external",
                severity="ERROR",
                path="viewer/src/content.config.ts",
                message=f"schema drift detected (rc={rc}): {head}",
                suggestion="sync survey_any/_schema.py with viewer/src/content.config.ts",
            )
        )
    return findings


CHECKS: Final[dict[str, tuple[str, Callable[[Repo], list[Finding]]]]] = {
    "sources": ("topics sources: entries resolve to references/", check_sources),
    "related": ("related: targets exist and are bidirectional", check_related),
    "relations": ("typed relations: targets exist, type in vocab", check_relations),
    "links": ("relative .md links in bodies resolve", check_links),
    "dates": ("references date:/retrieved: use YYYY-MM-DD", check_dates),
    "synthesis": ("status: done topics have scent / adequate maturity", check_synthesis),
    "strength": ("references carry an evidence strength:", check_strength),
    "lessons": ("lessons have objectives + 理解度チェック", check_lessons),
    "currency": ("no unescaped currency $ outside code", check_currency),
    "skills": ("skill/agent prose references defined mise tasks", check_skills),
    "tokenizer": ("_tokenizer.py and tokenizer.ts tokenize identically", check_tokenizer),
    "external": ("tags-validate --strict + check-schema-drift", check_external),
}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _counts(findings: list[Finding]) -> dict[str, int]:
    return {sev: sum(1 for f in findings if f.severity == sev) for sev in SEVERITIES}


def render_human(results: dict[str, list[Finding]]) -> str:
    """Render grouped findings as a readable report (display capped per check)."""
    out: list[str] = ["# survey-any doctor", ""]
    for check_id, findings in results.items():
        desc = CHECKS[check_id][0]
        c = _counts(findings)
        badge = " ".join(f"{sev}:{n}" for sev, n in c.items() if n) or "ok"
        out.append(f"## [{check_id}] {desc}  ({badge})")
        ordered = sorted(findings, key=lambda f: (SEVERITIES.index(f.severity), f.path, f.line or 0))
        for f in ordered[:DISPLAY_CAP]:
            loc = f"{f.path}:{f.line}" if f.line else f.path
            out.append(f"  [{f.severity:5s}] {loc}")
            out.append(f"          {f.message}")
            if f.suggestion:
                out.append(f"          -> {f.suggestion}")
        if len(ordered) > DISPLAY_CAP:
            out.append(f"  ... {len(ordered) - DISPLAY_CAP} more (use --json for the full list)")
        out.append("")

    out.append("## summary")
    out.append("")
    width = max(len(cid) for cid in results)
    out.append(f"  {'check'.ljust(width)}  ERROR  WARN  INFO")
    totals = {sev: 0 for sev in SEVERITIES}
    for check_id, findings in results.items():
        c = _counts(findings)
        for sev in SEVERITIES:
            totals[sev] += c[sev]
        out.append(f"  {check_id.ljust(width)}  {c['ERROR']:5d}  {c['WARN']:4d}  {c['INFO']:4d}")
    out.append(f"  {'total'.ljust(width)}  {totals['ERROR']:5d}  {totals['WARN']:4d}  {totals['INFO']:4d}")
    out.append("")
    out.append("result: FAIL (errors present)" if totals["ERROR"] else "result: OK (no errors)")
    return "\n".join(out)


def render_json(results: dict[str, list[Finding]]) -> str:
    checks = {
        check_id: {
            "description": CHECKS[check_id][0],
            "counts": _counts(findings),
            "findings": [asdict(f) for f in findings],
        }
        for check_id, findings in results.items()
    }
    totals = {sev: sum(c["counts"][sev] for c in checks.values()) for sev in SEVERITIES}
    payload = {"root": str(ROOT), "checks": checks, "totals": totals, "ok": totals["ERROR"] == 0}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cross-cutting consistency checker for survey-any")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument("--only", metavar="IDS", help="comma-separated check ids to run (see --list)")
    p.add_argument("--list", action="store_true", help="list available check ids and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list:
        for check_id, (desc, _) in CHECKS.items():
            print(f"{check_id:10s} {desc}")
        return 0

    selected = list(CHECKS)
    if args.only:
        selected = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [s for s in selected if s not in CHECKS]
        if unknown:
            print(f"unknown check id(s): {', '.join(unknown)} (available: {', '.join(CHECKS)})", file=sys.stderr)
            return 2

    repo = load_repo()
    results = {check_id: CHECKS[check_id][1](repo) for check_id in selected}

    print(render_json(results) if args.json else render_human(results))
    has_error = any(f.severity == "ERROR" for findings in results.values() for f in findings)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
