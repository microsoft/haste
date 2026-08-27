# Design: Source-Imagery Provenance

**Status:** implemented · **Feature area:** data-publishing

## Goal

Add a machine-readable and human-readable **reference to the source imagery** used
to generate a published dataset's output assets — **automatically** when the
imagery comes from a known open-data program (Vantor Open Data, Planet Open
Data), and as an **optional, user-supplied** citation otherwise.

The hard constraint is **licensing**: we auto-attribute *only* imagery we know is
open-data, because commercially-licensed imagery may not be freely referenceable.

## Two complementary concepts

We already emit **attribution** on published items — a STAC `providers` list
(`Vantor` / `Planet` as `producer`/`licensor`), inferred from the image layer's
`sourceType`. This design adds **provenance** — a link to the *specific source
scenes* an output was derived from. They are complementary:

| | Answers | Mechanism | Source of truth |
|---|---|---|---|
| Attribution (exists) | "Who made the imagery?" | `providers` | image-layer `sourceType*` |
| **Provenance (new)** | "Which source scenes was this derived from?" | `rel="derived_from"` links + `haste:source_imagery` | scenes captured at catalog add-time |

## Core principle: a fail-safe licensing gate

Automation is gated on **provenance captured at ingest**, never *inferred later*:

- A source-imagery reference is marked `attributable: true` **only** in the Open
  Data Catalog add-flow, where we know the scene came from a registered open-data
  program.
- The backend independently **validates** each reference's `programId` against an
  allowlist of open-data programs before honoring it (it does **not** trust a
  client-supplied `attributable`/`license`).
- If provenance was not captured from the catalog, we auto-emit **nothing**.

> **Why not infer from `sourceType`?** A user can legitimately select the `Vantor`
> source type for *commercially-licensed* Vantor imagery. Inferring "open data"
> from the vendor would be exactly the licensing mistake this feature avoids. The
> gate must be *"came through the open-data catalog"*, proven by captured data.

---

## Data model

### `SourceImageryRef` (new)

One entry per source scene, self-contained so downstream code needs no lookups:

```jsonc
{
  "programId": "vantor-open-data",          // registry key; the automation gate
  "programName": "Vantor Open Data Program",
  "sceneId": "<stac item id>",
  "title": "Caracas post-event (2024-08-30)",
  "href": "https://vantor-opendata.s3.amazonaws.com/events/<event>/<sceneId>.json",
  "license": "CC-BY-NC-4.0",
  "attributable": true,                     // true only when captured from a program
  "phase": "post",                          // "pre" | "post" | null
  "capturedDate": "2024-08-30T00:00:00Z"
}
```

`href` is the **STAC item URL we fetched** (see Decision #2) — the canonical
`derived_from` target.

### Field additions

| Model | New field | Notes |
|---|---|---|
| `ImageLayer` | `sourceImageryReferences: List[SourceImageryRef] = []` | populated by the catalog add-flow; empty for user-supplied imagery |
| `PublishDatasetOptions` | `sourceImageryReferences: List[SourceImageryRef] = []` | resolved from the layer (mirrors `imagerySources` threading) |
| `PublishedDataset` | `sourceImageryReferences: List[SourceImageryRef] = []` | carried at publish; drives `derived_from` |
| `PublishRequest` | `sourceImageryCitation: Optional[str]` | optional, URL-aware free text (Decision #5) |
| `PublishedDataset` | `sourceImageryCitation: Optional[str]` | persisted; editable |
| `PublishMetadataUpdate` | `sourceImageryCitation: Optional[str]` | editable via the edit dialog |

### Open-data program registry (backend, authoritative)

A small allowlist — the scalability seam. Adding a program is one entry (+ a
catalog source), with **no publish/emit code change**:

```python
OPEN_DATA_PROGRAMS = {
  "vantor-open-data": {"name": "Vantor Open Data Program",
                       "license": "CC-BY-NC-4.0", "url": "https://vantor.com/..."},
  "planet-open-data": {"name": "Planet Disaster Data",
                       "license": "CC-BY-NC-4.0", "url": "https://www.planet.com/..."},
}
```

The backend uses the registry's **canonical** `name`/`license` (ignoring
client-supplied values) and drops any reference whose `programId` is not listed.

---

## Flow: capture → carry → emit

### 1. Capture (UI — Open Data Catalog add-flow)

When a scene is added to a layer via `onAddScene`, record a `SourceImageryRef`
into the form's `sourceImageryReferences` (keyed by phase), persisted on layer
save. Per **Decision #2**, `href` = the STAC item **fetch URL**:

- **Planet** — `normalizePlanetItem` already receives `itemUrl`
  ([openDataCatalog.js:450](../../../ui/src/Components/OpenDataCatalog/openDataCatalog.js#L450)); capture as `itemHref`. No new plumbing.
- **Vantor** — thread `absUrl(l.href, baseUrl)` from `fetchVantorItems`
  ([openDataCatalog.js:379](../../../ui/src/Components/OpenDataCatalog/openDataCatalog.js#L379)) into `normalizeVantorItem`; capture as `itemHref`.

Scenes already carry `id`, `source`, `title`, `datetime`, `phase`; we add
`itemHref`, `programId`, and (from the registry) `license`.

### 2. Carry (backend — resolve_options → dataset)

`resolve_options` copies `image_layer.sourceImageryReferences` onto
`PublishDatasetOptions`; the processor copies them + `request.sourceImageryCitation`
onto the `PublishedDataset` — the same path `imagerySources` already takes.

### 3. Emit (backend — `stac.py` item build)

For each `ref` whose `programId` is in `OPEN_DATA_PROGRAMS`:

- **`derived_from` link** (full scene list — Decision #3):
  `{ "rel": "derived_from", "href": ref.href, "type": "application/json",
     "title": "<programName> — <title>" }`

- **`haste:source_imagery` property** (deduped per program — Decision #3):
  `[{ "program": "Vantor Open Data Program", "license": "CC-BY-NC-4.0",
      "sceneCount": 3, "url": <program url> }]`

For `sourceImageryCitation` (URL-aware — Decision #5):

- **is an `https` URL** → add `{ "rel": "derived_from", "href": <citation>,
  "type": "text/html", "title": "Source imagery" }` **and** set
  `haste:source_imagery_citation` to the URL.
- **plain text** → set `haste:source_imagery_citation` only (no link).

`haste:source_imagery` is deduped by **`programId`** (a scene count per program),
not per license.

### Local target — record only

`derived_from`/citation are STAC concepts and the Local target has no catalog
(and only per-file downloads, no bundle). The validated source-imagery
references + citation are kept on the `PublishedDataset` record and surfaced in
the HASTE UI (publish + view/edit dialogs); nothing extra is written to storage.

> A `source_imagery.json` sidecar was considered (to travel with the downloaded
> assets), but since downloads are per-artifact and the provenance is already
> visible in the UI, it was dropped as redundant. If per-file provenance ever
> matters, add it back and expose it as a download (not a silent blob).

## Published STAC output (example)

```jsonc
"properties": {
  "haste:source_imagery": [
    { "program": "Vantor Open Data Program", "license": "CC-BY-NC-4.0",
      "sceneCount": 2, "url": "https://vantor.com/..." }
  ],
  "haste:source_imagery_citation": "https://example.org/my-imagery-source"
},
"links": [
  { "rel": "derived_from", "type": "application/json",
    "href": "https://vantor-opendata.s3.amazonaws.com/events/caracas/scene-a.json",
    "title": "Vantor Open Data Program — Caracas pre-event" },
  { "rel": "derived_from", "type": "application/json",
    "href": "https://vantor-opendata.s3.amazonaws.com/events/caracas/scene-b.json",
    "title": "Vantor Open Data Program — Caracas post-event" },
  { "rel": "derived_from", "type": "text/html",
    "href": "https://example.org/my-imagery-source", "title": "Source imagery" }
]
```

---

## UX (publish dialog + edit-metadata dialog — Decision #4)

A **Source imagery** section in both dialogs, mirroring the `interactiveViewerUrl`
pattern already shipped:

- **Open-data layer** (has `sourceImageryReferences`): render them **read-only**
  as chips/links — program + license badge + per-scene titles — labeled
  *"auto-detected from open data."* Provenance is factual, so not editable in v1.
- **Any layer**: an optional **"Additional source citation"** input
  (`sourceImageryCitation`), URL-aware, placeholder `https://… or a citation`.
  Prefilled empty. For user-supplied imagery this is the *only* control shown —
  the "blank optional for user input" case.

On **edit**, `sourceImageryCitation` is editable; changing it re-emits the item's
citation link/property (reusing `update_published_metadata`). The structured refs
are not edited (they follow the source layer).

---

## Scalability

Adding a new open-data program:

1. Add an `OPEN_DATA_PROGRAMS` registry entry (name, license, url).
2. Add the program's discovery to the Open Data Catalog explorer (a new source).

Capture stamps `programId`; emit iterates generically. **No changes** to the data
model, the publish pipeline, or the STAC builder.

## Licensing note

Both current programs are **CC BY-NC 4.0 (non-commercial)**. The NC term can
propagate to *derived* products, so surfacing the source `license` on the
published item is a compliance feature, not just courtesy — the UI should show
the license badge prominently, and the STAC `haste:source_imagery.license`
carries it to downstream consumers.

## Resolved decisions (v1)

- **Local target** → keep provenance on the dataset record + shown in the UI;
  no storage sidecar (see *Local target — record only*).
- **Collection-level `derived_from`** → **out of scope for v1**; emitted per
  **item** only. A per-collection union (like the provider union) is deferred.
- **`haste:source_imagery` de-dup key** → by **`programId`**.

## Non-goals (v1)

- **Editing structured refs** — read-only in v1; the free-text citation is the
  escape hatch for corrections/additions.

## Testing sketch

- Capture: catalog add records a ref with the fetch-URL `href` (Vantor + Planet).
- Gate: a ref with an unknown `programId` is dropped; `attributable`/`license`
  from the client are ignored in favor of the registry.
- Emit (PC): N scenes → N `derived_from` links + `haste:source_imagery` deduped
  by `programId`; URL citation → link + property; text citation → property only.
- Emit (Local): provenance stays on the dataset record + UI; no sidecar written.
- Edit: changing the citation re-emits on the live item; refs unchanged.
- Non-open-data layer: no auto refs; only the optional citation is honored.

---

## Execution plan

Additive and backward-compatible throughout — all new fields default empty, so
existing datasets/layers are unaffected. No new runtime flag (behavior is gated
by data presence + PC enablement). Phases are ordered so each is independently
reviewable; **2 and 3 can run in parallel after 1**, and nothing is user-visible
until Phase 4.

### Phase 1 — Data model + open-data program registry

**Goal:** foundation types + the authoritative gate; no behavior change.

| Task | Files | Verification | Status |
|---|---|---|---|
| Add `SourceImageryRef` model | `models/publishing.py` | validates/serializes | done |
| Add fields: `ImageLayer.sourceImageryReferences`; `PublishDatasetOptions`/`PublishedDataset.sourceImageryReferences`; `sourceImageryCitation` on `PublishRequest`/`PublishedDataset`/`PublishMetadataUpdate` (URL-aware validator) | `models/projects.py`, `models/publishing.py` | defaults empty; citation normalizes | done |
| Add `OPEN_DATA_PROGRAMS` registry + `validate_source_refs()` (drop unknown `programId`; use registry `name`/`license`, ignore client-supplied) | `publishing/open_data.py` (new), `config.py` | unknown program dropped; client license overridden | done |
| Unit tests | `tests/core/{models,publishing}/` | model + validator covered | done |

**Exit:** models round-trip; validator is fail-safe (unknown → dropped, license from registry).

### Phase 2 — Catalog capture (UI)

**Goal:** persist provenance where it's known.

| Task | Files | Verification | Status |
|---|---|---|---|
| Capture the item **fetch URL** as `itemHref` (Vantor: thread `absUrl(l.href, baseUrl)` into `normalizeVantorItem`; Planet: use existing `itemUrl`); stamp `programId`/`license` | `OpenDataCatalog/openDataCatalog.js` | scene carries `itemHref`, `programId` | done |
| `onAddScene` records a `SourceImageryRef` into form state (keyed by phase); persist on layer create/update | `OpenDataCatalogPanel.jsx`, `CreateEditImageLayerForm.jsx`, `CreateEditImageLayerHelper.js` | catalog layer saved with refs; user layer has none | done |
| UI tests | `*.test.js`/`.jsx` | normalize + add-flow build refs | done |

**Exit:** a layer built from the catalog persists refs with fetch-URL hrefs; user-supplied layers stay empty.

### Phase 3 — Carry-through (backend)

**Goal:** move captured refs onto the dataset (mirrors `imagerySources`).

| Task | Files | Verification | Status |
|---|---|---|---|
| `resolve_options` copies validated `image_layer.sourceImageryReferences` → options | `publishing/source.py` | options expose validated refs | done |
| Processor copies refs + `request.sourceImageryCitation` → `PublishedDataset` | `processors/publishing.py` | dataset carries both | done |
| Tests | `tests/core/publishing/` | carry + gate at carry-time | done |

**Exit:** `GetPublishDatasetOptions` and the stored dataset expose validated refs.

### Phase 4 — Emit (PC `derived_from` + property)

**Goal:** produce the actual provenance output (first user-visible phase).

| Task | Files | Verification | Status |
|---|---|---|---|
| `build_vector_item`: emit `derived_from` links (all scenes) + `haste:source_imagery` (dedup by `programId`); URL-aware citation → link+property, text → property | `publishing/stac.py` | links + property shapes | done |
| `update_published_metadata`: re-emit citation on edit | `publishing/planetary_computer_provider.py` | edit re-emits | done |
| Local provider: provenance kept on the record + UI, no sidecar written | `publishing/local_provider.py` | no storage sidecar | done |
| Tests | `tests/core/publishing/` | PC + Local + edit paths | done |

**Exit:** PC item carries `derived_from` + property; Local keeps provenance on the record.

### Phase 5 — UI surfacing (publish + edit dialogs)

**Goal:** show provenance; accept the optional citation.

| Task | Files | Verification | Status |
|---|---|---|---|
| "Source imagery" section: read-only open-data chips (program + license badge + titles, "auto-detected"); optional URL-aware "Additional source citation" input, prefilled empty | `PublishDatasetModal.jsx`, `PublishedDatasetRow.jsx` | both dialogs | done |
| Wire `sourceImageryCitation` into publish + edit payloads | same | payload carries citation | done |
| UI tests | `*.test` | open-data vs user-supplied rendering | done |

**Exit:** publish/edit dialogs display refs and round-trip the citation.

### Phase 6 — Docs + end-to-end

| Task | Files | Verification | Status |
|---|---|---|---|
| Update `design.md`, `data-model.md`, `ux-spec.md`; add user story + `test-plan.md` rows | `spec/features/data-publishing/` | specs consistent | done |
| Local-docker smoke: catalog layer → publish → verify refs on dataset | — | e2e green | done |

**Exit:** specs consistent; end-to-end verified on the local instance.
