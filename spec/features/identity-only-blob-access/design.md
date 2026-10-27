# Design: Identity-Only Blob Access

## Current behavior

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
- Only blobs in the app's own account and data container are signed; provider
  and other-account URLs pass through unchanged.
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

1. Merge code; the setting is still present, so behavior is unchanged except the
   token shape.
2. Remove `BLOB_CONNECTION_STRING` from the deployment config; deploy to dev1;
   exercise upload, imagery, labeling, training, inference, downloads and
   publishing.
3. Repeat for dev2, then production.
4. Delete the stored policy, then disable shared-key access on the data account
   in a separate change, one environment at a time.

Rollback: re-add the setting (code still honors it) and re-enable shared-key
access.
