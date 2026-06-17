"""Frontmatter schemas — Python-side Source of Truth.

Mirrors `viewer/src/content.config.ts` (zod) one-to-one. Whenever the zod
collections change, update the dataclasses below and `check-schema-drift.py`
will keep the two sides honest.

Design choices (case A in the task brief):
  - frozen dataclass for immutable value objects
  - validator functions return a typed dataclass instance from a parsed
    `dict` (the output of `_frontmatter.parse_frontmatter`)
  - permissive on input shape (frontmatter parser produces strings even for
    booleans / numbers / dates), strict on the resulting type
  - standard library only

Each `validate_*_fm` raises `ValueError` for hard failures (unknown enum
values, type mismatch on required fields). Missing optional fields fall
back to the zod default. Extra unknown keys are tolerated for now (the
drift checker is the place that flags them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from typing import Any, Final, Iterable

# ---------------------------------------------------------------------------
# Enum value sets — mirror zod `z.enum([...])`.
# ---------------------------------------------------------------------------

TOPIC_STATUSES: Final[frozenset[str]] = frozenset(
    {"done", "in-progress", "memo", "archived"}
)
COURSE_STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "published", "archived"}
)
COURSE_DIFFICULTIES: Final[frozenset[str]] = frozenset(
    {"beginner", "intermediate", "advanced"}
)
REFERENCE_READ_DEPTHS: Final[frozenset[str]] = frozenset(
    {"full", "abstract", "overview"}
)


# ---------------------------------------------------------------------------
# Helpers — keep all coercion logic here, away from the dataclasses.
# ---------------------------------------------------------------------------


def _as_str_or_none(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"{key}: expected string, got {type(value).__name__}")


def _as_str_default(key: str, value: Any, default: str) -> str:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value
    raise ValueError(f"{key}: expected string, got {type(value).__name__}")


def _as_bool_default(key: str, value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    raise ValueError(f"{key}: expected boolean, got {value!r}")


def _as_number_or_none(key: str, value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        # bool is a subclass of int — reject to avoid silent coercion.
        raise ValueError(f"{key}: expected number, got bool")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{key}: expected number, got {value!r}") from exc
    raise ValueError(f"{key}: expected number, got {type(value).__name__}")


def _as_number_default(key: str, value: Any, default: float | int) -> float | int:
    parsed = _as_number_or_none(key, value)
    return default if parsed is None else parsed


def _as_date_or_none(key: str, value: Any) -> date | None:
    """Mirror the zod `optionalDate` preprocess + `z.coerce.date()`.

    - empty / None / the YAML string "null" -> None (matches the preprocess)
    - "YYYY", "YYYY-MM", "YYYY-MM-DD"[T..] all coerce to a date (JS `new Date`
      tolerates these; we approximate by filling missing parts with 01)
    """
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        # Year-only: `2025` -> 2025-01-01.
        if re.fullmatch(r"\d{4}", candidate):
            return date(int(candidate), 1, 1)
        # Year-month: `2025-03` -> 2025-03-01.
        m = re.fullmatch(r"(\d{4})-(\d{2})", candidate)
        if m:
            return date(int(m.group(1)), int(m.group(2)), 1)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
        # Permissive: trailing timezone like `+0900` collapsed earlier strptime
        # may still fail; fall back to ISO parsing of the date portion.
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError as exc:
            raise ValueError(f"{key}: expected date, got {value!r}") from exc
    raise ValueError(f"{key}: expected date, got {type(value).__name__}")


def _as_str_list(key: str, value: Any) -> list[str]:
    """Coerce zod `z.array(z.string()).default([])`-style fields."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        # Single scalar — frontmatter parser returns str for `tags: foo`.
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                # references.tags allows number -> string via `.transform(String)`.
                out.append(str(item))
                continue
            if not isinstance(item, str):
                raise ValueError(f"{key}: list items must be strings, got {item!r}")
            out.append(item)
        return out
    raise ValueError(f"{key}: expected list of strings, got {type(value).__name__}")


def _as_enum(key: str, value: Any, allowed: frozenset[str], default: str | None) -> str:
    if value is None or value == "":
        if default is None:
            raise ValueError(f"{key}: required, got empty")
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key}: expected string, got {type(value).__name__}")
    if value not in allowed:
        raise ValueError(
            f"{key}: {value!r} not in {sorted(allowed)}"
        )
    return value


def _as_optional_enum(key: str, value: Any, allowed: frozenset[str]) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key}: expected string, got {type(value).__name__}")
    if value not in allowed:
        raise ValueError(f"{key}: {value!r} not in {sorted(allowed)}")
    return value


# ---------------------------------------------------------------------------
# Schema dataclasses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicFrontmatter:
    """Mirror of `topics` collection schema in viewer/src/content.config.ts."""

    title: str = "Untitled"
    status: str = "memo"
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    created: date | None = None
    updated: date | None = None
    review_at: date | None = None
    sources: list[str] = field(default_factory=list)
    public: bool = False
    archived_at: date | None = None
    archive_reason: str | None = None
    redirect: str | None = None
    replaces: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceFrontmatter:
    """Mirror of `references` collection schema."""

    title: str = "Untitled"
    type: str = "article"
    author: str | None = None
    organization: str | None = None
    url: str | None = None
    date: date | None = None
    year: float | int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    open_access_pdf: str | None = None
    citation_count: float | int | None = None
    read_depth: str | None = None
    retrieved: date | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CourseSources:
    """Nested object used by both courses and lessons."""

    topics: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CourseFrontmatter:
    """Mirror of `courses` collection schema."""

    title: str = "Untitled"
    status: str = "draft"
    tags: list[str] = field(default_factory=list)
    difficulty: str = "beginner"
    prerequisites: list[str] = field(default_factory=list)
    estimated_hours: float | int = 0
    created: date | None = None
    updated: date | None = None
    objectives: list[str] = field(default_factory=list)
    sources: CourseSources = field(default_factory=CourseSources)


@dataclass(frozen=True)
class LessonFrontmatter:
    """Mirror of `lessons` collection schema."""

    title: str = "Untitled"
    order: float | int = 0
    estimated_minutes: float | int = 0
    objectives: list[str] = field(default_factory=list)
    sources: CourseSources = field(default_factory=CourseSources)


# ---------------------------------------------------------------------------
# Field-name accessors — used by check-schema-drift.py.
# ---------------------------------------------------------------------------


def topic_field_names() -> frozenset[str]:
    return frozenset(f.name for f in fields(TopicFrontmatter))


def reference_field_names() -> frozenset[str]:
    return frozenset(f.name for f in fields(ReferenceFrontmatter))


def course_field_names() -> frozenset[str]:
    return frozenset(f.name for f in fields(CourseFrontmatter))


def lesson_field_names() -> frozenset[str]:
    return frozenset(f.name for f in fields(LessonFrontmatter))


# ---------------------------------------------------------------------------
# Validators.
# ---------------------------------------------------------------------------


def _coerce_sources_block(key: str, value: Any) -> CourseSources:
    if value is None or value == "":
        return CourseSources()
    if isinstance(value, dict):
        return CourseSources(
            topics=_as_str_list(f"{key}.topics", value.get("topics")),
            references=_as_str_list(f"{key}.references", value.get("references")),
        )
    raise ValueError(f"{key}: expected mapping with topics/references, got {type(value).__name__}")


def validate_topic_fm(fm: dict[str, Any]) -> TopicFrontmatter:
    """Validate parsed topic frontmatter and return a typed instance."""
    return TopicFrontmatter(
        title=_as_str_default("title", fm.get("title"), "Untitled"),
        status=_as_enum("status", fm.get("status"), TOPIC_STATUSES, "memo"),
        tags=_as_str_list("tags", fm.get("tags")),
        related=_as_str_list("related", fm.get("related")),
        created=_as_date_or_none("created", fm.get("created")),
        updated=_as_date_or_none("updated", fm.get("updated")),
        review_at=_as_date_or_none("review_at", fm.get("review_at")),
        sources=_as_str_list("sources", fm.get("sources")),
        public=_as_bool_default("public", fm.get("public"), False),
        archived_at=_as_date_or_none("archived_at", fm.get("archived_at")),
        archive_reason=_as_str_or_none("archive_reason", fm.get("archive_reason")),
        redirect=_as_str_or_none("redirect", fm.get("redirect")),
        replaces=_as_str_list("replaces", fm.get("replaces")),
    )


def validate_reference_fm(fm: dict[str, Any]) -> ReferenceFrontmatter:
    """Validate parsed reference frontmatter and return a typed instance."""
    return ReferenceFrontmatter(
        title=_as_str_default("title", fm.get("title"), "Untitled"),
        type=_as_str_default("type", fm.get("type"), "article"),
        author=_as_str_or_none("author", fm.get("author")),
        organization=_as_str_or_none("organization", fm.get("organization")),
        url=_as_str_or_none("url", fm.get("url")),
        date=_as_date_or_none("date", fm.get("date")),
        year=_as_number_or_none("year", fm.get("year")),
        venue=_as_str_or_none("venue", fm.get("venue")),
        doi=_as_str_or_none("doi", fm.get("doi")),
        arxiv_id=_as_str_or_none("arxiv_id", fm.get("arxiv_id")),
        semantic_scholar_id=_as_str_or_none(
            "semantic_scholar_id", fm.get("semantic_scholar_id")
        ),
        open_access_pdf=_as_str_or_none("open_access_pdf", fm.get("open_access_pdf")),
        citation_count=_as_number_or_none("citation_count", fm.get("citation_count")),
        read_depth=_as_optional_enum("read_depth", fm.get("read_depth"), REFERENCE_READ_DEPTHS),
        retrieved=_as_date_or_none("retrieved", fm.get("retrieved")),
        tags=_as_str_list("tags", fm.get("tags")),
    )


def validate_course_fm(fm: dict[str, Any]) -> CourseFrontmatter:
    """Validate parsed course frontmatter and return a typed instance."""
    return CourseFrontmatter(
        title=_as_str_default("title", fm.get("title"), "Untitled"),
        status=_as_enum("status", fm.get("status"), COURSE_STATUSES, "draft"),
        tags=_as_str_list("tags", fm.get("tags")),
        difficulty=_as_enum(
            "difficulty", fm.get("difficulty"), COURSE_DIFFICULTIES, "beginner"
        ),
        prerequisites=_as_str_list("prerequisites", fm.get("prerequisites")),
        estimated_hours=_as_number_default("estimated_hours", fm.get("estimated_hours"), 0),
        created=_as_date_or_none("created", fm.get("created")),
        updated=_as_date_or_none("updated", fm.get("updated")),
        objectives=_as_str_list("objectives", fm.get("objectives")),
        sources=_coerce_sources_block("sources", fm.get("sources")),
    )


def validate_lesson_fm(fm: dict[str, Any]) -> LessonFrontmatter:
    """Validate parsed lesson frontmatter and return a typed instance."""
    return LessonFrontmatter(
        title=_as_str_default("title", fm.get("title"), "Untitled"),
        order=_as_number_default("order", fm.get("order"), 0),
        estimated_minutes=_as_number_default(
            "estimated_minutes", fm.get("estimated_minutes"), 0
        ),
        objectives=_as_str_list("objectives", fm.get("objectives")),
        sources=_coerce_sources_block("sources", fm.get("sources")),
    )


__all__: Iterable[str] = (
    "TOPIC_STATUSES",
    "COURSE_STATUSES",
    "COURSE_DIFFICULTIES",
    "REFERENCE_READ_DEPTHS",
    "TopicFrontmatter",
    "ReferenceFrontmatter",
    "CourseFrontmatter",
    "LessonFrontmatter",
    "CourseSources",
    "topic_field_names",
    "reference_field_names",
    "course_field_names",
    "lesson_field_names",
    "validate_topic_fm",
    "validate_reference_fm",
    "validate_course_fm",
    "validate_lesson_fm",
)
