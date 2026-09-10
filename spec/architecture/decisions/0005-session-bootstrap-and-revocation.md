# ADR-0005: Session Bootstrap and Revocation

**Status:** proposed
**Date:** 2026-09-02
**Deciders:** prbatero

## Contents

- [Context](#context)
- [Options](#options)
- [Decision](#decision)
- [Consequences](#consequences)

## Context

The UI currently serializes SWA authentication, ACL loading, an Azure
management-plane user listing, an unconditional ACL rewrite, and publishing
provider discovery before rendering a route. Live dev1 telemetry shows this
shared path consumes about two seconds at the median and can exceed three
seconds.

## Options

### Keep Management-Plane Reconciliation on Every Login

- Preserves immediate comparison with SWA user assignments.
- Adds latency, management-plane availability, and an unnecessary write to
  every application load.

### Use a Read-Only Session Bootstrap

- Uses the trusted SWA principal and HASTE ACL in one API request.
- Removes stable-session writes and management-plane calls.
- Requires explicit out-of-band reconciliation for external revocation.

## Decision

Use a read-only `GetSessionBootstrap` endpoint for normal startup. The endpoint
accepts no identity input, decodes the SWA principal, loads current ACL state,
intersects trusted principal roles with ACL roles, and returns user settings
plus publishing capabilities.

Stable active users are never written during bootstrap. Inactive, pending, or
deleted users receive a roleless blocked session and are never auto-reactivated.
Sensitive routes continue to authorize independently. Management-plane
reconciliation remains an explicit administrative workflow; no automated
revocation SLA is claimed by this change.

Explicit reconciliation binds the SWA user object ID onto legacy email-only
ACL records. Once bound, runtime matching never falls back to email for that
record.

Deployment is blocked until the Function runtime endpoint is restricted to the
trusted SWA/APIM path or independently validates a signed identity. The ingress
change was explicitly deferred during implementation review.

### Components Affected

| Component | Change |
|---|---|
| `hastegeo` | Plain-data session resolution logic |
| `hastefuncapi` | Thin bootstrap HTTP wrapper |
| React UI | Replace serial startup calls with one bootstrap call |

## Consequences

- Stable startup becomes one read-only request.
- Management-plane outages no longer block every page load.
- External SWA assignment changes reach the HASTE ACL only after explicit
  administrative reconciliation.
- ACL state remains the deny-first runtime authority.
- No Azure resource, local-development service, or persistent schema changes.