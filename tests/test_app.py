import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pdf_language_learner.app import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_home_serves_reader() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "PDF language reader" in response.text
    assert 'id="saved-vocabulary-list"' in response.text
    assert 'id="revision-view"' in response.text


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

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
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

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
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


@pytest.fixture
def vocabulary_database(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pdf_language_learner.app.DATABASE_PATH", tmp_path / "margin.db"
    )


def vocabulary_payload(**overrides) -> dict[str, str]:
    payload = {
        "original_source": "Wörter",
        "normalized_source": "Wort",
        "translation": "word",
        "source_language": "German",
        "target_language": "English",
        "context": "Viele Wörter ergeben einen Satz.",
        "document_key": "margin:example.pdf:123:456",
    }
    payload.update(overrides)
    return payload


def test_vocabulary_is_persisted(vocabulary_database) -> None:
    saved = client.post("/api/vocabulary", json=vocabulary_payload())

    assert saved.status_code == 200
    assert saved.json()["created"] is True
    items = client.get("/api/vocabulary").json()
    assert len(items) == 1
    assert items[0]["normalized_source"] == "Wort"
    assert items[0]["review"] == {
        "last_reviewed_at": None,
        "next_review_at": None,
        "repetitions": 0,
        "lapses": 0,
    }


def test_vocabulary_deduplicates_normalized_form(vocabulary_database) -> None:
    first = client.post("/api/vocabulary", json=vocabulary_payload()).json()
    duplicate = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(
            original_source="wort",
            normalized_source=" wort ",
            translation="different translation",
            target_language="French",
        ),
    ).json()

    assert duplicate["created"] is False
    assert duplicate["item"]["id"] == first["item"]["id"]
    assert len(client.get("/api/vocabulary").json()) == 1


def test_vocabulary_keeps_same_spelling_from_different_languages(
        vocabulary_database,
) -> None:
    client.post("/api/vocabulary", json=vocabulary_payload())
    second = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(source_language="English"),
    )

    assert second.json()["created"] is True
    assert len(client.get("/api/vocabulary").json()) == 2


def test_vocabulary_can_be_deleted(vocabulary_database) -> None:
    item_id = client.post("/api/vocabulary", json=vocabulary_payload()).json()["item"]["id"]

    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    assert client.get("/api/vocabulary").json() == []
    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 404


def save_revision_vocabulary() -> list[dict]:
    words = [
        ("Wort", "word"),
        ("Haus", "house"),
        ("Katze", "cat"),
        ("Buch", "book"),
    ]
    return [
        client.post(
            "/api/vocabulary",
            json=vocabulary_payload(
                original_source=source,
                normalized_source=source,
                translation=translation,
            ),
        ).json()["item"]
        for source, translation in words
    ]


def test_revision_session_uses_due_vocabulary(vocabulary_database) -> None:
    saved = save_revision_vocabulary()

    response = client.get("/api/revision/session")

    assert response.status_code == 200
    session = response.json()
    assert session["due_count"] == 4
    assert {card["item_id"] for card in session["cards"]} == {
        item["id"] for item in saved
    }
    assert all(2 <= len(card["choices"]) <= 4 for card in session["cards"])
    assert all(card["category"] == "new" for card in session["cards"])


def test_correct_revision_is_persisted_and_no_longer_due(
    vocabulary_database,
) -> None:
    saved = save_revision_vocabulary()
    item = saved[0]

    response = client.post(
        f"/api/revision/{item['id']}/answer",
        json={
            "direction": "source_to_translation",
            "selected_answer": " WORD ",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["correct"] is True
    assert result["correct_answer"] == "word"
    assert result["category"] == "usually_correct"
    assert result["item"]["review"]["repetitions"] == 1
    assert result["item"]["review"]["lapses"] == 0
    session = client.get("/api/revision/session").json()
    assert session["due_count"] == 3
    assert item["id"] not in {card["item_id"] for card in session["cards"]}


def test_incorrect_revision_records_lapse(vocabulary_database) -> None:
    item = save_revision_vocabulary()[0]

    response = client.post(
        f"/api/revision/{item['id']}/answer",
        json={
            "direction": "translation_to_source",
            "selected_answer": "Haus",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["correct"] is False
    assert result["correct_answer"] == "Wort"
    assert result["category"] == "needs_practice"
    assert result["item"]["review"]["repetitions"] == 0
    assert result["item"]["review"]["lapses"] == 1


def test_revision_requires_distractors(vocabulary_database) -> None:
    client.post("/api/vocabulary", json=vocabulary_payload())

    assert client.get("/api/revision/session").json() == {
        "cards": [],
        "due_count": 0,
    }


def test_revision_of_unknown_word_returns_not_found(vocabulary_database) -> None:
    response = client.post(
        "/api/revision/missing/answer",
        json={
            "direction": "source_to_translation",
            "selected_answer": "word",
        },
    )

    assert response.status_code == 404
