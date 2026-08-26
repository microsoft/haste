# Impact Analysis: Building Validation configuration

## Blast radius

| Area | Exposure |
|---|---|
| `GetBuildingFootprintsGeoJSON` | Refactor only. Same seed, same clamp, same output for the default 200. Also used by the validation view exclusively, so the reach is narrow. |
| `PutBuildingValidation` | Behavior change: now reads before writing. Used by the validation view's label save and by the new clear action. |
| `BuildingValidation` documents | Additive field, default-filled on read. No migration. |
| Validation / Assessment reports | Read `labels`, untouched. A larger sample means more labels and therefore a larger evidence base for the same accuracy computation. |
| Interactive Labeler | None. It has its own `INTERACTIVE` label store; only the layer-scoped `VALIDATION` store is touched here. |

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | A future NumPy/pandas change breaks the permutation-prefix property, silently reshuffling users' validation sets on a count change. | Low | High | `sample_indices` owns the prefix logic and a unit test asserts nesting directly, so the break surfaces as a fast offline test failure. |
| R2 | Adding `sampleSize` to the model lets a label save reset it to the default. | High if unguarded | Medium | `PutBuildingValidation` preserves the stored value; regression test. This is the PR #135 failure mode. |
| R3 | Re-ingesting footprints reshuffles the sample, so previously labeled buildings may leave the set. | Low | Medium | Pre-existing behavior, not introduced here. Documented in `data-model.md`. Not fixed in this feature. |
| R4 | Two users change the count concurrently, or one changes it while another labels. | Low | Low | Rules are enforced server-side against the stored document. Labels are already last-write-wins per layer; this does not make that worse. |
| R5 | Raising the count to 2000 on a dense layer slows the validation view's initial load. | Medium | Low | The 2000 clamp already exists server-side and is now surfaced as the field's max rather than being silently applied. |
| R6 | A user lowers the count expecting a fresh sample and is blocked instead. | Medium | Low | The refusal names the label count and offers Clear in the same modal, so the recovery is one click away. |

## Dependencies

- None outside the repo. No new packages, so no `security` agent review.
- `origin/main` at `0b6b29c` (merge of PR #165) is required for the UI to
  install; earlier commits fail `npm install` with an `ERESOLVE` on
  `react`/`@azure/msal-react`.

## Backward compatibility

- Existing `BuildingValidation` documents read back as `sampleSize: 200`,
  matching the hardcoded behavior they were created under.
- `GetBuildingValidation` gains a field; additive, so older clients ignore it.
- No change to the footprints GeoPackage, tile artifacts, or any queue message.

## Rollback

Revertable as a single commit range. Documents already carrying `sampleSize`
would keep the field and it would be ignored, with the UI falling back to 200.
