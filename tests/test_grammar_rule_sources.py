from pathlib import Path

from pdf_language_learner.german_grammar_catalogue import GRAMMAR_TOPICS
from pdf_language_learner.grammar_rule_sources import (
    grammar_rule_prompt_material,
    grammar_rule_sources,
    parse_grammar_rule_file,
)
from pdf_language_learner.spanish_grammar_catalogue import SPANISH_GRAMMAR_TOPICS


def test_completed_authored_rule_inventory_matches_catalogues() -> None:
    german = grammar_rule_sources("German")
    spanish = grammar_rule_sources("SPANISH")

    assert "a1b1_nebensaetze_weil_wenn_dass" in german
    assert "a1b1_praepositionaladverbien_pronomen" in german
    assert "es_a1_u1_regular_ar_verbs" in spanish
    assert "es_a1_u6_location_expressions" in spanish
    assert set(german) <= {topic.key for topic in GRAMMAR_TOPICS}
    assert set(spanish) <= {topic.key for topic in SPANISH_GRAMMAR_TOPICS}


def test_parser_ignores_incomplete_sections(tmp_path: Path) -> None:
    path = tmp_path / "rules.md"
    path.write_text(
        """# Rules
<!-- topic: complete -->
## Complete

An explanation.

<!-- topic: incomplete -->
## Incomplete

<!-- TODO: Enter this later. -->
""",
        encoding="utf-8",
    )

    sources = parse_grammar_rule_file(path)
    assert [source.topic_key for source in sources] == ["complete"]
    assert sources[0].markdown == "## Complete\n\nAn explanation."


def test_missing_topic_gets_exemplars_but_never_todo_text() -> None:
    material = grammar_rule_prompt_material(
        "spanish",
        [{"key": "es_a1_u6_use_of_a_and_en"}],
    )

    assert "AUTHORED SOURCES FOR SELECTED TOPICS" not in material
    assert "STYLE EXEMPLARS FOR TOPICS WITHOUT AN AUTHORED SOURCE" in material
    assert "TODO" not in material
