import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pdf_language_learner.app import app, saved_grammar_vocabulary, select_grammar_topics
from pdf_language_learner.grammar_revision import (
    GRAMMAR_CYCLE_INTERVAL,
    GRAMMAR_REVIEW_TOPIC_LIMIT,
    GRAMMAR_RULE_TABLE_LIMIT,
    GrammarCycleStage,
    GrammarExerciseType,
    GrammarGeneratedExercise,
    GrammarGeneratedSession,
    GrammarGenerationResponse,
    GrammarSessionKind,
    deterministic_grammar_grade,
    grammar_cycle_stage,
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
    assert "conjugation tasks must show the target pronoun" in system_instruction
    assert "tú, usted, or ustedes" in system_instruction
    assert "exactly four choices" in system_instruction
    assert "exactly one unambiguously correct choice" in system_instruction
    assert "guided sentence completion or sentence combination" in system_instruction
    assert "list those elements in a deliberately scrambled order" in system_instruction
    assert "Never present them in the target order" in system_instruction
    assert "Translation tasks must name the required construction" in system_instruction
    assert "Return exactly fifteen exercises" in system_instruction
    assert "five multiple_choice, five fill_blank, and five translation" in system_instruction


def test_rule_table_limit_is_sent_to_the_model_and_not_only_checked() -> None:
    """A cap the model never sees can only reject a response already paid for.

    The provider schema is built from GrammarGenerationResponse, so a limit set
    only on GrammarGeneratedSession shapes nothing and fails late instead.
    """

    sent = GrammarGenerationResponse.model_json_schema()["properties"]["rule_tables"]
    validated = GrammarGeneratedSession.model_json_schema()["properties"]["rule_tables"]

    assert sent.get("maxItems") == GRAMMAR_RULE_TABLE_LIMIT
    assert validated.get("maxItems") == GRAMMAR_RULE_TABLE_LIMIT
    assert sent == validated


def test_rule_tables_fit_a_three_pattern_paradigm() -> None:
    """German adjective declension needs one table per article pattern."""

    table = {
        "title": "Adjektivendungen",
        "headers": ["Kasus", "maskulin"],
        "rows": [["Nominativ", "-e"]],
    }
    exercise = {
        "topic_key": "a1b1_nominativ_akkusativ_dativ_adjektivdeklination",
        "instruction": "Use the target grammar.",
        "prompt": "Complete the task.",
        "choices": ["netter", "nette", "netten", "nettes"],
        "accepted_answers": ["netter"],
        "reference_answer": "netter",
        "grading_rubric": "The ending must be correct.",
        "explanation": "Strong ending after no article.",
    }
    payload = {
        "rule_summary": "Adjective endings depend on the preceding article.",
        "worked_examples": ["Ein netter Mann.", "Der nette Mann."],
        **{
            slot: dict(exercise, choices=exercise["choices"] if mc else [])
            for slot, mc in (
                ("multiple_choice_1", True), ("multiple_choice_2", True),
                ("multiple_choice_3", True), ("multiple_choice_4", True),
                ("multiple_choice_5", True), ("fill_blank_1", False),
                ("fill_blank_2", False), ("fill_blank_3", False),
                ("fill_blank_4", False), ("fill_blank_5", False),
                ("translation_1", False), ("translation_2", False),
                ("translation_3", False), ("translation_4", False),
                ("translation_5", False),
            )
        },
    }

    session = GrammarGenerationResponse.model_validate(
        {**payload, "rule_tables": [table] * GRAMMAR_RULE_TABLE_LIMIT}
    ).to_generated_session()
    assert len(session.rule_tables) == GRAMMAR_RULE_TABLE_LIMIT

    # One past the limit is still refused, and refused before the model call.
    with pytest.raises(ValidationError):
        GrammarGenerationResponse.model_validate(
            {**payload, "rule_tables": [table] * (GRAMMAR_RULE_TABLE_LIMIT + 1)}
        )


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


def test_grammar_cycle_stage_alternates_lesson_and_review() -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)

    # Nothing studied yet, so the cycle opens with a new topic.
    assert grammar_cycle_stage(
        last_completed_lesson_at=None,
        last_completed_review_at=None,
        last_completed_session_at=None,
        now=now,
    ) is GrammarCycleStage.LESSON

    # A lesson with no review after it owes that review, however long it waits.
    lesson_at = now - timedelta(days=9)
    assert grammar_cycle_stage(
        last_completed_lesson_at=lesson_at,
        last_completed_review_at=lesson_at - timedelta(days=3),
        last_completed_session_at=lesson_at,
        now=now,
    ) is GrammarCycleStage.REVIEW

    # A closed cycle locks grammar until the interval has passed.
    closed_at = now - GRAMMAR_CYCLE_INTERVAL + timedelta(minutes=1)
    assert grammar_cycle_stage(
        last_completed_lesson_at=closed_at - timedelta(minutes=30),
        last_completed_review_at=closed_at,
        last_completed_session_at=closed_at,
        now=now,
    ) is GrammarCycleStage.LOCKED
    assert grammar_cycle_stage(
        last_completed_lesson_at=closed_at - timedelta(minutes=30),
        last_completed_review_at=closed_at,
        last_completed_session_at=closed_at - timedelta(minutes=1),
        now=now,
    ) is GrammarCycleStage.LESSON


def test_grammar_cycle_interval_is_anchored_on_any_session_kind() -> None:
    """A retired session kind must still delay the next lesson."""

    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    old = now - timedelta(days=30)

    assert grammar_cycle_stage(
        last_completed_lesson_at=old,
        last_completed_review_at=old,
        last_completed_session_at=now - timedelta(hours=1),
        now=now,
    ) is GrammarCycleStage.LOCKED


def test_grammar_cycle_stage_requires_an_aware_now() -> None:
    with pytest.raises(ValueError, match="timezone"):
        grammar_cycle_stage(
            last_completed_lesson_at=None,
            last_completed_review_at=None,
            last_completed_session_at=None,
            now=datetime(2026, 9, 5, 12),
        )


def grammar_session_kinds_over_one_visit(
    connection: sqlite3.Connection, language: str, now: datetime, visits: int
) -> list[str | None]:
    """Ask for `visits` sessions at one instant, completing each one served."""

    kinds: list[str | None] = []
    for index in range(visits):
        selection = select_grammar_topics(connection, language, now)
        if selection is None:
            kinds.append(None)
            continue
        kind, topics = selection
        kinds.append(kind.value)
        connection.execute(
            """
            INSERT INTO grammar_sessions (
                id, canonical_language, kind, topic_keys_json, rule_summary,
                worked_examples_json, created_at, completed_at
            ) VALUES (?, ?, ?, ?, '', '[]', ?, ?)
            """,
            (
                f"session-{index}",
                language,
                kind.value,
                json.dumps([topic.key for topic in topics]),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        # A completed lesson introduces the topic it taught.
        if kind is GrammarSessionKind.LESSON:
            connection.executemany(
                """
                INSERT OR IGNORE INTO grammar_reviews (
                    canonical_language, topic_key, introduced_at
                ) VALUES (?, ?, ?)
                """,
                ((language, topic.key, now.isoformat()) for topic in topics),
            )
    return kinds


def test_grammar_cycle_serves_one_lesson_then_one_review_then_locks(
    tmp_path, monkeypatch
) -> None:
    """Regression: lessons used to be ungated and reviews were never reached."""

    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    client.get("/api/grammar/topics", params={"language": "Spanish"})
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert grammar_session_kinds_over_one_visit(
            connection, "spanish", now, 5
        ) == ["lesson", "review", None, None, None]

        # A day early is still locked; the interval reopens the cycle.
        assert select_grammar_topics(
            connection, "spanish", now + timedelta(days=1)
        ) is None
        reopened = select_grammar_topics(
            connection, "spanish", now + GRAMMAR_CYCLE_INTERVAL
        )
        assert reopened is not None
        assert reopened[0] is GrammarSessionKind.LESSON


def test_grammar_review_excludes_the_freshly_taught_topic(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    client.get("/api/grammar/topics", params={"language": "Spanish"})
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    taught = SPANISH_GRAMMAR_TOPICS[61]

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert grammar_session_kinds_over_one_visit(
            connection, "spanish", now, 1
        ) == ["lesson"]
        selection = select_grammar_topics(connection, "spanish", now)

    assert selection is not None
    kind, topics = selection
    assert kind is GrammarSessionKind.REVIEW
    assert len(topics) == GRAMMAR_REVIEW_TOPIC_LIMIT
    assert taught.key not in {topic.key for topic in topics}


def test_grammar_review_is_formed_even_when_no_topic_is_due(
    tmp_path, monkeypatch
) -> None:
    """An owed review must never come back empty.

    Restricting the review to `is_due` topics would deadlock the cycle: the
    review could not be built, so it could not complete, so the language would
    never advance past the review stage again.
    """

    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    client.get("/api/grammar/topics", params={"language": "Spanish"})
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            INSERT INTO grammar_sessions (
                id, canonical_language, kind, topic_keys_json, rule_summary,
                worked_examples_json, created_at, completed_at
            ) VALUES ('owed', 'spanish', 'lesson', '[]', '', '[]', ?, ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            UPDATE grammar_reviews
            SET last_reviewed_at = ?, next_review_at = '2999-01-01T00:00:00+00:00',
                repetitions = 1
            WHERE canonical_language = 'spanish'
            """,
            (now.isoformat(),),
        )
        selection = select_grammar_topics(connection, "spanish", now)

    assert selection is not None
    kind, topics = selection
    assert kind is GrammarSessionKind.REVIEW
    assert len(topics) == GRAMMAR_REVIEW_TOPIC_LIMIT


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
            ("multiple_choice_4", GrammarExerciseType.MULTIPLE_CHOICE),
            ("multiple_choice_5", GrammarExerciseType.MULTIPLE_CHOICE),
            ("fill_blank_1", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_2", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_3", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_4", GrammarExerciseType.FILL_BLANK),
            ("fill_blank_5", GrammarExerciseType.FILL_BLANK),
            ("translation_1", GrammarExerciseType.TRANSLATION),
            ("translation_2", GrammarExerciseType.TRANSLATION),
            ("translation_3", GrammarExerciseType.TRANSLATION),
            ("translation_4", GrammarExerciseType.TRANSLATION),
            ("translation_5", GrammarExerciseType.TRANSLATION),
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
        "pdf_language_learner.app.grammar_structured_model_response",
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
    for _ in range(15):
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
        "multiple_choice",
        "multiple_choice",
        "fill_blank",
        "fill_blank",
        "fill_blank",
        "fill_blank",
        "fill_blank",
        "translation",
        "translation",
        "translation",
        "translation",
        "translation",
    ]
    assert calls.count("grammar answer grading") == 5
    assert grading_token_budgets == [1000] * 5
    with sqlite3.connect(database) as connection:
        progress = connection.execute(
            "SELECT repetitions, lapses FROM grammar_reviews WHERE topic_key = ?",
            (next_topic.key,),
        ).fetchone()
    assert progress == (1, 0)


def test_finished_lesson_hands_straight_over_to_its_review(
    tmp_path, monkeypatch
) -> None:
    """The client is told a review is queued, then served it."""

    database = tmp_path / "margin.db"
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database)
    generated_kinds = []

    def fake_structured(operation, **kwargs):
        if operation == "grammar answer grading":
            return json.dumps({"correct": True, "feedback": "Correct."})
        # The prompt opens "Create a <kind> session."
        generated_kinds.append(kwargs["messages"][1]["content"].split()[2])
        topic_keys = [
            line.split(":")[0].removeprefix("- ").strip()
            for line in kwargs["messages"][1]["content"].splitlines()
            if line.startswith("- ")
        ]
        slots = (
            "multiple_choice_1", "multiple_choice_2", "multiple_choice_3",
            "multiple_choice_4", "multiple_choice_5", "fill_blank_1",
            "fill_blank_2", "fill_blank_3", "fill_blank_4", "fill_blank_5",
            "translation_1", "translation_2", "translation_3",
            "translation_4", "translation_5",
        )
        return json.dumps(
            {
                "rule_summary": "A concise explanation.",
                "rule_tables": [],
                "worked_examples": ["Example one.", "Example two."],
                **{
                    slot: {
                        # Spread the fifteen exercises evenly over the topics given.
                        "topic_key": topic_keys[index % len(topic_keys)],
                        "instruction": "Use the target grammar.",
                        "prompt": "Complete the task.",
                        "choices": ["correct", "other", "another", "last"]
                        if slot.startswith("multiple_choice")
                        else [],
                        "accepted_answers": ["correct"],
                        "reference_answer": "correct",
                        "grading_rubric": "The target structure must be correct.",
                        "explanation": "This uses the target structure.",
                    }
                    for index, slot in enumerate(slots)
                },
            }
        )

    monkeypatch.setattr(
        "pdf_language_learner.app.grammar_structured_model_response",
        fake_structured,
    )

    def play_through_session() -> dict:
        session = client.post(
            "/api/grammar/session", json={"language": "Spanish"}
        ).json()
        result = {}
        for _ in range(session["total"]):
            current = client.post(
                "/api/grammar/session", json={"language": "Spanish"}
            ).json()
            result = client.post(
                f"/api/grammar/session/{current['id']}"
                f"/exercises/{current['exercise']['id']}/answer",
                json={"answer": "correct"},
            ).json()
        return {"kind": session["kind"], "topics": session["topics"], **result}

    lesson = play_through_session()
    assert lesson["kind"] == "lesson"
    assert len(lesson["topics"]) == 1
    assert lesson["session_complete"] is True
    assert lesson["conjugation_topic_keys"] == [
        "es_a2_u7_negative_imperative"
    ]
    # The client uses this to offer "Continue to review" instead of "Finish".
    assert lesson["next_session_kind"] == GrammarSessionKind.REVIEW.value

    review = play_through_session()
    assert review["kind"] == "review"
    assert len(review["topics"]) == GRAMMAR_REVIEW_TOPIC_LIMIT
    # Every reviewed rule offers its own explanation in the session payload.
    assert all("summary" in topic for topic in review["topics"])
    # The cycle is closed, so the sitting ends here.
    assert review["next_session_kind"] is None
    assert isinstance(review["conjugation_topic_keys"], list)
    assert client.post(
        "/api/grammar/session", json={"language": "Spanish"}
    ).status_code == 404
    assert generated_kinds == ["lesson", "review"]


def test_grammar_topics_distinguish_seen_and_new(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", tmp_path / "margin.db")
    topics = client.get("/api/grammar/topics", params={"language": "Spanish"}).json()

    assert topics[60]["status"] == "seen"
    assert topics[61]["status"] == "new"
