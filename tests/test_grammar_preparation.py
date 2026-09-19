"""Advance generation must save latency without changing the practice schedule."""

import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pdf_language_learner.grammar_revision import (
    GRAMMAR_CYCLE_INTERVAL,
    GrammarExerciseType,
    GrammarGeneratedExercise,
    GrammarGeneratedSession,
    GrammarSessionKind,
)

backend = importlib.import_module("pdf_language_learner.app")


def generated_content(topics):
    return GrammarGeneratedSession(
        rule_summary="A prepared rule explanation.",
        worked_examples=["First example.", "Second example."],
        exercises=[
            GrammarGeneratedExercise(
                topic_key=topics[index % len(topics)].key,
                type=exercise_type,
                instruction="Complete the sentence.",
                prompt=f"Exercise {index}.",
                choices=["correct", "a", "b", "c"]
                if exercise_type is GrammarExerciseType.MULTIPLE_CHOICE else [],
                accepted_answers=["correct"],
                reference_answer="correct",
                grading_rubric="Use the rule.",
                explanation="This follows the rule.",
            )
            for index, exercise_type in enumerate(
                exercise_type for exercise_type in GrammarExerciseType for _ in range(5)
            )
        ],
    )


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    class Clock:
        value = datetime(2026, 9, 14, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.value

    calls = []

    def generate(language, kind, topics, vocabulary):
        calls.append((language, kind, [topic.key for topic in topics], vocabulary))
        return generated_content(topics)

    monkeypatch.setattr(backend, "DATABASE_PATH", tmp_path / "margin.db")
    monkeypatch.setattr(backend, "datetime", Clock)
    monkeypatch.setattr(backend, "generate_grammar_content", generate)
    monkeypatch.setattr(backend, "deterministic_grammar_grade", lambda *args: True)
    return Clock, calls


def close_cycle(language, now):
    with backend.vocabulary_database() as connection:
        connection.execute(
            """
            INSERT INTO grammar_sessions (
                id, canonical_language, kind, topic_keys_json, rule_summary,
                worked_examples_json, created_at, completed_at
            ) VALUES (?, ?, 'review', '[]', '', '[]', ?, ?)
            """,
            (f"closed-{language}", language, now.isoformat(), now.isoformat()),
        )


def play_session(client, language):
    response = client.post("/api/grammar/session", json={"language": language})
    assert response.status_code == 200
    first = response.json()
    for _ in range(first["total"]):
        session = client.post("/api/grammar/session", json={"language": language}).json()
        answer = client.post(
            f"/api/grammar/session/{session['id']}/exercises/{session['exercise']['id']}/answer",
            json={"answer": "correct"},
        )
        assert answer.status_code == 200
    assert answer.json()["session_complete"]
    return first


@pytest.mark.parametrize("language", ["german", "spanish"])
def test_prepared_cycle_stays_locked_then_serves_both_sessions(preparation, language, monkeypatch):
    clock, calls = preparation
    close_cycle(language, clock.value)
    monkeypatch.setattr(backend, "saved_grammar_vocabulary", lambda *args: ["familiar word"])
    with backend.vocabulary_database() as connection:
        progress = [tuple(row) for row in connection.execute("SELECT * FROM grammar_reviews")]
    backend.prepare_upcoming_grammar()
    backend.prepare_upcoming_grammar()  # Includes the same work a restart would discover.
    assert [call[1] for call in calls] == [GrammarSessionKind.LESSON, GrammarSessionKind.REVIEW]
    assert all(call[0] == language and call[3] == ["familiar word"] for call in calls)
    with backend.vocabulary_database() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM grammar_reviews")] == progress
        assert connection.execute("SELECT COUNT(*) FROM grammar_sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM grammar_prepared_content").fetchone()[0] == 2
    client = TestClient(backend.app)
    assert client.post("/api/grammar/session", json={"language": language}).status_code == 404
    clock.value += GRAMMAR_CYCLE_INTERVAL - timedelta(seconds=1)
    assert client.post("/api/grammar/session", json={"language": language}).status_code == 404
    clock.value += timedelta(seconds=1)
    # New vocabulary does not turn a ready lesson into another slow model call.
    monkeypatch.setattr(backend, "saved_grammar_vocabulary", lambda *args: ["newer word"])
    lesson = play_session(client, language)
    review = play_session(client, language)
    assert lesson["kind"] == "lesson"
    assert review["kind"] == "review"
    assert len(review["topics"]) == 3
    assert lesson["topics"][0]["key"] not in {topic["key"] for topic in review["topics"]}
    assert len(calls) == 2
    assert client.post("/api/grammar/session", json={"language": language}).status_code == 404
    with backend.vocabulary_database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM grammar_prepared_content").fetchone()[0] == 0
    backend.prepare_upcoming_grammar()
    assert len(calls) == 4  # Fresh content for the following cycle.


def test_untouched_languages_do_not_generate_on_startup(preparation):
    _, calls = preparation
    backend.prepare_upcoming_grammar()
    assert calls == []


def test_active_first_lesson_prepares_its_review(preparation):
    _, calls = preparation
    client = TestClient(backend.app)
    lesson = client.post("/api/grammar/session", json={"language": "spanish"}).json()
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.LESSON, GrammarSessionKind.REVIEW]
    assert client.post("/api/grammar/session", json={"language": "spanish"}).json()["id"] == lesson["id"]
    play_session(client, "spanish")
    play_session(client, "spanish")
    assert len(calls) == 2


def test_finished_catalogue_prepares_only_reviews(preparation):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    with backend.vocabulary_database() as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO grammar_reviews (canonical_language, topic_key, introduced_at) VALUES (?, ?, ?)",
            [("spanish", topic.key, clock.value.isoformat()) for topic in backend.grammar_catalogue("spanish")],
        )
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.REVIEW]
    clock.value += GRAMMAR_CYCLE_INTERVAL
    assert play_session(TestClient(backend.app), "spanish")["kind"] == "review"
    assert len(calls) == 1


def test_failed_lesson_does_not_lose_ready_review_and_is_retried(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    generate = backend.generate_grammar_content

    def fail_lesson(language, kind, topics, vocabulary):
        if kind is GrammarSessionKind.LESSON:
            raise RuntimeError("provider unavailable")
        return generate(language, kind, topics, vocabulary)

    monkeypatch.setattr(backend, "generate_grammar_content", fail_lesson)
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.REVIEW]
    monkeypatch.setattr(backend, "generate_grammar_content", generate)
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.REVIEW, GrammarSessionKind.LESSON]


def test_missing_preparation_can_be_generated_when_due(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    generate = backend.generate_grammar_content

    def unavailable(*args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(backend, "generate_grammar_content", unavailable)
    backend.prepare_upcoming_grammar()
    clock.value += GRAMMAR_CYCLE_INTERVAL
    client = TestClient(backend.app)
    assert client.post("/api/grammar/session", json={"language": "spanish"}).status_code == 502
    monkeypatch.setattr(backend, "generate_grammar_content", generate)
    assert client.post("/api/grammar/session", json={"language": "spanish"}).status_code == 200
    assert len(calls) == 1


def test_small_review_pool_waits_for_lesson_completion(preparation):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    with backend.vocabulary_database() as connection:
        connection.execute("DELETE FROM grammar_reviews WHERE canonical_language = 'spanish'")
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.LESSON]
    clock.value += GRAMMAR_CYCLE_INTERVAL
    client = TestClient(backend.app)
    lesson = play_session(client, "spanish")
    backend.prepare_upcoming_grammar()
    assert [call[1] for call in calls] == [GrammarSessionKind.LESSON, GrammarSessionKind.REVIEW]
    review = play_session(client, "spanish")
    assert [topic["key"] for topic in review["topics"]] == [topic["key"] for topic in lesson["topics"]]
    assert len(calls) == 2


@pytest.mark.parametrize("invalidation", ["version", "progress", "corrupt"])
def test_invalid_prepared_content_falls_back_to_generation(preparation, monkeypatch, invalidation):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    backend.prepare_upcoming_grammar()
    if invalidation == "version":
        monkeypatch.setattr(backend, "GRAMMAR_CONTENT_VERSION", backend.GRAMMAR_CONTENT_VERSION + 1)
    else:
        with backend.vocabulary_database() as connection:
            if invalidation == "progress":
                connection.execute(
                    "INSERT INTO grammar_reviews (canonical_language, topic_key, introduced_at) VALUES ('spanish', ?, ?)",
                    (calls[0][2][0], clock.value.isoformat()),
                )
            else:
                connection.execute("UPDATE grammar_prepared_content SET content_json = '{}' WHERE kind = 'lesson'")
    clock.value += GRAMMAR_CYCLE_INTERVAL
    response = TestClient(backend.app).post("/api/grammar/session", json={"language": "spanish"})
    assert response.status_code == 200
    assert len(calls) == 3
    if invalidation == "progress":
        assert response.json()["topics"][0]["key"] != calls[0][2][0]


def test_ready_lesson_does_not_wait_for_review_generation(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    generating_review = threading.Event()
    release_review = threading.Event()
    generate = backend.generate_grammar_content

    def slow_review(language, kind, topics, vocabulary):
        if kind is GrammarSessionKind.REVIEW:
            generating_review.set()
            assert release_review.wait(10)
        return generate(language, kind, topics, vocabulary)

    monkeypatch.setattr(backend, "generate_grammar_content", slow_review)
    with ThreadPoolExecutor(max_workers=2) as pool:
        preparation_task = pool.submit(backend.prepare_upcoming_grammar)
        try:
            assert generating_review.wait(10)
            clock.value += GRAMMAR_CYCLE_INTERVAL
            request = pool.submit(
                TestClient(backend.app).post, "/api/grammar/session", json={"language": "spanish"}
            )
            assert request.result(timeout=5).status_code == 200
        finally:
            release_review.set()
        preparation_task.result(timeout=10)
    assert len(calls) == 2


def test_foreground_reuses_in_flight_preparation(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    generating_lesson = threading.Event()
    release_lesson = threading.Event()
    generate = backend.generate_grammar_content

    def slow_lesson(language, kind, topics, vocabulary):
        if kind is GrammarSessionKind.LESSON:
            generating_lesson.set()
            assert release_lesson.wait(10)
        return generate(language, kind, topics, vocabulary)

    monkeypatch.setattr(backend, "generate_grammar_content", slow_lesson)
    with ThreadPoolExecutor(max_workers=3) as pool:
        preparation_task = pool.submit(backend.prepare_upcoming_grammar)
        try:
            assert generating_lesson.wait(10)
            clock.value += GRAMMAR_CYCLE_INTERVAL
            requests = [pool.submit(
                TestClient(backend.app).post, "/api/grammar/session", json={"language": "spanish"}
            ) for _ in range(2)]
        finally:
            release_lesson.set()
        sessions = [request.result(timeout=10).json() for request in requests]
        preparation_task.result(timeout=10)
    assert sessions[0]["id"] == sessions[1]["id"]
    assert sum(call[1] is GrammarSessionKind.LESSON for call in calls) == 1


def test_lifespan_recovers_preparation_without_a_browser(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    monkeypatch.setenv("GRAMMAR_PREGENERATION_ENABLED", "true")
    prepared = threading.Event()
    prepare = backend.prepare_upcoming_grammar

    def observed_prepare(stop=None):
        prepare(stop)
        prepared.set()

    monkeypatch.setattr(backend, "prepare_upcoming_grammar", observed_prepare)
    with TestClient(backend.app):
        assert prepared.wait(10)
    assert len(calls) == 2
    prepared.clear()
    with TestClient(backend.app):
        assert prepared.wait(10)
    assert len(calls) == 2


def test_lifespan_defaults_to_disabled_grammar_pregeneration(preparation, monkeypatch):
    clock, calls = preparation
    close_cycle("spanish", clock.value)
    prepared = threading.Event()

    def observed_prepare(stop=None):
        prepared.set()

    monkeypatch.delenv("GRAMMAR_PREGENERATION_ENABLED", raising=False)
    monkeypatch.setattr(backend, "prepare_upcoming_grammar", observed_prepare)
    with TestClient(backend.app):
        assert not prepared.wait(0.1)
    assert calls == []
