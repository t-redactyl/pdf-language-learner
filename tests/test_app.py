import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
import wn
from fastapi.testclient import TestClient

from pdf_language_learner.app import (
    LOCAL_NOUN_GRAMMAR_CACHE,
    MULTI_WORD_TERMS,
    SourceNounGrammar,
    STANZA_PIPELINES,
    SynonymCandidateSet,
    SynonymValue,
    WordAnalysis,
    analyze_word_in_context,
    app,
    cached_model_translation,
    cached_ranked_synonyms,
    cached_source_noun_grammar,
    cached_verb_lemma_decision,
    frequency_ranked_synonym_candidates,
    multi_word_term_in_context,
    ollama_client,
    ollama_keep_alive,
    part_of_speech_filtered_synonym_candidates,
    stanza_pipeline,
    warm_translation_model,
    wordnet_synonym_candidates,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_runtime_caches():
    # Tests replace model and NLP dependencies with purpose-built fakes. Ensure
    # cached results and clients cannot leak from one test into the next.
    for cached_function in (
        ollama_client,
        analyze_word_in_context,
        cached_verb_lemma_decision,
        cached_source_noun_grammar,
        cached_model_translation,
        cached_ranked_synonyms,
        frequency_ranked_synonym_candidates,
        part_of_speech_filtered_synonym_candidates,
        wordnet_synonym_candidates,
    ):
        cached_function.cache_clear()
    LOCAL_NOUN_GRAMMAR_CACHE.clear()
    yield
    for cached_function in (
        ollama_client,
        analyze_word_in_context,
        cached_verb_lemma_decision,
        cached_source_noun_grammar,
        cached_model_translation,
        cached_ranked_synonyms,
        frequency_ranked_synonym_candidates,
        part_of_speech_filtered_synonym_candidates,
        wordnet_synonym_candidates,
    ):
        cached_function.cache_clear()
    LOCAL_NOUN_GRAMMAR_CACHE.clear()


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_wordnet_database_allows_fastapi_worker_threads() -> None:
    assert wn.config.allow_multithreading is True


def test_home_serves_reader() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "PDF language reader" in response.text
    assert 'id="saved-vocabulary-list"' in response.text
    assert 'id="revision-view"' in response.text
    assert 'id="interface-language"' in response.text
    assert 'id="toggle-reader-meta"' in response.text
    assert 'id="synonyms-result"' in response.text
    assert 'data-i18n="hero.title"' in response.text
    assert '/static/app.js?v=19' in response.text


def test_spanish_interface_catalog_is_served() -> None:
    response = client.get("/static/i18n.js")

    assert response.status_code == 200
    assert "Convierte la lectura en otros idiomas" in response.text
    assert 'localStorage.setItem(STORAGE_KEY, locale)' in response.text


def test_ollama_client_is_reused(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host
            created.append(self)

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    assert ollama_client() is ollama_client()
    assert len(created) == 1


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("-1", -1.0), ("0", 0.0), ("90", 90.0), ("30m", "30m"), ("2h", "2h")],
)
def test_ollama_keep_alive_preserves_duration_semantics(
    monkeypatch, configured, expected
) -> None:
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", configured)

    assert ollama_keep_alive() == expected


def test_translation_model_warmup_uses_configured_lifecycle(
    monkeypatch, caplog
) -> None:
    calls = []

    class FakeClient:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                total_duration=20_000_000,
                load_duration=12_000_000,
            )

    monkeypatch.setenv("OLLAMA_MODEL", "example:1b")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "2h")
    monkeypatch.setattr("pdf_language_learner.app.ollama_client", FakeClient)
    caplog.set_level(logging.INFO, logger="uvicorn.error.margin")

    warm_translation_model()

    assert calls == [
        {"model": "example:1b", "prompt": "", "keep_alive": "2h"}
    ]
    assert "Ollama warm-up (example:1b) completed" in caplog.text
    assert "load=12.0ms" in caplog.text


def test_translation_model_warmup_failure_is_non_fatal(monkeypatch, caplog) -> None:
    class FakeClient:
        def generate(self, **kwargs):
            raise ConnectionError("Ollama is unavailable")

    monkeypatch.setattr("pdf_language_learner.app.ollama_client", FakeClient)

    warm_translation_model()

    assert "Ollama warm-up" in caplog.text
    assert "Ollama is unavailable" in caplog.text


def test_identical_translation_requests_reuse_cached_model_result(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": "How are you?"})
                )
            )

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    payload = {
        "text": "Wie geht es dir?",
        "source_language": "German",
        "target_language": "English",
        "context": "Wie geht es dir? Lange nicht gesehen.",
    }

    first = client.post("/api/translate", json=payload)
    second = client.post("/api/translate", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1
    assert cached_model_translation.cache_info().hits == 1


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("Dit is een Nederlandse tekst over het leren van nieuwe talen.", "Dutch"),
        ("This is an English text about learning and reading new languages.", "English"),
        ("Ceci est un texte français consacré à la lecture et aux langues.", "French"),
        ("Dies ist ein deutscher Text über das Lesen und das Lernen von Sprachen.", "German"),
        ("Questo è un testo italiano sulla lettura e sullo studio delle lingue.", "Italian"),
        ("To jest polski tekst o czytaniu książek i nauce nowych języków.", "Polish"),
        ("Este é um texto português sobre leitura e aprendizagem de línguas.", "Portuguese"),
        ("Este es un texto español sobre la lectura y el aprendizaje de idiomas.", "Spanish"),
        ("这是一个关于阅读和学习语言的中文文本，用于测试语言检测功能。", "Chinese (Simplified)"),
        ("これは読書と言語学習についての日本語の文章です。", "Japanese"),
        ("이것은 독서와 언어 학습에 관한 한국어 문장입니다.", "Korean"),
    ],
)
def test_detect_language_uses_local_detector(monkeypatch, sample, expected) -> None:
    class UnexpectedClient:
        def __init__(self, host: str) -> None:
            raise AssertionError("language detection must not contact Ollama")

    monkeypatch.setattr("pdf_language_learner.app.Client", UnexpectedClient)
    response = client.post("/api/detect-language", json={"text": sample})

    assert response.status_code == 200
    assert response.json() == {"detected_language": expected}


def test_prepare_language_starts_background_preparation(monkeypatch) -> None:
    requested = []
    wordnet_requested = []
    monkeypatch.setattr(
        "pdf_language_learner.app.start_stanza_preparation",
        lambda language: requested.append(language) or "preparing",
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.start_wordnet_preparation",
        lambda language: wordnet_requested.append(language),
    )

    response = client.post(
        "/api/prepare-language", json={"source_language": " German "}
    )

    assert response.status_code == 202
    assert response.json() == {"status": "preparing"}
    assert requested == ["German"]
    assert wordnet_requested == ["German"]


def test_prepare_language_rejects_unsupported_language() -> None:
    response = client.post(
        "/api/prepare-language", json={"source_language": "Klingon"}
    )

    assert response.status_code == 422
    assert "not supported" in response.json()["detail"]


def test_stanza_pipeline_initializes_each_language_once(monkeypatch) -> None:
    initialization_started = Event()
    allow_initialization_to_finish = Event()
    pipeline = object()
    calls = []

    def fake_pipeline(**kwargs):
        calls.append(kwargs)
        initialization_started.set()
        assert allow_initialization_to_finish.wait(timeout=2)
        return pipeline

    monkeypatch.setattr("pdf_language_learner.app.stanza.Pipeline", fake_pipeline)
    STANZA_PIPELINES.pop("german", None)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(stanza_pipeline, "German")
            assert initialization_started.wait(timeout=2)
            second = executor.submit(stanza_pipeline, "german")
            allow_initialization_to_finish.set()

            assert first.result(timeout=2) is pipeline
            assert second.result(timeout=2) is pipeline
    finally:
        STANZA_PIPELINES.pop("german", None)

    assert len(calls) == 1


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
                "source_gender": "neutral",
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
                "source_gender": "neutral",
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
                "source_gender": "masculine",
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
                "source_gender": "none",
                "target_lemma": "casa",
                "target_definite_article": "la",
            },
            "the house", "la casa",
        ),
        (
            "Augen", "German", "English", WordAnalysis("Augen", "Auge", "NOUN"),
            {
                "source_definite_article": "das",
                "source_gender": "neutral",
                "target_lemma": "eyes",
                "target_definite_article": "the",
            },
            "das Auge", "the eye",
        ),
        (
            "profesora", "Spanish", "English",
            WordAnalysis("profesora", "profesor", "NOUN"),
            {
                "source_definite_article": "el",
                "source_gender": "masculine",
                "target_lemma": "teacher",
                "target_definite_article": "the",
            },
            "el profesor", "the teacher",
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
            required = set(kwargs["format"]["required"])
            if required == {"article", "gender"}:
                prompt = kwargs["messages"][1]["content"]
                assert f"Normalized dictionary lemma: {analysis.lemma}" in prompt
                assert "Selected token:" not in prompt
                assert "Surrounding context:" not in prompt
                if source.casefold() != analysis.lemma.casefold():
                    assert source not in prompt
                assert kwargs["format"]["properties"]["article"][
                    "enum"
                ] == list({
                    "German": ("der", "die", "das"),
                    "Italian": ("il", "lo", "la", "l'"),
                    "English": ("the",),
                    "Spanish": ("el", "la"),
                }[source_language])
                return SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({
                        "article": model_response["source_definite_article"],
                        "gender": model_response["source_gender"],
                    }))
                )
            if analysis.pos == "NOUN":
                assert set(kwargs["format"]["required"]) == {
                    "target_lemma",
                    "target_definite_article",
                }
            else:
                assert kwargs["format"]["required"] == ["translation"]
            prompt = kwargs["messages"][1]["content"]
            assert f"Part of speech (Universal POS): {analysis.pos}" in prompt
            assert f"Source lemma: {analysis.lemma}" in prompt
            assert (
                "Surrounding context (do not translate): Ein Beispiel im Kontext."
                in prompt
            )
            response_data = dict(model_response)
            response_data.pop("source_definite_article", None)
            response_data.pop("source_gender", None)
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(response_data))
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context", fake_analysis
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.local_noun_grammars",
        lambda lemmas, language: tuple(None for _ in lemmas),
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
    expected = {
        "detected_language": source_language,
        "is_word": True,
        "normalized_source": normalized_source,
        "translation": translation,
    }
    if model_response.get("source_gender") not in {None, "none"}:
        expected["noun_gender"] = model_response["source_gender"]
    assert response.json() == expected


def test_contextual_gender_removes_source_noun_model_lookup(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            calls.append(kwargs)
            assert set(kwargs["format"]["required"]) == {
                "target_lemma",
                "target_definite_article",
            }
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "target_lemma": "house",
                "target_definite_article": "the",
            })))

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis(
            "Häuser", "Haus", "NOUN", noun_gender="neutral"
        ),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "Häuser",
            "source_language": "German",
            "target_language": "English",
            "context": "Viele Häuser stehen hier.",
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == "das Haus"
    assert response.json()["noun_gender"] == "neutral"
    assert len(calls) == 1


def test_translate_combines_translation_and_synonyms(monkeypatch) -> None:
    synonym_calls = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "translation": "probably / presumably",
            })))

    analysis = WordAnalysis("vermutlich", "vermutlich", "ADJ")
    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )

    def fake_synonyms(model, word_analysis, source_language, context):
        synonym_calls.append(
            (model, word_analysis, source_language, context)
        )
        return [
            SynonymValue(text="wahrscheinlich"),
            SynonymValue(text="wohl"),
        ]

    monkeypatch.setattr(
        "pdf_language_learner.app.contextual_synonyms", fake_synonyms
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "vermutlich",
            "source_language": "German",
            "target_language": "English",
            "context": "Das ist vermutlich richtig.",
            "include_synonyms": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": "German",
        "is_word": True,
        "normalized_source": "vermutlich",
        "translation": "probably / presumably",
        "synonyms": [
            {"text": "wahrscheinlich"},
            {"text": "wohl"},
        ],
    }
    assert synonym_calls == [
        (
            "translategemma:4b",
            analysis,
            "German",
            "Das ist vermutlich richtig.",
        )
    ]


def test_local_target_grammar_overrides_model_article(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            required = set(kwargs["format"]["required"])
            data = (
                {"article": "the", "gender": "none"}
                if required == {"article", "gender"}
                else {"target_lemma": "agua", "target_definite_article": "la"}
            )
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(data))
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("water", "water", "NOUN"),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.local_noun_grammars",
        lambda lemmas, language: (
            SourceNounGrammar(article="el", gender="feminine"),
        ),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "water",
            "source_language": "English",
            "target_language": "Spanish",
        },
    )

    assert response.status_code == 200
    assert response.json()["translation"] == "el agua"


def test_source_noun_grammar_is_cached_across_target_languages(monkeypatch) -> None:
    grammar_calls = 0
    translation_calls = 0

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            nonlocal grammar_calls, translation_calls
            required = set(kwargs["format"]["required"])
            if required == {"article", "gender"}:
                grammar_calls += 1
                data = {"article": "das", "gender": "neutral"}
            else:
                translation_calls += 1
                prompt = kwargs["messages"][1]["content"]
                data = (
                    {"target_lemma": "house", "target_definite_article": "the"}
                    if "Target language: English" in prompt
                    else {"target_lemma": "maison", "target_definite_article": "la"}
                )
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(data))
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("Häuser", "Haus", "NOUN"),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    payload = {
        "text": "Häuser",
        "source_language": "German",
        "context": "Viele Häuser stehen an dieser Straße.",
        "context_offset": 6,
    }

    english = client.post(
        "/api/translate", json={**payload, "target_language": "English"}
    )
    french = client.post(
        "/api/translate", json={**payload, "target_language": "French"}
    )

    assert english.status_code == french.status_code == 200
    assert english.json()["normalized_source"] == "das Haus"
    assert french.json()["normalized_source"] == "das Haus"
    assert grammar_calls == 1
    assert translation_calls == 2
    assert cached_source_noun_grammar.cache_info().hits == 1


def test_noun_grammar_and_translation_requests_run_concurrently(monkeypatch) -> None:
    rendezvous = Barrier(2)
    calls = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            calls.append(kwargs)
            rendezvous.wait(timeout=2)
            required = set(kwargs["format"]["required"])
            data = (
                {"article": "das", "gender": "neutral"}
                if required == {"article", "gender"}
                else {"target_lemma": "house", "target_definite_article": "the"}
            )
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(data))
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("Häuser", "Haus", "NOUN"),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "Häuser",
            "source_language": "German",
            "target_language": "English",
            "context": "Viele Häuser stehen an dieser Straße.",
            "context_offset": 6,
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == "das Haus"
    assert response.json()["translation"] == "the house"
    assert len(calls) == 2


@pytest.mark.parametrize(
    (
        "source",
        "context",
        "analysis",
        "decision",
        "model_translation",
        "normalized_source",
        "translation",
    ),
    [
        (
            "pongo",
            "Me pongo el pijama.",
            WordAnalysis("Me pongo", "poner", "VERB", ("Me",)),
            {"dictionary_lemma": "ponerse"},
            "put on",
            "ponerse",
            "to put on",
        ),
        (
            "encanta",
            "Me encanta esta canción.",
            WordAnalysis("Me encanta", "encantar", "VERB", ("Me",)),
            {"dictionary_lemma": "encantar"},
            "love",
            "encantar",
            "to love",
        ),
        (
            "veo",
            "Lo veo claramente.",
            WordAnalysis("Lo veo", "ver", "VERB", ("Lo",)),
            {"dictionary_lemma": "ver"},
            "see",
            "ver",
            "to see",
        ),
        (
            "compré",
            "Me compré un libro.",
            WordAnalysis("Me compré", "comprar", "VERB", ("Me",)),
            {"dictionary_lemma": "comprar"},
            "buy",
            "comprar",
            "to buy",
        ),
    ],
)
def test_translate_semantically_decides_which_clitics_enter_verb_lemma(
    monkeypatch,
    source,
    context,
    analysis,
    decision,
    model_translation,
    normalized_source,
    translation,
) -> None:
    prompts = []

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            prompt = kwargs["messages"][1]["content"]
            prompts.append(prompt)
            required = set(kwargs["format"]["required"])
            if required == {"dictionary_lemma"}:
                assert f"Base verb lemma: {analysis.lemma}" in prompt
                assert (
                    f"Detected clitic candidates: "
                    f"{analysis.associated_clitics[0]}" in prompt
                )
                assert f"Full sentence context: {context}" in prompt
                return SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(decision))
                )
            assert required == {"translation"}
            assert f"Source lemma: {normalized_source}" in prompt
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": model_translation})
                )
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": source,
            "source_language": "Spanish",
            "target_language": "English",
            "context": context,
            "context_offset": context.index(source),
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == normalized_source
    assert response.json()["translation"] == translation
    assert len(prompts) == 2


def test_translate_uses_confident_reflexive_lemma_without_classifier(
    monkeypatch,
) -> None:
    analysis = WordAnalysis(
        "Me preparo",
        "preparar",
        "VERB",
        ("Me",),
        "prepararse",
    )

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            assert kwargs["format"]["required"] == ["translation"]
            prompt = kwargs["messages"][1]["content"]
            assert "Source lemma: prepararse" in prompt
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": "get ready"})
                )
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "preparo",
            "source_language": "Spanish",
            "target_language": "English",
            "context": "Me preparo para salir.",
            "context_offset": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == "prepararse"
    assert response.json()["translation"] == "to get ready"


def test_translate_uses_confident_german_sich_lemma_without_classifier(
    monkeypatch,
) -> None:
    analysis = WordAnalysis(
        "erinnerte sich",
        "erinnern",
        "VERB",
        ("sich",),
        "sich erinnern",
    )

    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            assert kwargs["format"]["required"] == ["translation"]
            prompt = kwargs["messages"][1]["content"]
            assert "Source lemma: sich erinnern" in prompt
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": "remember"})
                )
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/translate",
        json={
            "text": "ERINNERTE",
            "source_language": "German",
            "target_language": "English",
            "context": "ER ERINNERTE SICH AN diese alte Eiche.",
            "context_offset": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["normalized_source"] == "sich erinnern"
    assert response.json()["translation"] == "to remember"


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


@pytest.mark.parametrize(
    ("text", "language", "context", "offset", "expected"),
    [
        ("veces", "Spanish", "A veces leo por la noche.", 2, "a veces"),
        ("tal", "Spanish", "Tal vez venga mañana.", 0, "tal vez"),
        ("eso", "Spanish", "No había pan; por eso salí.", 18, "por eso"),
        (
            "por",
            "Spanish",
            "Por la tarde, cuando vuelvo a casa.",
            0,
            "por la tarde",
        ),
        (
            "por",
            "Spanish",
            "Por la noche, me preparo la cena.",
            0,
            "por la noche",
        ),
        (
            "Beispiel",
            "German",
            "Das ist zum Beispiel üblich.",
            12,
            "zum Beispiel",
        ),
        ("Fall", "German", "Ich komme auf jeden Fall.", 20, "auf jeden Fall"),
        (
            "fin",
            "Spanish",
            "A fin de cuentas, no importa.",
            2,
            "a fin de cuentas",
        ),
        (
            "Grunde",
            "German",
            "Das ist im Grunde genommen richtig.",
            11,
            "im Grunde genommen",
        ),
    ],
)
def test_multi_word_term_contains_selected_word(
    text, language, context, offset, expected
) -> None:
    assert multi_word_term_in_context(text, language, context, offset) == expected


@pytest.mark.parametrize("language", ["german", "spanish"])
def test_multi_word_term_lexicon_is_broad_and_has_no_duplicates(language) -> None:
    terms = MULTI_WORD_TERMS[language]
    canonical_terms = [term.casefold() for term in terms]

    assert len(terms) >= 100
    assert len(canonical_terms) == len(set(canonical_terms))


@pytest.mark.parametrize(
    ("text", "context", "offset", "resolved_term", "translation"),
    [
        ("veces", "A veces leo por la noche.", 2, "a veces", "sometimes"),
        (
            "por",
            "Por la tarde, cuando vuelvo a casa.",
            0,
            "por la tarde",
            "in the afternoon",
        ),
        (
            "por",
            "Por la noche, me preparo la cena.",
            0,
            "por la noche",
            "at night",
        ),
    ],
)
def test_translate_expands_selected_word_to_known_expression(
    monkeypatch, text, context, offset, resolved_term, translation
) -> None:
    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            prompt = kwargs["messages"][1]["content"]
            assert f"Phrase to translate: {resolved_term}" in prompt
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"translation": translation})
                )
            )

    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)
    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: pytest.fail(
            "known expressions must not use single-word analysis"
        ),
    )

    response = client.post(
        "/api/translate",
        json={
            "text": text,
            "source_language": "Spanish",
            "target_language": "English",
            "context": context,
            "context_offset": offset,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": "Spanish",
        "is_word": True,
        "normalized_source": resolved_term,
        "translation": translation,
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


def test_word_analysis_retries_all_caps_proper_noun_as_lowercase(monkeypatch) -> None:
    context = (
        "ER ERINNERTE SICH AN diese alte Eiche, die mit dem gespaltenen Stamm."
    )
    parsed_contexts = []

    def pipeline(parsed_context):
        parsed_contexts.append(parsed_context)
        if parsed_context == context:
            words = [
                SimpleNamespace(
                    text="ERINNERTE",
                    lemma="ERINNERTE",
                    upos="PROPN",
                    start_char=3,
                    end_char=12,
                )
            ]
        else:
            words = [
                parsed_word(
                    "erinnerte", "erinnern", "VERB", 3, 12, 2
                ),
                parsed_word(
                    "sich",
                    "sich",
                    "PRON",
                    13,
                    17,
                    3,
                    head=2,
                    deprel="obj",
                ),
            ]
        return SimpleNamespace(sentences=[SimpleNamespace(words=words)])

    monkeypatch.setattr(
        "pdf_language_learner.app.stanza_pipeline", lambda _: pipeline
    )

    analysis = analyze_word_in_context(
        "ERINNERTE", "German", context, context.index("ERINNERTE")
    )

    assert parsed_contexts == [context, context.lower()]
    assert analysis == WordAnalysis(
        "erinnerte sich",
        "erinnern",
        "VERB",
        ("sich",),
        "sich erinnern",
    )


def parsed_word(
    text,
    lemma,
    upos,
    start,
    end,
    word_id,
    *,
    head=0,
    deprel="root",
    feats=None,
):
    return SimpleNamespace(
        text=text,
        lemma=lemma,
        upos=upos,
        start_char=start,
        end_char=end,
        id=word_id,
        head=head,
        deprel=deprel,
        feats=feats,
    )


@pytest.mark.parametrize(
    ("selected_text", "language", "context", "offset", "words", "expected"),
    [
        (
            "steht",
            "German",
            "Er steht früh auf.",
            3,
            [
                parsed_word("Er", "er", "PRON", 0, 2, 1, head=2, deprel="nsubj"),
                parsed_word("steht", "stehen", "VERB", 3, 8, 2),
                parsed_word(
                    "auf",
                    "auf",
                    "ADP",
                    14,
                    17,
                    4,
                    head=2,
                    deprel="compound:prt",
                ),
            ],
            WordAnalysis("steht auf", "aufstehen", "VERB"),
        ),
        (
            "erinnere",
            "German",
            "Ich erinnere mich daran.",
            4,
            [
                parsed_word("erinnere", "erinnern", "VERB", 4, 12, 2),
                parsed_word(
                    "mich",
                    "sich",
                    "PRON",
                    13,
                    17,
                    3,
                    head=2,
                    deprel="obj",
                    feats="Case=Acc|Reflex=Yes",
                ),
            ],
            WordAnalysis(
                "erinnere mich", "erinnern", "VERB", ("mich",)
            ),
        ),
        (
            "levanto",
            "Spanish",
            "Me levanto temprano.",
            3,
            [
                parsed_word(
                    "Me",
                    "yo",
                    "PRON",
                    0,
                    2,
                    1,
                    head=2,
                    deprel="expl:pv",
                ),
                parsed_word("levanto", "levantar", "VERB", 3, 10, 2),
            ],
            WordAnalysis("Me levanto", "levantar", "VERB", ("Me",)),
        ),
        (
            "pongo",
            "Spanish",
            "Me pongo el pijama.",
            3,
            [
                parsed_word(
                    "Me",
                    "yo",
                    "PRON",
                    0,
                    2,
                    1,
                    head=2,
                    deprel="obl:arg",
                    feats="Number=Sing|Person=1|PronType=Prs",
                ),
                parsed_word(
                    "pongo",
                    "poner",
                    "VERB",
                    3,
                    8,
                    2,
                    feats="Number=Sing|Person=1|VerbForm=Fin",
                ),
            ],
            WordAnalysis("Me pongo", "poner", "VERB", ("Me",)),
        ),
        (
            "preparo",
            "Spanish",
            "Me preparo para salir.",
            3,
            [
                parsed_word(
                    "Me",
                    "yo",
                    "PRON",
                    0,
                    2,
                    1,
                    head=2,
                    deprel="expl:pv",
                    feats="Number=Sing|Person=1|PronType=Prs",
                ),
                parsed_word(
                    "preparo",
                    "preparar",
                    "VERB",
                    3,
                    10,
                    2,
                    feats="Number=Sing|Person=1|VerbForm=Fin",
                ),
            ],
            WordAnalysis(
                "Me preparo",
                "preparar",
                "VERB",
                ("Me",),
                "prepararse",
            ),
        ),
        (
            "ducho",
            "Spanish",
            "Me ducho por la mañana.",
            3,
            [
                parsed_word(
                    "Me",
                    "yo",
                    "PRON",
                    0,
                    2,
                    1,
                    head=2,
                    deprel="expl:pv",
                    feats="Number=Sing|Person=1|PronType=Prs",
                ),
                parsed_word(
                    "ducho",
                    "ducir",
                    "VERB",
                    3,
                    8,
                    2,
                    feats="Number=Sing|Person=1|VerbForm=Fin",
                ),
            ],
            WordAnalysis(
                "Me ducho",
                "duchar",
                "VERB",
                ("Me",),
                "ducharse",
            ),
        ),
        (
            "veo",
            "Spanish",
            "Lo veo claramente.",
            3,
            [
                parsed_word(
                    "Lo", "él", "PRON", 0, 2, 1, head=2, deprel="obj"
                ),
                parsed_word("veo", "ver", "VERB", 3, 6, 2),
            ],
            WordAnalysis("Lo veo", "ver", "VERB", ("Lo",)),
        ),
    ],
)
def test_verb_analysis_detects_dependency_linked_components(
    monkeypatch, selected_text, language, context, offset, words, expected
) -> None:
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=words)]
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.stanza_pipeline", lambda _: pipeline
    )

    assert analyze_word_in_context(
        selected_text, language, context, offset
    ) == expected


def test_verb_analysis_ignores_unattached_reflexive_pronoun(monkeypatch) -> None:
    words = [
        parsed_word("me", "yo", "PRON", 0, 2, 1, head=3, deprel="obj"),
        parsed_word("habla", "hablar", "VERB", 3, 8, 2),
    ]
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=words)]
    )
    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    analysis = analyze_word_in_context("habla", "Spanish", "Me habla.", 3)

    assert analysis == WordAnalysis("habla", "hablar", "VERB")


def test_spanish_verb_analysis_detects_non_reflexive_clitic(monkeypatch) -> None:
    words = [
        parsed_word(
            "Me",
            "yo",
            "PRON",
            0,
            2,
            1,
            head=2,
            deprel="expl:pv",
            feats="Number=Sing|Person=1|PronType=Prs",
        ),
        parsed_word(
            "ve",
            "ver",
            "VERB",
            3,
            5,
            2,
            feats="Number=Sing|Person=3|VerbForm=Fin",
        ),
    ]
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=words)]
    )
    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    analysis = analyze_word_in_context("ve", "Spanish", "Me ve.", 3)

    assert analysis == WordAnalysis("Me ve", "ver", "VERB", ("Me",))


def test_spanish_verb_analysis_detects_clitic_climbing(monkeypatch) -> None:
    words = [
        parsed_word("Me", "yo", "PRON", 0, 2, 1, head=2, deprel="expl:pv"),
        parsed_word("quiero", "querer", "VERB", 3, 9, 2),
        parsed_word(
            "acostar", "acostar", "VERB", 10, 17, 3, head=2,
            deprel="xcomp",
        ),
    ]
    pipeline = lambda text: SimpleNamespace(
        sentences=[SimpleNamespace(words=words)]
    )
    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    analysis = analyze_word_in_context(
        "acostar", "Spanish", "Me quiero acostar.", 10
    )

    assert analysis == WordAnalysis(
        "Me acostar", "acostar", "VERB", ("Me",)
    )


def test_spanish_verb_analysis_detects_clitics_inside_surface_token(
    monkeypatch,
) -> None:
    words = [
        parsed_word("Da", "dar", "VERB", None, None, 1),
        parsed_word(
            "me", "yo", "PRON", None, None, 2, head=1,
            deprel="obl:arg",
        ),
        # Stanza can misattach a clitic in an imperative, but its membership in
        # the same surface token still makes it a valid stage-one candidate.
        parsed_word(
            "lo", "él", "PRON", None, None, 3, head=4, deprel="det"
        ),
        parsed_word("mañana", "mañana", "NOUN", 7, 13, 4, head=1),
    ]
    surface_token = SimpleNamespace(
        text="Dámelo", start_char=0, end_char=6, words=words[:3]
    )
    mañana_token = SimpleNamespace(
        text="mañana", start_char=7, end_char=13, words=words[3:]
    )
    pipeline_calls = 0

    def pipeline(text):
        nonlocal pipeline_calls
        pipeline_calls += 1
        return SimpleNamespace(
            sentences=[
                SimpleNamespace(
                    words=words, tokens=[surface_token, mañana_token]
                )
            ]
        )

    monkeypatch.setattr("pdf_language_learner.app.stanza_pipeline", lambda _: pipeline)

    args = ("Dámelo", "Spanish", "Dámelo mañana.", 0)
    analysis = analyze_word_in_context(*args)
    repeated = analyze_word_in_context(*args)

    assert analysis == WordAnalysis(
        "Da me lo", "dar", "VERB", ("me", "lo")
    )
    assert repeated is analysis
    assert pipeline_calls == 1
    assert analyze_word_in_context.cache_info().hits == 1


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


def test_wordnet_candidates_keep_same_part_of_speech_and_remove_source(
    monkeypatch,
) -> None:
    class FakeSynset:
        def __init__(self, lemmas):
            self._lemmas = lemmas

        def lemmas(self):
            return self._lemmas

    class FakeWordnet:
        def synsets(self, lemma, pos):
            assert (lemma, pos) == ("schnell", "a")
            return [
                FakeSynset(["schnell", "rasch", "flink"]),
                FakeSynset(["rasch", "geschwind"]),
            ]

    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_for_language",
        lambda language: FakeWordnet(),
    )

    assert wordnet_synonym_candidates("schnell", "German", "ADJ") == SynonymCandidateSet(
        values=("rasch", "flink", "geschwind"),
        sense_count=2,
    )


def test_wordnet_candidates_recover_from_an_overly_strict_pos(monkeypatch) -> None:
    class FakeSynset:
        def __init__(self, lemmas):
            self._lemmas = lemmas

        def lemmas(self):
            return self._lemmas

    class FakeWordnet:
        def synsets(self, lemma, pos=None):
            assert lemma == "schnell"
            return (
                [FakeSynset(["schnell"])]
                if pos == "a"
                else [FakeSynset(["schnell", "rasch"])]
            )

    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_for_language",
        lambda language: FakeWordnet(),
    )

    assert wordnet_synonym_candidates(
        "schnell", "German", "ADJ"
    ) == SynonymCandidateSet(
        values=("rasch",), sense_count=1, used_pos_fallback=True
    )


def test_synonym_candidates_are_frequency_sorted_and_rare_words_removed(
    monkeypatch,
) -> None:
    frequencies = {
        "schnell": 5.0,
        "alltäglich": 4.7,
        "gebräuchlich": 3.1,
        "veraltet": 2.9,
        "verschollen": 0.0,
    }
    monkeypatch.setattr(
        "pdf_language_learner.app.zipf_frequency",
        lambda word, language: frequencies[word],
    )

    assert frequency_ranked_synonym_candidates(
        "schnell",
        "German",
        ("verschollen", "gebräuchlich", "alltäglich", "veraltet"),
    ) == ("alltäglich", "gebräuchlich")


def test_synonym_frequency_filter_preserves_candidates_without_corpus_data(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "pdf_language_learner.app.zipf_frequency",
        lambda word, language: 0.0,
    )
    candidates = ("unbekanntes Wort", "weiteres Wort")

    assert frequency_ranked_synonym_candidates(
        "Ausgangswort", "German", candidates
    ) == candidates


def test_synonym_candidates_reject_an_incompatible_part_of_speech(
    monkeypatch,
) -> None:
    pipeline_calls = []

    def pipeline(text):
        pipeline_calls.append(text)
        return SimpleNamespace(sentences=[
            SimpleNamespace(words=[SimpleNamespace(text="eventuell", upos="ADV")]),
            SimpleNamespace(words=[SimpleNamespace(text="mögen", upos="VERB")]),
            SimpleNamespace(
                words=[SimpleNamespace(text="möglicherweise", upos="ADV")]
            ),
            SimpleNamespace(
                words=[SimpleNamespace(text="wahrscheinlich", upos="ADJ")]
            ),
        ])

    monkeypatch.setattr(
        "pdf_language_learner.app.stanza_pipeline", lambda language: pipeline
    )

    assert part_of_speech_filtered_synonym_candidates(
        "German",
        "ADV",
        ("eventuell", "mögen", "möglicherweise", "wahrscheinlich"),
    ) == ("eventuell", "möglicherweise", "wahrscheinlich")
    assert pipeline_calls == [
        "Das ist eventuell richtig. Das ist mögen richtig. "
        "Das ist möglicherweise richtig. Das ist wahrscheinlich richtig."
    ]


def test_synonyms_are_ranked_by_context_and_restricted_to_wordnet(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

        def chat(self, **kwargs):
            assert kwargs["format"]["required"] == ["synonyms"]
            assert kwargs["options"]["num_predict"] == 64
            assert "useful close synonyms" in kwargs["messages"][0]["content"]
            prompt = kwargs["messages"][1]["content"]
            assert "Source lemma: schnell" in prompt
            assert "Das Auto ist sehr schnell." in prompt
            assert "flink, rasch" in prompt
            assert "eilig" not in prompt
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "synonyms": ["rasch", "erfunden", "RASCH", "flink"]
            })))

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("schnell", "schnell", "ADJ"),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: SynonymCandidateSet(
            values=("rasch", "flink", "eilig"), sense_count=2
        ),
    )
    frequencies = {
        "schnell": 5.0,
        "rasch": 4.2,
        "flink": 4.5,
        "eilig": 2.0,
    }
    monkeypatch.setattr(
        "pdf_language_learner.app.zipf_frequency",
        lambda word, language: frequencies[word],
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", FakeClient)

    response = client.post(
        "/api/synonyms",
        json={
            "text": "schnell",
            "source_language": "German",
            "context": "Das Auto ist sehr schnell.",
            "context_offset": 18,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": "German",
        "normalized_source": "schnell",
        "noun_gender": None,
        "synonyms": [
            {"text": "rasch", "noun_gender": None},
            {"text": "flink", "noun_gender": None},
        ],
    }


def test_synonyms_skip_ollama_when_wordnet_has_no_candidates(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, host: str) -> None:
            raise AssertionError("Ollama should not run without WordNet candidates")

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis(
            "Wort", "Wort", "NOUN", noun_gender="neutral"
        ),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: SynonymCandidateSet(values=(), sense_count=0),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", UnexpectedClient)

    response = client.post(
        "/api/synonyms",
        json={"text": "Wort", "source_language": "German"},
    )

    assert response.status_code == 200
    assert response.json()["synonyms"] == []


def test_noun_synonyms_include_local_articles_and_gender(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, host: str) -> None:
            raise AssertionError("A single WordNet sense should stay model-free")

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis(
            "Haus", "Haus", "NOUN", noun_gender="neutral"
        ),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: SynonymCandidateSet(
            values=("Gebäude", "Heim"), sense_count=1
        ),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.local_noun_grammars",
        lambda lemmas, language: tuple(
            SourceNounGrammar(article="das", gender="neutral") for _ in lemmas
        ),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", UnexpectedClient)

    response = client.post(
        "/api/synonyms",
        json={"text": "Haus", "source_language": "German"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detected_language": "German",
        "normalized_source": "das Haus",
        "noun_gender": "neutral",
        "synonyms": [
            {"text": "das Gebäude", "noun_gender": "neutral"},
            {"text": "das Heim", "noun_gender": "neutral"},
        ],
    }


def test_synonyms_skip_ollama_for_a_single_wordnet_sense(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, host: str) -> None:
            raise AssertionError("One unambiguous sense does not need ranking")

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("veloz", "veloz", "ADJ"),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: SynonymCandidateSet(
            values=("rápido", "ligero", "acelerado", "velozmente"),
            sense_count=1,
        ),
    )
    monkeypatch.setattr("pdf_language_learner.app.Client", UnexpectedClient)

    response = client.post(
        "/api/synonyms",
        json={
            "text": "veloz",
            "source_language": "Spanish",
            "context": "Es un corredor veloz.",
        },
    )

    assert response.status_code == 200
    assert response.json()["synonyms"] == [
        {"text": "rápido", "noun_gender": None},
        {"text": "ligero", "noun_gender": None},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "quick", "source_language": "English"},
        {"text": "muy rápido", "source_language": "Spanish"},
    ],
)
def test_synonyms_reject_unsupported_lookup(payload) -> None:
    response = client.post("/api/synonyms", json=payload)

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
    return tmp_path


def vocabulary_payload(**overrides) -> dict[str, str]:
    payload = {
        "original_source": "Wörter",
        "normalized_source": "Wort",
        "translation": "word",
        "source_language": "German",
        "target_language": "English",
        "context": "Viele Wörter ergeben einen Satz.",
        "document_key": "margin:example.pdf:123:456",
        "noun_gender": "neutral",
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
    assert items[0]["noun_gender"] == "neutral"
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


def test_vocabulary_uses_and_lists_language_specific_tables(
    vocabulary_database,
) -> None:
    client.post("/api/vocabulary", json=vocabulary_payload())
    client.post(
        "/api/vocabulary",
        json=vocabulary_payload(
            original_source="books",
            normalized_source="book",
            source_language="English",
            translation="Buch",
            target_language="German",
        ),
    )

    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert "vocabulary" not in tables
    assert {"vocabulary_german", "vocabulary_english"} <= tables
    assert client.get("/api/vocabulary/languages").json() == ["English", "German"]
    german = client.get("/api/vocabulary", params={"language": "German"}).json()
    english = client.get("/api/vocabulary", params={"language": "English"}).json()
    assert [item["normalized_source"] for item in german] == ["Wort"]
    assert [item["normalized_source"] for item in english] == ["book"]


def test_legacy_vocabulary_table_is_migrated(vocabulary_database) -> None:
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.execute(
            """
            CREATE TABLE vocabulary (
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
            INSERT INTO vocabulary (
                id, original_source, normalized_source, canonical_source,
                translation, source_language, canonical_source_language,
                target_language, context, document_key, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-id", "Wörter", "Wort", "wort", "word", "German",
                "german", "English", "Viele Wörter.", "legacy-document",
                "2026-08-23T12:00:00+00:00",
            ),
        )

    assert client.get("/api/vocabulary/languages").json() == ["German"]
    items = client.get("/api/vocabulary", params={"language": "German"}).json()
    assert [item["id"] for item in items] == ["legacy-id"]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "vocabulary" not in tables
    assert "vocabulary_german" in tables


def test_vocabulary_can_be_deleted(vocabulary_database) -> None:
    item_id = client.post("/api/vocabulary", json=vocabulary_payload()).json()["item"]["id"]

    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    assert client.get("/api/vocabulary").json() == []
    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 404


def test_deleted_vocabulary_is_removed_from_revision(vocabulary_database) -> None:
    item_id = client.post(
        "/api/vocabulary", json=vocabulary_payload()
    ).json()["item"]["id"]

    assert client.get("/api/revision/session").json()["due_count"] == 1
    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    assert client.get("/api/revision/session").json() == {
        "cards": [],
        "due_count": 0,
    }


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
    assert all(card["exercise"] == "multiple_choice" for card in session["cards"])
    assert all(card["category"] == "new" for card in session["cards"])
    assert all(card["noun_gender"] == "neutral" for card in session["cards"])
    for card in session["cards"]:
        if card["direction"] == "translation_to_source":
            assert card["choice_genders"] == {
                choice: "neutral" for choice in card["choices"]
            }
        else:
            assert card["choice_genders"] == {}


def test_revision_session_only_uses_selected_language(vocabulary_database) -> None:
    german = save_revision_vocabulary()
    for source, translation in (("book", "Buch"), ("cat", "Katze")):
        client.post(
            "/api/vocabulary",
            json=vocabulary_payload(
                original_source=source,
                normalized_source=source,
                translation=translation,
                source_language="English",
                target_language="German",
            ),
        )

    session = client.get(
        "/api/revision/session", params={"language": "German"}
    ).json()

    assert session["due_count"] == 4
    assert {card["item_id"] for card in session["cards"]} == {
        item["id"] for item in german
    }
    assert all(card["source_language"] == "German" for card in session["cards"])


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


def test_revision_without_distractors_uses_typed_recall(vocabulary_database) -> None:
    item = client.post("/api/vocabulary", json=vocabulary_payload()).json()["item"]

    session = client.get("/api/revision/session").json()

    assert session["due_count"] == 1
    assert len(session["cards"]) == 1
    card = session["cards"][0]
    assert card["item_id"] == item["id"]
    assert card["exercise"] == "typed_recall"
    assert card["choices"] == []
    assert card["category"] == "new"


def test_familiar_due_vocabulary_uses_typed_recall(vocabulary_database) -> None:
    saved = save_revision_vocabulary()
    item = saved[0]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.execute(
            """
            UPDATE vocabulary_german
            SET repetitions = 1, consecutive_correct = 1,
                next_review_at = '2026-08-22T12:00:00+00:00'
            WHERE id = ?
            """,
            (item["id"],),
        )

    session = client.get("/api/revision/session").json()
    card = next(card for card in session["cards"] if card["item_id"] == item["id"])

    assert card["category"] == "usually_correct"
    assert card["exercise"] == "typed_recall"
    assert card["choices"] == []


def test_revision_of_unknown_word_returns_not_found(vocabulary_database) -> None:
    response = client.post(
        "/api/revision/missing/answer",
        json={
            "direction": "source_to_translation",
            "selected_answer": "word",
        },
    )

    assert response.status_code == 404
