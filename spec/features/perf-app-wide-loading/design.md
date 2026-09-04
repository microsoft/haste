# Technical Design: App-Wide Loading Performance

## Contents

- [Architecture](#architecture)
- [Session Bootstrap](#session-bootstrap)
- [Published Datasets](#published-datasets)
- [Route Loading](#route-loading)
- [Labeling Workspace](#labeling-workspace)
- [Active Jobs](#active-jobs)
- [Cancellation and Loading Ownership](#cancellation-and-loading-ownership)
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

## Labeling Workspace

### `GET /api/GetLabelingWorkspace`

The route requires `projectId` and `imageLayerId`. It returns the one label
project, target image layer, project event types, and primary classes required
by the standard Labeling Tool. Project and image-layer reads overlap. The label
project is loaded directly through the image layer's existing `labelProjectId`;
legacy layers without a usable pointer fall back to one partition scan.

The UI starts this request at the same time as the route-specific Azure Maps
control and drawing assets. It displays one route-owned staged workspace loader
until data, map readiness, drawing controls, and the first stable map frame are
ready. The map starts at the workspace bounds without an animated camera flight
and is disposed if navigation interrupts initialization.

## Active Jobs

### `GET /api/GetActiveJobs`

The route returns a compact list of active imagery, training, and inference
jobs. It reads the project summary once, loads only image-layer and model
partitions for candidate projects, and excludes labels, validation records,
artifacts, and terminal work. A short process-local single-flight cache bounds
repeat work; ETags support empty `304` responses.

The Dashboard makes one conditional request instead of one
`GetProjectDetails` request per project. Polls run only while visible, never
overlap, and abort on route unmount. Dashboard content does not wait for the
optional model catalog or active-jobs widget.

## Cancellation and Loading Ownership

Route initialization uses route-local loading state. The global blocking
overlay remains reserved for explicit user actions such as save, delete, and
publish. A Suspense fallback is suppressed while that blocking overlay is
visible so only one page-level status surface is exposed.

GET helpers accept an `AbortSignal`. Dashboard, active-job, and Labeling Tool
requests abort when their owning route unmounts. Late completions cannot clear
another route's loading state or mutate an unmounted component.

## Security

- Identity comes only from the decoded SWA principal; no user ID is accepted
  from query or body.
- ACL status and deletion state are checked on every bootstrap request.
- Client roles are intersected with ACL roles; role disagreement cannot grant
  access.
- Stable sessions do not write user state or call the management plane.
- Caches store data representations, not authorization decisions.
- Both additive read routes require an active ACL-backed application role.
- Development fallback remains restricted to `DEVELOPMENT_MODE`.

## Deferred Work

- Moving Blob container/access-policy initialization into deployment requires
  separate SAS and provisioning coverage.
- A materialized publishing index is deferred unless cached p95 remains above
  1.5 seconds or the 1,000-record bound becomes material.
- Distributed caching, push updates, Function capacity changes, and new
  dependencies are out of scope.