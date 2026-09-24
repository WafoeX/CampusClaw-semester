.PHONY: install format format-check lint typecheck test quality

install:
	uv sync --frozen --python 3.12

format:
	uv run ruff format src tests

format-check:
	uv run ruff format --check src tests

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src tests

test:
	uv run pytest

quality: format-check lint typecheck test
