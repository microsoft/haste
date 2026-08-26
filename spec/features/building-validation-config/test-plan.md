# Test Plan: Building Validation configuration

## Strategy

The two pieces most likely to break silently are the sampling nesting property
and the `sampleSize` preservation on label save. Both are pure enough to test
offline, so neither depends on Azure or a browser.

| Layer | Runner | Scope |
|---|---|---|
| `hastegeo` unit | `hatch run test:pytest` | `sample_indices` determinism, nesting, clamping |
| API unit | `hatch run test:pytest` | count-change rules, `sampleSize` preservation |
| UI unit | `node --test` | `canApplySampleSize` rule table |
| Manual | dev stack | modal wiring, confirms, in-place re-fetch |

## Coverage matrix

### `sample_indices` — `hastelib/tests/core/utils/test_footprints.py`

| Case | Assertion | Story |
|---|---|---|
| Nesting | `sample_indices(n, 200)` is a prefix of `sample_indices(n, 300)` | US-002 |
| Nesting (set form) | the 200-draw is a subset of the 300-draw | US-002 |
| Determinism | two calls with equal arguments are identical | US-002 |
| Clamp low | `sample_size <= 0` clamps to 1 | US-001 |
| Clamp high | `sample_size > 2000` clamps to 2000 | US-001 |
| Small dataset | `n_rows <= sample_size` returns every row | US-001 |
| Range | every returned index is in `[0, n_rows)` and unique | US-002 |

### Endpoints

| Case | Assertion | Story |
|---|---|---|
| Label save omits `sampleSize` | stored value survives | US-005 |
| Label save carries `sampleSize` | explicit value is written | US-005 |
| Clear labels (`labels: {}`) | labels emptied, `sampleSize` survives | US-004 |
| `new == current` | `200`, no write | US-001 |
| `new > current`, labels present | `200`, value updated | US-002 |
| `new < current`, no labels | `200`, value updated | US-003 |
| `new < current`, labels present | `409`, stored value unchanged | US-003 |
| Missing / non-integer / out-of-range | `400` | US-001 |
| Missing `projectId` / `imageLayerId` | `400` | US-001 |

### `canApplySampleSize` — `ui/src/Components/BuildingValidation/validationConfig.test.js`

| Case | Assertion | Story |
|---|---|---|
| Equal | `noop` | US-001 |
| Higher, no labels | `extend` | US-002 |
| Higher, labels present | `extend` — allowed | US-002 |
| Lower, no labels | `resample` | US-003 |
| Lower, labels present | `blocked`, message names the label count | US-003 |
| Below 1 / above 2000 / non-numeric | `invalid` | US-001 |
| Missing current (fresh document) | treated as the default 200 | US-001 |

## Commands

```bash
cd hastelib && hatch run test:pytest tests/core/utils/test_footprints.py -v
cd ui && npm run test:validation-config
cd ui && npm run lint
```

## Manual verification

1. Gear disabled on a layer with no footprints.
2. Open the modal from the project table; change 200 → 300; launch; confirm the
   count of rendered buildings.
3. Label a few, raise to 400 from inside the validation view, confirm the map
   re-renders in place and the labels survive.
4. Lower the count with labels present; confirm the refusal and that the stored
   value is unchanged.
5. Clear labels from both entry points; confirm each asks first.
6. Save labels, reopen the modal, confirm the count is still what was set.
