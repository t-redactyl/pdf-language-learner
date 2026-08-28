FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    OLLAMA_HOST="http://127.0.0.1:11434" \
    OLLAMA_MODEL="translategemma:4b" \
    OLLAMA_KEEP_ALIVE="-1" \
    OLLAMA_MODELS="/opt/ollama/models" \
    MARGIN_DATABASE_PATH="/data/margin.db" \
    MARGIN_OPEN_THESAURUS_PATH="/data/openthesaurus.txt" \
    STANZA_RESOURCES_DIR="/data/stanza"

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl tini zstd \
    && curl --fail --silent --show-error --location \
        --output /tmp/install-ollama.sh https://ollama.com/install.sh \
    && sh /tmp/install-ollama.sh \
    && rm /tmp/install-ollama.sh \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies before copying the application so ordinary code changes
# can reuse this slower Docker build layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN set -eu; \
    chmod +x start.sh; \
    mkdir -p /data "$OLLAMA_MODELS"; \
    ollama serve >/tmp/ollama-build.log 2>&1 & \
    ollama_pid=$!; \
    attempt=0; \
    until ollama list >/dev/null 2>&1; do \
        attempt=$((attempt + 1)); \
        if ! kill -0 "$ollama_pid" 2>/dev/null || [ "$attempt" -ge 120 ]; then \
            cat /tmp/ollama-build.log; \
            exit 1; \
        fi; \
        sleep 1; \
    done; \
    ollama pull "$OLLAMA_MODEL"; \
    kill "$ollama_pid" 2>/dev/null || true; \
    wait "$ollama_pid" || true

EXPOSE 7860

ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["./start.sh"]
