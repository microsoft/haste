# UI Lifecycle Optimization Design

## HTTP Cancellation

The shared API helpers accept an optional final `RequestInit` argument and
forward it to `fetch`. Route effects create an `AbortController`, pass its
signal to read operations, and abort it from cleanup. The API helpers preserve
`AbortError` so callers can distinguish navigation cleanup from failures.

Mutation helpers remain compatible with their existing signatures. A caller
may pass a signal explicitly, but navigation does not automatically cancel a
mutation after the server may have accepted it.

## Polling

Polling starts only after the initial read. Each poll checks document
visibility and skips execution while another read is active. Effect cleanup
clears the interval and aborts its current read.

## Map Resources

Map-owning routes mark initialization as cancelled during cleanup. They
dispose swipe controls before disposing primary and secondary map instances.
Late async initialization checks the cancellation state before creating or
updating resources.

## Route Loading

`AppBody` uses `lazy` imports for route-level components and a shared
`Suspense` fallback. Authentication and authorization continue to gate route
creation before lazy modules load.

## Validation

- Unit tests verify `AbortSignal` forwarding and `AbortError` preservation.
- Existing UI tests verify unaffected helper behavior.
- The production build must succeed and emit multiple JavaScript chunks.
- ESLint is run and any failures introduced by this change are fixed.
