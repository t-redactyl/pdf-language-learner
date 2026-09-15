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
from pdf_language_learner.grammar_quality import GrammarQualityReview, GrammarQualityVerdict


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
        (GrammarExerciseType.MULTIPLE_CHOICE,) * 5
        + (GrammarExerciseType.FILL_BLANK,) * 5
        + (GrammarExerciseType.TRANSLATION,) * 5
    )
    exercises = [
        GrammarGeneratedExercise(
            topic_key="present",
            type=exercise_type,
            instruction="Use the present tense.",
            prompt="Complete <this> sentence.",
            choices=["Hablo.", "Hablas.", "Habla.", "Hablan."]
            if exercise_type is GrammarExerciseType.MULTIPLE_CHOICE
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


@pytest.mark.parametrize("approved", [False, True])
def test_report_shows_judge_feedback_and_retains_unapproved_drafts(approved):
    generated = generated_session()
    rejected = GrammarQualityVerdict.model_validate({
        "lesson_issues": [{
            "category": "grammar", "problem": "Wrong <form>", "suggested_fix": "Use <correct> form",
        }],
        "exercises": [{"position": position, "issues": []} for position in range(1, 16)],
    })
    if approved:
        passed = rejected.model_copy(update={"lesson_issues": []})
        generated.quality_review = GrammarQualityReview(model="judge", verdicts=[rejected, passed])
    result = GrammarPreviewResult(
        topic=topic("present"), sample=1, generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        prompt_sha256="a" * 64, generated=generated,
        error=None if approved else "grammar session repair: max_output_tokens",
        verdicts=(rejected,),
        usage={
            "grammar session generation [generator]": {
                "calls": 1, "input_tokens": 1200, "output_tokens": 3400,
                "reasoning_tokens": 2800,
            },
            "grammar session quality review [judge]": {
                "calls": 1, "input_tokens": 2200, "output_tokens": 900,
                "reasoning_tokens": 500,
            },
        },
    )
    report = render_preview_report(
        language="Spanish", model="test", report_id="report", created_at=result.generated_at,
        results=[result], expected_results=1,
    )
    assert "LLM quality review" in report
    assert "Wrong &lt;form&gt;" in report
    assert "Suggested fix: Use &lt;correct&gt; form" in report
    assert "Present tense" in report
    assert "Raw structured output" in report
    assert "2 model calls" in report
    assert "3,400 input tokens" in report
    assert "4,300 output tokens (3,300 reasoning)" in report
    if approved:
        assert "Approved after 1 revision(s)" in report
        assert "Not approved for practice" not in report
    else:
        assert "Not approved for practice" in report
        assert "grammar session repair: max_output_tokens" in report
