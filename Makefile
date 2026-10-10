.PHONY: bootstrap lint typecheck test ci pre-push

bootstrap:
	uv sync
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy grazlab_content_research

test:
	uv run pytest

ci: lint typecheck test

# The gate that used to live in GitHub Actions. GitHub Actions became a cost constraint, so
# `.github/workflows/ci.yml` is gone and `make ci` is now THE bar for every PR. A bare
# `make ci` skips the one thing that workflow did beyond it, so it moves here, wired to
# `git push` by `.pre-commit-config.yaml`'s pre-push hook (installed by `make bootstrap`).
# Run it by hand any time with `make pre-push`.
#   1. `uv sync --all-extras --dev --locked` — the environment CI built, from the lockfile;
#      `--locked` fails if pyproject and uv.lock have drifted, so drift is a defect to SEE,
#      not a resolution to do quietly (no new dependency without checking the lockfile).
#   2. `make ci` — ruff + mypy + pytest.
pre-push:
	uv sync --all-extras --dev --locked
	$(MAKE) ci
