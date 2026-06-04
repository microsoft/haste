# Rollout Plan: [Feature Title]

## Rollout Strategy

**Type:** big-bang | phased | canary | feature-flag
**Target date:** [YYYY-MM-DD]

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` | pip install / Docker rebuild | All Function Apps |
| `hastefuncapi` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `hastefuncqueues` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `titilerfuncapi` | GitHub Actions `docker-build-and-push.yml` | Container |
| React UI | GitHub Actions `deploy-apps.yml` | Azure Static Web Apps |

## Feature Flags

| Flag Name | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| | `hastefuncapi` app setting / UI env var | off | | yes / no |

## Rollout Phases

### Phase 1: Dev1 Environment — [date]

- **Target:** SWA `dev1` environment
- **Duration:** [time before expanding]
- **Deployment:**
  1. Merge PR to `main` (triggers `deploy-apps.yml`)
  2. Verify in dev1 SWA: [dev1 URL]
- **Success criteria:**
  - [ ] API endpoints respond correctly
  - [ ] Queue workers process messages
  - [ ] UI renders feature
  - [ ] Docker Compose stack works
- **Rollback trigger:** [conditions]

### Phase 2: Testing Environment — [date]

- **Target:** SWA `testing` environment
- **Duration:** [time before full production]
- **Success criteria:**
  - [ ] E2E test scenarios pass
  - [ ] Performance thresholds met
  - [ ] No Cosmos data corruption
- **Rollback trigger:** [conditions]

### Phase 3: Production — [date]

- **Target:** Production SWA + Function Apps
- **Federated credentials:** `fed-cred-main.json` (GitHub Actions OIDC)
- **Success criteria:**
  - [ ] All health checks green
  - [ ] Error rate stable
  - [ ] User feedback positive
- **Feature flag cleanup:** Remove flag by [date]

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Disable feature flag (if applicable) | | immediate |
| 2 | Revert PR / deploy previous commit | | <15 min |
| 3 | Verify Cosmos data integrity | | |
| 4 | Verify queue processing resumed | | |
| 5 | Verify UI fallback works | | |

**Cosmos data rollback required?** yes / no — [describe if yes]
**Blob artifacts cleanup needed?** yes / no — [describe if yes]

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| API error rate | Azure Functions metrics | | |
| Queue depth | Azure Queue Storage metrics | | |
| API p99 latency | Application Insights | | |
| Batch job failures | Azure Batch metrics | | |
| Tile serving errors | `titilerfuncapi` logs | | |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| | | P1 / P2 / P3 | [team / channel] |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Pre-deploy | Deployment plan |
| Disaster analysts | | Post-deploy | Feature available |
| Partners (if applicable) | | At GA | Usage instructions |

## Post-Rollout Checklist

- [ ] Feature flag cleaned up
- [ ] Temporary monitoring removed
- [ ] `docs/` documentation updated
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`)
- [ ] Docker Compose stack verified
- [ ] `CHANGELOG.md` updated
- [ ] Retrospective scheduled (if applicable)
