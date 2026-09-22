all: run

ensure-uv:
	@which uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

install: ensure-uv
	uv sync

run: ensure-uv
	uv run python3 src

trun: ensure-uv
	uv run python3 src --renderer=terminal

nvrun: ensure-uv
	uv run python3 src --no-visual

debug: ensure-uv
	uv run python3 -m pdb src/__main__.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .mypy_cache

lint: ensure-uv
	uv run flake8 . --exclude=.venv
	uv run mypy . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict: ensure-uv
	uv run flake8 . --exclude=.venv
	uv run mypy . --strict

test: ensure-uv
	uv run pytest

.PHONY: ensure-uv install run debug clean lint lint-strict test
