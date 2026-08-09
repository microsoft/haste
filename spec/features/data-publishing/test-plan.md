# Test Plan: Data Publishing & Published Datasets

## Test Strategy

| Level | Scope | Tool/Framework | Coverage Target |
|---|---|---|---|
| Unit | Models, provider ABC/registry, Local provider, STAC builders, processor | `unittest`/pytest (`hastelib/tests/`) | ≥ 85% of `core/publishing/` |
| Integration | 5 API routes + queue worker | pytest + Azure Functions harness / Azurite | All routes + happy/error paths |
| Provider (contract) | Planetary Computer HTTP against a mock GeoCatalog | pytest + `responses`/mock | 201/202/40x + poll states |
| UI | Dialog + section components/states | Vitest + React Testing Library | All states in [ux-spec.md](ux-spec.md#ui-states-all) |
| E2E | Full stack (Local target) via Docker Compose | Docker Compose + manual/Playwright | US-001/002/003 |
| Performance | Publish enqueue + list at volume | custom scripts | thresholds below |

## Test Scenarios

### Unit Tests (`hastelib/tests/`)

| ID | Module | Scenario | Input | Expected Output | Story Ref |
|---|---|---|---|---|---|
| UT-001 | `core/models/publishing` | Serialize/deserialize `PublishedDataset`; enum validation | dict | round-trips; bad `target`/`status` rejected | US-001 |
| UT-002 | `core/publishing/registry` | Register + resolve + list_infos; unknown id | ids | providers listed; `KeyError`/error on unknown | US-006 |
| UT-003 | `core/publishing/base` | Provider `validate` contract (Local) | request | None when valid; message when not | US-001 |
| UT-004 | `core/publishing/local_provider` | Copy bundle → `published/{id}/`; links returned | fixture bundle | blobs copied; PUBLISHED links; unpublish cleans up | US-003 |
| UT-005 | `core/publishing/local_provider` | Total selected bytes exceed `PUBLISH_MAX_TOTAL_BYTES` | oversized bundle | publish rejected before copy; clear error | US-003 |
| UT-006 | `core/publishing/stac` | Item geometry from valid-area mask (union → EPSG:4326, bbox, area_km2); `pystac` validates | mask GeoJSON | valid item, `projection` ext | US-004 |
| UT-007 | `core/publishing/stac` | Vector item (GPKG) geometry/bbox/media types + damage props | GPKG + summary | valid item; correct assets/props | US-004 |
| UT-008 | `core/publishing/stac` | Collection build + item-id sanitization (no `-_+().`) | project | valid collection; safe ids | US-004 |
| UT-009 | `core/processors/publishing` | `enqueue` writes PENDING + queues; `run` drives Local to PUBLISHED | request | record transitions; message enqueued | US-001/003 |
| UT-010 | `core/processors/publishing` | Provider exception → FAILED + statusMessage | failing provider | status FAILED, message set | US-004 |

### API Integration Tests

| ID | Endpoint | Method | Scenario | Preconditions | Expected Response | Story Ref |
|---|---|---|---|---|---|---|
| IT-001 | `/api/GetPublishingProviders` | GET | List providers + isConfigured | PC unset | 200; local configured, PC disabled | US-006 |
| IT-002 | `/api/PutPublishDatasetQueueMessage` | POST | Valid publish (Local) | completed model | 202 + PENDING record; message queued | US-001 |
| IT-003 | `/api/PutPublishDatasetQueueMessage` | POST | Missing/invalid fields | — | 400 | US-001 |
| IT-004 | `/api/PutPublishDatasetQueueMessage` | POST | Model without artifacts | model no gpkg | 404 | US-001 |
| IT-005 | `/api/PutPublishDatasetQueueMessage` | POST | Duplicate name still publishing | in-progress dup | 409 | US-001 |
| IT-006 | `/api/GetPublishedDatasets` | GET | List (optional projectId) sorted desc | ≥1 published | 200 + array | US-002 |
| IT-007 | `/api/GetPublishedDataset` | GET | Fetch one; missing id | — | 200 / 404 | US-005 |
| IT-008 | `/api/DeletePublishedDataset` | DELETE | Publisher/admin unpublish; non-owner | records | 200 / 403 | US-005 |

### Queue Worker Tests

| ID | Queue | Scenario | Message | Expected Side Effect | Story Ref |
|---|---|---|---|---|---|
| QT-001 | `publish-queue` | Local publish end-to-end | `{datasetId,projectId}` | artifacts copied; record PUBLISHED + links | US-003 |
| QT-002 | `publish-queue` | PC publish (mock GeoCatalog) | `{...}` | collection upserted; item geometry = valid-area mask; ingested; operations polled; `TotalFailedItems=0`; PUBLISHED | US-004 |
| QT-003 | `publish-queue` | Provider raises | `{...}` | record FAILED + statusMessage; logged | US-004 |
| QT-004 | `publish-queue` | Malformed / unknown datasetId | `{...}` | error log; no crash | — |

### UI Component Tests

| ID | Component | Scenario | User Action | Expected Behavior | Story Ref |
|---|---|---|---|---|---|
| UI-001 | `ModelResultsButton` | Publish item enabled/disabled | open menu | enabled w/ gpkg; disabled+tooltip otherwise | US-001 |
| UI-002 | `PublishDatasetModal` | Prefill name + description + targets | open dialog | name `<project> – <layer>`; desc from report; dropdown from API | US-001 |
| UI-003 | `PublishDatasetModal` | Validation + submit + 409 | submit | field/banner errors; success closes; 409 banner | US-001 |
| UI-004 | `PublishDatasetModal` | Unconfigured PC target | open dropdown | PC disabled w/ note | US-006 |
| UI-005 | `PublishedDatasets` | Empty / loading / no-results | mount/search | empty state; overlay spinner; `NoResultsMessage` | US-002 |
| UI-006 | `PublishedDatasetRow` | Status chips + polling + actions | render | in-progress polls; success enables retrieve; failed shows message/Retry | US-002/005 |
| UI-007 | `PublishDatasetModal` | Asset checklist: available prechecked, absent grayed, zero-selected blocks Publish | toggle checkboxes | correct list; Publish disabled at zero selected | US-007 |

### End-to-End Tests (Docker Compose)

| ID | User Flow | Steps | Expected Outcome | Story Ref |
|---|---|---|---|---|
| E2E-001 | Publish to Local | 1. `docker compose up` 2. Complete a model 3. Publish dataset (Local) 4. Open Published Datasets | Row PUBLISHED; artifacts downloadable | US-001/003 |
| E2E-002 | In-progress → success | Publish; watch section | Row transitions IN_PROGRESS → PUBLISHED without reload | US-002 |
| E2E-003 | Unpublish | Unpublish a Local dataset | Row removed; `published/{id}/` cleaned | US-005 |
| E2E-004 | Publish to PC (gated) | Configure GeoCatalog + (private) SasToken source; publish PC target | Collection/items ingested; assets copied to managed storage; Explorer shows footprints+metadata; GeoPackage downloadable via collection SAS | US-004 |

### Edge Case & Negative Tests

| ID | Scenario | Input | Expected Behavior |
|---|---|---|---|
| NEG-001 | Unauthenticated API request | no key | 401 |
| NEG-002 | Non-existent datasetId | random id | 404 |
| NEG-003 | Unknown target value | `target=foo` | 400 |
| NEG-005 | Empty artifact selection | `artifacts=[]` | 400 |
| NEG-006 | Requested kind not on model | `artifacts=["footprints"]` when absent | 404 |
| NEG-004 | Non-owner unpublish | other user | 403 |
| EDGE-001 | Assessment report unavailable | no report | description prefill blank; publish still works |
| EDGE-002 | Source model deleted after Local publish (copy mode) | delete model | links still resolve |
| EDGE-003 | GeoCatalog ingestion never terminates | stuck poll | bounded timeout → FAILED |
| EDGE-004 | STAC item id with illegal chars | dirty name | sanitized; ingest succeeds |

### Performance Tests

| ID | Scenario | Load Profile | Target Metric | Threshold |
|---|---|---|---|---|
| PERF-001 | Enqueue latency | 50 concurrent publishes | p99 API latency | < 2s |
| PERF-002 | List at volume | 1,000 datasets in index | `GetPublishedDatasets` p95 | < 1s |
| PERF-003 | Local copy throughput | 500 MB artifact set | copy time | bounded, logged |

## Test Data Requirements

| Dataset | Description | Source | Sensitive? |
|---|---|---|---|
| Sample damage GPKG + valid mask + COG | Small model output fixtures | Synthetic | no |
| Sample assessment report JSON | For description prefill + STAC props | Synthetic | no |
| Mock GeoCatalog responses | 201/202 + poll status transitions | Fixtures | no |

## Coverage Matrix

| User Story | Unit | API Integration | Queue | UI | E2E | Performance |
|---|---|---|---|---|---|---|
| US-001 | UT-001, UT-009 | IT-002/003/004/005 | QT-001 | UI-001/002/003 | E2E-001 | PERF-001 |
| US-002 | — | IT-006 | — | UI-005/006 | E2E-002 | PERF-002 |
| US-003 | UT-004/005/009 | IT-002 | QT-001 | — | E2E-001/003 | PERF-003 |
| US-004 | UT-006/007/008/010 | — | QT-002/003 | — | E2E-004 | — |
| US-005 | — | IT-007/008 | — | UI-006 | E2E-003 | — |
| US-006 | UT-002 | IT-001 | — | UI-004 | — | — |
| US-007 | — | NEG-005/006 | — | UI-007 | — | — |

## Environment Requirements

| Environment | Purpose | Config |
|---|---|---|
| Local (Docker Compose) | Dev + Local-target E2E | `docker-compose.yml` + Azurite + `publish-queue` seed |
| CI (GitHub Actions) | Unit/integration + Component Governance | `secret-scan.yml`, `deploy-apps.yml` |
| Dev1 SWA | Integration incl. PC target (dev GeoCatalog) | SWA `dev1` + PC config |
| Testing SWA | Pre-prod validation | SWA `test` config |

## Sign-off Criteria

- [ ] All P0 stories (US-001/002/003) have E2E coverage
- [ ] `core/publishing/` unit coverage ≥ 85%
- [ ] No P0/P1 bugs open
- [ ] Performance thresholds met
- [ ] `docker compose up` runs clean with Local publishing
- [ ] GitHub Actions CI passes (secret-scan, deploy-apps)
- [ ] Component Governance clean (`azure-identity`, `pystac`, `geopandas`, `pyogrio`, `shapely`)
- [ ] PC provider validated against a real/dev GeoCatalog (gated)
