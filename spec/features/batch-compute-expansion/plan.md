# Execution Plan: Batch compute expansion + multi-tenant shared GPU pools

Phases are adapted for a compute/infra + library feature — there is no UI or API
route change. See [user-stories.md](user-stories.md#agent-assignment-map) for the
agent→story mapping and [rollout.md](rollout.md) for the deployment sequence.

## Phases

### Phase 1: Design & isolation PoC — done

**Goal:** De-risk the architecture before provisioning scarce GPU pools.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Write spec (README, design, impact-analysis, user-stories, test-plan, rollout) | `backend-dev` | — | — | done |
| PoC: per-job SAS Batch I/O on a throwaway pool | `backend-dev` | — | US-003 | done |
| PoC: cross-tenant SAS access denied | `backend-dev`, `security` | — | US-003 | done |
| PoC: ACR-pull via a shared ACR-pull-only identity | `backend-dev` | — | US-001 | done |

**Exit Criteria:**
- [x] SAS Batch I/O works as a drop-in for `identity_reference`
- [x] Cross-tenant access is denied at the credential boundary
- [x] Shared-identity ACR pull authenticates

### Phase 2: Shared-pool IaC — in-progress

**Goal:** Parameterize the pool module and provision the shared pools.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Parameterize `infra/modules/batchPool.bicep` (scale/node/VNet) | `backend-dev` | — | US-001, US-005 | done |
| Add `infra/shared-pools.bicep` + `.bicepparam` (generic prefix, BYO account/ACR) | `backend-dev` | batchPool | US-001 | done |
| Create the ACR-pull-only identity + `AcrPull` grant | `backend-dev` | — | US-001 | done |
| Deploy the shared-dev pool pair (H100 + T4, scale-to-zero) | `backend-dev` | above | US-001, US-005 | done |
| Deploy the shared-demo pool pair | `backend-dev` | quota | US-001 | not-started |
| Finalize pool networking (subnet + per-tenant storage firewall) | `backend-dev` | — | US-003 | not-started |

**Exit Criteria:**
- [x] Pools created, autoscale low-priority, 0 nodes idle
- [ ] Networking model finalized for real workloads

### Phase 3: hastelib routing + per-job SAS (v2.1.0) — done

**Goal:** Capacity-aware routing + per-job SAS in the core library.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Candidate pool-id lists + flags in `config.py` | `backend-dev` | — | US-004 | done |
| `select_pool` + submit-time binding + `manage_pools` gate in `azure_batch.py` | `backend-dev` | config | US-004 | done |
| Per-job user-delegation SAS on `ResourceFile`/`OutputFile` | `backend-dev` | — | US-003 | done |
| `Storage Blob Delegator` grant in `functionApp.bicep` | `backend-dev` | — | US-003 | done |
| Update all 5 processors to pass candidate lists | `backend-dev` | above | US-004 | done |
| Unit tests in `hastelib/tests/` (`test_azure_batch_routing.py`) | `backend-dev` | above | US-003, US-004 | done |
| Pin `azure-batch==14.2.0` | `backend-dev` | — | — | done |

**Exit Criteria:**
- [x] 9 unit tests pass
- [x] All flags default to legacy behavior (no regression for existing envs)

### Phase 4: Integration & rollout — pending (gated on GPU quota)

**Goal:** Validate end-to-end on real envs, then roll out.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Obtain low-priority GPU quota increase | Platform Operator | — | US-005 | not-started |
| E2E on dev1 + dev2 (two live tenants on shared pools) | `backend-dev` | Phases 2,3 + quota | US-001..004 | not-started |
| Onboard demo environments to shared pools | Platform Operator | E2E | US-002 | not-started |
| (Confirmed) drain + delete legacy per-env pools | Platform Operator | full migration | — | not-started |

**Exit Criteria:**
- [ ] Both tenants coexist on the shared pool; cross-env access denied (E2E)
- [ ] Routing + spillover behave as designed; pools scale to zero
- [ ] CI (`hatch run test:pytest`) green

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec approved | 2026-07-14 | Signed-off spec + isolation PoC |
| Shared-dev pools live | 2026-07-14 | Pools provisioned (0 nodes, waiting on quota) |
| v2.1.0 library done | 2026-07-14 | Routing + SAS merged; unit tests green |
| E2E validated | TBD (gated on quota) | dev1 + dev2 on shared pools |
| Release | TBD | Demos onboarded to shared compute |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | Library + IaC + PoC + tests | 1, 2, 3, 4 |
| `security` | Isolation-model review | 1 |
| Platform Operator (human) | Quota, onboarding, destructive cleanup | 2, 4 |

> No `ui` or `gis` tasks — this feature has no UI or imagery-provider change.

## Resource Requirements

- **Agents:** `backend-dev` (implements), `backend-validation` (validates), `security` (isolation review).
- **Azure services:** Azure Batch (shared H100 + T4 pools), one ACR-pull-only UMI, `Storage Blob Delegator` grants. No Cosmos/Queue/SWA change.
- **GPU compute:** H100 (`Standard_NC40ads_H100_v5`, 40c) + T4 (`Standard_NC16as_T4_v3`, 16c) low-priority nodes. **Requires a low-priority GPU quota increase** before pools can scale up.
- **External data:** none.

## Open Questions

- [ ] Low-priority GPU quota increase — blocks Phase 4 scale-up.
- [ ] Preemption-safety of demo workloads on spot (retry/idempotency).
- [ ] Shared-pool networking (subnet + per-tenant storage-firewall allowlisting).
- [ ] Timing of the destructive legacy-pool cleanup (needs explicit confirmation).
