# Margin — PDF Language Learner

A local-first language reader that lets you select text, detect its language, and translate it. It supports browser-local PDFs and public web pages that contain an article or transcript, optionally with audio.

## Run locally

```bash
uv sync --dev
uv run python main.py
```

Open <http://127.0.0.1:8000>, choose a text-based PDF or paste a public article URL, select text, choose a target language, and translate. Starred vocabulary is saved to `data/margin.db` by default and remains available across documents and browser sessions. Set `MARGIN_DATABASE_PATH` to use a different SQLite file.

URL imports are downloaded by the local FastAPI server and reduced to plain transcript paragraphs plus a direct audio URL when the publisher exposes one. Dynamic sites are supported through embedded transcript data (including DW lesson manuscripts), and linked transcript PDFs such as Deutsch-to-go's “Text (PDF)” attachments are detected and extracted automatically. Some publishers keep audio behind their own JavaScript player; in that case Margin links to the original player while still making the extracted article text selectable.

The reader loads PDF.js from cdnjs, so the first page load needs an internet connection. Scanned/image-only PDFs require OCR, which is not part of this first version.

On the first single-word lookup in a language, Stanza downloads that language's
POS and lemmatization models. Later lookups reuse the local models. The selected
word is tagged inside its sentence before it is sent to the local translation
model.

The lookup panel can switch between translation and context-aware synonyms.
Synonyms are available for single German and Spanish words. Margin obtains
same-part-of-speech candidates from Open-de-WordNet or Open Multilingual
WordNet, then asks Ollama to keep and rank only candidates matching the selected
word's meaning in its sentence. Once the document language is known, Margin
prepares the relevant WordNet lexicon in the background and reuses it locally.
Single-sense lookups bypass Ollama, while ambiguous candidate sets are
cached after contextual ranking.
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
