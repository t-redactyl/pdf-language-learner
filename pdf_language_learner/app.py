import os
from pathlib import Path

import simplemma
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ollama import Client
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

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


def normalize_source(text: str, source_language: str) -> str:
    language = LEMMATIZER_LANGUAGES.get(source_language.casefold())
    if language is None or len(text.split()) != 1:
        return text
    return simplemma.lemmatize(text, lang=language) or text


app = FastAPI(title="PDF Language Learner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
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
            detail = f"Local translation model failed: {exc}",
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
