# Rollout — Polygon training workflow sync

## Two artifacts, deployed separately

This is the part most likely to cause confusion, because "redeploying the dev
environment" usually means the Function Apps and **does not rebuild the
training image**.

| Change | Ships via | Artifact | Consumed by |
|---|---|---|---|
| `docker/training/code/**` | `docker-build-and-push.yml` (triggers on that path) | training image, pinned by `AZURE_BATCH_DOCKER_IMAGE` | Batch tasks |
| `hastelib/**` | `deploy-apps.yml` | `hastegeo` wheel | `hastefuncapi`, `hastefuncqueues` |

Config generation runs in **`hastefuncqueues`**, not `hastefuncapi` — a deploy
covering only the API app changes nothing.

### The failure mode of a partial deploy

An old training image accepts a new config without complaint:
`use_constraint_loss` was already a required key in its `_DEFAULT_CONFIG`, and
`_validate_config` ignores keys it does not know. So the job runs and silently
uses the **old** loss.

Confirm the image tag was built from a commit containing this branch's
`docker/training/code/**`:

```bash
az functionapp config appsettings list -n <queues-app> -g <rg> \
  --query "[?name=='AZURE_BATCH_DOCKER_IMAGE'].value" -o tsv
```

The startup log is the decisive check — this line exists only in the new image:

```
Constraint loss enabled: penalizing P(Damaged Building=3) at No Damage (=5) pixels
```

If `use_constraint_loss` is `true` in the generated config but that line is
absent from the task's stdout, the container is stale.

## Retraining is required

**Models trained before this change cannot be salvaged by an inference-side
fix.** Under the previous objective the training signal at "No Damage" pixels
was genuinely absent, so what the model learned there is arbitrary. Any project
with a **No Damage** class needs a retrain, and its existing damage reports
should be treated as unreliable.

If the mask rasterization bug also applied (see
[test-plan.md](test-plan.md)), the scope is wider: any multi-class model would
have trained on background-only masks.

## Backwards compatibility

| Surface | Behavior |
|---|---|
| Existing configs | Unaffected. Every new key is optional and defaults to previous behavior. |
| Projects without a `No Damage` class | Unaffected. `should_use_constraint_loss` returns false and the channel layout is unchanged. |
| Projects with `No Damage` **not last** | Constraint loss stays off, reason logged. Trains as before. To opt in, reorder the project's classes. |
| Existing checkpoints | Load unchanged. `load_from_checkpoint` replays `num_classes` from the checkpoint, so a pre-change model keeps its own channel count. |
| Clustering | Off unless `labels.cluster_size_in_meters` is set. |

## Staged rollout

1. **Build the training image** from this branch and point a dev environment's
   `AZURE_BATCH_DOCKER_IMAGE` at it.
2. **Deploy the wheel** to `hastefuncqueues` (and `hastefuncapi`).
3. **Retrain** a project that has a `No Damage` class, ordered last. Confirm
   from the task stdout that the constraint loss engaged, and from the
   prediction raster that no pixel carries the `No Damage` value or 0.
4. **Check a mask artifact** for values above 1 — this also settles the open
   question about the rasterize CRS bug.
5. **Exercise clustering separately** on a sparse-label project; confirm the
   `images/`  and `masks/` pair count matches the reported cluster count.

## Rollback

Revert by repointing `AZURE_BATCH_DOCKER_IMAGE` at the previous tag and
redeploying the prior wheel. No schema or storage migration is involved, so
rollback is complete and immediate — but any model trained in between keeps the
channel layout it was trained with, and a mixed fleet is fine because
`num_classes` travels in the checkpoint.

The one asymmetry: rolling back the wheel while leaving the new image in place
returns `use_constraint_loss` to unset, so new runs train "No Damage" as a hard
class again. That is the pre-existing behavior, not a new failure.
