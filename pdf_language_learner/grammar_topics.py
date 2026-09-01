"""Shared types and validation for language-specific grammar catalogues."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Iterable


class GrammarLanguage(StrEnum):
    GERMAN = "german"
    SPANISH = "spanish"


class GrammarLevel(StrEnum):
    A1_B1 = "A1-B1"
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    B2_C1 = "B2-C1"
    C1 = "C1"


@dataclass(frozen=True)
class GrammarTopic:
    key: str
    language: GrammarLanguage
    book: str
    level: GrammarLevel
    category: str
    title: str
    example: str
    source_group: str | None = None
    sequence: int = 0


def ordered_grammar_topics(
    language: GrammarLanguage,
    topics: Iterable[GrammarTopic],
) -> tuple[GrammarTopic, ...]:
    """Validate a catalogue and assign its stable, one-based teaching order."""

    ordered = tuple(topics)
    keys = [topic.key for topic in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Duplicate {language} grammar topic key")
    if any(topic.language is not language for topic in ordered):
        raise ValueError(f"Mixed languages in {language} grammar catalogue")
    return tuple(
        replace(topic, sequence=position)
        for position, topic in enumerate(ordered, start=1)
    )
