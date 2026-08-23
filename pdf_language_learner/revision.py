"""Pure spaced-repetition rules for saved vocabulary.

This module intentionally knows nothing about FastAPI or SQLite.  Keeping the
schedule deterministic makes it possible to test it with fixed timestamps and
to replace the policy later without changing the HTTP or persistence layers.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


CORRECT_INTERVAL_DAYS = (1, 3, 7, 14, 30, 60, 120)
INCORRECT_INTERVAL = timedelta(minutes=10)


class RevisionCategory(StrEnum):
    NEW = "new"
    ALWAYS_CORRECT = "always_correct"
    USUALLY_CORRECT = "usually_correct"
    NEEDS_PRACTICE = "needs_practice"


class RevisionDirection(StrEnum):
    SOURCE_TO_TRANSLATION = "source_to_translation"
    TRANSLATION_TO_SOURCE = "translation_to_source"


@dataclass(frozen=True)
class ScheduleState:
    """The persisted values needed to calculate one card's next review."""

    repetitions: int = 0
    lapses: int = 0
    consecutive_correct: int = 0
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None


def revision_category(state: ScheduleState) -> RevisionCategory:
    """Classify a card from its observed answer history.

    Three error-free answers are enough to call a card consistently known.
    After an error, it needs two consecutive correct answers and at least 60%
    lifetime accuracy before it leaves the needs-practice category.
    """

    attempts = state.repetitions + state.lapses
    if attempts == 0:
        return RevisionCategory.NEW
    if state.lapses == 0 and state.repetitions >= 3:
        return RevisionCategory.ALWAYS_CORRECT
    accuracy = state.repetitions / attempts
    if state.lapses == 0 or (
        state.consecutive_correct >= 2 and accuracy >= 0.6
    ):
        return RevisionCategory.USUALLY_CORRECT
    return RevisionCategory.NEEDS_PRACTICE


def schedule_review(
    state: ScheduleState,
    *,
    correct: bool,
    reviewed_at: datetime,
) -> ScheduleState:
    """Return the state produced by one first-attempt answer."""

    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    reviewed_at = reviewed_at.astimezone(UTC)

    if not correct:
        return ScheduleState(
            repetitions=state.repetitions,
            lapses=state.lapses + 1,
            consecutive_correct=0,
            last_reviewed_at=reviewed_at,
            next_review_at=reviewed_at + INCORRECT_INTERVAL,
        )

    streak = state.consecutive_correct + 1
    interval_index = min(streak - 1, len(CORRECT_INTERVAL_DAYS) - 1)
    return ScheduleState(
        repetitions=state.repetitions + 1,
        lapses=state.lapses,
        consecutive_correct=streak,
        last_reviewed_at=reviewed_at,
        next_review_at=reviewed_at
        + timedelta(days=CORRECT_INTERVAL_DAYS[interval_index]),
    )


def is_due(state: ScheduleState, *, at: datetime) -> bool:
    """New cards and cards whose due time has passed are available."""

    if at.tzinfo is None:
        raise ValueError("at must include a timezone")
    return state.next_review_at is None or state.next_review_at <= at.astimezone(UTC)


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
