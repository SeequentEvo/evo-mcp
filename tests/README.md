# Tests

This directory contains automated tests for the Evo MCP server.

## Structure

- `unit/`: Fast, isolated tests that do not call live Evo services.
- `integration/`: Optional live tests that can call Evo APIs.
- `helpers.py`: Shared testing stubs (for example, `FakeMCP`).
- `conftest.py`: Pytest configuration for the test suite.

## Test files

### Shared support files

- `conftest.py`: Adds `src/` to `sys.path` so tests can import the project modules without installing the package into the active environment.
- `helpers.py`: Contains light-weight test doubles used across the suite.
	- `FakeMCP` records functions decorated with `@mcp.tool()` so tests can call registered tools directly.
	- `FakePage` mimics the SDK paging interface used by methods that return an object with an `.items()` method and supports `len(page)`.

### Unit tests

- `unit/test_context_cache.py`: Covers the `EvoContext` cache helpers.
	- Verifies `save_variables_to_cache()` and `load_variables_from_cache()` round-trip cached instance state.
	- Verifies `get_access_token_from_cache()` returns a valid JWT and rejects an expired JWT.
	- These tests stay local to a temporary directory and do not perform OAuth or network calls.

- `unit/test_admin_tools.py`: Covers the workspace-management MCP tools in `admin_tools.py`.
	- Verifies workspace creation response mapping.
	- Verifies workspace summary schema counting.
	- Verifies workspace snapshot generation, including optional blob reference collection and download-failure fallback.
	- Verifies object copy behavior, including blob copy orchestration and UUID clearing before create.
	- Verifies whole-workspace duplication filters objects correctly and tracks copy failures.

- `unit/test_filesystem_tools.py`: Covers the local CSV/data directory tools in `filesystem_tools.py`.
	- Exercises invalid directory configuration handling.
	- Verifies recursive file discovery under `EVO_LOCAL_DATA_DIR`.
	- Verifies CSV preview metadata, sample row generation, and missing-file handling.

- `unit/test_general_tools.py`: Covers selected workspace and instance management behaviors in `general_tools.py`.
	- Verifies `get_workspace` rejects missing identifiers.
	- Verifies workspace lookup by name raises a clear error when no match exists.
	- Verifies `list_workspaces` maps SDK models into the tool response shape.
	- Verifies `select_instance` switches the active instance using discovery results.
	- These tests use `AsyncMock` and `SimpleNamespace` instead of live SDK clients.

- `unit/test_instance_users_admin_tools.py`: Covers the instance-user admin MCP tools in `instance_users_admin_tools.py`.
	- Verifies paged user listing respects the requested `count` limit and maps user records into tool responses.
	- Verifies instance role listing passthrough.
	- Verifies add-user responses are mapped into invitation and member email lists.
	- Verifies remove-user and update-role operations call the workspace client with the expected arguments.
	- Verifies these tools fail clearly when no instance is selected.

- `unit/test_object_build_tools_dry_run.py`: Covers dry-run validation paths for the object builder tools.
	- `build_and_create_pointset`: success path and missing required coordinate columns.
	- `build_and_create_line_segments`: success path and invalid segment index validation.
	- `build_and_create_downhole_collection`: success path and invalid interval-file configuration.
	- `build_and_create_downhole_intervals`: success path and missing required midpoint column.
	- The tests intentionally stop at `dry_run=True`, so they validate CSV parsing and input checks without creating Evo objects or uploading data.

- `unit/test_setup_mcp.py`: Covers the interactive setup script helpers in `scripts/setup_mcp.py`.
	- Verifies `.env` parsing and writing behavior.
	- Verifies HTTP startup env validation and project-relative command resolution.
	- Verifies generated MCP client config entries for VS Code and Cursor.
	- Verifies WSL-specific VS Code config directory resolution prefers the VS Code server path.
	- Verifies `setup_mcp_config()` accepts an existing empty `mcp.json` and writes a valid Evo MCP config.

- `unit/test_server_bootstrap.py`: Covers MCP server bootstrap and conditional registration in `mcp_tools.py`.
	- Verifies invalid `MCP_TRANSPORT` falls back to `stdio`.
	- Verifies invalid `MCP_TOOL_FILTER` falls back to `all`.
	- Verifies `all`, `admin`, and `data` modes register the expected tools, prompts, and shared schema resource.
	- These tests import `mcp_tools` repeatedly with different environment settings and inspect FastMCP registrations through its listing APIs.

### Integration tests

- `integration/test_live_list_workspaces.py`: Read-only smoke test for live Evo connectivity.
	- Requires `RUN_EVO_LIVE_TESTS=1` plus the Evo auth environment variables documented below.
	- Calls `ensure_initialized()` and then checks that `workspace_client.list_workspaces()` returns objects with basic expected fields.
	- This is intentionally a minimal live test that validates authentication and a simple workspace listing flow without mutating server state.

- `integration/test_live_general_tools.py`: Additional read-only live coverage for the general MCP tools.
	- Verifies live workspace-service health checks.
	- Verifies instance discovery via `list_my_instances`.
	- Verifies workspace lookup by ID using a real accessible workspace.
	- Verifies object listing for a real workspace.
	- Verifies object metadata lookup by path when the selected workspace contains at least one object.
	- These tests remain opt-in and skip gracefully when the account has no accessible workspaces or no objects in the selected workspace.

- `integration/test_live_admin_tools.py`: Read-only live coverage for safe admin-tool flows.
	- Verifies workspace summary aggregation against a real workspace.
	- Verifies snapshot generation without blob expansion for a real workspace.
	- Avoids mutating admin operations such as workspace creation, copying, or duplication.

## Adding tests

- Add fast, isolated coverage under `unit/` when the code can be exercised with mocks, stubs, temporary files, or pure data fixtures.
- Add `integration/` coverage only for flows that need a real Evo instance or live SDK behavior.
- Prefer small test modules grouped by production module or feature area, as in the current layout.
- When testing MCP tool registration directly, use `FakeMCP` for individual tool modules and import `mcp_tools` only when bootstrap behavior itself is under test.

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

Instance and workspace selection for the live tests:

- The live tests do not read an instance from a test fixture file.
- On first `ensure_initialized()`, `evo_context` selects the first organization returned by Evo discovery if there is no cached instance selection.
- The selected `org_id` and `hub_url` are then cached in `.cache/variables.json` and reused by later test runs.
- The workspace-based live tests then use the first accessible workspace returned by `workspace_client.list_workspaces(limit=5)`.

If you hit permission errors or unexpected workspaces:

- Clear `.cache/variables.json` to force a fresh discovery-based instance selection on the next run.
- Confirm that the authenticated account has access to the selected instance and at least one readable workspace there.
- Some live tests intentionally skip when the selected instance has no accessible workspaces or no objects in the chosen workspace.

Known SDK caveat:

- The `test_live_get_object_by_path_when_workspace_has_objects` case in `integration/test_live_general_tools.py` can fail due to current Evo SDK path normalization behavior when an object path like `object.json` is normalized to `./object.json`. This is a false-negative risk in the SDK path handling rather than a required server-side write capability.

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
