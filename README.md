---
title: Margin — PDF Language Learner
emoji: 📖
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Margin — PDF Language Learner

A local-first language reader that lets you select text, detect its language, and translate it. It supports browser-local PDFs and public web pages that contain an article or transcript, optionally with audio.

## Run locally

```bash
cp .env .env
# Set OPENAI_API_KEY in .env. Grammar model settings are optional.
uv sync --dev
uv run python main.py
```

The app loads `.env` automatically for local development. Exported environment
variables take precedence, and `.env` is excluded from Git.

Open <http://127.0.0.1:8000>, choose a text-based PDF or paste a public article URL, select text, choose a target language, and translate. PDF zoom controls enlarge only the document while keeping text selection and highlights aligned. Starred vocabulary is saved to `data/margin.db` by default and remains available across documents and browser sessions. Set `MARGIN_DATABASE_PATH` to use a different SQLite file.

## Deploy on Hugging Face Spaces

Create a private Docker Space and push this repository to it. CPU Basic hardware
is sufficient because generation uses hosted model APIs. Add `OPENAI_API_KEY`
as a Space **Secret**, not a variable. The container serves
the app on the port that Hugging Face expects, and its changeable files use
`/data` by default:

- `/data/margin.db` stores saved vocabulary and revision history.
- `/data/stanza` stores downloaded language-analysis models.
- `/data/openthesaurus.txt` stores the downloaded German thesaurus.

To retain these files across restarts, create a private Hugging Face Storage
Bucket and attach it to the Space as a read-write volume mounted at `/data`.
Without that volume, the app still runs, but these files can disappear whenever
the Space stops or restarts.

The defaults can be changed in the Space's **Settings → Variables** page:

| Variable                       | Default                    | Purpose                                      |
|--------------------------------|----------------------------|----------------------------------------------|
| `OPENAI_MODEL`                 | `gpt-5.6-luna`             | OpenAI model used for translation            |
| `OPENAI_TIMEOUT_SECONDS`       | `30`                       | Translation request timeout                  |
| `OPENAI_MNEMONIC_MODEL`        | `gpt-5.6-luna`             | Mnemonic analysis and candidate generation   |
| `OPENAI_MNEMONIC_GENERATION_EFFORT` | `medium`              | Mnemonic analysis and writing effort         |
| `OPENAI_MNEMONIC_JUDGE_MODEL`  | `gpt-5.4`                  | Independent mnemonic-quality judge           |
| `OPENAI_MNEMONIC_JUDGE_EFFORT` | `low`                      | Mnemonic judge reasoning effort              |
| `GEMINI_API_KEY`               | —                          | Gemini key; its presence enables Gemini mnemonics |
| `MNEMONIC_PROVIDER`            | automatic                  | Optional `gemini` or `openai` override        |
| `GEMINI_MNEMONIC_MODEL`        | `gemini-3.8-flash`         | Gemini mnemonic analysis and generation model |
| `GEMINI_MNEMONIC_JUDGE_MODEL`  | `gemini-3.8-flash`         | Gemini mnemonic quality judge model           |
| `GEMINI_TIMEOUT_SECONDS`       | `60`                       | Gemini mnemonic request timeout               |
| `OPENAI_GRAMMAR_MODEL`         | `gpt-5.6-luna`             | OpenAI model used for grammar                 |
| `GRAMMAR_PREGENERATION_ENABLED` | `false`                    | Generate upcoming grammar sessions in the background |
| `OPENAI_GRAMMAR_TIMEOUT_SECONDS` | `180`                    | Grammar request timeout                      |
| `OPENAI_GRAMMAR_MAX_OUTPUT_TOKENS` | `20000`               | Grammar generation token ceiling             |
| `OPENAI_GRAMMAR_GENERATION_EFFORT` | `xhigh`                | Reasoning effort for lesson generation       |
| `OPENAI_GRAMMAR_GRADING_EFFORT` | `high`                    | Reasoning effort for open-ended grading      |
| `OPENAI_GRAMMAR_JUDGE_MODEL`   | `gpt-5.4`                  | Independent exercise-quality judge           |
| `OPENAI_GRAMMAR_JUDGE_EFFORT`  | `low`                      | Reasoning effort for the quality judge        |
| `OPENAI_GRAMMAR_JUDGE_MAX_OUTPUT_TOKENS` | `6000`             | Judge reasoning and response token budget     |
| `OPENAI_GRAMMAR_REPAIR_EFFORT` | `low`                      | Reasoning effort for targeted repairs         |
| `OPENAI_GRAMMAR_REPAIR_MAX_OUTPUT_TOKENS` | `8000`            | Targeted-repair token ceiling                 |
| `MARGIN_DATABASE_PATH`         | `/data/margin.db`          | Vocabulary database location                 |
| `MARGIN_OPEN_THESAURUS_PATH`   | `/data/openthesaurus.txt`  | German thesaurus location                    |
| `STANZA_RESOURCES_DIR`         | `/data/stanza`             | Stanza model directory                       |

When `GEMINI_API_KEY` is set, mnemonic analysis, candidate generation, and
quality judging use Gemini automatically. Translation and grammar requests
continue to use OpenAI. Set `MNEMONIC_PROVIDER=openai` to keep mnemonic requests
on OpenAI even when the Gemini key is present, or set it to `gemini` to require
Gemini. The model names are configurable because Gemini 1.5 Flash is no longer
listed as a current model in Google's API documentation; the default follows
Google's current Flash example.

URL imports are downloaded by the local FastAPI server and reduced to plain transcript paragraphs plus playable media when the publisher exposes it. Dynamic sites are supported through embedded transcript data (including DW lesson manuscripts, HLS video on Video-Thema pages, Langsam gesprochene Nachrichten articles, and Spanish Babbel podcasts hosted by TimelineNotation), and linked transcript PDFs such as Deutsch-to-go's “Text (PDF)” attachments are detected and extracted automatically. Some publishers keep media behind their own JavaScript player; in that case Margin links to the original player while still making the extracted article text selectable.

The reader loads PDF.js from cdnjs, so the first page load needs an internet connection. Scanned/image-only PDFs require OCR, which is not part of this first version.

On the first single-word lookup in a language, Stanza downloads that language's
POS and lemmatization models. Later lookups reuse the local models. The selected
word is tagged inside its sentence before it is sent to OpenAI.

Single-word lookups show the normalized word, its translation, and up to two
context-aware synonyms together. Spanish candidates come from Open Multilingual
WordNet. German candidates combine Open-de-WordNet with the richer
[OpenThesaurus](https://www.openthesaurus.de/) export, which is downloaded once
to `data/openthesaurus.txt` and reused locally. OpenThesaurus data is used under
the LGPL 2.1 option offered by its publisher. Margin asks OpenAI to keep and rank
only candidates matching the selected word's meaning in its sentence.
Candidates are first ordered using local
`wordfreq` corpus data; words below Zipf 2.5 or roughly 100 times less frequent
than the source word are discarded. When WordNet has to fall back from a strict
part-of-speech query, a batched local Stanza check rejects grammatically
incompatible candidates. Once the document language is known, Margin prepares
the relevant dictionaries in the background and reuses them locally. Set
`MARGIN_OPEN_THESAURUS_PATH` to store the German export elsewhere; if it cannot
be downloaded, German lookups continue with OdeNet.
Single-sense lookups bypass OpenAI, while ambiguous candidate sets are cached
after contextual ranking. Synonym ranking runs alongside translation so the
combined result does not add unnecessary sequential model latency.
For German and Spanish nouns, the existing Stanza morphology supplies gender
locally. Margin derives definite articles from that gender for normalized
sources, translations, and synonym results; Spanish stressed-a nouns such as
`agua` use the singular article `el`. Other source languages retain the model
grammar fallback.

## Preview generated grammar lessons

Generate grammar lessons in batches for human review without creating sessions
or changing revision progress. First list the available topic keys:

```bash
uv run python scripts/preview_grammar.py --language Spanish --list-topics
```

Then select topics by key, level, or category. Filters can be repeated and are
combined; `--samples` generates independent versions of each selected topic:

```bash
uv run python scripts/preview_grammar.py \
  --language Spanish \
  --level A2 \
  --limit 12 \
  --samples 1 \
  --output eval/results/spanish-a2.html
```

The self-contained HTML report includes the rule explanations, tables,
exercises, raw structured output, and a review rubric. Decisions and notes are
saved in that browser's local storage. Reports are checkpointed after every
model response and ignored by Git. Use `--all` explicitly to generate the full
catalogue; this guard helps prevent accidental API spend.

## Preview generated vocabulary mnemonics

Inspect the saved dictionary forms without calling OpenAI:

```bash
uv run python scripts/preview_mnemonics.py --language German --list-words
```

Then generate one or more independent samples for selected words:

```bash
uv run python scripts/preview_mnemonics.py \
  --language German \
  --word aufmachen \
  --word Handschuh \
  --samples 3 \
  --output eval/results/german-mnemonics.html
```

To test a word that is not saved, provide its meaning. Context is optional but
helps the pipeline choose the intended sense:

```bash
uv run python scripts/preview_mnemonics.py \
  --language German \
  --word aufmachen \
  --translation "to open" \
  --context "Mach bitte das Fenster auf." \
  --samples 3 \
  --output eval/results/aufmachen-mnemonics.html
```

Direct-input mode bypasses SQLite. Use `--target-language` when the supplied
translation is not English.

The report shows the linguistic analysis, explicit prefix/stem or compound
parts, both strategy-specific candidates, the independent judge's decision and
findings, token usage, raw pipeline output, and a human-review form saved in the
browser's local storage. Previewing reads saved vocabulary without replacing
the mnemonic used by revision. Use `--all` explicitly to test every saved word;
`--limit` can cap a larger selection.

When a word has opaque or archaic morphology, the mnemonic pipeline may use a
sound bridge: an invented target-language phrase that follows distinctive
sounds from the source word and becomes a vivid scene for its meaning. Any defensible
modern prefix or compound part remains labelled separately; invented sound
chunks are never presented as roots or etymology. If the initial linguistic
analysis finds no strategy for an opaque prefixed verb or compound noun, a
creative second pass tries looser near-homophones, names, numbers, and surreal
phrases before accepting that no useful aid is available.

When `GRAMMAR_PREGENERATION_ENABLED=true`, starting or restarting the Space
resumes any missing grammar preparation for languages with practice history or
an active lesson. An untouched language makes no automatic model requests.
OpenAI request and Stanza initialization/inference timings are
written to the server log. Repeated
word analyses, grammatical classifications, and exact translation requests are
held in bounded in-memory caches for the lifetime of the server process. Source
noun grammar and target translation keep their separate prompts but are issued
concurrently.
When a document's source language becomes known, the browser also asks the server
to prepare just that language's Stanza pipeline in the background.

## Grammar preparation

After grammar practice finishes, Margin prepares the next new-rule lesson and
its three-topic review during the two-day pause. It uses the catalogue's next
unseen rule, the usual review priorities, and a snapshot of familiar saved
vocabulary (at least five correct vocabulary answers). Both German and Spanish
are supported. Once a catalogue is complete, it prepares the next review only.
Starting a first lesson also queues its review while the learner works.

Prepared exercises live in SQLite and survive restarts with the same database.
They do not introduce rules, update scores, or unlock practice early. When a
session is due, Margin checks its topics, progress, and content version before
using the prepared exercises. A changed selection or missing result falls back
to normal generation. New vocabulary alone does not discard a prepared session.

Preparation runs in the server process without needing an open browser, using
the existing grammar model and ordinary API requests. It keeps at most one
lesson and one review per language, retries missing or failed work every five
minutes, and resumes after a restart. The server must be running to prepare
exercises; a sleeping Space catches up when it wakes. Use one Uvicorn worker
(the deployment default) so background and on-demand generation share locks.
Automatic pre-generation is disabled by default. Set
`GRAMMAR_PREGENERATION_ENABLED=true` to enable it. Grammar sessions remain
available and generate on demand when opened, so changing this setting does not
remove the feature or lose progress.

Each generation attempt is recorded in `grammar_generation_runs`. Every model
response belonging to that run is recorded separately in `grammar_model_usage`,
including its operation, model, call order, retry attempt, input and cached-input
tokens, output and reasoning tokens, configured output ceiling, and reasoning
effort. Completed runs also retain their topics, approval or failure status,
quality-review count, blocking-finding count, repair status, and error. Requests
that fail before the provider returns usage still appear as failed runs, but
cannot have a corresponding usage row because no token totals were returned.

For example, this query summarizes grammar generation by pipeline stage:

```sql
SELECT operation, model, COUNT(*) AS calls,
       SUM(input_tokens) AS input_tokens,
       SUM(output_tokens) AS output_tokens,
       SUM(reasoning_tokens) AS reasoning_tokens
FROM grammar_model_usage
GROUP BY operation, model
ORDER BY SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) DESC;
```

Every newly generated lesson and review now passes through an independent LLM
judge before being saved. The judge checks all fifteen exercises, the rule
explanation, tables, and examples for natural vocabulary and collocations,
plausible meanings, correct grammar, clear instructions, valid answer keys, and
fit to the selected topic and level. Saved vocabulary is optional: both models
are instructed to omit words that would make an exercise unnatural.

The generator receives concrete feedback and can revise the session once.
Repairs use a restricted schema containing only exercises with blocking findings
and an optional replacement lesson section. Other exercises are preserved by the
application. Each revision is judged with the previous findings and the actual
change list, so the judge checks fixes and regressions using the same standards.
Findings distinguish blocking errors from optional suggestions; suggestions are
retained in the report but do not prevent approval. The judge uses the actual
grading policy, including case-insensitive closed-answer matching and translation
grading against the whole prompt, reference, and rubric together.
Translations matching a normalized reference or accepted answer are marked
correct locally; only non-matching translations require a model grading call.
Only approved content is saved; if
review fails or the judge is unavailable, background preparation retries later
and on-demand generation reports a failure. This also applies to the preview
script. Judge feedback, the model name, and final approval are retained in the
prepared content and the session's `quality_review_json` for inspection. Older
prepared exercises are regenerated; sessions with answers already recorded remain
resumable. This is an automated quality filter, not a guarantee of correctness.

The judge uses `OPENAI_GRAMMAR_JUDGE_MODEL`, independently of the generator's
`OPENAI_GRAMMAR_MODEL`. These additional model calls add cost and generation time,
usually during the background preparation window. The default judge uses the
existing OpenAI credentials and grammar request timeout.

Empty, truncated, or malformed responses retry once at the failed step. Judges
and targeted repairs preserve the current draft
and feedback. When the API reports output-token exhaustion (reasoning uses this
budget too), the retry keeps the configured ceiling and lowers reasoning effort
to leave room for the structured response. Token ceilings are never increased
implicitly. Refusals and content-filter failures are not retried. Final
errors identify the operation and retain provider status and token diagnostics.

The preview report displays judge feedback and approval status directly. If a
sample still fails, its last valid draft and available feedback remain visible
for human inspection, clearly marked as unapproved. Such drafts are never saved
as practice sessions. The command still exits with a failure status if any sample
failed. Translation accepted-answer lists are illustrative: the judge checks the
rubric's flexibility rather than requiring every equivalent wording in the list.

## Design choices

- PDF.js renders pages and supplies an accurate selectable text layer.
- Stanza performs contextual POS tagging and lemmatization for single words.
- Simplemma and Unicode script detection identify the document language locally;
  structured OpenAI calls perform translation and rank WordNet synonym candidates.
- PDFs remain local; no upload endpoint exists. For URL imports, the server fetches only public HTTP(S) pages and rejects local/private network destinations.
- Selected text and its surrounding sentence context are sent to OpenAI for
  translation and disambiguation; entire PDF files are not uploaded to OpenAI.
- SQLite stores saved vocabulary on the backend. A unique normalized-form and source-language index prevents duplicate words or phrases.
