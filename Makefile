lint:
	uv run --extra dev ruff check
	uv run --extra dev ruff format --check

lint-fix:
	uv run --extra dev ruff check --fix
	uv run --extra dev ruff format
