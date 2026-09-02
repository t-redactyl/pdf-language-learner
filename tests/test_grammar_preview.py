from datetime import UTC, datetime

import pytest

from pdf_language_learner.grammar_preview import (
    GrammarPreviewResult,
    prompt_fingerprint,
    render_preview_report,
    select_preview_topics,
    write_preview_report,
)
from pdf_language_learner.grammar_revision import (
    GrammarExerciseType,
    GrammarGeneratedExercise,
    GrammarGeneratedSession,
    GrammarRuleTable,
)
from pdf_language_learner.grammar_topics import (
    GrammarLanguage,
    GrammarLevel,
    GrammarTopic,
)


def topic(
    key: str,
    *,
    level: GrammarLevel = GrammarLevel.A2,
    category: str = "Verbs",
) -> GrammarTopic:
    return GrammarTopic(
        key=key,
        language=GrammarLanguage.SPANISH,
        book="test-book",
        level=level,
        category=category,
        title=f"Topic <{key}>",
        example="Hablo español.",
        sequence=1,
    )


def generated_session() -> GrammarGeneratedSession:
    exercise_types = (
        GrammarExerciseType.FILL_BLANK,
        GrammarExerciseType.FILL_BLANK,
        GrammarExerciseType.ORDERING,
        GrammarExerciseType.ORDERING,
        GrammarExerciseType.TRANSLATION,
        GrammarExerciseType.TRANSLATION,
        GrammarExerciseType.PRODUCTION,
    )
    exercises = [
        GrammarGeneratedExercise(
            topic_key="present",
            type=exercise_type,
            instruction="Use the present tense.",
            prompt="Complete <this> sentence.",
            choices=["hablo", "hablas", "habla"]
            if exercise_type is GrammarExerciseType.MULTIPLE_CHOICE
            else [],
            tokens=["Yo", "hablo"]
            if exercise_type is GrammarExerciseType.ORDERING
            else [],
            accepted_answers=["Hablo."],
            reference_answer="Hablo.",
            grading_rubric="The verb must agree with yo.",
            explanation="The -o ending marks first-person singular.",
        )
        for exercise_type in exercise_types
    ]
    return GrammarGeneratedSession(
        rule_summary="Never render <script>alert('x')</script> as HTML.",
        rule_tables=[
            GrammarRuleTable(
                title="Present tense",
                headers=["Person", "Form"],
                rows=[["yo", "hablo"], ["tú", "hablas"]],
            )
        ],
        worked_examples=["Yo hablo.", "Tú hablas."],
        exercises=exercises,
    )


def test_select_preview_topics_intersects_filters_and_limits() -> None:
    catalogue = [
        topic("present"),
        topic("past", category="Past tenses"),
        topic("articles", level=GrammarLevel.A1, category="Articles"),
    ]

    selected = select_preview_topics(
        catalogue,
        levels=["a2"],
        categories=["VERBS", "past tenses"],
        limit=1,
    )

    assert [item.key for item in selected] == ["present"]


def test_select_preview_topics_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown topic key"):
        select_preview_topics([topic("present")], topic_keys=["missing"])


def test_prompt_fingerprint_changes_with_vocabulary() -> None:
    selected = topic("present")

    assert prompt_fingerprint(selected, []) != prompt_fingerprint(
        selected, ["biblioteca"]
    )


def test_preview_report_renders_content_safely_and_persists_reviews(
    tmp_path,
) -> None:
    created_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    result = GrammarPreviewResult(
        topic=topic("present"),
        sample=1,
        generated_at=created_at,
        prompt_sha256="a" * 64,
        generated=generated_session(),
    )

    report = render_preview_report(
        language="Spanish",
        model="claude-test",
        report_id="report-1",
        created_at=created_at,
        results=[result],
        expected_results=2,
    )

    assert "1/2" in report
    assert "Present tense" in report
    assert "Grammatically accurate" in report
    assert "Raw structured output" in report
    assert "localStorage.setItem" in report
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in report
    assert "<script>alert('x')</script>" not in report

    destination = tmp_path / "reports" / "preview.html"
    write_preview_report(destination, report)
    assert destination.read_text(encoding="utf-8") == report
    assert not destination.with_suffix(".html.tmp").exists()
