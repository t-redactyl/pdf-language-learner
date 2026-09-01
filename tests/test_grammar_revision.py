import json
import sqlite3
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from pdf_language_learner.app import app
from pdf_language_learner.grammar_revision import (
    GrammarExerciseType,
    GrammarSessionKind,
    deterministic_grammar_grade,
    grammar_generation_messages,
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
    assert "accurate, self-contained, and internally consistent" in system_instruction
    assert "hablo -> habl- -> no hables" in system_instruction
    assert "include a rule_table when a compact table" in system_instruction
    assert "do not embed Markdown tables" in system_instruction


def test_grammar_scheduler_uses_topic_level_intervals() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    first = schedule_grammar_review(ScheduleState(), correct=True, reviewed_at=now)
    second = schedule_grammar_review(first, correct=True, reviewed_at=now)
    missed = schedule_grammar_review(second, correct=False, reviewed_at=now)

    assert (first.next_review_at - now).days == 3
    assert (second.next_review_at - now).days == 7
    assert (missed.next_review_at - now).days == 1
    assert missed.consecutive_correct == 0


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

    def fake_structured(operation, **kwargs):
        calls.append(operation)
        if operation == "grammar answer grading":
            return json.dumps({"correct": True, "feedback": "The target form is correct."})
        exercises = []
        for exercise_type in GrammarExerciseType:
            exercises.append(
                {
                    "topic_key": next_topic.key,
                    "type": exercise_type.value,
                    "instruction": "Use the target grammar.",
                    "prompt": "Complete the task.",
                    "choices": ["correct", "other", "another"] if exercise_type is GrammarExerciseType.MULTIPLE_CHOICE else [],
                    "tokens": ["correct"] if exercise_type is GrammarExerciseType.ORDERING else [],
                    "accepted_answers": ["correct"],
                    "reference_answer": "correct",
                    "grading_rubric": "The target structure must be correct.",
                    "explanation": "This uses the target structure.",
                }
            )
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
                "exercises": exercises,
            }
        )

    monkeypatch.setattr(
        "pdf_language_learner.app.structured_model_response", fake_structured
    )
    response = client.post("/api/grammar/session", json={"language": "Spanish"})
    assert response.status_code == 200
    session = response.json()
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

    resumed = client.post("/api/grammar/session", json={"language": "Spanish"}).json()
    assert resumed["id"] == session["id"]
    assert calls.count("grammar session generation") == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM grammar_reviews WHERE topic_key = ?", (next_topic.key,)
        ).fetchone() is None

    for _ in range(6):
        current = client.post(
            "/api/grammar/session", json={"language": "Spanish"}
        ).json()
        exercise = current["exercise"]
        result = client.post(
            f"/api/grammar/session/{current['id']}/exercises/{exercise['id']}/answer",
            json={"answer": "correct"},
        )
        assert result.status_code == 200
    assert result.json()["session_complete"] is True
    assert calls.count("grammar answer grading") == 3
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
