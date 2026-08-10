# Feature: Data Publishing & Published Datasets

**Status:** draft
**Author:** HASTE engineering team
**Date:** 2026-08-05
**Target Release:** TBD
**Priority:** P2
**Work Item:** —

## Summary

A new **Published Datasets** section (a sibling to the **Model Catalog**) plus a
**Publish dataset** action on model results. Today an analyst can *download* a
model's outputs — the damage GeoPackage, valid-area mask, footprints, processed
COGs and the assessment report. This feature adds the ability to **publish**
those same HASTE-generated artifacts as a first-class, named, described dataset
that others can discover and retrieve. Publishing is routed through a
**provider abstraction** so a dataset can be published to different targets:
initially **Local** (registered inside HASTE-managed storage and listed in the
Published Datasets section) and **Planetary Computer** (Microsoft Planetary
Computer Pro GeoCatalog, using STAC-compatible metadata). The provider interface
is designed so new targets (e.g. an external STAC API, ArcGIS, a data portal)
can be added later without reworking the UI, API, or async workflow.

## Motivation

- Analysts and partners repeatedly ask "where is the *final* dataset for this
  event?" — today the answer is a set of ad-hoc publications.
- Downloads are ephemeral (SAS URLs, tied to a single model that may be
  re-run or deleted). A published dataset is a **stable, described, discoverable**
  record with its own name, description, provenance and status.
- The **Model Catalog** already proves the pattern (curated, listable, catalogued
  entities). "Published Datasets" is the output-side analogue and reuses the same
  storage, API and UI conventions.
- Publishing to **Planetary Computer Pro** lets HASTE outputs join the broader
  geospatial STAC ecosystem (searchable, tileable, standards-based) with no
  manual STAC authoring by the analyst.

## Success Criteria

- [ ] From a completed model's results, an analyst can open **Publish dataset**,
      see a name pre-filled from `${project} – ${layer}` and a description
      pre-filled from the assessment report, pick a target, and publish.
- [ ] Published datasets appear in a new **Published Datasets** section with
      empty / loading / success / failure / in-progress states.
- [ ] The **Local** provider registers the dataset in HASTE storage and exposes
      stable retrieval links, independent of the source model's lifecycle.
- [ ] The **Planetary Computer** provider creates/updates a STAC Collection and
      ingests STAC Item(s) for the dataset's artifacts into a GeoCatalog, and the
      published record carries the collection id + explorer links.
- [ ] Adding a new provider requires only a new `PublishingProvider`
      implementation + registry entry — no UI/API/queue changes.
- [ ] Publishing that takes time runs as an async job with visible status,
      matching the training/inference/zip job pattern.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | new `publishing.py` (`PublishedDataset`, `PublishRequest`, enums, `ProviderInfo`) |
| `hastelib/src/hastegeo/core/publishing/` | **new subpackage**: provider ABC, registry, `local`, `planetary_computer`, STAC builders |
| `hastelib/src/hastegeo/core/processors/` | new `publishing.py` — orchestrates validate → persist → enqueue → run provider → status |
| `hastelib/src/hastegeo/core/config.py` | `PUBLISHED_DATASETS` metadata type; `publish_queue_name`; PC GeoCatalog config keys |
| `api/hastefuncapi/` | `GetPublishingProviders`, `GetPublishedDatasets`, `GetPublishedDataset`, `PutPublishDatasetQueueMessage`, `DeletePublishedDataset` |
| `api/hastefuncqueues/` | `GetPublishDatasetQueueMessage` trigger on `publish-queue` |
| `ui/src/Components/` | new `PublishedDatasets.jsx`, `PublishedDatasetRow.jsx`, `PublishDatasetModal.jsx`; "Publish dataset…" in `ProjectManagement/ModelResultsButton.jsx`; sidebar/route wiring |
| `ui/src/util/` | new API helpers (via existing `api.js`); shared assessment-summary helper |
| `docker/` | Azurite `publish-queue` seed; optional PC emulator/config env |
| `.github/workflows/` | Component Governance for new Python deps (`azure-identity`, `pystac`, `geopandas`, `pyogrio`, `shapely`) |

## Related Specs

| Spec | Relationship |
|---|---|
| [open-data-catalog](../open-data-catalog/) | related — reuses STAC concepts, TiTiler preview, and the "browse external geospatial data" precedent (this feature is the *publish/output* counterpart to that *discover/input* feature) |
| [gdal-compensating-controls](../gdal-compensating-controls/) | related — STAC item generation reads GeoTIFF/GPKG under the GDAL driver allowlist |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [user-stories.md](user-stories.md) | Personas, user stories & acceptance criteria (product requirements) | draft |
| [ux-spec.md](ux-spec.md) | UX specification: Published Datasets section + Publish dialog, all UI states | draft |
| [design.md](design.md) | Technical design, provider interface, Local + Planetary Computer providers, API contracts | draft |
| [data-model.md](data-model.md) | Cosmos/Blob metadata schema, published-dataset storage layout, STAC mapping | draft |
| [plan.md](plan.md) | Execution plan, milestones, phases | draft |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | draft |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | draft |
| [rollout.md](rollout.md) | Rollout strategy, flags, rollback | draft |

## Key Design Decisions

- **Model Published Datasets on the Model Catalog pattern** — a single `index`
  metadata doc, `Get/Put/Delete` routes, and a catalog-style React page. The two
  features are symmetric (curated inputs vs curated outputs) and reuse the same
  storage/API/UI conventions.
- **`PublishingProvider` abstraction + registry from day one** — extensibility is
  a core requirement; Local + Planetary Computer already prove ≥2 providers, so
  the seam must exist. New targets are a new provider subclass + registry entry,
  with no UI/API/queue change.
- **All publishing runs through the async `publish-queue`** (even Local) — one
  uniform status lifecycle (`PENDING → IN_PROGRESS → PUBLISHED | FAILED`) matching
  training/inference/zip; PC ingestion is inherently async, so a single path
  avoids a sync/async split in the UI.
- **Local provider copies artifacts** into an immutable `published/{datasetId}/`
  prefix so a published dataset survives the source model being re-run or deleted.
- **Users select which existing outputs to publish** (GeoPackage, valid mask,
  footprints, image COG …) via a prechecked checklist; the selection travels as
  `artifacts: [...]` and providers publish only that subset.
- **Provider configuration is operator-owned** — Azure App Settings + managed
  identity, set at deploy; no in-app admin screen in v1. The UI only reflects
  `isConfigured` via `GetPublishingProviders`. The `ProviderInfo` contract still
  allows a self-service admin UI later with no UI/API rework.
- **Planetary Computer = MPC Pro GeoCatalog STAC API** (`/stac/collections`,
  `/stac/collections/{id}/items`, `api-version=2026-04-15`), auth via
  `DefaultAzureCredential` (scope `https://geocatalog.spatio.azure.com/.default`).
  Item geometry comes from the valid-area mask (`geopandas`/`shapely`); one STAC
  Collection per project (≈ per event); private HASTE containers need a `SasToken`
  ingestion source (managed-identity sources are portal/ARM only).
- **PC publishing is download-only in v1** — GeoPackage/GeoJSON are stored and
  served via the STAC API but not tiled/rendered on the Explorer map (it appears
  as item footprints + metadata; consumers download the GeoPackage). Rasterized
  COG rendering is a future enhancement.
