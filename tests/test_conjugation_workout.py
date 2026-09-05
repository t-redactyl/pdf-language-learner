import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from pdf_language_learner.app import app
from pdf_language_learner.conjugation_workout import (
    CONJUGATION_ITEMS,
    CONJUGATION_ITEMS_BY_KEY,
    CONJUGATION_TOPIC_KEYS,
    grade_conjugation,
    schedule_conjugation,
    validate_conjugation_inventory,
)
from pdf_language_learner.german_grammar_catalogue import GRAMMAR_TOPICS
from pdf_language_learner.revision import ScheduleState
from pdf_language_learner.spanish_grammar_catalogue import SPANISH_GRAMMAR_TOPICS


client = TestClient(app)


def test_inventory_is_stable_unique_and_backed_by_the_two_catalogues() -> None:
    validate_conjugation_inventory((*GRAMMAR_TOPICS, *SPANISH_GRAMMAR_TOPICS))

    assert len(CONJUGATION_ITEMS) == len(CONJUGATION_ITEMS_BY_KEY)
    assert len(CONJUGATION_ITEMS) == 441
    assert all(item.answers for item in CONJUGATION_ITEMS)
    assert {
        "a1b1_praeteritum_perfekt",
        "b2c1_konjunktiv2_gegenwart_formen",
        "b2c1_passiv_in_allen_zeiten",
        "b2c1_ueberblick_zeiten",
        "es_a1_u1_regular_ar_verbs",
        "es_a1_u11_indefinido",
        "es_a2_u3_imperfect_tense",
        "es_a2_u6_affirmative_imperative",
        "es_a2_u7_negative_imperative",
        "es_a2_u9_future_tense",
        "es_a2_u10_conditional",
    } <= CONJUGATION_TOPIC_KEYS


def test_grading_preserves_spanish_accents() -> None:
    item = next(
        item
        for item in CONJUGATION_ITEMS
        if item.lemma == "estudiar" and item.person == "vosotros/as"
    )

    assert grade_conjugation(item, "  ESTUDIÁIS. ") is True
    assert grade_conjugation(item, "estudiais") is False


def test_wrong_form_retries_now_and_correct_form_starts_short_interval() -> None:
    reviewed_at = datetime(2026, 9, 5, 12, tzinfo=UTC)
    wrong = schedule_conjugation(
        ScheduleState(), correct=False, reviewed_at=reviewed_at
    )
    assert wrong.lapses == 1
    assert wrong.next_review_at == reviewed_at

    recovered = schedule_conjugation(wrong, correct=True, reviewed_at=reviewed_at)
    assert recovered.consecutive_correct == 1
    assert recovered.next_review_at == reviewed_at + timedelta(days=1)


def test_conjugation_api_interleaves_topics_and_schedules_each_form(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)

    response = client.get(
        "/api/conjugation/session", params={"language": "Spanish", "limit": 20}
    )
    assert response.status_code == 200
    session = response.json()
    assert len(session["cards"]) == 20
    # Only the 17 verb topics in the learner's pre-existing Spanish progress
    # are unlocked; later catalogue topics stay out of the workout.
    assert len({card["topic_key"] for card in session["cards"]}) == 17
    assert "es_a2_u7_negative_imperative" not in {
        card["topic_key"] for card in session["cards"]
    }
    assert all("reference_answer" not in card for card in session["cards"])

    card = session["cards"][0]
    expected = CONJUGATION_ITEMS_BY_KEY[card["key"]].reference_answer
    wrong = client.post(
        f"/api/conjugation/items/{card['key']}/answer", json={"answer": "wrong"}
    )
    assert wrong.status_code == 200
    assert wrong.json()["retry_now"] is True
    assert wrong.json()["reference_answer"] == expected

    retried = client.get(
        "/api/conjugation/session", params={"language": "Spanish", "limit": 1}
    ).json()
    assert retried["cards"][0]["key"] == card["key"]

    correct = client.post(
        f"/api/conjugation/items/{card['key']}/answer", json={"answer": expected}
    )
    assert correct.json()["correct"] is True
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT repetitions, lapses FROM conjugation_reviews WHERE item_key = ?",
            (card["key"],),
        ).fetchone()
    assert row == (1, 1)


def test_later_conjugations_unlock_with_their_grammar_topic(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    topic_key = "es_a2_u7_negative_imperative"
    item = next(item for item in CONJUGATION_ITEMS if item.topic_key == topic_key)

    locked = client.get(
        "/api/conjugation/session",
        params={"language": "Spanish", "topics": topic_key, "limit": 8},
    )
    assert locked.status_code == 409
    assert client.post(
        f"/api/conjugation/items/{item.key}/answer", json={"answer": item.reference_answer}
    ).status_code == 409

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO grammar_reviews (
                canonical_language, topic_key, introduced_at
            ) VALUES ('spanish', ?, ?)
            """,
            (topic_key, datetime.now(UTC).isoformat()),
        )

    workout = client.get(
        "/api/conjugation/session",
        params={"language": "Spanish", "topics": topic_key, "limit": 8},
    )
    assert workout.status_code == 200
    assert len(workout.json()["cards"]) == 8
    assert {card["topic_key"] for card in workout.json()["cards"]} == {topic_key}


def test_conjugation_topics_endpoint_reports_the_audited_inventory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", tmp_path / "margin.db")

    topics = client.get(
        "/api/conjugation/topics", params={"language": "German"}
    ).json()
    assert sum(topic["forms"] for topic in topics) == 244
    assert {topic["key"] for topic in topics} == {
        item.topic_key for item in CONJUGATION_ITEMS if item.language.value == "german"
    }
    assert any(topic["unlocked"] for topic in topics)
    assert any(not topic["unlocked"] for topic in topics)
