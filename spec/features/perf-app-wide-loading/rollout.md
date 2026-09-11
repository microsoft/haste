# Rollout Plan: App-Wide Loading Performance

## Contents

- [Strategy](#strategy)
- [Dev1 Validation](#dev1-validation)
- [Monitoring](#monitoring)
- [Rollback](#rollback)

## Strategy

Use phased deployment to the existing dev1 Function App and Static Web App.
Do not deploy `GetSessionBootstrap` until the public Function runtime endpoint
is restricted to the trusted SWA/APIM ingress path. That infrastructure change
was deferred and is not part of this branch.

## Dev1 Validation

1. Complete and validate the Function ingress prerequisite.
2. Deploy API and UI from the same tested commit.
3. Run the authenticated Playwright matrix across every route.
4. Compare Application Insights endpoint p50/p95 and request counts with the
   `1.0.40rc3` baseline.
5. Hold for one normal usage cycle before wider deployment.

Rollback if authentication failures rise, any route exceeds five seconds p95,
or publishing status freshness exceeds ten seconds.

## Monitoring

| Signal | Baseline | Gate |
|---|---:|---:|
| Bootstrap p95 | Legacy chain about 3 s | <1 s |
| Published datasets p95 | 1.89 s post-deploy | <0.75 s warm |
| Project details p95 | 2.27 s post-deploy | <=3 s |
| Labeling workspace p95 | Not previously measured | <1 s |
| Active jobs p95 | N project-detail requests | <1 s warm |
| API failures | 0 for evaluated endpoints | No increase |
| Route content-ready p95 | Not previously measured | <=3 s |

## Rollback

Redeploy the previous API/UI commit together. Existing endpoints and data
remain compatible, and process-local caches disappear on restart. No persistent
data repair is required.