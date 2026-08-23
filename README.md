# Margin — PDF Language Learner

A local-first language reader that lets you select text, detect its language, and translate it. It supports browser-local PDFs and public web pages that contain an article or transcript, optionally with audio.

## Run locally

```bash
uv sync --dev
uv run python main.py
```

Open <http://127.0.0.1:8000>, choose a text-based PDF or paste a public article URL, select text, choose a target language, and translate. Starred vocabulary is saved to `data/margin.db` by default and remains available across documents and browser sessions. Set `MARGIN_DATABASE_PATH` to use a different SQLite file.

URL imports are downloaded by the local FastAPI server and reduced to plain transcript paragraphs plus a direct audio URL when the publisher exposes one. Dynamic sites are supported through embedded transcript data (including DW lesson manuscripts). Some publishers keep audio behind their own JavaScript player; in that case Margin links to the original player while still making the extracted article text selectable.

The reader loads PDF.js from cdnjs, so the first page load needs an internet connection. Scanned/image-only PDFs require OCR, which is not part of this first version.

On the first single-word lookup in a language, Stanza downloads that language's
POS and lemmatization models. Later lookups reuse the local models. The selected
word is tagged inside its sentence before it is sent to the local translation
model.

## Design choices

- PDF.js renders pages and supplies an accurate selectable text layer.
- Stanza performs contextual POS tagging and lemmatization for single words.
- Structured Ollama calls perform language detection and translation locally.
- PDFs remain local; no upload endpoint exists. For URL imports, the server fetches only public HTTP(S) pages and rejects local/private network destinations.
- SQLite stores saved vocabulary on the backend. A unique normalized-form and source-language index prevents duplicate words or phrases.
