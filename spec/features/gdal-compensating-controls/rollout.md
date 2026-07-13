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
| `HASTE_MAX_UPLOAD_BYTES` | 5 GiB | leave default unless prod imagery is larger |
| `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES` | 8 GiB | tune to the largest legitimate COG |
| `GDAL_SKIP` | `HDF4 HDF4Image HDF5 HDF5Image netCDF` | set in Dockerfiles; do not unset |

## Validation post-deploy

- Run a real image-layer prep end-to-end (mosaic → COG → footprints) and
  confirm success.
- Confirm an oversized/wrong-type upload returns 400.
- Confirm startup logs show the disabled-driver count.

## Rollback

- Revert the PR (pure code + Dockerfile env). No data migration, so rollback
  is immediate and safe. If only the download/upload limits are too strict,
  raise the env knobs without redeploying code.

## Monitoring

- WARNING logs for size/type/redirect rejections (watch for false positives
  after deploy).
- Startup driver-disable log line present in imageryprep/training containers.

## Exit of the underlying exception

These controls are compensating, not a fix. The GDAL exception in
`known-vulnerabilities.md` Root Cause C closes when a trusted GDAL 3.13+ pip
wheel (or a deployment-model change removing the wheel dependency) lands.
Reviewed weekly per `docs/triage-process.md`.
