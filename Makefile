.PHONY: bootstrap lint typecheck test ci

bootstrap:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy grazlab_content_research

test:
	uv run pytest

ci: lint typecheck test
