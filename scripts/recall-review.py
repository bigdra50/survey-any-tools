#!/usr/bin/env python3
"""Spaced-repetition scheduler for topic `recall:` prompts (SM-2, simplified).

Implements the "retention & transfer" layer of the reader-centered design plan
(R4): retrieval practice (Roediger & Karpicke 2006) and spaced learning
(Cepeda et al. 2006) are the two highest-yield study techniques per Dunlosky
et al. (2013). This script surfaces `recall:` self-test questions from topic
frontmatter on a schedule and reschedules them via a simplified SM-2 update
after the reader grades their own recall attempt.

Not to be confused with `scripts/review-due.py`: that script flags topics for
CREW/MUSTIE-style weeding (should this topic be archived / rewritten because
it is stale?). This script is about relearning (should I retrieve this
topic's content from memory again to keep it durable?). The two are
independent judgments and intentionally do not share state or thresholds.

State is kept out of frontmatter (to avoid frontmatter churn on every review)
in `memory/recall-state.json`, keyed by topic directory name:

    {
      "<topic-name>": {
        "interval_days": 6,
        "ease": 2.5,
        "last_reviewed": "2026-07-07",
        "next_due": "2026-07-13"
      },
      ...
    }

Usage:
    python3 scripts/recall-review.py                  # list due topics + their recall: questions
    python3 scripts/recall-review.py --all             # list all scheduled topics + state
    python3 scripts/recall-review.py --grade <topic> <0-5>   # record a recall attempt, reschedule
    python3 scripts/recall-review.py --json            # machine-readable due list
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontmatter import get_list, load_frontmatter  # noqa: E402
from _root import content_root  # noqa: E402

ROOT = content_root()
TOPICS_DIR = ROOT / "topics"
STATE_PATH = ROOT / "memory" / "recall-state.json"

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
FIRST_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6


@dataclass(frozen=True)
class CardState:
    """SM-2 scheduling state for one topic."""

    interval_days: int
    ease: float
    last_reviewed: str
    next_due: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _today() -> date:
    return datetime.now().date()


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def load_state() -> dict[str, CardState]:
    """Load recall-state.json; missing file is treated as empty state (pure w.r.t. filesystem snapshot)."""
    if not STATE_PATH.exists():
        return {}
    raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {name: CardState(**fields) for name, fields in raw.items()}


def save_state(state: dict[str, CardState]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {name: card.to_dict() for name, card in state.items()}
    STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sm2_next(card: CardState | None, grade: int, today: date) -> CardState:
    """Compute the next CardState after a recall attempt graded 0-5 (SM-2, simplified).

    grade >= 3 counts as a successful recall; interval grows (1 -> 6 -> round(interval*ease)).
    grade < 3 counts as a lapse; interval resets to 1 day but ease is still adjusted down.
    Ease is clamped at MIN_EASE per the original SM-2 algorithm.
    """
    if not 0 <= grade <= 5:
        raise ValueError(f"grade must be 0-5, got {grade}")

    prev_ease = card.ease if card is not None else DEFAULT_EASE
    prev_interval = card.interval_days if card is not None else 0

    ease_delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
    new_ease = max(MIN_EASE, prev_ease + ease_delta)

    if grade < 3:
        new_interval = FIRST_INTERVAL_DAYS
    elif prev_interval <= 0:
        new_interval = FIRST_INTERVAL_DAYS
    elif prev_interval == FIRST_INTERVAL_DAYS:
        new_interval = SECOND_INTERVAL_DAYS
    else:
        new_interval = max(1, round(prev_interval * new_ease))

    next_due = today.fromordinal(today.toordinal() + new_interval)
    return CardState(
        interval_days=new_interval,
        ease=round(new_ease, 4),
        last_reviewed=today.isoformat(),
        next_due=next_due.isoformat(),
    )


def topic_recall_questions(name: str) -> list[str]:
    readme = TOPICS_DIR / name / "README.md"
    if not readme.exists():
        return []
    fm = load_frontmatter(readme)
    return get_list(fm, "recall")


def all_topics_with_recall() -> list[str]:
    """Topic directory names that have a non-empty `recall:` frontmatter field."""
    names = []
    for readme in sorted(TOPICS_DIR.glob("*/README.md")):
        if get_list(load_frontmatter(readme), "recall"):
            names.append(readme.parent.name)
    return names


def cmd_due(*, emit_json: bool) -> int:
    today = _today()
    state = load_state()
    topics = all_topics_with_recall()

    due: list[dict[str, object]] = []
    for name in topics:
        card = state.get(name)
        is_due = card is None or _parse_date(card.next_due) <= today
        if not is_due:
            continue
        due.append(
            {
                "topic": name,
                "questions": topic_recall_questions(name),
                "next_due": card.next_due if card else "new",
            }
        )

    if emit_json:
        print(json.dumps(due, ensure_ascii=False))
        return 0

    print(f"Recall-due topics: {len(due)}")
    print()
    for entry in due:
        print(f"## {entry['topic']}  (due: {entry['next_due']})")
        for q in entry["questions"]:
            print(f"  - {q}")
        print()
    return 0


def cmd_all() -> int:
    state = load_state()
    topics = all_topics_with_recall()
    print(f"{'TOPIC':<50} {'INTERVAL':<10} {'EASE':<6} {'LAST':<12} NEXT_DUE")
    for name in topics:
        card = state.get(name)
        if card is None:
            print(f"{name:<50} {'new':<10} {'-':<6} {'-':<12} not scheduled")
        else:
            print(
                f"{name:<50} {card.interval_days}d{'':<7} {card.ease:<6} "
                f"{card.last_reviewed:<12} {card.next_due}"
            )
    return 0


def cmd_grade(topic: str, grade: int) -> int:
    if not (TOPICS_DIR / topic / "README.md").exists():
        print(f"error: topics/{topic}/README.md not found", file=sys.stderr)
        return 1

    state = load_state()
    today = _today()
    new_card = sm2_next(state.get(topic), grade, today)
    state = {**state, topic: new_card}
    save_state(state)
    print(f"{topic}: grade={grade} -> interval={new_card.interval_days}d ease={new_card.ease} next_due={new_card.next_due}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", action="store_true", help="List all recall-scheduled topics and their state")
    p.add_argument("--json", action="store_true", dest="emit_json", help="Emit due list as JSON")
    p.add_argument(
        "--grade",
        nargs=2,
        metavar=("TOPIC", "GRADE"),
        help="Record a recall attempt: --grade <topic-name> <0-5>",
    )
    args = p.parse_args()

    if args.grade:
        topic_name, grade_str = args.grade
        try:
            grade = int(grade_str)
        except ValueError:
            print(f"error: grade must be an integer 0-5, got {grade_str!r}", file=sys.stderr)
            return 1
        try:
            return cmd_grade(topic_name, grade)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.all:
        return cmd_all()

    return cmd_due(emit_json=args.emit_json)


if __name__ == "__main__":
    sys.exit(main())
