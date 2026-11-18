# Design: Identity-Only Blob Access

## Contents

- [Baseline behavior](#baseline-behavior)
- [Target behavior](#target-behavior)
- [Risks](#risks)
- [Rollout](#rollout)

## Baseline behavior

| Path | With connection string | Without it |
|---|---|---|
| Queue client, blob data layer, artifact store, publishing lease | Account key | `DefaultAzureCredential` + account URL |
| `download_blob_to_tempfile`, `read_blob_range` | Account key | **Fails** (`A connection string or account URL is required`) |
| Read links (`get_file_remote_path`, `get_download_url`) | Container SAS on a 90-day stored policy, signed with the key | Container SAS naming the same policy, signed with a delegation key (rejected by the service) |

## Target behavior

### Credential selection

`utils/blob.py` selects the client in one place: the connection string when set
(the local emulator), otherwise `BLOB_ACCOUNT_URL` with the managed identity. If
neither is set it raises a `ValueError` naming both settings.

### Read tokens

One helper, `blob_read_sas`, builds every link minted for clients:

- scope: the single blob (`sr=b`), read-only;
- expiry: 60 minutes, start backdated 5 minutes for clock skew;
- signing: a user-delegation key when running against Azure; the account key
  only for the local emulator;
- no stored access policy.

The data layer and the artifact store both call it so they cannot drift.

### Stored policy

The container read policy (`image-r-policy`) is no longer created or refreshed.
Re-creating it on startup would undo any operational deletion, and deletion is
the way tokens signed under it are revoked.

### Persisted URLs

Tokens last an hour, so a token must never be the only way to reach a stored
blob. Stored image-layer and label-tile URLs are kept unsigned and a fresh
per-blob token is minted when a URL is handed out:

- Label tile URLs embed the blob URL without a query, and label generation signs
  only around its own raster read.
- The label project, labeling workspace, project details (previews) and
  visualizer responses sign at response time. Signing replaces any older query,
  so legacy stored URLs that carry a policy token keep working after the policy
  is deleted.
- Only blobs in the app's own account and data container are signed.
  Project-owned links must also match the server-derived project hash prefix.
  A foreign Azure account/container or out-of-project link fails before signing.
  Supported external provider URLs pass through unchanged outside project-owned
  response materialization.
- Label-project imagery is client-editable, not an authorization source.
  Rebuild tile sources from the loaded ImageLayer and configured TiTiler endpoint,
  after checking the project/layer linkage. Preserve upstream's existing storage
  layout; do not introduce Community partner prefixes.

### Ephemeral Functions storage

After a compatible package is deployed and validated, explicitly enable
`keylessAppCutover` to remove the Azure Files `/data` mount and connection
string. The default retains legacy settings during prerequisite provisioning.
Persist the enabled flag so a later IaC deployment cannot restore legacy
settings. Functions then use `/tmp` for disposable scratch and local log copies;
Blob remains durable storage and Application Insights is the operational log sink.

Multipart upload state must live in Blob staged blocks, not local chunk files.
Validate the first chunk's declared format before staging; account for all
staged blocks when enforcing size limits and finalize only when all expected
blocks exist. Retries and requests handled by another instance must work without
the first instance's filesystem. Serialize staging, commit and cancellation with
a lease on the destination blob, and pass the lease to each write so an expired
holder cannot modify the upload. Retain the File account/share for rollback and
inspection; do not delete data.

### Storage posture and RBAC

The shared worker identity gets Blob Data Contributor on the application data
container and Blob Delegator on its account. Keep the system-assigned Functions
host roles and TiTiler isolation unchanged. Deploy replacement assignments under
new deterministic IDs; do not change a role definition on an existing assignment.
Incremental deployment retains old account-level Owner assignments, so inspect
and explicitly retire those exact grants after access validation. Retire the
obsolete File-account Blob Owner grant separately, without deleting File data.

Anonymous Blob access is denied explicitly. Shared Key flags remain compatibility
gates (`allowMainSharedKeyAccess` and `allowFileSharedKeyAccess`, initially true).
An initial deployment does not disable accounts. After separately approved
cutovers, persist false values in the environment's IaC parameter source and
verify that subsequent deployments keep them false.

### Candidate deployment

Permit an explicit maintainer-dispatched candidate package attestation on a
repository branch for development validation only. Verify the build workflow,
event, source SHA/ref, checksums and attestation before Azure login. Non-main
deployments may target only dev1. Production continues to require main-signed
packages. Runtime-wheel publishing conditions do not change.

### Long sessions

Tile URLs stop working when their token expires. Label responses include
`tileCredentialExpiresAt`, and the labeling tool, interactive labeler and
building validation re-request the labeling data shortly before that time (and
when the tab regains focus). Only the imagery URLs of the existing map layers
are replaced, so drawn labels, selections and the loaded model are untouched.
A failed refresh keeps the current imagery, retries, and shows a banner with
retry and reload actions. The visualizer does the same for the displayed
prediction version: `GetVisualizerResults` returns `tileCredentialExpiresAt`,
and shortly before it the page re-requests that same version and swaps only
the four tile layers' URLs on both maps. The map is not rebuilt (the scene key
ignores the token), results and edits are untouched, and switching versions
discards any refresh still in flight.
- The tile service has no grant on the data account, so the nested token in the
  tile URL is its only access; this is why signing happens per response.

Other persisted URLs (`labelsUrl`, `embeddingsGeoJSONUrl`,
`featuresSidecarUrl`) are never used with their token in Azure: the UI goes
through the identity-authenticated storage proxy, and Functions and Batch read
by blob path.

## Risks

| Risk | Mitigation |
|---|---|
| A caller still needs the key | Tests per path; dev1 run with the setting removed before any other environment |
| Existing 90-day links stop working once the policy is deleted | Deleted deliberately and only after dev1 validation; response-time signing replaces tokens on stored URLs |
| An endpoint returns a stored URL without signing it | Dev1 exercise of labeling, visualizer and project views before the policy is deleted |

## Rollout

1. Validate the attested dev1 candidate before merging. Apply prerequisite roles
   only with approval; drain existing multipart uploads before scratch cutover.
2. Deploy compatible packages through Actions. Only after publication succeeds,
   remove the obsolete Blob connection setting and existing HASTE File mount.
   Exercise upload, imagery, labeling, training, inference, downloads and publishing.
3. After review and dev1 acceptance, merge and promote main through dev1, dev2,
   then production, with approval for each stage.
4. Retire legacy policies/roles and disable Shared Key only in separately approved
   stages, one eligible account at a time. Retained File storage has its own gate.

Before each live stage, record nonsecret package/image/mount/RBAC rollback
metadata. Restoring a key-dependent version after disablement requires explicit
approval to re-enable Shared Key. Revoke the legacy policy only after consumers
are migrated; code rollback does not automatically restore revoked tokens.

See [rollout.md](rollout.md) for separate compatibility and disablement gates.
