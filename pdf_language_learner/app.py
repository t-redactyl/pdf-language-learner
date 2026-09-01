import io
import json
import logging
import os
import random
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import urlsplit

from anthropic import Anthropic
import httpx
import simplemma
import stanza
import wn
from wordfreq import zipf_frequency
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator
from dotenv import load_dotenv

from pdf_language_learner.revision import (
    RevisionCategory,
    RevisionDirection,
    RevisionExercise,
    ScheduleState,
    is_due,
    parse_timestamp,
    revision_category,
    schedule_review,
)
from pdf_language_learner.grammar_progress import (
    INITIAL_GRAMMAR_PROGRESS_MIGRATION,
    grammar_topic_status,
    initially_seen_topics,
)
from pdf_language_learner.german_grammar_catalogue import GRAMMAR_TOPICS
from pdf_language_learner.grammar_revision import (
    GrammarExerciseType,
    GrammarGeneratedSession,
    GrammarGenerationResponse,
    GrammarGrade,
    GrammarSessionKind,
    GrammarTopicSummary,
    deterministic_grammar_grade,
    grammar_generation_messages,
    grammar_grading_messages,
    grammar_topic_summary_messages,
    schedule_grammar_review,
)
from pdf_language_learner.grammar_topics import GrammarTopic
from pdf_language_learner.spanish_grammar_catalogue import SPANISH_GRAMMAR_TOPICS
from pdf_language_learner.suggestions import canonical_url, suggestions_for
from pdf_language_learner.web_import import WebImportError, fetch_web_document

# Attach application diagnostics to Uvicorn's configured server logger so INFO
# timings are visible both through the development entry point and `uvicorn` CLI.
logger = logging.getLogger("uvicorn.error").getChild("margin")

ROOT = Path(__file__).resolve().parent.parent


def load_local_environment(path: Path = ROOT / ".env") -> None:
    """Load local configuration without replacing exported environment values."""

    load_dotenv(path, override=False)


load_local_environment()

STATIC = ROOT / "static"
DATABASE_PATH = Path(
    os.getenv("MARGIN_DATABASE_PATH", ROOT / "data" / "margin.db")
)
OPEN_THESAURUS_PATH = Path(
    os.getenv(
        "MARGIN_OPEN_THESAURUS_PATH",
        ROOT / "data" / "openthesaurus.txt",
    )
)
OPEN_THESAURUS_EXPORT_URL = os.getenv(
    "MARGIN_OPEN_THESAURUS_URL",
    "https://www.openthesaurus.de/export/OpenThesaurus-Textversion.zip",
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

LANGUAGE_NAMES_BY_CODE = {
    language_code: display_name.title()
    for display_name, language_code in LEMMATIZER_LANGUAGES.items()
}
JAPANESE_SCRIPT = re.compile(r"[\u3040-\u30ff]")
KOREAN_SCRIPT = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
CHINESE_SCRIPT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

STANZA_LANGUAGES = {
    **LEMMATIZER_LANGUAGES,
    "chinese (simplified)": "zh-hans",
    "japanese": "ja",
    "korean": "ko",
}

NOUN_POS = {"NOUN"}
VERB_POS = {"VERB", "AUX"}
STANZA_PIPELINE_LOCK = threading.Lock()
STANZA_PIPELINE_INIT_LOCKS = {
    language: threading.Lock() for language in STANZA_LANGUAGES
}
STANZA_PIPELINES: dict[str, Any] = {}
STANZA_PREPARATION_LOCK = threading.Lock()
STANZA_PREPARING: set[str] = set()
LOCAL_NOUN_GRAMMAR_CACHE: dict[tuple[str, str], "SourceNounGrammar | None"] = {}
LOCAL_NOUN_GRAMMAR_CACHE_LOCK = threading.Lock()
RUNTIME_CACHE_SIZE = 512
MAX_SYNONYMS = 2
MAX_SYNONYM_CANDIDATES = 32
MIN_SYNONYM_ZIPF = 2.5
MAX_SYNONYM_ZIPF_DROP = 2.0
CONNECTOR_REVISION_LIMIT = 8
CONNECTOR_BACKFILL_VERSION = "connector-sentences-v2"
GERMAN_CONNECTORS = {
    "obwohl": {
        "categories": ("subordinating conjunction",),
        "glosses": ("although", "even though"),
    },
    "obgleich": {
        "categories": ("subordinating conjunction",),
        "glosses": ("although", "even though"),
    },
    "obschon": {
        "categories": ("subordinating conjunction",),
        "glosses": ("although", "even though"),
    },
    "während": {
        "categories": ("subordinating conjunction",),
        "glosses": ("while", "whereas", "during"),
    },
    "sofern": {
        "categories": ("subordinating conjunction",),
        "glosses": ("provided that", "as long as"),
    },
    "falls": {
        "categories": ("subordinating conjunction",),
        "glosses": ("if", "in case"),
    },
    "sodass": {
        "categories": ("subordinating conjunction",),
        "glosses": ("so that", "with the result that"),
    },
    "so dass": {
        "categories": ("subordinating conjunction",),
        "glosses": ("so that", "with the result that"),
    },
    "solange": {
        "categories": ("subordinating conjunction",),
        "glosses": ("as long as", "while"),
    },
    "sobald": {
        "categories": ("subordinating conjunction",),
        "glosses": ("as soon as",),
    },
    "nachdem": {
        "categories": ("subordinating conjunction",),
        "glosses": ("after",),
    },
    "bevor": {
        "categories": ("subordinating conjunction",),
        "glosses": ("before",),
    },
    "weil": {
        "categories": ("subordinating conjunction",),
        "glosses": ("because",),
    },
    "wohingegen": {
        "categories": ("subordinating conjunction",),
        "glosses": ("whereas", "in contrast"),
    },
    "trotzdem": {
        "categories": ("conjunctive adverb",),
        "glosses": ("nevertheless", "despite that"),
    },
    "dennoch": {
        "categories": ("conjunctive adverb",),
        "glosses": ("nevertheless", "nonetheless"),
    },
    "deshalb": {
        "categories": ("conjunctive adverb",),
        "glosses": ("therefore", "for that reason"),
    },
    "deswegen": {
        "categories": ("conjunctive adverb",),
        "glosses": ("therefore", "because of that"),
    },
    "daher": {
        "categories": ("conjunctive adverb",),
        "glosses": ("therefore", "hence"),
    },
    "allerdings": {
        "categories": ("conjunctive adverb",),
        "glosses": ("however", "admittedly"),
    },
    "folglich": {
        "categories": ("conjunctive adverb",),
        "glosses": ("consequently",),
    },
    "somit": {
        "categories": ("conjunctive adverb",),
        "glosses": ("thus", "therefore"),
    },
    "hingegen": {
        "categories": ("conjunctive adverb",),
        "glosses": ("on the other hand", "by contrast"),
    },
    "außerdem": {
        "categories": ("conjunctive adverb",),
        "glosses": ("besides", "in addition"),
    },
    "damit": {
        "categories": ("subordinating conjunction", "da-compound"),
        "glosses": ("so that", "with it"),
    },
    "darum": {
        "categories": ("conjunctive adverb", "da-compound"),
        "glosses": ("therefore", "about it"),
    },
    "dabei": {
        "categories": ("da-compound",),
        "glosses": ("in doing so", "with it", "at the same time"),
    },
    "dafür": {
        "categories": ("da-compound",),
        "glosses": ("for it", "in favour of it", "in return"),
    },
    "dagegen": {
        "categories": ("da-compound",),
        "glosses": ("against it", "on the other hand"),
    },
    "danach": {
        "categories": ("da-compound",),
        "glosses": ("after it", "afterwards"),
    },
    "daran": {
        "categories": ("da-compound",),
        "glosses": ("on it", "about it"),
    },
    "darauf": {
        "categories": ("da-compound",),
        "glosses": ("on it", "after that"),
    },
    "daraus": {
        "categories": ("da-compound",),
        "glosses": ("from it", "out of it"),
    },
    "darin": {
        "categories": ("da-compound",),
        "glosses": ("in it", "therein"),
    },
    "darüber": {
        "categories": ("da-compound",),
        "glosses": ("about it", "above it"),
    },
    "darunter": {
        "categories": ("da-compound",),
        "glosses": ("under it", "among them"),
    },
    "davon": {
        "categories": ("da-compound",),
        "glosses": ("of it", "from it"),
    },
    "davor": {
        "categories": ("da-compound",),
        "glosses": ("before it", "in front of it"),
    },
    "dazu": {
        "categories": ("da-compound",),
        "glosses": ("to it", "in addition"),
    },
    "dazwischen": {
        "categories": ("da-compound",),
        "glosses": ("between them", "in between"),
    },
}
SPANISH_CONNECTORS = {
    "aunque": {
        "categories": ("subordinating conjunction",),
        "glosses": ("although", "even though"),
    },
    "para que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("so that", "in order that"),
    },
    "mientras": {
        "categories": ("subordinating conjunction",),
        "glosses": ("while", "whereas"),
    },
    "mientras que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("whereas", "while"),
    },
    "siempre que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("provided that", "as long as"),
    },
    "a condición de que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("provided that", "on condition that"),
    },
    "a menos que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("unless",),
    },
    "en caso de que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("in case",),
    },
    "ya que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("since", "because"),
    },
    "puesto que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("since", "given that"),
    },
    "dado que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("given that", "since"),
    },
    "porque": {
        "categories": ("subordinating conjunction",),
        "glosses": ("because",),
    },
    "si": {
        "categories": ("subordinating conjunction",),
        "glosses": ("if",),
    },
    "antes de que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("before",),
    },
    "después de que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("after",),
    },
    "hasta que": {
        "categories": ("subordinating conjunction",),
        "glosses": ("until",),
    },
    "tan pronto como": {
        "categories": ("subordinating conjunction",),
        "glosses": ("as soon as",),
    },
    "en cuanto": {
        "categories": ("subordinating conjunction",),
        "glosses": ("as soon as", "regarding"),
    },
    "sin embargo": {
        "categories": ("conjunctive adverb",),
        "glosses": ("however", "nevertheless"),
    },
    "no obstante": {
        "categories": ("conjunctive adverb",),
        "glosses": ("nevertheless", "however"),
    },
    "aun así": {
        "categories": ("conjunctive adverb",),
        "glosses": ("even so", "nevertheless"),
    },
    "con todo": {
        "categories": ("conjunctive adverb",),
        "glosses": ("nevertheless", "all the same"),
    },
    "por eso": {
        "categories": ("conjunctive adverb",),
        "glosses": ("therefore", "that is why"),
    },
    "por lo tanto": {
        "categories": ("conjunctive adverb",),
        "glosses": ("therefore", "consequently"),
    },
    "por consiguiente": {
        "categories": ("conjunctive adverb",),
        "glosses": ("consequently", "therefore"),
    },
    "en consecuencia": {
        "categories": ("conjunctive adverb",),
        "glosses": ("consequently", "as a result"),
    },
    "así que": {
        "categories": ("conjunctive adverb",),
        "glosses": ("so", "therefore"),
    },
    "de ahí que": {
        "categories": ("conjunctive adverb",),
        "glosses": ("hence", "which is why"),
    },
    "además": {
        "categories": ("conjunctive adverb",),
        "glosses": ("furthermore", "besides"),
    },
    "asimismo": {
        "categories": ("conjunctive adverb",),
        "glosses": ("likewise", "furthermore"),
    },
    "en cambio": {
        "categories": ("conjunctive adverb",),
        "glosses": ("on the other hand", "instead"),
    },
    "por el contrario": {
        "categories": ("conjunctive adverb",),
        "glosses": ("on the contrary", "by contrast"),
    },
    "por un lado": {
        "categories": ("conjunctive adverb",),
        "glosses": ("on the one hand",),
    },
    "por otro lado": {
        "categories": ("conjunctive adverb",),
        "glosses": ("on the other hand",),
    },
    "es decir": {
        "categories": ("conjunctive adverb",),
        "glosses": ("that is", "in other words"),
    },
    "o sea": {
        "categories": ("conjunctive adverb",),
        "glosses": ("that is", "in other words"),
    },
    "de hecho": {
        "categories": ("conjunctive adverb",),
        "glosses": ("in fact",),
    },
    "por último": {
        "categories": ("conjunctive adverb",),
        "glosses": ("finally", "lastly"),
    },
}
WORD_FREQUENCY_LANGUAGES = {
    "german": "de",
    "spanish": "es",
}
SYNONYM_POS_COMPATIBILITY = {
    "NOUN": {"NOUN", "PROPN"},
    "VERB": {"VERB", "AUX"},
    "AUX": {"VERB", "AUX"},
    "ADJ": {"ADJ"},
    "ADV": {"ADV"},
}
OPEN_THESAURUS_METADATA_MARKERS = (
    "abwert",
    "adjektiv",
    "adverb",
    "altertüm",
    "bildungsspr",
    "derb",
    "fachspr",
    "geh.",
    "hauptform",
    "iron",
    "kindersprache",
    "literar",
    "norddt",
    "österr",
    "regional",
    "religiös",
    "salopp",
    "scherz",
    "schweiz",
    "selten",
    "subst",
    "süddt",
    "technisch",
    "ugs.",
    "umgangssprach",
    "variabel",
    "veraltet",
    "verb",
    "vulg",
)
OPEN_THESAURUS_NON_LEXICAL_MARKERS = ("spruch", "slogan", "beispielsatz")
MODEL_CALL_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="openai-call",
)
WORDNET_LEXICONS = {
    "german": "odenet:1.4",
    "spanish": "omw-es:2.0",
}
# Wn pools one SQLite connection per database. FastAPI's synchronous endpoints
# can run on different worker threads, and the background lexicon warm-up opens
# the same database before a request uses it, so the pooled connection must be
# created in Wn's supported multithreaded mode. Access is still serialized by
# WORDNET_LOCK below.
wn.config.allow_multithreading = True
WORDNETS: dict[str, wn.Wordnet] = {}
WORDNET_LOCK = threading.RLock()
WORDNET_PREPARING: set[str] = set()
OPEN_THESAURUS_LOCK = threading.Lock()
OPEN_THESAURUS_INDEX: dict[str, tuple[tuple[str, ...], ...]] | None = None


@lru_cache(maxsize=1)
def language_detector() -> simplemma.LanguageDetector:
    started = time.perf_counter()
    detector = simplemma.LanguageDetector(tuple(LANGUAGE_NAMES_BY_CODE))
    logger.info(
        "Simplemma language detector initialized in %.1fms",
        (time.perf_counter() - started) * 1_000,
    )
    return detector


def detect_document_language(text: str) -> str:
    started = time.perf_counter()
    if JAPANESE_SCRIPT.search(text):
        detected = "Japanese"
    elif KOREAN_SCRIPT.search(text):
        detected = "Korean"
    elif CHINESE_SCRIPT.search(text):
        # Simplified Chinese is the only Chinese option currently exposed by
        # the reader. Script inspection intentionally runs after Japanese.
        detected = "Chinese (Simplified)"
    else:
        language_code = language_detector().main_language(text)
        detected = LANGUAGE_NAMES_BY_CODE.get(language_code)
        if detected is None:
            raise ValueError("the document language could not be identified")
    logger.info(
        "Local language detection selected %s in %.1fms",
        detected,
        (time.perf_counter() - started) * 1_000,
    )
    return detected


def translation_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.6-luna")


def anthropic_grammar_model() -> str:
    model = os.getenv("ANTHROPIC_GRAMMAR_MODEL", "").strip()
    if not model:
        raise ValueError("ANTHROPIC_GRAMMAR_MODEL is not configured")
    return model


def anthropic_grammar_generation_tokens() -> int:
    value = int(os.getenv("ANTHROPIC_GRAMMAR_MAX_OUTPUT_TOKENS", "12000"))
    if value < 1000:
        raise ValueError("ANTHROPIC_GRAMMAR_MAX_OUTPUT_TOKENS must be at least 1000")
    return value


def anthropic_grammar_effort() -> str:
    effort = os.getenv("ANTHROPIC_GRAMMAR_EFFORT", "medium").strip().casefold()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError(
            "ANTHROPIC_GRAMMAR_EFFORT must be low, medium, high, xhigh, or max"
        )
    return effort


@lru_cache(maxsize=1)
def openai_client() -> OpenAI:
    """Return one process-wide client so HTTP connections can be reused."""

    return OpenAI(
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
        max_retries=1,
    )


@lru_cache(maxsize=1)
def anthropic_client() -> Anthropic:
    """Return one process-wide Anthropic client for grammar requests."""

    return Anthropic(
        timeout=float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "180")),
        max_retries=1,
    )


def _log_openai_timing(operation: str, response: Any, elapsed_ms: float) -> None:
    metrics = [f"wall={elapsed_ms:.1f}ms"]
    usage = getattr(response, "usage", None)
    if usage is not None:
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(usage, field, None)
            if isinstance(value, int):
                metrics.append(f"{field.removesuffix('_tokens')}={value}")
    logger.info("OpenAI %s completed: %s", operation, " ".join(metrics))


def timed_openai_response(client: OpenAI, operation: str, **kwargs):
    started = time.perf_counter()
    try:
        response = client.responses.create(**kwargs)
    except Exception:
        logger.warning(
            "OpenAI %s failed after %.1fms",
            operation,
            (time.perf_counter() - started) * 1_000,
        )
        raise
    _log_openai_timing(
        operation, response, (time.perf_counter() - started) * 1_000
    )
    return response


def strict_json_schema(schema: dict) -> dict:
    """Return the OpenAI strict-mode form of a Pydantic JSON schema."""

    strict_schema = json.loads(json.dumps(schema))

    def make_strict(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                properties = value.get("properties", {})
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for child in value.values():
                make_strict(child)
        elif isinstance(value, list):
            for child in value:
                make_strict(child)

    make_strict(strict_schema)
    return strict_schema


def structured_model_response(
    operation: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    schema: dict,
    schema_name: str,
    max_output_tokens: int,
) -> str:
    response = timed_openai_response(
        openai_client(),
        operation,
        model=model,
        input=messages,
        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": strict_json_schema(schema),
            }
        },
        reasoning={"effort": "none"},
        max_output_tokens=max_output_tokens,
        store=False,
    )
    if not response.output_text:
        raise ValueError("the model returned no structured output")
    return response.output_text


def anthropic_structured_model_response(
    operation: str,
    *,
    messages: list[dict[str, str]],
    response_model: type[BaseModel],
    max_output_tokens: int,
    effort: str = "low",
) -> str:
    """Return a Pydantic-validated structured response from Anthropic."""

    system = "\n\n".join(
        message["content"] for message in messages if message["role"] == "system"
    )
    conversation = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    if not conversation:
        raise ValueError(
            "Anthropic requests require at least one conversation message"
        )

    started = time.perf_counter()
    try:
        response = anthropic_client().messages.parse(
            model=anthropic_grammar_model(),
            max_tokens=max_output_tokens,
            system=system,
            messages=conversation,
            output_format=response_model,
            output_config={"effort": effort},
        )
    except ValidationError as exc:
        logger.warning(
            "Anthropic %s returned invalid structured output after %.1fms",
            operation,
            (time.perf_counter() - started) * 1_000,
        )
        if any(
            error["type"] == "json_invalid" and "EOF" in error["msg"]
            for error in exc.errors()
        ):
            raise ValueError(
                "Anthropic structured output was truncated before the JSON "
                f"completed (max_tokens={max_output_tokens})"
            ) from exc
        raise
    except Exception:
        logger.warning(
            "Anthropic %s failed after %.1fms",
            operation,
            (time.perf_counter() - started) * 1_000,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1_000
    usage = response.usage
    logger.info(
        "Anthropic %s completed: wall=%.1fms input=%d output=%d",
        operation,
        elapsed_ms,
        usage.input_tokens,
        usage.output_tokens,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError(
            "Anthropic returned no structured output "
            f"(stop reason: {response.stop_reason}, max_tokens={max_output_tokens})"
        )
    return parsed.model_dump_json()


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
    include_synonyms: bool = False

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


class SynonymRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    source_language: str = Field(min_length=2, max_length=60)
    context: str = Field(default="", max_length=2_000)
    context_offset: int | None = Field(default=None, ge=0, le=2_000)

    @field_validator("text", "source_language")
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


class LanguagePreparationRequest(BaseModel):
    source_language: str = Field(min_length=2, max_length=60)

    @field_validator("source_language")
    @classmethod
    def strip_source_language(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LanguagePreparationResult(BaseModel):
    status: Literal["ready", "preparing"]


class WebImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2_000)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()


class WebImportResult(BaseModel):
    url: str
    title: str
    transcript: list[str]
    audio_url: str | None = None
    video_url: str | None = None
    source_language: str | None = None


class ListeningHistoryCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2_000)
    title: str = Field(min_length=1, max_length=500)

    @field_validator("url", "title")
    @classmethod
    def strip_listening_history_value(cls, value: str) -> str:
        return value.strip()


class SuggestionResult(BaseModel):
    key: str
    series: str
    language: str
    cefr: str
    title: str
    url: str
    season: int | None = None
    episode: int | None = None
    is_bonus: bool = False


class LanguageDetectionResult(BaseModel):
    detected_language: str = Field(
        min_length=2,
        description="The predominant language of the document, written in English",
    )


class SynonymValue(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TranslationResult(BaseModel):
    detected_language: str = Field(description="The source language in English")
    is_word: bool = Field(
        description=(
            "Whether the selection resolves to a dictionary-style vocabulary "
            "term, including a recognized multi-word expression"
        )
    )
    original_source: str = Field(
        description=(
            "The complete source-language surface form, including any "
            "syntax-linked particles or clitics"
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
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = Field(
        default=None,
        description="The grammatical gender of a noun, when the source language assigns one",
    )
    synonyms: list[SynonymValue] | None = Field(
        default=None,
        description="Context-appropriate synonyms for supported single-word lookups",
    )


class SynonymResult(BaseModel):
    detected_language: str = Field(description="The source language in English")
    normalized_source: str = Field(description="The source word in dictionary form")
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None
    synonyms: list[SynonymValue] = Field(
        description="Context-appropriate synonyms ranked by usefulness"
    )


class TranslatedText(BaseModel):
    translation: str = Field(
        min_length=1,
        description="A natural translation in the requested target language",
    )


class ContextualConnectorGloss(BaseModel):
    position: int = Field(
        ge=0,
        description="The zero-based position of the supplied connector occurrence",
    )
    gloss: str = Field(
        min_length=1,
        max_length=120,
        description="One concise English equivalent in this sentence",
    )

    @field_validator("gloss")
    @classmethod
    def strip_gloss(cls, value: str) -> str:
        value = value.strip().strip(".")
        if not value:
            raise ValueError("must not be blank")
        return value


class ContextualConnectorGlossBatch(BaseModel):
    glosses: list[ContextualConnectorGloss] = Field(min_length=1, max_length=200)


class RankedSynonyms(BaseModel):
    synonyms: list[str] = Field(
        max_length=5,
        description="Ranked candidates that match the word's contextual meaning",
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


class SourceNounGrammar(BaseModel):
    article: str = Field(
        description="The definite article for the supplied normalized source lemma",
    )
    gender: Literal["masculine", "feminine", "neutral", "none"] = Field(
        description=(
            "The noun's grammatical gender, or none when the language does not "
            "assign grammatical gender to nouns"
        ),
    )


class VocabularyCreate(BaseModel):
    original_source: str = Field(min_length=1, max_length=2_000)
    normalized_source: str = Field(min_length=1, max_length=2_000)
    translation: str = Field(min_length=1, max_length=2_000)
    source_language: str = Field(min_length=2, max_length=60)
    target_language: str = Field(min_length=2, max_length=60)
    context: str = Field(default="", max_length=2_000)
    document_key: str = Field(default="", max_length=1_000)
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None
    synonyms: list[SynonymValue] = Field(
        default_factory=list,
        max_length=MAX_SYNONYMS,
    )

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
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None
    synonyms: list[SynonymValue] = Field(default_factory=list)
    saved_at: str
    review: ReviewState


class VocabularySaveResult(BaseModel):
    item: VocabularyItem
    created: bool


class RevisionCard(BaseModel):
    item_id: str
    prompt: str
    hint_answer: str
    original_source: str
    normalized_source: str
    context: str
    direction: RevisionDirection
    exercise: RevisionExercise
    choices: list[str]
    choice_genders: dict[
        str, Literal["masculine", "feminine", "neutral"]
    ] = Field(default_factory=dict)
    category: RevisionCategory
    source_language: str
    target_language: str
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None


class SynonymMatchingPair(BaseModel):
    item_id: str
    normalized_source: str
    synonym: str
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None
    synonym_gender: Literal["masculine", "feminine", "neutral"] | None = None


class SynonymMatchingRound(BaseModel):
    exercise: Literal["synonym_matching"] = "synonym_matching"
    source_language: str
    pairs: list[SynonymMatchingPair] = Field(min_length=4, max_length=5)


class ConnectorRevisionCard(BaseModel):
    occurrence_id: str
    exercise: Literal["connector_cloze"] = "connector_cloze"
    sentence: str
    connector: str
    start_offset: int
    end_offset: int
    glosses: list[str]
    contextual_gloss: str | None = None
    choices: list[str] = Field(min_length=2, max_length=4)
    connector_categories: list[str]
    category: RevisionCategory
    source_language: str


class RevisionSession(BaseModel):
    cards: list[RevisionCard]
    due_count: int
    synonym_round: SynonymMatchingRound | None = None
    connector_cards: list[ConnectorRevisionCard] = Field(default_factory=list)
    connector_due_count: int = 0


class RevisionAnswer(BaseModel):
    direction: RevisionDirection
    selected_answer: str = Field(min_length=1, max_length=2_000)
    hint_used: bool = False

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


class ConnectorRevisionAnswer(BaseModel):
    selected_answer: str = Field(min_length=1, max_length=200)

    @field_validator("selected_answer")
    @classmethod
    def strip_connector_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ConnectorRevisionAnswerResult(BaseModel):
    correct: bool
    correct_answer: str
    category: RevisionCategory


@dataclass(frozen=True)
class WordAnalysis:
    token: str
    lemma: str
    pos: str
    associated_clitics: tuple[str, ...] = ()
    confident_verb_lemma: str | None = None
    noun_gender: Literal["masculine", "feminine", "neutral"] | None = None


@dataclass(frozen=True)
class SynonymCandidateSet:
    values: tuple[str, ...]
    sense_count: int
    used_pos_fallback: bool = False


def stanza_pipeline(source_language: str):
    normalized_language = source_language.casefold()
    language = STANZA_LANGUAGES.get(normalized_language)
    if language is None:
        raise ValueError(f"POS tagging is not supported for {source_language}")
    with STANZA_PIPELINE_INIT_LOCKS[normalized_language]:
        existing = STANZA_PIPELINES.get(normalized_language)
        if existing is not None:
            return existing
        started = time.perf_counter()
        processors = "tokenize,pos,lemma"
        if normalized_language in VERB_CLITICS:
            processors += ",depparse"
        try:
            pipeline = stanza.Pipeline(
                lang=language,
                processors=processors,
                download_method=stanza.DownloadMethod.REUSE_RESOURCES,
                use_gpu=False,
                verbose=False,
            )
        except Exception:
            logger.warning(
                "Stanza pipeline initialization failed for %s after %.1fms",
                source_language,
                (time.perf_counter() - started) * 1_000,
            )
            raise
        STANZA_PIPELINES[normalized_language] = pipeline
        logger.info(
            "Stanza pipeline initialized for %s in %.1fms",
            source_language,
            (time.perf_counter() - started) * 1_000,
        )
        return pipeline


def _prepare_stanza_language(source_language: str) -> None:
    normalized_language = source_language.casefold()
    try:
        stanza_pipeline(source_language)
    except Exception as exc:
        logger.warning(
            "Background Stanza preparation failed for %s: %s",
            source_language,
            exc,
        )
    finally:
        with STANZA_PREPARATION_LOCK:
            STANZA_PREPARING.discard(normalized_language)


def start_stanza_preparation(source_language: str) -> Literal["ready", "preparing"]:
    normalized_language = source_language.casefold()
    if normalized_language not in STANZA_LANGUAGES:
        raise ValueError(f"POS tagging is not supported for {source_language}")
    with STANZA_PREPARATION_LOCK:
        if normalized_language in STANZA_PIPELINES:
            return "ready"
        if normalized_language in STANZA_PREPARING:
            return "preparing"
        STANZA_PREPARING.add(normalized_language)
    threading.Thread(
        target=_prepare_stanza_language,
        args=(source_language,),
        name=f"stanza-{STANZA_LANGUAGES[normalized_language]}-warmup",
        daemon=True,
    ).start()
    return "preparing"


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


def noun_gender_from_word(
    word,
) -> Literal["masculine", "feminine", "neutral"] | None:
    return {
        "Masc": "masculine",
        "Fem": "feminine",
        "Neut": "neutral",
    }.get(morphological_features(word).get("Gender"))


def preserve_spanish_feminine_lemma(
    surface: str,
    lemma: str,
    gender: Literal["masculine", "feminine", "neutral"] | None,
) -> str:
    if gender != "feminine":
        return lemma
    surface = surface.strip()
    if surface.casefold().endswith("as") and len(surface) > 2:
        return surface[:-1]
    if surface.casefold().endswith("a"):
        return surface
    return lemma


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


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
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
    lock_started = time.perf_counter()
    with STANZA_PIPELINE_LOCK:
        lock_wait_ms = (time.perf_counter() - lock_started) * 1_000
        inference_started = time.perf_counter()
        document = pipeline(context_text)
        inference_ms = (time.perf_counter() - inference_started) * 1_000
    logger.info(
        "Stanza inference for %s completed: inference=%.1fms lock_wait=%.1fms",
        source_language,
        inference_ms,
        lock_wait_ms,
    )
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
    noun_gender = (
        noun_gender_from_word(selected) if selected.upos in NOUN_POS else None
    )
    if selected.upos in NOUN_POS and source_language.casefold() == "spanish":
        lemma = preserve_spanish_feminine_lemma(
            selected.text, lemma, noun_gender
        )
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
        noun_gender=noun_gender,
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
    schema = SourceNounGrammar.model_json_schema()
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
                "Identify the grammatical gender and choose the definite article "
                "that agrees with the exact normalized dictionary lemma supplied. "
                "Use neutral for the neuter grammatical gender and none when this "
                "language does not assign grammatical gender to nouns. Base both only "
                "on that lemma and its language. Do not infer gender from an "
                "original inflected form, a person, or sentence context. Return "
                "only the requested fields."
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


SPANISH_FEMININE_EL_NOUNS = {
    "acta", "águila", "ala", "alma", "ama", "ancla", "ánfora", "arca",
    "área", "arma", "arpa", "aula", "ave", "agua", "hada", "hacha",
    "hambre",
}


def local_article_for_gender(
    lemma: str,
    language: str,
    gender: Literal["masculine", "feminine", "neutral"],
) -> str:
    language = language.casefold()
    if language == "german":
        return {
            "masculine": "der",
            "feminine": "die",
            "neutral": "das",
        }[gender]
    if language == "spanish":
        if gender == "masculine":
            return "el"
        word = canonicalize(lemma).split()[-1]
        return "el" if word in SPANISH_FEMININE_EL_NOUNS else "la"
    raise ValueError(f"local noun articles are not supported for {language}")


def grammar_from_gender(
    lemma: str,
    language: str,
    gender: Literal["masculine", "feminine", "neutral"] | None,
) -> SourceNounGrammar | None:
    if gender is None or language.casefold() not in {"german", "spanish"}:
        return None
    return SourceNounGrammar(
        article=local_article_for_gender(lemma, language, gender),
        gender=gender,
    )


def local_noun_grammars(
    lemmas: tuple[str, ...], source_language: str
) -> tuple[SourceNounGrammar | None, ...]:
    language = source_language.casefold()
    if language not in {"german", "spanish"} or not lemmas:
        return tuple(None for _ in lemmas)
    keys = [(language, canonicalize(lemma)) for lemma in lemmas]
    with LOCAL_NOUN_GRAMMAR_CACHE_LOCK:
        missing = [
            (key, lemma)
            for key, lemma in zip(keys, lemmas, strict=True)
            if key not in LOCAL_NOUN_GRAMMAR_CACHE
        ]
        if missing:
            prefix = "Ich sehe" if language == "german" else "Veo"
            text = " ".join(f"{prefix} {lemma}." for _, lemma in missing)
            pipeline = stanza_pipeline(source_language)
            started = time.perf_counter()
            with STANZA_PIPELINE_LOCK:
                document = pipeline(text)
            logger.info(
                "Local noun morphology for %s completed in %.1fms",
                source_language,
                (time.perf_counter() - started) * 1_000,
            )
            for index, (key, lemma) in enumerate(missing):
                sentence = (
                    document.sentences[index]
                    if index < len(document.sentences)
                    else None
                )
                words = getattr(sentence, "words", ())
                analyzed = next(
                    (
                        word
                        for word in reversed(words)
                        if noun_gender_from_word(word) is not None
                    ),
                    None,
                )
                gender = noun_gender_from_word(analyzed) if analyzed else None
                LOCAL_NOUN_GRAMMAR_CACHE[key] = grammar_from_gender(
                    lemma, source_language, gender
                )
        return tuple(LOCAL_NOUN_GRAMMAR_CACHE[key] for key in keys)


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


def contextual_connector_gloss_messages(
    *,
    source_language: str,
    sentence: str,
    occurrences: list[dict[str, Any]],
) -> list[dict[str, str]]:
    occurrence_lines = "\n".join(
        (
            f"{position}. {occurrence['surface_text']!r} at characters "
            f"{occurrence['start_offset']}-{occurrence['end_offset']} "
            f"(dictionary senses: {', '.join(occurrence['glosses'])})"
        )
        for position, occurrence in enumerate(occurrences)
    )
    return [
        {
            "role": "system",
            "content": (
                "You provide contextual English glosses for connector words in "
                "a language-learning application. For each supplied occurrence, "
                "return exactly one short English equivalent that expresses what "
                "the connector means in this specific sentence. Prefer a natural "
                "substitution over a dictionary list. Never give alternatives, "
                "slashes, explanations, punctuation, or translations of neighboring "
                "words. Preserve each supplied zero-based position exactly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source_language}\n"
                f"Sentence: {sentence}\n"
                "Connector occurrences:\n"
                f"{occurrence_lines}\n"
                "Return one contextual English gloss for every occurrence."
            ),
        },
    ]


def synonym_ranking_messages(
    *,
    source: str,
    source_language: str,
    context: str,
    part_of_speech: str,
    candidates: tuple[str, ...],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You rank synonyms for a language-learning application. Select "
                "candidates that express the source word's sense and part of speech "
                "in the supplied context. Include useful close synonyms even when "
                "they are not interchangeable in every possible sentence. Rank the "
                "most natural candidate first and return at most two. Never invent, "
                "inflect, translate, explain, or return a candidate from a different "
                "sense. Return an empty list only when every candidate belongs to a "
                "different contextual sense."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source_language}\n"
                f"Source lemma: {source}\n"
                f"Part of speech (Universal POS): {part_of_speech}\n"
                f"Surrounding context: {context or '(not available)'}\n"
                f"Allowed dictionary candidates: {', '.join(candidates)}\n"
                "Return only suitable items from the allowed candidate list."
            ),
        },
    ]


def clean_open_thesaurus_term(raw_term: str) -> str:
    term = re.sub(r"^\(sich\)\s+", "sich ", raw_term.strip())
    while match := re.search(r"\s+\(([^()]*)\)$", term):
        note = match.group(1).casefold()
        if any(marker in note for marker in OPEN_THESAURUS_NON_LEXICAL_MARKERS):
            return ""
        if not any(marker in note for marker in OPEN_THESAURUS_METADATA_MARKERS):
            break
        term = term[:match.start()].rstrip()
    # OpenThesaurus groups occasionally include example sentences alongside
    # lexical alternatives. They express a related idea but cannot substitute
    # for the selected word, so they must not enter the synonym candidate pool.
    if re.search(r"[.!?…][”’\"')\]]*$", term):
        # Periods are part of valid dictionary abbreviations such as ``bspw.``
        # and ``z. B.``; retain those while excluding punctuated prose.
        abbreviation = re.fullmatch(r"(?:[^\W\d_]{1,5}\.\s*)+", term)
        if abbreviation is None:
            return ""
    return term


def parse_open_thesaurus(
    text: str,
) -> dict[str, tuple[tuple[str, ...], ...]]:
    index: dict[str, list[tuple[str, ...]]] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        terms = tuple(dict.fromkeys(
            cleaned
            for raw_term in line.split(";")
            if (cleaned := clean_open_thesaurus_term(raw_term))
        ))
        if len(terms) < 2:
            continue
        for term in terms:
            index.setdefault(canonicalize(term), []).append(terms)
    return {key: tuple(groups) for key, groups in index.items()}


def download_open_thesaurus() -> str:
    response = httpx.get(
        OPEN_THESAURUS_EXPORT_URL,
        follow_redirects=True,
        timeout=30,
    )
    response.raise_for_status()
    if len(response.content) > 10_000_000:
        raise ValueError("OpenThesaurus archive is unexpectedly large")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        info = archive.getinfo("openthesaurus.txt")
        if info.file_size > 10_000_000:
            raise ValueError("OpenThesaurus text export is unexpectedly large")
        text = archive.read(info).decode("utf-8")
    OPEN_THESAURUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OPEN_THESAURUS_PATH.with_suffix(".tmp")
    try:
        temporary_path.write_text(text, encoding="utf-8")
        temporary_path.replace(OPEN_THESAURUS_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)
    return text


def open_thesaurus_index() -> dict[str, tuple[tuple[str, ...], ...]]:
    global OPEN_THESAURUS_INDEX
    with OPEN_THESAURUS_LOCK:
        if OPEN_THESAURUS_INDEX is not None:
            return OPEN_THESAURUS_INDEX
        try:
            text = (
                OPEN_THESAURUS_PATH.read_text(encoding="utf-8")
                if OPEN_THESAURUS_PATH.exists()
                else download_open_thesaurus()
            )
            OPEN_THESAURUS_INDEX = parse_open_thesaurus(text)
        except Exception:
            # Avoid making every lookup repeat a slow failed download.
            OPEN_THESAURUS_INDEX = {}
            raise
        return OPEN_THESAURUS_INDEX


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def open_thesaurus_synonym_candidates(lemma: str) -> SynonymCandidateSet:
    groups = open_thesaurus_index().get(canonicalize(lemma), ())
    excluded = canonicalize(lemma)
    candidates: dict[str, str] = {}
    sense_count = 0
    for group in groups:
        has_alternative = False
        for candidate in group:
            key = canonicalize(candidate)
            if key and key != excluded:
                has_alternative = True
                candidates.setdefault(key, candidate)
        if has_alternative:
            sense_count += 1
    return SynonymCandidateSet(
        values=tuple(candidates.values()),
        sense_count=sense_count,
        used_pos_fallback=bool(candidates),
    )


def wordnet_for_language(source_language: str) -> wn.Wordnet:
    language = source_language.casefold()
    specifier = WORDNET_LEXICONS.get(language)
    if specifier is None:
        raise ValueError("synonyms are currently available only for German and Spanish")
    with WORDNET_LOCK:
        wordnet = WORDNETS.get(language)
        if wordnet is not None:
            return wordnet
        try:
            wordnet = wn.Wordnet(specifier)
        except wn.Error:
            logger.info("Downloading WordNet lexicon %s", specifier)
            wn.download(specifier, progress_handler=None)
            wordnet = wn.Wordnet(specifier)
        WORDNETS[language] = wordnet
        return wordnet


def _prepare_wordnet_language(source_language: str) -> None:
    language = source_language.casefold()
    try:
        wordnet_for_language(source_language)
    except Exception as exc:
        logger.warning(
            "Background WordNet preparation failed for %s: %s",
            source_language,
            exc,
        )
    if language == "german":
        try:
            open_thesaurus_index()
        except Exception as exc:
            logger.warning(
                "Background OpenThesaurus preparation failed: %s", exc
            )
    with WORDNET_LOCK:
        WORDNET_PREPARING.discard(language)


def start_wordnet_preparation(source_language: str) -> None:
    language = source_language.casefold()
    if language not in WORDNET_LEXICONS:
        return
    with WORDNET_LOCK:
        if language in WORDNETS or language in WORDNET_PREPARING:
            return
        WORDNET_PREPARING.add(language)
    threading.Thread(
        target=_prepare_wordnet_language,
        args=(source_language,),
        name=f"wordnet-{language}-warmup",
        daemon=True,
    ).start()


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def wordnet_synonym_candidates(
    lemma: str, source_language: str, part_of_speech: str
) -> SynonymCandidateSet:
    wordnet_pos = {
        "NOUN": "n",
        "VERB": "v",
        "AUX": "v",
        "ADJ": "a",
        "ADV": "r",
    }.get(part_of_speech)
    candidates: dict[str, str] = {}
    lookup_forms = [lemma]
    if lemma.casefold().startswith("sich "):
        lookup_forms.append(lemma[5:].strip())
    elif source_language.casefold() == "spanish" and lemma.casefold().endswith("se"):
        lookup_forms.append(lemma[:-2])
    excluded = {canonicalize(value) for value in lookup_forms}
    sense_count = 0
    with WORDNET_LOCK:
        wordnet = wordnet_for_language(source_language)

        def add_synsets(synsets: list[wn.Synset]) -> bool:
            nonlocal sense_count
            for synset in synsets:
                has_alternative = False
                for candidate in synset.lemmas():
                    candidate = candidate.replace("_", " ").strip()
                    key = canonicalize(candidate)
                    if key and key not in excluded:
                        has_alternative = True
                        candidates.setdefault(key, candidate)
                    if len(candidates) >= 32:
                        if has_alternative:
                            sense_count += 1
                        return True
                if has_alternative:
                    sense_count += 1
            return False

        for lookup in lookup_forms:
            synsets = wordnet.synsets(lookup, pos=wordnet_pos) if wordnet_pos else []
            if add_synsets(synsets):
                return SynonymCandidateSet(tuple(candidates.values()), sense_count)
            # Recover from an unknown/mistagged POS, a source-only synset, or
            # lexicons whose adjective categories do not map exactly to UPOS.
            if not candidates and wordnet_pos:
                add_synsets(wordnet.synsets(lookup))
                if candidates:
                    return SynonymCandidateSet(
                        tuple(candidates.values()),
                        sense_count,
                        used_pos_fallback=True,
                    )
            if candidates:
                break
    return SynonymCandidateSet(tuple(candidates.values()), sense_count)


def dictionary_synonym_candidates(
    lemma: str,
    source_language: str,
    part_of_speech: str,
) -> SynonymCandidateSet:
    wordnet_candidates = wordnet_synonym_candidates(
        lemma, source_language, part_of_speech
    )
    if source_language.casefold() != "german":
        return wordnet_candidates
    try:
        open_thesaurus_candidates = open_thesaurus_synonym_candidates(lemma)
    except Exception as exc:
        logger.warning("OpenThesaurus lookup failed; using OdeNet only: %s", exc)
        return wordnet_candidates
    merged: dict[str, str] = {}
    for candidate in (
        *wordnet_candidates.values,
        *open_thesaurus_candidates.values,
    ):
        merged.setdefault(canonicalize(candidate), candidate)
    return SynonymCandidateSet(
        values=tuple(merged.values()),
        sense_count=(
            wordnet_candidates.sense_count
            + open_thesaurus_candidates.sense_count
        ),
        used_pos_fallback=(
            wordnet_candidates.used_pos_fallback
            or open_thesaurus_candidates.used_pos_fallback
        ),
    )


def canonicalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def frequency_ranked_synonym_candidates(
    source: str,
    source_language: str,
    candidates: tuple[str, ...],
) -> tuple[str, ...]:
    language_code = WORD_FREQUENCY_LANGUAGES.get(source_language.casefold())
    if language_code is None or not candidates:
        return candidates
    scored = [
        (candidate, zipf_frequency(candidate, language_code))
        for candidate in candidates
    ]
    if not any(score > 0 for _, score in scored):
        # Preserve WordNet's result if wordfreq has no evidence either way.
        return candidates[:MAX_SYNONYM_CANDIDATES]
    source_score = zipf_frequency(source, language_code)
    threshold = max(
        MIN_SYNONYM_ZIPF,
        source_score - MAX_SYNONYM_ZIPF_DROP,
    )
    filtered = tuple(
        candidate
        for candidate, score in sorted(
            scored,
            key=lambda item: item[1],
            reverse=True,
        )
        if score >= threshold
    )
    return filtered[:MAX_SYNONYM_CANDIDATES]


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def part_of_speech_filtered_synonym_candidates(
    source_language: str,
    part_of_speech: str,
    candidates: tuple[str, ...],
) -> tuple[str, ...]:
    language = source_language.casefold()
    compatible = SYNONYM_POS_COMPATIBILITY.get(part_of_speech)
    if language == "german" and part_of_speech in {"ADJ", "ADV"}:
        # German uninflected adjectives regularly function adverbially.
        compatible = {"ADJ", "ADV"}
    templates = {
        "german": {
            "NOUN": "Ich sehe {}.",
            "VERB": "Wir wollen {}.",
            "AUX": "Wir wollen {}.",
            "ADJ": "Das ist {}.",
            "ADV": "Das ist {} richtig.",
        },
        "spanish": {
            "NOUN": "Veo {}.",
            "VERB": "Quiero {}.",
            "AUX": "Quiero {}.",
            "ADJ": "Es {}.",
            "ADV": "Es {} correcto.",
        },
    }
    template = templates.get(language, {}).get(part_of_speech)
    if compatible is None or template is None or not candidates:
        return candidates
    analyzable = [
        (index, candidate)
        for index, candidate in enumerate(candidates)
        if re.fullmatch(r"[^\W\d_]+(?:-[^\W\d_]+)*", candidate)
    ]
    if not analyzable:
        return candidates
    pipeline = stanza_pipeline(source_language)
    text = " ".join(template.format(candidate) for _, candidate in analyzable)
    with STANZA_PIPELINE_LOCK:
        document = pipeline(text)
    rejected: set[int] = set()
    for (index, candidate), sentence in zip(
        analyzable, document.sentences, strict=False
    ):
        candidate_key = canonicalize(candidate)
        analyzed = next(
            (
                word
                for word in sentence.words
                if canonicalize(word.text) == candidate_key
            ),
            None,
        )
        if analyzed is not None and analyzed.upos not in compatible:
            rejected.add(index)
    return tuple(
        candidate
        for index, candidate in enumerate(candidates)
        if index not in rejected
    )


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
            noun_gender TEXT,
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


def migrate_vocabulary_gender(connection: sqlite3.Connection) -> None:
    for registered in registered_language_tables(connection):
        table_name = registered["table_name"]
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if "noun_gender" not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN noun_gender TEXT")


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


def create_connector_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_sentences (
            id TEXT PRIMARY KEY,
            source_language TEXT NOT NULL,
            canonical_source_language TEXT NOT NULL,
            text TEXT NOT NULL,
            canonical_text TEXT NOT NULL,
            document_key TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL,
            UNIQUE (canonical_source_language, canonical_text)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vocabulary_sentence_links (
            vocabulary_item_id TEXT NOT NULL,
            sentence_id TEXT NOT NULL,
            PRIMARY KEY (vocabulary_item_id, sentence_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_occurrences (
            id TEXT PRIMARY KEY,
            sentence_id TEXT NOT NULL,
            connector_key TEXT NOT NULL,
            surface_text TEXT NOT NULL,
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            categories_json TEXT NOT NULL,
            glosses_json TEXT NOT NULL,
            contextual_gloss TEXT,
            UNIQUE (sentence_id, connector_key, start_offset)
        )
        """
    )
    occurrence_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(connector_occurrences)"
        ).fetchall()
    }
    if "contextual_gloss" not in occurrence_columns:
        connection.execute(
            "ALTER TABLE connector_occurrences ADD COLUMN contextual_gloss TEXT"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_reviews (
            canonical_source_language TEXT NOT NULL,
            connector_key TEXT NOT NULL,
            last_reviewed_at TEXT,
            next_review_at TEXT,
            repetitions INTEGER NOT NULL DEFAULT 0,
            lapses INTEGER NOT NULL DEFAULT 0,
            consecutive_correct INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (canonical_source_language, connector_key)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def create_grammar_tables(connection: sqlite3.Connection) -> None:
    """Create language-neutral topic-level grammar review state."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_sessions (
            id TEXT PRIMARY KEY,
            canonical_language TEXT NOT NULL,
            kind TEXT NOT NULL,
            topic_keys_json TEXT NOT NULL,
            rule_summary TEXT NOT NULL,
            topic_summaries_json TEXT NOT NULL DEFAULT '{}',
            rule_tables_json TEXT NOT NULL DEFAULT '[]',
            worked_examples_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    session_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(grammar_sessions)")
    }
    if "rule_tables_json" not in session_columns:
        connection.execute(
            "ALTER TABLE grammar_sessions "
            "ADD COLUMN rule_tables_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "topic_summaries_json" not in session_columns:
        connection.execute(
            "ALTER TABLE grammar_sessions "
            "ADD COLUMN topic_summaries_json TEXT NOT NULL DEFAULT '{}'"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_exercises (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            topic_key TEXT NOT NULL,
            exercise_type TEXT NOT NULL,
            instruction TEXT NOT NULL,
            prompt TEXT NOT NULL,
            choices_json TEXT NOT NULL,
            tokens_json TEXT NOT NULL,
            accepted_answers_json TEXT NOT NULL,
            reference_answer TEXT NOT NULL,
            grading_rubric TEXT NOT NULL,
            explanation TEXT NOT NULL,
            UNIQUE (session_id, position)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_exercise_answers (
            exercise_id TEXT PRIMARY KEY,
            answer TEXT NOT NULL,
            correct INTEGER NOT NULL,
            feedback TEXT NOT NULL,
            answered_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_reviews (
            canonical_language TEXT NOT NULL,
            topic_key TEXT NOT NULL,
            introduced_at TEXT NOT NULL,
            last_reviewed_at TEXT,
            next_review_at TEXT,
            repetitions INTEGER NOT NULL DEFAULT 0,
            lapses INTEGER NOT NULL DEFAULT 0,
            consecutive_correct INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (canonical_language, topic_key)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_topic_summaries (
            canonical_language TEXT NOT NULL,
            topic_key TEXT NOT NULL,
            summary TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (canonical_language, topic_key)
        )
        """
    )
    summary_cache_migrated = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        ("grammar_topic_summary_cache_v1",),
    ).fetchone()
    if summary_cache_migrated is None:
        for session in connection.execute(
            """
            SELECT canonical_language, topic_summaries_json, created_at
            FROM grammar_sessions ORDER BY created_at DESC
            """
        ).fetchall():
            summaries = json.loads(session["topic_summaries_json"])
            connection.executemany(
                """
                INSERT OR IGNORE INTO grammar_topic_summaries (
                    canonical_language, topic_key, summary, generated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        session["canonical_language"],
                        topic_key,
                        summary,
                        session["created_at"],
                    )
                    for topic_key, summary in summaries.items()
                    if summary
                ),
            )
        connection.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            ("grammar_topic_summary_cache_v1", datetime.now(UTC).isoformat()),
        )


def seed_initial_grammar_progress(
    connection: sqlite3.Connection,
    *,
    introduced_at: datetime | None = None,
) -> None:
    """Record the learner's pre-existing coursework exactly once."""

    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        (INITIAL_GRAMMAR_PROGRESS_MIGRATION,),
    ).fetchone()
    if applied is not None:
        return
    introduced_at = introduced_at or datetime.now(UTC)
    if introduced_at.tzinfo is None:
        raise ValueError("introduced_at must include a timezone")
    timestamp = introduced_at.astimezone(UTC).isoformat()
    connection.executemany(
        """
        INSERT OR IGNORE INTO grammar_reviews (
            canonical_language, topic_key, introduced_at
        ) VALUES (?, ?, ?)
        """,
        (
            (topic.language.value, topic.key, timestamp)
            for topic in initially_seen_topics()
        ),
    )
    connection.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        (INITIAL_GRAMMAR_PROGRESS_MIGRATION, timestamp),
    )


def connector_catalogue(language: str) -> dict[str, dict[str, tuple[str, ...]]]:
    normalized_language = canonicalize(language)
    if normalized_language in {"german", "deutsch"}:
        return GERMAN_CONNECTORS
    if normalized_language in {"spanish", "español", "espanol"}:
        return SPANISH_CONNECTORS
    return {}


def connector_occurrences_in_sentence(
    sentence: str,
    language: str,
) -> list[tuple[str, re.Match[str]]]:
    matches: list[tuple[str, re.Match[str]]] = []
    occupied: list[tuple[int, int]] = []
    for connector in sorted(connector_catalogue(language), key=len, reverse=True):
        pattern = re.escape(connector).replace(r"\ ", r"\s+")
        for match in re.finditer(
            rf"(?<!\w){pattern}(?!\w)", sentence, flags=re.IGNORECASE
        ):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            matches.append((connector, match))
    return sorted(matches, key=lambda entry: entry[1].start())


def index_saved_sentence(
    connection: sqlite3.Connection,
    *,
    vocabulary_item_id: str,
    source_language: str,
    context: str,
    document_key: str,
    saved_at: str,
) -> str | None:
    sentence = context.strip()
    if not sentence:
        return None
    canonical_language = canonicalize(source_language)
    canonical_sentence = canonicalize(sentence)
    sentence_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"margin-sentence\0{canonical_language}\0{canonical_sentence}",
        )
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO connector_sentences (
            id, source_language, canonical_source_language, text,
            canonical_text, document_key, saved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sentence_id,
            source_language,
            canonical_language,
            sentence,
            canonical_sentence,
            document_key,
            saved_at,
        ),
    )
    stored = connection.execute(
        """
        SELECT * FROM connector_sentences
        WHERE canonical_source_language = ? AND canonical_text = ?
        """,
        (canonical_language, canonical_sentence),
    ).fetchone()
    if stored is None:
        return None
    sentence_id = stored["id"]
    connection.execute(
        """
        INSERT OR IGNORE INTO vocabulary_sentence_links (
            vocabulary_item_id, sentence_id
        ) VALUES (?, ?)
        """,
        (vocabulary_item_id, sentence_id),
    )
    catalogue = connector_catalogue(stored["source_language"])
    for connector, match in connector_occurrences_in_sentence(
        stored["text"], stored["source_language"]
    ):
        definition = catalogue[connector]
        occurrence_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"margin-connector\0{sentence_id}\0{connector}\0{match.start()}",
            )
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO connector_occurrences (
                id, sentence_id, connector_key, surface_text,
                start_offset, end_offset, categories_json, glosses_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurrence_id,
                sentence_id,
                connector,
                match.group(),
                match.start(),
                match.end(),
                json.dumps(definition["categories"], ensure_ascii=False),
                json.dumps(definition["glosses"], ensure_ascii=False),
            ),
        )
    pending_occurrence = connection.execute(
        """
        SELECT 1 FROM connector_occurrences
        WHERE sentence_id = ? AND contextual_gloss IS NULL
        LIMIT 1
        """,
        (sentence_id,),
    ).fetchone()
    return sentence_id if pending_occurrence is not None else None


def backfill_connector_sentences(connection: sqlite3.Connection) -> None:
    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        (CONNECTOR_BACKFILL_VERSION,),
    ).fetchone()
    if applied is not None:
        return
    for registered in registered_language_tables(connection):
        rows = connection.execute(
            f"SELECT id, source_language, context, document_key, saved_at "
            f"FROM {registered['table_name']}"
        ).fetchall()
        for row in rows:
            index_saved_sentence(
                connection,
                vocabulary_item_id=row["id"],
                source_language=row["source_language"],
                context=row["context"],
                document_key=row["document_key"],
                saved_at=row["saved_at"],
            )
    connection.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        (CONNECTOR_BACKFILL_VERSION, datetime.now(UTC).isoformat()),
    )


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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vocabulary_synonyms (
                vocabulary_item_id TEXT NOT NULL,
                text TEXT NOT NULL,
                canonical_text TEXT NOT NULL,
                noun_gender TEXT,
                position INTEGER NOT NULL,
                PRIMARY KEY (vocabulary_item_id, canonical_text)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS listening_history (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                listened_at TEXT NOT NULL
            )
            """
        )
        create_connector_tables(connection)
        create_grammar_tables(connection)
        seed_initial_grammar_progress(connection)
        migrate_legacy_vocabulary(connection)
        migrate_vocabulary_gender(connection)
        backfill_connector_sentences(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()


def enrich_connector_sentence(sentence_id: str) -> None:
    """Generate and persist one contextual English gloss per connector occurrence."""

    try:
        with vocabulary_database() as connection:
            sentence = connection.execute(
                "SELECT source_language, text FROM connector_sentences WHERE id = ?",
                (sentence_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, surface_text, start_offset, end_offset, glosses_json
                FROM connector_occurrences
                WHERE sentence_id = ? AND contextual_gloss IS NULL
                ORDER BY start_offset, id
                """,
                (sentence_id,),
            ).fetchall()
        if sentence is None or not rows:
            return

        occurrences = [
            {
                "id": row["id"],
                "surface_text": row["surface_text"],
                "start_offset": row["start_offset"],
                "end_offset": row["end_offset"],
                "glosses": json.loads(row["glosses_json"]),
            }
            for row in rows
        ]
        content = structured_model_response(
            "contextual connector glosses",
            model=translation_model(),
            messages=contextual_connector_gloss_messages(
                source_language=sentence["source_language"],
                sentence=sentence["text"],
                occurrences=occurrences,
            ),
            schema=ContextualConnectorGlossBatch.model_json_schema(),
            schema_name="contextual_connector_glosses",
            max_output_tokens=min(4096, 48 * len(occurrences)),
        )
        generated = ContextualConnectorGlossBatch.model_validate_json(content)
        glosses_by_position = {
            item.position: item.gloss
            for item in generated.glosses
            if item.position < len(occurrences)
        }
        if not glosses_by_position:
            raise ValueError("the model returned no matching connector glosses")

        with vocabulary_database() as connection:
            for position, gloss in glosses_by_position.items():
                connection.execute(
                    """
                    UPDATE connector_occurrences
                    SET contextual_gloss = ?
                    WHERE id = ? AND contextual_gloss IS NULL
                    """,
                    (gloss, occurrences[position]["id"]),
                )
    except Exception:
        # Contextual enrichment is intentionally best-effort. Revision can
        # always fall back to the first curated dictionary gloss.
        logger.exception(
            "Contextual connector-gloss enrichment failed for sentence %s",
            sentence_id,
        )


def vocabulary_synonyms(
    connection: sqlite3.Connection,
    item_id: str,
) -> list[SynonymValue]:
    rows = connection.execute(
        """
        SELECT text, noun_gender
        FROM vocabulary_synonyms
        WHERE vocabulary_item_id = ?
        ORDER BY position, canonical_text
        """,
        (item_id,),
    ).fetchall()
    return [
        SynonymValue(text=row["text"], noun_gender=row["noun_gender"])
        for row in rows
    ]


def vocabulary_item(
    row: sqlite3.Row,
    synonyms: list[SynonymValue] | None = None,
) -> VocabularyItem:
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
        noun_gender=row["noun_gender"],
        synonyms=synonyms or [],
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
    row: sqlite3.Row,
    rows: list[sqlite3.Row],
    *,
    supports_letter_tiles: bool = False,
) -> RevisionCard:
    state = schedule_state(row)
    category = revision_category(state)
    if supports_letter_tiles:
        if state.consecutive_correct >= 4:
            exercise = RevisionExercise.TYPED_RECALL
            directions = list(RevisionDirection)
        elif state.consecutive_correct >= 2:
            exercise = RevisionExercise.LETTER_TILES
            directions = [RevisionDirection.TRANSLATION_TO_SOURCE]
        else:
            directions = [
                direction
                for direction in RevisionDirection
                if len(revision_choices(row, rows, direction)) >= 2
            ]
            if directions:
                exercise = RevisionExercise.MULTIPLE_CHOICE
            else:
                exercise = RevisionExercise.LETTER_TILES
                directions = [RevisionDirection.TRANSLATION_TO_SOURCE]
    else:
        familiar = category in {
            RevisionCategory.ALWAYS_CORRECT,
            RevisionCategory.USUALLY_CORRECT,
        }
        if familiar:
            exercise = RevisionExercise.TYPED_RECALL
            directions = list(RevisionDirection)
        else:
            directions = [
                direction
                for direction in RevisionDirection
                if len(revision_choices(row, rows, direction)) >= 2
            ]
            exercise = (
                RevisionExercise.MULTIPLE_CHOICE
                if directions
                else RevisionExercise.TYPED_RECALL
            )
            if not directions:
                directions = list(RevisionDirection)

    direction = random.SystemRandom().choice(directions)
    prompt_field = (
        "normalized_source"
        if direction is RevisionDirection.SOURCE_TO_TRANSLATION
        else "translation"
    )
    choices = (
        revision_choices(row, rows, direction)
        if exercise is RevisionExercise.MULTIPLE_CHOICE
        else []
    )
    choice_genders = {}
    if direction is RevisionDirection.TRANSLATION_TO_SOURCE:
        genders_by_source = {
            candidate["normalized_source"]: candidate["noun_gender"]
            for candidate in rows
            if candidate["noun_gender"] is not None
        }
        choice_genders = {
            choice: genders_by_source[choice]
            for choice in choices
            if choice in genders_by_source
        }
    return RevisionCard(
        item_id=row["id"],
        prompt=row[prompt_field],
        hint_answer=row[
            "translation"
            if direction is RevisionDirection.SOURCE_TO_TRANSLATION
            else "normalized_source"
        ],
        original_source=row["original_source"],
        normalized_source=row["normalized_source"],
        context=row["context"],
        direction=direction,
        exercise=exercise,
        choices=choices,
        choice_genders=choice_genders,
        category=category,
        source_language=row["source_language"],
        target_language=row["target_language"],
        noun_gender=row["noun_gender"],
    )


def synonym_matching_round(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
) -> SynonymMatchingRound | None:
    groups: dict[str, list[tuple[sqlite3.Row, list[SynonymValue]]]] = {}
    for row in rows:
        if schedule_state(row).consecutive_correct < 5:
            continue
        synonyms = vocabulary_synonyms(connection, row["id"])
        if synonyms:
            groups.setdefault(canonicalize(row["source_language"]), []).append(
                (row, synonyms)
            )

    generator = random.SystemRandom()
    candidates_by_language = list(groups.values())
    generator.shuffle(candidates_by_language)
    for candidates in candidates_by_language:
        if len(candidates) < 4:
            continue
        best: list[SynonymMatchingPair] = []
        for _ in range(20):
            shuffled_candidates = list(candidates)
            generator.shuffle(shuffled_candidates)
            selected_sources: set[str] = set()
            selected_synonyms: set[str] = set()
            pairs: list[SynonymMatchingPair] = []
            for row, stored_synonyms in shuffled_candidates:
                source_key = canonicalize(row["normalized_source"])
                if source_key in selected_sources or source_key in selected_synonyms:
                    continue
                available = [
                    synonym
                    for synonym in stored_synonyms
                    if canonicalize(synonym.text) not in {
                        source_key,
                        *selected_sources,
                        *selected_synonyms,
                    }
                ]
                if not available:
                    continue
                generator.shuffle(available)
                synonym = available[0]
                synonym_key = canonicalize(synonym.text)
                selected_sources.add(source_key)
                selected_synonyms.add(synonym_key)
                pairs.append(
                    SynonymMatchingPair(
                        item_id=row["id"],
                        normalized_source=row["normalized_source"],
                        synonym=synonym.text,
                        noun_gender=row["noun_gender"],
                        synonym_gender=synonym.noun_gender,
                    )
                )
                if len(pairs) == 5:
                    break
            if len(pairs) > len(best):
                best = pairs
            if len(best) == 5:
                break
        if len(best) >= 4:
            return SynonymMatchingRound(
                source_language=candidates[0][0]["source_language"],
                pairs=best[:5],
            )
    return None


def connector_revision_cards(
    connection: sqlite3.Connection,
    *,
    language: str | None,
    now: datetime,
    limit: int = CONNECTOR_REVISION_LIMIT,
) -> tuple[list[ConnectorRevisionCard], int]:
    parameters: tuple[str, ...] = ()
    language_filter = ""
    if language is not None:
        language_filter = "WHERE s.canonical_source_language = ?"
        parameters = (canonicalize(language),)
    rows = connection.execute(
        f"""
        SELECT o.*, s.text AS sentence, s.source_language,
            s.canonical_source_language,
            r.last_reviewed_at, r.next_review_at,
            COALESCE(r.repetitions, 0) AS repetitions,
            COALESCE(r.lapses, 0) AS lapses,
            COALESCE(r.consecutive_correct, 0) AS consecutive_correct
        FROM connector_occurrences o
        JOIN connector_sentences s ON s.id = o.sentence_id
        LEFT JOIN connector_reviews r
          ON r.canonical_source_language = s.canonical_source_language
         AND r.connector_key = o.connector_key
        {language_filter}
        """,
        parameters,
    ).fetchall()
    due_by_connector: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        if is_due(schedule_state(row), at=now):
            key = (row["canonical_source_language"], row["connector_key"])
            due_by_connector.setdefault(key, []).append(row)
    generator = random.SystemRandom()
    connector_groups = list(due_by_connector.values())
    generator.shuffle(connector_groups)
    cards: list[ConnectorRevisionCard] = []
    for occurrences in connector_groups[:limit]:
        row = generator.choice(occurrences)
        categories = json.loads(row["categories_json"])
        connector = row["connector_key"]
        catalogue = connector_catalogue(row["source_language"])
        preferred = [
            candidate
            for candidate, definition in catalogue.items()
            if candidate != connector
            and set(definition["categories"]).intersection(categories)
        ]
        fallback = [
            candidate
            for candidate in catalogue
            if candidate != connector and candidate not in preferred
        ]
        generator.shuffle(preferred)
        generator.shuffle(fallback)
        choices = [connector, *(preferred + fallback)[:3]]
        generator.shuffle(choices)
        cards.append(
            ConnectorRevisionCard(
                occurrence_id=row["id"],
                sentence=row["sentence"],
                connector=row["surface_text"],
                start_offset=row["start_offset"],
                end_offset=row["end_offset"],
                glosses=json.loads(row["glosses_json"]),
                contextual_gloss=row["contextual_gloss"],
                choices=choices,
                connector_categories=categories,
                category=revision_category(schedule_state(row)),
                source_language=row["source_language"],
            )
        )
    return cards, len(due_by_connector)


app = FastAPI(title="PDF Language Learner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/import-web", response_model=WebImportResult)
def import_web(request: WebImportRequest) -> WebImportResult:
    try:
        document = fetch_web_document(request.url)
    except WebImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WebImportResult(
        url=document.url,
        title=document.title,
        transcript=document.transcript,
        audio_url=document.audio_url,
        video_url=document.video_url,
        source_language=document.source_language,
    )


@app.get("/api/suggestions", response_model=list[SuggestionResult])
def list_suggestions() -> list[SuggestionResult]:
    with vocabulary_database() as connection:
        listened_urls = {
            row["url"]
            for row in connection.execute("SELECT url FROM listening_history").fetchall()
        }
    return [SuggestionResult(**vars(item)) for item in suggestions_for(listened_urls)]


@app.post("/api/listening-history", status_code=204)
def record_listening_history(request: ListeningHistoryCreate) -> Response:
    url = canonical_url(request.url)
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
        raise HTTPException(status_code=422, detail="Listening URL must be public HTTP(S)")
    with vocabulary_database() as connection:
        connection.execute(
            """
            INSERT INTO listening_history (url, title, listened_at)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                listened_at = excluded.listened_at
            """,
            (url, request.title, datetime.now(UTC).isoformat()),
        )
    return Response(status_code=204)


@app.get("/api/vocabulary/languages", response_model=list[str])
def list_vocabulary_languages() -> list[str]:
    with vocabulary_database() as connection:
        languages = [row["display_name"] for row in registered_language_tables(connection)]
    return languages


class GrammarSessionRequest(BaseModel):
    language: str


class GrammarAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


def grammar_catalogue(language: str) -> tuple[GrammarTopic, ...]:
    normalized = canonicalize(language)
    if normalized in {"german", "deutsch"}:
        return GRAMMAR_TOPICS
    if normalized in {"spanish", "espanol", "español"}:
        return SPANISH_GRAMMAR_TOPICS
    raise HTTPException(status_code=422, detail="Grammar revision supports German and Spanish")


def grammar_schedule_from_row(row: sqlite3.Row | None) -> ScheduleState:
    if row is None:
        return ScheduleState()
    return ScheduleState(
        repetitions=row["repetitions"],
        lapses=row["lapses"],
        consecutive_correct=row["consecutive_correct"],
        last_reviewed_at=parse_timestamp(row["last_reviewed_at"]),
        next_review_at=parse_timestamp(row["next_review_at"]),
    )


def select_grammar_topics(
    connection: sqlite3.Connection,
    language: str,
    now: datetime,
) -> tuple[GrammarSessionKind, list[GrammarTopic]] | None:
    catalogue = grammar_catalogue(language)
    canonical_language = catalogue[0].language.value
    review_rows = {
        row["topic_key"]: row
        for row in connection.execute(
            "SELECT * FROM grammar_reviews WHERE canonical_language = ?",
            (canonical_language,),
        ).fetchall()
    }
    unseen = [topic for topic in catalogue if topic.key not in review_rows]
    due = [
        topic for topic in catalogue
        if topic.key in review_rows
        and is_due(grammar_schedule_from_row(review_rows[topic.key]), at=now)
    ]
    due.sort(
        key=lambda topic: (
            review_rows[topic.key]["next_review_at"] is not None,
            review_rows[topic.key]["next_review_at"] or "",
            topic.sequence,
        )
    )
    completed = connection.execute(
        "SELECT COUNT(*) FROM grammar_sessions WHERE canonical_language = ? AND completed_at IS NOT NULL",
        (canonical_language,),
    ).fetchone()[0]
    if unseen and (not due or completed % 3 < 2):
        return GrammarSessionKind.LESSON, unseen[:1]
    if due:
        return GrammarSessionKind.REVIEW, due[:3]
    if unseen:
        return GrammarSessionKind.LESSON, unseen[:1]
    return None


def saved_grammar_vocabulary(
    connection: sqlite3.Connection, language: str
) -> list[str]:
    """Return recently reviewed words, falling back only when none were reviewed."""

    table = language_table(connection, language)
    if table is None:
        return []
    reviewed = [
        row["normalized_source"]
        for row in connection.execute(
            f"""
            SELECT normalized_source FROM {table}
            WHERE last_reviewed_at IS NOT NULL
            ORDER BY last_reviewed_at DESC, saved_at DESC
            LIMIT 24
            """
        ).fetchall()
    ]
    if reviewed:
        return reviewed
    return [
        row["normalized_source"]
        for row in connection.execute(
            f"SELECT normalized_source FROM {table} ORDER BY saved_at DESC LIMIT 24"
        ).fetchall()
    ]


def generate_grammar_content(
    language: str,
    kind: GrammarSessionKind,
    topics: list[GrammarTopic],
    vocabulary: list[str],
) -> GrammarGeneratedSession:
    topic_data = [
        {
            "key": topic.key,
            "title": topic.title,
            "level": topic.level.value,
            "example": topic.example,
        }
        for topic in topics
    ]
    content = anthropic_structured_model_response(
        "grammar session generation",
        messages=grammar_generation_messages(
            language=language,
            kind=kind,
            topics=topic_data,
            saved_vocabulary=vocabulary,
        ),
        response_model=GrammarGenerationResponse,
        max_output_tokens=anthropic_grammar_generation_tokens(),
        effort=anthropic_grammar_effort(),
    )
    generated = GrammarGenerationResponse.model_validate_json(
        content
    ).to_generated_session()
    allowed = {topic.key for topic in topics}
    if any(exercise.topic_key not in allowed for exercise in generated.exercises):
        raise ValueError("generated exercise referred to an unselected grammar topic")
    counts = {
        topic.key: sum(
            exercise.topic_key == topic.key for exercise in generated.exercises
        )
        for topic in topics
    }
    if max(counts.values()) - min(counts.values()) > 1 or any(
        count == 0 for count in counts.values()
    ):
        raise ValueError("generated exercises were not balanced across selected topics")
    return generated


def persist_grammar_session(
    connection: sqlite3.Connection,
    *,
    language: str,
    kind: GrammarSessionKind,
    topics: list[GrammarTopic],
    generated: GrammarGeneratedSession,
    now: datetime,
) -> str:
    session_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO grammar_sessions (
            id, canonical_language, kind, topic_keys_json, rule_summary,
            rule_tables_json, worked_examples_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            canonicalize(language),
            kind.value,
            json.dumps([topic.key for topic in topics]),
            generated.rule_summary,
            json.dumps(
                [table.model_dump() for table in generated.rule_tables],
                ensure_ascii=False,
            ),
            json.dumps(generated.worked_examples, ensure_ascii=False),
            now.isoformat(),
        ),
    )
    connection.executemany(
        """
        INSERT INTO grammar_exercises (
            id, session_id, position, topic_key, exercise_type, instruction,
            prompt, choices_json, tokens_json, accepted_answers_json,
            reference_answer, grading_rubric, explanation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(uuid.uuid4()), session_id, position, exercise.topic_key,
                exercise.type.value, exercise.instruction, exercise.prompt,
                json.dumps(exercise.choices, ensure_ascii=False),
                json.dumps(exercise.tokens, ensure_ascii=False),
                json.dumps(exercise.accepted_answers, ensure_ascii=False),
                exercise.reference_answer, exercise.grading_rubric,
                exercise.explanation,
            )
            for position, exercise in enumerate(generated.exercises, start=1)
        ],
    )
    return session_id


def grammar_session_payload(
    connection: sqlite3.Connection, session_id: str
) -> dict[str, Any]:
    session_row = connection.execute(
        "SELECT * FROM grammar_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session_row is None:
        raise HTTPException(status_code=404, detail="Grammar session not found")
    exercises = connection.execute(
        """
        SELECT e.*, a.correct FROM grammar_exercises e
        LEFT JOIN grammar_exercise_answers a ON a.exercise_id = e.id
        WHERE e.session_id = ? ORDER BY e.position
        """,
        (session_id,),
    ).fetchall()
    answered = [row for row in exercises if row["correct"] is not None]
    current = next((row for row in exercises if row["correct"] is None), None)
    catalogue = {topic.key: topic for topic in grammar_catalogue(session_row["canonical_language"])}
    topic_keys = json.loads(session_row["topic_keys_json"])
    topic_summaries = json.loads(session_row["topic_summaries_json"])
    topic_summaries.update(
        {
            row["topic_key"]: row["summary"]
            for row in connection.execute(
                """
                SELECT topic_key, summary FROM grammar_topic_summaries
                WHERE canonical_language = ?
                """,
                (session_row["canonical_language"],),
            ).fetchall()
        }
    )
    payload: dict[str, Any] = {
        "id": session_id,
        "language": session_row["canonical_language"],
        "kind": session_row["kind"],
        "topics": [
            {
                "key": key, "title": catalogue[key].title,
                "category": catalogue[key].category, "level": catalogue[key].level.value,
                "summary": topic_summaries.get(key),
            }
            for key in topic_keys
        ],
        "rule_summary": session_row["rule_summary"],
        "rule_tables": json.loads(session_row["rule_tables_json"]),
        "worked_examples": json.loads(session_row["worked_examples_json"]),
        "answered": len(answered),
        "correct": sum(row["correct"] for row in answered),
        "total": len(exercises),
        "complete": session_row["completed_at"] is not None,
        "exercise": None,
    }
    if current is not None:
        payload["exercise"] = {
            "id": current["id"], "position": current["position"],
            "topic_key": current["topic_key"], "type": current["exercise_type"],
            "instruction": current["instruction"], "prompt": current["prompt"],
            "choices": json.loads(current["choices_json"]),
            "tokens": json.loads(current["tokens_json"]),
        }
    return payload


@app.get("/api/grammar/topics")
def list_grammar_topics(language: str) -> list[dict[str, Any]]:
    catalogue = grammar_catalogue(language)
    with vocabulary_database() as connection:
        rows = {
            row["topic_key"]: row for row in connection.execute(
                "SELECT * FROM grammar_reviews WHERE canonical_language = ?",
                (catalogue[0].language.value,),
            ).fetchall()
        }
    return [
        {
            "key": topic.key, "title": topic.title, "category": topic.category,
            "level": topic.level.value, "sequence": topic.sequence,
            "status": grammar_topic_status(
                introduced=topic.key in rows,
                schedule=grammar_schedule_from_row(rows.get(topic.key)),
            ).value,
        }
        for topic in catalogue
    ]


@app.post("/api/grammar/session")
def start_grammar_session(request: GrammarSessionRequest) -> dict[str, Any]:
    now = datetime.now(UTC)
    catalogue = grammar_catalogue(request.language)
    canonical_language = catalogue[0].language.value
    with vocabulary_database() as connection:
        existing = connection.execute(
            """
            SELECT id FROM grammar_sessions
            WHERE canonical_language = ? AND completed_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (canonical_language,),
        ).fetchone()
        if existing is not None:
            return grammar_session_payload(connection, existing["id"])
        selection = select_grammar_topics(connection, canonical_language, now)
        if selection is None:
            raise HTTPException(status_code=404, detail="No grammar topics are due")
        kind, topics = selection
        vocabulary = saved_grammar_vocabulary(connection, canonical_language)
    try:
        generated = generate_grammar_content(
            canonical_language, kind, topics, vocabulary
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Grammar session generation failed: {exc}"
        ) from exc
    with vocabulary_database() as connection:
        session_id = persist_grammar_session(
            connection, language=canonical_language, kind=kind,
            topics=topics, generated=generated, now=now,
        )
        return grammar_session_payload(connection, session_id)


@app.post("/api/grammar/session/{session_id}/topics/{topic_key}/summary")
def generate_grammar_topic_summary(
    session_id: str, topic_key: str
) -> dict[str, str]:
    with vocabulary_database() as connection:
        session = connection.execute(
            "SELECT * FROM grammar_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Grammar session not found")
        topic_keys = json.loads(session["topic_keys_json"])
        if topic_key not in topic_keys:
            raise HTTPException(
                status_code=404, detail="Grammar topic not found in session"
            )
        language = session["canonical_language"]
        cached = connection.execute(
            """
            SELECT summary FROM grammar_topic_summaries
            WHERE canonical_language = ? AND topic_key = ?
            """,
            (language, topic_key),
        ).fetchone()
        if cached is not None:
            return {"summary": cached["summary"]}
        summaries = json.loads(session["topic_summaries_json"])
        if summary := summaries.get(topic_key):
            connection.execute(
                """
                INSERT OR IGNORE INTO grammar_topic_summaries (
                    canonical_language, topic_key, summary, generated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (language, topic_key, summary, session["created_at"]),
            )
            return {"summary": summary}
        catalogue = {
            topic.key: topic for topic in grammar_catalogue(language)
        }
        topic = catalogue[topic_key]

    try:
        content = anthropic_structured_model_response(
            "grammar topic summary",
            messages=grammar_topic_summary_messages(
                language=language,
                title=topic.title,
                category=topic.category,
                example=topic.example,
            ),
            response_model=GrammarTopicSummary,
            max_output_tokens=400,
            effort="low",
        )
        generated = GrammarTopicSummary.model_validate_json(content).summary
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Grammar summary generation failed: {exc}"
        ) from exc

    with vocabulary_database() as connection:
        session = connection.execute(
            "SELECT topic_summaries_json FROM grammar_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Grammar session not found")
        connection.execute(
            """
            INSERT OR IGNORE INTO grammar_topic_summaries (
                canonical_language, topic_key, summary, generated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (language, topic_key, generated, datetime.now(UTC).isoformat()),
        )
        cached = connection.execute(
            """
            SELECT summary FROM grammar_topic_summaries
            WHERE canonical_language = ? AND topic_key = ?
            """,
            (language, topic_key),
        ).fetchone()
        summary = cached["summary"]
        summaries = json.loads(session["topic_summaries_json"])
        summaries[topic_key] = summary
        connection.execute(
            "UPDATE grammar_sessions SET topic_summaries_json = ? WHERE id = ?",
            (json.dumps(summaries, ensure_ascii=False), session_id),
        )
        return {"summary": summary}


@app.post("/api/grammar/session/{session_id}/exercises/{exercise_id}/answer")
def answer_grammar_exercise(
    session_id: str, exercise_id: str, request: GrammarAnswerRequest
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with vocabulary_database() as connection:
        row = connection.execute(
            """
            SELECT e.*, s.canonical_language, s.completed_at
            FROM grammar_exercises e JOIN grammar_sessions s ON s.id = e.session_id
            WHERE e.id = ? AND e.session_id = ?
            """,
            (exercise_id, session_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Grammar exercise not found")
        if row["completed_at"] is not None:
            raise HTTPException(status_code=409, detail="Grammar session is complete")
        prior = connection.execute(
            "SELECT * FROM grammar_exercise_answers WHERE exercise_id = ?",
            (exercise_id,),
        ).fetchone()
        if prior is not None:
            return {
                "correct": bool(prior["correct"]), "feedback": prior["feedback"],
                "reference_answer": row["reference_answer"],
                "explanation": row["explanation"], "session_complete": False,
            }
        exercise_type = GrammarExerciseType(row["exercise_type"])
        correct = deterministic_grammar_grade(
            exercise_type, request.answer,
            json.loads(row["accepted_answers_json"]), row["reference_answer"],
        )
        language = row["canonical_language"]
        grading_data = dict(row)
    if correct is None:
        try:
            content = anthropic_structured_model_response(
                "grammar answer grading",
                messages=grammar_grading_messages(
                    language=language, prompt=grading_data["prompt"],
                    instruction=grading_data["instruction"], answer=request.answer,
                    reference_answer=grading_data["reference_answer"],
                    rubric=grading_data["grading_rubric"],
                ),
                response_model=GrammarGrade,
                max_output_tokens=250,
            )
            grade = GrammarGrade.model_validate_json(content)
            correct, feedback = grade.correct, grade.feedback
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Grammar grading failed: {exc}") from exc
    else:
        feedback = "Correct." if correct else "Review the target form and compare your answer."
    with vocabulary_database() as connection:
        connection.execute(
            "INSERT INTO grammar_exercise_answers VALUES (?, ?, ?, ?, ?)",
            (exercise_id, request.answer, int(correct), feedback, now.isoformat()),
        )
        remaining = connection.execute(
            """
            SELECT COUNT(*) FROM grammar_exercises e
            LEFT JOIN grammar_exercise_answers a ON a.exercise_id = e.id
            WHERE e.session_id = ? AND a.exercise_id IS NULL
            """,
            (session_id,),
        ).fetchone()[0]
        complete = remaining == 0
        if complete:
            finish_grammar_session(connection, session_id, now)
        return {
            "correct": bool(correct), "feedback": feedback,
            "reference_answer": grading_data["reference_answer"],
            "explanation": grading_data["explanation"],
            "session_complete": complete,
        }


def finish_grammar_session(
    connection: sqlite3.Connection, session_id: str, now: datetime
) -> None:
    session_row = connection.execute(
        "SELECT * FROM grammar_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    results = connection.execute(
        """
        SELECT e.topic_key, COUNT(*) attempted, SUM(a.correct) correct
        FROM grammar_exercises e JOIN grammar_exercise_answers a ON a.exercise_id = e.id
        WHERE e.session_id = ? GROUP BY e.topic_key
        """,
        (session_id,),
    ).fetchall()
    for result in results:
        previous = connection.execute(
            "SELECT * FROM grammar_reviews WHERE canonical_language = ? AND topic_key = ?",
            (session_row["canonical_language"], result["topic_key"]),
        ).fetchone()
        updated = schedule_grammar_review(
            grammar_schedule_from_row(previous),
            correct=result["correct"] / result["attempted"] >= 2 / 3,
            reviewed_at=now,
        )
        connection.execute(
            """
            INSERT INTO grammar_reviews (
                canonical_language, topic_key, introduced_at, last_reviewed_at,
                next_review_at, repetitions, lapses, consecutive_correct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_language, topic_key) DO UPDATE SET
                last_reviewed_at=excluded.last_reviewed_at,
                next_review_at=excluded.next_review_at,
                repetitions=excluded.repetitions, lapses=excluded.lapses,
                consecutive_correct=excluded.consecutive_correct
            """,
            (
                session_row["canonical_language"], result["topic_key"], now.isoformat(),
                updated.last_reviewed_at.isoformat(), updated.next_review_at.isoformat(),
                updated.repetitions, updated.lapses, updated.consecutive_correct,
            ),
        )
    connection.execute(
        "UPDATE grammar_sessions SET completed_at = ? WHERE id = ?",
        (now.isoformat(), session_id),
    )


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
        items = [
            vocabulary_item(
                row,
                vocabulary_synonyms(connection, row["id"]),
            )
            for row in rows
        ]
    return items


@app.post("/api/vocabulary", response_model=VocabularySaveResult)
def save_vocabulary(
    request: VocabularyCreate,
    background_tasks: BackgroundTasks,
) -> VocabularySaveResult:
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
                target_language, context, document_key, noun_gender, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                request.noun_gender,
                saved_at,
            ),
        )
        created = cursor.rowcount == 1
        if request.noun_gender is not None:
            connection.execute(
                f"UPDATE {table_name} SET noun_gender = ? WHERE canonical_source = ?",
                (request.noun_gender, canonical_source),
            )
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
        if created:
            seen = {canonical_source}
            for position, synonym in enumerate(request.synonyms):
                canonical_synonym = canonicalize(synonym.text)
                if canonical_synonym in seen:
                    continue
                seen.add(canonical_synonym)
                connection.execute(
                    """
                    INSERT INTO vocabulary_synonyms (
                        vocabulary_item_id, text, canonical_text,
                        noun_gender, position
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        synonym.text,
                        canonical_synonym,
                        synonym.noun_gender,
                        position,
                    ),
                )
        connector_sentence_id = index_saved_sentence(
            connection,
            vocabulary_item_id=row["id"],
            source_language=request.source_language,
            context=request.context,
            document_key=request.document_key,
            saved_at=saved_at,
        )
        item = vocabulary_item(
            row,
            vocabulary_synonyms(connection, row["id"]),
        )
    if connector_sentence_id is not None:
        background_tasks.add_task(enrich_connector_sentence, connector_sentence_id)
    return VocabularySaveResult(item=item, created=created)


@app.delete("/api/vocabulary/{item_id}", status_code=204)
def delete_vocabulary(item_id: str) -> Response:
    with vocabulary_database() as connection:
        linked_sentence_ids = [
            row["sentence_id"]
            for row in connection.execute(
                """
                SELECT sentence_id FROM vocabulary_sentence_links
                WHERE vocabulary_item_id = ?
                """,
                (item_id,),
            ).fetchall()
        ]
        deleted = False
        for registered in registered_language_tables(connection):
            cursor = connection.execute(
                f"DELETE FROM {registered['table_name']} WHERE id = ?", (item_id,)
            )
            if cursor.rowcount:
                deleted = True
                break
        if deleted:
            connection.execute(
                "DELETE FROM vocabulary_synonyms WHERE vocabulary_item_id = ?",
                (item_id,),
            )
            connection.execute(
                "DELETE FROM vocabulary_sentence_links WHERE vocabulary_item_id = ?",
                (item_id,),
            )
            for sentence_id in linked_sentence_ids:
                still_linked = connection.execute(
                    """
                    SELECT 1 FROM vocabulary_sentence_links
                    WHERE sentence_id = ? LIMIT 1
                    """,
                    (sentence_id,),
                ).fetchone()
                if still_linked is not None:
                    continue
                connection.execute(
                    "DELETE FROM connector_occurrences WHERE sentence_id = ?",
                    (sentence_id,),
                )
                connection.execute(
                    "DELETE FROM connector_sentences WHERE id = ?",
                    (sentence_id,),
                )
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved vocabulary item not found")
    return Response(status_code=204)


@app.get("/api/revision/session", response_model=RevisionSession)
def revision_session(
    background_tasks: BackgroundTasks,
    language: str | None = None,
    limit: int = 40,
    supports_letter_tiles: bool = False,
) -> RevisionSession:
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
        synonym_round = synonym_matching_round(connection, rows)
        connector_cards, connector_due_count = connector_revision_cards(
            connection,
            language=language,
            now=now,
        )
        canonical_language = canonicalize(language) if language is not None else None
        pending_connector_sentences = connection.execute(
            """
            SELECT DISTINCT o.sentence_id
            FROM connector_occurrences o
            JOIN connector_sentences s ON s.id = o.sentence_id
            WHERE o.contextual_gloss IS NULL
              AND (? IS NULL OR s.canonical_source_language = ?)
            LIMIT ?
            """,
            (
                canonical_language,
                canonical_language,
                CONNECTOR_REVISION_LIMIT,
            ),
        ).fetchall()

    due_count = sum(is_due(schedule_state(row), at=now) for row in rows)
    selected = select_session_rows(rows, now=now, limit=limit)
    for pending in pending_connector_sentences:
        background_tasks.add_task(enrich_connector_sentence, pending["sentence_id"])
    return RevisionSession(
        cards=[
            revision_card(
                row,
                rows,
                supports_letter_tiles=supports_letter_tiles,
            )
            for row in selected
        ],
        due_count=due_count,
        synonym_round=synonym_round,
        connector_cards=connector_cards,
        connector_due_count=connector_due_count,
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
        correct = (
            not request.hint_used
            and canonicalize(request.selected_answer) == canonicalize(correct_answer)
        )
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
        stored_synonyms = vocabulary_synonyms(connection, item_id)

    return RevisionAnswerResult(
        correct=correct,
        correct_answer=correct_answer,
        category=revision_category(updated),
        item=vocabulary_item(updated_row, stored_synonyms),
    )


@app.post(
    "/api/revision/connectors/{occurrence_id}/answer",
    response_model=ConnectorRevisionAnswerResult,
)
def answer_connector_revision(
    occurrence_id: str,
    request: ConnectorRevisionAnswer,
) -> ConnectorRevisionAnswerResult:
    reviewed_at = datetime.now(UTC)
    with vocabulary_database() as connection:
        row = connection.execute(
            """
            SELECT o.connector_key, s.canonical_source_language,
                r.last_reviewed_at, r.next_review_at,
                COALESCE(r.repetitions, 0) AS repetitions,
                COALESCE(r.lapses, 0) AS lapses,
                COALESCE(r.consecutive_correct, 0) AS consecutive_correct
            FROM connector_occurrences o
            JOIN connector_sentences s ON s.id = o.sentence_id
            LEFT JOIN connector_reviews r
              ON r.canonical_source_language = s.canonical_source_language
             AND r.connector_key = o.connector_key
            WHERE o.id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Saved connector occurrence not found",
            )
        correct_answer = row["connector_key"]
        correct = canonicalize(request.selected_answer) == canonicalize(correct_answer)
        updated = schedule_review(
            schedule_state(row), correct=correct, reviewed_at=reviewed_at
        )
        connection.execute(
            """
            INSERT INTO connector_reviews (
                canonical_source_language, connector_key,
                last_reviewed_at, next_review_at, repetitions,
                lapses, consecutive_correct
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_source_language, connector_key) DO UPDATE SET
                last_reviewed_at = excluded.last_reviewed_at,
                next_review_at = excluded.next_review_at,
                repetitions = excluded.repetitions,
                lapses = excluded.lapses,
                consecutive_correct = excluded.consecutive_correct
            """,
            (
                row["canonical_source_language"],
                correct_answer,
                updated.last_reviewed_at.isoformat(),
                updated.next_review_at.isoformat(),
                updated.repetitions,
                updated.lapses,
                updated.consecutive_correct,
            ),
        )
    return ConnectorRevisionAnswerResult(
        correct=correct,
        correct_answer=correct_answer,
        category=revision_category(updated),
    )


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def cached_verb_lemma_decision(
    model: str,
    analysis: WordAnalysis,
    source_language: str,
    context: str,
) -> VerbLemmaDecision:
    content = structured_model_response(
        "verb lemma classification",
        model=model,
        messages=verb_lemma_messages(analysis, source_language, context),
        schema=VerbLemmaDecision.model_json_schema(),
        schema_name="verb_lemma_decision",
        max_output_tokens=96,
    )
    return VerbLemmaDecision.model_validate_json(content)


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def cached_source_noun_grammar(
    model: str,
    lemma: str,
    source_language: str,
) -> SourceNounGrammar:
    content = structured_model_response(
        "source noun grammar",
        model=model,
        messages=source_article_messages(lemma, source_language),
        schema=source_article_schema(source_language),
        schema_name="source_noun_grammar",
        max_output_tokens=32,
    )
    return SourceNounGrammar.model_validate_json(content)


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def cached_model_translation(
    model: str,
    source: str,
    source_language: str,
    target_language: str,
    context: str,
    is_word: bool,
    word_analysis: WordAnalysis | None,
) -> TranslatedText | NounTranslation:
    is_noun = word_analysis is not None and word_analysis.pos in NOUN_POS
    response_model = NounTranslation if is_noun else TranslatedText
    response_schema = (
        noun_translation_schema(target_language)
        if is_noun
        else response_model.model_json_schema()
    )
    content = structured_model_response(
        "translation",
        model=model,
        messages=translation_messages(
            source=source,
            source_language=source_language,
            target_language=target_language,
            context=context,
            is_word=is_word,
            word_analysis=word_analysis,
        ),
        schema=response_schema,
        schema_name="noun_translation" if is_noun else "translation",
        max_output_tokens=128,
    )
    return response_model.model_validate_json(content)


@lru_cache(maxsize=RUNTIME_CACHE_SIZE)
def cached_ranked_synonyms(
    model: str,
    source: str,
    source_language: str,
    context: str,
    part_of_speech: str,
    candidates: tuple[str, ...],
) -> tuple[str, ...]:
    content = structured_model_response(
        "synonym ranking",
        model=model,
        messages=synonym_ranking_messages(
            source=source,
            source_language=source_language,
            context=context,
            part_of_speech=part_of_speech,
            candidates=candidates,
        ),
        schema=RankedSynonyms.model_json_schema(),
        schema_name="ranked_synonyms",
        max_output_tokens=64,
    )
    ranked = RankedSynonyms.model_validate_json(content).synonyms
    allowed = {canonicalize(candidate): candidate for candidate in candidates}
    filtered: list[str] = []
    seen: set[str] = set()
    for candidate in ranked:
        key = canonicalize(candidate)
        if key in allowed and key not in seen:
            filtered.append(allowed[key])
            seen.add(key)
    return tuple(filtered)


def contextual_synonyms(
    model: str,
    analysis: WordAnalysis,
    source_language: str,
    context: str,
) -> list[SynonymValue]:
    candidate_set = dictionary_synonym_candidates(
        analysis.lemma, source_language, analysis.pos
    )
    candidates = frequency_ranked_synonym_candidates(
        analysis.lemma,
        source_language,
        candidate_set.values,
    )
    if candidate_set.used_pos_fallback:
        candidates = part_of_speech_filtered_synonym_candidates(
            source_language,
            analysis.pos,
            candidates,
        )
    if not candidates:
        ranked = ()
    elif candidate_set.sense_count > 1:
        ranked = cached_ranked_synonyms(
            model,
            analysis.lemma,
            source_language,
            context,
            analysis.pos,
            candidates,
        )
    else:
        ranked = candidates
    ranked = ranked[:MAX_SYNONYMS]
    synonym_grammars: tuple[SourceNounGrammar | None, ...] = tuple(
        None for _ in ranked
    )
    if analysis.pos in NOUN_POS:
        synonym_grammars = local_noun_grammars(tuple(ranked), source_language)
    return [
        SynonymValue(
            text=(
                article_and_lemma(grammar.article, synonym)
                if grammar is not None
                else synonym
            ),
            noun_gender=(
                grammar.gender
                if grammar is not None and grammar.gender != "none"
                else None
            ),
        )
        for synonym, grammar in zip(ranked, synonym_grammars, strict=True)
    ]


@app.post("/api/detect-language", response_model=LanguageDetectionResult)
def detect_language(request: LanguageDetectionRequest) -> LanguageDetectionResult:
    try:
        return LanguageDetectionResult(
            detected_language=detect_document_language(request.text)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local language detection failed: {exc}",
        ) from exc


@app.post(
    "/api/prepare-language",
    response_model=LanguagePreparationResult,
    status_code=202,
)
def prepare_language(
    request: LanguagePreparationRequest,
) -> LanguagePreparationResult:
    try:
        status = start_stanza_preparation(request.source_language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    start_wordnet_preparation(request.source_language)
    return LanguagePreparationResult(status=status)


@app.post("/api/synonyms", response_model=SynonymResult)
def synonyms(request: SynonymRequest) -> SynonymResult:
    if request.source_language.casefold() not in WORDNET_LEXICONS:
        raise HTTPException(
            status_code=422,
            detail="Synonyms are currently available only for German and Spanish",
        )
    if len(request.text.split()) != 1:
        raise HTTPException(
            status_code=422,
            detail="Select a single word to look up synonyms",
        )
    try:
        analysis = analyze_word_in_context(
            request.text,
            request.source_language,
            request.context,
            request.context_offset,
        )
        source = analysis.lemma
        source_grammar = None
        if analysis.pos in NOUN_POS:
            source_grammar = grammar_from_gender(
                source, request.source_language, analysis.noun_gender
            )
            if source_grammar is None:
                source_grammar = local_noun_grammars(
                    (source,), request.source_language
                )[0]
        normalized_source = (
            article_and_lemma(source_grammar.article, source)
            if source_grammar is not None
            else source
        )
        return SynonymResult(
            detected_language=request.source_language,
            normalized_source=normalized_source,
            noun_gender=(
                source_grammar.gender
                if source_grammar is not None and source_grammar.gender != "none"
                else None
            ),
            synonyms=contextual_synonyms(
                translation_model(),
                analysis,
                request.source_language,
                request.context,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local synonym lookup failed: {exc}",
        ) from exc


@app.post(
    "/api/translate",
    response_model=TranslationResult,
    response_model_exclude_none=True,
)
def translate(request: TranslationRequest) -> TranslationResult:
    synonym_future = None
    try:
        model = translation_model()
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
                word_analysis = apply_verb_lemma_decision(
                    word_analysis,
                    cached_verb_lemma_decision(
                        model,
                        word_analysis,
                        request.source_language,
                        request.context,
                    ),
                )

        if (
            request.include_synonyms
            and is_single_word
            and word_analysis is not None
            and request.source_language.casefold() in WORDNET_LEXICONS
        ):
            synonym_future = MODEL_CALL_EXECUTOR.submit(
                contextual_synonyms,
                model,
                word_analysis,
                request.source_language,
                request.context,
            )

        def request_translation(
            context: str,
        ) -> TranslatedText | NounTranslation:
            return cached_model_translation(
                model,
                source_text,
                request.source_language,
                request.target_language,
                context,
                is_single_word,
                word_analysis,
            )

        source_article = ""
        noun_gender = None
        if word_analysis is not None and word_analysis.pos in NOUN_POS:
            noun_grammar = grammar_from_gender(
                word_analysis.lemma,
                request.source_language,
                word_analysis.noun_gender,
            )
            if noun_grammar is not None:
                # Stanza already produced this gender while locating the source
                # word, so supported languages need no second model request.
                translated = request_translation(request.context)
            else:
                # Retain the model fallback for languages whose Stanza model
                # does not expose noun gender.
                openai_client()
                grammar_future = MODEL_CALL_EXECUTOR.submit(
                    cached_source_noun_grammar,
                    model, word_analysis.lemma, request.source_language,
                )
                translation_future = MODEL_CALL_EXECUTOR.submit(
                    request_translation, request.context
                )
                try:
                    noun_grammar = grammar_future.result()
                    translated = translation_future.result()
                except Exception:
                    grammar_future.cancel()
                    translation_future.cancel()
                    raise
            source_article = normalized_article(
                noun_grammar.article, request.source_language
            )
            if noun_grammar.gender != "none":
                noun_gender = noun_grammar.gender
        else:
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
                normalized_source = article_and_lemma(
                    source_article, word_analysis.lemma
                )
                target_lemma = normalize_source(
                    translated.target_lemma, request.target_language
                )
                target_grammar = local_noun_grammars(
                    (target_lemma,), request.target_language
                )[0]
                target_article = normalized_article(
                    (
                        target_grammar.article
                        if target_grammar is not None
                        else translated.target_definite_article
                    ),
                    request.target_language,
                )
                translation = article_and_lemma(target_article, target_lemma)
            else:
                normalized_source = word_analysis.lemma

        synonym_values = None
        if synonym_future is not None:
            try:
                synonym_values = synonym_future.result()
            except Exception:
                logger.exception(
                    "Synonym lookup failed during translation for %s",
                    request.source_language,
                )
                synonym_values = []

        original_source = source_text
        if word_analysis is not None and len(word_analysis.token.split()) > 1:
            original_source = word_analysis.token

        return TranslationResult(
            detected_language=request.source_language,
            is_word=is_term,
            original_source=original_source,
            normalized_source=normalized_source,
            translation=translation,
            noun_gender=noun_gender,
            synonyms=synonym_values,
        )

    except Exception as exc:
        if synonym_future is not None:
            synonym_future.cancel()
        raise HTTPException(
            status_code=502,
            detail=f"Translation service failed: {exc}",
        ) from exc
