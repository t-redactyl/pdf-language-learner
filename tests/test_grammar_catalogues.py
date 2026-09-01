import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pdf_language_learner.app import (
    create_grammar_tables,
    seed_initial_grammar_progress,
)
from pdf_language_learner.german_grammar_catalogue import (
    A1_B1_TOPICS,
    B2_C1_TOPICS,
    GRAMMAR_TOPICS,
    grammar_topic_by_key,
)
from pdf_language_learner.grammar_progress import (
    GrammarTopicStatus,
    grammar_topic_status,
    initially_seen_topics,
)
from pdf_language_learner.grammar_topics import GrammarLanguage
from pdf_language_learner.revision import ScheduleState
from pdf_language_learner.spanish_grammar_catalogue import (
    A1_SPANISH_GRAMMAR_TOPICS,
    A2_SPANISH_GRAMMAR_TOPICS,
    SPANISH_GRAMMAR_TOPICS,
    spanish_grammar_topic_by_key,
    spanish_grammar_topics_by_category,
    spanish_grammar_topics_by_source_group,
)


ROOT = Path(__file__).resolve().parent.parent


def test_catalogues_have_unique_language_specific_ordering() -> None:
    assert len(GRAMMAR_TOPICS) == 100
    assert len(SPANISH_GRAMMAR_TOPICS) == 71
    assert len(A1_SPANISH_GRAMMAR_TOPICS) == 43
    assert len(A2_SPANISH_GRAMMAR_TOPICS) == 28

    for language, topics in (
        (GrammarLanguage.GERMAN, GRAMMAR_TOPICS),
        (GrammarLanguage.SPANISH, SPANISH_GRAMMAR_TOPICS),
    ):
        assert {topic.language for topic in topics} == {language}
        assert [topic.sequence for topic in topics] == list(
            range(1, len(topics) + 1)
        )
        assert len({topic.key for topic in topics}) == len(topics)


def test_spanish_source_units_are_separate_from_grammar_categories() -> None:
    source_groups = spanish_grammar_topics_by_source_group()
    categories = spanish_grammar_topics_by_category()

    assert set(source_groups) == {
        "A1 - Unidad 1",
        "A1 - Unidad 2",
        "A1 - Unidad 3",
        "A1 - Unidad 5",
        "A1 - Unidad 6",
        "A1 - Unidad 7",
        "A1 - Unidad 9",
        "A1 - Unidad 10",
        "A1 - Unidad 11",
        "A2 - Unidad 1",
        "A2 - Unidad 2",
        "A2 - Unidad 3",
        "A2 - Unidad 5",
        "A2 - Unidad 6",
        "A2 - Unidad 7",
        "A2 - Unidad 9",
        "A2 - Unidad 10",
    }
    assert "Past tenses" in categories
    assert "Prepositions" in categories
    assert not set(source_groups).intersection(categories)


def test_spanish_eval_items_link_to_catalogue_topics() -> None:
    evaluation = json.loads(
        (ROOT / "eval" / "spanish_grammar_eval_set.json").read_text()
    )

    assert len(evaluation["items"]) == 42
    assert sum(item["is_correct"] for item in evaluation["items"]) == 21
    assert {item["level"] for item in evaluation["items"]} == {"A1", "A2"}
    assert [item["id"] for item in evaluation["items"]] == list(range(1, 43))
    for item in evaluation["items"]:
        topic = spanish_grammar_topic_by_key(item["topic_key"])
        assert topic is not None
        assert topic.level == item["level"]


def test_topic_lookups_use_ordered_catalogues() -> None:
    assert grammar_topic_by_key(GRAMMAR_TOPICS[-1].key) == GRAMMAR_TOPICS[-1]
    assert (
        spanish_grammar_topic_by_key(SPANISH_GRAMMAR_TOPICS[-1].key)
        == SPANISH_GRAMMAR_TOPICS[-1]
    )


def test_grammar_reviews_are_shared_across_languages() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        create_grammar_tables(connection)
        columns = {
            row[1]: row
            for row in connection.execute(
                "PRAGMA table_info(grammar_reviews)"
            ).fetchall()
        }
    finally:
        connection.close()

    assert columns["canonical_language"][5] == 1
    assert columns["topic_key"][5] == 2
    assert "introduced_at" in columns


def test_initial_progress_matches_existing_coursework() -> None:
    topics = initially_seen_topics()
    german = [topic for topic in topics if topic.language is GrammarLanguage.GERMAN]
    spanish = [topic for topic in topics if topic.language is GrammarLanguage.SPANISH]

    assert german == list(A1_B1_TOPICS)
    assert B2_C1_TOPICS[0] not in german
    assert len(spanish) == 61
    assert spanish[-1].key == "es_a2_u6_affirmative_imperative"
    assert A2_SPANISH_GRAMMAR_TOPICS[18] not in spanish


def test_initial_progress_is_seeded_once_without_overwriting_reviews() -> None:
    connection = sqlite3.connect(":memory:")
    introduced_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    try:
        create_grammar_tables(connection)
        connection.execute(
            """
            INSERT INTO grammar_reviews (
                canonical_language, topic_key, introduced_at,
                repetitions, consecutive_correct
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "spanish",
                "es_a1_u1_definite_articles",
                "2026-01-01T00:00:00+00:00",
                2,
                2,
            ),
        )
        seed_initial_grammar_progress(connection, introduced_at=introduced_at)
        counts = dict(
            connection.execute(
                """
                SELECT canonical_language, COUNT(*)
                FROM grammar_reviews GROUP BY canonical_language
                """
            ).fetchall()
        )
        preserved = connection.execute(
            """
            SELECT introduced_at, repetitions
            FROM grammar_reviews
            WHERE canonical_language = 'spanish'
              AND topic_key = 'es_a1_u1_definite_articles'
            """
        ).fetchone()
        connection.execute(
            """
            DELETE FROM grammar_reviews
            WHERE canonical_language = 'spanish'
              AND topic_key = 'es_a1_u1_gender_of_nouns'
            """
        )
        seed_initial_grammar_progress(connection, introduced_at=introduced_at)
        deleted_stays_new = connection.execute(
            """
            SELECT 1 FROM grammar_reviews
            WHERE canonical_language = 'spanish'
              AND topic_key = 'es_a1_u1_gender_of_nouns'
            """
        ).fetchone()
    finally:
        connection.close()

    assert counts == {"german": 12, "spanish": 61}
    assert preserved == ("2026-01-01T00:00:00+00:00", 2)
    assert deleted_stays_new is None


def test_grammar_status_distinguishes_new_seen_and_mastery() -> None:
    assert grammar_topic_status(
        introduced=False,
        schedule=ScheduleState(),
    ) is GrammarTopicStatus.NEW
    assert grammar_topic_status(
        introduced=True,
        schedule=ScheduleState(),
    ) is GrammarTopicStatus.SEEN
    assert grammar_topic_status(
        introduced=True,
        schedule=ScheduleState(lapses=1),
    ) is GrammarTopicStatus.NEEDS_PRACTICE
    assert grammar_topic_status(
        introduced=True,
        schedule=ScheduleState(repetitions=1, consecutive_correct=1),
    ) is GrammarTopicStatus.USUALLY_CORRECT
    assert grammar_topic_status(
        introduced=True,
        schedule=ScheduleState(repetitions=3, consecutive_correct=3),
    ) is GrammarTopicStatus.ALWAYS_CORRECT
