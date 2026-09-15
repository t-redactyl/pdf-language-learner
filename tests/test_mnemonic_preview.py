import sqlite3
from datetime import UTC, datetime

import pytest
import pdf_language_learner.app as app_module

from pdf_language_learner.app import (
    MnemonicComponent,
    VocabularyMnemonic,
    VocabularyMnemonicAnalysis,
    VocabularyMnemonicCandidates,
    VocabularyMnemonicGeneration,
    VocabularyMnemonicQualityReview,
)
from pdf_language_learner.mnemonic_preview import (
    MnemonicPreviewItem,
    MnemonicPreviewResult,
    direct_preview_item,
    load_saved_vocabulary,
    main,
    prompt_fingerprint,
    render_preview_report,
    write_preview_report,
)


def preview_database(tmp_path):
    path = tmp_path / "margin.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE vocabulary_languages (
                canonical_language TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                table_name TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            "INSERT INTO vocabulary_languages VALUES "
            "('german', 'German', 'vocabulary_german')"
        )
        connection.execute(
            """
            CREATE TABLE vocabulary_german (
                id TEXT PRIMARY KEY,
                normalized_source TEXT NOT NULL,
                translation TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                context TEXT NOT NULL,
                saved_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO vocabulary_german VALUES (?, ?, ?, 'German', 'English', ?, ?)",
            [
                ("1", "Handschuh", "glove", "Ein <Handschuh>.", "2026-09-15T12:00:00Z"),
                ("2", "aufmachen", "to open", "Mach das Fenster auf.", "2026-09-15T13:00:00Z"),
            ],
        )
    return path


def item() -> MnemonicPreviewItem:
    return MnemonicPreviewItem(
        item_id="word-1",
        source="Handschuh",
        translation="glove",
        source_language="German",
        target_language="English",
        context="Ein <Handschuh> schützt die Hand.",
    )


def test_direct_preview_item_accepts_unsaved_vocabulary() -> None:
    direct = direct_preview_item(
        word="  aufmachen ",
        translation=" to open ",
        source_language=" German ",
        context=" Mach das Fenster auf. ",
    )

    assert direct.source == "aufmachen"
    assert direct.translation == "to open"
    assert direct.source_language == "German"
    assert direct.target_language == "English"
    assert direct.context == "Mach das Fenster auf."
    assert direct.item_id.startswith("direct-")


def generation() -> VocabularyMnemonicGeneration:
    components = [
        MnemonicComponent(form="Hand", meaning="hand", role="compound_part"),
        MnemonicComponent(form="Schuh", meaning="shoe", role="compound_part"),
    ]
    candidates = VocabularyMnemonicCandidates(
        candidates=[
            VocabularyMnemonic(
                strategy="conceptual_bridge",
                components=components,
                hook="A shoe for a hand.",
                explanation="Picture a tiny shoe covering your hand: a glove.",
            ),
            VocabularyMnemonic(
                strategy="conceptual_bridge",
                components=components,
                hook="Hand + Schuh makes Handschuh.",
                explanation="The literal hand-shoe performs the job of a glove.",
            ),
        ]
    )
    return VocabularyMnemonicGeneration(
        analysis=VocabularyMnemonicAnalysis(
            strategy="conceptual_bridge",
            word_structure="compound_noun",
            components=components,
            sound_cue=None,
            analysis_note="A transparent modern compound.",
        ),
        candidates=candidates,
        quality_review=VocabularyMnemonicQualityReview(
            approved=True,
            selected_index=0,
            findings=["Accurate and concrete."],
        ),
    )


def test_load_saved_vocabulary_selects_words_without_writing(tmp_path) -> None:
    database = preview_database(tmp_path)

    selected = load_saved_vocabulary(
        database,
        language="GERMAN",
        words=["Handschuh"],
    )

    assert [(entry.source, entry.translation) for entry in selected] == [
        ("Handschuh", "glove")
    ]
    with pytest.raises(ValueError, match="unknown saved word"):
        load_saved_vocabulary(database, language="German", words=["missing"])


def test_prompt_fingerprint_changes_with_models_and_content_version() -> None:
    base = prompt_fingerprint(
        item(), generator_model="generator", judge_model="judge", content_version=2
    )

    assert base != prompt_fingerprint(
        item(), generator_model="other", judge_model="judge", content_version=2
    )
    assert base != prompt_fingerprint(
        item(), generator_model="generator", judge_model="judge", content_version=3
    )


def test_preview_report_shows_every_pipeline_stage_and_escapes_content(tmp_path) -> None:
    created_at = datetime(2026, 9, 15, 12, tzinfo=UTC)
    result = MnemonicPreviewResult(
        item=item(),
        sample=1,
        generated_at=created_at,
        prompt_sha256="a" * 64,
        generation=generation(),
        usage={
            "vocabulary mnemonic analysis [generator]": {
                "calls": 1,
                "input_tokens": 100,
                "output_tokens": 50,
                "reasoning_tokens": 20,
            },
            "vocabulary mnemonic quality review [judge]": {
                "calls": 1,
                "input_tokens": 200,
                "output_tokens": 80,
                "reasoning_tokens": 30,
            },
        },
    )

    report = render_preview_report(
        language="German",
        generator_model="generator",
        judge_model="judge",
        report_id="report-1",
        created_at=created_at,
        results=[result],
        expected_results=2,
    )

    assert "1. Linguistic analysis" in report
    assert "2. Strategy-specific candidates" in report
    assert "3. Independent judge" in report
    assert "Approved candidate 1" in report
    assert "2 model calls" in report
    assert "300 input tokens" in report
    assert "&lt;Handschuh&gt;" in report
    assert "localStorage.setItem" in report
    assert "Raw pipeline output" in report
    destination = tmp_path / "reports" / "mnemonics.html"
    write_preview_report(destination, report)
    assert destination.read_text(encoding="utf-8") == report
    assert not destination.with_suffix(".html.tmp").exists()


def test_list_words_cli_does_not_require_generation_selection(tmp_path, capsys) -> None:
    database = preview_database(tmp_path)

    assert main([
        "--database", str(database), "--language", "German", "--list-words"
    ]) == 0

    output = capsys.readouterr().out
    assert "aufmachen\tto open" in output
    assert "Handschuh\tglove" in output


def test_direct_cli_bypasses_the_database(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "direct.html"
    monkeypatch.setattr(app_module, "mnemonic_model", lambda: "generator")
    monkeypatch.setattr(app_module, "mnemonic_judge_model", lambda: "judge")
    monkeypatch.setattr(
        app_module,
        "generate_vocabulary_mnemonic",
        lambda row: generation(),
    )

    assert main([
        "--database", str(tmp_path / "missing.db"),
        "--language", "German",
        "--word", "aufmachen",
        "--translation", "to open",
        "--context", "Mach das Fenster auf.",
        "--output", str(destination),
    ]) == 0

    report = destination.read_text(encoding="utf-8")
    assert "aufmachen" in report
    assert "to open" in report
    assert "Mach das Fenster auf." in report
