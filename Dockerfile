FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so code changes don't bust this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable --extra langfuse

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --extra langfuse


FROM python:3.12-slim-bookworm

RUN useradd --create-home app
COPY --from=build /app/.venv /app/.venv
USER app

# The server speaks MCP over stdio: run with `docker run -i`.
ENTRYPOINT ["/app/.venv/bin/freestyle-libre-mcp"]
