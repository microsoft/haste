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
| `hastelib/tests/core/utils/test_blob.py` | US-001 (`fetch_url_text` never-raise contract) |
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
| UT-008 | `NodeNotReady` beyond the budget | raises `RetryError` (not `reraise=True`) | US-001 |
| UT-009 | `unwrap_retry_error` on that `RetryError` | recovers the `BatchErrorException` and its code | US-001 |
| UT-010 | `unwrap_retry_error` on a plain exception | returns it unchanged | US-001 |
| UT-011 | Wrapped method calling another wrapped method | inner SDK call attempted **5** times, not 25 | US-001 |
| UT-012 | `TaskNotFound` | raises after exactly 1 attempt | US-001 |

> The backoff is removed with `retry_with(wait=wait_none())`, so the real
> predicate and stop policy are exercised without the 4–10s sleeps.
>
> UT-011 guards the budget-multiplication regression: `apply_retry_to_methods`
> decorates every `AzureBatchJob` method, and `get_file_by_match_from_task`
> calls the separately wrapped `is_task_running` / `is_task_completed`. Using
> `reraise=True` made an exhausted inner budget look retryable to the outer
> wrapper, turning 5 attempts into 25 (measured).

### Runner degradation

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-013 | Node gone during file listing | `get_filecontent_from_task` returns `None` and warns | US-001 |
| UT-014 | Node gone during file download | returns `None` | US-001 |
| UT-015 | Unrelated Batch error (`JobNotFound`) | propagates | US-001 |
| UT-016 | Exhausted `NodeNotReady` budget (`RetryError`) | returns `None` | US-001 |
| UT-017 | Exhausted 5xx budget (`RetryError`) | propagates | US-001 |
| UT-018 | Node answers normally | chunks are decoded and joined | US-001 |
| UT-019 | Cleanup against a dead node | delete skipped; `disable_job` still called | US-004 |
| UT-020 | Cleanup with an exhausted `NodeNotReady` budget | delete skipped; `disable_job` still called | US-004 |
| UT-021 | Cleanup fails with `OperationTimedOut` | propagates; `disable_job` not called | US-004 |

### Blob fallback transport (`fetch_url_text`)

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-022 | Successful response | returns the body; `raise_for_status` called | US-001 |
| UT-023 | Custom timeout | passed through to `requests.get` | US-001 |
| UT-024 | HTTP error | returns `None` | US-001 |
| UT-025 | Transport error | returns `None` | US-001 |
| UT-026 | Non-`http(s)` path | returns `None`; `requests` never called | US-001 |
| UT-027 | Empty/`None` URL | returns `None` | US-001 |

### Imagery fallback

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-028 | Node copy available | node copy used; blob never fetched | US-001 |
| UT-029 | Node copy unavailable | blob copy used; identifier/`taskId`/format passed correctly | US-001 |
| UT-030 | Neither copy available | returns `None` | US-001 |
| UT-031 | Fallback itself raises | returns `None`, does not propagate | US-001 |
| UT-032 | Manifest recovered from blob | `_update_results_from_job` populates the layer | US-001 |
| UT-033 | Manifest lost everywhere | raises `FileNotFoundError` | US-001 |
| UT-034 | Log unavailable everywhere | returns `[]`; no exception | US-002 |
| UT-035 | Log recovered from blob | parsed into `ImageryLogRecord`s | US-002 |
| UT-036 | Submitted output patterns | list containing both `outputs/*.*` and `logs/*.*` | US-002 |

### Message formatting

| ID | Case | Expected | Story |
|---|---|---|---|
| UT-037 | Azure-style error with code + message | `"<Code>: <message>"` | US-003 |
| UT-038 | Message with `RequestId:`/`Time:` trailer | trailer stripped | US-003 |
| UT-039 | Any Azure-style error | no `additional_properties` / `'lang'` leakage | US-003 |
| UT-040 | Code with no message | just the code | US-003 |
| UT-041 | Plain `ValueError` | `str(exc)` | US-003 |
| UT-042 | Exception with no text | the type name; never empty | US-003 |
| UT-043 | Plain-string message | `"<Code>: <message>"` | US-003 |

## Regression guard

The full `hastelib` suite must show no new failures. Measured against a clean
worktree at HEAD, excluding two modules that cannot run outside the conda test
env (`tests/workflows/test_prepare_imagery.py` needs `osgeo`;
`tests/core/processors/test_artifacts.py` needs `pytest-mock`):

| Run | Passed | Failed |
|---|---|---|
| Baseline (HEAD) | 155 | 2 |
| With this change | 200 | 0 |

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
