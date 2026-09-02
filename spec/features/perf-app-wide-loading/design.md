# Technical Design: App-Wide Loading Performance

## Contents

- [Architecture](#architecture)
- [Session Bootstrap](#session-bootstrap)
- [Published Datasets](#published-datasets)
- [Route Loading](#route-loading)
- [Security](#security)
- [Deferred Work](#deferred-work)

## Architecture

```text
SWA principal -> GetSessionBootstrap -> ACL processor -> bootstrap response
React route   -> cached/conditional API reads -> route content
Map route     -> route import || Maps CSS/control -> drawing || swipe -> map
```

Business logic lives under `hastegeo`; `function_app.py` remains a thin HTTP
boundary. Existing endpoints remain compatible during rollout.

## Session Bootstrap

### `GET /api/GetSessionBootstrap`

The request accepts no identity parameters. It decodes the trusted SWA client
principal and returns:

```json
{
  "user": {
    "userId": "user@example.com",
    "identityId": "entra-object-id",
    "userRoles": ["contributors"],
    "settings": {},
    "status": "Active"
  },
  "publishing": {
    "publishingEnabled": true,
    "providers": []
  }
}
```

A stable active session performs one ACL read and zero writes. It does not list
SWA users through the Azure management plane. Existing inactive, pending, or
deleted users receive a blocked session with no roles so the UI can retain its
account-status page. The bootstrap response is not an authorization token;
sensitive routes retain their own checks.

Pending invitations remain blocked until an administrator runs the explicit
user reconciliation workflow. Startup never writes the ACL or calls the Azure
management plane.

## Published Datasets

`GetPublishedDatasets` uses the existing bounded repository read behind a
process-local TTL/single-flight cache keyed by the normalized authenticated
query. The route emits an ETag and supports `If-None-Match`. Cache TTL is at
most five seconds; mutations invalidate the cache.

The UI stores ETags by query, sends conditional requests, and polls only when a
visible page contains active work and no request is in flight. Polling never
overlaps and preserves the current query.

## Route Loading

Route module import begins at the same time as map asset loading. Map control
CSS and drawing CSS load in parallel with map-control JavaScript; drawing and
swipe JavaScript load in parallel only after map control is available.

The application shell remains visible under Suspense. Data routes render a
stable loading state instead of an empty fragment. Help images use native lazy
loading and videos use `preload="none"`.

Independent Home, create/edit, and validation requests run concurrently while
preserving required versus optional failure behavior.

## Security

- Identity comes only from the decoded SWA principal; no user ID is accepted
  from query or body.
- ACL status and deletion state are checked on every bootstrap request.
- Client roles are intersected with ACL roles; role disagreement cannot grant
  access.
- Stable sessions do not write user state or call the management plane.
- Caches store data representations, not authorization decisions.
- Development fallback remains restricted to `DEVELOPMENT_MODE`.

## Deferred Work

- Moving Blob container/access-policy initialization into deployment requires
  separate SAS and provisioning coverage.
- A materialized publishing index is deferred unless cached p95 remains above
  1.5 seconds or the 1,000-record bound becomes material.
- Distributed caching, push updates, Function capacity changes, and new
  dependencies are out of scope.