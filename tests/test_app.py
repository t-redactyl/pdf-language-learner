import json
import os
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
    anthropic_client,
    anthropic_grammar_effort,
    anthropic_grammar_generation_tokens,
    anthropic_grammar_model,
    anthropic_structured_model_response,
    app,
    cached_model_translation,
    cached_ranked_synonyms,
    cached_source_noun_grammar,
    cached_verb_lemma_decision,
    dictionary_synonym_candidates,
    enrich_connector_sentence,
    frequency_ranked_synonym_candidates,
    load_local_environment,
    multi_word_term_in_context,
    openai_client,
    open_thesaurus_synonym_candidates,
    parse_open_thesaurus,
    part_of_speech_filtered_synonym_candidates,
    stanza_pipeline,
    strict_json_schema,
    translation_model,
    wordnet_synonym_candidates,
)
from pdf_language_learner.grammar_revision import GrammarGrade

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_runtime_caches(monkeypatch):
    # Tests replace model and NLP dependencies with purpose-built fakes. Ensure
    # cached results and clients cannot leak from one test into the next.
    for cached_function in (
        anthropic_client,
        openai_client,
        analyze_word_in_context,
        cached_verb_lemma_decision,
        cached_source_noun_grammar,
        cached_model_translation,
        cached_ranked_synonyms,
        frequency_ranked_synonym_candidates,
        open_thesaurus_synonym_candidates,
        part_of_speech_filtered_synonym_candidates,
        wordnet_synonym_candidates,
    ):
        cached_function.cache_clear()
    monkeypatch.setattr("pdf_language_learner.app.OPEN_THESAURUS_INDEX", {})
    LOCAL_NOUN_GRAMMAR_CACHE.clear()
    yield
    for cached_function in (
        openai_client,
        analyze_word_in_context,
        cached_verb_lemma_decision,
        cached_source_noun_grammar,
        cached_model_translation,
        cached_ranked_synonyms,
        frequency_ranked_synonym_candidates,
        open_thesaurus_synonym_candidates,
        part_of_speech_filtered_synonym_candidates,
        wordnet_synonym_candidates,
    ):
        cached_function.cache_clear()
    LOCAL_NOUN_GRAMMAR_CACHE.clear()


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_local_environment_file_is_loaded_without_overriding_exports(
    monkeypatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MARGIN_TEST_FROM_FILE=loaded\nMARGIN_TEST_EXPORTED=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MARGIN_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("MARGIN_TEST_EXPORTED", "exported-value")

    load_local_environment(env_file)

    assert os.environ["MARGIN_TEST_FROM_FILE"] == "loaded"
    assert os.environ["MARGIN_TEST_EXPORTED"] == "exported-value"


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
    assert 'id="revision-matching"' in response.text
    assert 'id="revision-connector-hint"' in response.text
    assert 'id="revision-exercise-selector"' in response.text
    assert 'id="revision-mode-grammar"' in response.text
    assert 'id="grammar-session"' in response.text
    assert 'id="grammar-topic-list"' in response.text
    assert 'id="revision-loading-copy"' in response.text
    assert 'class="revision-loading-mark"' in response.text
    assert 'data-i18n="hero.title"' in response.text
    assert '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">' in response.text
    assert 'id="pdf-zoom-toolbar"' in response.text
    assert 'id="pdf-zoom-out"' in response.text
    assert 'id="pdf-zoom-in"' in response.text
    assert 'id="toggle-translation-panel"' in response.text
    assert 'aria-controls="translation-panel-body"' in response.text
    assert '/static/styles.css?v=45' in response.text
    assert '/static/revision.js?v=35' in response.text
    assert '/static/app.js?v=46' in response.text
    assert 'id="suggestions-groups"' in response.text
    assert 'id="translation-vocabulary-toggle"' in response.text


def test_favicon_is_served() -> None:
    response = client.get("/static/favicon.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert 'viewBox="0 0 64 64"' in response.text


def test_frontend_entry_points_share_current_dependency_versions() -> None:
    app_script = client.get("/static/app.js").text
    revision_script = client.get("/static/revision.js").text
    grammar_script = client.get("/static/grammar.js").text
    i18n_script = client.get("/static/i18n.js").text
    styles = client.get("/static/styles.css").text
    text_script = client.get("/static/text.js").text

    assert './text.js?v=5' in app_script
    assert './text.js?v=5' in revision_script
    assert './i18n.js?v=20' in app_script
    assert './i18n.js?v=20' in revision_script
    assert './i18n.js?v=20' in grammar_script
    assert './grammar.js?v=9' in revision_script
    assert 'revisionMode === "grammar" ? "grammar.generating"' in revision_script
    assert '"grammar.generating": "Generating the next grammar exercise…"' in i18n_script
    assert '"grammar.reviewRules.other": "Reviewing {count} grammar rules"' in i18n_script
    assert "function renderTopicHeading()" in grammar_script
    assert "function ruleSummaryPoints(summary)" in grammar_script
    assert "function shuffledOrderingTokens(tokens)" in grammar_script
    assert "orderingTokens.forEach(({ index, token })" in grammar_script
    assert "function orderingAnswer()" in grammar_script
    assert "@keyframes margin-loading-bounce" not in styles
    assert "@keyframes margin-loading-typeface" in styles
    assert "@media (prefers-reduced-motion:reduce)" in styles
    assert (
        'document.querySelectorAll("#grammar-exercise button, #grammar-exercise input")'
        in grammar_script
    )
    assert "control.disabled = false" in grammar_script
    assert 'fetch("/api/suggestions")' in app_script
    assert 'fetch("/api/listening-history"' in app_script
    assert 'new window.Hls({ capLevelToPlayerSize: true, startLevel: 0 })' in app_script
    assert app_script.index("window.Hls?.isSupported()") < app_script.index(
        'video.canPlayType("application/vnd.apple.mpegurl")'
    )
    assert 'currentCard.contextual_gloss || currentCard.glosses[0] || ""' in revision_script
    assert 'currentCard.glosses.join(" / ")' not in revision_script
    assert 'renderConnectorSentence($("#revision-prompt-context"), card, true)' in revision_script
    assert 'renderConnectorSentence($("#revision-context"), card, true)' not in revision_script
    assert '$("#revision-choices").hidden = true' in revision_script
    assert "const remainingOptions = tileOptions.filter" in revision_script
    assert "pool.hidden = !remainingOptions.length || tilesLocked" in revision_script
    assert "controls.hidden = tilesLocked" in revision_script
    assert "hint_used: hintUsed" in revision_script
    assert "function revealTypedHint()" in revision_script
    assert "function revealTileHint()" in revision_script
    assert "export function renderClozeSentence" in text_script
    assert "originalSource: data.original_source || selectedText" in app_script
    assert "findWholeWordIgnoringCase" in text_script
    assert "renderVocabularyFeedbackContext(currentCard)" in revision_script
    assert "renderHighlightedSentence(element, context, [surfaceForm])" in revision_script
    assert '$("#revision-context").hidden = true' in revision_script
    assert "const measuredRange = expandHyphenatedWordRange(range);" in app_script
    assert "drag ? range : expandHyphenatedWordRange(range)" not in app_script
    assert "previousEndsWithUnselectedHyphen" in app_script
    assert "characters.slice(end)" in app_script


def test_narrow_library_keeps_history_and_saved_vocabulary_independently_scrollable() -> None:
    styles = client.get("/static/styles.css").text

    assert ".reader.meta-open #translation-history-list { max-height:38vh; overflow:auto; }" in styles
    assert ".reader.meta-open #saved-vocabulary-list { max-height:28vh; overflow:auto; }" in styles


def test_tablet_translation_panel_keeps_all_three_sections_on_one_row() -> None:
    styles = client.get("/static/styles.css").text

    assert "@media (max-width:760px)" in styles
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in styles
    assert "@media (max-width:600px)" in styles


def test_mobile_translation_panel_can_collapse_to_a_reading_handle() -> None:
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert 'setTranslationPanelCollapsed(!$(".translation-panel").classList.contains("is-collapsed"))' in script
    assert '.translation-panel.is-collapsed .translation-panel-body { display:none; }' in styles
    assert '.translation-panel-collapsed .pages { padding-bottom:68px; }' in styles
    assert 'viewBox="0 0 20 20"' in client.get("/").text
    assert '.translation-panel.is-collapsed .translation-panel-toggle-icon { transform:rotate(180deg); }' in styles


def test_mobile_translation_panel_can_toggle_saved_vocabulary() -> None:
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert '$("#translation-vocabulary-toggle")?.addEventListener("click"' in script
    assert "await toggleSavedVocabulary(displayedTranslation)" in script
    assert "button.hidden = !isWord" in script
    assert ".translation-vocabulary-toggle { display:none; }" in styles
    assert 'class="translation-panel-heading-actions"' in client.get("/").text
    assert ".translation-panel .translation-vocabulary-toggle { display:grid; width:26px; height:26px;" in styles
    assert ".translation-vocabulary-icon { color:inherit; font-size:20px;" in styles


def test_pdf_zoom_scales_only_the_document_and_keeps_highlights_relative() -> None:
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert "const PDF_ZOOM_LEVELS = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5]" in script
    assert "fitWidth * PDF_ZOOM_LEVELS[pdfZoomIndex]" in script
    assert "rect.x*100" in script
    assert ".pages-scroll {" in styles
    assert "overflow-x:auto" in styles


def test_pdf_pages_are_virtualized_to_limit_mobile_canvas_memory() -> None:
    script = client.get("/static/app.js").text

    assert 'rootMargin: "1200px 0px"' in script
    assert "Math.min(window.devicePixelRatio || 1, 1.5)" in script
    assert "releasePdfPage(entry.target)" in script
    assert 'wrapper.querySelector("canvas")?.remove()' in script


def test_spanish_interface_catalog_is_served() -> None:
    response = client.get("/static/i18n.js")

    assert response.status_code == 200
    assert "Convierte la lectura en otros idiomas" in response.text
    assert 'localStorage.setItem(STORAGE_KEY, locale)' in response.text


def test_openai_client_is_reused_and_configured(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

    assert openai_client() is openai_client()
    assert len(created) == 1
    assert created[0].kwargs == {"timeout": 12.5, "max_retries": 1}


def test_anthropic_client_is_reused_and_configured(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setenv("ANTHROPIC_TIMEOUT_SECONDS", "45")
    monkeypatch.setattr("pdf_language_learner.app.Anthropic", FakeClient)

    assert anthropic_client() is anthropic_client()
    assert len(created) == 1
    assert created[0].kwargs == {"timeout": 45.0, "max_retries": 1}


def test_anthropic_grammar_model_is_required(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_GRAMMAR_MODEL", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_GRAMMAR_MODEL"):
        anthropic_grammar_model()

    monkeypatch.setenv("ANTHROPIC_GRAMMAR_MODEL", "example-claude-model")
    assert anthropic_grammar_model() == "example-claude-model"


def test_anthropic_grammar_generation_settings(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_GRAMMAR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("ANTHROPIC_GRAMMAR_EFFORT", raising=False)
    assert anthropic_grammar_generation_tokens() == 12000
    assert anthropic_grammar_effort() == "medium"

    monkeypatch.setenv("ANTHROPIC_GRAMMAR_MAX_OUTPUT_TOKENS", "16000")
    monkeypatch.setenv("ANTHROPIC_GRAMMAR_EFFORT", "high")
    assert anthropic_grammar_generation_tokens() == 16000
    assert anthropic_grammar_effort() == "high"


def test_anthropic_structured_response_separates_system_message(
    monkeypatch,
) -> None:
    calls = []
    parsed = GrammarGrade(correct=True, feedback="Correct form.")
    response = SimpleNamespace(
        parsed_output=parsed,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=20, output_tokens=8),
    )

    class FakeMessages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return response

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        "pdf_language_learner.app.anthropic_client", lambda: fake_client
    )
    monkeypatch.setenv("ANTHROPIC_GRAMMAR_MODEL", "example-claude-model")

    content = anthropic_structured_model_response(
        "grammar answer grading",
        messages=[
            {"role": "system", "content": "Grade precisely."},
            {"role": "user", "content": "Learner answer: hablo"},
        ],
        response_model=GrammarGrade,
        max_output_tokens=250,
    )

    assert json.loads(content) == {
        "correct": True,
        "feedback": "Correct form.",
    }
    assert calls == [
        {
            "model": "example-claude-model",
            "max_tokens": 250,
            "system": "Grade precisely.",
            "messages": [
                {"role": "user", "content": "Learner answer: hablo"}
            ],
            "output_format": GrammarGrade,
            "output_config": {"effort": "low"},
        }
    ]


def test_translation_model_defaults_and_can_be_overridden(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert translation_model() == "gpt-5.6-luna"

    monkeypatch.setenv("OPENAI_MODEL", "example-model")
    assert translation_model() == "example-model"


def test_strict_json_schema_requires_all_object_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "translation": {"type": "string"},
            "detail": {
                "type": "object",
                "properties": {"gender": {"type": "string"}},
            },
        },
    }

    strict = strict_json_schema(schema)

    assert strict["required"] == ["translation", "detail"]
    assert strict["additionalProperties"] is False
    assert strict["properties"]["detail"]["required"] == ["gender"]
    assert strict["properties"]["detail"]["additionalProperties"] is False


def test_identical_translation_requests_reuse_cached_model_result(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=json.dumps({"translation": "How are you?"}), usage=None)

    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
    assert calls[0]["model"] == "gpt-5.6-luna"
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 128
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    assert calls[0]["text"]["format"]["strict"] is True
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
        def __init__(self, **kwargs) -> None:
            raise AssertionError("language detection must not contact OpenAI")

    monkeypatch.setattr("pdf_language_learner.app.OpenAI", UnexpectedClient)
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            required = set(kwargs["text"]["format"]["schema"]["required"])
            if required == {"article", "gender"}:
                prompt = kwargs["input"][1]["content"]
                assert f"Normalized dictionary lemma: {analysis.lemma}" in prompt
                assert "Selected token:" not in prompt
                assert "Surrounding context:" not in prompt
                if source.casefold() != analysis.lemma.casefold():
                    assert source not in prompt
                assert kwargs["text"]["format"]["schema"]["properties"]["article"][
                    "enum"
                ] == list({
                    "German": ("der", "die", "das"),
                    "Italian": ("il", "lo", "la", "l'"),
                    "English": ("the",),
                    "Spanish": ("el", "la"),
                }[source_language])
                return SimpleNamespace(output_text=json.dumps({
                        "article": model_response["source_definite_article"],
                        "gender": model_response["source_gender"],
                    }), usage=None)
            if analysis.pos == "NOUN":
                assert set(kwargs["text"]["format"]["schema"]["required"]) == {
                    "target_lemma",
                    "target_definite_article",
                }
            else:
                assert kwargs["text"]["format"]["schema"]["required"] == ["translation"]
            prompt = kwargs["input"][1]["content"]
            assert f"Part of speech (Universal POS): {analysis.pos}" in prompt
            assert f"Source lemma: {analysis.lemma}" in prompt
            assert (
                "Surrounding context (do not translate): Ein Beispiel im Kontext."
                in prompt
            )
            response_data = dict(model_response)
            response_data.pop("source_definite_article", None)
            response_data.pop("source_gender", None)
            return SimpleNamespace(output_text=json.dumps(response_data), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context", fake_analysis
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.local_noun_grammars",
        lambda lemmas, language: tuple(None for _ in lemmas),
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
        "original_source": source,
        "normalized_source": normalized_source,
        "translation": translation,
    }
    if model_response.get("source_gender") not in {None, "none"}:
        expected["noun_gender"] = model_response["source_gender"]
    assert response.json() == expected


def test_contextual_gender_removes_source_noun_model_lookup(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            calls.append(kwargs)
            assert set(kwargs["text"]["format"]["schema"]["required"]) == {
                "target_lemma",
                "target_definite_article",
            }
            return SimpleNamespace(output_text=json.dumps({
                "target_lemma": "house",
                "target_definite_article": "the",
            }), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis(
            "Häuser", "Haus", "NOUN", noun_gender="neutral"
        ),
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps({
                "translation": "probably / presumably",
            }), usage=None)

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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
        "original_source": "vermutlich",
        "normalized_source": "vermutlich",
        "translation": "probably / presumably",
        "synonyms": [
            {"text": "wahrscheinlich"},
            {"text": "wohl"},
        ],
    }
    assert synonym_calls == [
        (
            "gpt-5.6-luna",
            analysis,
            "German",
            "Das ist vermutlich richtig.",
        )
    ]


def test_local_target_grammar_overrides_model_article(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            required = set(kwargs["text"]["format"]["schema"]["required"])
            data = (
                {"article": "the", "gender": "none"}
                if required == {"article", "gender"}
                else {"target_lemma": "agua", "target_definite_article": "la"}
            )
            return SimpleNamespace(output_text=json.dumps(data), usage=None)

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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            nonlocal grammar_calls, translation_calls
            required = set(kwargs["text"]["format"]["schema"]["required"])
            if required == {"article", "gender"}:
                grammar_calls += 1
                data = {"article": "das", "gender": "neutral"}
            else:
                translation_calls += 1
                prompt = kwargs["input"][1]["content"]
                data = (
                    {"target_lemma": "house", "target_definite_article": "the"}
                    if "Target language: English" in prompt
                    else {"target_lemma": "maison", "target_definite_article": "la"}
                )
            return SimpleNamespace(output_text=json.dumps(data), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("Häuser", "Haus", "NOUN"),
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            calls.append(kwargs)
            rendezvous.wait(timeout=2)
            required = set(kwargs["text"]["format"]["schema"]["required"])
            data = (
                {"article": "das", "gender": "neutral"}
                if required == {"article", "gender"}
                else {"target_lemma": "house", "target_definite_article": "the"}
            )
            return SimpleNamespace(output_text=json.dumps(data), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("Häuser", "Haus", "NOUN"),
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            prompt = kwargs["input"][1]["content"]
            prompts.append(prompt)
            required = set(kwargs["text"]["format"]["schema"]["required"])
            if required == {"dictionary_lemma"}:
                assert f"Base verb lemma: {analysis.lemma}" in prompt
                assert (
                    f"Detected clitic candidates: "
                    f"{analysis.associated_clitics[0]}" in prompt
                )
                assert f"Full sentence context: {context}" in prompt
                return SimpleNamespace(output_text=json.dumps(decision), usage=None)
            assert required == {"translation"}
            assert f"Source lemma: {normalized_source}" in prompt
            return SimpleNamespace(output_text=json.dumps({"translation": model_translation}), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
    assert response.json()["original_source"] == analysis.token
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            assert kwargs["text"]["format"]["schema"]["required"] == ["translation"]
            prompt = kwargs["input"][1]["content"]
            assert "Source lemma: prepararse" in prompt
            return SimpleNamespace(output_text=json.dumps({"translation": "get ready"}), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
    assert response.json()["original_source"] == "Me preparo"
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            assert kwargs["text"]["format"]["schema"]["required"] == ["translation"]
            prompt = kwargs["input"][1]["content"]
            assert "Source lemma: sich erinnern" in prompt
            return SimpleNamespace(output_text=json.dumps({"translation": "remember"}), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: analysis,
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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
    assert response.json()["original_source"] == "erinnerte sich"
    assert response.json()["translation"] == "to remember"


def test_translate_retries_without_context_when_model_translates_excerpt(
    monkeypatch,
) -> None:
    prompts = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            prompts.append(kwargs["input"][1]["content"])
            translation = (
                "pleasant, compared to visiting Charlotte and her awful husband, "
                "while her cold fingers were forgotten as she danced along the path, "
                "occasionally stopping to admire the beautiful shapes of the "
                "snowflakes that surrounded her on the long journey home"
                if len(prompts) == 1
                else "do"
            )
            return SimpleNamespace(output_text=json.dumps({"translation": translation}), usage=None)

    monkeypatch.setattr(
        "pdf_language_learner.app.analyze_word_in_context",
        lambda *args: WordAnalysis("täte", "tun", "VERB"),
    )
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            prompt = kwargs["input"][1]["content"]
            assert f"Phrase to translate: {phrase}" in prompt
            assert "Dictionary form to translate" not in prompt
            return SimpleNamespace(output_text=json.dumps({"translation": translated_phrase}), usage=None)

    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
        "original_source": phrase,
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
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            prompt = kwargs["input"][1]["content"]
            assert f"Phrase to translate: {resolved_term}" in prompt
            return SimpleNamespace(output_text=json.dumps({"translation": translation}), usage=None)

    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)
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
        "original_source": resolved_term,
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


def test_open_thesaurus_parser_indexes_terms_and_removes_usage_labels() -> None:
    index = parse_open_thesaurus(
        "# OpenThesaurus export\n"
        "schnell (Adverb);rasch;flink (ugs.)\n"
        "sich beeilen;(sich) sputen (geh.)\n"
    )

    assert index["schnell"] == (("schnell", "rasch", "flink"),)
    assert index["flink"] == (("schnell", "rasch", "flink"),)
    assert index["sich sputen"] == (("sich beeilen", "sich sputen"),)


def test_open_thesaurus_parser_rejects_sentences_and_sayings() -> None:
    index = parse_open_thesaurus(
        "vorbei;Die Zeiten sind vorbei. (ugs., Spruch);vorüber\n"
        "irrelevant;Deine Sorgen möchte ich haben! (ugs.);belanglos\n"
        "egoistisch;Unterm Strich komm ich. (Slogan);selbstsüchtig\n"
        "beispielsweise;bspw.;z. B.\n"
    )

    assert index["vorbei"] == (("vorbei", "vorüber"),)
    assert index["irrelevant"] == (("irrelevant", "belanglos"),)
    assert index["egoistisch"] == (("egoistisch", "selbstsüchtig"),)
    assert index["beispielsweise"] == (("beispielsweise", "bspw.", "z. B."),)
    assert "die zeiten sind vorbei." not in index


def test_german_dictionary_candidates_merge_odenet_and_open_thesaurus(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: SynonymCandidateSet(
            values=("rasch", "flink"), sense_count=1
        ),
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.open_thesaurus_synonym_candidates",
        lambda lemma: SynonymCandidateSet(
            values=("flink", "zügig", "rapid"),
            sense_count=2,
            used_pos_fallback=True,
        ),
    )

    assert dictionary_synonym_candidates(
        "schnell", "German", "ADJ"
    ) == SynonymCandidateSet(
        values=("rasch", "flink", "zügig", "rapid"),
        sense_count=3,
        used_pos_fallback=True,
    )


def test_german_dictionary_candidates_fall_back_to_odenet(monkeypatch) -> None:
    wordnet_candidates = SynonymCandidateSet(
        values=("rasch",), sense_count=1
    )
    monkeypatch.setattr(
        "pdf_language_learner.app.wordnet_synonym_candidates",
        lambda *args: wordnet_candidates,
    )

    def unavailable_open_thesaurus(lemma):
        raise OSError("offline")

    monkeypatch.setattr(
        "pdf_language_learner.app.open_thesaurus_synonym_candidates",
        unavailable_open_thesaurus,
    )

    assert dictionary_synonym_candidates(
        "schnell", "German", "ADJ"
    ) is wordnet_candidates


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


def test_synonyms_are_ranked_by_context_and_restricted_to_dictionaries(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.responses = self

        def create(self, **kwargs):
            assert kwargs["text"]["format"]["schema"]["required"] == ["synonyms"]
            assert kwargs["max_output_tokens"] == 64
            assert "useful close synonyms" in kwargs["input"][0]["content"]
            prompt = kwargs["input"][1]["content"]
            assert "Source lemma: schnell" in prompt
            assert "Das Auto ist sehr schnell." in prompt
            assert "flink, rasch" in prompt
            assert "eilig" not in prompt
            return SimpleNamespace(output_text=json.dumps({
                "synonyms": ["rasch", "erfunden", "RASCH", "flink"]
            }), usage=None)

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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", FakeClient)

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


def test_synonyms_skip_openai_when_wordnet_has_no_candidates(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("OpenAI should not run without WordNet candidates")

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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", UnexpectedClient)

    response = client.post(
        "/api/synonyms",
        json={"text": "Wort", "source_language": "German"},
    )

    assert response.status_code == 200
    assert response.json()["synonyms"] == []


def test_noun_synonyms_include_local_articles_and_gender(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, **kwargs) -> None:
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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", UnexpectedClient)

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


def test_synonyms_skip_openai_for_a_single_wordnet_sense(monkeypatch) -> None:
    class UnexpectedClient:
        def __init__(self, **kwargs) -> None:
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
    monkeypatch.setattr("pdf_language_learner.app.OpenAI", UnexpectedClient)

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
    monkeypatch.setattr(
        "pdf_language_learner.app.enrich_connector_sentence",
        lambda sentence_id: None,
    )
    return tmp_path


def vocabulary_payload(**overrides) -> dict[str, object]:
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
    assert items[0]["synonyms"] == []
    assert items[0]["review"] == {
        "last_reviewed_at": None,
        "next_review_at": None,
        "repetitions": 0,
        "lapses": 0,
    }


def test_vocabulary_persists_ranked_synonyms(vocabulary_database) -> None:
    synonyms = [
        {"text": "Begriff", "noun_gender": "masculine"},
        {"text": "Ausdruck", "noun_gender": "masculine"},
    ]

    saved = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(synonyms=synonyms),
    )

    assert saved.status_code == 200
    item = saved.json()["item"]
    assert item["synonyms"] == synonyms
    assert client.get("/api/vocabulary").json()[0]["synonyms"] == synonyms
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        rows = connection.execute(
            """
            SELECT text, canonical_text, noun_gender, position
            FROM vocabulary_synonyms
            WHERE vocabulary_item_id = ?
            ORDER BY position
            """,
            (item["id"],),
        ).fetchall()
    assert rows == [
        ("Begriff", "begriff", "masculine", 0),
        ("Ausdruck", "ausdruck", "masculine", 1),
    ]


def test_vocabulary_excludes_self_and_duplicate_synonyms(vocabulary_database) -> None:
    self_synonym = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(synonyms=[{"text": " wort "}]),
    ).json()["item"]
    assert self_synonym["synonyms"] == []

    client.delete(f"/api/vocabulary/{self_synonym['id']}")
    duplicate_synonyms = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(
            synonyms=[{"text": "Begriff"}, {"text": " BEGRIFF "}],
        ),
    ).json()["item"]
    assert duplicate_synonyms["synonyms"] == [
        {"text": "Begriff", "noun_gender": None}
    ]


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
                "german", "English", "Obwohl es regnet, lesen wir.", "legacy-document",
                "2026-08-23T12:00:00+00:00",
            ),
        )

    assert client.get("/api/vocabulary/languages").json() == ["German"]
    items = client.get("/api/vocabulary", params={"language": "German"}).json()
    assert [item["id"] for item in items] == ["legacy-id"]
    assert items[0]["synonyms"] == []
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "vocabulary" not in tables
    assert "vocabulary_german" in tables
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        assert connection.execute(
            "SELECT connector_key FROM connector_occurrences"
        ).fetchone()[0] == "obwohl"


def test_vocabulary_can_be_deleted(vocabulary_database) -> None:
    item_id = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(synonyms=[{"text": "Begriff"}]),
    ).json()["item"]["id"]

    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    assert client.get("/api/vocabulary").json() == []
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        synonym_count = connection.execute(
            "SELECT COUNT(*) FROM vocabulary_synonyms"
        ).fetchone()[0]
    assert synonym_count == 0
    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 404


def test_saved_sentences_are_indexed_with_connector_occurrences(
    vocabulary_database,
) -> None:
    sentence = (
        "Obwohl es regnet, gehe ich hinaus; trotzdem nehme ich einen Schirm mit. "
        "Daraufhin gehe ich nach Hause."
    )
    item = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context=sentence),
    ).json()["item"]

    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.row_factory = sqlite3.Row
        saved_sentences = connection.execute(
            "SELECT * FROM connector_sentences"
        ).fetchall()
        occurrences = connection.execute(
            """
            SELECT connector_key, surface_text, start_offset, end_offset
            FROM connector_occurrences ORDER BY start_offset
            """
        ).fetchall()
        links = connection.execute(
            "SELECT vocabulary_item_id FROM vocabulary_sentence_links"
        ).fetchall()

    assert len(saved_sentences) == 1
    assert [row["connector_key"] for row in occurrences] == ["obwohl", "trotzdem"]
    assert [sentence[row["start_offset"]:row["end_offset"]] for row in occurrences] == [
        "Obwohl",
        "trotzdem",
    ]
    assert [row["vocabulary_item_id"] for row in links] == [item["id"]]


def test_duplicate_vocabulary_saves_preserve_additional_sentence_contexts(
    vocabulary_database,
) -> None:
    first = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context="Obwohl es regnet, gehen wir."),
    ).json()
    duplicate = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context="Deshalb bleiben wir später zu Hause."),
    ).json()

    assert first["created"] is True
    assert duplicate["created"] is False
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM connector_sentences"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM vocabulary_sentence_links"
        ).fetchone()[0] == 2


def test_existing_connector_occurrences_gain_contextual_gloss_column(
    vocabulary_database,
) -> None:
    database_path = vocabulary_database / "margin.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE connector_occurrences (
                id TEXT PRIMARY KEY,
                sentence_id TEXT NOT NULL,
                connector_key TEXT NOT NULL,
                surface_text TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                categories_json TEXT NOT NULL,
                glosses_json TEXT NOT NULL,
                UNIQUE (sentence_id, connector_key, start_offset)
            )
            """
        )

    assert client.get("/api/vocabulary").status_code == 200

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(connector_occurrences)"
            )
        }
    assert "contextual_gloss" in columns


def test_saving_connector_sentence_schedules_contextual_enrichment(
    vocabulary_database,
    monkeypatch,
) -> None:
    scheduled = []
    monkeypatch.setattr(
        "pdf_language_learner.app.enrich_connector_sentence",
        scheduled.append,
    )

    response = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context="Obwohl es regnet, gehen wir spazieren."),
    )

    assert response.status_code == 200
    assert len(scheduled) == 1
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        sentence_id = connection.execute(
            "SELECT id FROM connector_sentences"
        ).fetchone()[0]
    assert scheduled == [sentence_id]


def test_contextual_connector_enrichment_batches_sentence_occurrences(
    vocabulary_database,
    monkeypatch,
) -> None:
    sentence = "Obwohl es regnet, gehen wir; trotzdem bleiben wir lange."
    client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context=sentence),
    )
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        sentence_id = connection.execute(
            "SELECT id FROM connector_sentences"
        ).fetchone()[0]
    model_calls = []

    def fake_structured_model_response(operation, **kwargs):
        model_calls.append((operation, kwargs))
        return json.dumps(
            {
                "glosses": [
                    {"position": 0, "gloss": "even though"},
                    {"position": 1, "gloss": "nevertheless"},
                ]
            }
        )

    monkeypatch.setattr(
        "pdf_language_learner.app.structured_model_response",
        fake_structured_model_response,
    )

    enrich_connector_sentence(sentence_id)
    enrich_connector_sentence(sentence_id)

    assert len(model_calls) == 1
    operation, call = model_calls[0]
    assert operation == "contextual connector glosses"
    assert sentence in call["messages"][1]["content"]
    assert "0. 'Obwohl'" in call["messages"][1]["content"]
    assert "1. 'trotzdem'" in call["messages"][1]["content"]
    cards = client.get(
        "/api/revision/session", params={"language": "German"}
    ).json()["connector_cards"]
    contextual_glosses = {
        card["connector"].casefold(): card["contextual_gloss"] for card in cards
    }
    assert contextual_glosses == {
        "obwohl": "even though",
        "trotzdem": "nevertheless",
    }


def test_connector_revision_card_uses_sentence_gloss_and_choices(
    vocabulary_database,
) -> None:
    sentence = "Obwohl es regnet, gehen wir spazieren."
    client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context=sentence),
    )

    session = client.get(
        "/api/revision/session", params={"language": "German"}
    ).json()

    assert session["connector_due_count"] == 1
    assert len(session["connector_cards"]) == 1
    card = session["connector_cards"][0]
    assert card["exercise"] == "connector_cloze"
    assert card["sentence"] == sentence
    assert sentence[card["start_offset"]:card["end_offset"]] == "Obwohl"
    assert card["connector"] == "Obwohl"
    assert card["glosses"] == ["although", "even though"]
    assert card["contextual_gloss"] is None
    assert card["category"] == "new"
    assert "subordinating conjunction" in card["connector_categories"]
    assert "obwohl" in card["choices"]
    assert len(card["choices"]) == 4


def test_spanish_connector_revision_uses_longest_phrase_and_english_glosses(
    vocabulary_database,
) -> None:
    sentence = (
        "Mientras que Ana trabaja, yo estudio; sin embargo, después descansamos."
    )
    client.post(
        "/api/vocabulary",
        json=vocabulary_payload(
            original_source="trabaja",
            normalized_source="trabajar",
            translation="to work",
            source_language="Spanish",
            context=sentence,
            noun_gender=None,
        ),
    )

    session = client.get(
        "/api/revision/session", params={"language": "Spanish"}
    ).json()

    assert session["connector_due_count"] == 2
    assert len(session["connector_cards"]) == 2
    cards = {card["connector"].casefold(): card for card in session["connector_cards"]}
    assert set(cards) == {"mientras que", "sin embargo"}
    assert cards["mientras que"]["glosses"] == ["whereas", "while"]
    assert cards["sin embargo"]["glosses"] == ["however", "nevertheless"]
    assert "mientras que" in cards["mientras que"]["choices"]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        stored = {
            row[0]
            for row in connection.execute(
                "SELECT connector_key FROM connector_occurrences"
            )
        }
    assert stored == {"mientras que", "sin embargo"}


def test_connector_answers_have_independent_review_state(
    vocabulary_database,
) -> None:
    item = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context="Obwohl es regnet, gehen wir spazieren."),
    ).json()["item"]
    card = client.get(
        "/api/revision/session", params={"language": "German"}
    ).json()["connector_cards"][0]

    response = client.post(
        f"/api/revision/connectors/{card['occurrence_id']}/answer",
        json={"selected_answer": "OBWOHL"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "correct": True,
        "correct_answer": "obwohl",
        "category": "usually_correct",
    }
    next_session = client.get(
        "/api/revision/session", params={"language": "German"}
    ).json()
    assert next_session["connector_due_count"] == 0
    assert next_session["connector_cards"] == []
    saved_item = next(
        entry for entry in client.get("/api/vocabulary").json()
        if entry["id"] == item["id"]
    )
    assert saved_item["review"]["repetitions"] == 0
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        assert connection.execute(
            "SELECT repetitions FROM connector_reviews WHERE connector_key = 'obwohl'"
        ).fetchone()[0] == 1


def test_deleting_last_sentence_link_removes_connector_examples(
    vocabulary_database,
) -> None:
    item_id = client.post(
        "/api/vocabulary",
        json=vocabulary_payload(context="Obwohl es regnet, gehen wir spazieren."),
    ).json()["item"]["id"]

    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM connector_sentences"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM connector_occurrences"
        ).fetchone()[0] == 0


def test_deleted_vocabulary_is_removed_from_revision(vocabulary_database) -> None:
    item_id = client.post(
        "/api/vocabulary", json=vocabulary_payload()
    ).json()["item"]["id"]

    assert client.get("/api/revision/session").json()["due_count"] == 1
    assert client.delete(f"/api/vocabulary/{item_id}").status_code == 204
    assert client.get("/api/revision/session").json() == {
        "cards": [],
        "due_count": 0,
        "synonym_round": None,
        "connector_cards": [],
        "connector_due_count": 0,
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


SYNONYM_REVISION_PAIRS = (
    ("schnell", "rasch"),
    ("klug", "schlau"),
    ("beginnen", "starten"),
    ("ruhig", "still"),
    ("schwierig", "schwer"),
    ("häufig", "oft"),
)


def save_synonym_revision_vocabulary(count: int) -> list[dict]:
    return [
        client.post(
            "/api/vocabulary",
            json=vocabulary_payload(
                original_source=source,
                normalized_source=source,
                translation=f"translation of {source}",
                noun_gender=None,
                synonyms=[{"text": synonym}],
            ),
        ).json()["item"]
        for source, synonym in SYNONYM_REVISION_PAIRS[:count]
    ]


def mark_vocabulary_mastered(
    vocabulary_database, items: list[dict], streak: int = 5
) -> None:
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.executemany(
            """
            UPDATE vocabulary_german
            SET repetitions = ?, consecutive_correct = ?
            WHERE id = ?
            """,
            [(streak, streak, item["id"]) for item in items],
        )


@pytest.mark.parametrize(
    ("count", "expected_pair_count"),
    [(3, None), (4, 4), (6, 5)],
)
def test_revision_session_builds_synonym_round_with_four_or_five_pairs(
    vocabulary_database,
    count: int,
    expected_pair_count: int | None,
) -> None:
    saved = save_synonym_revision_vocabulary(count)
    mark_vocabulary_mastered(vocabulary_database, saved)

    synonym_round = client.get(
        "/api/revision/session",
        params={"language": "German"},
    ).json()["synonym_round"]

    if expected_pair_count is None:
        assert synonym_round is None
        return
    assert synonym_round["exercise"] == "synonym_matching"
    assert synonym_round["source_language"] == "German"
    assert len(synonym_round["pairs"]) == expected_pair_count
    expected = {
        item["id"]: (item["normalized_source"], item["synonyms"][0]["text"])
        for item in saved
    }
    assert {
        pair["item_id"]: (pair["normalized_source"], pair["synonym"])
        for pair in synonym_round["pairs"]
    }.items() <= expected.items()


def test_synonym_round_avoids_cross_column_text_collisions(
    vocabulary_database,
) -> None:
    pairs = (
        ("alpha", "beta"),
        ("beta", "alpha"),
        ("gamma", "one"),
        ("delta", "two"),
        ("epsilon", "three"),
    )
    saved = []
    for source, synonym in pairs:
        saved.append(
            client.post(
                "/api/vocabulary",
                json=vocabulary_payload(
                    original_source=source,
                    normalized_source=source,
                    translation=source,
                    synonyms=[{"text": synonym}],
                ),
            ).json()["item"]
        )
    mark_vocabulary_mastered(vocabulary_database, saved)

    synonym_round = client.get(
        "/api/revision/session",
        params={"language": "German"},
    ).json()["synonym_round"]

    assert synonym_round is not None
    assert len(synonym_round["pairs"]) == 4
    sources = {pair["normalized_source"].casefold() for pair in synonym_round["pairs"]}
    synonyms = {pair["synonym"].casefold() for pair in synonym_round["pairs"]}
    assert sources.isdisjoint(synonyms)
    assert len(synonyms) == len(synonym_round["pairs"])


def test_synonym_round_requires_five_consecutive_correct_reviews(
    vocabulary_database,
) -> None:
    saved = save_synonym_revision_vocabulary(4)
    mark_vocabulary_mastered(vocabulary_database, saved, streak=4)

    session = client.get(
        "/api/revision/session",
        params={"language": "German"},
    ).json()
    assert session["synonym_round"] is None

    mark_vocabulary_mastered(vocabulary_database, saved, streak=5)
    session = client.get(
        "/api/revision/session",
        params={"language": "German"},
    ).json()
    assert session["synonym_round"] is not None
    assert len(session["synonym_round"]["pairs"]) == 4


def test_revision_session_uses_due_vocabulary(vocabulary_database) -> None:
    saved = save_revision_vocabulary()

    response = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    )

    assert response.status_code == 200
    session = response.json()
    assert session["due_count"] == 4
    assert {card["item_id"] for card in session["cards"]} == {
        item["id"] for item in saved
    }
    assert all(card["category"] == "new" for card in session["cards"])
    assert all(card["noun_gender"] == "neutral" for card in session["cards"])
    for card in session["cards"]:
        item = next(item for item in saved if item["id"] == card["item_id"])
        assert card["original_source"] == item["original_source"]
        assert card["normalized_source"] == item["normalized_source"]
        assert card["context"] == item["context"]
        expected_hint = (
            item["translation"]
            if card["direction"] == "source_to_translation"
            else item["normalized_source"]
        )
        assert card["hint_answer"] == expected_hint
        assert card["exercise"] == "multiple_choice"
        assert 2 <= len(card["choices"]) <= 4
        if card["direction"] == "source_to_translation":
            assert card["choice_genders"] == {}


def test_new_revision_source_direction_retains_multiple_choice(
    vocabulary_database, monkeypatch
) -> None:
    class PreferSourceDirection:
        @staticmethod
        def shuffle(values) -> None:
            return None

        @staticmethod
        def choice(values):
            return next(
                value
                for value in values
                if value.value == "source_to_translation"
            )

    save_revision_vocabulary()
    monkeypatch.setattr(
        "pdf_language_learner.app.random.SystemRandom",
        PreferSourceDirection,
    )

    cards = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()["cards"]

    assert cards
    assert all(card["direction"] == "source_to_translation" for card in cards)
    assert all(card["exercise"] == "multiple_choice" for card in cards)
    assert all(2 <= len(card["choices"]) <= 4 for card in cards)


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
    session = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()
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


def test_hinted_revision_is_recorded_as_incorrect(vocabulary_database) -> None:
    item = save_revision_vocabulary()[0]

    response = client.post(
        f"/api/revision/{item['id']}/answer",
        json={
            "direction": "translation_to_source",
            "selected_answer": item["normalized_source"],
            "hint_used": True,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["correct"] is False
    assert result["correct_answer"] == item["normalized_source"]
    assert result["category"] == "needs_practice"
    assert result["item"]["review"]["repetitions"] == 0
    assert result["item"]["review"]["lapses"] == 1


def test_new_revision_without_distractors_uses_letter_tiles(
    vocabulary_database,
) -> None:
    item = client.post("/api/vocabulary", json=vocabulary_payload()).json()["item"]

    session = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()

    assert session["due_count"] == 1
    assert len(session["cards"]) == 1
    card = session["cards"][0]
    assert card["item_id"] == item["id"]
    assert card["direction"] == "translation_to_source"
    assert card["exercise"] == "letter_tiles"
    assert card["choices"] == []
    assert card["category"] == "new"

    legacy_card = client.get("/api/revision/session").json()["cards"][0]
    assert legacy_card["exercise"] == "typed_recall"


def test_needs_practice_revision_without_distractors_uses_letter_tiles(
    vocabulary_database,
) -> None:
    item = client.post("/api/vocabulary", json=vocabulary_payload()).json()["item"]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.execute(
            """
            UPDATE vocabulary_german
            SET lapses = 1, next_review_at = '2026-08-22T12:00:00+00:00'
            WHERE id = ?
            """,
            (item["id"],),
        )

    card = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()["cards"][0]

    assert card["category"] == "needs_practice"
    assert card["direction"] == "translation_to_source"
    assert card["exercise"] == "letter_tiles"
    assert card["choices"] == []


@pytest.mark.parametrize(
    ("streak", "expected_exercise"),
    [
        (0, "multiple_choice"),
        (1, "multiple_choice"),
        (2, "letter_tiles"),
        (3, "letter_tiles"),
        (4, "typed_recall"),
        (5, "typed_recall"),
    ],
)
def test_vocabulary_exercise_advances_with_correct_answer_streak(
    vocabulary_database, streak: int, expected_exercise: str
) -> None:
    saved = save_revision_vocabulary()
    item = saved[0]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.execute(
            """
            UPDATE vocabulary_german
            SET repetitions = ?, consecutive_correct = ?,
                next_review_at = '2026-08-22T12:00:00+00:00'
            WHERE id = ?
            """,
            (streak, streak, item["id"]),
        )

    session = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()
    card = next(card for card in session["cards"] if card["item_id"] == item["id"])

    assert card["exercise"] == expected_exercise
    if expected_exercise == "multiple_choice":
        assert len(card["choices"]) >= 2
    else:
        assert card["choices"] == []
    if expected_exercise == "letter_tiles":
        assert card["direction"] == "translation_to_source"


def test_vocabulary_exercise_returns_to_multiple_choice_after_lapse(
    vocabulary_database,
) -> None:
    saved = save_revision_vocabulary()
    item = saved[0]
    with sqlite3.connect(vocabulary_database / "margin.db") as connection:
        connection.execute(
            """
            UPDATE vocabulary_german
            SET repetitions = 5, lapses = 1, consecutive_correct = 0,
                next_review_at = '2026-08-22T12:00:00+00:00'
            WHERE id = ?
            """,
            (item["id"],),
        )

    session = client.get(
        "/api/revision/session",
        params={"supports_letter_tiles": True},
    ).json()
    card = next(card for card in session["cards"] if card["item_id"] == item["id"])

    assert card["category"] == "needs_practice"
    assert card["exercise"] == "multiple_choice"
    assert len(card["choices"]) >= 2


def test_revision_of_unknown_word_returns_not_found(vocabulary_database) -> None:
    response = client.post(
        "/api/revision/missing/answer",
        json={
            "direction": "source_to_translation",
            "selected_answer": "word",
        },
    )

    assert response.status_code == 404
