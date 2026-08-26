import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import geopandas as gpd
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..models.publishing import (
    ArtifactBundle,
    ArtifactKind,
    PublishedDataset,
    SourceArtifact,
    is_https_url,
)
from .open_data import OPEN_DATA_PROGRAMS, validate_source_refs

COLLECTION_ID_MAX_LENGTH = 242
ITEM_ID_MAX_LENGTH = 149
ASSET_KEY_MAX_LENGTH = 255
STAC_VERSION = "1.0.0"
ITEM_ASSETS_EXTENSION = (
    "https://stac-extensions.github.io/item-assets/v1.0.0/schema.json"
)
PROJECTION_EXTENSION = (
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
)
EXTENSION_SCHEMA_FILES = {
    ITEM_ASSETS_EXTENSION: "item-assets-v1.0.0.json",
    PROJECTION_EXTENSION: "projection-v2.0.0.json",
}

ASSET_KEYS = {
    ArtifactKind.GPKG: "damage",
    ArtifactKind.VALID_MASK: "aoi",
    ArtifactKind.FOOTPRINTS: "footprints",
}
ASSET_ROLES = {
    ArtifactKind.GPKG: ["data"],
    ArtifactKind.VALID_MASK: ["metadata"],
    ArtifactKind.FOOTPRINTS: ["data"],
}
ASSET_TITLES = {
    ArtifactKind.GPKG: "Damage assessment",
    ArtifactKind.VALID_MASK: "Valid assessment area",
    ArtifactKind.FOOTPRINTS: "Building footprints",
}

# Namespace for HASTE's custom STAC fields. Kept as a single constant so the
# published identifier is tool-neutral and can be changed in one place.
PROPERTY_PREFIX = "haste"
PROJECT_ID_PROPERTY = f"{PROPERTY_PREFIX}:project_id"

# Compact per-dataset summaries persisted on the (project-level) collection so
# its description can be rendered as a rolling summary of every dataset it
# holds. Read back from the existing collection on the next publish/unpublish.
COLLECTION_DATASETS_FIELD = f"{PROPERTY_PREFIX}:datasets"

# Well-known Earth-observation imagery sources, keyed by lowercase substrings
# that may appear in an image layer's free-text source type (e.g. "WorldView-3"
# → Vantor). The first table whose keys match wins; unmatched source types are
# passed through verbatim as the provider name (no URL). Intentionally small and
# easy to extend — add rows as new sensors/vendors are onboarded.
# Note: the legacy "maxar" key is retained because that is still the stored
# ``sourceType`` value for Vantor (formerly Maxar) Open Data layers.
_IMAGERY_PROVIDERS: Tuple[Tuple[Tuple[str, ...], Tuple[str, Optional[str]]], ...] = (
    (
        ("worldview", "geoeye", "quickbird", "maxar", "vantor"),
        ("Vantor", "https://vantor.com"),
    ),
    (
        ("planet", "planetscope", "skysat", "rapideye", "dove"),
        ("Planet Labs PBC", "https://www.planet.com"),
    ),
    (
        ("pleiades", "spot", "airbus"),
        ("Airbus Defence and Space", "https://space-solutions.airbus.com"),
    ),
    (
        ("sentinel",),
        ("European Space Agency (Copernicus)", "https://www.copernicus.eu"),
    ),
    (
        ("landsat",),
        ("USGS / NASA Landsat", "https://www.usgs.gov/landsat-missions"),
    ),
    (
        ("naip",),
        ("USDA NAIP", "https://naip-usdaonline.hub.arcgis.com"),
    ),
)


def _imagery_provider_info(source_type: str) -> Optional[Dict[str, Optional[str]]]:
    """Map a free-text imagery source type to a provider name (and URL).

    Unmatched, non-empty source types are passed through as the provider name
    with no URL. Empty/whitespace source types yield ``None``.
    """
    normalized = source_type.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    for keys, (name, url) in _IMAGERY_PROVIDERS:
        if any(key in lowered for key in keys):
            return {"name": name, "url": url}
    return {"name": normalized, "url": None}


def build_providers(
    organization: Optional[Mapping[str, Optional[str]]],
    imagery_sources: Optional[Sequence[str]],
) -> list:
    """Build the STAC ``providers`` list for a collection or item.

    Imagery sources are attributed as producers/licensors of the underlying
    data; the deployment's processing organization (if configured) as the
    processor that derived the assessment. Deduplicated by provider name.
    """
    pystac = _load_pystac()
    providers = []
    seen = set()
    for source in imagery_sources or []:
        info = _imagery_provider_info(source)
        if info is None or info["name"].lower() in seen:
            continue
        seen.add(info["name"].lower())
        providers.append(
            pystac.Provider(
                name=info["name"],
                url=info["url"],
                roles=[
                    pystac.ProviderRole.PRODUCER,
                    pystac.ProviderRole.LICENSOR,
                ],
            )
        )
    if organization and organization.get("name"):
        name = str(organization["name"]).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            providers.append(
                pystac.Provider(
                    name=name,
                    url=organization.get("url") or None,
                    roles=[pystac.ProviderRole.PROCESSOR],
                )
            )
    return providers


def source_imagery_property(refs: Sequence[Any]) -> list:
    """Compact per-program source-imagery display value, deduped by programId."""
    by_program: Dict[str, Dict[str, Any]] = {}
    for ref in refs:
        entry = by_program.get(ref.programId)
        if entry is None:
            program = OPEN_DATA_PROGRAMS.get(ref.programId) or {}
            entry = {
                "program": ref.programName,
                "license": ref.license,
                "sceneCount": 0,
            }
            if program.get("url"):
                entry["url"] = program["url"]
            by_program[ref.programId] = entry
        entry["sceneCount"] += 1
    return list(by_program.values())


def _add_source_imagery_provenance(
    item: Any, dataset: PublishedDataset
) -> None:
    """Emit ``derived_from`` links + ``haste:source_imagery`` for the source
    scenes an output was derived from, plus the URL-aware user citation.

    References are re-validated against the open-data registry (fail-safe): any
    that are not from a registered program are dropped.
    """
    pystac = _load_pystac()
    refs = validate_source_refs(
        getattr(dataset, "sourceImageryReferences", None)
    )
    for ref in refs:
        title = (
            f"{ref.programName} — {ref.title}"
            if ref.title
            else ref.programName
        )
        item.add_link(
            pystac.Link(
                rel="derived_from",
                target=ref.href,
                media_type=pystac.MediaType.JSON,
                title=title,
            )
        )
    if refs:
        item.properties[
            f"{PROPERTY_PREFIX}:source_imagery"
        ] = source_imagery_property(refs)

    citation = getattr(dataset, "sourceImageryCitation", None)
    citation = citation.strip() if isinstance(citation, str) else None
    if citation:
        item.properties[
            f"{PROPERTY_PREFIX}:source_imagery_citation"
        ] = citation
        if is_https_url(citation):
            item.add_link(
                pystac.Link(
                    rel="derived_from",
                    target=citation,
                    media_type="text/html",
                    title="Source imagery",
                )
            )


@dataclass(frozen=True)
class ValidMaskGeometry:
    geometry: Dict[str, Any]
    bbox: Sequence[float]
    area_square_kilometers: float


@dataclass(frozen=True)
class StacObjects:
    collection: Any
    item: Any


@dataclass(frozen=True)
class StacDocuments:
    collection: Dict[str, Any]
    item: Dict[str, Any]


def _sanitize_identifier(
    value: str,
    *,
    punctuation: str,
    max_length: int,
) -> str:
    normalized = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
    )
    normalized = re.sub(r"\s+", "-", normalized)
    allowed = re.escape(punctuation)
    normalized = re.sub(
        rf"[^A-Za-z0-9{allowed}]",
        "-",
        normalized,
    )
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = normalized[:max_length]
    if not re.search(r"[A-Za-z0-9]", normalized):
        raise ValueError("STAC identifier must contain a letter or digit")
    return normalized


def sanitize_collection_id(value: str) -> str:
    return _sanitize_identifier(
        value,
        punctuation="-_.",
        max_length=COLLECTION_ID_MAX_LENGTH,
    )


def sanitize_item_id(value: str) -> str:
    return _sanitize_identifier(
        value,
        punctuation="-_+,.()",
        max_length=ITEM_ID_MAX_LENGTH,
    )


def sanitize_asset_key(value: str) -> str:
    return _sanitize_identifier(
        value,
        punctuation="-_+,.()",
        max_length=ASSET_KEY_MAX_LENGTH,
    )


def build_collection_id(
    dataset: PublishedDataset,
    collection_prefix: str = "haste-",
) -> str:
    project_id = str(dataset.projectId).lower()
    prefix = _sanitize_identifier(
        collection_prefix,
        punctuation="-_.",
        max_length=COLLECTION_ID_MAX_LENGTH - len(project_id),
    )
    return sanitize_collection_id(f"{prefix}{project_id}")


def build_item_id(dataset: PublishedDataset) -> str:
    return sanitize_item_id(str(dataset.datasetId))


def resolve_valid_mask_geometry(
    valid_mask: Mapping[str, Any],
    source_crs: str = "EPSG:4326",
) -> ValidMaskGeometry:
    if valid_mask.get("type") != "FeatureCollection":
        raise ValueError("Valid-area mask must be a GeoJSON FeatureCollection")
    features = valid_mask.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Valid-area mask must contain at least one feature")

    geometries = []
    for feature in features:
        if not isinstance(feature, Mapping) or not feature.get("geometry"):
            raise ValueError("Valid-area mask feature is missing geometry")
        geometry = shape(feature["geometry"])
        if geometry.is_empty:
            raise ValueError("Valid-area mask geometry must not be empty")
        geometries.append(geometry)

    try:
        source_geometries = gpd.GeoSeries(geometries, crs=source_crs)
        wgs84_geometries = source_geometries.to_crs("EPSG:4326")
    except (CRSError, TypeError, ValueError) as error:
        raise ValueError("Valid-area mask CRS is invalid") from error

    combined = unary_union(wgs84_geometries.tolist())
    if combined.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Valid-area mask must contain polygon geometry")
    if not combined.is_valid:
        raise ValueError("Valid-area mask geometry is invalid")

    bounds = list(combined.bounds)
    if not all(math.isfinite(value) for value in bounds):
        raise ValueError("Valid-area mask bounds must be finite")
    if not (
        -180 <= bounds[0] <= bounds[2] <= 180
        and -90 <= bounds[1] <= bounds[3] <= 90
    ):
        raise ValueError("Valid-area mask bounds must be within EPSG:4326")

    projected = gpd.GeoSeries([combined], crs="EPSG:4326").to_crs("EPSG:6933")
    return ValidMaskGeometry(
        geometry=mapping(combined),
        bbox=bounds,
        area_square_kilometers=float(projected.area.iloc[0] / 1_000_000),
    )


def build_vector_item(
    dataset: PublishedDataset,
    source: ArtifactBundle,
    valid_mask: Mapping[str, Any],
    asset_hrefs: Mapping[str, str],
    projection_codes: Mapping[str, str],
    collection_href: str,
    *,
    valid_mask_crs: str = "EPSG:4326",
    collection_prefix: str = "haste-",
    license_id: str = "proprietary",
    organization: Optional[Mapping[str, Optional[str]]] = None,
) -> Any:
    pystac = _load_pystac()
    if not source.selectedArtifacts:
        raise ValueError("Select at least one artifact to publish")
    mask_geometry = resolve_valid_mask_geometry(valid_mask, valid_mask_crs)
    collection_id = build_collection_id(dataset, collection_prefix)
    properties = _build_item_properties(
        dataset,
        mask_geometry.area_square_kilometers,
        license_id,
    )
    item = pystac.Item(
        id=build_item_id(dataset),
        geometry=mask_geometry.geometry,
        bbox=list(mask_geometry.bbox),
        datetime=_parse_timestamp(dataset.createdDate),
        properties=properties,
        stac_extensions=[PROJECTION_EXTENSION],
        collection=collection_id,
    )
    item.add_link(
        pystac.Link(
            rel=pystac.RelType.COLLECTION,
            target=_require_https_url(
                collection_href, "GeoCatalog collection"
            ),
            media_type=pystac.MediaType.JSON,
        )
    )

    seen_keys = set()
    selected_projections = {}
    for artifact in source.selectedArtifacts:
        if artifact.kind not in ASSET_KEYS:
            raise ValueError(
                f"Unsupported Planetary Computer artifact: "
                f"{artifact.kind.value}"
            )
        asset_key = sanitize_asset_key(ASSET_KEYS[artifact.kind])
        if asset_key in seen_keys:
            raise ValueError(f"Duplicate STAC asset key: {asset_key}")
        seen_keys.add(asset_key)
        href = _require_https_href(
            asset_hrefs.get(artifact.sourcePath), artifact
        )
        projection_code = _projection_code(
            artifact,
            projection_codes,
            valid_mask_crs,
        )
        selected_projections[artifact.kind] = projection_code
        item.add_asset(
            asset_key,
            pystac.Asset(
                href=href,
                media_type=artifact.mediaType,
                title=ASSET_TITLES[artifact.kind],
                roles=ASSET_ROLES[artifact.kind],
                extra_fields={"proj:code": projection_code},
            ),
        )

    for kind in (
        ArtifactKind.GPKG,
        ArtifactKind.FOOTPRINTS,
        ArtifactKind.VALID_MASK,
    ):
        if kind in selected_projections:
            item.properties["proj:code"] = selected_projections[kind]
            break

    # Attribution: imagery source(s) as producers/licensors, the deployment's
    # processing organization as processor. Item-level for per-dataset accuracy.
    providers = build_providers(
        organization, getattr(dataset, "imagerySources", None)
    )
    if providers:
        item.properties["providers"] = [
            provider.to_dict() for provider in providers
        ]

    # Provenance: link the specific source scenes this output was derived from
    # (open-data programs only) + the optional URL-aware user citation.
    _add_source_imagery_provenance(item, dataset)

    # Optional operator-provided link to an interactive web viewer for this
    # dataset (rel=preview, text/html) — the vendored pattern, in place of an
    # image thumbnail on the item.
    viewer_url = getattr(dataset, "interactiveViewerUrl", None)
    if viewer_url:
        item.add_link(
            pystac.Link(
                rel="preview",
                target=_require_https_url(viewer_url, "interactive viewer"),
                media_type="text/html",
                title="Interactive viewer",
            )
        )
    return item


def _collection_dataset_entry(
    dataset: PublishedDataset, item: Any
) -> Dict[str, Any]:
    """Compact summary of one dataset for the collection's rolling description."""
    properties = getattr(item, "properties", None) or {}
    entry: Dict[str, Any] = {
        "id": str(dataset.datasetId),
        "name": dataset.name,
    }
    for source_key, target_key in (
        (f"{PROPERTY_PREFIX}:buildings_damaged", "buildings_damaged"),
        (f"{PROPERTY_PREFIX}:buildings_total", "buildings_total"),
        (f"{PROPERTY_PREFIX}:aoi_area_km2", "area_km2"),
    ):
        value = properties.get(source_key)
        if value is not None:
            entry[target_key] = value
    imagery = [
        source
        for source in (getattr(dataset, "imagerySources", None) or [])
        if source
    ]
    if imagery:
        entry["imagery"] = imagery
    return entry


def merge_collection_datasets(
    existing_collection: Optional[Mapping[str, Any]],
    entry: Mapping[str, Any],
) -> list:
    """Upsert ``entry`` into the datasets persisted on the existing collection."""
    existing: list = []
    if existing_collection:
        stored = existing_collection.get(COLLECTION_DATASETS_FIELD)
        if isinstance(stored, list):
            existing = [
                dict(item)
                for item in stored
                if isinstance(item, Mapping) and item.get("id")
            ]
    merged = [item for item in existing if item.get("id") != entry.get("id")]
    merged.append(dict(entry))
    merged.sort(
        key=lambda item: (str(item.get("name") or ""), str(item.get("id")))
    )
    return merged


def _collection_imagery_sources(
    entries: Sequence[Mapping[str, Any]]
) -> list:
    """Union of imagery source types across every dataset in the collection."""
    sources: list = []
    seen = set()
    for entry in entries:
        for source in entry.get("imagery") or []:
            key = str(source).strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                sources.append(key)
    return sources


def _format_count(value: Any) -> Optional[str]:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def render_collection_description(
    dataset: PublishedDataset, entries: Sequence[Mapping[str, Any]]
) -> str:
    """Render a rolling summary of every dataset held by the collection."""
    project = dataset.projectName or str(dataset.projectId)
    count = len(entries)
    noun = "dataset" if count == 1 else "datasets"
    lines = [
        f"HASTE disaster assessment for {project}. "
        f"This collection contains {count} published {noun}."
    ]
    for entry in entries:
        name = entry.get("name") or entry.get("id")
        details = []
        damaged = _format_count(entry.get("buildings_damaged"))
        total = _format_count(entry.get("buildings_total"))
        area = entry.get("area_km2")
        if damaged is not None and total is not None:
            details.append(f"{damaged} of {total} buildings assessed as damaged")
        elif damaged is not None:
            details.append(f"{damaged} buildings assessed as damaged")
        if area is not None:
            try:
                details.append(f"{float(area):.1f} km² assessed")
            except (TypeError, ValueError):
                pass
        suffix = f" — {'; '.join(details)}" if details else ""
        lines.append(f"- {name}{suffix}.")
    return "\n".join(lines)


def _apply_collection_providers(
    collection: Dict[str, Any],
    entries: Sequence[Mapping[str, Any]],
    organization: Optional[Mapping[str, Optional[str]]],
) -> None:
    """Recompute the collection provider union in place from its datasets."""
    providers = build_providers(
        organization, _collection_imagery_sources(entries)
    )
    if providers:
        collection["providers"] = [
            provider.to_dict() for provider in providers
        ]
    else:
        collection.pop("providers", None)


def rebuild_collection_after_removal(
    existing_collection: Mapping[str, Any],
    dataset: PublishedDataset,
    organization: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Drop ``dataset`` from the collection's rolling summary (for unpublish).

    Returns a copy of the existing collection document with this dataset removed
    from ``haste:datasets``, the description re-rendered, and the provider union
    recomputed from the datasets that remain.
    """
    updated = dict(existing_collection)
    stored = updated.get(COLLECTION_DATASETS_FIELD)
    entries: list = []
    if isinstance(stored, list):
        entries = [
            dict(entry)
            for entry in stored
            if isinstance(entry, Mapping)
            and entry.get("id") != str(dataset.datasetId)
        ]
    updated[COLLECTION_DATASETS_FIELD] = entries
    updated["description"] = render_collection_description(dataset, entries)
    _apply_collection_providers(updated, entries, organization)
    return updated


def refresh_collection_after_edit(
    existing_collection: Mapping[str, Any],
    dataset: PublishedDataset,
    organization: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Re-sync the collection to a dataset's edited metadata (for edit).

    Updates the dataset's entry (name + imagery sources) in ``haste:datasets``,
    re-renders the rolling description, and recomputes the collection-level
    provider union so imagery attribution stays consistent with the item.
    """
    updated = dict(existing_collection)
    stored = updated.get(COLLECTION_DATASETS_FIELD)
    entries: list = []
    for entry in stored if isinstance(stored, list) else []:
        if not isinstance(entry, Mapping):
            continue
        record = dict(entry)
        if record.get("id") == str(dataset.datasetId):
            record["name"] = dataset.name
            imagery = [
                source for source in (dataset.imagerySources or []) if source
            ]
            if imagery:
                record["imagery"] = imagery
            else:
                record.pop("imagery", None)
        entries.append(record)
    updated[COLLECTION_DATASETS_FIELD] = entries
    updated["description"] = render_collection_description(dataset, entries)
    _apply_collection_providers(updated, entries, organization)
    return updated


def build_collection(
    dataset: PublishedDataset,
    item: Any,
    collection_href: str,
    *,
    existing_collection: Optional[Mapping[str, Any]] = None,
    collection_prefix: str = "haste-",
    license_id: str = "proprietary",
    organization: Optional[Mapping[str, Optional[str]]] = None,
) -> Any:
    pystac = _load_pystac()
    collection_id = build_collection_id(dataset, collection_prefix)
    spatial_bbox, temporal_interval = _merge_collection_extent(
        collection_id,
        item,
        existing_collection,
    )
    datasets = merge_collection_datasets(
        existing_collection,
        _collection_dataset_entry(dataset, item),
    )
    imagery_sources = _collection_imagery_sources(datasets)
    providers = build_providers(organization, imagery_sources)
    collection = pystac.Collection(
        id=collection_id,
        title=dataset.projectName or collection_id,
        description=render_collection_description(dataset, datasets),
        license=license_id,
        keywords=[
            "HASTE",
            "disaster assessment",
            "building damage",
        ],
        providers=providers or None,
        extent=pystac.Extent(
            spatial=pystac.SpatialExtent([spatial_bbox]),
            temporal=pystac.TemporalExtent([temporal_interval]),
        ),
        summaries=pystac.Summaries(
            {PROJECT_ID_PROPERTY: [str(dataset.projectId)]}
        ),
        stac_extensions=[ITEM_ASSETS_EXTENSION],
        extra_fields={
            "item_assets": _collection_item_assets(),
            COLLECTION_DATASETS_FIELD: datasets,
        },
    )
    collection.add_link(
        pystac.Link(
            rel=pystac.RelType.SELF,
            target=_require_https_url(
                collection_href, "GeoCatalog collection"
            ),
            media_type=pystac.MediaType.JSON,
        )
    )
    # No collection-level assets: MPC Pro rejects `assets` in the collection
    # POST ("must be added using the GeoCatalog Collection Asset API"). The
    # thumbnail lives on the item, which is what drives the Explorer preview.
    return collection


def build_stac_objects(
    dataset: PublishedDataset,
    source: ArtifactBundle,
    valid_mask: Mapping[str, Any],
    asset_hrefs: Mapping[str, str],
    projection_codes: Mapping[str, str],
    collection_href: str,
    *,
    valid_mask_crs: str = "EPSG:4326",
    existing_collection: Optional[Mapping[str, Any]] = None,
    collection_prefix: str = "haste-",
    license_id: str = "proprietary",
    organization: Optional[Mapping[str, Optional[str]]] = None,
) -> StacObjects:
    item = build_vector_item(
        dataset,
        source,
        valid_mask,
        asset_hrefs,
        projection_codes,
        collection_href,
        valid_mask_crs=valid_mask_crs,
        collection_prefix=collection_prefix,
        license_id=license_id,
        organization=organization,
    )
    collection = build_collection(
        dataset,
        item,
        collection_href,
        existing_collection=existing_collection,
        collection_prefix=collection_prefix,
        license_id=license_id,
        organization=organization,
    )
    return StacObjects(collection=collection, item=item)


def validate_stac_objects(objects: StacObjects, validator: Any = None) -> None:
    """Validate the exact serialized STAC 1.0 documents."""
    pystac = _load_pystac()
    validator = validator or offline_stac_validator()
    documents = serialize_stac_objects(objects)
    pystac.validation.validate_dict(
        documents.collection,
        stac_object_type=pystac.STACObjectType.COLLECTION,
        stac_version=STAC_VERSION,
        extensions=documents.collection.get("stac_extensions", []),
        validator=validator,
    )
    pystac.validation.validate_dict(
        documents.item,
        stac_object_type=pystac.STACObjectType.ITEM,
        stac_version=STAC_VERSION,
        extensions=documents.item.get("stac_extensions", []),
        validator=validator,
    )


def offline_stac_validator() -> Any:
    pystac = _load_pystac()
    validator = pystac.validation.JsonSchemaSTACValidator()
    schema_directory = resources.files(__package__).joinpath("schemas")
    for uri, file_name in EXTENSION_SCHEMA_FILES.items():
        schema = json.loads(
            schema_directory.joinpath(file_name).read_text(encoding="utf-8")
        )
        validator.schema_cache[uri] = schema
    return validator


def serialize_stac_objects(objects: StacObjects) -> StacDocuments:
    collection = objects.collection.to_dict()
    item = objects.item.to_dict()
    if (
        collection.get("stac_version") != STAC_VERSION
        or item.get("stac_version") != STAC_VERSION
    ):
        raise RuntimeError(
            f"Planetary Computer publishing requires STAC {STAC_VERSION}"
        )
    return StacDocuments(collection=collection, item=item)


def _merge_collection_extent(
    collection_id: str,
    item: Any,
    existing_collection: Optional[Mapping[str, Any]],
) -> Tuple[list[float], list[datetime]]:
    bboxes = [list(item.bbox)]
    starts = [item.datetime]
    ends = [item.datetime]
    if existing_collection is not None:
        if existing_collection.get("id") != collection_id:
            raise ValueError("Existing STAC collection ID does not match")
        summaries = existing_collection.get("summaries") or {}
        project_ids = summaries.get(PROJECT_ID_PROPERTY) or []
        if project_ids != [str(item.properties[PROJECT_ID_PROPERTY])]:
            raise ValueError(
                "Existing STAC collection project provenance does not match"
            )
        extent = existing_collection.get("extent") or {}
        for bbox in (extent.get("spatial") or {}).get("bbox") or []:
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise ValueError("Existing STAC collection bbox is invalid")
            normalized_bbox = [float(value) for value in bbox]
            if not all(math.isfinite(value) for value in normalized_bbox):
                raise ValueError("Existing STAC collection bbox is invalid")
            if not (
                -180 <= normalized_bbox[0] <= normalized_bbox[2] <= 180
                and -90 <= normalized_bbox[1] <= normalized_bbox[3] <= 90
            ):
                raise ValueError("Existing STAC collection bbox is invalid")
            bboxes.append(normalized_bbox)
        for interval in (extent.get("temporal") or {}).get("interval") or []:
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError(
                    "Existing STAC collection interval is invalid"
                )
            start = (
                _parse_timestamp(interval[0])
                if interval[0] is not None
                else None
            )
            end = (
                _parse_timestamp(interval[1])
                if interval[1] is not None
                else None
            )
            if start is not None and end is not None and start > end:
                raise ValueError(
                    "Existing STAC collection interval is invalid"
                )
            if start is not None:
                starts.append(start)
            if end is not None:
                ends.append(end)

    spatial_bbox = [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]
    return spatial_bbox, [min(starts), max(ends)]


def _load_pystac() -> Any:
    try:
        import pystac
    except ImportError as error:
        raise RuntimeError(
            "Planetary Computer publishing requires the "
            "hastegeo[planetary-computer] extra"
        ) from error
    return pystac


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None:
        raise ValueError("STAC datetime must include a UTC offset")
    return timestamp.astimezone(timezone.utc)


def _require_https_href(value: str | None, artifact: SourceArtifact) -> str:
    if not value:
        raise ValueError(
            f"Missing STAC HREF for {artifact.kind.value} artifact"
        )
    return _require_https_url(value, "Planetary Computer asset HREF")


def _require_https_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must use HTTPS")
    return value


def _projection_code(
    artifact: SourceArtifact,
    projection_codes: Mapping[str, str],
    valid_mask_crs: str,
) -> str:
    if artifact.kind == ArtifactKind.VALID_MASK:
        projection_code = valid_mask_crs
    else:
        projection_code = projection_codes.get(artifact.sourcePath)
    if not projection_code:
        raise ValueError(
            f"Missing projection code for {artifact.kind.value} artifact"
        )
    if not re.fullmatch(r"EPSG:[1-9][0-9]*", projection_code):
        raise ValueError("Projection code must use the EPSG:<code> form")
    try:
        CRS.from_epsg(int(projection_code.split(":", 1)[1]))
    except CRSError as error:
        raise ValueError("Projection code is not a known EPSG CRS") from error
    return projection_code


def _build_item_properties(
    dataset: PublishedDataset,
    area_square_kilometers: float,
    license_id: str,
) -> Dict[str, Any]:
    summary = dataset.assessmentSummary
    predictions = summary.get("predictions") or {}
    metrics = summary.get("metrics") or {}
    population = summary.get("populationEstimate") or {}
    p = PROPERTY_PREFIX
    properties = {
        "title": dataset.name,
        "description": dataset.description,
        "license": license_id,
        f"{p}:project_id": str(dataset.projectId),
        f"{p}:image_layer_id": dataset.imageLayerId,
        f"{p}:model_id": dataset.modelId,
        f"{p}:aoi_area_km2": round(area_square_kilometers, 6),
        f"{p}:buildings_total": _first_present(
            predictions, "total", fallback=summary.get("buildingsTotal")
        ),
        f"{p}:buildings_cloud": _first_present(
            predictions, "cloudy", fallback=summary.get("buildingsCloud")
        ),
        f"{p}:buildings_clear": _first_present(
            predictions,
            "knownNonCloudy",
            fallback=summary.get("buildingsClear"),
        ),
        f"{p}:buildings_damaged": _first_present(
            predictions,
            "predictedDamaged",
            fallback=summary.get("predictedDamaged"),
        ),
        f"{p}:damaged_pct_of_clear": _first_present(
            predictions,
            "predictedDamagedPctOfKnown",
            fallback=summary.get("damagedPctOfClear"),
        ),
        f"{p}:validation_precision": _first_present(
            metrics, "precision", fallback=summary.get("precision")
        ),
        f"{p}:validation_recall": _first_present(
            metrics, "recall", fallback=summary.get("recall")
        ),
        f"{p}:validation_extrapolated_damaged": _first_present(
            population,
            "estimatedDamaged",
            fallback=summary.get("estimatedDamaged"),
        ),
        f"{p}:validation_ci_lower": _first_present(
            population, "ciLower", fallback=summary.get("ciLower")
        ),
        f"{p}:validation_ci_upper": _first_present(
            population, "ciUpper", fallback=summary.get("ciUpper")
        ),
    }
    return {
        key: value for key, value in properties.items() if value is not None
    }


def _first_present(
    values: Mapping[str, Any], key: str, *, fallback: Any = None
) -> Any:
    return values[key] if key in values else fallback


def _collection_item_assets() -> Dict[str, Dict[str, Any]]:
    return {
        "damage": {
            "title": ASSET_TITLES[ArtifactKind.GPKG],
            "type": "application/geopackage+sqlite3",
            "roles": ASSET_ROLES[ArtifactKind.GPKG],
        },
        "aoi": {
            "title": ASSET_TITLES[ArtifactKind.VALID_MASK],
            "type": "application/geo+json",
            "roles": ASSET_ROLES[ArtifactKind.VALID_MASK],
        },
        "footprints": {
            "title": ASSET_TITLES[ArtifactKind.FOOTPRINTS],
            "type": "application/geopackage+sqlite3",
            "roles": ASSET_ROLES[ArtifactKind.FOOTPRINTS],
        },
    }
