"""Pure policies and structured content models for grammar revision."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from pdf_language_learner.revision import ScheduleState


GRAMMAR_CORRECT_INTERVAL_DAYS = (3, 7, 14, 30, 60, 120)
GRAMMAR_INCORRECT_INTERVAL = timedelta(days=2)
GRAMMAR_REVIEW_SESSION_INTERVAL = timedelta(days=2)
GRAMMAR_REVIEW_TOPIC_LIMIT = 3
GRAMMAR_NEW_TOPIC_LIMIT = 1


class GrammarSessionKind(StrEnum):
    LESSON = "lesson"
    REVIEW = "review"
    MIXED = "mixed"


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
    tokens: list[str] = Field(default_factory=list, max_length=7)
    accepted_answers: list[str] = Field(default_factory=list)
    reference_answer: str
    grading_rubric: str
    explanation: str


class GrammarGeneratedExerciseContent(BaseModel):
    """Exercise fields shared by the six structurally named response slots."""

    topic_key: str
    instruction: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list, max_length=7)
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
    worked_examples: list[str] = Field(min_length=2, max_length=4)
    exercises: list[GrammarGeneratedExercise] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_exercise_mix(self) -> "GrammarGeneratedSession":
        exercise_types = {exercise.type for exercise in self.exercises}
        if exercise_types != set(GrammarExerciseType):
            raise ValueError("grammar sessions require one of each exercise type")
        return self


class GrammarGenerationResponse(BaseModel):
    """Provider response with all six exercise types structurally required."""

    rule_summary: str
    rule_tables: list[GrammarRuleTable] = Field(default_factory=list)
    worked_examples: list[str] = Field(min_length=2, max_length=4)
    multiple_choice: GrammarGeneratedExerciseContent
    fill_blank: GrammarGeneratedExerciseContent
    ordering: GrammarGeneratedExerciseContent
    transformation: GrammarGeneratedExerciseContent
    translation: GrammarGeneratedExerciseContent
    production: GrammarGeneratedExerciseContent

    def to_generated_session(self) -> GrammarGeneratedSession:
        exercises = [
            GrammarGeneratedExercise(type=exercise_type, **content.model_dump())
            for exercise_type, content in (
                (GrammarExerciseType.MULTIPLE_CHOICE, self.multiple_choice),
                (GrammarExerciseType.FILL_BLANK, self.fill_blank),
                (GrammarExerciseType.ORDERING, self.ordering),
                (GrammarExerciseType.TRANSFORMATION, self.transformation),
                (GrammarExerciseType.TRANSLATION, self.translation),
                (GrammarExerciseType.PRODUCTION, self.production),
            )
        ]
        return GrammarGeneratedSession(
            rule_summary=self.rule_summary,
            rule_tables=self.rule_tables,
            worked_examples=self.worked_examples,
            exercises=exercises,
        )


class GrammarGrade(BaseModel):
    correct: bool
    feedback: str


class GrammarTopicSummary(BaseModel):
    summary: str = Field(min_length=1, max_length=700)


def normalize_grammar_answer(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"\s+([,.;:!?%)\]}])", r"\1", value)
    value = re.sub(r"([¿¡(\[{])\s+", r"\1", value)
    value = re.sub(r"[.!?¡¿]+$", "", value)
    return re.sub(r"\s+", " ", value).strip()


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
    if kind is GrammarSessionKind.LESSON:
        distribution = (
            "All six exercises must target the one topic and progress from recognition "
            "toward constrained production."
        )
    elif kind is GrammarSessionKind.MIXED and len(topics) == 4:
        distribution = (
            "This is a mixed session: the final topic is new and the first three are "
            "reviews. Give the new topic two exercises, and distribute the other four "
            "across the review topics so every topic is practised."
        )
    else:
        distribution = "Interleave the topics as evenly as possible."
    return [
        {
            "role": "system",
            "content": (
                f"You create precise {language} grammar revision for an adult learner. "
                "Return exactly six exercises: one multiple_choice, one fill_blank, one ordering, "
                "one transformation, one translation, and one production. Put each exercise in its "
                "correspondingly named response field; do not return an exercises array. Never create error-finding "
                "or error-correction tasks. Keep production tightly constrained. Use saved vocabulary "
                "naturally when it fits, never at the expense of the target grammar. Multiple choice "
                "must have 3-4 choices. Keep the ordering exercise short and focused: its completed "
                "sentence must contain no more than 12 words and its tokens list must contain no more "
                "than 7 selectable tiles. Group words that are not meaningfully reordered for the "
                "target rule into one multiword tile, such as 'wegen des Mangels an Wohnraum' or 'die "
                "Auflagen'. Supply every tile needed for the sentence, and avoid sentences with several "
                "grammatically valid orders unless every valid order is accepted. Closed tasks must "
                "include all "
                "valid accepted answers. Every exercise must be answerable using only information visible "
                "to the learner before submission; never rely on the reference answer or explanation to "
                "identify what they are meant to write. When an exercise asks the learner to inflect, "
                "conjugate, decline, transform, or insert a particular word or phrase, explicitly name its "
                "source form in the instruction or prompt. For example, write 'Complete the sentence with "
                "the past participle of herstellen' or include '(herstellen)' beside the blank. A blank "
                "sentence plus a grammatical description such as 'insert the correct past participle' is "
                "invalid because several different words could fit. Explain every grammar rule in "
                "English. In particular, write "
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
                "session, return an empty rule_tables list. For a mixed session, the final listed "
                "topic is new; explain it clearly and include a rule table when that materially "
                "helps. Format rule_summary as 3-6 short bullet "
                "points, with one self-contained point per line beginning with '- '. Do not write "
                "rule_summary as a prose paragraph."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Create a {kind.value} session.\nTopics:\n{topic_lines}\n"
                f"Saved vocabulary: {vocabulary}\n{distribution}\n"
                "Give a concise rule summary and 2-4 useful worked examples."
            ),
        },
    ]


def grammar_topic_summary_messages(
    *,
    language: str,
    title: str,
    category: str,
    example: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"Explain one {language} grammar rule to an adult learner in English. "
                "Write one very brief, self-contained prose paragraph of no more than "
                "three sentences. State the core rule and clarify the supplied example. "
                "Do not use bullets, headings, Markdown, or introductory filler. Keep "
                "target-language forms in the language being studied."
            ),
        },
        {
            "role": "user",
            "content": f"Rule: {title}\nCategory: {category}\nExample: {example}",
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
