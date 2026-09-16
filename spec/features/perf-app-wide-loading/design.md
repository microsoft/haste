# Technical Design: App-Wide Loading Performance

## Contents

- [Route Loading](#route-loading)
- [Cancellation and Loading Ownership](#cancellation-and-loading-ownership)

## Route Loading

Route module import begins at the same time as map asset loading. Map control
CSS and drawing CSS load in parallel with map-control JavaScript; drawing and
swipe JavaScript load in parallel only after map control is available.

The application shell remains visible under Suspense. Data routes render a
stable loading state instead of an empty fragment. Help images use native lazy
loading and videos use `preload="none"`.

Independent Home, create/edit, and validation requests run concurrently while
preserving required versus optional failure behavior.


## Cancellation and Loading Ownership

Route initialization uses route-local loading state. The global blocking
overlay remains reserved for explicit user actions such as save, delete, and
publish. A Suspense fallback is suppressed while that blocking overlay is
visible so only one page-level status surface is exposed.

GET helpers accept an `AbortSignal`. Dashboard, active-job, and Labeling Tool
requests abort when their owning route unmounts. Late completions cannot clear
another route's loading state or mutate an unmounted component.
