# Tests

## Test files

- `unit/test_check_python_license_headers.py`: tests the repository-local license header checker used by the lint workflow.
  - Verifies the standard SPDX header is accepted.
  - Verifies Python scripts with a shebang before the header are accepted.
  - Verifies missing headers are reported and cause a non-zero exit status.

## Running tests

From the repository root:

```bash
python -m pytest -q -m unit
```
