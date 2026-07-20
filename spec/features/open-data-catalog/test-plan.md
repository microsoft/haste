# Test Plan: Open Data Catalog Explorer

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | allowlist + clip-bbox validation | pytest/unittest (`hastelib/tests/`) | validators covered |
| Manual/integration | discovery, preview, clip end-to-end | Docker Compose local stack | key flows |
| E2E | imagery-prep clip job | real `haste-imageryprep` run | 1 verified run |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Expected | Story |
|---|---|---|---|---|
| UT-001 | `url_allowlist` | `data.source.coop` imagery URL | returns `"sourcecoop"` | US-001/004 |
| UT-002 | `url_allowlist` | `validate_clip_bbox` valid `[w,s,e,n]` | `None` | US-004 |
| UT-003 | `url_allowlist` | wrong length / non-numeric / out-of-range / inverted bbox | error string | US-004 |

> Implemented in `hastelib/tests/core/utils/test_url_allowlist.py` (32 tests passing).

### API Integration Tests

| ID | Endpoint | Scenario | Expected | Story |
|---|---|---|---|---|
| IT-001 | `PUT /api/PutLayer` | Planet post URL + valid `clipBbox` | 200; layer persisted with `clipBbox` | US-003/004 |
| IT-002 | `PUT /api/PutLayer` | invalid `clipBbox` (e.g. `[1,2,3]`) | 400 with message | US-004 |
| IT-003 | `PUT /api/PutLayer` | non-allowlisted imagery host | 400 | US-003 |

### Queue / Workflow Tests

| ID | Scenario | Expected | Story |
|---|---|---|---|
| QT-001 | Layer with `clipBbox` processed by `haste-imageryprep` | mosaic clipped to AOI; `Clipping mosaic to AOI bbox …` logged | US-004 |
| QT-002 | Planet (`source.coop`) post URL | downloaded via generic HTTP route (not S3/Blob SDK) | US-004 |

### UI Component Scenarios

| ID | Component | User Action | Expected | Story |
|---|---|---|---|---|
| UI-001 | Panel | open catalog | events discovered + merged | US-001 |
| UI-002 | Map | select scene | TiTiler preview + loading chip until tiles in | US-002 |
| UI-003 | SceneListItem | view a `post` scene | only ＋ Post-event button shown | US-003 |
| UI-004 | Map | draw clip box | persistent AOI rectangle; `clipBbox` set | US-004 |
| UI-005 | Panel | with AOI set | only overlapping scenes shown; "covers AOI" badges | US-005 |
| UI-006 | Map→list | click a footprint | list scrolls to + highlights + expands the row | US-006 |

### End-to-End (Docker Compose) — executed

| ID | Flow | Result | Story |
|---|---|---|---|
| E2E-001 | PutLayer (Planet Caracas scene + `clipBbox`) → imagery prep → inspect output | **Passed** — output mosaic WGS84 bounds match the drawn box (lon to 5 dp; ~30 m lat delta from UTM reprojection); AOI + 5,374 footprints derived from the clipped area | US-004 |

### Edge Case & Negative Tests

| ID | Scenario | Expected |
|---|---|---|
| NEG-001 | One source catalog down | other source loads; warning banner |
| NEG-002 | Duplicate STAC ids | deduped; unique `uid` keys (no React duplicate-key warning) |
| EDGE-001 | Scene without a COG | add disabled; footprint-only note |
| EDGE-002 | Clip AOI not overlapping a scene | scene hidden by default AOI filter |

## Coverage Matrix

| Story | Unit | API | Queue/WF | UI | E2E |
|---|---|---|---|---|---|
| US-001 | UT-001 | — | — | UI-001 | — |
| US-002 | — | — | — | UI-002 | — |
| US-003 | — | IT-001/003 | — | UI-003 | — |
| US-004 | UT-002/003 | IT-001/002 | QT-001/002 | UI-004 | E2E-001 |
| US-005 | — | — | — | UI-005 | — |
| US-006 | — | — | — | UI-006 | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | dev + E2E | `docker/docker-compose.yml` (Azurite, TiTiler, imageryprep) |

## Sign-off Criteria

- [x] Allowlist + clip-bbox unit tests pass (32).
- [x] Clip verified end-to-end against a real imagery-prep run.
- [x] `docker-compose` stack runs the catalog + prep clean.
- [ ] Automated UI/API integration tests (currently manual).
