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
uv sync --dev
uv run python main.py
```

Open <http://127.0.0.1:8000>, choose a text-based PDF or paste a public article URL, select text, choose a target language, and translate. Starred vocabulary is saved to `data/margin.db` by default and remains available across documents and browser sessions. Set `MARGIN_DATABASE_PATH` to use a different SQLite file.

## Deploy on Hugging Face Spaces

Create a private Docker Space and push this repository to it. Start with CPU
Basic hardware; Ollama will use a supported GPU automatically if the Space is
upgraded later.

The container includes `translategemma:4b` and serves the app on the port that
Hugging Face expects. Its changeable files use `/data` by default:

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
| `OLLAMA_MODEL`                 | `translategemma:4b`        | Ollama model used for translation            |
| `OLLAMA_KEEP_ALIVE`            | `-1`                       | Keep the model loaded while the Space runs   |
| `MARGIN_DATABASE_PATH`         | `/data/margin.db`          | Vocabulary database location                 |
| `MARGIN_OPEN_THESAURUS_PATH`   | `/data/openthesaurus.txt`  | German thesaurus location                    |
| `STANZA_RESOURCES_DIR`         | `/data/stanza`             | Stanza model directory                       |

URL imports are downloaded by the local FastAPI server and reduced to plain transcript paragraphs plus a direct audio URL when the publisher exposes one. Dynamic sites are supported through embedded transcript data (including DW lesson manuscripts), and linked transcript PDFs such as Deutsch-to-go's “Text (PDF)” attachments are detected and extracted automatically. Some publishers keep audio behind their own JavaScript player; in that case Margin links to the original player while still making the extracted article text selectable.

The reader loads PDF.js from cdnjs, so the first page load needs an internet connection. Scanned/image-only PDFs require OCR, which is not part of this first version.

On the first single-word lookup in a language, Stanza downloads that language's
POS and lemmatization models. Later lookups reuse the local models. The selected
word is tagged inside its sentence before it is sent to the local translation
model.

Single-word lookups show the normalized word, its translation, and up to two
context-aware synonyms together. Spanish candidates come from Open Multilingual
WordNet. German candidates combine Open-de-WordNet with the richer
[OpenThesaurus](https://www.openthesaurus.de/) export, which is downloaded once
to `data/openthesaurus.txt` and reused locally. OpenThesaurus data is used under
the LGPL 2.1 option offered by its publisher. Margin asks Ollama to keep and rank
only candidates matching the selected word's meaning in its sentence.
Candidates are first ordered using local
`wordfreq` corpus data; words below Zipf 2.5 or roughly 100 times less frequent
than the source word are discarded. When WordNet has to fall back from a strict
part-of-speech query, a batched local Stanza check rejects grammatically
incompatible candidates. Once the document language is known, Margin prepares
the relevant dictionaries in the background and reuses them locally. Set
`MARGIN_OPEN_THESAURUS_PATH` to store the German export elsewhere; if it cannot
be downloaded, German lookups continue with OdeNet.
Single-sense lookups bypass Ollama, while ambiguous candidate sets are cached
after contextual ranking. Synonym ranking runs alongside translation so the
combined result does not add unnecessary sequential model latency.
For German and Spanish nouns, the existing Stanza morphology supplies gender
locally. Margin derives definite articles from that gender for normalized
sources, translations, and synonym results; Spanish stressed-a nouns such as
`agua` use the singular article `el`. Other source languages retain the model
grammar fallback.

At startup the server warms the Ollama translation model in the background and
keeps it loaded by default. Set `OLLAMA_WARMUP=false` to disable that request or
`OLLAMA_KEEP_ALIVE` to change the default indefinite (`-1`) retention. Ollama and
Stanza initialization/inference timings are written to the server log. Repeated
word analyses, grammatical classifications, and exact translation requests are
held in bounded in-memory caches for the lifetime of the server process. Source
noun grammar and target translation keep their separate prompts but are issued
concurrently when Ollama has capacity to process parallel requests.
When a document's source language becomes known, the browser also asks the server
to prepare just that language's Stanza pipeline in the background.

## Design choices

- PDF.js renders pages and supplies an accurate selectable text layer.
- Stanza performs contextual POS tagging and lemmatization for single words.
- Simplemma and Unicode script detection identify the document language locally;
  structured Ollama calls perform translation and rank WordNet synonym candidates.
- PDFs remain local; no upload endpoint exists. For URL imports, the server fetches only public HTTP(S) pages and rejects local/private network destinations.
- SQLite stores saved vocabulary on the backend. A unique normalized-form and source-language index prevents duplicate words or phrases.
