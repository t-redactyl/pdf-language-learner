import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pdf_language_learner.app import WordAnalysis, analyze_word_in_context, app

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
    (
        "source",
        "source_language",
        "target_language",
        "analysis",
        "model_response",
        "normalized_source",
        "translation",
    ),
    [
        (
            "Wörter", "German", "English", WordAnalysis("Wörter", "Wort", "NOUN"),
            {
                "source_definite_article": "das",
                "target_lemma": "word",
                "target_definite_article": "the",
            },
            "das Wort", "the word",
        ),
        (
            "wird", "German", "English", WordAnalysis("wird", "werden", "VERB"),
            {"translation": "become"}, "werden", "to become",
        ),
        (
            "Häuser", "German", "English", WordAnalysis("Häuser", "Haus", "NOUN"),
            {
                "source_definite_article": "das",
                "target_lemma": "house",
                "target_definite_article": "the",
            },
            "das Haus", "the house",
        ),
        (
            "gingen", "German", "English", WordAnalysis("gingen", "gehen", "VERB"),
            {"translation": "go"}, "gehen", "to go",
        ),
        (
            "belles", "French", "English", WordAnalysis("belles", "beau", "ADJ"),
            {"translation": "beautiful"}, "beau", "beautiful",
        ),
        (
            "hablamos", "Spanish", "English", WordAnalysis("hablamos", "hablar", "VERB"),
            {"translation": "speak"}, "hablar", "to speak",
        ),
        (
            "gatti", "Italian", "English", WordAnalysis("gatti", "gatto", "NOUN"),
            {
                "source_definite_article": "il",
                "target_lemma": "cat",
                "target_definite_article": "the",
            },
            "il gatto", "the cat",
        ),
        (
            "spoke", "English", "German", WordAnalysis("spoke", "speak", "VERB"),
            {"translation": "sprechen"}, "to speak", "sprechen",
        ),
        (
            "houses", "English", "Spanish", WordAnalysis("houses", "house", "NOUN"),
            {
                "source_definite_article": "the",
                "target_lemma": "casa",
                "target_definite_article": "la",
            },
            "the house", "la casa",
        ),
        (
            "Augen", "German", "English", WordAnalysis("Augen", "Auge", "NOUN"),
            {
                "source_definite_article": "das",
                "target_lemma": "eyes",
                "target_definite_article": "the",
            },
            "das Auge", "the eye",
        ),
    ],
)
def test_translate_uses_contextual_pos_to_normalize_words(
    monkeypatch,
    source,
    source_language,
    target_language,
    analysis,
    model_response,
    normalized_source,
    translation,
) -> None:
    def fake_analysis(text, language, context, context_offset):
        assert (text, language) == (source, source_language)
        assert context == "Ein Beispiel im Kontext."
        assert context_offset == 4
        return analysis

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            if analysis.pos == "NOUN":
                assert set(kwargs["format"]["required"]) == {
                    "source_definite_article",
                    "target_lemma",
                    "target_definite_article",
                }
                assert kwargs["format"]["properties"][
                    "source_definite_article"
                ]["enum"] == list({
                    "German": ("der", "die", "das"),
                    "Italian": ("il", "lo", "la", "l'"),
                    "English": ("the",),
                }[source_language])
            else:
                assert kwargs["format"]["required"] == ["translation"]
            prompt = kwargs["messages"][1]["content"]
            assert f"Part of speech (Universal POS): {analysis.pos}" in prompt
            assert f"Source lemma: {analysis.lemma}" in prompt
            assert (
                "Surrounding context (do not translate): Ein Beispiel im Kontext."
                in prompt
            )
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(model_response))
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context", fake_analysis
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    response = client.post(
        "/api/translate",
        json={
            "text": source,
            "source_language": source_language,
            "target_language": target_language,
            "context": "Ein Beispiel im Kontext.",
            "context_offset": 4,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": source_language,
        "is_word": True,
        "normalized_source": normalized_source,
        "translation": translation,
    }


def test_translate_retries_without_context_when_model_translates_excerpt(
    monkeypatch,
) -> None:
    prompts = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            prompts.append(kwargs["messages"][1]["content"])
            translation = (
                "pleasant, compared to visiting Charlotte and her awful husband, "
                "while her cold fingers were forgotten as she danced along the path, "
                "occasionally stopping to admire the beautiful shapes of the "
                "snowflakes that surrounded her on the long journey home"
                if len(prompts) == 1
                else "do"
            )
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": translation})
                )
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("täte", "tun", "VERB"),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    response = client.post(
        "/api/translate",
        json={
            "text": "täte",
            "source_language": "German",
            "target_language": "English",
            "context": "Ein langer Satz, der nicht übersetzt werden soll.",
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == "tun"
    assert response.json()["translation"] == "to do"
    assert len(prompts) == 2
    assert "(not available)" in prompts[1]


def test_translate_phrase_without_normalizing_or_word_validation(monkeypatch) -> None:
    phrase = "gingen nach Hause"
    translated_phrase = "went home after the party when everybody was already tired"

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            prompt = kwargs["messages"][1]["content"]
            assert f"Phrase to translate: {phrase}" in prompt
            assert "Dictionary form to translate" not in prompt
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": translated_phrase})
                )
            )

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: pytest.fail("phrases must not invoke POS analysis"),
    )
    response = client.post(
        "/api/translate",
        json={
            "text": phrase,
            "source_language": "German",
            "target_language": "English",
            "context": "Sie gingen nach Hause.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": "German",
        "is_word": False,
        "normalized_source": phrase,
        "translation": translated_phrase,
    }


def test_word_analysis_uses_selected_occurrence_offset(monkeypatch) -> None:
    words = [
        SimpleNamespace(
            text="record", lemma="record", upos="VERB", start_char=2, end_char=8
        ),
        SimpleNamespace(
            text="record", lemma="record", upos="NOUN", start_char=11, end_char=17
        ),
    ]
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=words)]
    )
    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    analysis = analyze_word_in_context(
        "record", "English", "I record a record.", 11
    )

    assert analysis == WordAnalysis(token="record", lemma="record", pos="NOUN")


def test_noun_analysis_prefers_simplemma_singular(monkeypatch) -> None:
    word = SimpleNamespace(
        text="Augen", lemma="Augen", upos="NOUN", start_char=0, end_char=5
    )
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=[word])]
    )
    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    analysis = analyze_word_in_context("Augen", "German", "Augen", 0)

    assert analysis == WordAnalysis(token="Augen", lemma="Auge", pos="NOUN")


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
