# Rollout: GDAL Deferral Compensating Controls

## Strategy

Single coordinated change merged to `main`, then deployed via the normal
pipeline. No feature flag is required: the controls are safety constraints
with generous, env-tunable limits, and the driver allowlist is validated by
tests + an imagery smoke before merge. Container images pick up `GDAL_SKIP`
on the next build/deploy.

## Sequencing

1. Merge `hastegeo` changes (`gdal_security.py` + wiring + boundaries).
2. Rebuild `imageryprep` and `training` images (they bake `hastegeo` and now
   set `GDAL_SKIP`); publish a new `hastegeo` wheel if cutting a release.
3. Deploy API; redeploy containers.

## Configuration at rollout

| Key | Default | Action |
|---|---|---|
| `HASTE_MAX_UPLOAD_BYTES` | 5 GiB | Edit the GitHub Environment variable, then run `Update Size Limits` |
| `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES` | 8 GiB | Edit the GitHub Environment variable, then run `Update Size Limits` |
| `PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES` | 512 MiB | Bound combined assessment input files within API memory capacity |
| `GDAL_SKIP` | `HDF4 HDF4Image HDF5 HDF5Image netCDF` | set in Dockerfiles; do not unset |

## Validation post-deploy

- First deploy a hastegeo wheel containing cap forwarding and assessment
  configuration, plus both apps' `GetEffectiveLimits` routes. The update workflow
  cannot install these prerequisites.
- Dry-run the Environment variables, apply, and inspect stored values and HTTP
  samples. For local `azd`, synchronize the same-named decimal-byte variables
  before provisioning. Redeploy and check that the desired caps persist.
- Inspect a newly submitted imagery Batch task's environment and confirm
  bounded download behavior. Existing tasks retain their submitted caps.
- Run a real image-layer prep end-to-end (mosaic → COG → footprints) and
  confirm success.
- Confirm an oversized/wrong-type upload returns 400.
- Confirm startup logs show the disabled-driver count.

## Rollback

- Revert the PR (pure code + Dockerfile env). No data migration, so rollback
  is immediate and safe. If only the download/upload limits are too strict,
  restore the desired GitHub Environment variables and rerun `Update Size Limits`
  without redeploying code. Missing or blank variables restore defaults. Review
  per-app output after partial failures; there is no automatic cross-app rollback.

See the [operator procedure](../../../docs/configuration.md#ingestion-size-limits).

## Monitoring

- WARNING logs for size/type/redirect rejections (watch for false positives
  after deploy).
- Startup driver-disable log line present in imageryprep/training containers.

## Exit of the underlying exception

These controls are compensating, not a fix. The GDAL exception in
`known-vulnerabilities.md` Root Cause C closes when a trusted GDAL 3.13+ pip
wheel (or a deployment-model change removing the wheel dependency) lands.
Reviewed weekly per `docs/triage-process.md`.
