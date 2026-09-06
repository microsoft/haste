# Data Model: Common Prediction Results

**Contents:** [Ownership](#ownership) - [Result metadata](#result-metadata) -
[Sidecar schema](#sidecar-schema) - [Compatibility](#compatibility)

## Ownership

| Artifact | Owner | Production |
|---|---|---|
| Footprint GeoPackage and PMTiles | Image layer | Footprint cache and existing #183 tiling job |
| Embedding feature sidecar | Embedding model | Embedding job; unchanged |
| Prediction GeoPackage | Model | Interactive prediction save or standard inference |
| Prediction attribute sidecar | Model/prediction output | Same producer as its prediction GeoPackage |

## Result Metadata

Persist `predictionAttrsUrl` alongside the current prediction GeoPackage pointer.
Interactive models persist `predictedBuildingCount` and `predictedAt`; an empty
save must not remain ready because a GeoPackage URL exists. Result readiness
must not accept stale attributes after prediction regeneration.

The per-model `prediction_results` metadata document is authoritative for the
current generation and inference-publication fields. `Model` retains mirrors
for older consumers. New result reads overlay the authoritative record, so an
unrelated stale full-Model save cannot restore superseded pointers or readiness.
Absence of the authoritative record does not verify an existing generation
mirror; it remains unavailable until a valid publication occurs.

Shared-storage publishers serialize through the existing renewable Blob lease
coordinator; local metadata uses a process-shared filesystem lock and atomic
JSON replacement. These serialize participating publishers, not all metadata
writers or a transaction spanning Batch submission and blob uploads.
The authority write is mandatory; a failed compatibility-mirror write is logged
without stranding a committed generation before queue publication.

Model deletion uses that same publisher lock and leaves an empty deleted
generation barrier before removing the Model. The fresh barrier prevents late
first saves or completions from attaching to a replacement with reused IDs.
Cancellation persists intent against the captured generation; a request whose
generation changed while waiting returns a conflict instead of cancelling its
replacement.

`predictionRevision` identifies a raw generation, not an edited version number.
Generation-specific paths make the published GeoPackage/sidecar pair immutable
while a later generation is being produced. Reject stale revision requests
rather than returning the new artifact under an old cache key.

Keep raw prediction row identities compatible with layer footprint tile IDs.
Add explicit Overture IDs where the current producer only preserves positions.
Preserve non-finite/unknown score semantics in a valid JSON representation.

## Sidecar Schema

```json
{
  "schemaVersion": 1,
  "predictionRevision": "opaque-generation-id",
  "flavor": "inference",
  "n": 2,
  "ids": [0, 1],
  "overtureIds": ["building-a", "building-b"],
  "damage": [0.25, null],
  "unknown": [0.0, null],
  "damaged": [1, 0],
  "classes": ["Damaged", "Unknown"]
}
```

All columns have length `n`; IDs preserve the cached footprint order.
Scores are fractions or null, never invalid JSON NaN/Infinity. Validate stored
prediction IDs and Overture IDs against the footprint source. Class labels
also exist on raw results: their presence does not mean the artifact is edited.
The later editor uses explicit version provenance to decide that.

## Compatibility

New fields are optional for old documents. Old predictions without attributes
remain downloadable; the common vector view reports the missing artifact.
There is no automatic migration, new queue, or change to storage containers.
