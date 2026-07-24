# Test Plan: Batch compute expansion + multi-tenant shared GPU pools

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | `hastelib` routing + SAS toggle + config parsing | pytest (`hastelib/tests/`) | All new decision logic |
| Infra validation | Bicep compiles + what-if is clean | `az bicep build`, `az deployment ... what-if` | batchPool + shared-pools |
| Isolation PoC | SAS Batch I/O + cross-tenant denial on a real pool | `az batch` + user-delegation SAS | Both bets (done) |
| E2E | Two real envs (dev1 + dev2) on the shared pools | Live workflow runs | The full submit→SAS→Batch path |

> No UI, API-endpoint, or queue-message-format changes — those test levels are N/A.

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

Implemented in `tests/core/runners/test_azure_batch_routing.py` (9 tests, passing):

| ID | Module | Scenario | Expected Output | Story Ref |
|---|---|---|---|---|
| UT-001 | `runners/azure_batch.py` | `select_pool` with a single candidate | returns it, no API calls | US-004 |
| UT-002 | `runners/azure_batch.py` | `select_pool` with empty list | falls back to bound pool | US-004 |
| UT-003 | `runners/azure_batch.py` | preferred busy, second has idle node | spills over to the idle pool | US-004 |
| UT-004 | `runners/azure_batch.py` | first candidate has an idle node | returns the first (preferred) | US-004 |
| UT-005 | `runners/azure_batch.py` | no candidate has an idle node | returns preferred (scales/queues) | US-004 |
| UT-006 | `runners/azure_batch.py` | legacy mode (`use_sas=false`) | `_blob_identity()` = pool identity; URL untouched | US-003 |
| UT-007 | `runners/azure_batch.py` | SAS mode (`use_sas=true`) | `_blob_identity()` = None; URL gets SAS | US-003 |
| UT-008 | `runners/azure_batch.py` | `_maybe_sas` on empty URL | no-op | US-003 |
| UT-009 | `core/config.py` | candidate lists split + trimmed; unset → single-id fallback; flags | correct lists + `use_sas`/`manage_pools` | US-004 |

### Infra Validation

| ID | Scenario | Expected |
|---|---|---|
| INF-001 | `az bicep build infra/modules/batchPool.bicep` | compiles clean |
| INF-002 | `az bicep build infra/shared-pools.bicep` (via deploy) | compiles clean |
| INF-003 | `what-if` of `shared-pools.bicepparam` against live pools | no real change (Batch pool "Modify" is a known what-if false positive; live formula byte-matches) |

### Isolation PoC (done — see design.md, "Data isolation → Validation")

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| POC-001 | SAS-based Batch I/O | task with SAS `ResourceFile` + `OutputFile`, no `identity_reference` | task exit 0; output blob written via SAS |
| POC-002 | Cross-tenant isolation | tenant-A SAS reading tenant-B container | `BlobAccessDenied` (UserError) |
| POC-003 | Shared-identity ACR pull | pool with ACR-pull-only UMI prefetches the real image | authenticates + downloads (disk-size artifact on the cheap test VM only) |

### End-to-End Tests (dev1 + dev2, gated on GPU quota)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Two live tenants on shared pools | 1. Point dev1 + dev2 at `<prefix>-shared-dev-*` with `USE_SAS=true`, `MANAGE_POOLS=false` 2. Run training + inference from each | Both tenants' jobs coexist; each reads/writes only its own storage | US-001, US-002, US-003 |
| E2E-002 | Capacity-aware routing | Submit training (H100-first) + inference (T4-first); saturate one tier | Preferred tier used; spillover when preferred has no idle node | US-004 |
| E2E-003 | Scale-to-zero | Leave pools idle | Pools return to 0 nodes | US-005 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | SAS mode without `Storage Blob Delegator` | env with `USE_SAS=true`, no grant | `getUserDelegationKey` fails fast with a clear auth error |
| NEG-002 | Candidate pool does not exist | bad pool id in the list | capacity check catches `BatchErrorException`, tries next candidate |
| EDGE-001 | `manage_pools=true` against an autoscale pool | legacy resize path | (documented) resize fails on autoscale — hence `manage_pools=false` for shared pools |
| EDGE-002 | Spot node preempted mid-task | low-priority preemption | Batch reschedules the task (workload must be retry-safe) |

### Performance Tests

| ID | Scenario | Target Metric | Threshold |
|---|---|---|---|
| PERF-001 | Submit-time pool selection overhead | added latency per submit | < ~1s (1 `pool.get` per candidate; cached SAS key) |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Two tenant storage containers | Distinct blobs per tenant for isolation test | Synthetic | no |
| Small input blob | Read by the Batch task | Synthetic | no |

## Coverage Matrix

| User Story | Unit | Infra | PoC | E2E | Perf |
|---|---|---|---|---|---|
| US-001 | — | INF-002/003 | — | E2E-001 | — |
| US-002 | UT-009 | — | — | E2E-001 | — |
| US-003 | UT-006/007/008 | — | POC-001/002 | E2E-001 | — |
| US-004 | UT-001..005 | — | — | E2E-002 | PERF-001 |
| US-005 | — | INF-001 | POC-003 | E2E-003 | — |
| US-006 | — | — | — | (manual) | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (minimal venv) | Unit tests (no geo/ML deps) | `azure-batch==14.2.0` + pytest; `PYTHONPATH=src` |
| CI (conda `test` env) | Full `hatch run test:pytest` | `dev_env.yml` |
| dev1 + dev2 | E2E on shared pools | `USE_SAS=true`, `MANAGE_POOLS=false`, `*_POOL_IDS`=shared |

## Sign-off Criteria

- [x] All new unit tests pass (9/9)
- [x] Bicep compiles clean; shared-pools what-if shows no real drift
- [x] Isolation PoC passes (SAS I/O + cross-tenant denial + ACR pull)
- [ ] E2E on dev1 + dev2 passes (gated on low-priority GPU quota)
- [ ] Full `hatch run test:pytest` green in CI
- [ ] Component Governance scan clean (`azure-batch` pin only)
