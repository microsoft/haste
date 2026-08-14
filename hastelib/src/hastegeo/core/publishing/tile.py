"""Render a Planetary Computer collection tile (a damage-assessment map).

A dark overview image: the AOI (valid-area mask) outline, intact buildings in
grey and damaged buildings in red, plus a title/subtitle caption. Rendered with
OpenCV (``cv2``), which HASTE's publishing worker already ships — so no
matplotlib dependency is needed. ``cv2``/``numpy`` are imported lazily inside the
render call to keep them off the module import path.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

# Vendored palette (hex RGB).
_BACKGROUND = "#0b1a2b"
_AOI_EDGE = "#4da3ff"
_AOI_FACE = "#12324f"
_INTACT = "#7f8fa6"
_DAMAGED = "#ff4d4d"
_TITLE_COLOR = "#e8f1ff"
_SUBTITLE_COLOR = "#9fb5cc"

# Column names that may carry a per-building damage flag (truthy = damaged).
_DAMAGE_COLUMNS = (
    "damaged",
    "is_damaged",
    "damage",
    "damage_class",
    "predicted_damage",
    "prediction",
    "predicted",
    "label",
    "class",
)
_DAMAGED_STRINGS = {"1", "true", "yes", "damaged", "destroyed", "major", "minor"}


def _hex_to_bgr(value: str) -> tuple:
    value = value.lstrip("#")
    red, green, blue = (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )
    return (blue, green, red)  # OpenCV is BGR


def detect_damage_mask(buildings: Any) -> Optional[Any]:
    """Boolean Series (True = damaged), or None if no recognizable column."""
    for column in _DAMAGE_COLUMNS:
        if column in buildings.columns:
            series = buildings[column]
            try:
                import pandas as pd

                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.notna().any():
                    return (numeric.fillna(0) > 0).to_numpy()
            except Exception:
                pass
            lowered = series.astype(str).str.strip().str.lower()
            return lowered.isin(_DAMAGED_STRINGS).to_numpy()
    return None


def _iter_polygons(geometry: Any) -> Iterable[Any]:
    geom_type = getattr(geometry, "geom_type", None)
    if geom_type == "Polygon":
        yield geometry
    elif geom_type == "MultiPolygon":
        yield from geometry.geoms


def _pixel_rings(geoseries: Any, to_px, cap: Optional[int] = None) -> List[Any]:
    rings = []
    for geom in geoseries:
        if geom is None or geom.is_empty:
            continue
        for polygon in _iter_polygons(geom):
            coords = list(polygon.exterior.coords)
            if len(coords) >= 3:
                rings.append(to_px(coords))
        if cap is not None and len(rings) >= cap:
            break
    return rings


def render_collection_tile(
    buildings: Any,
    aoi: Any,
    *,
    title: str,
    subtitle: str = "",
    width: int = 1200,
    height: int = 630,
    max_buildings: int = 200_000,
) -> bytes:
    """Render the collection tile PNG from buildings + AOI GeoDataFrames."""
    import cv2
    import numpy as np

    aoi_m = aoi.to_crs(3857)
    buildings_m = buildings.to_crs(3857) if len(buildings) else buildings

    minx, miny, maxx, maxy = (float(v) for v in aoi_m.total_bounds)
    if not all(np.isfinite([minx, miny, maxx, maxy])) or (
        maxx <= minx or maxy <= miny
    ):
        raise ValueError("AOI bounds are invalid")
    pad_x, pad_y = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    minx, maxx, miny, maxy = minx - pad_x, maxx + pad_x, miny - pad_y, maxy + pad_y

    span_x, span_y = maxx - minx, maxy - miny
    scale = min(width / span_x, height / span_y)
    offset_x = (width - span_x * scale) / 2.0
    offset_y = (height - span_y * scale) / 2.0

    def to_px(coords):
        arr = np.asarray(coords, dtype=float)
        px = (arr[:, 0] - minx) * scale + offset_x
        py = height - ((arr[:, 1] - miny) * scale + offset_y)
        return np.column_stack([px, py]).astype(np.int32)

    canvas = np.full(
        (height, width, 3), _hex_to_bgr(_BACKGROUND), dtype=np.uint8
    )

    aoi_rings = _pixel_rings(aoi_m.geometry, to_px)
    if aoi_rings:
        cv2.fillPoly(canvas, aoi_rings, _hex_to_bgr(_AOI_FACE))
        cv2.polylines(
            canvas, aoi_rings, True, _hex_to_bgr(_AOI_EDGE), 2, cv2.LINE_AA
        )

    if len(buildings_m):
        mask = detect_damage_mask(buildings_m)
        if mask is None:
            rings = _pixel_rings(
                buildings_m.geometry, to_px, cap=max_buildings
            )
            if rings:
                cv2.fillPoly(canvas, rings, _hex_to_bgr(_INTACT))
        else:
            intact_rings = _pixel_rings(
                buildings_m.geometry[~mask], to_px, cap=max_buildings
            )
            damaged_rings = _pixel_rings(
                buildings_m.geometry[mask], to_px, cap=max_buildings
            )
            if intact_rings:
                cv2.fillPoly(canvas, intact_rings, _hex_to_bgr(_INTACT))
            if damaged_rings:
                cv2.fillPoly(canvas, damaged_rings, _hex_to_bgr(_DAMAGED))

    if title:
        cv2.putText(
            canvas, title[:64], (18, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
            _hex_to_bgr(_TITLE_COLOR), 2, cv2.LINE_AA,
        )
    if subtitle:
        cv2.putText(
            canvas, subtitle[:96], (18, height - 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, _hex_to_bgr(_SUBTITLE_COLOR), 1,
            cv2.LINE_AA,
        )

    ok, buffer = cv2.imencode(".png", canvas)
    if not ok:
        raise ValueError("Failed to encode collection tile PNG")
    return bytes(buffer.tobytes())
