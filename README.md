# Margin — PDF Language Learner

A local-first PDF reader that lets you select text, detect its language, and translate it. PDF files never leave the browser; only the selected text is sent to the translation API.

## Run locally

```bash
uv sync --dev
export OPENAI_API_KEY="your-api-key"
uv run python main.py
```

Open <http://127.0.0.1:8000>, choose a text-based PDF, select text, choose a target language, and translate. Highlights are saved in browser storage for that file.

The reader loads PDF.js from cdnjs, so the first page load needs an internet connection. Scanned/image-only PDFs require OCR, which is not part of this first version.

## Design choices

- PDF.js renders pages and supplies an accurate selectable text layer.
- One structured OpenAI Responses API call performs language detection and translation.
- The API key stays on the Python server and is never exposed to browser code.
- PDFs remain local; no upload endpoint exists.

API usage follows the official [OpenAI text generation guide](https://developers.openai.com/api/docs/guides/text).
