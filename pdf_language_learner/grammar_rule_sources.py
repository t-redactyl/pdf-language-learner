"""Load optional, human-authored grammar explanations from Markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


GRAMMAR_RULE_ROOT = Path(__file__).resolve().parent.parent / "grammar_rules"
TOPIC_MARKER = re.compile(r"<!--\s*topic:\s*([^\s]+)\s*-->")
TODO_MARKER = "<!-- TODO:"


@dataclass(frozen=True)
class GrammarRuleSource:
    topic_key: str
    markdown: str
    path: Path


def parse_grammar_rule_file(path: Path) -> list[GrammarRuleSource]:
    """Return completed topic sections, excluding the marker comments."""

    text = path.read_text(encoding="utf-8")
    markers = list(TOPIC_MARKER.finditer(text))
    sources = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        markdown = text[marker.end():end].strip()
        if not markdown or TODO_MARKER in markdown:
            continue
        sources.append(
            GrammarRuleSource(
                topic_key=marker.group(1), markdown=markdown, path=path,
            )
        )
    return sources


def grammar_rule_sources(language: str) -> dict[str, GrammarRuleSource]:
    """Load all completed authored explanations for one supported language."""

    language_key = language.strip().casefold()
    rule_directory = GRAMMAR_RULE_ROOT / language_key
    if language_key not in {"german", "spanish"} or not rule_directory.is_dir():
        return {}
    sources: dict[str, GrammarRuleSource] = {}
    for path in sorted(rule_directory.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        for source in parse_grammar_rule_file(path):
            if source.topic_key in sources:
                raise ValueError(f"duplicate grammar rule source for {source.topic_key}")
            sources[source.topic_key] = source
    return sources


def _topic_family(topic_key: str) -> str:
    parts = topic_key.split("_")
    return "_".join(parts[:2]) if topic_key.startswith("es_") else parts[0]


def grammar_rule_prompt_material(
    language: str,
    topics: Sequence[Mapping[str, object]],
    *,
    exemplar_limit: int = 2,
) -> str:
    """Format selected authored sources and compact exemplars for missing topics."""

    sources = grammar_rule_sources(language)
    selected_keys = [str(topic["key"]) for topic in topics]
    selected_sources = [sources[key] for key in selected_keys if key in sources]
    missing_keys = [key for key in selected_keys if key not in sources]

    sections = []
    if selected_sources:
        sections.append(
            "AUTHORED SOURCES FOR SELECTED TOPICS\n"
            + "\n\n".join(
                f"[topic: {source.topic_key}]\n{source.markdown}"
                for source in selected_sources
            )
        )

    if missing_keys and exemplar_limit:
        missing_families = {_topic_family(key) for key in missing_keys}
        candidates = [
            source for key, source in sources.items() if key not in selected_keys
        ]
        candidates.sort(key=lambda source: (
            _topic_family(source.topic_key) not in missing_families,
            len(source.markdown),
            source.topic_key,
        ))
        exemplars = candidates[:exemplar_limit]
        if exemplars:
            sections.append(
                "STYLE EXEMPLARS FOR TOPICS WITHOUT AN AUTHORED SOURCE\n"
                + "\n\n".join(
                    f"[example topic: {source.topic_key}]\n{source.markdown}"
                    for source in exemplars
                )
            )

    return "\n\n".join(sections)
