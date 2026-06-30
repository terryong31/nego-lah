# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# build-essential: for any deps with native extensions. curl: used by HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer is cached unless requirements change.
# (Use the BuildKit cache mount — NOT --no-cache-dir, which would defeat it.)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Copy application code (.dockerignore keeps .venv/.env/__pycache__ out).
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Multiple workers for real parallelism across cores. Override the count with
# the WEB_CONCURRENCY env var (e.g. set it to ~2x vCPUs). Shell form so the env
# var is expanded at runtime.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4}"]
