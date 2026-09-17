FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev && \
    useradd --create-home --uid 10001 --shell /usr/sbin/nologin app && \
    chown -R app:app /app

ENV PATH="/app/.venv/bin:${PATH}"
USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.environ.get('MCP_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).read()"]

CMD ["weknora-mcp"]
