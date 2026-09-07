# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency specifications first for Docker layer caching
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy application source code and install project with bytecode compilation
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runtime image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser -s /sbin/nologin -d /app appuser

# Copy virtualenv and application from builder with appuser ownership
COPY --chown=appuser:appuser --from=builder /app /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# `--forwarded-allow-ips` names the peers allowed to speak for someone else.
# Caddy runs in its own container, so it arrives from the compose bridge —
# not uvicorn's default 127.0.0.1. Without this, X-Forwarded-For is discarded,
# every request appears to come from Caddy, and every per-IP rate limit
# collapses into one bucket shared by all users.
#
# Deliberately the bridge range and NOT "*": with a wildcard uvicorn trusts the
# FIRST X-Forwarded-For entry, which is the one the client sent, so anyone
# could choose their own rate-limit bucket. Naming the range makes uvicorn scan
# from the right and stop at the first address a proxy didn't append — the real
# client. The container only listens on the compose network (`expose`, never
# `ports`), so nothing outside can reach it directly to claim that trust.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4} --forwarded-allow-ips '172.16.0.0/12,127.0.0.1'"]
