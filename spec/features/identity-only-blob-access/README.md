# Feature: Identity-Only Blob Access

**Status:** in-progress
**Author:** HASTE engineering team
**Date:** 2026-10-27
**Target Release:** next
**Priority:** P1
**Work Item:** —

## Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Success Criteria](#success-criteria)
- [Out of Scope](#out-of-scope)
- [HASTE Components Affected](#haste-components-affected)

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
- [ ] Signing is constrained to the requested project's storage prefix and
      labeling tiles are rebuilt from authoritative image-layer records.
- [ ] Functions use ephemeral scratch, with durable chunk uploads in Blob and
      no key-backed Azure Files mount.
- [ ] Candidate packages can be deployed to development with verified
      provenance, without permitting non-main production deployments.

## Out of Scope

- Batch account key and communication-service connection string.
- The Batch auto-storage account.
- Community-specific partner tenancy and private-network provisioning.
- Deleting retained Azure Files data or disabling keys without a consumer audit.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/.../utils/blob_sas.py` | New helper that mints blob-scoped read tokens |
| `hastelib/.../utils/blob.py` | Identity reads, project-scoped signing and delegation-key lifetime/cache |
| `hastelib/.../data_layer/azure_blob_storage_data_layer.py` | Unsigned metadata locations and durable multipart Blob staging; no stored policy |
| `hastelib/.../artifact_storage/azure_blob_artifact_storage.py` | Same |
| `hastelib/.../processors/labels.py`, `loading.py`, `visualizer.py` | Trusted response-only URL materialization |
| `hastelib/.../processors/uploader.py` | Bounded remote chunk state, finalization and cancellation |
| `ui/src/util/tileCredentialRefresh.js` | In-place refresh with malformed-response rejection |
| `infra/modules/{storage,functionApp,functions}.bicep`, `.github/scripts/deploy_apps.sh` | Keyless app settings, scratch/mount reconciliation, staged account flags and RBAC |
| `.github/workflows/{deploy-apps,gdal-runtime-build}.yml` | Attested development candidates; main-only production trust |

Related: [design.md](design.md),
[ADR-0008](../../architecture/decisions/0008-identity-only-blob-access.md).

Execution: [plan.md](plan.md), [user-stories.md](user-stories.md),
[impact-analysis.md](impact-analysis.md), [test-plan.md](test-plan.md),
[rollout.md](rollout.md).
