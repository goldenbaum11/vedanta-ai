# Vedanta AI — backend image.
#
# Two stages:
#   1. `builder` installs build-time tooling (compilers needed for some
#      of chromadb's C extensions when wheels are missing on arm64) and
#      pip-installs into an isolated prefix.
#   2. `runtime` copies the prefix into a slim base image and runs
#      uvicorn under a non-root user.
#
# The COPY of `requirements.txt` happens before the source so changes
# to application code don't bust the pip layer.
#
# Uses the built-in BuildKit dockerfile frontend (no `# syntax=`
# directive) so we don't have to pull an extra layer at build time.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
# --ignore-installed is critical: without it pip sees `packaging` and
# `wheel` already installed system-wide (we just upgraded them) and
# skips them when laying down the /install prefix, so the runtime
# stage ends up missing transitive deps from `limits`/slowapi.
RUN pip install --upgrade pip wheel \
    && pip install --prefix=/install --ignore-installed \
        -r /app/backend/requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# libpq5 covers asyncpg's runtime; ca-certificates is needed for HTTPS
# calls (Inria SHP, public corpora, embedding endpoints, etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 vedanta \
    && useradd --system --uid 1000 --gid vedanta --create-home --home-dir /home/vedanta vedanta

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=vedanta:vedanta backend /app/backend
COPY --chown=vedanta:vedanta scripts /app/scripts
COPY --chown=vedanta:vedanta data /app/data
COPY --chown=vedanta:vedanta pyproject.toml /app/pyproject.toml

# Per-tenant writeable dirs land under /data so they live on the
# Docker volume and survive container rebuilds. The application
# code respects DATABASE_URL / CHROMA_PERSIST_DIR so we just point
# them at /data in the compose file.
RUN mkdir -p /data && chown -R vedanta:vedanta /data

USER vedanta
EXPOSE 8000

# A naive curl to /health is good enough — the endpoint already
# probes the LLM, embeddings, Chroma, and the DB.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
