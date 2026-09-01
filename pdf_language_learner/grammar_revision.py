"""Pure policies and structured content models for grammar revision."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from pdf_language_learner.revision import ScheduleState


GRAMMAR_CORRECT_INTERVAL_DAYS = (3, 7, 14, 30, 60, 120)
GRAMMAR_INCORRECT_INTERVAL = timedelta(days=1)


class GrammarSessionKind(StrEnum):
    LESSON = "lesson"
    REVIEW = "review"


class GrammarExerciseType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    ORDERING = "ordering"
    TRANSFORMATION = "transformation"
    TRANSLATION = "translation"
    PRODUCTION = "production"


class GrammarGeneratedExercise(BaseModel):
    topic_key: str
    type: GrammarExerciseType
    instruction: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)
    reference_answer: str
    grading_rubric: str
    explanation: str


class GrammarRuleTable(BaseModel):
    title: str
    headers: list[str] = Field(min_length=2, max_length=6)
    rows: list[list[str]] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_row_widths(self) -> "GrammarRuleTable":
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("every grammar table row must match its headers")
        return self


class GrammarGeneratedSession(BaseModel):
    rule_summary: str
    rule_tables: list[GrammarRuleTable] = Field(default_factory=list, max_length=2)
    worked_examples: list[str] = Field(min_length=2, max_length=3)
    exercises: list[GrammarGeneratedExercise] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_exercise_mix(self) -> "GrammarGeneratedSession":
        exercise_types = {exercise.type for exercise in self.exercises}
        if exercise_types != set(GrammarExerciseType):
            raise ValueError("grammar sessions require one of each exercise type")
        return self


class GrammarGrade(BaseModel):
    correct: bool
    feedback: str


def normalize_grammar_answer(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[.!?¡¿]+$", "", value)
    return re.sub(r"\s+", " ", value)


def deterministic_grammar_grade(
    exercise_type: GrammarExerciseType,
    answer: str,
    accepted_answers: list[str],
    reference_answer: str,
) -> bool | None:
    """Grade closed exercises locally and defer open-ended ones to the model."""

    if exercise_type not in {
        GrammarExerciseType.MULTIPLE_CHOICE,
        GrammarExerciseType.FILL_BLANK,
        GrammarExerciseType.ORDERING,
    }:
        return None
    expected = accepted_answers or [reference_answer]
    normalized = normalize_grammar_answer(answer)
    return normalized in {normalize_grammar_answer(item) for item in expected}


def schedule_grammar_review(
    state: ScheduleState,
    *,
    correct: bool,
    reviewed_at: datetime,
) -> ScheduleState:
    """Apply the deliberately coarser, topic-level grammar schedule."""

    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    reviewed_at = reviewed_at.astimezone(UTC)
    if not correct:
        return ScheduleState(
            repetitions=state.repetitions,
            lapses=state.lapses + 1,
            consecutive_correct=0,
            last_reviewed_at=reviewed_at,
            next_review_at=reviewed_at + GRAMMAR_INCORRECT_INTERVAL,
        )
    streak = state.consecutive_correct + 1
    interval = GRAMMAR_CORRECT_INTERVAL_DAYS[
        min(streak - 1, len(GRAMMAR_CORRECT_INTERVAL_DAYS) - 1)
    ]
    return ScheduleState(
        repetitions=state.repetitions + 1,
        lapses=state.lapses,
        consecutive_correct=streak,
        last_reviewed_at=reviewed_at,
        next_review_at=reviewed_at + timedelta(days=interval),
    )


def grammar_generation_messages(
    *,
    language: str,
    kind: GrammarSessionKind,
    topics: list[dict[str, str | int]],
    saved_vocabulary: list[str],
) -> list[dict[str, str]]:
    topic_lines = "\n".join(
        f"- {topic['key']}: {topic['title']} ({topic['level']}); example: {topic['example']}"
        for topic in topics
    )
    vocabulary = ", ".join(saved_vocabulary) or "none available"
    distribution = (
        "All six exercises must target the one topic and progress from recognition "
        "toward constrained production."
        if kind is GrammarSessionKind.LESSON
        else "Interleave the topics evenly; when there are three topics, assign two exercises to each."
    )
    return [
        {
            "role": "system",
            "content": (
                f"You create precise {language} grammar revision for an adult learner. "
                "Return exactly six exercises: one multiple_choice, one fill_blank, one ordering, "
                "one transformation, one translation, and one production. Never create error-finding "
                "or error-correction tasks. Keep production tightly constrained. Use saved vocabulary "
                "naturally when it fits, never at the expense of the target grammar. Multiple choice "
                "must have 3-4 choices. Ordering must supply every token. Closed tasks must include all "
                "valid accepted answers. Explain every grammar rule in English. In particular, write "
                "the rule_summary and every exercise explanation in English, even when the language "
                "being studied is not English. Keep target-language forms, example sentences, prompts, "
                "and answers in the language being studied where the exercise requires them. Rule "
                "explanations must be accurate, self-contained, and internally consistent: define "
                "technical or shorthand terms, distinguish regular patterns from exceptions, and do "
                "not claim that a regular shortcut covers irregular forms. When describing a sequence "
                "of transformations, make each example begin with the form named in the instructions "
                "and show the relevant intermediate step. For example, do not say to start from a "
                "Spanish verb's present-tense yo form and then illustrate the rule with an unexplained "
                "arrow directly from the infinitive; show a sequence such as hablo -> habl- -> no "
                "hables and state explicitly which endings apply to -ar versus -er/-ir verbs. For a "
                "lesson, include a rule_table when a compact table makes the rule easier to understand, "
                "especially for conjugations, declensions, person-by-person endings, or comparisons of "
                "forms. Use at most two tables, give each a clear English title and headers, and keep "
                "each cell concise. Do not force a table for a rule that is clearer in prose, do not "
                "put prose "
                "paragraphs in cells, and do not embed Markdown tables in text fields. For a review "
                "session, return an empty rule_tables list."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Create a {kind.value} session.\nTopics:\n{topic_lines}\n"
                f"Saved vocabulary: {vocabulary}\n{distribution}\n"
                "Give a concise rule summary and 2-3 useful worked examples."
            ),
        },
    ]


def grammar_grading_messages(
    *,
    language: str,
    prompt: str,
    instruction: str,
    answer: str,
    reference_answer: str,
    rubric: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"Grade an adult learner's {language} grammar answer. Judge the target grammar, "
                "not stylistic preference. Accept genuinely equivalent wording. Ignore harmless "
                "capitalization and terminal punctuation. Give brief, encouraging, specific feedback."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Instruction: {instruction}\nPrompt: {prompt}\nLearner answer: {answer}\n"
                f"Reference answer: {reference_answer}\nRubric: {rubric}"
            ),
        },
    ]
