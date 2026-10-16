.PHONY: install run lint format build test check

install:
	uv sync --locked

run:
	uv run valutatrade

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest -q

check: lint test

build:
	uv build
