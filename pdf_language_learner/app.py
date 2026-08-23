import os
import random
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import simplemma
import stanza
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ollama import Client
from pydantic import BaseModel, Field, field_validator

from pdf_language_learner.revision import (
    RevisionCategory,
    RevisionDirection,
    ScheduleState,
    is_due,
    parse_timestamp,
    revision_category,
    schedule_review,
)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DATABASE_PATH = Path(
    os.getenv("MARGIN_DATABASE_PATH", ROOT / "data" / "margin.db")
)

LEMMATIZER_LANGUAGES = {
    "dutch": "nl",
    "english": "en",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "polish": "pl",
    "portuguese": "pt",
    "spanish": "es",
}

STANZA_LANGUAGES = {
    **LEMMATIZER_LANGUAGES,
    "chinese (simplified)": "zh-hans",
    "japanese": "ja",
    "korean": "ko",
}

NOUN_POS = {"NOUN"}
VERB_POS = {"VERB", "AUX"}
STANZA_PIPELINE_LOCK = threading.Lock()

DEFINITE_ARTICLES = {
    "dutch": ("de", "het"),
    "english": ("the",),
    "french": ("le", "la", "l'"),
    "german": ("der", "die", "das"),
    "italian": ("il", "lo", "la", "l'"),
    "portuguese": ("o", "a"),
    "spanish": ("el", "la"),
}


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    source_language: str = Field(min_length=2, max_length=60)
    target_language: str = Field(min_length=2, max_length=60)
    context: str = Field(default="", max_length=2_000)
    context_offset: int | None = Field(default=None, ge=0, le=2_000)

    @field_validator("text", "source_language", "target_language")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("context")
    @classmethod
    def strip_context(cls, value: str) -> str:
        return value.strip()


class LanguageDetectionRequest(BaseModel):
    text: str = Field(min_length=20, max_length=12_000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LanguageDetectionResult(BaseModel):
    detected_language: str = Field(
        min_length=2,
        description="The predominant language of the document, written in English",
    )


class TranslationResult(BaseModel):
    detected_language: str = Field(description="The source language in English")
    is_word: bool = Field(
        description="Whether the selected text is a single-word vocabulary lookup"
    )
    normalized_source: str = Field(
        description=(
            "The source text in dictionary form for a word lookup, or the unchanged "
            "source text for a phrase translation"
        )
    )
    translation: str = Field(
        description="A natural translation of the normalized source in the requested language"
    )


class TranslatedText(BaseModel):
    translation: str = Field(
        min_length=1,
        description="A natural translation in the requested target language",
    )


class NounTranslation(BaseModel):
    source_definite_article: str = Field(
        description="The source noun's definite article, without the noun",
    )
    target_lemma: str = Field(
        min_length=1,
        description="The singular target-language noun without an article",
    )
    target_definite_article: str = Field(
        description="The target noun's definite article, without the noun",
    )


class VocabularyCreate(BaseModel):
    original_source: str = Field(min_length=1, max_length=2_000)
    normalized_source: str = Field(min_length=1, max_length=2_000)
    translation: str = Field(min_length=1, max_length=2_000)
    source_language: str = Field(min_length=2, max_length=60)
    target_language: str = Field(min_length=2, max_length=60)
    context: str = Field(default="", max_length=2_000)
    document_key: str = Field(default="", max_length=1_000)

    @field_validator(
        "original_source",
        "normalized_source",
        "translation",
        "source_language",
        "target_language",
    )
    @classmethod
    def strip_required_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("context", "document_key")
    @classmethod
    def strip_optional_value(cls, value: str) -> str:
        return value.strip()


class ReviewState(BaseModel):
    last_reviewed_at: str | None = None
    next_review_at: str | None = None
    repetitions: int = 0
    lapses: int = 0


class VocabularyItem(BaseModel):
    id: str
    schema_version: int = 1
    original_source: str
    normalized_source: str
    translation: str
    source_language: str
    target_language: str
    context: str
    document_key: str
    saved_at: str
    review: ReviewState


class VocabularySaveResult(BaseModel):
    item: VocabularyItem
    created: bool


class RevisionCard(BaseModel):
    item_id: str
    prompt: str
    direction: RevisionDirection
    choices: list[str]
    category: RevisionCategory
    source_language: str
    target_language: str


class RevisionSession(BaseModel):
    cards: list[RevisionCard]
    due_count: int


class RevisionAnswer(BaseModel):
    direction: RevisionDirection
    selected_answer: str = Field(min_length=1, max_length=2_000)

    @field_validator("selected_answer")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class RevisionAnswerResult(BaseModel):
    correct: bool
    correct_answer: str
    category: RevisionCategory
    item: VocabularyItem


@dataclass(frozen=True)
class WordAnalysis:
    token: str
    lemma: str
    pos: str


@lru_cache(maxsize=len(STANZA_LANGUAGES))
def stanza_pipeline(source_language: str):
    language = STANZA_LANGUAGES.get(source_language.casefold())
    if language is None:
        raise ValueError(f"POS tagging is not supported for {source_language}")
    return stanza.Pipeline(
        lang=language,
        processors="tokenize,pos,lemma",
        download_method=stanza.DownloadMethod.REUSE_RESOURCES,
        use_gpu=False,
        verbose=False,
    )


def normalize_source(text: str, source_language: str) -> str:
    language = LEMMATIZER_LANGUAGES.get(source_language.casefold())
    if language is None or len(text.split()) != 1:
        return text
    return simplemma.lemmatize(text, lang=language) or text


def analyze_word_in_context(
    text: str,
    source_language: str,
    context: str,
    context_offset: int | None,
) -> WordAnalysis:
    context_text = context or text
    selected_start = context_offset
    if selected_start is None:
        found = context_text.casefold().find(text.casefold())
        selected_start = found if found >= 0 else 0
    selected_end = selected_start + len(text)

    pipeline = stanza_pipeline(source_language)
    with STANZA_PIPELINE_LOCK:
        document = pipeline(context_text)
    words = [word for sentence in document.sentences for word in sentence.words]
    overlapping = [
        word
        for word in words
        if word.start_char is not None
        and word.end_char is not None
        and word.start_char < selected_end
        and word.end_char > selected_start
        and word.upos not in {"PUNCT", "SYM"}
    ]
    selected = overlapping[0] if overlapping else None
    if selected is None:
        selected_key = canonicalize(text.strip(".,;:!?¡¿()[]{}\"“”'‘’"))
        selected = next(
            (word for word in words if canonicalize(word.text) == selected_key),
            None,
        )
    if selected is None:
        raise ValueError("the selected word could not be located in its context")

    stanza_lemma = selected.lemma or selected.text
    simplemma_lemma = normalize_source(selected.text, source_language)
    lemma = simplemma_lemma if selected.upos in NOUN_POS else stanza_lemma
    return WordAnalysis(
        token=selected.text,
        lemma=lemma,
        pos=selected.upos or "X",
    )


def is_sentence_like_word_translation(translation: str) -> bool:
    """Detect when a one-word lookup was answered with contextual prose."""

    return len(translation.split()) > 8 or len(translation) > 120


def english_infinitive(value: str) -> str:
    value = value.strip()
    return value if value.casefold().startswith("to ") else f"to {value}"


def definite_articles(language: str) -> tuple[str, ...]:
    # Polish and the supported East Asian languages do not have definite articles.
    return DEFINITE_ARTICLES.get(language.casefold(), ("",))


def noun_translation_schema(
    source_language: str, target_language: str
) -> dict:
    schema = NounTranslation.model_json_schema()
    schema["properties"]["source_definite_article"]["enum"] = list(
        definite_articles(source_language)
    )
    schema["properties"]["target_definite_article"]["enum"] = list(
        definite_articles(target_language)
    )
    return schema


def normalized_article(article: str, language: str) -> str:
    article = article.strip().casefold().replace("’", "'")
    allowed = definite_articles(language)
    if article not in allowed:
        expected = ", ".join(repr(value) for value in allowed)
        raise ValueError(
            f"invalid definite article {article!r} for {language}; expected {expected}"
        )
    return article


def article_and_lemma(article: str, lemma: str) -> str:
    article = article.strip()
    lemma = lemma.strip()
    if not article:
        return lemma
    return f"{article}{lemma}" if article.endswith("'") else f"{article} {lemma}"


def translation_messages(
    *,
    source: str,
    source_language: str,
    target_language: str,
    context: str,
    is_word: bool,
    word_analysis: WordAnalysis | None = None,
) -> list[dict[str, str]]:
    if not is_word:
        return [
            {
                "role": "system",
                "content": (
                    "You are a precise translator for a language-learning "
                    "application. Translate the supplied phrase naturally into "
                    "the requested target language. Preserve its meaning as used "
                    "and do not rewrite it into dictionary form. Return only the "
                    "translation, without an explanation. Use the surrounding "
                    "context only to disambiguate the phrase; do not translate "
                    "any additional text from the context."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Source language: {source_language}\n"
                    f"Target language: {target_language}\n"
                    f"Phrase to translate: {source}\n"
                    f"Surrounding context (do not translate): "
                    f"{context or '(not available)'}\n"
                    "Translate the phrase only."
                ),
            },
        ]

    if word_analysis is None:
        raise ValueError("word analysis is required for a single-word translation")
    form_instruction = (
        "This is a noun. Return its source definite article separately in "
        "source_definite_article. Translate the supplied singular source lemma "
        "to a singular target noun in target_lemma, with no article attached, "
        "and return its target definite article separately in "
        "target_definite_article. Use an empty article only for a language that "
        "has no definite articles."
        if word_analysis.pos in NOUN_POS
        else (
            "This is a verb. Translate the supplied source lemma into the target "
            "language's infinitive. English infinitives must include 'to'."
            if word_analysis.pos in VERB_POS
            else "Translate the supplied source lemma without adding an article."
        )
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a precise dictionary translator for a language-learning "
                "application. Follow the supplied part-of-speech analysis; do not "
                "reclassify the word. Return only the requested structured fields "
                "and a short dictionary-style translation, never a sentence, "
                "excerpt, explanation, or example. Use the surrounding context "
                "only to disambiguate meaning; never translate the context. "
                f"{form_instruction}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source_language}\n"
                f"Target language: {target_language}\n"
                f"Selected token: {word_analysis.token}\n"
                f"Part of speech (Universal POS): {word_analysis.pos}\n"
                f"Source lemma: {word_analysis.lemma}\n"
                f"Surrounding context (do not translate): "
                f"{context or '(not available)'}\n"
                "Return only the requested dictionary fields."
            ),
        },
    ]


def canonicalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@contextmanager
def vocabulary_database() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vocabulary (
                id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL DEFAULT 1,
                original_source TEXT NOT NULL,
                normalized_source TEXT NOT NULL,
                canonical_source TEXT NOT NULL,
                translation TEXT NOT NULL,
                source_language TEXT NOT NULL,
                canonical_source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                document_key TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL,
                last_reviewed_at TEXT,
                next_review_at TEXT,
                repetitions INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                consecutive_correct INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(vocabulary)").fetchall()
        }
        if "consecutive_correct" not in columns:
            connection.execute(
                """
                ALTER TABLE vocabulary
                ADD COLUMN consecutive_correct INTEGER NOT NULL DEFAULT 0
                """
            )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS vocabulary_normalized_source
                ON vocabulary (canonical_source_language, canonical_source)
            """
        )
        yield connection
        connection.commit()
    finally:
        connection.close()


def vocabulary_item(row: sqlite3.Row) -> VocabularyItem:
    return VocabularyItem(
        id=row["id"],
        schema_version=row["schema_version"],
        original_source=row["original_source"],
        normalized_source=row["normalized_source"],
        translation=row["translation"],
        source_language=row["source_language"],
        target_language=row["target_language"],
        context=row["context"],
        document_key=row["document_key"],
        saved_at=row["saved_at"],
        review=ReviewState(
            last_reviewed_at=row["last_reviewed_at"],
            next_review_at=row["next_review_at"],
            repetitions=row["repetitions"],
            lapses=row["lapses"],
        ),
    )


def schedule_state(row: sqlite3.Row) -> ScheduleState:
    return ScheduleState(
        repetitions=row["repetitions"],
        lapses=row["lapses"],
        consecutive_correct=row["consecutive_correct"],
        last_reviewed_at=parse_timestamp(row["last_reviewed_at"]),
        next_review_at=parse_timestamp(row["next_review_at"]),
    )


def select_session_rows(
    rows: list[sqlite3.Row], *, now: datetime, limit: int
) -> list[sqlite3.Row]:
    """Choose a balanced session while never showing a card before it is due."""

    groups: dict[RevisionCategory, list[sqlite3.Row]] = {
        category: [] for category in RevisionCategory
    }
    for row in rows:
        state = schedule_state(row)
        if is_due(state, at=now):
            groups[revision_category(state)].append(row)

    generator = random.SystemRandom()
    for group in groups.values():
        generator.shuffle(group)

    new_limit = min(8, max(1, round(limit * 0.2)))
    targets = {
        RevisionCategory.NEEDS_PRACTICE: round(limit * 0.35),
        RevisionCategory.USUALLY_CORRECT: round(limit * 0.30),
        RevisionCategory.ALWAYS_CORRECT: round(limit * 0.15),
        RevisionCategory.NEW: new_limit,
    }
    selected: list[sqlite3.Row] = []
    for category in (
        RevisionCategory.NEEDS_PRACTICE,
        RevisionCategory.USUALLY_CORRECT,
        RevisionCategory.ALWAYS_CORRECT,
        RevisionCategory.NEW,
    ):
        selected.extend(groups[category][: targets[category]])
        groups[category] = groups[category][targets[category] :]

    for category in (
        RevisionCategory.NEEDS_PRACTICE,
        RevisionCategory.USUALLY_CORRECT,
        RevisionCategory.ALWAYS_CORRECT,
        RevisionCategory.NEW,
    ):
        if len(selected) >= limit:
            break
        capacity = limit - len(selected)
        if category is RevisionCategory.NEW:
            already_new = sum(
                revision_category(schedule_state(row)) is RevisionCategory.NEW
                for row in selected
            )
            capacity = min(capacity, max(0, new_limit - already_new))
        selected.extend(groups[category][:capacity])

    generator.shuffle(selected)
    return selected[:limit]


def revision_choices(
    row: sqlite3.Row,
    rows: list[sqlite3.Row],
    direction: RevisionDirection,
) -> list[str]:
    answer_field = (
        "translation"
        if direction is RevisionDirection.SOURCE_TO_TRANSLATION
        else "normalized_source"
    )
    compatible = [
        candidate[answer_field]
        for candidate in rows
        if canonicalize(candidate["source_language"])
        == canonicalize(row["source_language"])
        and canonicalize(candidate["target_language"])
        == canonicalize(row["target_language"])
    ]
    unique = {
        canonicalize(value): value
        for value in compatible
        if canonicalize(value) != canonicalize(row[answer_field])
    }
    distractors = list(unique.values())
    generator = random.SystemRandom()
    generator.shuffle(distractors)
    choices = [row[answer_field], *distractors[:3]]
    generator.shuffle(choices)
    return choices


def revision_card(
    row: sqlite3.Row, rows: list[sqlite3.Row]
) -> RevisionCard | None:
    directions = [
        direction
        for direction in RevisionDirection
        if len(revision_choices(row, rows, direction)) >= 2
    ]
    if not directions:
        return None
    direction = random.SystemRandom().choice(directions)
    prompt_field = (
        "normalized_source"
        if direction is RevisionDirection.SOURCE_TO_TRANSLATION
        else "translation"
    )
    return RevisionCard(
        item_id=row["id"],
        prompt=row[prompt_field],
        direction=direction,
        choices=revision_choices(row, rows, direction),
        category=revision_category(schedule_state(row)),
        source_language=row["source_language"],
        target_language=row["target_language"],
    )


app = FastAPI(title="PDF Language Learner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/vocabulary", response_model=list[VocabularyItem])
def list_vocabulary() -> list[VocabularyItem]:
    with vocabulary_database() as connection:
        rows = connection.execute(
            "SELECT * FROM vocabulary ORDER BY saved_at DESC"
        ).fetchall()
    return [vocabulary_item(row) for row in rows]


@app.post("/api/vocabulary", response_model=VocabularySaveResult)
def save_vocabulary(request: VocabularyCreate) -> VocabularySaveResult:
    item_id = str(uuid.uuid4())
    saved_at = datetime.now(UTC).isoformat()
    canonical_source = canonicalize(request.normalized_source)
    canonical_language = canonicalize(request.source_language)
    with vocabulary_database() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO vocabulary (
                id, original_source, normalized_source, canonical_source,
                translation, source_language, canonical_source_language,
                target_language, context, document_key, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                request.original_source,
                request.normalized_source,
                canonical_source,
                request.translation,
                request.source_language,
                canonical_language,
                request.target_language,
                request.context,
                request.document_key,
                saved_at,
            ),
        )
        created = cursor.rowcount == 1
        row = connection.execute(
            """
            SELECT *
            FROM vocabulary
            WHERE canonical_source_language = ?
              AND canonical_source = ?
            """,
            (canonical_language, canonical_source),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Vocabulary could not be saved")
    return VocabularySaveResult(item=vocabulary_item(row), created=created)


@app.delete("/api/vocabulary/{item_id}", status_code=204)
def delete_vocabulary(item_id: str) -> Response:
    with vocabulary_database() as connection:
        cursor = connection.execute("DELETE FROM vocabulary WHERE id = ?", (item_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Saved vocabulary item not found")
    return Response(status_code=204)


@app.get("/api/revision/session", response_model=RevisionSession)
def revision_session(limit: int = 40) -> RevisionSession:
    limit = max(1, min(limit, 100))
    now = datetime.now(UTC)
    with vocabulary_database() as connection:
        rows = connection.execute("SELECT * FROM vocabulary").fetchall()

    eligible_rows = [
        row
        for row in rows
        if any(len(revision_choices(row, rows, direction)) >= 2 for direction in RevisionDirection)
    ]
    due_count = sum(is_due(schedule_state(row), at=now) for row in eligible_rows)
    selected = select_session_rows(eligible_rows, now=now, limit=limit)
    cards = [revision_card(row, rows) for row in selected]
    return RevisionSession(
        cards=[card for card in cards if card is not None],
        due_count=due_count,
    )


@app.post(
    "/api/revision/{item_id}/answer",
    response_model=RevisionAnswerResult,
)
def answer_revision(item_id: str, request: RevisionAnswer) -> RevisionAnswerResult:
    reviewed_at = datetime.now(UTC)
    with vocabulary_database() as connection:
        row = connection.execute(
            "SELECT * FROM vocabulary WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Vocabulary item not found")

        answer_field = (
            "translation"
            if request.direction is RevisionDirection.SOURCE_TO_TRANSLATION
            else "normalized_source"
        )
        correct_answer = row[answer_field]
        correct = canonicalize(request.selected_answer) == canonicalize(correct_answer)
        updated = schedule_review(
            schedule_state(row), correct=correct, reviewed_at=reviewed_at
        )
        connection.execute(
            """
            UPDATE vocabulary
            SET last_reviewed_at = ?, next_review_at = ?, repetitions = ?,
                lapses = ?, consecutive_correct = ?
            WHERE id = ?
            """,
            (
                updated.last_reviewed_at.isoformat(),
                updated.next_review_at.isoformat(),
                updated.repetitions,
                updated.lapses,
                updated.consecutive_correct,
                item_id,
            ),
        )
        updated_row = connection.execute(
            "SELECT * FROM vocabulary WHERE id = ?", (item_id,)
        ).fetchone()

    return RevisionAnswerResult(
        correct=correct,
        correct_answer=correct_answer,
        category=revision_category(updated),
        item=vocabulary_item(updated_row),
    )


@app.post("/api/detect-language", response_model=LanguageDetectionResult)
def detect_language(request: LanguageDetectionRequest) -> LanguageDetectionResult:
    try:
        client = Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        translation_model = os.getenv("OLLAMA_MODEL", "translategemma:4b")
        detection_model = os.getenv("OLLAMA_DETECTION_MODEL", translation_model)
        response = client.chat(
            model=detection_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Identify the single predominant language of this document "
                        "sample. Return its common English name. Ignore isolated names, "
                        "quotations, page numbers, and foreign words."
                    ),
                },
                {"role": "user", "content": request.text},
            ],
            format=LanguageDetectionResult.model_json_schema(),
            keep_alive="30m",
            options={"temperature": 0, "num_ctx": 4096, "num_predict": 64},
        )
        return LanguageDetectionResult.model_validate_json(response.message.content)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local language detection model failed: {exc}",
        ) from exc


@app.post("/api/translate", response_model=TranslationResult)
def translate(request: TranslationRequest) -> TranslationResult:
    try:
        client = Client(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )
        translation_model = os.getenv("OLLAMA_MODEL", "translategemma:4b")
        is_word = len(request.text.split()) == 1
        word_analysis = (
            analyze_word_in_context(
                request.text,
                request.source_language,
                request.context,
                request.context_offset,
            )
            if is_word
            else None
        )

        def request_translation(
            context: str,
        ) -> TranslatedText | NounTranslation:
            is_noun = word_analysis is not None and word_analysis.pos in NOUN_POS
            response_model = NounTranslation if is_noun else TranslatedText
            response_schema = (
                noun_translation_schema(
                    request.source_language, request.target_language
                )
                if is_noun
                else response_model.model_json_schema()
            )
            response = client.chat(
                model=translation_model,
                messages=translation_messages(
                    source=request.text,
                    source_language=request.source_language,
                    target_language=request.target_language,
                    context=context,
                    is_word=is_word,
                    word_analysis=word_analysis,
                ),
                format=response_schema,
                keep_alive="30m",
                options={"temperature": 0, "num_ctx": 1024, "num_predict": 128},
            )
            return response_model.model_validate_json(response.message.content)

        translated = request_translation(request.context)
        translated_text = (
            translated.target_lemma
            if isinstance(translated, NounTranslation)
            else translated.translation
        )
        if is_word and request.context and is_sentence_like_word_translation(
            translated_text
        ):
            # Small local models occasionally translate the context despite the
            # instruction. A context-free retry still gives a useful dictionary
            # answer and prevents an excerpt from being saved as vocabulary.
            translated = request_translation("")
            translated_text = (
                translated.target_lemma
                if isinstance(translated, NounTranslation)
                else translated.translation
            )
        if is_word and is_sentence_like_word_translation(translated_text):
            raise ValueError(
                "the model returned a sentence instead of a word translation"
            )

        normalized_source = request.text
        translation = translated_text
        if word_analysis is not None:
            if word_analysis.pos in VERB_POS:
                normalized_source = word_analysis.lemma
                if request.source_language.casefold() == "english":
                    normalized_source = english_infinitive(normalized_source)
                if request.target_language.casefold() == "english":
                    translation = english_infinitive(translation)
            elif word_analysis.pos in NOUN_POS:
                assert isinstance(translated, NounTranslation)
                source_article = normalized_article(
                    translated.source_definite_article, request.source_language
                )
                target_article = normalized_article(
                    translated.target_definite_article, request.target_language
                )
                normalized_source = article_and_lemma(
                    source_article, word_analysis.lemma
                )
                target_lemma = normalize_source(
                    translated.target_lemma, request.target_language
                )
                translation = article_and_lemma(target_article, target_lemma)
            else:
                normalized_source = word_analysis.lemma

        return TranslationResult(
            detected_language=request.source_language,
            is_word=is_word,
            normalized_source=normalized_source,
            translation=translation,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local translation model failed: {exc}",
        ) from exc
