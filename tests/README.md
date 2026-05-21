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
	- Requires `RUN_EVO_LIVE_TESTS=1` plus the service-app auth environment variables documented below.
	- Requires `EVO_TEST_INSTANCE_ID` so the test always targets the same Evo instance.
	- Calls `ensure_initialized()` and then checks that `workspace_client.list_workspaces()` returns objects with basic expected fields.
	- This is intentionally a minimal live test that validates authentication and a simple workspace listing flow without mutating server state.

- `integration/test_live_general_tools.py`: Additional read-only live coverage for the general MCP tools.
	- Requires `EVO_TEST_INSTANCE_ID` and `EVO_TEST_WORKSPACE_ID` for deterministic selection.
	- Verifies live workspace-service health checks.
	- Verifies instance discovery via `list_my_instances`.
	- Verifies workspace lookup by ID using a real accessible workspace.
	- Verifies object listing for a real workspace.
	- Verifies object metadata lookup by path when `EVO_TEST_OBJECT_PATH` is set to a known accessible object path.
	- These tests remain opt-in and skip gracefully when the deterministic selection env vars are not set.

- `integration/test_live_admin_tools.py`: Read-only live coverage for safe admin-tool flows.
	- Requires `EVO_TEST_INSTANCE_ID` and `EVO_TEST_WORKSPACE_ID` for deterministic selection.
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

At the moment, integration tests are not run by default. The default local test command and the current GitHub Actions workflow run unit tests only.

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

They are not run by default locally or in GitHub Actions. A live integration run only happens when you explicitly provide the required environment variables and invoke `pytest -m integration` yourself.

Instance and workspace selection for the live tests:

- The live tests require `AUTH_METHOD=client_credentials` and use service-app authentication rather than interactive user login.
- The live tests require explicit selection env vars.
- `EVO_TEST_INSTANCE_ID` identifies the Evo instance to use for the live run.
- `EVO_TEST_WORKSPACE_ID` identifies the workspace used by workspace-scoped live tests.
- `EVO_TEST_OBJECT_PATH` identifies the object path used by the live `get_object_by_path` test.
- The helper in `tests/integration/live_test_support.py` always switches `evo_context` to `EVO_TEST_INSTANCE_ID`.
- The helper also sets `EVO_DISABLE_TOKEN_CACHE=1` so a previously cached user token cannot leak into a service-app test run.

If you hit permission errors or unexpected workspaces:

- Confirm that the authenticated account has access to `EVO_TEST_INSTANCE_ID` and `EVO_TEST_WORKSPACE_ID`.
- Check that `EVO_TEST_OBJECT_PATH` exists in the configured workspace and is readable by the same account.

Known SDK caveat:

- The `test_live_get_object_by_path_when_workspace_has_objects` case in `integration/test_live_general_tools.py` can fail due to current Evo SDK path normalization behavior when an object path like `object.json` is normalized to `./object.json`. Set `EVO_TEST_OBJECT_PATH` to the exact path returned by a successful object listing in the target workspace. This remains a false-negative risk in SDK path handling rather than a required server-side write capability.

To run them, set:

- `RUN_EVO_LIVE_TESTS=1`
- `AUTH_METHOD=client_credentials`
- `EVO_CLIENT_ID`
- `EVO_CLIENT_SECRET`
- `EVO_DISCOVERY_URL`
- `EVO_TEST_INSTANCE_ID`
- `EVO_TEST_WORKSPACE_ID`

For the path-based object metadata test, also set:

- `EVO_TEST_OBJECT_PATH`

`ISSUER_URL` is optional for these tests and defaults to `https://ims.bentley.com` if unset.

Example:

```bash
RUN_EVO_LIVE_TESTS=1 \
AUTH_METHOD=client_credentials \
EVO_CLIENT_ID=your-service-client-id \
EVO_CLIENT_SECRET=your-service-client-secret \
EVO_DISCOVERY_URL=https://discover.api.seequent.com \
EVO_TEST_INSTANCE_ID=00000000-0000-0000-0000-000000000000 \
EVO_TEST_WORKSPACE_ID=11111111-1111-1111-1111-111111111111 \
uv run python -m pytest -q -m integration
```

## CI workflows

GitHub Actions test workflows are located in:

- `.github/workflows/on-pull-request.yaml`
- `.github/workflows/run-all-tests.yaml`
- `.github/actions/testing/action.yaml`

The CI matrix currently runs unit tests across Linux, macOS, and Windows on Python 3.10-3.14. It does not run the live integration tests by default.
