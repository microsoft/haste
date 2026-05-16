# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Compatibility shim — Overture Maps client moved to hastegeo.

The implementation now lives in ``hastegeo.core.utils.footprints`` so the
imageryprep workflow can share it. This module re-exports the public names
that pre-existing callers in ``docker/training/code/`` (notably
``bda/validate_overture.py`` and ``bda/test_footprints.py``) expect, so
those keep working without code changes.

New code should import directly from :mod:`hastegeo.core.utils.footprints`.
"""

from hastegeo.core.utils.footprints import (  # noqa: F401
    FALLBACK_RELEASE,
    HAS_GEOPANDAS,
    OVERTURE_ACCOUNT_NAME,
    _dataset_path,
    download_building_footprints,
    geoarrow_schema_adapter,
    geodataframe,
    get_all_overture_types,
    get_latest_release,
    record_batch_reader,
    type_theme_map,
)
