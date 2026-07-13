---
applyTo: "**/*.test.*,**/*.spec.*,**/test_*,**/tests/**"
---

# Testing Instructions

- Write tests that are isolated, deterministic, and well-documented.
- Each test should test one behavior. Use descriptive test names: `test_<what>_<when>_<expected>`.
- Follow the Arrange-Act-Assert (AAA) pattern.
- Python tests: use pytest via hatch:
  - **All tests:** `cd hastelib && hatch run test:pytest` (from repo root).
  - **Specific tests:** `cd hastelib && hatch run test:pytest tests/path/to/test_file.py -v`
- UI tests: use Playwright for E2E validation.
- Mock external dependencies (Azure Blob, Cosmos DB, Azure Batch, queues) — never call real services in unit tests.
- Use `pytest-mock` (`mocker` fixture) for mocking — never manipulate `sys.modules` directly.
- Use Azurite connection string for integration tests (see `pyproject.toml` env vars and `tests/conftest.py`).
- Include both positive and negative test cases.
- Test edge cases: empty inputs, nulls, boundary values, large GeoTIFF files.
- For geospatial tests, validate CRS preservation, bounds accuracy, and COG compliance.
- Run tests via Docker to ensure GDAL and all native dependencies are available.
- Run `cd ui && npm run lint` to validate frontend code quality.
