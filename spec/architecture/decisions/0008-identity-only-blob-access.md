# ADR-0008: Identity-Only Blob Access

**Status:** proposed
**Date:** 2026-10-27
**Deciders:** HASTE maintainers

## Contents

- [Context](#context)
- [Options Considered](#options-considered)
- [Decision](#decision)
- [Consequences](#consequences)

## Context

The API and queue apps receive the storage account key through
`BLOB_CONNECTION_STRING`. When it is set, read links are container-scoped SAS
tokens backed by a 90-day stored access policy. Container scope means any link
reads every project's data. A user-delegation SAS cannot use a stored policy, so
identity-based signing cannot reuse this design.

## Options Considered

### Keep the key and the stored policy

- No code change.
- Leaves a long-lived key in app settings and container-wide read links.
- Keeps shared-key access enabled on the data account.

### Blob-scoped, short-lived, identity-signed tokens

- Each link reads one blob for at most an hour and is signed by the app identity.
- Revocation comes from the delegation key, so there is no policy to maintain.
- Persisted URLs stay unsigned; tokens are minted when URLs are served.

## Decision

Mint read tokens with a single helper that produces blob-scoped, read-only,
60-minute user-delegation SAS tokens. Stop creating the stored policy. Remove
`BLOB_CONNECTION_STRING` from deployed apps and keep honoring it for the local
emulator. Disable shared-key access on the data account afterwards.

## Consequences

- Links minted before the change keep working until their policy is deleted.
- Tokens are shorter-lived, so stored URLs are kept unsigned and signed when
  served; anything else must read by path or go through the proxy.
- Deployment config no longer needs the account key.
- Functions use ephemeral scratch rather than the key-backed Azure Files
  mount; multipart chunks are staged durably in Blob across requests.
- Signing requires the trusted project's storage prefix; client-editable
  label imagery is replaced by server-derived image-layer sources.
- A development-only candidate attestation path permits pre-merge testing.
  Production still requires verified packages from main.
- File resources are retained. Shared Key disablement is a separately approved
  operation after consumer and restart/persistence validation.
