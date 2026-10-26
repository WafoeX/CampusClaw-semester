FROM ghcr.io/astral-sh/uv:0.12.16 AS uv
FROM python:3.12-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN groupadd --system mcp && useradd --system --gid mcp --no-create-home mcp
COPY --from=builder --chown=mcp:mcp /app/.venv /app/.venv
COPY --from=builder --chown=mcp:mcp /app/src /app/src
USER mcp
EXPOSE 8090
CMD ["uvicorn", "campusclaw_mcp.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
