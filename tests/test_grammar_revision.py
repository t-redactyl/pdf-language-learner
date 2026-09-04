import json
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pdf_language_learner.app import app, saved_grammar_vocabulary, select_grammar_topics
from pdf_language_learner.grammar_revision import (
    GrammarExerciseType,
    GrammarGeneratedExercise,
    GrammarSessionKind,
    deterministic_grammar_grade,
    grammar_generation_messages,
    grammar_topic_summary_messages,
    schedule_grammar_review,
)
from pdf_language_learner.revision import ScheduleState
from pdf_language_learner.spanish_grammar_catalogue import SPANISH_GRAMMAR_TOPICS


client = TestClient(app)


def test_grammar_generation_explains_rules_in_english() -> None:
    messages = grammar_generation_messages(
        language="Spanish",
        kind=GrammarSessionKind.LESSON,
        topics=[
            {
                "key": "present-tense",
                "title": "Present tense",
                "level": "A1",
                "example": "Hablo español.",
            }
        ],
        saved_vocabulary=[],
    )

    system_instruction = messages[0]["content"]
    assert "Explain every grammar rule in English" in system_instruction
    assert (
        "rule_summary and every exercise explanation in English"
        in system_instruction
    )
    assert "answerable using only information visible" in system_instruction
    assert "explicitly name its source form" in system_instruction
    assert "past participle of herstellen" in system_instruction
    assert "A blank sentence plus a grammatical description" in system_instruction
    assert "exactly four choices" in system_instruction
    assert "exactly one unambiguously correct choice" in system_instruction
    assert "guided sentence completion or sentence combination" in system_instruction
    assert "list those elements in a deliberately scrambled order" in system_instruction
    assert "Never present them in the target order" in system_instruction
    assert "Translation tasks must name the required construction" in system_instruction
    assert "Return exactly nine exercises" in system_instruction
    assert "three multiple_choice, three fill_blank, and three translation" in system_instruction


def test_grammar_topic_summary_is_brief_english_prose() -> None:
    messages = grammar_topic_summary_messages(
        language="German",
        title="Nebensätze mit weil, wenn, dass",
        category="Nebensätze",
        example="…weil ich Deutsch lernen möchte",
    )

    assert "in English" in messages[0]["content"]
    assert "one very brief, self-contained prose paragraph" in messages[0]["content"]
    assert "Do not use bullets" in messages[0]["content"]
    assert "Nebensätze mit weil, wenn, dass" in messages[1]["content"]


def test_grammar_vocabulary_prefers_most_recently_reviewed_items(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    item_ids = {}
    for word in ("older review", "newer review", "never reviewed"):
        response = client.post(
            "/api/vocabulary",
            json={
                "original_source": word,
                "normalized_source": word,
                "translation": word,
                "source_language": "German",
                "target_language": "English",
            },
        )
        assert response.status_code == 200
        item_ids[word] = response.json()["item"]["id"]

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.executemany(
            """
            UPDATE vocabulary_german
            SET saved_at = ?, last_reviewed_at = ?
            WHERE id = ?
            """,
            (
                ("2026-08-03T12:00:00+00:00", "2026-08-30T12:00:00+00:00", item_ids["older review"]),
                ("2026-08-01T12:00:00+00:00", "2026-09-01T12:00:00+00:00", item_ids["newer review"]),
                ("2026-09-02T12:00:00+00:00", None, item_ids["never reviewed"]),
            ),
        )

        assert saved_grammar_vocabulary(connection, "German") == [
            "newer review",
            "older review",
        ]

        connection.execute("UPDATE vocabulary_german SET last_reviewed_at = NULL")
        assert saved_grammar_vocabulary(connection, "German") == [
            "never reviewed",
            "older review",
            "newer review",
        ]


def test_grammar_scheduler_uses_topic_level_intervals() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    first = schedule_grammar_review(ScheduleState(), correct=True, reviewed_at=now)
    second = schedule_grammar_review(first, correct=True, reviewed_at=now)
    missed = schedule_grammar_review(second, correct=False, reviewed_at=now)

    assert (first.next_review_at - now).days == 3
    assert (second.next_review_at - now).days == 7
    assert (missed.next_review_at - now).days == 2
    assert missed.consecutive_correct == 0


def test_scheduled_grammar_review_includes_only_three_seen_topics(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    client.get("/api/grammar/topics", params={"language": "Spanish"})
    completed_at = "2026-08-01T12:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.executemany(
            """
            INSERT INTO grammar_sessions (
                id, canonical_language, kind, topic_keys_json, rule_summary,
                worked_examples_json, created_at, completed_at
            ) VALUES (?, 'spanish', 'lesson', '[]', '', '[]', ?, ?)
            """,
            (
                ("completed-lesson-1", completed_at, completed_at),
                ("completed-lesson-2", completed_at, completed_at),
            ),
        )
        selection = select_grammar_topics(
            connection,
            "Spanish",
            datetime(2026, 9, 1, tzinfo=UTC),
        )

    assert selection is not None
    kind, topics = selection
    assert kind is GrammarSessionKind.REVIEW
    assert len(topics) == 3
    seen_topic_keys = {topic.key for topic in SPANISH_GRAMMAR_TOPICS[:61]}
    assert {topic.key for topic in topics} <= seen_topic_keys


def test_grammar_review_prompt_forbids_new_topics() -> None:
    topics = [
        {
            "key": topic.key,
            "title": topic.title,
            "level": topic.level.value,
            "example": topic.example,
        }
        for topic in SPANISH_GRAMMAR_TOPICS[:3]
    ]

    messages = grammar_generation_messages(
        language="Spanish",
        kind=GrammarSessionKind.REVIEW,
        topics=topics,
        saved_vocabulary=[],
    )

    assert "review-only session" in messages[1]["content"]
    assert (
        "do not introduce or teach any additional grammar topic"
        in messages[1]["content"]
    )


def test_closed_grammar_grading_normalizes_punctuation() -> None:
    assert deterministic_grammar_grade(
        GrammarExerciseType.FILL_BLANK,
        "  Hablo. ",
        ["hablo"],
        "Hablo",
    ) is True
    assert deterministic_grammar_grade(
        GrammarExerciseType.TRANSLATION,
        "Hablo",
        [],
        "Hablo",
    ) is None


def test_grammar_lesson_is_resumable_and_introduced_only_on_completion(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    next_topic = SPANISH_GRAMMAR_TOPICS[61]
    calls = []
    grading_token_budgets = []

    def fake_structured(operation, **kwargs):
        calls.append(operation)
        if operation == "grammar answer grading":
            grading_token_budgets.append(kwargs["max_output_tokens"])
            return json.dumps({"correct": True, "feedback": "The target form is correct."})
        if operation == "grammar topic summary":
            return json.dumps({"summary": "Use this form to express the core rule."})
        exercises = {}
        exercise_slots = (
            ("multiple_choice_1", GrammarExerciseType.MULTIPLE_CHOICE),
            ("multiple_choice_2", GrammarExerciseType.MULTIPLE_CHOICE),
            ("multiple_choice_3", GrammarExerciseType.MULTIPLE_CHOICE),
            ("fill_blank_1", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_2", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_3", GrammarExerciseType.FILL_BLANK),
            ("translation_1", GrammarExerciseType.TRANSLATION),
            ("translation_2", GrammarExerciseType.TRANSLATION),
            ("translation_3", GrammarExerciseType.TRANSLATION),
        )
        for slot, exercise_type in exercise_slots:
            exercises[slot] = {
                "topic_key": next_topic.key,
                "instruction": "Use the target grammar.",
                "prompt": "Complete the task.",
                "choices": ["correct", "other", "another", "last"]
                if exercise_type is GrammarExerciseType.MULTIPLE_CHOICE
                else [],
                "accepted_answers": ["correct"],
                "reference_answer": "correct",
                "grading_rubric": "The target structure must be correct.",
                "explanation": "This uses the target structure.",
            }
        return json.dumps(
            {
                "rule_summary": "A concise explanation.",
                "rule_tables": [
                    {
                        "title": "Present tense",
                        "headers": ["Person", "Form"],
                        "rows": [["yo", "hablo"], ["tú", "hablas"]],
                    }
                ],
                "worked_examples": ["Example one.", "Example two."],
                **exercises,
            }
        )

    monkeypatch.setattr(
        "pdf_language_learner.app.anthropic_structured_model_response",
        fake_structured,
    )
    client.get("/api/grammar/topics", params={"language": "Spanish"})
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO grammar_sessions (
                id, canonical_language, kind, topic_keys_json, rule_summary,
                worked_examples_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-unfinished-session",
                "spanish",
                "lesson",
                json.dumps([next_topic.key]),
                "Old explanation.",
                "[]",
                "2026-08-01T12:00:00+00:00",
            ),
        )
    response = client.post("/api/grammar/session", json={"language": "Spanish"})
    assert response.status_code == 200
    session = response.json()
    assert session["id"] != "legacy-unfinished-session"
    assert session["kind"] == "lesson"
    assert session["topics"][0]["key"] == next_topic.key
    assert session["rule_tables"] == [
        {
            "title": "Present tense",
            "headers": ["Person", "Form"],
            "rows": [["yo", "hablo"], ["tú", "hablas"]],
        }
    ]
    assert "accepted_answers" not in session["exercise"]
    assert session["topics"][0]["summary"] is None

    summary_url = (
        f"/api/grammar/session/{session['id']}/topics/{next_topic.key}/summary"
    )
    first_summary = client.post(summary_url)
    second_summary = client.post(summary_url)
    assert first_summary.status_code == 200
    assert first_summary.json() == {
        "summary": "Use this form to express the core rule."
    }
    assert second_summary.json() == first_summary.json()
    assert calls.count("grammar topic summary") == 1
    with sqlite3.connect(database) as connection:
        cached = connection.execute(
            """
            SELECT summary FROM grammar_topic_summaries
            WHERE canonical_language = ? AND topic_key = ?
            """,
            ("spanish", next_topic.key),
        ).fetchone()
        assert cached == (first_summary.json()["summary"],)
        connection.execute(
            "UPDATE grammar_sessions SET topic_summaries_json = '{}' WHERE id = ?",
            (session["id"],),
        )

    resumed = client.post("/api/grammar/session", json={"language": "Spanish"}).json()
    assert resumed["id"] == session["id"]
    assert resumed["topics"][0]["summary"] == first_summary.json()["summary"]
    assert calls.count("grammar session generation") == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM grammar_reviews WHERE topic_key = ?", (next_topic.key,)
        ).fetchone() is None

    exercise_types = []
    for _ in range(9):
        current = client.post(
            "/api/grammar/session", json={"language": "Spanish"}
        ).json()
        exercise = current["exercise"]
        exercise_types.append(exercise["type"])
        result = client.post(
            f"/api/grammar/session/{current['id']}/exercises/{exercise['id']}/answer",
            json={"answer": "correct"},
        )
        assert result.status_code == 200
    assert result.json()["session_complete"] is True
    assert exercise_types == [
        "multiple_choice",
        "multiple_choice",
        "multiple_choice",
        "fill_blank",
        "fill_blank",
        "fill_blank",
        "translation",
        "translation",
        "translation",
    ]
    assert calls.count("grammar answer grading") == 3
    assert grading_token_budgets == [1000, 1000, 1000]
    with sqlite3.connect(database) as connection:
        progress = connection.execute(
            "SELECT repetitions, lapses FROM grammar_reviews WHERE topic_key = ?",
            (next_topic.key,),
        ).fetchone()
    assert progress == (1, 0)


def test_grammar_topics_distinguish_seen_and_new(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", tmp_path / "margin.db")
    topics = client.get("/api/grammar/topics", params={"language": "Spanish"}).json()

    assert topics[60]["status"] == "seen"
    assert topics[61]["status"] == "new"
