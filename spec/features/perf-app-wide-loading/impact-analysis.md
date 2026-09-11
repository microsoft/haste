# Impact Analysis: App-Wide Loading Performance

## Contents

- [Scope](#scope)
- [Risks](#risks)
- [Security](#security)
- [Rollback](#rollback)

## Scope

| Component | Change | Severity |
|---|---|---|
| `hastegeo` | Session and representation cache logic | high |
| `hastefuncapi` | Backward-compatible bootstrap and ETag behavior | high |
| React UI | Startup, route readiness, polling, media | medium |
| Azure Functions/SWA | Existing deployments only; no new resource | low |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Cached authorization grants stale access | high | Never cache authorization decisions; load ACL per bootstrap |
| Concurrent ACL writes lose updates | high | Keep bootstrap read-only; retain explicit admin reconciliation and avoid startup writes |
| Publishing cache returns stale status | medium | TTL at most 5 seconds plus mutation invalidation |
| Parallel loading changes error order | medium | Preserve required/optional request semantics in tests |
| Map assets race their prerequisites | medium | Load control before drawing/swipe and cover failures |
| Browser budget varies by network | medium | Record cold/warm desktop/mobile profiles and API timing |
| Aborted requests are reported as failures | low | Preserve `AbortError` and suppress expected unmount errors |
| Legacy layer has no valid label pointer | medium | Fall back to one partition scan without changing stored data |
| Active-job cache briefly trails queue updates | low | TTL at most 5 seconds; never cache authorization |
| Map is disposed while SDK events fire | medium | Guard teardown, remove listeners, and test interrupted startup |

## Security

The bootstrap accepts no identity query/body parameters. Its decoded SWA
principal is trustworthy only behind trusted SWA/APIM ingress or proper signed
identity validation. Until that prerequisite is enforced, direct callers to the
public Function endpoint can supply the asserted identity header. Current ACL
checks do not authenticate that assertion; deployment remains blocked on this
existing trust-boundary issue. No secrets, CORS changes, public storage, or new
roles are introduced here.

## Rollback

The change is fully reversible. Existing `GetUserById`, `PutUser`, and
`GetPublishingProviders` endpoints remain available, and the UI can revert to
the prior startup path. Caches are process-local and contain no durable state.
No data migration or Blob cleanup is required.