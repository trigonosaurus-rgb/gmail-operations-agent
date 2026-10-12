# syntax=docker/dockerfile:1
# One image: the API, the worker and the built UI. The default command is the public demo
# (synthetic inbox, no Google account); see docker-compose.yml.

# --- 1. The UI: static files from Vite ------------------------------------------------
FROM node:26-trixie-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. The Python app in a virtual environment ------------------------------------------
FROM python:3.14-slim-trixie AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable
# The Google client bundles discovery documents for ~600 APIs (~100 MB); keep the two we call.
RUN find .venv/lib/python*/site-packages/googleapiclient/discovery_cache/documents -name '*.json' \
    ! -name gmail.v1.json ! -name sheets.v4.json -delete

# --- 3. Runtime: no build tools, no sources, a non-root user -----------------------------
FROM python:3.14-slim-trixie
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /app/data && chown agent /app/data
WORKDIR /app
COPY --from=app /app/.venv /app/.venv
COPY --from=web /web/dist /app/frontend/dist
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    WEB_DIST_DIR=/app/frontend/dist \
    AGENT_DB_PATH=/app/data/agent.sqlite3 \
    DEMO_DB_PATH=/app/data/demo.sqlite3
USER agent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['API_PORT']}/api/health\", timeout=4)"]
CMD ["gmail-agent", "demo"]
