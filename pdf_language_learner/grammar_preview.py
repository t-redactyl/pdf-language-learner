"""Batch-preview support for reviewing generated grammar lessons."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from pdf_language_learner.grammar_revision import (
    GrammarGeneratedSession,
    GrammarSessionKind,
    grammar_generation_messages,
)
from pdf_language_learner.grammar_topics import GrammarTopic


REVIEW_CRITERIA = (
    ("accurate", "Grammatically accurate"),
    ("clear", "Clear and self-contained"),
    ("terms", "Terms are properly defined"),
    ("examples", "Examples follow the stated procedure"),
    ("exceptions", "Exceptions are distinguished from regular rules"),
    ("tables", "Tables are useful and correct"),
    ("exercises", "Exercises match the explanation"),
)


@dataclass(frozen=True)
class GrammarPreviewResult:
    topic: GrammarTopic
    sample: int
    generated_at: datetime
    prompt_sha256: str
    generated: GrammarGeneratedSession | None = None
    error: str | None = None


def select_preview_topics(
    catalogue: Sequence[GrammarTopic],
    *,
    levels: Sequence[str] = (),
    categories: Sequence[str] = (),
    topic_keys: Sequence[str] = (),
    limit: int | None = None,
) -> list[GrammarTopic]:
    """Select catalogue topics using case-insensitive intersecting filters."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    available_keys = {topic.key for topic in catalogue}
    unknown_keys = sorted(set(topic_keys) - available_keys)
    if unknown_keys:
        raise ValueError(f"unknown topic key(s): {', '.join(unknown_keys)}")

    wanted_levels = {value.casefold() for value in levels}
    wanted_categories = {value.casefold() for value in categories}
    wanted_keys = set(topic_keys)
    selected = [
        topic
        for topic in catalogue
        if (not wanted_levels or topic.level.value.casefold() in wanted_levels)
        and (
            not wanted_categories
            or topic.category.casefold() in wanted_categories
        )
        and (not wanted_keys or topic.key in wanted_keys)
    ]
    return selected[:limit]


def prompt_fingerprint(
    topic: GrammarTopic,
    saved_vocabulary: Sequence[str],
) -> str:
    messages = grammar_generation_messages(
        language=topic.language.value,
        kind=GrammarSessionKind.LESSON,
        topics=[
            {
                "key": topic.key,
                "title": topic.title,
                "level": topic.level.value,
                "example": topic.example,
            }
        ],
        saved_vocabulary=list(saved_vocabulary),
    )
    encoded = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_rule_table(table) -> str:
    headers = "".join(f"<th scope=\"col\">{_escape(item)}</th>" for item in table.headers)
    rows = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
        for row in table.rows
    )
    return (
        '<div class="rule-table-wrap"><table><caption>'
        f"{_escape(table.title)}</caption><thead><tr>{headers}</tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _render_exercise(exercise, position: int) -> str:
    extras = []
    if exercise.choices:
        extras.append(
            "<p><strong>Choices:</strong> "
            + " · ".join(_escape(item) for item in exercise.choices)
            + "</p>"
        )
    if exercise.tokens:
        extras.append(
            "<p><strong>Tokens:</strong> "
            + " · ".join(_escape(item) for item in exercise.tokens)
            + "</p>"
        )
    accepted = exercise.accepted_answers or [exercise.reference_answer]
    return (
        '<article class="exercise">'
        f"<h4>{position}. {_escape(exercise.type.value.replace('_', ' ').title())}</h4>"
        f"<p><strong>Instruction:</strong> {_escape(exercise.instruction)}</p>"
        f"<p class=\"prompt\">{_escape(exercise.prompt)}</p>"
        f"{''.join(extras)}"
        f"<p><strong>Accepted:</strong> {' · '.join(_escape(item) for item in accepted)}</p>"
        f"<p><strong>Rubric:</strong> {_escape(exercise.grading_rubric)}</p>"
        f"<p><strong>Explanation:</strong> {_escape(exercise.explanation)}</p>"
        "</article>"
    )


def _render_review_form() -> str:
    criteria = "".join(
        '<label class="criterion">'
        f'<input type="checkbox" data-field="{key}"> {_escape(label)}'
        "</label>"
        for key, label in REVIEW_CRITERIA
    )
    return (
        '<section class="review"><h3>Human review</h3>'
        f'<div class="criteria">{criteria}</div>'
        '<label class="rating">Overall decision '
        '<select data-field="decision"><option value="">Not reviewed</option>'
        '<option value="pass">Pass</option><option value="revise">Needs revision</option>'
        '<option value="fail">Incorrect</option></select></label>'
        '<label class="notes">Notes<textarea data-field="notes" rows="4" '
        'placeholder="What was confusing or incorrect?"></textarea></label></section>'
    )


def _render_result(result: GrammarPreviewResult) -> str:
    preview_id = f"{result.topic.key}:{result.sample}"
    heading = (
        f"{_escape(result.topic.title)} "
        f'<span class="sample">sample {result.sample}</span>'
    )
    metadata = (
        f"{_escape(result.topic.level.value)} · {_escape(result.topic.category)} · "
        f"{_escape(result.topic.key)} · generated "
        f"{_escape(result.generated_at.astimezone(UTC).isoformat())} · "
        f"prompt {_escape(result.prompt_sha256[:12])}"
    )
    if result.error is not None:
        return (
            f'<section class="preview error" data-preview-id="{_escape(preview_id)}">'
            f"<h2>{heading}</h2><p class=\"meta\">{metadata}</p>"
            f"<pre>{_escape(result.error)}</pre></section>"
        )
    if result.generated is None:
        raise ValueError("a successful preview result requires generated content")

    generated = result.generated
    tables = "".join(_render_rule_table(table) for table in generated.rule_tables)
    examples = "".join(f"<li>{_escape(item)}</li>" for item in generated.worked_examples)
    exercises = "".join(
        _render_exercise(exercise, position)
        for position, exercise in enumerate(generated.exercises, start=1)
    )
    raw_json = generated.model_dump_json(indent=2)
    return (
        f'<section class="preview" data-preview-id="{_escape(preview_id)}">'
        f"<h2>{heading}</h2><p class=\"meta\">{metadata}</p>"
        '<section class="lesson"><h3>Rule explanation</h3>'
        f"<p>{_escape(generated.rule_summary)}</p>{tables}"
        f"<h3>Worked examples</h3><ul>{examples}</ul></section>"
        f'<section class="exercises"><h3>Exercises</h3>{exercises}</section>'
        f"{_render_review_form()}"
        f'<details><summary>Raw structured output</summary><pre>{_escape(raw_json)}</pre></details>'
        "</section>"
    )


def render_preview_report(
    *,
    language: str,
    model: str,
    report_id: str,
    created_at: datetime,
    results: Sequence[GrammarPreviewResult],
    expected_results: int,
) -> str:
    """Render a self-contained report with reviews persisted in localStorage."""

    completed = len(results)
    failures = sum(result.error is not None for result in results)
    cards = "".join(_render_result(result) for result in results)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(language)} grammar preview</title>
<style>
:root{{--ink:#292922;--muted:#676960;--line:#d9d5c7;--paper:#fbfaf5;--gold:#c9aa43}}
*{{box-sizing:border-box}} body{{margin:0;background:#efede5;color:var(--ink);font:16px/1.55 system-ui,sans-serif}}
main{{width:min(1100px,calc(100% - 28px));margin:28px auto 80px}} header{{margin-bottom:24px}}
h1,h2,h3,h4{{line-height:1.2}} h1{{margin-bottom:6px}} .meta{{color:var(--muted);font-size:13px}}
.summary{{position:sticky;top:0;z-index:2;padding:10px 14px;border:1px solid var(--line);background:#fffffff2;backdrop-filter:blur(8px)}}
.preview{{margin:24px 0;padding:24px;border:1px solid var(--line);border-radius:8px;background:var(--paper);box-shadow:0 4px 18px #2929220c}}
.preview>h2{{margin-top:0}} .sample{{color:var(--muted);font-size:13px;font-weight:500}}
.lesson{{padding:18px;border-left:3px solid var(--gold);background:#f6f1dc}} .lesson h3:first-child{{margin-top:0}}
.rule-table-wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}
caption{{padding:8px 0;text-align:left;font-weight:700}} th,td{{padding:8px 10px;border:1px solid var(--line);text-align:left}} th{{background:#ece7d5}}
.exercises{{margin-top:22px}} .exercise{{padding:12px 0;border-top:1px solid var(--line)}} .exercise h4{{margin-bottom:8px}} .exercise p{{margin:6px 0}}
.prompt{{font:500 18px/1.45 Georgia,serif}} .review{{margin-top:22px;padding:16px;border:1px solid #b8b49f;background:white}}
.review h3{{margin-top:0}} .criteria{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px}}
.criterion,.rating,.notes{{display:block}} .rating,.notes{{margin-top:14px;font-weight:700}} select,textarea{{font:inherit}}
select{{margin-left:8px;padding:5px}} textarea{{width:100%;margin-top:6px;padding:8px;border:1px solid var(--line);font-weight:400}}
details{{margin-top:16px}} pre{{overflow:auto;padding:12px;background:#25251f;color:#f8f5e9;font:12px/1.45 ui-monospace,monospace;white-space:pre-wrap}}
.error{{border-color:#b94838}} .error h2{{color:#8d2d20}} @media(max-width:600px){{.preview{{padding:16px}}.lesson{{padding:14px}}}}
</style>
</head>
<body data-report-id="{_escape(report_id)}">
<main>
<header><h1>{_escape(language)} grammar preview</h1>
<p>Model: <strong>{_escape(model)}</strong> · created {_escape(created_at.astimezone(UTC).isoformat())}</p></header>
<p class="summary"><strong>{completed}/{expected_results}</strong> generated · <strong>{failures}</strong> failed · <strong id="reviewed-count">0</strong> reviewed</p>
{cards or '<p>No results generated yet.</p>'}
</main>
<script>
const storageKey = `margin:grammar-preview:${{document.body.dataset.reportId}}`;
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(storageKey) || "{{}}"); }} catch {{ saved = {{}}; }}
const cards = [...document.querySelectorAll("[data-preview-id]")];
function updateCount() {{
  document.querySelector("#reviewed-count").textContent = cards.filter(card => card.querySelector('[data-field="decision"]')?.value).length;
}}
for (const card of cards) {{
  const id = card.dataset.previewId;
  const state = saved[id] || {{}};
  for (const control of card.querySelectorAll("[data-field]")) {{
    const key = control.dataset.field;
    if (control.type === "checkbox") control.checked = Boolean(state[key]);
    else if (state[key] != null) control.value = state[key];
    control.addEventListener("change", () => {{
      saved[id] ||= {{}};
      saved[id][key] = control.type === "checkbox" ? control.checked : control.value;
      localStorage.setItem(storageKey, JSON.stringify(saved));
      updateCount();
    }});
    if (control.tagName === "TEXTAREA") control.addEventListener("input", () => {{
      saved[id] ||= {{}};
      saved[id][key] = control.value;
      localStorage.setItem(storageKey, JSON.stringify(saved));
    }});
  }}
}}
updateCount();
</script>
</body>
</html>"""


def write_preview_report(path: Path, content: str) -> None:
    """Atomically checkpoint a report after each model response."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate grammar lessons for batch human review without using SQLite."
    )
    parser.add_argument("--language", required=True, choices=("German", "Spanish"))
    parser.add_argument("--level", action="append", default=[], help="Repeatable level filter.")
    parser.add_argument(
        "--category", action="append", default=[], help="Repeatable category filter."
    )
    parser.add_argument("--topic", action="append", default=[], help="Repeatable topic key.")
    parser.add_argument("--all", action="store_true", help="Explicitly select the full catalogue.")
    parser.add_argument("--limit", type=int, help="Limit selected topics after filtering.")
    parser.add_argument("--samples", type=int, default=1, help="Generations per topic (default: 1).")
    parser.add_argument(
        "--vocabulary",
        action="append",
        default=[],
        help="Optional saved-vocabulary item to inject; repeat as needed.",
    )
    parser.add_argument("--output", type=Path, help="Destination HTML report.")
    parser.add_argument(
        "--list-topics", action="store_true", help="List topics without calling Anthropic."
    )
    return parser


def default_output_path(language: str, created_at: datetime) -> Path:
    timestamp = created_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return Path("eval/results") / f"{language.casefold()}-{timestamp}.html"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.all and (args.level or args.category or args.topic):
        parser.error("--all cannot be combined with topic filters")

    # Importing app loads the local .env and keeps the pure rendering module light.
    from pdf_language_learner.app import (
        anthropic_grammar_model,
        generate_grammar_content,
        grammar_catalogue,
    )

    catalogue = grammar_catalogue(args.language)
    if args.list_topics:
        for topic in catalogue:
            print(
                f"{topic.key}\t{topic.level.value}\t{topic.category}\t{topic.title}"
            )
        return 0
    if not args.all and not (args.level or args.category or args.topic):
        parser.error("choose --topic, --level, --category, or explicitly pass --all")

    try:
        topics = select_preview_topics(
            catalogue,
            levels=args.level,
            categories=args.category,
            topic_keys=args.topic,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not topics:
        parser.error("the selected filters matched no grammar topics")

    created_at = datetime.now(UTC)
    output = args.output or default_output_path(args.language, created_at)
    model = anthropic_grammar_model()
    report_id = hashlib.sha256(
        f"{args.language}\0{model}\0{created_at.isoformat()}".encode()
    ).hexdigest()[:20]
    expected = len(topics) * args.samples
    results: list[GrammarPreviewResult] = []

    for topic in topics:
        fingerprint = prompt_fingerprint(topic, args.vocabulary)
        for sample in range(1, args.samples + 1):
            print(
                f"Generating {len(results) + 1}/{expected}: "
                f"{topic.key} (sample {sample})",
                flush=True,
            )
            generated_at = datetime.now(UTC)
            try:
                generated = generate_grammar_content(
                    topic.language.value,
                    GrammarSessionKind.LESSON,
                    [topic],
                    list(args.vocabulary),
                )
                result = GrammarPreviewResult(
                    topic=topic,
                    sample=sample,
                    generated_at=generated_at,
                    prompt_sha256=fingerprint,
                    generated=generated,
                )
            except Exception as exc:
                result = GrammarPreviewResult(
                    topic=topic,
                    sample=sample,
                    generated_at=generated_at,
                    prompt_sha256=fingerprint,
                    error=f"{type(exc).__name__}: {exc}",
                )
                print(f"  Failed: {result.error}", file=sys.stderr, flush=True)
            results.append(result)
            write_preview_report(
                output,
                render_preview_report(
                    language=args.language,
                    model=model,
                    report_id=report_id,
                    created_at=created_at,
                    results=results,
                    expected_results=expected,
                ),
            )

    print(f"Report written to {output.resolve()}")
    return 1 if any(result.error is not None for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
