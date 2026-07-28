# Feature: Open Data Catalog Explorer

**Status:** implemented
**Author:** HASTE engineering team
**Date:** 2026-07-20
**Target Release:** TBD
**Priority:** P2
**Work Item:** —

## Summary

A side panel on the **Create Image Layer** page that lets disaster analysts
browse open disaster-response imagery from the **Vantor/Maxar** and **Planet**
Open Data Programs, preview a scene's imagery on a map, and add scenes directly
into an image layer's pre-/post-event inputs — including drawing a clip Area of
Interest (AOI) that the imagery-prep workflow applies to the mosaics. This
removes the manual, error-prone step of hunting down Cloud-Optimized GeoTIFF
(COG) URLs on S3/STAC catalogs and pasting them into the form.

## Motivation

- Analysts currently must locate a disaster's open imagery on external S3/STAC
  catalogs, copy exact COG URLs, and paste them into the layer form — slow and
  easy to get wrong (wrong host, wrong phase, no AOI).
- Open data (Vantor/Maxar, Planet) is the primary imagery source for many
  responses; making it first-class in the app shortens time-to-assessment.
- Reference prototype (self-contained, OpenLayers): the **Open Disaster
  Response Data Visualizer** —
  <https://visualizers.aiforgood.ai/damage-assessment/venezuela_earthqake_data_explorer.html>

## Success Criteria

- [x] Analysts can discover every available disaster event across Vantor + Planet from within the app.
- [x] A scene's COG URL can be added to pre/post imagery in one click, with source-type + capture-date auto-filled.
- [x] A drawn AOI clips the produced imagery to just that area (verified end-to-end).
- [x] Planet (`data.source.coop`) imagery downloads successfully through the imagery-prep workflow.
- [x] Pre imagery can only be added to Pre and post to Post from the catalog UI.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | `ImageLayer.clipBbox` field |
| `hastelib/src/hastegeo/core/utils/` | `url_allowlist` (source.coop + `validate_clip_bbox`); `downloader` HTTP route; `imagery.mosaic_imagery` clip |
| `hastelib/src/hastegeo/core/processors/` | `imagery` — `clip_bbox` in the prep config |
| `hastelib/src/hastegeo/workflows/prepare_imagery.py` | thread `clip_bbox` into the mosaic step |
| `api/hastefuncapi/` | `PutLayer` validates + carries `clipBbox` |
| `ui/src/Components/` | new `OpenDataCatalog/`; integration into `CreateEditImageLayer*`; `util/validation.js` |
| `docker/` | `nginx.conf` (titiler timeouts + body size); `docker-compose.yml` (cleanup knob) |

## Related Specs

| Spec | Relationship |
|---|---|
| [gdal-compensating-controls](../gdal-compensating-controls/) | related — imagery prep runs under the GDAL driver allowlist |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan, milestones, phases | implemented |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | implemented |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | implemented |
| [design.md](design.md) | Technical design & API contracts | implemented |
| [data-model.md](data-model.md) | Schema / model / blob changes | implemented |
| [test-plan.md](test-plan.md) | Test strategy & coverage matrix | implemented |
| [rollout.md](rollout.md) | Rollout strategy, flags, rollback | draft |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-17 | Client-side discovery, isolated in one framework-free module | Fast to ship; a stable `discoverEvents()`/`fetchEventCatalog()` contract can move behind an Azure Function later with no UI change. |
| 2026-07-17 | Support Vantor + Planet | Full parity with the reference; required allowlisting `data.source.coop`. |
| 2026-07-17 | Azure Maps for the map (not OpenLayers) | Reuse the app's existing `window.atlas` stack — no new dependency. |
| 2026-07-18 | Preview + clip via TiTiler | HASTE already runs TiTiler; streams any remote COG without an Azure Maps subscription. |
| 2026-07-19 | **Server-side clip** (layer-level `clipBbox` applied at imagery prep) chosen over client-side crop+upload | Instant add (no client crop/upload wait); the clip runs where imagery is already processed. The client-side TiTiler-crop approach was prototyped first (see [design.md](design.md#clip-approaches)). |
| 2026-07-19 | Route non-S3/Blob allowlisted hosts through the generic HTTP downloader | `data.source.coop` was validated but silently dropped by `ImageryDownloader`, failing Planet downloads. |
