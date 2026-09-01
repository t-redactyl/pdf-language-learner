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
# Set OPENAI_API_KEY, ANTHROPIC_API_KEY, and ANTHROPIC_GRAMMAR_MODEL in .env.
uv sync --dev
uv run python main.py
```

The app loads `.env` automatically for local development. Exported environment
variables take precedence, and `.env` is excluded from Git.

Open <http://127.0.0.1:8000>, choose a text-based PDF or paste a public article URL, select text, choose a target language, and translate. PDF zoom controls enlarge only the document while keeping text selection and highlights aligned. Starred vocabulary is saved to `data/margin.db` by default and remains available across documents and browser sessions. Set `MARGIN_DATABASE_PATH` to use a different SQLite file.

## Deploy on Hugging Face Spaces

Create a private Docker Space and push this repository to it. CPU Basic hardware
is sufficient because generation uses hosted model APIs. Add `OPENAI_API_KEY`
and `ANTHROPIC_API_KEY` as Space **Secrets**, not variables. Set
`ANTHROPIC_GRAMMAR_MODEL` to the chosen Claude model ID. The container serves
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
| `OPENAI_TIMEOUT_SECONDS`       | `30`                       | OpenAI request timeout                        |
| `ANTHROPIC_GRAMMAR_MODEL`      | required                   | Anthropic model used for grammar             |
| `ANTHROPIC_TIMEOUT_SECONDS`    | `180`                      | Anthropic request timeout                    |
| `ANTHROPIC_GRAMMAR_MAX_OUTPUT_TOKENS` | `12000`           | Grammar generation token ceiling            |
| `ANTHROPIC_GRAMMAR_EFFORT`     | `medium`                   | Claude effort for lesson generation         |
| `MARGIN_DATABASE_PATH`         | `/data/margin.db`          | Vocabulary database location                 |
| `MARGIN_OPEN_THESAURUS_PATH`   | `/data/openthesaurus.txt`  | German thesaurus location                    |
| `STANZA_RESOURCES_DIR`         | `/data/stanza`             | Stanza model directory                       |

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

There is no startup model request, so starting or restarting the Space incurs no
OpenAI charge. OpenAI request and Stanza initialization/inference timings are
written to the server log. Repeated
word analyses, grammatical classifications, and exact translation requests are
held in bounded in-memory caches for the lifetime of the server process. Source
noun grammar and target translation keep their separate prompts but are issued
concurrently.
When a document's source language becomes known, the browser also asks the server
to prepare just that language's Stanza pipeline in the background.

## Design choices

- PDF.js renders pages and supplies an accurate selectable text layer.
- Stanza performs contextual POS tagging and lemmatization for single words.
- Simplemma and Unicode script detection identify the document language locally;
  structured OpenAI calls perform translation and rank WordNet synonym candidates.
- PDFs remain local; no upload endpoint exists. For URL imports, the server fetches only public HTTP(S) pages and rejects local/private network destinations.
- Selected text and its surrounding sentence context are sent to OpenAI for
  translation and disambiguation; entire PDF files are not uploaded to OpenAI.
- SQLite stores saved vocabulary on the backend. A unique normalized-form and source-language index prevents duplicate words or phrases.
