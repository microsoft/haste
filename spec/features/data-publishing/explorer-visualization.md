# Design: Planetary Computer Explorer Visualization

Stacked on top of the data-publishing feature (`-pc`). Delivered as its own
PR (`-pc-explorer`) whose base is `prbatero/feat/data-publishing-pc`.

## Contents

- [Goal](#goal)
- [Why they don't show today](#why-they-dont-show-today)
- [Core principle](#core-principle-visualize-our-output-never-redistribute-source-pixels)
- [What we add](#what-we-add)
- [Rasterization](#rasterization)
- [Render configuration](#render-configuration)
- [Flow (PC publish)](#flow-pc-publish)
- [Idempotency](#idempotency-re-publish--second-dataset)
- [Configuration (env)](#configuration-env)
- [Scope](#scope)
- [Non-goals (v1)](#non-goals-v1)
- [Open decisions](#open-decisions)
- [Testing sketch](#testing-sketch)
- [Execution plan](#execution-plan)

## Goal

Make Planetary Computer (PC) published collections **visible and explorable in
the GeoCatalog Explorer**. Today a published collection is created and listed
under the Collections tab, but it has no "Launch in Explorer" action and does
not appear in the Explorer's dataset picker.

## Why they don't show today

Per the GeoCatalog docs, a collection is explorable only when it has, in
addition to `item_assets` + ingested items, a **visualization configuration**:

- a **render configuration** (`…/configurations/render-options`) — mandatory;
  without it "Launch in Explorer" is disabled,
- a **mosaic** (`…/configurations/mosaics`),
- **tile settings** (`…/configurations/tile-settings`).

We create none of these. Two facts compound the problem:

1. **We create no render/mosaic/tile config** — so nothing is explorable.
2. The Explorer renderer is **TiTiler raster-only** (every render `type` is
   `raster-tile`; `options` is a TiTiler query string over raster bands). Our
   PC item assets are **vector-only** (`damage`/`footprints` GeoPackage, `aoi`
   GeoJSON), so even with a render config there is nothing raster to draw.

## Core principle: visualize our output, never redistribute source pixels

The source imagery (Planet/Vantor/etc.) is licensed; republishing the processed
COG into a PC collection is a redistribution governed by that license and is
**out of scope**. Instead we render **our own derived output**: a small
single-band classification COG (damaged / undamaged), rasterized from the damage
GeoPackage we already publish. It contains **no source pixels**, so it carries
exactly the same license/attribution the vector output already carries and adds
no new licensing exposure. See [source-imagery-provenance](source-imagery-provenance.md)
for the attribution/provenance model this reuses.

## What we add

| Piece | Mechanism | Notes |
|---|---|---|
| Damage classification COG | `rasterio.features.rasterize` over footprints | our output; single-band `uint8`; PC target only |
| Item asset `damage_class` | STAC item asset, role `data` | the renderable raster; + collection `item_assets` entry |
| Render option | `POST …/configurations/render-options` | colormap `1→red, 0→grey, 255→transparent`, matching the thumbnail |
| Mosaic | `POST …/configurations/mosaics` | `most-recent`, `cql: []` (show all items) |
| Tile settings | `PUT …/configurations/tile-settings` | `minZoom` at building scale |

## Rasterization

Reuse `publishing/tile.py`'s `detect_damage_mask(buildings)` (the same
damaged/undamaged detection the collection thumbnail uses) so the raster and the
thumbnail agree.

- **Input:** the damage GeoPackage (already fetched for the thumbnail) + the AOI
  valid-mask, both already in hand during publish.
- **Grid:** a projected CRS (AOI's UTM / the layer CRS) for correct pixel sizes;
  extent clipped to the AOI bounds.
- **Encoding (single band, `uint8`):** `1 = damaged`, `0 = undamaged`,
  `255 = nodata` (outside footprints). Undamaged footprints are burned as `0`
  so they read as grey; everything outside a footprint is transparent.
- **Resolution:** `PUBLISH_DAMAGE_RASTER_METERS` (default `0.5` m), with a hard
  cap on output dimensions (`PUBLISH_DAMAGE_RASTER_MAX_PIXELS`, default e.g.
  8192 per side) — if the AOI at target resolution would exceed the cap, coarsen
  the pixel size to fit. Log when coarsened (no silent truncation).
- **Output:** a valid COG (tiled + overviews) so TiTiler serves it efficiently.

## Render configuration

```jsonc
// render-options (one entry)
{
  "id": "damage",
  "name": "Damage classification",
  "description": "Predicted building damage (red) over undamaged (grey).",
  "type": "raster-tile",
  "options": "assets=damage_class&nodata=255&colormap=<urlencoded {0:[grey],1:[red]}>",
  "minZoom": 13
}
// mosaic
{ "id": "most-recent", "name": "Most recent available", "cql": [] }
// tile-settings
{ "minZoom": 13, "maxItemsPerTile": 35 }
```

The colormap is the URL-encoded JSON discrete map (`0 → grey RGBA`,
`1 → red RGBA`); `nodata=255` keeps outside-footprint pixels transparent.

## Flow (PC publish)

1. Collection ensured/updated + item created (existing flow, unchanged).
2. Rasterize damage → COG (temp dir); upload to the publish store
   `published/<datasetId>/damage_class.tif`.
3. Item gains a `damage_class` asset (role `data`, COG media type); the
   collection `item_assets` gains a matching `damage_class` entry.
4. After the item is confirmed, register render-option + mosaic + tile-settings
   for the collection (idempotent; once per collection).
5. Unpublish: `finalize_unpublish` already deletes `published/<datasetId>/`, so
   the classification COG is cleaned up with the rest of the staging prefix.

Staging + cleanup reuse the `-pc` publish store and `finalize_unpublish` hook.

## Idempotency (re-publish / second dataset)

- The COG is per-dataset (`published/<datasetId>/`), regenerated per publish.
- Collection-level config (render/mosaic/tile) is per-collection: create once,
  tolerate "already exists" on re-publish (GET-or-409 → skip, or PUT where the
  API is replace-semantics). Never duplicate render options across datasets.

## Configuration (env)

| Setting | Default | Notes |
|---|---|---|
| `PUBLISH_EXPLORER_RENDER_ENABLED` | `true` | master toggle for this feature |
| `PUBLISH_DAMAGE_RASTER_METERS` | `0.5` | target pixel size (m) |
| `PUBLISH_DAMAGE_RASTER_MAX_PIXELS` | `8192` | per-side cap; coarsen to fit |
| `PUBLISH_DAMAGE_RASTER_MIN_ZOOM` | `13` | render/tile `minZoom` |

## Scope

- **PC target only.** Local publishing is unaffected (downloads only).
- **Vendor imagery is never redistributed.** Only the derived classification COG
  is published.
- Vector assets (`damage`, `footprints`, `aoi`) remain as downloadable item
  assets; they are not rendered (the Explorer can't render vector).

## Non-goals (v1)

- Damage **severity** classes (data carries a binary damaged flag today) — the
  encoding leaves room (`uint8`) to extend later.
- Rendering the source imagery backdrop (licensing; see principle above).
- Local-target Explorer parity (Local has no Explorer).

## Open decisions

| # | Decision | Choice |
|---|---|---|
| 1 | What to render | Binary damaged/undamaged classification COG (our output) |
| 2 | Colormap | `1→red`, `0→grey`, `255→transparent` (matches thumbnail) |
| 3 | Resolution | `0.5` m default, capped per-side, coarsen to fit |
| 4 | Where generated | PC provider at publish time (reuses publish store + cleanup) |
| 5 | Config lifecycle | Per-collection, idempotent; COG per-dataset |

## Testing sketch

- Rasterization: damaged → `1`, undamaged → `0`, outside → `255`; extent matches
  AOI; coarsening triggers past the pixel cap; output is a readable COG.
- Transport: render-option / mosaic / tile-settings POST/PUT bodies + idempotent
  re-publish (existing config not duplicated).
- Provider: publish wires the `damage_class` asset + registers config; second
  dataset to the same collection doesn't duplicate render options; unpublish
  removes the staging COG.

## Execution plan

| Phase | Task | Files | Status |
|---|---|---|---|
| 1 | Rasterize damage → classification COG (reuse `detect_damage_mask`) | `publishing/raster.py` (new), `publishing/tile.py` | done |
| 2 | Publish COG as `damage_class` item asset (+ `item_assets`) | `publishing/planetary_computer_provider.py` | done |
| 3 | Transport: render-options / mosaics / tile-settings methods | `publishing/planetary_computer_transport.py` | done |
| 4 | Wire config registration into publish flow (idempotent) | `publishing/planetary_computer_provider.py` | done |
| 5 | Config knobs + tests + this spec | `config.py`, `tests/core/publishing/` | done |
