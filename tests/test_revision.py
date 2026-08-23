from datetime import UTC, datetime, timedelta

import pytest

from pdf_language_learner.revision import (
    RevisionCategory,
    ScheduleState,
    is_due,
    revision_category,
    schedule_review,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def test_new_word_is_due_and_classified_as_new() -> None:
    state = ScheduleState()

    assert is_due(state, at=NOW)
    assert revision_category(state) is RevisionCategory.NEW


@pytest.mark.parametrize(
    ("streak", "expected_days"),
    [(0, 1), (1, 3), (2, 7), (3, 14), (4, 30), (5, 60), (6, 120), (20, 120)],
)
def test_correct_answer_advances_interval_ladder(
    streak: int, expected_days: int
) -> None:
    state = ScheduleState(repetitions=streak, consecutive_correct=streak)

    updated = schedule_review(state, correct=True, reviewed_at=NOW)

    assert updated.repetitions == streak + 1
    assert updated.consecutive_correct == streak + 1
    assert updated.next_review_at == NOW + timedelta(days=expected_days)


def test_incorrect_answer_resets_streak_and_returns_in_ten_minutes() -> None:
    state = ScheduleState(repetitions=4, consecutive_correct=4)

    updated = schedule_review(state, correct=False, reviewed_at=NOW)

    assert updated.repetitions == 4
    assert updated.lapses == 1
    assert updated.consecutive_correct == 0
    assert updated.next_review_at == NOW + timedelta(minutes=10)
    assert revision_category(updated) is RevisionCategory.NEEDS_PRACTICE


def test_three_error_free_answers_are_always_correct() -> None:
    state = ScheduleState(repetitions=3, consecutive_correct=3)

    assert revision_category(state) is RevisionCategory.ALWAYS_CORRECT


def test_failed_word_recovers_after_two_correct_answers() -> None:
    state = ScheduleState(repetitions=3, lapses=1, consecutive_correct=2)

    assert revision_category(state) is RevisionCategory.USUALLY_CORRECT


def test_schedule_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        schedule_review(ScheduleState(), correct=True, reviewed_at=datetime(2026, 1, 1))
