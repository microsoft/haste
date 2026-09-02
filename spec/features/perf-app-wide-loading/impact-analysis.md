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

## Security

The bootstrap accepts no caller-controlled identity. It uses the decoded SWA
principal and current ACL state, and does not weaken authorization on any
sensitive endpoint. No secrets, CORS changes, public storage, or new roles are
introduced.

## Rollback

The change is fully reversible. Existing `GetUserById`, `PutUser`, and
`GetPublishingProviders` endpoints remain available, and the UI can revert to
the prior startup path. Caches are process-local and contain no durable state.
No data migration or Blob cleanup is required.