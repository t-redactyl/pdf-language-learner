"""Batch-preview support for reviewing generated vocabulary mnemonics."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


REVIEW_CRITERIA = (
    ("accurate", "Morphology and meanings are accurate"),
    ("parts", "Prefix, stem, or compound parts are useful"),
    ("bridge", "The aid connects the form to the intended meaning"),
    ("memorable", "The image or explanation is memorable"),
    ("concise", "The aid is concise enough to recall quickly"),
)


@dataclass(frozen=True)
class MnemonicPreviewItem:
    item_id: str
    source: str
    translation: str
    source_language: str
    target_language: str
    context: str

    def generation_input(self) -> dict[str, str]:
        return {
            "normalized_source": self.source,
            "translation": self.translation,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "context": self.context,
        }


@dataclass(frozen=True)
class MnemonicPreviewResult:
    item: MnemonicPreviewItem
    sample: int
    generated_at: datetime
    prompt_sha256: str
    generation: Any | None = None
    error: str | None = None
    usage: dict[str, dict[str, int]] = field(default_factory=dict)


def direct_preview_item(
    *,
    word: str,
    translation: str,
    source_language: str,
    target_language: str = "English",
    context: str = "",
) -> MnemonicPreviewItem:
    values = {
        "word": word.strip(),
        "translation": translation.strip(),
        "source_language": source_language.strip(),
        "target_language": target_language.strip(),
        "context": context.strip(),
    }
    for name in ("word", "translation", "source_language", "target_language"):
        if not values[name]:
            raise ValueError(f"{name.replace('_', ' ')} must not be blank")
    fingerprint = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:20]
    return MnemonicPreviewItem(
        item_id=f"direct-{fingerprint}",
        source=values["word"],
        translation=values["translation"],
        source_language=values["source_language"],
        target_language=values["target_language"],
        context=values["context"],
    )


def _canonicalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def load_saved_vocabulary(
    database: Path,
    *,
    language: str,
    words: Sequence[str] = (),
    limit: int | None = None,
) -> list[MnemonicPreviewItem]:
    """Read preview items without migrating or updating the vocabulary database."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if not database.is_file():
        raise ValueError(f"vocabulary database does not exist: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        registered = connection.execute(
            "SELECT table_name FROM vocabulary_languages WHERE canonical_language = ?",
            (_canonicalize(language),),
        ).fetchone()
        if registered is None:
            return []
        table_name = registered["table_name"]
        if not re.fullmatch(r"vocabulary_[a-z0-9_]+", table_name):
            raise ValueError("the registered vocabulary table name is invalid")
        rows = connection.execute(
            f"SELECT id, normalized_source, translation, source_language, "
            f"target_language, context FROM {table_name} ORDER BY saved_at DESC"
        ).fetchall()
    finally:
        connection.close()

    requested = {_canonicalize(word): word for word in words}
    if requested:
        available = {_canonicalize(row["normalized_source"]) for row in rows}
        unknown = [original for key, original in requested.items() if key not in available]
        if unknown:
            raise ValueError(f"unknown saved word(s): {', '.join(unknown)}")
        rows = [
            row for row in rows
            if _canonicalize(row["normalized_source"]) in requested
        ]
    if limit is not None:
        rows = rows[:limit]
    return [
        MnemonicPreviewItem(
            item_id=row["id"],
            source=row["normalized_source"],
            translation=row["translation"],
            source_language=row["source_language"],
            target_language=row["target_language"],
            context=row["context"],
        )
        for row in rows
    ]


def prompt_fingerprint(
    item: MnemonicPreviewItem,
    *,
    generator_model: str,
    judge_model: str,
    content_version: int,
) -> str:
    payload = {
        "item": item.generation_input(),
        "generator_model": generator_model,
        "judge_model": judge_model,
        "content_version": content_version,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_components(components) -> str:
    if not components:
        return '<p class="muted">No morphological components.</p>'
    rows = "".join(
        f"<tr><td>{_escape(component.form)}</td>"
        f"<td>{_escape(component.role.replace('_', ' '))}</td>"
        f"<td>{_escape(component.meaning)}</td></tr>"
        for component in components
    )
    return (
        "<table><thead><tr><th>Form</th><th>Role</th><th>Meaning</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _render_review_form() -> str:
    criteria = "".join(
        '<label class="criterion">'
        f'<input type="checkbox" data-field="{key}"> {_escape(label)}'
        "</label>"
        for key, label in REVIEW_CRITERIA
    )
    return (
        '<section class="human-review"><h3>Human review</h3>'
        f'<div class="criteria">{criteria}</div>'
        '<label class="rating">Overall decision <select data-field="decision">'
        '<option value="">Not reviewed</option><option value="pass">Pass</option>'
        '<option value="revise">Needs revision</option>'
        '<option value="fail">Misleading</option></select></label>'
        '<label class="notes">Notes<textarea data-field="notes" rows="4" '
        'placeholder="What worked or failed?"></textarea></label></section>'
    )


def _render_result(result: MnemonicPreviewResult) -> str:
    preview_id = f"{result.item.item_id}:{result.sample}"
    metadata = (
        f"sample {result.sample} · generated "
        f"{_escape(result.generated_at.astimezone(UTC).isoformat())} · "
        f"prompt {_escape(result.prompt_sha256[:12])}"
    )
    if result.usage:
        calls = sum(value["calls"] for value in result.usage.values())
        input_tokens = sum(value["input_tokens"] for value in result.usage.values())
        output_tokens = sum(value["output_tokens"] for value in result.usage.values())
        reasoning = sum(value["reasoning_tokens"] for value in result.usage.values())
        metadata += (
            f" · {calls} model calls · {input_tokens:,} input tokens · "
            f"{output_tokens:,} output tokens ({reasoning:,} reasoning)"
        )
    opening = (
        f'<section class="preview{" error" if result.error else ""}" '
        f'data-preview-id="{_escape(preview_id)}"><h2>{_escape(result.item.source)} '
        f'<span>→ {_escape(result.item.translation)}</span></h2>'
        f'<p class="meta">{metadata}</p>'
        f'<p class="context">{_escape(result.item.context or "No context")}</p>'
    )
    if result.error is not None:
        return (
            opening
            + f'<p><strong>Generation failed.</strong></p><pre>{_escape(result.error)}</pre>'
            + _render_review_form()
            + "</section>"
        )
    if result.generation is None:
        raise ValueError("a successful result requires generation details")

    generation = result.generation
    analysis = generation.analysis
    analysis_html = (
        '<section class="analysis"><h3>1. Linguistic analysis</h3>'
        f'<p><strong>Structure:</strong> {_escape(analysis.word_structure.replace("_", " "))}<br>'
        f'<strong>Selected strategy:</strong> {_escape(analysis.strategy or "none")}<br>'
        f'<strong>Sound cue:</strong> {_escape(analysis.sound_cue or "none")}</p>'
        f"{_render_components(analysis.components)}"
        f'<p class="note">{_escape(analysis.analysis_note)}</p></section>'
    )
    candidate_html = '<p class="muted">No candidates generated.</p>'
    if generation.candidates is not None:
        selected = (
            generation.quality_review.selected_index
            if generation.quality_review and generation.quality_review.approved
            else None
        )
        candidate_html = "".join(
            f'<article class="candidate{" selected" if index == selected else ""}">'
            f'<h4>Candidate {index + 1}{" · selected" if index == selected else ""}</h4>'
            f"{_render_components(candidate.components)}"
            f'<p class="hook">{_escape(candidate.hook)}</p>'
            f'<p>{_escape(candidate.explanation)}</p></article>'
            for index, candidate in enumerate(generation.candidates.candidates)
        )
    candidates_section = (
        f'<section><h3>2. Strategy-specific candidates</h3>{candidate_html}</section>'
    )

    review = generation.quality_review
    if review is None:
        judge_html = '<p class="rejected">No candidate reached the judging stage.</p>'
    else:
        findings = "".join(f"<li>{_escape(item)}</li>" for item in review.findings)
        decision = (
            f"Approved candidate {review.selected_index + 1}"
            if review.approved and review.selected_index is not None
            else "Both candidates rejected"
        )
        judge_html = (
            f'<p class="{"approved" if review.approved else "rejected"}">'
            f"<strong>{_escape(decision)}</strong></p>"
            f"<ul>{findings}</ul>"
        )
    judge_section = f'<section><h3>3. Independent judge</h3>{judge_html}</section>'
    raw_json = generation.model_dump_json(indent=2)
    return (
        opening + analysis_html + candidates_section + judge_section
        + _render_review_form()
        + f'<details><summary>Raw pipeline output</summary><pre>{_escape(raw_json)}</pre></details>'
        + "</section>"
    )


def render_preview_report(
    *,
    language: str,
    generator_model: str,
    judge_model: str,
    report_id: str,
    created_at: datetime,
    results: Sequence[MnemonicPreviewResult],
    expected_results: int,
) -> str:
    completed = len(results)
    failures = sum(result.error is not None for result in results)
    approved = sum(
        bool(result.generation and result.generation.selected())
        for result in results
    )
    cards = "".join(_render_result(result) for result in results)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(language)} mnemonic preview</title><style>
:root{{--ink:#292922;--muted:#676960;--line:#d9d5c7;--paper:#fbfaf5;--gold:#c9aa43;--green:#426d49;--red:#963c30}}
*{{box-sizing:border-box}} body{{margin:0;background:#efede5;color:var(--ink);font:16px/1.55 system-ui,sans-serif}}
main{{width:min(1000px,calc(100% - 28px));margin:28px auto 80px}} h1,h2,h3,h4{{line-height:1.2}}
h1{{margin-bottom:6px}} h2 span,.meta,.muted{{color:var(--muted)}} .meta{{font-size:13px}}
.summary{{position:sticky;top:0;z-index:2;padding:10px 14px;border:1px solid var(--line);background:#fffffff2}}
.preview{{margin:24px 0;padding:24px;border:1px solid var(--line);border-radius:8px;background:var(--paper)}}
.preview.error{{border-color:var(--red)}} .context{{padding:10px 12px;border-left:3px solid var(--gold);background:#f6f1dc;font-family:Georgia,serif}}
.analysis,.human-review{{padding:16px;border:1px solid var(--line);background:white}} table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:7px 9px;border:1px solid var(--line);text-align:left}} th{{background:#ece7d5}} .note{{color:var(--muted)}}
.candidate{{margin:10px 0;padding:14px;border:1px solid var(--line);background:white}} .candidate.selected{{border:2px solid var(--green)}}
.candidate h4{{margin-top:0}} .hook{{font:600 18px/1.4 Georgia,serif}} .approved{{color:var(--green)}} .rejected{{color:var(--red)}}
.human-review{{margin-top:20px}} .human-review h3{{margin-top:0}} .criteria{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}}
.criterion,.rating,.notes{{display:block}} .rating,.notes{{margin-top:14px;font-weight:700}} select,textarea{{font:inherit}}
select{{margin-left:8px;padding:5px}} textarea{{width:100%;margin-top:6px;padding:8px;font-weight:400}} details{{margin-top:16px}}
pre{{overflow:auto;padding:12px;background:#25251f;color:#f8f5e9;font:12px/1.45 ui-monospace,monospace;white-space:pre-wrap}}
</style></head><body data-report-id="{_escape(report_id)}"><main>
<header><h1>{_escape(language)} mnemonic preview</h1><p>Generator: <strong>{_escape(generator_model)}</strong> · judge: <strong>{_escape(judge_model)}</strong> · created {_escape(created_at.astimezone(UTC).isoformat())}</p></header>
<p class="summary"><strong>{completed}/{expected_results}</strong> generated · <strong>{approved}</strong> approved · <strong>{failures}</strong> failed · <strong id="reviewed-count">0</strong> reviewed</p>
{cards or '<p>No results generated yet.</p>'}</main><script>
const storageKey = `margin:mnemonic-preview:${{document.body.dataset.reportId}}`;
let saved = {{}}; try {{ saved = JSON.parse(localStorage.getItem(storageKey) || "{{}}"); }} catch {{ saved = {{}}; }}
const cards = [...document.querySelectorAll("[data-preview-id]")];
function updateCount() {{ document.querySelector("#reviewed-count").textContent = cards.filter(card => card.querySelector('[data-field="decision"]')?.value).length; }}
for (const card of cards) {{ const id = card.dataset.previewId; const state = saved[id] || {{}};
for (const control of card.querySelectorAll("[data-field]")) {{ const key = control.dataset.field;
if (control.type === "checkbox") control.checked = Boolean(state[key]); else if (state[key] != null) control.value = state[key];
const save = () => {{ saved[id] ||= {{}}; saved[id][key] = control.type === "checkbox" ? control.checked : control.value; localStorage.setItem(storageKey, JSON.stringify(saved)); updateCount(); }};
control.addEventListener("change", save); if (control.tagName === "TEXTAREA") control.addEventListener("input", save); }} }} updateCount();
</script></body></html>"""


def write_preview_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate saved-word mnemonics for human review without updating SQLite."
    )
    parser.add_argument("--language", required=True)
    parser.add_argument(
        "--word",
        action="append",
        default=[],
        help="Dictionary form; repeat as needed when selecting saved words.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Explicitly select all saved words in the language.",
    )
    parser.add_argument("--limit", type=int, help="Limit selected words after filtering.")
    parser.add_argument(
        "--samples", type=int, default=1, help="Independent generations per word."
    )
    parser.add_argument(
        "--translation",
        help="Meaning for direct-input mode; bypasses saved vocabulary.",
    )
    parser.add_argument(
        "--target-language",
        default="English",
        help="Learner language for direct-input mode (default: English).",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Optional example sentence for direct-input mode.",
    )
    parser.add_argument(
        "--database", type=Path, help="Vocabulary database; defaults to the app setting."
    )
    parser.add_argument("--output", type=Path, help="Destination HTML report.")
    parser.add_argument(
        "--list-words",
        action="store_true",
        help="List saved words without calling OpenAI.",
    )
    return parser


def default_output_path(language: str, created_at: datetime) -> Path:
    timestamp = created_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("eval/results") / f"{language.casefold()}-mnemonics-{timestamp}.html"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.all and args.word:
        parser.error("--all cannot be combined with --word")
    direct = args.translation is not None
    if direct and (args.all or args.list_words):
        parser.error("--translation cannot be combined with --all or --list-words")
    if direct and len(args.word) != 1:
        parser.error("direct-input mode requires exactly one --word")
    if direct and args.limit is not None:
        parser.error("--limit is only available for saved vocabulary")
    if not direct and (args.context or args.target_language != "English"):
        parser.error("--context and --target-language require --translation")

    from pdf_language_learner.app import (
        DATABASE_PATH,
        MNEMONIC_CONTENT_VERSION,
        capture_model_usage,
        generate_vocabulary_mnemonic,
        mnemonic_judge_model,
        mnemonic_model,
    )

    database = args.database or DATABASE_PATH
    if not args.list_words and not args.all and not args.word:
        parser.error("choose --word or explicitly pass --all")
    if direct:
        try:
            items = [
                direct_preview_item(
                    word=args.word[0],
                    translation=args.translation,
                    source_language=args.language,
                    target_language=args.target_language,
                    context=args.context,
                )
            ]
        except ValueError as exc:
            parser.error(str(exc))
    else:
        try:
            items = load_saved_vocabulary(
                database,
                language=args.language,
                words=args.word,
                limit=args.limit,
            )
        except ValueError as exc:
            parser.error(str(exc))
    if args.list_words:
        for item in items:
            print(f"{item.source}\t{item.translation}")
        return 0
    if not items:
        parser.error("the selected language has no matching saved vocabulary")

    created_at = datetime.now(UTC)
    output = args.output or default_output_path(args.language, created_at)
    generator = mnemonic_model()
    judge = mnemonic_judge_model()
    report_id = hashlib.sha256(
        f"{args.language}\0{generator}\0{judge}\0{created_at.isoformat()}".encode()
    ).hexdigest()[:20]
    expected = len(items) * args.samples
    results: list[MnemonicPreviewResult] = []
    for item in items:
        fingerprint = prompt_fingerprint(
            item,
            generator_model=generator,
            judge_model=judge,
            content_version=MNEMONIC_CONTENT_VERSION,
        )
        for sample in range(1, args.samples + 1):
            print(
                f"Generating {len(results) + 1}/{expected}: "
                f"{item.source} (sample {sample})",
                flush=True,
            )
            generated_at = datetime.now(UTC)
            with capture_model_usage() as usage:
                try:
                    generation = generate_vocabulary_mnemonic(item.generation_input())
                    result = MnemonicPreviewResult(
                        item=item,
                        sample=sample,
                        generated_at=generated_at,
                        prompt_sha256=fingerprint,
                        generation=generation,
                        usage=usage,
                    )
                    decision = (
                        "approved"
                        if generation.selected() is not None
                        else "no aid approved"
                    )
                    print(f"  Judge: {decision}.", flush=True)
                except Exception as exc:
                    result = MnemonicPreviewResult(
                        item=item,
                        sample=sample,
                        generated_at=generated_at,
                        prompt_sha256=fingerprint,
                        error=f"{type(exc).__name__}: {exc}",
                        usage=usage,
                    )
                    print(f"  Failed: {result.error}", file=sys.stderr, flush=True)
            if usage:
                calls = sum(value["calls"] for value in usage.values())
                inputs = sum(value["input_tokens"] for value in usage.values())
                outputs = sum(value["output_tokens"] for value in usage.values())
                reasoning = sum(value["reasoning_tokens"] for value in usage.values())
                print(
                    f"  Tokens: {inputs:,} input, {outputs:,} output "
                    f"({reasoning:,} reasoning) across {calls} call(s).",
                    flush=True,
                )
            results.append(result)
            report = render_preview_report(
                language=args.language,
                generator_model=generator,
                judge_model=judge,
                report_id=report_id,
                created_at=created_at,
                results=results,
                expected_results=expected,
            )
            write_preview_report(output, report)
    print(f"Report written to {output.resolve()}")
    return 1 if any(result.error is not None for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
