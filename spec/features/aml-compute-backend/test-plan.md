# Test Plan: Backend-neutral compute runner + Azure Machine Learning backend

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | Compute models, router, execution service, each adapter in isolation | pytest/`unittest` (`hastelib/tests/`) | All new decision logic and validation rules |
| Contract | All adapters satisfy the same `ComputeRunner` semantics | Parameterized conformance suite | Batch, AML, local |
| Model compatibility | Legacy record loading, new record round-trip, client-supplied field rejection | Pydantic serialization tests | `TrainingJob`, `InferenceJob`, `ImageryPreprocessJob`, `ZipJob` |
| API integration | Optional compute-selection field validation and backward-compatible defaults | Existing Function test pattern (`api/hastefuncapi`) | Launch endpoints for all five workloads |
| Queue integration | Persisted handle survives requeue/restart; lifecycle calls route to the recorded backend | Queue handler tests with serialized resource records | `api/hastefuncqueues` |
| Container contract | `HASTE_JOB_WORKDIR` plus legacy `AZ_BATCH_*` aliases resolve identical paths | Shell/workflow tests | Training + imageryprep images |
| IaC | AML `Disabled`/`Existing` modes compile and pass static template checks for this rollout; `Create`-mode templates also compile locally but are not deployed (see [rollout.md](rollout.md)) | `az bicep build` (local compilation) + static template review; no `az deployment` operation performed | All three modes, locally |
| Security | No secret logging, least-privilege roles, path validation, cross-deployment isolation | Static tests + security review + live negative access test | Adapter code + IaC |
| Live AML smoke | Submit/poll/read/cancel/finalize a minimal CPU job | Dedicated validation deployment | AML adapter |
| Live GPU smoke | Each HASTE image confirms CUDA/GPU visibility on configured AML compute | Small deterministic job per image | AML compute |
| End-to-end | Each of the five workloads run on AML and compared with the Batch baseline | Full HASTE deployment | All workloads |
| Mixed backend | Concurrent explicit Batch and AML jobs, plus `auto` distribution | One deployment, both adapters enabled | Router + execution service |
| Resilience | Worker restart, default-backend change, compute scale-to-zero, throttling, missing output | Controlled integration scenarios | Execution service + adapters |
| Regression | Existing core library and API behavior | `cd hastelib && hatch run test:pytest` plus targeted API tests | Full suite |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Expected Output | Story Ref |
|---|---|---|---|---|
| UT-001 | `core/models/test_compute.py` | Destination path with `../` or leading `/` | `ValueError` before submission | US-001 |
| UT-002 | `core/models/test_compute.py` | Output pattern resolving outside job workspace | `ValueError` before submission | US-001 |
| UT-003 | `core/models/test_compute.py` | Unrecognized URI scheme on input/output | `ValueError` before submission | US-001 |
| UT-004 | `core/models/test_compute.py` | Mutable `:latest` tag on `imageReference` in a deployed profile (Batch-compatible: any other tag or an `@sha256:<digest>` reference is accepted) | `ValueError` before submission | US-001 |
| UT-004b | `core/models/test_compute.py` | Mutable `:latest`/`@latest` alias on the AML-specific `environmentReference` in a deployed profile (stricter than `imageReference`; a versioned, non-alias reference is accepted) | `ValueError` before submission | US-001, US-002 |
| UT-005 | `core/models/test_compute.py` | Credential-shaped string in `environment`/`tags` | rejected at construction | US-008 |
| UT-006 | `core/models/test_compute.py` | `ComputeJobHandle` round-trip serialization | no token/key/SAS field present | US-008 |
| UT-007 | `core/models/test_compute.py` | Legacy `TrainingJob` with only `jobId`/`taskId` | synthesized Batch `ComputeJobHandle` on load | US-004 |
| UT-008 | `core/models/test_compute.py` | Client-supplied `computeJob` on an API request payload | rejected/ignored server-side | US-004 |
| UT-009 | `core/runners/test_router.py` | Explicit backend request | routed directly, no capacity/weight logic invoked | US-003 |
| UT-010 | `core/runners/test_router.py` | `auto` with all candidates healthy | deterministic weighted rendezvous selection; same `executionId` always resolves the same way | US-003 |
| UT-011 | `core/runners/test_router.py` | `auto` with one candidate `unavailable` | filtered out; next deterministic candidate chosen | US-003 |
| UT-012 | `core/runners/test_router.py` | Explicit backend disabled/misconfigured | `BackendConfigurationError` before any provider call, no silent reroute | US-003 |
| UT-013 | `core/runners/test_execution_service.py` | Retry after indeterminate submission outcome | reconciles via deterministic provider job name, no duplicate submit | US-005 |
| UT-014 | `core/runners/test_execution_service.py` | Two workers race to submit the same `executionId` | exactly one create succeeds; the other retrieves/validates the existing job | US-005 |
| UT-015 | `core/runners/test_execution_service.py` | Config change mid-job | lifecycle calls use the persisted handle's backend, not the current default | US-004 |
| UT-016 | `core/runners/test_azure_ml.py` | Command-job construction (inputs, outputs, environment, compute, timeout, priority, spot, tags, identity) | exact expected `MLClient` call arguments (mocked) | US-002 |
| UT-016b | `core/runners/test_azure_ml.py` | Identity mapping: `AML_IDENTITY_MODE=user` (default) maps to `UserIdentityConfiguration` (the submitting/calling principal's own identity, no extra grant needed); `AML_IDENTITY_MODE=managed` maps to `ManagedIdentityConfiguration(resource_id=AML_MANAGED_IDENTITY_ID)`; `managed` without `AML_MANAGED_IDENTITY_ID` set | correct identity object per mode; `BackendConfigurationError` for `managed` with no ID configured, before any provider call | US-002, US-006, US-008 |
| UT-017 | `core/runners/test_azure_ml.py` | Status normalization from AML run states, including scaling-from-zero | mapped to correct `ComputeJobState`, `queued`/`preparing` not `failed` | US-002 |
| UT-018 | `core/runners/test_azure_ml.py` | `cancel()`/`finalize()` idempotency, repeated calls | no error on repeat; AML run history not deleted | US-002 |
| UT-019 | `core/runners/test_azure_ml.py` | Missing/invalid environment or ACR access | classified, sanitized `BackendConfigurationError`, no credential in message | US-002, US-008 |
| UT-020 | `core/runners/test_azure_batch.py` (extended) | Finalize a job whose Batch job still has other active tasks | shared Batch job is not disabled | US-001 |
| UT-021 | `core/runners/test_local.py` | Local adapter satisfies `ComputeRunner` without exposing `AZ_BATCH_*` on its public surface | conformance suite passes | US-001 |
| UT-022 | `core/processors/test_{train,inference,embedding,imagery,artifacts}.py` | Each processor builds a valid `ComputeJobSpec` and never calls `get_azure_batch_config()` | spec matches expected shape; `rg` check passes | US-001, US-007 |
| UT-023 | `core/config/test_config.py` | `RUNNER_TYPE` alias, per-workload overrides, AML settings validated only when enabled | correct resolution and conditional validation | US-003, US-006 |

### Contract (backend conformance) Tests

| ID | Scenario | Expected |
|---|---|---|
| CT-001 | Same `ComputeJobSpec` run through fake Batch, AML, and local adapters | identical `submit → get_status → read_output → cancel → finalize` behavior and state transitions |
| CT-002 | `get_capacity()` on each adapter | returns a valid `CapacitySnapshot` for every declared `(workload, resources)` combination |
| CT-003 | Every adapter's `read_output()` on a not-yet-available live progress file | returns `None`, not an exception |

### API Integration Tests

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | existing training launch endpoint | POST | Omit compute-selection field | none | 200, defaults to configured backend | US-003 |
| IT-002 | existing training launch endpoint | POST | Explicit `azure_ml` selection | AML enabled for training | 200, `computeJob.requestedBackend=azure_ml` persisted | US-003 |
| IT-003 | existing training launch endpoint | POST | Explicit backend not configured | none | 400, actionable configuration error | US-003 |
| IT-004 | existing training launch endpoint | POST | Client supplies `computeJob` runtime state | none | 400, or field silently ignored per API contract | US-004, US-008 |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | training queue | Poll after persisted AML handle | existing `TrainingJob` id | status/read routed to AML via persisted handle | US-004 |
| QT-002 | training queue | Poll after `COMPUTE_BACKEND_DEFAULT` changed | existing `TrainingJob` id | status/read still routed to originally selected backend | US-004 |
| QT-003 | inference queue | Automatic follow-on after AML training | training completion message | inference spec inherits `azure_ml` per follow-on policy, or records override reason | US-007 |
| QT-004 | artifact-packaging queue | Duplicate message delivery after submission | duplicate message | reconciled to existing execution, no duplicate provider job | US-005 |

### Container Contract Tests

| ID | Scenario | Expected |
|---|---|---|
| CC-001 | `set_dirs.sh` with `HASTE_JOB_WORKDIR` set | resolves the same paths as the legacy `AZ_BATCH_TASK_WORKING_DIR`-only path |
| CC-002 | `run_workflow.py` invoked with only legacy `AZ_BATCH_*` vars (already-published image) | still resolves correctly via adapter-exported legacy aliases |

### IaC Tests

| ID | Scenario | Expected |
|---|---|---|
| INF-001 | `az bicep build` (local compilation) on all new `aml*.bicep` modules | compiles clean |
| INF-002 | Local compilation/static template check with `amlMode=Disabled` | no AML resources are created; the Function App's `AML_*` settings (`AML_MODE`, `AML_IDENTITY_MODE`, etc.) are still emitted, with inert/empty values, not omitted |
| INF-003 | Local compilation/static template check with `amlMode=Create` (template review only — not deployed this rollout) | workspace, compute, environment, datastore, and `amlRole.bicep`'s least-privilege RBAC (AzureML Data Scientist, scoped to the queue Function App identity) are correctly defined in the template |
| INF-004 | Local compilation/static template check with `amlMode=Existing` | only application settings referencing the operator-provided workspace/compute/environment/datastore are emitted; no AML resource or RBAC template block renders, confirming pure-reference behavior |
| INF-005 | Re-run local compilation for any mode with unchanged parameters | template output is deterministic — no diff between compilations |

### Security Tests

| ID | Scenario | Expected |
|---|---|---|
| SEC-001 | Grep adapter/IaC code and logs for account keys, passwords, connection strings | none present |
| SEC-002 | Grep `ComputeJobHandle` serialization and log output for tokens/SAS/signed URLs | none present |
| SEC-003 | Cross-deployment access attempt from shared AML compute to another deployment's storage | denied at the credential boundary (live negative test) |
| SEC-004 | Dependency scan of `azure-ai-ml==1.34.1` + transitive packages | no unmitigated critical/high CVE; approved by `security`, confirmed by `security-validation` |
| SEC-005 | Bootstrap command construction with adversarial input path/URI | rejected by validation before shell command generation |

### Live Smoke Tests (validation deployment)

| ID | Scenario | Expected |
|---|---|---|
| SMOKE-001 | Minimal CPU AML job: submit, poll, read output, cancel, finalize | all lifecycle operations succeed |
| SMOKE-002 | Each HASTE workload image pulled and run on configured AML compute | CUDA/GPU visible where required; exit code 0 |

### End-to-End Tests

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Imagery preprocessing on AML | Run full imagery-prep workload on AML | Same COGs/previews/footprints/manifests/logs as Batch baseline | US-002 |
| E2E-002 | Training on AML | Run full training workload on AML | Same checkpoints, TensorBoard events, progress, logs as Batch baseline | US-002 |
| E2E-003 | Inference on AML | Run full inference workload on AML | Same output COG/GeoPackage, progress log, diagnostics as Batch baseline | US-002 |
| E2E-004 | Embedding on AML | Run full embedding workload on AML | Same embedding GeoJSON, PMTiles, sidecar, manifest as Batch baseline | US-002 |
| E2E-005 | Artifact packaging on AML | Run full artifact-packaging workload on AML | Same ZIPs and manifest as Batch baseline; runs on CPU target | US-002 |
| E2E-006 | Mixed backend | Concurrent explicit Batch + AML jobs, plus `auto` distribution, in one deployment | All complete correctly; `auto` uses both providers over a deterministic sample and never changes provider for the same `executionId` | US-003 |
| E2E-007 | Resilience | Restart Function workers mid-job; change `COMPUTE_BACKEND_DEFAULT`; scale AML compute to zero; inject throttling; simulate missing output | Correct lifecycle continuation in every case, per [design.md](design.md#edge-cases-and-failure-behavior) | US-004, US-005 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Explicit backend disabled | request `azure_ml` when `AML_MODE=Disabled` | 400 / configuration error before any provider call |
| NEG-002 | Indeterminate submission then real duplicate attempt | forced timeout + explicit re-submit | reconciliation, not a second provider job |
| NEG-003 | Cancellation races with completion | cancel called after provider already completed | final state remains `succeeded`/`failed`, not overwritten to `cancelled` |
| NEG-004 | Unknown provider status string | injected unmapped AML/Batch state | explicit mapping error raised and logged server-side, never silently `running` |
| NEG-005 | Output path collision | two executions targeting the same relative output path with incompatible metadata | rejected |
| NEG-006 | AML environment/ACR resolution missing | misconfigured environment name | sanitized error naming the environment, no credential leak |

### Performance Tests

| ID | Scenario | Target Metric | Threshold |
|---|---|---|---|
| PERF-001 | Spec construction + validation overhead per submission | added processor-side latency | negligible (in-process only, no additional network call) |
| PERF-002 | AML cold-start (scale-to-zero) vs. Batch cold-start | queue/startup time reported per backend | comparable order of magnitude; reported via telemetry, not blocking |
| PERF-003 | Capacity snapshot cache | age of served snapshot | within configured short TTL, never blocking a submission |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Small training/inference/embedding/imageryprep/artifact-packaging fixtures | Minimal but representative inputs for each workload | Synthetic / existing test fixtures | no |
| Two isolated storage containers | For the cross-deployment AML access-denied test | Synthetic | no |
| Sample legacy job documents (jobId/taskId only, no computeJob) | Compatibility/synthesis testing | Synthetic | no |

## Coverage Matrix

| User Story | Unit | Contract | API/Queue | IaC | Security | Live/E2E |
|---|---|---|---|---|---|---|
| US-001 | UT-001..004b, UT-005..006, UT-020..022 | CT-001..003 | — | — | — | — |
| US-002 | UT-004b, UT-016, UT-016b, UT-017..019 | CT-001..002 | — | — | — | SMOKE-001/002, E2E-001..005 |
| US-003 | UT-009..012, UT-023 | — | IT-001..003 | — | — | E2E-006 |
| US-004 | UT-007, UT-008, UT-015 | — | IT-004, QT-001/002 | — | — | E2E-007 |
| US-005 | UT-013, UT-014 | — | QT-004 | — | NEG-002 | E2E-007 |
| US-006 | UT-016b | — | — | INF-001..005 | — | — |
| US-007 | UT-022 | — | QT-003 | — | — | — |
| US-008 | UT-005, UT-006, UT-016b | — | — | — | SEC-001..005 | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (minimal venv) | Fast unit/model/router tests (no live cloud calls) | `PYTHONPATH=src` + pytest; mocked `MLClient`/Batch client |
| CI (conda `test` env) | Full `hatch run test:pytest` | `dev_env.yml` |
| Docker Compose local stack | Local-backend end-to-end sanity | existing `docker/docker-compose.yml` |
| Validation deployment (AML enabled) | Live smoke, GPU smoke, E2E, mixed-backend, resilience, security negative tests | `AML_MODE=Existing` (pure reference to an operator-provided AML workspace/compute/environment/datastore/identity), both Batch and AML enabled. `Create` mode is reserved for a separately approved future scenario and is not exercised live in this rollout |

## Sign-off Criteria

- [ ] All new unit and contract tests pass
- [ ] Full `hastelib` suite passes: `cd hastelib && hatch run test:pytest`
- [ ] `rg "get_azure_batch_config|AZ_BATCH_" hastelib/src/hastegeo/core/processors` returns no matches
- [ ] Bicep compiles clean and passes static template checks for all three
      AML modes (no Azure deployment operation required for this rollout)
- [ ] Live AML CPU and GPU smoke tests pass on the validation deployment
- [ ] End-to-end parity confirmed for all five workloads against the Batch baseline
- [ ] Mixed Batch/AML execution validated in one deployment
- [ ] Cross-deployment access-denied test passes on shared AML compute
- [x] `security` dependency review of `azure-ai-ml==1.34.1` complete; `security-validation` confirmed
- [ ] No secrets, tokens, or signed URLs found in logs, tags, or persisted handles
