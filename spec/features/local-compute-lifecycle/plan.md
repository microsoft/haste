# Plan: local compute lifecycle

## Implementation

| Task | Agent | Dependencies | Story | Status |
|---|---|---|---|---|
| Record focused spec and ADR-0006 | `backend-dev` | Approved lifecycle decision | All | complete |
| Implement receipts, host admission, reconciliation, cancellation, persistence gating | `backend-dev` | Spec | US-001 through US-005 | complete |
| Add conditional metadata updates and execution fences | `backend-dev` | Spec | US-006 | complete |
| Wire pending identities, queue consumers, recovery timers, and follow-ons | `backend-dev` | Lifecycle and fences | US-007 | complete |
| Add deterministic lifecycle, backend-CAS, processor, and queue tests | `backend-dev` | Implementation | All | complete |
| Run targeted and broader relevant tests and formatting/lint | `backend-dev` | Tests | All | complete |

## Integration gates

| Task | Agent | Dependencies | Story | Status |
|---|---|---|---|---|
| Independently validate implementation against acceptance | `backend-validation` | Parent integration | All | pending parent |
| Validate disposable Docker execution and restart on a Docker-capable host | `backend-validation` | Approved local smoke environment | US-001 through US-005 | pending integration |
| Preserve lifecycle/fencing seams in progress and backend-neutral prerequisites | `backend-dev` | Parent-owned stack integration | All | pending parent |

This is the independent lifecycle prerequisite based on current main.
The backend-neutral/AML integration remains in the feature PR. No Azure
resources or compute configuration are changed by this prerequisite.

## Validation evidence

After extracting the verified permission/output-pattern fixes, the
standalone main-based library and queue suite passed **625 tests** with
four platform skips and HTTP blocked. The known stale
`test_artifacts.py` call to removed `ArtifactProcessor.zip` remains excluded.
The five Linux permission tests also passed with real distinct producer and
consumer UIDs. No AML/neutral-only imports are present in this prerequisite.

The earlier development envelope passed 156 focused cases and 316 broader
regressions with two reproduced main API-guard failures deselected. The
complete earlier selector is retained below for those API boundaries.

```powershell
Set-Location .\hastelib
$env:PYTHONPATH = "$(Resolve-Path .\src);$(Resolve-Path ..)"
$tests = @(
    'tests\core\runners', 'tests\core\data_layer', 'tests\core\processors',
    'tests\core\utils\test_atomic_files.py',
    'tests\core\utils\test_batch_config.py',
    'tests\core\utils\test_validation_config.py',
    'tests\core\utils\test_errors.py',
    'tests\core\publishing\test_repository.py',
    'tests\core\publishing\test_lease.py',
    'tests\core\publishing\test_registry.py',
    '..\api\hastefuncqueues\tests',
    '..\api\hastefuncapi\tests\test_publishing_routes.py'
)
hatch run test:python -c "import pytest, sys; from unittest.mock import patch; block = patch('requests.sessions.Session.request', side_effect=AssertionError('Network disabled for unit validation')); block.start(); sys.exit(pytest.main(sys.argv[1:]))" @tests --ignore=tests\core\processors\test_artifacts.py -k 'not test_layer_request_rejects_workflow_owned_artifact_paths and not test_inference_launch_rejects_client_runtime_state' -q
hatch run test:python -m compileall -q src\hastegeo\core ..\api\hastefuncapi ..\api\hastefuncqueues
```

Both excluded API guard failures were reproduced against the original
`7243685` API source with HTTP disabled: `PutLayer` returns 500 instead of
400, and inference launch reaches a service call before rejecting supplied
runtime fields. Request-field guard work stays outside this prerequisite.

Black/isort (79 columns), blocking flake8, and compilation cover the changed
Python files. AST comparisons confirm that local file discovery and the
training log reader/metric/progress helpers remain unchanged for the progress
prerequisite. Run Hatch invocations sequentially because its conda provider
updates shared environment configuration.
