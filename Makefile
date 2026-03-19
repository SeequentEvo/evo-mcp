lint:
	uv run --extra dev ruff check
	uv run --extra dev ruff format --check
	@uv run --extra dev reuse lint-file $$(find src scripts -type f -name '*.py') || { \
		echo "License headers need updating. Run 'make lint-fix' to apply reuse annotations." >&2; \
		exit 1; \
	}

lint-fix:
	uv run --extra dev ruff check --fix
	uv run --extra dev ruff format
	@tmp_output=$$(mktemp); \
		uv run --extra dev reuse annotate --skip-existing --copyright="Bentley Systems, Incorporated" --license=Apache-2.0 $$(find src scripts -type f -name '*.py') > "$$tmp_output"; \
		status=$$?; \
		grep -v "^Skipped file '.*' already containing REUSE information$$" "$$tmp_output" || true; \
		rm -f "$$tmp_output"; \
		exit $$status
