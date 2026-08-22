import os
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import simplemma
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ollama import Client
from pydantic import BaseModel, Field, field_validator

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


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    source_language: str = Field(min_length=2, max_length=60)
    target_language: str = Field(min_length=2, max_length=60)
    context: str = Field(default="", max_length=2_000)

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
    normalized_source: str = Field(
        description=(
            "The source text in its dictionary form, in the source language "
            "(for example: singular nouns, infinitive verbs, and undeclined adjectives)"
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


def normalize_source(text: str, source_language: str) -> str:
    language = LEMMATIZER_LANGUAGES.get(source_language.casefold())
    if language is None or len(text.split()) != 1:
        return text
    return simplemma.lemmatize(text, lang=language) or text


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
                lapses INTEGER NOT NULL DEFAULT 0
            )
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
        normalized_source = normalize_source(request.text, request.source_language)

        translation_response = client.chat(
            model=translation_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise translator for a language-learning "
                        "application. Translate the supplied dictionary form into "
                        "the requested target language. Use the surrounding context "
                        "only to choose the correct sense; translate the dictionary "
                        "form, not the whole context."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {request.source_language}\n"
                        f"Target language: {request.target_language}\n"
                        f"Dictionary form to translate: {normalized_source}\n"
                        f"Surrounding context: {request.context or '(not available)'}"
                    ),
                },
            ],
            format=TranslatedText.model_json_schema(),
            keep_alive="30m",
            options={"temperature": 0, "num_ctx": 1024, "num_predict": 512},
        )
        translated = TranslatedText.model_validate_json(
            translation_response.message.content
        )

        return TranslationResult(
            detected_language=request.source_language,
            normalized_source=normalized_source,
            translation=translated.translation,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local translation model failed: {exc}",
        ) from exc

    # if not os.getenv("OPENAI_API_KEY"):
    #     raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    #
    # try:
    #     response = OpenAI().responses.parse(
    #         model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    #         instructions=(
    #             "You are a precise translator for a language-learning reading app. "
    #             "Detect the input language, then translate into the requested language. "
    #             "Preserve tone and meaning. Return only the requested structured result."
    #         ),
    #         input=(
    #             f"Target language: {request.target_language}\n"
    #             f"Text to detect and translate:\n{request.text}"
    #         ),
    #         text_format=TranslationResult,
    #     )
    # except Exception as exc:
    #     raise HTTPException(status_code=502, detail="Translation service failed") from exc
    #
    # if response.output_parsed is None:
    #     raise HTTPException(status_code=502, detail="Translation service returned no result")
    # return response.output_parsed
