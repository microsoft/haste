# Rollout: Building Validation configuration

## Strategy

Ship in one PR. No feature flag: the change is additive, the default preserves
today's behavior exactly (200 footprints), and there is no background job or
long-running migration to stage.

## Sequence

1. Merge the PR. `sampleSize` starts materializing on `BuildingValidation`
   documents the first time a user saves a config.
2. Deploy `hastefuncapi` — the new `PutBuildingValidationConfig` route and the
   merge-preserving `PutBuildingValidation` must be live before the UI that
   calls them.
3. Deploy the UI.

Deploying the UI first would surface a gear whose save returns 404. Ordering
matters more than staging here.

## Verification after deploy

- [ ] Open the config modal on an existing layer; it reads 200 without the
      field having been stored.
- [ ] Raise the count; relaunch; confirm previously labeled buildings are still
      present and labeled.
- [ ] Save labels; reopen the modal; confirm the count did not revert to 200.
- [ ] Lower the count with labels present; confirm the refusal.

## Rollback

Revert the PR and redeploy. `sampleSize` values already written are inert: the
reverted `GetBuildingValidation` still returns them, the reverted UI ignores
them, and sampling returns to the hardcoded 200.

Rolling back the API alone is also safe — the UI's config save fails with a
surfaced error, and everything else keeps working, because the count only ever
influences a query parameter that has a server-side default.

## Monitoring

Nothing new. Failures surface through the existing `hastefuncapi` logs; the
`409` from a blocked count reduction is an expected user-facing outcome, not an
error condition, and is logged at info level.
