# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Microsoft Azure Function."""

import logging
from typing import Annotated

import attr
import azure.functions as func
import morecantile
import rasterio
from fastapi import FastAPI, HTTPException, Query
from rio_tiler.io import Reader
from starlette.middleware.cors import CORSMiddleware
from starlette_cramjam.middleware import CompressionMiddleware
from titiler.application import __version__ as titiler_version
from titiler.application.settings import ApiSettings
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import TilerFactory
from titiler.core.middleware import (
    CacheControlMiddleware,
    LoggerMiddleware,
    LowerCaseQueryStringMiddleware,
    TotalTimeMiddleware,
)

from .dataset_url import (
    DatasetUrlError,
    DatasetUrlPolicy,
    DestinationChecker,
    validate_dataset_url,
)
from .gdal_config import apply_gdal_hardening, gdal_environment

logger = logging.getLogger(__name__)

apply_gdal_hardening()

api_settings = ApiSettings()
url_policy = DatasetUrlPolicy.from_env()
destination_checker = DestinationChecker(url_policy)

# The only TiTiler route HASTE uses. Everything else (info, statistics,
# preview, bbox/feature, STAC, MosaicJSON, viewers, docs) is not exposed.
TILE_ROUTE_PREFIX = "/tiles/{tileMatrixSetId}/{z}/{x}/{y}"


def DatasetUrlParams(
    url: Annotated[str, Query(description="Dataset URL")],
) -> str:
    """Admit only approved dataset URLs; reject before GDAL is involved."""
    try:
        validate_dataset_url(url, url_policy)
        destination_checker.check(url)
    except DatasetUrlError as exc:
        # Never log the URL itself: deployment URLs carry SAS signatures.
        logger.warning("Rejected dataset url: %s", exc)
        raise HTTPException(
            status_code=400, detail="Unsupported dataset url"
        ) from None
    return url


@attr.s
class GeoTIFFReader(Reader):
    """Reader that opens the dataset with the GeoTIFF driver only.

    COGs are GeoTIFFs. Restricting the driver at open means a URL serving
    VRT/XML or any other format fails to open instead of being parsed.
    """

    def __attrs_post_init__(self):
        if not self.dataset:
            self.dataset = self._ctx_stack.enter_context(
                rasterio.open(self.input, driver="GTiff")
            )
        super().__attrs_post_init__()


cog = TilerFactory(
    reader=GeoTIFFReader,
    path_dependency=DatasetUrlParams,
    environment_dependency=gdal_environment,
    supported_tms=morecantile.TileMatrixSets(
        {"WebMercatorQuad": morecantile.tms.get("WebMercatorQuad")}
    ),
    router_prefix="/cog",
    add_preview=False,
    add_part=False,
    add_viewer=False,
)
cog.router.routes = [
    route
    for route in cog.router.routes
    if getattr(route, "path", "").startswith(TILE_ROUTE_PREFIX)
]

app = FastAPI(
    title=api_settings.name,
    description="A lightweight Cloud Optimized GeoTIFF tile server",
    version=titiler_version,
    root_path=api_settings.root_path,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])
add_exception_handlers(app, DEFAULT_STATUS_CODES)


# Set all CORS enabled origins
if api_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.add_middleware(
    CompressionMiddleware,
    minimum_size=0,
    exclude_mediatype={
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/jp2",
        "image/webp",
    },
)

app.add_middleware(
    CacheControlMiddleware,
    cachecontrol=api_settings.cachecontrol,
    exclude_path={r"/healthz"},
)

if api_settings.debug:
    app.add_middleware(LoggerMiddleware, headers=True, querystrings=True)
    app.add_middleware(TotalTimeMiddleware)

if api_settings.lower_case_query_parameters:
    app.add_middleware(LowerCaseQueryStringMiddleware)


@app.get("/healthz", description="Health Check", tags=["Health Check"])
def ping():
    """Health check."""
    return {"ping": "pong!"}


async def main(
    req: func.HttpRequest,
    context: func.Context,
) -> func.HttpResponse:
    """Run App in AsgiMiddleware."""
    return await func.AsgiMiddleware(app).handle_async(req, context)
