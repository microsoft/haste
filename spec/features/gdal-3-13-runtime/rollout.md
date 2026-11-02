# Rollout: GDAL 3.13 Native Runtime

## Order

1. Publish the runtime and binding wheels to `haste-binaries`. They are
   additive: nothing references them until a consumer switches.
2. Deploy to dev environments: Function Apps from build-once packages, then
   both Batch images. Collect the runtime report from every app and from one
   imagery preparation run and one training/inference run.
3. Run the UI smoke tests: tiles, labeling and results views.
4. Deploy to production only after the security reviewer approves the
   evidence.

## Rollback

- **Function Apps.** Redeploy the previous package by its recorded SHA-256.
- **Batch images.** Point the pools at the previous image digest.
- **Never relax configuration as a rollback.** A runtime that fails its
  self-check stays down until a correct artifact is deployed.

## Notes for contributors

Deploying a Function App from a branch without this change reinstalls the
old dependencies. Rebase before deploying once this lands.
