# Execution Plan: Building Validation configuration

## Phases

### Phase 1: Backend foundation

**Goal:** the setting exists, is durable, and the sampling guarantee is
explicit rather than incidental.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add `sampleSize` to `BuildingValidation` | `backend-dev` | — | US-001 | done |
| Add `sample_indices` to `core/utils/footprints.py` | `backend-dev` | — | US-002 | done |
| Unit tests for `sample_indices` (nesting, clamp, determinism) | `backend-dev` | helper | US-002 | done |
| Wire `GetBuildingFootprintsGeoJSON` to the helper | `backend-dev` | helper | US-002 | done |
| Preserve `sampleSize` in `PutBuildingValidation` | `backend-dev` | model | US-005 | done |
| Add `PutBuildingValidationConfig` with the rules | `backend-dev` | model | US-001/2/3 | done |
| Endpoint tests (preservation + every rule row) | `backend-dev` | routes | US-003/5 | done |

**Exit criteria:**

- [x] `sample_indices(n, 200)` is provably a prefix of `sample_indices(n, 300)`, asserted by test.
- [x] A label save with no `sampleSize` leaves the stored value alone.
- [x] Lowering the count with labels present returns `409` and writes nothing.

### Phase 2: UI

**Goal:** the setting is reachable from both places, and clearing labels is
possible for the first time.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| `validationConfig.js` rule helper | `ui` | — | US-003 | done |
| `validationConfig.test.js` + `test:validation-config` script | `ui` | helper | US-003 | done |
| `ValidationConfigModal.jsx` (count field, save, clear-with-confirm) | `ui` | helper, Phase 1 routes | US-001/4 | done |
| Gear button in `LayerRow.jsx` | `ui` | modal | US-001 | done |
| `BuildingValidation.jsx`: use stored `sampleSize`, gear, in-place re-fetch | `ui` | modal | US-001/2 | done |
| Clear-labels control in `BuildingValidationRightPanel.jsx` | `ui` | modal | US-004 | done |

**Exit criteria:**

- [x] The hardcoded `sample=200` is gone from `BuildingValidation.jsx`.
- [x] Both clear-label entry points ask for confirmation first.
- [x] Gear is disabled exactly when **Launch** is.

### Phase 3: Documentation and verification

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| CHANGELOG entry | `backend-dev` | Phases 1–2 | — | done |
| Run pytest, UI unit tests, ESLint | `backend-validation`, `ui-validation` | Phases 1–2 | all | done |
| Manual pass on the dev stack | `ui-validation` | Phase 2 | all | done |
| Mark spec `implemented`, record outcomes | `orchestrator` | all | — | done |

**Exit criteria:**

- [x] `hatch run test:pytest tests/core/utils/test_footprints.py -v` green.
- [x] `npm run test:validation-config` green.
- [x] `npm run lint` clean.

## Sequencing note

Phase 1 lands before Phase 2 because the modal's save path depends on
`PutBuildingValidationConfig` existing; the UI rule helper is the one Phase 2
item that can be written in parallel.
