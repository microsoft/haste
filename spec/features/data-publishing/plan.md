# Execution Plan: Data Publishing & Published Datasets

## Phases

### Phase 1: Core Library — models, provider interface, Local, STAC

**Goal:** Implement the publishing domain in `hastelib/src/hastegeo/` independent
of API/UI.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add `models/publishing.py` (`PublishedDataset`, `PublishRequest`, `PublishTarget`/`PublishStatus`, `ProviderInfo`, `PublishResult`) | `backend-dev` | — | US-001..006 | not-started |
| Add `MetadataTypes.PUBLISHED_DATASETS` + `publish_queue_name` + PC config block in `config.py` | `backend-dev` | — | US-003/004/006 | not-started |
| Add `publishing/base.py` (`PublishingProvider` ABC, `ProviderConfigField`) + `registry.py` | `backend-dev` | models | US-006 | not-started |
| Implement `publishing/local_provider.py` (copy → `published/{datasetId}/`, links) | `backend-dev` | base, artifact storage | US-003 | not-started |
| Add `publishing/geocatalog_client.py` (hardened REST client + Entra auth) and `planetary_computer_transport.py` (resumable async-ingestion adapter) | `backend-dev` | — | US-004 | not-started |
| Implement `publishing/stac.py` (collection + vector item builders; geometry from valid-area mask, `ai4g:` stats) | `gis` | models | US-004 | not-started |
| Add `processors/publishing.py` (`enqueue`, `run`, `ArtifactBundle`) | `backend-dev` | providers, registry | US-001/003 | not-started |
| Unit tests in `hastelib/tests/core/{models,publishing,processors}/` | `backend-dev` | all above | US-001/003/006 | not-started |

**Exit Criteria:**
- [ ] Local provider publishes a fixture bundle end-to-end in a unit test
- [ ] Registry lists provider infos; STAC builders produce valid `pystac`-validated docs
- [ ] Core logic works with no API/UI present

### Phase 2: API Layer + Queue — enqueue, list, get, delete

**Goal:** Expose publishing via `hastefuncapi` routes and the `publish-queue`
worker.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add `GetPublishingProviders`, `GetPublishedDatasets`, `GetPublishedDataset`, `PutPublishDatasetQueueMessage`, `DeletePublishedDataset` (thin wrappers) | `backend-dev` | Phase 1 | US-001/002/005/006 | not-started |
| Add `GetPublishDatasetQueueMessage` trigger in `hastefuncqueues` | `backend-dev` | Phase 1 | US-001/003 | not-started |
| Seed `publish-queue` in Azurite / `docker-compose.yml` | `backend-dev` | — | — | not-started |
| Update `requirements.txt` (`azure-identity`, `pystac[validation]`, `geopandas`, `pyogrio`, `shapely`, `requests`) | `backend-dev` | — | — | not-started |
| API integration + queue-worker tests | `backend-dev` | above | US-001/002/003 | not-started |

**Exit Criteria:**
- [ ] Publish → PENDING record + queued message; worker drives Local to PUBLISHED
- [ ] List/get/delete callable via REST; 400/404/409 paths covered
- [ ] Works in Docker Compose local stack

### Phase 3: Planetary Computer provider

**Goal:** Ingest STAC into a MPC Pro GeoCatalog.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Implement `planetary_computer_provider.py` (ensure-collection, build+ingest items, poll operations, `TotalFailedItems`, validate, unpublish) | `gis` | Phase 1 stac/client, Phase 2 | US-004 | not-started |
| Item-id sanitization + media types + damage properties from assessment summary | `gis` | stac | US-004 | not-started |
| Credential/ingestion-source handling (`DefaultAzureCredential`, `inma/ingestion-sources`) | `backend-dev` | provider | US-004 | not-started |
| Security review of new deps + credential flow | `security` | requirements | US-004 | not-started |
| Provider tests (mock GeoCatalog HTTP: 201/202/40x, poll states) | `backend-dev` | provider | US-004 | not-started |

**Exit Criteria:**
- [ ] Against a mock/dev GeoCatalog: collection ensured, items ingested, status polled to terminal, links stored
- [ ] Failure paths (40x, timeout) → FAILED with message; unpublish deletes items
- [ ] `security`/`security-validation` sign-off on deps + credentials

### Phase 4: UI — section, dialog, entry point

**Goal:** Surface publishing in the React app.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| `PublishDatasetModal.jsx` (name/description/target, prefill, submit) | `ui` | Phase 2 | US-001/006 | not-started |
| "Publish dataset…" `MenuItem` in `ModelResultsButton.jsx` | `ui` | modal | US-001 | not-started |
| Extract `util/assessmentSummary.js` (`buildSummarySentence`) from `AssessmentReportModal.jsx` | `ui` | — | US-001 | not-started |
| `PublishedDatasets.jsx` + `PublishedDatasetRow.jsx` (catalog-style, all states, polling) | `ui` | Phase 2 | US-002/005 | not-started |
| Sidebar item + `/published-datasets` route (`AppSidebar.jsx`, `AppBody.jsx`) | `ui` | section | US-002 | not-started |
| API helpers in `util/api.js`; UI component tests | `ui` | above | US-001/002/005 | not-started |

**Exit Criteria:**
- [ ] Publish flow works from results menu; datasets list with empty/loading/in-progress/success/failure states
- [ ] Works with SWA CLI local dev (`swa start`) against Docker Compose backend

### Phase 5: Integration & Deployment

**Goal:** Validate end-to-end and ship.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| E2E via Docker Compose (Local target full loop) | `backend-dev` | Phase 4 | US-001/002/003 | not-started |
| PC target E2E against a real/dev GeoCatalog (gated) | `gis` | Phase 3/4 | US-004 | not-started |
| Update `docs/` (publishing feature) + `CHANGELOG.md` | `backend-dev` | — | — | not-started |
| GitHub Actions: Component Governance for new deps | `backend-dev` | — | — | not-started |

**Exit Criteria:**
- [ ] `docker compose up` clean with Local publishing working end-to-end
- [ ] CI passes (secret-scan, deploy-apps, Component Governance)
- [ ] Docs + changelog updated

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec approved | | Signed-off design docs (this folder) |
| Core + Local done | | `hastelib` publishing package, Local provider, tests |
| API + Queue done | | Endpoints + `publish-queue` worker functional |
| PC provider done | | STAC ingestion into GeoCatalog |
| UI done | | Section + dialog + entry point in the app |
| Release | | Deployed to production SWA behind flag |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | models, config, base/registry, Local, processor, API, queue, integration | 1, 2, 3, 5 |
| `gis` | STAC builders, Planetary Computer provider, PC E2E | 1, 3, 5 |
| `ui` | dialog, section, entry point, routing, UI tests | 4 |
| `security` | new-dep + credential review | 3 |

## Resource Requirements

- **Agents:** `backend-dev`, `gis`, `ui`, `security` (+ validation counterparts).
- **Azure services:** `publish-queue` (Queue Storage); artifact/data Blob prefix
  `published/`; a **MPC Pro GeoCatalog** + registered ingestion source for the PC
  target (dev + prod); managed identity with GeoCatalog + storage access.
- **New Python deps:** `azure-identity`, `pystac[validation]`, `geopandas`, `pyogrio`, `shapely`, `requests` (Component
  Governance).
- **GPU compute:** none.
- **External data:** none (operates on HASTE-generated artifacts).

## Open Questions

- [ ] Is a dev/test GeoCatalog available for CI, or is PC E2E manual/gated?
- [ ] Feature flag scope: gate the whole section, or just the PC target, until
      GeoCatalog is provisioned? (see [rollout.md](rollout.md))
- [ ] Collection-per-project vs per-event id strategy (also in design Open
      Questions).
