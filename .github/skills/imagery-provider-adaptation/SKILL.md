---
name: imagery-provider-adaptation
description: "Imagery provider adaptation skill for HASTE. Encapsulates provider-specific logic for satellite imagery sources (Planet, Maxar, Airbus, etc.). Use when: 'new imagery provider', 'add source type', 'satellite provider', 'Planet', 'Maxar', 'Airbus', 'Pleiades', 'WorldView', 'SkySat', 'imagery ingestion', 'provider adapter'."
source: "HASTE imagery processing pipeline, satellite provider documentation"
domain: "geospatial"
level: "advanced"
agents: ["gis", "backend-dev"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Imagery Provider Adaptation

## Overview

Structured process for adding new satellite imagery providers to HASTE. Each provider has different data formats, coordinate systems, APIs, band configurations, and delivery methods. This skill encapsulates the provider-specific logic needed to adapt a new source.

## Key Concepts

### Current Providers

| Provider | Satellites | Format | Bands | Delivery |
|----------|-----------|--------|-------|----------|
| Maxar | WorldView-2/3/4, GeoEye-1 | GeoTIFF | 4-8 bands (BGRN + extras) | S3, STAC, Direct URL |
| Planet | PlanetScope, SkySat | GeoTIFF, COG | 4 bands (BGRN) | Planet API, S3 |
| Airbus | Pleiades, Pleiades Neo, SPOT | GeoTIFF, DIMAP | 4 bands (BGRN) | OneAtlas, S3 |

### Provider Adapter Components

Each new provider requires:
1. **Source Type Definition** — Model configuration in `hastegeo.core.models`
2. **Download Handler** — Provider-specific authentication and download logic
3. **Band Mapping** — Map provider bands to HASTE's expected band order
4. **Metadata Parser** — Extract spatial metadata from provider-specific formats
5. **Preprocessing Rules** — Resolution normalization, radiometric correction
6. **Tests** — Integration tests with sample provider data

## Patterns & Techniques

### Adding a New Provider: Step-by-Step

**Step 1: Define source type**
Add to the source type configuration in `hastegeo.core.models`:
```python
# New source type with provider-specific configuration
class NewProviderConfig(BaseModel):
    provider_name: str
    api_url: str
    band_order: list[str]  # e.g., ["B", "G", "R", "NIR"]
    default_crs: str  # e.g., "EPSG:4326"
    tile_size: int  # e.g., 256
```

**Step 2: Implement download handler**
In `hastegeo.core.processors.imagery`:
```python
# Handle provider-specific authentication and URL patterns
# Use requests with proper auth (API key, OAuth, etc.)
# Stream large files to avoid memory issues
# Validate downloaded file integrity
```

**Step 3: Implement band mapping**
```python
# Map provider bands to HASTE standard order
# HASTE expects: [Blue, Green, Red, NIR] for 4-band
# Handle extra bands (e.g., coastal, red-edge, SWIR)
# Handle missing bands (e.g., panchromatic only)
```

**Step 4: Implement preprocessing**
```python
# 1. Validate CRS — reproject if needed
# 2. Normalize resolution — resample to target GSD
# 3. Apply radiometric correction if needed
# 4. Generate COG with internal tiling and overviews
# 5. Validate output with rasterio
```

**Step 5: Add to imagery processor**
Update `ImageryPreProcessor` to route to the new handler based on source type.

**Step 6: Write tests**
```python
# Test with real sample data (small AOI, public data preferred)
# Verify CRS preservation
# Verify band order mapping
# Verify COG compliance
# Verify metadata extraction
```

### Provider-Specific Gotchas

| Provider | Gotcha | Mitigation |
|----------|--------|------------|
| Maxar | Multiple UTM zones in a single order | Check CRS per file, reproject to consistent zone |
| Planet | UDM2 quality masks delivered separately | Download and apply quality mask before processing |
| Airbus | DIMAP format metadata | Parse XML metadata alongside GeoTIFF |
| All | Different nodata conventions | Standardize nodata to 0 or NaN during preprocessing |

## Decision Framework

| Scenario | Approach |
|----------|----------|
| Provider uses standard GeoTIFF | Minimal adapter — mostly URL/auth handling |
| Provider uses proprietary format | Full adapter — format conversion + metadata extraction |
| Provider delivers via STAC | Use existing STAC client, add provider-specific auth |
| Provider requires API key | Store in Config, never hardcode |
| Provider delivers in tiles | Implement tile stitching before COG generation |

## Quick Reference: COG Output Standard

```
Format: Cloud Optimized GeoTIFF
Tiling: 256x256 or 512x512 internal tiles
Overviews: Nearest power of 2, down to 256px
Compression: LZW or DEFLATE
CRS: Preserve source CRS (typically UTM or EPSG:4326)
Nodata: 0 for uint8/uint16, NaN for float
Bands: Blue, Green, Red, NIR (minimum)
```

## Common Pitfalls

- **Assuming all providers use the same band order** — Always check and map explicitly
- **Hardcoding provider URLs/keys** — Use `Config` class
- **Ignoring quality masks** — Bad pixels contaminate training data
- **Not testing with edge cases** — Antimeridian crossing, polar regions, dateline
- **Downloading entire scenes when only a small AOI is needed** — Use provider APIs to clip
