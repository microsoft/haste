# Rollout: Common Prediction Results

## Deploy

Merge the reviewed footprint change first, then this feature, then the
versioned editor. Deploy the updated training image with the API/core/UI so
new standard inference jobs produce attributes before completion.

## Existing Results

No automatic backfill occurs on a GET or on opening the results page. Rerun
interactive prediction or standard inference to produce a missing results
sidecar. Existing raw downloads remain available. Missing layer geometry uses
the existing footprint-tiling recovery path, not a prediction-prep queue.

## Rollback

Roll back application images/UI together. The additive metadata and sidecar
artifacts may remain in storage; do not delete project data or rerun `data-init`.
Changes to the user's local Compose stack are outside this implementation task.
