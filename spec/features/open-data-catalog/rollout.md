# Rollout Plan: Open Data Catalog Explorer

## Rollout Strategy

**Type:** phased (dev1 → testing → production)
**Target date:** TBD

> Verified in the local Docker Compose stack; not yet deployed to Azure.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` | Docker rebuild (imageryprep + Function Apps) | all Function Apps + imageryprep image |
| `hastefuncapi` | `deploy-apps.yml` | Azure Functions |
| `hastefuncqueues` | `deploy-apps.yml` | Azure Functions |
| React UI | `deploy-apps.yml` | Azure Static Web Apps |

## Feature Flags

| Flag | Location | Default | Notes |
|---|---|---|---|
| (none) | — | — | No flag; the "Browse Open Data Catalog" button is additive and low-risk. A flag could gate it if desired. |

## Prerequisites (production)

| Item | Requirement |
|---|---|
| Imagery allowlist | `data.source.coop` allowed by the deployed API/downloader (ships with this change) |
| TiTiler public endpoint | `VITE_TITILER_URL` reachable from the browser (already used by the labeling tool) |
| Azure Maps | Client-ID/AAD auth configured (satellite basemap). Blank basemap works without it. |
| Ingress/APIM | Body-size + timeout headroom for chunk uploads / any TiTiler crop (the local `nginx.conf` changes are dev-only and must be mirrored on the real gateway if needed) |

## Rollout Phases

### Phase 1: Dev1 — TBD
- Merge to `main` → `deploy-apps.yml`.
- Verify: catalog lists events; add scene; draw AOI; process a layer and confirm clipped output; Planet download succeeds.

### Phase 2: Testing — TBD
- E2E scenarios (see [test-plan.md](test-plan.md)) pass; no ImageLayer metadata regressions.

### Phase 3: Production — TBD
- Health checks green; error rate stable; imagery-prep clip jobs succeed.

## Rollback Plan

| Step | Action | ETA |
|---|---|---|
| 1 | Revert PR / deploy previous commit | <15 min |
| 2 | Confirm ImageLayers process unclipped (unknown `clipBbox` ignored) | — |

**Cosmos/metadata rollback required?** No — `clipBbox` optional/additive.
**Blob cleanup?** No.

## Monitoring

| Metric | Source | Watch |
|---|---|---|
| PutLayer 400 rate | Functions metrics | spikes → bad `clipBbox`/URLs |
| imagery-prep failures | layer `statusMessage` / queue logs | download or clip errors |
| External catalog reachability | UI per-source warning banners | Vantor/Planet outages |

## Post-Rollout Checklist

- [ ] `docs/` updated (catalog usage).
- [ ] `CHANGELOG.md` updated.
- [ ] Production ingress body-size/timeout mirrored if clip-upload path is used.
