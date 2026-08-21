import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ollama import Client
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    target_language: str = Field(min_length=2, max_length=60)

    @field_validator("text", "target_language")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TranslationResult(BaseModel):
    detected_language: str = Field(description="The source language in English")
    translation: str = Field(description="A natural translation in the requested language")


app = FastAPI(title="PDF Language Learner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/translate", response_model=TranslationResult)
def translate(request: TranslationRequest) -> TranslationResult:
    try:
        client = Client(
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )

        response = client.chat(
            model = os.getenv("OLLAMA_MODEL", "translategemma:4b"),
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a precise translator for a language-learning "
                        "application. Detect the input language and translate it "
                        "into the requested language. Preserve tone and meaning."
                        "Do not explain, do not converse, do not add commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Target language: {request.target_language}\n"
                        f"Text to translate: \n{request.text}"
                    ),
                },
            ],
            format = TranslationResult.model_json_schema(),
            keep_alive="30m",
            options = {"temperature": 0,
                       "num_ctx": 1024,
                       "num_predict": 512}
        )

        return TranslationResult.model_validate_json(
            response.message.content
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
