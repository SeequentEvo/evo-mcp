lint:
	uv run --extra dev ruff check
	uv run --extra dev ruff format --check
	uv run python scripts/check_python_license_headers.py

lint-fix:
	uv run --extra dev ruff check --fix
	uv run --extra dev ruff format
	uv run python scripts/check_python_license_headers.py --fix
