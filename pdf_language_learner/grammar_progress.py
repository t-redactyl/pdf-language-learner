"""Learner-specific introduction state for grammar topics."""

from __future__ import annotations

from enum import StrEnum

from pdf_language_learner.german_grammar_catalogue import GRAMMAR_TOPICS
from pdf_language_learner.grammar_topics import GrammarLanguage, GrammarTopic
from pdf_language_learner.revision import (
    RevisionCategory,
    ScheduleState,
    revision_category,
)
from pdf_language_learner.spanish_grammar_catalogue import SPANISH_GRAMMAR_TOPICS


INITIAL_GRAMMAR_PROGRESS_MIGRATION = "grammar-initial-progress-v1"
INITIAL_SEEN_THROUGH_KEYS = {
    GrammarLanguage.GERMAN: "a1b1_praepositionaladverbien_pronomen",
    GrammarLanguage.SPANISH: "es_a2_u6_affirmative_imperative",
}


class GrammarTopicStatus(StrEnum):
    NEW = "new"
    SEEN = "seen"
    NEEDS_PRACTICE = "needs_practice"
    USUALLY_CORRECT = "usually_correct"
    ALWAYS_CORRECT = "always_correct"


def topics_through(
    topics: tuple[GrammarTopic, ...],
    through_key: str,
) -> tuple[GrammarTopic, ...]:
    """Return the ordered prefix ending at ``through_key``, inclusively."""

    for position, topic in enumerate(topics):
        if topic.key == through_key:
            return topics[: position + 1]
    raise ValueError(f"Unknown grammar topic cutoff: {through_key}")


def initially_seen_topics() -> tuple[GrammarTopic, ...]:
    """Topics learned before grammar revision was introduced in Margin."""

    catalogues = {
        GrammarLanguage.GERMAN: GRAMMAR_TOPICS,
        GrammarLanguage.SPANISH: SPANISH_GRAMMAR_TOPICS,
    }
    return tuple(
        topic
        for language, cutoff in INITIAL_SEEN_THROUGH_KEYS.items()
        for topic in topics_through(catalogues[language], cutoff)
    )


def grammar_topic_status(
    *,
    introduced: bool,
    schedule: ScheduleState,
) -> GrammarTopicStatus:
    """Distinguish unseen material from seen but unassessed material."""

    if not introduced:
        return GrammarTopicStatus.NEW
    if schedule.repetitions + schedule.lapses == 0:
        return GrammarTopicStatus.SEEN
    category = revision_category(schedule)
    if category is RevisionCategory.NEEDS_PRACTICE:
        return GrammarTopicStatus.NEEDS_PRACTICE
    if category is RevisionCategory.USUALLY_CORRECT:
        return GrammarTopicStatus.USUALLY_CORRECT
    if category is RevisionCategory.ALWAYS_CORRECT:
        return GrammarTopicStatus.ALWAYS_CORRECT
    return GrammarTopicStatus.SEEN
