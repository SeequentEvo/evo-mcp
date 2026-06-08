FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm@sha256:e4fa1f978c539608a10cdf74700ac32a3f719dfc6e8b6b6001da82deb36302a2 AS runtime

LABEL org.opencontainers.image.title="evo-mcp" \
      org.opencontainers.image.description="Evo MCP server" \
      org.opencontainers.image.source="https://github.com/SeequentEvo/evo-mcp" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=5000 \
    HOME=/home/evo-mcp \
    EVO_MCP_STATE_DIR=/home/evo-mcp/.local/share/evo-mcp \
    EVO_MCP_CACHE_DIR=/home/evo-mcp/.local/share/evo-mcp/cache \
    EVO_MCP_DEBUG_LOG_PATH=/home/evo-mcp/.local/share/evo-mcp/logs/mcp_tools_debug.log

RUN useradd --create-home --home-dir /home/evo-mcp --shell /usr/sbin/nologin --uid 10001 evo-mcp

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY src ./src

# Seed default runtime dirs with non-root ownership so Docker named volumes
# mounted at these paths inherit writeable ownership on first use.
RUN mkdir -p /home/evo-mcp/.local/share/evo-mcp/cache /home/evo-mcp/.local/share/evo-mcp/logs \
    && chown -R evo-mcp:evo-mcp /home/evo-mcp

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD python -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2).read(); sys.exit(0)"

USER evo-mcp
CMD ["python", "src/mcp_tools.py"]
