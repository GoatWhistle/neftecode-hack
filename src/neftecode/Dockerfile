FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src/neftecode/ ./src/neftecode/
RUN uv sync --locked --no-dev

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    NEFTECODE_PORT=8765 \
    NEFTECODE_HOST=0.0.0.0
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml uv.lock README.md ./
COPY src/neftecode/ ./src/neftecode/
COPY config/ ./config/

RUN mkdir -p /app/artifacts /app/src/frontend/dist && chown -R app:app /app

USER app
EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('NEFTECODE_PORT','8765')+'/api/scenarios', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "neftecode serve --port ${NEFTECODE_PORT}"]
