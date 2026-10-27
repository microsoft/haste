# Feature: Identity-Only Blob Access

**Status:** in-review
**Author:** HASTE engineering team
**Date:** 2026-10-27
**Target Release:** next
**Priority:** P1
**Work Item:** —

## Summary

The API and queue apps carry the storage account key in an app setting
(`BLOB_CONNECTION_STRING`). Its presence also selects the shared-key code path,
which mints container-wide read tokens backed by a 90-day stored access policy.
This feature removes the key from app settings, signs read tokens with the app's
managed identity, and scopes each token to one blob with a short expiry. Once no
caller depends on the key, shared-key access can be disabled on the data
storage account.

## Motivation

- A container-scoped token appended to one blob's URL is worth more than the URL
  suggests. Data for every project lives in one container separated only by a
  path prefix, so container-wide read is service-wide read.
- A user-delegation SAS cannot reference a stored access policy, so the policy
  path cannot work once the key is gone.
- The key in app settings is a long-lived credential that can be read by anyone
  with access to the app configuration.
- Every other storage consumer already falls back to the managed identity when
  the connection string is empty. Two byte-range helpers in `utils/blob.py` do
  not.

## Success Criteria

- [ ] API and queue apps run without `BLOB_CONNECTION_STRING` in Azure.
- [ ] Read tokens are blob-scoped (`sr=b`), read-only, expire within an hour and
      reference no stored access policy.
- [ ] Tokens minted in Azure are user-delegation SAS (signed by the identity).
- [ ] The container read policy is no longer created or maintained.
- [ ] The docker dev stack, which points `BLOB_CONNECTION_STRING` at the local
      emulator, keeps working unchanged.
- [ ] Browser downloads and published datasets keep working in dev1 with the
      setting removed.
- [ ] Shared-key access can then be disabled on the data storage account
      (separate, gated change).

## Out of Scope

- The Azure Files account backing the Functions `/data` mount, which needs a key.
- Batch account key and communication-service connection string.
- The Batch auto-storage account.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/.../utils/blob_sas.py` | New helper that mints blob-scoped read tokens |
| `hastelib/.../utils/blob.py` | Byte-range and download helpers fall back to the identity |
| `hastelib/.../data_layer/azure_blob_storage_data_layer.py` | Uses the helper; stops creating the container policy |
| `hastelib/.../artifact_storage/azure_blob_artifact_storage.py` | Same |
| `infra/modules/functions.bicep`, `.github/scripts/deploy_apps.sh` | Stop setting `BLOB_CONNECTION_STRING` |

Related: [design.md](design.md),
[ADR-0008](../../architecture/decisions/0008-identity-only-blob-access.md).
