---
applyTo: "**/hastegeo/**,**/processors/imagery*,**/data_layer/**,**/workflows/**"
---

# Geospatial Instructions

- Always use GDAL/rasterio for raster I/O — never raw file operations on imagery.
- Output imagery must be Cloud Optimized GeoTIFF (COG) format.
- Preserve spatial metadata through the pipeline: CRS, transform, bounds, resolution, nodata.
- Validate coordinate reference systems on all imagery inputs.
- Use internal tiling (256x256 or 512x512) and overview levels for COG performance.
- Use LZW or DEFLATE compression for COGs.
- Handle provider-specific formats: Planet (PlanetScope, SkySat), Vantor (WorldView), Airbus (Pleiades, SPOT).
- Use shapely for geometric operations, not manual coordinate math.
- Always validate bounding box geometry before spatial queries.
- Test geospatial functions with known-good reference data and expected CRS/bounds.
