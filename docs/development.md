# Development Guide

This guide covers development practices and workflows for the HASTE project.

## Local Storage Emulator (Azurite)

HASTE uses [Azurite](https://github.com/Azure/Azurite) to emulate Azure Blob, Queue, and Table Storage for local development. It is listed under `dependencies` in `package.json` so it can be run via `npx azurite`.

**Azurite must never be used outside of local development.** It is not hardened for network exposure and has known transitive vulnerabilities (see below) that are acceptable only because the emulator is localhost-only and never handles production data or credentials.

### Known security limitations

Azurite's dependency tree includes `@azure/ms-rest-js@1.x` (deprecated upstream, no new releases) and `axios@0.x`/`uuid@3.x`, which carry open CVEs. These cannot be resolved with npm `overrides` because:

- `@azure/ms-rest-js` uses the removed `require('uuid/v4')` subpath — forcing uuid ≥7 would break azurite at runtime.
- `@azure/ms-rest-js` uses `axios.CancelToken` — removed in axios 1.x, so forcing an upgrade would break azurite at runtime.

The safe mitigation is use-restriction, not patching:

- Run azurite only on `localhost` (the default). Never bind it to `0.0.0.0` or expose it through any port-forwarding, tunnel, or container network.
- Do not use azurite in CI pipelines that run with production secrets in scope.
- Do not deploy the `azurite` package to any production or staging environment.
- Switch to a real Azure Storage account (via connection string or managed identity) for any non-local environment.

These alerts are tracked and reviewed periodically. Resolution is blocked on azurite shipping a major dependency upgrade; see the security reports in [`docs/security-reports/`](security-reports/) for the latest status.

---

## Code Quality Standards

### Pre-commit Hooks

The project uses pre-commit hooks to automatically format and lint code:

```bash
# Install pre-commit hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

The pre-commit configuration includes:

- **Black**: Code formatting (79 character line length)
- **isort**: Import sorting
- **flake8**: Linting and style checking
- **ruff**: Fast Python linter (also available in `env.yml`)

## Documentation Standards

### API Documentation

All public functions and classes should have comprehensive docstrings:

```python
async def MyAPIFunction(req: func.HttpRequest) -> func.HttpResponse:
    """
    Brief description of what the function does.

    Detailed description with more context about the function's purpose,
    how it fits into the larger system, and any important notes.

    Args:
        req (func.HttpRequest): The HTTP request with parameters:
            - param1 (str): Description of parameter
            - param2 (int, optional): Description of optional parameter

    Returns:
        func.HttpResponse: JSON response with:
            - 200: Success with data
            - 400: Bad request
            - 500: Server error

    Example:
        GET /api/MyAPIFunction?param1=value

        Response:
        {
            "data": "result",
            "status": "success"
        }
    """
```

### Building Documentation

Documentation is built using Jupyter Book:

```bash
cd docs
jb build .
```

## Testing

### Unit Tests

Write unit tests for all core functionality:

```python
import pytest
from mymodule import MyClass

def test_my_function():
    """Test that MyClass.my_method works correctly."""
    instance = MyClass()
    result = instance.my_method("input")
    assert result == "expected_output"
```

### Integration Tests

Test API endpoints and workflows end-to-end.

## Contributing

1. **Fork the repository** and create a feature branch
2. **Write comprehensive docstrings** for all new functions
3. **Add unit tests** for new functionality
4. **Run pre-commit hooks** to ensure code quality
5. **Update documentation** if needed
6. **Submit a pull request** with a clear description

### Branch Naming

Use descriptive branch names:

- `feature/add-new-endpoint`
- `bugfix/fix-upload-issue`
- `docs/improve-api-documentation`

### Commit Messages

Write clear, descriptive commit messages:

```text
Add comprehensive docstrings to API functions

- Added detailed docstrings to all main API endpoints
- Included parameter descriptions and response codes
- Added usage examples for complex endpoints
```
