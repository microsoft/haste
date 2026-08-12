# Rollout Plan: Batch node-loss resilience

## Rollout Strategy

**Type:** big-bang (no feature flag)

The change is a strict widening of what the system tolerates: the node copy of a
file is still read first, and every non-node Batch error still propagates
exactly as before. There is no configuration surface worth flagging, and a flag
would leave the failing path in place for whoever forgot to turn it on.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` (wheel) | `hatch build -t wheel` → Function App rebuild | All Function Apps |
| `hastefuncqueues` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `hastefuncapi` | GitHub Actions `deploy-apps.yml` | Azure Functions (picks up the wheel; no code change) |

No infrastructure deployment. No Bicep, pool, or app-setting changes.

## Feature Flags

None.

## Rollout Phases

### Phase 1: dev1

- **Target:** dev1 Function Apps + SWA
- **Deployment:** merge to `main` (triggers `deploy-apps.yml`)
- **Success criteria:**
  - [ ] A new image layer on a scale-to-zero pool reaches COMPLETED
  - [ ] Function logs show the node-unavailable warning followed by a successful
        fallback, when the node does disappear
  - [ ] `<projectHash>/<taskId>/` in the outputs container contains both
        `imagery_manifest.json` and `imagery_friendly.log`
  - [ ] A deliberately broken layer (bad imagery URL) shows a readable cause
        appended below its prior progress, not a raw SDK dump
  - [ ] Training / inference / artifact jobs still complete normally
- **Rollback trigger:** any workload failing with an error that previously
  propagated, or a layer completing with an empty/incorrect manifest

### Phase 2: testing

- **Target:** testing environment
- **Success criteria:**
  - [ ] No new failure modes across a full imagery → label → train → inference run
  - [ ] Batch job/task failure rate unchanged or lower

### Phase 3: production

- **Target:** production Function Apps
- **Success criteria:**
  - [ ] Imagery layer failure rate unchanged or lower
  - [ ] No increase in queue-message processing time beyond the retry budget

## Rollback Plan

| Step | Action | ETA |
|---|---|---|
| 1 | Revert the PR on `main` | immediate |
| 2 | Redeploy via `deploy-apps.yml` | <15 min |
| 3 | Confirm imagery submission still works | <5 min |

**Cosmos data rollback required?** No — no schema or document changes.
**Blob artifacts cleanup needed?** No — the extra `imagery_friendly.log` blobs
are inert if the reader is reverted.

Reverting restores the previous behavior exactly, including the original
failure mode. Nothing written while the change was live becomes unreadable.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Expectation |
|---|---|---|
| Image layer FAILED rate | Cosmos / UI | decreases |
| Occurrences of `NodeNotReady` in function logs | Application Insights | may appear as warnings; should no longer coincide with FAILED layers |
| `is unavailable` warning count | Application Insights | indicator of how often the race actually fires — informs whether the pool itself should change |
| Queue message processing duration | Azure Functions metrics | may rise by up to the retry budget on affected messages |
| Batch task failure rate | Azure Batch metrics | unchanged (this change does not affect task execution) |

### Alerts to Configure

None new. The existing failure-rate monitoring is sufficient; this change is
expected to reduce, not add, failure signal.

## Post-Rollout Checklist

- [ ] Re-run the dev1 image layers that failed with `NodeNotReady` (they are not
      repaired retroactively — the `logs/` upload only applies to newly
      submitted tasks)
- [ ] Record the observed frequency of the node-unavailable warning, and decide
      whether the pool's deallocation policy warrants an ADR
- [ ] `docs/` updated (done as part of this change)
- [ ] Spec status moved to `released`
