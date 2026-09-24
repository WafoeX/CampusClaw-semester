FROM ghcr.io/astral-sh/uv:0.12.16 AS uv
FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src
WORKDIR /app

RUN groupadd --system campusclaw \
    && useradd --system --gid campusclaw --home-dir /app --no-create-home campusclaw \
    && mkdir -p /var/lib/campusclaw/materials \
    && chown -R campusclaw:campusclaw /var/lib/campusclaw
COPY --from=builder --chown=campusclaw:campusclaw /app/.venv /app/.venv
COPY --from=builder --chown=campusclaw:campusclaw /app/src /app/src
COPY --from=builder --chown=campusclaw:campusclaw /app/migrations /app/migrations
COPY --from=builder --chown=campusclaw:campusclaw /app/alembic.ini /app/alembic.ini
USER campusclaw
EXPOSE 8000
CMD ["uvicorn", "campusclaw.main:app", "--host", "0.0.0.0", "--port", "8000"]
