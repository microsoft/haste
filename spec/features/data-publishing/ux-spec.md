# UX Specification: Data Publishing & Published Datasets

> New UI reuses the existing `pgrid-*` catalog layout, Fluent UI v9 components,
> `theme.js`/`ThemeContext`, and the `icons.jsx` `FluentIcon` wrapper. The two
> anchor patterns are `ModelCatalog.jsx` (the section) and the existing modals /
> `ModelResultsButton.jsx` menu (the entry point + dialog).

## Entry points

### 1. "Publish dataset…" on model results

Added to the results menu in
[ModelResultsButton.jsx](../../../ui/src/Components/ProjectManagement/ModelResultsButton.jsx),
after **Assessment Report** (the menu today: View · Download Geopackage ·
Download Training/Inference Artifacts · Validation Report · Assessment Report):

```
┌─ results menu ───────────────┐
│ View                         │
│ Download Geopackage (.gpkg)  │
│ Download Training Artifacts  │
│ Download Inference Artifacts │
│ Validation Report            │
│ Assessment Report            │
│ ─────────────────────────    │
│ ⇪ Publish dataset…           │  ← NEW (FluentIcon "Share"/"CloudArrowUp")
└──────────────────────────────┘
```

- **Enabled** only when the model is completed and has ≥1 publishable artifact
  (`model.gpkgUrl` present). Otherwise disabled with tooltip "Run inference to
  produce a dataset before publishing."
- Click → opens **Publish Dataset dialog** (below).

### 2. Sidebar → Published Datasets section

New nav item in [AppSidebar.jsx](../../../ui/src/Components/AppSidebar.jsx),
grouped near **Model Catalog**; route `/published-datasets` in
[AppBody.jsx](../../../ui/src/Components/AppBody.jsx). Icon: `Database` /
`CloudArrowUp`. Visible to all authenticated users (see
[permissions](#permissions--access-control)).

## Publish Dataset dialog

Fluent UI **Dialog** (small form → `Dialog`/`DialogSurface`/`DialogBody`, as in
`SectionModal.jsx`; may use `OverlayDrawer` per the app's modal convention). Fields:

```
┌─ Publish dataset ───────────────────────────────── ✕ ┐
│                                                      │
│  Dataset name *                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │ Hurricane Harvey – Downtown Layer              │ │  ← prefilled '<project> – <layer>', editable
│  └────────────────────────────────────────────────┘ │
│                                                      │
│  Description                                         │
│  ┌────────────────────────────────────────────────┐ │
│  │ 1,234 of 5,000 known buildings predicted       │ │  ← prefilled from assessment report
│  │ damaged (precision 0.82, recall 0.77)…         │ │     summary; editable (Textarea)
│  └────────────────────────────────────────────────┘ │
│                                                      │
│  Assets to publish *                                 │
│   ☑ Damage GeoPackage (.gpkg)          2.3 MB        │  ← checkboxes, one per AVAILABLE
│   ☑ Valid-area mask (.geojson)         120 KB        │     output; prechecked; ≥1 required
│   ☑ Building footprints (.gpkg)        1.1 MB        │
│   ☑ Processed image (COG .tif)         48 MB         │
│   ☐ Training artifacts (.zip)          —  (grayed if │
│                                             absent)  │
│                                                      │
│  Target publishing location *                        │
│  ┌────────────────────────────────────────────────┐ │
│  │ Local (In App storage)                    ▾    │ │  ← Dropdown; options from
│  └────────────────────────────────────────────────┘ │     GetPublishingProviders
│    • Local (In App storage)                           │
│    • Planetary Computer   (disabled if not configured)│
│                                                      │
│  [provider hint / validation message]                │
│                                                      │
│                        [ Cancel ]   [ Publish ]      │
└──────────────────────────────────────────────────────┘
```

- **Dataset name** — `Input`, required, prefilled `${projectName} – ${layerName}`,
  editable. Validation via existing `util/validation.js` (`validateEmptyOrInvalid`).
- **Description** — `Textarea`, optional, prefilled from the assessment report
  summary. Prefill source: `GetAssessmentReport` + shared
  `assessmentSummary.buildSummarySentence()` (extracted from
  `AssessmentReportModal.jsx`). If the report is unavailable, field is blank.
- **Assets to publish** — a `Checkbox` list, **one per artifact the source model
  actually produced** (resolved from the model/layer documents, with size where
  known). All available assets are **prechecked** by default; artifacts the model
  did not produce are shown grayed/disabled (or omitted). At least one asset must
  be selected. Candidate kinds: Damage GeoPackage (`gpkg`), Valid-area mask
  (`valid_mask`), Building footprints (`footprints`), Processed image COG
  (`processed_cog`); optionally training/inference artifact zips. The selection is
  sent as `artifacts: [...]` in the publish request and determines exactly what is
  copied (Local) or turned into STAC assets/items (Planetary Computer).
- **Target** — `Dropdown`, required, options from `GetPublishingProviders`.
  Unconfigured providers render **disabled** with a "not configured" note. If a
  provider declares `configRequirements`, surface them as helper text /
  validation (provider-agnostic — no per-provider UI hard-coding).
- **Publish** — validates, calls `PutPublishDatasetQueueMessage`, shows a success
  toast/dialog ("Publishing started — track it in Published Datasets"), closes.
- **Cancel / ✕** — dismiss, no side effects.

### Dialog states

| State | UI |
|---|---|
| Loading prefill | Name/target ready immediately; asset checklist populated from the model's available outputs; description shows a subtle spinner until the assessment report resolves (non-blocking) |
| No assets selected | Publish disabled; inline hint "Select at least one asset to publish" |
| Validation error | Field-level `validationMessage` (name) or dialog-level banner (target/provider) |
| Submitting | Publish button shows spinner + disabled; fields locked |
| Submit success | Toast/confirmation + close; new row appears in section as IN_PROGRESS |
| Submit conflict (409) | Banner "A dataset with this name is already publishing" |
| Submit failure (5xx) | Banner with retry; dialog stays open |

## Published Datasets section

Catalog-style page modeled on `ModelCatalog.jsx` — `pgrid-page` container,
`pgrid-header` (title + subtitle + info tooltip), `pgrid-toolbar` (`SearchBox` +
optional target/status filters), sortable table, `pgrid-footer` pagination with
`PAGE_SIZE_OPTIONS`.

```
┌─ Published Datasets ─────────────────────────────────── ⓘ ┐
│  Curated, described outputs published from HASTE results.  │
│                                                            │
│  [ 🔍 Search ]         Target: [All ▾]   Status: [All ▾]   │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ Name ↕ | Project/Layer | Target | Status | By | Date  │ │
│ ├──────────────────────────────────────────────────────┤ │
│ │ Harvey – Downtown | Harvey/L1 | Local | ✅ Published |…│ │
│ │ Ida – Coast       | Ida/L2    | 🌐 PC  | ⏳ Publishing|…│ │
│ │ Fiona – North     | Fiona/L1  | 🌐 PC  | ❌ Failed    |…│ │
│ └──────────────────────────────────────────────────────┘ │
│  Showing 1–8 of 23        Rows: [8 ▾]     ‹ Prev  Next ›   │
└────────────────────────────────────────────────────────────┘
```

Columns: **Name**, **Project / Layer**, **Target** (Local / Planetary Computer
with icon), **Status** (chip), **Published by**, **Published date**, **Actions**.
Sortable columns mirror the catalog (`toggleSort`, `{key, dir}` state). Row
actions (menu on `PublishedDatasetRow.jsx`):

- **Published (Local):** Download each artifact (reuses `fileDownload`).
- **Published (PC):** Open in Explorer / Copy STAC collection link.
- **In progress:** actions disabled; live status.
- **Failed:** show `statusMessage`; Retry (re-publish); Remove.
- **Owner/admin:** Edit metadata; Unpublish (`DeletePublishedDataset`, with
  confirm).

**Edit metadata** (`PutUpdatePublishedDataset`, owner/admin) opens an inline
form on `PublishedDatasetRow.jsx`, available only for datasets in a terminal
state (`PUBLISHED` / `FAILED` / `UNPUBLISH_FAILED`) — in-progress records aren't
editable, enforced both in the UI and server-side in `update_metadata`. Editable
fields: **name**, **description**, **interactive viewer URL** (optional https
`rel=preview` link), and **source-imagery citation** (optional free-text /
URL-aware attribution surfaced on the dataset). Imagery-source provider
attribution is inferred from the image-layer source type and is not editable.
For a PC dataset the edit pushes to the live STAC item
(title/description/preview-link + `providers` + citation) and refreshes the
collection's rolling summary and provider union; for Local it updates the stored
record only.

## UI states (all)

| State | Trigger | UX |
|---|---|---|
| **Empty** | No datasets published | Icon + "No published datasets yet" + one-line guide "Publish from a model's results menu" (mirrors ModelCatalog empty state) |
| **Loading** | Section fetch in flight | Full-page overlay spinner via `appContext.setIsLoading()` (catalog pattern) |
| **No results (filtered)** | Search/filter matches nothing | `NoResultsMessage` with a clear-search action |
| **In progress** | Dataset status IN_PROGRESS/PENDING | Row chip "⏳ Publishing…"; UI polls `GetPublishedDatasets` (or per-row `GetPublishedDataset`) on an interval until terminal; no broken links |
| **Success** | Status PUBLISHED | Row chip "✅ Published"; retrieval actions enabled |
| **Failure** | Status FAILED | Row chip "❌ Failed"; expandable `statusMessage`; Retry / Remove |

Status chips use Fluent tokens (`colorPaletteGreenForeground1`,
`colorPaletteYellowForeground1`, `colorPaletteRedForeground1`) via
`theme.js`/`ThemeContext`, consistent with the app's theming.

## How published datasets are displayed and accessed

- **Discovery:** the Published Datasets section (searchable/sortable/paginated).
- **Local retrieval:** direct SAS download per artifact via `fileDownload`
  (same mechanism as the current results downloads).
- **Planetary Computer retrieval:** external links to the GeoCatalog collection
  and Explorer; STAC collection URL is copyable for programmatic use. **Set
  expectations in the UI:** in the PC Explorer a published dataset shows as item
  **footprints + metadata**, and the damage **GeoPackage is download-only** — PC
  Pro does not tile/render vector data, so the damage layer is not drawn on the
  Explorer map (rasterized-COG rendering is a future enhancement). A short
  helper note on PC-target rows/detail should say "Footprints + metadata in
  Explorer; download the GeoPackage for the damage layer."
- **Provenance:** each row exposes source project/layer/model + the assessment
  summary snapshot.

## Permissions & access control

| Action | Who | Enforcement |
|---|---|---|
| See the Published Datasets section | Any authenticated user | Route available to all logged-in users (like Model Catalog viewing) |
| Publish a dataset | Any user who can access the source project/model | Same access as viewing/downloading the model's results today |
| Unpublish / Retry / Remove | The publisher (`publishedByUser`) or an Admin | API checks the client principal (`_decode_client_principal`); UI hides the action otherwise |
| Configure Planetary Computer target | Admin / operator (app settings) | Config via App Settings; UI reflects `isConfigured` from `GetPublishingProviders` |

> v1 assumes "public within the tenant" visibility (no per-dataset ACLs), matching
> the current Model Catalog model. Per-dataset sharing lists are out of scope
> ([user-stories.md](user-stories.md#out-of-scope)).

## Accessibility & responsiveness

- Fluent UI components provide keyboard/focus/ARIA defaults; dialog traps focus
  and closes on Esc.
- Section table follows the responsive `pgrid`/Bootstrap breakpoints
  (`appParams.bootstrapBreakpoint`); on narrow widths the table collapses to
  stacked cards (as ModelCatalog does).
- Status conveyed by icon **and** text (not color alone).
