#!/bin/sh
set -eu

mkdir -p \
    "$(dirname "$MARGIN_DATABASE_PATH")" \
    "$(dirname "$MARGIN_OPEN_THESAURUS_PATH")" \
    "$STANZA_RESOURCES_DIR" \
    "$OLLAMA_MODELS"

ollama serve &
ollama_pid=$!

attempt=0
until ollama list >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if ! kill -0 "$ollama_pid" 2>/dev/null || [ "$attempt" -ge 120 ]; then
        echo "Ollama did not start successfully." >&2
        exit 1
    fi
    sleep 1
done

# The model is included in the image. This fallback also makes a deliberately
# overridden OLLAMA_MODELS directory repair itself on first startup.
if ! ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
    ollama pull "$OLLAMA_MODEL"
fi

exec uvicorn pdf_language_learner.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
