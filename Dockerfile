FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    OPENAI_MODEL="gpt-5.6-luna" \
    OPENAI_TIMEOUT_SECONDS="30" \
    ANTHROPIC_TIMEOUT_SECONDS="60" \
    MARGIN_DATABASE_PATH="/data/margin.db" \
    MARGIN_OPEN_THESAURUS_PATH="/data/openthesaurus.txt" \
    STANZA_RESOURCES_DIR="/data/stanza"

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates tini \
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
    mkdir -p /data

EXPOSE 7860

ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["./start.sh"]
