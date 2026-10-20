# Web OS SPA (ADR 0015): built once, served by `kb web` from KB_WEB_DIST.
FROM node:22-slim AS web
WORKDIR /build
COPY package.json package-lock.json ./
COPY web/package.json web/
RUN npm ci
COPY web web
RUN npm run build

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /build/web/dist ./web/dist
ENV KB_WEB_DIST=/app/web/dist

RUN useradd --create-home --uid 1000 kb \
    && mkdir -p /data/telegram && chown kb:kb /data/telegram && chmod 700 /data/telegram \
    && mkdir -p /models && chown kb:kb /models \
    && mkdir -p /data/dictations /data/audio && chown kb:kb /data/dictations /data/audio
USER kb
ENV PATH="/app/.venv/bin:$PATH"
CMD ["kb", "--help"]
