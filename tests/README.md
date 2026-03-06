# Tests

This directory contains automated tests for the Evo MCP server.

## Structure

- `unit/`: Fast, isolated tests that do not call live Evo services.
- `integration/`: Optional live tests that can call Evo APIs.
- `helpers.py`: Shared testing stubs (for example, `FakeMCP`).
- `conftest.py`: Pytest configuration for the test suite.

## Running tests

From the repository root:

```bash
# Run all tests (integration tests are skipped by default)
uv run python -m pytest -q

# Run unit tests only
uv run python -m pytest -q -m unit

# Run integration tests only (still skipped unless enabled)
uv run python -m pytest -q -m integration
```

If you are not using `uv`, run the same commands with your Python executable:

```bash
python -m pytest -q -m unit
```

## Test markers

Markers are defined in `pyproject.toml`:

- `unit`: isolated tests with no external services
- `integration`: tests that may call live Evo APIs

## Live integration tests

Integration tests are intentionally opt-in.

To run them, set:

- `RUN_EVO_LIVE_TESTS=1`
- `EVO_CLIENT_ID`
- `EVO_REDIRECT_URL`
- `EVO_DISCOVERY_URL`

Example:

```bash
RUN_EVO_LIVE_TESTS=1 uv run python -m pytest -q -m integration
```

## CI workflows

GitHub Actions test workflows are located in:

- `.github/workflows/on-pull-request.yaml`
- `.github/workflows/run-all-tests.yaml`
- `.github/actions/testing/action.yaml`

The CI matrix runs unit tests across Linux, macOS, and Windows on Python 3.10-3.14.
