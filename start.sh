#!/bin/sh
set -eu

mkdir -p \
    "$(dirname "$MARGIN_DATABASE_PATH")" \
    "$(dirname "$MARGIN_OPEN_THESAURUS_PATH")" \
    "$STANZA_RESOURCES_DIR"

exec uvicorn pdf_language_learner.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
