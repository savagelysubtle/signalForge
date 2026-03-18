FROM python:3.14-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY src/backend/pyproject.toml src/backend/uv.lock ./src/backend/

WORKDIR /app/src/backend
RUN uv sync --no-dev --no-install-project --frozen

WORKDIR /app
COPY src/backend/ ./src/backend/
COPY templates/ ./templates/

WORKDIR /app/src/backend

ENV PORT=8420

EXPOSE ${PORT}

CMD uv run uvicorn main:app --host 0.0.0.0 --port ${PORT}
