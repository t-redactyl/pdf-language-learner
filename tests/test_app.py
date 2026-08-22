import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pdf_language_learner import app as app_module
from pdf_language_learner.app import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_home_serves_reader() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "PDF language reader" in response.text


def test_detect_language_uses_document_sample(monkeypatch) -> None:
    sample = "Dies ist ein ausreichend langer deutscher Text aus dem geöffneten Dokument."

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            assert kwargs["messages"][1]["content"] == sample
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"detected_language": "German"})
                )
            )

    monkeypatch.setattr(app_module, "Client", FakeClient)
    response = client.post("/api/detect-language", json={"text": sample})

    assert response.status_code == 200
    assert response.json() == {"detected_language": "German"}


@pytest.mark.parametrize(
    ("source", "source_language", "normalized_source", "translation"),
    [
        ("Wörter", "German", "Wort", "word"),  # plural noun
        ("wird", "German", "werden", "become"),  # conjugated verb
        ("Häuser", "German", "Haus", "house"),  # plural noun
        ("gingen", "German", "gehen", "go"),  # conjugated verb
        ("belles", "French", "beau", "beautiful"),  # declined adjective
        ("hablamos", "Spanish", "hablar", "speak"),  # conjugated verb
        ("gatti", "Italian", "gatto", "cat"),  # plural noun
    ],
)
def test_translate_returns_normalized_words_across_languages(
    monkeypatch, source, source_language, normalized_source, translation
) -> None:
    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            assert kwargs["format"]["required"] == ["translation"]
            assert f"Dictionary form to translate: {normalized_source}" in (
                kwargs["messages"][1]["content"]
            )
            assert "Surrounding context: Ein Beispiel im Kontext." in (
                kwargs["messages"][1]["content"]
            )
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"translation": translation}))
            )

    monkeypatch.setattr(app_module, "Client", FakeClient)
    response = client.post(
        "/api/translate",
        json={
            "text": source,
            "source_language": source_language,
            "target_language": "English",
            "context": "Ein Beispiel im Kontext.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": source_language,
        "normalized_source": normalized_source,
        "translation": translation,
    }


def test_translate_rejects_blank_text() -> None:
    response = client.post(
        "/api/translate",
        json={
            "text": "   ",
            "source_language": "German",
            "target_language": "English",
        },
    )
    assert response.status_code == 422


def test_translate_requires_document_source_language() -> None:
    response = client.post(
        "/api/translate",
        json={"text": "Wörter", "target_language": "English"},
    )
    assert response.status_code == 422
