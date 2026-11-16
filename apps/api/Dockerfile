# One image for every Python process: API, arq worker, market-data streamer,
# strategy runner. Built from the repo root:  docker build -f apps/api/Dockerfile .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "uv>=0.5"

WORKDIR /app

# dependency layer (cached unless lockfile / manifests change)
COPY pyproject.toml uv.lock ./
COPY packages/py-common/pyproject.toml packages/py-common/
COPY packages/db/pyproject.toml packages/db/
COPY services/market-data/pyproject.toml services/market-data/
COPY services/broker-gateway/pyproject.toml services/broker-gateway/
COPY services/strategy-engine/pyproject.toml services/strategy-engine/
COPY services/ai-agent/pyproject.toml services/ai-agent/
COPY services/jobs/pyproject.toml services/jobs/
COPY apps/api/pyproject.toml apps/api/
RUN uv sync --frozen --no-dev --no-install-workspace

# source layer
COPY packages packages
COPY services services
COPY apps/api apps/api
COPY evals evals
COPY docs docs
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 algo && chown -R algo /app
USER algo
WORKDIR /app/apps/api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
