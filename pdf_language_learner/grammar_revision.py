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
GRAMMAR_GERMAN_NEW_EXAMPLE_EXPLANATION = """
Verbposition in Satzverbindungen (Verb Position in Connected Sentences)

The Rule
In German, when you connect two clauses, the position of the verb depends on the type of connecting word you use. There are three main types:

Type 1 — Koordinierende Konnektoren (Position 0)
Words like und, aber, oder, denn, sondern connect two main clauses. The word order in both clauses stays normal — subject first, verb second. These connectors occupy "position 0", meaning they don't count as part of the clause.
* Ich arbeite viel, aber ich verdiene wenig.
* Er kommt nicht, denn er ist krank.

Type 2 — Adverbiale Konnektoren (Position 1)
Words like deshalb, trotzdem, dennoch, außerdem, dann, danach are adverbs, not conjunctions. They sit in position 1, which pushes the verb to position 2 and the subject to position 3.
* Ich war müde. Deshalb bin ich früh ins Bett gegangen.
* Er hat wenig Geld. Trotzdem kauft er teure Kleidung.

Notice the pattern: Konnektor — Verb — Subjekt

Type 3 — Subordinierende Konnektoren (Nebensatz)
Words like weil, obwohl, dass, wenn, obwohl, damit send the verb to the end of the clause.
* Ich gehe nicht aus, weil ich müde bin.
* Er kauft teure Kleidung, obwohl er wenig Geld hat.

Common Connectors by Type
Type 1 (Position 0): und, aber, oder, denn, sondern
Type 2 (Position 1): deshalb, trotzdem, dennoch, außerdem, danach, dann, daher, deswegen
Type 3 (Nebensatz): weil, obwohl, dass, wenn, falls, damit, obwohl, nachdem, während
"""

GRAMMAR_SPANISH_NEW_EXAMPLE_EXPLANATION = """
Objeto Indirecto (OI) — Indirect Object Pronouns

The rule: Indirect object pronouns indicate to whom or for whom an action is done. They do not change for gender.

| Person | Pronoun |
| ------ | ------- |
| yo | me |
| tú | te | 
| él/ella/usted | le |
| nosotros/as | nos | 
| vosotros/as | os |
| ellos/ellas/ustedes | les |

They go before the conjugated verb. Common verbs that take an indirect object: dar, decir, escribir, mandar, preguntar, regalar, gustar, encantar, parecer.

Le doy el libro a María. (I give the book to María.)

Important: When OI and OD pronouns appear together in the same sentence, the indirect comes first. And le/les changes to se before lo/la/los/las:

¿Le das el libro a María? → Se lo doy. (NOT le lo)
"""


class GrammarSessionKind(StrEnum):
    LESSON = "lesson"
    REVIEW = "review"
    MIXED = "mixed"


class GrammarExerciseType(StrEnum):
    # Multiple choice remains readable for unfinished legacy sessions.
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    TRANSLATION = "translation"


class GrammarGeneratedExercise(BaseModel):
    topic_key: str
    type: GrammarExerciseType
    instruction: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)
    reference_answer: str
    grading_rubric: str
    explanation: str


class GrammarGeneratedExerciseContent(BaseModel):
    """Exercise fields shared by the nine structurally named response slots."""

    topic_key: str
    instruction: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
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
    exercises: list[GrammarGeneratedExercise] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_exercise_mix(self) -> "GrammarGeneratedSession":
        expected = {
            GrammarExerciseType.MULTIPLE_CHOICE: 3,
            GrammarExerciseType.FILL_BLANK: 3,
            GrammarExerciseType.TRANSLATION: 3,
        }
        actual = {
            exercise_type: sum(
                exercise.type is exercise_type for exercise in self.exercises
            )
            for exercise_type in GrammarExerciseType
        }
        actual = {
            exercise_type: count
            for exercise_type, count in actual.items()
            if count
        }
        if actual != expected:
            raise ValueError(
                "grammar sessions require three multiple-choice questions, three fill "
                "blanks, and three translations"
            )
        for exercise in self.exercises:
            if exercise.type is GrammarExerciseType.MULTIPLE_CHOICE:
                if len(exercise.choices) != 4:
                    raise ValueError("multiple-choice questions require four choices")
                if exercise.reference_answer not in exercise.choices:
                    raise ValueError(
                        "a multiple-choice reference answer must appear in its choices"
                    )
        return self


class GrammarGenerationResponse(BaseModel):
    """Provider response with the required nine-exercise mix."""

    rule_summary: str
    rule_tables: list[GrammarRuleTable] = Field(default_factory=list)
    worked_examples: list[str] = Field(min_length=2, max_length=4)
    multiple_choice_1: GrammarGeneratedExerciseContent
    multiple_choice_2: GrammarGeneratedExerciseContent
    multiple_choice_3: GrammarGeneratedExerciseContent
    fill_blank_1: GrammarGeneratedExerciseContent
    fill_blank_2: GrammarGeneratedExerciseContent
    fill_blank_3: GrammarGeneratedExerciseContent
    translation_1: GrammarGeneratedExerciseContent
    translation_2: GrammarGeneratedExerciseContent
    translation_3: GrammarGeneratedExerciseContent

    def to_generated_session(self) -> GrammarGeneratedSession:
        exercises = [
            GrammarGeneratedExercise(type=exercise_type, **content.model_dump())
            for exercise_type, content in (
                (GrammarExerciseType.MULTIPLE_CHOICE, self.multiple_choice_1),
                (GrammarExerciseType.MULTIPLE_CHOICE, self.multiple_choice_2),
                (GrammarExerciseType.MULTIPLE_CHOICE, self.multiple_choice_3),
                (GrammarExerciseType.FILL_BLANK, self.fill_blank_1),
                (GrammarExerciseType.FILL_BLANK, self.fill_blank_2),
                (GrammarExerciseType.FILL_BLANK, self.fill_blank_3),
                (GrammarExerciseType.TRANSLATION, self.translation_1),
                (GrammarExerciseType.TRANSLATION, self.translation_2),
                (GrammarExerciseType.TRANSLATION, self.translation_3),
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
            "All nine exercises must target the one topic and progress from recognition "
            "through guided completion to translation."
        )
    elif kind is GrammarSessionKind.MIXED and len(topics) == 4:
        distribution = (
            "This is a mixed session: the final topic is new and the first three are "
            "reviews. Give the new topic two exercises, and distribute the other seven "
            "across the review topics so every topic is practised."
        )
    else:
        distribution = "Interleave the topics as evenly as possible."
    return [
        {
            "role": "system",
            "content": (
                f"You create precise {language} grammar revision for an adult learner. "
                "Return exactly nine exercises in this order: three multiple_choice, three "
                "fill_blank, and three translation. Put each exercise in its correspondingly "
                "named response field; do not return an exercises array. Use saved "
                "vocabulary naturally when it fits, never at the expense of the target grammar. "
                "Keep choices and tokens lists empty except that every multiple_choice task must "
                "have exactly four choices and exactly one unambiguously correct choice. Its "
                "distractors should be plausible for the target rule, not random vocabulary, and "
                "the reference answer must match one choice exactly. Closed tasks must include all "
                "valid accepted answers. Every exercise must be answerable using only information visible "
                "to the learner before submission; never rely on the reference answer or explanation to "
                "identify what they are meant to write. When an exercise asks the learner to inflect, "
                "conjugate, decline, transform, or insert a particular word or phrase, explicitly name its "
                "source form in the instruction or prompt. For example, write 'Complete the sentence with "
                "the past participle of herstellen' or include '(herstellen)' beside the blank. A blank "
                "sentence plus a grammatical description such as 'insert the correct past participle' is "
                "invalid because several different words could fit. Explain every grammar rule in "
                "English. In particular, write the rule_summary and every exercise explanation in English, even when the language "
                "being studied is not English. Keep target-language forms, example sentences, prompts, "
                "and answers in the language being studied where the exercise requires them. "
                "For new exercises, please give a succinct explanation of the grammar rule, in the style of Grammatik Aktiv. "
                f"There is an example of how to format the German grammar instructions in {GRAMMAR_GERMAN_NEW_EXAMPLE_EXPLANATION}, "
                f"and an example of how to format the Spanish grammar instructions in {GRAMMAR_SPANISH_NEW_EXAMPLE_EXPLANATION}. "
                "Multiple-choice tasks must ask the learner to select the form or "
                "connector that makes the displayed sentence correct. Fill-blank tasks should be "
                "guided sentence completion or sentence combination: supply any required connector "
                "or source form explicitly and make clear whether the learner writes only the blank "
                "or a complete clause. If a task asks the learner to put supplied words, phrases, or "
                "sentence elements into the correct order, list those elements in a deliberately "
                "scrambled order. Never present them in the target order, and never reveal that order "
                "through their labels or surrounding explanation. Translation tasks must name the required construction or "
                "connector in parentheses. Keep prompts short, natural, level-appropriate, and "
                "semantically coherent. Test only rules taught in the summary or worked examples."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Create a {kind.value} session.\nTopics:\n{topic_lines}\n"
                f"Saved vocabulary: {vocabulary}\n{distribution}\n"
                "Give a concise rule summary and 2-4 useful worked examples. Model the "
                "clarity of a compact textbook exercise rather than a comprehensive grammar reference."
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
