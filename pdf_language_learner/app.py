import os
import random
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
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

VERB_CLITICS = {
    # German does not have Romance-style clitics, but these are the forms that
    # can realize a reflexive pronoun associated with a dictionary verb.
    "german": {"mir", "mich", "dir", "dich", "sich", "uns", "euch"},
    "spanish": {
        "me", "te", "se", "nos", "os",
        "lo", "la", "los", "las",
        "le", "les",
    },
}

DEFINITE_ARTICLES = {
    "dutch": ("de", "het"),
    "english": ("the",),
    "french": ("le", "la", "l'"),
    "german": ("der", "die", "das"),
    "italian": ("il", "lo", "la", "l'"),
    "portuguese": ("o", "a"),
    "spanish": ("el", "la"),
}

# Expressions in this lexicon are vocabulary terms even though they contain
# spaces. Keep the entries in dictionary form; matching is case-insensitive
# and tolerates PDF whitespace between their component words.
MULTI_WORD_TERMS = {
    "german": (
        "ab und zu",
        "allein schon",
        "alles in allem",
        "als Erstes",
        "als Nächstes",
        "als ob",
        "an erster Stelle",
        "an und für sich",
        "anders als",
        "anstatt zu",
        "auf Anhieb",
        "auf Dauer",
        "auf der anderen Seite",
        "auf der einen Seite",
        "auf diese Art",
        "auf diese Weise",
        "auf einmal",
        "auf jeden Fall",
        "auf keinen Fall",
        "auf lange Sicht",
        "aus diesem Grund",
        "bei Weitem",
        "bis auf Weiteres",
        "bis dahin",
        "bis jetzt",
        "bitte schön",
        "da und dort",
        "das heißt",
        "des Weiteren",
        "ein bisschen",
        "ein für alle Mal",
        "eines Tages",
        "einer nach dem anderen",
        "es sei denn",
        "früher oder später",
        "für gewöhnlich",
        "für immer",
        "für kurze Zeit",
        "ganz und gar",
        "ganz zu schweigen von",
        "genau genommen",
        "gern geschehen",
        "gute Nacht",
        "guten Abend",
        "guten Morgen",
        "guten Tag",
        "Hand in Hand",
        "herzlich willkommen",
        "hin und wieder",
        "im Allgemeinen",
        "im Detail",
        "im Endeffekt",
        "im Ernst",
        "im Gegensatz dazu",
        "im Gegensatz zu",
        "im Großen und Ganzen",
        "im Grunde",
        "im Grunde genommen",
        "im Hinblick auf",
        "im Laufe der Zeit",
        "im Laufe von",
        "im Nachhinein",
        "im Prinzip",
        "im Rahmen von",
        "im Vergleich dazu",
        "im Vergleich zu",
        "im Voraus",
        "im Wesentlichen",
        "im Zusammenhang mit",
        "in Anbetracht",
        "in Bezug auf",
        "in der Nähe von",
        "in der Regel",
        "in der Tat",
        "in der Zwischenzeit",
        "in diesem Fall",
        "in erster Linie",
        "in gewisser Weise",
        "in letzter Zeit",
        "in Wirklichkeit",
        "je nachdem",
        "kein Problem",
        "keine Ahnung",
        "kurz gesagt",
        "mehr oder weniger",
        "meiner Ansicht nach",
        "meiner Meinung nach",
        "mit anderen Worten",
        "nach und nach",
        "nach wie vor",
        "nicht einmal",
        "nicht mehr",
        "noch einmal",
        "noch lange nicht",
        "noch nie",
        "nun gut",
        "ohne Weiteres",
        "ohne Zweifel",
        "Schritt für Schritt",
        "seit Kurzem",
        "seit Langem",
        "so gut wie",
        "so oder so",
        "so schnell wie möglich",
        "so viel wie möglich",
        "Tag für Tag",
        "tut mir leid",
        "über kurz oder lang",
        "unter anderem",
        "unter keinen Umständen",
        "vielen Dank",
        "von Anfang an",
        "von mir aus",
        "von nun an",
        "von Zeit zu Zeit",
        "vor allem",
        "weder noch",
        "wenn auch",
        "wie dem auch sei",
        "wie gesagt",
        "zu Ende",
        "zu Fuß",
        "zu Hause",
        "zum Beispiel",
        "zum Glück",
        "zum größten Teil",
        "zum Schluss",
        "zum Teil",
        "zur gleichen Zeit",
    ),
    "spanish": (
        "a base de",
        "a causa de",
        "a continuación",
        "a corto plazo",
        "a diferencia de",
        "a fin de",
        "a fin de cuentas",
        "a la larga",
        "a la vez",
        "a largo plazo",
        "a lo largo de",
        "a lo mejor",
        "a menudo",
        "a partir de",
        "a pesar de",
        "a primera vista",
        "a propósito",
        "a través de",
        "a veces",
        "al contrario",
        "al fin",
        "al fin y al cabo",
        "al final",
        "al lado de",
        "al menos",
        "al mismo tiempo",
        "alrededor de",
        "ante todo",
        "antes de",
        "aparte de",
        "aquí y allá",
        "así como",
        "así que",
        "aun así",
        "bajo ningún concepto",
        "buenas noches",
        "buenas tardes",
        "buenos días",
        "cada vez",
        "cada vez más",
        "cada vez menos",
        "cerca de",
        "claro que no",
        "claro que sí",
        "como máximo",
        "como mínimo",
        "con el fin de",
        "con respecto a",
        "con tal de",
        "cuanto antes",
        "de acuerdo",
        "de antemano",
        "de hecho",
        "de inmediato",
        "de la misma manera",
        "de nuevo",
        "de ningún modo",
        "de ninguna manera",
        "de pronto",
        "de repente",
        "de todos modos",
        "de vez en cuando",
        "debajo de",
        "debido a",
        "delante de",
        "dentro de",
        "desde entonces",
        "desde luego",
        "después de",
        "detrás de",
        "día tras día",
        "en absoluto",
        "en adelante",
        "en cambio",
        "en caso de",
        "en cuanto a",
        "en efecto",
        "en el fondo",
        "en general",
        "en lugar de",
        "en medio de",
        "en otras palabras",
        "en particular",
        "en primer lugar",
        "en realidad",
        "en resumen",
        "en segundo lugar",
        "en seguida",
        "en serio",
        "en todo caso",
        "en torno a",
        "en última instancia",
        "en vano",
        "en vez de",
        "encima de",
        "frente a",
        "fuera de",
        "gracias a",
        "hasta ahora",
        "hasta cierto punto",
        "hasta luego",
        "hasta pronto",
        "hoy en día",
        "junto a",
        "lejos de",
        "lo antes posible",
        "lo siento",
        "más allá de",
        "más o menos",
        "mientras tanto",
        "ni más ni menos",
        "ni siquiera",
        "no obstante",
        "paso a paso",
        "poco a poco",
        "por casualidad",
        "por cierto",
        "por consiguiente",
        "por el contrario",
        "por ejemplo",
        "por eso",
        "por favor",
        "por fin",
        "por el día",
        "por la mañana",
        "por la madrugada",
        "por la noche",
        "por la tarde",
        "por las mañanas",
        "por las noches",
        "por las tardes",
        "por lo general",
        "por lo menos",
        "por lo tanto",
        "por otro lado",
        "por otra parte",
        "por primera vez",
        "por si acaso",
        "por supuesto",
        "por último",
        "por una parte",
        "qué tal",
        "sin duda",
        "sin embargo",
        "sin más",
        "sin problema",
        "sobre todo",
        "tal vez",
        "tan pronto como",
        "tarde o temprano",
        "una vez más",
        "una y otra vez",
        "ya que",
    ),
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
        description=(
            "Whether the selection resolves to a dictionary-style vocabulary "
            "term, including a recognized multi-word expression"
        )
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


class VerbLemmaDecision(BaseModel):
    dictionary_lemma: str = Field(
        min_length=1,
        max_length=200,
        description="The contextual source-language dictionary form of the verb",
    )


class NounTranslation(BaseModel):
    target_lemma: str = Field(
        min_length=1,
        description="The singular target-language noun without an article",
    )
    target_definite_article: str = Field(
        description="The target noun's definite article, without the noun",
    )


class SourceArticle(BaseModel):
    article: str = Field(
        description="The definite article for the supplied normalized source lemma",
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
    associated_clitics: tuple[str, ...] = ()
    confident_verb_lemma: str | None = None


@lru_cache(maxsize=len(STANZA_LANGUAGES))
def stanza_pipeline(source_language: str):
    normalized_language = source_language.casefold()
    language = STANZA_LANGUAGES.get(normalized_language)
    if language is None:
        raise ValueError(f"POS tagging is not supported for {source_language}")
    processors = "tokenize,pos,lemma"
    if normalized_language in VERB_CLITICS:
        processors += ",depparse"
    return stanza.Pipeline(
        lang=language,
        processors=processors,
        download_method=stanza.DownloadMethod.REUSE_RESOURCES,
        use_gpu=False,
        verbose=False,
    )


def normalize_source(text: str, source_language: str) -> str:
    language = LEMMATIZER_LANGUAGES.get(source_language.casefold())
    if language is None or len(text.split()) != 1:
        return text
    return simplemma.lemmatize(text, lang=language) or text


def multi_word_term_in_context(
    text: str,
    source_language: str,
    context: str,
    context_offset: int | None,
) -> str | None:
    """Return the longest known expression containing the selected text."""

    terms = MULTI_WORD_TERMS.get(source_language.casefold(), ())
    if not terms:
        return None

    selected_key = canonicalize(text)
    ordered_terms = sorted(terms, key=lambda term: len(term.split()), reverse=True)
    for term in ordered_terms:
        if selected_key == canonicalize(term):
            return term
    if not context:
        return None

    selected_spans: list[tuple[int, int]] = []
    if context_offset is not None and context_offset <= len(context):
        selected_spans.append((context_offset, context_offset + len(text)))
    else:
        selected_pattern = re.compile(re.escape(text), re.IGNORECASE)
        selected_spans.extend(
            match.span() for match in selected_pattern.finditer(context)
        )

    for term in ordered_terms:
        expression = r"(?<!\w)" + r"\s+".join(
            re.escape(word) for word in term.split()
        ) + r"(?!\w)"
        for match in re.finditer(expression, context, re.IGNORECASE):
            if any(
                match.start() <= selected_start
                and selected_end <= match.end()
                for selected_start, selected_end in selected_spans
            ):
                return term
    return None


def morphological_features(word) -> dict[str, str]:
    return {
        key: value
        for feature in (getattr(word, "feats", None) or "").split("|")
        if "=" in feature
        for key, value in [feature.split("=", 1)]
    }


def is_confident_spanish_reflexive(clitic, verb) -> bool:
    if (getattr(clitic, "deprel", None) or "") != "expl:pv":
        return False
    clitic_features = morphological_features(clitic)
    verb_features = morphological_features(verb)
    verb_person = verb_features.get("Person")
    if verb_person is None or clitic_features.get("Person") != verb_person:
        return False
    clitic_number = clitic_features.get("Number")
    verb_number = verb_features.get("Number")
    return clitic_number is None or clitic_number == verb_number


def verb_associated_clitics(
    selected,
    sentence_words: list,
    source_language: str,
    selected_token_words: list | None = None,
) -> list:
    """Collect syntax-linked clitic candidates without interpreting their role."""

    clitic_forms = VERB_CLITICS.get(source_language.casefold(), set())
    if not clitic_forms:
        return []
    selected_token_words = selected_token_words or [selected]
    selected_id = getattr(selected, "id", None)
    possible_heads = {selected_id}

    # Spanish permits clitic climbing ("me quiero acostar"). When the selected
    # verb is an open complement, expose clitics attached to its governing verb
    # as candidates; the semantic decision stage will decide where they belong.
    if (
        source_language.casefold() == "spanish"
        and (getattr(selected, "deprel", None) or "") == "xcomp"
    ):
        possible_heads.add(getattr(selected, "head", None))

    clitics = [
        word
        for word in sentence_words
        if getattr(word, "upos", None) == "PRON"
        and canonicalize(word.text) in clitic_forms
        and (
            getattr(word, "head", None) in possible_heads
            or word in selected_token_words
        )
    ]
    clitics.sort(key=lambda word: getattr(word, "start_char", 0) or 0)
    return clitics


def verb_analysis_with_dependents(
    selected,
    sentence_words: list,
    source_language: str,
    selected_token_words: list | None = None,
    base_lemma: str | None = None,
) -> WordAnalysis:
    """Normalize a particle and record clitics linked to the selected verb."""

    lemma = base_lemma or selected.lemma or selected.text
    selected_id = getattr(selected, "id", None)
    if selected_id is None or (selected.upos or "X") not in VERB_POS:
        return WordAnalysis(selected.text, lemma, selected.upos or "X")

    dependents = [
        word
        for word in sentence_words
        if getattr(word, "head", None) == selected_id
    ]
    associated = []
    language = source_language.casefold()

    if language == "german":
        particles = [
            word
            for word in dependents
            if (getattr(word, "deprel", None) or "") == "compound:prt"
        ]
        particles.sort(key=lambda word: getattr(word, "start_char", 0) or 0)
        for particle in particles:
            prefix = (particle.lemma or particle.text).casefold()
            if prefix and not lemma.casefold().startswith(prefix):
                lemma = f"{prefix}{lemma}"
        associated.extend(particles)

    clitics = verb_associated_clitics(
        selected,
        sentence_words,
        source_language,
        selected_token_words,
    )
    associated.extend(clitics)
    confident_verb_lemma = None
    if language == "german" and any(
        canonicalize(clitic.text) == "sich" for clitic in clitics
    ):
        confident_verb_lemma = f"sich {lemma}"
    elif (
        language == "spanish"
        and len(clitics) == 1
        and is_confident_spanish_reflexive(clitics[0], selected)
    ):
        confident_verb_lemma = (
            lemma if lemma.casefold().endswith("se") else f"{lemma}se"
        )

    token_words = [selected, *associated]
    token_words.sort(key=lambda word: getattr(word, "start_char", 0) or 0)
    token = " ".join(word.text for word in token_words)
    return WordAnalysis(
        token=token,
        lemma=lemma,
        pos=selected.upos or "X",
        associated_clitics=tuple(word.text for word in clitics),
        confident_verb_lemma=confident_verb_lemma,
    )


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
    located_words = []
    for sentence in document.sentences:
        tokens = getattr(sentence, "tokens", None)
        if tokens:
            for token in tokens:
                token_words = token.words
                for word in token_words:
                    located_words.append(
                        (
                            word,
                            sentence.words,
                            token_words,
                            word.start_char
                            if word.start_char is not None
                            else token.start_char,
                            word.end_char
                            if word.end_char is not None
                            else token.end_char,
                        )
                    )
        else:
            located_words.extend(
                (
                    word,
                    sentence.words,
                    [word],
                    word.start_char,
                    word.end_char,
                )
                for word in sentence.words
            )
    overlapping = [
        (word, sentence_words, token_words)
        for word, sentence_words, token_words, word_start, word_end in located_words
        if word_start is not None
        and word_end is not None
        and word_start < selected_end
        and word_end > selected_start
        and word.upos not in {"PUNCT", "SYM"}
    ]
    selected_location = overlapping[0] if overlapping else None
    if selected_location is None:
        selected_key = canonicalize(text.strip(".,;:!?¡¿()[]{}\"“”'‘’"))
        selected_location = next(
            (
                (word, sentence_words, token_words)
                for word, sentence_words, token_words, _, _ in located_words
                if canonicalize(word.text) == selected_key
            ),
            None,
        )
    if selected_location is None:
        raise ValueError("the selected word could not be located in its context")

    selected, sentence_words, selected_token_words = selected_location

    # PDF typography often uppercases a run of text for emphasis. Stanza can
    # consequently interpret an inflected verb such as German "ERINNERTE" as a
    # proper noun and preserve it as the lemma. Retry ambiguous all-caps tokens
    # with casing removed from the full context so syntax-linked dependents are
    # recovered as well. Only use the retry when lowercasing preserves offsets.
    if (
        (selected.upos or "X") in {"PROPN", "X"}
        and text.isupper()
        and text != text.lower()
    ):
        lowercase_context = context_text.lower()
        lowercase_text = text.lower()
        if (
            len(lowercase_context) == len(context_text)
            and len(lowercase_text) == len(text)
        ):
            lowercase_analysis = analyze_word_in_context(
                lowercase_text,
                source_language,
                lowercase_context,
                selected_start,
            )
            if lowercase_analysis.pos not in {"PROPN", "X"}:
                return lowercase_analysis

    stanza_lemma = selected.lemma or selected.text
    simplemma_lemma = normalize_source(selected.text, source_language)
    lemma = simplemma_lemma if selected.upos in NOUN_POS else stanza_lemma
    if selected.upos in VERB_POS:
        if (
            source_language.casefold() == "spanish"
            and simplemma_lemma.casefold().endswith(("ar", "er", "ir"))
        ):
            lemma = simplemma_lemma
        return verb_analysis_with_dependents(
            selected,
            sentence_words,
            source_language,
            selected_token_words,
            lemma,
        )
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
    target_language: str,
) -> dict:
    schema = NounTranslation.model_json_schema()
    schema["properties"]["target_definite_article"]["enum"] = list(
        definite_articles(target_language)
    )
    return schema


def source_article_schema(source_language: str) -> dict:
    schema = SourceArticle.model_json_schema()
    schema["properties"]["article"]["enum"] = list(
        definite_articles(source_language)
    )
    return schema


def source_article_messages(
    lemma: str, source_language: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Choose the definite article that grammatically agrees with the "
                "exact normalized dictionary lemma supplied. Base the choice only "
                "on that lemma and its language. Do not infer gender from an "
                "original inflected form, a person, or sentence context. Return "
                "only the article field."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source_language}\n"
                f"Normalized dictionary lemma: {lemma}"
            ),
        },
    ]


def verb_lemma_messages(
    analysis: WordAnalysis, source_language: str, context: str
) -> list[dict[str, str]]:
    candidates = ", ".join(analysis.associated_clitics)
    return [
        {
            "role": "system",
            "content": (
                "You are a grammatical dictionary-form classifier. A dependency "
                "parser has already detected pronoun/clitic candidates associated "
                "with one selected verb. Decide which candidates, if any, are part "
                "of the contextual dictionary verb. Include reflexive, reciprocal, "
                "inherently pronominal, and fixed lexicalized clitics when omitting "
                "them would lose the verb construction's dictionary meaning. "
                "Exclude ordinary direct or indirect objects and optional "
                "benefactive or ethical datives. For Spanish, convert person-specific "
                "reflexive forms to the conventional infinitive ending in -se; retain "
                "other clitics only in genuinely fixed dictionary constructions. For "
                "German, use 'sich' with the infinitive for a dictionary-form "
                "reflexive. A German separable prefix is already included in the base "
                "lemma. Return only the source-language dictionary lemma; do not "
                "translate anything. Examples: 'me pongo el pijama' -> ponerse; "
                "'me acuesto' -> acostarse; 'me preparo' -> prepararse; 'me "
                "encanta' -> encantar; 'me gusta' -> gustar; 'lo veo' -> ver; "
                "'me compré un libro' -> comprar."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source_language}\n"
                f"Selected verb and candidates: {analysis.token}\n"
                f"Base verb lemma: {analysis.lemma}\n"
                f"Detected clitic candidates: {candidates}\n"
                f"Full sentence context: {context or '(not available)'}\n"
                "Return the contextual dictionary lemma."
            ),
        },
    ]


def apply_verb_lemma_decision(
    analysis: WordAnalysis, decision: VerbLemmaDecision
) -> WordAnalysis:
    dictionary_lemma = decision.dictionary_lemma.strip()
    return replace(analysis, lemma=dictionary_lemma)


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
        "This is a noun. Translate the supplied singular source lemma to a "
        "singular target noun in target_lemma, with no article attached, and "
        "return its target definite article separately in "
        "target_definite_article. Use an empty article only for a language that "
        "has no definite articles. Do not return or choose the source article."
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
                "For a function word, return only its contextual equivalent; "
                "never append translations of neighboring words. "
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


def vocabulary_table_slug(language: str) -> str:
    ascii_language = unicodedata.normalize("NFKD", canonicalize(language)).encode(
        "ascii", "ignore"
    ).decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_language).strip("_")
    return slug or f"language_{uuid.uuid5(uuid.NAMESPACE_URL, canonicalize(language)).hex[:8]}"


def create_vocabulary_table(connection: sqlite3.Connection, table_name: str) -> None:
    if not re.fullmatch(r"vocabulary_[a-z0-9_]+", table_name):
        raise ValueError("Invalid vocabulary table name")
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
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
    connection.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_normalized_source
            ON {table_name} (canonical_source)
        """
    )


def language_table(
    connection: sqlite3.Connection, language: str, *, create: bool = False
) -> str | None:
    canonical_language = canonicalize(language)
    row = connection.execute(
        """
        SELECT table_name FROM vocabulary_languages
        WHERE canonical_language = ?
        """,
        (canonical_language,),
    ).fetchone()
    if row is not None:
        return row["table_name"]
    if not create:
        return None

    base_name = f"vocabulary_{vocabulary_table_slug(language)}"
    table_name = base_name
    collision = connection.execute(
        "SELECT 1 FROM vocabulary_languages WHERE table_name = ?", (table_name,)
    ).fetchone()
    if collision is not None:
        suffix = uuid.uuid5(uuid.NAMESPACE_URL, canonical_language).hex[:8]
        table_name = f"{base_name}_{suffix}"
    create_vocabulary_table(connection, table_name)
    connection.execute(
        """
        INSERT INTO vocabulary_languages (
            canonical_language, display_name, table_name
        ) VALUES (?, ?, ?)
        """,
        (canonical_language, language.strip(), table_name),
    )
    return table_name


def registered_language_tables(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT display_name, table_name
        FROM vocabulary_languages
        ORDER BY display_name COLLATE NOCASE
        """
    ).fetchall()


def migrate_legacy_vocabulary(connection: sqlite3.Connection) -> None:
    legacy_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vocabulary'"
    ).fetchone()
    if legacy_exists is None:
        return

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
    rows = connection.execute("SELECT * FROM vocabulary").fetchall()
    column_names = (
        "id, schema_version, original_source, normalized_source, canonical_source, "
        "translation, source_language, canonical_source_language, target_language, "
        "context, document_key, saved_at, last_reviewed_at, next_review_at, "
        "repetitions, lapses, consecutive_correct"
    )
    placeholders = ", ".join("?" for _ in range(17))
    for row in rows:
        table_name = language_table(connection, row["source_language"], create=True)
        connection.execute(
            f"INSERT OR IGNORE INTO {table_name} ({column_names}) VALUES ({placeholders})",
            tuple(row[name.strip()] for name in column_names.split(",")),
        )
    connection.execute("DROP TABLE vocabulary")


@contextmanager
def vocabulary_database() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vocabulary_languages (
                canonical_language TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                table_name TEXT NOT NULL UNIQUE
            )
            """
        )
        migrate_legacy_vocabulary(connection)
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


@app.get("/api/vocabulary/languages", response_model=list[str])
def list_vocabulary_languages() -> list[str]:
    with vocabulary_database() as connection:
        languages = [row["display_name"] for row in registered_language_tables(connection)]
    return languages


@app.get("/api/vocabulary", response_model=list[VocabularyItem])
def list_vocabulary(language: str | None = None) -> list[VocabularyItem]:
    with vocabulary_database() as connection:
        if language is not None:
            table_name = language_table(connection, language)
            rows = (
                connection.execute(
                    f"SELECT * FROM {table_name} ORDER BY saved_at DESC"
                ).fetchall()
                if table_name is not None
                else []
            )
        else:
            rows = [
                row
                for registered in registered_language_tables(connection)
                for row in connection.execute(
                    f"SELECT * FROM {registered['table_name']}"
                ).fetchall()
            ]
            rows.sort(key=lambda row: row["saved_at"], reverse=True)
    return [vocabulary_item(row) for row in rows]


@app.post("/api/vocabulary", response_model=VocabularySaveResult)
def save_vocabulary(request: VocabularyCreate) -> VocabularySaveResult:
    item_id = str(uuid.uuid4())
    saved_at = datetime.now(UTC).isoformat()
    canonical_source = canonicalize(request.normalized_source)
    canonical_language = canonicalize(request.source_language)
    with vocabulary_database() as connection:
        table_name = language_table(connection, request.source_language, create=True)
        cursor = connection.execute(
            f"""
            INSERT OR IGNORE INTO {table_name} (
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
            f"""
            SELECT *
            FROM {table_name}
            WHERE canonical_source = ?
            """,
            (canonical_source,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Vocabulary could not be saved")
    return VocabularySaveResult(item=vocabulary_item(row), created=created)


@app.delete("/api/vocabulary/{item_id}", status_code=204)
def delete_vocabulary(item_id: str) -> Response:
    with vocabulary_database() as connection:
        deleted = False
        for registered in registered_language_tables(connection):
            cursor = connection.execute(
                f"DELETE FROM {registered['table_name']} WHERE id = ?", (item_id,)
            )
            if cursor.rowcount:
                deleted = True
                break
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved vocabulary item not found")
    return Response(status_code=204)


@app.get("/api/revision/session", response_model=RevisionSession)
def revision_session(language: str | None = None, limit: int = 40) -> RevisionSession:
    limit = max(1, min(limit, 100))
    now = datetime.now(UTC)
    with vocabulary_database() as connection:
        if language is not None:
            table_name = language_table(connection, language)
            rows = (
                connection.execute(f"SELECT * FROM {table_name}").fetchall()
                if table_name is not None
                else []
            )
        else:
            rows = [
                row
                for registered in registered_language_tables(connection)
                for row in connection.execute(
                    f"SELECT * FROM {registered['table_name']}"
                ).fetchall()
            ]

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
        row = None
        table_name = None
        for registered in registered_language_tables(connection):
            candidate_table = registered["table_name"]
            row = connection.execute(
                f"SELECT * FROM {candidate_table} WHERE id = ?", (item_id,)
            ).fetchone()
            if row is not None:
                table_name = candidate_table
                break
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
            f"""
            UPDATE {table_name}
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
            f"SELECT * FROM {table_name} WHERE id = ?", (item_id,)
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
        multi_word_term = multi_word_term_in_context(
            request.text,
            request.source_language,
            request.context,
            request.context_offset,
        )
        is_single_word = multi_word_term is None and len(request.text.split()) == 1
        is_term = is_single_word or multi_word_term is not None
        source_text = multi_word_term or request.text
        word_analysis = (
            analyze_word_in_context(
                request.text,
                request.source_language,
                request.context,
                request.context_offset,
            )
            if is_single_word
            else None
        )
        if (
            word_analysis is not None
            and word_analysis.pos in VERB_POS
            and word_analysis.associated_clitics
        ):
            if word_analysis.confident_verb_lemma is not None:
                word_analysis = replace(
                    word_analysis, lemma=word_analysis.confident_verb_lemma
                )
            else:
                lemma_response = client.chat(
                    model=translation_model,
                    messages=verb_lemma_messages(
                        word_analysis,
                        request.source_language,
                        request.context,
                    ),
                    format=VerbLemmaDecision.model_json_schema(),
                    keep_alive="30m",
                    options={
                        "temperature": 0,
                        "num_ctx": 1024,
                        "num_predict": 96,
                    },
                )
                word_analysis = apply_verb_lemma_decision(
                    word_analysis,
                    VerbLemmaDecision.model_validate_json(
                        lemma_response.message.content
                    ),
                )
        source_article = ""
        if word_analysis is not None and word_analysis.pos in NOUN_POS:
            allowed_articles = definite_articles(request.source_language)
            if allowed_articles != ("",):
                article_response = client.chat(
                    model=translation_model,
                    messages=source_article_messages(
                        word_analysis.lemma, request.source_language
                    ),
                    format=source_article_schema(request.source_language),
                    keep_alive="30m",
                    options={
                        "temperature": 0,
                        "num_ctx": 256,
                        "num_predict": 16,
                    },
                )
                source_article = normalized_article(
                    SourceArticle.model_validate_json(
                        article_response.message.content
                    ).article,
                    request.source_language,
                )

        def request_translation(
            context: str,
        ) -> TranslatedText | NounTranslation:
            is_noun = word_analysis is not None and word_analysis.pos in NOUN_POS
            response_model = NounTranslation if is_noun else TranslatedText
            response_schema = (
                noun_translation_schema(request.target_language)
                if is_noun
                else response_model.model_json_schema()
            )
            response = client.chat(
                model=translation_model,
                messages=translation_messages(
                    source=source_text,
                    source_language=request.source_language,
                    target_language=request.target_language,
                    context=context,
                    is_word=is_single_word,
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
        if (
            is_single_word
            and request.context
            and is_sentence_like_word_translation(translated_text)
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
        if is_single_word and is_sentence_like_word_translation(translated_text):
            raise ValueError(
                "the model returned a sentence instead of a word translation"
            )

        normalized_source = source_text
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
            is_word=is_term,
            normalized_source=normalized_source,
            translation=translation,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local translation model failed: {exc}",
        ) from exc
