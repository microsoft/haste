# Test Plan: Batch node-loss resilience

## Strategy

| Level | Scope | Mechanism |
|---|---|---|
| Unit | Error classification, retry policy, runner degradation, imagery fallback, message formatting | `hastelib/tests`, `unittest.TestCase`, mocked Batch client |
| Manual | End-to-end recovery on a real autoscale/spot pool | dev1 imagery run |

Live Batch behavior is not simulated in CI: `BatchErrorException` instances are
constructed directly with the codes the service returns, and the Batch client is
mocked. What is verified is HASTE's *reaction* to those codes.

## Test files

| File | Covers |
|---|---|
| `hastelib/tests/core/runners/test_azure_batch_node_errors.py` | US-001 (retry), US-004 (cleanup), runner degradation |
| `hastelib/tests/core/processors/test_imagery_output_fallback.py` | US-001 (fallback), US-002 (log + upload patterns) |
| `hastelib/tests/core/utils/test_errors.py` | US-003 (message formatting) |

## Coverage matrix

### Error classification

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-001 | `NodeNotReady` (409) | transient, unavailable, retryable, **not** a server error | US-001 |
| UT-002 | `NodeStateInvalid` (409) | transient, retryable | US-001 |
| UT-003 | `NodeNotFound` (404) | terminal, unavailable, **not** retryable | US-001 |
| UT-004 | 500 `InternalServerError` | still retryable (no regression) | US-001 |
| UT-005 | `TaskNotFound` (404) | neither retryable nor unavailable | US-001 |
| UT-006 | `ValueError` | no error code; not retryable | US-001 |

### Retry policy

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-007 | `NodeNotReady` twice, then success | succeeds; 3 attempts | US-001 |
| UT-008 | `NodeNotReady` beyond the budget | raises `BatchErrorException`, **not** `RetryError` | US-001 |
| UT-009 | `TaskNotFound` | raises after exactly 1 attempt | US-001 |

> The backoff is removed with `retry_with(wait=wait_none())`, so the real
> predicate and stop policy are exercised without the 4–10s sleeps.

### Runner degradation

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-010 | Node gone during file listing | `get_filecontent_from_task` returns `None` and warns | US-001 |
| UT-011 | Node gone during file download | returns `None` | US-001 |
| UT-012 | Unrelated Batch error (`JobNotFound`) | propagates | US-001 |
| UT-013 | Node answers normally | chunks are decoded and joined | US-001 |
| UT-014 | Cleanup against a dead node | delete skipped; `disable_job` still called | US-004 |
| UT-015 | Cleanup fails with `OperationTimedOut` | propagates; `disable_job` not called | US-004 |

### Imagery fallback

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-016 | Node copy available | node copy used; blob never fetched | US-001 |
| UT-017 | Node copy unavailable | blob copy used; identifier/`taskId`/format passed correctly | US-001 |
| UT-018 | Neither copy available | returns `None` | US-001 |
| UT-019 | Fallback itself raises | returns `None`, does not propagate | US-001 |
| UT-020 | Manifest recovered from blob | `_update_results_from_job` populates the layer | US-001 |
| UT-021 | Manifest lost everywhere | raises `FileNotFoundError` | US-001 |
| UT-022 | Log unavailable everywhere | returns `[]`; no exception | US-002 |
| UT-023 | Log recovered from blob | parsed into `ImageryLogRecord`s | US-002 |
| UT-024 | Submitted output patterns | list containing both `outputs/*.*` and `logs/*.*` | US-002 |

### Message formatting

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-025 | Azure-style error with code + message | `"<Code>: <message>"` | US-003 |
| UT-026 | Message with `RequestId:`/`Time:` trailer | trailer stripped | US-003 |
| UT-027 | Any Azure-style error | no `additional_properties` / `'lang'` leakage | US-003 |
| UT-028 | Code with no message | just the code | US-003 |
| UT-029 | Plain `ValueError` | `str(exc)` | US-003 |
| UT-030 | Exception with no text | the type name; never empty | US-003 |
| UT-031 | Plain-string message | `"<Code>: <message>"` | US-003 |

## Regression guard

The full `hastelib` suite must show no new failures. Measured against a clean
worktree at HEAD, excluding two modules that cannot run outside the conda test
env (`tests/workflows/test_prepare_imagery.py` needs `osgeo`;
`tests/core/processors/test_artifacts.py` needs `pytest-mock`):

| Run | Passed | Failed |
|---|---|---|
| Baseline (HEAD) | 155 | 2 |
| With this change | 188 | 0 |

The two baseline failures were in
`test_imagery_preprocess_config.py`, which exercises
`_execute_image_preprocess` — the same method this change touches. They were a
fixture gap, not a product bug: `MagicMock(spec=ImageLayer)` does not expose
pydantic field names, so the mock had no `clipBbox` attribute once that field
was added to the submitted config. Fixed here with a one-line fixture addition
so the imagery suite is green and future readers are not left wondering whether
this change broke it.

## Commands

```bash
# Targeted
cd hastelib && hatch run test:pytest \
  tests/core/runners/test_azure_batch_node_errors.py \
  tests/core/processors/test_imagery_output_fallback.py \
  tests/core/utils/test_errors.py -v

# Full suite
cd hastelib && hatch run test:pytest
```

## Manual verification (dev1)

| Step | Expectation |
|---|---|
| 1. Submit an image layer on a pool that scales to zero | Task runs and completes |
| 2. Let the node deallocate before the trigger reads outputs | Function logs warn that the node is unavailable |
| 3. Observe the layer | COMPLETED, with the manifest recovered from blob |
| 4. Inspect `<projectHash>/<taskId>/` in the outputs container | Contains `imagery_manifest.json` **and** `imagery_friendly.log` |
| 5. Force a genuine failure (bad imagery URL) | Status dialog shows the readable cause appended below prior progress |

## Out of scope

- Simulating real node preemption in CI.
- Load/performance testing — the change adds at most one HTTP GET per layer.
